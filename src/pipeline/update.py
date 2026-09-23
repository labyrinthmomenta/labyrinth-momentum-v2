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
    required_dates: tuple[date, ...]
    existing: tuple[PriceBar, ...]
    periods: tuple
    requests: tuple[FetchRequest, ...]


@dataclass(frozen=True)
class SecurityStage:
    security: SecurityForUpdate
    primary_bars: tuple[PriceBar, ...]
    fallback_bars: tuple[PriceBar, ...]
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
    provider_unavailable: int
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
    return SecurityPlan(
        security,
        latest,
        tuple(expected_dates),
        tuple(existing),
        periods,
        requests,
    )


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
    max_provider_unavailable: int = 5,
    fallback_provider: MarketDataProvider | None = None,
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
    unavailable: dict[int, str] = {}

    if max_provider_unavailable < 0:
        raise ValueError("max_provider_unavailable must be >= 0")

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

            # A security can be classified as PROVIDER_UNAVAILABLE only when:
            # - canonical history is completely empty,
            # - the pipeline genuinely requested required sessions, and
            # - the provider returned zero bars for every request.
            #
            # Existing securities that merely miss a recent session are NOT
            # quarantined here; they continue into strict history validation.
            if plan.requests and not plan.existing and not fetched:
                ranges = ", ".join(
                    f"{request.ticker}:{request.start.isoformat()}..{request.end.isoformat()}"
                    for request in plan.requests
                )
                unavailable[plan.security.security_id] = (
                    f"provider returned no bars for required range(s): {ranges}"
                )
                continue

            fetched_issues = validate_ohlcv_structure(sorted(fetched, key=lambda bar: bar.date))
            fetched_errors = [issue for issue in fetched_issues if issue.severity == Severity.ERROR]
            if fetched_errors:
                preview = "; ".join(
                    f"{issue.code}@{issue.date}: {issue.message}" for issue in fetched_errors[:8]
                )
                raise UpdatePipelineError(
                    f"{plan.security.ticker}: provider data failed structure checks: {preview}"
                )

            # Recovery is deliberately attempted only after the primary provider
            # returned at least some data, or canonical history already exists.
            # A never-seen security for which the primary provider returned
            # nothing remains PROVIDER_UNAVAILABLE and is not masked by fallback.
            primary_staged = _merge_bars(plan.existing, fetched)
            staged_dates = {bar.date for bar in primary_staged}
            missing_after_primary = [
                day for day in plan.required_dates if day not in staged_dates
            ]

            fallback_bars: list[PriceBar] = []
            if fallback_provider is not None and missing_after_primary:
                for day in missing_after_primary:
                    ticker = ticker_for_date(plan.periods, day)
                    if ticker is None:
                        raise UpdatePipelineError(
                            f"{plan.security.ticker}: no ticker identifier for fallback date "
                            f"{day.isoformat()}"
                        )

                    try:
                        recovered = fallback_provider.fetch(ticker, day, day)
                    except Exception as exc:
                        raise UpdatePipelineError(
                            f"{plan.security.ticker}: fallback provider failed for "
                            f"{day.isoformat()}: {exc}"
                        ) from exc

                    provider_calls += 1
                    fallback_bars.extend(
                        bar for bar in recovered if bar.date == day
                    )

                fallback_bars = _merge_bars([], fallback_bars)
                fetched_total += len(fallback_bars)

                fallback_issues = validate_ohlcv_structure(fallback_bars)
                fallback_errors = [
                    issue for issue in fallback_issues
                    if issue.severity == Severity.ERROR
                ]
                if fallback_errors:
                    preview = "; ".join(
                        f"{issue.code}@{issue.date}: {issue.message}"
                        for issue in fallback_errors[:8]
                    )
                    raise UpdatePipelineError(
                        f"{plan.security.ticker}: fallback data failed structure checks: "
                        f"{preview}"
                    )

            staged = _merge_bars(primary_staged, fallback_bars)
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
            for bar in [*fetched, *fallback_bars]:
                ticker = ticker_for_date(plan.periods, bar.date)
                if ticker is None:
                    raise UpdatePipelineError(
                        f"{plan.security.ticker}: no ticker identifier for fetched date "
                        f"{bar.date.isoformat()}"
                    )
                ticker_map[bar.date] = ticker

            stages.append(
                SecurityStage(
                    plan.security,
                    tuple(fetched),
                    tuple(fallback_bars),
                    ticker_map,
                    report,
                )
            )

        # Circuit breaker: a small number of isolated, never-seen provider
        # misses can be represented explicitly. A broad provider failure must
        # still fail closed.
        unavailable_count = len(unavailable)
        if unavailable_count:
            if unavailable_count == len(selected):
                raise UpdatePipelineError(
                    "Provider-unavailable circuit breaker: all selected securities returned no data"
                )
            if unavailable_count > max_provider_unavailable:
                raise UpdatePipelineError(
                    "Provider-unavailable circuit breaker: "
                    f"{unavailable_count} securities exceeded limit "
                    f"{max_provider_unavailable}"
                )

        inserted = 0
        updated = 0
        # One explicit transaction for the canonical market-data mutation.
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stage in stages:
                add, replace = upsert_price_bars(
                    conn,
                    stage.security.security_id,
                    stage.primary_bars,
                    ticker_at_date=stage.ticker_at_date,
                    source=provider.source_name,
                )
                inserted += add
                updated += replace

                if fallback_provider is not None and stage.fallback_bars:
                    add, replace = upsert_price_bars(
                        conn,
                        stage.security.security_id,
                        stage.fallback_bars,
                        ticker_at_date=stage.ticker_at_date,
                        source=fallback_provider.source_name,
                    )
                    inserted += add
                    updated += replace

            recorded_at = datetime.now().astimezone().isoformat()
            for security in selected:
                message = unavailable.get(security.security_id)
                data_status = "PROVIDER_UNAVAILABLE" if message is not None else "OK"
                conn.execute(
                    """INSERT INTO security_data_status
                       (run_id,security_id,as_of_date,provider,status,message,recorded_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        run_id,
                        security.security_id,
                        as_of.isoformat(),
                        provider.source_name,
                        data_status,
                        message,
                        recorded_at,
                    ),
                )

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
            provider_unavailable=len(unavailable),
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
            provider_unavailable=len(unavailable),
            validation_status="FAIL",
            error_message=str(exc),
        )
        _finish_run(conn, summary)
        raise UpdatePipelineError(str(exc)) from exc
