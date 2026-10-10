import hashlib
import json

import pytest

from src.research.vcp_shadow_selection import (
    SHADOW_SELECTION_Q5_MIN_PERCENTILE,
    VCPShadowSelectionError,
    build_shadow_selection,
)


def _seal(payload):
    core = dict(
        payload
    )

    encoded = json.dumps(
        core,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    payload[
        "snapshot_sha256"
    ] = hashlib.sha256(
        encoded
    ).hexdigest()

    return payload


def _snapshot(scores):
    observations = []

    for index, score in enumerate(
        scores,
        start=1,
    ):
        observations.append(
            {
                "security_id": index,
                "ticker": f"T{index:02d}",
                "atr_vol_eq_score": score,
            }
        )

    return _seal(
        {
            "schema_version": 1,
            "snapshot_type": "prospective_vcp_oos",
            "outcomes_included": False,
            "as_of": "2026-08-31",
            "horizon_date_40": "2026-10-26",
            "available_through": "2026-10-09",
            "git_commit": "a" * 40,
            "model": {},
            "observation_count": len(
                observations
            ),
            "score_available_count": sum(
                score is not None
                for score in scores
            ),
            "observations": observations,
        }
    )


def test_shadow_selection_uses_frozen_q5_cutoff():
    snapshot = _snapshot(
        [
            0.10,
            0.20,
            0.30,
            0.40,
            0.50,
            0.60,
            0.70,
            0.80,
            0.90,
            1.00,
            1.10,
        ]
    )

    selection = build_shadow_selection(
        snapshot
    )

    assert (
        SHADOW_SELECTION_Q5_MIN_PERCENTILE
        == 0.80
    )

    assert [
        row.ticker
        for row
        in selection.rows
    ] == [
        "T11",
        "T10",
        "T09",
    ]


def test_shadow_selection_is_equal_weighted():
    selection = build_shadow_selection(
        _snapshot(
            [
                0.10,
                0.20,
                0.30,
                0.40,
                0.50,
                0.60,
                0.70,
                0.80,
                0.90,
                1.00,
                1.10,
            ]
        )
    )

    assert selection.selected_count == 3

    for row in selection.rows:
        assert row.weight == pytest.approx(
            1.0 / 3.0
        )

    assert sum(
        row.weight
        for row in selection.rows
    ) == pytest.approx(1.0)


def test_shadow_selection_excludes_missing_score():
    selection = build_shadow_selection(
        _snapshot(
            [
                None,
                0.10,
                0.20,
                0.30,
                0.40,
                0.50,
                0.60,
            ]
        )
    )

    assert selection.score_available_count == 6

    assert all(
        row.ticker != "T01"
        for row in selection.rows
    )


def test_shadow_selection_handles_ties_with_average_rank():
    selection = build_shadow_selection(
        _snapshot(
            [
                0.10,
                0.20,
                0.30,
                0.40,
                0.50,
                0.60,
                0.80,
                0.80,
                0.80,
                0.80,
                0.80,
            ]
        )
    )

    selected = {
        row.ticker
        for row in selection.rows
    }

    # Five tied top scores occupy ranks 7..11.
    # Their average rank is 9, so:
    # (9 - 1) / (11 - 1) = 0.80.
    # The frozen Q5 rule is percentile >= 0.80.
    assert selected == {
        "T07",
        "T08",
        "T09",
        "T10",
        "T11",
    }


def test_shadow_selection_rejects_mutated_snapshot():
    snapshot = _snapshot(
        [
            0.10,
            0.20,
            0.30,
            0.40,
            0.50,
            0.60,
        ]
    )

    snapshot[
        "observations"
    ][0][
        "atr_vol_eq_score"
    ] = 0.99

    with pytest.raises(
        VCPShadowSelectionError,
        match="SHA-256",
    ):
        build_shadow_selection(
            snapshot
        )


def test_shadow_selection_rejects_outcome_bearing_snapshot():
    snapshot = _snapshot(
        [
            0.10,
            0.20,
            0.30,
            0.40,
            0.50,
            0.60,
        ]
    )

    snapshot[
        "outcomes_included"
    ] = True

    # Reseal deliberately: this tests the policy guard,
    # not mutation detection.
    snapshot.pop(
        "snapshot_sha256"
    )

    _seal(
        snapshot
    )

    with pytest.raises(
        VCPShadowSelectionError,
        match="exclude outcomes",
    ):
        build_shadow_selection(
            snapshot
        )
