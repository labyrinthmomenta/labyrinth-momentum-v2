from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.strategy.swing_bar_adapter import build_swing_bars
from src.strategy.swing_detector import (
    SwingBar,
    SwingDetectionResult,
    SwingDetectorConfig,
    detect_swings,
)
from src.strategy.technical_prices import TechnicalPriceBar
from src.strategy.vcp_base_features import (
    VCPBaseFeatures,
    compute_vcp_base_features,
)
from src.strategy.vcp_breakout import (
    VCPBreakoutEvent,
    detect_vcp_breakout,
)
from src.strategy.vcp_features import (
    VCPFeatures,
    compute_vcp_features,
)
from src.strategy.vcp_follow_through import (
    VCPFollowThrough,
    measure_vcp_follow_through,
)
from src.strategy.vcp_geometry import (
    VCPGeometry,
    analyze_vcp_geometry,
)
from src.strategy.vcp_validity import (
    VCPValidityResult,
    assess_vcp_validity,
)
from src.strategy.vcp_state import (
    VCPStateConfig,
    VCPStateResult,
    classify_vcp_state,
)


@dataclass(frozen=True)
class VCPAnalysisResult:
    """Complete deterministic VCP analysis for one technical price series."""

    technical_bars: tuple[TechnicalPriceBar, ...]
    swing_bars: tuple[SwingBar, ...]
    swings: SwingDetectionResult

    geometry: VCPGeometry
    features: VCPFeatures
    base_features: VCPBaseFeatures
    validity: VCPValidityResult
    breakout: VCPBreakoutEvent
    follow_through: VCPFollowThrough
    state: VCPStateResult


def _resolve_base_end_date(
    technical_bars: Sequence[TechnicalPriceBar],
    breakout: VCPBreakoutEvent,
):
    """Resolve the causal right edge of the measured VCP base.

    Without a close-confirmed breakout, the base extends through the
    latest supplied technical bar.

    Once a close-confirmed breakout exists, the base ends on the
    immediately preceding actual trading bar. Calendar-day arithmetic
    is deliberately avoided.
    """

    if not technical_bars:
        raise ValueError(
            "At least one technical price bar is required"
        )

    break_date = breakout.first_close_break_date

    if break_date is None:
        return technical_bars[-1].date

    for index, bar in enumerate(technical_bars):
        if bar.date != break_date:
            continue

        if index == 0:
            raise ValueError(
                "VCP breakout cannot precede all base history"
            )

        return technical_bars[
            index - 1
        ].date

    raise ValueError(
        "first_close_break_date must match a technical price bar"
    )


def analyze_vcp(
    bars: Sequence[TechnicalPriceBar],
    *,
    state_config: VCPStateConfig,
    swing_config: SwingDetectorConfig | None = None,
    atr_period: int = 14,
) -> VCPAnalysisResult:
    """Run the complete pure-strategy VCP analysis chain.

    This function performs no database access and contains no
    production threshold defaults.

    Pipeline
    --------
    TechnicalPriceBar
        -> causal ATR-aware SwingBar
        -> swing detection
        -> VCP geometry
        -> VCP features
        -> structural VCP validity
        -> breakout
        -> causal base features
        -> follow-through
        -> VCP lifecycle state
    """

    technical_bars = tuple(bars)

    swing_bars = build_swing_bars(
        technical_bars,
        atr_period=atr_period,
    )

    swings = detect_swings(
        swing_bars,
        config=swing_config,
    )

    geometry = analyze_vcp_geometry(
        swings.confirmed,
        provisional=swings.provisional,
    )

    latest_atr_pct = (
        swing_bars[-1].atr_pct
        if swing_bars
        else None
    )

    features = compute_vcp_features(
        technical_bars,
        geometry,
        atr_pct=latest_atr_pct,
    )

    validity = assess_vcp_validity(
        geometry,
        features,
    )

    breakout = detect_vcp_breakout(
        technical_bars,
        geometry,
    )

    base_end_date = _resolve_base_end_date(
        technical_bars,
        breakout,
    )

    base_features = compute_vcp_base_features(
        technical_bars,
        geometry,
        end_date=base_end_date,
        atr_period=atr_period,
    )

    follow_through = measure_vcp_follow_through(
        technical_bars,
        breakout,
    )

    state = classify_vcp_state(
        geometry,
        features,
        breakout,
        validity=validity,
        config=state_config,
    )

    return VCPAnalysisResult(
        technical_bars=technical_bars,
        swing_bars=swing_bars,
        swings=swings,
        geometry=geometry,
        features=features,
        base_features=base_features,
        validity=validity,
        breakout=breakout,
        follow_through=follow_through,
        state=state,
    )
