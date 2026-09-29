from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.strategy.swing_detector import SwingPivot
from src.strategy.vcp_breakout import VCPBreakoutEvent
from src.strategy.vcp_features import VCPFeatures
from src.strategy.vcp_geometry import analyze_vcp_geometry
from src.strategy.vcp_state import (
    VCPState,
    VCPStateConfig,
    classify_vcp_state,
)


BASE_DATE = date(2026, 1, 1)


def _date(index: int) -> date:
    return BASE_DATE + timedelta(days=index - 1)


def _pivot(
    kind: str,
    price: float,
    extreme_index: int,
    confirmation_index: int,
) -> SwingPivot:
    return SwingPivot(
        kind=kind,
        price=price,
        extreme_date=_date(extreme_index),
        confirmation_date=_date(confirmation_index),
        threshold_pct=2.0,
    )


def _config() -> VCPStateConfig:
    # These are explicit research parameters for the state layer,
    # not claims that the thresholds are universally optimal.
    return VCPStateConfig(
        tightening_range_5_max_pct=5.0,
        tightening_true_range_compression_max=0.75,
        tightening_final_volume_ratio_max=0.75,
        near_pivot_max_distance_pct=5.0,
        breakout_volume_expansion_min_ratio=1.50,
    )


def _features(
    *,
    range_5_pct: float | None = 8.0,
    true_range_compression: float | None = 1.0,
    final_volume_ratio: float | None = 1.0,
    distance_to_pivot_pct: float | None = -10.0,
) -> VCPFeatures:
    return VCPFeatures(
        as_of=_date(40),
        observations=40,

        range_5_pct=range_5_pct,
        range_10_pct=10.0,

        true_range_compression_10_40=(
            true_range_compression
        ),

        final_contraction_volume_ratio_50=(
            final_volume_ratio
        ),

        distance_to_pivot_pct=(
            distance_to_pivot_pct
        ),

        distance_to_pivot_atr=None,

        has_provisional_swing=False,
        provisional_kind=None,
        provisional_distance_to_pivot_pct=None,
    )


def _no_breakout(
    *,
    pivot_price: float | None,
) -> VCPBreakoutEvent:
    return VCPBreakoutEvent(
        has_confirmed_pivot=(
            pivot_price is not None
        ),
        pivot_price=pivot_price,
        structure_ready_date=(
            _date(30)
            if pivot_price is not None
            else None
        ),

        first_intraday_breach_date=None,
        first_close_break_date=None,

        pivot_broken_by_close=False,

        breakout_close_pct_above_pivot=None,
        breakout_volume_ratio_20=None,

        current_close_above_pivot=(
            False
            if pivot_price is not None
            else None
        ),
    )


def _breakout(
    *,
    pivot_price: float,
    volume_ratio: float | None,
) -> VCPBreakoutEvent:
    return VCPBreakoutEvent(
        has_confirmed_pivot=True,
        pivot_price=pivot_price,
        structure_ready_date=_date(30),

        first_intraday_breach_date=_date(35),
        first_close_break_date=_date(35),

        pivot_broken_by_close=True,

        breakout_close_pct_above_pivot=1.0,
        breakout_volume_ratio_20=volume_ratio,

        current_close_above_pivot=True,
    )


def _one_contraction():
    return analyze_vcp_geometry(
        [
            _pivot(
                "HIGH",
                110.0,
                10,
                12,
            ),
            _pivot(
                "LOW",
                99.0,
                15,
                17,
            ),
        ]
    )


def _candidate_geometry():
    # T1 = 10%
    # T2 ~= 11.11%
    #
    # Two confirmed contractions exist, but depths are
    # not successively decreasing.
    return analyze_vcp_geometry(
        [
            _pivot(
                "HIGH",
                110.0,
                10,
                12,
            ),
            _pivot(
                "LOW",
                99.0,
                15,
                17,
            ),
            _pivot(
                "HIGH",
                108.0,
                20,
                22,
            ),
            _pivot(
                "LOW",
                96.0,
                25,
                27,
            ),
        ]
    )


def _contracting_geometry():
    # T1 = 10%
    # T2 ~= 5.56%
    return analyze_vcp_geometry(
        [
            _pivot(
                "HIGH",
                110.0,
                10,
                12,
            ),
            _pivot(
                "LOW",
                99.0,
                15,
                17,
            ),
            _pivot(
                "HIGH",
                108.0,
                20,
                22,
            ),
            _pivot(
                "LOW",
                102.0,
                25,
                27,
            ),
        ]
    )


def test_no_confirmed_contractions_is_no_structure():
    geometry = analyze_vcp_geometry([])

    result = classify_vcp_state(
        geometry,
        _features(
            distance_to_pivot_pct=None,
        ),
        _no_breakout(
            pivot_price=None,
        ),
        config=_config(),
    )

    assert result.state is VCPState.NO_STRUCTURE


def test_one_confirmed_contraction_is_base_forming():
    geometry = _one_contraction()

    result = classify_vcp_state(
        geometry,
        _features(),
        _no_breakout(
            pivot_price=geometry.pivot.price,
        ),
        config=_config(),
    )

    assert result.state is VCPState.BASE_FORMING


def test_two_contractions_without_decreasing_depths_is_candidate():
    geometry = _candidate_geometry()

    assert (
        geometry.confirmed_contraction_count
        == 2
    )
    assert (
        geometry.depths_strictly_decreasing
        is False
    )

    result = classify_vcp_state(
        geometry,
        _features(),
        _no_breakout(
            pivot_price=geometry.pivot.price,
        ),
        config=_config(),
    )

    assert result.state is VCPState.VCP_CANDIDATE


def test_decreasing_contractions_are_contracting():
    geometry = _contracting_geometry()

    result = classify_vcp_state(
        geometry,
        _features(
            range_5_pct=7.0,
            true_range_compression=0.90,
            final_volume_ratio=0.90,
            distance_to_pivot_pct=-10.0,
        ),
        _no_breakout(
            pivot_price=geometry.pivot.price,
        ),
        config=_config(),
    )

    assert result.state is VCPState.VCP_CONTRACTING


def test_all_configured_tightening_conditions_are_required():
    geometry = _contracting_geometry()

    result = classify_vcp_state(
        geometry,
        _features(
            range_5_pct=4.0,
            true_range_compression=0.70,
            final_volume_ratio=0.60,
            distance_to_pivot_pct=-8.0,
        ),
        _no_breakout(
            pivot_price=geometry.pivot.price,
        ),
        config=_config(),
    )

    assert result.state is VCPState.VCP_TIGHTENING


def test_missing_tightening_metric_fails_closed_to_contracting():
    geometry = _contracting_geometry()

    result = classify_vcp_state(
        geometry,
        _features(
            range_5_pct=4.0,
            true_range_compression=None,
            final_volume_ratio=0.60,
            distance_to_pivot_pct=-8.0,
        ),
        _no_breakout(
            pivot_price=geometry.pivot.price,
        ),
        config=_config(),
    )

    assert result.state is VCPState.VCP_CONTRACTING


def test_tightening_structure_within_near_pivot_distance_is_near_pivot():
    geometry = _contracting_geometry()

    result = classify_vcp_state(
        geometry,
        _features(
            range_5_pct=4.0,
            true_range_compression=0.70,
            final_volume_ratio=0.60,
            distance_to_pivot_pct=-3.0,
        ),
        _no_breakout(
            pivot_price=geometry.pivot.price,
        ),
        config=_config(),
    )

    assert result.state is VCPState.NEAR_PIVOT


def test_positive_distance_without_breakout_is_not_near_pivot():
    geometry = _contracting_geometry()

    result = classify_vcp_state(
        geometry,
        _features(
            range_5_pct=4.0,
            true_range_compression=0.70,
            final_volume_ratio=0.60,
            distance_to_pivot_pct=1.0,
        ),
        _no_breakout(
            pivot_price=geometry.pivot.price,
        ),
        config=_config(),
    )

    # "Near pivot" is deliberately defined from below.
    assert result.state is VCPState.VCP_TIGHTENING


def test_close_confirmed_breakout_overrides_pre_breakout_states():
    geometry = _contracting_geometry()

    result = classify_vcp_state(
        geometry,
        _features(
            range_5_pct=4.0,
            true_range_compression=0.70,
            final_volume_ratio=0.60,
            distance_to_pivot_pct=2.0,
        ),
        _breakout(
            pivot_price=geometry.pivot.price,
            volume_ratio=1.20,
        ),
        config=_config(),
    )

    assert result.state is VCPState.PIVOT_BROKEN


def test_breakout_volume_expansion_is_separate_state():
    geometry = _contracting_geometry()

    result = classify_vcp_state(
        geometry,
        _features(
            range_5_pct=4.0,
            true_range_compression=0.70,
            final_volume_ratio=0.60,
            distance_to_pivot_pct=2.0,
        ),
        _breakout(
            pivot_price=geometry.pivot.price,
            volume_ratio=1.80,
        ),
        config=_config(),
    )

    assert (
        result.state
        is VCPState.PIVOT_BROKEN_VOLUME_EXPANSION
    )


def test_missing_breakout_volume_does_not_invent_volume_expansion():
    geometry = _contracting_geometry()

    result = classify_vcp_state(
        geometry,
        _features(
            range_5_pct=4.0,
            true_range_compression=0.70,
            final_volume_ratio=0.60,
            distance_to_pivot_pct=2.0,
        ),
        _breakout(
            pivot_price=geometry.pivot.price,
            volume_ratio=None,
        ),
        config=_config(),
    )

    assert result.state is VCPState.PIVOT_BROKEN


def test_threshold_boundaries_are_inclusive():
    geometry = _contracting_geometry()

    result = classify_vcp_state(
        geometry,
        _features(
            range_5_pct=5.0,
            true_range_compression=0.75,
            final_volume_ratio=0.75,
            distance_to_pivot_pct=-5.0,
        ),
        _no_breakout(
            pivot_price=geometry.pivot.price,
        ),
        config=_config(),
    )

    assert result.state is VCPState.NEAR_PIVOT


def test_invalid_config_fails_closed():
    with pytest.raises(
        ValueError,
        match="near_pivot_max_distance_pct",
    ):
        VCPStateConfig(
            tightening_range_5_max_pct=5.0,
            tightening_true_range_compression_max=0.75,
            tightening_final_volume_ratio_max=0.75,
            near_pivot_max_distance_pct=-1.0,
            breakout_volume_expansion_min_ratio=1.50,
        )
