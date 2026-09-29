from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import math
from statistics import median
from typing import Sequence

from src.strategy.technical_prices import TechnicalPriceBar
from src.strategy.vcp_breakout import VCPBreakoutEvent


@dataclass(frozen=True)
class VCPFollowThrough:
    """Descriptive measurements after a close-confirmed breakout.

    The breakout session itself is excluded from the follow-through
    window.

    This object does not:
    - classify follow-through as good or bad,
    - apply a minimum number of sessions,
    - apply a volume threshold,
    - generate a score or trade signal.
    """

    has_close_breakout: bool
    breakout_date: date | None
    pivot_price: float | None

    post_breakout_sessions: int
    post_breakout_closes_above_pivot: int
    post_breakout_close_above_pivot_share: float | None

    max_post_breakout_close_pct_above_pivot: float | None
    min_post_breakout_close_pct_above_pivot: float | None
    latest_close_pct_above_pivot: float | None

    # Median volume of all sessions AFTER the breakout
    # divided by the median volume of the 20 sessions
    # immediately BEFORE the breakout.
    #
    # The breakout session itself is excluded from both samples.
    median_post_breakout_volume_ratio_20: float | None

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


def _validate_breakout_event(
    event: VCPBreakoutEvent,
) -> None:
    has_break_date = (
        event.first_close_break_date is not None
    )

    if (
        event.pivot_broken_by_close
        != has_break_date
    ):
        raise ValueError(
            "inconsistent breakout event: "
            "pivot_broken_by_close and "
            "first_close_break_date disagree"
        )

    if event.pivot_price is not None:
        if (
            not _finite(event.pivot_price)
            or event.pivot_price <= 0
        ):
            raise ValueError(
                "pivot price must be finite and positive"
            )

    if (
        event.pivot_broken_by_close
        and event.pivot_price is None
    ):
        raise ValueError(
            "inconsistent breakout event: "
            "close breakout requires pivot price"
        )


def _distance_pct(
    close: float,
    pivot_price: float,
) -> float:
    return (
        close / pivot_price - 1.0
    ) * 100.0


def _post_breakout_volume_ratio(
    bars: Sequence[TechnicalPriceBar],
    breakout_index: int,
) -> float | None:
    # Need exactly 20 earlier sessions.
    if breakout_index < 20:
        return None

    post_breakout = bars[
        breakout_index + 1:
    ]

    if not post_breakout:
        return None

    baseline = bars[
        breakout_index - 20:
        breakout_index
    ]

    baseline_median = float(
        median(
            float(bar.volume)
            for bar in baseline
        )
    )

    if baseline_median <= 0:
        return None

    post_median = float(
        median(
            float(bar.volume)
            for bar in post_breakout
        )
    )

    return (
        post_median
        / baseline_median
    )


def measure_vcp_follow_through(
    bars: Sequence[TechnicalPriceBar],
    breakout: VCPBreakoutEvent,
) -> VCPFollowThrough:
    """Measure post-breakout price and volume behavior.

    Causality rule
    --------------
    The close-confirmed breakout session is the event boundary.

    Only sessions strictly AFTER that date are treated as
    follow-through observations.
    """

    ordered = _validate_bars(
        bars
    )

    _validate_breakout_event(
        breakout
    )

    # A confirmed pivot may exist without a close breakout.
    if not breakout.pivot_broken_by_close:
        return VCPFollowThrough(
            has_close_breakout=False,
            breakout_date=None,
            pivot_price=breakout.pivot_price,

            post_breakout_sessions=0,
            post_breakout_closes_above_pivot=0,
            post_breakout_close_above_pivot_share=None,

            max_post_breakout_close_pct_above_pivot=None,
            min_post_breakout_close_pct_above_pivot=None,
            latest_close_pct_above_pivot=None,

            median_post_breakout_volume_ratio_20=None,
        )

    breakout_date = (
        breakout.first_close_break_date
    )

    pivot_price = breakout.pivot_price

    # Protected by _validate_breakout_event.
    assert breakout_date is not None
    assert pivot_price is not None

    date_to_index = {
        bar.date: index
        for index, bar in enumerate(ordered)
    }

    breakout_index = date_to_index.get(
        breakout_date
    )

    if breakout_index is None:
        raise ValueError(
            "breakout date does not exist "
            "in supplied price series"
        )

    post_breakout = ordered[
        breakout_index + 1:
    ]

    session_count = len(
        post_breakout
    )

    if session_count == 0:
        return VCPFollowThrough(
            has_close_breakout=True,
            breakout_date=breakout_date,
            pivot_price=pivot_price,

            post_breakout_sessions=0,
            post_breakout_closes_above_pivot=0,
            post_breakout_close_above_pivot_share=None,

            max_post_breakout_close_pct_above_pivot=None,
            min_post_breakout_close_pct_above_pivot=None,
            latest_close_pct_above_pivot=None,

            median_post_breakout_volume_ratio_20=None,
        )

    distances = [
        _distance_pct(
            float(bar.close),
            float(pivot_price),
        )
        for bar in post_breakout
    ]

    closes_above = sum(
        1
        for bar in post_breakout
        if float(bar.close) > float(pivot_price)
    )

    close_above_share = (
        closes_above
        / session_count
    )

    volume_ratio = (
        _post_breakout_volume_ratio(
            ordered,
            breakout_index,
        )
    )

    return VCPFollowThrough(
        has_close_breakout=True,
        breakout_date=breakout_date,
        pivot_price=pivot_price,

        post_breakout_sessions=session_count,

        post_breakout_closes_above_pivot=(
            closes_above
        ),

        post_breakout_close_above_pivot_share=(
            close_above_share
        ),

        max_post_breakout_close_pct_above_pivot=(
            max(distances)
        ),

        min_post_breakout_close_pct_above_pivot=(
            min(distances)
        ),

        latest_close_pct_above_pivot=(
            distances[-1]
        ),

        median_post_breakout_volume_ratio_20=(
            volume_ratio
        ),
    )
