from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.data.storage.adjustments import (
    AdjustmentRecord,
    load_price_adjustments,
    upsert_price_adjustments,
)
from src.data.storage.database import Database


def _db(tmp_path: Path) -> Database:
    db = Database(
        tmp_path / "adjustments.db"
    )
    db.initialize()

    db.conn.execute(
        """
        INSERT INTO securities(
            security_id,
            name,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            1,
            "TEST EQUITY",
            "2026-01-01T00:00:00+03:00",
            "2026-01-01T00:00:00+03:00",
        ),
    )
    db.conn.commit()

    return db


def _record(
    day: int,
    *,
    adj_close: float | None = 90.0,
    adjustment_factor: float | None = 0.90,
    dividend: float | None = 0.0,
    stock_split: float | None = 0.0,
) -> AdjustmentRecord:
    return AdjustmentRecord(
        date=date(2026, 1, day),
        adj_close=adj_close,
        adjustment_factor=adjustment_factor,
        dividend=dividend,
        stock_split=stock_split,
    )


def test_initialize_creates_price_adjustments_table(
    tmp_path: Path,
):
    db = _db(tmp_path)

    row = db.conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
          AND name='price_adjustments'
        """
    ).fetchone()

    assert row is not None

    db.close()


def test_price_adjustments_table_does_not_change_daily_prices_schema(
    tmp_path: Path,
):
    db = _db(tmp_path)

    columns = [
        row["name"]
        for row in db.conn.execute(
            "PRAGMA table_info(daily_prices)"
        ).fetchall()
    ]

    assert columns == [
        "security_id",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "ticker_at_date",
        "source",
        "fetched_at",
    ]

    db.close()


def test_upsert_and_load_round_trip(
    tmp_path: Path,
):
    db = _db(tmp_path)

    records = [
        _record(
            2,
            adj_close=92.0,
            adjustment_factor=0.92,
            dividend=0.0,
            stock_split=0.0,
        ),
        _record(
            1,
            adj_close=90.0,
            adjustment_factor=0.90,
            dividend=5.0,
            stock_split=0.0,
        ),
    ]

    inserted, updated = upsert_price_adjustments(
        db.conn,
        1,
        records,
        source="Yahoo Finance",
        fetched_at="2026-01-03T10:00:00+03:00",
    )

    db.conn.commit()

    assert inserted == 2
    assert updated == 0

    loaded = load_price_adjustments(
        db.conn,
        1,
    )

    # Storage reads must be chronological regardless
    # of caller insertion order.
    assert loaded == [
        _record(
            1,
            adj_close=90.0,
            adjustment_factor=0.90,
            dividend=5.0,
            stock_split=0.0,
        ),
        _record(
            2,
            adj_close=92.0,
            adjustment_factor=0.92,
            dividend=0.0,
            stock_split=0.0,
        ),
    ]

    db.close()


def test_upsert_reports_inserted_and_updated_counts(
    tmp_path: Path,
):
    db = _db(tmp_path)

    inserted, updated = upsert_price_adjustments(
        db.conn,
        1,
        [
            _record(1),
            _record(2),
        ],
        source="Yahoo Finance",
        fetched_at="2026-01-03T10:00:00+03:00",
    )

    db.conn.commit()

    assert (inserted, updated) == (2, 0)

    inserted, updated = upsert_price_adjustments(
        db.conn,
        1,
        [
            _record(
                2,
                adj_close=95.0,
                adjustment_factor=0.95,
                dividend=1.0,
            ),
            _record(3),
        ],
        source="Yahoo Finance",
        fetched_at="2026-01-04T10:00:00+03:00",
    )

    db.conn.commit()

    assert (inserted, updated) == (1, 1)

    loaded = load_price_adjustments(
        db.conn,
        1,
    )

    assert loaded[1] == _record(
        2,
        adj_close=95.0,
        adjustment_factor=0.95,
        dividend=1.0,
    )

    db.close()


def test_load_supports_inclusive_date_bounds(
    tmp_path: Path,
):
    db = _db(tmp_path)

    upsert_price_adjustments(
        db.conn,
        1,
        [
            _record(1),
            _record(2),
            _record(3),
            _record(4),
        ],
        source="Yahoo Finance",
    )

    db.conn.commit()

    loaded = load_price_adjustments(
        db.conn,
        1,
        start=date(2026, 1, 2),
        end=date(2026, 1, 3),
    )

    assert [
        item.date
        for item in loaded
    ] == [
        date(2026, 1, 2),
        date(2026, 1, 3),
    ]

    db.close()


def test_missing_vendor_values_round_trip_as_none(
    tmp_path: Path,
):
    db = _db(tmp_path)

    record = _record(
        1,
        adj_close=None,
        adjustment_factor=None,
        dividend=None,
        stock_split=None,
    )

    upsert_price_adjustments(
        db.conn,
        1,
        [record],
        source="Yahoo Finance",
    )

    db.conn.commit()

    assert load_price_adjustments(
        db.conn,
        1,
    ) == [record]

    db.close()


def test_source_and_fetched_at_are_auditable(
    tmp_path: Path,
):
    db = _db(tmp_path)

    upsert_price_adjustments(
        db.conn,
        1,
        [_record(1)],
        source="Yahoo Finance",
        fetched_at="2026-01-02T12:34:56+03:00",
    )

    db.conn.commit()

    row = db.conn.execute(
        """
        SELECT source, fetched_at
        FROM price_adjustments
        WHERE security_id=?
          AND date=?
        """,
        (
            1,
            "2026-01-01",
        ),
    ).fetchone()

    assert row["source"] == "Yahoo Finance"
    assert (
        row["fetched_at"]
        == "2026-01-02T12:34:56+03:00"
    )

    db.close()


def test_upsert_updates_audit_metadata_too(
    tmp_path: Path,
):
    db = _db(tmp_path)

    upsert_price_adjustments(
        db.conn,
        1,
        [_record(1)],
        source="Yahoo Finance",
        fetched_at="2026-01-02T10:00:00+03:00",
    )

    db.conn.commit()

    upsert_price_adjustments(
        db.conn,
        1,
        [
            _record(
                1,
                adj_close=91.0,
                adjustment_factor=0.91,
            )
        ],
        source="Yahoo Finance Refetch",
        fetched_at="2026-01-03T10:00:00+03:00",
    )

    db.conn.commit()

    row = db.conn.execute(
        """
        SELECT
            adj_close,
            adjustment_factor,
            source,
            fetched_at
        FROM price_adjustments
        WHERE security_id=?
          AND date=?
        """,
        (
            1,
            "2026-01-01",
        ),
    ).fetchone()

    assert row["adj_close"] == pytest.approx(91.0)
    assert row["adjustment_factor"] == pytest.approx(0.91)
    assert row["source"] == "Yahoo Finance Refetch"
    assert (
        row["fetched_at"]
        == "2026-01-03T10:00:00+03:00"
    )

    db.close()


def test_foreign_key_rejects_unknown_security(
    tmp_path: Path,
):
    db = _db(tmp_path)

    with pytest.raises(Exception):
        upsert_price_adjustments(
            db.conn,
            999,
            [_record(1)],
            source="Yahoo Finance",
        )

    db.close()


def test_empty_upsert_is_noop(
    tmp_path: Path,
):
    db = _db(tmp_path)

    assert upsert_price_adjustments(
        db.conn,
        1,
        [],
        source="Yahoo Finance",
    ) == (0, 0)

    db.close()
