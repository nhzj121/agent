"""Orchestrator coordinating the deep research workflow."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from queue import Empty, Queue
from threading import Lock, Thread
from typing import Any, Callable, Iterator

from hello_agents import HelloAgentsLLM, ToolAwareSimpleAgent
from hello_agents.tools import ToolRegistry
from hello_agents.tools.builtin.note_tool import NoteTool

from config import Configuration
from prompts import (
    report_writer_instructions,
    task_summarizer_instructions,
    todo_planner_system_prompt,
)
from models import SummaryState, SummaryStateOutput, TodoItem
from services.execution_control import (
    ExecutionControl, ExecutionStopped, bind_execution, checkpoint,
    close_thread_streams, tool_boundary)
from llm.project_llm import ProjectLLM
from tools.controlled_tool import ControlledTool
from services.search_runtime import run_search
from services.planner import PlanningService
from services.agent_adapter import ProjectToolAwareAgent
from services.note_ownership import NoteOwnership
from services.note_versions import NoteScope
from storage.note_repository import NoteError, NoteWriteResult
from services.reporter import ReportingService
from services.search import dispatch_search, prepare_research_context
from services.summarizer import SummarizationService
from services.tool_events import ToolCallTracker

logger = logging.getLogger(__name__)


class DeepResearchAgent:
    """Coordinator orchestrating TODO-based research workflow using HelloAgents."""

    def __init__(self, config: Configuration | None = None, *, note_repository=None) -> None:
        """Initialise the coordinator with configuration and shared tools."""
        self.config = config or Configuration.from_env()
        self._note_repository = note_repository
        self._note_owner = None
        self.last_note_result = None
        if self.config.enable_notes and note_repository is None:
            raise ValueError("notes require the configured files_v2 service factory or an explicit Repository; "
                             "set ENABLE_NOTES=false for no-note mode")
        self.llm = ProjectLLM(self._init_llm(), self.config)

        self.note_tool = None
        self.tools_registry: ToolRegistry | None = None

        self._tool_tracker = ToolCallTracker(
            (str(note_repository.workspace) if note_repository is not None else self.config.notes_workspace)
            if self.config.enable_notes else None
        )
        self._tool_event_sink_enabled = False
        self._state_lock = Lock()
        self._run_lock = Lock()
        self.run_id = None
        self.run_status = "running"

        self.todo_agent = self._create_tool_aware_agent(
            name="研究规划专家",
            system_prompt=todo_planner_system_prompt.strip(),
        )
        self.report_agent = self._create_tool_aware_agent(
            name="报告撰写专家",
            system_prompt=report_writer_instructions.strip(),
        )

        self._summarizer_factory: Callable[[], ToolAwareSimpleAgent] = lambda: self._create_tool_aware_agent(  # noqa: E501
            name="任务总结专家",
            system_prompt=task_summarizer_instructions.strip(),
        )

        self.planner = PlanningService(self.todo_agent, self.config)
        self.summarizer = SummarizationService(
            self._summarizer_factory, self.config,
            task_agent_factory=self._create_task_note_agent if note_repository is not None else None)
        self.reporting = ReportingService(self.report_agent, self.config)
        self._last_search_notices: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def _init_llm(self) -> HelloAgentsLLM:
        """Instantiate HelloAgentsLLM following configuration preferences."""
        llm_kwargs: dict[str, Any] = {"temperature": 0.0}

        model_id = self.config.llm_model_id or self.config.local_llm
        if model_id:
            llm_kwargs["model"] = model_id

        provider = (self.config.llm_provider or "").strip()
        if provider:
            llm_kwargs["provider"] = provider

        if provider == "ollama":
            llm_kwargs["base_url"] = self.config.sanitized_ollama_url()
            if self.config.llm_api_key:
                llm_kwargs["api_key"] = self.config.llm_api_key
            else:
                llm_kwargs["api_key"] = "ollama"
        elif provider == "lmstudio":
            llm_kwargs["base_url"] = self.config.lmstudio_base_url
            if self.config.llm_api_key:
                llm_kwargs["api_key"] = self.config.llm_api_key
        else:
            if self.config.llm_base_url:
                llm_kwargs["base_url"] = self.config.llm_base_url
            if self.config.llm_api_key:
                llm_kwargs["api_key"] = self.config.llm_api_key

        return HelloAgentsLLM(**llm_kwargs)

    def _create_tool_aware_agent(self, *, name: str, system_prompt: str) -> ToolAwareSimpleAgent:
        """Instantiate a ToolAwareSimpleAgent sharing tool registry and tracker."""
        return ToolAwareSimpleAgent(
            name=name,
            llm=self.llm,
            system_prompt=system_prompt,
            enable_tool_calling=self.tools_registry is not None,
            tool_registry=self.tools_registry,
            tool_call_listener=self._tool_tracker.record,
        )

    def _set_tool_event_sink(self, sink: Callable[[dict[str, Any]], None] | None) -> None:
        """Enable or disable immediate tool event callbacks."""
        self._tool_event_sink_enabled = sink is not None
        self._tool_tracker.set_event_sink(sink)

    def _begin_notes_run(self) -> None:
        # The service factory injects an activated Repository. Programmatic
        # callers may still explicitly inject a temporary/test Repository.
        if getattr(self, "_note_repository", None) is None:
            return
        self._note_owner = None
        if not self.config.enable_notes:
            self.todo_agent = self._create_tool_aware_agent(
                name="研究规划专家", system_prompt=todo_planner_system_prompt.strip())
            self.report_agent = self._create_tool_aware_agent(
                name="报告撰写专家", system_prompt=report_writer_instructions.strip())
            self.planner = PlanningService(self.todo_agent, self.config)
            self.reporting = ReportingService(self.report_agent, self.config)
            return
        self._note_owner = NoteOwnership(self._note_repository, self.run_id)
        self.last_note_result = None
        self.todo_agent = self._project_agent("研究规划专家", todo_planner_system_prompt, "planner")
        self.report_agent = self._project_agent("报告撰写专家", report_writer_instructions, "final_report")
        self.planner = PlanningService(self.todo_agent, self.config)
        self.reporting = ReportingService(self.report_agent, self.config)

    def _project_agent(self, name, prompt, purpose, task_id=None):
        return ProjectToolAwareAgent(
            name=name, system_prompt=prompt.strip(), llm=self.llm,
            repository=self._note_repository, ownership=self._note_owner,
            scope=NoteScope(self._note_owner.run_id, purpose, task_id),
            tool_call_listener=self._tool_tracker.record)

    def _create_task_note_agent(self, task):
        if self._note_owner is None:
            return self._summarizer_factory()
        return self._project_agent("任务总结专家", task_summarizer_instructions, "task", task.id)

    def _attach_verified_notes(self, state):
        owner = getattr(self, "_note_owner", None)
        if owner is None or owner.run_id != state.run_id:
            return
        for task in state.todo_items:
            binding = owner.binding(task.id)
            if binding is not None:
                task.note_id, task.note_path = binding.note_id, binding.note_path

    def _enter_run(self, streaming=False, execution=None):
        if not hasattr(self, "_run_lock"):
            self._run_lock = Lock()
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("research already running on this Agent")
        control = execution or ExecutionControl(self.config.research_deadline_seconds)
        self.execution = control
        control.on_idle(self._run_lock.release)
        self.run_id = control.id
        self.run_status = "running"
        self._streaming = streaming
        self._active_state = None
        self._terminal_published = set()
        self.last_note_result = None
        try:
            reset = getattr(self._tool_tracker, "reset", None)
            if reset:
                reset(run_id=self.run_id)
        except Exception:
            control.finish()
            raise

    def _cancel_state(self, exc):
        state = self._active_state
        self.run_status = "cancelled"
        if state is None:
            state = SummaryState(run_id=self.run_id, run_status="cancelled")
            self._active_state = state
        state.run_status = "cancelled"
        warning = f"{exc.code}: {exc.detail}"
        if warning not in state.warnings:
            state.warnings.append(warning)
        events = []
        with self.execution.lock:
            for task in state.todo_items:
                if task.status in ("pending", "in_progress"):
                    task.status = "cancelled"
                    task.error_code, task.detail = exc.code, exc.detail
                if task.status == "cancelled" and task.id not in self._terminal_published:
                    events.append({"type":"task_status", "task_id":task.id,
                                   "status":"cancelled", "detail":task.detail,
                                   "error_code":task.error_code})
        return events

    def cancellation_snapshot(self, execution):
        """Freeze transport terminal state under the existing commit/cancel lock."""
        with execution.lock:
            if getattr(self, "execution", None) is not execution:
                return [{"type":"done", "run_id":execution.id, "run_status":"cancelled",
                         "warnings":[f"{execution.code}: {execution.detail}"]}]
            self._cancel_state(ExecutionStopped(execution.code, execution.detail))
            # Include all known task terminal states, even when their queued
            # events were not delivered before transport cancellation.
            return [
                self._enrich_event({"type":"task_status", "task_id":task.id,
                                    "run_status":"cancelled", **self._serialize_task(task)})
                for task in self._active_state.todo_items
            ] + [self._enrich_event({"type":"done"})]

    def _fatal_state(self, exc):
        if self.execution.cancel_event.is_set():
            self._cancel_state(ExecutionStopped(self.execution.code, self.execution.detail))
            return
        self.run_status = "failed"
        state = self._active_state
        if state is not None:
            state.run_status = "failed"
            state.warnings.append(str(exc))
            with self.execution.lock:
                for task in state.todo_items:
                    if task.status in ("pending", "in_progress"):
                        self._fail_task(task, exc)
                self.execution.cancel(str(exc), code="RESEARCH_EXECUTION_FAILED")

    def _output(self, state):
        return SummaryStateOutput(
            running_summary=state.running_summary or "",
            report_markdown=state.structured_report or "",
            todo_items=state.todo_items, run_id=state.run_id, run_status=state.run_status,
            warnings=list(state.warnings), report_note_id=state.report_note_id,
            report_note_path=state.report_note_path, report_note_status=state.report_note_status,
            report_note_error=state.report_note_error)

    def run(self, topic: str, *, execution=None) -> SummaryStateOutput:
        self._enter_run(execution=execution)
        with bind_execution(self.execution):
            try:
                return self._run(topic)
            except ExecutionStopped as exc:
                self._cancel_state(exc)
                return self._output(self._active_state or SummaryState(
                    research_topic=topic, run_id=self.run_id, run_status="cancelled"))
            except Exception as exc:
                self._fatal_state(exc)
                raise
            finally:
                try:
                    close_thread_streams()
                finally:
                    self.execution.finish()

    def run_stream(self, topic: str, *, execution=None) -> Iterator[dict[str, Any]]:
        self._enter_run(streaming=True, execution=execution)
        inner = self._run_stream(topic)
        terminal_yielded = False
        # Bind around next/close, never across yield: ASGI can resume a sync
        # iterator in a different thread/context on its next invocation.
        try:
            while True:
                try:
                    with bind_execution(self.execution):
                        event = next(inner)
                except StopIteration:
                    break
                event = self._enrich_event(event)
                if event["type"] == "tool_call":
                    ack = getattr(self._tool_tracker, "ack", None)
                    if ack:
                        ack(event["event_id"])
                terminal_yielded = event.get("type") in ("done", "error")
                yield event
        except GeneratorExit:
            if not terminal_yielded:
                self.execution.cancel("research iterator closed")
                self._cancel_state(ExecutionStopped(self.execution.code or "CANCELLED",
                                                  self.execution.detail or "execution cancelled"))
            raise
        except ExecutionStopped as exc:
            for event in self._cancel_state(exc):
                yield self._enrich_event(event)
            yield self._enrich_event({"type":"done"})
        except Exception as exc:
            self._fatal_state(exc)
            raise
        finally:
            with bind_execution(self.execution):
                try:
                    inner.close()
                    close_thread_streams()
                finally:
                    self.execution.finish()

    def _validate_plan(self, state):
        checkpoint()
        if len(state.todo_items) > self.config.max_planned_tasks:
            exc = ValueError(f"MAX_PLANNED_TASKS exceeded: {len(state.todo_items)} > {self.config.max_planned_tasks}")
            for task in state.todo_items:
                self._fail_task(task, exc, "PLAN_LIMIT_EXCEEDED")
            raise exc

    def _initialize_tasks(self, state):
        for task in state.todo_items:
            if not self.config.enable_notes:
                task.note_status = "disabled"

    def _fail_task(self, task, exc, code="TASK_EXECUTION_FAILED"):
        with self.execution.lock:
            if task.status not in ("pending", "in_progress"):
                return
            if self.execution.cancel_event.is_set():
                task.status = "cancelled"
                task.error_code, task.detail = self.execution.code, self.execution.detail
            else:
                task.status = "failed"
                task.error_code, task.detail = code, str(exc)

    def _finish_status(self, state):
        completed = sum(t.status == "completed" for t in state.todo_items)
        state.run_status = ("completed" if completed == len(state.todo_items) and completed
                            else "partial" if completed else "failed")
        self.run_status = state.run_status
        for task in state.todo_items:
            if task.status == "failed":
                warning = f"任务 {task.id}: {task.error_code}: {task.detail}"
                if warning not in state.warnings:
                    state.warnings.append(warning)

    def _enrich_event(self, event):
        state = self._active_state
        payload = dict(event)
        if payload.get("type") == "task_status" and payload.get("status") in (
                "completed", "skipped", "failed", "cancelled"):
            self._terminal_published.add(payload.get("task_id"))
        payload.setdefault("run_id", self.run_id)
        payload.setdefault("run_status", self.run_status if payload.get("type") in ("final_report", "done") else "running")
        if state is not None:
            if payload.get("type") == "task_status":
                task = next((t for t in state.todo_items if t.id == payload.get("task_id")), None)
                if task:
                    payload = {**self._serialize_task(task), **payload}
            if payload.get("type") in ("final_report", "done"):
                payload.update(warnings=list(state.warnings),
                               report_note_status=state.report_note_status,
                               report_note_error=state.report_note_error)
            if payload.get("type") == "final_report":
                payload["tasks"] = [self._serialize_task(t) for t in state.todo_items]
        return payload

    def _run(self, topic: str) -> SummaryStateOutput:
        """Execute the research workflow and return the final report."""
        checkpoint()
        self._begin_notes_run()
        state = SummaryState(research_topic=topic, run_id=self.run_id)
        self._active_state = state
        checkpoint()
        state.todo_items = self.planner.plan_todo_list(state)
        self._validate_plan(state)
        self._drain_tool_events(state)

        if not state.todo_items:
            logger.info("No TODO items generated; falling back to single task")
            state.todo_items = [self.planner.create_fallback_task(state)]

        self._initialize_tasks(state)
        for task in state.todo_items:
            try:
                for _ in self._execute_task(state, task, emit_stream=False):
                    pass
            except ExecutionStopped:
                raise
            except Exception as exc:
                self._fail_task(task, exc)
                self._drain_tool_events(state)

        self._attach_verified_notes(state)
        self._finish_status(state)
        checkpoint()
        report = self.reporting.generate_report(state)
        checkpoint()
        self._drain_tool_events(state)
        state.structured_report = report
        state.running_summary = report
        self._persist_final_report(state, report)

        return SummaryStateOutput(
            running_summary=report,
            report_markdown=report,
            todo_items=state.todo_items, run_id=state.run_id, run_status=state.run_status,
            warnings=list(state.warnings), report_note_id=state.report_note_id,
            report_note_path=state.report_note_path, report_note_status=state.report_note_status,
            report_note_error=state.report_note_error,
        )

    def _run_stream(self, topic: str) -> Iterator[dict[str, Any]]:
        """Execute the workflow yielding incremental progress events."""
        checkpoint()
        self._begin_notes_run()
        state = SummaryState(research_topic=topic, run_id=self.run_id)
        self._active_state = state
        logger.debug("Starting streaming research: topic=%s", topic)
        yield {"type": "status", "message": "初始化研究流程"}

        checkpoint()
        state.todo_items = self.planner.plan_todo_list(state)
        self._validate_plan(state)
        for event in self._drain_tool_events(state, step=0):
            yield event
        if not state.todo_items:
            state.todo_items = [self.planner.create_fallback_task(state)]

        self._initialize_tasks(state)
        channel_map: dict[int, dict[str, Any]] = {}
        for index, task in enumerate(state.todo_items, start=1):
            token = f"task_{task.id}"
            task.stream_token = token
            channel_map[task.id] = {"step": index, "token": token}

        yield {
            "type": "todo_list",
            "tasks": [self._serialize_task(t) for t in state.todo_items],
            "step": 0,
        }

        event_queue: Queue[dict[str, Any]] = Queue()

        def enqueue(
            event: dict[str, Any],
            *,
            task: TodoItem | None = None,
            step_override: int | None = None,
        ) -> None:
            payload = dict(event)
            target_task_id = payload.get("task_id")
            if task is not None and payload.get("type") != "tool_call":
                target_task_id = task.id
                payload["task_id"] = task.id

            channel = channel_map.get(target_task_id) if target_task_id is not None else None
            if channel:
                payload.setdefault("step", channel["step"])
                payload["stream_token"] = channel["token"]
            if step_override is not None:
                payload["step"] = step_override
            try:
                event_queue.put(payload)
            except Exception:
                if payload.get("type") == "tool_call":
                    self._tool_tracker.release(payload["event_id"])
                raise
            if payload.get("type") == "tool_call":
                ack = getattr(self._tool_tracker, "ack", None)
                if ack:
                    ack(payload["event_id"])

        def tool_event_sink(event: dict[str, Any]) -> None:
            enqueue(event)

        self._set_tool_event_sink(tool_event_sink)

        threads: dict[int, Thread] = {}
        next_task = 0

        def worker(task: TodoItem, step: int) -> None:
            with bind_execution(self.execution):
                try:
                    checkpoint()
                    with tool_boundary():
                        if task.status != "pending":
                            return
                        task.status = "in_progress"
                    enqueue({"type":"task_status", "status":"in_progress"}, task=task)
                    for event in self._execute_task(state, task, emit_stream=True, step=step):
                        enqueue(event, task=task)
                except ExecutionStopped as exc:
                    with self.execution.lock:
                        if task.status in ("pending", "in_progress"):
                            task.status = "cancelled"
                            task.error_code, task.detail = exc.code, exc.detail
                            enqueue({"type":"task_status", "status":"cancelled",
                                     "error_code":exc.code, "detail":exc.detail}, task=task)
                except Exception as exc:
                    self._fail_task(task, exc)
                    for pending in self._drain_tool_events(state, step=step):
                        enqueue(pending)
                    logger.exception("Task execution failed")
                    enqueue({"type":"task_status", "status":task.status,
                             "detail":task.detail, "error_code":task.error_code}, task=task)
                finally:
                    try:
                        close_thread_streams()
                    finally:
                        try:
                            enqueue({"type":"__task_done__", "task_id":task.id})
                        finally:
                            self.execution.release()

        def fill_slots():
            nonlocal next_task
            while next_task < len(state.todo_items) and len(threads) < self.config.max_task_workers:
                checkpoint()
                task = state.todo_items[next_task]
                next_task += 1
                step = channel_map[task.id]["step"]
                thread = Thread(target=worker, args=(task, step), daemon=True)
                self.execution.retain()
                try:
                    thread.start()
                except Exception as exc:
                    self.execution.release()
                    self._fail_task(task, exc, "WORKER_START_FAILED")
                    enqueue({"type":"task_status", "status":task.status, "detail":task.detail,
                             "error_code":task.error_code}, task=task)
                else:
                    threads[task.id] = thread

        # Last actual producer retains execution ownership after the consumer
        # exits. No join of a blocked provider on close/deadline.
        self.execution.on_idle(lambda: self._set_tool_event_sink(None))
        try:
            fill_slots()
            while threads:
                checkpoint()
                try:
                    event = event_queue.get(timeout=min(.05, self.execution.remaining()))
                except Empty:
                    continue
                if event.get("type") == "__task_done__":
                    thread = threads.pop(event["task_id"])
                    thread.join()  # target has completed its synchronous work
                    fill_slots()
                    continue
                # Never publish a queued in_progress/completed after cancellation.
                checkpoint()
                yield event

            while True:
                checkpoint()
                try:
                    event = event_queue.get_nowait()
                except Empty:
                    break
                if event.get("type") != "__task_done__":
                    yield event
        finally:
            if not threads:
                self._set_tool_event_sink(None)

        self._attach_verified_notes(state)
        self._finish_status(state)
        checkpoint()
        report = self.reporting.generate_report(state)
        checkpoint()
        final_step = len(state.todo_items) + 1
        for event in self._drain_tool_events(state, step=final_step):
            yield event
        state.structured_report = report
        state.running_summary = report

        note_event = self._persist_final_report(state, report)
        if note_event:
            yield note_event

        yield {
            "type": "final_report",
            "report": report,
            "note_id": state.report_note_id,
            "note_path": state.report_note_path,
        }
        yield {"type": "done"}

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------
    def _execute_task(
        self,
        state: SummaryState,
        task: TodoItem,
        *,
        emit_stream: bool,
        step: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Run search + summarization for a single task."""
        with tool_boundary():
            if task.status not in ("pending", "in_progress"):
                return
            task.status = "in_progress"

        search_result, notices, answer_text, backend = run_search(dispatch_search,
            task.query,
            self.config,
            state.research_loop_count,
        )
        self._last_search_notices = notices
        task.notices.extend(n for n in notices if n not in task.notices)

        if emit_stream:
            for event in self._drain_tool_events(state, step=step):
                yield event
        else:
            self._drain_tool_events(state)

        if notices and emit_stream:
            for notice in notices:
                if notice:
                    yield {
                        "type": "status",
                        "message": notice,
                        "task_id": task.id,
                        "step": step,
                    }

        if not search_result or not search_result.get("results"):
            with tool_boundary():
                task.status = "skipped"
            if emit_stream:
                for event in self._drain_tool_events(state, step=step):
                    yield event
                yield {
                    "type": "task_status",
                    "task_id": task.id,
                    "status": "skipped",
                    "title": task.title,
                    "intent": task.intent,
                    "note_id": task.note_id,
                    "note_path": task.note_path,
                    "step": step,
                }
            else:
                self._drain_tool_events(state)
            return
        else:
            if not emit_stream:
                self._drain_tool_events(state)

        checkpoint()
        sources_summary, context = prepare_research_context(
            search_result,
            answer_text,
            self.config,
        )

        task.sources_summary = sources_summary

        with self._state_lock:
            state.web_research_results.append(context)
            state.sources_gathered.append(sources_summary)
            state.research_loop_count += 1

        summary_text: str | None = None

        if emit_stream:
            for event in self._drain_tool_events(state, step=step):
                yield event
            yield {
                "type": "sources",
                "task_id": task.id,
                "latest_sources": sources_summary,
                "raw_context": context,
                "step": step,
                "backend": backend,
                "note_id": task.note_id,
                "note_path": task.note_path,
            }

            summary_stream, summary_getter = self.summarizer.stream_task_summary(state, task, context)
            try:
                for event in self._drain_tool_events(state, step=step):
                    yield event
                for chunk in summary_stream:
                    checkpoint()
                    if chunk:
                        yield {
                            "type": "task_summary_chunk",
                            "task_id": task.id,
                            "content": chunk,
                            "note_id": task.note_id,
                            "step": step,
                        }
                    for event in self._drain_tool_events(state, step=step):
                        yield event
            finally:
                close = getattr(summary_stream, "close", None)
                if close is not None:
                    close()
            summary_text = summary_getter()
        else:
            summary_text = self.summarizer.summarize_task(state, task, context)
            self._drain_tool_events(state)

        with tool_boundary():
            if task.status not in ("pending", "in_progress"):
                return
            task.summary = summary_text.strip() if summary_text else "暂无可用信息"
            task.status = "completed"

        if emit_stream:
            for event in self._drain_tool_events(state, step=step):
                yield event
            yield {
                "type": "task_status",
                "task_id": task.id,
                "status": "completed",
                "summary": task.summary,
                "sources_summary": task.sources_summary,
                "note_id": task.note_id,
                "note_path": task.note_path,
                "step": step,
            }
        else:
            self._drain_tool_events(state)

    def _drain_tool_events(
        self,
        state: SummaryState,
        *,
        step: int | None = None,
    ) -> list[dict[str, Any]]:
        """Proxy to the shared tool call tracker."""
        return self._tool_tracker.drain(
            state, step=step, acknowledge=not getattr(self, "_streaming", False))

    @property
    def _tool_call_events(self) -> list[dict[str, Any]]:
        """Expose recorded tool events for legacy integrations."""
        return self._tool_tracker.as_dicts()

    def _serialize_task(self, task: TodoItem) -> dict[str, Any]:
        """Convert task dataclass to serializable dict for frontend."""
        return {
            "id": task.id,
            "title": task.title,
            "intent": task.intent,
            "query": task.query,
            "status": task.status,
            "summary": task.summary,
            "sources_summary": task.sources_summary,
            "note_id": task.note_id,
            "note_path": task.note_path,
            "stream_token": task.stream_token,
            "error_code": task.error_code, "detail": task.detail,
            "note_status": task.note_status, "note_error": task.note_error,
            "note_etag": task.note_etag, "notices": list(task.notices),
        }

    def _persist_final_report(self, state: SummaryState, report: str) -> dict[str, Any] | None:
        owner = getattr(self, "_note_owner", None)
        if owner is not None:
            artifact = getattr(self.reporting, "generated_text", None)
            try:
                if owner.run_id != state.run_id:
                    raise NoteError("OWNERSHIP_ERROR", "report owner belongs to another run")
                if artifact is None:
                    raise NoteError("READ_REQUIRED", "Reporter did not supply generation provenance")
                if artifact.text != report.strip():
                    raise NoteError("FORMAT_ERROR", "report text differs from generation artifact")
                with tool_boundary():
                    result = owner.persist_report(artifact, f"研究报告：{state.research_topic}")
                self.last_note_result = result
                state.report_note_status = "saved"
                state.report_note_id = result.note_id
                state.report_note_path = str(result.note_path)
                return {"type": "report_note", "note_id": result.note_id,
                        "note_path": str(result.note_path),
                        "title": f"研究报告：{state.research_topic}", "content": report.strip(),
                        "purpose": "final_report", "success": True}
            except NoteError as exc:
                self.last_note_result = NoteWriteResult(
                    False, exc.persisted, error_code=exc.code, detail=exc.detail)
                from services.tool_events import note_state
                state.report_note_status = note_state(False, exc.code, None)
                state.report_note_error = {"code": exc.code, "detail": exc.detail,
                                           "persisted": exc.persisted}
                state.warnings.append(f"最终报告笔记 {exc.code}: {exc.detail}")
                logger.warning("Final note persistence failed: %s", exc.code)
                return None

        if not self.config.enable_notes:
            state.report_note_status = "disabled"
        else:
            # Legacy text has no trusted run/purpose. Never select a task
            # conclusion or guess an ID for final persistence.
            state.report_note_status = "error"
            state.report_note_error = {"code": "OWNERSHIP_ERROR",
                                      "detail": "explicit verified Repository required"}
            self.last_note_result = NoteWriteResult(False, False, error_code="OWNERSHIP_ERROR",
                                                    detail="explicit verified Repository required")
            state.warnings.append("最终报告笔记未保存：需要显式已验证的 Repository")
        return None

    def _find_existing_report_note_id(self, state):
        owner = getattr(self, "_note_owner", None)
        if owner is None or owner.run_id != state.run_id:
            return None
        note = owner.final_note(NoteScope(state.run_id, "final_report"))
        return note.id if note else None

    @staticmethod
    def _extract_note_id_from_text(response: str) -> str | None:
        if not response:
            return None

        match = re.search(r"ID:\s*([^\n]+)", response)
        if not match:
            return None

        return match.group(1).strip()


def run_deep_research(topic: str, config: Configuration | None = None) -> SummaryStateOutput:
    """Convenience function mirroring the class-based API."""
    agent = DeepResearchAgent(config=config)
    return agent.run(topic)
