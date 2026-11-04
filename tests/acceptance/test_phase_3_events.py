"""G3 Tracker concurrency/delivery tests; no production data or external calls."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "code/chapter14/helloagents-deepresearch/backend/src"
sys.path.insert(0, str(SRC))
from models import SummaryState, TodoItem
from services.tool_events import ToolCallTracker, ToolCallEvent
from services.note_versions import NoteScope
from tools.project_note_tool import NoteToolResult
from storage.note_repository import NoteWriteResult


def payload(ok=True, code=None, task_id=1, note_id=None, action="create", run="run"):
    status = NoteWriteResult(ok, ok, note_id=note_id if ok else None,
                            etag="a"*64 if ok else None,
                            error_code=code, detail="fake note error" if code else None)
    return {"agent_name": "fake", "tool_name": "note", "raw_parameters": "{}",
            "parsed_parameters": {"action": action, "task_id": task_id, "note_id": note_id},
            "result": "ID: fake-id" if not ok else "ok",
            "note_result": NoteToolResult(status, "ok", task_id),
            "trusted_scope": NoteScope(run, "task", task_id)}

class EventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tracker = ToolCallTracker(self.tmp.name)
        self.task = TodoItem(id=1, title="t", intent="i", query="q")
        self.state = SummaryState(todo_items=[self.task])

    def test_concurrent_event_ids_are_allocated_atomically(self):
        barrier = threading.Barrier(20)
        original = ToolCallEvent
        def construct(*args, **kwargs):
            time.sleep(.003)
            return original(*args, **kwargs)
        def record(_):
            barrier.wait(5)
            self.tracker.record(payload())
        with patch("services.tool_events.ToolCallEvent", side_effect=construct):
            with ThreadPoolExecutor(20) as pool:
                list(pool.map(record, range(20)))
        ids = [x["id"] for x in self.tracker.as_dicts()]
        self.assertEqual(sorted(ids), list(range(1,21)))

    def test_normal_sink_once_and_drain_still_updates_state(self):
        sent = []
        self.tracker.set_event_sink(sent.append)
        self.tracker.record(payload(note_id="note_"+"1"*32))
        self.assertEqual(self.tracker.drain(self.state), [])
        self.assertEqual(len(sent), 1)
        self.assertEqual(self.task.note_status, "saved")
        self.assertEqual(self.task.note_id, "note_"+"1"*32)

    def test_failed_sink_is_available_for_one_replay(self):
        def fail(event):
            raise OSError("enqueue failed before put")
        self.tracker.set_event_sink(fail)
        self.tracker.record(payload(note_id="note_"+"1"*32))
        self.tracker.set_event_sink(None)
        first = self.tracker.drain(self.state)
        self.assertEqual(len(first), 1)
        self.assertEqual(self.tracker.drain(self.state), [])

    def test_inflight_close_failure_keeps_replay_without_duplicate(self):
        entered, release = threading.Event(), threading.Event()
        def sink(event):
            entered.set()
            release.wait(5)
            raise OSError("closing sink")
        self.tracker.set_event_sink(sink)
        thread = threading.Thread(target=lambda: self.tracker.record(payload()))
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.tracker.drain(self.state), [])
            self.tracker.set_event_sink(None)
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(self.tracker.drain(self.state)), 1)
        self.assertEqual(self.tracker.drain(self.state), [])

    def test_structured_failure_does_not_bind_model_supplied_id(self):
        self.tracker.record(payload(False, "WRITES_PAUSED", note_id="fake"))
        event = self.tracker.drain(self.state)[0]
        self.assertIsNone(self.task.note_id)
        self.assertIsNone(event["note_id"])
        self.assertFalse(event["success"])
        self.assertEqual(self.task.note_status, "paused")
        self.assertEqual(self.task.note_error["code"], "WRITES_PAUSED")

    def test_read_only_note_id_uses_trusted_result_mapping(self):
        event = payload(note_id="note_"+"2"*32, action="read")
        event["parsed_parameters"] = {"action": "read", "note_id": event["note_result"].status.note_id}
        self.tracker.record(event)
        sent = self.tracker.drain(self.state)
        self.assertEqual(sent[0]["task_id"], 1)
        self.assertEqual(self.task.note_id, "note_"+"2"*32)

    def test_read_does_not_hide_failed_write_but_write_can_recover(self):
        self.tracker.record(payload(False, "CONFLICT"))
        self.tracker.drain(self.state)
        read = payload(note_id="note_"+"3"*32, action="read")
        read["note_result"] = replace(read["note_result"],
                                     status=replace(read["note_result"].status, persisted=False))
        self.tracker.record(read)
        self.tracker.drain(self.state)
        self.assertEqual(self.task.note_status, "conflict")
        self.tracker.record(payload(note_id="note_"+"3"*32, action="update"))
        self.tracker.drain(self.state)
        self.assertEqual(self.task.note_status, "saved")

    def test_run_identity_blocks_foreign_projection(self):
        self.tracker.reset(run_id="current")
        with self.assertRaises(ValueError):
            self.tracker.record(payload(run="other"))
        self.assertEqual(self.tracker.as_dicts(), [])

if __name__ == "__main__":
    unittest.main()
