from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.strategy.swing_detector import SwingPivot


@dataclass(frozen=True)
class VCPContraction:
    """One confirmed HIGH -> LOW contraction."""

    index: int
    high: SwingPivot
    low: SwingPivot
    depth_pct: float
    ratio_to_previous: float | None
    recovery_ratio: float | None
    high_drift_pct: float | None


@dataclass(frozen=True)
class VCPGeometry:
    """Descriptive geometry derived from confirmed swing pivots."""

    contractions: tuple[VCPContraction, ...]
    confirmed_contraction_count: int
    depths_strictly_decreasing: bool
    count_within_bounds: bool
    pivot: SwingPivot | None
    provisional: SwingPivot | None


def _validate_confirmed_pivots(
    pivots: Sequence[SwingPivot],
) -> None:
    previous_extreme_date = None

    for pivot in pivots:
        if pivot.kind not in {"HIGH", "LOW"}:
            raise ValueError(
                f"unsupported pivot kind: {pivot.kind}"
            )

        if pivot.confirmation_date is None:
            raise ValueError(
                "confirmed pivot must have confirmation_date"
            )

        if pivot.confirmation_date < pivot.extreme_date:
            raise ValueError(
                "confirmation_date cannot precede extreme_date"
            )

        if (
            previous_extreme_date is not None
            and pivot.extreme_date <= previous_extreme_date
        ):
            raise ValueError(
                "confirmed pivots must be strictly increasing "
                "by extreme_date"
            )

        previous_extreme_date = pivot.extreme_date


def _depth_pct(
    high: SwingPivot,
    low: SwingPivot,
) -> float:
    if high.price <= 0:
        raise ValueError(
            "contraction high price must be positive"
        )

    if low.price <= 0:
        raise ValueError(
            "contraction low price must be positive"
        )

    if low.price >= high.price:
        raise ValueError(
            "contraction low must be below contraction high"
        )

    return (
        (high.price - low.price)
        / high.price
        * 100.0
    )


def analyze_vcp_geometry(
    confirmed: Sequence[SwingPivot],
    *,
    provisional: SwingPivot | None = None,
) -> VCPGeometry:
    """Measure VCP-style contraction geometry.

    This function is deliberately descriptive.

    It does not:
    - decide whether a setup is attractive,
    - assign a VCP quality score,
    - generate an entry/exit signal,
    - discard contractions merely because their depths fail
      to decrease.

    A confirmed contraction is an adjacent:

        HIGH -> LOW

    pair in the confirmed swing sequence.

    The final unconfirmed swing, when supplied through
    ``provisional``, is preserved for context but never included in
    confirmed contraction counts or measurements.
    """

    pivots = tuple(confirmed)

    _validate_confirmed_pivots(pivots)

    # Build only the rightmost active VCP-style structure.
    #
    # A local swing LOW may legitimately remain above the immediately
    # preceding local HIGH during a strong rising regime. Such a pair is
    # not a contraction; it terminates the previous active base instead
    # of invalidating the whole swing history.
    #
    # Likewise, once a later contraction HIGH exceeds the first HIGH of
    # the active base, the prior structure has been exceeded. The current
    # pair becomes the anchor of a new rightmost structure.
    pairs: list[tuple[SwingPivot, SwingPivot]] = []

    for left, right in zip(
        pivots,
        pivots[1:],
    ):
        if not (
            left.kind == "HIGH"
            and right.kind == "LOW"
        ):
            continue

        # Non-positive prices remain invalid data and must still fail
        # closed with the existing validation messages.
        if left.price <= 0 or right.price <= 0:
            _depth_pct(left, right)

        # This is a rising-regime swing relationship, not a contraction.
        # Reset the stale base and wait for the next valid HIGH -> LOW.
        if right.price >= left.price:
            pairs.clear()
            continue

        # A new HIGH above the active base anchor means the previous
        # rightmost structure has been exceeded. Start a new base here.
        if (
            pairs
            and left.price > pairs[0][0].price
        ):
            pairs.clear()

        pairs.append(
            (left, right)
        )

    depths = [
        _depth_pct(high, low)
        for high, low in pairs
    ]

    contractions: list[VCPContraction] = []

    for index, ((high, low), depth) in enumerate(
        zip(pairs, depths),
        start=1,
    ):
        previous_depth = (
            depths[index - 2]
            if index > 1
            else None
        )

        ratio_to_previous = (
            depth / previous_depth
            if previous_depth is not None
            else None
        )

        next_high = (
            pairs[index][0]
            if index < len(pairs)
            else None
        )

        recovery_ratio: float | None = None
        high_drift_pct: float | None = None

        if next_high is not None:
            contraction_range = (
                high.price - low.price
            )

            recovery_ratio = (
                (next_high.price - low.price)
                / contraction_range
            )

            high_drift_pct = (
                (next_high.price / high.price)
                - 1.0
            ) * 100.0

        contractions.append(
            VCPContraction(
                index=index,
                high=high,
                low=low,
                depth_pct=depth,
                ratio_to_previous=ratio_to_previous,
                recovery_ratio=recovery_ratio,
                high_drift_pct=high_drift_pct,
            )
        )

    contraction_count = len(contractions)

    # With fewer than two contractions there is no sequence from
    # which decreasing depth can meaningfully be established.
    depths_strictly_decreasing = (
        contraction_count >= 2
        and all(
            current < previous
            for previous, current in zip(
                depths,
                depths[1:],
            )
        )
    )

    count_within_bounds = (
        2 <= contraction_count <= 6
    )

    # The VCP pivot is defined as the HIGH belonging to the latest
    # fully confirmed HIGH -> LOW contraction. A later unpaired HIGH
    # does not replace it.
    pivot = (
        contractions[-1].high
        if contractions
        else None
    )

    return VCPGeometry(
        contractions=tuple(contractions),
        confirmed_contraction_count=contraction_count,
        depths_strictly_decreasing=depths_strictly_decreasing,
        count_within_bounds=count_within_bounds,
        pivot=pivot,
        provisional=provisional,
    )
