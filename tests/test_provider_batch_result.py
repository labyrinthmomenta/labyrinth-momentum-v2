from __future__ import annotations

from datetime import date

from src.data.providers.base import BatchFetchResult
from src.data.storage.adjustments import AdjustmentRecord


def test_batch_fetch_result_keeps_existing_positional_contract():
    result = BatchFetchResult(
        {"AAA": []},
        2,
    )

    assert result.bars_by_ticker == {"AAA": []}
    assert result.provider_calls == 2
    assert result.adjustments_by_ticker == {}


def test_batch_fetch_result_accepts_optional_adjustments():
    record = AdjustmentRecord(
        date=date(2026, 9, 21),
        adj_close=95.0,
        adjustment_factor=0.95,
        dividend=5.0,
        stock_split=0.0,
    )

    result = BatchFetchResult(
        {"AAA": []},
        1,
        adjustments_by_ticker={
            "AAA": [record],
        },
    )

    assert result.adjustments_by_ticker == {
        "AAA": [record],
    }
