from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from src.strategy.technical_prices import (
    VendorPriceBar,
    build_technical_prices,
)


def _bar(
    *,
    day: int = 1,
    open_: float = 100.0,
    high: float = 105.0,
    low: float = 95.0,
    close: float = 100.0,
    adj_close: float = 90.0,
    volume: float = 1_000_000.0,
    dividend: float = 0.0,
    stock_split: float = 0.0,
) -> VendorPriceBar:
    return VendorPriceBar(
        date=date(2026, 1, day),
        open=open_,
        high=high,
        low=low,
        close=close,
        adj_close=adj_close,
        volume=volume,
        dividend=dividend,
        stock_split=stock_split,
    )


def test_adjustment_factor_is_adj_close_divided_by_close():
    result = build_technical_prices(
        [
            _bar(
                close=100.0,
                adj_close=90.0,
            )
        ]
    )

    bar = result[0]

    assert bar.adjustment_factor == pytest.approx(0.90)


def test_all_ohlc_fields_use_same_adjustment_factor():
    result = build_technical_prices(
        [
            _bar(
                open_=100.0,
                high=110.0,
                low=90.0,
                close=100.0,
                adj_close=80.0,
            )
        ]
    )

    bar = result[0]

    assert bar.adjustment_factor == pytest.approx(0.80)

    assert bar.open == pytest.approx(80.0)
    assert bar.high == pytest.approx(88.0)
    assert bar.low == pytest.approx(72.0)
    assert bar.close == pytest.approx(80.0)


def test_volume_is_not_adjusted_and_raw_prices_are_preserved():
    source = _bar(
        open_=100.0,
        high=110.0,
        low=90.0,
        close=100.0,
        adj_close=80.0,
        volume=2_500_000.0,
    )

    result = build_technical_prices([source])

    bar = result[0]

    assert bar.volume == pytest.approx(2_500_000.0)

    assert bar.raw_open == pytest.approx(100.0)
    assert bar.raw_high == pytest.approx(110.0)
    assert bar.raw_low == pytest.approx(90.0)
    assert bar.raw_close == pytest.approx(100.0)

    assert bar.adj_close == pytest.approx(80.0)


def test_factor_one_leaves_technical_prices_unchanged():
    source = _bar(
        open_=101.0,
        high=106.0,
        low=99.0,
        close=104.0,
        adj_close=104.0,
    )

    bar = build_technical_prices([source])[0]

    assert bar.adjustment_factor == pytest.approx(1.0)

    assert bar.open == pytest.approx(source.open)
    assert bar.high == pytest.approx(source.high)
    assert bar.low == pytest.approx(source.low)
    assert bar.close == pytest.approx(source.close)


def test_dividend_explains_material_factor_change():
    bars = [
        _bar(
            day=1,
            close=100.0,
            adj_close=90.0,
        ),
        _bar(
            day=2,
            close=100.0,
            adj_close=95.0,
            dividend=5.0,
        ),
    ]

    result = build_technical_prices(bars)

    assert result[0].adjustment_status == "OK"
    assert result[1].adjustment_status == "OK"

    assert result[0].adjustment_factor == pytest.approx(0.90)
    assert result[1].adjustment_factor == pytest.approx(0.95)


def test_stock_split_metadata_does_not_apply_second_price_adjustment():
    # Yahoo historical OHLC is already split-normalized in the
    # BIST examples we validated.
    #
    # Therefore Stock Splits metadata is audit information only.
    # It must NOT divide the price by 10 again.
    source = _bar(
        open_=87.60,
        high=89.50,
        low=86.25,
        close=87.25,
        adj_close=87.25,
        stock_split=10.0,
    )

    bar = build_technical_prices([source])[0]

    assert bar.adjustment_factor == pytest.approx(1.0)
    assert bar.close == pytest.approx(87.25)
    assert bar.raw_close == pytest.approx(87.25)
    assert bar.stock_split == pytest.approx(10.0)


def test_unexplained_material_factor_change_is_flagged():
    bars = [
        _bar(
            day=1,
            close=100.0,
            adj_close=90.0,
        ),
        _bar(
            day=2,
            close=100.0,
            adj_close=95.0,
            dividend=0.0,
            stock_split=0.0,
        ),
    ]

    result = build_technical_prices(bars)

    assert result[0].adjustment_status == "OK"
    assert (
        result[1].adjustment_status
        == "UNEXPLAINED_ADJUSTMENT"
    )


@pytest.mark.parametrize(
    ("close", "adj_close"),
    [
        (0.0, 100.0),
        (100.0, 0.0),
        (float("nan"), 100.0),
        (100.0, float("nan")),
        (float("inf"), 100.0),
        (100.0, float("inf")),
    ],
)
def test_invalid_close_or_adj_close_fails_closed(
    close: float,
    adj_close: float,
):
    source = _bar(
        close=close,
        adj_close=adj_close,
    )

    with pytest.raises(ValueError):
        build_technical_prices([source])


def test_small_factor_noise_is_not_flagged_as_unexplained():
    # 0.02% factor movement stays below the default 0.05%
    # material-change tolerance.
    bars = [
        _bar(
            day=1,
            close=100.0,
            adj_close=90.0000,
        ),
        _bar(
            day=2,
            close=100.0,
            adj_close=90.0180,
        ),
    ]

    result = build_technical_prices(bars)

    assert result[1].adjustment_status == "OK"


def test_source_bars_must_be_strictly_increasing_by_date():
    first = _bar(day=1)
    second = replace(
        _bar(day=2),
        date=first.date,
    )

    with pytest.raises(
        ValueError,
        match="strictly increasing",
    ):
        build_technical_prices(
            [first, second]
        )
