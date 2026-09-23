from __future__ import annotations

import math
from typing import Sequence

from .momentum import cumulative_return


def sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def fip(returns: Sequence[float], window: int) -> float | None:
    """V2 selected FIP convention: sign(Momentum)*(Nneg-Npos)/N."""
    if len(returns) < window:
        return None
    sample = list(returns[-window:])
    if any(r is None or not math.isfinite(r) for r in sample):
        return None
    mom = cumulative_return(sample)
    n = len(sample)
    neg = sum(1 for r in sample if r < 0)
    pos = sum(1 for r in sample if r > 0)
    return sign(mom) * (neg - pos) / n
