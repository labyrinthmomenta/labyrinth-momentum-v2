from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import sqlite3
from typing import Iterable

from src.calculation.engine import PriceBar


@dataclass(frozen=True)
class MarketIndex:
    index_code: str
    name: str
    source: str | None
    active: bool = True


@dataclass(frozen=True)
class IndexPriceBar:
    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None = None


CORE_MARKET_INDICES = (
    MarketIndex(
        index_code="XU030",
        name="BIST 30",
        source="Yahoo Finance",
    ),
    MarketIndex(
        index_code="XU100",
        name="BIST 100",
        source="Yahoo Finance",
    ),
)


def _normalize_code(index_code: str) -> str:
    value = index_code.strip().upper()

    if not value:
        raise ValueError(
            "index_code must not be empty"
        )

    return value


def ensure_core_market_indices(
    conn: sqlite3.Connection,
    *,
    recorded_at: str | None = None,
) -> None:
    """Register the currently supported core regime indices.

    Caller owns the transaction.

    XYUZO and XTUMY are intentionally excluded until a
    usable historical provider is available.
    """

    timestamp = (
        recorded_at
        or datetime.now().astimezone().isoformat()
    )

    rows = [
        (
            item.index_code,
            item.name,
            item.source,
            1 if item.active else 0,
            timestamp,
            timestamp,
        )
        for item in CORE_MARKET_INDICES
    ]

    conn.executemany(
        """
        INSERT INTO market_indices(
            index_code,
            name,
            source,
            active,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)

        ON CONFLICT(index_code) DO UPDATE SET
            name=excluded.name,
            source=excluded.source,
            active=excluded.active,
            updated_at=excluded.updated_at
        """,
        rows,
    )


def active_market_indices(
    conn: sqlite3.Connection,
) -> list[MarketIndex]:
    rows = conn.execute(
        """
        SELECT
            index_code,
            name,
            source,
            active
        FROM market_indices
        WHERE active=1
        ORDER BY index_code
        """
    ).fetchall()

    return [
        MarketIndex(
            index_code=row[0],
            name=row[1],
            source=row[2],
            active=bool(row[3]),
        )
        for row in rows
    ]


def load_index_price_bars(
    conn: sqlite3.Connection,
    index_code: str,
    *,
    start: date | None = None,
    end: date | None = None,
) -> list[IndexPriceBar]:
    code = _normalize_code(index_code)

    sql = """
        SELECT
            date,
            open,
            high,
            low,
            close,
            volume
        FROM index_daily_prices
        WHERE index_code=?
    """

    params: list[object] = [code]

    if start is not None:
        sql += " AND date>=?"
        params.append(start.isoformat())

    if end is not None:
        sql += " AND date<=?"
        params.append(end.isoformat())

    sql += " ORDER BY date"

    rows = conn.execute(
        sql,
        tuple(params),
    ).fetchall()

    return [
        IndexPriceBar(
            date=date.fromisoformat(row[0]),
            open=(
                None
                if row[1] is None
                else float(row[1])
            ),
            high=(
                None
                if row[2] is None
                else float(row[2])
            ),
            low=(
                None
                if row[3] is None
                else float(row[3])
            ),
            close=float(row[4]),
            volume=(
                None
                if row[5] is None
                else float(row[5])
            ),
        )
        for row in rows
    ]


def load_recent_index_price_bars(
    conn: sqlite3.Connection,
    index_code: str,
    *,
    end: date,
    limit: int,
) -> list[IndexPriceBar]:
    if limit <= 0:
        raise ValueError(
            "limit must be positive"
        )

    code = _normalize_code(index_code)

    rows = conn.execute(
        """
        SELECT
            date,
            open,
            high,
            low,
            close,
            volume
        FROM index_daily_prices
        WHERE index_code=?
          AND date<=?
        ORDER BY date DESC
        LIMIT ?
        """,
        (
            code,
            end.isoformat(),
            limit,
        ),
    ).fetchall()

    bars = [
        IndexPriceBar(
            date=date.fromisoformat(row[0]),
            open=(
                None
                if row[1] is None
                else float(row[1])
            ),
            high=(
                None
                if row[2] is None
                else float(row[2])
            ),
            low=(
                None
                if row[3] is None
                else float(row[3])
            ),
            close=float(row[4]),
            volume=(
                None
                if row[5] is None
                else float(row[5])
            ),
        )
        for row in rows
    ]

    return list(reversed(bars))


def upsert_index_price_bars(
    conn: sqlite3.Connection,
    index_code: str,
    bars: Iterable[PriceBar],
    *,
    source: str,
    fetched_at: str | None = None,
) -> tuple[int, int]:
    """Upsert validated index bars.

    Caller owns the transaction.
    Returns (inserted, updated).

    This mirrors the equity price storage contract while
    keeping index history isolated from daily_prices.
    """

    code = _normalize_code(index_code)

    exists = conn.execute(
        """
        SELECT 1
        FROM market_indices
        WHERE index_code=?
        """,
        (code,),
    ).fetchone()

    if exists is None:
        raise ValueError(
            f"Unknown market index: {code}"
        )

    bars = list(bars)

    if not bars:
        return 0, 0

    fetched_at = (
        fetched_at
        or datetime.now().astimezone().isoformat()
    )

    dates = [
        bar.date.isoformat()
        for bar in bars
    ]

    placeholders = ",".join(
        "?"
        for _ in dates
    )

    existing = {
        row[0]
        for row in conn.execute(
            f"""
            SELECT date
            FROM index_daily_prices
            WHERE index_code=?
              AND date IN ({placeholders})
            """,
            (code, *dates),
        ).fetchall()
    }

    rows = [
        (
            code,
            bar.date.isoformat(),
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            source,
            fetched_at,
        )
        for bar in bars
    ]

    conn.executemany(
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(index_code, date) DO UPDATE SET
            open=excluded.open,
            high=excluded.high,
            low=excluded.low,
            close=excluded.close,
            volume=excluded.volume,
            source=excluded.source,
            fetched_at=excluded.fetched_at
        """,
        rows,
    )

    updated = sum(
        1
        for value in dates
        if value in existing
    )

    return (
        len(dates) - updated,
        updated,
    )
