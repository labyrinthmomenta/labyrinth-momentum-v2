from __future__ import annotations

from datetime import date
import sys
import types

import pandas as pd

from src.data.providers.yahoo import YahooProvider


def _batch_frame(symbols, day="2026-09-21"):
    if isinstance(symbols, str):
        symbols = [symbols]
    fields = ["Open", "High", "Low", "Close", "Volume"]
    columns = pd.MultiIndex.from_product([symbols, fields])
    values = []
    row = []
    for index, _symbol in enumerate(symbols):
        base = 100.0 + index
        row.extend([base, base + 2, base - 2, base + 1, 1000.0])
    values.append(row)
    return pd.DataFrame(values, index=pd.to_datetime([day]), columns=columns)


def test_yahoo_fetch_many_chunks_and_parses_multiindex(monkeypatch):
    calls = []

    def download(symbols, **kwargs):
        calls.append((symbols, kwargs))
        return _batch_frame(symbols)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=download))
    provider = YahooProvider(batch_size=2)
    result = provider.fetch_many(
        ["AAA", "BBB", "CCC"], date(2026, 9, 21), date(2026, 9, 21)
    )

    assert result.provider_calls == 2
    assert len(calls) == 2
    assert set(result.bars_by_ticker) == {"AAA", "BBB", "CCC"}
    assert all(len(result.bars_by_ticker[ticker]) == 1 for ticker in result.bars_by_ticker)
    assert result.bars_by_ticker["AAA"][0].date == date(2026, 9, 21)
    assert calls[0][1]["auto_adjust"] is False
    assert calls[0][1]["group_by"] == "ticker"
