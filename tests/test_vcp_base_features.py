from __future__ import annotations

from datetime import date, timedelta
from statistics import median

import pytest

from src.indicators.atr import atr_percent_series
from src.strategy.swing_detector import SwingPivot
from src.strategy.technical_prices import TechnicalPriceBar
from src.strategy.vcp_base_features import compute_vcp_base_features
from src.strategy.vcp_geometry import analyze_vcp_geometry


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
        adjustment_status="OK",
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


def _geometry(
    *,
    first_high_index: int = 21,
):
    return analyze_vcp_geometry(
        [
            _pivot(
                "HIGH",
                120.0,
                first_high_index,
                first_high_index + 1,
            ),
            _pivot(
                "LOW",
                90.0,
                first_high_index + 9,
                first_high_index + 10,
            ),
            _pivot(
                "HIGH",
                112.0,
                first_high_index + 19,
                first_high_index + 20,
            ),
            _pivot(
                "LOW",
                100.0,
                first_high_index + 29,
                first_high_index + 30,
            ),
        ]
    )


def test_base_start_duration_and_depth_use_active_structure():
    bars = [
        _bar(index)
        for index in range(1, 61)
    ]

    # Active base begins at session 21.
    bars[20] = _bar(
        21,
        high=120.0,
        low=100.0,
    )

    # Deepest price inside the base.
    bars[29] = _bar(
        30,
        high=101.0,
        low=90.0,
    )

    geometry = _geometry(
        first_high_index=21,
    )

    result = compute_vcp_base_features(
        bars,
        geometry,
        end_date=_date(60),
    )

    assert result.base_start_date == _date(21)
    assert result.base_end_date == _date(60)

    # Inclusive count of actual supplied trading bars:
    # sessions 21..60 = 40 sessions.
    assert result.base_duration_sessions == 40

    assert result.base_depth_pct == pytest.approx(
        (120.0 - 90.0)
        / 120.0
        * 100.0
    )


def test_base_ratios_compare_second_half_with_first_half():
    bars = []

    # 30 sessions of causal history before the base.
    # These also provide ATR14 warm-up.
    for index in range(1, 31):
        bars.append(
            _bar(
                index,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=1_500.0,
            )
        )

    # First half of base: wider range and higher volume.
    for index in range(31, 51):
        bars.append(
            _bar(
                index,
                high=102.0,
                low=98.0,
                close=100.0,
                volume=2_000.0,
            )
        )

    # Second half of base: tighter range and lower volume.
    for index in range(51, 71):
        bars.append(
            _bar(
                index,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=1_000.0,
            )
        )

    geometry = analyze_vcp_geometry(
        [
            _pivot("HIGH", 102.0, 31, 32),
            _pivot("LOW", 98.0, 40, 41),
            _pivot("HIGH", 101.0, 50, 51),
            _pivot("LOW", 99.0, 60, 61),
        ]
    )

    result = compute_vcp_base_features(
        bars,
        geometry,
        end_date=_date(70),
    )

    assert result.base_duration_sessions == 40

    # Banana-style volume dry-up:
    # second-half median / first-half median.
    assert result.base_volume_dryup_ratio == pytest.approx(
        0.5
    )

    atr_series = atr_percent_series(
        [bar.high for bar in bars],
        [bar.low for bar in bars],
        [bar.close for bar in bars],
        period=14,
    )

    # Base is sessions 31..70 -> Python indexes 30..69.
    base_atr = atr_series[30:70]

    first_half = [
        value
        for value in base_atr[:20]
        if value is not None
    ]

    second_half = [
        value
        for value in base_atr[20:]
        if value is not None
    ]

    expected_ratio = (
        median(second_half)
        / median(first_half)
    )

    assert result.base_atr_compression_ratio == pytest.approx(
        expected_ratio
    )

    assert result.base_atr_compression_ratio < 1.0


def test_bars_after_end_date_cannot_change_base_features():
    bars = []

    for index in range(1, 31):
        bars.append(
            _bar(
                index,
                high=101.0,
                low=99.0,
                volume=1_500.0,
            )
        )

    for index in range(31, 51):
        bars.append(
            _bar(
                index,
                high=102.0,
                low=98.0,
                volume=2_000.0,
            )
        )

    for index in range(51, 71):
        bars.append(
            _bar(
                index,
                high=101.0,
                low=99.0,
                volume=1_000.0,
            )
        )

    geometry = analyze_vcp_geometry(
        [
            _pivot("HIGH", 102.0, 31, 32),
            _pivot("LOW", 98.0, 40, 41),
            _pivot("HIGH", 101.0, 50, 51),
            _pivot("LOW", 99.0, 60, 61),
        ]
    )

    before = compute_vcp_base_features(
        bars,
        geometry,
        end_date=_date(70),
    )

    future_bars = list(bars)

    # Extreme post-base movement must not contaminate
    # a historical snapshot ending at session 70.
    for index in range(71, 81):
        future_bars.append(
            _bar(
                index,
                high=150.0,
                low=50.0,
                close=120.0,
                volume=100_000.0,
            )
        )

    after = compute_vcp_base_features(
        future_bars,
        geometry,
        end_date=_date(70),
    )

    assert after == before


def test_no_active_structure_returns_unavailable_base_features():
    bars = [
        _bar(index)
        for index in range(1, 41)
    ]

    result = compute_vcp_base_features(
        bars,
        analyze_vcp_geometry([]),
        end_date=_date(40),
    )

    assert result.base_start_date is None
    assert result.base_end_date is None
    assert result.base_duration_sessions is None
    assert result.base_depth_pct is None
    assert result.base_atr_compression_ratio is None
    assert result.base_volume_dryup_ratio is None


def test_base_start_date_must_exist_in_price_history():
    bars = [
        _bar(index)
        for index in range(1, 61)
        if index != 21
    ]

    geometry = _geometry(
        first_high_index=21,
    )

    with pytest.raises(
        ValueError,
        match="base start_date must match a technical price bar",
    ):
        compute_vcp_base_features(
            bars,
            geometry,
            end_date=_date(60),
        )


def test_base_end_date_must_exist_in_price_history():
    bars = [
        _bar(index)
        for index in range(1, 60)
    ]

    geometry = _geometry(
        first_high_index=21,
    )

    with pytest.raises(
        ValueError,
        match="base end_date must match a technical price bar",
    ):
        compute_vcp_base_features(
            bars,
            geometry,
            end_date=_date(60),
        )


def test_base_depth_cannot_be_negative():
    bars = [
        _bar(
            index,
            high=130.0,
            low=125.0,
            close=127.0,
        )
        for index in range(1, 61)
    ]

    geometry = _geometry(
        first_high_index=21,
    )

    with pytest.raises(
        ValueError,
        match="base low cannot exceed base anchor high",
    ):
        compute_vcp_base_features(
            bars,
            geometry,
            end_date=_date(60),
        )
