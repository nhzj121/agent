"""Serialize one research's note operations without changing the installed SDK."""

import re
from threading import Lock

from hello_agents.tools.builtin.note_tool import NoteTool
from services.runtime import ResearchRuntime, cancellable_slot


class ResearchNoteTool(NoteTool):
    def __init__(self, *, workspace: str, runtime: ResearchRuntime):
        self._runtime = runtime
        self._operation_lock = Lock()
        super().__init__(workspace=workspace)

    def run(self, parameters):
        # Lock reads as well: the SDK updates its index and Markdown separately.
        with cancellable_slot(self._operation_lock, self._runtime):
            return super().run(parameters)

    def _get_note_path(self, note_id):
        # A model-supplied ID must never escape this research's directory.
        if not isinstance(note_id, str) or not re.fullmatch(r"note_[A-Za-z0-9_-]+", note_id):
            raise ValueError("笔记 ID 无效，不允许跨研究目录访问")
        return super()._get_note_path(note_id)
