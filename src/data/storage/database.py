from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")

    def initialize(self) -> None:
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._apply_compatibility_migrations()
        self.conn.commit()

    def _apply_compatibility_migrations(self) -> None:
        """Small additive migrations for V2 development databases.

        V2 is still pre-release, but this keeps databases created by an earlier
        starter ZIP usable as new audit columns are added.
        """
        columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(pipeline_runs)").fetchall()
        }
        if "fetched_bars" not in columns:
            self.conn.execute("ALTER TABLE pipeline_runs ADD COLUMN fetched_bars INTEGER DEFAULT 0")
        if "provider_calls" not in columns:
            self.conn.execute("ALTER TABLE pipeline_runs ADD COLUMN provider_calls INTEGER DEFAULT 0")

    def execute(self, sql: str, params: tuple = ()):
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def executemany(self, sql: str, rows: Iterable[tuple]) -> None:
        self.conn.executemany(sql, rows)
        self.conn.commit()

    def close(self) -> None:
        # Persist committed WAL pages into the main database before artifacts are
        # committed by CI. Do not auto-commit an open transaction.
        try:
            if not self.conn.in_transaction:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass
        self.conn.close()
