from datetime import date

from src.data.calendar import BISTTradingCalendar
from src.data.calendar_store import sync_trading_days
from src.data.storage.database import Database


def test_calendar_sync_persists_session_types(tmp_path):
    db = Database(tmp_path / "test.db")
    db.initialize()
    cal = BISTTradingCalendar.from_csv()
    count = sync_trading_days(db, cal, date(2026, 3, 18), date(2026, 3, 23))
    assert count == 6
    half = db.conn.execute("SELECT * FROM trading_days WHERE date='2026-03-19'").fetchone()
    closed = db.conn.execute("SELECT * FROM trading_days WHERE date='2026-03-20'").fetchone()
    assert half["is_trading_day"] == 1 and half["session_type"] == "HALF"
    assert closed["is_trading_day"] == 0 and closed["session_type"] == "CLOSED"
    db.close()
