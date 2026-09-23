from __future__ import annotations

import math
from typing import Sequence


def cumulative_return(returns: Sequence[float]) -> float | None:
    """Compound daily returns. Returns None when no observations exist."""
    if not returns:
        return None
    value = 1.0
    for r in returns:
        if r is None or not math.isfinite(r):
            return None
        value *= 1.0 + r
    return value - 1.0


def momentum(returns: Sequence[float], window: int) -> float | None:
    """Momentum over the latest completed window of daily returns."""
    if len(returns) < window:
        return None
    return cumulative_return(list(returns[-window:]))
