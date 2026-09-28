from datetime import date

from src.strategy.index_features import IndexFeatures
from src.strategy.market_context import MarketBreadth
from src.strategy.regime import (
    classify_market_regime_components,
)


def index_features(
    *,
    m21,
    m63,
    m126,
    distance50,
    close=100.0,
    sma150=100.0,
):
    return IndexFeatures(
        as_of=date(2026, 9, 24),

        total_observations=200,
        contiguous_observations=200,

        contiguous_start=date(2026, 1, 1),
        last_gap_date=None,

        close=close,

        momentum_21=m21,
        momentum_63=m63,
        momentum_126=m126,
        momentum_252=None,

        sma50=100.0,
        sma150=sma150,
        sma200=None,

        distance_to_sma50_pct=distance50,
        distance_to_sma200_pct=None,

        sma50_slope_20=0.0,
        sma200_slope_20=None,
    )


def breadth(
    *,
    m21_pct,
    m63_pct,
    sma50_pct,
    sma200_pct,
    accel_pct,
    accel_median,
):
    return MarketBreadth(
        total_equities=600,

        momentum_21_coverage=600,
        momentum_21_positive_pct=m21_pct,

        momentum_63_coverage=600,
        momentum_63_positive_pct=m63_pct,
        momentum_63_median=-0.10,

        sma50_coverage=600,
        above_sma50_pct=sma50_pct,

        sma200_coverage=580,
        above_sma200_pct=sma200_pct,

        acceleration_21_63_coverage=600,
        acceleration_21_63_positive_pct=accel_pct,
        acceleration_21_63_median=accel_median,
    )


def test_negative_short_trend_is_detected():
    xu30 = index_features(
        m21=-0.05,
        m63=-0.03,
        m126=0.05,
        distance50=-2.0,
        close=101.0,
        sma150=100.0,
    )

    xu100 = index_features(
        m21=-0.10,
        m63=-0.08,
        m126=-0.02,
        distance50=-7.0,
        close=93.0,
        sma150=100.0,
    )

    result = classify_market_regime_components(
        xu30,
        xu100,
        breadth(
            m21_pct=10,
            m63_pct=15,
            sma50_pct=12,
            sma200_pct=20,
            accel_pct=58,
            accel_median=2,
        ),
    )

    assert result.xu030_short_trend == "NEGATIVE"
    assert result.xu100_short_trend == "NEGATIVE"


def test_medium_backdrop_can_differ_from_short_trend():
    xu30 = index_features(
        m21=-0.05,
        m63=-0.03,
        m126=0.05,
        distance50=-1.0,
        close=101.0,
        sma150=100.0,
    )

    xu100 = index_features(
        m21=-0.10,
        m63=-0.08,
        m126=-0.02,
        distance50=-5.0,
        close=95.0,
        sma150=100.0,
    )

    result = classify_market_regime_components(
        xu30,
        xu100,
        breadth(
            m21_pct=10,
            m63_pct=15,
            sma50_pct=12,
            sma200_pct=20,
            accel_pct=50,
            accel_median=0,
        ),
    )

    assert result.xu030_short_trend == "NEGATIVE"
    assert result.xu030_medium_backdrop == "POSITIVE"

    assert result.xu100_short_trend == "NEGATIVE"
    assert result.xu100_medium_backdrop == "NEGATIVE"


def test_xu030_relative_leadership_is_descriptive():
    xu30 = index_features(
        m21=-0.05,
        m63=-0.03,
        m126=0.06,
        distance50=-1.0,
    )

    xu100 = index_features(
        m21=-0.10,
        m63=-0.08,
        m126=-0.02,
        distance50=-7.0,
    )

    result = classify_market_regime_components(
        xu30,
        xu100,
        breadth(
            m21_pct=10,
            m63_pct=15,
            sma50_pct=12,
            sma200_pct=20,
            accel_pct=50,
            accel_median=0,
        ),
    )

    assert result.relative_leadership == "XU030_LEADS"


def test_negative_breadth_can_coexist_with_relative_improvement():
    xu30 = index_features(
        m21=-0.05,
        m63=-0.03,
        m126=0.05,
        distance50=-1.0,
    )

    xu100 = index_features(
        m21=-0.10,
        m63=-0.08,
        m126=-0.02,
        distance50=-7.0,
    )

    result = classify_market_regime_components(
        xu30,
        xu100,
        breadth(
            m21_pct=6,
            m63_pct=11,
            sma50_pct=8,
            sma200_pct=14,
            accel_pct=58,
            accel_median=2.2,
        ),
    )

    assert result.breadth_state == "BROAD_NEGATIVE"
    assert result.long_term_breadth_state == "NEGATIVE"

    assert (
        result.breadth_change_state
        == "IMPROVING_RELATIVE"
    )


def test_broad_positive_context_is_detected():
    xu30 = index_features(
        m21=0.05,
        m63=0.10,
        m126=0.20,
        distance50=5.0,
        close=110.0,
        sma150=100.0,
    )

    xu100 = index_features(
        m21=0.04,
        m63=0.08,
        m126=0.15,
        distance50=4.0,
        close=108.0,
        sma150=100.0,
    )

    result = classify_market_regime_components(
        xu30,
        xu100,
        breadth(
            m21_pct=70,
            m63_pct=65,
            sma50_pct=72,
            sma200_pct=60,
            accel_pct=60,
            accel_median=5,
        ),
    )

    assert result.xu030_short_trend == "POSITIVE"
    assert result.xu100_short_trend == "POSITIVE"

    assert result.breadth_state == "BROAD_POSITIVE"
    assert result.long_term_breadth_state == "POSITIVE"

    assert (
        result.breadth_change_state
        == "IMPROVING_RELATIVE"
    )
