from dataclasses import replace
from datetime import date

import pytest

from src.research.vcp_dataset import (
    VCPResearchObservation,
)
from src.research.vcp_relative import (
    VCPRelativeObservation,
)
from src.research.vcp_cross_sectional import (
    VCPCrossSectionalDataset,
    VCPCrossSectionalObservation,
    build_cross_sectional_features,
)


DAY_1 = date(2026, 6, 30)
DAY_2 = date(2026, 7, 31)


def _research_observation(
    *,
    as_of: date,
    security_id: int,
    ticker: str,
    base_depth: float | None,
    pivot_distance: float | None,
    base_atr: float | None = 0.80,
    base_volume: float | None = 0.75,
    final_first: float | None = 0.60,
) -> VCPResearchObservation:
    return VCPResearchObservation(
        as_of=as_of,
        security_id=security_id,
        ticker=ticker,
        history_sessions=120,
        vcp_state="VCP_CONTRACTING",
        contraction_count=3,
        structurally_valid=True,
        contraction_depths=(18.0, 12.0, 7.0),
        final_to_first_depth_ratio=final_first,
        decreasing_step_fraction=1.0,
        range_5_pct=4.5,
        current_tr_compression_10_40=0.82,
        final_contraction_volume_ratio_50=0.71,
        base_duration_sessions=42,
        base_depth_pct=base_depth,
        base_atr_compression_ratio=base_atr,
        base_volume_dryup_ratio=base_volume,
        pivot_price=120.0,
        distance_to_pivot_pct=pivot_distance,
        distance_to_pivot_atr=-0.8,
        first_intraday_breach_date=None,
        first_close_break_date=None,
        pivot_broken_by_close=False,
        breakout_volume_ratio_20=None,
        outcome_available=True,
        outcome_error=None,
        reference_close=117.0,
        forward_return_5=0.01,
        forward_return_10=0.02,
        forward_return_20=0.03,
        forward_return_40=0.04,
        mfe_40=0.10,
        mae_40=-0.05,
    )


def _relative(
    observation: VCPResearchObservation,
) -> VCPRelativeObservation:
    return VCPRelativeObservation(
        observation=observation,
        benchmark_return_5=0.0,
        benchmark_return_10=0.0,
        benchmark_return_20=0.0,
        benchmark_return_40=0.0,
        relative_return_5=observation.forward_return_5,
        relative_return_10=observation.forward_return_10,
        relative_return_20=observation.forward_return_20,
        relative_return_40=observation.forward_return_40,
    )


def test_cross_sectional_percentiles_are_computed_within_same_date():
    observations = (
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=1,
                ticker="AAA",
                base_depth=20.0,
                pivot_distance=-20.0,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=2,
                ticker="BBB",
                base_depth=30.0,
                pivot_distance=-10.0,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=3,
                ticker="CCC",
                base_depth=40.0,
                pivot_distance=-5.0,
            )
        ),

        # Very different raw scale on another date.
        _relative(
            _research_observation(
                as_of=DAY_2,
                security_id=1,
                ticker="AAA",
                base_depth=100.0,
                pivot_distance=-50.0,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_2,
                security_id=2,
                ticker="BBB",
                base_depth=200.0,
                pivot_distance=-25.0,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_2,
                security_id=3,
                ticker="CCC",
                base_depth=300.0,
                pivot_distance=-1.0,
            )
        ),
    )

    result = build_cross_sectional_features(
        observations
    )

    assert isinstance(
        result,
        VCPCrossSectionalDataset,
    )

    assert len(result.observations) == 6

    day_1 = result.observations[:3]
    day_2 = result.observations[3:]

    for group in (day_1, day_2):
        assert group[0].base_depth_percentile == pytest.approx(0.0)
        assert group[1].base_depth_percentile == pytest.approx(0.5)
        assert group[2].base_depth_percentile == pytest.approx(1.0)

        # -20 < -10 < -5, therefore closer-to-zero gets higher rank.
        assert group[0].distance_to_pivot_percentile == pytest.approx(0.0)
        assert group[1].distance_to_pivot_percentile == pytest.approx(0.5)
        assert group[2].distance_to_pivot_percentile == pytest.approx(1.0)


def test_cross_sectional_percentiles_use_average_rank_for_ties():
    observations = (
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=1,
                ticker="AAA",
                base_depth=20.0,
                pivot_distance=-10.0,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=2,
                ticker="BBB",
                base_depth=20.0,
                pivot_distance=-10.0,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=3,
                ticker="CCC",
                base_depth=40.0,
                pivot_distance=-5.0,
            )
        ),
    )

    result = build_cross_sectional_features(
        observations
    )

    aaa, bbb, ccc = result.observations

    # Positions 0 and 1 are tied.
    # Average rank = 0.5.
    # Normalized by n-1 = 2 => 0.25.
    assert aaa.base_depth_percentile == pytest.approx(0.25)
    assert bbb.base_depth_percentile == pytest.approx(0.25)
    assert ccc.base_depth_percentile == pytest.approx(1.0)

    assert aaa.distance_to_pivot_percentile == pytest.approx(0.25)
    assert bbb.distance_to_pivot_percentile == pytest.approx(0.25)
    assert ccc.distance_to_pivot_percentile == pytest.approx(1.0)


def test_missing_feature_does_not_enter_cross_sectional_denominator():
    observations = (
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=1,
                ticker="AAA",
                base_depth=20.0,
                pivot_distance=-20.0,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=2,
                ticker="BBB",
                base_depth=None,
                pivot_distance=None,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=3,
                ticker="CCC",
                base_depth=40.0,
                pivot_distance=-5.0,
            )
        ),
    )

    result = build_cross_sectional_features(
        observations
    )

    aaa, missing, ccc = result.observations

    # Only AAA and CCC participate:
    # lowest -> 0.0, highest -> 1.0.
    assert aaa.base_depth_percentile == pytest.approx(0.0)
    assert ccc.base_depth_percentile == pytest.approx(1.0)

    assert missing.base_depth_percentile is None
    assert missing.distance_to_pivot_percentile is None


def test_single_available_value_receives_neutral_percentile():
    observations = (
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=1,
                ticker="ONLY",
                base_depth=25.0,
                pivot_distance=-7.0,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=2,
                ticker="MISSING",
                base_depth=None,
                pivot_distance=None,
            )
        ),
    )

    result = build_cross_sectional_features(
        observations
    )

    only, missing = result.observations

    assert only.base_depth_percentile == pytest.approx(0.5)
    assert only.distance_to_pivot_percentile == pytest.approx(0.5)

    assert missing.base_depth_percentile is None
    assert missing.distance_to_pivot_percentile is None


def test_cross_sectional_layer_preserves_input_order_and_identity():
    observations = (
        _relative(
            _research_observation(
                as_of=DAY_2,
                security_id=30,
                ticker="THIRD",
                base_depth=30.0,
                pivot_distance=-3.0,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=10,
                ticker="FIRST",
                base_depth=10.0,
                pivot_distance=-10.0,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=20,
                ticker="SECOND",
                base_depth=20.0,
                pivot_distance=-5.0,
            )
        ),
    )

    result = build_cross_sectional_features(
        observations
    )

    assert tuple(
        item.relative_observation.observation.ticker
        for item in result.observations
    ) == (
        "THIRD",
        "FIRST",
        "SECOND",
    )

    for enriched, original in zip(
        result.observations,
        observations,
    ):
        assert enriched.relative_observation is original


def test_all_equal_feature_values_receive_neutral_percentile():
    observations = (
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=1,
                ticker="AAA",
                base_depth=25.0,
                pivot_distance=-15.0,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=2,
                ticker="BBB",
                base_depth=25.0,
                pivot_distance=-10.0,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=3,
                ticker="CCC",
                base_depth=25.0,
                pivot_distance=-5.0,
            )
        ),
    )

    result = build_cross_sectional_features(
        observations
    )

    assert all(
        item.base_depth_percentile == pytest.approx(0.5)
        for item in result.observations
    )


def test_missing_value_in_one_feature_does_not_change_other_feature_denominator():
    observations = (
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=1,
                ticker="AAA",
                base_depth=10.0,
                pivot_distance=-15.0,
                base_volume=0.50,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=2,
                ticker="BBB",
                base_depth=20.0,
                pivot_distance=-10.0,
                base_volume=None,
            )
        ),
        _relative(
            _research_observation(
                as_of=DAY_1,
                security_id=3,
                ticker="CCC",
                base_depth=30.0,
                pivot_distance=-5.0,
                base_volume=1.50,
            )
        ),
    )

    result = build_cross_sectional_features(
        observations
    )

    aaa, bbb, ccc = result.observations

    # Base depth still uses all three observations.
    assert aaa.base_depth_percentile == pytest.approx(0.0)
    assert bbb.base_depth_percentile == pytest.approx(0.5)
    assert ccc.base_depth_percentile == pytest.approx(1.0)

    # Volume ranking uses only the two available values.
    assert aaa.base_volume_dryup_percentile == pytest.approx(0.0)
    assert bbb.base_volume_dryup_percentile is None
    assert ccc.base_volume_dryup_percentile == pytest.approx(1.0)
