from datetime import date

import pytest

from src.calculation.engine import PriceBar
from src.data.storage.database import Database
from src.data.storage.indices import (
    active_market_indices,
    ensure_core_market_indices,
    load_index_price_bars,
    load_recent_index_price_bars,
    upsert_index_price_bars,
)


def make_bar(
    day: date,
    close: float,
    volume: float | None = None,
) -> PriceBar:
    return PriceBar(
        date=day,
        open=close - 1.0,
        high=close + 1.0,
        low=close - 2.0,
        close=close,
        volume=volume,
    )


def test_initialize_creates_market_index_tables(tmp_path):
    db = Database(
        tmp_path / "test.db"
    )

    try:
        db.initialize()

        tables = {
            row[0]
            for row in db.conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table'
                """
            ).fetchall()
        }

        assert "market_indices" in tables
        assert "index_daily_prices" in tables

    finally:
        db.close()


def test_core_market_indices_are_registered_idempotently(
    tmp_path,
):
    db = Database(
        tmp_path / "test.db"
    )

    try:
        db.initialize()

        ensure_core_market_indices(
            db.conn,
            recorded_at="2026-09-27T12:00:00+03:00",
        )

        ensure_core_market_indices(
            db.conn,
            recorded_at="2026-09-27T13:00:00+03:00",
        )

        db.conn.commit()

        indices = active_market_indices(
            db.conn
        )

        assert [
            item.index_code
            for item in indices
        ] == [
            "XU030",
            "XU100",
        ]

        assert all(
            item.source == "Yahoo Finance"
            for item in indices
        )

    finally:
        db.close()


def test_index_price_round_trip_and_upsert_counts(
    tmp_path,
):
    db = Database(
        tmp_path / "test.db"
    )

    try:
        db.initialize()
        ensure_core_market_indices(
            db.conn
        )

        inserted, updated = (
            upsert_index_price_bars(
                db.conn,
                "XU030",
                [
                    make_bar(
                        date(2026, 9, 23),
                        15000.0,
                    ),
                    make_bar(
                        date(2026, 9, 24),
                        15100.0,
                    ),
                ],
                source="Yahoo Finance",
                fetched_at="2026-09-27T12:00:00+03:00",
            )
        )

        assert inserted == 2
        assert updated == 0

        inserted, updated = (
            upsert_index_price_bars(
                db.conn,
                "XU030",
                [
                    make_bar(
                        date(2026, 9, 24),
                        15200.0,
                    ),
                ],
                source="Yahoo Finance",
                fetched_at="2026-09-27T13:00:00+03:00",
            )
        )

        assert inserted == 0
        assert updated == 1

        db.conn.commit()

        bars = load_index_price_bars(
            db.conn,
            "XU030",
        )

        assert len(bars) == 2
        assert bars[0].date == date(2026, 9, 23)
        assert bars[1].date == date(2026, 9, 24)
        assert bars[1].close == 15200.0

    finally:
        db.close()


def test_recent_index_prices_return_ascending_order(
    tmp_path,
):
    db = Database(
        tmp_path / "test.db"
    )

    try:
        db.initialize()
        ensure_core_market_indices(
            db.conn
        )

        upsert_index_price_bars(
            db.conn,
            "XU100",
            [
                make_bar(
                    date(2026, 9, 22),
                    12000.0,
                ),
                make_bar(
                    date(2026, 9, 23),
                    12100.0,
                ),
                make_bar(
                    date(2026, 9, 24),
                    12200.0,
                ),
            ],
            source="Yahoo Finance",
        )

        db.conn.commit()

        bars = load_recent_index_price_bars(
            db.conn,
            "XU100",
            end=date(2026, 9, 24),
            limit=2,
        )

        assert [
            bar.date
            for bar in bars
        ] == [
            date(2026, 9, 23),
            date(2026, 9, 24),
        ]

    finally:
        db.close()


def test_unknown_index_is_rejected(
    tmp_path,
):
    db = Database(
        tmp_path / "test.db"
    )

    try:
        db.initialize()

        with pytest.raises(
            ValueError,
            match="Unknown market index",
        ):
            upsert_index_price_bars(
                db.conn,
                "XYUZO",
                [
                    make_bar(
                        date(2026, 9, 24),
                        100.0,
                    ),
                ],
                source="Yahoo Finance",
            )

    finally:
        db.close()
