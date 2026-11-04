"""Offline reproductions against the unmodified local project and installed framework.
Run from repository root: code/chapter14/helloagents-deepresearch/backend/.venv/bin/python -B docs/audit_repro.py
Tests assert observed current behavior, including defects; passing does not mean fixed.
"""
from __future__ import annotations
import concurrent.futures
import contextlib
import hashlib
import importlib
import io
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "code/chapter14/helloagents-deepresearch"
os.chdir(ROOT)
assert os.environ.get("WSL_DISTRO_NAME") == "Ubuntu22.04.3"
assert subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip() == str(ROOT)
sys.dont_write_bytecode = True
sys.path.insert(0, str(BASE / "backend/src"))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
with contextlib.redirect_stdout(io.StringIO()):
    import agent as orchestration
from config import Configuration
from models import SummaryState, TodoItem
from services.tool_events import ToolCallTracker
import services.tool_events as events_module
from services.summarizer import SummarizationService
from services.reporter import ReportingService
from services.planner import PlanningService
from services.text_processing import strip_tool_calls
from services.search import prepare_research_context
from hello_agents import HelloAgentsLLM, ToolAwareSimpleAgent
from hello_agents.tools import ToolRegistry, SearchTool
from hello_agents.tools.builtin.note_tool import NoteTool
import hello_agents.tools.builtin.note_tool as note_module
import hello_agents.tools.builtin.search_tool as search_module
import httpx
from openai import OpenAI
logging.disable(logging.CRITICAL)

OBSERVATIONS = {}
def task(i=1):
    return TodoItem(id=i, title=f"task {i}", intent="intent", query=f"q{i}")
class FakeAgent:
    def __init__(self, chunks=(), error=False):
        self.chunks, self.error, self.cleared, self.prompt = chunks, error, False, ""
    def run(self, prompt):
        self.prompt = prompt
        if self.error:
            raise RuntimeError("fake model error")
        return "summary"
    def stream_run(self, prompt):
        self.prompt = prompt
        yield from self.chunks
        if self.error:
            raise RuntimeError("fake stream error")
    def clear_history(self):
        self.cleared = True
def successful_search(*args):
    return {"results": [{"title": "source", "url": "https://example.invalid/a", "content": "facts"}]}, [], None, "fake"
def orchestrator(tasks):
    with patch.object(orchestration.DeepResearchAgent, "_init_llm", return_value=NS()):
        obj = orchestration.DeepResearchAgent(Configuration(enable_notes=False))
    obj.audit_state = None
    def plan(state):
        obj.audit_state = state
        return tasks
    obj.planner = NS(plan_todo_list=plan, create_fallback_task=lambda s: task())
    obj.reporting = NS(generate_report=lambda state: "report")
    obj.summarizer = NS(
        summarize_task=lambda *a: "summary",
        stream_task_summary=lambda *a: (iter(["summary"]), lambda: "summary"))
    return obj

class AuditTests(unittest.TestCase):
    def test_01_run_does_not_consume_task_generator(self):
        obj = orchestrator([task()])
        with patch.object(orchestration, "dispatch_search", side_effect=successful_search) as search:
            result = obj.run("topic")
        self.assertEqual(search.call_count, 0)
        self.assertEqual(result.todo_items[0].status, "pending")
        OBSERVATIONS["sync_run"] = {"search_calls": search.call_count, "status": result.todo_items[0].status}

    def test_02_worker_failure_state_disagrees_with_event(self):
        obj = orchestrator([task()])
        with patch.object(orchestration, "dispatch_search", side_effect=RuntimeError("fake search failure")):
            output = list(obj.run_stream("topic"))
        failures = [e for e in output if e.get("status") == "failed"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(obj.audit_state.todo_items[0].status, "in_progress")
        self.assertTrue(any(e["type"] == "final_report" for e in output))
        OBSERVATIONS["worker_failure"] = {"sse": "failed", "state": "in_progress", "final_report": True}

    def test_03_answer_without_sources_is_skipped(self):
        obj = orchestrator([task()])
        with patch.object(orchestration, "dispatch_search", return_value=({"results": [], "answer": "answer"}, [], "answer", "fake")):
            list(obj.run_stream("topic"))
        self.assertEqual(obj.audit_state.todo_items[0].status, "skipped")

    def test_04_normal_producer_events_are_delivered_once(self):
        obj = orchestrator([task(1), task(2)])
        def summary(state, item, context):
            def chunks():
                obj._tool_tracker.record({"tool_name": "note", "parsed_parameters": {"task_id": item.id}, "result": "ok"})
                yield "summary"
            return chunks(), lambda: "summary"
        obj.summarizer.stream_task_summary = summary
        with patch.object(orchestration, "dispatch_search", side_effect=successful_search):
            output = list(obj.run_stream("topic"))
        calls = [e for e in output if e["type"] == "tool_call"]
        self.assertEqual(len(calls), 2)
        self.assertEqual({e["task_id"] for e in calls}, {1, 2})
        self.assertEqual(output[-1]["type"], "done")

    def test_05_close_waits_and_worker_continues(self):
        obj = orchestrator([task()])
        entered, release, finished, closing, closed = (threading.Event() for _ in range(5))
        def search(*args):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test barrier timeout")
            finished.set()
            return successful_search()
        with patch.object(orchestration, "dispatch_search", side_effect=search):
            stream = obj.run_stream("topic")
            while next(stream).get("status") != "in_progress":
                pass
            self.assertTrue(entered.wait(1))
            def close():
                closing.set()
                stream.close()
                closed.set()
            closer = threading.Thread(target=close)
            closer.start()
            self.assertTrue(closing.wait(1))
            try:
                self.assertFalse(closed.wait(0.05))
                self.assertFalse(finished.is_set())
            finally:
                release.set()
                closer.join(3)
        self.assertTrue(closed.is_set())
        self.assertEqual(obj.audit_state.todo_items[0].status, "completed")
        OBSERVATIONS["close"] = {"blocked_until_release": True, "worker_status_after_close": "completed"}

    def test_06_counter_is_success_count_not_unique_search_sequence(self):
        obj = orchestrator([task(1), task(2)])
        barrier = threading.Barrier(2)
        values = []
        def search(query, config, loop):
            values.append(loop)
            barrier.wait(2)
            return successful_search()
        with patch.object(orchestration, "dispatch_search", side_effect=search):
            list(obj.run_stream("topic"))
        self.assertEqual(values, [0, 0])
        self.assertEqual(obj.audit_state.research_loop_count, 2)
        OBSERVATIONS["loop_count"] = {"received": values, "final": 2}

    def test_07_tracker_duplicate_ids_under_forced_valid_interleaving(self):
        tracker = ToolCallTracker(None)
        barrier = threading.Barrier(2)
        real_event = events_module.ToolCallEvent
        def construct(**kwargs):
            barrier.wait(2)
            return real_event(**kwargs)
        with patch.object(events_module, "ToolCallEvent", side_effect=construct):
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                list(pool.map(lambda _: tracker.record({"tool_name": "fake"}), range(2)))
        ids = [e["id"] for e in tracker.as_dicts()]
        self.assertEqual(ids, [1, 1])
        OBSERVATIONS["tracker_ids"] = ids

    def test_08_note_id_alone_does_not_infer_task(self):
        tracker = ToolCallTracker("/tmp/fake-notes")
        state = SummaryState(research_topic="topic", todo_items=[task()])
        tracker.record({"tool_name": "note", "parsed_parameters": {"action": "create", "tags": ["task_1"]}, "result": "ID: note_abc"})
        tracker.drain(state)
        tracker.record({"tool_name": "note", "parsed_parameters": {"action": "read", "note_id": "note_abc"}, "result": "ID: note_abc"})
        payload = tracker.drain(state)[0]
        self.assertEqual(state.todo_items[0].note_id, "note_abc")
        self.assertIsNone(payload["task_id"])

    def test_09_failed_note_operation_can_attach_nonexistent_note(self):
        tracker = ToolCallTracker(None)
        state = SummaryState(todo_items=[task()])
        tracker.record({"tool_name": "note", "parsed_parameters": {"action": "update", "task_id": 1, "note_id": "missing"}, "result": "❌ 笔记不存在: missing"})
        tracker.drain(state)
        self.assertEqual(state.todo_items[0].note_id, "missing")

    def test_10_think_marker_split_leaks(self):
        fake = FakeAgent(["<thi", "nk>SECRET", "</think>visible"])
        service = SummarizationService(lambda: fake, Configuration())
        chunks, get_summary = service.stream_task_summary(SummaryState(research_topic="topic"), task(), "context")
        visible = "".join(chunks)
        self.assertIn("SECRET", visible)
        OBSERVATIONS["think_split"] = {"stream": visible, "final": get_summary()}

    def test_11_finally_yield_can_break_close_and_skip_clear(self):
        fake = FakeAgent(["prefix<think>secret</think>TAIL"])
        chunks, _ = SummarizationService(lambda: fake, Configuration()).stream_task_summary(SummaryState(), task(), "ctx")
        self.assertEqual(next(chunks), "prefix")
        with self.assertRaisesRegex(RuntimeError, "ignored GeneratorExit"):
            chunks.close()
        self.assertFalse(fake.cleared)
        chunks.close()

    def test_12_exception_cleanup_differs_by_service(self):
        summary_agent, report_agent, planner_agent = (FakeAgent(error=True) for _ in range(3))
        with self.assertRaises(RuntimeError):
            SummarizationService(lambda: summary_agent, Configuration()).summarize_task(SummaryState(), task(), "ctx")
        with self.assertRaises(RuntimeError):
            ReportingService(report_agent, Configuration()).generate_report(SummaryState())
        with self.assertRaises(RuntimeError):
            PlanningService(planner_agent, Configuration()).plan_todo_list(SummaryState(research_topic="topic"))
        self.assertTrue(summary_agent.cleared)
        self.assertFalse(report_agent.cleared)
        self.assertFalse(planner_agent.cleared)

    def test_13_strip_regex_fails_where_framework_parser_succeeds(self):
        text = 'A[TOOL_CALL:note:{"tags":["task_1"],"content":"C"}]Z'
        self.assertNotEqual(strip_tool_calls(text), "AZ")
        obj = ToolAwareSimpleAgent(name="fake", llm=NS(), enable_tool_calling=False)
        self.assertEqual(len(obj._parse_tool_calls(text)), 1)
        self.assertEqual(json.loads(obj._parse_tool_calls(text)[0]["parameters"])["tags"], ["task_1"])
        OBSERVATIONS["strip_nested"] = strip_tool_calls(text)

    def test_14_concurrent_note_create_collides(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = NoteTool(workspace=directory)
            barrier = threading.Barrier(2)
            original = tool._generate_note_id
            def generate():
                value = original()
                barrier.wait(2)
                return value
            from datetime import datetime
            with patch.object(note_module, "datetime") as clock, patch.object(tool, "_generate_note_id", side_effect=generate):
                clock.now.return_value = datetime(2026, 1, 1)
                with concurrent.futures.ThreadPoolExecutor(2) as pool:
                    result = list(pool.map(lambda i: tool.run({"action":"create","title":f"T{i}","content":f"C{i}"}), range(2)))
            ids = [orchestration.DeepResearchAgent._extract_note_id_from_text(t) for t in result]
            self.assertEqual(ids[0], ids[1])
            self.assertEqual(len(list(Path(directory).glob("*.md"))), 1)
            self.assertEqual(len(tool.notes_index["notes"]), 2)
            OBSERVATIONS["note_create"] = {"duplicate_id": True, "files": 1, "index_records": 2}

    def test_15_note_read_modify_write_loses_independent_update(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = NoteTool(workspace=directory)
            note_id = orchestration.DeepResearchAgent._extract_note_id_from_text(tool.run({"action":"create","title":"old","content":"body","tags":["old"]}))
            barrier, tags_done = threading.Barrier(2), threading.Event()
            original_parse, original_render = tool._markdown_to_note, tool._note_to_markdown
            def parse(text):
                value = original_parse(text)
                barrier.wait(2)
                return value
            def render(note):
                if threading.current_thread().name == "title-update":
                    if not tags_done.wait(2): raise RuntimeError("test ordering timeout")
                return original_render(note)
            errors = []
            def tags():
                try: tool.run({"action":"update","note_id":note_id,"tags":["new"]})
                except Exception as exc: errors.append(str(exc))
                finally: tags_done.set()
            def title():
                try: tool.run({"action":"update","note_id":note_id,"title":"new-title"})
                except Exception as exc: errors.append(str(exc))
            with patch.object(tool, "_markdown_to_note", side_effect=parse), patch.object(tool, "_note_to_markdown", side_effect=render):
                threads=[threading.Thread(target=tags,name="tags-update"),threading.Thread(target=title,name="title-update")]
                for thread in threads:thread.start()
                for thread in threads:thread.join(3)
            self.assertFalse(errors)
            result=original_parse((Path(directory)/f"{note_id}.md").read_text())
            self.assertEqual(result["title"], "new-title")
            self.assertEqual(result["tags"], ["old"])

    def test_16_two_note_instances_overwrite_index_snapshot(self):
        from datetime import datetime
        with tempfile.TemporaryDirectory() as directory:
            first, second = NoteTool(directory), NoteTool(directory)
            with patch.object(note_module, "datetime") as clock:
                clock.now.return_value = datetime(2026, 1, 1, 0, 0, 0)
                first.run({"action":"create","title":"first","content":"first"})
                clock.now.return_value = datetime(2026, 1, 1, 0, 0, 1)
                second.run({"action":"create","title":"second","content":"second"})
            index=json.loads((Path(directory)/"notes_index.json").read_text())
            self.assertEqual(len(index["notes"]),1)
            self.assertEqual(len(list(Path(directory).glob("*.md"))),2)

    def test_17_report_matching_can_select_task_conclusion(self):
        obj=orchestrator([task()])
        obj._tool_tracker.record({"tool_name":"note","parsed_parameters":{"action":"create","note_type":"conclusion","task_id":1,"title":"task finding"},"result":"ID: task_conclusion"})
        self.assertEqual(obj._find_existing_report_note_id(SummaryState(research_topic="other")), "task_conclusion")

    def test_18_persistence_reuses_one_report_but_leaves_earlier_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            obj=orchestrator([])
            obj.note_tool=NoteTool(directory)
            obj.config.notes_workspace=directory
            for title in ["report 1","report 2"]:
                response=obj.note_tool.run({"action":"create","title":title,"content":"body","note_type":"conclusion"})
                obj._tool_tracker.record({"tool_name":"note","parsed_parameters":{"action":"create","note_type":"conclusion","title":title},"result":response})
            obj._persist_final_report(SummaryState(research_topic="topic"), "final")
            self.assertEqual(len(list(Path(directory).glob("*.md"))),2)

    def test_19_note_failure_does_not_fail_task(self):
        class LLM:
            def __init__(self): self.calls=0
            def stream_invoke(self,*args,**kwargs):
                self.calls+=1
                if self.calls==1:yield '[TOOL_CALL:note:{"action":"update","note_id":"missing","task_id":1,"content":"body"}]'
                else:yield "summary"
        with tempfile.TemporaryDirectory() as directory:
            obj=orchestrator([task()])
            obj.note_tool=NoteTool(directory)
            obj.config.notes_workspace=directory
            obj.tools_registry=ToolRegistry()
            with contextlib.redirect_stdout(io.StringIO()):obj.tools_registry.register_tool(obj.note_tool)
            obj.llm=LLM()
            obj.summarizer=SummarizationService(obj._summarizer_factory,obj.config)
            with patch.object(orchestration,"dispatch_search",side_effect=successful_search):
                output=list(obj.run_stream("topic"))
            self.assertEqual(obj.audit_state.todo_items[0].status,"completed")
            self.assertTrue(any(e["type"]=="tool_call" and "❌" in e["result"] for e in output))

    def test_20_report_input_contains_failure_and_missing_sources(self):
        fake=FakeAgent()
        item=task();item.status="failed"
        ReportingService(fake,Configuration()).generate_report(SummaryState(research_topic="topic",todo_items=[item]))
        self.assertIn("执行状态：failed",fake.prompt)
        self.assertIn("暂无来源",fake.prompt)

    def test_21_context_budget_does_not_limit_snippet_or_answer(self):
        payload={"results":[{"title":"t","url":"https://example.invalid","content":"x"*12000,"raw_content":"r"*12000}]}
        _, context=prepare_research_context(payload,"a"*12000,Configuration())
        self.assertIn("x"*12000,context)
        self.assertIn("a"*12000,context)
        self.assertGreater(len(context),32000)
        OBSERVATIONS["context_chars_one_source"]=len(context)

    def test_22_shared_llm_client_concurrent_mock_transport(self):
        def handler(request):
            body=json.loads(request.content)
            return httpx.Response(200,json={"id":"fake","object":"chat.completion","created":0,"model":"fake","choices":[{"index":0,"message":{"role":"assistant","content":body["messages"][0]["content"]},"finish_reason":"stop"}]})
        client=OpenAI(api_key="fake",base_url="https://example.invalid/v1",http_client=httpx.Client(transport=httpx.MockTransport(handler)),max_retries=0)
        llm=HelloAgentsLLM.__new__(HelloAgentsLLM)
        llm._client=client;llm.model="fake";llm.temperature=0;llm.max_tokens=None
        try:
            with concurrent.futures.ThreadPoolExecutor(4) as pool:
                result=list(pool.map(lambda i: llm.invoke([{"role":"user","content":str(i)}]),range(8)))
            self.assertEqual(result,list(map(str,range(8))))
        finally:client.close()

    def test_23_partial_llm_stream_not_explicitly_closed(self):
        class Body(httpx.SyncByteStream):
            def __init__(self):self.closed=False
            def __iter__(self):
                yield b'data: {"id":"fake","object":"chat.completion.chunk","created":0,"model":"fake","choices":[{"index":0,"delta":{"content":"hello"}}]}\n\n'
                yield b'data: [DONE]\n\n'
            def close(self):self.closed=True
        body=Body()
        client=OpenAI(api_key="fake",base_url="https://example.invalid",max_retries=0,http_client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,stream=body,headers={"content-type":"text/event-stream"}))))
        llm=HelloAgentsLLM.__new__(HelloAgentsLLM)
        llm._client=client;llm.model="fake";llm.temperature=0;llm.max_tokens=None
        retained=[]
        original=client.chat.completions.create
        def create(**kwargs):
            stream=original(**kwargs);retained.append(stream);return stream
        with patch.object(client.chat.completions,"create",side_effect=create), contextlib.redirect_stdout(io.StringIO()):
            output=llm.stream_invoke([{"role":"user","content":"hi"}])
            self.assertEqual(next(output),"hello")
            output.close()
        self.assertFalse(body.closed)
        retained[0].close();client.close()
        self.assertTrue(body.closed)

    def test_24_tools_execute_after_llm_round_not_mid_chunk(self):
        sequence=[]
        class LLM:
            def __init__(self):self.count=0
            def stream_invoke(self,*args,**kwargs):
                self.count+=1
                if self.count==1:
                    yield '[TOOL_CALL:note:{"action":"read","note_id":"missing"}]'
                    sequence.append("round_finished")
                else:yield "answer"
        with tempfile.TemporaryDirectory() as directory:
            registry=ToolRegistry()
            with contextlib.redirect_stdout(io.StringIO()):registry.register_tool(NoteTool(directory))
            obj=ToolAwareSimpleAgent(name="fake",llm=LLM(),tool_registry=registry,tool_call_listener=lambda p:sequence.append("listener"))
            self.assertEqual("".join(obj.stream_run("prompt")),"answer")
        self.assertEqual(sequence,["round_finished","listener"])
        self.assertEqual(len(obj.get_history()),2)
        obj.clear_history();self.assertEqual(obj.get_history(),[])

    def test_25_missing_undeclared_huggingface_dependency_reproduces_import_error(self):
        code = """import importlib.abc,sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='huggingface_hub' or fullname.startswith('huggingface_hub.'):
   raise ModuleNotFoundError('blocked undeclared dependency: '+fullname)
sys.meta_path.insert(0,Block())
import hello_agents
"""
        result=subprocess.run([sys.executable,"-B","-c",code],capture_output=True,text=True,env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1"})
        self.assertNotEqual(result.returncode,0)
        self.assertIn("blocked undeclared dependency: huggingface_hub",result.stderr)
        OBSERVATIONS["missing_huggingface_import"]=result.stderr.splitlines()[-1]

    def test_26_explicit_backend_overrides_global_and_advanced_falls_back(self):
        tool=SearchTool.__new__(SearchTool)
        tool.backend="hybrid";tool.tavily_client=object();tool.serpapi_key=None
        with patch.object(tool,"_search_tavily",side_effect=RuntimeError("429 fake")),patch.object(tool,"_search_duckduckgo",return_value={"results":[],"backend":"duckduckgo","notices":[]}) as ddg:
            result=tool.run({"input":"query","backend":"duckduckgo","mode":"structured"})
            self.assertEqual(ddg.call_count,1)
            advanced=tool.run({"input":"query","backend":"advanced","mode":"structured"})
        self.assertIn("429 fake",advanced["notices"][0])

    def test_27_fastapi_error_is_sse_after_http_200(self):
        with contextlib.redirect_stdout(io.StringIO()):
            import main
        from loguru import logger
        logger.disable("main")
        from fastapi.testclient import TestClient
        class FakeResearch:
            def __init__(self,config):pass
            def run_stream(self,topic):
                yield {"type":"status","message":"started"}
                raise RuntimeError("fake stage error")
        with patch.object(main,"DeepResearchAgent",FakeResearch):
            response=TestClient(main.app).post("/research/stream",json={"topic":"topic"})
        self.assertEqual(response.status_code,200)
        parsed=[json.loads(frame[6:]) for frame in response.text.strip().split("\n\n")]
        self.assertEqual([event["type"] for event in parsed],["status","error"])
        self.assertIn("text/event-stream",response.headers["content-type"])

    def test_28_asgi_disconnect_does_not_cancel_active_worker(self):
        import asyncio
        import main
        obj = orchestrator([task()])
        entered, release, returned = threading.Event(), threading.Event(), threading.Event()
        def search(*args):
            entered.set()
            if not release.wait(3): raise RuntimeError("test barrier timeout")
            returned.set()
            return successful_search()
        async def scenario():
            disconnected = asyncio.Event()
            bodies = []
            async def receive():
                await disconnected.wait()
                return {"type": "http.disconnect"}
            async def send(message):
                if message["type"] == "http.response.body":
                    text = message.get("body", b"").decode()
                    bodies.append(text)
                    if '"status": "in_progress"' in text:
                        disconnected.set()
            with patch.object(main, "DeepResearchAgent", return_value=obj):
                route = next(route for route in main.app.routes if getattr(route, "path", "") == "/research/stream")
                response = route.endpoint(main.ResearchRequest(topic="fake"))
            request = asyncio.create_task(response({"type":"http", "asgi":{"spec_version":"2.3"}}, receive, send))
            try:
                await asyncio.wait_for(disconnected.wait(), 2)
                self.assertTrue(entered.wait(1))
                await asyncio.sleep(0.03)
                self.assertFalse(returned.is_set())
                self.assertEqual(obj.audit_state.todo_items[0].status, "in_progress")
            finally:
                release.set()
                await asyncio.wait_for(request, 3)
            self.assertTrue(returned.wait(1))
            OBSERVATIONS["asgi_disconnect"] = {"spec_version": "2.3", "worker_active_after_disconnect": True}
        with patch.object(orchestration, "dispatch_search", side_effect=search):
            asyncio.run(scenario())

    def test_29_note_id_can_escape_workspace_in_contained_temp_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = NoteTool(str(Path(directory)/"outer"))
            response = outside.run({"action":"create","title":"outside","content":"outside"})
            note_id = orchestration.DeepResearchAgent._extract_note_id_from_text(response)
            inner = NoteTool(str(Path(directory)/"inner"))
            result = inner.run({"action":"read","note_id":f"../outer/{note_id}"})
            self.assertIn("outside", result)
            result = inner.run({"action":"update","note_id":f"../outer/{note_id}","content":"changed outside inner workspace"})
            self.assertTrue(result.startswith("✅"))
            self.assertIn("changed outside inner workspace", outside.run({"action":"read","note_id":note_id}))

    def test_30_reversed_think_tags_do_not_terminate(self):
        code = (
            "import sys;sys.path.insert(0," + repr(str(BASE / "backend/src")) + ");"
            "from utils import strip_thinking_tokens;"
            "print('entered',flush=True);strip_thinking_tokens('</think><think>')"
        )
        with self.assertRaises(subprocess.TimeoutExpired) as failure:
            subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=0.6)
        output = failure.exception.stdout or b""
        if isinstance(output, bytes): output = output.decode()
        self.assertIn("entered", output)
        OBSERVATIONS["reversed_think_tags"] = "nonterminating; isolated child killed at 0.6 seconds"

if __name__=="__main__":
    # All external sockets are blocked. MockTransport and in-process ASGI need no network.
    with patch.object(socket.socket,"connect",side_effect=AssertionError("External network prohibited by audit")),patch.object(socket,"create_connection",side_effect=AssertionError("External network prohibited by audit")):
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(AuditTests)
        result=unittest.TextTestRunner(verbosity=2).run(suite)
    print("AUDIT_OBSERVATIONS="+json.dumps(OBSERVATIONS,ensure_ascii=False,sort_keys=True))
    raise SystemExit(not result.wasSuccessful())
