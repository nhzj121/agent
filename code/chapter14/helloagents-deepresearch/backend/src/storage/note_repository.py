"""Standalone note contracts. No Agent or framework imports."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol


class NoteError(Exception):
    """Explicit failure; persisted is False or 'unknown', never assumed on retry."""
    def __init__(self, code: str, detail: str, *, persisted: bool | str = False):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.persisted = persisted


@dataclass(frozen=True)
class NoteSnapshot:
    id: str
    title: str
    note_type: str
    tags: tuple[str, ...]
    content: str
    created_at: str
    updated_at: str
    etag: str
    format_version: int
    path: Path
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def run_id(self):
        return self.extra.get("run_id")

    @property
    def task_id(self):
        return self.extra.get("task_id")

    @property
    def purpose(self):
        return self.extra.get("purpose")

    @property
    def idempotency_key(self):
        return self.extra.get("idempotency_key")


@dataclass(frozen=True)
class NoteWriteResult:
    ok: bool
    persisted: bool | str
    note_id: str | None = None
    etag: str | None = None
    note_path: Path | None = None
    error_code: str | None = None
    detail: str | None = None


class NoteRepository(Protocol):
    def create(self, fields: Mapping[str, Any]) -> NoteSnapshot: ...
    def read(self, note_id: str) -> NoteSnapshot: ...
    def update(self, note_id: str, patch: Mapping[str, Any],
               expected_etag: str | None = None) -> NoteSnapshot: ...
    def delete(self, note_id: str, expected_etag: str | None = None) -> NoteWriteResult: ...
    def list(self) -> list[NoteSnapshot]: ...
    def search(self, query: str) -> list[NoteSnapshot]: ...
    def summary(self) -> dict[str, Any]: ...
