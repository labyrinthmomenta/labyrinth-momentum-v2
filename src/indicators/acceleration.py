from __future__ import annotations


def delta(short_value: float | None, long_value: float | None) -> float | None:
    if short_value is None or long_value is None:
        return None
    return short_value - long_value
