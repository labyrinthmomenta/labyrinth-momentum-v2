import pytest

from src.research.vcp_maturity import (
    DEFAULT_MIN_HISTORY_SESSIONS,
    is_history_mature,
)


def test_default_research_maturity_threshold_is_80_sessions():
    assert DEFAULT_MIN_HISTORY_SESSIONS == 80


@pytest.mark.parametrize(
    ("history_sessions", "expected"),
    (
        (0, False),
        (1, False),
        (59, False),
        (79, False),
        (80, True),
        (81, True),
        (120, True),
        (250, True),
    ),
)
def test_history_maturity_uses_inclusive_minimum(
    history_sessions,
    expected,
):
    assert (
        is_history_mature(
            history_sessions
        )
        is expected
    )


def test_history_maturity_allows_explicit_research_override():
    assert (
        is_history_mature(
            89,
            min_history_sessions=90,
        )
        is False
    )

    assert (
        is_history_mature(
            90,
            min_history_sessions=90,
        )
        is True
    )


@pytest.mark.parametrize(
    "history_sessions",
    (
        -1,
        -100,
    ),
)
def test_history_maturity_rejects_negative_history(
    history_sessions,
):
    with pytest.raises(
        ValueError,
        match="history_sessions",
    ):
        is_history_mature(
            history_sessions
        )


@pytest.mark.parametrize(
    "minimum",
    (
        0,
        -1,
    ),
)
def test_history_maturity_rejects_nonpositive_minimum(
    minimum,
):
    with pytest.raises(
        ValueError,
        match="min_history_sessions",
    ):
        is_history_mature(
            120,
            min_history_sessions=minimum,
        )
