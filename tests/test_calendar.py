from datetime import date

import pytest

from src.data.calendar import BISTTradingCalendar, CalendarCoverageError, SessionType


@pytest.fixture()
def calendar():
    return BISTTradingCalendar.from_csv()


def test_full_half_closed_sessions(calendar):
    assert calendar.session(date(2026, 3, 18)).session_type == SessionType.FULL
    assert calendar.session(date(2026, 3, 19)).session_type == SessionType.HALF
    assert calendar.session(date(2026, 3, 20)).session_type == SessionType.CLOSED


def test_half_day_counts_as_trading_day(calendar):
    days = calendar.trading_days(date(2026, 3, 18), date(2026, 3, 23))
    assert date(2026, 3, 19) in days
    assert date(2026, 3, 20) not in days
    assert date(2026, 3, 23) in days


def test_weekend_is_closed(calendar):
    assert not calendar.is_trading_day(date(2026, 9, 20))


def test_latest_trading_day_skips_holiday(calendar):
    assert calendar.latest_trading_day_on_or_before(date(2026, 5, 29)) == date(2026, 5, 26)


def test_previous_trading_days_do_not_count_closed_sessions(calendar):
    days = calendar.previous_trading_days(date(2026, 3, 23), 3)
    assert days == [date(2026, 3, 18), date(2026, 3, 19), date(2026, 3, 23)]


def test_calendar_fails_outside_verified_years(calendar):
    with pytest.raises(CalendarCoverageError):
        calendar.session(date(2027, 1, 4))
