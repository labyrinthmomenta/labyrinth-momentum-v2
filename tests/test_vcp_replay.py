from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from src.research.vcp_replay import (
    VCPForwardOutcome,
    compute_forward_outcome,
)
from src.strategy.technical_prices import TechnicalPriceBar


BASE_DATE = date(2026, 1, 2)


def _bar(
    session: int,
    *,
    close: float,
    high: float | None = None,
    low: float | None = None,
) -> TechnicalPriceBar:
    day = BASE_DATE + timedelta(days=session)

    high = (
        close + 1.0
        if high is None
        else high
    )

    low = (
        close - 1.0
        if low is None
        else low
    )

    return TechnicalPriceBar(
        date=day,

        open=close,
        high=high,
        low=low,
        close=close,

        volume=1_000.0,

        raw_open=close,
        raw_high=high,
        raw_low=low,
        raw_close=close,
        adj_close=close,

        dividend=0.0,
        stock_split=0.0,

        adjustment_factor=1.0,
        adjustment_status="OK",
    )


def test_forward_outcome_uses_future_trading_session_positions():
    reference = _bar(
        0,
        close=100.0,
    )

    future = tuple(
        _bar(
            session,
            close=100.0 + session,
            high=102.0 + session,
            low=98.0 + session,
        )
        for session in range(1, 41)
    )

    result = compute_forward_outcome(
        reference,
        future,
    )

    assert isinstance(
        result,
        VCPForwardOutcome,
    )

    assert result.reference_date == reference.date
    assert result.reference_close == 100.0

    assert result.forward_return_5 == pytest.approx(
        0.05
    )

    assert result.forward_return_10 == pytest.approx(
        0.10
    )

    assert result.forward_return_20 == pytest.approx(
        0.20
    )

    assert result.forward_return_40 == pytest.approx(
        0.40
    )

    # Highest future HIGH is session 40:
    # 142 / 100 - 1 = +42%.
    assert result.mfe_40 == pytest.approx(
        0.42
    )

    # Lowest future LOW is session 1:
    # 99 / 100 - 1 = -1%.
    assert result.mae_40 == pytest.approx(
        -0.01
    )


def test_missing_future_horizons_are_none():
    reference = _bar(
        0,
        close=100.0,
    )

    future = tuple(
        _bar(
            session,
            close=100.0 + session,
        )
        for session in range(1, 8)
    )

    result = compute_forward_outcome(
        reference,
        future,
    )

    assert result.forward_return_5 == pytest.approx(
        0.05
    )

    assert result.forward_return_10 is None
    assert result.forward_return_20 is None
    assert result.forward_return_40 is None

    # Do not report partial 40-session excursions.
    assert result.mfe_40 is None
    assert result.mae_40 is None


def test_horizons_count_sessions_not_calendar_days():
    reference = _bar(
        0,
        close=100.0,
    )

    source = [
        _bar(
            session,
            close=100.0 + session,
        )
        for session in range(1, 6)
    ]

    # Deliberately create large calendar gaps.
    dates = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 9),
        date(2026, 1, 15),
        date(2026, 1, 26),
    )

    future = tuple(
        replace(
            bar,
            date=day,
        )
        for bar, day in zip(
            source,
            dates,
        )
    )

    result = compute_forward_outcome(
        reference,
        future,
    )

    # Fifth supplied trading session, regardless
    # of calendar distance.
    assert result.forward_return_5 == pytest.approx(
        0.05
    )


from src.research.vcp_replay import (
    VCPReplaySnapshot,
    build_replay_snapshot,
)
from src.strategy.vcp_analysis import analyze_vcp
from src.strategy.vcp_state import VCPStateConfig


def _state_config() -> VCPStateConfig:
    return VCPStateConfig(
        tightening_range_5_max_pct=5.0,
        tightening_true_range_compression_max=0.75,
        tightening_final_volume_ratio_max=0.75,
        near_pivot_max_distance_pct=5.0,
        breakout_volume_expansion_min_ratio=1.50,
    )


def _analysis_bars() -> tuple[TechnicalPriceBar, ...]:
    closes = (
        100, 102, 104, 106, 108,
        110, 107, 104, 101, 98,
        100, 103, 106, 109, 112,
        109, 106, 103, 101, 99,
        101, 104, 107, 109, 111,
        109, 107, 105, 103, 102,
        104, 106, 108, 109, 110,
        108, 107, 106, 105, 104,
        105, 106, 107, 108, 109,
        110, 111, 112, 113, 114,
        113, 112, 111, 110, 109,
        110, 111, 112, 113, 115,
    )

    return tuple(
        _bar(
            session=index,
            close=float(close),
            high=float(close) * 1.02,
            low=float(close) * 0.98,
        )
        for index, close in enumerate(closes)
    )


def test_replay_snapshot_maps_analysis_without_reclassifying():
    bars = _analysis_bars()

    analysis = analyze_vcp(
        bars,
        state_config=_state_config(),
    )

    result = build_replay_snapshot(
        security_id=123,
        ticker="TEST",
        as_of=bars[-1].date,
        analysis=analysis,
    )

    assert isinstance(
        result,
        VCPReplaySnapshot,
    )

    assert result.security_id == 123
    assert result.ticker == "TEST"
    assert result.as_of == bars[-1].date

    assert result.vcp_state == analysis.state.state.value

    assert (
        result.contraction_count
        == analysis.geometry.confirmed_contraction_count
    )

    assert (
        result.structurally_valid
        == analysis.validity.structurally_valid
    )

    assert result.contraction_depths == tuple(
        contraction.depth_pct
        for contraction in analysis.geometry.contractions
    )

    assert (
        result.final_to_first_depth_ratio
        == analysis.validity.final_to_first_depth_ratio
    )

    assert (
        result.decreasing_step_fraction
        == analysis.validity.decreasing_step_fraction
    )

    assert (
        result.range_5_pct
        == analysis.features.range_5_pct
    )

    assert (
        result.current_tr_compression_10_40
        == analysis.features.true_range_compression_10_40
    )

    assert (
        result.final_contraction_volume_ratio_50
        == analysis.features.final_contraction_volume_ratio_50
    )

    assert (
        result.base_duration_sessions
        == analysis.base_features.base_duration_sessions
    )

    assert (
        result.base_depth_pct
        == analysis.base_features.base_depth_pct
    )

    assert (
        result.base_atr_compression_ratio
        == analysis.base_features.base_atr_compression_ratio
    )

    assert (
        result.base_volume_dryup_ratio
        == analysis.base_features.base_volume_dryup_ratio
    )

    assert result.pivot_price == (
        analysis.breakout.pivot_price
    )

    assert (
        result.distance_to_pivot_pct
        == analysis.features.distance_to_pivot_pct
    )

    assert (
        result.distance_to_pivot_atr
        == analysis.features.distance_to_pivot_atr
    )

    assert (
        result.first_intraday_breach_date
        == analysis.breakout.first_intraday_breach_date
    )

    assert (
        result.first_close_break_date
        == analysis.breakout.first_close_break_date
    )

    assert (
        result.pivot_broken_by_close
        == analysis.breakout.pivot_broken_by_close
    )

    assert (
        result.breakout_volume_ratio_20
        == analysis.breakout.breakout_volume_ratio_20
    )


def test_replay_snapshot_requires_exact_as_of_bar():
    bars = _analysis_bars()

    analysis = analyze_vcp(
        bars,
        state_config=_state_config(),
    )

    with pytest.raises(
        ValueError,
        match="as_of must match the latest technical bar",
    ):
        build_replay_snapshot(
            security_id=123,
            ticker="TEST",
            as_of=bars[-1].date + timedelta(days=1),
            analysis=analysis,
        )


def test_forward_outcome_rejects_unadjusted_reference_bar():
    reference = replace(
        _bar(
            0,
            close=100.0,
        ),
        adjustment_status="UNEXPLAINED_ADJUSTMENT",
    )

    future = tuple(
        _bar(
            session,
            close=100.0 + session,
        )
        for session in range(1, 6)
    )

    with pytest.raises(
        ValueError,
        match="reference bar requires adjustment_status=OK",
    ):
        compute_forward_outcome(
            reference,
            future,
        )


def test_forward_outcome_rejects_invalid_future_ohlc():
    reference = _bar(
        0,
        close=100.0,
    )

    valid = [
        _bar(
            session,
            close=100.0 + session,
        )
        for session in range(1, 5)
    ]

    invalid = replace(
        _bar(
            5,
            close=105.0,
        ),
        high=100.0,
        low=110.0,
    )

    future = tuple(
        valid + [invalid]
    )

    with pytest.raises(
        ValueError,
        match="future bar high cannot be below low",
    ):
        compute_forward_outcome(
            reference,
            future,
        )


from src.research.vcp_replay import (
    VCPReplayRow,
    build_replay_row,
)


def test_replay_row_keeps_snapshot_and_future_outcome_separate():
    bars = _analysis_bars()

    analysis = analyze_vcp(
        bars,
        state_config=_state_config(),
    )

    snapshot = build_replay_snapshot(
        security_id=123,
        ticker="TEST",
        as_of=bars[-1].date,
        analysis=analysis,
    )

    future = tuple(
        _bar(
            session=100 + session,
            close=115.0 + session,
            high=116.0 + session,
            low=114.0 + session,
        )
        for session in range(1, 41)
    )

    outcome = compute_forward_outcome(
        bars[-1],
        future,
    )

    row = build_replay_row(
        snapshot,
        outcome,
    )

    assert isinstance(
        row,
        VCPReplayRow,
    )

    assert row.snapshot == snapshot
    assert row.outcome == outcome

    assert (
        row.snapshot.as_of
        == row.outcome.reference_date
    )


def test_replay_row_rejects_mismatched_reference_date():
    bars = _analysis_bars()

    analysis = analyze_vcp(
        bars,
        state_config=_state_config(),
    )

    snapshot = build_replay_snapshot(
        security_id=123,
        ticker="TEST",
        as_of=bars[-1].date,
        analysis=analysis,
    )

    future = tuple(
        _bar(
            session=100 + session,
            close=115.0 + session,
        )
        for session in range(1, 41)
    )

    wrong_reference = replace(
        bars[-1],
        date=bars[-1].date + timedelta(days=1),
    )

    outcome = compute_forward_outcome(
        wrong_reference,
        future,
    )

    with pytest.raises(
        ValueError,
        match="snapshot as_of must match outcome reference_date",
    ):
        build_replay_row(
            snapshot,
            outcome,
        )


from src.data.storage.adjustments import (
    AdjustmentRecord,
    upsert_price_adjustments,
)
from src.data.storage.database import Database
from src.research.vcp_replay import build_replay_row_from_db


@pytest.fixture()
def replay_db(tmp_path):
    database = Database(
        tmp_path / "replay.db"
    )
    database.initialize()

    yield database

    database.close()


def _db_add_security(conn) -> int:
    now = "2026-10-05T00:00:00+03:00"

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
            "Replay Test AS",
            "2025-01-01",
            now,
            now,
        ),
    )

    return int(cursor.lastrowid)


def _db_add_identifier(
    conn,
    security_id: int,
    *,
    ticker: str,
    valid_from: date,
    valid_to: date | None,
    is_current: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO security_identifiers(
            security_id,
            ticker,
            valid_from,
            valid_to,
            is_current,
            source
        )
        VALUES (?, ?, ?, ?, ?, 'TEST')
        """,
        (
            security_id,
            ticker,
            valid_from.isoformat(),
            (
                valid_to.isoformat()
                if valid_to is not None
                else None
            ),
            1 if is_current else 0,
        ),
    )


def _db_add_yahoo_bar(
    conn,
    security_id: int,
    day: date,
    *,
    close: float,
) -> None:
    now = "2026-10-05T00:00:00+03:00"

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
        VALUES (
            ?, ?, ?, ?, ?, ?, ?,
            'TEST',
            'Yahoo Finance',
            ?
        )
        """,
        (
            security_id,
            day.isoformat(),
            close - 1.0,
            close + 2.0,
            close - 2.0,
            close,
            1_000_000.0,
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


def test_build_replay_row_from_db_uses_historical_ticker_and_future_sessions(
    replay_db,
):
    conn = replay_db.conn

    security_id = _db_add_security(
        conn
    )

    first_day = date(2026, 1, 1)

    days = tuple(
        first_day + timedelta(days=index)
        for index in range(100)
    )

    as_of = days[59]
    ticker_change_date = days[70]

    _db_add_identifier(
        conn,
        security_id,
        ticker="OLD",
        valid_from=days[0],
        valid_to=ticker_change_date,
        is_current=False,
    )

    _db_add_identifier(
        conn,
        security_id,
        ticker="NEW",
        valid_from=ticker_change_date,
        valid_to=None,
        is_current=True,
    )

    for index, day in enumerate(days):
        _db_add_yahoo_bar(
            conn,
            security_id,
            day,
            close=100.0 + index,
        )

    conn.commit()

    row = build_replay_row_from_db(
        conn,
        security_id,
        as_of=as_of,
        state_config=_state_config(),
    )

    # Replay identity must use the ticker that was
    # valid on the historical as-of date, not today's ticker.
    assert row.snapshot.ticker == "OLD"

    assert row.snapshot.security_id == security_id
    assert row.snapshot.as_of == as_of

    assert (
        row.outcome.reference_date
        == as_of
    )

    # as_of index 59 -> close = 159.
    assert row.outcome.reference_close == pytest.approx(
        159.0
    )

    # 40th FUTURE session is index 99 -> close = 199.
    assert row.outcome.forward_return_40 == pytest.approx(
        199.0 / 159.0 - 1.0
    )

    # Highest HIGH inside those 40 future sessions:
    # index 99 close 199 + 2 = 201.
    assert row.outcome.mfe_40 == pytest.approx(
        201.0 / 159.0 - 1.0
    )

    # Lowest LOW is first future session:
    # index 60 close 160 - 2 = 158.
    assert row.outcome.mae_40 == pytest.approx(
        158.0 / 159.0 - 1.0
    )

    # Sanity check: current identifier is already NEW.
    current_ticker = conn.execute(
        """
        SELECT ticker
        FROM security_identifiers
        WHERE security_id=?
          AND is_current=1
        """,
        (security_id,),
    ).fetchone()[0]

    assert current_ticker == "NEW"


from src.research.vcp_replay import historical_equities


def test_historical_equities_ignore_current_active_status_and_require_as_of_bar(
    replay_db,
):
    conn = replay_db.conn

    as_of = date(2026, 5, 15)

    # --------------------------------------------------
    # 1. Historical survivor:
    # currently inactive/delisted, but really traded on as_of.
    # Must be INCLUDED.
    # --------------------------------------------------

    historical_id = _db_add_security(conn)

    _db_add_identifier(
        conn,
        historical_id,
        ticker="HIST",
        valid_from=date(2025, 1, 1),
        valid_to=None,
        is_current=True,
    )

    _db_add_yahoo_bar(
        conn,
        historical_id,
        as_of,
        close=100.0,
    )

    conn.execute(
        """
        UPDATE securities
        SET active=0,
            status='DELISTED'
        WHERE security_id=?
        """,
        (historical_id,),
    )

    # --------------------------------------------------
    # 2. Identifier exists, but no exact as_of bar.
    # Must be EXCLUDED.
    # --------------------------------------------------

    no_bar_id = _db_add_security(conn)

    _db_add_identifier(
        conn,
        no_bar_id,
        ticker="NOBAR",
        valid_from=date(2025, 1, 1),
        valid_to=None,
        is_current=True,
    )

    _db_add_yahoo_bar(
        conn,
        no_bar_id,
        as_of - timedelta(days=1),
        close=90.0,
    )

    # --------------------------------------------------
    # 3. Inconsistent legacy data:
    # price exists before declared first_trade_date.
    # first_trade_date must still fail closed.
    # --------------------------------------------------

    future_listing_id = _db_add_security(conn)

    _db_add_identifier(
        conn,
        future_listing_id,
        ticker="FUTURE",
        valid_from=date(2026, 1, 1),
        valid_to=None,
        is_current=True,
    )

    _db_add_yahoo_bar(
        conn,
        future_listing_id,
        as_of,
        close=80.0,
    )

    conn.execute(
        """
        UPDATE securities
        SET first_trade_date=?
        WHERE security_id=?
        """,
        (
            date(2026, 6, 1).isoformat(),
            future_listing_id,
        ),
    )

    # --------------------------------------------------
    # 4. Ticker changed later.
    # Historical universe must use OLD ticker at as_of.
    # --------------------------------------------------

    changed_id = _db_add_security(conn)

    change_date = date(2026, 6, 1)

    _db_add_identifier(
        conn,
        changed_id,
        ticker="OLD",
        valid_from=date(2025, 1, 1),
        valid_to=change_date,
        is_current=False,
    )

    _db_add_identifier(
        conn,
        changed_id,
        ticker="NEW",
        valid_from=change_date,
        valid_to=None,
        is_current=True,
    )

    _db_add_yahoo_bar(
        conn,
        changed_id,
        as_of,
        close=110.0,
    )

    conn.commit()

    result = historical_equities(
        conn,
        as_of=as_of,
    )

    by_id = {
        item.security_id: item
        for item in result
    }

    assert historical_id in by_id
    assert by_id[historical_id].ticker == "HIST"

    assert changed_id in by_id
    assert by_id[changed_id].ticker == "OLD"

    assert no_bar_id not in by_id
    assert future_listing_id not in by_id


from src.research.vcp_replay import (
    VCPReplayBatch,
    VCPReplaySkip,
    build_replay_batch,
)


def test_build_replay_batch_keeps_rows_and_expected_skips_separate(
    replay_db,
):
    conn = replay_db.conn

    as_of = date(2026, 5, 15)

    # --------------------------------------------------
    # GOOD:
    # exact as_of price + matching adjustment metadata.
    # --------------------------------------------------

    good_id = _db_add_security(
        conn
    )

    _db_add_identifier(
        conn,
        good_id,
        ticker="GOOD",
        valid_from=date(2025, 1, 1),
        valid_to=None,
        is_current=True,
    )

    _db_add_yahoo_bar(
        conn,
        good_id,
        as_of,
        close=100.0,
    )

    # --------------------------------------------------
    # BAD:
    # exact canonical as_of price exists, so it belongs
    # to the historical universe, but adjustment metadata
    # is deliberately missing.
    # --------------------------------------------------

    bad_id = _db_add_security(
        conn
    )

    _db_add_identifier(
        conn,
        bad_id,
        ticker="BAD",
        valid_from=date(2025, 1, 1),
        valid_to=None,
        is_current=True,
    )

    now = "2026-10-05T00:00:00+03:00"

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
        VALUES (
            ?, ?, ?, ?, ?, ?, ?,
            'BAD',
            'Yahoo Finance',
            ?
        )
        """,
        (
            bad_id,
            as_of.isoformat(),
            99.0,
            102.0,
            98.0,
            100.0,
            1_000_000.0,
            now,
        ),
    )

    conn.commit()

    batch = build_replay_batch(
        conn,
        as_of=as_of,
        state_config=_state_config(),
    )

    assert isinstance(
        batch,
        VCPReplayBatch,
    )

    assert len(batch.rows) == 1
    assert batch.rows[0].snapshot.security_id == good_id
    assert batch.rows[0].snapshot.ticker == "GOOD"
    assert batch.rows[0].snapshot.as_of == as_of

    assert len(batch.skips) == 1

    skip = batch.skips[0]

    assert isinstance(
        skip,
        VCPReplaySkip,
    )

    assert skip.security_id == bad_id
    assert skip.ticker == "BAD"
    assert skip.as_of == as_of

    assert isinstance(skip.reason, str)
    assert skip.reason


import src.research.vcp_replay as replay_module


def test_replay_batch_does_not_swallow_programming_errors(
    replay_db,
    monkeypatch,
):
    conn = replay_db.conn
    as_of = date(2026, 5, 15)

    security_id = _db_add_security(
        conn
    )

    _db_add_identifier(
        conn,
        security_id,
        ticker="BUG",
        valid_from=date(2025, 1, 1),
        valid_to=None,
        is_current=True,
    )

    _db_add_yahoo_bar(
        conn,
        security_id,
        as_of,
        close=100.0,
    )

    conn.commit()

    def broken_builder(*args, **kwargs):
        raise TypeError(
            "simulated programming error"
        )

    monkeypatch.setattr(
        replay_module,
        "build_replay_row_from_db",
        broken_builder,
    )

    with pytest.raises(
        TypeError,
        match="simulated programming error",
    ):
        build_replay_batch(
            conn,
            as_of=as_of,
            state_config=_state_config(),
        )


def test_historical_batch_is_independent_of_current_active_and_status(
    replay_db,
):
    conn = replay_db.conn
    as_of = date(2026, 5, 15)

    security_id = _db_add_security(
        conn
    )

    _db_add_identifier(
        conn,
        security_id,
        ticker="HISTB",
        valid_from=date(2025, 1, 1),
        valid_to=None,
        is_current=True,
    )

    _db_add_yahoo_bar(
        conn,
        security_id,
        as_of,
        close=100.0,
    )

    conn.commit()

    before = build_replay_batch(
        conn,
        as_of=as_of,
        state_config=_state_config(),
    )

    assert tuple(
        row.snapshot.security_id
        for row in before.rows
    ) == (
        security_id,
    )

    conn.execute(
        """
        UPDATE securities
        SET active=0,
            status='DELISTED'
        WHERE security_id=?
        """,
        (security_id,),
    )

    conn.commit()

    after = build_replay_batch(
        conn,
        as_of=as_of,
        state_config=_state_config(),
    )

    assert tuple(
        row.snapshot.security_id
        for row in after.rows
    ) == (
        security_id,
    )

    assert after.rows[0].snapshot.ticker == "HISTB"
    assert after.rows[0].snapshot.as_of == as_of

    assert after.skips == before.skips


def test_batch_preserves_snapshot_when_only_future_outcome_fails(
    replay_db,
):
    conn = replay_db.conn

    as_of = date(2026, 5, 15)
    future_day = as_of + timedelta(days=1)

    security_id = _db_add_security(
        conn
    )

    _db_add_identifier(
        conn,
        security_id,
        ticker="OUTFAIL",
        valid_from=date(2025, 1, 1),
        valid_to=None,
        is_current=True,
    )

    # Historical snapshot data is fully valid.
    _db_add_yahoo_bar(
        conn,
        security_id,
        as_of,
        close=100.0,
    )

    # Future canonical price exists, but adjustment metadata is
    # deliberately missing. Snapshot should survive; only the
    # outcome label should fail.
    now = "2026-10-05T00:00:00+03:00"

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
        VALUES (
            ?, ?, ?, ?, ?, ?, ?,
            'OUTFAIL',
            'Yahoo Finance',
            ?
        )
        """,
        (
            security_id,
            future_day.isoformat(),
            100.0,
            103.0,
            99.0,
            102.0,
            1_000_000.0,
            now,
        ),
    )

    conn.commit()

    batch = build_replay_batch(
        conn,
        as_of=as_of,
        state_config=_state_config(),
    )

    assert len(batch.snapshots) == 1

    snapshot = batch.snapshots[0]

    assert snapshot.security_id == security_id
    assert snapshot.ticker == "OUTFAIL"
    assert snapshot.as_of == as_of

    assert batch.rows == ()

    assert len(batch.skips) == 1

    skip = batch.skips[0]

    assert skip.security_id == security_id
    assert skip.ticker == "OUTFAIL"
    assert skip.as_of == as_of
    assert skip.stage == "OUTCOME"
    assert skip.reason


from src.research.vcp_replay import (
    VCPReplayGrid,
    build_replay_grid,
)


def test_build_replay_grid_preserves_explicit_as_of_order(
    replay_db,
):
    conn = replay_db.conn

    security_id = _db_add_security(conn)

    _db_add_identifier(
        conn,
        security_id,
        ticker="GRID",
        valid_from=date(2025, 1, 1),
        valid_to=None,
        is_current=True,
    )

    dates = (
        date(2026, 5, 15),
        date(2026, 6, 15),
        date(2026, 7, 15),
    )

    for index, day in enumerate(dates):
        _db_add_yahoo_bar(
            conn,
            security_id,
            day,
            close=100.0 + index,
        )

    conn.commit()

    grid = build_replay_grid(
        conn,
        as_of_dates=dates,
        state_config=_state_config(),
    )

    assert isinstance(
        grid,
        VCPReplayGrid,
    )

    assert tuple(
        batch.as_of
        for batch in grid.batches
    ) == dates

    assert len(grid.batches) == 3

    for expected_date, batch in zip(
        dates,
        grid.batches,
    ):
        assert batch.as_of == expected_date
        assert len(batch.snapshots) == 1
        assert batch.snapshots[0].security_id == security_id
        assert batch.snapshots[0].as_of == expected_date


def test_build_replay_grid_rejects_duplicate_or_unsorted_dates(
    replay_db,
):
    conn = replay_db.conn

    with pytest.raises(
        ValueError,
        match="strictly increasing",
    ):
        build_replay_grid(
            conn,
            as_of_dates=(
                date(2026, 6, 15),
                date(2026, 5, 15),
            ),
            state_config=_state_config(),
        )

    with pytest.raises(
        ValueError,
        match="strictly increasing",
    ):
        build_replay_grid(
            conn,
            as_of_dates=(
                date(2026, 5, 15),
                date(2026, 5, 15),
            ),
            state_config=_state_config(),
        )


def test_replay_grid_preserves_per_date_outcome_skips_and_continues(
    replay_db,
    monkeypatch,
):
    conn = replay_db.conn

    dates = (
        date(2026, 5, 29),
        date(2026, 6, 30),
        date(2026, 7, 31),
    )

    calls = []

    def fake_build_replay_batch(
        conn_arg,
        *,
        as_of,
        state_config,
        swing_config=None,
        atr_period=14,
    ):
        assert conn_arg is conn

        calls.append(as_of)

        if as_of == dates[1]:
            return VCPReplayBatch(
                as_of=as_of,
                snapshots=(),
                rows=(),
                skips=(
                    VCPReplaySkip(
                        security_id=123,
                        ticker="MID",
                        as_of=as_of,
                        stage="OUTCOME",
                        reason="simulated future-label failure",
                    ),
                ),
            )

        return VCPReplayBatch(
            as_of=as_of,
            snapshots=(),
            rows=(),
            skips=(),
        )

    monkeypatch.setattr(
        replay_module,
        "build_replay_batch",
        fake_build_replay_batch,
    )

    grid = build_replay_grid(
        conn,
        as_of_dates=dates,
        state_config=_state_config(),
    )

    assert calls == list(dates)

    assert tuple(
        batch.as_of
        for batch in grid.batches
    ) == dates

    assert grid.batches[0].skips == ()

    middle_skips = grid.batches[1].skips

    assert len(middle_skips) == 1
    assert middle_skips[0].stage == "OUTCOME"
    assert middle_skips[0].ticker == "MID"
    assert middle_skips[0].as_of == dates[1]

    assert grid.batches[2].skips == ()
