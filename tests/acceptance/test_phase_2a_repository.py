"""G2a standalone tests. Every workspace is synthetic and temporary."""
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "code/chapter14/helloagents-deepresearch/backend/src"
sys.path.insert(0, str(SRC))
from storage.file_notes import FileNoteRepository
from storage.manual_edit import ManualEditController
from storage.note_repository import NoteError

FIELDS = {"title": "中文: 标题", "content": "# 正文\n\nbody\n", "tags": ["任务", "x"]}
LEGACY_ID = "note_20261029_204116_4"

def legacy(note_id=LEGACY_ID):
    return ("---\nid: "+note_id+"\ntitle: 中文: 标题\ntype: general\n"
            'tags: ["任务", "x"]\ncreated_at: 2026-10-29T20:41:16\n'
            "updated_at: 2026-10-29T20:41:17\ncustom: 未知: 字段\n"
            "---\n\n# 中文: 标题\n\n正文\n\n尾部\n")

class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ws = self.root / "workspace"
        self.ws.mkdir()
        self.repo = FileNoteRepository(self.ws)
        self.addCleanup(self.repo.close)
        # Storage tests must not import the framework or issue network requests.
        for name in ["socket.socket.connect", "socket.getaddrinfo"]:
            p = patch(name, side_effect=AssertionError("external API forbidden"))
            p.start()
            self.addCleanup(p.stop)

    def error(self, code, call):
        with self.assertRaises(NoteError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_roundtrip_patch_etag_and_required_versions(self):
        n = self.repo.create(FIELDS)
        self.assertRegex(n.id, r"^note_[0-9a-f]{32}$")
        self.assertEqual(n.etag, hashlib.sha256(n.path.read_bytes()).hexdigest())
        self.assertEqual(n.content, FIELDS["content"])
        self.error("READ_REQUIRED", lambda: self.repo.update(n.id, {"title": "new"}))
        self.error("READ_REQUIRED", lambda: self.repo.delete(n.id))
        newer = self.repo.update(n.id, {"title": "new"}, n.etag)
        self.assertEqual(newer.content, n.content)
        self.assertEqual(newer.tags, n.tags)
        self.error("CONFLICT", lambda: self.repo.update(n.id, {"content": "stale"}, n.etag))
        self.error("CONFLICT", lambda: self.repo.delete(n.id, n.etag))
        self.repo.delete(n.id, newer.etag)
        self.error("NOT_FOUND", lambda: self.repo.read(n.id))

    def test_twenty_threads_and_forced_collision(self):
        with ThreadPoolExecutor(20) as pool:
            notes = list(pool.map(lambda _: self.repo.create(FIELDS), range(20)))
        self.assertEqual(len({n.id for n in notes}), 20)
        self.assertEqual(len(list(self.ws.glob("*.md"))), 20)
        from uuid import UUID
        with patch("storage.file_notes.uuid.uuid4", return_value=UUID(int=1)):
            first = self.repo.create(FIELDS)
            raw = first.path.read_bytes()
            self.error("CONFLICT", lambda: self.repo.create({"title": "x", "content": "overwrite"}))
        self.assertEqual(first.path.read_bytes(), raw)

    def test_two_instances_cas_and_explicit_read_merge(self):
        with FileNoteRepository(self.ws) as other:
            n = self.repo.create(FIELDS)
            barrier = threading.Barrier(2)
            def update(repo):
                barrier.wait(3)
                try:
                    return repo.update(n.id, {"title": "winner"}, n.etag)
                except NoteError as exc:
                    return exc.code
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(update, [self.repo, other]))
            self.assertEqual(sum(x == "CONFLICT" for x in results if isinstance(x, str)), 1)
            latest = other.read(n.id)
            merged = other.update(n.id, {"content": "merged"}, latest.etag)
            self.assertEqual(merged.title, "winner")
            self.assertEqual(merged.content, "merged")

    def test_all_actions_validate_ids_and_links(self):
        n = self.repo.create(FIELDS)
        for bad in ["../outer", "/tmp/outer", r"..\outer", "note_../x", "a\0x", "note_bad", "", 1]:
            for action in [lambda: self.repo.read(bad),
                           lambda: self.repo.update(bad, {}, n.etag),
                           lambda: self.repo.delete(bad, n.etag)]:
                self.error("INVALID_ID", action)
        outside = self.root / "outside.md"
        outside.write_text("protected")
        n.path.unlink()
        n.path.symlink_to(outside)
        for action in [lambda: self.repo.read(n.id), lambda: self.repo.update(n.id, {}, n.etag),
                       lambda: self.repo.delete(n.id, n.etag), self.repo.list,
                       lambda: self.repo.search("protected"), self.repo.summary]:
            self.error("INVALID_ID", action)
        self.assertEqual(outside.read_text(), "protected")
        n.path.unlink()
        os.link(outside, n.path)
        self.error("INVALID_ID", lambda: self.repo.read(n.id))
        n.path.unlink()
        n.path.mkdir()
        self.error("INVALID_ID", lambda: self.repo.read(n.id))

    def test_workspace_and_control_symlinks(self):
        link = self.root / "link"
        link.symlink_to(self.ws, target_is_directory=True)
        self.error("INVALID_ID", lambda: FileNoteRepository(link))
        outside = self.root / "protected"
        outside.write_text("keep")
        for name in [".notes.lock", ".notes-control.json"]:
            p = self.ws / name
            if p.exists():
                p.unlink()
            p.symlink_to(outside)
            self.error("INVALID_ID", lambda: self.repo.create(FIELDS))
            p.unlink()
        self.assertEqual(outside.read_text(), "keep")

    def test_legacy_read_preserves_bytes_body_unknown_and_upgrade_on_write(self):
        p = self.ws / (LEGACY_ID + ".md")
        raw = legacy().encode()
        p.write_bytes(raw)
        n = self.repo.read(LEGACY_ID)
        self.assertEqual(n.title, "中文: 标题")
        self.assertEqual(n.content, "正文\n\n尾部\n")
        self.assertEqual(n.tags, ("任务", "x"))
        self.assertEqual(n.extra["custom"], "未知: 字段")
        self.assertEqual(n.format_version, 0)
        self.assertEqual(p.read_bytes(), raw)
        updated = self.repo.update(n.id, {"title": "新: 标题"}, n.etag)
        self.assertEqual(updated.format_version, 1)
        self.assertEqual(updated.content, n.content)
        self.assertEqual(updated.extra, n.extra)
        self.assertEqual(updated.created_at, n.created_at)

    def test_bad_formats_duplicate_keys_mismatched_ids_are_explicit(self):
        p = self.ws / (LEGACY_ID + ".md")
        bad = [
            "plain body", legacy().replace('["任务", "x"]', "[broken"),
            legacy().replace("id: "+LEGACY_ID, "id: note_20261029_204116_5"),
            legacy().replace("title: 中文: 标题", "title: one\ntitle: two"),
            legacy().replace("custom: 未知: 字段", " unparseable continuation"),
            legacy().replace("type: general", "format_version: 2\ntype: general"),
            legacy().replace("type: general", "'format_version': 2\ntype: general"),
            "---\nformat_version: 1\nid: [not-a-string]\n---\nbody",
        ]
        for text in bad:
            p.write_text(text)
            raw = p.read_bytes()
            self.error("FORMAT_ERROR", lambda: self.repo.read(LEGACY_ID))
            self.assertEqual(p.read_bytes(), raw)
        p.write_bytes(b"\xff")
        self.error("FORMAT_ERROR", lambda: self.repo.read(LEGACY_ID))

    def test_derived_queries_ignore_index_and_inspect_reports_corruption(self):
        n = self.repo.create(FIELDS)
        idx = self.ws / "notes_index.json"
        idx.write_text(json.dumps({"notes": [{"id": n.id}, {"id": n.id},
                                              {"id": LEGACY_ID}]}))
        report = self.repo.inspect()
        codes = {x["code"] for x in report["issues"]}
        self.assertTrue({"INDEX_DUPLICATE", "INDEX_MISSING_FILE"} <= codes)
        blocked_copy = self.root / "blocked-export"
        blocked_copy.mkdir()
        self.error("FORMAT_ERROR", lambda: self.repo.export(blocked_copy))
        self.assertEqual(list(blocked_copy.iterdir()), [])

        self.assertEqual(len(self.repo.list()), 1)
        self.assertEqual(self.repo.search("body")[0].id, n.id)
        self.assertEqual(self.repo.summary()["total_notes"], 1)
        idx.unlink()
        self.assertEqual(self.repo.list()[0].id, n.id)
        self.assertFalse(idx.exists())
        idx.write_text('{"notes":[]}')
        self.assertIn("INDEX_UNLISTED_FILE", {x["code"] for x in self.repo.inspect()["issues"]})

    def test_manual_edit_immediate_read_stale_conflict_and_pause_restart(self):
        n = self.repo.create(FIELDS)
        n.path.write_text(n.path.read_text().replace("body", "manual"))
        edited = self.repo.read(n.id)
        self.assertIn("manual", edited.content)
        self.error("CONFLICT", lambda: self.repo.update(n.id, {"content": "stale"}, n.etag))
        control = ManualEditController(self.repo)
        session = control.begin()
        with FileNoteRepository(self.ws) as restarted:
            self.error("WRITES_PAUSED", lambda: restarted.create(FIELDS))
            self.error("WRITES_PAUSED", lambda: restarted.update(n.id, {}, edited.etag))
            self.error("WRITES_PAUSED", lambda: restarted.delete(n.id, edited.etag))
            self.assertEqual(restarted.read(n.id).etag, edited.etag)
            n.path.write_text("")
            self.error("FORMAT_ERROR", lambda: ManualEditController(restarted).end(session["session_token"]))
            self.assertTrue(restarted.inspect()["paused"])
            n.path.write_text(legacy(n.id))
            self.error("CONFLICT", lambda: control.end("wrong-token"))
            control.end(session["session_token"])
        self.error("CONFLICT", lambda: self.repo.update(n.id, {}, edited.etag))

    def test_non_atomic_save_and_cas_after_check_race_is_documented(self):
        n = self.repo.create(FIELDS)
        n.path.write_text("")
        self.error("FORMAT_ERROR", lambda: self.repo.read(n.id))
        # Even valid metadata with incomplete body is indistinguishable from a
        # deliberate edit; a maintenance window does not prevent mid-save reads.
        n.path.write_text(legacy(n.id))
        current = self.repo.read(n.id)
        n.path.write_text(n.path.read_text().replace("正文\n\n尾部\n", "partial"))
        self.assertEqual(self.repo.read(n.id).content, "partial")
        n.path.write_text(legacy(n.id))
        ready, saved = threading.Event(), threading.Event()
        def editor():
            if ready.wait(5):
                n.path.write_text(legacy(n.id).replace("正文", "manual-save"))
                saved.set()
        thread = threading.Thread(target=editor)
        thread.start()
        def manual(stage):
            if stage == "before_replace":
                ready.set()
                self.assertTrue(saved.wait(5))
        self.repo._checkpoint = manual
        result = self.repo.update(n.id, {"content": "agent-save"}, current.etag)
        self.assertEqual(result.content, "agent-save")  # remaining race, NOT protection
        self.assertNotIn("manual-save", result.content)
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_fault_boundaries_and_commit_uncertain(self):
        for stage in ["temp_opened", "temp_written", "file_fsynced", "before_replace", "replaced", "dir_fsynced"]:
            n = self.repo.create(FIELDS)
            def fault(at):
                if at == stage:
                    raise OSError("injected")
            self.repo._checkpoint = fault
            expected = "COMMIT_UNCERTAIN" if stage in ("replaced", "dir_fsynced") else "IO_ERROR"
            exc = self.error(expected, lambda: self.repo.update(n.id, {"content": "new"}, n.etag))
            self.assertEqual(exc.persisted, "unknown" if expected == "COMMIT_UNCERTAIN" else False)
            self.repo._checkpoint = lambda _: None
            actual = self.repo.read(n.id)
            self.assertIn(actual.content, [n.content, "new"])
            if expected == "COMMIT_UNCERTAIN":
                self.assertEqual(actual.content, "new")
                self.error("CONFLICT", lambda: self.repo.update(n.id, {}, n.etag))
        self.assertEqual(list(self.ws.glob(".note-tmp-*")), [])

    def test_real_fsync_replace_errors_and_delete_uncertain(self):
        n = self.repo.create(FIELDS)
        with patch("storage.file_notes.os.fsync", side_effect=OSError("file sync")):
            self.error("IO_ERROR", lambda: self.repo.update(n.id, {}, n.etag))
        self.assertEqual(self.repo.read(n.id).etag, n.etag)
        with patch("storage.file_notes.os.replace", side_effect=OSError("rename")):
            self.error("COMMIT_UNCERTAIN", lambda: self.repo.update(n.id, {}, n.etag))
        real = os.fsync
        def fail_dir(fd):
            import stat
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("directory sync")
            real(fd)
        with patch("storage.file_notes.os.fsync", side_effect=fail_dir):
            self.error("COMMIT_UNCERTAIN", lambda: self.repo.delete(n.id, n.etag))
        self.error("NOT_FOUND", lambda: self.repo.read(n.id))

    def test_temp_name_collision_never_removes_existing_file(self):
        from uuid import UUID
        token = UUID(int=17)
        stale = self.ws / (".note-tmp-" + token.hex)
        stale.write_bytes(b"protected orphan temp")
        with patch("storage.file_notes.uuid.uuid4", return_value=token):
            self.error("IO_ERROR", lambda: self.repo.create(FIELDS))
        self.assertEqual(stale.read_bytes(), b"protected orphan temp")
        self.assertEqual(self.repo.list(), [])

    def test_new_yaml_roundtrip_unknown_nested_and_invalid_alias_not_committed(self):
        n = self.repo.create({**FIELDS, "title": "多行\n标题: 引号\"",
                              "extra": {"nested": {"items": [1, {"键": "值"}]}}})
        same = self.repo.read(n.id)
        self.assertEqual(same.title, n.title)
        self.assertEqual(same.content, FIELDS["content"])
        self.assertEqual(same.extra["nested"], {"items": [1, {"键": "值"}]})
        alias = []
        before = len(self.repo.list())
        self.error("FORMAT_ERROR", lambda: self.repo.create(
            {**FIELDS, "extra": {"a": alias, "b": alias}}))
        self.assertEqual(len(self.repo.list()), before)
        raw = n.path.read_text()
        n.path.write_text(raw.replace("format_version: 1", "format_version: 1\nformat_version: 1"))
        self.error("FORMAT_ERROR", lambda: self.repo.read(n.id))

    def test_file_fsync_precedes_replace_and_directory_fsync(self):
        import stat
        real_sync, real_replace = os.fsync, os.replace
        calls = []
        def sync(fd):
            calls.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
            return real_sync(fd)
        def replace(*a, **k):
            calls.append("replace")
            return real_replace(*a, **k)
        with patch("storage.file_notes.os.fsync", side_effect=sync), \
             patch("storage.file_notes.os.replace", side_effect=replace):
            self.repo.create(FIELDS)
        self.assertEqual(calls, ["file", "replace", "directory"])

    def test_corrupt_pause_control_fails_closed_and_uncertain_begin_is_observable(self):
        control = self.ws / ".notes-control.json"
        control.write_text('{"generation":0,"session_token":null,"session_token":null}')
        self.error("FORMAT_ERROR", lambda: self.repo.create(FIELDS))
        control.unlink()
        def fault(stage):
            if stage == "replaced":
                raise OSError("lost acknowledgement")
        self.repo._checkpoint = fault
        with patch("storage.manual_edit.secrets.token_hex", return_value="ab"*32):
            self.error("COMMIT_UNCERTAIN", lambda: ManualEditController(self.repo).begin())
        self.repo._checkpoint = lambda _: None
        with FileNoteRepository(self.ws) as restarted:
            self.assertTrue(restarted.inspect()["paused"])
            self.error("WRITES_PAUSED", lambda: restarted.create(FIELDS))
        ManualEditController(self.repo).end("ab"*32)

    def test_atomic_reader_sees_complete_notes_without_using_repository_lock(self):
        from storage.note_codec import decode
        n = self.repo.create({**FIELDS, "content": "A"*32768})
        started, stop = threading.Event(), threading.Event()
        errors, observations = [], []
        def reader():
            started.set()
            while not stop.is_set():
                try:
                    value = decode(n.path.read_bytes(), n.id, n.path).content
                    if value not in ("A"*32768, "B"*32768):
                        raise AssertionError("partial body")
                    observations.append(len(value))
                except Exception as exc:
                    errors.append(exc)
                    break
        thread = threading.Thread(target=reader)
        thread.start()
        self.assertTrue(started.wait(3))
        try:
            for i in range(40):
                n = self.repo.update(n.id, {"content": ("A" if i % 2 else "B")*32768}, n.etag)
        finally:
            stop.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(observations)

    def test_storage_stays_independent_of_framework(self):
        code = ("import sys; sys.path.insert(0,sys.argv[1]); "
                "import storage.file_notes,storage.manual_edit; "
                "assert 'hello_agents' not in sys.modules; "
                "assert 'agent' not in sys.modules")
        p = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(SRC)],
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_cli_explicit_workspace_and_snapshot_export_rollback(self):
        script = SRC.parent / "scripts/notes_admin.py"
        def cli(*args):
            return subprocess.run([sys.executable, "-B", str(script), *args],
                                  capture_output=True, text=True, timeout=10)
        self.assertNotEqual(cli("inspect").returncode, 0)
        # Protected SOURCE and all rehearsal directories are under TemporaryDirectory.
        p = self.ws / (LEGACY_ID + ".md")
        p.write_text(legacy())
        protected = p.read_bytes()
        destination = self.root / "copy"
        destination.mkdir()
        result = cli("export", "--workspace", str(self.ws), "--destination", str(destination))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((destination / p.name).read_bytes(), protected)
        with FileNoteRepository(destination) as copy:
            old = copy.read(LEGACY_ID)
            changed = copy.update(old.id, {"content": "candidate"}, old.etag)
            self.assertEqual(changed.content, "candidate")
        # Cutover selects candidate directory; rollback selects protected source,
        # rather than copying old data on top of new files.
        selected_workspace = destination
        with FileNoteRepository(selected_workspace) as selected:
            self.assertEqual(selected.read(LEGACY_ID).content, "candidate")
        selected_workspace = self.ws
        with FileNoteRepository(selected_workspace) as selected:
            self.assertEqual(selected.read(LEGACY_ID).content, "正文\n\n尾部\n")
        with FileNoteRepository(destination) as retained:
            self.assertEqual(retained.read(LEGACY_ID).content, "candidate")
        self.assertEqual(p.read_bytes(), protected)
        self.assertNotEqual(cli("export", "--workspace", str(self.ws),
                                "--destination", str(destination)).returncode, 0)
        begin = cli("manual-begin", "--workspace", str(destination))
        self.assertEqual(begin.returncode, 0, begin.stderr)
        token = json.loads(begin.stdout)["session_token"]
        end = cli("manual-end", "--workspace", str(destination), "--token", token)
        self.assertEqual(end.returncode, 0, end.stderr)

if __name__ == "__main__":
    unittest.main()
