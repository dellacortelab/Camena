"""SQLite storage. One owner, tiny tables, so plain sqlite3 behind a lock.

Every query here is a single-row or small-list operation that finishes in well
under a millisecond, so calling it straight from async code is fine.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY,
    text        TEXT NOT NULL,
    topic       TEXT NOT NULL DEFAULT 'general',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS list_items (
    id          INTEGER PRIMARY KEY,
    list_name   TEXT NOT NULL,
    text        TEXT NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS list_items_by_list ON list_items(list_name, done);
CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY,
    text        TEXT NOT NULL,
    due_at      TEXT NOT NULL,            -- UTC ISO-8601
    fired_at    TEXT,
    cancelled   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    schedule    TEXT NOT NULL,            -- see schedule.py
    next_run_at TEXT,                     -- UTC ISO-8601, NULL once finished
    last_run_at TEXT,
    last_result TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inbox (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,            -- 'reminder' | 'task' | 'system'
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    read        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    thread      TEXT NOT NULL,
    role        TEXT NOT NULL,            -- 'user' | 'assistant' | 'event'
    text        TEXT NOT NULL,
    image       TEXT,                     -- upload filename
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_by_thread ON messages(thread, id);
CREATE TABLE IF NOT EXISTS actions (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,            -- 'chat' | 'task: <title>' | 'shortcut'
    tool        TEXT NOT NULL,
    summary     TEXT NOT NULL,
    outcome     TEXT NOT NULL,            -- 'ran' | 'approved' | 'blocked'
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint    TEXT PRIMARY KEY,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Path):
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def run(self, sql: str, params: tuple = ()) -> int:
        """Execute a write; returns lastrowid for inserts, rowcount otherwise."""
        with self._lock:
            cur = self._conn.execute(sql, params)
            return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount

    # --- key/value -------------------------------------------------------

    def get_json(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM kv WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def set_json(self, key: str, value: Any) -> None:
        self.run(
            "INSERT INTO kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    # --- conversation log -------------------------------------------------

    def log_message(self, thread: str, role: str, text: str, image: str | None = None) -> int:
        return self.run(
            "INSERT INTO messages(thread, role, text, image, created_at) VALUES(?,?,?,?,?)",
            (thread, role, text, image, iso(utcnow())),
        )

    def log_action(self, source: str, tool: str, summary: str, outcome: str) -> int:
        return self.run(
            "INSERT INTO actions(source, tool, summary, outcome, created_at) VALUES(?,?,?,?,?)",
            (source, tool, summary, outcome, iso(utcnow())),
        )

    def add_inbox(self, source: str, title: str, body: str) -> int:
        return self.run(
            "INSERT INTO inbox(source, title, body, created_at) VALUES(?,?,?,?)",
            (source, title, body, iso(utcnow())),
        )
