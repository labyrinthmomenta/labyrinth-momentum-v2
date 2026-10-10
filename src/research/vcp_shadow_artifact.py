"""Immutable artifact writer for frozen prospective VCP shadow selections."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from src.research.vcp_shadow_selection import (
    SHADOW_SELECTION_POLICY,
    SHADOW_SELECTION_Q5_MIN_PERCENTILE,
    VCPShadowSelection,
)


SHADOW_ARTIFACT_SCHEMA_VERSION = 1
SHADOW_ARTIFACT_TYPE = "prospective_vcp_shadow_selection"

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class VCPShadowArtifactError(RuntimeError):
    """Raised when a shadow-selection artifact cannot be handled safely."""


def _canonical_bytes(
    payload: dict[str, Any],
) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(
    payload: dict[str, Any],
) -> str:
    return hashlib.sha256(
        _canonical_bytes(payload)
    ).hexdigest()


def build_shadow_artifact_payload(
    selection: VCPShadowSelection,
    *,
    policy_git_commit: str,
    created_at_utc: datetime | None = None,
) -> dict[str, Any]:
    """Build one sealed ex-ante shadow-selection artifact."""

    if not _GIT_SHA_RE.fullmatch(
        policy_git_commit
    ):
        raise VCPShadowArtifactError(
            "policy_git_commit must be a full "
            "40-character lowercase SHA"
        )

    if selection.selected_count != len(
        selection.rows
    ):
        raise VCPShadowArtifactError(
            "selected_count does not match rows"
        )

    if not selection.rows:
        raise VCPShadowArtifactError(
            "shadow selection is empty"
        )

    weight_sum = sum(
        row.weight
        for row in selection.rows
    )

    if abs(weight_sum - 1.0) > 1e-12:
        raise VCPShadowArtifactError(
            "shadow-selection weights must sum to 1"
        )

    timestamp = (
        created_at_utc
        or datetime.now(timezone.utc)
    )

    if timestamp.tzinfo is None:
        raise VCPShadowArtifactError(
            "created_at_utc must be timezone-aware"
        )

    timestamp = timestamp.astimezone(
        timezone.utc
    )

    rows = [
        {
            "security_id": row.security_id,
            "ticker": row.ticker,
            "score": row.score,
            "percentile": row.percentile,
            "weight": row.weight,
        }
        for row in selection.rows
    ]

    core: dict[str, Any] = {
        "schema_version": SHADOW_ARTIFACT_SCHEMA_VERSION,
        "artifact_type": SHADOW_ARTIFACT_TYPE,
        "outcomes_included": False,
        "as_of": selection.as_of,
        "horizon_date_40": selection.horizon_date_40,
        "source_snapshot_sha256": (
            selection.source_snapshot_sha256
        ),
        "policy_git_commit": policy_git_commit,
        "created_at_utc": (
            timestamp.isoformat().replace(
                "+00:00",
                "Z",
            )
        ),
        "policy": {
            "name": SHADOW_SELECTION_POLICY,
            "score": "ATR_VOL_EQ",
            "minimum_percentile": (
                SHADOW_SELECTION_Q5_MIN_PERCENTILE
            ),
            "weighting": "EQUAL_WEIGHT",
            "holding_horizon_sessions": 40,
            "market_regime_filter": False,
            "stop_loss": False,
            "discretionary_exit": False,
        },
        "score_available_count": (
            selection.score_available_count
        ),
        "selected_count": (
            selection.selected_count
        ),
        "rows": rows,
    }

    payload = dict(core)
    payload["artifact_sha256"] = _sha256(
        core
    )

    return payload


def verify_shadow_artifact_payload(
    payload: dict[str, Any],
) -> bool:
    stored = payload.get(
        "artifact_sha256"
    )

    if not isinstance(stored, str):
        return False

    core = {
        key: value
        for key, value in payload.items()
        if key != "artifact_sha256"
    }

    return stored == _sha256(core)


def write_shadow_artifact(
    payload: dict[str, Any],
    output_dir: str | Path,
) -> Path:
    """Write once; never overwrite an existing selection date."""

    if not verify_shadow_artifact_payload(
        payload
    ):
        raise VCPShadowArtifactError(
            "artifact SHA-256 verification failed"
        )

    as_of = payload.get("as_of")

    if not isinstance(as_of, str):
        raise VCPShadowArtifactError(
            "artifact has no valid as_of"
        )

    directory = Path(output_dir)

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = directory / f"{as_of}.json"

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
            handle.write("\n")

    except FileExistsError as exc:
        raise VCPShadowArtifactError(
            f"artifact already exists: {path}"
        ) from exc

    return path
