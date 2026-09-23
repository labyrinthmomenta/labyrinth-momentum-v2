import sqlite3
from pathlib import Path

from src.data.universe.manager import UniverseManager, UniverseRecord

SCHEMA = Path("src/data/storage/schema.sql").read_text(encoding="utf-8")


def db():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    return c


def test_new_equity_and_idempotent_update():
    c = db(); m = UniverseManager(c)
    r = UniverseRecord("TEST", "Test A.S.", first_trade_date="2026-01-05")
    first = m.upsert(r, as_of="2026-09-22")
    second = m.upsert(r, as_of="2026-09-22")
    assert first == second
    assert c.execute("select count(*) from securities").fetchone()[0] == 1
    assert c.execute("select count(*) from security_identifiers").fetchone()[0] == 1


def test_ticker_change_preserves_security_identity():
    c = db(); m = UniverseManager(c)
    m.upsert(UniverseRecord("OLD", "Same Company"), as_of="2026-05-01")
    sid = m.upsert(UniverseRecord("NEW", "Same Company"), as_of="2026-08-01")
    rows = c.execute("select ticker,is_current,valid_to from security_identifiers where security_id=? order by identifier_id", (sid,)).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "OLD" and rows[0][1] == 0
    assert rows[1][0] == "NEW" and rows[1][1] == 1
    hist = c.execute("select old_ticker,new_ticker from ticker_history").fetchone()
    assert tuple(hist) == ("OLD", "NEW")


def test_missing_does_not_mark_other_instrument_types():
    c = db(); m = UniverseManager(c)
    m.upsert(UniverseRecord("AAA", "Equity"), as_of="2026-09-22")
    m.upsert(UniverseRecord("ETF1", "Fund", instrument_type="ETF"), as_of="2026-09-22")
    m.mark_missing_inactive([], as_of="2026-09-22")
    assert c.execute("select active from securities where name='Equity'").fetchone()[0] == 0
    assert c.execute("select active from securities where name='Fund'").fetchone()[0] == 1

def test_sync_keeps_parallel_share_classes_as_separate_securities():
    c = db()
    m = UniverseManager(c)

    records = [
        UniverseRecord("ISCTR", "TÜRKİYE İŞ BANKASI A.Ş.", first_trade_date="1987-11-25"),
        UniverseRecord("ISATR", "TÜRKİYE İŞ BANKASI A.Ş."),
        UniverseRecord("ISBTR", "TÜRKİYE İŞ BANKASI A.Ş."),
        UniverseRecord("ISKUR", "TÜRKİYE İŞ BANKASI A.Ş."),
    ]

    m.sync(records, as_of="2026-09-22")

    rows = c.execute(
        """
        SELECT s.security_id, si.ticker
        FROM securities s
        JOIN security_identifiers si
          ON si.security_id = s.security_id
        WHERE si.is_current=1
        ORDER BY si.ticker
        """
    ).fetchall()

    assert [row[1] for row in rows] == [
        "ISATR",
        "ISBTR",
        "ISCTR",
        "ISKUR",
    ]
    assert len({row[0] for row in rows}) == 4

