"""Research-only history maturity policy for VCP replay studies.

This module does not change VCP detection, VCP state assignment,
production screening, or ranking.

It defines only the minimum causal price-history depth required for an
observation to be considered sufficiently mature for historical VCP
research.

The default of 80 sessions is based on detector warm-up diagnostics,
not forward-return optimization.
"""

from __future__ import annotations


DEFAULT_MIN_HISTORY_SESSIONS = 80


def is_history_mature(
    history_sessions: int,
    *,
    min_history_sessions: int = DEFAULT_MIN_HISTORY_SESSIONS,
) -> bool:
    """Return whether causal history satisfies the research minimum."""

    if history_sessions < 0:
        raise ValueError(
            "history_sessions must be nonnegative"
        )

    if min_history_sessions <= 0:
        raise ValueError(
            "min_history_sessions must be positive"
        )

    return (
        history_sessions
        >= min_history_sessions
    )
