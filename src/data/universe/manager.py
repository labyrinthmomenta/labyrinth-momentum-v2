"""BIST universe management.

The universe is deliberately separated from market-data fetching. BIST is the
reference for instrument identity/status; OHLCV providers only supply prices.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import csv
import io
import sqlite3
from typing import Iterable, Optional


@dataclass(frozen=True)
class UniverseRecord:
    ticker: str
    name: str
    instrument_type: str = "EQUITY"
    sector: Optional[str] = None
    industry: Optional[str] = None
    first_trade_date: Optional[str] = None
    status: str = "ACTIVE"
    active: int = 1


class UniverseManager:
    """Synchronise BIST-style universe records into SQLite."""

    def __init__(self, connection: sqlite3.Connection):
        self.conn = connection
        self.conn.row_factory = sqlite3.Row

    @staticmethod
    def normalize_ticker(value: str) -> str:
        return value.strip().upper().replace(".IS", "")

    @staticmethod
    def normalize_date(value: object) -> Optional[str]:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                pass
        raise ValueError(f"Unsupported date format: {value!r}")

    def _find_current_security(self, ticker: str):
        return self.conn.execute(
            """SELECT s.*, si.identifier_id, si.valid_from, si.valid_to
               FROM securities s JOIN security_identifiers si ON si.security_id=s.security_id
               WHERE si.ticker=? AND si.is_current=1""",
            (ticker,),
        ).fetchone()

    def _find_security_by_name(self, name: str):
        return self.conn.execute(
            "SELECT * FROM securities WHERE lower(name)=lower(?) ORDER BY security_id",
            (name,),
        ).fetchone()

    def upsert(
        self,
        record: UniverseRecord,
        as_of: Optional[str] = None,
        active_snapshot_tickers: Optional[set[str]] = None,
    ) -> int:
        ticker = self.normalize_ticker(record.ticker)
        as_of = self.normalize_date(as_of) or date.today().isoformat()
        first_trade = self.normalize_date(record.first_trade_date)

        current = self._find_current_security(ticker)
        if current:
            self.conn.execute(
                """UPDATE securities SET name=?, sector=?, industry=?, instrument_type=?,
                   status=?, first_trade_date=COALESCE(first_trade_date, ?), active=?, updated_at=?
                   WHERE security_id=?""",
                (record.name, record.sector, record.industry, record.instrument_type,
                 record.status, first_trade, record.active, datetime.now().astimezone().isoformat(),
                 current["security_id"]),
            )
            self.conn.execute(
                "UPDATE security_identifiers SET valid_to=NULL, is_current=1 WHERE identifier_id=?",
                (current["identifier_id"],),
            )
            return int(current["security_id"])

        # A matching company name alone is not sufficient evidence of a ticker
        # change. BIST issuers can have multiple share classes trading
        # concurrently (for example ISATR/ISBTR/ISCTR/ISKUR and
        # KRDMA/KRDMB/KRDMD).
        #
        # During an authoritative snapshot sync, only treat the new ticker as a
        # rename candidate when the existing current ticker is absent from the
        # same active snapshot.
        by_name = self._find_security_by_name(record.name)
        if by_name and active_snapshot_tickers is not None:
            existing_identifier = self.conn.execute(
                """SELECT ticker FROM security_identifiers
                   WHERE security_id=? AND is_current=1""",
                (int(by_name["security_id"]),),
            ).fetchone()
            if existing_identifier:
                existing_ticker = self.normalize_ticker(existing_identifier["ticker"])
                if existing_ticker in active_snapshot_tickers:
                    by_name = None

        if by_name:
            security_id = int(by_name["security_id"])
            old = self.conn.execute(
                """SELECT * FROM security_identifiers WHERE security_id=? AND is_current=1""",
                (security_id,),
            ).fetchone()
            old_ticker = old["ticker"] if old else None
            if old and old_ticker != ticker:
                self.conn.execute(
                    "UPDATE security_identifiers SET valid_to=?, is_current=0 WHERE identifier_id=?",
                    (as_of, old["identifier_id"]),
                )
                self.conn.execute(
                    """INSERT INTO security_identifiers
                       (security_id,ticker,valid_from,valid_to,is_current,source)
                       VALUES (?,?,?,?,1,?)""",
                    (security_id, ticker, as_of, None, "BIST"),
                )
                self.conn.execute(
                    """INSERT INTO ticker_history
                       (security_id,old_ticker,new_ticker,effective_date,reason,source)
                       VALUES (?,?,?,?,?,?)""",
                    (security_id, old_ticker, ticker, as_of, "ticker_change", "BIST"),
                )
            self.conn.execute(
                """UPDATE securities SET name=?, sector=?, industry=?, instrument_type=?,
                   status=?, first_trade_date=COALESCE(first_trade_date, ?), active=?, updated_at=?
                   WHERE security_id=?""",
                (record.name, record.sector, record.industry, record.instrument_type,
                 record.status, first_trade, record.active, datetime.now().astimezone().isoformat(), security_id),
            )
            return security_id

        now = datetime.now().astimezone().isoformat()
        cur = self.conn.execute(
            """INSERT INTO securities
               (name,sector,industry,instrument_type,status,first_trade_date,active,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (record.name, record.sector, record.industry, record.instrument_type,
             record.status, first_trade, record.active, now, now),
        )
        security_id = int(cur.lastrowid)
        self.conn.execute(
            """INSERT INTO security_identifiers
               (security_id,ticker,valid_from,valid_to,is_current,source)
               VALUES (?,?,?,?,1,?)""",
            (security_id, ticker, first_trade or as_of, None, "BIST"),
        )
        return security_id

    def mark_missing_inactive(self, active_tickers: Iterable[str], as_of: Optional[str] = None) -> int:
        """Mark securities absent from the authoritative snapshot as inactive.

        This does not delete history and does not automatically call a security
        DELISTED: absence can also represent suspension or source limitations.
        """
        active = {self.normalize_ticker(t) for t in active_tickers}
        as_of = self.normalize_date(as_of) or date.today().isoformat()
        rows = self.conn.execute(
            """SELECT s.security_id, si.ticker FROM securities s
               JOIN security_identifiers si ON si.security_id=s.security_id
               WHERE si.is_current=1 AND s.instrument_type='EQUITY'"""
        ).fetchall()
        changed = 0
        for row in rows:
            if row["ticker"] not in active:
                self.conn.execute(
                    "UPDATE securities SET active=0, updated_at=? WHERE security_id=?",
                    (datetime.now().astimezone().isoformat(), row["security_id"]),
                )
                changed += 1
        return changed

    def sync(self, records: Iterable[UniverseRecord], as_of: Optional[str] = None) -> dict:
        records = list(records)
        equity_tickers = [
            self.normalize_ticker(r.ticker)
            for r in records
            if r.instrument_type == "EQUITY" and r.active
        ]
        active_snapshot_tickers = set(equity_tickers)
        ids = [
            self.upsert(
                r,
                as_of=as_of,
                active_snapshot_tickers=active_snapshot_tickers,
            )
            for r in records
        ]
        inactive = self.mark_missing_inactive(equity_tickers, as_of=as_of)
        self.conn.commit()
        return {"records": len(records), "securities_upserted": len(ids), "marked_inactive": inactive}


def parse_bist_csv(text: str) -> list[UniverseRecord]:
    """Parse a BIST-exported CSV with tolerant Turkish/English headers.

    This parser intentionally does not assume a single BIST export filename or
    column order. Mapping can be adapted when the live BIST CSV schema changes.
    """
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t,")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    aliases = {
        "ticker": {"kod", "paykodu", "paykodu", "symbol", "ticker"},
        "name": {"payadi", "payadı", "unvan", "ünvan", "company", "name"},
        "sector": {"sektor", "sektör", "sector"},
        "industry": {"altsektor", "altsektör", "industry"},
        "first_trade_date": {"ilkislemtarihi", "ilk işlem tarihi", "firsttradedate"},
    }
    def key(v: str) -> str:
        return "".join(ch for ch in v.strip().lower() if ch.isalnum())
    normalized = [{key(k): v for k, v in row.items() if k is not None} for row in reader]
    def get(row, field):
        for candidate in aliases[field]:
            if key(candidate) in row:
                return row[key(candidate)]
        return None
    out = []
    for row in normalized:
        ticker = get(row, "ticker")
        name = get(row, "name")
        if not ticker or not name:
            continue
        out.append(UniverseRecord(
            ticker=ticker, name=name,
            sector=get(row, "sector"), industry=get(row, "industry"),
            first_trade_date=UniverseManager.normalize_date(get(row, "first_trade_date")),
        ))
    return out
