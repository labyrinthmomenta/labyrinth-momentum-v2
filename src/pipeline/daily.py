from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import shutil
import tempfile
from typing import Iterable

from src.data.calendar import BISTTradingCalendar
from src.data.calendar_store import sync_trading_days
from src.data.providers.base import MarketDataProvider
from src.data.storage.database import Database
from src.data.storage.prices import SecurityForUpdate, active_equities
from src.data.universe.manager import UniverseManager, UniverseRecord
from src.output.publication import PublicationSummary, build_publication_stage, promote_publication
from src.pipeline.update import UpdateSummary, run_incremental_update


class DailyPipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class DailyRunSummary:
    as_of: date
    dry_run: bool
    universe_status: str
    universe_records: int
    calendar_days_synced: int
    securities_selected: int
    update: UpdateSummary
    publication: PublicationSummary
    public_promoted: bool


def _select(securities: list[SecurityForUpdate], tickers: set[str] | None) -> list[SecurityForUpdate]:
    if not tickers:
        return securities
    by_ticker = {item.ticker: item for item in securities}
    missing = sorted(tickers - set(by_ticker))
    if missing:
        raise DailyPipelineError(f"Requested ticker(s) are not active EQUITY securities: {', '.join(missing)}")
    return [by_ticker[ticker] for ticker in sorted(tickers)]


def _backup_database(source: Database, target_path: Path) -> Database:
    target = Database(target_path)
    target.initialize()
    source.conn.backup(target.conn)
    target.conn.commit()
    return target


def run_daily_pipeline(
    *,
    db_path: str | Path,
    calendar: BISTTradingCalendar,
    provider: MarketDataProvider,
    as_of: date,
    public_dir: str | Path,
    required_return_window: int = 252,
    authoritative_universe_records: Iterable[UniverseRecord] | None = None,
    tickers: set[str] | None = None,
    dry_run: bool = False,
    dry_run_dir: str | Path | None = None,
) -> DailyRunSummary:
    """Run the complete V2 daily flow behind a publication gate.

    A ticker subset is deliberately restricted to dry-run mode. Production
    publication is allowed only for the complete active equity universe.
    """
    tickers = {t.strip().upper().replace('.IS', '') for t in tickers or set() if t.strip()}
    if tickers and not dry_run:
        raise DailyPipelineError("Ticker subsets are dry-run only; partial universe publication is forbidden")

    source = Database(db_path)
    source.initialize()
    temp_ctx: tempfile.TemporaryDirectory | None = None
    work_db = source
    try:
        if dry_run:
            temp_ctx = tempfile.TemporaryDirectory(prefix="labyrinth-v2-dryrun-")
            work_db = _backup_database(source, Path(temp_ctx.name) / "labyrinth-dryrun.db")

        records = list(authoritative_universe_records) if authoritative_universe_records is not None else None
        if records is not None:
            UniverseManager(work_db.conn).sync(records, as_of=as_of.isoformat())
            universe_status = "SYNCED"
            universe_count = len(records)
        else:
            universe_status = "SKIPPED"
            universe_count = 0

        start = date(min(calendar.covered_years), 1, 1)
        calendar_days_synced = sync_trading_days(work_db, calendar, start, as_of)

        all_active = active_equities(work_db.conn)
        selected = _select(all_active, tickers or None)
        if not selected:
            raise DailyPipelineError("No active EQUITY securities are available")

        update = run_incremental_update(
            work_db.conn,
            calendar,
            provider,
            as_of=as_of,
            required_return_window=required_return_window,
            securities=selected,
        )

        if dry_run:
            if dry_run_dir is None:
                stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
                dry_run_dir = Path("migration") / "dry_runs" / stamp
            stage = Path(dry_run_dir)
            publication = build_publication_stage(
                work_db.conn,
                calendar,
                as_of=as_of,
                stage_dir=stage,
                required_return_window=required_return_window,
                tickers=tickers or None,
                dry_run=True,
            )
            promoted = False
        else:
            # Full-universe invariant: the publication builder must see exactly
            # the same active set that was staged/validated by the update step.
            if len(selected) != len(all_active):
                raise DailyPipelineError("Production publication requires the complete active EQUITY universe")
            public = Path(public_dir)
            stage = public.parent / f".{public.name}.stage"
            publication = build_publication_stage(
                work_db.conn,
                calendar,
                as_of=as_of,
                stage_dir=stage,
                required_return_window=required_return_window,
                dry_run=False,
            )
            if publication.securities_published != len(all_active):
                raise DailyPipelineError("Publication count does not match the active EQUITY universe")
            promote_publication(stage, public)
            publication = PublicationSummary(
                as_of=publication.as_of,
                securities_expected=publication.securities_expected,
                securities_published=publication.securities_published,
                output_dir=str(public),
                dry_run=False,
                manifest_path=str(public / "manifest.json"),
            )
            promoted = True

        return DailyRunSummary(
            as_of=as_of,
            dry_run=dry_run,
            universe_status=universe_status,
            universe_records=universe_count,
            calendar_days_synced=calendar_days_synced,
            securities_selected=len(selected),
            update=update,
            publication=publication,
            public_promoted=promoted,
        )
    except Exception as exc:
        if isinstance(exc, DailyPipelineError):
            raise
        raise DailyPipelineError(str(exc)) from exc
    finally:
        if work_db is not source:
            work_db.close()
        source.close()
        if temp_ctx is not None:
            temp_ctx.cleanup()
