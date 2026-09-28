import math

from src.strategy.market_context import (
    compute_market_breadth,
)


def test_market_breadth_uses_feature_specific_denominators():
    rows = [
        {
            "momentum_21": 0.10,
            "momentum_63": 0.20,
            "distance_to_sma50_pct": 5.0,
            "distance_to_sma200_pct": 10.0,
            "acceleration_21_63_all": 20.0,
        },
        {
            "momentum_21": -0.05,
            "momentum_63": -0.10,
            "distance_to_sma50_pct": -2.0,
            "distance_to_sma200_pct": None,
            "acceleration_21_63_all": -10.0,
        },
        {
            "momentum_21": 0.03,
            "momentum_63": None,
            "distance_to_sma50_pct": None,
            "distance_to_sma200_pct": None,
            "acceleration_21_63_all": None,
        },
    ]

    breadth = compute_market_breadth(
        rows
    )

    assert breadth.total_equities == 3

    assert breadth.momentum_21_coverage == 3
    assert math.isclose(
        breadth.momentum_21_positive_pct,
        66.66666666666666,
        abs_tol=1e-12,
    )

    assert breadth.momentum_63_coverage == 2
    assert breadth.momentum_63_positive_pct == 50.0

    assert breadth.sma50_coverage == 2
    assert breadth.above_sma50_pct == 50.0

    assert breadth.sma200_coverage == 1
    assert breadth.above_sma200_pct == 100.0

    assert breadth.acceleration_21_63_coverage == 2
    assert breadth.acceleration_21_63_positive_pct == 50.0


def test_missing_values_are_not_counted_as_negative():
    rows = [
        {
            "momentum_21": 0.10,
        },
        {
            "momentum_21": None,
        },
        {
            "momentum_21": None,
        },
    ]

    breadth = compute_market_breadth(
        rows
    )

    assert breadth.momentum_21_coverage == 1
    assert breadth.momentum_21_positive_pct == 100.0


def test_medians_are_calculated_from_available_values():
    rows = [
        {
            "momentum_63": -0.20,
            "acceleration_21_63_all": -30.0,
        },
        {
            "momentum_63": 0.10,
            "acceleration_21_63_all": 10.0,
        },
        {
            "momentum_63": 0.30,
            "acceleration_21_63_all": 20.0,
        },
    ]

    breadth = compute_market_breadth(
        rows
    )

    assert breadth.momentum_63_median == 0.10
    assert breadth.acceleration_21_63_median == 10.0


def test_zero_is_neutral_not_positive():
    rows = [
        {
            "momentum_21": 0.0,
            "momentum_63": 0.0,
            "distance_to_sma50_pct": 0.0,
            "distance_to_sma200_pct": 0.0,
            "acceleration_21_63_all": 0.0,
        },
    ]

    breadth = compute_market_breadth(
        rows
    )

    assert breadth.momentum_21_positive_pct == 0.0
    assert breadth.momentum_63_positive_pct == 0.0
    assert breadth.above_sma50_pct == 0.0
    assert breadth.above_sma200_pct == 0.0
    assert breadth.acceleration_21_63_positive_pct == 0.0


def test_empty_universe_returns_none_metrics():
    breadth = compute_market_breadth(
        []
    )

    assert breadth.total_equities == 0

    assert breadth.momentum_21_coverage == 0
    assert breadth.momentum_21_positive_pct is None

    assert breadth.momentum_63_median is None

    assert breadth.above_sma50_pct is None
    assert breadth.above_sma200_pct is None

    assert breadth.acceleration_21_63_median is None
