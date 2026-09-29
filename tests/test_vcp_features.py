from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.strategy.swing_detector import SwingPivot
from src.strategy.technical_prices import TechnicalPriceBar
from src.strategy.vcp_geometry import analyze_vcp_geometry
from src.strategy.vcp_features import compute_vcp_features


BASE_DATE = date(2026, 1, 1)


def _date(index: int) -> date:
    return BASE_DATE + timedelta(days=index - 1)


def _bar(
    index: int,
    *,
    open_: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
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
    confirmation_index: int | None,
) -> SwingPivot:
    return SwingPivot(
        kind=kind,
        price=price,
        extreme_date=_date(extreme_index),
        confirmation_date=(
            _date(confirmation_index)
            if confirmation_index is not None
            else None
        ),
        threshold_pct=2.0,
    )


def test_range_5_and_10_use_technical_highs_and_lows():
    bars = []

    for index in range(1, 11):
        if index == 1:
            bars.append(
                _bar(
                    index,
                    high=120.0,
                    low=80.0,
                )
            )
        elif index == 6:
            bars.append(
                _bar(
                    index,
                    high=110.0,
                    low=90.0,
                )
            )
        else:
            bars.append(
                _bar(index)
            )

    geometry = analyze_vcp_geometry([])

    result = compute_vcp_features(
        bars,
        geometry,
    )

    assert result.range_5_pct == pytest.approx(
        (110.0 - 90.0) / 110.0 * 100.0
    )

    assert result.range_10_pct == pytest.approx(
        (120.0 - 80.0) / 120.0 * 100.0
    )


def test_range_features_require_full_lookback():
    bars = [
        _bar(index)
        for index in range(1, 8)
    ]

    result = compute_vcp_features(
        bars,
        analyze_vcp_geometry([]),
    )

    assert result.range_5_pct is not None
    assert result.range_10_pct is None


def test_true_range_compression_uses_non_overlapping_10_and_40_windows():
    bars = []

    # First bar only supplies the previous close required
    # for the first True Range observation.
    bars.append(
        _bar(
            1,
            high=100.0,
            low=100.0,
        )
    )

    # 40 prior TR observations:
    # TR = (102 - 98) / 100 = 4%
    for index in range(2, 42):
        bars.append(
            _bar(
                index,
                high=102.0,
                low=98.0,
                close=100.0,
            )
        )

    # Most recent 10 TR observations:
    # TR = (101 - 99) / 100 = 2%
    for index in range(42, 52):
        bars.append(
            _bar(
                index,
                high=101.0,
                low=99.0,
                close=100.0,
            )
        )

    result = compute_vcp_features(
        bars,
        analyze_vcp_geometry([]),
    )

    assert (
        result.true_range_compression_10_40
        == pytest.approx(0.50)
    )


def test_true_range_compression_requires_51_price_bars():
    bars = [
        _bar(index)
        for index in range(1, 51)
    ]

    result = compute_vcp_features(
        bars,
        analyze_vcp_geometry([]),
    )

    assert (
        result.true_range_compression_10_40
        is None
    )


def test_final_contraction_volume_ratio_uses_previous_50_sessions():
    bars = []

    for index in range(1, 66):
        volume = 1_000.0

        # Final confirmed contraction:
        # HIGH extreme day 58 -> LOW extreme day 64.
        if 58 <= index <= 64:
            volume = 250.0

        bars.append(
            _bar(
                index,
                volume=volume,
            )
        )

    high = _pivot(
        "HIGH",
        110.0,
        58,
        60,
    )

    low = _pivot(
        "LOW",
        100.0,
        64,
        65,
    )

    geometry = analyze_vcp_geometry(
        [high, low]
    )

    result = compute_vcp_features(
        bars,
        geometry,
    )

    assert (
        result.final_contraction_volume_ratio_50
        == pytest.approx(0.25)
    )


def test_final_contraction_volume_ratio_needs_50_prior_sessions():
    bars = [
        _bar(index)
        for index in range(1, 31)
    ]

    geometry = analyze_vcp_geometry(
        [
            _pivot(
                "HIGH",
                110.0,
                20,
                22,
            ),
            _pivot(
                "LOW",
                100.0,
                28,
                30,
            ),
        ]
    )

    result = compute_vcp_features(
        bars,
        geometry,
    )

    assert (
        result.final_contraction_volume_ratio_50
        is None
    )


def test_pivot_distance_is_reported_in_percent_and_atr_units():
    bars = [
        _bar(
            index,
            close=98.0,
            high=100.0,
            low=97.0,
            open_=98.0,
        )
        for index in range(1, 21)
    ]

    geometry = analyze_vcp_geometry(
        [
            _pivot(
                "HIGH",
                100.0,
                10,
                12,
            ),
            _pivot(
                "LOW",
                90.0,
                15,
                17,
            ),
        ]
    )

    result = compute_vcp_features(
        bars,
        geometry,
        atr_pct=2.0,
    )

    assert (
        result.distance_to_pivot_pct
        == pytest.approx(-2.0)
    )

    assert (
        result.distance_to_pivot_atr
        == pytest.approx(-1.0)
    )


def test_pivot_distance_is_none_when_no_confirmed_pivot_exists():
    bars = [
        _bar(index)
        for index in range(1, 21)
    ]

    result = compute_vcp_features(
        bars,
        analyze_vcp_geometry([]),
        atr_pct=2.0,
    )

    assert result.distance_to_pivot_pct is None
    assert result.distance_to_pivot_atr is None


def test_missing_atr_keeps_percent_distance_but_not_atr_distance():
    bars = [
        _bar(
            index,
            close=98.0,
            high=100.0,
            low=97.0,
            open_=98.0,
        )
        for index in range(1, 21)
    ]

    geometry = analyze_vcp_geometry(
        [
            _pivot(
                "HIGH",
                100.0,
                10,
                12,
            ),
            _pivot(
                "LOW",
                90.0,
                15,
                17,
            ),
        ]
    )

    result = compute_vcp_features(
        bars,
        geometry,
        atr_pct=None,
    )

    assert (
        result.distance_to_pivot_pct
        == pytest.approx(-2.0)
    )

    assert result.distance_to_pivot_atr is None


def test_provisional_swing_is_described_but_not_promoted_to_pivot():
    confirmed = [
        _pivot(
            "HIGH",
            100.0,
            10,
            12,
        ),
        _pivot(
            "LOW",
            90.0,
            15,
            17,
        ),
    ]

    provisional = _pivot(
        "HIGH",
        98.0,
        20,
        None,
    )

    geometry = analyze_vcp_geometry(
        confirmed,
        provisional=provisional,
    )

    bars = [
        _bar(index)
        for index in range(1, 21)
    ]

    result = compute_vcp_features(
        bars,
        geometry,
    )

    assert result.has_provisional_swing is True
    assert result.provisional_kind == "HIGH"

    assert (
        result.provisional_distance_to_pivot_pct
        == pytest.approx(-2.0)
    )

    # The confirmed pivot remains 100, not the provisional 98.
    assert geometry.pivot is not None
    assert geometry.pivot.price == pytest.approx(100.0)


def test_unexplained_adjustment_fails_closed():
    bars = [
        _bar(1),
        _bar(
            2,
            adjustment_status="UNEXPLAINED_ADJUSTMENT",
        ),
    ]

    with pytest.raises(
        ValueError,
        match="UNEXPLAINED_ADJUSTMENT",
    ):
        compute_vcp_features(
            bars,
            analyze_vcp_geometry([]),
        )
