from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Sequence

from src.calculation.engine import IndicatorSnapshot, PriceBar, derive_returns


def build_detail_payload(
    *,
    security_id: int,
    ticker: str,
    name: str,
    sector: str | None,
    industry: str | None,
    first_trade_date: date | None,
    snapshot: IndicatorSnapshot,
    bars: Sequence[PriceBar],
) -> dict:
    """Build a derived public detail payload from canonical OHLCV.

    The database remains canonical. This JSON is intentionally disposable and
    can always be rebuilt from SQLite.
    """
    returns = {point.date: point.value for point in derive_returns(bars)}
    daily = []
    for bar in bars:
        daily.append(
            {
                "date": bar.date.isoformat(),
                "close": bar.close,
                "volume": bar.volume,
                "return": returns.get(bar.date),
            }
        )
    payload = {
        "security": {
            "security_id": security_id,
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "industry": industry,
            "first_trade_date": first_trade_date.isoformat() if first_trade_date else None,
        },
        "snapshot": snapshot.as_dict(),
        "daily": daily,
    }
    payload["snapshot"]["as_of"] = snapshot.as_of.isoformat()
    return payload
