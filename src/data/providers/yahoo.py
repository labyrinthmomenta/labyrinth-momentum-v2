from __future__ import annotations

from datetime import date, timedelta
import math
import logging
from typing import Iterable

from src.calculation.engine import PriceBar
from src.data.calendar import BISTTradingCalendar, CalendarCoverageError

logger = logging.getLogger(__name__)
from src.data.providers.base import BatchFetchResult


class YahooProvider:
    """Yahoo Finance adapter for Borsa Istanbul equities.

    The pipeline uses raw, unadjusted OHLC so ATR and price continuity can be
    validated explicitly. ``auto_adjust=False`` is intentional and pinned in
    the call rather than relying on yfinance defaults.

    Full-universe updates use ``fetch_many`` so securities with the same missing
    date range are downloaded in chunks instead of one HTTP-style request per
    ticker. The single-ticker ``fetch`` method remains available as a fallback.
    """

    source_name = "Yahoo Finance"

    def __init__(self, suffix: str = ".IS", batch_size: int = 50,
                 calendar: BISTTradingCalendar | None = None):
        self.calendar = calendar if calendar is not None else BISTTradingCalendar.from_csv()
        self.suffix = suffix
        self.batch_size = max(1, int(batch_size))

    @staticmethod
    def _clean_number(value):
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    def _symbol(self, ticker: str) -> str:
        return ticker if ticker.endswith(self.suffix) else f"{ticker}{self.suffix}"

    @staticmethod
    def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
        for index in range(0, len(values), size):
            yield values[index : index + size]

    def _frame_to_bars(self, frame, start: date, end: date, ticker: str = "unknown") -> list[PriceBar]:
        if frame is None or frame.empty:
            return []

        # A one-symbol slice can retain a redundant MultiIndex level.
        if getattr(frame.columns, "nlevels", 1) > 1:
            frame = frame.copy()
            frame.columns = frame.columns.get_level_values(-1)

        required = {"Open", "High", "Low", "Close", "Volume"}
        missing = required - set(frame.columns)
        if missing:
            raise RuntimeError(f"Yahoo response missing columns: {sorted(missing)}")

        bars: list[PriceBar] = []
        for index, row in frame.iterrows():
            day = index.date() if hasattr(index, "date") else date.fromisoformat(str(index)[:10])
            if day < start or day > end:
                continue
            open_ = self._clean_number(row["Open"])
            high = self._clean_number(row["High"])
            low = self._clean_number(row["Low"])
            close = self._clean_number(row["Close"])
            volume = self._clean_number(row["Volume"])
            # Keep malformed rows visible to the quality layer rather than
            # silently coercing them into valid-looking zeroes.
            bars.append(
                PriceBar(
                    day,
                    float("nan") if open_ is None else open_,
                    float("nan") if high is None else high,
                    float("nan") if low is None else low,
                    float("nan") if close is None else close,
                    volume,
                )
            )
        return self._remove_closed_session_placeholders(
            sorted(bars, key=lambda item: item.date), ticker
        )

    def _remove_closed_session_placeholders(self, bars: list[PriceBar], ticker: str) -> list[PriceBar]:
        """Discard Yahoo rows dated on official BIST closed sessions.

        The BIST trading calendar is authoritative for whether a market
        session exists. Yahoo can emit carry-forward, adjusted, empty, or
        otherwise synthetic rows on closed dates; none belong in canonical
        daily prices.

        No dates are shifted and no prices are synthesized. Calendar dates
        outside verified coverage remain visible to downstream validation.
        """
        kept: list[PriceBar] = []
        removed: list[date] = []

        for bar in bars:
            try:
                trading = self.calendar.is_trading_day(bar.date)
            except CalendarCoverageError:
                kept.append(bar)
                continue

            if not trading:
                removed.append(bar.date)
                continue

            kept.append(bar)

        if removed:
            logger.warning(
                "YAHOO_CLOSED_SESSION_PLACEHOLDER ticker=%s removed=%d dates=%s",
                ticker,
                len(removed),
                ",".join(day.isoformat() for day in removed),
            )

        return kept

    def fetch(self, ticker: str, start: date, end: date) -> list[PriceBar]:
        if end < start:
            raise ValueError("end must be on or after start")
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("yfinance is required for Yahoo data provider") from exc

        symbol = self._symbol(ticker)
        vendor_end = end + timedelta(days=1)  # yfinance end is exclusive.
        frame = yf.download(
            symbol,
            start=start.isoformat(),
            end=vendor_end.isoformat(),
            auto_adjust=False,
            progress=False,
            actions=False,
            group_by="column",
            threads=False,
        )
        if frame is not None and not frame.empty and getattr(frame.columns, "nlevels", 1) > 1:
            # Single-symbol downloads often return Price/Ticker MultiIndex.
            try:
                frame = frame.xs(symbol, axis=1, level=-1, drop_level=True)
            except (KeyError, ValueError):
                frame = frame.copy()
                frame.columns = frame.columns.get_level_values(0)
        return self._frame_to_bars(frame, start, end, ticker)

    def fetch_many(self, tickers: list[str], start: date, end: date) -> BatchFetchResult:
        """Download one date range for many BIST tickers in bounded chunks."""
        if end < start:
            raise ValueError("end must be on or after start")
        clean = list(dict.fromkeys(t.strip().upper().replace(self.suffix, "") for t in tickers if t.strip()))
        if not clean:
            return BatchFetchResult({}, 0)
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("yfinance is required for Yahoo data provider") from exc

        output: dict[str, list[PriceBar]] = {ticker: [] for ticker in clean}
        calls = 0
        vendor_end = end + timedelta(days=1)
        for chunk in self._chunks(clean, self.batch_size):
            symbols = [self._symbol(ticker) for ticker in chunk]
            calls += 1
            frame = yf.download(
                symbols,
                start=start.isoformat(),
                end=vendor_end.isoformat(),
                auto_adjust=False,
                progress=False,
                actions=False,
                group_by="ticker",
                threads=False,
            )
            if frame is None or frame.empty:
                continue

            if len(chunk) == 1:
                ticker = chunk[0]
                symbol = symbols[0]
                sub = frame
                if getattr(frame.columns, "nlevels", 1) > 1:
                    # group_by='ticker' normally gives Ticker/Price levels.
                    try:
                        sub = frame[symbol]
                    except (KeyError, TypeError):
                        try:
                            sub = frame.xs(symbol, axis=1, level=0, drop_level=True)
                        except (KeyError, ValueError):
                            sub = frame.copy()
                            sub.columns = sub.columns.get_level_values(-1)
                output[ticker].extend(self._frame_to_bars(sub, start, end, ticker))
                continue

            if getattr(frame.columns, "nlevels", 1) < 2:
                raise RuntimeError("Yahoo batch response did not include per-ticker columns")
            level0 = set(frame.columns.get_level_values(0))
            level_last = set(frame.columns.get_level_values(-1))
            for ticker, symbol in zip(chunk, symbols):
                try:
                    if symbol in level0:
                        sub = frame[symbol]
                    elif symbol in level_last:
                        sub = frame.xs(symbol, axis=1, level=-1, drop_level=True)
                    else:
                        # Missing symbols are represented by an empty result and
                        # will fail the downstream missing-session validation.
                        continue
                    output[ticker].extend(self._frame_to_bars(sub, start, end, ticker))
                except (KeyError, ValueError):
                    continue

        # yfinance multi-symbol downloads can occasionally return an empty
        # ticker slice or non-finite OHLC even though a single-symbol request is
        # healthy. Retry only those suspicious ticker results once through the
        # conservative single-ticker path (threads=False).
        #
        # A genuinely unsupported ticker remains empty after this retry and is
        # handled explicitly by the pipeline as PROVIDER_UNAVAILABLE.
        for ticker in clean:
            bars = output.get(ticker, [])

            if not bars:
                retry_reason = "empty"
            elif any(
                not all(
                    math.isfinite(value)
                    for value in (bar.open, bar.high, bar.low, bar.close)
                )
                for bar in bars
            ):
                retry_reason = "nonfinite_ohlc"
            else:
                continue

            logger.warning(
                "YAHOO_BATCH_RETRY ticker=%s reason=%s",
                ticker,
                retry_reason,
            )

            calls += 1
            output[ticker] = self.fetch(ticker, start, end)

        return BatchFetchResult(output, calls)


def fetch_ohlcv(ticker: str, calendar_days: int = 30):
    """Backwards-compatible helper retained for earlier V2 code/tests."""
    end = date.today()
    start = end - timedelta(days=calendar_days)
    return YahooProvider().fetch(ticker, start, end)
