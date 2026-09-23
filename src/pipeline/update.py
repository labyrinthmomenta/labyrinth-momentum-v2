from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import sqlite3
from typing import Iterable

from src.calculation.engine import PriceBar
from src.data.calendar import BISTTradingCalendar
from src.data.providers.base import BatchFetchResult, MarketDataProvider
from src.data.storage.prices import (
    SecurityForUpdate,
    active_equities,
    identifier_periods,
    load_price_bars,
    ticker_for_date,
    upsert_price_bars,
)
from src.validation.data_quality import QualityReport, Severity, validate_ohlcv_structure, validate_price_history


class UpdatePipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchRequest:
    ticker: str
    start: date
    end: date


@dataclass(frozen=True)
class SecurityPlan:
    security: SecurityForUpdate
    latest: date
    existing: tuple[PriceBar, ...]
    periods: tuple
    requests: tuple[FetchRequest, ...]


@dataclass(frozen=True)
class SecurityStage:
    security: SecurityForUpdate
    fetched_bars: tuple[PriceBar, ...]
    ticker_at_date: dict[date, str]
    quality: QualityReport


@dataclass(frozen=True)
class UpdateSummary:
    run_id: int
    status: str
    securities_checked: int
    prices_inserted: int
    prices_updated: int
    fetched_bars: int
    provider_calls: int
    validation_status: str
    error_message: str | None = None


def _merge_bars(existing: Iterable[PriceBar], incoming: Iterable[PriceBar]) -> list[PriceBar]:
    merged = {bar.date: bar for bar in existing}
    for bar in incoming:
        merged[bar.date] = bar
    return [merged[key] for key in sorted(merged)]


def _contiguous_requests(missing_dates: list[date], periods, calendar: BISTTradingCalendar) -> list[FetchRequest]:
    """Group missing trading dates by ticker and adjacent market sessions.

    Fetch ranges are calendar-date ranges. Re-fetching already present days
    inside a range is harmless because writes are deterministic upserts.
    """
    if not missing_dates:
        return []
    requests: list[FetchRequest] = []
    current_ticker: str | None = None
    start: date | None = None
    previous: date | None = None

    for day in missing_dates:
        ticker = ticker_for_date(periods, day)
        if ticker is None:
            raise UpdatePipelineError(f"No ticker identifier is valid for {day.isoformat()}")
        split = current_ticker is not None and ticker != current_ticker
        if not split and previous is not None:
            # Consecutive trading sessions may be separated by weekends/holidays.
            expected_next = calendar.trading_days(previous + timedelta(days=1), day)
            split = not expected_next or expected_next[-1] != day or len(expected_next) != 1
        if split:
            assert current_ticker is not None and start is not None and previous is not None
            requests.append(FetchRequest(current_ticker, start, previous))
            start = day
        elif start is None:
            start = day
        current_ticker = ticker
        previous = day

    assert current_ticker is not None and start is not None and previous is not None
    requests.append(FetchRequest(current_ticker, start, previous))
    return requests


def _required_dates(
    calendar: BISTTradingCalendar,
    as_of: date,
    return_window: int,
    listing_start: date | None,
) -> tuple[date, list[date]]:
    latest = calendar.latest_trading_day_on_or_before(as_of)
    days = calendar.previous_trading_days(latest, return_window + 1, include_value=True)
    if listing_start is not None:
        days = [day for day in days if day >= listing_start]
    return latest, days


def _start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO pipeline_runs(started_at,status,validation_status) VALUES (?,?,?)",
        (datetime.now().astimezone().isoformat(), "RUNNING", "PENDING"),
    )
    conn.commit()
    return int(cur.lastrowid)


def _finish_run(conn: sqlite3.Connection, summary: UpdateSummary) -> None:
    conn.execute(
        """
        UPDATE pipeline_runs SET finished_at=?, status=?, securities_checked=?,
            prices_inserted=?, prices_updated=?, fetched_bars=?, provider_calls=?,
            validation_status=?, error_message=?
        WHERE run_id=?
        """,
        (
            datetime.now().astimezone().isoformat(),
            summary.status,
            summary.securities_checked,
            summary.prices_inserted,
            summary.prices_updated,
            summary.fetched_bars,
            summary.provider_calls,
            summary.validation_status,
            summary.error_message,
            summary.run_id,
        ),
    )
    conn.commit()


def _build_plan(
    conn: sqlite3.Connection,
    calendar: BISTTradingCalendar,
    security: SecurityForUpdate,
    *,
    as_of: date,
    required_return_window: int,
) -> SecurityPlan:
    latest, expected_dates = _required_dates(
        calendar, as_of, required_return_window, security.first_trade_date
    )
    if not expected_dates:
        raise UpdatePipelineError(
            f"{security.ticker}: no required trading dates remain after first_trade_date filtering"
        )

    existing = load_price_bars(
        conn,
        security.security_id,
        start=expected_dates[0],
        end=latest,
    )
    existing_dates = {bar.date for bar in existing}
    missing = [day for day in expected_dates if day not in existing_dates]
    periods = tuple(identifier_periods(conn, security.security_id))
    requests = tuple(_contiguous_requests(missing, periods, calendar))
    return SecurityPlan(security, latest, tuple(existing), periods, requests)


def _fetch_all(
    provider: MarketDataProvider,
    plans: list[SecurityPlan],
) -> tuple[dict[tuple[str, date, date], list[PriceBar]], int]:
    """Fetch all unique requests, using provider batching when available."""
    unique: dict[tuple[str, date, date], FetchRequest] = {}
    for plan in plans:
        for request in plan.requests:
            unique[(request.ticker, request.start, request.end)] = request
    if not unique:
        return {}, 0

    output: dict[tuple[str, date, date], list[PriceBar]] = {}
    provider_calls = 0
    fetch_many = getattr(provider, "fetch_many", None)

    if callable(fetch_many):
        # Batch only requests sharing an identical date range. This covers the
        # common full-universe case while preserving ticker-history ranges.
        grouped: dict[tuple[date, date], list[FetchRequest]] = defaultdict(list)
        for request in unique.values():
            grouped[(request.start, request.end)].append(request)
        for (start, end), requests in sorted(grouped.items(), key=lambda item: item[0]):
            tickers = sorted({request.ticker for request in requests})
            result = fetch_many(tickers, start, end)
            if not isinstance(result, BatchFetchResult):
                raise UpdatePipelineError("Provider fetch_many() must return BatchFetchResult")
            provider_calls += result.provider_calls
            for request in requests:
                bars = result.bars_by_ticker.get(request.ticker, [])
                output[(request.ticker, request.start, request.end)] = [
                    bar for bar in bars if request.start <= bar.date <= request.end
                ]
        return output, provider_calls

    for key, request in unique.items():
        provider_calls += 1
        batch = provider.fetch(request.ticker, request.start, request.end)
        output[key] = [bar for bar in batch if request.start <= bar.date <= request.end]
    return output, provider_calls


def run_incremental_update(
    conn: sqlite3.Connection,
    calendar: BISTTradingCalendar,
    provider: MarketDataProvider,
    *,
    as_of: date,
    required_return_window: int = 252,
    securities: Iterable[SecurityForUpdate] | None = None,
) -> UpdateSummary:
    """Stage, validate, then atomically commit market-data updates.

    No ``daily_prices`` rows are changed until *every* selected active equity
    has a passing staged history. The fetch phase is planned first so providers
    that support batching can collapse hundreds of equal date ranges into a
    small number of vendor downloads.
    """
    run_id = _start_run(conn)
    selected = list(securities) if securities is not None else active_equities(conn)
    stages: list[SecurityStage] = []
    fetched_total = 0
    provider_calls = 0

    try:
        plans = [
            _build_plan(
                conn,
                calendar,
                security,
                as_of=as_of,
                required_return_window=required_return_window,
            )
            for security in selected
        ]
        fetched_by_request, provider_calls = _fetch_all(provider, plans)

        for plan in plans:
            fetched: list[PriceBar] = []
            for request in plan.requests:
                fetched.extend(
                    fetched_by_request.get((request.ticker, request.start, request.end), [])
                )
            fetched_total += len(fetched)

            fetched_issues = validate_ohlcv_structure(sorted(fetched, key=lambda bar: bar.date))
            fetched_errors = [issue for issue in fetched_issues if issue.severity == Severity.ERROR]
            if fetched_errors:
                preview = "; ".join(
                    f"{issue.code}@{issue.date}: {issue.message}" for issue in fetched_errors[:8]
                )
                raise UpdatePipelineError(
                    f"{plan.security.ticker}: provider data failed structure checks: {preview}"
                )

            staged = _merge_bars(plan.existing, fetched)
            report = validate_price_history(
                staged,
                calendar,
                as_of=as_of,
                required_return_window=required_return_window,
                listing_start=plan.security.first_trade_date,
            )
            if not report.passed:
                preview = "; ".join(
                    f"{issue.code}@{issue.date}: {issue.message}" for issue in report.errors[:8]
                )
                raise UpdatePipelineError(f"{plan.security.ticker}: validation failed: {preview}")

            ticker_map: dict[date, str] = {}
            for bar in fetched:
                ticker = ticker_for_date(plan.periods, bar.date)
                if ticker is None:
                    raise UpdatePipelineError(
                        f"{plan.security.ticker}: no ticker identifier for fetched date {bar.date.isoformat()}"
                    )
                ticker_map[bar.date] = ticker
            stages.append(SecurityStage(plan.security, tuple(fetched), ticker_map, report))

        inserted = 0
        updated = 0
        # One explicit transaction for the canonical market-data mutation.
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stage in stages:
                add, replace = upsert_price_bars(
                    conn,
                    stage.security.security_id,
                    stage.fetched_bars,
                    ticker_at_date=stage.ticker_at_date,
                    source=provider.source_name,
                )
                inserted += add
                updated += replace
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        summary = UpdateSummary(
            run_id=run_id,
            status="SUCCESS",
            securities_checked=len(selected),
            prices_inserted=inserted,
            prices_updated=updated,
            fetched_bars=fetched_total,
            provider_calls=provider_calls,
            validation_status="PASS",
        )
        _finish_run(conn, summary)
        return summary

    except Exception as exc:
        if conn.in_transaction:
            conn.rollback()
        summary = UpdateSummary(
            run_id=run_id,
            status="FAILED",
            securities_checked=len(stages),
            prices_inserted=0,
            prices_updated=0,
            fetched_bars=fetched_total,
            provider_calls=provider_calls,
            validation_status="FAIL",
            error_message=str(exc),
        )
        _finish_run(conn, summary)
        raise UpdatePipelineError(str(exc)) from exc
