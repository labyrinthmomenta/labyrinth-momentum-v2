from datetime import date, timedelta
import math

import pytest

from src.calculation.engine import DataQualityError, PriceBar, compute_snapshot, derive_returns, last_completed_month


def bars_from_closes(start: date, closes: list[float]) -> list[PriceBar]:
    return [
        PriceBar(
            date=start + timedelta(days=i),
            open=close,
            high=close + 1.0,
            low=max(0.01, close - 1.0),
            close=close,
            volume=1000,
        )
        for i, close in enumerate(closes)
    ]


def test_returns_are_derived_from_close_not_stored():
    points = derive_returns(bars_from_closes(date(2026, 1, 1), [100.0, 110.0, 99.0]))
    assert len(points) == 2
    assert math.isclose(points[0].value, 0.10, abs_tol=1e-12)
    assert math.isclose(points[1].value, -0.10, abs_tol=1e-12)


def test_snapshot_requires_253_closes_for_252_return_window():
    bars = bars_from_closes(date(2025, 1, 1), [100.0 + i for i in range(252)])
    snapshot = compute_snapshot(bars)
    assert snapshot.observations == 251
    assert snapshot.momentum_252 is None
    assert snapshot.fip_252 is None

    bars = bars_from_closes(date(2025, 1, 1), [100.0 + i for i in range(253)])
    snapshot = compute_snapshot(bars)
    assert snapshot.observations == 252
    assert snapshot.momentum_252 is not None
    assert snapshot.fip_252 is not None


def test_delta_fields_are_short_minus_long():
    # Alternating positive/negative moves make the FIP windows non-trivial.
    closes = [100.0]
    for i in range(1, 90):
        closes.append(closes[-1] * (1.02 if i % 3 else 0.99))
    snapshot = compute_snapshot(bars_from_closes(date(2026, 1, 1), closes))
    assert math.isclose(
        snapshot.delta_momentum_21_63,
        snapshot.momentum_21 - snapshot.momentum_63,
        abs_tol=1e-12,
    )
    assert math.isclose(
        snapshot.delta_fip_21_63,
        snapshot.fip_21 - snapshot.fip_63,
        abs_tol=1e-12,
    )


def test_completed_month_is_calendar_month_not_21_day_window():
    # Daily synthetic bars are sufficient to verify month selection semantics.
    bars = bars_from_closes(date(2026, 7, 20), [100.0 + i for i in range(70)])
    snapshot = compute_snapshot(bars, as_of=date(2026, 9, 20))
    assert snapshot.completed_month == "2026-08"
    assert snapshot.completed_month_observations == 31
    assert snapshot.completed_month_momentum is not None
    assert snapshot.completed_month_fip is not None


def test_last_completed_month_handles_january():
    assert last_completed_month(date(2026, 1, 15)) == (2025, 12)


def test_bad_ohlc_is_rejected_instead_of_silently_zero_filled():
    bars = [
        PriceBar(date(2026, 1, 1), 10, 11, 9, 10),
        PriceBar(date(2026, 1, 2), 10, 8, 9, 10),
    ]
    with pytest.raises(DataQualityError):
        compute_snapshot(bars)
