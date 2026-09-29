from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.strategy.technical_prices import TechnicalPriceBar
from src.strategy.vcp_breakout import VCPBreakoutEvent
from src.strategy.vcp_follow_through import (
    measure_vcp_follow_through,
)


BASE_DATE = date(2026, 1, 1)


def _date(index: int) -> date:
    return BASE_DATE + timedelta(days=index - 1)


def _bar(
    index: int,
    *,
    open_: float = 99.0,
    high: float = 101.0,
    low: float = 98.0,
    close: float = 99.0,
    volume: float = 1_000.0,
    adjustment_status: str = "OK",
) -> TechnicalPriceBar:
    return TechnicalPriceBar(
        date=_date(index),

        open=open_,
        high=high,
        low=low,
        close=close,

        volume=volume,

        raw_open=open_,
        raw_high=high,
        raw_low=low,
        raw_close=close,
        adj_close=close,

        dividend=0.0,
        stock_split=0.0,

        adjustment_factor=1.0,
        adjustment_status=adjustment_status,
    )


def _breakout(
    *,
    pivot_price: float = 100.0,
    breakout_index: int | None = 21,
) -> VCPBreakoutEvent:
    if breakout_index is None:
        return VCPBreakoutEvent(
            has_confirmed_pivot=True,
            pivot_price=pivot_price,
            structure_ready_date=_date(10),

            first_intraday_breach_date=None,
            first_close_break_date=None,

            pivot_broken_by_close=False,

            breakout_close_pct_above_pivot=None,
            breakout_volume_ratio_20=None,

            current_close_above_pivot=False,
        )

    return VCPBreakoutEvent(
        has_confirmed_pivot=True,
        pivot_price=pivot_price,
        structure_ready_date=_date(10),

        first_intraday_breach_date=_date(
            breakout_index
        ),
        first_close_break_date=_date(
            breakout_index
        ),

        pivot_broken_by_close=True,

        breakout_close_pct_above_pivot=1.0,
        breakout_volume_ratio_20=1.5,

        current_close_above_pivot=True,
    )


def test_no_close_breakout_has_no_follow_through_window():
    bars = [
        _bar(index)
        for index in range(1, 25)
    ]

    result = measure_vcp_follow_through(
        bars,
        _breakout(
            breakout_index=None,
        ),
    )

    assert result.has_close_breakout is False
    assert result.breakout_date is None
    assert result.pivot_price == pytest.approx(100.0)

    assert result.post_breakout_sessions == 0
    assert result.post_breakout_closes_above_pivot == 0

    assert (
        result.post_breakout_close_above_pivot_share
        is None
    )

    assert (
        result.max_post_breakout_close_pct_above_pivot
        is None
    )

    assert (
        result.min_post_breakout_close_pct_above_pivot
        is None
    )

    assert (
        result.latest_close_pct_above_pivot
        is None
    )

    assert (
        result.median_post_breakout_volume_ratio_20
        is None
    )


def test_breakout_day_itself_is_not_counted_as_follow_through():
    bars = [
        _bar(index)
        for index in range(1, 21)
    ]

    bars.append(
        _bar(
            21,
            open_=99.0,
            high=102.0,
            low=98.0,
            close=101.0,
            volume=1_500.0,
        )
    )

    result = measure_vcp_follow_through(
        bars,
        _breakout(
            breakout_index=21,
        ),
    )

    assert result.has_close_breakout is True
    assert result.breakout_date == _date(21)

    assert result.post_breakout_sessions == 0
    assert result.post_breakout_closes_above_pivot == 0

    assert (
        result.post_breakout_close_above_pivot_share
        is None
    )

    assert (
        result.max_post_breakout_close_pct_above_pivot
        is None
    )

    assert (
        result.median_post_breakout_volume_ratio_20
        is None
    )


def test_post_breakout_close_persistence_is_measured():
    bars = [
        _bar(index)
        for index in range(1, 21)
    ]

    # Breakout day.
    bars.append(
        _bar(
            21,
            open_=99.0,
            high=102.0,
            low=98.0,
            close=101.0,
        )
    )

    # Follow-through session 1:
    # closes 3% above pivot.
    bars.append(
        _bar(
            22,
            open_=101.0,
            high=104.0,
            low=100.0,
            close=103.0,
        )
    )

    # Follow-through session 2:
    # closes 2% below pivot.
    bars.append(
        _bar(
            23,
            open_=99.0,
            high=100.0,
            low=97.0,
            close=98.0,
        )
    )

    result = measure_vcp_follow_through(
        bars,
        _breakout(
            breakout_index=21,
        ),
    )

    assert result.post_breakout_sessions == 2

    assert (
        result.post_breakout_closes_above_pivot
        == 1
    )

    assert (
        result.post_breakout_close_above_pivot_share
        == pytest.approx(0.50)
    )

    assert (
        result.max_post_breakout_close_pct_above_pivot
        == pytest.approx(3.0)
    )

    assert (
        result.min_post_breakout_close_pct_above_pivot
        == pytest.approx(-2.0)
    )

    assert (
        result.latest_close_pct_above_pivot
        == pytest.approx(-2.0)
    )


def test_touching_pivot_is_not_counted_as_close_above():
    bars = [
        _bar(index)
        for index in range(1, 21)
    ]

    bars.append(
        _bar(
            21,
            close=101.0,
            high=102.0,
        )
    )

    bars.append(
        _bar(
            22,
            open_=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
        )
    )

    result = measure_vcp_follow_through(
        bars,
        _breakout(
            breakout_index=21,
        ),
    )

    assert result.post_breakout_sessions == 1

    assert (
        result.post_breakout_closes_above_pivot
        == 0
    )

    assert (
        result.post_breakout_close_above_pivot_share
        == pytest.approx(0.0)
    )

    assert (
        result.latest_close_pct_above_pivot
        == pytest.approx(0.0)
    )


def test_post_breakout_volume_ratio_uses_pre_breakout_20_session_baseline():
    bars = []

    # Exactly 20 sessions before breakout,
    # all with volume = 1000.
    for index in range(1, 21):
        bars.append(
            _bar(
                index,
                volume=1_000.0,
            )
        )

    # Breakout-day volume is intentionally large.
    # It must not contaminate either side of the
    # post-breakout volume comparison.
    bars.append(
        _bar(
            21,
            close=101.0,
            high=102.0,
            volume=5_000.0,
        )
    )

    # Two post-breakout sessions.
    bars.append(
        _bar(
            22,
            close=102.0,
            high=103.0,
            volume=1_500.0,
        )
    )

    bars.append(
        _bar(
            23,
            close=103.0,
            high=104.0,
            volume=2_000.0,
        )
    )

    result = measure_vcp_follow_through(
        bars,
        _breakout(
            breakout_index=21,
        ),
    )

    # median(1500, 2000) / median(previous 20 x 1000)
    # = 1750 / 1000
    assert (
        result.median_post_breakout_volume_ratio_20
        == pytest.approx(1.75)
    )


def test_post_breakout_volume_ratio_requires_20_pre_breakout_sessions():
    bars = [
        _bar(index)
        for index in range(1, 11)
    ]

    bars.append(
        _bar(
            11,
            close=101.0,
            high=102.0,
        )
    )

    bars.append(
        _bar(
            12,
            close=102.0,
            high=103.0,
            volume=2_000.0,
        )
    )

    result = measure_vcp_follow_through(
        bars,
        _breakout(
            breakout_index=11,
        ),
    )

    assert result.post_breakout_sessions == 1

    assert (
        result.median_post_breakout_volume_ratio_20
        is None
    )


def test_zero_pre_breakout_volume_baseline_returns_none():
    bars = []

    for index in range(1, 21):
        bars.append(
            _bar(
                index,
                volume=0.0,
            )
        )

    bars.append(
        _bar(
            21,
            close=101.0,
            high=102.0,
            volume=5_000.0,
        )
    )

    bars.append(
        _bar(
            22,
            close=102.0,
            high=103.0,
            volume=2_000.0,
        )
    )

    result = measure_vcp_follow_through(
        bars,
        _breakout(
            breakout_index=21,
        ),
    )

    assert (
        result.median_post_breakout_volume_ratio_20
        is None
    )


def test_historical_breakout_remains_even_when_latest_close_is_below_pivot():
    bars = [
        _bar(index)
        for index in range(1, 21)
    ]

    bars.append(
        _bar(
            21,
            close=101.0,
            high=102.0,
        )
    )

    bars.append(
        _bar(
            22,
            open_=99.0,
            high=100.0,
            low=96.0,
            close=97.0,
        )
    )

    result = measure_vcp_follow_through(
        bars,
        _breakout(
            breakout_index=21,
        ),
    )

    assert result.has_close_breakout is True
    assert result.breakout_date == _date(21)

    assert result.post_breakout_sessions == 1

    assert (
        result.latest_close_pct_above_pivot
        == pytest.approx(-3.0)
    )


def test_breakout_date_must_exist_in_supplied_price_series():
    bars = [
        _bar(index)
        for index in range(1, 15)
    ]

    with pytest.raises(
        ValueError,
        match="breakout date",
    ):
        measure_vcp_follow_through(
            bars,
            _breakout(
                breakout_index=21,
            ),
        )


def test_unexplained_adjustment_fails_closed():
    bars = [
        _bar(index)
        for index in range(1, 23)
    ]

    bars[21] = _bar(
        22,
        adjustment_status="UNEXPLAINED_ADJUSTMENT",
    )

    with pytest.raises(
        ValueError,
        match="UNEXPLAINED_ADJUSTMENT",
    ):
        measure_vcp_follow_through(
            bars,
            _breakout(
                breakout_index=21,
            ),
        )


def test_price_bars_must_be_strictly_increasing():
    bars = [
        _bar(1),
        _bar(2),
        _bar(2),
    ]

    with pytest.raises(
        ValueError,
        match="strictly increasing",
    ):
        measure_vcp_follow_through(
            bars,
            _breakout(
                breakout_index=None,
            ),
        )


def test_inconsistent_breakout_event_fails_closed():
    bars = [
        _bar(index)
        for index in range(1, 25)
    ]

    event = VCPBreakoutEvent(
        has_confirmed_pivot=True,
        pivot_price=100.0,
        structure_ready_date=_date(10),

        first_intraday_breach_date=_date(21),
        first_close_break_date=None,

        # Inconsistent:
        # flag says broken, but there is no close-break date.
        pivot_broken_by_close=True,

        breakout_close_pct_above_pivot=None,
        breakout_volume_ratio_20=None,

        current_close_above_pivot=True,
    )

    with pytest.raises(
        ValueError,
        match="inconsistent breakout",
    ):
        measure_vcp_follow_through(
            bars,
            event,
        )
