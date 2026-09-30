from __future__ import annotations

from datetime import date
import sys
import types

import pandas as pd
import pytest

from src.data.providers.yahoo import YahooProvider
from src.data.storage.adjustments import AdjustmentRecord


def test_fetch_adjustments_requests_actions_and_parses_metadata(monkeypatch):
    calls = []

    frame = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [105.0],
            "Low": [98.0],
            "Close": [100.0],
            "Adj Close": [95.0],
            "Volume": [1000.0],
            "Dividends": [5.0],
            "Stock Splits": [0.0],
        },
        index=pd.to_datetime(["2026-09-21"]),
    )

    def download(symbol, **kwargs):
        calls.append((symbol, kwargs))
        return frame

    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        types.SimpleNamespace(download=download),
    )

    provider = YahooProvider()

    records = provider.fetch_adjustments(
        "AAA",
        date(2026, 9, 21),
        date(2026, 9, 21),
    )

    assert records == [
        AdjustmentRecord(
            date=date(2026, 9, 21),
            adj_close=95.0,
            adjustment_factor=0.95,
            dividend=5.0,
            stock_split=0.0,
        )
    ]

    assert len(calls) == 1

    symbol, kwargs = calls[0]

    assert symbol == "AAA.IS"
    assert kwargs["auto_adjust"] is False
    assert kwargs["actions"] is True
    assert kwargs["threads"] is False


def test_fetch_adjustments_missing_action_columns_remain_none(monkeypatch):
    frame = pd.DataFrame(
        {
            "Close": [100.0],
            "Adj Close": [100.0],
        },
        index=pd.to_datetime(["2026-09-21"]),
    )

    def download(symbol, **kwargs):
        return frame

    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        types.SimpleNamespace(download=download),
    )

    records = YahooProvider().fetch_adjustments(
        "AAA",
        date(2026, 9, 21),
        date(2026, 9, 21),
    )

    assert records == [
        AdjustmentRecord(
            date=date(2026, 9, 21),
            adj_close=100.0,
            adjustment_factor=1.0,
            dividend=None,
            stock_split=None,
        )
    ]


def test_fetch_adjustments_invalid_factor_inputs_fail_closed(monkeypatch):
    frame = pd.DataFrame(
        {
            "Close": [0.0],
            "Adj Close": [95.0],
            "Dividends": [0.0],
            "Stock Splits": [0.0],
        },
        index=pd.to_datetime(["2026-09-21"]),
    )

    def download(symbol, **kwargs):
        return frame

    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        types.SimpleNamespace(download=download),
    )

    records = YahooProvider().fetch_adjustments(
        "AAA",
        date(2026, 9, 21),
        date(2026, 9, 21),
    )

    assert records[0].adj_close == pytest.approx(95.0)
    assert records[0].adjustment_factor is None


def test_fetch_many_returns_prices_and_adjustments_from_same_download(monkeypatch):
    calls = []

    symbols = ["AAA.IS", "BBB.IS"]
    fields = [
        "Open",
        "High",
        "Low",
        "Close",
        "Adj Close",
        "Volume",
        "Dividends",
        "Stock Splits",
    ]

    columns = pd.MultiIndex.from_product(
        [symbols, fields]
    )

    frame = pd.DataFrame(
        [[
            # AAA
            100.0, 105.0, 98.0, 100.0,
            95.0, 1000.0, 5.0, 0.0,

            # BBB
            200.0, 205.0, 198.0, 200.0,
            200.0, 2000.0, 0.0, 0.0,
        ]],
        index=pd.to_datetime(["2026-09-21"]),
        columns=columns,
    )

    def download(requested_symbols, **kwargs):
        calls.append(
            (requested_symbols, kwargs)
        )
        return frame

    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        types.SimpleNamespace(
            download=download
        ),
    )

    result = YahooProvider(
        batch_size=10
    ).fetch_many(
        ["AAA", "BBB"],
        date(2026, 9, 21),
        date(2026, 9, 21),
    )

    # One vendor snapshot must feed both outputs.
    assert len(calls) == 1
    assert result.provider_calls == 1

    assert len(
        result.bars_by_ticker["AAA"]
    ) == 1
    assert len(
        result.bars_by_ticker["BBB"]
    ) == 1

    assert result.adjustments_by_ticker[
        "AAA"
    ] == [
        AdjustmentRecord(
            date=date(2026, 9, 21),
            adj_close=95.0,
            adjustment_factor=0.95,
            dividend=5.0,
            stock_split=0.0,
        )
    ]

    assert result.adjustments_by_ticker[
        "BBB"
    ] == [
        AdjustmentRecord(
            date=date(2026, 9, 21),
            adj_close=200.0,
            adjustment_factor=1.0,
            dividend=0.0,
            stock_split=0.0,
        )
    ]

    _, kwargs = calls[0]

    assert kwargs["auto_adjust"] is False
    assert kwargs["actions"] is True
