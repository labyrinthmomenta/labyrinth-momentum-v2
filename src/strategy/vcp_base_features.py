from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Sequence

from src.indicators.atr import atr_percent_series
from src.strategy.technical_prices import TechnicalPriceBar
from src.strategy.vcp_geometry import VCPGeometry


@dataclass(frozen=True)
class VCPBaseFeatures:
    """Descriptive measurements of the active VCP base.

    These fields are research features only.

    They do not:
    - determine structural validity,
    - classify the VCP lifecycle state,
    - generate an entry signal,
    - contribute to ranking.
    """

    base_start_date: date | None
    base_end_date: date | None
    base_duration_sessions: int | None
    base_depth_pct: float | None
    base_atr_compression_ratio: float | None
    base_volume_dryup_ratio: float | None


def _unavailable() -> VCPBaseFeatures:
    return VCPBaseFeatures(
        base_start_date=None,
        base_end_date=None,
        base_duration_sessions=None,
        base_depth_pct=None,
        base_atr_compression_ratio=None,
        base_volume_dryup_ratio=None,
    )


def _half_ratio(
    values: Sequence[float | None],
) -> float | None:
    """Return median(second half) / median(first half).

    Missing observations are ignored inside each half.

    For an odd number of sessions the second half receives the
    middle/right-side observation. This keeps the split deterministic
    without looking outside the supplied base window.
    """

    if len(values) < 2:
        return None

    midpoint = len(values) // 2

    first_half = [
        float(value)
        for value in values[:midpoint]
        if value is not None
    ]

    second_half = [
        float(value)
        for value in values[midpoint:]
        if value is not None
    ]

    if not first_half or not second_half:
        return None

    first_median = median(first_half)

    if first_median == 0:
        return None

    return (
        median(second_half)
        / first_median
    )


def compute_vcp_base_features(
    bars: Sequence[TechnicalPriceBar],
    geometry: VCPGeometry,
    *,
    end_date: date,
    atr_period: int = 14,
) -> VCPBaseFeatures:
    """Measure the rightmost active VCP base.

    The active base starts at the extreme date of the HIGH belonging
    to the first contraction preserved by ``VCPGeometry``.

    ``end_date`` is supplied by the caller so historical replay can
    choose the causal right edge explicitly. Bars after ``end_date``
    are never used.

    ATR percent is calculated on the complete causal history through
    ``end_date`` first, then restricted to the base window. This
    preserves ATR warm-up observations that occurred before the base.
    """

    if not geometry.contractions:
        return _unavailable()

    start_date = (
        geometry.contractions[0]
        .high
        .extreme_date
    )

    if end_date < start_date:
        raise ValueError(
            "base end_date cannot precede base start_date"
        )

    all_dates = {
        bar.date
        for bar in bars
    }

    if start_date not in all_dates:
        raise ValueError(
            "base start_date must match a technical price bar"
        )

    if end_date not in all_dates:
        raise ValueError(
            "base end_date must match a technical price bar"
        )

    causal_bars = [
        bar
        for bar in bars
        if bar.date <= end_date
    ]

    if not causal_bars:
        return _unavailable()

    previous_date = None

    for bar in causal_bars:
        if (
            previous_date is not None
            and bar.date <= previous_date
        ):
            raise ValueError(
                "technical price bars must be strictly "
                "increasing by date"
            )

        if bar.adjustment_status != "OK":
            raise ValueError(
                "VCP base features require adjustment_status=OK"
            )

        previous_date = bar.date

    base_indexes = [
        index
        for index, bar in enumerate(causal_bars)
        if start_date <= bar.date <= end_date
    ]

    if not base_indexes:
        return _unavailable()

    base_bars = [
        causal_bars[index]
        for index in base_indexes
    ]

    anchor_high = (
        geometry.contractions[0]
        .high
        .price
    )

    if anchor_high <= 0:
        raise ValueError(
            "base anchor high must be positive"
        )

    deepest_low = min(
        bar.low
        for bar in base_bars
    )

    if deepest_low <= 0:
        raise ValueError(
            "base low must be positive"
        )

    if deepest_low > anchor_high:
        raise ValueError(
            "base low cannot exceed base anchor high"
        )

    base_depth_pct = (
        (anchor_high - deepest_low)
        / anchor_high
        * 100.0
    )

    atr_values = atr_percent_series(
        [bar.high for bar in causal_bars],
        [bar.low for bar in causal_bars],
        [bar.close for bar in causal_bars],
        period=atr_period,
    )

    base_atr_values = [
        atr_values[index]
        for index in base_indexes
    ]

    base_volume_values = [
        float(bar.volume)
        for bar in base_bars
    ]

    return VCPBaseFeatures(
        base_start_date=start_date,
        base_end_date=end_date,
        base_duration_sessions=len(base_bars),
        base_depth_pct=base_depth_pct,
        base_atr_compression_ratio=_half_ratio(
            base_atr_values
        ),
        base_volume_dryup_ratio=_half_ratio(
            base_volume_values
        ),
    )
