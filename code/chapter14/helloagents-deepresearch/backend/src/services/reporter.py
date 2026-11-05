"""Service that consolidates task results into the final report."""

from __future__ import annotations

from services.native_agent import AgentProtocolError, NativeToolAgent

from models import SummaryState
from config import Configuration
from utils import strip_thinking_tokens


class ReportingService:
    """Generates the final structured report."""

    def __init__(self, report_agent: NativeToolAgent, config: Configuration) -> None:
        self._agent = report_agent
        self._config = config

    def generate_report(self, state: SummaryState) -> str:
        """Generate a structured report based on completed tasks."""

        tasks_block = []
        for task in state.todo_items:
            summary_block = task.summary or "暂无可用信息"
            sources_block = task.sources_summary or "暂无来源"
            tasks_block.append(
                f"### 任务 {task.id}: {task.title}\n"
                f"- 任务目标：{task.intent}\n"
                f"- 检索查询：{task.query}\n"
                f"- 执行状态：{task.status}\n"
                f"- 任务总结：\n{summary_block}\n"
                f"- 来源概览：\n{sources_block}\n"
            )

        note_references = []
        for task in state.todo_items:
            if task.note_id:
                note_references.append(
                    f"- 任务 {task.id}《{task.title}》：note_id={task.note_id}"
                )

        notes_section = "\n".join(note_references) if note_references else "- 暂无可用任务笔记"

        prompt = (
            f"研究主题：{state.research_topic}\n"
            f"任务概览：\n{''.join(tasks_block)}\n"
            f"可用任务笔记：\n{notes_section}\n"
            "请通过原生 note 工具逐条读取上述笔记，整合所有信息后撰写报告。\n"
            "如需保存汇总结论，可调用 note 工具创建 conclusion 笔记，tags 使用 deep_research 和 report。"
        )

        if not self._config.enable_notes:
            prompt = (
                f"研究主题：{state.research_topic}\n"
                f"任务概览：\n{''.join(tasks_block)}\n"
                "本次未启用笔记，请直接依据任务概览生成最终报告。"
            )
        try:
            response = self._agent.run(prompt)
            if self._config.enable_notes:
                expected = {task.note_id for task in state.todo_items if task.note_id}
                read_ids = {
                    item.parameters.get("note_id") for item in self._agent.executions
                    if item.tool == "note" and item.parameters.get("action") == "read"
                }
                if expected - read_ids:
                    raise AgentProtocolError("报告生成前未确认所有任务笔记已成功读取")
        finally:
            self._agent.clear_history()

        report_text = response.strip()
        if self._config.strip_thinking_tokens:
            report_text = strip_thinking_tokens(report_text)

        return report_text or "报告生成失败，请检查输入。"

