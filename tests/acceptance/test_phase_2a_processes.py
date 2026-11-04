"""Real Linux multi-process locks and termination boundaries, temporary data only."""
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "code/chapter14/helloagents-deepresearch/backend/src"
sys.path.insert(0, str(SRC))
from storage.file_notes import FileNoteRepository
from storage.manual_edit import ManualEditController
from storage.note_repository import NoteError

def create_many(path):
    with FileNoteRepository(path) as repo:
        return [repo.create({"title": "process", "content": str(i)}).id for i in range(25)]

def boundary_writer(path, note_id, etag, stage, conn):
    with FileNoteRepository(path) as repo:
        def hook(at):
            if at == stage:
                conn.send("reached")
                conn.recv()
        repo._checkpoint = hook
        repo.update(note_id, {"content": "new-complete"}, etag)

def paused_writer(path):
    with FileNoteRepository(path) as repo:
        try:
            repo.create({"title": "x", "content": "x"})
        except NoteError as exc:
            return exc.code
    return "unexpected success"


def cas_writer(path, note_id, etag, conn):
    with FileNoteRepository(path) as repo:
        conn.send("ready")
        conn.recv()
        try:
            repo.update(note_id, {"title": "process-update"}, etag)
            conn.send("ok")
        except NoteError as exc:
            conn.send(exc.code)

class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.ctx = mp.get_context("spawn")

    def test_cross_process_same_etag_only_one_commit(self):
        with FileNoteRepository(self.path) as repo:
            n = repo.create({"title": "t", "content": "old"})
            pipes = [self.ctx.Pipe() for _ in range(2)]
            workers = [self.ctx.Process(target=cas_writer,
                       args=(str(self.path), n.id, n.etag, child)) for _, child in pipes]
            try:
                for worker in workers:
                    worker.start()
                for parent, _ in pipes:
                    self.assertTrue(parent.poll(10))
                    self.assertEqual(parent.recv(), "ready")
                for parent, _ in pipes:
                    parent.send("go")
                results = []
                for parent, _ in pipes:
                    self.assertTrue(parent.poll(10))
                    results.append(parent.recv())
                self.assertCountEqual(results, ["ok", "CONFLICT"])
                self.assertEqual(repo.read(n.id).title, "process-update")
            finally:
                for worker in workers:
                    worker.join(10)
                    if worker.is_alive():
                        worker.kill()
                        worker.join(10)
                for parent, child in pipes:
                    parent.close()
                    child.close()

    def test_four_processes_create_hundred(self):
        with ProcessPoolExecutor(4, mp_context=self.ctx) as pool:
            groups = list(pool.map(create_many, [str(self.path)]*4))
        ids = [n for group in groups for n in group]
        self.assertEqual(len(set(ids)), 100)
        with FileNoteRepository(self.path) as repo:
            self.assertEqual(len(repo.list()), 100)

    def test_kill_at_write_boundaries_always_whole_file(self):
        for stage in ["temp_opened", "temp_written", "file_fsynced", "before_replace", "replaced", "dir_fsynced"]:
            with self.subTest(stage=stage), FileNoteRepository(self.path) as repo:
                n = repo.create({"title": "t", "content": "old-complete"})
                parent, child = self.ctx.Pipe()
                p = self.ctx.Process(target=boundary_writer,
                                     args=(str(self.path), n.id, n.etag, stage, child))
                p.start()
                try:
                    self.assertTrue(parent.poll(10), "writer did not reach boundary")
                    self.assertEqual(parent.recv(), "reached")
                    p.terminate()
                    p.join(10)
                    self.assertFalse(p.is_alive())
                finally:
                    if p.is_alive():
                        p.kill()
                    p.join(10)
                    parent.close()
                    child.close()
                result = repo.read(n.id)
                self.assertEqual(result.content, "new-complete" if stage in
                                 ("replaced", "dir_fsynced") else "old-complete")
                # Stale temp files from a killed writer are not live notes.
                self.assertTrue(all(x.id for x in repo.list()))

    def test_manual_begin_waits_for_commit_and_persists_across_processes(self):
        with FileNoteRepository(self.path) as repo:
            n = repo.create({"title": "t", "content": "old"})
            parent, child = self.ctx.Pipe()
            p = self.ctx.Process(target=boundary_writer,
                                 args=(str(self.path), n.id, n.etag, "before_replace", child))
            p.start()
            sessions, errors = [], []
            started, done = threading.Event(), threading.Event()
            def begin():
                started.set()
                try:
                    sessions.append(ManualEditController(repo).begin())
                except Exception as exc:
                    errors.append(exc)
                finally:
                    done.set()
            try:
                self.assertTrue(parent.poll(10))
                parent.recv()
                thread = threading.Thread(target=begin)
                thread.start()
                self.assertTrue(started.wait(3))
                self.assertFalse(done.wait(.1), "begin returned while commit holds lock")
                parent.send("release")
                p.join(10)
                thread.join(10)
                self.assertTrue(done.is_set())
                self.assertEqual(errors, [])
                self.assertEqual(repo.read(n.id).content, "new-complete")
                with ProcessPoolExecutor(1, mp_context=self.ctx) as pool:
                    self.assertEqual(pool.submit(paused_writer, str(self.path)).result(10),
                                     "WRITES_PAUSED")
                ManualEditController(repo).end(sessions[0]["session_token"])
            finally:
                if p.is_alive():
                    p.kill()
                p.join(10)
                parent.close()
                child.close()

if __name__ == "__main__":
    unittest.main()
