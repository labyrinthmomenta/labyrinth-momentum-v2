from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest

from src.calculation.engine import PriceBar
from src.data.calendar import BISTTradingCalendar
from src.data.storage.database import Database
from src.data.universe.manager import UniverseManager, UniverseRecord
from src.pipeline.daily import DailyPipelineError, run_daily_pipeline


class CalendarProvider:
    source_name = "TEST"

    def __init__(self, calendar: BISTTradingCalendar, broken_ticker: str | None = None):
        self.calendar = calendar
        self.broken_ticker = broken_ticker
        self.calls: list[tuple[str, date, date]] = []

    def fetch(self, ticker: str, start: date, end: date) -> list[PriceBar]:
        self.calls.append((ticker, start, end))
        days = self.calendar.trading_days(start, end)
        bars = []
        for i, day in enumerate(days):
            base = 100.0 + ((day.toordinal() % 97) * 0.07)
            high = base + 1.0
            low = base - 1.0
            if ticker == self.broken_ticker and i == 0:
                high = base - 2.0
            bars.append(PriceBar(day, base, high, low, base + 0.2, 1000.0 + i))
        return bars


def records():
    return [
        UniverseRecord("AAA", "Alpha A.S.", first_trade_date="2023-01-02"),
        UniverseRecord("BBB", "Beta A.S.", first_trade_date="2023-01-02"),
    ]


def test_end_to_end_dry_run_does_not_mutate_canonical_db_or_public_dir(tmp_path):
    calendar = BISTTradingCalendar.from_csv()
    db_path = tmp_path / "canonical.db"
    db = Database(db_path)
    db.initialize()
    UniverseManager(db.conn).sync(records(), as_of="2026-09-23")
    before = db.conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
    db.close()

    public = tmp_path / "docs" / "data"
    public.mkdir(parents=True)
    (public / "keep.txt").write_text("untouched", encoding="utf-8")
    dry = tmp_path / "dry-output"
    summary = run_daily_pipeline(
        db_path=db_path,
        calendar=calendar,
        provider=CalendarProvider(calendar),
        as_of=date(2026, 9, 23),
        public_dir=public,
        tickers={"AAA"},
        dry_run=True,
        dry_run_dir=dry,
    )
    assert summary.public_promoted is False
    assert (public / "keep.txt").read_text(encoding="utf-8") == "untouched"
    assert (dry / "screener.json").exists()
    assert (dry / "details" / "AAA.json").exists()
    db = Database(db_path)
    after = db.conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
    db.close()
    assert before == after == 0


def test_partial_universe_cannot_publish(tmp_path):
    calendar = BISTTradingCalendar.from_csv()
    db_path = tmp_path / "canonical.db"
    db = Database(db_path)
    db.initialize()
    UniverseManager(db.conn).sync(records(), as_of="2026-09-23")
    db.close()
    with pytest.raises(DailyPipelineError, match="dry-run only"):
        run_daily_pipeline(
            db_path=db_path,
            calendar=calendar,
            provider=CalendarProvider(calendar),
            as_of=date(2026, 9, 23),
            public_dir=tmp_path / "docs" / "data",
            tickers={"AAA"},
            dry_run=False,
        )


def test_full_daily_run_promotes_only_after_all_securities_pass(tmp_path):
    calendar = BISTTradingCalendar.from_csv()
    db_path = tmp_path / "canonical.db"
    summary = run_daily_pipeline(
        db_path=db_path,
        calendar=calendar,
        provider=CalendarProvider(calendar),
        as_of=date(2026, 9, 23),
        public_dir=tmp_path / "docs" / "data",
        authoritative_universe_records=records(),
        dry_run=False,
    )
    assert summary.public_promoted is True
    assert summary.securities_selected == 2
    public = tmp_path / "docs" / "data"
    manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "PASS"
    assert manifest["securities_published"] == 2
    assert (public / "details" / "AAA.json").exists()
    assert (public / "details" / "BBB.json").exists()
    screener = json.loads((public / "screener.json").read_text(encoding="utf-8"))
    assert {row["ticker"] for row in screener} == {"AAA", "BBB"}


def test_failed_security_blocks_public_promotion(tmp_path):
    calendar = BISTTradingCalendar.from_csv()
    db_path = tmp_path / "canonical.db"
    public = tmp_path / "docs" / "data"
    public.mkdir(parents=True)
    (public / "previous.json").write_text('{"version":"good"}', encoding="utf-8")

    with pytest.raises(DailyPipelineError):
        run_daily_pipeline(
            db_path=db_path,
            calendar=calendar,
            provider=CalendarProvider(calendar, broken_ticker="BBB"),
            as_of=date(2026, 9, 23),
            public_dir=public,
            authoritative_universe_records=records(),
            dry_run=False,
        )
    assert (public / "previous.json").read_text(encoding="utf-8") == '{"version":"good"}'
    db = Database(db_path)
    assert db.conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0] == 0
    db.close()


def test_new_listing_can_publish_with_null_long_windows(tmp_path):
    calendar = BISTTradingCalendar.from_csv()
    db_path = tmp_path / "canonical.db"
    records_new = [UniverseRecord("NEW", "New IPO A.S.", first_trade_date="2026-09-01")]
    summary = run_daily_pipeline(
        db_path=db_path,
        calendar=calendar,
        provider=CalendarProvider(calendar),
        as_of=date(2026, 9, 23),
        public_dir=tmp_path / "docs" / "data",
        authoritative_universe_records=records_new,
        dry_run=False,
    )
    assert summary.public_promoted
    payload = json.loads((tmp_path / "docs" / "data" / "details" / "NEW.json").read_text(encoding="utf-8"))
    assert payload["snapshot"]["momentum_252"] is None
    assert payload["snapshot"]["fip_252"] is None
    assert payload["snapshot"]["observations"] < 252


def test_second_full_run_is_idempotent_for_market_data(tmp_path):
    calendar = BISTTradingCalendar.from_csv()
    db_path = tmp_path / "canonical.db"
    public = tmp_path / "docs" / "data"
    provider = CalendarProvider(calendar)
    first = run_daily_pipeline(
        db_path=db_path,
        calendar=calendar,
        provider=provider,
        as_of=date(2026, 9, 23),
        public_dir=public,
        authoritative_universe_records=records(),
        dry_run=False,
    )
    calls_after_first = len(provider.calls)
    second = run_daily_pipeline(
        db_path=db_path,
        calendar=calendar,
        provider=provider,
        as_of=date(2026, 9, 23),
        public_dir=public,
        authoritative_universe_records=records(),
        dry_run=False,
    )
    assert first.update.prices_inserted > 0
    assert second.update.prices_inserted == 0
    assert second.update.prices_updated == 0
    assert len(provider.calls) == calls_after_first
