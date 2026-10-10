"""Immutable prospective snapshot ledger for frozen VCP OOS research.

Snapshots contain only information that is allowed to be known at the
cross-section as-of date. Forward returns, relative forward returns,
MFE/MAE and outcome state are deliberately excluded by an explicit
allow-list.

A snapshot may only be created while the OOS cross-section is IMMATURE.
Existing snapshot files are never overwritten.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from src.research.vcp_oos import (
    VCP_QUALITY_FORWARD_HORIZON,
    VCP_QUALITY_RESEARCH_FREEZE_DATE,
)
from src.research.vcp_oos_report import (
    VCPOOSDateReport,
    VCPOOSEvaluationStatus,
)
from src.research.vcp_quality import (
    ATR_VOL_EQ_ATR_WEIGHT,
    ATR_VOL_EQ_VOLUME_WEIGHT,
    VCP_QUALITY_MIN_HISTORY_SESSIONS,
    VCPQualityResearchObservation,
)
from src.strategy.vcp_state import VCPStateConfig


SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_TYPE = "prospective_vcp_oos"

_GIT_SHA_RE = re.compile(
    r"^[0-9a-f]{40}$"
)


class VCPOOSSnapshotError(RuntimeError):
    """Raised when a prospective snapshot cannot be created safely."""


def _finite_or_none(
    value: float | None,
) -> float | None:
    if value is None:
        return None

    number = float(value)

    if not math.isfinite(number):
        return None

    return number


def _date_or_none(
    value: Any,
) -> str | None:
    if value is None:
        return None

    return value.isoformat()


def _vcp_config_payload(
    config: VCPStateConfig,
) -> dict[str, float]:
    return {
        "tightening_range_5_max_pct": (
            config.tightening_range_5_max_pct
        ),
        "tightening_true_range_compression_max": (
            config.tightening_true_range_compression_max
        ),
        "tightening_final_volume_ratio_max": (
            config.tightening_final_volume_ratio_max
        ),
        "near_pivot_max_distance_pct": (
            config.near_pivot_max_distance_pct
        ),
        "breakout_volume_expansion_min_ratio": (
            config.breakout_volume_expansion_min_ratio
        ),
    }


def _observation_payload(
    item: VCPQualityResearchObservation,
) -> dict[str, Any]:
    """Serialize only explicitly approved pre-outcome fields."""

    cross = (
        item.cross_sectional_observation
    )

    observation = (
        cross
        .relative_observation
        .observation
    )

    return {
        "security_id": observation.security_id,
        "ticker": observation.ticker,
        "history_sessions": (
            observation.history_sessions
        ),
        "vcp_state": observation.vcp_state,
        "contraction_count": (
            observation.contraction_count
        ),
        "structurally_valid": (
            observation.structurally_valid
        ),
        "contraction_depths": [
            _finite_or_none(value)
            for value
            in observation.contraction_depths
        ],
        "final_to_first_depth_ratio": (
            _finite_or_none(
                observation
                .final_to_first_depth_ratio
            )
        ),
        "decreasing_step_fraction": (
            _finite_or_none(
                observation
                .decreasing_step_fraction
            )
        ),
        "range_5_pct": _finite_or_none(
            observation.range_5_pct
        ),
        "current_tr_compression_10_40": (
            _finite_or_none(
                observation
                .current_tr_compression_10_40
            )
        ),
        "final_contraction_volume_ratio_50": (
            _finite_or_none(
                observation
                .final_contraction_volume_ratio_50
            )
        ),
        "base_duration_sessions": (
            observation.base_duration_sessions
        ),
        "base_depth_pct": _finite_or_none(
            observation.base_depth_pct
        ),
        "base_atr_compression_ratio": (
            _finite_or_none(
                observation
                .base_atr_compression_ratio
            )
        ),
        "base_volume_dryup_ratio": (
            _finite_or_none(
                observation
                .base_volume_dryup_ratio
            )
        ),
        "pivot_price": _finite_or_none(
            observation.pivot_price
        ),
        "distance_to_pivot_pct": (
            _finite_or_none(
                observation
                .distance_to_pivot_pct
            )
        ),
        "distance_to_pivot_atr": (
            _finite_or_none(
                observation
                .distance_to_pivot_atr
            )
        ),
        "first_intraday_breach_date": (
            _date_or_none(
                observation
                .first_intraday_breach_date
            )
        ),
        "first_close_break_date": (
            _date_or_none(
                observation
                .first_close_break_date
            )
        ),
        "pivot_broken_by_close": (
            observation.pivot_broken_by_close
        ),
        "breakout_volume_ratio_20": (
            _finite_or_none(
                observation
                .breakout_volume_ratio_20
            )
        ),
        "base_depth_percentile": (
            _finite_or_none(
                cross.base_depth_percentile
            )
        ),
        "distance_to_pivot_percentile": (
            _finite_or_none(
                cross
                .distance_to_pivot_percentile
            )
        ),
        "base_atr_compression_percentile": (
            _finite_or_none(
                cross
                .base_atr_compression_percentile
            )
        ),
        "base_volume_dryup_percentile": (
            _finite_or_none(
                cross
                .base_volume_dryup_percentile
            )
        ),
        "final_to_first_depth_percentile": (
            _finite_or_none(
                cross
                .final_to_first_depth_percentile
            )
        ),
        "atr_vol_eq_score": (
            _finite_or_none(
                item.atr_vol_eq_score
            )
        ),
    }


def _canonical_bytes(
    payload: dict[str, Any],
) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode(
        "utf-8"
    )


def _payload_sha256(
    payload: dict[str, Any],
) -> str:
    return hashlib.sha256(
        _canonical_bytes(
            payload
        )
    ).hexdigest()


def build_oos_snapshot_payload(
    *,
    observations: Sequence[
        VCPQualityResearchObservation
    ],
    report: VCPOOSDateReport,
    vcp_state_config: VCPStateConfig,
    git_commit: str,
    created_at_utc: datetime | None = None,
) -> dict[str, Any]:
    """Build one immutable prospective snapshot payload."""

    if (
        report.status
        is not VCPOOSEvaluationStatus.IMMATURE
    ):
        raise VCPOOSSnapshotError(
            "snapshot creation is allowed only "
            "for IMMATURE OOS dates"
        )

    if not _GIT_SHA_RE.fullmatch(
        git_commit
    ):
        raise VCPOOSSnapshotError(
            "git_commit must be a full "
            "40-character lowercase SHA"
        )

    if not observations:
        raise VCPOOSSnapshotError(
            "snapshot requires at least "
            "one observation"
        )

    rows = [
        _observation_payload(
            item
        )
        for item
        in observations
    ]

    rows.sort(
        key=lambda row: (
            row["ticker"],
            row["security_id"],
        )
    )

    for item in observations:
        observation = (
            item
            .cross_sectional_observation
            .relative_observation
            .observation
        )

        if (
            observation.as_of
            != report.as_of
        ):
            raise VCPOOSSnapshotError(
                "observation as_of does not "
                "match report as_of"
            )

    if (
        len(rows)
        != report.observation_count
    ):
        raise VCPOOSSnapshotError(
            "snapshot observation count does "
            "not match OOS report"
        )

    score_count = sum(
        row["atr_vol_eq_score"]
        is not None
        for row
        in rows
    )

    if (
        score_count
        != report.score_available_count
    ):
        raise VCPOOSSnapshotError(
            "snapshot score coverage does "
            "not match OOS report"
        )

    timestamp = (
        created_at_utc
        or datetime.now(
            timezone.utc
        )
    )

    if timestamp.tzinfo is None:
        raise VCPOOSSnapshotError(
            "created_at_utc must be "
            "timezone-aware"
        )

    timestamp = timestamp.astimezone(
        timezone.utc
    )

    core: dict[str, Any] = {
        "schema_version": (
            SNAPSHOT_SCHEMA_VERSION
        ),
        "snapshot_type": SNAPSHOT_TYPE,
        "outcomes_included": False,
        "as_of": report.as_of.isoformat(),
        "horizon_date_40": (
            report.horizon_date_40.isoformat()
        ),
        "available_through": (
            report.available_through.isoformat()
        ),
        "created_at_utc": (
            timestamp
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        ),
        "git_commit": git_commit,
        "model": {
            "score_name": "ATR_VOL_EQ",
            "atr_weight": (
                ATR_VOL_EQ_ATR_WEIGHT
            ),
            "volume_weight": (
                ATR_VOL_EQ_VOLUME_WEIGHT
            ),
            "minimum_history_sessions": (
                VCP_QUALITY_MIN_HISTORY_SESSIONS
            ),
            "research_freeze_date": (
                VCP_QUALITY_RESEARCH_FREEZE_DATE
                .isoformat()
            ),
            "forward_horizon_sessions": (
                VCP_QUALITY_FORWARD_HORIZON
            ),
            "vcp_state_config": (
                _vcp_config_payload(
                    vcp_state_config
                )
            ),
        },
        "observation_count": len(
            rows
        ),
        "score_available_count": (
            score_count
        ),
        "observations": rows,
    }

    payload = dict(
        core
    )

    payload["snapshot_sha256"] = (
        _payload_sha256(
            core
        )
    )

    return payload


def verify_oos_snapshot_payload(
    payload: dict[str, Any],
) -> bool:
    """Verify the embedded canonical SHA-256."""

    stored = payload.get(
        "snapshot_sha256"
    )

    if not isinstance(
        stored,
        str,
    ):
        return False

    core = {
        key: value
        for key, value
        in payload.items()
        if key != "snapshot_sha256"
    }

    return (
        stored
        == _payload_sha256(
            core
        )
    )


def write_oos_snapshot(
    payload: dict[str, Any],
    output_dir: str | Path,
) -> Path:
    """Write a snapshot once; never overwrite an existing date."""

    if not verify_oos_snapshot_payload(
        payload
    ):
        raise VCPOOSSnapshotError(
            "snapshot payload SHA-256 "
            "verification failed"
        )

    as_of = payload.get(
        "as_of"
    )

    if not isinstance(
        as_of,
        str,
    ):
        raise VCPOOSSnapshotError(
            "snapshot payload has no "
            "valid as_of"
        )

    directory = Path(
        output_dir
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        directory
        / f"{as_of}.json"
    )

    try:
        with path.open(
            "x",
            encoding="utf-8",
        ) as handle:
            json.dump(
                payload,
                handle,
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )

            handle.write(
                "\n"
            )

    except FileExistsError as exc:
        raise VCPOOSSnapshotError(
            f"snapshot already exists: {path}"
        ) from exc

    return path
