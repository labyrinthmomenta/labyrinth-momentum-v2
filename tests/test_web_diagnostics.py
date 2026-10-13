from __future__ import annotations

from datetime import date, timedelta

from src.calculation.engine import PriceBar
from src.output.web_diagnostics import (
    build_web_diagnostics,
    write_screener_csv,
)


class WeekdayCalendar:
    def trading_days(self, start: date, end: date):
        result = []
        value = start
        while value <= end:
            if value.weekday() < 5:
                result.append(value)
            value += timedelta(days=1)
        return result


def _bar(day: date, close: float) -> PriceBar:
    return PriceBar(
        day,
        close,
        close,
        close,
        close,
        1000.0,
    )


def test_web_diagnostics_counts_positive_negative_flat():
    bars = [
        _bar(date(2026, 8, 31), 100.0),
        _bar(date(2026, 9, 1), 101.0),
        _bar(date(2026, 9, 2), 100.0),
        _bar(date(2026, 9, 3), 100.0),
        _bar(date(2026, 10, 1), 110.0),
        _bar(date(2026, 10, 2), 110.0),
    ]

    payload = build_web_diagnostics(
        bars,
        WeekdayCalendar(),
        as_of=date(2026, 10, 2),
        listing_start=date(2020, 1, 1),
        months=2,
    )

    september = payload["monthly_history"][0]
    october = payload["monthly_history"][1]

    assert september["positive"] == 1
    assert september["negative"] == 1
    assert september["flat"] == 1

    assert october["positive"] == 1
    assert october["negative"] == 0
    assert october["flat"] == 1

    assert payload["screener"]["current_month"] == "2026-10"
    assert payload["screener"]["current_month_positive"] == 1
    assert payload["screener"]["current_month_negative"] == 0
    assert payload["screener"]["current_month_flat"] == 1


def test_web_diagnostics_reports_session_gap():
    bars = [
        _bar(date(2026, 10, 1), 100.0),
        _bar(date(2026, 10, 2), 101.0),
    ]

    payload = build_web_diagnostics(
        bars,
        WeekdayCalendar(),
        as_of=date(2026, 10, 5),
        listing_start=date(2020, 1, 1),
        months=1,
    )

    current = payload["monthly_history"][0]

    assert current["sessions"] == 2
    assert current["expected_sessions"] == 3
    assert current["session_gap"] == 1


def test_screener_csv_roundtrip_shape(tmp_path):
    path = tmp_path / "screener.csv"

    write_screener_csv(
        path,
        [
            {
                "ticker": "AAA",
                "core_ready": True,
                "value": 1.25,
                "empty": None,
            }
        ],
    )

    content = path.read_text(encoding="utf-8-sig")

    assert "ticker" in content
    assert "AAA" in content
    assert "true" in content
    assert "1.25" in content
