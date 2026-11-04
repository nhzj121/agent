"""Actual HTTP/SSE + Fake LLM/search + TemporaryDirectory Repository."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "code/chapter14/helloagents-deepresearch/backend/src"
sys.path.insert(0, str(SRC))
from fastapi.testclient import TestClient
import main
from agent import DeepResearchAgent
from config import Configuration
from storage.file_notes import FileNoteRepository
from storage.manual_edit import ManualEditController
from test_phase_2b_versions import FakeLLM

def frames(text):
    return [json.loads(block[5:].strip()) for block in text.split("\n\n") if block.startswith("data:")]

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = FileNoteRepository(self.tmp.name)
        self.addCleanup(self.repo.close)
        for name in ["socket.socket.connect", "socket.getaddrinfo"]:
            guard = patch(name, side_effect=AssertionError("external API forbidden"))
            guard.start(); self.addCleanup(guard.stop)

    def factory(self, *, config):
        coordinator = None
        def script(i, messages):
            if i == 0:
                return '{"tasks":[{"title":"t","intent":"i","query":"q"}]}'
            if i == 1:
                return '[TOOL_CALL:note:{"action":"create","title":"task","content":"task-note"}]'
            if i == 2:
                return "task-summary"
            if i == 3:
                binding = coordinator._note_owner.binding(1)
                read = ("[TOOL_CALL:note:" + json.dumps(
                    {"action":"read","note_id":binding.note_id}) + "]") if binding else ""
                return read + '[TOOL_CALL:note:{"action":"create","title":"report","content":"draft"}]'
            return "final-report"
        llm = FakeLLM(script)
        config = Configuration(enable_notes=True, notes_workspace="/do-not-access")
        with patch.object(DeepResearchAgent, "_init_llm", return_value=llm), \
             patch("agent.NoteTool", side_effect=AssertionError("legacy forbidden")):
            coordinator = DeepResearchAgent(config, note_repository=self.repo)
        return coordinator

    def test_complete_explicit_repository_workflow_and_frontend_fixture(self):
        with patch("agent.dispatch_search", return_value=(
                {"results":[{"url":"https://fake.invalid"}]}, [], "", "fake")), \
             patch("agent.prepare_research_context", return_value=("sources", "context")):
            with TestClient(main.create_app(agent_factory=self.factory)) as client:
                sync = client.post("/research", json={"topic":"fake"}).json()
                response = client.post("/research/stream", json={"topic":"fake"})
        events = frames(response.text)
        self.assertEqual(sync["run_status"], "completed")
        self.assertEqual(sync["todo_items"][0]["note_status"], "saved")
        final = next(e for e in events if e["type"] == "final_report")
        self.assertEqual(events[-1]["run_status"], "completed")
        self.assertEqual(final["tasks"][0]["note_status"], "saved")
        self.assertEqual(final["tasks"][0]["summary"], "task-summary")
        self.assertEqual(sum(e["type"] == "report_note" for e in events), 1)
        run = final["run_id"]
        owned = [n for n in self.repo.list() if n.extra.get("run_id") == run]
        self.assertEqual(len(owned), 2)
        self.assertEqual(sum(n.extra["purpose"] == "final_report" for n in owned), 1)
        self.assertEqual(self.repo.read(final["note_id"]).extra["purpose"], "final_report")
        tool_events = [e for e in events if e["type"] == "tool_call"]
        self.assertEqual(len({e["event_id"] for e in tool_events}), len(tool_events))
        reads = [e for e in tool_events if e["parameters"]["action"] == "read"]
        self.assertEqual(len(reads), 1)
        self.assertEqual(reads[0]["task_id"], 1)
        self.assertEqual(reads[0]["stage"], "reporter")
        self.assertEqual(reads[0]["note_id"], final["tasks"][0]["note_id"])

        self.assertTrue(all(e["run_id"] == run for e in events))
        (ROOT/"docs/g3_evidence/fake-workflow.json").write_text(json.dumps(
            {"events":events,"expected":final},ensure_ascii=False,indent=2))

    def test_summary_completed_with_note_paused_is_visible(self):
        ManualEditController(self.repo).begin()
        with patch("agent.dispatch_search", return_value=(
                {"results":[{"url":"https://fake.invalid"}]}, [], "", "fake")), \
             patch("agent.prepare_research_context", return_value=("sources", "context")), \
             TestClient(main.create_app(agent_factory=self.factory)) as client:
            events = frames(client.post("/research/stream", json={"topic":"fake"}).text)
        final = next(e for e in events if e["type"] == "final_report")
        task = final["tasks"][0]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["summary"], "task-summary")
        self.assertEqual(task["note_status"], "paused")
        self.assertIsNone(task["note_id"])
        self.assertTrue(final["warnings"])
        self.assertEqual(final["report_note_status"], "paused")
        self.assertIsNone(final["note_id"])
        (ROOT/"docs/g3_evidence/fake-paused.json").write_text(json.dumps(
            {"events":events,"expected":final},ensure_ascii=False,indent=2))

    def test_sync_and_sse_failures_share_task_and_reporter_status(self):
        agents = []
        def factory(*, config):
            llm = FakeLLM(lambda i,m: (
                '{"tasks":[{"title":"ok","query":"ok"},{"title":"bad","query":"bad"}]}'
                if i == 0 else "report"))
            with patch.object(DeepResearchAgent, "_init_llm", return_value=llm):
                a = DeepResearchAgent(Configuration(enable_notes=False))
            agents.append((a,llm))
            return a
        def search(query,*args):
            if query == "bad": raise ValueError("fake search failure")
            return {"results":[{"url":"https://fake.invalid"}]}, [], "", "fake"
        with patch("agent.dispatch_search", side_effect=search), \
             patch("agent.prepare_research_context", return_value=("sources","context")), \
             TestClient(main.create_app(agent_factory=factory)) as client:
            sync_response = client.post("/research", json={"topic":"fake"})
            stream_response = client.post("/research/stream", json={"topic":"fake"})
        self.assertEqual(sync_response.status_code, 200)
        sync = sync_response.json()
        events = frames(stream_response.text)
        final = next(e for e in events if e["type"]=="final_report")
        self.assertEqual(sync["run_status"], "partial")
        self.assertEqual(final["run_status"], "partial")
        self.assertEqual([t["status"] for t in sync["todo_items"]], ["completed","failed"])
        self.assertEqual([t["status"] for t in final["tasks"]], ["completed","failed"])
        self.assertEqual(sum(e["type"]=="task_status" and e["status"]=="failed" for e in events),1)
        for a,llm in agents:
            self.assertIn("执行状态：failed", llm.messages[-1][-1]["content"])

    def test_two_workers_sink_put_failure_replays_once_with_correct_task(self):
        from queue import Queue
        from threading import Barrier, Lock
        barrier = Barrier(2)
        class FailOnceQueue(Queue):
            def __init__(self):
                super().__init__()
                self.failed = False
                self.gate = Lock()
            def put(self, item, *args, **kwargs):
                with self.gate:
                    if item.get("type") == "tool_call" and not self.failed:
                        self.failed = True
                        raise OSError("one enqueue failure")
                return super().put(item,*args,**kwargs)
        def script(i,messages):
            initial = next(m["content"] for m in messages if m["role"]=="user")
            if initial.startswith("任务主题："):
                if len(messages)==2:
                    barrier.wait(5)
                    return '[TOOL_CALL:note:{"action":"create","title":"task","content":"body"}]'
                return "summary"
            if "任务概览：" in initial:
                if len(messages)==2:
                    return '[TOOL_CALL:note:{"action":"create","title":"report","content":"draft"}]'
                return "report"
            return '{"tasks":[{"title":"one","query":"q1"},{"title":"two","query":"q2"}]}'
        llm = FakeLLM(script)
        with patch.object(DeepResearchAgent, "_init_llm", return_value=llm):
            a = DeepResearchAgent(Configuration(enable_notes=True), note_repository=self.repo)
        with patch("agent.Queue", FailOnceQueue), \
             patch("agent.dispatch_search", return_value=(
                 {"results":[{"url":"https://fake.invalid"}]}, [], "", "fake")), \
             patch("agent.prepare_research_context", return_value=("sources","context")):
            events = list(a.run_stream("fake"))
        tools = [e for e in events if e["type"]=="tool_call"]
        self.assertEqual(len(tools),3)
        self.assertEqual(len({e["event_id"] for e in tools}),3)
        tasks = next(e for e in events if e["type"]=="final_report")["tasks"]
        self.assertEqual([t["note_status"] for t in tasks],["saved","saved"])
        for event in tools:
            n = self.repo.read(event["note_id"])
            self.assertEqual(n.extra.get("task_id"),event["task_id"])

    def test_reused_agent_disabling_notes_does_not_borrow_old_run(self):
        script = [
            '{"tasks":[{"title":"t","query":"q"}]}',
            '[TOOL_CALL:note:{"action":"create","title":"task","content":"body"}]',
            "summary",
            '[TOOL_CALL:note:{"action":"create","title":"report","content":"draft"}]',
            "report",
            '{"tasks":[{"title":"t","query":"q"}]}',
            "summary-disabled", "report-disabled"]
        with patch.object(DeepResearchAgent, "_init_llm", return_value=FakeLLM(lambda i,m:script[i])):
            a = DeepResearchAgent(Configuration(enable_notes=True), note_repository=self.repo)
        with patch("agent.dispatch_search", return_value=(
                {"results":[{"url":"https://fake.invalid"}]}, [], "", "fake")), \
             patch("agent.prepare_research_context", return_value=("sources","context")):
            one = a.run("one")
            a.config.enable_notes = False
            two = a.run("two")
        self.assertNotEqual(one.run_id,two.run_id)
        self.assertEqual(two.todo_items[0].note_status,"disabled")
        self.assertIsNone(two.todo_items[0].note_id)
        self.assertIsNone(two.report_note_id)
        self.assertEqual(two.report_note_status,"disabled")
        self.assertEqual(len(self.repo.list()),2)

    def test_all_skipped_is_failed_and_research_fatal_valueerror_is_500(self):
        def factory(*,config):
            llm = FakeLLM(lambda i,m:'{"tasks":[{"title":"t","query":"q"}]}' if i==0 else "report")
            with patch.object(DeepResearchAgent,"_init_llm",return_value=llm):
                return DeepResearchAgent(Configuration(enable_notes=False))
        with patch("agent.dispatch_search",return_value=({"results":[]},[],"","fake")), \
             TestClient(main.create_app(agent_factory=factory)) as client:
            result=client.post("/research",json={"topic":"x"}).json()
        self.assertEqual(result["run_status"],"failed")
        self.assertEqual(result["todo_items"][0]["status"],"skipped")
        class Bad:
            def run(self,topic): raise ValueError("planner model failed")
        with TestClient(main.create_app(agent_factory=lambda **kw:Bad())) as client:
            self.assertEqual(client.post("/research",json={"topic":"x"}).status_code,500)

    def test_same_agent_reentry_is_rejected_until_original_work_finishes(self):
        from threading import Event, Thread
        entered, release = Event(), Event()
        outputs = []
        def search(*args):
            entered.set()
            if not release.wait(5): raise RuntimeError("test release timeout")
            return {"results":[{"url":"https://fake.invalid"}]}, [], "", "fake"
        llm = FakeLLM(lambda i,m:'{"tasks":[{"title":"t","query":"q"}]}' if i==0 else "report")
        with patch.object(DeepResearchAgent, "_init_llm", return_value=llm):
            agent = DeepResearchAgent(Configuration(enable_notes=False))
        with patch("agent.dispatch_search",side_effect=search), \
             patch("agent.prepare_research_context",return_value=("sources","context")):
            thread = Thread(target=lambda: outputs.append(agent.run("first")),daemon=True)
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                run_id = agent.run_id
                with self.assertRaisesRegex(RuntimeError,"already running"):
                    agent.run("second")
                self.assertEqual(agent.run_id,run_id)
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outputs[0].run_status,"completed")
        self.assertFalse(agent._run_lock.locked())

    def test_worker_start_failure_is_terminal_without_hang(self):
        llm = FakeLLM(lambda i,m: '{"tasks":[{"title":"t","query":"q"}]}' if i==0 else "report")
        with patch.object(DeepResearchAgent, "_init_llm", return_value=llm):
            agent = DeepResearchAgent(Configuration(enable_notes=False))
        with patch("agent.Thread.start", side_effect=RuntimeError("cannot start")):
            events = list(agent.run_stream("fake"))
        terminal = [e for e in events if e["type"]=="task_status" and e["status"]=="failed"]
        self.assertEqual(len(terminal), 1)
        self.assertEqual(events[-1]["run_status"], "failed")

    def test_fatal_stream_exception_after_headers_emits_error_and_releases_iterator(self):
        class Bad:
            run_id = "bad-run"
            run_status = "running"
            closed = False
            def run(self, topic): raise RuntimeError("fatal")
            def run_stream(self, topic):
                try:
                    yield {"type":"status","run_id":self.run_id}
                    raise RuntimeError("fatal")
                finally:
                    self.closed = True
        instance = Bad()
        with TestClient(main.create_app(agent_factory=lambda **kw: instance)) as client:
            self.assertEqual(client.post("/research",json={"topic":"x"}).status_code,500)
            response = client.post("/research/stream",json={"topic":"x"})
        self.assertEqual(response.status_code,200)
        events = frames(response.text)
        self.assertEqual(events[-1]["type"],"error")
        self.assertEqual(events[-1]["run_status"],"failed")
        self.assertTrue(instance.closed)

if __name__ == "__main__":
    unittest.main()
