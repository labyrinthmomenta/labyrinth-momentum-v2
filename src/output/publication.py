from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid

from src.calculation.validated import compute_validated_snapshot
from src.data.calendar import BISTTradingCalendar
from src.data.storage.prices import load_recent_price_bars
from src.output.build_detail import build_detail_payload


class PublicationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublicationSummary:
    as_of: date
    securities_expected: int
    securities_published: int
    output_dir: str
    dry_run: bool
    manifest_path: str


def _active_output_rows(conn: sqlite3.Connection, tickers: set[str] | None = None):
    conn.row_factory = sqlite3.Row
    sql = """
        SELECT s.security_id, s.name, s.sector, s.industry, s.first_trade_date, si.ticker
        FROM securities s
        JOIN security_identifiers si ON si.security_id=s.security_id
        WHERE s.instrument_type='EQUITY' AND s.active=1 AND s.status='ACTIVE' AND si.is_current=1
    """
    params: list[object] = []
    if tickers:
        placeholders = ",".join("?" for _ in tickers)
        sql += f" AND si.ticker IN ({placeholders})"
        params.extend(sorted(tickers))
    sql += " ORDER BY si.ticker"
    return conn.execute(sql, tuple(params)).fetchall()


def _json_default(value):
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def build_publication_stage(
    conn: sqlite3.Connection,
    calendar: BISTTradingCalendar,
    *,
    as_of: date,
    stage_dir: str | Path,
    required_return_window: int = 252,
    tickers: set[str] | None = None,
    dry_run: bool = False,
) -> PublicationSummary:
    """Build *all* JSON into an isolated stage directory.

    No public directory is touched here. If any security fails validation or
    calculation, the function raises and the staged output is disposable.
    """
    stage = Path(stage_dir)
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "details").mkdir(parents=True, exist_ok=True)

    rows = _active_output_rows(conn, tickers)
    if not rows:
        raise PublicationError("No active EQUITY securities selected for publication")

    screener: list[dict] = []
    for row in rows:
        first_trade = date.fromisoformat(row["first_trade_date"]) if row["first_trade_date"] else None
        bars = load_recent_price_bars(
            conn,
            int(row["security_id"]),
            end=as_of,
            limit=required_return_window + 1,
        )
        if not bars:
            raise PublicationError(f"{row['ticker']}: no canonical price bars available")
        try:
            snapshot, report = compute_validated_snapshot(
                bars,
                calendar,
                as_of=as_of,
                required_return_window=required_return_window,
                listing_start=first_trade,
            )
        except Exception as exc:
            raise PublicationError(f"{row['ticker']}: calculation gate failed: {exc}") from exc
        if not report.passed:
            raise PublicationError(f"{row['ticker']}: validation gate failed")

        snapshot_dict = snapshot.as_dict()
        snapshot_dict["as_of"] = snapshot.as_of.isoformat()
        screener.append(
            {
                "security_id": int(row["security_id"]),
                "ticker": row["ticker"],
                "name": row["name"],
                "sector": row["sector"],
                "industry": row["industry"],
                **snapshot_dict,
            }
        )
        detail = build_detail_payload(
            security_id=int(row["security_id"]),
            ticker=row["ticker"],
            name=row["name"],
            sector=row["sector"],
            industry=row["industry"],
            first_trade_date=first_trade,
            snapshot=snapshot,
            bars=bars,
        )
        _write_json(stage / "details" / f"{row['ticker']}.json", detail)

    _write_json(stage / "screener.json", screener)
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "as_of": as_of.isoformat(),
        "status": "PASS",
        "dry_run": dry_run,
        "securities_expected": len(rows),
        "securities_published": len(screener),
        "required_return_window": required_return_window,
        "files": {
            "screener": "screener.json",
            "details": len(screener),
        },
    }
    _write_json(stage / "manifest.json", manifest)
    return PublicationSummary(
        as_of=as_of,
        securities_expected=len(rows),
        securities_published=len(screener),
        output_dir=str(stage),
        dry_run=dry_run,
        manifest_path=str(stage / "manifest.json"),
    )


def promote_publication(stage_dir: str | Path, public_dir: str | Path) -> None:
    """Promote a fully validated stage with rollback-safe directory swapping."""
    stage = Path(stage_dir)
    public = Path(public_dir)
    if not (stage / "manifest.json").exists():
        raise PublicationError("Publication stage has no manifest.json")
    public.parent.mkdir(parents=True, exist_ok=True)
    backup = public.with_name(f".{public.name}.backup-{uuid.uuid4().hex}")
    had_public = public.exists()
    try:
        if had_public:
            os.replace(public, backup)
        os.replace(stage, public)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if public.exists() and not had_public:
            shutil.rmtree(public, ignore_errors=True)
        if backup.exists() and not public.exists():
            os.replace(backup, public)
        raise
