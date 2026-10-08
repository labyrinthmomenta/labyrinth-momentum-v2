from datetime import date
from types import SimpleNamespace

import pytest

from src.research.vcp_quality import (
    VCPQualityResearchObservation,
)
from src.research.vcp_quality_report import (
    VCPQualityOutcomeRow,
    build_quality_outcome_rows,
    compute_leave_one_month_out,
    compute_monthly_quality_metrics,
    summarize_monthly_quality,
)


DAY_1 = date(2026, 6, 30)
DAY_2 = date(2026, 7, 31)


def _quality_observation(
    *,
    as_of,
    ticker,
    score,
    outcome,
):
    observation = SimpleNamespace(
        as_of=as_of,
        ticker=ticker,
    )

    relative = SimpleNamespace(
        observation=observation,
        relative_return_40=outcome,
    )

    cross = SimpleNamespace(
        relative_observation=relative,
    )

    return VCPQualityResearchObservation(
        cross_sectional_observation=cross,
        atr_vol_eq_score=score,
    )


def test_build_quality_outcome_rows_preserves_usable_observations():
    items = (
        _quality_observation(
            as_of=DAY_1,
            ticker="AAA",
            score=0.20,
            outcome=0.10,
        ),
        _quality_observation(
            as_of=DAY_1,
            ticker="BBB",
            score=0.80,
            outcome=0.30,
        ),
    )

    result = build_quality_outcome_rows(
        items
    )

    assert result == (
        VCPQualityOutcomeRow(
            as_of=DAY_1,
            ticker="AAA",
            score=0.20,
            relative_return_40=0.10,
        ),
        VCPQualityOutcomeRow(
            as_of=DAY_1,
            ticker="BBB",
            score=0.80,
            relative_return_40=0.30,
        ),
    )


@pytest.mark.parametrize(
    ("score", "outcome"),
    (
        (None, 0.10),
        (0.50, None),
        (float("nan"), 0.10),
        (0.50, float("nan")),
        (float("inf"), 0.10),
        (0.50, float("-inf")),
    ),
)
def test_build_quality_outcome_rows_fails_closed(
    score,
    outcome,
):
    result = build_quality_outcome_rows(
        (
            _quality_observation(
                as_of=DAY_1,
                ticker="AAA",
                score=score,
                outcome=outcome,
            ),
        )
    )

    assert result == ()


def _row(
    *,
    as_of,
    ticker,
    score,
    outcome,
):
    return VCPQualityOutcomeRow(
        as_of=as_of,
        ticker=ticker,
        score=score,
        relative_return_40=outcome,
    )


def test_monthly_metrics_detect_perfect_monotonic_relationship():
    rows = tuple(
        _row(
            as_of=DAY_1,
            ticker=f"T{i}",
            score=float(i),
            outcome=float(i) / 100.0,
        )
        for i in range(1, 11)
    )

    result = compute_monthly_quality_metrics(
        rows
    )

    assert len(result) == 1

    month = result[0]

    assert month.observation_count == 10
    assert month.ic40 == pytest.approx(1.0)

    assert month.q1_count == 2
    assert month.q5_count == 2

    assert (
        month.q1_mean_relative_return_40
        == pytest.approx(0.015)
    )

    assert (
        month.q5_mean_relative_return_40
        == pytest.approx(0.095)
    )

    assert (
        month.q5_minus_q1_relative_return_40
        == pytest.approx(0.08)
    )


def test_monthly_metrics_are_computed_independently_by_date():
    rows = (
        _row(
            as_of=DAY_1,
            ticker="AAA",
            score=1.0,
            outcome=0.01,
        ),
        _row(
            as_of=DAY_1,
            ticker="BBB",
            score=2.0,
            outcome=0.02,
        ),
        _row(
            as_of=DAY_1,
            ticker="CCC",
            score=3.0,
            outcome=0.03,
        ),
        _row(
            as_of=DAY_2,
            ticker="DDD",
            score=100.0,
            outcome=0.30,
        ),
        _row(
            as_of=DAY_2,
            ticker="EEE",
            score=200.0,
            outcome=0.20,
        ),
        _row(
            as_of=DAY_2,
            ticker="FFF",
            score=300.0,
            outcome=0.10,
        ),
    )

    result = compute_monthly_quality_metrics(
        rows
    )

    assert [item.as_of for item in result] == [
        DAY_1,
        DAY_2,
    ]

    assert result[0].ic40 == pytest.approx(1.0)
    assert result[1].ic40 == pytest.approx(-1.0)


def test_summary_equal_weights_months_not_observations():
    metrics = compute_monthly_quality_metrics(
        (
            _row(
                as_of=DAY_1,
                ticker="A",
                score=1.0,
                outcome=0.01,
            ),
            _row(
                as_of=DAY_1,
                ticker="B",
                score=2.0,
                outcome=0.02,
            ),
            _row(
                as_of=DAY_1,
                ticker="C",
                score=3.0,
                outcome=0.03,
            ),
            _row(
                as_of=DAY_2,
                ticker="D",
                score=1.0,
                outcome=0.03,
            ),
            _row(
                as_of=DAY_2,
                ticker="E",
                score=2.0,
                outcome=0.02,
            ),
            _row(
                as_of=DAY_2,
                ticker="F",
                score=3.0,
                outcome=0.01,
            ),
        )
    )

    summary = summarize_monthly_quality(
        metrics
    )

    assert summary.month_count == 2
    assert summary.observation_count == 6

    assert summary.mean_monthly_ic40 == pytest.approx(
        0.0
    )

    assert summary.positive_ic40_months == 1


def test_leave_one_month_out_excludes_each_date():
    metrics = compute_monthly_quality_metrics(
        (
            _row(
                as_of=DAY_1,
                ticker="A",
                score=1.0,
                outcome=0.01,
            ),
            _row(
                as_of=DAY_1,
                ticker="B",
                score=2.0,
                outcome=0.02,
            ),
            _row(
                as_of=DAY_1,
                ticker="C",
                score=3.0,
                outcome=0.03,
            ),
            _row(
                as_of=DAY_2,
                ticker="D",
                score=1.0,
                outcome=0.03,
            ),
            _row(
                as_of=DAY_2,
                ticker="E",
                score=2.0,
                outcome=0.02,
            ),
            _row(
                as_of=DAY_2,
                ticker="F",
                score=3.0,
                outcome=0.01,
            ),
        )
    )

    result = compute_leave_one_month_out(
        metrics
    )

    assert len(result) == 2

    assert result[0].excluded_as_of == DAY_1
    assert result[0].remaining_month_count == 1
    assert result[0].mean_monthly_ic40 == pytest.approx(
        -1.0
    )

    assert result[1].excluded_as_of == DAY_2
    assert result[1].remaining_month_count == 1
    assert result[1].mean_monthly_ic40 == pytest.approx(
        1.0
    )
