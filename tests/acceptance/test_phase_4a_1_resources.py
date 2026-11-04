"""Real OpenAI/HTTPX MockTransport: deadlines, retries and response ownership."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import httpx
from openai import OpenAI, APITimeoutError

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"code/chapter14/helloagents-deepresearch/backend/src"))
from config import Configuration

class Body(httpx.SyncByteStream):
    def __init__(self,mode="normal"):
        self.mode=mode;self.closed=False
    def __iter__(self):
        yield b'data: {"choices":[{"delta":{"content":"one"}}]}\n\n'
        if self.mode=="error": raise httpx.ReadError("broken stream")
        yield b'data: {"choices":[{"delta":{"content":"two"}}]}\n\n'
        yield b'data: [DONE]\n\n'
    def close(self): self.closed=True

class ResourceTests(unittest.TestCase):
    def setUp(self):
        for target in ["socket.socket.connect","socket.getaddrinfo"]:
            g=patch(target,side_effect=AssertionError("real network forbidden"));g.start();self.addCleanup(g.stop)

    def llm(self,handler,**config):
        from llm.project_llm import ProjectLLM
        client=OpenAI(api_key="fake",base_url="https://mock.invalid/v1",
                      http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        self.addCleanup(client.close)
        base=SimpleNamespace(_client=client,model="fake",temperature=0.,max_tokens=20)
        return ProjectLLM(base,Configuration(**config)),client

    def test_sdk_stream_normal_error_and_early_close(self):
        from services.execution_control import ExecutionControl,bind_execution
        for mode in ["normal","error","early"]:
            with self.subTest(mode=mode):
                body=Body(mode)
                llm,client=self.llm(lambda req:httpx.Response(200,stream=body))
                ctx=ExecutionControl(60)
                with bind_execution(ctx):
                    stream=llm.stream_invoke([{"role":"user","content":"x"}])
                    if mode=="normal": self.assertEqual(list(stream),["one","two"])
                    elif mode=="error":
                        with self.assertRaises(httpx.ReadError): list(stream)
                    else:
                        self.assertEqual(next(stream),"one");stream.close()
                self.assertTrue(body.closed)
                self.assertFalse(client.is_closed())
                ctx.finish()

    def test_one_stream_close_does_not_close_other_shared_request(self):
        bodies=[]
        def handler(req):
            b=Body();bodies.append(b);return httpx.Response(200,stream=b)
        llm,client=self.llm(handler)
        from services.execution_control import ExecutionControl,bind_execution
        ctx=ExecutionControl(60)
        with bind_execution(ctx):
            one=llm.stream_invoke([]);two=llm.stream_invoke([])
            self.assertEqual(next(one),"one");self.assertEqual(next(two),"one")
            one.close()
            self.assertFalse(client.is_closed())
            self.assertFalse(bodies[1].closed)
            self.assertEqual(list(two),["two"])
        self.assertTrue(all(b.closed for b in bodies));ctx.finish()

    def test_timeout_retries_clamped_to_remaining_budget(self):
        from services.execution_control import ExecutionControl,ExecutionStopped,bind_execution
        now=[0.];seen=[]
        def handler(req):
            seen.append(req.extensions["timeout"])
            now[0]+= .8
            raise httpx.ReadTimeout("fake timeout",request=req)
        llm,client=self.llm(handler,model_max_retries=4)
        ctx=ExecutionControl(1,clock=lambda:now[0],waiter=lambda seconds:now.__setitem__(0,now[0]+seconds))
        with bind_execution(ctx):
            with self.assertRaises(ExecutionStopped): llm.invoke([])
        self.assertLessEqual(len(seen),2)
        self.assertTrue(all(0<v<=1 for t in seen for v in t.values()))
        self.assertLess(seen[-1]["read"],seen[0]["read"])
        ctx.finish()

    def test_bounded_retry_and_explicit_connect_read_timeout(self):
        from services.execution_control import ExecutionControl,bind_execution
        requests=[]
        def handler(req):
            requests.append(req)
            return httpx.Response(429,json={"error":{"message":"rate limited","type":"rate_limit"}})
        llm,_=self.llm(handler,model_max_retries=1)
        ctx=ExecutionControl(60,waiter=lambda seconds:None)
        with bind_execution(ctx):
            with self.assertRaises(Exception): llm.invoke([])
        self.assertEqual(len(requests),2)
        for req in requests:
            self.assertEqual(req.extensions["timeout"]["connect"],5)
            self.assertEqual(req.extensions["timeout"]["read"],20)
        ctx.finish()

    def test_partial_stream_is_not_retried(self):
        from services.execution_control import ExecutionControl,bind_execution
        requests=[]
        body=Body("error")
        def handler(req): requests.append(req);return httpx.Response(200,stream=body)
        llm,_=self.llm(handler,model_max_retries=3)
        ctx=ExecutionControl(60)
        with bind_execution(ctx):
            stream=llm.stream_invoke([])
            self.assertEqual(next(stream),"one")
            with self.assertRaises(httpx.ReadError):next(stream)
        self.assertEqual(len(requests),1);self.assertTrue(body.closed);ctx.finish()


    def test_real_framework_retaining_llm_iterator_closes_owned_sdk_response(self):
        from services.execution_control import ExecutionControl,bind_execution
        from hello_agents import ToolAwareSimpleAgent
        from services.summarizer import SummarizationService
        from models import SummaryState,TodoItem
        # Keep the generator strongly referenced: CPython GC is not a cleanup policy.
        retained=[]
        body=Body()
        # Long first chunk makes upstream emit before SDK completion.
        class LongBody(Body):
            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"abcdefghijklmnopqrstuvwxyz"}}]}\n\n'
                yield b'data: [DONE]\n\n'
        body=LongBody()
        llm,client=self.llm(lambda req:httpx.Response(200,stream=body))
        class Retaining:
            def __getattr__(self,name):return getattr(llm,name)
            def stream_invoke(self,*args,**kwargs):
                inner=llm.stream_invoke(*args,**kwargs);retained.append(inner);return inner
        upstream=ToolAwareSimpleAgent(name="fake",llm=Retaining(),system_prompt="x",enable_tool_calling=False)
        service=SummarizationService(lambda:upstream,Configuration(enable_notes=False))
        ctx=ExecutionControl(60)
        with bind_execution(ctx):
            stream,get=service.stream_task_summary(SummaryState(research_topic="x"),
                TodoItem(id=1,title="x",intent="x",query="q"),"ctx")
            self.assertTrue(next(stream))
            self.assertFalse(body.closed)
            stream.close()
        self.assertTrue(body.closed)
        self.assertFalse(client.is_closed())
        self.assertEqual(upstream._history,[])
        self.assertTrue(retained)
        for inner in retained:inner.close()
        ctx.finish()

    def test_shared_sdk_concurrent_outputs_and_contexts_do_not_mix(self):
        import json
        from concurrent.futures import ThreadPoolExecutor
        from services.execution_control import ExecutionControl,bind_execution
        def handler(req):
            message=json.loads(req.content)["messages"][0]["content"]
            return httpx.Response(200,json={"id":"x","object":"chat.completion","created":0,
                "model":"fake","choices":[{"index":0,"message":{"role":"assistant","content":message},
                                          "finish_reason":"stop"}]})
        llm,client=self.llm(handler)
        def invoke(i):
            ctx=ExecutionControl(60)
            try:
                with bind_execution(ctx):return llm.invoke([{"role":"user","content":str(i)}])
            finally:ctx.finish()
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(list(pool.map(invoke,range(16))),[str(i) for i in range(16)])
        self.assertFalse(client.is_closed())

    def test_existing_search_backend_override_and_fallback_unchanged(self):
        from services.search import dispatch_search
        import services.search as search
        from hello_agents.tools import SearchTool
        tool=SearchTool.__new__(SearchTool)
        tool.backend="hybrid";tool.tavily_client=object();tool.serpapi_key=None
        with patch.object(search,"_GLOBAL_SEARCH_TOOL",tool), \
             patch.object(tool,"_search_tavily",side_effect=RuntimeError("429 fake")), \
             patch.object(tool,"_search_duckduckgo",return_value={
                 "backend":"duckduckgo","results":[],"notices":[]}) as ddg:
            result,notices,answer,backend=dispatch_search("q",Configuration(search_api="duckduckgo"),3)
            self.assertEqual(ddg.call_count,1)
            self.assertEqual(backend,"duckduckgo")
            result,notices,answer,backend=dispatch_search("q",Configuration(search_api="advanced"),3)
        self.assertEqual(backend,"duckduckgo")
        self.assertIn("429 fake",notices[0])


    def test_blocked_sdk_stream_retains_execution_until_provider_releases(self):
        import json,threading
        from agent import DeepResearchAgent
        from hello_agents import HelloAgentsLLM
        from services.execution_control import ExecutionControl
        entered,release=threading.Event(),threading.Event()
        class BlockingBody(Body):
            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"abcdefghijklmnopqrstuvwxyz"}}]}\n\n'
                entered.set()
                if not release.wait(5):raise RuntimeError("test wait")
                yield b'data: [DONE]\n\n'
        body=BlockingBody()
        def handler(req):
            data=json.loads(req.content)
            if data.get("stream"):return httpx.Response(200,stream=body)
            return httpx.Response(200,json={"id":"x","object":"chat.completion","created":0,
                "model":"fake","choices":[{"index":0,"message":{"role":"assistant",
                "content":'{"tasks":[{"title":"t","query":"q"}]}'}, "finish_reason":"stop"}]})
        adapter,client=self.llm(handler)
        now=[0.]
        ctx=ExecutionControl(1,clock=lambda:now[0])
        with patch.object(DeepResearchAgent,"_init_llm",return_value=adapter._llm):
            a=DeepResearchAgent(Configuration(enable_notes=False))
        events=[]
        with patch("agent.dispatch_search",return_value=({"results":[{"url":"https://fake.invalid"}]},[],"","fake")), \
             patch("agent.prepare_research_context",return_value=("s","c")), \
             patch.object(a.reporting,"generate_report") as reporter:
            consumer=threading.Thread(target=lambda:events.extend(a.run_stream("x",execution=ctx)))
            consumer.start()
            try:
                self.assertTrue(entered.wait(2))
                now[0]=2.;consumer.join(2)
                self.assertFalse(consumer.is_alive())
                self.assertTrue(a._run_lock.locked())
                self.assertFalse(body.closed)
                self.assertFalse(client.is_closed())
                reporter.assert_not_called()
            finally:
                release.set();consumer.join(5)
                self.assertTrue(ctx.wait_idle(3))
        self.assertTrue(body.closed)
        self.assertFalse(client.is_closed())
        self.assertFalse(a._run_lock.locked())
        self.assertEqual(events[-1]["run_status"],"cancelled")
        self.assertEqual(a._active_state.todo_items[0].status,"cancelled")

if __name__=="__main__": unittest.main()
