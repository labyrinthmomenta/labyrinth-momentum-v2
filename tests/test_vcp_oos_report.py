from datetime import date

import pytest

from src.research.vcp_oos import (
    VCPOOSDataset,
    VCPOOSMaturityStatus,
    VCPOOSObservation,
)
from src.research.vcp_oos_report import (
    VCPOOSEvaluationStatus,
    build_oos_date_reports,
)


DAY_1 = date(2026, 8, 31)
DAY_1_HORIZON = date(2026, 10, 26)

DAY_2 = date(2026, 9, 30)
DAY_2_HORIZON = date(2026, 11, 26)

AVAILABLE = date(2026, 12, 1)


def _item(
    *,
    as_of=DAY_1,
    horizon=DAY_1_HORIZON,
    ticker="AAA",
    status=VCPOOSMaturityStatus.MATURE,
    score=0.50,
    outcome=0.10,
    available_through=AVAILABLE,
):
    score_available = (
        score is not None
    )

    return VCPOOSObservation(
        as_of=as_of,
        ticker=ticker,
        horizon_date_40=horizon,
        available_through=available_through,
        status=status,
        score=score,
        relative_return_40=outcome,
        score_available=score_available,
    )


def test_immature_date_never_produces_performance_metrics():
    dataset = VCPOOSDataset(
        observations=(
            _item(
                status=VCPOOSMaturityStatus.IMMATURE,
                outcome=None,
                available_through=date(
                    2026,
                    10,
                    9,
                ),
            ),
        )
    )

    report = build_oos_date_reports(
        dataset
    )[0]

    assert (
        report.status
        is VCPOOSEvaluationStatus.IMMATURE
    )

    assert report.ic40 is None
    assert report.q5_minus_q1_relative_return_40 is None
    assert report.q1_count == 0
    assert report.q5_count == 0


def test_data_incomplete_date_is_blocked_even_when_other_rows_are_usable():
    items = [
        _item(
            ticker=f"T{i}",
            score=float(i),
            outcome=float(i) / 100.0,
        )
        for i in range(1, 10)
    ]

    items.append(
        _item(
            ticker="MISSING",
            status=VCPOOSMaturityStatus.DATA_INCOMPLETE,
            score=10.0,
            outcome=None,
        )
    )

    report = build_oos_date_reports(
        VCPOOSDataset(
            observations=tuple(items)
        )
    )[0]

    assert (
        report.status
        is VCPOOSEvaluationStatus.DATA_INCOMPLETE
    )

    assert report.observation_count == 10
    assert report.outcome_available_count == 9
    assert report.data_incomplete_count == 1

    assert report.ic40 is None
    assert report.q5_minus_q1_relative_return_40 is None


def test_ready_date_computes_frozen_metrics():
    dataset = VCPOOSDataset(
        observations=tuple(
            _item(
                ticker=f"T{i}",
                score=float(i),
                outcome=float(i) / 100.0,
            )
            for i in range(1, 11)
        )
    )

    report = build_oos_date_reports(
        dataset
    )[0]

    assert (
        report.status
        is VCPOOSEvaluationStatus.READY
    )

    assert report.observation_count == 10
    assert report.evaluation_eligible_count == 10

    assert report.outcome_coverage_pct == pytest.approx(
        1.0
    )
    assert report.score_coverage_pct == pytest.approx(
        1.0
    )

    assert report.ic40 == pytest.approx(
        1.0
    )

    assert report.q1_count == 2
    assert report.q5_count == 2

    assert (
        report.q1_mean_relative_return_40
        == pytest.approx(0.015)
    )

    assert (
        report.q5_mean_relative_return_40
        == pytest.approx(0.095)
    )

    assert (
        report.q5_minus_q1_relative_return_40
        == pytest.approx(0.08)
    )


def test_missing_score_is_reported_as_coverage_not_data_incomplete():
    items = [
        _item(
            ticker=f"T{i}",
            score=float(i),
            outcome=float(i) / 100.0,
        )
        for i in range(1, 10)
    ]

    items.append(
        _item(
            ticker="NO_SCORE",
            score=None,
            outcome=0.20,
        )
    )

    report = build_oos_date_reports(
        VCPOOSDataset(
            observations=tuple(items)
        )
    )[0]

    assert (
        report.status
        is VCPOOSEvaluationStatus.READY
    )

    assert report.observation_count == 10
    assert report.outcome_available_count == 10
    assert report.data_incomplete_count == 0

    assert report.score_available_count == 9
    assert report.evaluation_eligible_count == 9

    assert report.outcome_coverage_pct == pytest.approx(
        1.0
    )
    assert report.score_coverage_pct == pytest.approx(
        0.9
    )

    assert report.ic40 is not None


def test_non_oos_observations_are_not_reported():
    item = VCPOOSObservation(
        as_of=date(2026, 7, 31),
        ticker="PRE",
        horizon_date_40=None,
        available_through=AVAILABLE,
        status=VCPOOSMaturityStatus.NOT_OOS,
        score=0.50,
        relative_return_40=0.10,
        score_available=True,
    )

    reports = build_oos_date_reports(
        VCPOOSDataset(
            observations=(item,)
        )
    )

    assert reports == ()


def test_multiple_oos_dates_are_gated_independently():
    mature_items = tuple(
        _item(
            as_of=DAY_1,
            horizon=DAY_1_HORIZON,
            ticker=f"A{i}",
            score=float(i),
            outcome=float(i) / 100.0,
        )
        for i in range(1, 6)
    )

    immature_items = tuple(
        _item(
            as_of=DAY_2,
            horizon=DAY_2_HORIZON,
            ticker=f"B{i}",
            status=VCPOOSMaturityStatus.IMMATURE,
            score=float(i),
            outcome=None,
            available_through=date(
                2026,
                10,
                9,
            ),
        )
        for i in range(1, 6)
    )

    reports = build_oos_date_reports(
        VCPOOSDataset(
            observations=(
                *mature_items,
                *immature_items,
            )
        )
    )

    assert len(reports) == 2

    assert reports[0].as_of == DAY_1
    assert (
        reports[0].status
        is VCPOOSEvaluationStatus.READY
    )
    assert reports[0].ic40 is not None

    assert reports[1].as_of == DAY_2
    assert (
        reports[1].status
        is VCPOOSEvaluationStatus.IMMATURE
    )
    assert reports[1].ic40 is None


def test_inconsistent_horizon_dates_fail_closed():
    dataset = VCPOOSDataset(
        observations=(
            _item(
                ticker="AAA",
            ),
            _item(
                ticker="BBB",
                horizon=date(
                    2026,
                    10,
                    27,
                ),
            ),
        )
    )

    with pytest.raises(
        ValueError,
        match="inconsistent \\+40 horizons",
    ):
        build_oos_date_reports(
            dataset
        )


def test_immature_cannot_mix_with_mature_same_date():
    dataset = VCPOOSDataset(
        observations=(
            _item(
                ticker="AAA",
                status=VCPOOSMaturityStatus.MATURE,
            ),
            _item(
                ticker="BBB",
                status=VCPOOSMaturityStatus.IMMATURE,
                outcome=None,
            ),
        )
    )

    with pytest.raises(
        ValueError,
        match="IMMATURE cannot be mixed",
    ):
        build_oos_date_reports(
            dataset
        )
