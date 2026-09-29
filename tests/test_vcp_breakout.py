from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.strategy.swing_detector import SwingPivot
from src.strategy.technical_prices import TechnicalPriceBar
from src.strategy.vcp_geometry import analyze_vcp_geometry
from src.strategy.vcp_breakout import detect_vcp_breakout


BASE_DATE = date(2026, 1, 1)


def _date(index: int) -> date:
    return BASE_DATE + timedelta(days=index - 1)


def _bar(
    index: int,
    *,
    open_: float = 95.0,
    high: float = 96.0,
    low: float = 94.0,
    close: float = 95.0,
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


def _pivot(
    kind: str,
    price: float,
    extreme_index: int,
    confirmation_index: int,
) -> SwingPivot:
    return SwingPivot(
        kind=kind,
        price=price,
        extreme_date=_date(extreme_index),
        confirmation_date=_date(confirmation_index),
        threshold_pct=2.0,
    )


def _geometry():
    # Final confirmed contraction:
    #
    # HIGH extreme = day 4
    # HIGH confirmation = day 5
    # LOW extreme = day 8
    # LOW confirmation = day 10
    #
    # Therefore the completed VCP structure becomes causally
    # available only after day 10.
    return analyze_vcp_geometry(
        [
            _pivot(
                "HIGH",
                100.0,
                4,
                5,
            ),
            _pivot(
                "LOW",
                90.0,
                8,
                10,
            ),
        ]
    )


def test_no_confirmed_pivot_produces_no_breakout_event():
    bars = [
        _bar(index)
        for index in range(1, 15)
    ]

    result = detect_vcp_breakout(
        bars,
        analyze_vcp_geometry([]),
    )

    assert result.has_confirmed_pivot is False
    assert result.pivot_price is None
    assert result.structure_ready_date is None

    assert result.first_intraday_breach_date is None
    assert result.first_close_break_date is None

    assert result.pivot_broken_by_close is False
    assert result.breakout_close_pct_above_pivot is None
    assert result.breakout_volume_ratio_20 is None
    assert result.current_close_above_pivot is None


def test_breakout_search_starts_after_final_low_confirmation():
    bars = []

    for index in range(1, 13):
        if index == 9:
            bars.append(
                _bar(
                    index,
                    open_=99.0,
                    high=102.0,
                    low=98.0,
                    close=101.0,
                )
            )
        elif index == 10:
            bars.append(
                _bar(
                    index,
                    open_=100.0,
                    high=103.0,
                    low=99.0,
                    close=102.0,
                )
            )
        else:
            bars.append(
                _bar(index)
            )

    result = detect_vcp_breakout(
        bars,
        _geometry(),
    )

    assert result.structure_ready_date == _date(10)

    # Day 9 is before structure completion.
    # Day 10 is the LOW confirmation day itself.
    # Neither may become a breakout event.
    assert result.first_intraday_breach_date is None
    assert result.first_close_break_date is None
    assert result.pivot_broken_by_close is False


def test_first_eligible_close_above_pivot_is_breakout():
    bars = [
        _bar(index)
        for index in range(1, 11)
    ]

    bars.append(
        _bar(
            11,
            open_=99.0,
            high=102.0,
            low=98.0,
            close=101.0,
        )
    )

    result = detect_vcp_breakout(
        bars,
        _geometry(),
    )

    assert (
        result.first_intraday_breach_date
        == _date(11)
    )

    assert (
        result.first_close_break_date
        == _date(11)
    )

    assert result.pivot_broken_by_close is True

    assert (
        result.breakout_close_pct_above_pivot
        == pytest.approx(1.0)
    )

    assert result.current_close_above_pivot is True


def test_intraday_breach_without_close_is_kept_separate():
    bars = [
        _bar(index)
        for index in range(1, 11)
    ]

    # Day 11 trades above pivot but closes below it.
    bars.append(
        _bar(
            11,
            open_=99.0,
            high=101.0,
            low=98.0,
            close=99.0,
        )
    )

    # Day 12 finally closes above the pivot.
    bars.append(
        _bar(
            12,
            open_=99.0,
            high=102.0,
            low=98.0,
            close=101.0,
        )
    )

    result = detect_vcp_breakout(
        bars,
        _geometry(),
    )

    assert (
        result.first_intraday_breach_date
        == _date(11)
    )

    assert (
        result.first_close_break_date
        == _date(12)
    )

    assert result.pivot_broken_by_close is True


def test_touching_pivot_exactly_is_not_a_breakout():
    bars = [
        _bar(index)
        for index in range(1, 11)
    ]

    bars.append(
        _bar(
            11,
            open_=99.0,
            high=100.0,
            low=98.0,
            close=100.0,
        )
    )

    result = detect_vcp_breakout(
        bars,
        _geometry(),
    )

    assert result.first_intraday_breach_date is None
    assert result.first_close_break_date is None
    assert result.pivot_broken_by_close is False


def test_first_close_break_date_does_not_move_on_later_bars():
    bars = [
        _bar(index)
        for index in range(1, 25)
    ]

    bars.append(
        _bar(
            25,
            open_=99.0,
            high=102.0,
            low=98.0,
            close=101.0,
        )
    )

    bars.append(
        _bar(
            26,
            open_=101.0,
            high=104.0,
            low=100.0,
            close=103.0,
        )
    )

    result = detect_vcp_breakout(
        bars,
        _geometry(),
    )

    assert (
        result.first_close_break_date
        == _date(25)
    )

    assert (
        result.breakout_close_pct_above_pivot
        == pytest.approx(1.0)
    )

    assert result.current_close_above_pivot is True


def test_breakout_volume_ratio_uses_previous_20_sessions_only():
    bars = []

    for index in range(1, 31):
        bars.append(
            _bar(
                index,
                volume=1_000.0,
            )
        )

    # First close breakout on day 31.
    # Breakout-day volume must NOT be included in its own baseline.
    bars.append(
        _bar(
            31,
            open_=99.0,
            high=102.0,
            low=98.0,
            close=101.0,
            volume=1_800.0,
        )
    )

    result = detect_vcp_breakout(
        bars,
        _geometry(),
    )

    assert (
        result.first_close_break_date
        == _date(31)
    )

    assert (
        result.breakout_volume_ratio_20
        == pytest.approx(1.80)
    )


def test_breakout_volume_ratio_requires_20_prior_sessions():
    bars = [
        _bar(index)
        for index in range(1, 15)
    ]

    bars.append(
        _bar(
            15,
            open_=99.0,
            high=102.0,
            low=98.0,
            close=101.0,
            volume=2_000.0,
        )
    )

    result = detect_vcp_breakout(
        bars,
        _geometry(),
    )

    assert (
        result.first_close_break_date
        == _date(15)
    )

    assert result.breakout_volume_ratio_20 is None


def test_zero_volume_baseline_returns_none_instead_of_dividing_by_zero():
    bars = []

    for index in range(1, 31):
        bars.append(
            _bar(
                index,
                volume=0.0,
            )
        )

    bars.append(
        _bar(
            31,
            open_=99.0,
            high=102.0,
            low=98.0,
            close=101.0,
            volume=2_000.0,
        )
    )

    result = detect_vcp_breakout(
        bars,
        _geometry(),
    )

    assert result.pivot_broken_by_close is True
    assert result.breakout_volume_ratio_20 is None


def test_current_close_above_pivot_is_independent_of_historical_breakout():
    bars = [
        _bar(index)
        for index in range(1, 20)
    ]

    # Breakout occurs on day 20.
    bars.append(
        _bar(
            20,
            open_=99.0,
            high=102.0,
            low=98.0,
            close=101.0,
        )
    )

    # Price later moves back below the pivot.
    bars.append(
        _bar(
            21,
            open_=99.0,
            high=100.0,
            low=96.0,
            close=97.0,
        )
    )

    result = detect_vcp_breakout(
        bars,
        _geometry(),
    )

    assert result.pivot_broken_by_close is True

    assert (
        result.first_close_break_date
        == _date(20)
    )

    assert result.current_close_above_pivot is False


def test_unexplained_adjustment_fails_closed():
    bars = [
        _bar(index)
        for index in range(1, 12)
    ]

    bars[10] = _bar(
        11,
        adjustment_status="UNEXPLAINED_ADJUSTMENT",
    )

    with pytest.raises(
        ValueError,
        match="UNEXPLAINED_ADJUSTMENT",
    ):
        detect_vcp_breakout(
            bars,
            _geometry(),
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
        detect_vcp_breakout(
            bars,
            _geometry(),
        )
