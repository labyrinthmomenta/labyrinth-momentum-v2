from datetime import date, timedelta

import pytest

from src.indicators.atr import atr_percent_series
from src.strategy.swing_bar_adapter import build_swing_bars
from src.strategy.technical_prices import TechnicalPriceBar


def _technical_bar(
    index: int,
    *,
    adjustment_status: str = "OK",
) -> TechnicalPriceBar:
    day = date(2026, 1, 2) + timedelta(days=index)

    raw_close = 100.0 + index
    factor = 0.90

    raw_open = raw_close - 0.5
    raw_high = raw_close + 2.0
    raw_low = raw_close - 2.0

    return TechnicalPriceBar(
        date=day,

        open=raw_open * factor,
        high=raw_high * factor,
        low=raw_low * factor,
        close=raw_close * factor,

        volume=1_000_000.0 + index,

        raw_open=raw_open,
        raw_high=raw_high,
        raw_low=raw_low,
        raw_close=raw_close,
        adj_close=raw_close * factor,

        dividend=0.0,
        stock_split=0.0,

        adjustment_factor=factor,
        adjustment_status=adjustment_status,
    )


def test_build_swing_bars_skips_atr_warmup_and_uses_adjusted_prices():
    bars = tuple(
        _technical_bar(index)
        for index in range(16)
    )

    result = build_swing_bars(
        bars,
        atr_period=14,
    )

    # ATR14 needs 15 price bars, so indexes 0..13 are warm-up.
    assert len(result) == 2

    assert result[0].date == bars[14].date
    assert result[1].date == bars[15].date

    assert result[0].high == pytest.approx(
        bars[14].high
    )
    assert result[0].low == pytest.approx(
        bars[14].low
    )
    assert result[0].close == pytest.approx(
        bars[14].close
    )

    # Guard against accidentally feeding raw prices into swing logic.
    assert result[0].close != pytest.approx(
        bars[14].raw_close
    )


def test_build_swing_bars_atr_matches_causal_atr_series():
    bars = tuple(
        _technical_bar(index)
        for index in range(20)
    )

    highs = [
        bar.high
        for bar in bars
    ]
    lows = [
        bar.low
        for bar in bars
    ]
    closes = [
        bar.close
        for bar in bars
    ]

    expected_atr = atr_percent_series(
        highs,
        lows,
        closes,
        period=14,
    )

    result = build_swing_bars(
        bars,
        atr_period=14,
    )

    expected_pairs = [
        (bar, atr_pct)
        for bar, atr_pct in zip(
            bars,
            expected_atr,
        )
        if atr_pct is not None
    ]

    assert len(result) == len(expected_pairs)

    for swing_bar, (technical_bar, atr_pct) in zip(
        result,
        expected_pairs,
    ):
        assert swing_bar.date == technical_bar.date
        assert swing_bar.high == pytest.approx(
            technical_bar.high
        )
        assert swing_bar.low == pytest.approx(
            technical_bar.low
        )
        assert swing_bar.close == pytest.approx(
            technical_bar.close
        )
        assert swing_bar.atr_pct == pytest.approx(
            atr_pct
        )


def test_build_swing_bars_returns_empty_when_atr_warmup_is_incomplete():
    bars = tuple(
        _technical_bar(index)
        for index in range(14)
    )

    result = build_swing_bars(
        bars,
        atr_period=14,
    )

    assert result == ()


def test_build_swing_bars_rejects_non_ok_technical_price():
    bars = [
        _technical_bar(index)
        for index in range(16)
    ]

    bars[10] = _technical_bar(
        10,
        adjustment_status="UNEXPLAINED_ADJUSTMENT",
    )

    with pytest.raises(
        ValueError,
        match="UNEXPLAINED_ADJUSTMENT",
    ):
        build_swing_bars(
            bars,
            atr_period=14,
        )
