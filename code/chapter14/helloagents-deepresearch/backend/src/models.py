"""State models used by the deep research workflow."""

import operator
from dataclasses import dataclass, field
from typing import List, Optional

from typing_extensions import Annotated


@dataclass(kw_only=True)
class TodoItem:
    """单个待办任务项。"""

    id: int
    title: str
    intent: str
    query: str
    status: str = field(default="pending")
    summary: Optional[str] = field(default=None)
    sources_summary: Optional[str] = field(default=None)
    notices: list[str] = field(default_factory=list)
    note_id: Optional[str] = field(default=None)
    note_path: Optional[str] = field(default=None)
    stream_token: Optional[str] = field(default=None)
    error_code: Optional[str] = None
    detail: Optional[str] = None
    note_status: str = "not_started"
    note_error: Optional[dict] = None
    note_etag: Optional[str] = None


@dataclass(kw_only=True)
class SummaryState:
    run_id: Optional[str] = None
    run_status: str = "running"
    warnings: list[str] = field(default_factory=list)
    report_note_status: str = "not_started"
    report_note_error: Optional[dict] = None
    research_topic: str = field(default=None)  # Report topic
    search_query: str = field(default=None)  # Deprecated placeholder
    web_research_results: Annotated[list, operator.add] = field(default_factory=list)
    sources_gathered: Annotated[list, operator.add] = field(default_factory=list)
    research_loop_count: int = field(default=0)  # Research loop count
    running_summary: str = field(default=None)  # Legacy summary field
    todo_items: Annotated[list, operator.add] = field(default_factory=list)
    structured_report: Optional[str] = field(default=None)
    report_note_id: Optional[str] = field(default=None)
    report_note_path: Optional[str] = field(default=None)


@dataclass(kw_only=True)
class SummaryStateInput:
    run_id: Optional[str] = None
    run_status: str = "running"
    warnings: list[str] = field(default_factory=list)
    report_note_status: str = "not_started"
    report_note_error: Optional[dict] = None
    research_topic: str = field(default=None)  # Report topic


@dataclass(kw_only=True)
class SummaryStateOutput:
    running_summary: str = field(default=None)  # Backward-compatible文本
    report_markdown: Optional[str] = field(default=None)
    todo_items: List[TodoItem] = field(default_factory=list)
    run_id: Optional[str] = None
    run_status: str = "completed"
    warnings: list[str] = field(default_factory=list)
    report_note_id: Optional[str] = None
    report_note_path: Optional[str] = None
    report_note_status: str = "not_started"
    report_note_error: Optional[dict] = None

