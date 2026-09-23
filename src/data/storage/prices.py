from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import sqlite3
from typing import Iterable

from src.calculation.engine import PriceBar


@dataclass(frozen=True)
class SecurityForUpdate:
    security_id: int
    ticker: str
    name: str
    first_trade_date: date | None
    status: str


@dataclass(frozen=True)
class IdentifierPeriod:
    ticker: str
    valid_from: date
    valid_to: date | None  # exclusive when present

    def contains(self, value: date) -> bool:
        return self.valid_from <= value and (self.valid_to is None or value < self.valid_to)


def active_equities(conn: sqlite3.Connection) -> list[SecurityForUpdate]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT s.security_id, s.name, s.first_trade_date, s.status, si.ticker
        FROM securities s
        JOIN security_identifiers si ON si.security_id=s.security_id
        WHERE s.instrument_type='EQUITY'
          AND s.active=1
          AND s.status='ACTIVE'
          AND si.is_current=1
        ORDER BY si.ticker
        """
    ).fetchall()
    return [
        SecurityForUpdate(
            security_id=int(row["security_id"]),
            ticker=row["ticker"],
            name=row["name"],
            first_trade_date=date.fromisoformat(row["first_trade_date"]) if row["first_trade_date"] else None,
            status=row["status"],
        )
        for row in rows
    ]


def identifier_periods(conn: sqlite3.Connection, security_id: int) -> list[IdentifierPeriod]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT ticker, valid_from, valid_to
        FROM security_identifiers
        WHERE security_id=?
        ORDER BY valid_from, identifier_id
        """,
        (security_id,),
    ).fetchall()
    return [
        IdentifierPeriod(
            ticker=row["ticker"],
            valid_from=date.fromisoformat(row["valid_from"]),
            valid_to=date.fromisoformat(row["valid_to"]) if row["valid_to"] else None,
        )
        for row in rows
    ]


def ticker_for_date(periods: Iterable[IdentifierPeriod], value: date) -> str | None:
    matches = [period for period in periods if period.contains(value)]
    if not matches:
        return None
    # If legacy data contains overlapping periods, prefer the latest valid_from.
    return max(matches, key=lambda item: item.valid_from).ticker


def load_price_bars(
    conn: sqlite3.Connection,
    security_id: int,
    *,
    start: date | None = None,
    end: date | None = None,
) -> list[PriceBar]:
    sql = "SELECT date, open, high, low, close, volume FROM daily_prices WHERE security_id=?"
    params: list[object] = [security_id]
    if start is not None:
        sql += " AND date>=?"
        params.append(start.isoformat())
    if end is not None:
        sql += " AND date<=?"
        params.append(end.isoformat())
    sql += " ORDER BY date"
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        PriceBar(
            date.fromisoformat(row[0]),
            float(row[1]),
            float(row[2]),
            float(row[3]),
            float(row[4]),
            None if row[5] is None else float(row[5]),
        )
        for row in rows
    ]


def upsert_price_bars(
    conn: sqlite3.Connection,
    security_id: int,
    bars: Iterable[PriceBar],
    *,
    ticker_at_date: dict[date, str],
    source: str,
    fetched_at: str | None = None,
) -> tuple[int, int]:
    """Upsert validated bars. Caller owns the transaction."""
    bars = list(bars)
    if not bars:
        return 0, 0
    fetched_at = fetched_at or datetime.now().astimezone().isoformat()
    dates = [bar.date.isoformat() for bar in bars]
    placeholders = ",".join("?" for _ in dates)
    existing = {
        row[0]
        for row in conn.execute(
            f"SELECT date FROM daily_prices WHERE security_id=? AND date IN ({placeholders})",
            (security_id, *dates),
        ).fetchall()
    }
    rows = [
        (
            security_id,
            bar.date.isoformat(),
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            ticker_at_date[bar.date],
            source,
            fetched_at,
        )
        for bar in bars
    ]
    conn.executemany(
        """
        INSERT INTO daily_prices(
            security_id,date,open,high,low,close,volume,ticker_at_date,source,fetched_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(security_id,date) DO UPDATE SET
            open=excluded.open,
            high=excluded.high,
            low=excluded.low,
            close=excluded.close,
            volume=excluded.volume,
            ticker_at_date=excluded.ticker_at_date,
            source=excluded.source,
            fetched_at=excluded.fetched_at
        """,
        rows,
    )
    updated = sum(1 for value in dates if value in existing)
    return len(dates) - updated, updated


def load_recent_price_bars(
    conn: sqlite3.Connection,
    security_id: int,
    *,
    end: date,
    limit: int,
) -> list[PriceBar]:
    """Load the most recent N canonical bars through `end`, ascending by date."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    rows = conn.execute(
        """
        SELECT date, open, high, low, close, volume
        FROM daily_prices
        WHERE security_id=? AND date<=?
        ORDER BY date DESC
        LIMIT ?
        """,
        (security_id, end.isoformat(), limit),
    ).fetchall()
    bars = [
        PriceBar(
            date.fromisoformat(row[0]),
            float(row[1]),
            float(row[2]),
            float(row[3]),
            float(row[4]),
            None if row[5] is None else float(row[5]),
        )
        for row in rows
    ]
    return list(reversed(bars))
