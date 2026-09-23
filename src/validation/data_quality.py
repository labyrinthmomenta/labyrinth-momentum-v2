from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import math
from typing import Sequence

from src.calculation.engine import PriceBar
from src.data.calendar import BISTTradingCalendar, CalendarCoverageError, SessionType


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: Severity
    message: str
    date: date | None = None


@dataclass(frozen=True)
class QualityReport:
    as_of: date
    expected_latest_trading_day: date | None
    issues: tuple[QualityIssue, ...]
    required_return_window: int

    @property
    def passed(self) -> bool:
        return not any(issue.severity == Severity.ERROR for issue in self.issues)

    @property
    def errors(self) -> tuple[QualityIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == Severity.ERROR)

    @property
    def warnings(self) -> tuple[QualityIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == Severity.WARNING)


class PriceDataQualityError(ValueError):
    """Raised when price data cannot safely feed the calculation engine."""


def _finite(value: float | None) -> bool:
    return value is not None and math.isfinite(float(value))


def validate_ohlcv_structure(bars: Sequence[PriceBar]) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    seen: set[date] = set()
    previous_date: date | None = None
    for bar in bars:
        if bar.date in seen:
            issues.append(QualityIssue("DUPLICATE_DATE", Severity.ERROR, "Duplicate price date", bar.date))
        seen.add(bar.date)
        if previous_date is not None and bar.date <= previous_date:
            issues.append(
                QualityIssue(
                    "NON_MONOTONIC_DATES",
                    Severity.ERROR,
                    "Price bars are not strictly increasing by date",
                    bar.date,
                )
            )
        previous_date = bar.date

        for field_name in ("open", "high", "low", "close"):
            value = getattr(bar, field_name)
            if not _finite(value):
                issues.append(
                    QualityIssue("NON_FINITE_OHLC", Severity.ERROR, f"{field_name} is missing/non-finite", bar.date)
                )
            elif float(value) <= 0:
                issues.append(
                    QualityIssue("NON_POSITIVE_OHLC", Severity.ERROR, f"{field_name} must be > 0", bar.date)
                )
        if _finite(bar.volume) and float(bar.volume) < 0:
            issues.append(QualityIssue("NEGATIVE_VOLUME", Severity.ERROR, "volume must be >= 0", bar.date))

        if all(_finite(getattr(bar, name)) for name in ("open", "high", "low", "close")):
            if bar.high < max(bar.open, bar.close, bar.low):
                issues.append(
                    QualityIssue("INVALID_HIGH", Severity.ERROR, "high is below another OHLC value", bar.date)
                )
            if bar.low > min(bar.open, bar.close, bar.high):
                issues.append(
                    QualityIssue("INVALID_LOW", Severity.ERROR, "low is above another OHLC value", bar.date)
                )
    return issues


def validate_price_history(
    bars: Sequence[PriceBar],
    calendar: BISTTradingCalendar,
    *,
    as_of: date,
    required_return_window: int = 252,
    listing_start: date | None = None,
) -> QualityReport:
    """Validate that a security has an uncompressed canonical BIST lookback.

    A return window of N requires N+1 consecutive BIST trading-day closes.
    Missing market sessions are errors, not silently compressed observations.
    """
    issues = validate_ohlcv_structure(bars)
    ordered = list(bars)
    expected_latest: date | None = None

    try:
        expected_latest = calendar.latest_trading_day_on_or_before(as_of)
        required_dates = calendar.previous_trading_days(
            expected_latest,
            required_return_window + 1,
            include_value=True,
        )
        # IPOs/new listings legitimately have less than a full lookback. Dates
        # before the official first trade date are not missing market data.
        if listing_start is not None:
            required_dates = [d for d in required_dates if d >= listing_start]
    except CalendarCoverageError as exc:
        issues.append(QualityIssue("CALENDAR_OUT_OF_RANGE", Severity.ERROR, str(exc)))
        return QualityReport(as_of, expected_latest, tuple(issues), required_return_window)

    dates = [bar.date for bar in ordered]
    date_set = set(dates)

    for bar in ordered:
        if bar.date > as_of:
            issues.append(
                QualityIssue("FUTURE_BAR", Severity.ERROR, f"Price bar is after as_of={as_of.isoformat()}", bar.date)
            )
            continue
        try:
            session = calendar.session(bar.date)
        except CalendarCoverageError as exc:
            issues.append(QualityIssue("CALENDAR_OUT_OF_RANGE", Severity.ERROR, str(exc), bar.date))
            continue
        if session.session_type == SessionType.CLOSED:
            issues.append(
                QualityIssue(
                    "BAR_ON_CLOSED_SESSION",
                    Severity.ERROR,
                    "Price bar exists on a BIST closed session",
                    bar.date,
                )
            )

    missing = [d for d in required_dates if d not in date_set]
    for missing_date in missing:
        issues.append(
            QualityIssue(
                "MISSING_TRADING_SESSION",
                Severity.ERROR,
                "Required BIST trading-day close is missing; lookback must not be compressed",
                missing_date,
            )
        )

    if expected_latest not in date_set:
        issues.append(
            QualityIssue(
                "STALE_LATEST_BAR",
                Severity.ERROR,
                f"Latest expected BIST session {expected_latest.isoformat()} is missing",
                expected_latest,
            )
        )

    # A zero-volume day can be legitimate for some securities, so it is warning-only.
    for bar in ordered:
        if bar.volume == 0:
            issues.append(
                QualityIssue("ZERO_VOLUME", Severity.WARNING, "Zero volume; verify suspension/illiquidity", bar.date)
            )

    return QualityReport(as_of, expected_latest, tuple(issues), required_return_window)


def require_valid_price_history(
    bars: Sequence[PriceBar],
    calendar: BISTTradingCalendar,
    *,
    as_of: date,
    required_return_window: int = 252,
    listing_start: date | None = None,
) -> QualityReport:
    report = validate_price_history(
        bars,
        calendar,
        as_of=as_of,
        required_return_window=required_return_window,
        listing_start=listing_start,
    )
    if not report.passed:
        preview = "; ".join(f"{issue.code}: {issue.message}" for issue in report.errors[:5])
        raise PriceDataQualityError(preview)
    return report
