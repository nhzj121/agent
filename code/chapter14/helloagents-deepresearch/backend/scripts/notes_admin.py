"""Explicit-workspace maintenance CLI. No default notes path or Agent imports."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from storage.file_notes import FileNoteRepository
from storage.manual_edit import ManualEditController
from storage.note_repository import NoteError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("inspect", "manual-begin", "manual-end", "export"):
        command = sub.add_parser(action)
        command.add_argument("--workspace", required=True, type=Path)
        if action == "manual-end":
            command.add_argument("--token", required=True)
        if action == "export":
            command.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    try:
        with FileNoteRepository(args.workspace) as repo:
            if args.action == "inspect":
                result = repo.inspect()
            elif args.action == "manual-begin":
                result = ManualEditController(repo).begin()
            elif args.action == "manual-end":
                result = ManualEditController(repo).end(args.token)
            else:
                result = repo.export(args.destination)
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result.get("issues") else 0
    except NoteError as exc:
        print(json.dumps({"error_code": exc.code, "detail": exc.detail,
                          "persisted": exc.persisted}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
