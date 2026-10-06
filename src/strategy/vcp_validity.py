from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from src.strategy.vcp_features import VCPFeatures
from src.strategy.vcp_geometry import VCPGeometry


@dataclass(frozen=True)
class VCPValidityResult:
    """Structural VCP validity evidence.

    This layer evaluates the current active price base only.

    It deliberately does NOT evaluate:
    - Minervini Stage 2 / Trend Template eligibility,
    - relative strength,
    - breakout state,
    - entry timing,
    - trade quality or ranking.

    Book-derived concepts and Labyrinth proxies are kept explicit
    rather than silently treated as equivalent.
    """

    contraction_count_valid: bool

    overall_volatility_contracting: bool
    final_is_tightest: bool

    right_side_tightness_present: bool
    final_volume_below_50d: bool

    first_contraction_depth_pct: float | None
    final_contraction_depth_pct: float | None
    final_to_first_depth_ratio: float | None

    decreasing_step_fraction: float | None

    structurally_valid: bool
    failure_reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def _finite(
    value: float | None,
) -> bool:
    return (
        value is not None
        and math.isfinite(float(value))
    )


def _depth_profile(
    geometry: VCPGeometry,
) -> tuple[
    float | None,
    float | None,
    float | None,
    float | None,
]:
    """Return descriptive contraction-profile measurements.

    Returns:
        first depth,
        final depth,
        final / first ratio,
        fraction of successive steps that contracted.
    """

    depths = [
        float(contraction.depth_pct)
        for contraction in geometry.contractions
    ]

    if not depths:
        return (
            None,
            None,
            None,
            None,
        )

    first = depths[0]
    final = depths[-1]

    final_to_first = (
        final / first
        if first > 0
        else None
    )

    if len(depths) < 2:
        decreasing_fraction = None
    else:
        decreasing_steps = sum(
            current < previous
            for previous, current in zip(
                depths,
                depths[1:],
            )
        )

        decreasing_fraction = (
            decreasing_steps
            / (len(depths) - 1)
        )

    return (
        first,
        final,
        final_to_first,
        decreasing_fraction,
    )


def assess_vcp_validity(
    geometry: VCPGeometry,
    features: VCPFeatures,
) -> VCPValidityResult:
    """Assess structural VCP evidence for the active base.

    Design rules
    ------------
    Book-derived:
    - a developed VCP normally contains 2-6 contractions;
    - volatility should contract from left to right;
    - the far-right contraction should be especially tight;
    - volume should contract as supply dries up;
    - final-contraction volume should be below its 50-day
      average reference level.

    Labyrinth proxy:
    - ``true_range_compression_10_40 < 1.0`` is used as an
      objective proxy for quieter right-side price action.
      This ratio is NOT a Minervini formula.

    We deliberately do not require every single contraction
    to be strictly smaller than its predecessor. The overall
    left-to-right contraction profile is evaluated instead.
    """

    count = (
        geometry.confirmed_contraction_count
    )

    if count != len(
        geometry.contractions
    ):
        raise ValueError(
            "geometry contraction count is inconsistent"
        )

    contraction_count_valid = (
        2 <= count <= 6
    )

    (
        first_depth,
        final_depth,
        final_to_first,
        decreasing_step_fraction,
    ) = _depth_profile(
        geometry
    )

    if (
        count >= 2
        and first_depth is not None
        and final_depth is not None
    ):
        # Overall contraction is intentionally less strict than
        # requiring every T to decrease monotonically.
        overall_volatility_contracting = (
            final_depth < first_depth
        )

        depths = [
            float(contraction.depth_pct)
            for contraction in geometry.contractions
        ]

        # The far-right T should be the narrowest contraction
        # in the active base.
        final_is_tightest = (
            final_depth
            <= min(depths)
        )

    else:
        overall_volatility_contracting = False
        final_is_tightest = False

    tr_compression = (
        features.true_range_compression_10_40
    )

    right_side_tightness_known = _finite(
        tr_compression
    )

    right_side_tightness_present = (
        right_side_tightness_known
        and float(tr_compression) < 1.0
    )

    final_volume_ratio = (
        features.final_contraction_volume_ratio_50
    )

    final_volume_known = _finite(
        final_volume_ratio
    )

    final_volume_below_50d = (
        final_volume_known
        and float(final_volume_ratio) < 1.0
    )

    failure_reasons: list[str] = []

    if not contraction_count_valid:
        failure_reasons.append(
            "CONTRACTION_COUNT_OUT_OF_BOUNDS"
        )

    # Only judge contraction-shape quality once a developed
    # 2-6T structure actually exists.
    if contraction_count_valid:
        if not overall_volatility_contracting:
            failure_reasons.append(
                "VOLATILITY_NOT_CONTRACTING"
            )

    # Right-side tightness and final-contraction volume remain
    # explicit diagnostic evidence. They describe readiness /
    # supply quality, not minimum structural validity.

    structurally_valid = (
        contraction_count_valid
        and overall_volatility_contracting
    )

    return VCPValidityResult(
        contraction_count_valid=(
            contraction_count_valid
        ),

        overall_volatility_contracting=(
            overall_volatility_contracting
        ),

        final_is_tightest=(
            final_is_tightest
        ),

        right_side_tightness_present=(
            right_side_tightness_present
        ),

        final_volume_below_50d=(
            final_volume_below_50d
        ),

        first_contraction_depth_pct=(
            first_depth
        ),

        final_contraction_depth_pct=(
            final_depth
        ),

        final_to_first_depth_ratio=(
            final_to_first
        ),

        decreasing_step_fraction=(
            decreasing_step_fraction
        ),

        structurally_valid=(
            structurally_valid
        ),

        failure_reasons=tuple(
            failure_reasons
        ),
    )
