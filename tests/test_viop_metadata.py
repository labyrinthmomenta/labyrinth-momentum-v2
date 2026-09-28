from __future__ import annotations

import sqlite3

from src.data.storage.database import Database
from src.data.universe.manager import UniverseManager, UniverseRecord


def test_universe_manager_persists_viop_metadata(tmp_path):
    db = Database(tmp_path / "viop.db")
    db.initialize()

    manager = UniverseManager(db.conn)

    sid = manager.upsert(
        UniverseRecord(
            ticker="TEST",
            name="Test A.S.",
            is_viop=1,
            viop_source="BIST_VIOP_UNDERLYINGS",
            viop_as_of="2026-09-24",
        ),
        as_of="2026-09-24",
    )
    db.conn.commit()

    row = db.conn.execute(
        """
        SELECT is_viop, viop_source, viop_as_of
        FROM securities
        WHERE security_id=?
        """,
        (sid,),
    ).fetchone()

    assert row["is_viop"] == 1
    assert row["viop_source"] == "BIST_VIOP_UNDERLYINGS"
    assert row["viop_as_of"] == "2026-09-24"

    # VIOP membership is dynamic and can later be removed.
    manager.upsert(
        UniverseRecord(
            ticker="TEST",
            name="Test A.S.",
            is_viop=0,
            viop_source="BIST_VIOP_UNDERLYINGS",
            viop_as_of="2026-10-01",
        ),
        as_of="2026-10-01",
    )
    db.conn.commit()

    row = db.conn.execute(
        """
        SELECT is_viop, viop_source, viop_as_of
        FROM securities
        WHERE security_id=?
        """,
        (sid,),
    ).fetchone()

    assert row["is_viop"] == 0
    assert row["viop_as_of"] == "2026-10-01"

    db.close()


def test_existing_database_gets_viop_columns(tmp_path):
    path = tmp_path / "old.db"

    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE securities (
            security_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            sector TEXT,
            industry TEXT,
            instrument_type TEXT NOT NULL DEFAULT 'EQUITY',
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            first_trade_date TEXT,
            last_trade_date TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    db = Database(path)
    db.initialize()

    columns = {
        row["name"]
        for row in db.conn.execute(
            "PRAGMA table_info(securities)"
        ).fetchall()
    }

    assert "is_viop" in columns
    assert "viop_source" in columns
    assert "viop_as_of" in columns

    db.close()
