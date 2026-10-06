from datetime import date

from src.research.vcp_dataset import (
    VCPResearchObservation,
    build_research_observations,
)
from src.research.vcp_replay import (
    VCPForwardOutcome,
    VCPReplayBatch,
    VCPReplayRow,
    VCPReplaySkip,
    VCPReplaySnapshot,
)


AS_OF = date(2026, 7, 31)


def _snapshot(
    *,
    security_id: int,
    ticker: str,
) -> VCPReplaySnapshot:
    return VCPReplaySnapshot(
        security_id=security_id,
        ticker=ticker,
        as_of=AS_OF,
        vcp_state="VCP_CONTRACTING",
        contraction_count=3,
        structurally_valid=True,
        contraction_depths=(
            18.0,
            12.0,
            7.0,
        ),
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
    )


def test_build_research_observations_flattens_complete_replay_row():
    snapshot = _snapshot(
        security_id=1,
        ticker="GOOD",
    )

    outcome = VCPForwardOutcome(
        reference_date=AS_OF,
        reference_close=117.0,
        forward_return_5=0.03,
        forward_return_10=0.05,
        forward_return_20=0.12,
        forward_return_40=0.18,
        mfe_40=0.25,
        mae_40=-0.06,
    )

    row = VCPReplayRow(
        snapshot=snapshot,
        outcome=outcome,
    )

    batch = VCPReplayBatch(
        as_of=AS_OF,
        snapshots=(snapshot,),
        rows=(row,),
        skips=(),
    )

    observations = build_research_observations(
        batch
    )

    assert len(observations) == 1

    obs = observations[0]

    assert isinstance(
        obs,
        VCPResearchObservation,
    )

    # Identity / causal snapshot
    assert obs.as_of == AS_OF
    assert obs.security_id == 1
    assert obs.ticker == "GOOD"
    assert obs.vcp_state == "VCP_CONTRACTING"
    assert obs.structurally_valid is True

    # Structural / geometry features
    assert obs.contraction_count == 3
    assert obs.contraction_depths == (
        18.0,
        12.0,
        7.0,
    )
    assert obs.final_to_first_depth_ratio == 7.0 / 18.0
    assert obs.decreasing_step_fraction == 1.0

    # Base-relative features
    assert obs.base_duration_sessions == 42
    assert obs.base_depth_pct == 18.0
    assert obs.base_atr_compression_ratio == 0.78
    assert obs.base_volume_dryup_ratio == 0.69

    # Current readiness features
    assert obs.range_5_pct == 4.5
    assert obs.current_tr_compression_10_40 == 0.82
    assert obs.final_contraction_volume_ratio_50 == 0.71

    # Pivot / breakout context
    assert obs.pivot_price == 120.0
    assert obs.distance_to_pivot_pct == -2.5
    assert obs.distance_to_pivot_atr == -0.8
    assert obs.pivot_broken_by_close is False
    assert obs.breakout_volume_ratio_20 is None

    # Future outcome label
    assert obs.outcome_available is True
    assert obs.outcome_error is None

    assert obs.reference_close == 117.0
    assert obs.forward_return_5 == 0.03
    assert obs.forward_return_10 == 0.05
    assert obs.forward_return_20 == 0.12
    assert obs.forward_return_40 == 0.18
    assert obs.mfe_40 == 0.25
    assert obs.mae_40 == -0.06


def test_build_research_observations_preserves_snapshot_when_outcome_failed():
    snapshot = _snapshot(
        security_id=2,
        ticker="OUTFAIL",
    )

    skip = VCPReplaySkip(
        security_id=2,
        ticker="OUTFAIL",
        as_of=AS_OF,
        stage="OUTCOME",
        reason="simulated adjustment mismatch",
    )

    batch = VCPReplayBatch(
        as_of=AS_OF,
        snapshots=(snapshot,),
        rows=(),
        skips=(skip,),
    )

    observations = build_research_observations(
        batch
    )

    assert len(observations) == 1

    obs = observations[0]

    # Snapshot survives.
    assert obs.security_id == 2
    assert obs.ticker == "OUTFAIL"
    assert obs.as_of == AS_OF
    assert obs.structurally_valid is True
    assert obs.base_atr_compression_ratio == 0.78

    # Future label failure is explicit rather than silently dropping
    # the historical observation.
    assert obs.outcome_available is False
    assert obs.outcome_error == "simulated adjustment mismatch"

    assert obs.reference_close is None
    assert obs.forward_return_5 is None
    assert obs.forward_return_10 is None
    assert obs.forward_return_20 is None
    assert obs.forward_return_40 is None
    assert obs.mfe_40 is None
    assert obs.mae_40 is None


import pytest


def _outcome() -> VCPForwardOutcome:
    return VCPForwardOutcome(
        reference_date=AS_OF,
        reference_close=117.0,
        forward_return_5=0.03,
        forward_return_10=0.05,
        forward_return_20=0.12,
        forward_return_40=0.18,
        mfe_40=0.25,
        mae_40=-0.06,
    )


def test_research_dataset_rejects_row_and_outcome_skip_for_same_snapshot():
    snapshot = _snapshot(
        security_id=10,
        ticker="CONFLICT",
    )

    row = VCPReplayRow(
        snapshot=snapshot,
        outcome=_outcome(),
    )

    skip = VCPReplaySkip(
        security_id=10,
        ticker="CONFLICT",
        as_of=AS_OF,
        stage="OUTCOME",
        reason="conflicting outcome failure",
    )

    batch = VCPReplayBatch(
        as_of=AS_OF,
        snapshots=(snapshot,),
        rows=(row,),
        skips=(skip,),
    )

    with pytest.raises(
        ValueError,
        match="both replay row and OUTCOME skip",
    ):
        build_research_observations(
            batch
        )


def test_research_dataset_rejects_mismatched_row_snapshot_identity():
    snapshot = _snapshot(
        security_id=20,
        ticker="EXPECTED",
    )

    mismatched_snapshot = _snapshot(
        security_id=20,
        ticker="WRONG",
    )

    row = VCPReplayRow(
        snapshot=mismatched_snapshot,
        outcome=_outcome(),
    )

    batch = VCPReplayBatch(
        as_of=AS_OF,
        snapshots=(snapshot,),
        rows=(row,),
        skips=(),
    )

    with pytest.raises(
        ValueError,
        match="snapshot identity",
    ):
        build_research_observations(
            batch
        )


def test_research_dataset_rejects_unexplained_missing_outcome():
    snapshot = _snapshot(
        security_id=30,
        ticker="MISSING",
    )

    batch = VCPReplayBatch(
        as_of=AS_OF,
        snapshots=(snapshot,),
        rows=(),
        skips=(),
    )

    with pytest.raises(
        ValueError,
        match="no replay row or OUTCOME skip",
    ):
        build_research_observations(
            batch
        )


from dataclasses import replace

from src.research.vcp_dataset import (
    VCPResearchDataset,
    build_research_dataset,
)
from src.research.vcp_replay import VCPReplayGrid


def test_build_research_dataset_flattens_grid_in_chronological_batch_order():
    first_date = date(2026, 6, 30)
    second_date = date(2026, 7, 31)

    first_snapshot = replace(
        _snapshot(
            security_id=101,
            ticker="FIRST",
        ),
        as_of=first_date,
    )

    second_snapshot = replace(
        _snapshot(
            security_id=202,
            ticker="SECOND",
        ),
        as_of=second_date,
    )

    first_outcome = replace(
        _outcome(),
        reference_date=first_date,
    )

    first_row = VCPReplayRow(
        snapshot=first_snapshot,
        outcome=first_outcome,
    )

    first_batch = VCPReplayBatch(
        as_of=first_date,
        snapshots=(first_snapshot,),
        rows=(first_row,),
        skips=(),
    )

    second_skip = VCPReplaySkip(
        security_id=202,
        ticker="SECOND",
        as_of=second_date,
        stage="OUTCOME",
        reason="future adjustment unavailable",
    )

    second_batch = VCPReplayBatch(
        as_of=second_date,
        snapshots=(second_snapshot,),
        rows=(),
        skips=(second_skip,),
    )

    grid = VCPReplayGrid(
        batches=(
            first_batch,
            second_batch,
        )
    )

    dataset = build_research_dataset(
        grid
    )

    assert isinstance(
        dataset,
        VCPResearchDataset,
    )

    assert len(dataset.observations) == 2

    first, second = dataset.observations

    assert (
        first.as_of,
        first.security_id,
        first.ticker,
    ) == (
        first_date,
        101,
        "FIRST",
    )

    assert first.outcome_available is True
    assert first.forward_return_20 == 0.12

    assert (
        second.as_of,
        second.security_id,
        second.ticker,
    ) == (
        second_date,
        202,
        "SECOND",
    )

    assert second.outcome_available is False
    assert second.outcome_error == "future adjustment unavailable"
    assert second.forward_return_20 is None


def test_build_research_dataset_preserves_all_snapshots_across_dates():
    first_date = date(2026, 6, 30)
    second_date = date(2026, 7, 31)

    first_a = replace(
        _snapshot(
            security_id=1,
            ticker="AAA",
        ),
        as_of=first_date,
    )

    first_b = replace(
        _snapshot(
            security_id=2,
            ticker="BBB",
        ),
        as_of=first_date,
    )

    second_a = replace(
        _snapshot(
            security_id=1,
            ticker="AAA",
        ),
        as_of=second_date,
    )

    batches = (
        VCPReplayBatch(
            as_of=first_date,
            snapshots=(first_a, first_b),
            rows=(),
            skips=(
                VCPReplaySkip(
                    security_id=1,
                    ticker="AAA",
                    as_of=first_date,
                    stage="OUTCOME",
                    reason="missing label A",
                ),
                VCPReplaySkip(
                    security_id=2,
                    ticker="BBB",
                    as_of=first_date,
                    stage="OUTCOME",
                    reason="missing label B",
                ),
            ),
        ),
        VCPReplayBatch(
            as_of=second_date,
            snapshots=(second_a,),
            rows=(),
            skips=(
                VCPReplaySkip(
                    security_id=1,
                    ticker="AAA",
                    as_of=second_date,
                    stage="OUTCOME",
                    reason="missing later label",
                ),
            ),
        ),
    )

    dataset = build_research_dataset(
        VCPReplayGrid(
            batches=batches,
        )
    )

    assert tuple(
        (
            observation.as_of,
            observation.security_id,
        )
        for observation in dataset.observations
    ) == (
        (first_date, 1),
        (first_date, 2),
        (second_date, 1),
    )

    assert len(dataset.observations) == 3
