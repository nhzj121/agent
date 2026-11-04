"""G1 regression tests: all runtime calls are Fake, with no existing notes."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "code/chapter14/helloagents-deepresearch/backend/src"
sys.path.insert(0, str(SRC))
from config import Configuration
from models import SummaryState, TodoItem
from agent import DeepResearchAgent
from services.planner import PlanningService
from services.reporter import ReportingService
from services.summarizer import SummarizationService
from services.text_processing import strip_tool_calls
from utils import strip_thinking_tokens

def task(i=1):
    return TodoItem(id=i, title=f"Task{i}", intent="intent", query=f"query{i}")

class FakeAgent:
    def __init__(self, response="正文", chunks=None, error=None):
        self.response, self.chunks, self.error = response, chunks or [], error
        self.history = ["old"]
        self.clears = 0
        self.closed = False
        self.prompt = None
    def run(self, prompt):
        self.prompt = prompt
        if self.error:
            raise self.error
        return self.response
    def stream_run(self, prompt):
        self.prompt = prompt
        try:
            yield from self.chunks
            if self.error:
                raise self.error
        finally:
            self.closed = True
    def clear_history(self):
        self.clears += 1
        self.history.clear()

class G1Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Configuration(enable_notes=False, notes_workspace=self.temp.name)
        for target in ["socket.socket.connect", "socket.socket.connect_ex", "socket.getaddrinfo",
                       "agent.HelloAgentsLLM", "agent.NoteTool"]:
            guard = patch(target, side_effect=AssertionError("real service forbidden"))
            guard.start()
            self.addCleanup(guard.stop)

    def coordinator(self, tasks):
        a = DeepResearchAgent.__new__(DeepResearchAgent)
        a.config = self.config
        a.note_tool = None
        a._state_lock = Lock()
        a._tool_event_sink_enabled = False
        a._tool_tracker = SimpleNamespace(drain=lambda *a, **k: [],
                                          set_event_sink=lambda sink: None)
        a.planner = SimpleNamespace(plan_todo_list=lambda state: tasks,
                                    create_fallback_task=PlanningService.create_fallback_task)
        a.summarizer = SummarizationService(lambda: FakeAgent(chunks=["sum"]), self.config)
        a.report_agent = FakeAgent("report")
        a.reporting = ReportingService(a.report_agent, self.config)
        return a

    def search(self, query, config, count):
        return {"results": [{"url": "https://fake.invalid", "content": "fake"}]}, [], "", "fake"

    def test_sync_single_multiple_and_fallback(self):
        for count in [1, 3, 0]:
            with self.subTest(count=count):
                a = self.coordinator([task(i+1) for i in range(count)])
                with patch("agent.dispatch_search", side_effect=self.search) as search, \
                     patch("agent.prepare_research_context", return_value=("sources", "context")):
                    result = a.run("topic")
                self.assertEqual(search.call_count, max(1, count))
                self.assertEqual(len(result.todo_items), max(1, count))
                self.assertTrue(all(t.status == "completed" and t.summary == "正文"
                                    for t in result.todo_items))
                self.assertIn("执行状态：completed", a.report_agent.prompt)
                self.assertEqual(result.report_markdown, "report")

    def test_worker_failures_object_event_and_reporter_agree(self):
        for stage in ["search", "summary"]:
            with self.subTest(stage=stage):
                t = task()
                a = self.coordinator([t])
                if stage == "summary":
                    a.summarizer = SummarizationService(
                        lambda: FakeAgent(chunks=["partial"], error=ValueError("fake failure")),
                        self.config)
                with patch("agent.dispatch_search", side_effect=
                           ValueError("fake failure") if stage == "search" else self.search), \
                     patch("agent.prepare_research_context", return_value=("sources", "context")):
                    events = list(a.run_stream("topic"))
                terminal = [e for e in events if e["type"] == "task_status" and
                            e["status"] in ("completed", "failed", "skipped")]
                self.assertEqual(t.status, "failed")
                self.assertEqual([e["status"] for e in terminal], ["failed"])
                self.assertIn("执行状态：failed", a.report_agent.prompt)
                self.assertEqual(events[-1]["type"], "done")
                self.assertEqual(events[-1]["run_status"], "failed")
                self.assertTrue(events[-1]["run_id"])

    def stream(self, chunks, error=None):
        fake = FakeAgent(chunks=chunks, error=error)
        service = SummarizationService(lambda: fake, self.config)
        stream, get = service.stream_task_summary(SummaryState(research_topic="topic"), task(), "ctx")
        return fake, stream, get

    def test_think_all_boundaries_and_character_chunks(self):
        cases = [
            ("前<think>SECRET</think>后", "前后"),
            ("前<think>SECRET<think>NESTED</think>SECRET</think>后", "前后"),
            ("前</think>后<think>SECRET", "前后"),
            ("前<think>SECRET", "前"),
            ("前<thi", "前"),
            ("比较 a < b > c", "比较 a < b > c"),
        ]
        for text, expected in cases:
            partitions = [[text[:i], text[i:]] for i in range(len(text)+1)] + [list(text)]
            for chunks in partitions:
                with self.subTest(text=text, chunks=chunks):
                    fake, stream, get = self.stream(chunks)
                    self.assertEqual("".join(stream), expected)
                    self.assertEqual(get(), expected)
                    self.assertEqual(strip_thinking_tokens(text), expected)
                    self.assertEqual(fake.clears, 1)
                    self.assertTrue(fake.closed)

    def test_partial_close_does_not_yield_and_closes_owned_stream(self):
        fake, stream, get = self.stream(["前", "<think>SECRET", "</think>后"])
        self.assertEqual(next(stream), "前")
        stream.close()
        self.assertTrue(fake.closed)
        self.assertEqual(fake.clears, 1)
        self.assertEqual(get(), "前")

    def test_close_mid_single_chunk_has_no_finally_yield(self):
        fake, stream, get = self.stream(["prefix<think>secret</think>TAIL"])
        first = next(stream)
        self.assertTrue(first.startswith("prefix"))
        stream.close()
        self.assertTrue(fake.closed)
        self.assertEqual(fake.clears, 1)
        self.assertEqual(get(), first)

    def test_close_with_unclosed_think_and_exception_release(self):
        for error in [None, ValueError("original")]:
            fake, stream, get = self.stream(["前<think>SECRET"], error=error)
            self.assertEqual(next(stream), "前")
            if error:
                with self.assertRaisesRegex(ValueError, "original"):
                    list(stream)
            else:
                stream.close()
            self.assertEqual(fake.clears, 1)
            self.assertTrue(fake.closed)
            self.assertNotIn("SECRET", get())

    def test_inner_exception_not_masked_by_cleanup(self):
        fake, stream, _ = self.stream(["前"], error=ValueError("original"))
        fake.clear_history = Mock(side_effect=RuntimeError("cleanup"))
        with self.assertRaisesRegex(ValueError, "original"):
            list(stream)
        fake.clear_history.assert_called_once()
        self.assertTrue(fake.closed)

    def test_execute_task_close_releases_summary_stream(self):
        a = self.coordinator([task()])
        fake = FakeAgent(chunks=["first", "second"])
        a.summarizer = SummarizationService(lambda: fake, self.config)
        with patch("agent.dispatch_search", side_effect=self.search), \
             patch("agent.prepare_research_context", return_value=("sources", "context")):
            stream = a._execute_task(SummaryState(research_topic="t"), task(), emit_stream=True)
            self.assertEqual(next(stream)["type"], "sources")
            self.assertEqual(next(stream)["type"], "task_summary_chunk")
            stream.close()
        self.assertTrue(fake.closed)
        self.assertEqual(fake.clears, 1)

    def test_synchronous_summary_cleanup_and_filter(self):
        for error in [None, ValueError("summary")]:
            fake = FakeAgent("前<think>SECRET</think>后", error=error)
            service = SummarizationService(lambda: fake, self.config)
            if error:
                with self.assertRaisesRegex(ValueError, "summary"):
                    service.summarize_task(SummaryState(research_topic="t"), task(), "ctx")
            else:
                self.assertEqual(service.summarize_task(
                    SummaryState(research_topic="t"), task(), "ctx"), "前后")
            self.assertEqual(fake.clears, 1)

    def test_filter_disabled_keeps_thinking(self):
        self.config.strip_thinking_tokens = False
        fake, stream, get = self.stream(["<thi", "nk>SECRET</think>正文"])
        self.assertEqual("".join(stream), "<think>SECRET</think>正文")
        self.assertEqual(get(), "<think>SECRET</think>正文")
        self.assertEqual(fake.clears, 1)

    def test_malformed_input_has_process_deadline(self):
        code = ("from utils import strip_thinking_tokens; "
                "assert strip_thinking_tokens('</think>x<think>SECRET') == 'x'; "
                "assert strip_thinking_tokens('a<think>x<think>y</think>z</think>b') == 'ab'")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        result = subprocess.run([sys.executable, "-B", "-c", code], env=env,
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tool_json_arrays_quotes_escapes_multiple_and_plain_brackets(self):
        payload = {"tags": ["a", ["b", {"x": 'quote " and ] \\'}]],
                   "content": "正文 ] [ nested", "empty": []}
        marker = "[TOOL_CALL:note:" + json.dumps(payload, ensure_ascii=False) + "]"
        self.assertEqual(strip_tool_calls("前"+marker+"中"+marker+"后 [正文]"), "前中后 [正文]")
        self.assertEqual(strip_tool_calls("前[TOOL_CALL:note:action=read,note_id=x]后"), "前后")
        self.assertEqual(strip_tool_calls("前[TOOL_CALL:note:{broken"), "前")
        self.assertEqual(strip_tool_calls("普通 [数组] 和 引号"), "普通 [数组] 和 引号")

    def test_planner_reporter_history_normal_and_exception(self):
        for role in ["planner", "reporter"]:
            for error in [None, ValueError("fake")]:
                with self.subTest(role=role, error=error):
                    fake = FakeAgent('{"tasks":[{"title":"t","query":"q"}]}', error=error)
                    state = SummaryState(research_topic="topic")
                    service = PlanningService(fake, self.config) if role == "planner" else ReportingService(fake, self.config)
                    call = service.plan_todo_list if role == "planner" else service.generate_report
                    if error:
                        with self.assertRaisesRegex(ValueError, "fake"):
                            call(state)
                    else:
                        call(state)
                    self.assertEqual(fake.clears, 1)
                    self.assertEqual(fake.history, [])

    def test_stream_event_order_and_fields(self):
        t = task()
        a = self.coordinator([t])
        with patch("agent.dispatch_search", side_effect=self.search), \
             patch("agent.prepare_research_context", return_value=("sources", "context")):
            events = list(a.run_stream("topic"))
        self.assertEqual([e["type"] for e in events],
                         ["status", "todo_list", "task_status", "sources",
                          "task_summary_chunk", "task_status", "final_report", "done"])
        self.assertEqual(events[2]["status"], "in_progress")
        self.assertEqual(events[5]["status"], "completed")
        for e in events[2:6]:
            self.assertEqual(e["task_id"], 1)
            self.assertEqual(e["step"], 1)
            self.assertEqual(e["stream_token"], "task_1")
        self.assertEqual(events[4]["content"], "sum")
        self.assertTrue({"type", "report", "note_id", "note_path"} <= set(events[-2]))
        self.assertEqual(events[-2]["run_status"], "completed")
        self.assertTrue(events[-2]["run_id"])

if __name__ == "__main__":
    unittest.main()
