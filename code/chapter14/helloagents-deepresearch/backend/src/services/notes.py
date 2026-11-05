"""Helpers for coordinating native note tool usage."""

from __future__ import annotations

import json

from models import TodoItem


def build_note_guidance(task: TodoItem) -> str:
    """Describe note operations without embedding a text-call protocol."""
    tags = json.dumps(["deep_research", f"task_{task.id}"], ensure_ascii=False)
    common = (
        f"- 工具参数 task_id 使用 {task.id}，tags 使用 {tags}。\n"
        "- 保持已有段落结构，在对应段落补充完整的研究发现和来源依据。\n"
        "- 必须依据工具真实返回确认操作成功；不要在正文模拟工具调用或工具结果。\n"
    )
    if task.note_id:
        return (
            "笔记协作指引：\n"
            f"- 当前任务笔记 ID：{task.note_id}。\n"
            "- 先通过原生 note 工具的 read 操作读取该笔记，再通过 update 操作同步研究发现。\n"
            + common
        )
    return (
        "笔记协作指引：\n"
        "- 当前任务没有笔记，请通过原生 note 工具的 create 操作创建 task_state 笔记。\n"
        + common
    )
