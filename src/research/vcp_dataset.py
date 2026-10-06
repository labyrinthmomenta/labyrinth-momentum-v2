"""Research dataset records derived from historical VCP replay.

This layer does not recalculate VCP features or future outcomes.

It only combines:

- causal snapshot information known at ``as_of``
- future outcome labels when available
- explicit outcome failure information when labels are unavailable
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.research.vcp_replay import (
    VCPReplayBatch,
    VCPReplayGrid,
    VCPReplaySnapshot,
)


@dataclass(frozen=True)
class VCPResearchObservation:
    # --------------------------------------------------
    # Identity
    # --------------------------------------------------

    as_of: date
    security_id: int
    ticker: str

    # --------------------------------------------------
    # Causal VCP snapshot
    # --------------------------------------------------

    vcp_state: str
    contraction_count: int
    structurally_valid: bool

    contraction_depths: tuple[float, ...]
    final_to_first_depth_ratio: float | None
    decreasing_step_fraction: float | None

    range_5_pct: float | None
    current_tr_compression_10_40: float | None
    final_contraction_volume_ratio_50: float | None

    base_duration_sessions: int | None
    base_depth_pct: float | None
    base_atr_compression_ratio: float | None
    base_volume_dryup_ratio: float | None

    pivot_price: float | None
    distance_to_pivot_pct: float | None
    distance_to_pivot_atr: float | None

    first_intraday_breach_date: date | None
    first_close_break_date: date | None
    pivot_broken_by_close: bool
    breakout_volume_ratio_20: float | None

    # --------------------------------------------------
    # Future label availability
    # --------------------------------------------------

    outcome_available: bool
    outcome_error: str | None

    # --------------------------------------------------
    # Future outcome labels
    # --------------------------------------------------

    reference_close: float | None
    forward_return_5: float | None
    forward_return_10: float | None
    forward_return_20: float | None
    forward_return_40: float | None
    mfe_40: float | None
    mae_40: float | None


def _snapshot_fields(
    snapshot: VCPReplaySnapshot,
) -> dict[str, object]:
    """Flatten one causal replay snapshot without recalculation."""

    return {
        "as_of": snapshot.as_of,
        "security_id": snapshot.security_id,
        "ticker": snapshot.ticker,
        "vcp_state": snapshot.vcp_state,
        "contraction_count": snapshot.contraction_count,
        "structurally_valid": snapshot.structurally_valid,
        "contraction_depths": snapshot.contraction_depths,
        "final_to_first_depth_ratio": snapshot.final_to_first_depth_ratio,
        "decreasing_step_fraction": snapshot.decreasing_step_fraction,
        "range_5_pct": snapshot.range_5_pct,
        "current_tr_compression_10_40": (
            snapshot.current_tr_compression_10_40
        ),
        "final_contraction_volume_ratio_50": (
            snapshot.final_contraction_volume_ratio_50
        ),
        "base_duration_sessions": snapshot.base_duration_sessions,
        "base_depth_pct": snapshot.base_depth_pct,
        "base_atr_compression_ratio": (
            snapshot.base_atr_compression_ratio
        ),
        "base_volume_dryup_ratio": (
            snapshot.base_volume_dryup_ratio
        ),
        "pivot_price": snapshot.pivot_price,
        "distance_to_pivot_pct": snapshot.distance_to_pivot_pct,
        "distance_to_pivot_atr": snapshot.distance_to_pivot_atr,
        "first_intraday_breach_date": (
            snapshot.first_intraday_breach_date
        ),
        "first_close_break_date": snapshot.first_close_break_date,
        "pivot_broken_by_close": snapshot.pivot_broken_by_close,
        "breakout_volume_ratio_20": snapshot.breakout_volume_ratio_20,
    }


def build_research_observations(
    batch: VCPReplayBatch,
) -> tuple[VCPResearchObservation, ...]:
    """Build one research observation for every causal snapshot.

    A future outcome failure never removes the historical snapshot.

    Complete replay rows supply outcome labels. An OUTCOME skip supplies
    an explicit error while all future-label fields remain ``None``.

    Batch inconsistencies fail closed rather than silently producing a
    partially corrupted research dataset.
    """

    rows_by_security = {
        row.snapshot.security_id: row
        for row in batch.rows
    }

    outcome_skips_by_security = {
        skip.security_id: skip
        for skip in batch.skips
        if skip.stage == "OUTCOME"
    }

    observations: list[VCPResearchObservation] = []

    for snapshot in batch.snapshots:
        security_id = snapshot.security_id

        row = rows_by_security.get(
            security_id
        )

        outcome_skip = outcome_skips_by_security.get(
            security_id
        )

        # A completed outcome row and an OUTCOME failure are mutually
        # exclusive states.
        if row is not None and outcome_skip is not None:
            raise ValueError(
                "snapshot has both replay row and OUTCOME skip "
                f"for security_id={security_id}"
            )

        # A replay row must refer to the exact historical identity
        # represented by the causal batch snapshot.
        if row is not None:
            row_identity = (
                row.snapshot.security_id,
                row.snapshot.ticker,
                row.snapshot.as_of,
            )

            snapshot_identity = (
                snapshot.security_id,
                snapshot.ticker,
                snapshot.as_of,
            )

            if row_identity != snapshot_identity:
                raise ValueError(
                    "replay row snapshot identity does not match "
                    "batch snapshot"
                )

        # If no completed future label exists, the missing outcome must
        # be explicitly explained by the replay layer.
        if row is None and outcome_skip is None:
            raise ValueError(
                "snapshot has no replay row or OUTCOME skip "
                f"for security_id={security_id}"
            )

        # OUTCOME skip identity must also match the causal snapshot.
        if outcome_skip is not None:
            skip_identity = (
                outcome_skip.security_id,
                outcome_skip.ticker,
                outcome_skip.as_of,
            )

            snapshot_identity = (
                snapshot.security_id,
                snapshot.ticker,
                snapshot.as_of,
            )

            if skip_identity != snapshot_identity:
                raise ValueError(
                    "OUTCOME skip snapshot identity does not match "
                    "batch snapshot"
                )

        snapshot_values = _snapshot_fields(
            snapshot
        )

        if row is not None:
            outcome = row.outcome

            observation = VCPResearchObservation(
                **snapshot_values,
                outcome_available=True,
                outcome_error=None,
                reference_close=outcome.reference_close,
                forward_return_5=outcome.forward_return_5,
                forward_return_10=outcome.forward_return_10,
                forward_return_20=outcome.forward_return_20,
                forward_return_40=outcome.forward_return_40,
                mfe_40=outcome.mfe_40,
                mae_40=outcome.mae_40,
            )

        else:
            observation = VCPResearchObservation(
                **snapshot_values,
                outcome_available=False,
                outcome_error=outcome_skip.reason,
                reference_close=None,
                forward_return_5=None,
                forward_return_10=None,
                forward_return_20=None,
                forward_return_40=None,
                mfe_40=None,
                mae_40=None,
            )

        observations.append(
            observation
        )

    return tuple(observations)


@dataclass(frozen=True)
class VCPResearchDataset:
    """Flattened panel of historical VCP research observations."""

    observations: tuple[VCPResearchObservation, ...]


def build_research_dataset(
    grid: VCPReplayGrid,
) -> VCPResearchDataset:
    """Flatten replay-grid batches into one research panel.

    Each causal historical snapshot becomes exactly one research
    observation.

    Batch order is preserved, so an already chronological replay grid
    remains chronological in the resulting dataset. Future outcome
    failures remain explicit through ``VCPResearchObservation`` rather
    than removing snapshots.
    """

    observations: list[VCPResearchObservation] = []

    for batch in grid.batches:
        observations.extend(
            build_research_observations(
                batch
            )
        )

    return VCPResearchDataset(
        observations=tuple(
            observations
        )
    )

