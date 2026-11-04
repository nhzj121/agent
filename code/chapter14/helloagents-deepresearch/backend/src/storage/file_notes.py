"""Linux, single-machine Markdown repository. All operations are directory-fd relative.

All cooperating writers must retain the lock file. Editors do not participate in
flock: use a maintenance window if saving concurrently with repository writers.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import uuid

from .note_codec import decode, encode
from .note_repository import NoteError, NoteWriteResult

ID = re.compile(r"note_(?:[0-9a-f]{32}|\d{8}_\d{6}_\d+)\Z", re.ASCII)
CONTROL = ".notes-control.json"
LOCK = ".notes.lock"


def validate_id(note_id):
    if not isinstance(note_id, str) or not ID.fullmatch(note_id):
        raise NoteError("INVALID_ID", "expected opaque UUID or legacy note ID")
    return note_id


def _io(exc):
    code = "INVALID_ID" if exc.errno in (errno.ELOOP, errno.ENOTDIR) else "IO_ERROR"
    return NoteError(code, str(exc))


def _regular(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise NoteError("INVALID_ID", "not a regular unlinked-to-other-paths file")


class FileNoteRepository:
    def __init__(self, workspace):
        raw = os.fspath(workspace)
        if not os.path.isabs(raw) or ".." in Path(raw).parts:
            raise NoteError("INVALID_ID", "workspace must be an explicit absolute directory")
        self.workspace = Path(raw)
        self._fd = None
        # Reject symlinks in every existing directory component, not just leaf.
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for part in self.workspace.parts[1:]:
                new_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                                 os.O_CLOEXEC, dir_fd=fd)
                os.close(fd)
                fd = new_fd
            self._fd, fd = fd, None
        except OSError as exc:
            raise _io(exc) from exc
        finally:
            if fd is not None:
                os.close(fd)

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @contextmanager
    def _locked(self, *, write=False):
        if self._fd is None:
            raise NoteError("IO_ERROR", "repository is closed")
        fd = None
        try:
            # Each operation gets a separate open file description: flock also
            # serializes threads and independent instances within the same PID.
            fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW |
                         os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=self._fd)
            _regular(fd)
            fcntl.flock(fd, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            yield
        except OSError as exc:
            raise _io(exc) from exc
        finally:
            if fd is not None:
                os.close(fd)  # releases flock even if the body failed

    def _bytes(self, name):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                         os.O_CLOEXEC, dir_fd=self._fd)
        except FileNotFoundError as exc:
            raise NoteError("NOT_FOUND", name) from exc
        except OSError as exc:
            raise _io(exc) from exc
        try:
            _regular(fd)
            with os.fdopen(fd, "rb", closefd=False) as stream:
                return stream.read()
        finally:
            os.close(fd)

    def _read(self, note_id):
        validate_id(note_id)
        return decode(self._bytes(note_id + ".md"), note_id,
                      self.workspace / (note_id + ".md"))

    def read(self, note_id):
        validate_id(note_id)
        with self._locked():
            return self._read(note_id)

    def _control(self):
        try:
            raw = self._bytes(CONTROL)
        except NoteError as exc:
            if exc.code == "NOT_FOUND":
                return {"generation": 0, "session_token": None}
            raise
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate control key")
                    result[key] = value
                return result
            data = json.loads(raw, object_pairs_hook=unique)
            if (not isinstance(data, dict) or set(data) != {"generation", "session_token"}
                    or type(data["generation"]) is not int or data["generation"] < 0
                    or (data["session_token"] is not None and
                        (not isinstance(data["session_token"], str) or
                         not re.fullmatch(r"[0-9a-f]{64}", data["session_token"])))):
                raise ValueError("invalid maintenance control")
            return data
        except (ValueError, UnicodeError) as exc:
            raise NoteError("FORMAT_ERROR", "invalid maintenance control") from exc

    def _writable(self):
        if self._control()["session_token"] is not None:
            raise NoteError("WRITES_PAUSED", "manual edit window active")

    def _checkpoint(self, stage):
        """Fault-injection seam; production path performs every real syscall."""

    def _atomic(self, name, raw):
        temp = ".note-tmp-" + uuid.uuid4().hex
        fd = None
        attempted_commit = False
        created_temp = False
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW |
                         os.O_CLOEXEC, 0o600, dir_fd=self._fd)
            created_temp = True
            self._checkpoint("temp_opened")
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                self._checkpoint("temp_written")
                os.fsync(fd)
                self._checkpoint("file_fsynced")
            os.close(fd)
            fd = None
            self._checkpoint("before_replace")
            attempted_commit = True
            os.replace(temp, name, src_dir_fd=self._fd, dst_dir_fd=self._fd)
            self._checkpoint("replaced")
            os.fsync(self._fd)
            self._checkpoint("dir_fsynced")
        except Exception as exc:
            if isinstance(exc, NoteError) and not attempted_commit:
                raise
            code = "COMMIT_UNCERTAIN" if attempted_commit else "IO_ERROR"
            raise NoteError(code, str(exc),
                            persisted="unknown" if attempted_commit else False) from exc
        finally:
            if fd is not None:
                os.close(fd)
            if created_temp:
                try:
                    os.unlink(temp, dir_fd=self._fd)
                except OSError:
                    # Never mask a COMMIT_UNCERTAIN error; stale temp files are
                    # ignored, not automatically promoted or removed on startup.
                    pass

    def _exists(self, name):
        try:
            os.stat(name, dir_fd=self._fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    def _create_locked(self, fields):
        allowed = {"title", "content", "note_type", "tags", "extra"}
        if not isinstance(fields, dict) or set(fields) - allowed:
            raise NoteError("FORMAT_ERROR", "unknown creation fields")
        extra = fields.get("extra", {})
        reserved = {"id", "title", "type", "tags", "created_at", "updated_at", "format_version"}
        if not isinstance(extra, dict) or reserved & extra.keys():
            raise NoteError("FORMAT_ERROR", "invalid extra metadata")
        for _ in range(8):
            note_id = "note_" + uuid.uuid4().hex
            if not self._exists(note_id + ".md"):
                break
        else:
            raise NoteError("CONFLICT", "ID allocation exhausted")
        now = datetime.now(timezone.utc).isoformat()
        data = {**extra, "id": note_id, "title": fields.get("title"),
                "type": fields.get("note_type", "general"), "tags": fields.get("tags", []),
                "created_at": now, "updated_at": now}
        raw = encode(data, fields.get("content", ""))
        snapshot = decode(raw, note_id, self.workspace / (note_id + ".md"))
        self._atomic(note_id + ".md", raw)
        return snapshot


    def create(self, fields):
        with self._locked(write=True):
            self._writable()
            return self._create_locked(fields)

    def create_once(self, fields, identity):
        """Atomic trusted identity create-if-absent; existing content is untouched."""
        if (not isinstance(identity, dict) or not identity or
                not set(identity) <= {"run_id", "purpose", "task_id", "idempotency_key"} or
                not {"run_id", "purpose", "idempotency_key"} <= set(identity) or
                any(not isinstance(identity[k], str) or not identity[k]
                    for k in ("run_id", "purpose", "idempotency_key")) or
                not isinstance(fields, dict) or not isinstance(fields.get("extra"), dict) or
                any(fields.get("extra", {}).get(k) != v for k, v in identity.items())):
            raise NoteError("OWNERSHIP_ERROR", "invalid trusted creation identity")
        with self._locked(write=True):
            self._writable()
            found = [n for n in self._list()
                     if all(n.extra.get(k) == v for k, v in identity.items())]
            if len(found) > 1:
                raise NoteError("CONFLICT", "duplicate trusted identity")
            if found:
                return found[0], False
            return self._create_locked(fields), True

    @staticmethod
    def _version(expected_etag):
        if not isinstance(expected_etag, str) or not expected_etag:
            raise NoteError("READ_REQUIRED", "expected_etag from a snapshot is required")

    def update(self, note_id, patch, expected_etag=None):
        validate_id(note_id)
        self._version(expected_etag)
        if not isinstance(patch, dict) or set(patch) - {"title", "content", "note_type", "tags"}:
            raise NoteError("FORMAT_ERROR", "patch may only change title/content/note_type/tags")
        with self._locked(write=True):
            self._writable()
            current = self._read(note_id)
            if current.etag != expected_etag:
                raise NoteError("CONFLICT", "snapshot no longer matches disk")
            data = {**current.extra, "id": current.id,
                    "title": patch.get("title", current.title),
                    "type": patch.get("note_type", current.note_type),
                    "tags": patch.get("tags", list(current.tags)),
                    "created_at": current.created_at,
                    "updated_at": datetime.now(timezone.utc).isoformat()}
            raw = encode(data, patch.get("content", current.content))
            snapshot = decode(raw, note_id, current.path)
            self._atomic(note_id + ".md", raw)
            return snapshot

    def delete(self, note_id, expected_etag=None):
        validate_id(note_id)
        self._version(expected_etag)
        with self._locked(write=True):
            self._writable()
            current = self._read(note_id)
            if current.etag != expected_etag:
                raise NoteError("CONFLICT", "snapshot no longer matches disk")
            attempted = False
            try:
                attempted = True
                os.unlink(note_id + ".md", dir_fd=self._fd)
                os.fsync(self._fd)
            except OSError as exc:
                raise NoteError("COMMIT_UNCERTAIN" if attempted else "IO_ERROR", str(exc),
                                persisted="unknown" if attempted else False) from exc
            return NoteWriteResult(ok=True, persisted=True, note_id=note_id)

    def _entries(self):
        # A fresh open file description prevents concurrent readers from sharing
        # directory enumeration offsets. dup(self._fd) would still share them.
        fd = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                     os.O_CLOEXEC, dir_fd=self._fd)
        try:
            return os.listdir(fd)
        finally:
            os.close(fd)

    def _names(self):
        return sorted(name for name in self._entries() if name.endswith(".md"))

    def _list(self):
        return [self._read(name[:-3]) for name in self._names()]

    def list(self):
        with self._locked():
            return self._list()

    def search(self, query):
        if not isinstance(query, str):
            raise NoteError("FORMAT_ERROR", "query must be text")
        key = query.casefold()
        return [n for n in self.list() if key in
                "\n".join([n.title, n.content, *n.tags]).casefold()]

    def summary(self):
        notes = self.list()
        counts = {}
        for note in notes:
            counts[note.note_type] = counts.get(note.note_type, 0) + 1
        return {"total_notes": len(notes), "by_type": counts}

    def _inspect(self, *, include_index=True):
        issues, ids = [], set()
        for name in self._names():
            try:
                ids.add(self._read(name[:-3]).id)
            except NoteError as exc:
                issues.append({"path": name, "code": exc.code, "detail": exc.detail})
        if include_index and self._exists("notes_index.json"):
            try:
                data = json.loads(self._bytes("notes_index.json"))
                rows = data["notes"]
                if not isinstance(rows, list) or not all(
                        isinstance(x, dict) and isinstance(x.get("id"), str) for x in rows):
                    raise ValueError("invalid legacy index rows")
                seen = set()
                for row in rows:
                    note_id = row["id"]
                    if note_id in seen:
                        issues.append({"code": "INDEX_DUPLICATE", "id": note_id})
                    seen.add(note_id)
                    if note_id not in ids:
                        issues.append({"code": "INDEX_MISSING_FILE", "id": note_id})
                for note_id in ids - seen:
                    issues.append({"code": "INDEX_UNLISTED_FILE", "id": note_id})
            except (NoteError, ValueError, KeyError, TypeError) as exc:
                issues.append({"code": "INDEX_ERROR", "detail": str(exc)})
        state = self._control()
        return {"issues": issues, "paused": state["session_token"] is not None,
                "generation": state["generation"], "total_notes": len(ids)}

    def inspect(self):
        with self._locked():
            return self._inspect()

    def export(self, destination):
        """Byte-preserving snapshot export to an existing empty explicit directory.

        This is not a live migration or a conversion back to unsafe NoteTool.
        Errors leave a partial destination for inspection; never delete user data.
        """
        with self._locked():
            report = self._inspect()
            if report["issues"]:
                raise NoteError("FORMAT_ERROR", "inspection must pass before export")
            with FileNoteRepository(destination) as target:
                if os.fstat(target._fd).st_ino == os.fstat(self._fd).st_ino and \
                        os.fstat(target._fd).st_dev == os.fstat(self._fd).st_dev:
                    raise NoteError("CONFLICT", "export destination is source")
                if target._entries():
                    raise NoteError("CONFLICT", "destination must be empty")
                with target._locked(write=True):
                    if any(name != LOCK for name in target._entries()):
                        raise NoteError("CONFLICT", "destination changed while acquiring lock")
                    for name in self._names():
                        raw = self._bytes(name)
                        decode(raw, name[:-3], self.workspace / name)
                        target._atomic(name, raw)
                return {"exported": report["total_notes"], "destination": str(target.workspace)}
