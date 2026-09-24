from __future__ import annotations

import sqlite3

from src.data.storage.database import Database


def test_initialize_migrates_old_security_data_status_check(tmp_path):
    path = tmp_path / "legacy.db"

    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE security_data_status (
            run_id INTEGER NOT NULL,
            security_id INTEGER NOT NULL,
            as_of_date TEXT NOT NULL,
            provider TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK (status IN ('OK', 'PROVIDER_UNAVAILABLE')),
            message TEXT,
            recorded_at TEXT NOT NULL,
            PRIMARY KEY (run_id, security_id)
        )
        """
    )
    conn.commit()
    conn.close()

    db = Database(path)
    db.initialize()

    sql = db.conn.execute(
        """SELECT sql
           FROM sqlite_master
           WHERE type='table' AND name='security_data_status'"""
    ).fetchone()[0]

    assert "INSUFFICIENT_TRADING_DATA" in sql
    db.close()
