"""Read-only orchestrator for prospective frozen VCP OOS evaluation.

This module connects the existing research layers without modifying:

- production ranking,
- production VCP defaults,
- the SQLite database,
- the frozen ATR_VOL_EQ methodology.

The research VCP state configuration below is explicitly frozen for
prospective validation. It is not a production default.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import sqlite3

from src.data.calendar import BISTTradingCalendar
from src.research.vcp_cross_sectional import (
    build_cross_sectional_features,
)
from src.research.vcp_dataset import (
    build_research_dataset,
)
from src.research.vcp_oos import (
    build_oos_dataset,
    is_prospective_oos_date,
)
from src.research.vcp_oos_report import (
    VCPOOSDateReport,
    build_oos_date_reports,
)
from src.research.vcp_quality import (
    VCPQualityResearchObservation,
    build_vcp_quality_scores,
    is_frozen_vcp_quality_cohort_member,
)
from src.research.vcp_relative import (
    build_relative_outcomes,
)
from src.research.vcp_replay import (
    build_replay_grid,
)
from src.strategy.vcp_state import (
    VCPStateConfig,
)


FROZEN_RESEARCH_VCP_STATE_CONFIG = VCPStateConfig(
    tightening_range_5_max_pct=5.0,
    tightening_true_range_compression_max=0.75,
    tightening_final_volume_ratio_max=0.75,
    near_pivot_max_distance_pct=5.0,
    breakout_volume_expansion_min_ratio=1.50,
)


class VCPOOSRunError(RuntimeError):
    """Raised when a prospective OOS run cannot be evaluated safely."""


@dataclass(frozen=True)
class VCPOOSRunResult:
    """One read-only prospective OOS run."""

    as_of: date
    available_through: date

    all_observation_count: int
    frozen_cohort_count: int

    quality_observations: tuple[
        VCPQualityResearchObservation,
        ...
    ]

    report: VCPOOSDateReport


def _database_horizon(
    conn: sqlite3.Connection,
) -> date:
    row = conn.execute(
        """
        SELECT MAX(date)
        FROM daily_prices
        """
    ).fetchone()

    if row is None or row[0] is None:
        raise VCPOOSRunError(
            "daily_prices has no available data horizon"
        )

    return date.fromisoformat(
        str(row[0])
    )


def run_frozen_vcp_oos(
    db_path: str | Path,
    *,
    calendar: BISTTradingCalendar,
    as_of: date,
) -> VCPOOSRunResult:
    """Run one prospective frozen VCP OOS cross-section read-only."""

    if not is_prospective_oos_date(
        as_of
    ):
        raise VCPOOSRunError(
            f"{as_of.isoformat()} is not after "
            "the frozen research cutoff"
        )

    path = Path(
        db_path
    ).expanduser().resolve()

    if not path.is_file():
        raise VCPOOSRunError(
            f"database not found: {path}"
        )

    uri = (
        path.as_uri()
        + "?mode=ro"
    )

    conn = sqlite3.connect(
        uri,
        uri=True,
    )

    try:
        available_through = _database_horizon(
            conn
        )

        if as_of > available_through:
            raise VCPOOSRunError(
                f"as_of={as_of.isoformat()} exceeds "
                f"database horizon={available_through.isoformat()}"
            )

        grid = build_replay_grid(
            conn,
            as_of_dates=(as_of,),
            state_config=(
                FROZEN_RESEARCH_VCP_STATE_CONFIG
            ),
        )

    finally:
        conn.close()

    dataset = build_research_dataset(
        grid
    )

    relative = build_relative_outcomes(
        dataset
    )

    cohort = tuple(
        item
        for item in relative.observations
        if is_frozen_vcp_quality_cohort_member(
            item.observation
        )
    )

    if not cohort:
        raise VCPOOSRunError(
            f"no frozen VCP cohort observations "
            f"for {as_of.isoformat()}"
        )

    cross = build_cross_sectional_features(
        cohort
    )

    quality = build_vcp_quality_scores(
        cross.observations
    )

    oos = build_oos_dataset(
        quality,
        calendar=calendar,
        available_through=available_through,
    )

    reports = build_oos_date_reports(
        oos
    )

    if len(reports) != 1:
        raise VCPOOSRunError(
            "expected exactly one OOS date report, "
            f"received {len(reports)}"
        )

    return VCPOOSRunResult(
        as_of=as_of,
        available_through=available_through,
        all_observation_count=len(
            relative.observations
        ),
        frozen_cohort_count=len(
            cohort
        ),
        quality_observations=tuple(
            quality
        ),
        report=reports[0],
    )
