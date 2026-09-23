from __future__ import annotations

from typing import Sequence


def true_ranges(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> list[float]:
    """True Range for each bar after the first bar."""
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("OHLC arrays must have equal length")
    if len(closes) < 2:
        return []
    return [
        max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        for i in range(1, len(closes))
    ]


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> float | None:
    """Wilder ATR using the standard initial SMA followed by Wilder smoothing."""
    if period <= 0:
        raise ValueError("period must be positive")
    tr = true_ranges(highs, lows, closes)
    if len(tr) < period:
        return None

    value = sum(tr[:period]) / period
    for current in tr[period:]:
        value = ((period - 1) * value + current) / period
    return value


def atr_percent(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> float | None:
    value = atr(highs, lows, closes, period)
    if value is None or not closes or closes[-1] == 0:
        return None
    return value / closes[-1] * 100.0
