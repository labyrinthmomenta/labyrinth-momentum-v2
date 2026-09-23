from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Iterable

from src.data.calendar import BISTTradingCalendar
from src.data.providers.base import MarketDataProvider
from src.data.universe.manager import UniverseRecord
from src.data.universe.official import OfficialUniverseSnapshot
from src.validation.data_quality import Severity, validate_ohlcv_structure


class LivePreflightError(RuntimeError):
    pass


@dataclass(frozen=True)
class TickerProbe:
    ticker: str
    requested_start: date
    requested_end: date
    bars_received: int
    first_bar: date | None
    last_bar: date | None
    status: str


@dataclass(frozen=True)
class PreflightSummary:
    as_of: date
    equities: int
    market_counts: dict[str, int]
    tickers_checked: tuple[str, ...]
    probes: tuple[TickerProbe, ...]
    status: str


def run_live_preflight(
    *,
    calendar: BISTTradingCalendar,
    provider: MarketDataProvider,
    as_of: date,
    universe_fetcher: Callable[[], OfficialUniverseSnapshot],
    tickers: Iterable[str] = ("A1CAP", "ASELS", "THYAO"),
    lookback_calendar_days: int = 14,
) -> PreflightSummary:
    """Check live upstream sources without touching SQLite or public outputs.

    The probe deliberately asks for only a short price range. It verifies source
    reachability/schema and that each requested ticker is part of the official
    current equity universe. Full 253-session completeness remains the job of
    the normal dry-run/update pipeline.
    """
    snapshot = universe_fetcher()
    official = {r.ticker.upper().replace('.IS', ''): r for r in snapshot.records if r.instrument_type == 'EQUITY'}
    requested = tuple(sorted({t.strip().upper().replace('.IS', '') for t in tickers if t.strip()}))
    if not requested:
        raise LivePreflightError("At least one ticker is required for live preflight")

    missing = [ticker for ticker in requested if ticker not in official]
    if missing:
        raise LivePreflightError(f"Ticker(s) missing from official EQUITY universe: {', '.join(missing)}")

    latest = calendar.latest_trading_day_on_or_before(as_of)
    start = latest - timedelta(days=lookback_calendar_days)
    probes: list[TickerProbe] = []
    for ticker in requested:
        bars = provider.fetch(ticker, start, latest)
        bars = sorted(bars, key=lambda b: b.date)
        issues = validate_ohlcv_structure(bars)
        errors = [i for i in issues if i.severity == Severity.ERROR]
        if errors:
            preview = '; '.join(f"{i.code}@{i.date}" for i in errors[:5])
            raise LivePreflightError(f"{ticker}: provider structure check failed: {preview}")
        if not bars:
            raise LivePreflightError(f"{ticker}: provider returned no OHLCV bars")
        if bars[-1].date != latest:
            raise LivePreflightError(
                f"{ticker}: provider latest bar {bars[-1].date.isoformat()} != expected BIST session {latest.isoformat()}"
            )
        probes.append(
            TickerProbe(
                ticker=ticker,
                requested_start=start,
                requested_end=latest,
                bars_received=len(bars),
                first_bar=bars[0].date,
                last_bar=bars[-1].date,
                status='PASS',
            )
        )

    return PreflightSummary(
        as_of=as_of,
        equities=len(snapshot.records),
        market_counts=dict(snapshot.market_counts),
        tickers_checked=requested,
        probes=tuple(probes),
        status='PASS',
    )
