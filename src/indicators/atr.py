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


def atr_percent_series(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> list[float | None]:
    """Return causal Wilder ATR% aligned one-for-one with price bars.

    The first ``period`` price bars return None because ``period``
    True Range observations require ``period + 1`` price bars.

    Every later value uses only information available on or before
    that bar. The Wilder state is updated once per new True Range.
    """

    if period <= 0:
        raise ValueError("period must be positive")

    if not (
        len(highs)
        == len(lows)
        == len(closes)
    ):
        raise ValueError(
            "OHLC arrays must have equal length"
        )

    result: list[float | None] = [
        None
    ] * len(closes)

    tr = true_ranges(
        highs,
        lows,
        closes,
    )

    if len(tr) < period:
        return result

    # The initial Wilder ATR is the SMA of the first ``period``
    # True Range observations. Since TR starts on price bar 1,
    # this first ATR belongs to price-bar index ``period``.
    value = sum(
        tr[:period]
    ) / period

    first_index = period

    if closes[first_index] != 0:
        result[first_index] = (
            value
            / closes[first_index]
            * 100.0
        )

    # tr[k] belongs to price-bar index k + 1.
    for price_index in range(
        period + 1,
        len(closes),
    ):
        current_tr = tr[
            price_index - 1
        ]

        value = (
            (period - 1) * value
            + current_tr
        ) / period

        if closes[price_index] != 0:
            result[price_index] = (
                value
                / closes[price_index]
                * 100.0
            )

    return result

