"""Pre-registered evaluation of sealed prospective VCP shadow selections.

This module evaluates only securities already sealed in a shadow-selection
artifact. It does not rebuild Q5, re-rank scores, optimize weights, apply
market-regime filters, or modify production ranking.

Primary metric:
    sealed-weight mean +40 relative return.

Performance remains blocked until the artifact horizon is calendar-mature
and every sealed selected ticker has one finite mature +40 outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from math import isfinite
from typing import Any

from src.research.vcp_oos import (
    VCPOOSDataset,
    VCPOOSMaturityStatus,
)
from src.research.vcp_shadow_artifact import (
    verify_shadow_artifact_payload,
)
from src.research.vcp_shadow_selection import (
    SHADOW_SELECTION_POLICY,
    SHADOW_SELECTION_Q5_MIN_PERCENTILE,
)


class VCPShadowEvaluationError(RuntimeError):
    """Raised when sealed shadow evaluation invariants are violated."""


class VCPShadowEvaluationStatus(str, Enum):
    IMMATURE = "IMMATURE"
    DATA_INCOMPLETE = "DATA_INCOMPLETE"
    READY = "READY"


@dataclass(frozen=True)
class VCPShadowEvaluationReport:
    as_of: date
    horizon_date_40: date
    available_through: date

    status: VCPShadowEvaluationStatus

    artifact_sha256: str

    selected_count: int
    matched_count: int
    outcome_available_count: int
    outcome_coverage_pct: float

    shadow_mean_relative_return_40: float | None


def _validate_artifact(
    artifact: dict[str, Any],
) -> tuple[date, date, tuple[dict[str, Any], ...]]:
    if not verify_shadow_artifact_payload(
        artifact
    ):
        raise VCPShadowEvaluationError(
            "shadow artifact SHA-256 verification failed"
        )

    if artifact.get("outcomes_included") is not False:
        raise VCPShadowEvaluationError(
            "shadow artifact must exclude outcomes"
        )

    policy = artifact.get("policy")

    if not isinstance(policy, dict):
        raise VCPShadowEvaluationError(
            "shadow artifact has no valid policy"
        )

    expected_policy = {
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
    }

    if policy != expected_policy:
        raise VCPShadowEvaluationError(
            "shadow artifact policy drift detected"
        )

    try:
        as_of = date.fromisoformat(
            str(artifact["as_of"])
        )
        horizon = date.fromisoformat(
            str(artifact["horizon_date_40"])
        )
    except (KeyError, ValueError) as exc:
        raise VCPShadowEvaluationError(
            "shadow artifact has invalid dates"
        ) from exc

    rows_raw = artifact.get("rows")

    if not isinstance(rows_raw, list):
        raise VCPShadowEvaluationError(
            "shadow artifact has no valid rows"
        )

    rows = tuple(rows_raw)

    selected_count = artifact.get(
        "selected_count"
    )

    if (
        not isinstance(selected_count, int)
        or selected_count <= 0
        or selected_count != len(rows)
    ):
        raise VCPShadowEvaluationError(
            "shadow artifact selected_count mismatch"
        )

    tickers: list[str] = []
    weights: list[float] = []

    for row in rows:
        if not isinstance(row, dict):
            raise VCPShadowEvaluationError(
                "shadow artifact row is invalid"
            )

        ticker = row.get("ticker")

        if not isinstance(ticker, str) or not ticker:
            raise VCPShadowEvaluationError(
                "shadow artifact row has invalid ticker"
            )

        try:
            weight = float(row["weight"])
        except (KeyError, TypeError, ValueError) as exc:
            raise VCPShadowEvaluationError(
                "shadow artifact row has invalid weight"
            ) from exc

        if not isfinite(weight) or weight <= 0:
            raise VCPShadowEvaluationError(
                "shadow artifact row has invalid weight"
            )

        tickers.append(ticker)
        weights.append(weight)

    if len(tickers) != len(set(tickers)):
        raise VCPShadowEvaluationError(
            "shadow artifact contains duplicate tickers"
        )

    if abs(sum(weights) - 1.0) > 1e-12:
        raise VCPShadowEvaluationError(
            "shadow artifact weights must sum to 1"
        )

    expected_weight = 1.0 / len(rows)

    if any(
        abs(weight - expected_weight) > 1e-12
        for weight in weights
    ):
        raise VCPShadowEvaluationError(
            "shadow artifact equal-weight policy drift detected"
        )

    return as_of, horizon, rows


def evaluate_shadow_artifact(
    artifact: dict[str, Any],
    dataset: VCPOOSDataset,
) -> VCPShadowEvaluationReport:
    """Evaluate one sealed selection without rebuilding the selection."""

    as_of, horizon, rows = _validate_artifact(
        artifact
    )

    same_date = tuple(
        item
        for item in dataset.observations
        if item.as_of == as_of
    )

    if not same_date:
        raise VCPShadowEvaluationError(
            "OOS dataset has no observations for artifact date"
        )

    available_dates = {
        item.available_through
        for item in same_date
    }

    if len(available_dates) != 1:
        raise VCPShadowEvaluationError(
            "same-date OOS observations have inconsistent data horizons"
        )

    available_through = next(
        iter(available_dates)
    )

    by_ticker = {}

    for item in same_date:
        if item.ticker in by_ticker:
            raise VCPShadowEvaluationError(
                "same-date OOS dataset contains duplicate ticker"
            )

        if (
            item.horizon_date_40 is not None
            and item.horizon_date_40 != horizon
        ):
            raise VCPShadowEvaluationError(
                "OOS observation horizon does not match sealed artifact"
            )

        if (
            item.status
            is VCPOOSMaturityStatus.NOT_OOS
        ):
            raise VCPShadowEvaluationError(
                "NOT_OOS observation cannot evaluate shadow artifact"
            )

        by_ticker[item.ticker] = item

    selected_count = len(rows)

    matched = [
        (row, by_ticker[row["ticker"]])
        for row in rows
        if row["ticker"] in by_ticker
    ]

    matched_count = len(matched)

    outcome_available_count = sum(
        item.status
        is VCPOOSMaturityStatus.MATURE
        and item.relative_return_40 is not None
        and isfinite(
            float(item.relative_return_40)
        )
        for _, item in matched
    )

    coverage = (
        outcome_available_count
        / selected_count
    )

    if available_through < horizon:
        return VCPShadowEvaluationReport(
            as_of=as_of,
            horizon_date_40=horizon,
            available_through=available_through,
            status=VCPShadowEvaluationStatus.IMMATURE,
            artifact_sha256=str(
                artifact["artifact_sha256"]
            ),
            selected_count=selected_count,
            matched_count=matched_count,
            outcome_available_count=(
                outcome_available_count
            ),
            outcome_coverage_pct=coverage,
            shadow_mean_relative_return_40=None,
        )

    complete = (
        matched_count == selected_count
        and outcome_available_count
        == selected_count
    )

    if not complete:
        return VCPShadowEvaluationReport(
            as_of=as_of,
            horizon_date_40=horizon,
            available_through=available_through,
            status=(
                VCPShadowEvaluationStatus.DATA_INCOMPLETE
            ),
            artifact_sha256=str(
                artifact["artifact_sha256"]
            ),
            selected_count=selected_count,
            matched_count=matched_count,
            outcome_available_count=(
                outcome_available_count
            ),
            outcome_coverage_pct=coverage,
            shadow_mean_relative_return_40=None,
        )

    weighted_return = sum(
        float(row["weight"])
        * float(item.relative_return_40)
        for row, item in matched
    )

    return VCPShadowEvaluationReport(
        as_of=as_of,
        horizon_date_40=horizon,
        available_through=available_through,
        status=VCPShadowEvaluationStatus.READY,
        artifact_sha256=str(
            artifact["artifact_sha256"]
        ),
        selected_count=selected_count,
        matched_count=matched_count,
        outcome_available_count=(
            outcome_available_count
        ),
        outcome_coverage_pct=coverage,
        shadow_mean_relative_return_40=(
            weighted_return
        ),
    )


@dataclass(frozen=True)
class VCPShadowEvaluationSummary:
    month_count: int
    ready_month_count: int

    status: VCPShadowEvaluationStatus

    mean_monthly_shadow_relative_return_40: float | None
    positive_months: int


def summarize_shadow_evaluations(
    reports: tuple[VCPShadowEvaluationReport, ...],
) -> VCPShadowEvaluationSummary:
    """Equal-weight months; never weight by selected security count."""

    if not reports:
        raise VCPShadowEvaluationError(
            "shadow evaluation summary requires at least one report"
        )

    as_of_dates = [
        report.as_of
        for report in reports
    ]

    if len(as_of_dates) != len(
        set(as_of_dates)
    ):
        raise VCPShadowEvaluationError(
            "duplicate shadow evaluation dates are not allowed"
        )

    ready = tuple(
        report
        for report in reports
        if (
            report.status
            is VCPShadowEvaluationStatus.READY
        )
    )

    if any(
        report.status
        is VCPShadowEvaluationStatus.DATA_INCOMPLETE
        for report in reports
    ):
        status = (
            VCPShadowEvaluationStatus.DATA_INCOMPLETE
        )

    elif any(
        report.status
        is VCPShadowEvaluationStatus.IMMATURE
        for report in reports
    ):
        status = VCPShadowEvaluationStatus.IMMATURE

    else:
        status = VCPShadowEvaluationStatus.READY

    if status is not VCPShadowEvaluationStatus.READY:
        return VCPShadowEvaluationSummary(
            month_count=len(reports),
            ready_month_count=len(ready),
            status=status,
            mean_monthly_shadow_relative_return_40=None,
            positive_months=sum(
                (
                    report.shadow_mean_relative_return_40
                    is not None
                    and report.shadow_mean_relative_return_40
                    > 0
                )
                for report in ready
            ),
        )

    monthly_returns = tuple(
        report.shadow_mean_relative_return_40
        for report in ready
    )

    if any(
        value is None
        for value in monthly_returns
    ):
        raise VCPShadowEvaluationError(
            "READY shadow report has no performance metric"
        )

    values = tuple(
        float(value)
        for value in monthly_returns
        if value is not None
    )

    return VCPShadowEvaluationSummary(
        month_count=len(reports),
        ready_month_count=len(ready),
        status=VCPShadowEvaluationStatus.READY,
        mean_monthly_shadow_relative_return_40=(
            sum(values) / len(values)
        ),
        positive_months=sum(
            value > 0
            for value in values
        ),
    )
