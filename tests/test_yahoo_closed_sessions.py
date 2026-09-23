from datetime import date
import sys
import types

import pandas as pd
import pytest

from src.calculation.engine import PriceBar
from src.data.calendar import BISTTradingCalendar
from src.data.providers.yahoo import YahooProvider
from src.validation.data_quality import validate_price_history

START, END = date(2026, 5, 26), date(2026, 6, 1)
DAYS = ['2026-05-26', '2026-05-27', '2026-05-28', '2026-05-29', '2026-06-01']


def frame():
    return pd.DataFrame([
        [10.01, 10.09, 9.82, 9.85, 3763856],
        [9.85, 9.85, 9.85, 9.85, 0],
        [9.85, 9.85, 9.85, 9.85, 0],
        [9.85, 9.85, 9.85, 9.85, 0],
        [9.96, 10.31, 9.89, 10.12, 11388217],
    ], columns=['Open', 'High', 'Low', 'Close', 'Volume'], index=pd.to_datetime(DAYS))


@pytest.mark.parametrize('batch', [False, True])
def test_single_and_batch_remove_only_verified_holiday_placeholders(monkeypatch, caplog, batch):
    def download(symbols, **kwargs):
        if isinstance(symbols, str):
            return pd.concat({symbols: frame()}, axis=1).swaplevel(axis=1)
        return pd.concat({symbol: frame() for symbol in symbols}, axis=1)
    monkeypatch.setitem(sys.modules, 'yfinance', types.SimpleNamespace(download=download))
    provider = YahooProvider()
    results = (provider.fetch_many(['A1CAP', 'ASELS'], START, END).bars_by_ticker
               if batch else {'A1CAP': provider.fetch('A1CAP', START, END)})
    for ticker, bars in results.items():
        assert [b.date for b in bars] == [START, END]
        assert bars[0].volume == 3763856  # Half-day session preserved.
        assert validate_price_history(bars, provider.calendar, as_of=END, required_return_window=1).passed
        assert f'ticker={ticker} removed=3' in caplog.text


@pytest.mark.parametrize('column,value', [('Volume', 1), ('Volume', None), ('High', 10), ('Close', None), ('Open', -1)])
def test_suspicious_closed_session_row_is_retained_and_rejected(column, value):
    source = frame()
    source.loc['2026-05-27', column] = value
    provider = YahooProvider()
    bars = provider._frame_to_bars(source, START, END)
    assert date(2026, 5, 27) in [b.date for b in bars]
    report = validate_price_history(bars, provider.calendar, as_of=END, required_return_window=1)
    assert not report.passed
    assert any(i.code == 'BAR_ON_CLOSED_SESSION' for i in report.errors)


def test_flat_zero_volume_closed_bar_with_changed_price_is_not_discarded():
    source = frame()
    source.loc['2026-05-27', ['Open', 'High', 'Low', 'Close']] = 9.86
    bars = YahooProvider()._frame_to_bars(source, START, END)
    assert date(2026, 5, 27) in [b.date for b in bars]


def test_no_preceding_close_means_no_automatic_removal():
    bars = YahooProvider()._frame_to_bars(frame().iloc[1:], date(2026, 5, 27), END)
    assert len(bars) == 4


def test_open_session_zero_volume_flat_bar_is_kept():
    source = frame()
    source.loc['2026-06-01'] = [9.85, 9.85, 9.85, 9.85, 0]
    bars = YahooProvider()._frame_to_bars(source, START, END)
    assert len(bars) == 2 and bars[-1].date == END and bars[-1].volume == 0


def test_unknown_calendar_year_is_left_for_quality_validation():
    source = frame()
    source.index = source.index + pd.DateOffset(years=10)
    bars = YahooProvider()._frame_to_bars(source, date(2036, 5, 26), date(2036, 6, 1))
    assert len(bars) == 5


def test_missing_open_session_still_fails():
    provider = YahooProvider()
    bars = provider._frame_to_bars(frame().iloc[:-1], START, END)
    report = validate_price_history(bars, provider.calendar, as_of=END, required_return_window=1)
    assert any(i.code == 'MISSING_TRADING_SESSION' for i in report.errors)

def test_closed_session_all_nan_ohlc_is_removed():
    source = frame()
    source.loc[
        '2026-05-27',
        ['Open', 'High', 'Low', 'Close'],
    ] = float('nan')
    source.loc['2026-05-27', 'Volume'] = float('nan')

    bars = YahooProvider()._frame_to_bars(source, START, END)

    assert date(2026, 5, 27) not in [b.date for b in bars]


def test_open_session_all_nan_ohlc_is_not_removed():
    source = frame()
    source.loc[
        '2026-06-01',
        ['Open', 'High', 'Low', 'Close'],
    ] = float('nan')
    source.loc['2026-06-01', 'Volume'] = float('nan')

    provider = YahooProvider()
    bars = provider._frame_to_bars(source, START, END)

    assert date(2026, 6, 1) in [b.date for b in bars]

    report = validate_price_history(
        bars,
        provider.calendar,
        as_of=END,
        required_return_window=1,
    )
    assert not report.passed
    assert any(i.code == 'NON_FINITE_OHLC' for i in report.errors)


def test_closed_session_partial_nan_ohlc_is_not_removed():
    source = frame()
    source.loc['2026-05-27', 'Open'] = float('nan')

    bars = YahooProvider()._frame_to_bars(source, START, END)

    assert date(2026, 5, 27) in [b.date for b in bars]


def test_closed_session_all_nan_with_positive_volume_is_not_removed():
    source = frame()
    source.loc[
        '2026-05-27',
        ['Open', 'High', 'Low', 'Close'],
    ] = float('nan')
    source.loc['2026-05-27', 'Volume'] = 100

    bars = YahooProvider()._frame_to_bars(source, START, END)

    assert date(2026, 5, 27) in [b.date for b in bars]

