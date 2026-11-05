"""Project-local adapter for native, structured function calls."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from services.runtime import ResearchCancelled, ResearchRuntime

from hello_agents import HelloAgentsLLM
from hello_agents.tools import ToolRegistry

logger = logging.getLogger(__name__)

# Detect protocol leakage; never interpret text in the answer as an executable call.
PROTOCOL_MARKER = re.compile(
    r"</?[｜|]+DSML[｜|]+\s*(?:calls|tool_calls|invoke|parameter)\b"
    r"|[\[<]\s*TOOL_CALL\s*:"
    r"|</?(?:think|system_warning)\b"
    r"|budget:token_budget",
    re.IGNORECASE,
)


class AgentProtocolError(RuntimeError):
    """The model did not produce a complete, valid answer or function call."""


@dataclass
class ToolExecution:
    tool: str
    parameters: dict[str, Any]
    result: str


class NativeToolAgent:
    """Keep tool rounds private and return only a final assistant answer.

    The existing HelloAgents client supplies provider/model settings; no installed
    package is patched. Structured tool results still use the existing listener.
    """

    def __init__(
        self,
        *,
        name: str,
        llm: HelloAgentsLLM,
        system_prompt: str,
        tool_registry: ToolRegistry | None = None,
        tool_call_listener: Callable[[dict[str, Any]], None] | None = None,
        runtime: ResearchRuntime | None = None,
    ) -> None:
        self.runtime = runtime or ResearchRuntime()
        self.name = name
        self.llm = llm
        self.system_prompt = system_prompt
        self.tool_registry = tool_registry
        self.tool_call_listener = tool_call_listener
        self.task_id: int | None = None
        self.executions: list[ToolExecution] = []
        self._history: list[dict[str, Any]] = []
        self._executed: dict[str, tuple[str, str]] = {}

    def _check_cancelled(self) -> None:
        if self.runtime is not None:
            self.runtime.check_cancelled()

    def clear_history(self) -> None:
        self._history.clear()
        self.executions.clear()
        self._executed.clear()

    @staticmethod
    def _check_text(text: str) -> None:
        if PROTOCOL_MARKER.search(text):
            logger.error("模型正文含工具/控制协议标记，未作为答案接受：%s", text)
            raise AgentProtocolError("模型返回了异常工具或控制标记，工具执行及总结未确认完成")

    @staticmethod
    def _check_finish(reason: str | None, *, tool_calls: bool = False) -> None:
        expected = "tool_calls" if tool_calls else "stop"
        if reason != expected:
            raise AgentProtocolError(f"模型响应未完整结束（finish_reason={reason!r}），未确认完成")

    def _schemas(self) -> list[dict[str, Any]]:
        if self.tool_registry is None:
            return []
        schemas = []
        for tool in self.tool_registry.get_all_tools():
            schema = tool.to_openai_schema()
            if tool.name == "note":
                schema["function"]["parameters"]["properties"]["task_id"] = {
                    "type": "integer", "description": "关联的研究任务编号（如 1、2）"
                }
            schemas.append(schema)
        return schemas

    @contextmanager
    def _open_stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> Any:
        self._check_cancelled()
        request: dict[str, Any] = {
            "model": self.llm.model,
            "messages": messages,
            "temperature": self.llm.temperature,
            "stream": True,
        }
        if self.llm.max_tokens is not None:
            request["max_tokens"] = self.llm.max_tokens
        if tools:
            request["tools"] = tools
            request["tool_choice"] = "auto"
        # Hold the permit until the entire response is consumed and closed.
        # Tool execution happens after this context, so it never holds an LLM slot.
        with self.runtime.llm_slot():
            response = self.llm._client.chat.completions.create(**request)
            with response:
                self._check_cancelled()
                yield response

    def _collect_round(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        content: list[str] = []
        reasoning: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        finish: str | None = None
        with self._open_stream(messages, tools) as response:
            for chunk in response:
                self._check_cancelled()
                for choice in chunk.choices:
                    delta = choice.delta
                    if delta.content:
                        content.append(delta.content)
                    if getattr(delta, "reasoning_content", None):
                        reasoning.append(delta.reasoning_content)
                    if choice.finish_reason:
                        finish = choice.finish_reason
                    for fragment in delta.tool_calls or []:
                        call = calls.setdefault(fragment.index, {
                            "id": "", "type": "function",
                            "function": {"name": "", "arguments": ""},
                        })
                        if fragment.id:
                            call["id"] += fragment.id
                        if fragment.function:
                            if fragment.function.name:
                                call["function"]["name"] += fragment.function.name
                            if fragment.function.arguments:
                                call["function"]["arguments"] += fragment.function.arguments
        self._check_cancelled()
        text = "".join(content)
        self._check_text(text)
        ordered = [calls[index] for index in sorted(calls)]
        self._check_finish(finish, tool_calls=bool(ordered))
        message: dict[str, Any] = {"role": "assistant", "content": text or None}
        if reasoning:
            message["reasoning_content"] = "".join(reasoning)
        if ordered:
            message["tool_calls"] = ordered
        return message

    def _execute(self, call: dict[str, Any]) -> str:
        self._check_cancelled()
        call_id = call["id"]
        name = call["function"]["name"]
        raw = call["function"]["arguments"]
        if not call_id or not name:
            raise AgentProtocolError("工具调用缺少编号或工具名，未执行")
        try:
            parameters = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AgentProtocolError("工具参数不是完整 JSON，未执行") from exc
        if not isinstance(parameters, dict):
            raise AgentProtocolError("工具参数必须是 JSON 对象，未执行")
        tool = self.tool_registry.get_tool(name) if self.tool_registry else None
        if tool is None or not tool.validate_parameters(parameters):
            raise AgentProtocolError(f"工具 {name!r} 未注册或缺少必要参数，未执行")
        signature = json.dumps([name, parameters], sort_keys=True, ensure_ascii=False)
        if call_id in self._executed:
            previous, result = self._executed[call_id]
            if previous != signature:
                raise AgentProtocolError("同一工具调用编号出现不同参数，未重复执行")
            return result
        try:
            result = str(tool.run(parameters))
        except ResearchCancelled:
            raise
        except Exception as exc:
            result = f"❌ 工具调用失败：{exc}"
        tracked_parameters = dict(parameters)
        if self.task_id is not None:
            tracked_parameters["task_id"] = self.task_id
        self.executions.append(ToolExecution(name, tracked_parameters, result))
        self._executed[call_id] = (signature, result)
        if self.tool_call_listener:
            self.tool_call_listener({
                "agent_name": self.name, "tool_name": name,
                "raw_parameters": raw, "parsed_parameters": tracked_parameters,
                "result": result,
            })
        self._check_cancelled()
        if result.lstrip().startswith("❌"):
            raise AgentProtocolError(f"工具 {name!r} 执行失败：{result}")
        return result

    def run(self, input_text: str, max_tool_iterations: int = 8) -> str:
        tools = self._schemas()
        system_prompt = self.system_prompt
        if not tools:
            system_prompt += (
                "\n本次未启用任何工具，所有笔记协作要求均不适用。"
                "直接完成答案，不模拟工具调用或声称执行了笔记操作。"
            )
        messages = [
            {"role": "system", "content": system_prompt},
            *self._history,
            {"role": "user", "content": input_text},
        ]
        for _ in range(max_tool_iterations):
            message = self._collect_round(messages, tools)
            calls = message.get("tool_calls", [])
            if not calls:
                answer = (message["content"] or "").strip()
                if not answer:
                    raise AgentProtocolError("模型未返回有效答案，未确认完成")
                self._history = messages[1:] + [message]
                return answer
            messages.append(message)
            # Execute complete calls in order, including parallel calls in one turn.
            for call in calls:
                messages.append({
                    "role": "tool", "tool_call_id": call["id"],
                    "content": self._execute(call),
                })
        raise AgentProtocolError("工具协作超过轮次上限，未确认完成")

    def stream_answer(self, prompt: str, *, system_prompt: str) -> Iterator[str]:
        """Generate only the answer from fresh context, without tool instructions.

        Retain a short tail so a protocol marker split over chunks is detected
        before its prefix reaches the UI. An interrupted/limited answer fails.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        pending = ""
        finish: str | None = None
        with self._open_stream(messages) as response:
            for chunk in response:
                self._check_cancelled()
                for choice in chunk.choices:
                    if choice.delta.tool_calls:
                        raise AgentProtocolError("最终总结阶段意外返回工具调用，未确认完成")
                    pending += choice.delta.content or ""
                    self._check_text(pending)
                    if choice.finish_reason:
                        finish = choice.finish_reason
                    if len(pending) > 64:
                        yield pending[:-64]
                        pending = pending[-64:]
        self._check_cancelled()
        self._check_finish(finish)
        if pending:
            yield pending
