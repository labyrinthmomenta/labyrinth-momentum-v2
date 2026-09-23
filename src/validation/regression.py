from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import math
from pathlib import Path

from src.indicators.fip import sign
from src.indicators.momentum import cumulative_return


@dataclass(frozen=True)
class LegacyReconstruction:
    ticker: str
    as_of: date
    window_start: str
    window_end: str
    observations: int
    negative_days: int
    positive_days: int
    flat_days: int
    momentum: float
    fip: float
    expected_momentum: float | None
    expected_fip: float | None
    momentum_match: bool
    fip_match: bool


def compare_number(actual: float | None, expected: float | None, tolerance: float = 1e-6) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance)


def _previous_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    absolute = year * 12 + (month - 1) + delta
    return absolute // 12, absolute % 12 + 1


def reconstruct_v1_12_1_from_detail(path: str | Path, *, as_of: date | None = None) -> LegacyReconstruction:
    """Reconstruct V1's 12-1 Momentum/FIP from a detail JSON fixture.

    This is a legacy regression check, not the V2 fixed-252-day methodology.
    The detail JSON must contain daily returns for the complete 12 calendar
    months ending with the month before `as_of`.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    monthly = payload.get("monthly") or []
    day_rows = [day for month in monthly for day in (month.get("days") or [])]
    if not day_rows:
        raise ValueError("Legacy detail JSON does not contain daily return rows")

    if as_of is None:
        as_of = max(date.fromisoformat(day["date"]) for day in day_rows)

    end_year, end_month = _previous_month(as_of.year, as_of.month)
    start_year, start_month = _shift_month(end_year, end_month, -11)
    start_key = f"{start_year:04d}-{start_month:02d}"
    end_key = f"{end_year:04d}-{end_month:02d}"

    values: list[float] = []
    for month in monthly:
        key = month.get("month")
        if start_key <= key <= end_key:
            values.extend(float(day["ret"]) for day in (month.get("days") or []))

    if not values:
        raise ValueError("No legacy daily returns found inside the 12-1 window")

    momentum_value = cumulative_return(values)
    if momentum_value is None:
        raise ValueError("Legacy momentum could not be reconstructed")
    neg = sum(value < 0 for value in values)
    pos = sum(value > 0 for value in values)
    flat = sum(value == 0 for value in values)
    fip_value = sign(momentum_value) * (neg - pos) / len(values)

    expected_momentum = payload.get("mom")
    expected_fip = payload.get("fip")
    return LegacyReconstruction(
        ticker=payload.get("ticker", ""),
        as_of=as_of,
        window_start=start_key,
        window_end=end_key,
        observations=len(values),
        negative_days=neg,
        positive_days=pos,
        flat_days=flat,
        momentum=momentum_value,
        fip=fip_value,
        expected_momentum=expected_momentum,
        expected_fip=expected_fip,
        momentum_match=compare_number(momentum_value, expected_momentum),
        fip_match=compare_number(fip_value, expected_fip),
    )
