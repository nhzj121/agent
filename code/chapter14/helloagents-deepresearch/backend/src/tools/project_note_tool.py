"""Local note tool view; tool parameters never provide version authorization."""
from dataclasses import asdict, dataclass
import json

from hello_agents.tools.base import Tool, ToolParameter
from storage.note_repository import NoteError, NoteWriteResult


@dataclass(frozen=True)
class NoteToolResult:
    status: NoteWriteResult
    text: str
    task_id: int | None = None


class ProjectNoteTool(Tool):
    def __init__(self, repository, ownership, scope, ledger):
        super().__init__("note", "笔记 create/read/update/delete/list/search/summary；先 read 后在新一轮更新", False)
        self.repository, self.ownership, self.scope, self.ledger = repository, ownership, scope, ledger
        self.last_result = None

    def get_parameters(self):
        return [ToolParameter(name=k, type=t, required=(k == "action"), description=k)
                for k, t in [("action", "string"), ("note_id", "string"), ("title", "string"),
                             ("content", "string"), ("note_type", "string"), ("tags", "array"),
                             ("task_id", "integer"), ("expected_etag", "string"),
                             ("query", "string"), ("limit", "integer")]]

    def _failure(self, exc):
        return NoteToolResult(
            NoteWriteResult(False, exc.persisted, error_code=exc.code, detail=exc.detail),
            "❌ " + exc.code + ": " + json.dumps(exc.detail, ensure_ascii=False),
            self.scope.task_id)

    def execute(self, params):
        receipt = None
        try:
            if not self.ledger.active:
                raise NoteError("READ_REQUIRED", "no active Agent execution")
            forbidden = {"run_id", "purpose", "idempotency_key", "receipt_id",
                         "execution_id", "agent_scope", "extra"}
            if forbidden & params.keys():
                raise NoteError("OWNERSHIP_ERROR", "model cannot set trusted identity/receipt")
            if "task_id" in params and params["task_id"] != self.scope.task_id:
                raise NoteError("OWNERSHIP_ERROR", "untrusted task claim")
            action = params.get("action")
            snapshot, fresh, persisted = None, False, False
            if action == "create":
                if not params.get("title") or not params.get("content"):
                    raise NoteError("FORMAT_ERROR", "create requires title and content")
                snapshot, fresh = self.ownership.create(
                    {k: params[k] for k in ("title", "content", "note_type", "tags") if k in params},
                    self.scope)
                persisted = fresh
            elif action == "read":
                snapshot = self.repository.read(params.get("note_id"))
                self.ownership.validate(snapshot, self.scope)
                self.ownership.bind(snapshot)
                fresh = True  # full read, not an idempotent ID acknowledgement
            elif action in ("update", "delete"):
                note_id = params.get("note_id")
                grant = self.ledger.grant(note_id)
                if grant is None:
                    raise NoteError("READ_REQUIRED", "read must reach a new model generation first")
                for name in ("expected_etag", "etag"):
                    if name in params and params[name] != grant.etag:
                        raise NoteError("VERSION_PARAM_MISMATCH", "model version differs from trusted basis")
                current = self.repository.read(note_id)
                self.ownership.validate(current, self.scope, write=True)
                if action == "delete":
                    status = self.repository.delete(note_id, grant.etag)
                    self.ledger.revoke(note_id)
                    self.ownership.forget(note_id)
                    return NoteToolResult(status, "✅ 笔记删除成功", self.scope.task_id), None
                snapshot = self.repository.update(
                    note_id, {k: params[k] for k in ("title", "content", "note_type", "tags") if k in params},
                    grant.etag)
                self.ledger.revoke(note_id)
                self.ownership.bind(snapshot)
                persisted = True
            elif action in ("list", "search", "summary"):
                notes = []
                for note in self.repository.list():
                    try:
                        self.ownership.validate(note, self.scope)
                    except NoteError:
                        continue
                    if params.get("note_type") and note.note_type != params["note_type"]:
                        continue
                    if action != "search" or str(params.get("query", "")).casefold() in (
                            note.title + "\n" + note.content + "\n" + " ".join(note.tags)).casefold():
                        notes.append(note)
                limit = params.get("limit", 10)
                if type(limit) is not int or limit < 0:
                    raise NoteError("FORMAT_ERROR", "limit must be a nonnegative integer")
                counts = {}
                for note in notes:
                    counts[note.note_type] = counts.get(note.note_type, 0) + 1
                data = ([{"note_id": n.id, "title": n.title, "note_type": n.note_type}
                         for n in notes[:limit]] if action != "summary"
                        else {"total_notes": len(notes), "by_type": counts})
                return NoteToolResult(NoteWriteResult(True, False),
                                      json.dumps(data, ensure_ascii=False)), None
            else:
                raise NoteError("FORMAT_ERROR", "unknown note action")
            full = action == "read" or (action == "create" and fresh)
            payload = json.dumps({
                "id": snapshot.id, "title": snapshot.title, "note_type": snapshot.note_type,
                "tags": snapshot.tags, "content": snapshot.content,
                "created_at": snapshot.created_at, "updated_at": snapshot.updated_at,
                "etag": snapshot.etag, "extra": dict(snapshot.extra),
                "format_version": snapshot.format_version, "path": str(snapshot.path),
            }, ensure_ascii=False, sort_keys=True, default=str)
            text = "✅ 笔记操作成功\nID: " + snapshot.id
            if full:
                receipt = self.ledger.receipt(snapshot, payload)
                text += "\nreceipt_id: " + receipt.receipt_id + "\n" + payload
            else:
                text += "\n请 read 后在新一轮生成中更新。"
            task_id = snapshot.extra.get("task_id") if snapshot.extra.get("purpose") == "task" else None
            return NoteToolResult(NoteWriteResult(
                True, persisted, snapshot.id, snapshot.etag, snapshot.path), text, task_id), receipt
        except NoteError as exc:
            if params.get("action") in ("update", "delete") and exc.code in (
                    "CONFLICT", "COMMIT_UNCERTAIN"):
                self.ledger.revoke(params.get("note_id"))
            return self._failure(exc), None

    def run(self, parameters):
        result, receipt = self.execute(parameters)
        self.last_result = result
        if self.ledger.active:
            self.ledger.record(result.text, receipt)
        return result.text
