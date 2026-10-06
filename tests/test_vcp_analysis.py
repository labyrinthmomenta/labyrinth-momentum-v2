from dataclasses import replace
from datetime import date, timedelta

from src.strategy.swing_bar_adapter import build_swing_bars
from src.strategy.swing_detector import (
    SwingDetectorConfig,
    detect_swings,
)
from src.strategy.technical_prices import TechnicalPriceBar
from src.strategy.vcp_analysis import (
    _resolve_base_end_date,
    analyze_vcp,
)
from src.strategy.vcp_breakout import (
    VCPBreakoutEvent,
    detect_vcp_breakout,
)
from src.strategy.vcp_base_features import compute_vcp_base_features
from src.strategy.vcp_features import compute_vcp_features
from src.strategy.vcp_follow_through import (
    measure_vcp_follow_through,
)
from src.strategy.vcp_geometry import analyze_vcp_geometry
from src.strategy.vcp_state import (
    VCPStateConfig,
    classify_vcp_state,
)


BASE_DATE = date(2026, 1, 2)


def _bar(
    index: int,
    close: float,
) -> TechnicalPriceBar:
    day = BASE_DATE + timedelta(days=index)

    high = close * 1.02
    low = close * 0.98
    open_price = close * 0.995

    return TechnicalPriceBar(
        date=day,

        open=open_price,
        high=high,
        low=low,
        close=close,

        volume=1_000_000.0 + index * 10_000,

        raw_open=open_price,
        raw_high=high,
        raw_low=low,
        raw_close=close,
        adj_close=close,

        dividend=0.0,
        stock_split=0.0,

        adjustment_factor=1.0,
        adjustment_status="OK",
    )


def _bars() -> tuple[TechnicalPriceBar, ...]:
    closes = (
        100, 102, 104, 106, 108,
        110, 107, 104, 101, 98,
        100, 103, 106, 109, 112,
        109, 106, 103, 101, 99,
        101, 104, 107, 109, 111,
        109, 107, 105, 103, 102,
        104, 106, 108, 109, 110,
        108, 107, 106, 105, 104,
        105, 106, 107, 108, 109,
        110, 111, 112, 113, 114,
        113, 112, 111, 110, 109,
        110, 111, 112, 113, 115,
    )

    return tuple(
        _bar(index, float(close))
        for index, close in enumerate(closes)
    )


def _state_config() -> VCPStateConfig:
    return VCPStateConfig(
        tightening_range_5_max_pct=5.0,
        tightening_true_range_compression_max=0.75,
        tightening_final_volume_ratio_max=0.75,
        near_pivot_max_distance_pct=5.0,
        breakout_volume_expansion_min_ratio=1.50,
    )


def test_analyze_vcp_matches_manual_strategy_chain():
    bars = _bars()

    swing_config = SwingDetectorConfig(
        reversal_multiplier=1.50,
        absolute_floor_pct=1.50,
        min_leg_sessions=2,
    )

    state_config = _state_config()

    swing_bars = build_swing_bars(
        bars,
        atr_period=14,
    )

    swings = detect_swings(
        swing_bars,
        config=swing_config,
    )

    geometry = analyze_vcp_geometry(
        swings.confirmed,
        provisional=swings.provisional,
    )

    latest_atr_pct = (
        swing_bars[-1].atr_pct
        if swing_bars
        else None
    )

    features = compute_vcp_features(
        bars,
        geometry,
        atr_pct=latest_atr_pct,
    )

    breakout = detect_vcp_breakout(
        bars,
        geometry,
    )

    if breakout.first_close_break_date is None:
        base_end_date = bars[-1].date
    else:
        breakout_index = next(
            index
            for index, bar in enumerate(bars)
            if bar.date == breakout.first_close_break_date
        )

        assert breakout_index > 0

        base_end_date = bars[
            breakout_index - 1
        ].date

    base_features = compute_vcp_base_features(
        bars,
        geometry,
        end_date=base_end_date,
        atr_period=14,
    )

    follow_through = measure_vcp_follow_through(
        bars,
        breakout,
    )

    state = classify_vcp_state(
        geometry,
        features,
        breakout,
        config=state_config,
    )

    result = analyze_vcp(
        bars,
        state_config=state_config,
        swing_config=swing_config,
        atr_period=14,
    )

    assert result.technical_bars == bars
    assert result.swing_bars == swing_bars
    assert result.swings == swings
    assert result.geometry == geometry
    assert result.features == features
    assert result.base_features == base_features
    assert result.breakout == breakout
    assert result.follow_through == follow_through
    assert result.state == state


def test_analyze_vcp_forwards_custom_atr_period():
    bars = _bars()

    result = analyze_vcp(
        bars,
        state_config=_state_config(),
        atr_period=4,
    )

    # ATR period 4 requires 5 technical price bars.
    assert result.swing_bars[0].date == bars[4].date
    assert len(result.swing_bars) == len(bars) - 4



def test_analyze_vcp_exposes_structural_validity():
    from src.strategy.vcp_validity import assess_vcp_validity

    result = analyze_vcp(
        _bars(),
        state_config=_state_config(),
    )

    expected = assess_vcp_validity(
        result.geometry,
        result.features,
    )

    assert result.validity == expected



def test_base_end_date_uses_previous_actual_trading_bar():
    source = _bars()[:3]

    friday = date(2026, 1, 9)
    monday = date(2026, 1, 12)
    tuesday = date(2026, 1, 13)

    bars = (
        replace(source[0], date=friday),
        replace(source[1], date=monday),
        replace(source[2], date=tuesday),
    )

    breakout = VCPBreakoutEvent(
        has_confirmed_pivot=True,
        pivot_price=100.0,
        structure_ready_date=date(2026, 1, 8),
        first_intraday_breach_date=monday,
        first_close_break_date=monday,
        pivot_broken_by_close=True,
        breakout_close_pct_above_pivot=1.0,
        breakout_volume_ratio_20=None,
        current_close_above_pivot=True,
    )

    assert (
        _resolve_base_end_date(
            bars,
            breakout,
        )
        == friday
    )


def test_base_end_date_is_latest_bar_without_close_breakout():
    bars = _bars()[:3]

    breakout = VCPBreakoutEvent(
        has_confirmed_pivot=True,
        pivot_price=100.0,
        structure_ready_date=bars[0].date,
        first_intraday_breach_date=None,
        first_close_break_date=None,
        pivot_broken_by_close=False,
        breakout_close_pct_above_pivot=None,
        breakout_volume_ratio_20=None,
        current_close_above_pivot=False,
    )

    assert (
        _resolve_base_end_date(
            bars,
            breakout,
        )
        == bars[-1].date
    )
