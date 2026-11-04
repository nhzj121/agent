"""G4a.1 offline acceptance: no real providers or existing note workspaces."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "code/chapter14/helloagents-deepresearch/backend/src"
sys.path.insert(0, str(SRC))
from agent import DeepResearchAgent
from config import Configuration
from test_phase_2b_versions import FakeLLM
from storage.file_notes import FileNoteRepository

SEARCH = ({"results":[{"url":"https://fake.invalid"}]}, [], "", "fake")

class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = FileNoteRepository(self.tmp.name)
        self.addCleanup(self.repo.close)
        for target in ["socket.socket.connect", "socket.getaddrinfo"]:
            guard = patch(target, side_effect=AssertionError("external network forbidden"))
            guard.start(); self.addCleanup(guard.stop)

    def make(self, count=1, **options):
        def script(i, messages):
            prompt = next(m["content"] for m in messages if m["role"]=="user")
            if prompt.startswith("任务主题："): return "summary"
            if "任务概览：" in prompt: return "report"
            return json.dumps({"tasks":[{"title":str(n),"query":str(n)} for n in range(count)]})
        with patch.object(DeepResearchAgent, "_init_llm", return_value=FakeLLM(script)):
            return DeepResearchAgent(Configuration(enable_notes=True, **options), note_repository=self.repo)

    def test_defaults_and_environment(self):
        c = Configuration()
        self.assertEqual((c.max_task_workers,c.max_active_research,c.max_planned_tasks), (3,2,8))
        self.assertEqual((c.research_deadline_seconds,c.model_connect_timeout,c.model_read_timeout),(180,5,20))
        with patch.dict("os.environ", {"MAX_TASK_WORKERS":"2","MODEL_MAX_RETRIES":"0"}):
            self.assertEqual(Configuration.from_env().max_task_workers,2)
            self.assertEqual(Configuration.from_env().model_max_retries,0)
        for key in ["max_task_workers","max_active_research","max_planned_tasks",
                    "research_deadline_seconds","model_connect_timeout","model_read_timeout"]:
            with self.subTest(key=key), self.assertRaises(ValueError): Configuration(**{key:0})

    def test_eight_tasks_real_active_workers_bounded(self):
        a = self.make(8)
        lock = threading.Lock()
        active = peak = calls = 0
        def search(*args):
            nonlocal active,peak,calls
            with lock:
                active += 1; calls += 1; peak = max(peak,active)
            time.sleep(.025)
            with lock: active -= 1
            return SEARCH
        with patch("agent.dispatch_search", side_effect=search), patch("agent.prepare_research_context",return_value=("s","c")):
            events=list(a.run_stream("topic"))
        self.assertLessEqual(peak,3)
        self.assertGreater(peak,1)
        self.assertEqual(calls,8)
        self.assertEqual([t.status for t in a._active_state.todo_items],["completed"]*8)
        self.assertEqual(events[-1]["run_status"],"completed")

    def test_excess_plan_is_rejected_not_truncated(self):
        a=self.make(9)
        with patch("agent.dispatch_search") as search:
            with self.assertRaisesRegex(ValueError,"MAX_PLANNED_TASKS"):
                list(a.run_stream("topic"))
        search.assert_not_called()
        self.assertEqual(len(a._active_state.todo_items),9)
        self.assertTrue(all(t.status=="failed" for t in a._active_state.todo_items))
        self.assertEqual(a.run_status,"failed")

    def test_search_deadline_blocks_summary_report_and_late_completion(self):
        from services.execution_control import ExecutionControl
        now=[10.]
        ctx=ExecutionControl(1,clock=lambda:now[0])
        a=self.make(4)
        def search(*args):
            now[0]=12.
            return SEARCH
        with patch.object(a,"_begin_notes_run"), patch("agent.dispatch_search",side_effect=search), patch.object(a.reporting,"generate_report") as reporter:
            events=list(a.run_stream("topic",execution=ctx))
        self.assertEqual(events[-1]["type"],"done")
        self.assertEqual(events[-1]["run_status"],"cancelled")
        self.assertTrue(all(t.status=="cancelled" for t in a._active_state.todo_items))
        self.assertTrue(all(t.error_code=="DEADLINE_EXCEEDED" for t in a._active_state.todo_items))
        reporter.assert_not_called()
        self.assertFalse(any(e["type"]=="final_report" for e in events))
        self.assertFalse(any(e["type"]=="task_status" and e["status"]=="completed" for e in events))

    def test_cancel_keeps_run_lock_and_capacity_until_blocked_search_really_exits(self):
        from services.execution_control import ExecutionControl, ResearchAdmission, ResearchBusy
        admission=ResearchAdmission(2)
        lease1,lease2=admission.acquire(),admission.acquire()
        ctx=ExecutionControl(60,on_idle=lease1.release)
        a=self.make(1)
        entered,release=threading.Event(),threading.Event()
        def search(*args):
            entered.set()
            if not release.wait(5): raise RuntimeError("test wait")
            return SEARCH
        stream=a.run_stream("topic",execution=ctx)
        events=[]
        def consume():
            try: events.extend(stream)
            except Exception as exc: events.append(exc)
        with patch("agent.dispatch_search",side_effect=search):
            thread=threading.Thread(target=consume);thread.start()
            try:
                self.assertTrue(entered.wait(2))
                ctx.cancel("test cancellation")
                thread.join(1)
                self.assertFalse(thread.is_alive(),"control loop must finish without joining blocked call")
                self.assertTrue(a._run_lock.locked())
                with self.assertRaises(ResearchBusy): admission.acquire()
                with self.assertRaisesRegex(RuntimeError,"already running"): a.run("second")
            finally:
                release.set();thread.join(5)
        self.assertTrue(ctx.wait_idle(3))
        self.assertFalse(a._run_lock.locked())
        self.assertEqual(admission.active,1)
        self.assertEqual(a._active_state.todo_items[0].status,"cancelled")
        self.assertEqual(events[-1]["run_status"],"cancelled")
        lease2.release()
        self.assertEqual(admission.active,0)

    def test_http_admission_429_before_factory_and_recovery(self):
        from services.execution_control import ResearchAdmission
        import main
        from fastapi.testclient import TestClient
        admission=ResearchAdmission(2)
        leases=[admission.acquire(),admission.acquire()]
        with patch.object(main,"_build_config",return_value=Configuration(enable_notes=False)), \
             TestClient(main.create_app(agent_factory=lambda **kw:self.make(),admission=admission)) as client:
            for path in ["/research","/research/stream"]:
                response=client.post(path,json={"topic":"x"})
                self.assertEqual(response.status_code,429)
                self.assertEqual(response.json()["detail"]["code"],"RESEARCH_CAPACITY_EXCEEDED")
            leases.pop().release()
            with patch("agent.dispatch_search",return_value=SEARCH),patch("agent.prepare_research_context",return_value=("s","c")):
                self.assertEqual(client.post("/research",json={"topic":"x"}).status_code,200)
            self.assertEqual(admission.active,1)
        leases.pop().release()

    def test_worker_start_failure_and_stage_exceptions(self):
        for stage in ["planner","search","summary","reporter","start"]:
            with self.subTest(stage=stage):
                a=self.make(2)
                target={"planner":(a.planner,"plan_todo_list"),"summary":(a.summarizer,"stream_task_summary"),
                        "reporter":(a.reporting,"generate_report")}
                with patch.object(a,"_begin_notes_run"), patch("agent.dispatch_search",side_effect=RuntimeError("search error") if stage=="search" else None,
                           return_value=SEARCH),patch("agent.prepare_research_context",return_value=("s","c")):
                    if stage in target:
                        obj,name=target[stage]
                        with patch.object(obj,name,side_effect=RuntimeError(stage)):
                            if stage in ["planner","reporter"]:
                                with self.assertRaisesRegex(RuntimeError,stage): list(a.run_stream("x"))
                            else: list(a.run_stream("x"))
                    elif stage=="start":
                        with patch("agent.Thread.start",side_effect=RuntimeError("start")):
                            list(a.run_stream("x"))
                    else: list(a.run_stream("x"))
                self.assertFalse(a._run_lock.locked())
                if stage in ["search","summary","start"]:
                    self.assertEqual([t.status for t in a._active_state.todo_items],["failed"]*2)
                if stage in ["planner","reporter"]: self.assertEqual(a._active_state.run_status,"failed")

    def test_note_write_after_cancel_rejected_without_changing_etag(self):
        from services.execution_control import ExecutionControl, bind_execution
        from services.agent_adapter import ProjectToolAwareAgent
        from services.note_ownership import NoteOwnership
        from services.note_versions import NoteScope
        owner=NoteOwnership(self.repo,"run")
        scope=NoteScope("run","task",1)
        ctx=ExecutionControl(60)
        llm=FakeLLM(lambda i,m:'[TOOL_CALL:note:{"action":"create","title":"x","content":"body"}]')
        a=ProjectToolAwareAgent(llm=llm,repository=self.repo,ownership=owner,scope=scope,name="x",system_prompt="x")
        ctx.cancel("stop")
        with bind_execution(ctx):
            with self.assertRaises(Exception): a.run("x")
        self.assertEqual(self.repo.list(),[])
        ctx.finish()


    def test_real_two_active_researches_third_rejected_before_initialization(self):
        from services.execution_control import ResearchAdmission
        import main
        from fastapi.testclient import TestClient
        admission=ResearchAdmission(2)
        entered=threading.Barrier(3)
        release=threading.Event()
        created=[]
        def factory(**kw):
            a=self.make();created.append(a);return a
        def search(*args):
            entered.wait(4)
            if not release.wait(5): raise RuntimeError("test release")
            return SEARCH
        responses=[]
        def request():
            with TestClient(main.create_app(agent_factory=factory,admission=admission)) as client:
                responses.append(client.post("/research",json={"topic":"x"}))
        with patch("agent.dispatch_search",side_effect=search),patch("agent.prepare_research_context",return_value=("s","c")):
            threads=[threading.Thread(target=request) for _ in range(2)]
            for t in threads:t.start()
            try:
                entered.wait(4)
                with TestClient(main.create_app(agent_factory=factory,admission=admission)) as client:
                    response=client.post("/research/stream",json={"topic":"third"})
                self.assertEqual(response.status_code,429)
                self.assertEqual(len(created),2)
                self.assertEqual(admission.active,2)
            finally:
                release.set()
                for t in threads:t.join(5)
        self.assertTrue(all(not t.is_alive() for t in threads))
        self.assertEqual([x.status_code for x in responses],[200,200])
        self.assertEqual(admission.active,0)

    def test_deadline_during_summary_never_starts_reporter_and_keeps_capacity(self):
        from services.execution_control import ExecutionControl
        now=[0.]
        ctx=ExecutionControl(1,clock=lambda:now[0])
        a=self.make(4)
        entered,release=threading.Event(),threading.Event()
        calls=[]
        def summary(*args):
            def chunks():
                entered.set()
                if not release.wait(5):raise RuntimeError("test wait")
                yield "late"
            calls.append("summary")
            return chunks(),lambda:"late"
        events=[]
        with patch.object(a,"_begin_notes_run"),patch("agent.dispatch_search",return_value=SEARCH), \
             patch("agent.prepare_research_context",return_value=("s","c")), \
             patch.object(a.summarizer,"stream_task_summary",side_effect=summary), \
             patch.object(a.reporting,"generate_report") as reporter:
            thread=threading.Thread(target=lambda:events.extend(a.run_stream("x",execution=ctx)))
            thread.start()
            try:
                self.assertTrue(entered.wait(2));now[0]=2.
                thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertTrue(a._run_lock.locked())
                reporter.assert_not_called()
            finally:
                release.set();thread.join(5)
                self.assertTrue(ctx.wait_idle(3))
        self.assertTrue(all(t.status=="cancelled" for t in a._active_state.todo_items))
        self.assertFalse(any(e["type"]=="task_summary_chunk" for e in events))
        self.assertEqual(events[-1]["run_status"],"cancelled")

    def test_sync_and_stream_deadline_agree_no_fabricated_report(self):
        from services.execution_control import ExecutionControl
        snapshots=[]
        for streamed in [False,True]:
            a=self.make(2)
            now=[0.]
            ctx=ExecutionControl(1,clock=lambda:now[0])
            def search(*args):
                now[0]=2.
                return SEARCH
            with patch("agent.dispatch_search",side_effect=search):
                if streamed:
                    events=list(a.run_stream("x",execution=ctx))
                    self.assertEqual(events[-1]["run_status"],"cancelled")
                else:
                    output=a.run("x",execution=ctx)
                    self.assertEqual(output.run_status,"cancelled")
                    self.assertEqual(output.report_markdown,"")
            snapshots.append([(t.status,t.error_code) for t in a._active_state.todo_items])
        self.assertEqual(snapshots[0],snapshots[1])

    def test_close_with_blocked_worker_returns_without_releasing_its_slot(self):
        from services.execution_control import ExecutionControl
        ctx=ExecutionControl(60)
        a=self.make(1)
        entered,release=threading.Event(),threading.Event()
        def search(*args):
            entered.set()
            if not release.wait(5):raise RuntimeError("test wait")
            return SEARCH
        with patch("agent.dispatch_search",side_effect=search):
            stream=a.run_stream("x",execution=ctx)
            try:
                while next(stream)["type"]!="task_status":pass
                self.assertTrue(entered.wait(2))
                start=time.monotonic();stream.close()
                self.assertLess(time.monotonic()-start,.5)
                self.assertTrue(a._run_lock.locked())
            finally:
                release.set()
                self.assertTrue(ctx.wait_idle(3))
        self.assertEqual(a._active_state.todo_items[0].status,"cancelled")
        self.assertFalse(a._run_lock.locked())

    def test_planner_reporter_return_after_deadline_cannot_advance(self):
        from services.execution_control import ExecutionControl
        for stage in ["planner","reporter"]:
            a=self.make()
            now=[0.]
            ctx=ExecutionControl(1,clock=lambda:now[0])
            obj,name=(a.planner,"plan_todo_list") if stage=="planner" else (a.reporting,"generate_report")
            def late(*args):
                now[0]=2.
                return [__import__("models").TodoItem(id=1,title="x",intent="i",query="q")] if stage=="planner" else "late report"
            with patch.object(a,"_begin_notes_run"),patch.object(obj,name,side_effect=late), \
                 patch("agent.dispatch_search",return_value=SEARCH),patch("agent.prepare_research_context",return_value=("s","c")):
                events=list(a.run_stream("x",execution=ctx))
            self.assertEqual(events[-1]["run_status"],"cancelled")
            self.assertFalse(any(e["type"] in ("final_report","report_note") for e in events))
            self.assertEqual(self.repo.list(),[])

    def test_cancel_orders_note_commit_and_prevents_followup_write(self):
        from services.execution_control import ExecutionControl,bind_execution
        from tools.controlled_tool import ControlledTool
        from hello_agents.tools.base import Tool
        ctx=ExecutionControl(60)
        entered,release=threading.Event(),threading.Event()
        writes=[]
        class FakeTool(Tool):
            def __init__(self):super().__init__("note","fake")
            def get_parameters(self):return []
            def run(self,p):
                entered.set()
                if not release.wait(5):raise RuntimeError("test wait")
                writes.append("committed")
                return "ok"
        tool=ControlledTool(FakeTool())
        def commit():
            with bind_execution(ctx):tool.run({})
        writer=threading.Thread(target=commit)
        cancelled=threading.Event()
        def cancel():ctx.cancel("stop");cancelled.set()
        writer.start()
        self.assertTrue(entered.wait(2))
        canceller=threading.Thread(target=cancel);canceller.start()
        self.assertFalse(cancelled.wait(.05))
        release.set();writer.join(3);canceller.join(3)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(writes,["committed"])
        with bind_execution(ctx):
            with self.assertRaises(Exception):tool.run({})
        self.assertEqual(writes,["committed"])
        ctx.finish()


    def test_legacy_factory_protocol_and_initialization_failure_release_admission(self):
        import main
        from fastapi.testclient import TestClient
        from services.execution_control import ResearchAdmission
        admission=ResearchAdmission(2)
        class Legacy:
            def __init__(self,config):pass
            def run(self,topic):return SimpleNamespace(report_markdown="legacy",running_summary="legacy",todo_items=[])
            def run_stream(self,topic):
                yield {"type":"status"}
                yield {"type":"done"}
        with patch.object(main,"DeepResearchAgent",Legacy),TestClient(main.create_app(admission=admission)) as client:
            self.assertEqual(client.post("/research",json={"topic":"x"}).status_code,200)
            text=client.post("/research/stream",json={"topic":"x"}).text
            self.assertIn('"type": "done"',text)
        self.assertEqual(admission.active,0)
        def bad(**kwargs):raise RuntimeError("init")
        with TestClient(main.create_app(agent_factory=bad,admission=admission)) as client:
            for path in ["/research","/research/stream"]:
                self.assertEqual(client.post(path,json={"topic":"x"}).status_code,500)
                self.assertEqual(admission.active,0)


    def test_pre_cancelled_or_expired_context_starts_no_model_call(self):
        from services.execution_control import ExecutionControl
        for expired in [False,True]:
            a=self.make()
            now=[0.]
            ctx=ExecutionControl(1,clock=lambda:now[0])
            if expired:now[0]=2.
            else:ctx.cancel_event.set()
            with patch.object(a,"_begin_notes_run") as start:
                events=list(a.run_stream("x",execution=ctx))
            start.assert_not_called()
            self.assertEqual(events[-1]["type"],"done")
            self.assertEqual(events[-1]["run_status"],"cancelled")
            self.assertTrue(events[-1]["warnings"])
            self.assertFalse(a._run_lock.locked())

if __name__=="__main__": unittest.main()
