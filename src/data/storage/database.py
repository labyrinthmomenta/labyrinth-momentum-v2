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

        self._migrate_security_data_status_check()

    def _migrate_security_data_status_check(self) -> None:
        """Allow newer data-status values in databases created by older V2 builds."""
        row = self.conn.execute(
            """SELECT sql
               FROM sqlite_master
               WHERE type='table' AND name='security_data_status'"""
        ).fetchone()

        if row is None:
            return

        table_sql = row["sql"] or ""
        if "INSUFFICIENT_TRADING_DATA" in table_sql:
            return

        # SQLite cannot ALTER an existing CHECK constraint in place, so rebuild
        # this small audit table while preserving all existing status history.
        self.conn.execute(
            "ALTER TABLE security_data_status RENAME TO security_data_status_legacy"
        )

        self.conn.execute(
            """
            CREATE TABLE security_data_status (
                run_id INTEGER NOT NULL,
                security_id INTEGER NOT NULL,
                as_of_date TEXT NOT NULL,
                provider TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK (
                        status IN (
                            'OK',
                            'PROVIDER_UNAVAILABLE',
                            'INSUFFICIENT_TRADING_DATA'
                        )
                    ),
                message TEXT,
                recorded_at TEXT NOT NULL,
                PRIMARY KEY (run_id, security_id),
                FOREIGN KEY (run_id) REFERENCES pipeline_runs(run_id),
                FOREIGN KEY (security_id) REFERENCES securities(security_id)
            )
            """
        )

        self.conn.execute(
            """
            INSERT INTO security_data_status
                (run_id, security_id, as_of_date, provider, status, message, recorded_at)
            SELECT
                run_id, security_id, as_of_date, provider, status, message, recorded_at
            FROM security_data_status_legacy
            """
        )

        self.conn.execute("DROP TABLE security_data_status_legacy")

        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_security_data_status_security_date
            ON security_data_status(security_id, as_of_date)
            """
        )

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
