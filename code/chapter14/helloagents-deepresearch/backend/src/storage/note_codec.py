"""Versioned YAML codec plus explicit line-oriented HelloAgents legacy codec."""
import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import yaml
from .note_repository import NoteError, NoteSnapshot

KNOWN = {"id", "title", "type", "tags", "created_at", "updated_at", "format_version"}


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ValueError("duplicate/non-string metadata key")
        result[key] = loader.construct_object(value_node)
    return result


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def validate(data: dict[str, Any], content: str) -> None:
    for key in ("id", "title", "type", "created_at", "updated_at"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValueError(f"missing/invalid {key}")
    if not isinstance(content, str):
        raise ValueError("content must be text")
    tags = data.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(x, str) for x in tags):
        raise ValueError("tags must be a list of strings")


def decode(raw: bytes, note_id: str, path: Path) -> NoteSnapshot:
    try:
        text = raw.decode("utf-8", errors="strict")
        match = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
        if not match:
            raise ValueError("missing frontmatter delimiters")
        header, body = match.group(1), text[match.end():]
        if re.search(r"""^(?:format_version|['"]format_version['"])\s*:""", header, re.M):
            if any(isinstance(e, yaml.events.AliasEvent) for e in yaml.parse(header)):
                raise ValueError("YAML aliases are unsupported")
            data = yaml.load(header, Loader=UniqueSafeLoader)
            if not isinstance(data, dict) or type(data.get("format_version")) is not int or data["format_version"] != 1:
                raise ValueError("unsupported format_version")
            version = 1
        else:
            data = {}
            for line in header.splitlines():
                if not line.strip():
                    continue
                if line[:1].isspace() or ":" not in line:
                    raise ValueError("unsupported legacy multiline/metadata syntax")
                key, value = line.split(":", 1)
                key, value = key.strip(), value.strip()
                if not key or key in data:
                    raise ValueError("duplicate/empty legacy key")
                data[key] = json.loads(value) if key == "tags" else value
            version = 0
            # The original writer inserts this separator and heading. Remove only
            # its exact envelope, preserving body whitespace and unknown fields.
            if body.startswith("\r\n"):
                body = body[2:]
            elif body.startswith("\n"):
                body = body[1:]
            heading = "# " + data.get("title", "")
            for suffix in ("\r\n\r\n", "\n\n"):
                if body.startswith(heading + suffix):
                    body = body[len(heading + suffix):]
                    break
        validate(data, body)
        if data["id"] != note_id:
            raise ValueError("filename and metadata id differ")
        return NoteSnapshot(
            id=note_id, title=data["title"], note_type=data["type"],
            tags=tuple(data.get("tags", [])), content=body,
            created_at=data["created_at"], updated_at=data["updated_at"],
            etag=hashlib.sha256(raw).hexdigest(), format_version=version,
            path=path, extra=copy.deepcopy({k: v for k, v in data.items() if k not in KNOWN}),
        )
    except (ValueError, TypeError, yaml.YAMLError, RecursionError) as exc:
        raise NoteError("FORMAT_ERROR", str(exc)) from exc


def encode(data: dict[str, Any], content: str) -> bytes:
    try:
        validate(data, content)
        metadata = copy.deepcopy(data)
        metadata["format_version"] = 1
        return ("---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
                + "---\n" + content).encode("utf-8")
    except (ValueError, TypeError, yaml.YAMLError, RecursionError) as exc:
        raise NoteError("FORMAT_ERROR", str(exc)) from exc
