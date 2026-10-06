from dataclasses import replace
from datetime import date

import pytest

from src.research.vcp_dataset import (
    VCPResearchDataset,
    VCPResearchObservation,
)
from src.research.vcp_relative import (
    VCPRelativeObservation,
    build_relative_outcomes,
)


DAY_1 = date(2026, 6, 30)
DAY_2 = date(2026, 7, 31)


def _observation(
    *,
    as_of: date,
    security_id: int,
    ticker: str,
    r5: float | None,
    r10: float | None,
    r20: float | None,
    r40: float | None,
    outcome_available: bool = True,
) -> VCPResearchObservation:
    return VCPResearchObservation(
        as_of=as_of,
        security_id=security_id,
        ticker=ticker,
        vcp_state="VCP_CONTRACTING",
        contraction_count=3,
        structurally_valid=True,
        contraction_depths=(18.0, 12.0, 7.0),
        final_to_first_depth_ratio=7.0 / 18.0,
        decreasing_step_fraction=1.0,
        range_5_pct=4.5,
        current_tr_compression_10_40=0.82,
        final_contraction_volume_ratio_50=0.71,
        base_duration_sessions=42,
        base_depth_pct=18.0,
        base_atr_compression_ratio=0.78,
        base_volume_dryup_ratio=0.69,
        pivot_price=120.0,
        distance_to_pivot_pct=-2.5,
        distance_to_pivot_atr=-0.8,
        first_intraday_breach_date=None,
        first_close_break_date=None,
        pivot_broken_by_close=False,
        breakout_volume_ratio_20=None,
        outcome_available=outcome_available,
        outcome_error=None if outcome_available else "missing future label",
        reference_close=117.0 if outcome_available else None,
        forward_return_5=r5,
        forward_return_10=r10,
        forward_return_20=r20,
        forward_return_40=r40,
        mfe_40=0.25 if outcome_available else None,
        mae_40=-0.06 if outcome_available else None,
    )


def test_relative_outcomes_use_same_date_universe_median():
    dataset = VCPResearchDataset(
        observations=(
            _observation(
                as_of=DAY_1,
                security_id=1,
                ticker="AAA",
                r5=0.01,
                r10=0.02,
                r20=0.03,
                r40=0.04,
            ),
            _observation(
                as_of=DAY_1,
                security_id=2,
                ticker="BBB",
                r5=0.03,
                r10=0.04,
                r20=0.07,
                r40=0.10,
            ),
            _observation(
                as_of=DAY_1,
                security_id=3,
                ticker="CCC",
                r5=0.05,
                r10=0.08,
                r20=0.11,
                r40=0.16,
            ),
        )
    )

    result = build_relative_outcomes(
        dataset
    )

    assert len(result.observations) == 3

    aaa, bbb, ccc = result.observations

    assert isinstance(
        aaa,
        VCPRelativeObservation,
    )

    # Same-date medians:
    # +5  = 3%
    # +10 = 4%
    # +20 = 7%
    # +40 = 10%
    assert aaa.benchmark_return_5 == pytest.approx(0.03)
    assert aaa.benchmark_return_10 == pytest.approx(0.04)
    assert aaa.benchmark_return_20 == pytest.approx(0.07)
    assert aaa.benchmark_return_40 == pytest.approx(0.10)

    assert aaa.relative_return_5 == pytest.approx(-0.02)
    assert aaa.relative_return_10 == pytest.approx(-0.02)
    assert aaa.relative_return_20 == pytest.approx(-0.04)
    assert aaa.relative_return_40 == pytest.approx(-0.06)

    assert bbb.relative_return_5 == pytest.approx(0.0)
    assert bbb.relative_return_10 == pytest.approx(0.0)
    assert bbb.relative_return_20 == pytest.approx(0.0)
    assert bbb.relative_return_40 == pytest.approx(0.0)

    assert ccc.relative_return_5 == pytest.approx(0.02)
    assert ccc.relative_return_10 == pytest.approx(0.04)
    assert ccc.relative_return_20 == pytest.approx(0.04)
    assert ccc.relative_return_40 == pytest.approx(0.06)


def test_relative_outcomes_never_mix_different_as_of_dates():
    dataset = VCPResearchDataset(
        observations=(
            _observation(
                as_of=DAY_1,
                security_id=1,
                ticker="AAA",
                r5=0.10,
                r10=0.10,
                r20=0.10,
                r40=0.10,
            ),
            _observation(
                as_of=DAY_1,
                security_id=2,
                ticker="BBB",
                r5=0.20,
                r10=0.20,
                r20=0.20,
                r40=0.20,
            ),
            _observation(
                as_of=DAY_2,
                security_id=1,
                ticker="AAA",
                r5=-0.20,
                r10=-0.20,
                r20=-0.20,
                r40=-0.20,
            ),
            _observation(
                as_of=DAY_2,
                security_id=2,
                ticker="BBB",
                r5=0.00,
                r10=0.00,
                r20=0.00,
                r40=0.00,
            ),
        )
    )

    result = build_relative_outcomes(
        dataset
    )

    day_1 = [
        item
        for item in result.observations
        if item.observation.as_of == DAY_1
    ]

    day_2 = [
        item
        for item in result.observations
        if item.observation.as_of == DAY_2
    ]

    assert all(
        item.benchmark_return_20 == pytest.approx(0.15)
        for item in day_1
    )

    assert all(
        item.benchmark_return_20 == pytest.approx(-0.10)
        for item in day_2
    )


def test_relative_outcomes_preserve_missing_future_labels():
    dataset = VCPResearchDataset(
        observations=(
            _observation(
                as_of=DAY_1,
                security_id=1,
                ticker="GOOD",
                r5=0.02,
                r10=0.04,
                r20=0.06,
                r40=0.08,
            ),
            _observation(
                as_of=DAY_1,
                security_id=2,
                ticker="MISSING",
                r5=None,
                r10=None,
                r20=None,
                r40=None,
                outcome_available=False,
            ),
        )
    )

    result = build_relative_outcomes(
        dataset
    )

    good, missing = result.observations

    # Missing future-label observation is not used in the benchmark.
    assert good.benchmark_return_20 == pytest.approx(0.06)
    assert good.relative_return_20 == pytest.approx(0.0)

    # But its causal observation is still preserved.
    assert missing.observation.ticker == "MISSING"
    assert missing.observation.outcome_available is False
    assert missing.relative_return_5 is None
    assert missing.relative_return_10 is None
    assert missing.relative_return_20 is None
    assert missing.relative_return_40 is None


def test_relative_outcomes_compute_each_horizon_independently():
    dataset = VCPResearchDataset(
        observations=(
            _observation(
                as_of=DAY_1,
                security_id=1,
                ticker="AAA",
                r5=0.01,
                r10=0.02,
                r20=0.03,
                r40=None,
            ),
            _observation(
                as_of=DAY_1,
                security_id=2,
                ticker="BBB",
                r5=0.03,
                r10=0.04,
                r20=0.07,
                r40=0.10,
            ),
            _observation(
                as_of=DAY_1,
                security_id=3,
                ticker="CCC",
                r5=0.05,
                r10=0.08,
                r20=0.11,
                r40=0.20,
            ),
        )
    )

    result = build_relative_outcomes(
        dataset
    )

    aaa, bbb, ccc = result.observations

    # +20 uses all three observations.
    assert aaa.benchmark_return_20 == pytest.approx(0.07)

    # +40 uses only the two available +40 labels.
    assert aaa.benchmark_return_40 == pytest.approx(0.15)
    assert aaa.relative_return_40 is None

    assert bbb.relative_return_40 == pytest.approx(-0.05)
    assert ccc.relative_return_40 == pytest.approx(0.05)


def test_relative_outcomes_preserve_dataset_order_and_observation_identity():
    observations = (
        _observation(
            as_of=DAY_2,
            security_id=30,
            ticker="THIRD",
            r5=0.03,
            r10=0.04,
            r20=0.05,
            r40=0.06,
        ),
        _observation(
            as_of=DAY_1,
            security_id=10,
            ticker="FIRST",
            r5=0.01,
            r10=0.02,
            r20=0.03,
            r40=0.04,
        ),
        _observation(
            as_of=DAY_1,
            security_id=20,
            ticker="SECOND",
            r5=0.02,
            r10=0.03,
            r20=0.04,
            r40=0.05,
        ),
    )

    dataset = VCPResearchDataset(
        observations=observations
    )

    result = build_relative_outcomes(
        dataset
    )

    assert tuple(
        item.observation.ticker
        for item in result.observations
    ) == (
        "THIRD",
        "FIRST",
        "SECOND",
    )

    assert len(result.observations) == len(observations)

    for relative_item, original in zip(
        result.observations,
        observations,
    ):
        # Derived-label layer wraps the original research observation;
        # it does not rebuild or mutate it.
        assert relative_item.observation is original


def test_relative_outcomes_leave_empty_horizon_benchmark_none():
    dataset = VCPResearchDataset(
        observations=(
            _observation(
                as_of=DAY_1,
                security_id=1,
                ticker="AAA",
                r5=0.01,
                r10=0.02,
                r20=0.03,
                r40=None,
            ),
            _observation(
                as_of=DAY_1,
                security_id=2,
                ticker="BBB",
                r5=0.03,
                r10=0.04,
                r20=0.07,
                r40=None,
            ),
        )
    )

    result = build_relative_outcomes(
        dataset
    )

    # Other horizons still get their normal same-date benchmark.
    assert all(
        item.benchmark_return_20 == pytest.approx(0.05)
        for item in result.observations
    )

    # No +40 labels exist on this date, so the +40 benchmark and
    # relative labels remain unavailable rather than being invented.
    assert all(
        item.benchmark_return_40 is None
        for item in result.observations
    )

    assert all(
        item.relative_return_40 is None
        for item in result.observations
    )
