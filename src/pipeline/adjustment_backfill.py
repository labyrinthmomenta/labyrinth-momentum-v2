from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import sqlite3

from src.data.storage.adjustments import (
    load_price_adjustments,
    upsert_price_adjustments,
)
from src.data.storage.prices import (
    active_equities,
    identifier_periods,
    load_price_bars,
    ticker_for_date,
)


@dataclass(frozen=True)
class AdjustmentBackfillRequest:
    security_id: int
    ticker: str
    start: date
    end: date
    required_dates: tuple[date, ...]



@dataclass(frozen=True)
class AdjustmentBackfillSummary:
    requests_planned: int
    provider_calls: int
    records_fetched: int
    records_accepted: int
    records_inserted: int
    records_updated: int


def build_adjustment_backfill_plan(
    conn: sqlite3.Connection,
    *,
    as_of: date,
    tickers: set[str] | None = None,
) -> list[AdjustmentBackfillRequest]:
    """Plan missing adjustment metadata for existing canonical price dates.

    The plan is read-only:
    - daily_prices defines the dates that actually need metadata;
    - dates already present in price_adjustments are excluded;
    - historical identifier periods determine which ticker belongs to each date.
    """

    requests: list[AdjustmentBackfillRequest] = []

    selected_tickers = (
        {
            ticker.strip().upper().replace(".IS", "")
            for ticker in tickers
            if ticker.strip()
        }
        if tickers is not None
        else None
    )

    for security in active_equities(conn):
        if (
            selected_tickers is not None
            and security.ticker.upper() not in selected_tickers
        ):
            continue

        prices = load_price_bars(
            conn,
            security.security_id,
            end=as_of,
        )

        if not prices:
            continue

        existing_adjustments = load_price_adjustments(
            conn,
            security.security_id,
            end=as_of,
        )

        existing_dates = {
            record.date
            for record in existing_adjustments
        }

        missing_dates = [
            bar.date
            for bar in prices
            if bar.date not in existing_dates
        ]

        if not missing_dates:
            continue

        periods = identifier_periods(
            conn,
            security.security_id,
        )

        dates_by_ticker: dict[str, list[date]] = {}

        for day in missing_dates:
            ticker = ticker_for_date(
                periods,
                day,
            )

            if ticker is None:
                raise ValueError(
                    f"{security.ticker}: no historical ticker "
                    f"identifier for {day.isoformat()}"
                )

            dates_by_ticker.setdefault(
                ticker,
                [],
            ).append(day)

        for ticker, required_dates in dates_by_ticker.items():
            ordered_dates = tuple(
                sorted(required_dates)
            )

            requests.append(
                AdjustmentBackfillRequest(
                    security_id=security.security_id,
                    ticker=ticker,
                    start=ordered_dates[0],
                    end=ordered_dates[-1],
                    required_dates=ordered_dates,
                )
            )

    return sorted(
        requests,
        key=lambda request: (
            request.start,
            request.security_id,
            request.ticker,
        ),
    )



def run_adjustment_backfill(
    conn: sqlite3.Connection,
    provider,
    *,
    as_of: date,
    tickers: set[str] | None = None,
) -> AdjustmentBackfillSummary:
    """Fetch and atomically persist missing adjustment metadata only.

    Existing daily_prices are read-only input to this operation.
    Provider rows outside the plan's required dates are ignored.
    """

    plan = build_adjustment_backfill_plan(
        conn,
        as_of=as_of,
        tickers=tickers,
    )

    if not plan:
        return AdjustmentBackfillSummary(
            requests_planned=0,
            provider_calls=0,
            records_fetched=0,
            records_accepted=0,
            records_inserted=0,
            records_updated=0,
        )

    source = getattr(
        provider,
        "source_name",
        None,
    )

    if not source:
        raise ValueError(
            "Adjustment provider must define source_name"
        )

    staged: list[
        tuple[
            AdjustmentBackfillRequest,
            list,
        ]
    ] = []

    records_fetched = 0
    records_accepted = 0

    # Fetch everything before opening the write transaction.
    for request in plan:
        records = list(
            provider.fetch_adjustments(
                request.ticker,
                request.start,
                request.end,
            )
        )

        records_fetched += len(records)

        required_dates = set(
            request.required_dates
        )

        accepted = sorted(
            (
                record
                for record in records
                if record.date in required_dates
            ),
            key=lambda record: record.date,
        )

        accepted_dates = {
            record.date
            for record in accepted
        }

        missing_dates = sorted(
            required_dates - accepted_dates
        )

        if missing_dates:
            raise ValueError(
                f"{request.ticker}: missing adjustment metadata for "
                + ", ".join(
                    day.isoformat()
                    for day in missing_dates
                )
            )

        records_accepted += len(accepted)

        staged.append(
            (
                request,
                accepted,
            )
        )

    inserted = 0
    updated = 0

    conn.execute("BEGIN IMMEDIATE")

    try:
        for request, records in staged:
            if not records:
                continue

            add, replace = upsert_price_adjustments(
                conn,
                request.security_id,
                records,
                source=source,
            )

            inserted += add
            updated += replace

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    return AdjustmentBackfillSummary(
        requests_planned=len(plan),
        provider_calls=len(plan),
        records_fetched=records_fetched,
        records_accepted=records_accepted,
        records_inserted=inserted,
        records_updated=updated,
    )
