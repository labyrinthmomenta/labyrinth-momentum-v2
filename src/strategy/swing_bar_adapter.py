from __future__ import annotations

from typing import Sequence

from src.indicators.atr import atr_percent_series
from src.strategy.swing_detector import SwingBar
from src.strategy.technical_prices import TechnicalPriceBar


def build_swing_bars(
    bars: Sequence[TechnicalPriceBar],
    *,
    atr_period: int = 14,
) -> tuple[SwingBar, ...]:
    """Build ATR-aware swing-detector input from technical prices.

    Policy
    ------
    1. Only corporate-action-safe TechnicalPriceBar inputs are accepted.
    2. ATR is calculated from adjusted High / Low / Close.
    3. ATR values are causal: each value uses only data available on
       or before that bar.
    4. Bars inside the ATR warm-up period are omitted rather than
       assigned an invented ATR value.
    """

    ordered = tuple(bars)

    if not ordered:
        return ()

    for previous, current in zip(
        ordered,
        ordered[1:],
    ):
        if current.date <= previous.date:
            raise ValueError(
                "technical price bars must be strictly increasing by date"
            )

    for bar in ordered:
        if bar.adjustment_status != "OK":
            raise ValueError(
                "technical price bar is not safe for swing detection: "
                f"{bar.adjustment_status} on {bar.date}"
            )

    highs = [
        float(bar.high)
        for bar in ordered
    ]
    lows = [
        float(bar.low)
        for bar in ordered
    ]
    closes = [
        float(bar.close)
        for bar in ordered
    ]

    atr_values = atr_percent_series(
        highs,
        lows,
        closes,
        period=atr_period,
    )

    output: list[SwingBar] = []

    for bar, atr_pct in zip(
        ordered,
        atr_values,
    ):
        if atr_pct is None:
            continue

        output.append(
            SwingBar(
                date=bar.date,
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                atr_pct=float(atr_pct),
            )
        )

    return tuple(output)
