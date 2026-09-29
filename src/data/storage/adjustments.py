from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import sqlite3
from typing import Iterable


@dataclass(frozen=True)
class AdjustmentRecord:
    date: date
    adj_close: float | None
    adjustment_factor: float | None
    dividend: float | None
    stock_split: float | None


def load_price_adjustments(
    conn: sqlite3.Connection,
    security_id: int,
    *,
    start: date | None = None,
    end: date | None = None,
) -> list[AdjustmentRecord]:
    if start is not None and end is not None and end < start:
        raise ValueError("end must be on or after start")

    sql = """
        SELECT date, adj_close, adjustment_factor, dividend, stock_split
        FROM price_adjustments
        WHERE security_id=?
    """
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
        AdjustmentRecord(
            date=date.fromisoformat(row[0]),
            adj_close=None if row[1] is None else float(row[1]),
            adjustment_factor=None if row[2] is None else float(row[2]),
            dividend=None if row[3] is None else float(row[3]),
            stock_split=None if row[4] is None else float(row[4]),
        )
        for row in rows
    ]


def upsert_price_adjustments(
    conn: sqlite3.Connection,
    security_id: int,
    records: Iterable[AdjustmentRecord],
    *,
    source: str,
    fetched_at: str | None = None,
) -> tuple[int, int]:
    records = list(records)

    if not records:
        return 0, 0

    if not source:
        raise ValueError("source must not be empty")

    dates = [record.date.isoformat() for record in records]

    if len(set(dates)) != len(dates):
        raise ValueError("Adjustment records must have unique dates")

    fetched_at = fetched_at or datetime.now().astimezone().isoformat()

    placeholders = ",".join("?" for _ in dates)

    existing = {
        row[0]
        for row in conn.execute(
            f"""
            SELECT date
            FROM price_adjustments
            WHERE security_id=?
              AND date IN ({placeholders})
            """,
            (security_id, *dates),
        ).fetchall()
    }

    rows = [
        (
            security_id,
            record.date.isoformat(),
            record.adj_close,
            record.adjustment_factor,
            record.dividend,
            record.stock_split,
            source,
            fetched_at,
        )
        for record in records
    ]

    conn.executemany(
        """
        INSERT INTO price_adjustments(
            security_id,
            date,
            adj_close,
            adjustment_factor,
            dividend,
            stock_split,
            source,
            fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(security_id, date) DO UPDATE SET
            adj_close=excluded.adj_close,
            adjustment_factor=excluded.adjustment_factor,
            dividend=excluded.dividend,
            stock_split=excluded.stock_split,
            source=excluded.source,
            fetched_at=excluded.fetched_at
        """,
        rows,
    )

    updated = sum(date_value in existing for date_value in dates)
    return len(records) - updated, updated
