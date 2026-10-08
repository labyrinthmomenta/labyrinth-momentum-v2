from types import SimpleNamespace

import pytest

from src.research.vcp_quality import (
    ATR_VOL_EQ_ATR_WEIGHT,
    ATR_VOL_EQ_VOLUME_WEIGHT,
    VCP_QUALITY_MIN_HISTORY_SESSIONS,
    build_vcp_quality_scores,
    compute_atr_vol_eq_score,
    is_frozen_vcp_quality_cohort_member,
)


def test_frozen_quality_methodology_constants():
    assert ATR_VOL_EQ_ATR_WEIGHT == 0.50
    assert ATR_VOL_EQ_VOLUME_WEIGHT == 0.50
    assert VCP_QUALITY_MIN_HISTORY_SESSIONS == 80


def test_atr_vol_eq_uses_exact_equal_weights():
    result = compute_atr_vol_eq_score(
        base_atr_compression_percentile=0.20,
        base_volume_dryup_percentile=0.80,
    )

    assert result == pytest.approx(0.50)


def test_atr_vol_eq_has_no_hidden_normalization():
    first = compute_atr_vol_eq_score(
        base_atr_compression_percentile=0.10,
        base_volume_dryup_percentile=0.90,
    )
    second = compute_atr_vol_eq_score(
        base_atr_compression_percentile=0.40,
        base_volume_dryup_percentile=0.60,
    )

    assert first == pytest.approx(0.50)
    assert second == pytest.approx(0.50)


@pytest.mark.parametrize(
    (
        "atr",
        "volume",
    ),
    (
        (None, 0.50),
        (0.50, None),
        (None, None),
    ),
)
def test_atr_vol_eq_missing_inputs_fail_closed(
    atr,
    volume,
):
    assert (
        compute_atr_vol_eq_score(
            base_atr_compression_percentile=atr,
            base_volume_dryup_percentile=volume,
        )
        is None
    )


@pytest.mark.parametrize(
    (
        "atr",
        "volume",
    ),
    (
        (float("nan"), 0.50),
        (float("inf"), 0.50),
        (float("-inf"), 0.50),
        (0.50, float("nan")),
        (0.50, float("inf")),
        (0.50, float("-inf")),
    ),
)
def test_atr_vol_eq_non_finite_inputs_fail_closed(
    atr,
    volume,
):
    assert (
        compute_atr_vol_eq_score(
            base_atr_compression_percentile=atr,
            base_volume_dryup_percentile=volume,
        )
        is None
    )


def _research_observation(
    *,
    history_sessions=80,
    structurally_valid=True,
    pivot_broken_by_close=False,
):
    return SimpleNamespace(
        history_sessions=history_sessions,
        structurally_valid=structurally_valid,
        pivot_broken_by_close=pivot_broken_by_close,
    )


def test_frozen_cohort_includes_exactly_80_sessions():
    observation = _research_observation(
        history_sessions=80,
    )

    assert is_frozen_vcp_quality_cohort_member(
        observation
    )


def test_frozen_cohort_rejects_immature_observation():
    observation = _research_observation(
        history_sessions=79,
    )

    assert not is_frozen_vcp_quality_cohort_member(
        observation
    )


def test_frozen_cohort_requires_structural_validity():
    observation = _research_observation(
        structurally_valid=False,
    )

    assert not is_frozen_vcp_quality_cohort_member(
        observation
    )


def test_frozen_cohort_requires_prebreakout_state():
    observation = _research_observation(
        pivot_broken_by_close=True,
    )

    assert not is_frozen_vcp_quality_cohort_member(
        observation
    )


def _cross_sectional(
    *,
    atr,
    volume,
    ticker,
):
    return SimpleNamespace(
        base_atr_compression_percentile=atr,
        base_volume_dryup_percentile=volume,
        ticker=ticker,
    )


def test_quality_builder_preserves_order_and_identity():
    aaa = _cross_sectional(
        atr=0.20,
        volume=0.80,
        ticker="AAA",
    )
    bbb = _cross_sectional(
        atr=0.70,
        volume=0.50,
        ticker="BBB",
    )

    result = build_vcp_quality_scores(
        (aaa, bbb)
    )

    assert len(result) == 2

    assert (
        result[0].cross_sectional_observation
        is aaa
    )
    assert (
        result[1].cross_sectional_observation
        is bbb
    )

    assert result[0].atr_vol_eq_score == pytest.approx(
        0.50
    )
    assert result[1].atr_vol_eq_score == pytest.approx(
        0.60
    )


def test_quality_builder_is_deterministic():
    observations = (
        _cross_sectional(
            atr=0.25,
            volume=0.75,
            ticker="AAA",
        ),
        _cross_sectional(
            atr=0.90,
            volume=0.40,
            ticker="BBB",
        ),
    )

    first = build_vcp_quality_scores(
        observations
    )
    second = build_vcp_quality_scores(
        observations
    )

    assert first == second
