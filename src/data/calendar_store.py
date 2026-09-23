from __future__ import annotations

from datetime import date

from src.data.calendar import BISTTradingCalendar
from src.data.storage.database import Database


def sync_trading_days(
    db: Database,
    calendar: BISTTradingCalendar,
    start: date,
    end: date,
) -> int:
    """Upsert verified calendar sessions into SQLite trading_days."""
    rows = []
    for session in calendar.sessions(start, end):
        rows.append(
            (
                session.date.isoformat(),
                1 if session.is_trading_day else 0,
                session.session_type.value,
                session.source or "BIST calendar rules",
            )
        )
    db.conn.executemany(
        """
        INSERT INTO trading_days(date, is_trading_day, session_type, source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            is_trading_day=excluded.is_trading_day,
            session_type=excluded.session_type,
            source=excluded.source
        """,
        rows,
    )
    db.conn.commit()
    return len(rows)
