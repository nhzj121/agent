"""Owned task/final-report notes and explicit opt-in workflow integration."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "code/chapter14/helloagents-deepresearch/backend/src"
sys.path.insert(0, str(SRC))
from agent import DeepResearchAgent
from config import Configuration
from models import SummaryState, TodoItem
from services.agent_adapter import ProjectToolAwareAgent
from services.note_versions import NoteScope
from services.note_ownership import NoteOwnership
from services.reporter import ReportingService
from storage.file_notes import FileNoteRepository
from storage.note_repository import NoteError
from test_phase_2b_versions import FakeLLM
from test_phase_2b_tool_adapter import call


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = FileNoteRepository(self.temp.name)
        self.addCleanup(self.repo.close)
        self.owner = NoteOwnership(self.repo, "run")
        self.scope = NoteScope("run", "final_report")
        for name in ["socket.socket.connect", "socket.getaddrinfo"]:
            guard = patch(name, side_effect=AssertionError("external API forbidden"))
            guard.start()
            self.addCleanup(guard.stop)

    def agent(self, script, owner=None, scope=None):
        return ProjectToolAwareAgent(
            llm=FakeLLM(script), repository=self.repo, ownership=owner or self.owner,
            scope=scope or self.scope, name="report", system_prompt="report")

    def error(self, code, callback):
        with self.assertRaises(NoteError) as exc:
            callback()
        self.assertEqual(exc.exception.code, code)

    def test_ordinary_conclusion_and_other_run_are_not_final_report(self):
        regular = self.repo.create({"title": "研究报告 misleading", "content": "task-data",
            "note_type": "conclusion", "extra": {"run_id": "run", "purpose": "task", "task_id": 1}})
        foreign = NoteOwnership(self.repo, "foreign")
        foreign_note = foreign.create({"title": "report", "content": "foreign"},
                                      NoteScope("foreign", "final_report"))[0]
        a = self.agent(lambda i, m: "new-report")
        a.run("topic")
        result = self.owner.persist_report(a.generated_text, "report")
        self.assertNotIn(result.note_id, [regular.id, foreign_note.id])
        self.assertEqual(self.repo.read(regular.id).content, "task-data")
        self.assertEqual(self.repo.read(foreign_note.id).content, "foreign")
        self.assertEqual(self.owner.persist_report(a.generated_text, "report"), result)
        self.assertEqual(len(self.repo.list()), 3)

    def test_existing_report_without_basis_fails_and_stale_basis_conflicts(self):
        report = self.owner.create({"title": "report", "content": "old"}, self.scope)[0]
        a = self.agent(lambda i, m: "new")
        a.run("topic")
        self.error("READ_REQUIRED", lambda: self.owner.persist_report(a.generated_text, "report"))
        a = self.agent(lambda i, m: [call("read", report.id), "new"][i])
        a.run("topic")
        self.repo.update(report.id, {"content": "external"}, report.etag)
        self.error("CONFLICT", lambda: self.owner.persist_report(a.generated_text, "report"))
        self.assertEqual(self.repo.read(report.id).content, "external")

    def test_reporter_create_and_final_persist_are_one_note(self):
        a = self.agent(lambda i, m: [
            '[TOOL_CALL:note:{"action":"create","title":"report","note_type":"conclusion","content":"draft"}]',
            "<think>secret</think>final-report"][i])
        service = ReportingService(a, Configuration(enable_notes=False))
        text = service.generate_report(SummaryState(research_topic="topic"))
        self.assertEqual(text, "final-report")
        self.assertEqual(service.generated_text.text, text)
        self.assertEqual(len(service.generated_text.basis.receipts), 1)
        result = self.owner.persist_report(service.generated_text, "report")
        self.assertEqual(len(self.repo.list()), 1)
        self.assertEqual(self.repo.read(result.note_id).content, text)
        self.assertEqual(self.owner.persist_report(service.generated_text, "report"), result)

    def test_duplicate_create_is_id_only_and_cannot_overwrite(self):
        n = self.owner.create({"title": "report", "content": "protected"}, self.scope)[0]
        a = self.agent(lambda i, m: [
            '[TOOL_CALL:note:{"action":"create","title":"report","content":"bad"}]', "new"][i])
        a.run("topic")
        self.assertEqual(len(a.generated_text.basis.receipts), 0)
        self.error("READ_REQUIRED", lambda: self.owner.persist_report(a.generated_text, "report"))
        self.assertEqual(len(self.repo.list()), 1)
        self.assertEqual(self.repo.read(n.id).content, "protected")

    def test_parallel_directory_scans_have_independent_cursors(self):
        for i in range(8):
            self.repo.create({"title": str(i), "content": "x"})
        expected = set(n.id + ".md" for n in self.repo.list())
        def scans(_):
            for i in range(150):
                names = self.repo._names()
                if set(names) != expected or len(names) != len(expected):
                    return names
            return None
        with ThreadPoolExecutor(8) as pool:
            bad = [x for x in pool.map(scans, range(8)) if x is not None]
        self.assertEqual(bad, [])

    def test_atomic_identity_creation_across_owner_instances(self):
        def work(i):
            owner = NoteOwnership(self.repo, "shared")
            agent = self.agent(lambda j, m: str(i), owner, NoteScope("shared", "final_report"))
            agent.run("topic")
            try:
                return owner.persist_report(agent.generated_text, "report").note_id
            except NoteError as exc:
                self.assertEqual(exc.code, "READ_REQUIRED")
                return None
        with ThreadPoolExecutor(8) as pool:
            values = list(pool.map(work, range(8)))
        self.assertEqual(sum(x is not None for x in values), 1)
        self.assertEqual(len(self.repo.list()), 1)

    def test_binding_is_projection_and_cannot_upgrade_frozen_basis(self):
        scope = NoteScope("run", "task", 1)
        n = self.owner.create({"title": "t", "content": "v1"}, scope)[0]
        def script(i, m):
            if i == 0:
                return call("read", n.id)
            if i == 1:
                latest = self.repo.update(n.id, {"content": "manual-v2"}, n.etag)
                self.owner.bind(latest)  # display now shows v2
                return call("update", n.id, content="stale")
            return "done"
        a = self.agent(script, scope=scope)
        a.run("topic")
        self.assertEqual(a.results[-1].status.error_code, "CONFLICT")
        self.assertEqual(self.owner.binding(1).etag, self.repo.read(n.id).etag)

    def test_sync_and_stream_opt_in_workflow_never_construct_legacy_tool(self):
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                coordinator = None
                def script(i, messages):
                    if i == 0:
                        return '{"tasks":[{"title":"t","intent":"i","query":"q"}]}'
                    if i == 1:
                        return '[TOOL_CALL:note:{"action":"create","title":"task","content":"task-note"}]'
                    if i == 2:
                        return "task-summary"
                    if i == 3:
                        note_id = coordinator._note_owner.binding(1).note_id
                        return call("read", note_id) + (
                            '[TOOL_CALL:note:{"action":"create","title":"report","content":"draft"}]')
                    return "final-report"
                llm = FakeLLM(script)
                config = Configuration(enable_notes=True, notes_workspace="/must-not-open-existing-notes")
                with patch.object(DeepResearchAgent, "_init_llm", return_value=llm), \
                     patch("agent.NoteTool", side_effect=AssertionError("legacy must not construct")), \
                     patch("agent.dispatch_search", return_value=(
                         {"results": [{"url": "https://fake.invalid"}]}, [], "", "fake")), \
                     patch("agent.prepare_research_context", return_value=("sources", "context")):
                    coordinator = DeepResearchAgent(config, note_repository=self.repo)
                    if streaming:
                        events = list(coordinator.run_stream("topic"))
                        self.assertEqual(events[-1]["type"], "done")
                        self.assertEqual(events[-1]["run_status"], "completed")
                        self.assertTrue(events[-1]["run_id"])
                        self.assertEqual(events[-2]["report"], "final-report")
                        self.assertEqual(sum(e["type"] == "report_note" for e in events), 1)
                    else:
                        result = coordinator.run("topic")
                        self.assertEqual(result.report_markdown, "final-report")
                        self.assertIsNotNone(result.todo_items[0].note_id)
                self.assertTrue(coordinator.last_note_result.ok)
                run_id = coordinator._note_owner.run_id
                notes = [n for n in self.repo.list() if n.extra.get("run_id") == run_id]
                self.assertEqual(len(notes), 2)
                self.assertEqual(sum(n.extra["purpose"] == "final_report" for n in notes), 1)
                self.assertEqual(len(llm.messages), 5)

if __name__ == "__main__":
    unittest.main()
