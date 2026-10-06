from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.strategy.swing_detector import SwingPivot
from src.strategy.vcp_features import VCPFeatures
from src.strategy.vcp_geometry import analyze_vcp_geometry
from src.strategy.vcp_validity import assess_vcp_validity


BASE_DATE = date(2026, 1, 1)


def _pivot(
    kind: str,
    price: float,
    day: int,
) -> SwingPivot:
    extreme_date = BASE_DATE + timedelta(days=day)

    return SwingPivot(
        kind=kind,
        price=price,
        extreme_date=extreme_date,
        confirmation_date=(
            extreme_date + timedelta(days=1)
        ),
        threshold_pct=3.0,
    )


def _geometry_from_depths(
    depths: list[float],
):
    pivots = []

    for index, depth_pct in enumerate(depths):
        # Keep successive HIGHs below the active-base anchor so
        # geometry remains one rightmost active structure.
        high = 100.0 - index

        low = high * (
            1.0 - depth_pct / 100.0
        )

        day = index * 6

        pivots.extend(
            [
                _pivot(
                    "HIGH",
                    high,
                    day,
                ),
                _pivot(
                    "LOW",
                    low,
                    day + 3,
                ),
            ]
        )

    return analyze_vcp_geometry(
        pivots
    )


def _features(
    *,
    true_range_compression: float | None,
    final_volume_ratio: float | None,
) -> VCPFeatures:
    return VCPFeatures(
        as_of=date(2026, 10, 2),
        observations=200,

        range_5_pct=4.0,
        range_10_pct=7.0,

        true_range_compression_10_40=(
            true_range_compression
        ),

        final_contraction_volume_ratio_50=(
            final_volume_ratio
        ),

        distance_to_pivot_pct=-3.0,
        distance_to_pivot_atr=-1.0,

        has_provisional_swing=False,
        provisional_kind=None,
        provisional_distance_to_pivot_pct=None,
    )


def test_agesa_style_structure_is_structurally_valid():
    geometry = _geometry_from_depths(
        [15.28, 7.97]
    )

    result = assess_vcp_validity(
        geometry,
        _features(
            true_range_compression=0.75,
            final_volume_ratio=0.70,
        ),
    )

    assert result.contraction_count_valid is True
    assert result.overall_volatility_contracting is True
    assert result.final_is_tightest is True
    assert result.right_side_tightness_present is True
    assert result.final_volume_below_50d is True

    assert result.structurally_valid is True
    assert result.failure_reasons == ()


def test_akfis_style_reexpansion_is_structurally_invalid():
    geometry = _geometry_from_depths(
        [17.93, 32.62, 22.05]
    )

    result = assess_vcp_validity(
        geometry,
        _features(
            true_range_compression=1.01,
            final_volume_ratio=0.89,
        ),
    )

    assert result.contraction_count_valid is True

    # Final T is larger than the first T and is not the
    # tightest contraction on the right.
    assert result.overall_volatility_contracting is False
    assert result.final_is_tightest is False

    assert result.structurally_valid is False

    assert result.failure_reasons == (
        "VOLATILITY_NOT_CONTRACTING",
    )



def test_reasonable_middle_reexpansion_can_still_be_valid():
    geometry = _geometry_from_depths(
        [20.0, 14.0, 16.0, 8.0]
    )

    result = assess_vcp_validity(
        geometry,
        _features(
            true_range_compression=0.80,
            final_volume_ratio=0.75,
        ),
    )

    # We deliberately do NOT require every single contraction
    # to be strictly smaller than the one before it.
    assert geometry.depths_strictly_decreasing is False

    assert result.overall_volatility_contracting is True
    assert result.final_is_tightest is True
    assert result.structurally_valid is True


@pytest.mark.parametrize(
    "depths",
    [
        [10.0],
        [
            25.0,
            20.0,
            17.0,
            14.0,
            11.0,
            8.0,
            5.0,
        ],
    ],
)
def test_contraction_count_outside_two_to_six_is_invalid(
    depths,
):
    geometry = _geometry_from_depths(
        depths
    )

    result = assess_vcp_validity(
        geometry,
        _features(
            true_range_compression=0.70,
            final_volume_ratio=0.70,
        ),
    )

    assert result.contraction_count_valid is False
    assert result.structurally_valid is False

    assert (
        "CONTRACTION_COUNT_OUT_OF_BOUNDS"
        in result.failure_reasons
    )


@pytest.mark.parametrize(
    (
        "true_range_compression",
        "final_volume_ratio",
    ),
    [
        (
            None,
            0.70,
        ),
        (
            0.70,
            None,
        ),
        (
            None,
            None,
        ),
    ],
)
def test_missing_quality_evidence_does_not_invalidate_structure(
    true_range_compression,
    final_volume_ratio,
):
    geometry = _geometry_from_depths(
        [15.0, 8.0]
    )

    result = assess_vcp_validity(
        geometry,
        _features(
            true_range_compression=(
                true_range_compression
            ),
            final_volume_ratio=(
                final_volume_ratio
            ),
        ),
    )

    # Structural validity depends only on the developed
    # contraction geometry, not on optional readiness /
    # supply-quality evidence.
    assert result.contraction_count_valid is True
    assert result.overall_volatility_contracting is True
    assert result.structurally_valid is True

    # Missing quality evidence remains visible through the
    # diagnostic fields, but is not a structural failure.
    if true_range_compression is None:
        assert result.right_side_tightness_present is False

    if final_volume_ratio is None:
        assert result.final_volume_below_50d is False

    assert result.failure_reasons == ()


@pytest.mark.parametrize(
    (
        "true_range_compression",
        "final_volume_ratio",
        "expected_tightness",
        "expected_volume",
    ),
    [
        (
            1.20,
            0.70,
            False,
            True,
        ),
        (
            0.70,
            1.20,
            True,
            False,
        ),
        (
            1.20,
            1.20,
            False,
            False,
        ),
    ],
)
def test_unfavourable_quality_evidence_does_not_invalidate_structure(
    true_range_compression,
    final_volume_ratio,
    expected_tightness,
    expected_volume,
):
    geometry = _geometry_from_depths(
        [20.0, 14.0, 16.0, 8.0]
    )

    result = assess_vcp_validity(
        geometry,
        _features(
            true_range_compression=(
                true_range_compression
            ),
            final_volume_ratio=(
                final_volume_ratio
            ),
        ),
    )

    assert geometry.depths_strictly_decreasing is False

    assert result.contraction_count_valid is True
    assert result.overall_volatility_contracting is True

    # These remain useful quality/readiness diagnostics.
    assert (
        result.right_side_tightness_present
        is expected_tightness
    )
    assert (
        result.final_volume_below_50d
        is expected_volume
    )

    # But neither is a hard structural-validity gate.
    assert result.structurally_valid is True
    assert result.failure_reasons == ()


def test_small_final_reexpansion_is_not_a_hard_rejection():
    geometry = _geometry_from_depths(
        [29.01, 19.93, 11.19, 11.90]
    )

    result = assess_vcp_validity(
        geometry,
        _features(
            true_range_compression=0.80,
            final_volume_ratio=0.75,
        ),
    )

    assert result.contraction_count_valid is True
    assert result.overall_volatility_contracting is True

    # The final T is slightly larger than the preceding minimum.
    # This remains useful quality information, but should not by
    # itself invalidate an otherwise contracting VCP structure.
    assert result.final_is_tightest is False

    assert result.right_side_tightness_present is True
    assert result.final_volume_below_50d is True

    assert result.structurally_valid is True

    assert (
        "FINAL_CONTRACTION_NOT_TIGHTEST"
        not in result.failure_reasons
    )
