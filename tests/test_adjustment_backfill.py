from datetime import date

import pytest

from src.data.storage.database import Database
from src.data.storage.adjustments import (
    AdjustmentRecord,
    upsert_price_adjustments,
)
from src.pipeline.adjustment_backfill import (
    build_adjustment_backfill_plan,
    run_adjustment_backfill,
)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    yield database
    database.close()


def _add_security_with_ticker_history(conn):
    now = "2026-10-01T00:00:00+03:00"

    cursor = conn.execute(
        """
        INSERT INTO securities(
            name,
            instrument_type,
            status,
            first_trade_date,
            active,
            created_at,
            updated_at
        )
        VALUES (?, 'EQUITY', 'ACTIVE', ?, 1, ?, ?)
        """,
        (
            "Test AS",
            "2023-01-01",
            now,
            now,
        ),
    )

    security_id = cursor.lastrowid

    conn.execute(
        """
        INSERT INTO security_identifiers(
            security_id,
            ticker,
            valid_from,
            valid_to,
            is_current
        )
        VALUES (?, ?, ?, ?, 0)
        """,
        (
            security_id,
            "OLD",
            "2023-01-01",
            "2024-01-01",
        ),
    )

    conn.execute(
        """
        INSERT INTO security_identifiers(
            security_id,
            ticker,
            valid_from,
            valid_to,
            is_current
        )
        VALUES (?, ?, ?, NULL, 1)
        """,
        (
            security_id,
            "NEW",
            "2024-01-01",
        ),
    )

    return security_id


def _add_price(
    conn,
    security_id,
    day,
    *,
    source="TEST",
):
    conn.execute(
        """
        INSERT INTO daily_prices(
            security_id,
            date,
            open,
            high,
            low,
            close,
            volume,
            ticker_at_date,
            source,
            fetched_at
        )
        VALUES (?, ?, 100, 101, 99, 100, 1000, ?, ?, ?)
        """,
        (
            security_id,
            day.isoformat(),
            "OLD" if day.year == 2023 else "NEW",
            source,
            "2026-10-01T00:00:00+03:00",
        ),
    )


def test_backfill_plan_finds_only_missing_dates_and_uses_historical_ticker(
    db,
):
    security_id = _add_security_with_ticker_history(
        db.conn,
    )

    old_existing = date(2023, 12, 27)
    old_missing = date(2023, 12, 28)
    new_missing_1 = date(2024, 1, 2)
    new_missing_2 = date(2024, 1, 3)

    for day in (
        old_existing,
        old_missing,
        new_missing_1,
        new_missing_2,
    ):
        _add_price(
            db.conn,
            security_id,
            day,
        )

    upsert_price_adjustments(
        db.conn,
        security_id,
        [
            AdjustmentRecord(
                date=old_existing,
                adj_close=100.0,
                adjustment_factor=1.0,
                dividend=0.0,
                stock_split=0.0,
            )
        ],
        source="YAHOO",
    )

    db.conn.commit()

    plan = build_adjustment_backfill_plan(
        db.conn,
        as_of=date(2024, 1, 3),
    )

    assert [
        (
            request.security_id,
            request.ticker,
            request.start,
            request.end,
            request.required_dates,
        )
        for request in plan
    ] == [
        (
            security_id,
            "OLD",
            old_missing,
            old_missing,
            (old_missing,),
        ),
        (
            security_id,
            "NEW",
            new_missing_1,
            new_missing_2,
            (
                new_missing_1,
                new_missing_2,
            ),
        ),
    ]


def test_backfill_plan_is_empty_when_all_price_dates_have_adjustments(
    db,
):
    security_id = _add_security_with_ticker_history(
        db.conn,
    )

    days = (
        date(2023, 12, 28),
        date(2024, 1, 2),
        date(2024, 1, 3),
    )

    for day in days:
        _add_price(
            db.conn,
            security_id,
            day,
        )

    upsert_price_adjustments(
        db.conn,
        security_id,
        [
            AdjustmentRecord(
                date=day,
                adj_close=100.0,
                adjustment_factor=1.0,
                dividend=0.0,
                stock_split=0.0,
            )
            for day in days
        ],
        source="YAHOO",
    )

    db.conn.commit()

    plan = build_adjustment_backfill_plan(
        db.conn,
        as_of=date(2024, 1, 3),
    )

    assert plan == []



class FakeAdjustmentProvider:
    source_name = "TEST"

    def __init__(self, records):
        self.records = records
        self.calls = []

    def fetch_adjustments(self, ticker, start, end):
        self.calls.append(
            (
                ticker,
                start,
                end,
            )
        )
        # Deliberately return everything. The orchestration layer must
        # retain only dates explicitly required by the backfill plan.
        return list(self.records)


def test_backfill_fetches_required_range_and_persists_only_required_dates(
    db,
):
    security_id = _add_security_with_ticker_history(
        db.conn,
    )

    existing_day = date(2024, 1, 2)
    missing_day_1 = date(2024, 1, 3)
    missing_day_2 = date(2024, 1, 4)
    unrelated_day = date(2024, 1, 5)

    for day in (
        existing_day,
        missing_day_1,
        missing_day_2,
    ):
        _add_price(
            db.conn,
            security_id,
            day,
        )

    # This row must remain untouched because it is not part of the
    # missing-date plan.
    upsert_price_adjustments(
        db.conn,
        security_id,
        [
            AdjustmentRecord(
                date=existing_day,
                adj_close=90.0,
                adjustment_factor=0.9,
                dividend=0.0,
                stock_split=0.0,
            )
        ],
        source="EXISTING",
    )

    db.conn.commit()

    provider = FakeAdjustmentProvider(
        [
            AdjustmentRecord(
                date=existing_day,
                adj_close=999.0,
                adjustment_factor=9.99,
                dividend=0.0,
                stock_split=0.0,
            ),
            AdjustmentRecord(
                date=missing_day_1,
                adj_close=101.0,
                adjustment_factor=1.01,
                dividend=0.0,
                stock_split=0.0,
            ),
            AdjustmentRecord(
                date=missing_day_2,
                adj_close=102.0,
                adjustment_factor=1.02,
                dividend=0.0,
                stock_split=0.0,
            ),
            AdjustmentRecord(
                date=unrelated_day,
                adj_close=103.0,
                adjustment_factor=1.03,
                dividend=0.0,
                stock_split=0.0,
            ),
        ]
    )

    before_prices = db.conn.execute(
        """
        SELECT date, open, high, low, close, volume
        FROM daily_prices
        WHERE security_id=?
        ORDER BY date
        """,
        (security_id,),
    ).fetchall()

    run_adjustment_backfill(
        db.conn,
        provider,
        as_of=missing_day_2,
    )

    assert provider.calls == [
        (
            "NEW",
            missing_day_1,
            missing_day_2,
        )
    ]

    rows = db.conn.execute(
        """
        SELECT
            date,
            adj_close,
            adjustment_factor,
            source
        FROM price_adjustments
        WHERE security_id=?
        ORDER BY date
        """,
        (security_id,),
    ).fetchall()

    assert [
        tuple(row)
        for row in rows
    ] == [
        (
            existing_day.isoformat(),
            90.0,
            0.9,
            "EXISTING",
        ),
        (
            missing_day_1.isoformat(),
            101.0,
            1.01,
            "TEST",
        ),
        (
            missing_day_2.isoformat(),
            102.0,
            1.02,
            "TEST",
        ),
    ]

    after_prices = db.conn.execute(
        """
        SELECT date, open, high, low, close, volume
        FROM daily_prices
        WHERE security_id=?
        ORDER BY date
        """,
        (security_id,),
    ).fetchall()

    assert [
        tuple(row)
        for row in after_prices
    ] == [
        tuple(row)
        for row in before_prices
    ]


def test_backfill_does_not_commit_partial_provider_response(
    db,
):
    security_id = _add_security_with_ticker_history(
        db.conn,
    )

    missing_day_1 = date(2024, 1, 2)
    missing_day_2 = date(2024, 1, 3)

    for day in (
        missing_day_1,
        missing_day_2,
    ):
        _add_price(
            db.conn,
            security_id,
            day,
        )

    db.conn.commit()

    # Provider deliberately omits one required date.
    provider = FakeAdjustmentProvider(
        [
            AdjustmentRecord(
                date=missing_day_1,
                adj_close=101.0,
                adjustment_factor=1.01,
                dividend=0.0,
                stock_split=0.0,
            )
        ]
    )

    with pytest.raises(
        ValueError,
        match="missing adjustment metadata",
    ):
        run_adjustment_backfill(
            db.conn,
            provider,
            as_of=missing_day_2,
        )

    adjustment_count = db.conn.execute(
        """
        SELECT COUNT(*)
        FROM price_adjustments
        WHERE security_id=?
        """,
        (security_id,),
    ).fetchone()[0]

    assert adjustment_count == 0


def test_backfill_write_failure_rolls_back_all_adjustments(
    db,
):
    security_id = _add_security_with_ticker_history(
        db.conn,
    )

    day_1 = date(2024, 1, 2)
    day_2 = date(2024, 1, 3)

    for day in (
        day_1,
        day_2,
    ):
        _add_price(
            db.conn,
            security_id,
            day,
        )

    db.conn.commit()

    provider = FakeAdjustmentProvider(
        [
            AdjustmentRecord(
                date=day_1,
                adj_close=101.0,
                adjustment_factor=1.01,
                dividend=0.0,
                stock_split=0.0,
            ),
            AdjustmentRecord(
                date=day_2,
                adj_close=102.0,
                adjustment_factor=1.02,
                dividend=0.0,
                stock_split=0.0,
            ),
        ]
    )

    db.conn.execute(
        f"""
        CREATE TRIGGER fail_second_backfill_adjustment
        BEFORE INSERT ON price_adjustments
        WHEN NEW.date = '{day_2.isoformat()}'
        BEGIN
            SELECT RAISE(
                ABORT,
                'forced backfill adjustment failure'
            );
        END;
        """
    )
    db.conn.commit()

    with pytest.raises(
        Exception,
        match="forced backfill adjustment failure",
    ):
        run_adjustment_backfill(
            db.conn,
            provider,
            as_of=day_2,
        )

    rows = db.conn.execute(
        """
        SELECT date
        FROM price_adjustments
        WHERE security_id=?
        ORDER BY date
        """,
        (security_id,),
    ).fetchall()

    assert rows == []


def test_backfill_plan_can_be_restricted_to_current_ticker_subset(
    db,
):
    first_id = _add_security_with_ticker_history(
        db.conn,
    )

    second_now = "2026-10-02T00:00:00+03:00"

    cursor = db.conn.execute(
        """
        INSERT INTO securities(
            name,
            instrument_type,
            status,
            first_trade_date,
            active,
            created_at,
            updated_at
        )
        VALUES (?, 'EQUITY', 'ACTIVE', ?, 1, ?, ?)
        """,
        (
            "Second AS",
            "2024-01-01",
            second_now,
            second_now,
        ),
    )

    second_id = cursor.lastrowid

    db.conn.execute(
        """
        INSERT INTO security_identifiers(
            security_id,
            ticker,
            valid_from,
            valid_to,
            is_current
        )
        VALUES (?, 'SECOND', '2024-01-01', NULL, 1)
        """,
        (second_id,),
    )

    day = date(2024, 1, 3)

    _add_price(
        db.conn,
        first_id,
        day,
    )

    db.conn.execute(
        """
        INSERT INTO daily_prices(
            security_id,
            date,
            open,
            high,
            low,
            close,
            volume,
            ticker_at_date,
            source,
            fetched_at
        )
        VALUES (?, ?, 100, 101, 99, 100, 1000, 'SECOND', 'TEST', ?)
        """,
        (
            second_id,
            day.isoformat(),
            second_now,
        ),
    )

    db.conn.commit()

    plan = build_adjustment_backfill_plan(
        db.conn,
        as_of=day,
        tickers={"NEW"},
    )

    assert {
        request.security_id
        for request in plan
    } == {
        first_id,
    }


def test_run_backfill_passes_ticker_subset_to_planner(
    db,
):
    first_id = _add_security_with_ticker_history(
        db.conn,
    )

    now = "2026-10-02T00:00:00+03:00"

    cursor = db.conn.execute(
        """
        INSERT INTO securities(
            name,
            instrument_type,
            status,
            first_trade_date,
            active,
            created_at,
            updated_at
        )
        VALUES (?, 'EQUITY', 'ACTIVE', ?, 1, ?, ?)
        """,
        (
            "Second AS",
            "2024-01-01",
            now,
            now,
        ),
    )

    second_id = cursor.lastrowid

    db.conn.execute(
        """
        INSERT INTO security_identifiers(
            security_id,
            ticker,
            valid_from,
            valid_to,
            is_current
        )
        VALUES (?, 'SECOND', '2024-01-01', NULL, 1)
        """,
        (second_id,),
    )

    day = date(2024, 1, 3)

    _add_price(
        db.conn,
        first_id,
        day,
    )

    db.conn.execute(
        """
        INSERT INTO daily_prices(
            security_id,
            date,
            open,
            high,
            low,
            close,
            volume,
            ticker_at_date,
            source,
            fetched_at
        )
        VALUES (?, ?, 100, 101, 99, 100, 1000, 'SECOND', 'TEST', ?)
        """,
        (
            second_id,
            day.isoformat(),
            now,
        ),
    )

    db.conn.commit()

    provider = FakeAdjustmentProvider(
        [
            AdjustmentRecord(
                date=day,
                adj_close=100.0,
                adjustment_factor=1.0,
                dividend=0.0,
                stock_split=0.0,
            )
        ]
    )

    summary = run_adjustment_backfill(
        db.conn,
        provider,
        as_of=day,
        tickers={"NEW"},
    )

    assert provider.calls == [
        (
            "NEW",
            day,
            day,
        )
    ]

    assert summary.requests_planned == 1

    assert db.conn.execute(
        """
        SELECT COUNT(*)
        FROM price_adjustments
        WHERE security_id=?
        """,
        (first_id,),
    ).fetchone()[0] == 1

    assert db.conn.execute(
        """
        SELECT COUNT(*)
        FROM price_adjustments
        WHERE security_id=?
        """,
        (second_id,),
    ).fetchone()[0] == 0



def test_run_backfill_excludes_dates_from_other_canonical_price_sources(
    db,
):
    security_id = _add_security_with_ticker_history(
        db.conn,
    )

    yahoo_day = date(2024, 1, 2)
    fallback_day = date(2024, 1, 3)

    _add_price(
        db.conn,
        security_id,
        yahoo_day,
        source="Yahoo Finance",
    )

    _add_price(
        db.conn,
        security_id,
        fallback_day,
        source="BIST_THB",
    )

    db.conn.commit()

    provider = FakeAdjustmentProvider(
        [
            AdjustmentRecord(
                date=yahoo_day,
                adj_close=100.0,
                adjustment_factor=1.0,
                dividend=0.0,
                stock_split=0.0,
            ),
            AdjustmentRecord(
                date=fallback_day,
                adj_close=100.0,
                adjustment_factor=1.0,
                dividend=0.0,
                stock_split=0.0,
            ),
        ]
    )

    provider.source_name = "Yahoo Finance"

    summary = run_adjustment_backfill(
        db.conn,
        provider,
        as_of=fallback_day,
    )

    assert provider.calls == [
        (
            "NEW",
            yahoo_day,
            yahoo_day,
        )
    ]

    rows = db.conn.execute(
        """
        SELECT date, source
        FROM price_adjustments
        WHERE security_id=?
        ORDER BY date
        """,
        (security_id,),
    ).fetchall()

    assert [
        tuple(row)
        for row in rows
    ] == [
        (
            yahoo_day.isoformat(),
            "Yahoo Finance",
        )
    ]

    assert summary.records_accepted == 1
