from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Iterable

from src.calculation.engine import PriceBar
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


def _recover_fallback_bar(
    provider: MarketDataProvider | None,
    ticker: str,
    day: date,
) -> PriceBar | None:
    """Return one structurally valid authoritative fallback bar, if available."""
    if provider is None:
        return None

    try:
        recovered = [
            bar
            for bar in provider.fetch(ticker, day, day)
            if bar.date == day
        ]
    except Exception as exc:
        raise LivePreflightError(
            f"{ticker}: fallback provider failed for {day.isoformat()}: {exc}"
        ) from exc

    issues = validate_ohlcv_structure(recovered)
    errors = [
        issue for issue in issues
        if issue.severity == Severity.ERROR
    ]

    if len(recovered) != 1 or errors:
        return None

    return recovered[0]


def run_live_preflight(
    *,
    calendar: BISTTradingCalendar,
    provider: MarketDataProvider,
    as_of: date,
    universe_fetcher: Callable[[], OfficialUniverseSnapshot],
    tickers: Iterable[str] = ("A1CAP", "ASELS", "THYAO"),
    lookback_calendar_days: int = 14,
    fallback_provider: MarketDataProvider | None = None,
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

        if not bars:
            # Preflight still verifies that the primary provider itself is
            # reachable. A total primary outage must not be hidden by fallback.
            raise LivePreflightError(
                f"{ticker}: provider returned no OHLCV bars"
            )

        issues = validate_ohlcv_structure(bars)
        errors = [
            issue for issue in issues
            if issue.severity == Severity.ERROR
        ]

        if errors:
            if fallback_provider is None:
                preview = '; '.join(
                    f"{issue.code}@{issue.date}"
                    for issue in errors[:5]
                )
                raise LivePreflightError(
                    f"{ticker}: provider structure check failed: {preview}"
                )

            undated_errors = [
                issue for issue in errors
                if issue.date is None
            ]
            if undated_errors:
                preview = '; '.join(
                    f"{issue.code}@{issue.date}"
                    for issue in undated_errors[:5]
                )
                raise LivePreflightError(
                    f"{ticker}: provider structure check failed: {preview}"
                )

            invalid_dates = sorted({
                issue.date for issue in errors
                if issue.date is not None
            })
            invalid_set = set(invalid_dates)
            bars = [
                bar for bar in bars
                if bar.date not in invalid_set
            ]

            for day in invalid_dates:
                recovered = _recover_fallback_bar(
                    fallback_provider,
                    ticker,
                    day,
                )
                if recovered is None:
                    raise LivePreflightError(
                        f"{ticker}: fallback recovery failed for "
                        f"{day.isoformat()}"
                    )
                bars.append(recovered)

            bars = sorted(bars, key=lambda b: b.date)

        # A stale/missing latest primary bar can also be recovered because the
        # production update pipeline has the same authoritative capability.
        if bars[-1].date != latest:
            recovered = _recover_fallback_bar(
                fallback_provider,
                ticker,
                latest,
            )
            if recovered is not None:
                bars = [
                    bar for bar in bars
                    if bar.date != latest
                ]
                bars.append(recovered)
                bars = sorted(bars, key=lambda b: b.date)

        if bars[-1].date != latest:
            raise LivePreflightError(
                f"{ticker}: provider latest bar "
                f"{bars[-1].date.isoformat()} != expected BIST session "
                f"{latest.isoformat()}"
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
