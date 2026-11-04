"""Pre-implementation extension-point gate: real HelloAgents, Fake LLM, temporary files."""
from concurrent.futures import ThreadPoolExecutor
import copy
import importlib.metadata
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "code/chapter14/helloagents-deepresearch/backend/src"
sys.path.insert(0, str(SRC))
from hello_agents import ToolAwareSimpleAgent
from hello_agents.tools import ToolRegistry
from storage.file_notes import FileNoteRepository
from storage.note_repository import NoteError

def call(action, note_id, **kw):
    return "[TOOL_CALL:note:" + json.dumps(
        {"action": action, "note_id": note_id, **kw}, ensure_ascii=False) + "]"

class Probe:
    """Experimental tool + LLM view; no inheritance/patching of Agent loops."""
    name, description, expandable = "note", "gate probe", False

    def __init__(self, repo, scripted):
        self.repo, self.scripted = repo, scripted
        self.pending, self.frozen, self.trace, self.messages = [], {}, [], []
        self.receipts = {}

    def get_parameters(self):
        return []

    def run(self, params):
        self.trace.append("tool:" + params["action"])
        if params["action"] == "read":
            n = self.repo.read(params["note_id"])
            token = uuid.uuid4().hex
            text = json.dumps({"id": n.id, "etag": n.etag, "content": n.content,
                               "receipt": token})
            self.receipts[token] = (n.id, n.etag)
            self.pending.append(("🔧 工具 note 执行结果：\n"+text, token))
            return text
        expected = self.frozen.get(params["note_id"])
        if expected is None:
            return "READ_REQUIRED"
        try:
            self.repo.update(params["note_id"], {"content": params["content"]}, expected)
        except NoteError as exc:
            return exc.code
        return "ok"

    def freeze(self, messages):
        self.trace.append("generation")
        self.messages.append(copy.deepcopy(messages))
        # Only a full authentic framework-generated user result message counts.
        content = messages[-1]["content"]
        for text, receipt in self.pending:
            if (messages[-1]["role"] == "user" and
                content.startswith("工具执行结果：\n") and text in content):
                note_id, etag = self.receipts[receipt]
                self.frozen[note_id] = etag
        self.pending.clear()

    def invoke(self, messages, **kwargs):
        self.freeze(messages)
        return self.scripted(len(self.messages)-1, self)

    def stream_invoke(self, messages, **kwargs):
        text = self.invoke(messages, **kwargs)
        # The real upstream parser must handle split tool markers.
        for i in range(0, len(text), 7):
            yield text[i:i+7]

    def agent(self, listener=None):
        registry = ToolRegistry()
        registry.register_tool(self)
        return ToolAwareSimpleAgent(name="probe", llm=self, tool_registry=registry,
                                    enable_tool_calling=True, tool_call_listener=listener)

class ExtensionGateTests(unittest.TestCase):
    def test_01_framework_version_and_delivery_freeze_order(self):
        self.assertEqual(importlib.metadata.version("hello-agents"), "0.2.9")
        for streaming in (False, True):
            with self.subTest(streaming=streaming), tempfile.TemporaryDirectory() as ws, \
                    FileNoteRepository(ws) as repo:
                n = repo.create({"title": "t", "content": "v1"})
                listener = []
                def scripted(i, p):
                    if i == 0:
                        return call("read", n.id)
                    if i == 1:
                        self.assertEqual(p.frozen[n.id], n.etag)
                        self.assertIn('"content": "v1"', p.messages[-1][-1]["content"])
                        return call("update", n.id, content="v2")
                    return "done"
                p = Probe(repo, scripted)
                agent = p.agent(listener.append)
                output = "".join(agent.stream_run("topic")) if streaming else agent.run("topic")
                self.assertEqual(output, "done")
                self.assertEqual(repo.read(n.id).content, "v2")
                self.assertEqual(p.trace, ["generation", "tool:read", "generation",
                                           "tool:update", "generation"])
                self.assertEqual([e["parsed_parameters"]["action"] for e in listener],
                                 ["read", "update"])

    def test_02_same_answer_read_update_uses_only_previous_generation(self):
        for streaming in (False, True):
            for previous in (False, True):
                with self.subTest(streaming=streaming, previous=previous), \
                        tempfile.TemporaryDirectory() as ws, FileNoteRepository(ws) as repo:
                    n = repo.create({"title": "t", "content": "v1"})
                    events = []
                    def scripted(i, p):
                        if previous and i == 0:
                            return call("read", n.id)
                        if i == int(previous):
                            if previous:
                                repo.update(n.id, {"content": "external-v2"}, n.etag)
                            return call("read", n.id) + call("update", n.id, content="stale")
                        return "done"
                    p = Probe(repo, scripted)
                    agent = p.agent(events.append)
                    if streaming:
                        list(agent.stream_run("topic"))
                    else:
                        agent.run("topic")
                    update = next(e for e in events if e["parsed_parameters"]["action"] == "update")
                    self.assertIn("CONFLICT" if previous else "READ_REQUIRED", update["result"])
                    self.assertEqual(repo.read(n.id).content, "external-v2" if previous else "v1")

    def test_03_distinct_agents_do_not_share_credentials(self):
        with tempfile.TemporaryDirectory() as ws, FileNoteRepository(ws) as repo:
            notes = [repo.create({"title": "t", "content": "v1"}) for _ in range(2)]
            def work(index):
                n = notes[index]
                def scripted(i, p):
                    if i == 0:
                        return call("read", n.id)
                    if i == 1:
                        self.assertEqual(set(p.frozen), {n.id})
                        return call("update", n.id, content=str(index))
                    return "done"
                p = Probe(repo, scripted)
                p.agent().run("topic")
                return p
            with ThreadPoolExecutor(2) as pool:
                probes = list(pool.map(work, range(2)))
            self.assertTrue(set(probes[0].receipts).isdisjoint(probes[1].receipts))
            self.assertEqual([repo.read(n.id).content for n in notes], ["0", "1"])

if __name__ == "__main__":
    unittest.main()
