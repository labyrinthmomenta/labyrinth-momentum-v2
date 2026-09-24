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
    data_run_id: int | None = None,
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

    status_by_security: dict[int, tuple[str, str | None]] = {}
    if data_run_id is not None:
        status_rows = conn.execute(
            """SELECT security_id,status,message
               FROM security_data_status
               WHERE run_id=?""",
            (data_run_id,),
        ).fetchall()
        status_by_security = {
            int(item["security_id"]): (item["status"], item["message"])
            for item in status_rows
        }

        expected_ids = {int(row["security_id"]) for row in rows}
        missing_status = sorted(expected_ids - set(status_by_security))
        if missing_status:
            raise PublicationError(
                "Publication data-status coverage is incomplete for run "
                f"{data_run_id}: {missing_status[:8]}"
            )

    null_snapshot = {
        "as_of": as_of.isoformat(),
        "observations": None,
        "momentum_252": None,
        "momentum_126": None,
        "momentum_63": None,
        "momentum_21": None,
        "fip_252": None,
        "fip_126": None,
        "fip_63": None,
        "fip_21": None,
        "atr14_percent": None,
        "delta_momentum_21_63": None,
        "delta_fip_21_63": None,
        "completed_month": None,
        "completed_month_momentum": None,
        "completed_month_fip": None,
        "completed_month_observations": None,
    }

    screener: list[dict] = []
    data_available = 0
    provider_unavailable = 0
    insufficient_trading_data = 0

    for row in rows:
        security_id = int(row["security_id"])
        data_status, status_message = status_by_security.get(
            security_id,
            ("OK", None),
        )

        if data_status in {
            "PROVIDER_UNAVAILABLE",
            "INSUFFICIENT_TRADING_DATA",
        }:
            if data_status == "PROVIDER_UNAVAILABLE":
                provider_unavailable += 1
            else:
                insufficient_trading_data += 1

            screener.append(
                {
                    "security_id": security_id,
                    "ticker": row["ticker"],
                    "name": row["name"],
                    "sector": row["sector"],
                    "industry": row["industry"],
                    "data_status": data_status,
                    "data_status_message": status_message,
                    **null_snapshot,
                }
            )

            detail = {
                "security": {
                    "security_id": security_id,
                    "ticker": row["ticker"],
                    "name": row["name"],
                    "sector": row["sector"],
                    "industry": row["industry"],
                    "first_trade_date": row["first_trade_date"],
                },
                "data_status": data_status,
                "data_status_message": status_message,
                "snapshot": dict(null_snapshot),
                "daily": [],
            }
            _write_json(stage / "details" / f"{row['ticker']}.json", detail)
            continue

        if data_status != "OK":
            raise PublicationError(
                f"{row['ticker']}: unsupported data status {data_status!r}"
            )

        data_available += 1
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
                "data_status": "OK",
                "data_status_message": None,
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
        detail["data_status"] = "OK"
        detail["data_status_message"] = None
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
        "data_available": data_available,
        "provider_unavailable": provider_unavailable,
        "insufficient_trading_data": insufficient_trading_data,
        "data_status_counts": {
            "OK": data_available,
            "PROVIDER_UNAVAILABLE": provider_unavailable,
            "INSUFFICIENT_TRADING_DATA": insufficient_trading_data,
        },
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
