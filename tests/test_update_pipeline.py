from __future__ import annotations

from datetime import date, datetime
import sqlite3

import pytest

from src.calculation.engine import PriceBar
from src.data.calendar import BISTTradingCalendar
from src.data.storage.database import Database
from src.pipeline.update import UpdatePipelineError, run_incremental_update


class FakeProvider:
    source_name = "FAKE"

    def __init__(self, data):
        self.data = data
        self.calls = []

    def fetch(self, ticker, start, end):
        self.calls.append((ticker, start, end))
        return [bar for bar in self.data.get(ticker, []) if start <= bar.date <= end]


def mkbar(day, close):
    return PriceBar(day, close, close + 1.0, close - 1.0, close, 1000.0)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    yield database
    database.close()


@pytest.fixture()
def calendar():
    return BISTTradingCalendar.from_csv()


def add_security(db, ticker="TEST", name="Test AS", first_trade="2025-01-02"):
    now = datetime.now().astimezone().isoformat()
    cur = db.conn.execute(
        """INSERT INTO securities(name,instrument_type,status,first_trade_date,active,created_at,updated_at)
           VALUES (?,?,?,?,1,?,?)""",
        (name, "EQUITY", "ACTIVE", first_trade, now, now),
    )
    sid = int(cur.lastrowid)
    db.conn.execute(
        """INSERT INTO security_identifiers(security_id,ticker,valid_from,is_current,source)
           VALUES (?,?,?,1,'TEST')""",
        (sid, ticker, first_trade),
    )
    db.conn.commit()
    return sid


def insert_bars(db, sid, ticker, bars):
    now = datetime.now().astimezone().isoformat()
    db.conn.executemany(
        """INSERT INTO daily_prices
           (security_id,date,open,high,low,close,volume,ticker_at_date,source,fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        [
            (sid, b.date.isoformat(), b.open, b.high, b.low, b.close, b.volume, ticker, "SEED", now)
            for b in bars
        ],
    )
    db.conn.commit()


def count_prices(db, sid):
    return db.conn.execute("SELECT COUNT(*) FROM daily_prices WHERE security_id=?", (sid,)).fetchone()[0]


def test_fetches_only_missing_latest_session_and_commits(db, calendar):
    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 6)
    sid = add_security(db, first_trade=days[0].isoformat())
    seed = [mkbar(day, 100 + i) for i, day in enumerate(days[:-1])]
    insert_bars(db, sid, "TEST", seed)
    provider = FakeProvider({"TEST": [mkbar(days[-1], 105)]})

    summary = run_incremental_update(
        db.conn, calendar, provider, as_of=as_of, required_return_window=5
    )

    assert summary.status == "SUCCESS"
    assert summary.prices_inserted == 1
    assert summary.provider_calls == 1
    assert provider.calls == [("TEST", days[-1], days[-1])]
    assert count_prices(db, sid) == 6


def test_second_run_is_idempotent_and_makes_no_provider_call(db, calendar):
    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 6)
    sid = add_security(db, first_trade=days[0].isoformat())
    insert_bars(db, sid, "TEST", [mkbar(day, 100 + i) for i, day in enumerate(days)])
    provider = FakeProvider({})

    summary = run_incremental_update(
        db.conn, calendar, provider, as_of=as_of, required_return_window=5
    )

    assert summary.status == "SUCCESS"
    assert summary.provider_calls == 0
    assert summary.prices_inserted == 0
    assert count_prices(db, sid) == 6


def test_ipo_short_history_is_valid_not_missing_pre_listing_sessions(db, calendar):
    as_of = date(2026, 9, 21)
    recent = calendar.previous_trading_days(as_of, 4)
    sid = add_security(db, first_trade=recent[0].isoformat())
    provider = FakeProvider({"TEST": [mkbar(day, 50 + i) for i, day in enumerate(recent)]})

    summary = run_incremental_update(
        db.conn, calendar, provider, as_of=as_of, required_return_window=21
    )

    assert summary.status == "SUCCESS"
    assert summary.prices_inserted == 4
    assert count_prices(db, sid) == 4


def test_ticker_change_fetches_each_identifier_for_its_valid_period(db, calendar):
    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 6)
    effective = days[3]
    sid = add_security(db, ticker="OLD", name="Rename AS", first_trade=days[0].isoformat())
    db.conn.execute(
        "UPDATE security_identifiers SET valid_to=?, is_current=0 WHERE security_id=?",
        (effective.isoformat(), sid),
    )
    db.conn.execute(
        """INSERT INTO security_identifiers(security_id,ticker,valid_from,is_current,source)
           VALUES (?,?,?,1,'TEST')""",
        (sid, "NEW", effective.isoformat()),
    )
    db.conn.commit()
    provider = FakeProvider(
        {
            "OLD": [mkbar(day, 100 + i) for i, day in enumerate(days[:3])],
            "NEW": [mkbar(day, 103 + i) for i, day in enumerate(days[3:])],
        }
    )

    summary = run_incremental_update(
        db.conn, calendar, provider, as_of=as_of, required_return_window=5
    )

    assert summary.status == "SUCCESS"
    assert [call[0] for call in provider.calls] == ["OLD", "NEW"]
    stored = db.conn.execute(
        "SELECT date,ticker_at_date FROM daily_prices WHERE security_id=? ORDER BY date", (sid,)
    ).fetchall()
    assert [row[1] for row in stored[:3]] == ["OLD"] * 3
    assert [row[1] for row in stored[3:]] == ["NEW"] * 3


def test_validation_failure_rolls_back_all_price_mutations(db, calendar):
    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 4)
    sid1 = add_security(db, ticker="AAA", name="AAA AS", first_trade=days[0].isoformat())
    sid2 = add_security(db, ticker="BBB", name="BBB AS", first_trade=days[0].isoformat())
    # AAA is complete. BBB deliberately omits the latest required session.
    provider = FakeProvider(
        {
            "AAA": [mkbar(day, 100 + i) for i, day in enumerate(days)],
            "BBB": [mkbar(day, 200 + i) for i, day in enumerate(days[:-1])],
        }
    )

    with pytest.raises(UpdatePipelineError):
        run_incremental_update(
            db.conn, calendar, provider, as_of=as_of, required_return_window=3
        )

    assert count_prices(db, sid1) == 0
    assert count_prices(db, sid2) == 0
    run = db.conn.execute(
        "SELECT status,validation_status,prices_inserted FROM pipeline_runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert tuple(run) == ("FAILED", "FAIL", 0)


def test_duplicate_provider_date_fails_before_commit(db, calendar):
    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 2)
    sid = add_security(db, first_trade=days[0].isoformat())
    duplicate = mkbar(days[0], 100)
    provider = FakeProvider({"TEST": [duplicate, duplicate, mkbar(days[1], 101)]})

    with pytest.raises(UpdatePipelineError, match="DUPLICATE_DATE"):
        run_incremental_update(
            db.conn, calendar, provider, as_of=as_of, required_return_window=1
        )
    assert count_prices(db, sid) == 0


def test_batch_provider_collapses_same_date_range(db, calendar):
    from src.data.providers.base import BatchFetchResult

    class FakeBatchProvider(FakeProvider):
        def __init__(self, data):
            super().__init__(data)
            self.batch_calls = []

        def fetch(self, ticker, start, end):  # pragma: no cover - must not be used
            raise AssertionError("single-ticker fetch should not be used")

        def fetch_many(self, tickers, start, end):
            self.batch_calls.append((tuple(tickers), start, end))
            return BatchFetchResult(
                {
                    ticker: [bar for bar in self.data.get(ticker, []) if start <= bar.date <= end]
                    for ticker in tickers
                },
                provider_calls=1,
            )

    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 4)
    sid1 = add_security(db, ticker="AAA", name="AAA AS", first_trade=days[0].isoformat())
    sid2 = add_security(db, ticker="BBB", name="BBB AS", first_trade=days[0].isoformat())
    provider = FakeBatchProvider(
        {
            "AAA": [mkbar(day, 100 + i) for i, day in enumerate(days)],
            "BBB": [mkbar(day, 200 + i) for i, day in enumerate(days)],
        }
    )

    summary = run_incremental_update(
        db.conn, calendar, provider, as_of=as_of, required_return_window=3
    )

    assert summary.status == "SUCCESS"
    assert summary.provider_calls == 1
    assert len(provider.batch_calls) == 1
    assert provider.batch_calls[0][0] == ("AAA", "BBB")
    assert count_prices(db, sid1) == 4
    assert count_prices(db, sid2) == 4


def test_batch_provider_reports_underlying_vendor_call_count(db, calendar):
    from src.data.providers.base import BatchFetchResult

    class ChunkedFakeProvider(FakeProvider):
        def fetch_many(self, tickers, start, end):
            return BatchFetchResult(
                {
                    ticker: [bar for bar in self.data.get(ticker, []) if start <= bar.date <= end]
                    for ticker in tickers
                },
                provider_calls=3,
            )

    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 2)
    add_security(db, ticker="AAA", name="AAA AS", first_trade=days[0].isoformat())
    add_security(db, ticker="BBB", name="BBB AS", first_trade=days[0].isoformat())
    provider = ChunkedFakeProvider(
        {
            "AAA": [mkbar(day, 100 + i) for i, day in enumerate(days)],
            "BBB": [mkbar(day, 200 + i) for i, day in enumerate(days)],
        }
    )

    summary = run_incremental_update(
        db.conn, calendar, provider, as_of=as_of, required_return_window=1
    )
    assert summary.provider_calls == 3


def test_never_seen_empty_security_is_provider_unavailable(db, calendar):
    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 4)

    sid_ok = add_security(
        db, ticker="AAA", name="AAA AS", first_trade=days[0].isoformat()
    )
    sid_missing = add_security(
        db, ticker="BBB", name="BBB AS", first_trade=days[0].isoformat()
    )

    provider = FakeProvider(
        {
            "AAA": [mkbar(day, 100 + i) for i, day in enumerate(days)],
            "BBB": [],
        }
    )

    summary = run_incremental_update(
        db.conn,
        calendar,
        provider,
        as_of=as_of,
        required_return_window=3,
    )

    assert summary.status == "SUCCESS"
    assert summary.provider_unavailable == 1
    assert count_prices(db, sid_ok) == 4
    assert count_prices(db, sid_missing) == 0

    statuses = db.conn.execute(
        """SELECT sds.status, si.ticker
           FROM security_data_status sds
           JOIN security_identifiers si
             ON si.security_id=sds.security_id
            AND si.is_current=1
           WHERE sds.run_id=?
           ORDER BY si.ticker""",
        (summary.run_id,),
    ).fetchall()

    assert [tuple(row) for row in statuses] == [
        ("OK", "AAA"),
        ("PROVIDER_UNAVAILABLE", "BBB"),
    ]


def test_all_selected_empty_trips_provider_circuit_breaker(db, calendar):
    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 4)

    add_security(db, ticker="AAA", name="AAA AS", first_trade=days[0].isoformat())
    add_security(db, ticker="BBB", name="BBB AS", first_trade=days[0].isoformat())

    provider = FakeProvider({"AAA": [], "BBB": []})

    with pytest.raises(UpdatePipelineError, match="circuit breaker"):
        run_incremental_update(
            db.conn,
            calendar,
            provider,
            as_of=as_of,
            required_return_window=3,
        )

    assert db.conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM security_data_status").fetchone()[0] == 0


def test_existing_history_missing_latest_is_not_provider_unavailable(db, calendar):
    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 4)

    sid = add_security(
        db, ticker="AAA", name="AAA AS", first_trade=days[0].isoformat()
    )

    insert_bars(
        db,
        sid,
        "AAA",
        [mkbar(day, 100 + i) for i, day in enumerate(days[:-1])],
    )

    provider = FakeProvider({"AAA": []})

    with pytest.raises(UpdatePipelineError, match="MISSING_TRADING_SESSION"):
        run_incremental_update(
            db.conn,
            calendar,
            provider,
            as_of=as_of,
            required_return_window=3,
        )

    assert db.conn.execute("SELECT COUNT(*) FROM security_data_status").fetchone()[0] == 0


def test_provider_unavailable_limit_trips_circuit_breaker(db, calendar):
    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 2)

    good = add_security(
        db, ticker="GOOD", name="Good AS", first_trade=days[0].isoformat()
    )

    data = {
        "GOOD": [mkbar(day, 100 + i) for i, day in enumerate(days)],
    }

    for i in range(6):
        ticker = f"M{i}"
        add_security(
            db,
            ticker=ticker,
            name=f"Missing {i} AS",
            first_trade=days[0].isoformat(),
        )
        data[ticker] = []

    provider = FakeProvider(data)

    with pytest.raises(UpdatePipelineError, match="exceeded limit"):
        run_incremental_update(
            db.conn,
            calendar,
            provider,
            as_of=as_of,
            required_return_window=1,
        )

    assert count_prices(db, good) == 0
    assert db.conn.execute("SELECT COUNT(*) FROM security_data_status").fetchone()[0] == 0



def test_fallback_recovers_only_missing_required_session_and_preserves_source(db, calendar):
    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 4)
    sid = add_security(
        db,
        ticker="TEST",
        name="Test AS",
        first_trade=days[0].isoformat(),
    )

    missing = days[1]
    primary_bars = [
        mkbar(day, 100 + i)
        for i, day in enumerate(days)
        if day != missing
    ]

    provider = FakeProvider({"TEST": primary_bars})
    fallback = FakeProvider({"TEST": [mkbar(missing, 150)]})
    fallback.source_name = "BIST_THB"

    summary = run_incremental_update(
        db.conn,
        calendar,
        provider,
        as_of=as_of,
        required_return_window=3,
        fallback_provider=fallback,
    )

    assert summary.status == "SUCCESS"
    assert summary.prices_inserted == 4
    assert summary.provider_calls == 2
    assert fallback.calls == [("TEST", missing, missing)]
    assert count_prices(db, sid) == 4

    sources = dict(
        db.conn.execute(
            "SELECT date, source FROM daily_prices WHERE security_id=? ORDER BY date",
            (sid,),
        ).fetchall()
    )

    assert sources[missing.isoformat()] == "BIST_THB"
    for day in days:
        if day != missing:
            assert sources[day.isoformat()] == "FAKE"


def test_fallback_is_not_called_when_primary_history_is_complete(db, calendar):
    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 4)

    add_security(
        db,
        ticker="TEST",
        name="Test AS",
        first_trade=days[0].isoformat(),
    )

    provider = FakeProvider({
        "TEST": [mkbar(day, 100 + i) for i, day in enumerate(days)]
    })
    fallback = FakeProvider({})
    fallback.source_name = "BIST_THB"

    summary = run_incremental_update(
        db.conn,
        calendar,
        provider,
        as_of=as_of,
        required_return_window=3,
        fallback_provider=fallback,
    )

    assert summary.status == "SUCCESS"
    assert summary.provider_calls == 1
    assert fallback.calls == []


def test_never_seen_primary_empty_remains_provider_unavailable_without_fallback(db, calendar):
    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 4)

    add_security(
        db,
        ticker="GOOD",
        name="Good AS",
        first_trade=days[0].isoformat(),
    )
    add_security(
        db,
        ticker="MISS",
        name="Missing AS",
        first_trade=days[0].isoformat(),
    )

    provider = FakeProvider({
        "GOOD": [mkbar(day, 100 + i) for i, day in enumerate(days)],
        "MISS": [],
    })

    fallback = FakeProvider({
        "MISS": [mkbar(day, 200 + i) for i, day in enumerate(days)]
    })
    fallback.source_name = "BIST_THB"

    summary = run_incremental_update(
        db.conn,
        calendar,
        provider,
        as_of=as_of,
        required_return_window=3,
        fallback_provider=fallback,
    )

    assert summary.status == "SUCCESS"
    assert summary.provider_unavailable == 1
    assert fallback.calls == []

    statuses = db.conn.execute(
        """
        SELECT sds.status, si.ticker
        FROM security_data_status sds
        JOIN security_identifiers si
          ON si.security_id=sds.security_id AND si.is_current=1
        WHERE sds.run_id=?
        ORDER BY si.ticker
        """,
        (summary.run_id,),
    ).fetchall()

    assert [tuple(row) for row in statuses] == [
        ("OK", "GOOD"),
        ("PROVIDER_UNAVAILABLE", "MISS"),
    ]


def test_fallback_miss_still_fails_closed(db, calendar):
    as_of = date(2026, 9, 21)
    days = calendar.previous_trading_days(as_of, 4)

    sid = add_security(
        db,
        ticker="TEST",
        name="Test AS",
        first_trade=days[0].isoformat(),
    )

    insert_bars(
        db,
        sid,
        "TEST",
        [mkbar(day, 100 + i) for i, day in enumerate(days[:-1])],
    )

    provider = FakeProvider({"TEST": []})
    fallback = FakeProvider({})
    fallback.source_name = "BIST_THB"

    with pytest.raises(UpdatePipelineError, match="MISSING_TRADING_SESSION"):
        run_incremental_update(
            db.conn,
            calendar,
            provider,
            as_of=as_of,
            required_return_window=3,
            fallback_provider=fallback,
        )

    assert fallback.calls == [("TEST", days[-1], days[-1])]
    assert count_prices(db, sid) == 3
    assert db.conn.execute(
        "SELECT COUNT(*) FROM security_data_status"
    ).fetchone()[0] == 0
