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
    breakout: VCPBreakoutEvent
    follow_through: VCPFollowThrough
    state: VCPStateResult


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
        -> breakout
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

    breakout = detect_vcp_breakout(
        technical_bars,
        geometry,
    )

    follow_through = measure_vcp_follow_through(
        technical_bars,
        breakout,
    )

    state = classify_vcp_state(
        geometry,
        features,
        breakout,
        config=state_config,
    )

    return VCPAnalysisResult(
        technical_bars=technical_bars,
        swing_bars=swing_bars,
        swings=swings,
        geometry=geometry,
        features=features,
        breakout=breakout,
        follow_through=follow_through,
        state=state,
    )
