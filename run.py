from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from src.data.calendar import BISTTradingCalendar
from src.data.providers.bist_thb import BISTTHBProvider
from src.data.providers.yahoo import YahooProvider
from src.data.storage.database import Database
from src.data.universe.manager import parse_bist_csv
from src.data.universe.official import fetch_official_universe, guard_universe_change, OfficialUniverseError
from src.reporting.legacy_compare import build_legacy_comparison, write_legacy_comparison
from src.pipeline.daily import DailyPipelineError, run_daily_pipeline
from src.pipeline.update import UpdatePipelineError, run_incremental_update
from src.pipeline.preflight import LivePreflightError, run_live_preflight
from src.data.calendar_store import sync_trading_days

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "labyrinth.db"
PUBLIC_DIR = ROOT / "docs" / "data"


def parse_args():
    parser = argparse.ArgumentParser(description="Labyrinth Momentum V2")
    parser.add_argument("command", nargs="?", choices=("init", "update", "daily", "dry-run", "legacy-report", "preflight"), default="init")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path")
    parser.add_argument("--as-of", dest="as_of", help="YYYY-MM-DD; defaults to today")
    parser.add_argument("--window", type=int, default=252, help="Maximum return lookback")
    parser.add_argument("--public-dir", default=str(PUBLIC_DIR), help="Derived public JSON directory")
    parser.add_argument("--universe-csv", help="Authoritative full BIST universe CSV snapshot")
    parser.add_argument("--tickers", help="Comma-separated ticker subset; dry-run only")
    parser.add_argument("--dry-run-dir", help="Non-public output directory for dry-run JSON")
    parser.add_argument("--official-universe", action="store_true", help="Fetch current EQUITY universe from official KAP/BIST sources")
    parser.add_argument("--legacy-detail-dir", help="V1 detail JSON directory for regression/comparison report")
    parser.add_argument("--legacy-excel", help="V1 source-of-truth Excel workbook for exact legacy regression")
    parser.add_argument("--legacy-report-out", default="migration/reports/v1_v2_comparison.json", help="Legacy comparison report path")
    return parser.parse_args()


def _universe_records(path: str | None):
    if not path:
        return None
    return parse_bist_csv(Path(path).read_text(encoding="utf-8-sig"))


def _tickers(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {item.strip().upper().replace(".IS", "") for item in value.split(",") if item.strip()}


def main() -> int:
    args = parse_args()
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    calendar = BISTTradingCalendar.from_csv()

    if args.command == "legacy-report":
        if not args.legacy_detail_dir:
            print("FAILED: --legacy-detail-dir is required for legacy-report")
            return 2
        report = build_legacy_comparison(
            v1_detail_dir=args.legacy_detail_dir,
            v1_excel_path=args.legacy_excel,
            v2_screener_json=(Path(args.public_dir) / "screener.json") if (Path(args.public_dir) / "screener.json").exists() else None,
            as_of=as_of if args.as_of else None,
        )
        output = write_legacy_comparison(report, args.legacy_report_out)
        print(
            f"{report['status']} legacy_files={report['summary']['v1_files_checked']} "
            f"excel_matches={report['summary']['v1_excel_json_matches']} "
            f"common_v2={report['summary']['v2_common_tickers']} output={output}"
        )
        return 0 if report["status"] == "PASS" else 2

    if args.command == "preflight":
        try:
            summary = run_live_preflight(
                calendar=calendar,
                provider=YahooProvider(),
                fallback_provider=BISTTHBProvider(),
                as_of=as_of,
                universe_fetcher=fetch_official_universe,
                tickers=_tickers(args.tickers) or {"A1CAP", "ASELS", "THYAO"},
            )
            markets = ",".join(f"{k}:{v}" for k, v in sorted(summary.market_counts.items()))
            probes = ",".join(f"{p.ticker}:{p.bars_received}@{p.last_bar}" for p in summary.probes)
            print(
                f"PASS preflight as_of={summary.as_of} equities={summary.equities} "
                f"markets=[{markets}] probes=[{probes}]"
            )
            return 0
        except (OfficialUniverseError, LivePreflightError, Exception) as exc:
            print(f"FAILED preflight: {exc}")
            return 2

    if args.command == "init":
        db = Database(args.db)
        db.initialize()
        db.close()
        print(f"Initialized {Path(args.db).resolve()}")
        return 0

    if args.command == "update":
        db = Database(args.db)
        db.initialize()
        try:
            start = date(min(calendar.covered_years), 1, 1)
            sync_trading_days(db, calendar, start, as_of)
            summary = run_incremental_update(
                db.conn,
                calendar,
                YahooProvider(),
                as_of=as_of,
                required_return_window=args.window,
                fallback_provider=BISTTHBProvider(),
            )
            print(
                "SUCCESS "
                f"run_id={summary.run_id} securities={summary.securities_checked} "
                f"inserted={summary.prices_inserted} updated={summary.prices_updated} "
                f"fetched={summary.fetched_bars} provider_calls={summary.provider_calls}"
            )
            return 0
        except UpdatePipelineError as exc:
            print(f"FAILED: {exc}")
            return 2
        finally:
            db.close()

    try:
        dry = args.command == "dry-run"
        universe_records = _universe_records(args.universe_csv)
        if args.official_universe:
            if universe_records is not None:
                raise DailyPipelineError("Use either --official-universe or --universe-csv, not both")
            official = fetch_official_universe()
            universe_records = official.records
            guard_db = Database(args.db)
            guard_db.initialize()
            try:
                guard_universe_change(guard_db.conn, universe_records)
            finally:
                guard_db.close()
            market_text = ",".join(f"{k}:{v}" for k, v in sorted(official.market_counts.items()))
            print(
                f"OFFICIAL-UNIVERSE equities={official.kap_records} "
                f"first_trade_records={official.first_trade_records} markets=[{market_text}]"
            )
        summary = run_daily_pipeline(
            db_path=args.db,
            calendar=calendar,
            provider=YahooProvider(),
            as_of=as_of,
            public_dir=args.public_dir,
            required_return_window=args.window,
            authoritative_universe_records=universe_records,
            tickers=_tickers(args.tickers),
            dry_run=dry,
            dry_run_dir=args.dry_run_dir,
            fallback_provider=BISTTHBProvider(),
        )
        print(
            f"{'DRY-RUN' if dry else 'SUCCESS'} as_of={summary.as_of} "
            f"securities={summary.securities_selected} inserted={summary.update.prices_inserted} "
            f"updated={summary.update.prices_updated} fetched={summary.update.fetched_bars} "
            f"published={summary.publication.securities_published} "
            f"output={summary.publication.output_dir}"
        )
        return 0
    except (DailyPipelineError, OfficialUniverseError) as exc:
        print(f"FAILED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
