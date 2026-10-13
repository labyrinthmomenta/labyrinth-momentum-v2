from __future__ import annotations

from calendar import monthrange
import csv
from datetime import date
from pathlib import Path
from typing import Sequence

from src.calculation.engine import PriceBar, derive_returns
from src.data.calendar import BISTTradingCalendar


def _month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _shift_month(value: date, offset: int) -> tuple[int, int]:
    index = value.year * 12 + (value.month - 1) + offset
    return index // 12, index % 12 + 1


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def unavailable_web_screener_fields(as_of: date) -> dict:
    return {
        "current_month": _month_key(as_of),
        "current_month_positive": None,
        "current_month_negative": None,
        "current_month_flat": None,
        "current_month_sessions": None,
        "current_month_expected_sessions": None,
        "current_month_session_gap": None,
    }


def build_web_diagnostics(
    bars: Sequence[PriceBar],
    calendar: BISTTradingCalendar,
    *,
    as_of: date,
    listing_start: date | None = None,
    months: int = 13,
) -> dict:
    """Build presentation diagnostics from canonical price bars.

    These values are derived publication data only. They do not alter any
    momentum, FIP, ranking, VCP, or trading calculation.
    """
    if months <= 0:
        raise ValueError("months must be positive")

    ordered = sorted(
        (bar for bar in bars if bar.date <= as_of),
        key=lambda bar: bar.date,
    )

    returns = {
        point.date: point.value
        for point in derive_returns(ordered)
    }

    month_keys: list[tuple[int, int]] = [
        _shift_month(as_of, offset)
        for offset in range(-(months - 1), 1)
    ]

    monthly_history: list[dict] = []

    for year, month in month_keys:
        start = _month_start(year, month)
        end = min(_month_end(year, month), as_of)

        if listing_start is not None and end < listing_start:
            continue

        expected_start = start
        if listing_start is not None and listing_start > expected_start:
            expected_start = listing_start

        month_bars = [
            bar
            for bar in ordered
            if bar.date.year == year and bar.date.month == month
        ]

        month_returns = [
            returns[bar.date]
            for bar in month_bars
            if returns.get(bar.date) is not None
        ]

        positive = sum(value > 0 for value in month_returns)
        negative = sum(value < 0 for value in month_returns)
        flat = sum(value == 0 for value in month_returns)

        momentum = None
        fip = None

        if month_returns:
            growth = 1.0
            for value in month_returns:
                growth *= 1.0 + value

            momentum = growth - 1.0
            fip = (
                _sign(momentum)
                * (negative - positive)
                / len(month_returns)
            )

        expected_sessions = len(
            calendar.trading_days(expected_start, end)
        )
        observed_sessions = len(month_bars)

        monthly_history.append(
            {
                "month": f"{year:04d}-{month:02d}",
                "is_current": year == as_of.year and month == as_of.month,
                "momentum": momentum,
                "fip": fip,
                "positive": positive,
                "negative": negative,
                "flat": flat,
                "classified_returns": len(month_returns),
                "sessions": observed_sessions,
                "expected_sessions": expected_sessions,
                "session_gap": max(
                    expected_sessions - observed_sessions,
                    0,
                ),
            }
        )

    current_key = _month_key(as_of)

    current = next(
        (
            row
            for row in monthly_history
            if row["month"] == current_key
        ),
        None,
    )

    if current is None:
        screener = unavailable_web_screener_fields(as_of)
    else:
        screener = {
            "current_month": current["month"],
            "current_month_positive": current["positive"],
            "current_month_negative": current["negative"],
            "current_month_flat": current["flat"],
            "current_month_sessions": current["sessions"],
            "current_month_expected_sessions": current["expected_sessions"],
            "current_month_session_gap": current["session_gap"],
        }

    return {
        "screener": screener,
        "monthly_history": monthly_history,
    }


def write_screener_csv(path: Path, rows: Sequence[dict]) -> None:
    """Write the flat published screener payload as UTF-8 CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)

    fields: list[str] = []
    seen: set[str] = set()

    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
        )
        writer.writeheader()

        for row in rows:
            writer.writerow(
                {
                    key: (
                        ""
                        if value is None
                        else str(value).lower()
                        if isinstance(value, bool)
                        else value
                    )
                    for key, value in row.items()
                }
            )
