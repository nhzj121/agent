"""Trusted per-run note ownership, verified bindings and final-report persistence."""
from dataclasses import dataclass
import hashlib
from threading import RLock

from storage.note_repository import NoteError, NoteWriteResult


@dataclass(frozen=True)
class NoteBinding:
    run_id: str
    task_id: int
    note_id: str
    etag: str
    note_path: str
    verified: bool = True


class NoteOwnership:
    def __init__(self, repository, run_id):
        self.repository, self.run_id = repository, run_id
        self.bindings = {}
        self._commits = {}
        self._lock = RLock()

    def identity(self, scope):
        if scope.run_id != self.run_id:
            raise NoteError("OWNERSHIP_ERROR", "scope belongs to another run")
        identity = {"run_id": self.run_id, "purpose": scope.purpose}
        if scope.task_id is not None:
            identity["task_id"] = scope.task_id
        if scope.purpose in ("task", "final_report"):
            identity["idempotency_key"] = (
                f"{self.run_id}:{scope.purpose}:{scope.task_id if scope.task_id is not None else ''}")
        return identity

    def validate(self, note, scope, *, write=False):
        if note.extra.get("run_id") != self.run_id or scope.run_id != self.run_id:
            raise NoteError("OWNERSHIP_ERROR", "unverified or foreign run note")
        if scope.purpose == "final_report" and not write:
            return
        expected = self.identity(scope)
        if any(note.extra.get(key) != value for key, value in expected.items()):
            raise NoteError("OWNERSHIP_ERROR", "note is outside this task/purpose")

    def bind(self, note):
        task_id = note.extra.get("task_id")
        if (note.extra.get("run_id") == self.run_id and note.extra.get("purpose") == "task"
                and type(task_id) is int):
            with self._lock:
                self.bindings[task_id] = NoteBinding(
                    self.run_id, task_id, note.id, note.etag, str(note.path))

    def binding(self, task_id):
        with self._lock:
            return self.bindings.get(task_id)

    def forget(self, note_id):
        with self._lock:
            self.bindings = {k: v for k, v in self.bindings.items() if v.note_id != note_id}

    def create(self, fields, scope):
        identity = self.identity(scope)
        fields = {**fields, "extra": identity}
        if "idempotency_key" in identity:
            note, fresh = self.repository.create_once(fields, identity)
        else:
            note, fresh = self.repository.create(fields), True
        self.validate(note, scope, write=True)
        self.bind(note)
        return note, fresh

    def final_note(self, scope):
        identity = self.identity(scope)
        matches = [n for n in self.repository.list()
                   if all(n.extra.get(k) == v for k, v in identity.items())]
        if len(matches) > 1:
            raise NoteError("CONFLICT", "duplicate trusted report identity")
        return matches[0] if matches else None

    def persist_report(self, artifact, title):
        basis = artifact.basis
        if basis.run_id != self.run_id or basis.purpose != "final_report" or basis.task_id is not None:
            raise NoteError("OWNERSHIP_ERROR", "not a Reporter generation")
        from services.note_versions import NoteScope
        scope = NoteScope(self.run_id, "final_report")
        key = (artifact.artifact_id, hashlib.sha256(artifact.text.encode()).hexdigest())
        with self._lock:
            note = self.final_note(scope)
            if key in self._commits:
                previous = self._commits[key]
                if note and note.id == previous.note_id and note.etag == previous.etag:
                    return previous
                raise NoteError("CONFLICT", "persisted artifact changed after acknowledgement")
            if note is None:
                note, fresh = self.create(
                    {"title": title, "content": artifact.text, "note_type": "conclusion",
                     "tags": ["deep_research", "report"]}, scope)
                if fresh:
                    result = NoteWriteResult(True, True, note.id, note.etag, note.path)
                    self._commits[key] = result
                    return result
            # Finding the current note above never supplies the expected ETag.
            receipt = basis.get(note.id)
            if (receipt is None or receipt.execution_id != basis.execution_id or
                    receipt.agent_scope != basis.agent_scope or receipt.run_id != self.run_id):
                raise NoteError("READ_REQUIRED", "report lacks its generation-time full snapshot")
            self.validate(note, scope, write=True)
            note = self.repository.update(
                note.id, {"title": title, "content": artifact.text}, receipt.etag)
            result = NoteWriteResult(True, True, note.id, note.etag, note.path)
            self._commits[key] = result
            return result
