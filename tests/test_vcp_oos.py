from datetime import date
from types import SimpleNamespace

from src.data.calendar import BISTTradingCalendar
from src.research.vcp_oos import (
    VCP_QUALITY_FORWARD_HORIZON,
    VCP_QUALITY_RESEARCH_FREEZE_DATE,
    VCPOOSMaturityStatus,
    build_oos_dataset,
    forward_trading_session_date,
    is_prospective_oos_date,
)
from src.research.vcp_quality import (
    VCPQualityResearchObservation,
)


def _calendar() -> BISTTradingCalendar:
    # No exceptions needed for these synthetic January 2026 tests.
    return BISTTradingCalendar(
        exceptions=[],
        covered_years={2026},
    )


def _quality_observation(
    *,
    as_of,
    ticker="AAA",
    score=0.50,
    outcome=0.10,
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


def test_freeze_date_and_horizon_are_fixed():
    assert VCP_QUALITY_RESEARCH_FREEZE_DATE == date(
        2026,
        7,
        31,
    )

    assert VCP_QUALITY_FORWARD_HORIZON == 40


def test_freeze_date_itself_is_not_oos():
    assert not is_prospective_oos_date(
        date(2026, 7, 31)
    )


def test_first_day_after_freeze_is_oos():
    assert is_prospective_oos_date(
        date(2026, 8, 1)
    )


def test_forward_session_count_excludes_as_of_and_weekends():
    calendar = _calendar()

    result = forward_trading_session_date(
        calendar,
        as_of=date(2026, 1, 2),  # Friday
        sessions_ahead=2,
    )

    # Monday Jan 5 = +1, Tuesday Jan 6 = +2.
    assert result == date(
        2026,
        1,
        6,
    )


def test_pre_freeze_observation_is_not_oos():
    dataset = build_oos_dataset(
        (
            _quality_observation(
                as_of=date(2026, 7, 31),
            ),
        ),
        calendar=_calendar(),
        available_through=date(
            2026,
            12,
            31,
        ),
    )

    item = dataset.observations[0]

    assert (
        item.status
        is VCPOOSMaturityStatus.NOT_OOS
    )

    assert not item.is_oos
    assert not item.calendar_mature
    assert not item.evaluation_eligible


def test_calendar_immature_even_if_outcome_is_present():
    calendar = _calendar()

    as_of = date(2026, 8, 3)

    horizon = forward_trading_session_date(
        calendar,
        as_of=as_of,
        sessions_ahead=40,
    )

    dataset = build_oos_dataset(
        (
            _quality_observation(
                as_of=as_of,
                score=0.70,
                outcome=0.12,
            ),
        ),
        calendar=calendar,
        available_through=date(
            2026,
            8,
            31,
        ),
    )

    item = dataset.observations[0]

    assert horizon > date(
        2026,
        8,
        31,
    )

    assert (
        item.status
        is VCPOOSMaturityStatus.IMMATURE
    )

    assert not item.calendar_mature
    assert not item.evaluation_eligible


def test_calendar_mature_with_outcome_is_mature():
    calendar = _calendar()

    as_of = date(2026, 8, 3)

    horizon = forward_trading_session_date(
        calendar,
        as_of=as_of,
        sessions_ahead=40,
    )

    dataset = build_oos_dataset(
        (
            _quality_observation(
                as_of=as_of,
                score=0.70,
                outcome=0.12,
            ),
        ),
        calendar=calendar,
        available_through=horizon,
    )

    item = dataset.observations[0]

    assert (
        item.status
        is VCPOOSMaturityStatus.MATURE
    )

    assert item.calendar_mature
    assert item.outcome_available
    assert item.evaluation_eligible


def test_calendar_mature_without_outcome_is_data_incomplete():
    calendar = _calendar()

    as_of = date(2026, 8, 3)

    horizon = forward_trading_session_date(
        calendar,
        as_of=as_of,
        sessions_ahead=40,
    )

    dataset = build_oos_dataset(
        (
            _quality_observation(
                as_of=as_of,
                score=0.70,
                outcome=None,
            ),
        ),
        calendar=calendar,
        available_through=horizon,
    )

    item = dataset.observations[0]

    assert (
        item.status
        is VCPOOSMaturityStatus.DATA_INCOMPLETE
    )

    assert item.calendar_mature
    assert not item.outcome_available
    assert not item.evaluation_eligible


def test_mature_outcome_can_have_missing_score():
    calendar = _calendar()

    as_of = date(2026, 8, 3)

    horizon = forward_trading_session_date(
        calendar,
        as_of=as_of,
        sessions_ahead=40,
    )

    dataset = build_oos_dataset(
        (
            _quality_observation(
                as_of=as_of,
                score=None,
                outcome=0.12,
            ),
        ),
        calendar=calendar,
        available_through=horizon,
    )

    item = dataset.observations[0]

    assert (
        item.status
        is VCPOOSMaturityStatus.MATURE
    )

    assert not item.score_available
    assert item.outcome_available
    assert not item.evaluation_eligible


def test_non_finite_outcome_after_horizon_is_data_incomplete():
    calendar = _calendar()

    as_of = date(2026, 8, 3)

    horizon = forward_trading_session_date(
        calendar,
        as_of=as_of,
        sessions_ahead=40,
    )

    dataset = build_oos_dataset(
        (
            _quality_observation(
                as_of=as_of,
                score=0.70,
                outcome=float("nan"),
            ),
        ),
        calendar=calendar,
        available_through=horizon,
    )

    assert (
        dataset.observations[0].status
        is VCPOOSMaturityStatus.DATA_INCOMPLETE
    )


def test_dataset_exposes_distinct_maturity_groups():
    calendar = _calendar()

    mature_date = date(
        2026,
        8,
        3,
    )

    horizon = forward_trading_session_date(
        calendar,
        as_of=mature_date,
        sessions_ahead=40,
    )

    dataset = build_oos_dataset(
        (
            _quality_observation(
                as_of=mature_date,
                ticker="MATURE",
                outcome=0.20,
            ),
            _quality_observation(
                as_of=mature_date,
                ticker="INCOMPLETE",
                outcome=None,
            ),
            _quality_observation(
                as_of=date(
                    2026,
                    10,
                    1,
                ),
                ticker="IMMATURE",
                outcome=None,
            ),
        ),
        calendar=calendar,
        available_through=horizon,
    )

    assert [
        item.ticker
        for item in dataset.mature
    ] == ["MATURE"]

    assert [
        item.ticker
        for item in dataset.data_incomplete
    ] == ["INCOMPLETE"]

    assert [
        item.ticker
        for item in dataset.immature
    ] == ["IMMATURE"]

    assert [
        item.ticker
        for item in dataset.evaluation_eligible
    ] == ["MATURE"]
