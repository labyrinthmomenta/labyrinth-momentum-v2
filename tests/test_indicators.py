import math

from src.indicators.momentum import momentum
from src.indicators.fip import fip
from src.indicators.atr import (
    atr_percent,
    atr_percent_series,
)
from src.indicators.acceleration import delta


def test_momentum_compounds_returns():
    assert math.isclose(momentum([0.10, -0.05], 2), 0.045, rel_tol=0, abs_tol=1e-12)


def test_fip_sign_convention():
    # Momentum is positive; 1 negative and 2 positive => (1-2)/3.
    assert math.isclose(fip([0.10, -0.02, 0.03], 3), -1/3, rel_tol=0, abs_tol=1e-12)


def test_fip_negative_momentum_flips_sign():
    # Momentum negative; 2 negative and 1 positive => -1/3 under sign(M)*(Nneg-Npos)/N.
    assert math.isclose(fip([-0.10, -0.02, 0.03], 3), -1/3, rel_tol=0, abs_tol=1e-12)


def test_atr_percent():
    highs = [11, 12, 13, 14, 15]
    lows = [9, 10, 11, 12, 13]
    closes = [10, 11, 12, 13, 14]
    # With this synthetic series every TR is 2, so Wilder ATR is 2.
    expected_atr = 2.0
    assert math.isclose(atr_percent(highs, lows, closes, period=4), expected_atr / 14 * 100)


def test_delta():
    assert delta(0.10, 0.25) == -0.15
    assert delta(None, 0.25) is None


def test_atr_percent_series_preserves_alignment_and_warmup():
    closes = [
        float(value)
        for value in range(100, 116)
    ]
    highs = [
        close + 1.0
        for close in closes
    ]
    lows = [
        close - 1.0
        for close in closes
    ]

    result = atr_percent_series(
        highs,
        lows,
        closes,
        period=14,
    )

    assert len(result) == len(closes)

    # ATR14 needs 14 True Range observations, which requires
    # 15 price bars. Therefore indexes 0..13 are unavailable.
    assert result[:14] == [None] * 14

    expected_atr = 2.0

    assert math.isclose(
        result[14],
        expected_atr / closes[14] * 100.0,
        rel_tol=0,
        abs_tol=1e-12,
    )

    assert math.isclose(
        result[15],
        expected_atr / closes[15] * 100.0,
        rel_tol=0,
        abs_tol=1e-12,
    )


def test_atr_percent_series_matches_causal_prefix_calculation():
    closes = [
        100.0,
        101.0,
        99.0,
        102.0,
        104.0,
        103.0,
        105.0,
        107.0,
        106.0,
        110.0,
        108.0,
        111.0,
        113.0,
        112.0,
        115.0,
        114.0,
        118.0,
        117.0,
        120.0,
        119.0,
    ]

    highs = [
        close + offset
        for close, offset in zip(
            closes,
            [
                1.0, 2.0, 1.5, 2.5, 1.0,
                1.5, 2.0, 1.0, 2.5, 1.5,
                1.0, 2.0, 1.5, 1.0, 2.5,
                1.0, 2.0, 1.5, 2.5, 1.0,
            ],
        )
    ]

    lows = [
        close - offset
        for close, offset in zip(
            closes,
            [
                1.0, 1.5, 2.0, 1.0, 2.5,
                1.0, 1.5, 2.0, 1.0, 2.5,
                1.5, 1.0, 2.0, 2.5, 1.0,
                2.0, 1.0, 2.5, 1.5, 2.0,
            ],
        )
    ]

    result = atr_percent_series(
        highs,
        lows,
        closes,
        period=14,
    )

    for index, actual in enumerate(result):
        expected = atr_percent(
            highs[: index + 1],
            lows[: index + 1],
            closes[: index + 1],
            period=14,
        )

        if expected is None:
            assert actual is None
        else:
            assert actual is not None
            assert math.isclose(
                actual,
                expected,
                rel_tol=0,
                abs_tol=1e-12,
            )

