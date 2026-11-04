"""Composition only: delegate exactly once to unmodified ToolAwareSimpleAgent."""
import logging
import sys

from hello_agents import ToolAwareSimpleAgent
from hello_agents.tools import ToolRegistry
from services.note_versions import VersionLedger
from services.execution_control import checkpoint, close_thread_streams
from tools.controlled_tool import ControlledTool
from tools.project_note_tool import ProjectNoteTool, NoteToolResult
from storage.note_repository import NoteWriteResult

logger = logging.getLogger(__name__)


class LocalLLMView:
    def __init__(self, llm, ledger):
        self._llm, self.ledger = llm, ledger

    def __getattr__(self, name):
        return getattr(self._llm, name)

    def invoke(self, messages, **kwargs):
        checkpoint()
        self.ledger.freeze(messages)
        return self._llm.invoke(messages, **kwargs)

    def stream_invoke(self, messages, **kwargs):
        checkpoint()
        self.ledger.freeze(messages)
        # Keep the frozen basis after normal stream exhaustion: tools run later.
        inner = self._llm.stream_invoke(messages, **kwargs)
        try:
            yield from inner
        finally:
            close = getattr(inner, "close", None)
            if close is not None:
                close()


class ProjectToolAwareAgent:
    def __init__(self, *, llm, repository, ownership, scope, name, system_prompt,
                 tool_call_listener=None):
        self.ledger = VersionLedger(scope)
        self.note_tool = ProjectNoteTool(repository, ownership, scope, self.ledger)
        registry = ToolRegistry()
        registry.register_tool(ControlledTool(self.note_tool), auto_expand=False)
        self.results = []
        self.generated_text = None

        def listener(event):
            outcome = self.note_tool.last_result
            self.note_tool.last_result = None
            if outcome is None or event.get("result") != "🔧 工具 note 执行结果：\n" + outcome.text:
                outcome = NoteToolResult(NoteWriteResult(False, False, error_code="FORMAT_ERROR"), "❌ FORMAT_ERROR")
            self.results.append(outcome)
            if tool_call_listener is None:
                return
            # Project-owned projection protects the old Tracker without changing
            # its implementation or introducing new SSE fields (G3 remains).
            status = outcome.status
            params = {"action": event["parsed_parameters"].get("action")}
            if outcome.task_id is not None:
                params["task_id"] = outcome.task_id
            text = "❌ " + str(status.error_code)
            if status.ok:
                text = outcome.text
                if params["action"] != "delete" and status.note_id:
                    params["note_id"] = status.note_id
            tool_call_listener({**event, "parsed_parameters": params, "result": text,
                                "note_result": outcome, "trusted_scope": scope})

        self.upstream = ToolAwareSimpleAgent(
            name=name, llm=LocalLLMView(llm, self.ledger), system_prompt=system_prompt,
            tool_registry=registry, enable_tool_calling=True, tool_call_listener=listener)

    def __getattr__(self, name):
        return getattr(self.upstream, name)

    def run(self, input_text, *args, **kwargs):
        self.ledger.start()
        self.generated_text = None
        self.results = []
        try:
            text = self.upstream.run(input_text, *args, **kwargs)
            self.generated_text = self.ledger.generated(text)
            return text
        finally:
            self.ledger.finish()

    def stream_run(self, input_text, *args, **kwargs):
        self.ledger.start()
        self.generated_text = None
        self.results = []
        inner = None
        output = []
        try:
            inner = self.upstream.stream_run(input_text, *args, **kwargs)
            for chunk in inner:
                output.append(chunk)
                yield chunk
            self.generated_text = self.ledger.generated("".join(output))
        finally:
            active_error = sys.exc_info()[0] is not None
            try:
                close = getattr(inner, "close", None)
                if close:
                    close()
            except Exception:
                if not active_error:
                    raise
                logger.warning("Upstream close failed", exc_info=True)
            finally:
                try:
                    close_thread_streams()
                finally:
                    self.ledger.finish()
