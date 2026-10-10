"""Frozen prospective shadow-selection policy for VCP OOS research.

This module derives an ex-ante paper selection only from a sealed OOS
snapshot. It does not access the database, forward outcomes, production
ranking, or market-regime filters.

Frozen policy:
- finite ATR_VOL_EQ scores only,
- same-date average-rank percentiles,
- Q5 selection at percentile >= 0.80,
- equal weight among selected names,
- evaluation horizon remains +40 official BIST sessions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any

from src.research.vcp_oos import (
    VCP_QUALITY_FORWARD_HORIZON,
)
from src.research.vcp_oos_snapshot import (
    verify_oos_snapshot_payload,
)


SHADOW_SELECTION_SCHEMA_VERSION = 1
SHADOW_SELECTION_POLICY = "ATR_VOL_EQ_Q5_EQUAL_WEIGHT"
SHADOW_SELECTION_Q5_MIN_PERCENTILE = 0.80


class VCPShadowSelectionError(RuntimeError):
    """Raised when a shadow selection cannot be built safely."""


@dataclass(frozen=True)
class VCPShadowSelectionRow:
    security_id: int
    ticker: str
    score: float
    percentile: float
    weight: float


@dataclass(frozen=True)
class VCPShadowSelection:
    as_of: str
    horizon_date_40: str
    source_snapshot_sha256: str
    score_available_count: int
    selected_count: int
    rows: tuple[VCPShadowSelectionRow, ...]


def _average_ranks(
    values: Sequence[float],
) -> list[float]:
    indexed = sorted(
        enumerate(values),
        key=lambda pair: pair[1],
    )

    ranks = [0.0] * len(values)
    start = 0

    while start < len(indexed):
        end = start

        while (
            end + 1 < len(indexed)
            and indexed[end + 1][1]
            == indexed[start][1]
        ):
            end += 1

        average_rank = (
            (start + 1)
            + (end + 1)
        ) / 2.0

        for position in range(
            start,
            end + 1,
        ):
            original_index = indexed[position][0]
            ranks[original_index] = average_rank

        start = end + 1

    return ranks


def _percentile_ranks(
    values: Sequence[float],
) -> list[float]:
    if not values:
        return []

    if len(values) == 1:
        return [0.5]

    ranks = _average_ranks(
        values
    )

    return [
        (rank - 1.0)
        / (len(values) - 1.0)
        for rank in ranks
    ]


def build_shadow_selection(
    snapshot: dict[str, Any],
) -> VCPShadowSelection:
    """Build the frozen Q5 equal-weight selection from one sealed snapshot."""

    if not verify_oos_snapshot_payload(
        snapshot
    ):
        raise VCPShadowSelectionError(
            "source snapshot SHA-256 verification failed"
        )

    if snapshot.get(
        "outcomes_included"
    ) is not False:
        raise VCPShadowSelectionError(
            "source snapshot must exclude outcomes"
        )

    observations = snapshot.get(
        "observations"
    )

    if not isinstance(
        observations,
        list,
    ):
        raise VCPShadowSelectionError(
            "source snapshot has no valid observations"
        )

    scored: list[
        tuple[int, str, float]
    ] = []

    for item in observations:
        score = item.get(
            "atr_vol_eq_score"
        )

        if score is None:
            continue

        score = float(
            score
        )

        if not isfinite(
            score
        ):
            continue

        scored.append(
            (
                int(
                    item["security_id"]
                ),
                str(
                    item["ticker"]
                ),
                score,
            )
        )

    expected_score_count = snapshot.get(
        "score_available_count"
    )

    if (
        len(scored)
        != expected_score_count
    ):
        raise VCPShadowSelectionError(
            "finite score count does not match "
            "sealed snapshot coverage"
        )

    if not scored:
        raise VCPShadowSelectionError(
            "no finite ATR_VOL_EQ scores available"
        )

    percentiles = _percentile_ranks(
        [
            score
            for _, _, score
            in scored
        ]
    )

    selected = [
        (
            security_id,
            ticker,
            score,
            percentile,
        )
        for (
            security_id,
            ticker,
            score,
        ), percentile
        in zip(
            scored,
            percentiles,
        )
        if (
            percentile
            >= SHADOW_SELECTION_Q5_MIN_PERCENTILE
        )
    ]

    if not selected:
        raise VCPShadowSelectionError(
            "frozen Q5 policy selected no securities"
        )

    weight = (
        1.0
        / len(selected)
    )

    rows = tuple(
        VCPShadowSelectionRow(
            security_id=security_id,
            ticker=ticker,
            score=score,
            percentile=percentile,
            weight=weight,
        )
        for (
            security_id,
            ticker,
            score,
            percentile,
        )
        in sorted(
            selected,
            key=lambda row: (
                -row[2],
                row[1],
                row[0],
            ),
        )
    )

    if (
        VCP_QUALITY_FORWARD_HORIZON
        != 40
    ):
        raise VCPShadowSelectionError(
            "frozen forward horizon drift detected"
        )

    return VCPShadowSelection(
        as_of=str(
            snapshot["as_of"]
        ),
        horizon_date_40=str(
            snapshot["horizon_date_40"]
        ),
        source_snapshot_sha256=str(
            snapshot["snapshot_sha256"]
        ),
        score_available_count=len(
            scored
        ),
        selected_count=len(
            rows
        ),
        rows=rows,
    )
