"""Task summarization utilities."""

from __future__ import annotations

import logging
import sys

from collections.abc import Callable, Iterator
from typing import Tuple

from hello_agents import ToolAwareSimpleAgent

from models import SummaryState, TodoItem
from config import Configuration
from utils import ThinkingFilter, strip_thinking_tokens
from services.notes import build_note_guidance
from services.execution_control import checkpoint, close_thread_streams
from services.text_processing import strip_tool_calls


logger = logging.getLogger(__name__)


class SummarizationService:
    """Handles synchronous and streaming task summarization."""

    def __init__(
        self,
        summarizer_factory: Callable[[], ToolAwareSimpleAgent],
        config: Configuration,
        task_agent_factory=None,
    ) -> None:
        self._agent_factory = summarizer_factory
        self._task_agent_factory = task_agent_factory
        self._config = config

    def summarize_task(self, state: SummaryState, task: TodoItem, context: str) -> str:
        """Generate a task-specific summary using the summarizer agent."""

        checkpoint()
        prompt = self._build_prompt(state, task, context)

        agent = (self._task_agent_factory(task) if self._task_agent_factory is not None
                 else self._agent_factory())
        try:
            response = agent.run(prompt)
        finally:
            agent.clear_history()

        summary_text = response.strip()
        if self._config.strip_thinking_tokens:
            summary_text = strip_thinking_tokens(summary_text)

        summary_text = strip_tool_calls(summary_text).strip()

        return summary_text or "暂无可用信息"

    def stream_task_summary(
        self, state: SummaryState, task: TodoItem, context: str
    ) -> Tuple[Iterator[str], Callable[[], str]]:
        """Stream the summary text for a task while collecting full output."""

        checkpoint()
        prompt = self._build_prompt(state, task, context)
        remove_thinking = self._config.strip_thinking_tokens
        visible_output = ""
        agent = (self._task_agent_factory(task) if self._task_agent_factory is not None
                 else self._agent_factory())

        def generator() -> Iterator[str]:
            nonlocal visible_output
            thinking = ThinkingFilter()
            inner = None
            try:
                inner = agent.stream_run(prompt)
                for chunk in inner:
                    segment = thinking.feed(chunk) if remove_thinking else chunk
                    if segment:
                        visible_output += segment
                        yield segment
            finally:
                # No yield during close/error. Release only iterators we own.
                active_error = sys.exc_info()[0] is not None
                cleanup_error = None
                for cleanup in (getattr(inner, "close", None), close_thread_streams, agent.clear_history):
                    if cleanup is None:
                        continue
                    try:
                        cleanup()
                    except Exception as exc:
                        if cleanup_error is None:
                            cleanup_error = exc
                        logger.warning("Summary cleanup failed", exc_info=True)
                if cleanup_error is not None and not active_error:
                    raise cleanup_error

        def get_summary() -> str:
            return strip_tool_calls(visible_output).strip()

        return generator(), get_summary

    def _build_prompt(self, state: SummaryState, task: TodoItem, context: str) -> str:
        """Construct the summarization prompt shared by both modes."""

        return (
            f"任务主题：{state.research_topic}\n"
            f"任务名称：{task.title}\n"
            f"任务目标：{task.intent}\n"
            f"检索查询：{task.query}\n"
            f"任务上下文：\n{context}\n"
            f"{build_note_guidance(task)}\n"
            "请按照以上协作要求先同步笔记，然后返回一份面向用户的 Markdown 总结（仍遵循任务总结模板）。"
        )
