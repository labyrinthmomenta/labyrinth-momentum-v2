from __future__ import annotations

from datetime import date
import sqlite3

from src.strategy.swing_detector import SwingDetectorConfig
from src.strategy.technical_price_adapter import load_technical_prices
from src.strategy.vcp_analysis import (
    VCPAnalysisResult,
    analyze_vcp,
)
from src.strategy.vcp_state import VCPStateConfig


def run_vcp_analysis(
    conn: sqlite3.Connection,
    security_id: int,
    *,
    as_of: date,
    state_config: VCPStateConfig,
    swing_config: SwingDetectorConfig | None = None,
    atr_period: int = 14,
) -> VCPAnalysisResult:
    """Run causal production VCP analysis from stored market data.

    All available canonical history up to and including ``as_of`` is
    loaded. No arbitrary lookback is applied, so ATR warm-up, swing
    history and VCP geometry are not truncated by the pipeline layer.

    Price and adjustment data after ``as_of`` are excluded by the
    technical-price adapter.
    """

    technical_bars = load_technical_prices(
        conn,
        security_id,
        end=as_of,
    )

    return analyze_vcp(
        technical_bars,
        state_config=state_config,
        swing_config=swing_config,
        atr_period=atr_period,
    )
