from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from pathlib import Path

DEFAULT_EXCEPTION_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "reference" / "bist_calendar_exceptions.csv"
)


class CalendarCoverageError(ValueError):
    """Raised when a date falls outside the verified official calendar coverage."""


class SessionType(str, Enum):
    FULL = "FULL"
    HALF = "HALF"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class CalendarException:
    date: date
    session_type: SessionType
    holiday_name: str
    source: str


@dataclass(frozen=True)
class CalendarSession:
    date: date
    session_type: SessionType
    holiday_name: str | None = None
    source: str | None = None

    @property
    def is_trading_day(self) -> bool:
        return self.session_type in (SessionType.FULL, SessionType.HALF)


class BISTTradingCalendar:
    """Verified BIST Pay Market calendar backed by official holiday exceptions.

    Normal Monday-Friday dates are FULL sessions. Official exceptions can mark
    a weekday as HALF or CLOSED. Weekend dates are CLOSED unless a future
    explicit exception says otherwise.

    The calendar intentionally fails outside its verified year coverage instead
    of guessing future or older Turkish market holidays.
    """

    def __init__(self, exceptions: list[CalendarException], covered_years: set[int]):
        if not covered_years:
            raise ValueError("covered_years cannot be empty")
        self._exceptions = {item.date: item for item in exceptions}
        self.covered_years = frozenset(covered_years)

    @classmethod
    def from_csv(cls, path: str | Path = DEFAULT_EXCEPTION_PATH) -> "BISTTradingCalendar":
        path = Path(path)
        exceptions: list[CalendarException] = []
        years: set[int] = set()
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"date", "session_type", "holiday_name", "source"}
            if not required.issubset(reader.fieldnames or set()):
                missing = required - set(reader.fieldnames or [])
                raise ValueError(f"Calendar CSV missing columns: {sorted(missing)}")
            for row in reader:
                d = date.fromisoformat(row["date"])
                years.add(d.year)
                exceptions.append(
                    CalendarException(
                        date=d,
                        session_type=SessionType(row["session_type"]),
                        holiday_name=row["holiday_name"].strip(),
                        source=row["source"].strip(),
                    )
                )
        return cls(exceptions, years)

    def _assert_covered(self, value: date) -> None:
        if value.year not in self.covered_years:
            lo, hi = min(self.covered_years), max(self.covered_years)
            raise CalendarCoverageError(
                f"{value.isoformat()} is outside verified BIST calendar coverage ({lo}-{hi})"
            )

    def session(self, value: date) -> CalendarSession:
        self._assert_covered(value)
        exception = self._exceptions.get(value)
        if exception is not None:
            return CalendarSession(
                date=value,
                session_type=exception.session_type,
                holiday_name=exception.holiday_name,
                source=exception.source,
            )
        if value.weekday() >= 5:
            return CalendarSession(date=value, session_type=SessionType.CLOSED)
        return CalendarSession(date=value, session_type=SessionType.FULL)

    def is_trading_day(self, value: date) -> bool:
        return self.session(value).is_trading_day

    def sessions(self, start: date, end: date) -> list[CalendarSession]:
        if end < start:
            raise ValueError("end must be on or after start")
        self._assert_covered(start)
        self._assert_covered(end)
        result: list[CalendarSession] = []
        current = start
        while current <= end:
            result.append(self.session(current))
            current += timedelta(days=1)
        return result

    def trading_days(self, start: date, end: date) -> list[date]:
        return [session.date for session in self.sessions(start, end) if session.is_trading_day]

    def latest_trading_day_on_or_before(self, value: date) -> date:
        current = value
        while True:
            self._assert_covered(current)
            if self.is_trading_day(current):
                return current
            current -= timedelta(days=1)

    def previous_trading_days(
        self,
        value: date,
        count: int,
        *,
        include_value: bool = True,
    ) -> list[date]:
        """Return the last `count` BIST trading dates in ascending order."""
        if count <= 0:
            raise ValueError("count must be positive")
        current = value if include_value else value - timedelta(days=1)
        result: list[date] = []
        while len(result) < count:
            self._assert_covered(current)
            if self.is_trading_day(current):
                result.append(current)
            current -= timedelta(days=1)
        return list(reversed(result))
