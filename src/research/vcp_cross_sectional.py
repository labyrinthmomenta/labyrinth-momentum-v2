"""Same-date cross-sectional feature normalization for VCP research.

This layer converts raw VCP feature values into within-date percentile
ranks for the supplied research cohort.

Percentile semantics are intentionally direction-neutral:

    0.0 = lowest raw feature value on that date
    1.0 = highest raw feature value on that date

Whether low or high values are preferable is a research question and is
not encoded here.

Missing feature values do not enter the ranking denominator. Ties use
average rank. A single available value receives the neutral percentile
0.5.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from src.research.vcp_relative import VCPRelativeObservation


@dataclass(frozen=True)
class VCPCrossSectionalObservation:
    """One relative observation enriched with same-date feature ranks."""

    relative_observation: VCPRelativeObservation

    base_depth_percentile: float | None
    distance_to_pivot_percentile: float | None
    base_atr_compression_percentile: float | None
    base_volume_dryup_percentile: float | None
    final_to_first_depth_percentile: float | None


@dataclass(frozen=True)
class VCPCrossSectionalDataset:
    """Cross-sectionally normalized VCP research observations."""

    observations: tuple[VCPCrossSectionalObservation, ...]


_FEATURES = (
    (
        "base_depth_pct",
        "base_depth_percentile",
    ),
    (
        "distance_to_pivot_pct",
        "distance_to_pivot_percentile",
    ),
    (
        "base_atr_compression_ratio",
        "base_atr_compression_percentile",
    ),
    (
        "base_volume_dryup_ratio",
        "base_volume_dryup_percentile",
    ),
    (
        "final_to_first_depth_ratio",
        "final_to_first_depth_percentile",
    ),
)


def _average_rank_percentiles(
    observations: tuple[VCPRelativeObservation, ...],
    indices: list[int],
    feature_name: str,
) -> dict[int, float]:
    """Return tie-aware percentile ranks for one date and feature."""

    available: list[tuple[int, float]] = []

    for index in indices:
        observation = (
            observations[index]
            .observation
        )

        value = getattr(
            observation,
            feature_name,
        )

        if value is not None:
            available.append(
                (
                    index,
                    float(value),
                )
            )

    count = len(available)

    if count == 0:
        return {}

    if count == 1:
        return {
            available[0][0]: 0.5
        }

    available.sort(
        key=lambda item: item[1]
    )

    result: dict[int, float] = {}

    start = 0

    while start < count:
        value = available[start][1]

        end = start

        while (
            end + 1 < count
            and available[end + 1][1] == value
        ):
            end += 1

        # Positions are zero-based:
        #
        #   first value  -> 0
        #   last value   -> count - 1
        #
        # Tied observations receive their average position.
        average_rank = (
            start + end
        ) / 2.0

        percentile = (
            average_rank
            / (count - 1)
        )

        for position in range(
            start,
            end + 1,
        ):
            original_index = (
                available[position][0]
            )

            result[
                original_index
            ] = percentile

        start = end + 1

    return result


def build_cross_sectional_features(
    observations: tuple[VCPRelativeObservation, ...]
    | list[VCPRelativeObservation],
) -> VCPCrossSectionalDataset:
    """Add same-date feature percentiles to a supplied research cohort.

    Ranking is performed only inside the observations supplied by the
    caller. This allows the research layer to choose the cohort first,
    for example structurally-valid pre-breakout setups, and then rank
    features only against comparable candidates.

    Input order and observation identity are preserved.
    """

    items = tuple(
        observations
    )

    indices_by_date: dict[
        date,
        list[int],
    ] = defaultdict(list)

    for index, item in enumerate(
        items
    ):
        indices_by_date[
            item.observation.as_of
        ].append(
            index
        )

    percentile_values: list[
        dict[str, float | None]
    ] = [
        {
            output_name: None
            for _, output_name in _FEATURES
        }
        for _ in items
    ]

    for indices in indices_by_date.values():

        for (
            feature_name,
            output_name,
        ) in _FEATURES:

            ranks = _average_rank_percentiles(
                items,
                indices,
                feature_name,
            )

            for index, percentile in ranks.items():
                percentile_values[
                    index
                ][
                    output_name
                ] = percentile

    enriched = tuple(
        VCPCrossSectionalObservation(
            relative_observation=item,
            **percentile_values[index],
        )
        for index, item in enumerate(
            items
        )
    )

    return VCPCrossSectionalDataset(
        observations=enriched
    )
