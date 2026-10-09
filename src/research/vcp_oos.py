"""Prospective out-of-sample validation for frozen VCP quality research.

Research development period:
    through 2026-07-31

Prospective OOS period:
    2026-08-01 onward

Calendar maturity and data availability are deliberately separated.

An OOS observation can be:

NOT_OOS
    As-of date is on or before the frozen research cutoff.

IMMATURE
    The official 40th BIST trading session after as-of has not yet
    occurred within the available data horizon.

MATURE
    The official +40 session horizon has passed and a finite
    relative_return_40 is available.

DATA_INCOMPLETE
    The official +40 session horizon has passed, but the +40 relative
    outcome is missing or non-finite.

Score availability is tracked independently. A calendar-mature observation
may therefore have ``score_available=False``.

Production ranking is not modified here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from math import isfinite
from typing import Sequence

from src.data.calendar import BISTTradingCalendar
from src.research.vcp_quality import (
    VCPQualityResearchObservation,
)


VCP_QUALITY_RESEARCH_FREEZE_DATE = date(
    2026,
    7,
    31,
)

VCP_QUALITY_FORWARD_HORIZON = 40


class VCPOOSMaturityStatus(str, Enum):
    NOT_OOS = "NOT_OOS"
    IMMATURE = "IMMATURE"
    MATURE = "MATURE"
    DATA_INCOMPLETE = "DATA_INCOMPLETE"


@dataclass(frozen=True)
class VCPOOSObservation:
    """One frozen-score observation classified for prospective validation."""

    as_of: date
    ticker: str

    horizon_date_40: date | None
    available_through: date

    status: VCPOOSMaturityStatus

    score: float | None
    relative_return_40: float | None

    score_available: bool

    @property
    def is_oos(self) -> bool:
        return self.status is not VCPOOSMaturityStatus.NOT_OOS

    @property
    def calendar_mature(self) -> bool:
        return self.status in (
            VCPOOSMaturityStatus.MATURE,
            VCPOOSMaturityStatus.DATA_INCOMPLETE,
        )

    @property
    def outcome_available(self) -> bool:
        return (
            self.status
            is VCPOOSMaturityStatus.MATURE
        )

    @property
    def evaluation_eligible(self) -> bool:
        """True only when both frozen score and mature outcome are usable."""

        return (
            self.status
            is VCPOOSMaturityStatus.MATURE
            and self.score_available
        )


@dataclass(frozen=True)
class VCPOOSDataset:
    """Prospective observations grouped by calendar/data maturity."""

    observations: tuple[VCPOOSObservation, ...]

    @property
    def mature(self) -> tuple[VCPOOSObservation, ...]:
        """Calendar-mature observations with usable +40 outcome."""

        return tuple(
            item
            for item in self.observations
            if (
                item.status
                is VCPOOSMaturityStatus.MATURE
            )
        )

    @property
    def immature(self) -> tuple[VCPOOSObservation, ...]:
        return tuple(
            item
            for item in self.observations
            if (
                item.status
                is VCPOOSMaturityStatus.IMMATURE
            )
        )

    @property
    def data_incomplete(self) -> tuple[VCPOOSObservation, ...]:
        return tuple(
            item
            for item in self.observations
            if (
                item.status
                is VCPOOSMaturityStatus.DATA_INCOMPLETE
            )
        )

    @property
    def evaluation_eligible(
        self,
    ) -> tuple[VCPOOSObservation, ...]:
        return tuple(
            item
            for item in self.observations
            if item.evaluation_eligible
        )


def is_prospective_oos_date(
    as_of: date,
) -> bool:
    """Return True only for observations strictly after research freeze."""

    return (
        as_of
        > VCP_QUALITY_RESEARCH_FREEZE_DATE
    )


def forward_trading_session_date(
    calendar: BISTTradingCalendar,
    *,
    as_of: date,
    sessions_ahead: int,
) -> date:
    """Return the Nth official BIST trading session strictly after as-of."""

    if sessions_ahead <= 0:
        raise ValueError(
            "sessions_ahead must be positive"
        )

    current = as_of + timedelta(days=1)
    count = 0

    while True:
        if calendar.is_trading_day(
            current
        ):
            count += 1

            if count == sessions_ahead:
                return current

        current += timedelta(days=1)


def build_oos_dataset(
    observations: Sequence[
        VCPQualityResearchObservation
    ],
    *,
    calendar: BISTTradingCalendar,
    available_through: date,
) -> VCPOOSDataset:
    """Classify frozen observations using official calendar maturity.

    ``available_through`` is the last market date the caller considers
    available for research evaluation.

    Calendar maturity is determined independently from:

    - score availability,
    - security-level price-bar completeness,
    - relative outcome availability.
    """

    result: list[VCPOOSObservation] = []

    for item in observations:
        cross = item.cross_sectional_observation
        relative = cross.relative_observation
        observation = relative.observation

        score = item.atr_vol_eq_score
        outcome = relative.relative_return_40

        finite_score = (
            score is not None
            and isfinite(float(score))
        )

        finite_outcome = (
            outcome is not None
            and isfinite(float(outcome))
        )

        if not is_prospective_oos_date(
            observation.as_of
        ):
            result.append(
                VCPOOSObservation(
                    as_of=observation.as_of,
                    ticker=observation.ticker,
                    horizon_date_40=None,
                    available_through=available_through,
                    status=VCPOOSMaturityStatus.NOT_OOS,
                    score=(
                        float(score)
                        if finite_score
                        else None
                    ),
                    relative_return_40=(
                        float(outcome)
                        if finite_outcome
                        else None
                    ),
                    score_available=finite_score,
                )
            )
            continue

        horizon_date = forward_trading_session_date(
            calendar,
            as_of=observation.as_of,
            sessions_ahead=VCP_QUALITY_FORWARD_HORIZON,
        )

        if horizon_date > available_through:
            status = VCPOOSMaturityStatus.IMMATURE

        elif finite_outcome:
            status = VCPOOSMaturityStatus.MATURE

        else:
            status = (
                VCPOOSMaturityStatus.DATA_INCOMPLETE
            )

        result.append(
            VCPOOSObservation(
                as_of=observation.as_of,
                ticker=observation.ticker,
                horizon_date_40=horizon_date,
                available_through=available_through,
                status=status,
                score=(
                    float(score)
                    if finite_score
                    else None
                ),
                relative_return_40=(
                    float(outcome)
                    if finite_outcome
                    else None
                ),
                score_available=finite_score,
            )
        )

    return VCPOOSDataset(
        observations=tuple(result)
    )
