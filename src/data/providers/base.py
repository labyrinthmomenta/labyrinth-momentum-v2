from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from src.calculation.engine import PriceBar


@dataclass(frozen=True)
class BatchFetchResult:
    """Result of one logical multi-ticker provider request.

    ``provider_calls`` records the number of underlying vendor download calls
    used by the adapter (for example, Yahoo chunks a large ticker set). This
    keeps pipeline telemetry meaningful even when batching is enabled.
    """

    bars_by_ticker: dict[str, list[PriceBar]]
    provider_calls: int


class MarketDataProvider(Protocol):
    """Minimal provider contract used by the update pipeline.

    ``end`` is inclusive at this abstraction layer. Provider adapters are
    responsible for translating to any vendor-specific exclusive end date.

    Providers may optionally implement ``fetch_many(tickers, start, end)`` and
    return :class:`BatchFetchResult`. The pipeline detects this method at
    runtime and otherwise falls back to ``fetch``.
    """

    source_name: str

    def fetch(self, ticker: str, start: date, end: date) -> list[PriceBar]:
        ...
