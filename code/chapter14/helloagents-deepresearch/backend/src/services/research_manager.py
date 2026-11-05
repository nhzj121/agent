"""Single-process, in-memory research queue, snapshots and replayable events.

Bounded background workers own execution. HTTP subscriptions only observe it.
Active and queued research capacity is reserved atomically at admission.
"""

import logging

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Condition, Thread
from typing import Callable, Iterator
from uuid import uuid4

from config import Configuration
from services.runtime import RequestBudget, ResearchCancelled, ResearchRuntime

logger = logging.getLogger(__name__)

TERMINAL = {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _Research:
    research_id: str
    topic: str
    config: Configuration
    runtime: ResearchRuntime = field(default_factory=ResearchRuntime)
    status: str = "PENDING"
    stage: str = "queued"
    created_at: str = field(default_factory=now)
    started_at: str | None = None
    finished_at: str | None = None
    tasks: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    report: str = ""
    outcome: dict | None = None
    error: str | None = None


class ResearchQueueFull(RuntimeError):
    """All active and waiting research positions are occupied."""


class ResearchManager:
    def __init__(self, agent_factory: Callable, *, config: Configuration | None = None):
        self._factory = agent_factory
        self._settings = (config or Configuration.from_env()).model_copy(deep=True)
        self._budget = RequestBudget(self._settings.max_llm_concurrency, self._settings.max_search_concurrency)
        self._condition = Condition()
        self._jobs: dict[str, _Research] = {}
        self._pending = deque()
        self._workers: dict[str, Thread] = {}
        self._closed = False

    def _get(self, research_id: str) -> _Research:
        # Caller holds the condition lock.
        if research_id not in self._jobs:
            raise KeyError(research_id)
        return self._jobs[research_id]

    def submit(self, topic: str, config: Configuration) -> dict:
        topic = topic.strip()
        if not topic:
            raise ValueError("研究主题不能为空")
        with self._condition:
            if self._closed:
                raise RuntimeError("研究管理器已关闭")
            if (len(self._workers) >= self._settings.max_concurrent_researches
                    and len(self._pending) >= self._settings.max_pending_researches):
                raise ResearchQueueFull("研究运行和等待位置已满，请稍后提交")
            research_id = uuid4().hex
            job_config = config.model_copy(deep=True)
            job_config.max_task_workers = self._settings.max_task_workers
            job = _Research(research_id, topic, job_config, runtime=ResearchRuntime(
                research_id=research_id, budget=self._budget))
            self._jobs[job.research_id] = job
            self._pending.append(job.research_id)
            self._publish(job, {"type": "research_status", "status": job.status})
            self._start_available()
            return self._snapshot(job)

    def _start_available(self) -> None:
        # Called with the manager lock held, so waiting capacity is exact even
        # during simultaneous submissions. CANCELLING jobs keep their position.
        while (not self._closed and self._pending
               and len(self._workers) < self._settings.max_concurrent_researches):
            job = self._get(self._pending.popleft())
            job.status, job.stage, job.started_at = "RUNNING", "planning", now()
            self._publish(job, {"type": "research_status", "status": job.status})
            thread = Thread(target=self._execute, args=(job,),
                            name=f"research-{job.research_id[:8]}", daemon=True)
            self._workers[job.research_id] = thread
            try:
                thread.start()
            except Exception as exc:
                self._workers.pop(job.research_id)
                self._finish(job, None, str(exc))

    def _publish(self, job: _Research, payload: dict) -> None:
        event = deepcopy(payload)
        event.update(research_id=job.research_id, seq=len(job.events) + 1, timestamp=now())
        job.events.append(event)
        self._condition.notify_all()

    def _record(self, job: _Research, event: dict) -> None:
        kind = event.get("type")
        if kind == "todo_list":
            job.tasks = {task["id"]: deepcopy(task) for task in event.get("tasks", [])}
            job.stage = "tasks"
        elif kind in {"task_status", "task_summary_chunk", "sources"}:
            task_id = event.get("task_id")
            if task_id is not None:
                task = job.tasks.setdefault(task_id, {"id": task_id, "status": "pending"})
                if kind == "task_status":
                    task.update({key: deepcopy(value) for key, value in event.items()
                                 if key in {"title", "intent", "query", "status", "summary", "sources_summary",
                                            "note_id", "note_path", "detail", "stream_token"}})
                elif kind == "task_summary_chunk":
                    task["summary"] = (task.get("summary") or "") + str(event.get("content") or "")
                else:
                    task["sources_summary"] = event.get("latest_sources")
        elif kind == "final_report":
            job.report = str(event.get("report") or "")
            job.stage = "report"
        elif kind == "status":
            if event.get("stage") in {"planning", "tasks", "report"}:
                job.stage = event["stage"]
            elif not job.tasks:
                job.stage = "planning"
        task_id = event.get("task_id")
        if task_id in job.tasks:
            task = job.tasks[task_id]
            for key in ("note_id", "note_path", "stream_token"):
                if event.get(key) is not None:
                    task[key] = event[key]
            if kind == "status" and event.get("message"):
                task.setdefault("notices", []).append(event["message"])
        self._publish(job, event)

    def _outcome(self, job: _Research, status: str, error=None) -> dict:
        counts = {state: sum(t.get("status") == state for t in job.tasks.values())
                  for state in ("completed", "failed", "skipped", "cancelled")}
        return dict(status=status, total_tasks=len(job.tasks),
                    **{key + "_tasks": value for key, value in counts.items()},
                    report_available=bool(job.report), error=error)

    def _finish(self, job: _Research, outcome: dict | None, error=None) -> None:
        if job.runtime.cancelled:
            for task in job.tasks.values():
                if task.get("status") in {"pending", "in_progress"}:
                    task["status"] = "cancelled"
                    self._publish(job, {"type": "task_status", "task_id": task["id"], "status": "cancelled"})
            outcome = self._outcome(job, "cancelled")
        elif outcome is None:
            completed = any(task.get("status") == "completed" for task in job.tasks.values())
            # An unexpected fatal error cannot leave pending tasks marked running.
            for task in job.tasks.values():
                if task.get("status") in {"pending", "in_progress"}:
                    task["status"] = "failed"
                    self._publish(job, {"type": "task_status", "task_id": task["id"],
                                        "status": "failed", "detail": error})
            outcome = self._outcome(job, "partial" if completed else "failed", error)
        else:
            outcome = deepcopy(outcome)
            outcome.setdefault("cancelled_tasks", 0)
            outcome["report_available"] = bool(job.report)
        if outcome["status"].upper() not in TERMINAL:
            outcome = self._outcome(job, "failed", "研究未返回有效结束状态")
        job.outcome = outcome
        job.error = outcome.get("error")
        job.status = outcome["status"].upper()
        job.stage = "finished"
        job.finished_at = now()
        self._publish(job, {"type": "research_status", "status": job.status})
        self._publish(job, {"type": "done", "outcome": outcome})

    def _execute(self, job: _Research) -> None:
        outcome, error = None, None
        stream = None
        try:
            job.runtime.check_cancelled()
            agent = self._factory(job.config, job.runtime)
            job.runtime.check_cancelled()
            stream = agent.run_stream(job.topic)
            for event in stream:
                with self._condition:
                    if event.get("type") == "done":
                        outcome = event.get("outcome")
                    else:
                        self._record(job, event)
        except ResearchCancelled:
            pass
        except Exception as exc:
            logger.exception("Research %s execution failed", job.research_id)
            error = str(exc)
        finally:
            try:
                if stream is not None:
                    stream.close()
            except Exception as exc:
                error = error or str(exc)
                outcome = None
            with self._condition:
                self._finish(job, outcome, error or "研究流程未正常完成")
                self._workers.pop(job.research_id)
                self._start_available()

    def cancel(self, research_id: str) -> dict:
        with self._condition:
            job = self._get(research_id)
            if job.status not in TERMINAL and job.status != "CANCELLING":
                job.runtime.cancel()
                if job.status == "PENDING":
                    self._pending.remove(research_id)
                    self._finish(job, None)
                else:
                    job.status = "CANCELLING"
                    self._publish(job, {"type": "research_status", "status": job.status})
            return self._snapshot(job)

    def _snapshot(self, job: _Research, *, full=True) -> dict:
        result = dict(research_id=job.research_id, topic=job.topic, status=job.status,
                      stage=job.stage, created_at=job.created_at, started_at=job.started_at,
                      finished_at=job.finished_at, snapshot_seq=len(job.events),
                      report_available=bool(job.report), error=job.error,
                      progress=self._outcome(job, job.status.lower()))
        if full:
            result.update(todo_items=list(job.tasks.values()), report_markdown=job.report,
                          outcome=job.outcome,
                          logs=[e for e in job.events if e.get("type") in {"status", "research_status", "task_status"}],
                          tool_calls=[e for e in job.events if e.get("type") == "tool_call"])
        return deepcopy(result)

    def get(self, research_id: str) -> dict:
        with self._condition:
            return self._snapshot(self._get(research_id))

    def list(self) -> list[dict]:
        with self._condition:
            return [self._snapshot(job, full=False) for job in reversed(list(self._jobs.values()))]

    def wait(self, research_id: str) -> dict:
        with self._condition:
            job = self._get(research_id)
            self._condition.wait_for(lambda: job.status in TERMINAL)
            return self._snapshot(job)

    def validate_cursor(self, research_id: str, after: int) -> None:
        with self._condition:
            job = self._get(research_id)
            if after < 0 or after > len(job.events):
                raise ValueError("事件游标超出当前研究范围")

    def events(self, research_id: str, after: int = 0) -> Iterator[dict | None]:
        self.validate_cursor(research_id, after)
        while True:
            with self._condition:
                job = self._get(research_id)
                if after == len(job.events) and job.status not in TERMINAL:
                    self._condition.wait(timeout=10)
                batch = deepcopy(job.events[after:])
                finished = job.status in TERMINAL
            for event in batch:
                after = event["seq"]
                yield event
            if finished:
                return
            if not batch:
                yield None  # SSE heartbeat; subscriber departure never cancels execution.

    def close(self) -> None:
        with self._condition:
            self._closed = True
            for job in self._jobs.values():
                if job.status not in TERMINAL:
                    self.cancel(job.research_id)
            workers = list(self._workers.values())
            self._condition.notify_all()
        for worker in workers:
            worker.join()
