"""Gated prospective reporting for frozen VCP OOS validation.

Performance metrics are produced only when an OOS cross-section is
calendar-mature and has no incomplete +40 outcomes.

Score availability is reported independently. Missing frozen scores do
not alter the methodology or trigger weight/threshold changes.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum

from src.research.vcp_oos import (
    VCPOOSDataset,
    VCPOOSMaturityStatus,
    VCPOOSObservation,
)
from src.research.vcp_quality_report import (
    VCPQualityOutcomeRow,
    compute_monthly_quality_metrics,
)


class VCPOOSEvaluationStatus(str, Enum):
    """Date-level prospective evaluation gate."""

    IMMATURE = "IMMATURE"
    DATA_INCOMPLETE = "DATA_INCOMPLETE"
    READY = "READY"


@dataclass(frozen=True)
class VCPOOSDateReport:
    """One OOS cross-section with gate and optional frozen metrics."""

    as_of: date
    horizon_date_40: date
    available_through: date

    status: VCPOOSEvaluationStatus

    observation_count: int
    outcome_available_count: int
    data_incomplete_count: int

    score_available_count: int
    evaluation_eligible_count: int

    outcome_coverage_pct: float
    score_coverage_pct: float

    ic40: float | None

    q1_count: int
    q5_count: int

    q1_mean_relative_return_40: float | None
    q5_mean_relative_return_40: float | None
    q5_minus_q1_relative_return_40: float | None


def _validate_date_group(
    items: Sequence[VCPOOSObservation],
) -> tuple[date, date]:
    """Validate shared horizon and data horizon for one as-of date."""

    horizon_dates = {
        item.horizon_date_40
        for item in items
    }

    if None in horizon_dates:
        raise ValueError(
            "OOS observations must have a +40 horizon date"
        )

    if len(horizon_dates) != 1:
        raise ValueError(
            "same-date OOS observations have inconsistent +40 horizons"
        )

    available_dates = {
        item.available_through
        for item in items
    }

    if len(available_dates) != 1:
        raise ValueError(
            "same-date OOS observations have inconsistent data horizons"
        )

    horizon_date = next(
        iter(horizon_dates)
    )

    available_through = next(
        iter(available_dates)
    )

    assert horizon_date is not None

    return (
        horizon_date,
        available_through,
    )


def _date_status(
    items: Sequence[VCPOOSObservation],
) -> VCPOOSEvaluationStatus:
    """Fail closed when a date is not fully ready for evaluation."""

    statuses = {
        item.status
        for item in items
    }

    if VCPOOSMaturityStatus.NOT_OOS in statuses:
        raise ValueError(
            "NOT_OOS observations cannot enter an OOS date report"
        )

    if VCPOOSMaturityStatus.IMMATURE in statuses:
        if len(statuses) != 1:
            raise ValueError(
                "IMMATURE cannot be mixed with mature statuses "
                "for the same as-of date"
            )

        return VCPOOSEvaluationStatus.IMMATURE

    if VCPOOSMaturityStatus.DATA_INCOMPLETE in statuses:
        return VCPOOSEvaluationStatus.DATA_INCOMPLETE

    if statuses == {
        VCPOOSMaturityStatus.MATURE
    }:
        return VCPOOSEvaluationStatus.READY

    raise ValueError(
        f"unsupported OOS maturity combination: {statuses}"
    )


def _ready_metrics(
    items: Sequence[VCPOOSObservation],
):
    """Compute frozen metrics only from score-eligible mature observations."""

    rows = tuple(
        VCPQualityOutcomeRow(
            as_of=item.as_of,
            ticker=item.ticker,
            score=float(item.score),
            relative_return_40=float(
                item.relative_return_40
            ),
        )
        for item in items
        if item.evaluation_eligible
        and item.score is not None
        and item.relative_return_40 is not None
    )

    if not rows:
        return None

    metrics = compute_monthly_quality_metrics(
        rows
    )

    if len(metrics) != 1:
        raise ValueError(
            "ready OOS metrics must contain exactly one as-of date"
        )

    return metrics[0]


def build_oos_date_reports(
    dataset: VCPOOSDataset,
) -> tuple[VCPOOSDateReport, ...]:
    """Build gated OOS reports independently for each prospective date."""

    by_date: dict[
        date,
        list[VCPOOSObservation],
    ] = defaultdict(list)

    for item in dataset.observations:
        if item.is_oos:
            by_date[item.as_of].append(
                item
            )

    reports: list[
        VCPOOSDateReport
    ] = []

    for as_of in sorted(by_date):
        items = tuple(
            by_date[as_of]
        )

        (
            horizon_date,
            available_through,
        ) = _validate_date_group(
            items
        )

        status = _date_status(
            items
        )

        observation_count = len(
            items
        )

        outcome_available_count = sum(
            item.outcome_available
            for item in items
        )

        data_incomplete_count = sum(
            item.status
            is VCPOOSMaturityStatus.DATA_INCOMPLETE
            for item in items
        )

        score_available_count = sum(
            item.score_available
            for item in items
        )

        evaluation_eligible_count = sum(
            item.evaluation_eligible
            for item in items
        )

        metrics = (
            _ready_metrics(items)
            if status
            is VCPOOSEvaluationStatus.READY
            else None
        )

        reports.append(
            VCPOOSDateReport(
                as_of=as_of,
                horizon_date_40=horizon_date,
                available_through=available_through,
                status=status,
                observation_count=observation_count,
                outcome_available_count=outcome_available_count,
                data_incomplete_count=data_incomplete_count,
                score_available_count=score_available_count,
                evaluation_eligible_count=(
                    evaluation_eligible_count
                ),
                outcome_coverage_pct=(
                    outcome_available_count
                    / observation_count
                ),
                score_coverage_pct=(
                    score_available_count
                    / observation_count
                ),
                ic40=(
                    metrics.ic40
                    if metrics is not None
                    else None
                ),
                q1_count=(
                    metrics.q1_count
                    if metrics is not None
                    else 0
                ),
                q5_count=(
                    metrics.q5_count
                    if metrics is not None
                    else 0
                ),
                q1_mean_relative_return_40=(
                    metrics.q1_mean_relative_return_40
                    if metrics is not None
                    else None
                ),
                q5_mean_relative_return_40=(
                    metrics.q5_mean_relative_return_40
                    if metrics is not None
                    else None
                ),
                q5_minus_q1_relative_return_40=(
                    metrics.q5_minus_q1_relative_return_40
                    if metrics is not None
                    else None
                ),
            )
        )

    return tuple(
        reports
    )
