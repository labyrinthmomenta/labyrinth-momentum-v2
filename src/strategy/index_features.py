from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
import math
from typing import Sequence

from src.calculation.engine import PriceBar, derive_returns
from src.data.calendar import BISTTradingCalendar
from src.indicators.momentum import momentum
from src.strategy.features import compute_strategy_features


@dataclass(frozen=True)
class IndexFeatures:
    """Descriptive market-index features.

    Only the most recent uninterrupted official BIST
    trading-session tail is used for rolling features.

    Missing official sessions are never forward-filled,
    synthesized, or silently skipped.
    """

    as_of: date

    total_observations: int
    contiguous_observations: int

    contiguous_start: date | None
    last_gap_date: date | None

    close: float | None

    momentum_21: float | None
    momentum_63: float | None
    momentum_126: float | None
    momentum_252: float | None

    sma50: float | None
    sma150: float | None
    sma200: float | None

    distance_to_sma50_pct: float | None
    distance_to_sma200_pct: float | None

    sma50_slope_20: float | None
    sma200_slope_20: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def contiguous_trading_tail(
    bars: Sequence[PriceBar],
    calendar: BISTTradingCalendar,
    *,
    as_of: date,
) -> tuple[list[PriceBar], date | None]:
    """Return the latest uninterrupted official-session tail.

    The returned gap date is the nearest missing official
    BIST trading session immediately before the contiguous
    tail, when such a gap exists inside supplied history.
    """

    eligible = sorted(
        (
            bar
            for bar in bars
            if bar.date <= as_of
        ),
        key=lambda bar: bar.date,
    )

    if not eligible:
        return [], None

    dates = [
        bar.date
        for bar in eligible
    ]

    if len(dates) != len(set(dates)):
        raise ValueError(
            "Duplicate index dates are not allowed"
        )

    by_date = {
        bar.date: bar
        for bar in eligible
    }

    for bar in eligible:
        if not calendar.is_trading_day(bar.date):
            raise ValueError(
                "Index history contains an official "
                f"closed-session bar: {bar.date}"
            )

        if (
            not math.isfinite(float(bar.close))
            or float(bar.close) <= 0
        ):
            raise ValueError(
                f"Invalid index close on {bar.date}"
            )

    first_date = eligible[0].date

    official_sessions: list[date] = []

    day = first_date

    while day <= as_of:
        if calendar.is_trading_day(day):
            official_sessions.append(day)

        day += timedelta(days=1)

    tail: list[PriceBar] = []
    last_gap: date | None = None

    for day in reversed(official_sessions):

        bar = by_date.get(day)

        if bar is None:
            last_gap = day
            break

        tail.append(bar)

    tail.reverse()

    return tail, last_gap


def compute_index_features(
    bars: Sequence[PriceBar],
    calendar: BISTTradingCalendar,
    *,
    as_of: date,
) -> IndexFeatures:
    """Compute market-index context from contiguous history."""

    eligible = [
        bar
        for bar in bars
        if bar.date <= as_of
    ]

    tail, last_gap = contiguous_trading_tail(
        eligible,
        calendar,
        as_of=as_of,
    )

    if not tail:
        return IndexFeatures(
            as_of=as_of,
            total_observations=len(eligible),
            contiguous_observations=0,
            contiguous_start=None,
            last_gap_date=last_gap,
            close=None,
            momentum_21=None,
            momentum_63=None,
            momentum_126=None,
            momentum_252=None,
            sma50=None,
            sma150=None,
            sma200=None,
            distance_to_sma50_pct=None,
            distance_to_sma200_pct=None,
            sma50_slope_20=None,
            sma200_slope_20=None,
        )

    returns = [
        point.value
        for point in derive_returns(tail)
    ]

    trend = compute_strategy_features(
        tail,
        as_of=as_of,
    )

    return IndexFeatures(
        as_of=as_of,

        total_observations=len(eligible),
        contiguous_observations=len(tail),

        contiguous_start=tail[0].date,
        last_gap_date=last_gap,

        close=float(tail[-1].close),

        momentum_21=momentum(
            returns,
            21,
        ),

        momentum_63=momentum(
            returns,
            63,
        ),

        momentum_126=momentum(
            returns,
            126,
        ),

        momentum_252=momentum(
            returns,
            252,
        ),

        sma50=trend.sma50,
        sma150=trend.sma150,
        sma200=trend.sma200,

        distance_to_sma50_pct=(
            trend.distance_to_sma50_pct
        ),

        distance_to_sma200_pct=(
            trend.distance_to_sma200_pct
        ),

        sma50_slope_20=(
            trend.sma50_slope_20
        ),

        sma200_slope_20=(
            trend.sma200_slope_20
        ),
    )
