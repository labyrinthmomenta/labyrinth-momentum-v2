"""Research date selection helpers.

This module chooses observation dates for historical research.

It is deliberately separate from the replay engine:
- calendar/date selection happens here,
- causal VCP replay happens in vcp_replay.py.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.data.calendar import BISTTradingCalendar


def _next_month(value: date) -> date:
    """Return the first day of the month after ``value``."""

    if value.month == 12:
        return date(
            value.year + 1,
            1,
            1,
        )

    return date(
        value.year,
        value.month + 1,
        1,
    )


def month_end_trading_dates(
    calendar: BISTTradingCalendar,
    *,
    start_month: date,
    end_month: date,
) -> tuple[date, ...]:
    """Return the final official BIST trading session of each month.

    ``start_month`` and ``end_month`` are inclusive month markers and
    must both be the first calendar day of their respective months.

    FULL and HALF sessions are both valid trading days because the
    authoritative BIST calendar determines ``is_trading_day``.

    Closed weekends and official holidays are never silently used as
    replay dates.
    """

    if (
        start_month.day != 1
        or end_month.day != 1
    ):
        raise ValueError(
            "start_month and end_month must be the first day of a month"
        )

    if start_month > end_month:
        raise ValueError(
            "start_month must not be after end_month"
        )

    result: list[date] = []

    current = start_month

    while current <= end_month:
        following_month = _next_month(
            current
        )

        month_end = (
            following_month
            - timedelta(days=1)
        )

        trading_days = calendar.trading_days(
            current,
            month_end,
        )

        if not trading_days:
            raise ValueError(
                "no official BIST trading session found for "
                f"{current.year:04d}-{current.month:02d}"
            )

        result.append(
            trading_days[-1]
        )

        current = following_month

    return tuple(result)
