from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from statistics import median
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class MarketBreadth:
    """Descriptive cross-sectional market breadth.

    Each metric uses its own available-data denominator.
    Missing observations are never interpreted as zero or
    as a negative signal.
    """

    total_equities: int

    momentum_21_coverage: int
    momentum_21_positive_pct: float | None

    momentum_63_coverage: int
    momentum_63_positive_pct: float | None
    momentum_63_median: float | None

    sma50_coverage: int
    above_sma50_pct: float | None

    sma200_coverage: int
    above_sma200_pct: float | None

    acceleration_21_63_coverage: int
    acceleration_21_63_positive_pct: float | None
    acceleration_21_63_median: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        result = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(result):
        return None

    return result


def _positive_pct(
    values: Sequence[float],
) -> float | None:
    if not values:
        return None

    positive = sum(
        1
        for value in values
        if value > 0
    )

    return (
        positive
        / len(values)
        * 100.0
    )


def compute_market_breadth(
    rows: Sequence[Mapping[str, Any]],
) -> MarketBreadth:
    """Calculate descriptive BIST equity breadth.

    Expected row fields:

    momentum_21
    momentum_63
    distance_to_sma50_pct
    distance_to_sma200_pct
    acceleration_21_63_all

    The caller determines the universe. Production usage
    should supply active equities with data_status=OK.
    """

    prepared = [
        dict(row)
        for row in rows
    ]

    m21 = [
        value
        for row in prepared
        if (
            value := _number(
                row.get("momentum_21")
            )
        ) is not None
    ]

    m63 = [
        value
        for row in prepared
        if (
            value := _number(
                row.get("momentum_63")
            )
        ) is not None
    ]

    sma50_distance = [
        value
        for row in prepared
        if (
            value := _number(
                row.get("distance_to_sma50_pct")
            )
        ) is not None
    ]

    sma200_distance = [
        value
        for row in prepared
        if (
            value := _number(
                row.get("distance_to_sma200_pct")
            )
        ) is not None
    ]

    acceleration = [
        value
        for row in prepared
        if (
            value := _number(
                row.get("acceleration_21_63_all")
            )
        ) is not None
    ]

    return MarketBreadth(
        total_equities=len(prepared),

        momentum_21_coverage=len(m21),
        momentum_21_positive_pct=_positive_pct(
            m21
        ),

        momentum_63_coverage=len(m63),
        momentum_63_positive_pct=_positive_pct(
            m63
        ),

        momentum_63_median=(
            None
            if not m63
            else float(median(m63))
        ),

        sma50_coverage=len(
            sma50_distance
        ),

        above_sma50_pct=_positive_pct(
            sma50_distance
        ),

        sma200_coverage=len(
            sma200_distance
        ),

        above_sma200_pct=_positive_pct(
            sma200_distance
        ),

        acceleration_21_63_coverage=len(
            acceleration
        ),

        acceleration_21_63_positive_pct=(
            _positive_pct(
                acceleration
            )
        ),

        acceleration_21_63_median=(
            None
            if not acceleration
            else float(
                median(acceleration)
            )
        ),
    )
