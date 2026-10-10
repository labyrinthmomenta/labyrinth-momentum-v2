from datetime import datetime, timezone

import pytest

from src.research.vcp_shadow_artifact import (
    VCPShadowArtifactError,
    build_shadow_artifact_payload,
    verify_shadow_artifact_payload,
    write_shadow_artifact,
)
from src.research.vcp_shadow_selection import (
    VCPShadowSelection,
    VCPShadowSelectionRow,
)


def _selection():
    rows = (
        VCPShadowSelectionRow(
            security_id=1,
            ticker="AAA",
            score=0.90,
            percentile=1.00,
            weight=0.50,
        ),
        VCPShadowSelectionRow(
            security_id=2,
            ticker="BBB",
            score=0.80,
            percentile=0.80,
            weight=0.50,
        ),
    )

    return VCPShadowSelection(
        as_of="2026-08-31",
        horizon_date_40="2026-10-26",
        source_snapshot_sha256="a" * 64,
        score_available_count=10,
        selected_count=2,
        rows=rows,
    )


def _payload():
    return build_shadow_artifact_payload(
        _selection(),
        policy_git_commit="b" * 40,
        created_at_utc=datetime(
            2026,
            10,
            10,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )


def test_shadow_artifact_contains_frozen_policy():
    payload = _payload()

    assert payload["outcomes_included"] is False
    assert (
        payload["policy"]["minimum_percentile"]
        == 0.80
    )
    assert (
        payload["policy"]["weighting"]
        == "EQUAL_WEIGHT"
    )
    assert payload["policy"]["stop_loss"] is False
    assert verify_shadow_artifact_payload(
        payload
    )


def test_shadow_artifact_contains_no_outcomes():
    payload = _payload()

    text = str(payload)

    forbidden = (
        "forward_return",
        "relative_return",
        "benchmark_return",
        "mfe",
        "mae",
    )

    for name in forbidden:
        assert name not in text


def test_shadow_artifact_hash_detects_mutation():
    payload = _payload()

    payload["rows"][0]["weight"] = 0.40

    assert not verify_shadow_artifact_payload(
        payload
    )


def test_shadow_artifact_is_write_once(
    tmp_path,
):
    payload = _payload()

    first = write_shadow_artifact(
        payload,
        tmp_path,
    )

    assert first.exists()

    with pytest.raises(
        VCPShadowArtifactError,
        match="already exists",
    ):
        write_shadow_artifact(
            payload,
            tmp_path,
        )
