"""Durable, workspace-wide cooperative maintenance windows."""
import json
import secrets
from .file_notes import CONTROL
from .note_repository import NoteError


class ManualEditController:
    def __init__(self, repository):
        self.repository = repository

    def begin(self):
        repo = self.repository
        with repo._locked(write=True):
            state = repo._control()
            if state["session_token"] is not None:
                raise NoteError("WRITES_PAUSED", "an edit window is already active")
            state = {"session_token": secrets.token_hex(32), "generation": state["generation"] + 1}
            repo._atomic(CONTROL, json.dumps(state).encode())
            return state.copy()

    def end(self, token):
        repo = self.repository
        with repo._locked(write=True):
            state = repo._control()
            if (not isinstance(token, str) or state["session_token"] is None or
                    not secrets.compare_digest(token, state["session_token"])):
                raise NoteError("CONFLICT", "maintenance token mismatch")
            # Legacy index is advisory and may be stale. Validate authority files,
            # not the index; inspect/export report index problems separately.
            if repo._inspect(include_index=False)["issues"]:
                raise NoteError("FORMAT_ERROR", "invalid notes; writes remain paused")
            next_state = {"session_token": None, "generation": state["generation"] + 1}
            repo._atomic(CONTROL, json.dumps(next_state).encode())
            return {"generation": next_state["generation"], "paused": False}
