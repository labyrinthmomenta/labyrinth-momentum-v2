from datetime import date
from pathlib import Path
import sqlite3

from src.data.storage.indices import (
    ensure_core_market_indices,
    load_index_price_bars,
)


SCHEMA = Path(
    "src/data/storage/schema.sql"
)


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        SCHEMA.read_text()
    )
    ensure_core_market_indices(conn)
    return conn


def test_load_index_price_bars_accepts_verified_close_only_row():
    conn = make_conn()

    conn.execute(
        """
        INSERT INTO index_daily_prices(
            index_code,
            date,
            open,
            high,
            low,
            close,
            volume,
            source,
            fetched_at
        )
        VALUES (
            'XU030',
            '2025-12-25',
            NULL,
            NULL,
            NULL,
            12305.97,
            NULL,
            'VERIFIED_PUBLIC_CLOSE',
            '2026-10-08T00:00:00+03:00'
        )
        """
    )

    bars = load_index_price_bars(
        conn,
        "XU030",
        start=date(2025, 12, 25),
        end=date(2025, 12, 25),
    )

    assert len(bars) == 1

    bar = bars[0]

    assert bar.date == date(2025, 12, 25)
    assert bar.close == 12305.97
    assert bar.open is None
    assert bar.high is None
    assert bar.low is None
    assert bar.volume is None


def test_load_recent_index_price_bars_accepts_verified_close_only_row():
    conn = make_conn()

    conn.execute(
        """
        INSERT INTO index_daily_prices(
            index_code,
            date,
            open,
            high,
            low,
            close,
            volume,
            source,
            fetched_at
        )
        VALUES (
            'XU100',
            '2025-12-25',
            NULL,
            NULL,
            NULL,
            11336.18,
            NULL,
            'VERIFIED_PUBLIC_CLOSE',
            '2026-10-08T00:00:00+03:00'
        )
        """
    )

    from src.data.storage.indices import (
        load_recent_index_price_bars,
    )

    bars = load_recent_index_price_bars(
        conn,
        "XU100",
        end=date(2025, 12, 25),
        limit=1,
    )

    assert len(bars) == 1

    bar = bars[0]

    assert bar.date == date(2025, 12, 25)
    assert bar.close == 11336.18
    assert bar.open is None
    assert bar.high is None
    assert bar.low is None
    assert bar.volume is None
