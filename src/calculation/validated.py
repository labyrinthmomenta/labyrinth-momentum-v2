from __future__ import annotations

from datetime import date
from typing import Sequence

from src.calculation.engine import IndicatorSnapshot, PriceBar, compute_snapshot
from src.data.calendar import BISTTradingCalendar
from src.validation.data_quality import QualityReport, require_valid_price_history


def compute_validated_snapshot(
    bars: Sequence[PriceBar],
    calendar: BISTTradingCalendar,
    *,
    as_of: date,
    required_return_window: int = 252,
    listing_start: date | None = None,
) -> tuple[IndicatorSnapshot, QualityReport]:
    """Production-safe calculation entry point.

    The canonical BIST calendar is checked before indicators are calculated, so
    a missing trading session cannot be replaced by an older observation.
    """
    report = require_valid_price_history(
        bars,
        calendar,
        as_of=as_of,
        required_return_window=required_return_window,
        listing_start=listing_start,
    )
    snapshot = compute_snapshot(bars, as_of=report.expected_latest_trading_day)
    return snapshot, report
