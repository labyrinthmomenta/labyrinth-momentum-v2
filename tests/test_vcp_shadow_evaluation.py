from datetime import datetime, date, timezone

import pytest

from src.research.vcp_oos import (
    VCPOOSDataset,
    VCPOOSMaturityStatus,
    VCPOOSObservation,
)
from src.research.vcp_shadow_artifact import (
    build_shadow_artifact_payload,
)
from src.research.vcp_shadow_evaluation import (
    VCPShadowEvaluationError,
    VCPShadowEvaluationStatus,
    evaluate_shadow_artifact,
)
from src.research.vcp_shadow_selection import (
    VCPShadowSelection,
    VCPShadowSelectionRow,
)


AS_OF = date(2026, 8, 31)
HORIZON = date(2026, 10, 26)


def _artifact():
    selection = VCPShadowSelection(
        as_of=AS_OF.isoformat(),
        horizon_date_40=HORIZON.isoformat(),
        source_snapshot_sha256="a" * 64,
        score_available_count=10,
        selected_count=2,
        rows=(
            VCPShadowSelectionRow(
                security_id=1,
                ticker="AAA",
                score=0.90,
                percentile=1.00,
                weight=0.50,
            ),
            VCPShadowSelectionRow(
                security_id=2,
                ticker="BBB",
                score=0.80,
                percentile=0.80,
                weight=0.50,
            ),
        ),
    )

    return build_shadow_artifact_payload(
        selection,
        policy_git_commit="b" * 40,
        created_at_utc=datetime(
            2026,
            10,
            10,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )


def _item(
    ticker,
    *,
    status=VCPOOSMaturityStatus.MATURE,
    outcome=0.10,
    available_through=HORIZON,
):
    return VCPOOSObservation(
        as_of=AS_OF,
        ticker=ticker,
        horizon_date_40=HORIZON,
        available_through=available_through,
        status=status,
        score=0.50,
        relative_return_40=outcome,
        score_available=True,
    )


def test_immature_shadow_evaluation_never_exposes_performance():
    report = evaluate_shadow_artifact(
        _artifact(),
        VCPOOSDataset(
            observations=(
                _item(
                    "AAA",
                    status=VCPOOSMaturityStatus.IMMATURE,
                    outcome=None,
                    available_through=date(
                        2026,
                        10,
                        9,
                    ),
                ),
                _item(
                    "BBB",
                    status=VCPOOSMaturityStatus.IMMATURE,
                    outcome=None,
                    available_through=date(
                        2026,
                        10,
                        9,
                    ),
                ),
            )
        ),
    )

    assert (
        report.status
        is VCPShadowEvaluationStatus.IMMATURE
    )
    assert (
        report.shadow_mean_relative_return_40
        is None
    )


def test_ready_shadow_evaluation_uses_sealed_weights():
    dataset = VCPOOSDataset(
        observations=(
            _item("AAA", outcome=0.20),
            _item("BBB", outcome=-0.10),
            _item("UNSELECTED", outcome=9.99),
        )
    )

    report = evaluate_shadow_artifact(
        _artifact(),
        dataset,
    )

    assert (
        report.status
        is VCPShadowEvaluationStatus.READY
    )
    assert report.selected_count == 2
    assert report.matched_count == 2
    assert report.outcome_available_count == 2
    assert report.outcome_coverage_pct == pytest.approx(
        1.0
    )
    assert (
        report.shadow_mean_relative_return_40
        == pytest.approx(0.05)
    )


def test_mature_missing_selected_outcome_is_data_incomplete():
    report = evaluate_shadow_artifact(
        _artifact(),
        VCPOOSDataset(
            observations=(
                _item("AAA", outcome=0.20),
                _item(
                    "BBB",
                    status=(
                        VCPOOSMaturityStatus.DATA_INCOMPLETE
                    ),
                    outcome=None,
                ),
            )
        ),
    )

    assert (
        report.status
        is VCPShadowEvaluationStatus.DATA_INCOMPLETE
    )
    assert report.outcome_available_count == 1
    assert (
        report.shadow_mean_relative_return_40
        is None
    )


def test_mature_missing_selected_ticker_is_data_incomplete():
    report = evaluate_shadow_artifact(
        _artifact(),
        VCPOOSDataset(
            observations=(
                _item("AAA", outcome=0.20),
                _item("UNSELECTED", outcome=0.30),
            )
        ),
    )

    assert (
        report.status
        is VCPShadowEvaluationStatus.DATA_INCOMPLETE
    )
    assert report.matched_count == 1
    assert (
        report.shadow_mean_relative_return_40
        is None
    )


def test_mutated_shadow_artifact_fails_closed():
    artifact = _artifact()
    artifact["rows"][0]["weight"] = 0.40

    with pytest.raises(
        VCPShadowEvaluationError,
        match="SHA-256",
    ):
        evaluate_shadow_artifact(
            artifact,
            VCPOOSDataset(
                observations=(
                    _item("AAA"),
                    _item("BBB"),
                )
            ),
        )


def test_horizon_mismatch_fails_closed():
    item = VCPOOSObservation(
        as_of=AS_OF,
        ticker="AAA",
        horizon_date_40=date(
            2026,
            10,
            27,
        ),
        available_through=HORIZON,
        status=VCPOOSMaturityStatus.MATURE,
        score=0.50,
        relative_return_40=0.10,
        score_available=True,
    )

    with pytest.raises(
        VCPShadowEvaluationError,
        match="horizon",
    ):
        evaluate_shadow_artifact(
            _artifact(),
            VCPOOSDataset(
                observations=(
                    item,
                    _item("BBB"),
                )
            ),
        )


def _report(
    *,
    as_of,
    status,
    value,
):
    from src.research.vcp_shadow_evaluation import (
        VCPShadowEvaluationReport,
    )

    return VCPShadowEvaluationReport(
        as_of=as_of,
        horizon_date_40=HORIZON,
        available_through=HORIZON,
        status=status,
        artifact_sha256="c" * 64,
        selected_count=2,
        matched_count=2,
        outcome_available_count=(
            2
            if status
            is VCPShadowEvaluationStatus.READY
            else 0
        ),
        outcome_coverage_pct=(
            1.0
            if status
            is VCPShadowEvaluationStatus.READY
            else 0.0
        ),
        shadow_mean_relative_return_40=value,
    )


def test_shadow_summary_equal_weights_months():
    from src.research.vcp_shadow_evaluation import (
        summarize_shadow_evaluations,
    )

    summary = summarize_shadow_evaluations(
        (
            _report(
                as_of=date(2026, 8, 31),
                status=VCPShadowEvaluationStatus.READY,
                value=0.10,
            ),
            _report(
                as_of=date(2026, 9, 30),
                status=VCPShadowEvaluationStatus.READY,
                value=-0.02,
            ),
        )
    )

    assert (
        summary.status
        is VCPShadowEvaluationStatus.READY
    )
    assert summary.month_count == 2
    assert summary.ready_month_count == 2
    assert summary.positive_months == 1
    assert (
        summary.mean_monthly_shadow_relative_return_40
        == pytest.approx(0.04)
    )


def test_shadow_summary_blocks_while_any_month_is_immature():
    from src.research.vcp_shadow_evaluation import (
        summarize_shadow_evaluations,
    )

    summary = summarize_shadow_evaluations(
        (
            _report(
                as_of=date(2026, 8, 31),
                status=VCPShadowEvaluationStatus.READY,
                value=0.10,
            ),
            _report(
                as_of=date(2026, 9, 30),
                status=VCPShadowEvaluationStatus.IMMATURE,
                value=None,
            ),
        )
    )

    assert (
        summary.status
        is VCPShadowEvaluationStatus.IMMATURE
    )
    assert summary.ready_month_count == 1
    assert (
        summary.mean_monthly_shadow_relative_return_40
        is None
    )


def test_shadow_summary_data_incomplete_blocks_performance():
    from src.research.vcp_shadow_evaluation import (
        summarize_shadow_evaluations,
    )

    summary = summarize_shadow_evaluations(
        (
            _report(
                as_of=date(2026, 8, 31),
                status=(
                    VCPShadowEvaluationStatus.DATA_INCOMPLETE
                ),
                value=None,
            ),
            _report(
                as_of=date(2026, 9, 30),
                status=VCPShadowEvaluationStatus.READY,
                value=0.08,
            ),
        )
    )

    assert (
        summary.status
        is VCPShadowEvaluationStatus.DATA_INCOMPLETE
    )
    assert (
        summary.mean_monthly_shadow_relative_return_40
        is None
    )


def test_shadow_summary_rejects_duplicate_dates():
    from src.research.vcp_shadow_evaluation import (
        summarize_shadow_evaluations,
    )

    report = _report(
        as_of=date(2026, 8, 31),
        status=VCPShadowEvaluationStatus.READY,
        value=0.10,
    )

    with pytest.raises(
        VCPShadowEvaluationError,
        match="duplicate",
    ):
        summarize_shadow_evaluations(
            (report, report)
        )
