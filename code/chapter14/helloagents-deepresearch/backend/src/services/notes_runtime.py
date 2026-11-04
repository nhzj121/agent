"""Explicit files_v2 activation and service wiring; never migrate a source directory."""
import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import uuid

from storage.file_notes import FileNoteRepository, LOCK
from storage.note_repository import NoteError

MARKER = ".files-v2-workspace.json"


@dataclass(frozen=True)
class FilesSettings:
    workspace: Path
    protected: tuple[Path, ...]


def _absolute(value, label):
    if not isinstance(value, (str, Path)) or not str(value):
        raise ValueError(f"{label} requires an explicit absolute Linux path")
    raw = str(value)
    if ("\0" in raw or "\\" in raw or raw.startswith("//")
            or any(part in (".", "..") for part in raw.split("/"))
            or not Path(raw).is_absolute()):
        raise ValueError(f"{label} requires an absolute path without traversal")
    return Path(raw)


def _paths(workspace, protected):
    target = _absolute(workspace, "NOTES_V2_WORKSPACE")
    if not protected:
        raise ValueError("at least one explicit protected source is required")
    sources = []
    for value in protected:
        source = _absolute(value, "protected workspace")
        try:
            canonical = source.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ValueError("protected sources require canonical accessible path metadata") from exc
        if canonical != source:
            raise ValueError("protected sources must use real absolute paths, not symlink aliases")
        sources.append(source)
    sources = tuple(sorted(set(sources)))
    # This source-layout directory is never an activation target. Installed
    # services additionally require the real old path explicitly via config.
    backend = Path(__file__).absolute().parents[2]
    builtins = [backend / "notes"] if backend.name == "backend" else []
    for source in (*sources, *builtins):
        if target == source or source in target.parents or target in source.parents:
            raise ValueError(f"new workspace overlaps protected source: {source}")
    # Keep backend/notes reserved even when this module comes from a wheel.
    parts = target.parts
    if any(parts[i:i+2] == ("backend", "notes") for i in range(len(parts)-1)):
        raise ValueError("project backend/notes is permanently protected")
    return FilesSettings(target, sources)


def configured_settings(config):
    if not config.enable_notes:
        return None
    if config.notes_storage != "files_v2":
        raise ValueError("ENABLE_NOTES=true requires NOTES_STORAGE=files_v2; or set ENABLE_NOTES=false")
    # NOTES_WORKSPACE remains a protected SOURCE, never an implicit v2 target.
    return _paths(config.notes_v2_workspace,
                  [config.notes_workspace, *config.notes_protected_workspaces])


def _marker(repo, settings):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate activation marker key")
            result[key] = value
        return result
    try:
        data = json.loads(repo._bytes(MARKER), object_pairs_hook=unique)
        required = {"version", "storage", "workspace", "workspace_id", "device",
                    "inode", "protected_workspaces"}
        if not isinstance(data, dict) or set(data) != required:
            raise ValueError("invalid activation marker fields")
        stat = os.fstat(repo._fd)
        if (type(data["version"]) is not int or data["version"] != 1
                or data["storage"] != "files_v2" or data["workspace"] != str(settings.workspace)
                or type(data["device"]) is not int or data["device"] != stat.st_dev
                or type(data["inode"]) is not int or data["inode"] != stat.st_ino
                or not isinstance(data["workspace_id"], str)
                or not re.fullmatch(r"[0-9a-f]{32}", data["workspace_id"])
                or not isinstance(data["protected_workspaces"], list)):
            raise ValueError("activation marker does not match this workspace")
        pinned = {_absolute(p, "marker protected source") for p in data["protected_workspaces"]}
        if not pinned or not pinned.issubset(set(settings.protected)):
            raise ValueError("activation's protected sources cannot be removed")
        return data
    except (NoteError, ValueError, UnicodeError, TypeError) as exc:
        raise ValueError(f"files_v2 workspace is not activated/valid: {exc}") from exc


def initialize_workspace(workspace, protected):
    """Explicit empty-directory operation. No mkdir, export, migration or fallback."""
    settings = _paths(workspace, protected)
    try:
        with FileNoteRepository(settings.workspace) as repo:
            # Refuse populated unactivated directories before creating a lock.
            if set(repo._entries()) - {LOCK}:
                raise ValueError("activation requires an empty new workspace")
            with repo._locked(write=True):
                if set(repo._entries()) - {LOCK}:
                    raise ValueError("workspace changed or already activated")
                stat = os.fstat(repo._fd)
                data = {"version":1, "storage":"files_v2", "workspace":str(settings.workspace),
                        "workspace_id":uuid.uuid4().hex, "device":stat.st_dev, "inode":stat.st_ino,
                        "protected_workspaces":[str(p) for p in settings.protected]}
                # Existing G2a real flock/atomic write/file fsync/directory fsync.
                repo._atomic(MARKER, json.dumps(data, sort_keys=True).encode())
                return _marker(repo, settings)
    except (NoteError, OSError) as exc:
        raise ValueError(f"files_v2 activation failed: {exc}") from exc


def open_configured_repository(config):
    settings = configured_settings(config)
    if settings is None:
        return None
    repo = None
    try:
        repo = FileNoteRepository(settings.workspace)
        # Missing marker never initializes a legacy directory or its lock/index.
        _marker(repo, settings)
        with repo._locked():
            _marker(repo, settings)
            inspection = repo._inspect()
            if inspection["issues"]:
                raise ValueError("activated workspace inspection failed: " +
                                 json.dumps(inspection["issues"], ensure_ascii=False))
        return repo
    except (NoteError, OSError, ValueError) as exc:
        if repo is not None:
            repo.close()
        raise ValueError(f"files_v2 configuration rejected: {exc}") from exc


def validate_service_configuration(config):
    repo = open_configured_repository(config)
    if repo is None:
        return None
    try:
        return {"storage":"files_v2", "workspace":str(repo.workspace)}
    finally:
        repo.close()


def create_service_agent(config, execution, *, agent_class=None):
    """Production factory owns a per-research Repository until execution idle."""
    if agent_class is None:
        from agent import DeepResearchAgent
        agent_class = DeepResearchAgent
    repo = open_configured_repository(config)
    try:
        if repo is None:
            return agent_class(config=config)
        agent = agent_class(config=config, note_repository=repo)
        execution.on_idle(repo.close)
        return agent
    except BaseException:
        if repo is not None:
            repo.close()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("init", help="activate an existing empty new directory")
    command.add_argument("--workspace", required=True, type=Path)
    command.add_argument("--protected-workspace", required=True, action="append", type=Path)
    sub.add_parser("check", help="validate environment configuration without initializing")
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize_workspace(args.workspace, args.protected_workspace)
        else:
            from config import Configuration
            result = validate_service_configuration(Configuration.from_env()) or {"storage":"disabled"}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
