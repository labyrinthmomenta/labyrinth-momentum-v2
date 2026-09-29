from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import math
from statistics import median
from typing import Sequence

from src.strategy.technical_prices import TechnicalPriceBar
from src.strategy.vcp_geometry import VCPGeometry


@dataclass(frozen=True)
class VCPBreakoutEvent:
    """Descriptive event measurements around a confirmed VCP pivot.

    This object records what happened relative to the pivot.

    It does not:
    - decide whether the breakout is attractive,
    - classify volume as sufficient/insufficient,
    - generate an entry or exit signal,
    - provide a composite score.
    """

    has_confirmed_pivot: bool
    pivot_price: float | None

    # The VCP structure is causally available only when the LOW
    # belonging to the final confirmed contraction has itself been
    # confirmed.
    structure_ready_date: date | None

    # First eligible session whose intraday HIGH exceeded pivot.
    first_intraday_breach_date: date | None

    # First eligible session whose CLOSE exceeded pivot.
    first_close_break_date: date | None

    # Historical event flag: once a close-confirmed break has
    # occurred, this remains True even if price later falls below.
    pivot_broken_by_close: bool

    # Measured on the first close-confirmed breakout session.
    breakout_close_pct_above_pivot: float | None

    # Breakout-session volume / median volume of the preceding
    # 20 sessions. The breakout session itself is excluded.
    breakout_volume_ratio_20: float | None

    # Current state is deliberately separate from historical event.
    current_close_above_pivot: bool | None

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


def _structure_ready_date(
    geometry: VCPGeometry,
) -> date | None:
    if not geometry.contractions:
        return None

    final_contraction = (
        geometry.contractions[-1]
    )

    return (
        final_contraction.low.confirmation_date
    )


def _volume_ratio_20(
    bars: Sequence[TechnicalPriceBar],
    breakout_index: int,
) -> float | None:
    """Breakout volume / previous 20-session median volume."""

    if breakout_index < 20:
        return None

    baseline = bars[
        breakout_index - 20:
        breakout_index
    ]

    baseline_volumes = [
        float(bar.volume)
        for bar in baseline
    ]

    baseline_median = float(
        median(baseline_volumes)
    )

    if baseline_median <= 0:
        return None

    breakout_volume = float(
        bars[breakout_index].volume
    )

    return (
        breakout_volume
        / baseline_median
    )


def detect_vcp_breakout(
    bars: Sequence[TechnicalPriceBar],
    geometry: VCPGeometry,
) -> VCPBreakoutEvent:
    """Describe pivot-breach events after VCP structure confirmation.

    Causality rule
    --------------
    The breakout search begins strictly AFTER the confirmation date
    of the LOW belonging to the final confirmed HIGH -> LOW
    contraction.

    Therefore neither:
    - price action before LOW confirmation, nor
    - price action on the LOW confirmation session itself

    can be recorded as a breakout event.

    Intraday breach and close-confirmed break remain separate events.
    """

    ordered = _validate_bars(
        bars
    )

    pivot = geometry.pivot

    if pivot is None:
        return VCPBreakoutEvent(
            has_confirmed_pivot=False,
            pivot_price=None,
            structure_ready_date=None,

            first_intraday_breach_date=None,
            first_close_break_date=None,

            pivot_broken_by_close=False,

            breakout_close_pct_above_pivot=None,
            breakout_volume_ratio_20=None,

            current_close_above_pivot=None,
        )

    pivot_price = float(
        pivot.price
    )

    if (
        not _finite(pivot_price)
        or pivot_price <= 0
    ):
        raise ValueError(
            "Confirmed pivot price must be finite and positive"
        )

    ready_date = _structure_ready_date(
        geometry
    )

    if ready_date is None:
        raise ValueError(
            "Confirmed VCP pivot requires a structure ready date"
        )

    first_intraday_breach_date: date | None = None
    first_close_break_date: date | None = None

    breakout_close_pct_above_pivot: float | None = None
    breakout_volume_ratio_20: float | None = None

    for index, bar in enumerate(ordered):
        # Strictly later than LOW confirmation date.
        if bar.date <= ready_date:
            continue

        if (
            first_intraday_breach_date is None
            and float(bar.high) > pivot_price
        ):
            first_intraday_breach_date = (
                bar.date
            )

        if (
            first_close_break_date is None
            and float(bar.close) > pivot_price
        ):
            first_close_break_date = (
                bar.date
            )

            breakout_close_pct_above_pivot = (
                (
                    float(bar.close)
                    / pivot_price
                )
                - 1.0
            ) * 100.0

            breakout_volume_ratio_20 = (
                _volume_ratio_20(
                    ordered,
                    index,
                )
            )

    pivot_broken_by_close = (
        first_close_break_date is not None
    )

    current_close_above_pivot = (
        float(ordered[-1].close)
        > pivot_price
    )

    return VCPBreakoutEvent(
        has_confirmed_pivot=True,
        pivot_price=pivot_price,
        structure_ready_date=ready_date,

        first_intraday_breach_date=(
            first_intraday_breach_date
        ),

        first_close_break_date=(
            first_close_break_date
        ),

        pivot_broken_by_close=(
            pivot_broken_by_close
        ),

        breakout_close_pct_above_pivot=(
            breakout_close_pct_above_pivot
        ),

        breakout_volume_ratio_20=(
            breakout_volume_ratio_20
        ),

        current_close_above_pivot=(
            current_close_above_pivot
        ),
    )
