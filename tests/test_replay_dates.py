from datetime import date

import pytest

from src.data.calendar import BISTTradingCalendar
from src.research.replay_dates import month_end_trading_dates


def test_month_end_trading_dates_use_last_official_bist_session():
    calendar = BISTTradingCalendar.from_csv()

    result = month_end_trading_dates(
        calendar,
        start_month=date(2026, 5, 1),
        end_month=date(2026, 7, 1),
    )

    assert result == (
        date(2026, 5, 26),
        date(2026, 6, 30),
        date(2026, 7, 31),
    )


def test_month_end_trading_dates_accept_half_session_as_trading_day():
    calendar = BISTTradingCalendar.from_csv()

    result = month_end_trading_dates(
        calendar,
        start_month=date(2026, 5, 1),
        end_month=date(2026, 5, 1),
    )

    assert result == (
        date(2026, 5, 26),
    )


def test_month_end_trading_dates_require_first_day_month_markers():
    calendar = BISTTradingCalendar.from_csv()

    with pytest.raises(
        ValueError,
        match="first day",
    ):
        month_end_trading_dates(
            calendar,
            start_month=date(2026, 5, 15),
            end_month=date(2026, 7, 1),
        )


def test_month_end_trading_dates_require_ordered_month_range():
    calendar = BISTTradingCalendar.from_csv()

    with pytest.raises(
        ValueError,
        match="start_month",
    ):
        month_end_trading_dates(
            calendar,
            start_month=date(2026, 8, 1),
            end_month=date(2026, 7, 1),
        )
