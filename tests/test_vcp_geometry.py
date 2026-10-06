from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.strategy.swing_detector import SwingPivot
from src.strategy.vcp_geometry import analyze_vcp_geometry


BASE_DATE = date(2026, 1, 2)


def _pivot(
    kind: str,
    price: float,
    day: int,
    *,
    confirmed: bool = True,
) -> SwingPivot:
    extreme_date = BASE_DATE + timedelta(days=day)

    return SwingPivot(
        kind=kind,
        price=price,
        extreme_date=extreme_date,
        confirmation_date=(
            extreme_date + timedelta(days=1)
            if confirmed
            else None
        ),
        threshold_pct=3.0,
    )


def _classic_3t() -> tuple[SwingPivot, ...]:
    """Classic shrinking 3T structure.

    T1:
        H1 = 110
        L1 =  90
        depth = 18.1818%

    T2:
        H2 = 106
        L2 =  96
        depth = 9.4340%

    T3:
        H3 = 104
        L3 =  99
        depth = 4.8077%
    """
    return (
        _pivot("HIGH", 110.0, 0),
        _pivot("LOW",   90.0, 3),

        _pivot("HIGH", 106.0, 6),
        _pivot("LOW",   96.0, 9),

        _pivot("HIGH", 104.0, 12),
        _pivot("LOW",   99.0, 15),
    )


def _sequence_with_depths(
    depths: list[float],
) -> tuple[SwingPivot, ...]:
    """Create deterministic HIGH→LOW contraction pairs."""
    pivots: list[SwingPivot] = []

    for index, depth_pct in enumerate(depths):
        high = 120.0 - index
        low = high * (1.0 - depth_pct / 100.0)

        pivots.append(
            _pivot(
                "HIGH",
                high,
                index * 6,
            )
        )

        pivots.append(
            _pivot(
                "LOW",
                low,
                index * 6 + 3,
            )
        )

    return tuple(pivots)


def test_builds_three_confirmed_high_low_contractions():
    geometry = analyze_vcp_geometry(
        _classic_3t()
    )

    assert geometry.confirmed_contraction_count == 3
    assert len(geometry.contractions) == 3

    assert [
        contraction.index
        for contraction in geometry.contractions
    ] == [1, 2, 3]

    assert geometry.contractions[0].high.price == pytest.approx(
        110.0
    )
    assert geometry.contractions[0].low.price == pytest.approx(
        90.0
    )

    assert geometry.contractions[1].high.price == pytest.approx(
        106.0
    )
    assert geometry.contractions[1].low.price == pytest.approx(
        96.0
    )

    assert geometry.contractions[2].high.price == pytest.approx(
        104.0
    )
    assert geometry.contractions[2].low.price == pytest.approx(
        99.0
    )


def test_calculates_contraction_depths_and_ratios():
    geometry = analyze_vcp_geometry(
        _classic_3t()
    )

    t1, t2, t3 = geometry.contractions

    assert t1.depth_pct == pytest.approx(
        18.181818,
        rel=1e-6,
    )
    assert t2.depth_pct == pytest.approx(
        9.433962,
        rel=1e-6,
    )
    assert t3.depth_pct == pytest.approx(
        4.807692,
        rel=1e-6,
    )

    assert t1.ratio_to_previous is None

    assert t2.ratio_to_previous == pytest.approx(
        0.518868,
        rel=1e-6,
    )

    assert t3.ratio_to_previous == pytest.approx(
        0.509615,
        rel=1e-6,
    )

    assert geometry.depths_strictly_decreasing is True


def test_calculates_recovery_ratio_and_high_drift():
    geometry = analyze_vcp_geometry(
        _classic_3t()
    )

    t1, t2, t3 = geometry.contractions

    # Recovery after T1:
    #
    # (H2 - L1) / (H1 - L1)
    # = (106 - 90) / (110 - 90)
    # = 0.80
    assert t1.recovery_ratio == pytest.approx(
        0.80
    )

    # Recovery after T2:
    #
    # (H3 - L2) / (H2 - L2)
    # = (104 - 96) / (106 - 96)
    # = 0.80
    assert t2.recovery_ratio == pytest.approx(
        0.80
    )

    # No later confirmed HIGH is needed to evaluate T3 yet.
    assert t3.recovery_ratio is None

    assert t1.high_drift_pct == pytest.approx(
        -3.636364,
        rel=1e-6,
    )

    assert t2.high_drift_pct == pytest.approx(
        -1.886792,
        rel=1e-6,
    )

    assert t3.high_drift_pct is None


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, False),
        (2, True),
        (6, True),
        (7, False),
    ],
)
def test_contraction_count_bounds_are_two_through_six(
    count: int,
    expected: bool,
):
    depths = [
        28.0,
        23.0,
        18.0,
        14.0,
        10.0,
        7.0,
        4.0,
    ][:count]

    geometry = analyze_vcp_geometry(
        _sequence_with_depths(depths)
    )

    assert geometry.confirmed_contraction_count == count
    assert geometry.count_within_bounds is expected


def test_non_decreasing_depth_is_reported_not_silently_removed():
    pivots = _sequence_with_depths(
        [
            18.0,
            10.0,
            12.0,
        ]
    )

    geometry = analyze_vcp_geometry(
        pivots
    )

    assert geometry.confirmed_contraction_count == 3

    assert [
        contraction.depth_pct
        for contraction in geometry.contractions
    ] == pytest.approx(
        [
            18.0,
            10.0,
            12.0,
        ]
    )

    assert geometry.depths_strictly_decreasing is False


def test_provisional_low_does_not_become_confirmed_contraction():
    confirmed = (
        _pivot("HIGH", 110.0, 0),
        _pivot("LOW",   90.0, 3),

        _pivot("HIGH", 106.0, 6),
        _pivot("LOW",   96.0, 9),

        # H3 exists, but its LOW is still developing.
        _pivot("HIGH", 104.0, 12),
    )

    provisional_low = _pivot(
        "LOW",
        99.0,
        15,
        confirmed=False,
    )

    without_provisional = analyze_vcp_geometry(
        confirmed
    )

    with_provisional = analyze_vcp_geometry(
        confirmed,
        provisional=provisional_low,
    )

    assert (
        without_provisional.confirmed_contraction_count
        == 2
    )

    assert (
        with_provisional.confirmed_contraction_count
        == 2
    )

    assert (
        with_provisional.contractions
        == without_provisional.contractions
    )

    assert with_provisional.provisional == provisional_low


def test_pivot_is_high_of_last_confirmed_contraction():
    geometry = analyze_vcp_geometry(
        _classic_3t()
    )

    assert geometry.pivot is not None

    assert geometry.pivot.kind == "HIGH"
    assert geometry.pivot.price == pytest.approx(
        104.0
    )

    assert (
        geometry.pivot.extreme_date
        == _classic_3t()[4].extreme_date
    )


def test_invalid_high_low_pair_resets_active_vcp_structure():
    pivots = (
        # Old structure.
        _pivot("HIGH", 110.0, 0),
        _pivot("LOW",   90.0, 3),

        # A local LOW can legitimately remain above the prior
        # local HIGH in a rising price regime. This is not a VCP
        # contraction and terminates the previous active base.
        _pivot("HIGH", 105.0, 6),
        _pivot("LOW",  106.0, 9),

        # New rightmost structure.
        _pivot("HIGH", 130.0, 12),
        _pivot("LOW",  110.0, 15),

        _pivot("HIGH", 125.0, 18),
        _pivot("LOW",  118.0, 21),
    )

    geometry = analyze_vcp_geometry(
        pivots
    )

    assert geometry.confirmed_contraction_count == 2

    assert [
        contraction.high.price
        for contraction in geometry.contractions
    ] == pytest.approx(
        [130.0, 125.0]
    )

    assert [
        contraction.low.price
        for contraction in geometry.contractions
    ] == pytest.approx(
        [110.0, 118.0]
    )

    assert [
        contraction.index
        for contraction in geometry.contractions
    ] == [1, 2]

    assert geometry.pivot is not None
    assert geometry.pivot.price == pytest.approx(
        125.0
    )


def test_new_high_above_active_base_anchor_starts_new_structure():
    pivots = (
        # First base.
        _pivot("HIGH", 110.0, 0),
        _pivot("LOW",   90.0, 3),

        _pivot("HIGH", 105.0, 6),
        _pivot("LOW",   95.0, 9),

        # 112 exceeds the first/base HIGH of 110.
        # The prior structure is therefore no longer the
        # rightmost active base.
        _pivot("HIGH", 112.0, 12),
        _pivot("LOW",  100.0, 15),

        _pivot("HIGH", 108.0, 18),
        _pivot("LOW",  103.0, 21),
    )

    geometry = analyze_vcp_geometry(
        pivots
    )

    assert geometry.confirmed_contraction_count == 2

    assert [
        contraction.high.price
        for contraction in geometry.contractions
    ] == pytest.approx(
        [112.0, 108.0]
    )

    assert [
        contraction.low.price
        for contraction in geometry.contractions
    ] == pytest.approx(
        [100.0, 103.0]
    )

    assert geometry.pivot is not None
    assert geometry.pivot.price == pytest.approx(
        108.0
    )
