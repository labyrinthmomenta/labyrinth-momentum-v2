from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import math
from statistics import fmean, median
from typing import Sequence

from src.calculation.engine import PriceBar


SMA_SLOPE_LAG = 20


@dataclass(frozen=True)
class StrategyFeatures:
    """Descriptive features used by the strategy layer.

    These fields do not themselves represent trade signals.

    Trend fields describe price structure.
    Volume fields describe participation/liquidity.
    ATR remains in IndicatorSnapshot and is intentionally
    not duplicated here.
    """

    as_of: date
    observations: int

    close: float

    sma50: float | None
    sma150: float | None
    sma200: float | None

    distance_to_sma50_pct: float | None
    distance_to_sma200_pct: float | None

    sma50_slope_20: float | None
    sma200_slope_20: float | None

    median_volume_20: float | None
    median_turnover_20: float | None

    rvol20: float | None
    volume_dryup_5_20: float | None
    down_volume_share_20: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def _finite(value: float | None) -> bool:
    return (
        value is not None
        and math.isfinite(float(value))
    )


def _validate_and_order(
    bars: Sequence[PriceBar],
    *,
    as_of: date | None,
) -> list[PriceBar]:
    if not bars:
        raise ValueError(
            "At least one price bar is required"
        )

    ordered = sorted(
        bars,
        key=lambda bar: bar.date,
    )

    if as_of is None:
        as_of = ordered[-1].date

    eligible = [
        bar
        for bar in ordered
        if bar.date <= as_of
    ]

    if not eligible:
        raise ValueError(
            "No price bars exist on or before as_of"
        )

    previous_date: date | None = None

    for bar in eligible:
        if (
            previous_date is not None
            and bar.date <= previous_date
        ):
            raise ValueError(
                "Price bars must have unique, "
                "strictly increasing dates"
            )

        previous_date = bar.date

        if not _finite(bar.close):
            raise ValueError(
                f"Invalid close on {bar.date}"
            )

        if float(bar.close) <= 0:
            raise ValueError(
                f"Non-positive close on {bar.date}"
            )

    return eligible


def _sma(
    closes: Sequence[float],
    window: int,
) -> float | None:
    if len(closes) < window:
        return None

    return fmean(closes[-window:])


def _distance_pct(
    value: float,
    reference: float | None,
) -> float | None:
    if (
        reference is None
        or reference == 0
    ):
        return None

    return (
        value / reference - 1.0
    ) * 100.0


def _sma_slope_pct(
    closes: Sequence[float],
    *,
    window: int,
    lag: int = SMA_SLOPE_LAG,
) -> float | None:
    """Percentage change in an SMA over a fixed session lag."""

    if len(closes) < window + lag:
        return None

    current = fmean(
        closes[-window:]
    )

    previous_end = len(closes) - lag

    previous = fmean(
        closes[
            previous_end - window:
            previous_end
        ]
    )

    if previous == 0:
        return None

    return (
        current / previous - 1.0
    ) * 100.0


def _volume_values(
    bars: Sequence[PriceBar],
) -> list[float] | None:
    values: list[float] = []

    for bar in bars:
        volume = bar.volume

        if not _finite(volume):
            return None

        number = float(volume)

        if number < 0:
            return None

        values.append(number)

    return values


def _median_volume_20(
    bars: Sequence[PriceBar],
) -> float | None:
    if len(bars) < 20:
        return None

    values = _volume_values(
        bars[-20:]
    )

    if values is None:
        return None

    return float(median(values))


def _median_turnover_20(
    bars: Sequence[PriceBar],
) -> float | None:
    if len(bars) < 20:
        return None

    sample = bars[-20:]
    volumes = _volume_values(sample)

    if volumes is None:
        return None

    turnovers = [
        float(bar.close) * volume
        for bar, volume
        in zip(sample, volumes)
    ]

    return float(median(turnovers))


def _rvol20(
    bars: Sequence[PriceBar],
) -> float | None:
    """Today's volume divided by previous 20-session median."""

    if len(bars) < 21:
        return None

    current_volume = bars[-1].volume

    if (
        not _finite(current_volume)
        or float(current_volume) < 0
    ):
        return None

    baseline = _volume_values(
        bars[-21:-1]
    )

    if baseline is None:
        return None

    baseline_median = float(
        median(baseline)
    )

    if baseline_median <= 0:
        return None

    return (
        float(current_volume)
        / baseline_median
    )


def _volume_dryup_5_20(
    bars: Sequence[PriceBar],
) -> float | None:
    """Recent 5-session median volume / preceding 20-session median.

    The two samples do not overlap.
    """

    if len(bars) < 25:
        return None

    recent = _volume_values(
        bars[-5:]
    )

    baseline = _volume_values(
        bars[-25:-5]
    )

    if (
        recent is None
        or baseline is None
    ):
        return None

    baseline_median = float(
        median(baseline)
    )

    if baseline_median <= 0:
        return None

    return (
        float(median(recent))
        / baseline_median
    )


def _down_volume_share_20(
    bars: Sequence[PriceBar],
) -> float | None:
    """Share of 20-session volume occurring on negative close days."""

    if len(bars) < 21:
        return None

    sample = bars[-21:]

    current_bars = sample[1:]

    volumes = _volume_values(
        current_bars
    )

    if volumes is None:
        return None

    total_volume = sum(volumes)

    if total_volume <= 0:
        return None

    down_volume = 0.0

    for previous, current, volume in zip(
        sample,
        current_bars,
        volumes,
    ):
        if current.close < previous.close:
            down_volume += volume

    return down_volume / total_volume


def compute_strategy_features(
    bars: Sequence[PriceBar],
    *,
    as_of: date | None = None,
) -> StrategyFeatures:
    """Compute price-structure and volume context.

    Individual features return None when their required
    lookback or volume observations are unavailable.
    Missing history is never silently shortened.
    """

    eligible = _validate_and_order(
        bars,
        as_of=as_of,
    )

    actual_as_of = (
        as_of
        if as_of is not None
        else eligible[-1].date
    )

    closes = [
        float(bar.close)
        for bar in eligible
    ]

    close = closes[-1]

    sma50 = _sma(
        closes,
        50,
    )

    sma150 = _sma(
        closes,
        150,
    )

    sma200 = _sma(
        closes,
        200,
    )

    return StrategyFeatures(
        as_of=actual_as_of,
        observations=len(eligible),

        close=close,

        sma50=sma50,
        sma150=sma150,
        sma200=sma200,

        distance_to_sma50_pct=_distance_pct(
            close,
            sma50,
        ),

        distance_to_sma200_pct=_distance_pct(
            close,
            sma200,
        ),

        sma50_slope_20=_sma_slope_pct(
            closes,
            window=50,
        ),

        sma200_slope_20=_sma_slope_pct(
            closes,
            window=200,
        ),

        median_volume_20=_median_volume_20(
            eligible
        ),

        median_turnover_20=_median_turnover_20(
            eligible
        ),

        rvol20=_rvol20(
            eligible
        ),

        volume_dryup_5_20=_volume_dryup_5_20(
            eligible
        ),

        down_volume_share_20=_down_volume_share_20(
            eligible
        ),
    )
