"""Canonical market-index update pipeline.

This module populates the market_indices and index_daily_prices
tables used by the descriptive Market Regime layer.

Provider data is fetched and validated before any database write.
Database persistence is then performed atomically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
import sqlite3

from src.calculation.engine import PriceBar
from src.data.providers.base import MarketDataProvider
from src.data.storage.indices import (
    CORE_MARKET_INDICES,
    ensure_core_market_indices,
    upsert_index_price_bars,
)


@dataclass(frozen=True)
class IndexUpdateSummary:
    indices_processed: int
    bars_fetched: int
    inserted: int
    updated: int


def _validate_bars(
    index_code: str,
    bars: list[PriceBar],
    *,
    start: date,
    end: date,
) -> None:
    seen_dates: set[date] = set()

    for bar in bars:
        if (
            bar.date < start
            or bar.date > end
        ):
            raise ValueError(
                f"{index_code} returned bar outside "
                f"requested range: {bar.date}"
            )

        if bar.date in seen_dates:
            raise ValueError(
                f"{index_code} duplicate bar date: "
                f"{bar.date}"
            )

        seen_dates.add(
            bar.date
        )

        open_price = float(
            bar.open
        )
        high = float(
            bar.high
        )
        low = float(
            bar.low
        )
        close = float(
            bar.close
        )

        prices = (
            open_price,
            high,
            low,
            close,
        )

        if any(
            (
                not math.isfinite(value)
                or value <= 0
            )
            for value in prices
        ):
            raise ValueError(
                f"{index_code} invalid OHLC "
                f"on {bar.date}"
            )

        if (
            high < max(
                open_price,
                close,
                low,
            )
            or low > min(
                open_price,
                close,
                high,
            )
        ):
            raise ValueError(
                f"{index_code} invalid OHLC "
                f"on {bar.date}"
            )

        if bar.volume is not None:
            volume = float(
                bar.volume
            )

            if (
                not math.isfinite(volume)
                or volume < 0
            ):
                raise ValueError(
                    f"{index_code} invalid volume "
                    f"on {bar.date}"
                )


def update_market_indices(
    conn: sqlite3.Connection,
    provider: MarketDataProvider,
    *,
    start: date,
    end: date,
) -> IndexUpdateSummary:
    """Fetch and atomically persist the core BIST indices."""

    if start > end:
        raise ValueError(
            "start must not be after end"
        )

    source = getattr(
        provider,
        "source_name",
        None,
    )

    if (
        not isinstance(source, str)
        or not source.strip()
    ):
        raise ValueError(
            "provider must expose a non-empty source_name"
        )

    fetched_by_code: dict[
        str,
        list[PriceBar],
    ] = {}

    # Stage first: no database writes until all provider
    # requests and all validation checks have succeeded.
    for market_index in CORE_MARKET_INDICES:
        code = market_index.index_code

        bars = list(
            provider.fetch(
                code,
                start,
                end,
            )
        )

        _validate_bars(
            code,
            bars,
            start=start,
            end=end,
        )

        fetched_by_code[code] = bars

    inserted = 0
    updated = 0

    # Persist atomically only after the complete staging phase.
    with conn:
        ensure_core_market_indices(
            conn
        )

        for market_index in CORE_MARKET_INDICES:
            code = market_index.index_code

            new_inserted, new_updated = (
                upsert_index_price_bars(
                    conn,
                    code,
                    fetched_by_code[code],
                    source=source,
                )
            )

            inserted += new_inserted
            updated += new_updated

    return IndexUpdateSummary(
        indices_processed=len(
            CORE_MARKET_INDICES
        ),
        bars_fetched=sum(
            len(bars)
            for bars
            in fetched_by_code.values()
        ),
        inserted=inserted,
        updated=updated,
    )
