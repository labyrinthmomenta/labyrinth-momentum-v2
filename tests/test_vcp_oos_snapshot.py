from datetime import (
    date,
    datetime,
    timezone,
)
import json
from types import SimpleNamespace

import pytest

from src.research.vcp_oos_report import (
    VCPOOSEvaluationStatus,
)
from src.research.vcp_oos_snapshot import (
    VCPOOSSnapshotError,
    build_oos_snapshot_payload,
    verify_oos_snapshot_payload,
    write_oos_snapshot,
)


def _config():
    return SimpleNamespace(
        tightening_range_5_max_pct=5.0,
        tightening_true_range_compression_max=0.75,
        tightening_final_volume_ratio_max=0.75,
        near_pivot_max_distance_pct=5.0,
        breakout_volume_expansion_min_ratio=1.50,
    )


def _quality(
    ticker: str,
    security_id: int,
    *,
    score: float | None,
    as_of: date = date(
        2026,
        8,
        31,
    ),
):
    observation = SimpleNamespace(
        as_of=as_of,
        security_id=security_id,
        ticker=ticker,
        history_sessions=120,
        vcp_state="NEAR_PIVOT",
        contraction_count=3,
        structurally_valid=True,
        contraction_depths=(
            18.0,
            11.0,
            6.0,
        ),
        final_to_first_depth_ratio=0.333,
        decreasing_step_fraction=1.0,
        range_5_pct=4.2,
        current_tr_compression_10_40=0.61,
        final_contraction_volume_ratio_50=0.58,
        base_duration_sessions=48,
        base_depth_pct=19.0,
        base_atr_compression_ratio=0.55,
        base_volume_dryup_ratio=0.63,
        pivot_price=100.0,
        distance_to_pivot_pct=2.2,
        distance_to_pivot_atr=0.8,
        first_intraday_breach_date=None,
        first_close_break_date=None,
        pivot_broken_by_close=False,
        breakout_volume_ratio_20=0.90,

        # Deliberate future/outcome fields.
        # Snapshot serialization must never copy these.
        outcome_available=True,
        outcome_error=None,
        reference_close=98.0,
        forward_return_5=0.99,
        forward_return_10=0.99,
        forward_return_20=0.99,
        forward_return_40=0.99,
        mfe_40=0.99,
        mae_40=-0.99,
    )

    relative = SimpleNamespace(
        observation=observation,
        benchmark_return_5=0.50,
        benchmark_return_10=0.50,
        benchmark_return_20=0.50,
        benchmark_return_40=0.50,
        relative_return_5=0.49,
        relative_return_10=0.49,
        relative_return_20=0.49,
        relative_return_40=0.49,
    )

    cross = SimpleNamespace(
        relative_observation=relative,
        base_depth_percentile=0.20,
        distance_to_pivot_percentile=0.30,
        base_atr_compression_percentile=0.80,
        base_volume_dryup_percentile=0.70,
        final_to_first_depth_percentile=0.75,
    )

    return SimpleNamespace(
        cross_sectional_observation=cross,
        atr_vol_eq_score=score,
    )


def _report(
    *,
    status=(
        VCPOOSEvaluationStatus.IMMATURE
    ),
    observation_count=2,
    score_available_count=1,
):
    return SimpleNamespace(
        as_of=date(
            2026,
            8,
            31,
        ),
        horizon_date_40=date(
            2026,
            10,
            26,
        ),
        available_through=date(
            2026,
            10,
            9,
        ),
        status=status,
        observation_count=(
            observation_count
        ),
        score_available_count=(
            score_available_count
        ),
    )


def _payload():
    return build_oos_snapshot_payload(
        observations=(
            _quality(
                "THYAO",
                2,
                score=None,
            ),
            _quality(
                "ASELS",
                1,
                score=0.75,
            ),
        ),
        report=_report(),
        vcp_state_config=_config(),
        git_commit="a" * 40,
        created_at_utc=datetime(
            2026,
            10,
            10,
            9,
            0,
            tzinfo=timezone.utc,
        ),
    )


def test_snapshot_is_deterministic_and_sorted():
    payload = _payload()

    assert payload[
        "outcomes_included"
    ] is False

    assert [
        row["ticker"]
        for row
        in payload["observations"]
    ] == [
        "ASELS",
        "THYAO",
    ]

    assert (
        payload["model"]["score_name"]
        == "ATR_VOL_EQ"
    )

    assert (
        payload["model"]["atr_weight"]
        == 0.50
    )

    assert (
        payload["model"]["volume_weight"]
        == 0.50
    )

    assert (
        payload["model"]
        ["minimum_history_sessions"]
        == 80
    )

    assert verify_oos_snapshot_payload(
        payload
    )


def test_snapshot_contains_no_future_outcomes():
    payload = _payload()

    encoded = json.dumps(
        payload,
        sort_keys=True,
    )

    forbidden = (
        "forward_return_",
        "relative_return_",
        "benchmark_return_",
        "outcome_available",
        "outcome_error",
        "mfe_40",
        "mae_40",
        "reference_close",
    )

    for name in forbidden:
        assert name not in encoded


def test_snapshot_hash_detects_mutation():
    payload = _payload()

    payload["observations"][0][
        "atr_vol_eq_score"
    ] = 0.123

    assert not verify_oos_snapshot_payload(
        payload
    )


def test_snapshot_rejects_mature_date():
    with pytest.raises(
        VCPOOSSnapshotError,
        match="IMMATURE",
    ):
        build_oos_snapshot_payload(
            observations=(
                _quality(
                    "ASELS",
                    1,
                    score=0.75,
                ),
            ),
            report=_report(
                status=(
                    VCPOOSEvaluationStatus.READY
                ),
                observation_count=1,
                score_available_count=1,
            ),
            vcp_state_config=_config(),
            git_commit="a" * 40,
        )


def test_snapshot_rejects_report_count_mismatch():
    with pytest.raises(
        VCPOOSSnapshotError,
        match="observation count",
    ):
        build_oos_snapshot_payload(
            observations=(
                _quality(
                    "ASELS",
                    1,
                    score=0.75,
                ),
            ),
            report=_report(
                observation_count=2,
                score_available_count=1,
            ),
            vcp_state_config=_config(),
            git_commit="a" * 40,
        )


def test_snapshot_is_write_once(
    tmp_path,
):
    payload = _payload()

    first = write_oos_snapshot(
        payload,
        tmp_path,
    )

    assert first.exists()

    with pytest.raises(
        VCPOOSSnapshotError,
        match="already exists",
    ):
        write_oos_snapshot(
            payload,
            tmp_path,
        )
