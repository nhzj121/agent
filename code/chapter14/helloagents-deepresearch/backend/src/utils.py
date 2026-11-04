"""Utility helpers shared across deep researcher services."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Union

CHARS_PER_TOKEN = 4

logger = logging.getLogger(__name__)


def get_config_value(value: Any) -> str:
    """Return configuration value as plain string."""

    return value if isinstance(value, str) else value.value


class ThinkingFilter:
    """Incremental exact-tag filter; unfinished thinking/prefixes fail closed."""

    def __init__(self) -> None:
        self._pending = ""
        self._depth = 0

    def feed(self, chunk: str) -> str:
        self._pending += chunk
        output: list[str] = []
        tags = ("<think>", "</think>")
        pos = 0
        while pos < len(self._pending):
            if self._pending.startswith(tags[0], pos):
                self._depth += 1
                pos += len(tags[0])
            elif self._pending.startswith(tags[1], pos):
                self._depth = max(0, self._depth - 1)
                pos += len(tags[1])
            elif len(self._pending) - pos < len(tags[1]) and any(
                tag.startswith(self._pending[pos:]) for tag in tags
            ):
                break
            else:
                if not self._depth:
                    output.append(self._pending[pos])
                pos += 1
        self._pending = self._pending[pos:]
        return "".join(output)


def strip_thinking_tokens(text: str) -> str:
    """Apply the same conservative thinking-tag policy as the stream."""
    return ThinkingFilter().feed(text)


def deduplicate_and_format_sources(
    search_response: Dict[str, Any] | List[Dict[str, Any]],
    max_tokens_per_source: int,
    *,
    fetch_full_page: bool = False,
) -> str:
    """Format and deduplicate search results for downstream prompting."""

    if isinstance(search_response, dict):
        sources_list = search_response.get("results", [])
    else:
        sources_list = search_response

    unique_sources: dict[str, Dict[str, Any]] = {}
    for source in sources_list:
        url = source.get("url")
        if not url:
            continue
        if url not in unique_sources:
            unique_sources[url] = source

    formatted_parts: List[str] = []
    for source in unique_sources.values():
        title = source.get("title") or source.get("url", "")
        content = source.get("content", "")
        formatted_parts.append(f"信息来源: {title}\n\n")
        formatted_parts.append(f"URL: {source.get('url', '')}\n\n")
        formatted_parts.append(f"信息内容: {content}\n\n")

        if fetch_full_page:
            raw_content = source.get("raw_content")
            if raw_content is None:
                logger.debug("raw_content missing for %s", source.get("url", ""))
                raw_content = ""
            char_limit = max_tokens_per_source * CHARS_PER_TOKEN
            if len(raw_content) > char_limit:
                raw_content = f"{raw_content[:char_limit]}... [truncated]"
            formatted_parts.append(
                f"详细信息内容限制为 {max_tokens_per_source} 个 token: {raw_content}\n\n"
            )

    return "".join(formatted_parts).strip()


def format_sources(search_results: Dict[str, Any] | None) -> str:
    """Return bullet list summarising search sources."""

    if not search_results:
        return ""

    results = search_results.get("results", [])
    return "\n".join(
        f"* {item.get('title', item.get('url', ''))} : {item.get('url', '')}"
        for item in results
        if item.get("url")
    )
