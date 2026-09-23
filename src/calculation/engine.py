from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import math
from typing import Iterable, Sequence

from src.indicators.acceleration import delta
from src.indicators.atr import atr_percent
from src.indicators.fip import fip
from src.indicators.momentum import momentum

DEFAULT_WINDOWS = (252, 126, 63, 21)


@dataclass(frozen=True)
class PriceBar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(frozen=True)
class ReturnPoint:
    date: date
    value: float


@dataclass(frozen=True)
class IndicatorSnapshot:
    as_of: date
    observations: int
    momentum_252: float | None
    momentum_126: float | None
    momentum_63: float | None
    momentum_21: float | None
    fip_252: float | None
    fip_126: float | None
    fip_63: float | None
    fip_21: float | None
    atr14_percent: float | None
    delta_momentum_21_63: float | None
    delta_fip_21_63: float | None
    completed_month: str
    completed_month_momentum: float | None
    completed_month_fip: float | None
    completed_month_observations: int

    def as_dict(self) -> dict:
        return asdict(self)


class DataQualityError(ValueError):
    """Raised when an OHLC series cannot be safely used for calculations."""


def _finite(value: float | None) -> bool:
    return value is not None and math.isfinite(float(value))


def _validate_bars(bars: Sequence[PriceBar]) -> None:
    previous_date: date | None = None
    for bar in bars:
        if previous_date is not None and bar.date <= previous_date:
            raise DataQualityError("Price bars must have unique, strictly increasing dates")
        previous_date = bar.date
        for field_name in ("open", "high", "low", "close"):
            value = getattr(bar, field_name)
            if not _finite(value):
                raise DataQualityError(f"{field_name} is missing or non-finite on {bar.date}")
            if value < 0:
                raise DataQualityError(f"{field_name} is negative on {bar.date}")
        if bar.high < bar.low:
            raise DataQualityError(f"high < low on {bar.date}")
        if bar.close == 0:
            raise DataQualityError(f"close is zero on {bar.date}")


def derive_returns(bars: Sequence[PriceBar]) -> list[ReturnPoint]:
    """Derive close-to-close daily returns, aligned to the later close date."""
    bars = list(bars)
    _validate_bars(bars)
    points: list[ReturnPoint] = []
    for previous, current in zip(bars, bars[1:]):
        points.append(ReturnPoint(current.date, current.close / previous.close - 1.0))
    return points


def last_completed_month(as_of: date) -> tuple[int, int]:
    """Return (year, month) for the calendar month immediately before as_of."""
    if as_of.month == 1:
        return as_of.year - 1, 12
    return as_of.year, as_of.month - 1


def _month_values(points: Sequence[ReturnPoint], year: int, month: int) -> list[float]:
    return [point.value for point in points if point.date.year == year and point.date.month == month]


def _indicator_map(values: Sequence[float], windows: Iterable[int]) -> tuple[dict[int, float | None], dict[int, float | None]]:
    moms = {window: momentum(values, window) for window in windows}
    fips = {window: fip(values, window) for window in windows}
    return moms, fips


def compute_snapshot(
    bars: Sequence[PriceBar],
    *,
    as_of: date | None = None,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    atr_period: int = 14,
) -> IndicatorSnapshot:
    """Compute one V2 indicator snapshot from canonical OHLC bars.

    Windows are observation based: 252/126/63/21 daily returns. Production use
    should first validate the OHLC dates against the canonical BIST trading-day
    calendar so missing sessions cannot be silently compressed.
    """
    if not bars:
        raise DataQualityError("At least one price bar is required")
    if tuple(windows) != DEFAULT_WINDOWS:
        missing = set(DEFAULT_WINDOWS) - set(windows)
        if missing:
            raise ValueError(f"Required V2 windows missing: {sorted(missing)}")

    ordered = sorted(bars, key=lambda bar: bar.date)
    if as_of is None:
        as_of = ordered[-1].date
    eligible = [bar for bar in ordered if bar.date <= as_of]
    if not eligible:
        raise DataQualityError("No price bars exist on or before as_of")
    _validate_bars(eligible)

    returns = derive_returns(eligible)
    values = [point.value for point in returns]
    moms, fips = _indicator_map(values, windows)

    highs = [bar.high for bar in eligible]
    lows = [bar.low for bar in eligible]
    closes = [bar.close for bar in eligible]
    atr_pct = atr_percent(highs, lows, closes, period=atr_period)

    month_year, month_number = last_completed_month(as_of)
    month_values = _month_values(returns, month_year, month_number)
    month_momentum = momentum(month_values, len(month_values)) if month_values else None
    month_fip = fip(month_values, len(month_values)) if month_values else None

    return IndicatorSnapshot(
        as_of=as_of,
        observations=len(values),
        momentum_252=moms[252],
        momentum_126=moms[126],
        momentum_63=moms[63],
        momentum_21=moms[21],
        fip_252=fips[252],
        fip_126=fips[126],
        fip_63=fips[63],
        fip_21=fips[21],
        atr14_percent=atr_pct,
        delta_momentum_21_63=delta(moms[21], moms[63]),
        delta_fip_21_63=delta(fips[21], fips[63]),
        completed_month=f"{month_year:04d}-{month_number:02d}",
        completed_month_momentum=month_momentum,
        completed_month_fip=month_fip,
        completed_month_observations=len(month_values),
    )
