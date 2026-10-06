"""Date-relative forward outcome labels for VCP research.

This layer is purely derived research data.

For each historical ``as_of`` date and each forward horizon, the
benchmark is the median return of all observations having that label
available on the same date.

Relative return is:

    stock forward return - same-date universe median return

No VCP feature or raw forward outcome is recalculated or mutated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median

from src.research.vcp_dataset import (
    VCPResearchDataset,
    VCPResearchObservation,
)


@dataclass(frozen=True)
class VCPRelativeObservation:
    """One research observation enriched with date-relative labels."""

    observation: VCPResearchObservation

    benchmark_return_5: float | None
    benchmark_return_10: float | None
    benchmark_return_20: float | None
    benchmark_return_40: float | None

    relative_return_5: float | None
    relative_return_10: float | None
    relative_return_20: float | None
    relative_return_40: float | None


@dataclass(frozen=True)
class VCPRelativeDataset:
    """Research observations with same-date relative-return labels."""

    observations: tuple[VCPRelativeObservation, ...]


_HORIZONS = (
    ("forward_return_5", "benchmark_return_5", "relative_return_5"),
    ("forward_return_10", "benchmark_return_10", "relative_return_10"),
    ("forward_return_20", "benchmark_return_20", "relative_return_20"),
    ("forward_return_40", "benchmark_return_40", "relative_return_40"),
)


def _date_benchmarks(
    observations: tuple[VCPResearchObservation, ...],
) -> dict[date, dict[str, float | None]]:
    """Compute independent same-date medians for each horizon."""

    dates = {
        observation.as_of
        for observation in observations
    }

    result: dict[
        date,
        dict[str, float | None],
    ] = {}

    for as_of in dates:
        same_date = [
            observation
            for observation in observations
            if observation.as_of == as_of
        ]

        horizon_values: dict[str, float | None] = {}

        for outcome_field, _, _ in _HORIZONS:
            values = [
                value
                for observation in same_date
                if (
                    value := getattr(
                        observation,
                        outcome_field,
                    )
                )
                is not None
            ]

            horizon_values[outcome_field] = (
                median(values)
                if values
                else None
            )

        result[as_of] = horizon_values

    return result


def build_relative_outcomes(
    dataset: VCPResearchDataset,
) -> VCPRelativeDataset:
    """Add same-date universe-relative forward return labels.

    Benchmarks are calculated independently by horizon. Missing labels
    never remove the causal research observation.

    An observation with no +40 label, for example, is excluded only
    from the +40 benchmark calculation. Its +5/+10/+20 labels can still
    participate normally.
    """

    observations = dataset.observations

    benchmarks = _date_benchmarks(
        observations
    )

    relative_observations: list[
        VCPRelativeObservation
    ] = []

    for observation in observations:
        date_benchmarks = benchmarks[
            observation.as_of
        ]

        values: dict[str, object] = {
            "observation": observation,
        }

        for (
            outcome_field,
            benchmark_field,
            relative_field,
        ) in _HORIZONS:
            raw_return = getattr(
                observation,
                outcome_field,
            )

            benchmark = date_benchmarks[
                outcome_field
            ]

            relative = (
                raw_return - benchmark
                if (
                    raw_return is not None
                    and benchmark is not None
                )
                else None
            )

            values[benchmark_field] = benchmark
            values[relative_field] = relative

        relative_observations.append(
            VCPRelativeObservation(
                **values
            )
        )

    return VCPRelativeDataset(
        observations=tuple(
            relative_observations
        )
    )
