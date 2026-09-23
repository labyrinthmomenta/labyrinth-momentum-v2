import math

from src.indicators.momentum import momentum
from src.indicators.fip import fip
from src.indicators.atr import atr_percent
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
