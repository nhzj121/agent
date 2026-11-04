"""Execution-local, server-issued read receipts; never infer grants from model text."""
from dataclasses import dataclass
import copy
import hashlib
import json
from threading import Lock
import uuid


@dataclass(frozen=True)
class NoteScope:
    run_id: str
    purpose: str
    task_id: int | None = None


@dataclass(frozen=True)
class ReadReceipt:
    receipt_id: str
    execution_id: str
    run_id: str
    agent_scope: str
    task_id: int | None
    purpose: str
    note_id: str
    etag: str
    snapshot_digest: str
    tool_execution_id: str


@dataclass(frozen=True)
class GenerationBasis:
    generation_id: str
    execution_id: str
    run_id: str
    agent_scope: str
    purpose: str
    task_id: int | None
    receipts: tuple[ReadReceipt, ...] = ()

    def get(self, note_id):
        return next((r for r in self.receipts if r.note_id == note_id), None)


@dataclass(frozen=True)
class GeneratedText:
    text: str
    basis: GenerationBasis
    artifact_id: str


class VersionLedger:
    def __init__(self, scope):
        self.scope = scope
        self.agent_scope = uuid.uuid4().hex
        self._lock = Lock()
        self.active = False
        self.basis = None

    def start(self):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("same Agent cannot execute concurrently")
        self.active = True
        self.execution_id = uuid.uuid4().hex
        self.delivered = {}
        self.pending = []
        self.previous_messages = None
        self.revoked = set()
        self.basis = None

    def receipt(self, snapshot, payload):
        return ReadReceipt(
            uuid.uuid4().hex, self.execution_id, self.scope.run_id, self.agent_scope,
            self.scope.task_id, self.scope.purpose, snapshot.id, snapshot.etag,
            hashlib.sha256(payload.encode()).hexdigest(), uuid.uuid4().hex)

    def record(self, text, receipt=None):
        self.pending.append(("🔧 工具 note 执行结果：\n" + text, receipt))

    def revoke(self, note_id):
        self.delivered.pop(note_id, None)
        self.revoked.add(note_id)
        # A newer read in the same already-generated batch cannot repair a
        # conflict or authorize a second write.
        self.pending = [(text, None if r and r.note_id == note_id else r)
                        for text, r in self.pending]

    def freeze(self, messages):
        if not self.active:
            raise RuntimeError("LLM view used outside execution")
        if (self.previous_messages is not None and
                messages[:len(self.previous_messages)] != self.previous_messages):
            self.delivered.clear()  # trimmed/rewritten input cannot borrow old grants
        if self.pending:
            expected = ("工具执行结果：\n" +
                        "\n\n".join(text for text, _ in self.pending) +
                        "\n\n请基于这些结果给出完整的回答。")
            previous = self.previous_messages
            authentic = (
                previous is not None and len(messages) == len(previous) + 2 and
                messages[:-2] == previous and messages[-2].get("role") == "assistant" and
                messages[-1] == {"role": "user", "content": expected})
            if authentic:
                for _, receipt in self.pending:
                    if receipt is not None:
                        self.delivered[receipt.note_id] = receipt
                        self.revoked.discard(receipt.note_id)
            # Do not accept substrings, receipt-looking user text or history.
            self.pending.clear()
        self.previous_messages = copy.deepcopy(messages)
        self.basis = GenerationBasis(
            uuid.uuid4().hex, self.execution_id, self.scope.run_id, self.agent_scope,
            self.scope.purpose, self.scope.task_id, tuple(self.delivered.values()))

    def grant(self, note_id):
        if not self.active or self.basis is None or note_id in self.revoked:
            return None
        return self.basis.get(note_id)

    def generated(self, text):
        if self.basis is None:
            raise RuntimeError("no model generation")
        # Revoked receipts must not survive in a generated artifact.
        basis = GenerationBasis(
            self.basis.generation_id, self.basis.execution_id, self.basis.run_id,
            self.basis.agent_scope, self.basis.purpose, self.basis.task_id,
            tuple(r for r in self.basis.receipts if r.note_id not in self.revoked))
        return GeneratedText(text, basis, uuid.uuid4().hex)

    def finish(self):
        self.pending.clear()
        self.delivered.clear()
        self.revoked.clear()
        self.previous_messages = None
        self.basis = None
        self.active = False
        self._lock.release()
