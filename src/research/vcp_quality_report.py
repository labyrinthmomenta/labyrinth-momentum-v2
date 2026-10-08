"""Deterministic reporting for the frozen VCP research quality score.

This module evaluates already-computed research quality scores against
same-date relative forward outcomes.

It does not:

- build the VCP cohort,
- change the frozen ATR_VOL_EQ score,
- optimize weights,
- modify production ranking,
- incorporate market regime into the score.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from math import isfinite
from statistics import mean

from src.research.vcp_quality import (
    VCPQualityResearchObservation,
)


@dataclass(frozen=True)
class VCPQualityOutcomeRow:
    """One usable frozen-score / relative-outcome observation."""

    as_of: date
    ticker: str
    score: float
    relative_return_40: float


@dataclass(frozen=True)
class VCPQualityMonthlyMetrics:
    """Same-date quality diagnostics."""

    as_of: date
    observation_count: int
    ic40: float | None
    q1_count: int
    q5_count: int
    q1_mean_relative_return_40: float | None
    q5_mean_relative_return_40: float | None
    q5_minus_q1_relative_return_40: float | None


@dataclass(frozen=True)
class VCPQualitySummary:
    """Equal-weighted summary of monthly diagnostics."""

    month_count: int
    observation_count: int
    mean_monthly_ic40: float | None
    positive_ic40_months: int
    mean_monthly_q5_minus_q1: float | None
    positive_q5_minus_q1_months: int
    mean_monthly_q5: float | None


@dataclass(frozen=True)
class VCPQualityLeaveOneMonthOut:
    """Summary after excluding one monthly cross-section."""

    excluded_as_of: date
    remaining_month_count: int
    mean_monthly_ic40: float | None
    mean_monthly_q5_minus_q1: float | None
    mean_monthly_q5: float | None


def build_quality_outcome_rows(
    observations: Sequence[VCPQualityResearchObservation],
) -> tuple[VCPQualityOutcomeRow, ...]:
    """Keep only observations having finite score and +40 relative outcome."""

    rows: list[VCPQualityOutcomeRow] = []

    for item in observations:
        cross = item.cross_sectional_observation
        relative = cross.relative_observation
        observation = relative.observation

        score = item.atr_vol_eq_score
        outcome = relative.relative_return_40

        if score is None or outcome is None:
            continue

        score = float(score)
        outcome = float(outcome)

        if not (
            isfinite(score)
            and isfinite(outcome)
        ):
            continue

        rows.append(
            VCPQualityOutcomeRow(
                as_of=observation.as_of,
                ticker=observation.ticker,
                score=score,
                relative_return_40=outcome,
            )
        )

    return tuple(rows)


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


def _pearson(
    x: Sequence[float],
    y: Sequence[float],
) -> float | None:
    if len(x) != len(y):
        raise ValueError(
            "x and y must have equal length"
        )

    if len(x) < 2:
        return None

    mean_x = mean(x)
    mean_y = mean(y)

    delta_x = [
        value - mean_x
        for value in x
    ]
    delta_y = [
        value - mean_y
        for value in y
    ]

    scale_x = sum(
        value * value
        for value in delta_x
    ) ** 0.5

    scale_y = sum(
        value * value
        for value in delta_y
    ) ** 0.5

    if scale_x == 0 or scale_y == 0:
        return None

    return (
        sum(
            left * right
            for left, right in zip(
                delta_x,
                delta_y,
            )
        )
        / (scale_x * scale_y)
    )


def _spearman(
    x: Sequence[float],
    y: Sequence[float],
) -> float | None:
    if len(x) < 3:
        return None

    return _pearson(
        _average_ranks(x),
        _average_ranks(y),
    )


def _percentile_ranks(
    values: Sequence[float],
) -> list[float]:
    if not values:
        return []

    if len(values) == 1:
        return [0.5]

    ranks = _average_ranks(values)

    return [
        (rank - 1.0)
        / (len(values) - 1.0)
        for rank in ranks
    ]


def compute_monthly_quality_metrics(
    rows: Sequence[VCPQualityOutcomeRow],
) -> tuple[VCPQualityMonthlyMetrics, ...]:
    """Compute same-date IC40 and frozen score quintile diagnostics."""

    by_date: dict[
        date,
        list[VCPQualityOutcomeRow],
    ] = defaultdict(list)

    for row in rows:
        by_date[row.as_of].append(row)

    results: list[VCPQualityMonthlyMetrics] = []

    for as_of in sorted(by_date):
        group = by_date[as_of]

        scores = [
            row.score
            for row in group
        ]

        outcomes = [
            row.relative_return_40
            for row in group
        ]

        percentiles = _percentile_ranks(
            scores
        )

        q1 = [
            row.relative_return_40
            for row, percentile in zip(
                group,
                percentiles,
            )
            if percentile <= 0.20
        ]

        q5 = [
            row.relative_return_40
            for row, percentile in zip(
                group,
                percentiles,
            )
            if percentile >= 0.80
        ]

        q1_mean = (
            mean(q1)
            if q1
            else None
        )

        q5_mean = (
            mean(q5)
            if q5
            else None
        )

        spread = (
            q5_mean - q1_mean
            if (
                q1_mean is not None
                and q5_mean is not None
            )
            else None
        )

        results.append(
            VCPQualityMonthlyMetrics(
                as_of=as_of,
                observation_count=len(group),
                ic40=_spearman(
                    scores,
                    outcomes,
                ),
                q1_count=len(q1),
                q5_count=len(q5),
                q1_mean_relative_return_40=q1_mean,
                q5_mean_relative_return_40=q5_mean,
                q5_minus_q1_relative_return_40=spread,
            )
        )

    return tuple(results)


def summarize_monthly_quality(
    metrics: Sequence[VCPQualityMonthlyMetrics],
) -> VCPQualitySummary:
    """Equal-weight monthly summary used by frozen research diagnostics."""

    items = tuple(metrics)

    ic_values = [
        item.ic40
        for item in items
        if item.ic40 is not None
    ]

    spread_values = [
        item.q5_minus_q1_relative_return_40
        for item in items
        if (
            item.q5_minus_q1_relative_return_40
            is not None
        )
    ]

    q5_values = [
        item.q5_mean_relative_return_40
        for item in items
        if item.q5_mean_relative_return_40
        is not None
    ]

    return VCPQualitySummary(
        month_count=len(items),
        observation_count=sum(
            item.observation_count
            for item in items
        ),
        mean_monthly_ic40=(
            mean(ic_values)
            if ic_values
            else None
        ),
        positive_ic40_months=sum(
            value > 0
            for value in ic_values
        ),
        mean_monthly_q5_minus_q1=(
            mean(spread_values)
            if spread_values
            else None
        ),
        positive_q5_minus_q1_months=sum(
            value > 0
            for value in spread_values
        ),
        mean_monthly_q5=(
            mean(q5_values)
            if q5_values
            else None
        ),
    )


def compute_leave_one_month_out(
    metrics: Sequence[VCPQualityMonthlyMetrics],
) -> tuple[VCPQualityLeaveOneMonthOut, ...]:
    """Recompute equal-weight summaries after excluding each month."""

    items = tuple(metrics)

    results: list[
        VCPQualityLeaveOneMonthOut
    ] = []

    for excluded in items:
        remaining = tuple(
            item
            for item in items
            if item.as_of != excluded.as_of
        )

        summary = summarize_monthly_quality(
            remaining
        )

        results.append(
            VCPQualityLeaveOneMonthOut(
                excluded_as_of=excluded.as_of,
                remaining_month_count=(
                    summary.month_count
                ),
                mean_monthly_ic40=(
                    summary.mean_monthly_ic40
                ),
                mean_monthly_q5_minus_q1=(
                    summary
                    .mean_monthly_q5_minus_q1
                ),
                mean_monthly_q5=(
                    summary.mean_monthly_q5
                ),
            )
        )

    return tuple(results)
