"""SQLite storage for research metadata, task results and reports only.

No API credentials, process logs, tool calls or streaming events are stored.
"""

import fcntl
import json
import sqlite3
from pathlib import Path
from threading import RLock


class ResearchStorageError(RuntimeError):
    """History could not be read or committed; never silently replace it."""


class SQLiteResearchStore:
    def __init__(self, path: str):
        if path == ":memory:":
            self.path = path
        else:
            target = Path(path).expanduser()
            if not target.is_absolute():
                target = Path(__file__).resolve().parents[2] / target
            self.path = str(target.resolve())
        self._connection = None
        self.epoch = ""
        self._lock_file = None
        self._lock = RLock()

    def open(self):
        with self._lock:
            if self._connection is not None:
                return
            try:
                if self.path != ":memory:":
                    Path(self.path).parent.mkdir(parents=True, exist_ok=True)
                    self._lock_file = open(self.path + ".lock", "a")
                    # A second backend must not mark the first backend's live jobs interrupted.
                    fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
                self._connection.execute("PRAGMA foreign_keys=ON")
                self._connection.execute("PRAGMA journal_mode=WAL")
                self._connection.execute("PRAGMA synchronous=FULL")
                version = self._connection.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise ResearchStorageError(f"不支持的研究数据库版本：{version}")
                with self._connection:
                    self._connection.executescript("""
                        CREATE TABLE IF NOT EXISTS researches (
                            research_id TEXT PRIMARY KEY,
                            created_at TEXT NOT NULL,
                            status TEXT NOT NULL,
                            metadata_json TEXT NOT NULL
                        );
                        CREATE TABLE IF NOT EXISTS research_store_meta (
                            key TEXT PRIMARY KEY, value INTEGER NOT NULL
                        );
                        CREATE INDEX IF NOT EXISTS research_created_at ON researches(created_at);
                        CREATE TABLE IF NOT EXISTS research_tasks (
                            research_id TEXT NOT NULL REFERENCES researches(research_id) ON DELETE CASCADE,
                            task_id INTEGER NOT NULL,
                            position INTEGER NOT NULL,
                            payload_json TEXT NOT NULL,
                            PRIMARY KEY (research_id, task_id)
                        );
                        CREATE TABLE IF NOT EXISTS research_reports (
                            research_id TEXT PRIMARY KEY REFERENCES researches(research_id) ON DELETE CASCADE,
                            markdown TEXT NOT NULL,
                            note_id TEXT,
                            note_path TEXT
                        );
                        PRAGMA user_version=1;
                    """)
                    self._connection.execute("INSERT OR IGNORE INTO research_store_meta VALUES ('boot_generation', 0)")
                    self._connection.execute("UPDATE research_store_meta SET value=value+1 WHERE key='boot_generation'")
                    self.epoch = str(self._connection.execute(
                        "SELECT value FROM research_store_meta WHERE key='boot_generation'"
                    ).fetchone()[0])
            except Exception as exc:
                self.close()
                raise ResearchStorageError(f"无法打开研究历史数据库：{exc}") from exc

    def save(self, result: dict):
        self.open()
        metadata = {key: result.get(key) for key in (
            "research_id", "topic", "status", "stage", "created_at", "started_at", "finished_at",
            "snapshot_seq", "error", "outcome", "notes_workspace"
        )}
        try:
            with self._lock, self._connection:
                self._connection.execute("""
                    INSERT INTO researches VALUES (?, ?, ?, ?)
                    ON CONFLICT(research_id) DO UPDATE SET created_at=excluded.created_at,
                        status=excluded.status, metadata_json=excluded.metadata_json
                """, (result["research_id"], result["created_at"], result["status"],
                      json.dumps(metadata, ensure_ascii=False)))
                self._connection.execute("DELETE FROM research_tasks WHERE research_id=?", (result["research_id"],))
                self._connection.executemany("INSERT INTO research_tasks VALUES (?, ?, ?, ?)", [
                    (result["research_id"], task["id"], index, json.dumps(task, ensure_ascii=False))
                    for index, task in enumerate(result["todo_items"])
                ])
                self._connection.execute("""
                    INSERT INTO research_reports VALUES (?, ?, ?, ?)
                    ON CONFLICT(research_id) DO UPDATE SET markdown=excluded.markdown,
                        note_id=excluded.note_id, note_path=excluded.note_path
                """, (result["research_id"], result["report_markdown"],
                      result.get("report_note_id"), result.get("report_note_path")))
        except Exception as exc:
            raise ResearchStorageError(f"研究历史写入失败：{exc}") from exc

    def load(self) -> list[dict]:
        self.open()
        try:
            with self._lock:
                rows = self._connection.execute("SELECT research_id, metadata_json FROM researches ORDER BY created_at, rowid").fetchall()
                results = []
                for research_id, raw in rows:
                    result = json.loads(raw)
                    tasks = self._connection.execute(
                        "SELECT payload_json FROM research_tasks WHERE research_id=? ORDER BY position", (research_id,)
                    ).fetchall()
                    result["todo_items"] = [json.loads(task[0]) for task in tasks]
                    report = self._connection.execute(
                        "SELECT markdown, note_id, note_path FROM research_reports WHERE research_id=?", (research_id,)
                    ).fetchone()
                    result["report_markdown"] = report[0] if report else ""
                    result["report_note_id"] = report[1] if report else None
                    result["report_note_path"] = report[2] if report else None
                    results.append(result)
                return results
        except Exception as exc:
            raise ResearchStorageError(f"研究历史读取失败：{exc}") from exc

    def close(self):
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            if self._lock_file is not None:
                self._lock_file.close()
                self._lock_file = None
