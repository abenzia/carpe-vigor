"""State, in one SQLite file: the person's profile, the week's plan, the pantry, the budget, orders, the week log.

Single-user on purpose (a demo, a judge's laptop). Everything is JSON in a key/value table, read and
written whole: no migrations to run, nothing to set up.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from . import config


class Store:
    def __init__(self, path: Path | str = config.DB_PATH):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS log (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT DEFAULT CURRENT_TIMESTAMP, kind TEXT, data TEXT)")
        self.conn.commit()

    def get(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key: str, value: Any):
        self.conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, json.dumps(value, ensure_ascii=False, default=str)))
        self.conn.commit()

    def delete(self, key: str):
        self.conn.execute("DELETE FROM kv WHERE key = ?", (key,))
        self.conn.commit()

    def log(self, kind: str, data: dict):
        self.conn.execute("INSERT INTO log (kind, data) VALUES (?, ?)", (kind, json.dumps(data, ensure_ascii=False, default=str)))
        self.conn.commit()

    def events(self, kind: str | None = None) -> list[dict]:
        q = "SELECT at, kind, data FROM log" + (" WHERE kind = ?" if kind else "") + " ORDER BY id DESC"
        rows = self.conn.execute(q, (kind,) if kind else ()).fetchall()
        return [{"at": at, "kind": k, **json.loads(d)} for at, k, d in rows]

    def reset(self):
        self.conn.execute("DELETE FROM kv")
        self.conn.execute("DELETE FROM log")
        self.conn.commit()
