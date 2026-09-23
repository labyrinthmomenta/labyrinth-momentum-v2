from datetime import date

import pytest

from src.calculation.engine import PriceBar
from src.calculation.validated import compute_validated_snapshot
from src.data.calendar import BISTTradingCalendar
from src.validation.data_quality import PriceDataQualityError, validate_price_history


def bar(day, close=100.0, volume=1000.0):
    return PriceBar(day, close, close + 1, close - 1, close, volume)


@pytest.fixture()
def calendar():
    return BISTTradingCalendar.from_csv()


def make_complete_bars(calendar, as_of, return_window):
    dates = calendar.previous_trading_days(as_of, return_window + 1)
    return [bar(d, close=100 + i) for i, d in enumerate(dates)]


def test_complete_calendar_aligned_history_passes(calendar):
    bars = make_complete_bars(calendar, date(2026, 9, 21), 21)
    report = validate_price_history(bars, calendar, as_of=date(2026, 9, 21), required_return_window=21)
    assert report.passed


def test_missing_session_is_error_not_compressed(calendar):
    bars = make_complete_bars(calendar, date(2026, 9, 21), 21)
    missing_date = bars[-5].date
    bars = [b for b in bars if b.date != missing_date]
    # Add an older bar so the raw observation count still appears sufficient.
    older = calendar.previous_trading_days(bars[0].date, 2)[0]
    bars = [bar(older, close=99.0)] + bars
    report = validate_price_history(bars, calendar, as_of=date(2026, 9, 21), required_return_window=21)
    assert not report.passed
    assert any(i.code == "MISSING_TRADING_SESSION" and i.date == missing_date for i in report.errors)


def test_half_day_bar_is_valid(calendar):
    dates = calendar.previous_trading_days(date(2026, 3, 23), 3)
    bars = [bar(d, 100 + i) for i, d in enumerate(dates)]
    report = validate_price_history(bars, calendar, as_of=date(2026, 3, 23), required_return_window=2)
    assert report.passed
    assert date(2026, 3, 19) in [b.date for b in bars]


def test_bar_on_closed_session_fails(calendar):
    bars = make_complete_bars(calendar, date(2026, 9, 21), 2)
    bars.append(bar(date(2026, 9, 20)))  # Sunday
    bars.sort(key=lambda b: b.date)
    report = validate_price_history(bars, calendar, as_of=date(2026, 9, 21), required_return_window=2)
    assert any(i.code == "BAR_ON_CLOSED_SESSION" for i in report.errors)


def test_invalid_ohlc_fails(calendar):
    bars = make_complete_bars(calendar, date(2026, 9, 21), 2)
    bad = bars[-1]
    bars[-1] = PriceBar(bad.date, 100, 99, 98, 100, 1000)
    report = validate_price_history(bars, calendar, as_of=date(2026, 9, 21), required_return_window=2)
    assert any(i.code == "INVALID_HIGH" for i in report.errors)


def test_zero_volume_is_warning_only(calendar):
    bars = make_complete_bars(calendar, date(2026, 9, 21), 2)
    last = bars[-1]
    bars[-1] = PriceBar(last.date, last.open, last.high, last.low, last.close, 0)
    report = validate_price_history(bars, calendar, as_of=date(2026, 9, 21), required_return_window=2)
    assert report.passed
    assert any(i.code == "ZERO_VOLUME" for i in report.warnings)


def test_validated_calculation_blocks_missing_session(calendar):
    bars = make_complete_bars(calendar, date(2026, 9, 21), 252)
    bars.pop(-10)
    with pytest.raises(PriceDataQualityError):
        compute_validated_snapshot(bars, calendar, as_of=date(2026, 9, 21))
