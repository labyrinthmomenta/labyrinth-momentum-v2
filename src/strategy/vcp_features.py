from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import math
from statistics import median
from typing import Sequence

from src.strategy.technical_prices import TechnicalPriceBar
from src.strategy.vcp_geometry import VCPGeometry


@dataclass(frozen=True)
class VCPFeatures:
    """Descriptive measurements around a VCP structure.

    These fields are measurements only. They do not represent
    a setup score, breakout signal, entry signal, or recommendation.
    """

    as_of: date
    observations: int

    # Recent price tightness.
    range_5_pct: float | None
    range_10_pct: float | None

    # Median normalized True Range of the latest 10 sessions
    # divided by the preceding non-overlapping 40 sessions.
    true_range_compression_10_40: float | None

    # Median volume inside the final confirmed contraction
    # divided by the median volume of the 50 sessions immediately
    # preceding that contraction.
    final_contraction_volume_ratio_50: float | None

    # Current close relative to the confirmed VCP pivot.
    distance_to_pivot_pct: float | None
    distance_to_pivot_atr: float | None

    # Current unconfirmed swing context.
    has_provisional_swing: bool
    provisional_kind: str | None
    provisional_distance_to_pivot_pct: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def _finite(value: float) -> bool:
    return math.isfinite(float(value))


def _validate_bars(
    bars: Sequence[TechnicalPriceBar],
) -> tuple[TechnicalPriceBar, ...]:
    if not bars:
        raise ValueError(
            "At least one technical price bar is required"
        )

    ordered = tuple(bars)

    previous_date: date | None = None

    for bar in ordered:
        if (
            previous_date is not None
            and bar.date <= previous_date
        ):
            raise ValueError(
                "Technical price bars must be strictly "
                "increasing by date"
            )

        previous_date = bar.date

        if bar.adjustment_status != "OK":
            raise ValueError(
                "Technical price series contains "
                f"{bar.adjustment_status} on {bar.date}"
            )

        for name, value in (
            ("open", bar.open),
            ("high", bar.high),
            ("low", bar.low),
            ("close", bar.close),
            ("volume", bar.volume),
        ):
            if not _finite(value):
                raise ValueError(
                    f"Invalid {name} on {bar.date}"
                )

        if (
            bar.open <= 0
            or bar.high <= 0
            or bar.low <= 0
            or bar.close <= 0
        ):
            raise ValueError(
                f"Non-positive OHLC on {bar.date}"
            )

        if bar.high < bar.low:
            raise ValueError(
                f"High below low on {bar.date}"
            )

        if not (
            bar.low <= bar.open <= bar.high
        ):
            raise ValueError(
                f"Open outside high/low on {bar.date}"
            )

        if not (
            bar.low <= bar.close <= bar.high
        ):
            raise ValueError(
                f"Close outside high/low on {bar.date}"
            )

        if bar.volume < 0:
            raise ValueError(
                f"Negative volume on {bar.date}"
            )

    return ordered


def _range_pct(
    bars: Sequence[TechnicalPriceBar],
    window: int,
) -> float | None:
    if len(bars) < window:
        return None

    sample = bars[-window:]

    highest = max(
        float(bar.high)
        for bar in sample
    )

    lowest = min(
        float(bar.low)
        for bar in sample
    )

    if highest <= 0:
        return None

    return (
        (highest - lowest)
        / highest
        * 100.0
    )


def _normalized_true_ranges(
    bars: Sequence[TechnicalPriceBar],
) -> list[float]:
    """Return True Range as a percentage of previous close.

    The first price bar does not produce a True Range observation
    because no previous close exists.
    """

    values: list[float] = []

    for previous, current in zip(
        bars,
        bars[1:],
    ):
        previous_close = float(
            previous.close
        )

        true_range = max(
            float(current.high)
            - float(current.low),
            abs(
                float(current.high)
                - previous_close
            ),
            abs(
                float(current.low)
                - previous_close
            ),
        )

        values.append(
            true_range
            / previous_close
            * 100.0
        )

    return values


def _true_range_compression_10_40(
    bars: Sequence[TechnicalPriceBar],
) -> float | None:
    # 50 True Range observations require 51 price bars.
    if len(bars) < 51:
        return None

    true_ranges = _normalized_true_ranges(
        bars
    )

    # Latest 50 TR observations only:
    # 40-session baseline + 10-session recent sample.
    sample = true_ranges[-50:]

    baseline = sample[:40]
    recent = sample[40:]

    baseline_median = float(
        median(baseline)
    )

    if baseline_median <= 0:
        return None

    recent_median = float(
        median(recent)
    )

    return (
        recent_median
        / baseline_median
    )


def _final_contraction_volume_ratio_50(
    bars: Sequence[TechnicalPriceBar],
    geometry: VCPGeometry,
) -> float | None:
    if not geometry.contractions:
        return None

    contraction = (
        geometry.contractions[-1]
    )

    high_date = (
        contraction.high.extreme_date
    )

    low_date = (
        contraction.low.extreme_date
    )

    date_to_index = {
        bar.date: index
        for index, bar in enumerate(bars)
    }

    start_index = date_to_index.get(
        high_date
    )

    end_index = date_to_index.get(
        low_date
    )

    # Geometry may have been computed from a wider series.
    # Missing dates therefore mean this individual feature cannot
    # be measured from the supplied bars.
    if (
        start_index is None
        or end_index is None
        or end_index < start_index
    ):
        return None

    # Baseline is deliberately non-overlapping:
    # exactly 50 sessions immediately before the contraction HIGH.
    if start_index < 50:
        return None

    baseline = bars[
        start_index - 50:
        start_index
    ]

    contraction_bars = bars[
        start_index:
        end_index + 1
    ]

    if not contraction_bars:
        return None

    baseline_median = float(
        median(
            float(bar.volume)
            for bar in baseline
        )
    )

    if baseline_median <= 0:
        return None

    contraction_median = float(
        median(
            float(bar.volume)
            for bar in contraction_bars
        )
    )

    return (
        contraction_median
        / baseline_median
    )


def _distance_pct(
    value: float,
    reference: float,
) -> float:
    if (
        not _finite(value)
        or not _finite(reference)
        or value <= 0
        or reference <= 0
    ):
        raise ValueError(
            "Distance values must be finite and positive"
        )

    return (
        value / reference - 1.0
    ) * 100.0


def _pivot_distances(
    *,
    close: float,
    geometry: VCPGeometry,
    atr_pct: float | None,
) -> tuple[
    float | None,
    float | None,
]:
    if geometry.pivot is None:
        return None, None

    distance_pct = _distance_pct(
        close,
        geometry.pivot.price,
    )

    if (
        atr_pct is None
        or not math.isfinite(
            float(atr_pct)
        )
        or float(atr_pct) <= 0
    ):
        return distance_pct, None

    return (
        distance_pct,
        distance_pct
        / float(atr_pct),
    )


def _provisional_context(
    geometry: VCPGeometry,
) -> tuple[
    bool,
    str | None,
    float | None,
]:
    provisional = geometry.provisional

    if provisional is None:
        return False, None, None

    distance: float | None = None

    if geometry.pivot is not None:
        distance = _distance_pct(
            provisional.price,
            geometry.pivot.price,
        )

    return (
        True,
        provisional.kind,
        distance,
    )


def compute_vcp_features(
    bars: Sequence[TechnicalPriceBar],
    geometry: VCPGeometry,
    *,
    atr_pct: float | None = None,
) -> VCPFeatures:
    """Compute descriptive VCP-specific features.

    This function intentionally does not:
    - compute a composite VCP score,
    - decide whether a VCP is valid or attractive,
    - detect a breakout,
    - generate an entry/exit signal.

    General strategy metrics such as RVOL20 and
    volume_dryup_5_20 remain in StrategyFeatures and are
    intentionally not duplicated here.
    """

    ordered = _validate_bars(
        bars
    )

    close = float(
        ordered[-1].close
    )

    (
        distance_to_pivot_pct,
        distance_to_pivot_atr,
    ) = _pivot_distances(
        close=close,
        geometry=geometry,
        atr_pct=atr_pct,
    )

    (
        has_provisional_swing,
        provisional_kind,
        provisional_distance_to_pivot_pct,
    ) = _provisional_context(
        geometry
    )

    return VCPFeatures(
        as_of=ordered[-1].date,
        observations=len(ordered),

        range_5_pct=_range_pct(
            ordered,
            5,
        ),

        range_10_pct=_range_pct(
            ordered,
            10,
        ),

        true_range_compression_10_40=(
            _true_range_compression_10_40(
                ordered
            )
        ),

        final_contraction_volume_ratio_50=(
            _final_contraction_volume_ratio_50(
                ordered,
                geometry,
            )
        ),

        distance_to_pivot_pct=(
            distance_to_pivot_pct
        ),

        distance_to_pivot_atr=(
            distance_to_pivot_atr
        ),

        has_provisional_swing=(
            has_provisional_swing
        ),

        provisional_kind=(
            provisional_kind
        ),

        provisional_distance_to_pivot_pct=(
            provisional_distance_to_pivot_pct
        ),
    )
