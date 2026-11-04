"""In-memory tool journal, atomic IDs and acknowledged live/drain delivery."""
from dataclasses import asdict, dataclass
import logging
from pathlib import Path
from threading import Lock
from typing import Any
import uuid

from services.note_versions import NoteScope
from tools.project_note_tool import NoteToolResult

logger = logging.getLogger(__name__)


def note_state(ok, code, note_id):
    if ok:
        return "saved" if note_id else None
    return {"WRITES_PAUSED": "paused", "CONFLICT": "conflict",
            "VERSION_PARAM_MISMATCH": "conflict"}.get(code, "error")


@dataclass
class ToolCallEvent:
    id: int
    agent: str
    tool: str
    raw_parameters: str
    parsed_parameters: dict[str, Any]
    result: str
    task_id: int | None
    note_id: str | None
    run_id: str
    stage: str | None = None
    success: bool | None = None
    error_code: str | None = None
    detail: str | None = None
    note_etag: str | None = None
    note_status: str | None = None
    persisted: bool | str | None = None


class ToolCallTracker:
    def __init__(self, notes_workspace):
        self._notes_workspace = notes_workspace
        self._events = []
        self._cursor = 0
        self._lock = Lock()
        self._event_sink = None
        self._run_id = None
        self._delivered = set()
        self._inflight = set()

    def record(self, payload):
        params = payload.get("parsed_parameters") or {}
        if not isinstance(params, dict):
            params = {}
        outcome, scope = payload.get("note_result"), payload.get("trusted_scope")
        structured = isinstance(outcome, NoteToolResult) and isinstance(scope, NoteScope)
        task_id = note_id = success = code = detail = etag = status = persisted = stage = None
        if structured:
            result = outcome.status
            task_id = outcome.task_id if type(outcome.task_id) is int else scope.task_id
            success, code, detail, persisted = result.ok, result.error_code, result.detail, result.persisted
            note_id = result.note_id if success and params.get("action") != "delete" else None
            etag = result.etag if note_id else None
            status = note_state(success, code, note_id)
            if success and params.get("action") == "delete":
                status = "not_started"
            stage = {"task": "summarizer", "final_report": "reporter"}.get(scope.purpose, scope.purpose)
        elif payload.get("tool_name") == "note":
            code, detail, status = "UNVERIFIED_TOOL_RESULT", "旧工具未提供可验证的结构化结果", "error"

        # Legacy text may still be logged but cannot grant trusted bindings or
        # infer success from emoji/ID, title or tags.
        with self._lock:
            if self._run_id is None:
                self._run_id = scope.run_id if structured else uuid.uuid4().hex
            if structured and scope.run_id != self._run_id:
                raise ValueError("foreign run tool event")
            event = ToolCallEvent(
                id=len(self._events)+1, agent=str(payload.get("agent_name") or "unknown"),
                tool=str(payload.get("tool_name") or "unknown"),
                raw_parameters=str(payload.get("raw_parameters") or ""),
                parsed_parameters=dict(params), result=str(payload.get("result") or ""),
                task_id=task_id, note_id=note_id, run_id=self._run_id, stage=stage,
                success=success, error_code=code, detail=detail, note_etag=etag,
                note_status=status, persisted=persisted)
            self._events.append(event)
            sink = self._event_sink
            if sink is not None:
                self._inflight.add(event.id)
        if sink is not None:
            try:
                sink(self._build_payload(event))
            except Exception:
                logger.warning("Tool sink failed; event retained for drain", exc_info=True)
                self.release(event.id)
            else:
                self.ack(event.id)

    def ack(self, event_id):
        with self._lock:
            self._inflight.discard(event_id)
            self._delivered.add(event_id)

    def release(self, event_id):
        with self._lock:
            self._inflight.discard(event_id)

    def drain(self, state, *, step=None, acknowledge=True):
        with self._lock:
            for event in self._events[self._cursor:]:
                self._apply(state, event)
            self._cursor = len(self._events)
            pending = [e for e in self._events if e.id not in self._delivered
                       and e.id not in self._inflight]
            if acknowledge:
                self._delivered.update(e.id for e in pending)
            else:
                self._inflight.update(e.id for e in pending)
            return [self._build_payload(e, step) for e in pending]

    def _apply(self, state, event):
        # A single locked attribution cursor, independent of delivery/replay.
        if getattr(state, "run_id", None) not in (None, event.run_id):
            return
        if event.success is False or event.error_code:
            warning = f"{event.stage or event.agent}: {event.error_code}: {event.detail or ''}"
            if warning not in state.warnings:
                state.warnings.append(warning)
        for task in state.todo_items:
            if task.id != event.task_id:
                continue
            action = event.parsed_parameters.get("action")
            if event.note_id:
                task.note_id = event.note_id
                task.note_path = str(Path(self._notes_workspace) / (event.note_id+".md")) if self._notes_workspace else None
                task.note_etag = event.note_etag
            if action == "delete" and (event.success or event.persisted == "unknown"):
                task.note_id = task.note_path = task.note_etag = None
            if event.note_status:
                failed_before = task.note_status in ("error", "paused", "conflict")
                if not (event.note_status == "saved" and failed_before and event.persisted is not True):
                    task.note_status = event.note_status
                    task.note_error = ({"code": event.error_code, "detail": event.detail,
                                        "persisted": event.persisted} if event.success is False else None)
            if event.success is False:
                text = f"笔记 {event.error_code}: {event.detail or ''}"
                if text not in task.notices:
                    task.notices.append(text)
            break

    def reset(self, run_id=None):
        with self._lock:
            if self._inflight:
                raise RuntimeError("cannot reset while a producer/delivery is active")
            self._events.clear()
            self._cursor = 0
            self._delivered.clear()
            self._run_id = run_id
            self._event_sink = None

    def as_dicts(self):
        with self._lock:
            return [asdict(e) for e in self._events]

    def set_event_sink(self, sink):
        with self._lock:
            self._event_sink = sink

    def _build_payload(self, event, step=None):
        payload = {
            "type": "tool_call", "event_id": event.id, "agent": event.agent,
            "tool": event.tool, "parameters": event.parsed_parameters,
            "result": event.result, "task_id": event.task_id, "note_id": event.note_id,
            "run_id": event.run_id, "stage": event.stage, "success": event.success,
            "error_code": event.error_code, "detail": event.detail,
            "note_etag": event.note_etag, "note_status": event.note_status,
            "persisted": event.persisted}
        if event.note_id and self._notes_workspace:
            payload["note_path"] = str(Path(self._notes_workspace) / (event.note_id+".md"))
        if step is not None:
            payload["step"] = step
        return payload
