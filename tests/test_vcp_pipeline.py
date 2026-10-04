from datetime import date

import pytest

from src.data.storage.adjustments import (
    AdjustmentRecord,
    upsert_price_adjustments,
)
from src.data.storage.database import Database
from src.pipeline.vcp import run_vcp_analysis
from src.strategy.technical_price_adapter import (
    load_technical_prices,
)
from src.strategy.vcp_analysis import analyze_vcp
from src.strategy.vcp_state import VCPStateConfig


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    yield database
    database.close()


def _state_config() -> VCPStateConfig:
    return VCPStateConfig(
        tightening_range_5_max_pct=5.0,
        tightening_true_range_compression_max=0.75,
        tightening_final_volume_ratio_max=0.75,
        near_pivot_max_distance_pct=5.0,
        breakout_volume_expansion_min_ratio=1.50,
    )


def _add_security(conn) -> int:
    now = "2026-10-04T00:00:00+03:00"

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
            "VCP Test AS",
            "2025-01-01",
            now,
            now,
        ),
    )

    return int(cursor.lastrowid)


def _add_yahoo_bar(
    conn,
    security_id: int,
    day: date,
    *,
    close: float,
    volume: float,
) -> None:
    now = "2026-10-04T00:00:00+03:00"

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
        VALUES (?, ?, ?, ?, ?, ?, ?, 'TEST', 'Yahoo Finance', ?)
        """,
        (
            security_id,
            day.isoformat(),
            close - 1.0,
            close + 2.0,
            close - 2.0,
            close,
            volume,
            now,
        ),
    )

    upsert_price_adjustments(
        conn,
        security_id,
        [
            AdjustmentRecord(
                date=day,
                adj_close=close,
                adjustment_factor=1.0,
                dividend=0.0,
                stock_split=0.0,
            )
        ],
        source="Yahoo Finance",
    )


def test_run_vcp_analysis_matches_manual_database_to_strategy_chain(
    db,
):
    security_id = _add_security(
        db.conn,
    )

    days = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
    )

    for index, day in enumerate(days):
        _add_yahoo_bar(
            db.conn,
            security_id,
            day,
            close=100.0 + index,
            volume=1_000_000 + index,
        )

    db.conn.commit()

    state_config = _state_config()
    as_of = days[-1]

    technical_bars = load_technical_prices(
        db.conn,
        security_id,
        end=as_of,
    )

    expected = analyze_vcp(
        technical_bars,
        state_config=state_config,
    )

    actual = run_vcp_analysis(
        db.conn,
        security_id,
        as_of=as_of,
        state_config=state_config,
    )

    assert actual == expected


def test_run_vcp_analysis_excludes_prices_after_as_of(
    db,
):
    security_id = _add_security(
        db.conn,
    )

    day_1 = date(2026, 1, 5)
    as_of = date(2026, 1, 6)
    future_day = date(2026, 1, 7)

    _add_yahoo_bar(
        db.conn,
        security_id,
        day_1,
        close=100.0,
        volume=1_000_000,
    )

    _add_yahoo_bar(
        db.conn,
        security_id,
        as_of,
        close=101.0,
        volume=1_100_000,
    )

    _add_yahoo_bar(
        db.conn,
        security_id,
        future_day,
        close=150.0,
        volume=9_999_999,
    )

    db.conn.commit()

    result = run_vcp_analysis(
        db.conn,
        security_id,
        as_of=as_of,
        state_config=_state_config(),
    )

    assert result.technical_bars[-1].date == as_of

    assert all(
        bar.date <= as_of
        for bar in result.technical_bars
    )

    assert future_day not in {
        bar.date
        for bar in result.technical_bars
    }
