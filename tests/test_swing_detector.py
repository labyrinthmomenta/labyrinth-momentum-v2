from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from src.strategy.swing_detector import (
    SwingBar,
    SwingDetectorConfig,
    detect_swings,
)


CONFIG = SwingDetectorConfig(
    reversal_multiplier=1.50,
    absolute_floor_pct=1.50,
    min_leg_sessions=2,
)


def _bars(
    rows: list[tuple[float, float, float]],
    *,
    atr_pct: float = 2.0,
    start: date = date(2026, 1, 2),
) -> list[SwingBar]:
    """Build deterministic synthetic daily bars.

    rows = [(high, low, close), ...]
    """
    return [
        SwingBar(
            date=start + timedelta(days=i),
            high=high,
            low=low,
            close=close,
            atr_pct=atr_pct,
        )
        for i, (high, low, close) in enumerate(rows)
    ]


def _normal_3t_series() -> list[SwingBar]:
    """Synthetic 3-contraction VCP-like geometry.

    Expected confirmed extremes:

        H1 = 110
        L1 =  90     T1 = 18.18%

        H2 = 106
        L2 =  96     T2 =  9.43%

        H3 = 104
        L3 =  99     T3 =  4.81%

    ATR% is fixed at 2%, therefore the reversal threshold is:

        max(1.5%, 1.5 * 2%) = 3%
    """
    return _bars(
        [
            (101.0, 99.0, 100.0),    # d00
            (106.0, 104.0, 105.0),   # d01
            (110.0, 108.0, 109.5),   # d02 H1 extreme
            (109.0, 107.0, 108.0),   # d03
            (104.0, 102.0, 103.0),   # d04 H1 confirmed

            (96.0, 94.0, 95.0),      # d05
            (91.0, 90.0, 90.5),      # d06 L1 extreme
            (93.0, 91.0, 92.0),      # d07
            (95.0, 93.0, 94.0),      # d08 L1 confirmed

            (102.0, 100.0, 101.0),   # d09
            (106.0, 104.0, 105.5),   # d10 H2 extreme
            (105.0, 103.0, 104.0),   # d11
            (103.0, 101.0, 102.0),   # d12 H2 confirmed

            (99.0, 97.0, 98.0),      # d13
            (97.0, 96.0, 96.5),      # d14 L2 extreme
            (99.0, 97.0, 98.0),      # d15
            (101.0, 99.0, 100.0),    # d16 L2 confirmed

            (103.0, 101.0, 102.0),   # d17
            (104.0, 102.0, 103.5),   # d18 H3 extreme
            (103.0, 101.0, 102.0),   # d19
            (101.0, 99.5, 100.0),    # d20 H3 confirmed

            (100.0, 99.0, 99.5),     # d21 L3 extreme
            (101.5, 99.5, 100.5),    # d22 - not confirmed yet
            (103.0, 101.5, 102.5),   # d23 L3 confirmed
        ]
    )


def _contraction_depth(high: float, low: float) -> float:
    return 100.0 * (high - low) / high


def _confirmed_contraction_count(pivots) -> int:
    return sum(
        1
        for left, right in zip(pivots, pivots[1:])
        if left.kind == "HIGH" and right.kind == "LOW"
    )


def test_detects_three_successively_smaller_confirmed_contractions():
    bars = _normal_3t_series()

    result = detect_swings(bars, CONFIG)

    pivots = result.confirmed[-6:]

    assert [p.kind for p in pivots] == [
        "HIGH",
        "LOW",
        "HIGH",
        "LOW",
        "HIGH",
        "LOW",
    ]

    expected_extreme_days = [
        bars[2].date,
        bars[6].date,
        bars[10].date,
        bars[14].date,
        bars[18].date,
        bars[21].date,
    ]

    assert [p.extreme_date for p in pivots] == expected_extreme_days

    depths = [
        _contraction_depth(pivots[0].price, pivots[1].price),
        _contraction_depth(pivots[2].price, pivots[3].price),
        _contraction_depth(pivots[4].price, pivots[5].price),
    ]

    assert depths[0] == pytest.approx(18.1818, rel=1e-4)
    assert depths[1] == pytest.approx(9.4340, rel=1e-4)
    assert depths[2] == pytest.approx(4.8077, rel=1e-4)

    assert depths[0] > depths[1] > depths[2]
    assert _confirmed_contraction_count(result.confirmed) >= 3


def test_high_volatility_noise_does_not_create_false_swings():
    # ATR%=6 -> threshold=max(1.5%, 9%) = 9%.
    # All movements stay below a meaningful reversal threshold.
    closes = [
        100.0,
        104.0,
        101.0,
        105.0,
        102.0,
        106.0,
        103.0,
        107.0,
        104.0,
        106.0,
        103.0,
        105.0,
    ]

    bars = _bars(
        [
            (close + 0.5, close - 0.5, close)
            for close in closes
        ],
        atr_pct=6.0,
    )

    result = detect_swings(bars, CONFIG)

    assert result.confirmed == ()


def test_final_low_remains_provisional_until_close_confirms_reversal():
    # Stop before d23, so L3 has formed intraday but has not yet
    # received the required closing-price rebound confirmation.
    bars = _normal_3t_series()[:23]

    result = detect_swings(bars, CONFIG)

    assert _confirmed_contraction_count(result.confirmed) == 2

    assert result.confirmed[-1].kind == "HIGH"
    assert result.confirmed[-1].extreme_date == bars[18].date

    assert result.provisional is not None
    assert result.provisional.kind == "LOW"
    assert result.provisional.extreme_date == bars[21].date
    assert result.provisional.confirmation_date is None


def test_intraday_wick_alone_does_not_confirm_reversal():
    # ATR%=2 -> 3% close-based reversal required.
    #
    # Candidate high = 110.
    # 3% confirmation level = 106.70.
    #
    # d03 trades as low as 100 intraday, but closes at 108.5.
    # Therefore the HIGH must remain unconfirmed.
    bars = _bars(
        [
            (101.0, 99.0, 100.0),
            (106.0, 104.0, 105.0),
            (110.0, 108.0, 109.5),
            (109.0, 100.0, 108.5),
            (109.0, 106.5, 108.0),
        ],
        atr_pct=2.0,
    )

    result = detect_swings(bars, CONFIG)

    confirmed_highs = [
        pivot
        for pivot in result.confirmed
        if pivot.kind == "HIGH"
    ]

    assert confirmed_highs == []

    assert result.provisional is not None
    assert result.provisional.kind == "HIGH"
    assert result.provisional.extreme_date == bars[2].date


def test_uniform_price_rescaling_preserves_swing_geometry():
    """Corporate-action-safe adjusted prices must preserve geometry.

    A uniform price-scale change must not change pivot dates or
    confirmation dates because the detector works with percentages
    and ATR%.
    """
    original = _normal_3t_series()

    scaled = [
        replace(
            bar,
            high=bar.high * 10.0,
            low=bar.low * 10.0,
            close=bar.close * 10.0,
        )
        for bar in original
    ]

    original_result = detect_swings(original, CONFIG)
    scaled_result = detect_swings(scaled, CONFIG)

    original_geometry = [
        (
            pivot.kind,
            pivot.extreme_date,
            pivot.confirmation_date,
        )
        for pivot in original_result.confirmed
    ]

    scaled_geometry = [
        (
            pivot.kind,
            pivot.extreme_date,
            pivot.confirmation_date,
        )
        for pivot in scaled_result.confirmed
    ]

    assert scaled_geometry == original_geometry


def test_confirmation_date_is_never_before_extreme_date():
    result = detect_swings(_normal_3t_series(), CONFIG)

    assert result.confirmed

    for pivot in result.confirmed:
        assert pivot.confirmation_date is not None
        assert pivot.confirmation_date >= pivot.extreme_date


def test_confirmed_history_does_not_repaint_when_future_bars_arrive():
    bars = _normal_3t_series()

    # d20 has already confirmed H3.
    prefix_result = detect_swings(
        bars[:21],
        CONFIG,
    )

    full_result = detect_swings(
        bars,
        CONFIG,
    )

    assert prefix_result.confirmed

    prefix_count = len(prefix_result.confirmed)

    assert (
        full_result.confirmed[:prefix_count]
        == prefix_result.confirmed
    )


def test_empty_and_single_bar_inputs_do_not_invent_pivots():
    empty = detect_swings([], CONFIG)

    assert empty.confirmed == ()
    assert empty.provisional is None

    single = detect_swings(
        _bars(
            [(101.0, 99.0, 100.0)],
            atr_pct=2.0,
        ),
        CONFIG,
    )

    assert single.confirmed == ()
    assert single.provisional is None


def test_detector_can_begin_with_a_downward_leg():
    bars = _bars(
        [
            (101.0, 99.0, 100.0),
            (98.0, 95.0, 96.0),
            (97.0, 94.0, 95.0),   # LOW candidate
            (98.0, 96.0, 97.0),   # close confirms rebound
        ],
        atr_pct=2.0,
    )

    result = detect_swings(bars, CONFIG)

    assert len(result.confirmed) == 1

    pivot = result.confirmed[0]

    assert pivot.kind == "LOW"
    assert pivot.price == pytest.approx(94.0)
    assert pivot.extreme_date == bars[2].date
    assert pivot.confirmation_date == bars[3].date


def test_reversal_threshold_is_frozen_at_extreme_date():
    # Candidate HIGH forms while ATR%=2:
    #
    # threshold = max(1.5%, 1.5 * 2%) = 3%
    #
    # ATR then jumps to 10%, but the already formed HIGH must
    # continue using its original 3% threshold.
    bars = _bars(
        [
            (101.0, 99.0, 100.0),
            (106.0, 104.0, 105.0),
            (110.0, 108.0, 109.0),   # HIGH, ATR%=2
            (109.0, 106.0, 106.5),   # ATR jumps here
        ],
        atr_pct=2.0,
    )

    bars[-1] = replace(
        bars[-1],
        atr_pct=10.0,
    )

    result = detect_swings(bars, CONFIG)

    assert len(result.confirmed) == 1

    pivot = result.confirmed[0]

    assert pivot.kind == "HIGH"
    assert pivot.price == pytest.approx(110.0)
    assert pivot.extreme_date == bars[2].date
    assert pivot.confirmation_date == bars[3].date
    assert pivot.threshold_pct == pytest.approx(3.0)


def test_minimum_leg_length_prevents_too_close_opposite_pivot():
    config = SwingDetectorConfig(
        reversal_multiplier=1.50,
        absolute_floor_pct=1.50,
        min_leg_sessions=3,
    )

    bars = _bars(
        [
            (101.0, 99.0, 100.0),
            (106.0, 104.0, 105.0),
            (110.0, 108.0, 109.0),   # HIGH extreme
            (108.0, 105.0, 106.0),   # HIGH confirmed

            (101.0, 100.0, 100.5),   # LOW candidate, too close
            (105.0, 100.0, 104.0),   # reversal, but leg too short

            (100.0, 98.0, 99.0),     # later/lower LOW candidate
            (103.0, 101.0, 102.0),   # now valid confirmation
        ],
        atr_pct=2.0,
    )

    result = detect_swings(bars, config)

    assert [p.kind for p in result.confirmed] == [
        "HIGH",
        "LOW",
    ]

    low = result.confirmed[1]

    assert low.price == pytest.approx(98.0)
    assert low.extreme_date == bars[6].date
    assert low.confirmation_date == bars[7].date


def test_duplicate_or_non_increasing_dates_are_rejected():
    bars = _bars(
        [
            (101.0, 99.0, 100.0),
            (102.0, 100.0, 101.0),
        ]
    )

    bars[1] = replace(
        bars[1],
        date=bars[0].date,
    )

    with pytest.raises(
        ValueError,
        match="strictly increasing",
    ):
        detect_swings(bars, CONFIG)


def test_invalid_ohlc_is_rejected():
    bars = _bars(
        [
            (101.0, 99.0, 100.0),
            # Close is outside the daily high-low range.
            (102.0, 100.0, 103.0),
        ]
    )

    with pytest.raises(
        ValueError,
        match="close must lie within",
    ):
        detect_swings(bars, CONFIG)
