"""Utility helpers for normalizing agent generated text."""

from __future__ import annotations


def strip_tool_calls(text: str) -> str:
    """Remove tool markers, tracking arrays and JSON string escapes.

    An unfinished marker consumes the remaining suffix rather than exposing
    partially generated arguments. Brackets outside markers are left intact.
    """
    if not text:
        return text
    marker = "[TOOL_CALL:"
    output: list[str] = []
    pos = 0
    while True:
        start = text.find(marker, pos)
        if start < 0:
            output.append(text[pos:])
            break
        output.append(text[pos:start])
        depth, quoted, escaped = 1, False, False
        end = start + len(marker)
        while end < len(text) and depth:
            char = text[end]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
            end += 1
        pos = end
        if depth:
            break
    return "".join(output)
