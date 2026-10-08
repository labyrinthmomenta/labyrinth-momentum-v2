"""Frozen VCP quality score for research-only analysis.

This module deliberately keeps VCP setup quality separate from:

- production ranking,
- market-regime context,
- trade-readiness / pivot proximity,
- contraction-depth diagnostics.

The frozen ATR_VOL_EQ score is:

    0.50 * ATR compression percentile
    + 0.50 * volume dry-up percentile

The caller remains responsible for choosing the research cohort before
cross-sectional ranking. No hidden re-ranking or normalization is
performed here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

from src.research.vcp_cross_sectional import (
    VCPCrossSectionalObservation,
)
from src.research.vcp_dataset import (
    VCPResearchObservation,
)


ATR_VOL_EQ_ATR_WEIGHT = 0.50
ATR_VOL_EQ_VOLUME_WEIGHT = 0.50

VCP_QUALITY_MIN_HISTORY_SESSIONS = 80


@dataclass(frozen=True)
class VCPQualityResearchObservation:
    """One cross-sectional observation with its frozen quality score."""

    cross_sectional_observation: VCPCrossSectionalObservation
    atr_vol_eq_score: float | None


def is_frozen_vcp_quality_cohort_member(
    observation: VCPResearchObservation,
) -> bool:
    """Return whether an observation belongs to the frozen research cohort.

    Frozen methodology:

    - at least 80 historical sessions,
    - structurally valid VCP,
    - pre-breakout: pivot not yet broken by close.
    """

    return (
        observation.history_sessions
        >= VCP_QUALITY_MIN_HISTORY_SESSIONS
        and observation.structurally_valid
        and not observation.pivot_broken_by_close
    )


def compute_atr_vol_eq_score(
    *,
    base_atr_compression_percentile: float | None,
    base_volume_dryup_percentile: float | None,
) -> float | None:
    """Compute the frozen 50/50 ATR-volume VCP quality score.

    Missing or non-finite inputs fail closed to ``None``.

    No clipping, re-ranking, regime adjustment, depth adjustment,
    pivot-distance adjustment, or weight optimization is performed.
    """

    if (
        base_atr_compression_percentile is None
        or base_volume_dryup_percentile is None
    ):
        return None

    atr = float(
        base_atr_compression_percentile
    )
    volume = float(
        base_volume_dryup_percentile
    )

    if not (
        isfinite(atr)
        and isfinite(volume)
    ):
        return None

    return (
        ATR_VOL_EQ_ATR_WEIGHT * atr
        + ATR_VOL_EQ_VOLUME_WEIGHT * volume
    )


def build_vcp_quality_scores(
    observations: Sequence[
        VCPCrossSectionalObservation
    ],
) -> tuple[VCPQualityResearchObservation, ...]:
    """Attach the frozen research score without changing cohort semantics.

    Input order and observation identity are preserved.
    """

    return tuple(
        VCPQualityResearchObservation(
            cross_sectional_observation=observation,
            atr_vol_eq_score=compute_atr_vol_eq_score(
                base_atr_compression_percentile=(
                    observation
                    .base_atr_compression_percentile
                ),
                base_volume_dryup_percentile=(
                    observation
                    .base_volume_dryup_percentile
                ),
            ),
        )
        for observation in observations
    )
