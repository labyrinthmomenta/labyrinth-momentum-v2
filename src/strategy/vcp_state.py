from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import math

from src.strategy.vcp_breakout import VCPBreakoutEvent
from src.strategy.vcp_features import VCPFeatures
from src.strategy.vcp_geometry import VCPGeometry


class VCPState(str, Enum):
    """Descriptive lifecycle state of a VCP structure."""

    NO_STRUCTURE = "NO_STRUCTURE"
    BASE_FORMING = "BASE_FORMING"
    VCP_CANDIDATE = "VCP_CANDIDATE"
    VCP_CONTRACTING = "VCP_CONTRACTING"
    VCP_TIGHTENING = "VCP_TIGHTENING"
    NEAR_PIVOT = "NEAR_PIVOT"
    PIVOT_BROKEN = "PIVOT_BROKEN"
    PIVOT_BROKEN_VOLUME_EXPANSION = (
        "PIVOT_BROKEN_VOLUME_EXPANSION"
    )


@dataclass(frozen=True)
class VCPStateConfig:
    """Explicit research thresholds for state classification.

    These values are configuration parameters, not universal
    claims about optimal VCP thresholds.
    """

    tightening_range_5_max_pct: float
    tightening_true_range_compression_max: float
    tightening_final_volume_ratio_max: float

    near_pivot_max_distance_pct: float

    breakout_volume_expansion_min_ratio: float

    def __post_init__(self) -> None:
        _require_positive(
            "tightening_range_5_max_pct",
            self.tightening_range_5_max_pct,
        )

        _require_positive(
            "tightening_true_range_compression_max",
            self.tightening_true_range_compression_max,
        )

        _require_positive(
            "tightening_final_volume_ratio_max",
            self.tightening_final_volume_ratio_max,
        )

        _require_positive(
            "near_pivot_max_distance_pct",
            self.near_pivot_max_distance_pct,
        )

        _require_positive(
            "breakout_volume_expansion_min_ratio",
            self.breakout_volume_expansion_min_ratio,
        )


@dataclass(frozen=True)
class VCPStateResult:
    """Result of deterministic VCP state classification."""

    state: VCPState

    confirmed_contraction_count: int
    depths_strictly_decreasing: bool

    tightening_conditions_met: bool
    near_pivot_condition_met: bool

    pivot_broken_by_close: bool
    breakout_volume_expansion_met: bool

    def as_dict(self) -> dict:
        data = asdict(self)
        data["state"] = self.state.value
        return data


def _finite(value: float | None) -> bool:
    return (
        value is not None
        and math.isfinite(float(value))
    )


def _require_positive(
    name: str,
    value: float,
) -> None:
    if (
        not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise ValueError(
            f"{name} must be finite and positive"
        )


def _validate_inputs(
    geometry: VCPGeometry,
    features: VCPFeatures,
    breakout: VCPBreakoutEvent,
) -> None:
    count = geometry.confirmed_contraction_count

    if count < 0:
        raise ValueError(
            "confirmed contraction count cannot be negative"
        )

    if count != len(geometry.contractions):
        raise ValueError(
            "geometry contraction count is inconsistent"
        )

    if (
        count == 0
        and geometry.pivot is not None
    ):
        raise ValueError(
            "geometry pivot requires a confirmed contraction"
        )

    if (
        count > 0
        and geometry.pivot is None
    ):
        raise ValueError(
            "confirmed contractions require a geometry pivot"
        )

    has_break_date = (
        breakout.first_close_break_date is not None
    )

    if (
        breakout.pivot_broken_by_close
        != has_break_date
    ):
        raise ValueError(
            "inconsistent breakout event"
        )

    if breakout.has_confirmed_pivot:
        if breakout.pivot_price is None:
            raise ValueError(
                "confirmed breakout pivot requires pivot price"
            )

        if (
            not _finite(breakout.pivot_price)
            or float(breakout.pivot_price) <= 0
        ):
            raise ValueError(
                "breakout pivot price must be finite and positive"
            )

    elif breakout.pivot_price is not None:
        raise ValueError(
            "pivot price cannot exist without confirmed pivot"
        )

    if breakout.pivot_broken_by_close:
        if not breakout.has_confirmed_pivot:
            raise ValueError(
                "close breakout requires confirmed pivot"
            )

    # When both layers expose a confirmed pivot, they should refer
    # to the same structure.
    if (
        geometry.pivot is not None
        and breakout.pivot_price is not None
        and not math.isclose(
            float(geometry.pivot.price),
            float(breakout.pivot_price),
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    ):
        raise ValueError(
            "geometry and breakout pivot prices disagree"
        )


def _tightening_conditions_met(
    features: VCPFeatures,
    config: VCPStateConfig,
) -> bool:
    """Fail closed when any required tightening metric is missing."""

    values = (
        features.range_5_pct,
        features.true_range_compression_10_40,
        features.final_contraction_volume_ratio_50,
    )

    if not all(
        _finite(value)
        for value in values
    ):
        return False

    assert features.range_5_pct is not None
    assert (
        features.true_range_compression_10_40
        is not None
    )
    assert (
        features.final_contraction_volume_ratio_50
        is not None
    )

    return (
        features.range_5_pct
        <= config.tightening_range_5_max_pct

        and features.true_range_compression_10_40
        <= config.tightening_true_range_compression_max

        and features.final_contraction_volume_ratio_50
        <= config.tightening_final_volume_ratio_max
    )


def _near_pivot_condition_met(
    features: VCPFeatures,
    config: VCPStateConfig,
) -> bool:
    """Near-pivot is deliberately measured from below the pivot."""

    distance = features.distance_to_pivot_pct

    if not _finite(distance):
        return False

    assert distance is not None

    return (
        -config.near_pivot_max_distance_pct
        <= float(distance)
        <= 0.0
    )


def _breakout_volume_expansion_met(
    breakout: VCPBreakoutEvent,
    config: VCPStateConfig,
) -> bool:
    ratio = breakout.breakout_volume_ratio_20

    if not _finite(ratio):
        return False

    assert ratio is not None

    return (
        float(ratio)
        >= config.breakout_volume_expansion_min_ratio
    )


def classify_vcp_state(
    geometry: VCPGeometry,
    features: VCPFeatures,
    breakout: VCPBreakoutEvent,
    *,
    config: VCPStateConfig,
) -> VCPStateResult:
    """Classify the descriptive lifecycle state of a VCP structure.

    Priority is intentionally ordered from the most advanced
    observable event backward:

        PIVOT_BROKEN_VOLUME_EXPANSION
        PIVOT_BROKEN
        NEAR_PIVOT
        VCP_TIGHTENING
        VCP_CONTRACTING
        VCP_CANDIDATE
        BASE_FORMING
        NO_STRUCTURE

    The classifier does not compute new market indicators, assign
    a quality score, or generate a trading recommendation.
    """

    _validate_inputs(
        geometry,
        features,
        breakout,
    )

    count = (
        geometry.confirmed_contraction_count
    )

    tightening = (
        _tightening_conditions_met(
            features,
            config,
        )
    )

    near_pivot = (
        _near_pivot_condition_met(
            features,
            config,
        )
    )

    volume_expansion = (
        _breakout_volume_expansion_met(
            breakout,
            config,
        )
    )

    # Breakout events have the highest lifecycle priority.
    if breakout.pivot_broken_by_close:
        state = (
            VCPState.PIVOT_BROKEN_VOLUME_EXPANSION
            if volume_expansion
            else VCPState.PIVOT_BROKEN
        )

    elif count == 0:
        state = VCPState.NO_STRUCTURE

    elif count == 1:
        state = VCPState.BASE_FORMING

    # Two or more confirmed contractions constitute a candidate
    # structure even when contraction depths do not decrease.
    elif not geometry.depths_strictly_decreasing:
        state = VCPState.VCP_CANDIDATE

    else:
        # A successively contracting structure exists.
        state = VCPState.VCP_CONTRACTING

        # Tightening requires all configured measurements.
        if tightening:
            state = VCPState.VCP_TIGHTENING

            # Near-pivot is a refinement of an already-tightening
            # structure, and only applies at/below the pivot.
            if near_pivot:
                state = VCPState.NEAR_PIVOT

    return VCPStateResult(
        state=state,

        confirmed_contraction_count=count,
        depths_strictly_decreasing=(
            geometry.depths_strictly_decreasing
        ),

        tightening_conditions_met=tightening,
        near_pivot_condition_met=near_pivot,

        pivot_broken_by_close=(
            breakout.pivot_broken_by_close
        ),

        breakout_volume_expansion_met=(
            volume_expansion
        ),
    )
