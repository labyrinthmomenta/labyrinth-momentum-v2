from __future__ import annotations

from datetime import date

import pytest

from src.calculation.engine import PriceBar
from src.data.calendar import BISTTradingCalendar
from src.data.universe.manager import UniverseRecord
from src.data.universe.official import OfficialUniverseSnapshot
from src.pipeline.preflight import LivePreflightError, run_live_preflight


def calendar():
    return BISTTradingCalendar.from_csv()


class FakeProvider:
    source_name = "Fake"
    def __init__(self, rows):
        self.rows = rows
    def fetch(self, ticker, start, end):
        return [b for b in self.rows[ticker] if start <= b.date <= end]


def snapshot():
    records = [UniverseRecord("A1CAP", "A1"), UniverseRecord("ASELS", "ASELSAN"), UniverseRecord("THYAO", "THY")]
    return OfficialUniverseSnapshot(
        records=records,
        kap_records=3,
        first_trade_records=3,
        first_trade_url="https://example/ilkislem.zip",
        source_date="2026-09-23",
        market_counts={"YILDIZ PAZAR": 3},
    )


def bar(d):
    return PriceBar(d, 100, 102, 99, 101, 1000)


def test_live_preflight_checks_official_membership_and_latest_provider_bar():
    cal = calendar()
    as_of = date(2026, 9, 21)
    latest = cal.latest_trading_day_on_or_before(as_of)
    prior = cal.previous_trading_days(latest, 3)
    provider = FakeProvider({t: [bar(d) for d in prior] for t in ("A1CAP", "ASELS", "THYAO")})
    summary = run_live_preflight(
        calendar=cal,
        provider=provider,
        as_of=as_of,
        universe_fetcher=snapshot,
        tickers=("A1CAP", "ASELS", "THYAO"),
    )
    assert summary.status == "PASS"
    assert summary.equities == 3
    assert all(p.last_bar == latest for p in summary.probes)


def test_live_preflight_fails_if_ticker_is_not_official_equity():
    with pytest.raises(LivePreflightError, match="missing from official"):
        run_live_preflight(
            calendar=calendar(),
            provider=FakeProvider({}),
            as_of=date(2026, 9, 21),
            universe_fetcher=snapshot,
            tickers=("NOTREAL",),
        )


def test_live_preflight_fails_on_stale_provider():
    cal = calendar()
    as_of = date(2026, 9, 21)
    latest = cal.latest_trading_day_on_or_before(as_of)
    stale = cal.previous_trading_days(latest, 2)[0]
    provider = FakeProvider({"THYAO": [bar(stale)]})
    with pytest.raises(LivePreflightError, match="latest bar"):
        run_live_preflight(
            calendar=cal,
            provider=provider,
            as_of=as_of,
            universe_fetcher=snapshot,
            tickers=("THYAO",),
        )
