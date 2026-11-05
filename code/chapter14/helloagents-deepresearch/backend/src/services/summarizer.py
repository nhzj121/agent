"""Separate verified note collaboration from final answer generation."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import re

from config import Configuration
from models import SummaryState, TodoItem
from prompts import task_summary_writer_instructions
from services.native_agent import AgentProtocolError, NativeToolAgent
from services.notes import build_note_guidance


class SummarizationService:
    """Only final-answer fragments are exposed to the summary event stream."""

    def __init__(
        self,
        summarizer_factory: Callable[[], NativeToolAgent],
        config: Configuration,
    ) -> None:
        self._agent_factory = summarizer_factory
        self._config = config

    def _prepare(
        self, state: SummaryState, task: TodoItem, context: str
    ) -> tuple[NativeToolAgent, str]:
        agent = self._agent_factory()
        agent.task_id = task.id
        verified_note = ""
        try:
            if self._config.enable_notes:
                agent.run(self._build_prompt(state, task, context))
                read_ids: set[str] = set()
                target_id = task.note_id
                created_here = False
                synchronized = False
                for execution in agent.executions:
                    if execution.tool != "note":
                        continue
                    params = execution.parameters
                    action = params.get("action")
                    note_id = params.get("note_id")
                    if action == "read" and isinstance(note_id, str):
                        read_ids.add(note_id)
                    elif action == "create" and target_id is None:
                        match = re.search(r"ID:\s*([^\n]+)", execution.result)
                        if match:
                            target_id = match.group(1).strip()
                            created_here = True
                            verified_note = str(params.get("content") or "")
                            synchronized = True
                    elif action == "update" and note_id == target_id:
                        if note_id in read_ids or created_here:
                            verified_note = str(params.get("content") or "")
                            synchronized = True
                if not synchronized or not verified_note.strip():
                    raise AgentProtocolError("未确认任务笔记已按要求成功读取并同步，停止生成完成总结")
            final_prompt = (
                f"研究主题：{state.research_topic}\n"
                f"任务名称：{task.title}\n任务目标：{task.intent}\n"
                f"检索查询：{task.query}\n"
                f"研究材料：\n{context}\n"
                f"已通过工具核实写入的任务笔记内容：\n{verified_note or '本次未启用笔记'}\n"
                "请依据上述材料直接输出唯一一份面向用户的最终任务总结。"
            )
            return agent, final_prompt
        except BaseException:
            agent.clear_history()
            raise

    def summarize_task(self, state: SummaryState, task: TodoItem, context: str) -> str:
        stream, get_summary = self.stream_task_summary(state, task, context)
        for _ in stream:
            pass
        return get_summary()

    def stream_task_summary(
        self, state: SummaryState, task: TodoItem, context: str
    ) -> tuple[Iterator[str], Callable[[], str]]:
        pieces: list[str] = []

        def generator() -> Iterator[str]:
            agent, prompt = self._prepare(state, task, context)
            try:
                for chunk in agent.stream_answer(
                    prompt, system_prompt=task_summary_writer_instructions.strip()
                ):
                    pieces.append(chunk)
                    yield chunk
                if not "".join(pieces).strip():
                    raise AgentProtocolError("模型未返回有效的最终任务总结")
            finally:
                agent.clear_history()

        return generator(), lambda: "".join(pieces).strip()

    def _build_prompt(self, state: SummaryState, task: TodoItem, context: str) -> str:
        return (
            f"任务主题：{state.research_topic}\n任务名称：{task.title}\n"
            f"任务目标：{task.intent}\n检索查询：{task.query}\n"
            f"任务上下文：\n{context}\n{build_note_guidance(task)}\n"
            "请完成笔记读取、分析与同步；面向用户的总结由独立阶段生成。"
        )
