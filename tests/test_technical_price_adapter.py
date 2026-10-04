from datetime import date

import pytest

from src.data.storage.adjustments import (
    AdjustmentRecord,
    upsert_price_adjustments,
)
from src.data.storage.database import Database
from src.strategy.technical_price_adapter import (
    load_technical_prices,
)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    yield database
    database.close()


def _add_security(conn):
    now = "2026-10-02T00:00:00+03:00"

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
            "2025-11-20",
            now,
            now,
        ),
    )

    return int(cursor.lastrowid)


def _add_price(
    conn,
    security_id,
    day,
    *,
    close,
    volume,
    source="Yahoo Finance",
):
    now = "2026-10-02T00:00:00+03:00"

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
        VALUES (?, ?, ?, ?, ?, ?, ?, 'TEST', ?, ?)
        """,
        (
            security_id,
            day.isoformat(),
            close - 1.0,
            close + 2.0,
            close - 2.0,
            close,
            volume,
            source,
            now,
        ),
    )


def test_adapter_builds_ok_technical_prices_across_explained_dividend_transition(
    db,
):
    security_id = _add_security(
        db.conn,
    )

    day_1 = date(2025, 11, 21)
    day_2 = date(2025, 11, 24)
    dividend_day = date(2025, 11, 25)

    factor_before = 0.9987275

    rows = (
        (
            day_1,
            100.0,
            factor_before,
            0.0,
        ),
        (
            day_2,
            102.0,
            factor_before,
            0.0,
        ),
        (
            dividend_day,
            101.0,
            1.0,
            0.234649,
        ),
    )

    for index, (
        day,
        close,
        factor,
        dividend,
    ) in enumerate(rows):
        _add_price(
            db.conn,
            security_id,
            day,
            close=close,
            volume=1_000_000 + index,
        )

        upsert_price_adjustments(
            db.conn,
            security_id,
            [
                AdjustmentRecord(
                    date=day,
                    adj_close=close * factor,
                    adjustment_factor=factor,
                    dividend=dividend,
                    stock_split=0.0,
                )
            ],
            source="Yahoo Finance",
        )

    db.conn.commit()

    result = load_technical_prices(
        db.conn,
        security_id,
    )

    assert len(result) == 3

    assert [
        bar.adjustment_status
        for bar in result
    ] == [
        "OK",
        "OK",
        "OK",
    ]

    assert result[0].adjustment_factor == pytest.approx(
        factor_before
    )
    assert result[1].adjustment_factor == pytest.approx(
        factor_before
    )
    assert result[2].adjustment_factor == pytest.approx(
        1.0
    )

    assert result[2].dividend == pytest.approx(
        0.234649
    )

    assert result[0].close == pytest.approx(
        100.0 * factor_before
    )

    assert result[0].raw_close == pytest.approx(
        100.0
    )

    assert result[0].volume == pytest.approx(
        1_000_000
    )


def test_adapter_does_not_invent_zero_for_missing_volume(
    db,
):
    security_id = _add_security(
        db.conn,
    )

    day = date(2025, 11, 21)

    _add_price(
        db.conn,
        security_id,
        day,
        close=100.0,
        volume=None,
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
        ],
        source="Yahoo Finance",
    )

    db.conn.commit()

    with pytest.raises(
        ValueError,
        match="volume",
    ):
        load_technical_prices(
            db.conn,
            security_id,
        )


def test_adapter_fails_closed_when_adjustment_metadata_is_missing(
    db,
):
    security_id = _add_security(
        db.conn,
    )

    day = date(2025, 11, 21)

    _add_price(
        db.conn,
        security_id,
        day,
        close=100.0,
        volume=1_000_000,
    )

    # Intentionally do NOT insert a price_adjustments row.
    db.conn.commit()

    with pytest.raises(
        ValueError,
        match="missing adjustment metadata",
    ):
        load_technical_prices(
            db.conn,
            security_id,
        )


def test_adapter_fails_closed_when_stored_factor_disagrees_with_prices(
    db,
):
    security_id = _add_security(
        db.conn,
    )

    day = date(2025, 11, 21)

    _add_price(
        db.conn,
        security_id,
        day,
        close=100.0,
        volume=1_000_000,
    )

    upsert_price_adjustments(
        db.conn,
        security_id,
        [
            AdjustmentRecord(
                date=day,
                adj_close=90.0,
                adjustment_factor=0.95,
                dividend=0.0,
                stock_split=0.0,
            )
        ],
        source="Yahoo Finance",
    )

    db.conn.commit()

    with pytest.raises(
        ValueError,
        match="stored adjustment factor does not match",
    ):
        load_technical_prices(
            db.conn,
            security_id,
        )


def test_adapter_does_not_use_other_source_adjustment_for_yahoo_price(
    db,
):
    security_id = _add_security(
        db.conn,
    )

    day = date(2026, 1, 5)

    _add_price(
        db.conn,
        security_id,
        day,
        close=100.0,
        volume=1_000_000,
        source="Yahoo Finance",
    )

    # Same date, but deliberately the WRONG adjustment source.
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
        ],
        source="BIST_THB",
    )

    db.conn.commit()

    with pytest.raises(
        ValueError,
        match="missing adjustment metadata",
    ):
        load_technical_prices(
            db.conn,
            security_id,
        )


def test_adapter_bridges_bist_thb_bar_when_yahoo_factor_is_stable_on_both_sides(
    db,
):
    security_id = _add_security(
        db.conn,
    )

    previous_day = date(2026, 1, 5)
    fallback_day = date(2026, 1, 6)
    next_day = date(2026, 1, 7)

    factor = 0.90

    _add_price(
        db.conn,
        security_id,
        previous_day,
        close=100.0,
        volume=1_000_000,
        source="Yahoo Finance",
    )

    upsert_price_adjustments(
        db.conn,
        security_id,
        [
            AdjustmentRecord(
                date=previous_day,
                adj_close=100.0 * factor,
                adjustment_factor=factor,
                dividend=0.0,
                stock_split=0.0,
            )
        ],
        source="Yahoo Finance",
    )

    _add_price(
        db.conn,
        security_id,
        fallback_day,
        close=105.0,
        volume=1_100_000,
        source="BIST_THB",
    )

    _add_price(
        db.conn,
        security_id,
        next_day,
        close=110.0,
        volume=1_200_000,
        source="Yahoo Finance",
    )

    upsert_price_adjustments(
        db.conn,
        security_id,
        [
            AdjustmentRecord(
                date=next_day,
                adj_close=110.0 * factor,
                adjustment_factor=factor,
                dividend=0.0,
                stock_split=0.0,
            )
        ],
        source="Yahoo Finance",
    )

    db.conn.commit()

    result = load_technical_prices(
        db.conn,
        security_id,
    )

    assert len(result) == 3

    bridged = result[1]

    assert bridged.date == fallback_day
    assert bridged.raw_close == pytest.approx(
        105.0
    )
    assert bridged.adjustment_factor == pytest.approx(
        factor
    )
    assert bridged.close == pytest.approx(
        105.0 * factor
    )
    assert bridged.adj_close == pytest.approx(
        105.0 * factor
    )
    assert bridged.adjustment_status == "OK"


def test_adapter_rejects_bist_thb_bridge_across_factor_boundary(
    db,
):
    security_id = _add_security(
        db.conn,
    )

    previous_day = date(2026, 1, 5)
    fallback_day = date(2026, 1, 6)
    next_day = date(2026, 1, 7)

    _add_price(
        db.conn,
        security_id,
        previous_day,
        close=100.0,
        volume=1_000_000,
        source="Yahoo Finance",
    )

    upsert_price_adjustments(
        db.conn,
        security_id,
        [
            AdjustmentRecord(
                date=previous_day,
                adj_close=90.0,
                adjustment_factor=0.90,
                dividend=0.0,
                stock_split=0.0,
            )
        ],
        source="Yahoo Finance",
    )

    _add_price(
        db.conn,
        security_id,
        fallback_day,
        close=105.0,
        volume=1_100_000,
        source="BIST_THB",
    )

    _add_price(
        db.conn,
        security_id,
        next_day,
        close=110.0,
        volume=1_200_000,
        source="Yahoo Finance",
    )

    upsert_price_adjustments(
        db.conn,
        security_id,
        [
            AdjustmentRecord(
                date=next_day,
                adj_close=110.0,
                adjustment_factor=1.0,
                dividend=1.0,
                stock_split=0.0,
            )
        ],
        source="Yahoo Finance",
    )

    db.conn.commit()

    with pytest.raises(
        ValueError,
        match="factor boundary",
    ):
        load_technical_prices(
            db.conn,
            security_id,
        )


def test_adapter_trims_leading_one_sided_bist_thb_prefix(
    db,
):
    security_id = _add_security(
        db.conn,
    )

    fallback_day = date(2026, 1, 5)
    yahoo_day = date(2026, 1, 6)

    _add_price(
        db.conn,
        security_id,
        fallback_day,
        close=99.0,
        volume=900_000,
        source="BIST_THB",
    )

    _add_price(
        db.conn,
        security_id,
        yahoo_day,
        close=100.0,
        volume=1_000_000,
        source="Yahoo Finance",
    )

    upsert_price_adjustments(
        db.conn,
        security_id,
        [
            AdjustmentRecord(
                date=yahoo_day,
                adj_close=100.0,
                adjustment_factor=1.0,
                dividend=0.0,
                stock_split=0.0,
            )
        ],
        source="Yahoo Finance",
    )

    db.conn.commit()

    result = load_technical_prices(
        db.conn,
        security_id,
    )

    assert len(result) == 1
    assert result[0].date == yahoo_day
    assert result[0].adjustment_status == "OK"


def test_adapter_fails_closed_on_trailing_one_sided_bist_thb_bar(
    db,
):
    security_id = _add_security(
        db.conn,
    )

    yahoo_day = date(2026, 1, 5)
    fallback_day = date(2026, 1, 6)

    _add_price(
        db.conn,
        security_id,
        yahoo_day,
        close=100.0,
        volume=1_000_000,
        source="Yahoo Finance",
    )

    upsert_price_adjustments(
        db.conn,
        security_id,
        [
            AdjustmentRecord(
                date=yahoo_day,
                adj_close=100.0,
                adjustment_factor=1.0,
                dividend=0.0,
                stock_split=0.0,
            )
        ],
        source="Yahoo Finance",
    )

    _add_price(
        db.conn,
        security_id,
        fallback_day,
        close=101.0,
        volume=1_100_000,
        source="BIST_THB",
    )

    db.conn.commit()

    with pytest.raises(
        ValueError,
        match="trailing one-sided",
    ):
        load_technical_prices(
            db.conn,
            security_id,
        )


def test_adapter_rejects_bist_thb_bridge_when_neighbor_gap_is_too_long(
    db,
):
    security_id = _add_security(
        db.conn,
    )

    previous_day = date(2026, 1, 2)
    fallback_day = date(2026, 1, 12)
    next_day = date(2026, 1, 13)

    factor = 1.0

    _add_price(
        db.conn,
        security_id,
        previous_day,
        close=100.0,
        volume=1_000_000,
        source="Yahoo Finance",
    )

    upsert_price_adjustments(
        db.conn,
        security_id,
        [
            AdjustmentRecord(
                date=previous_day,
                adj_close=100.0,
                adjustment_factor=factor,
                dividend=0.0,
                stock_split=0.0,
            )
        ],
        source="Yahoo Finance",
    )

    _add_price(
        db.conn,
        security_id,
        fallback_day,
        close=101.0,
        volume=1_100_000,
        source="BIST_THB",
    )

    _add_price(
        db.conn,
        security_id,
        next_day,
        close=102.0,
        volume=1_200_000,
        source="Yahoo Finance",
    )

    upsert_price_adjustments(
        db.conn,
        security_id,
        [
            AdjustmentRecord(
                date=next_day,
                adj_close=102.0,
                adjustment_factor=factor,
                dividend=0.0,
                stock_split=0.0,
            )
        ],
        source="Yahoo Finance",
    )

    db.conn.commit()

    with pytest.raises(
        ValueError,
        match="bridge gap exceeds 7 days",
    ):
        load_technical_prices(
            db.conn,
            security_id,
        )
