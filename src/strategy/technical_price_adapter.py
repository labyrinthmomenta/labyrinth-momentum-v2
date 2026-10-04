from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import date
import math
import sqlite3

from src.strategy.technical_prices import (
    TechnicalPriceBar,
    VendorPriceBar,
    build_technical_prices,
)


YAHOO_SOURCE = "Yahoo Finance"
BIST_THB_SOURCE = "BIST_THB"
MAX_BRIDGE_GAP_DAYS = 7


def _require_adjustment_values(
    *,
    security_id: int,
    day: date,
    adj_close,
    adjustment_factor,
    dividend,
    stock_split,
) -> tuple[float, float, float, float]:
    values = {
        "adj_close": adj_close,
        "adjustment_factor": adjustment_factor,
        "dividend": dividend,
        "stock_split": stock_split,
    }

    for name, value in values.items():
        if value is None:
            raise ValueError(
                f"{name} is missing for "
                f"security_id={security_id} "
                f"on {day.isoformat()}"
            )

    adj_close_value = float(adj_close)
    factor_value = float(adjustment_factor)
    dividend_value = float(dividend)
    split_value = float(stock_split)

    for name, value in (
        ("adj_close", adj_close_value),
        ("adjustment_factor", factor_value),
        ("dividend", dividend_value),
        ("stock_split", split_value),
    ):
        if not math.isfinite(value):
            raise ValueError(
                f"{name} must be finite for "
                f"security_id={security_id} "
                f"on {day.isoformat()}"
            )

    if factor_value <= 0:
        raise ValueError(
            f"adjustment_factor must be positive for "
            f"security_id={security_id} "
            f"on {day.isoformat()}"
        )

    return (
        adj_close_value,
        factor_value,
        dividend_value,
        split_value,
    )


def _exact_vendor_bar(
    *,
    security_id: int,
    day: date,
    raw_open: float,
    raw_high: float,
    raw_low: float,
    raw_close: float,
    volume,
    adjustment,
) -> VendorPriceBar:
    (
        adj_close,
        stored_factor,
        dividend,
        stock_split,
    ) = _require_adjustment_values(
        security_id=security_id,
        day=day,
        adj_close=adjustment[0],
        adjustment_factor=adjustment[1],
        dividend=adjustment[2],
        stock_split=adjustment[3],
    )

    if raw_close <= 0:
        raise ValueError(
            f"close must be positive for "
            f"security_id={security_id} "
            f"on {day.isoformat()}"
        )

    derived_factor = adj_close / raw_close

    if not math.isclose(
        stored_factor,
        derived_factor,
        rel_tol=1e-9,
        abs_tol=1e-12,
    ):
        raise ValueError(
            "stored adjustment factor does not match "
            f"adj_close / close for security_id={security_id} "
            f"on {day.isoformat()}"
        )

    if volume is None:
        raise ValueError(
            f"volume is missing for "
            f"security_id={security_id} "
            f"on {day.isoformat()}"
        )

    return VendorPriceBar(
        date=day,
        open=raw_open,
        high=raw_high,
        low=raw_low,
        close=raw_close,
        adj_close=adj_close,
        volume=float(volume),
        dividend=dividend,
        stock_split=stock_split,
    )


def _bridged_vendor_bar(
    *,
    security_id: int,
    day: date,
    raw_open: float,
    raw_high: float,
    raw_low: float,
    raw_close: float,
    volume,
    factor: float,
) -> VendorPriceBar:
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError(
            f"invalid bridge adjustment factor for "
            f"security_id={security_id} "
            f"on {day.isoformat()}"
        )

    if volume is None:
        raise ValueError(
            f"volume is missing for "
            f"security_id={security_id} "
            f"on {day.isoformat()}"
        )

    return VendorPriceBar(
        date=day,
        open=raw_open,
        high=raw_high,
        low=raw_low,
        close=raw_close,
        adj_close=raw_close * factor,
        volume=float(volume),

        # No same-day corporate-action metadata exists for the
        # BIST_THB fallback bar. The bridge is permitted only when
        # the Yahoo factor is stable on both surrounding sides.
        dividend=0.0,
        stock_split=0.0,
    )


def load_technical_prices(
    conn: sqlite3.Connection,
    security_id: int,
    *,
    start: date | None = None,
    end: date | None = None,
    material_change_tolerance_pct: float = 0.05,
) -> tuple[TechnicalPriceBar, ...]:
    """Load corporate-action-safe prices for technical analysis.

    Source policy
    -------------
    * A canonical price first requires adjustment metadata from the
      same source and same date.
    * A BIST_THB canonical fallback bar without same-source adjustment
      may use a Yahoo Finance bridge only when strictly previous and
      next Yahoo adjustment factors are equal and both are no more
      than MAX_BRIDGE_GAP_DAYS away.
    * Leading BIST_THB one-sided bars before the first Yahoo adjustment
      are trimmed.
    * Trailing/internal one-sided bridges, factor boundaries and long
      bridge gaps fail closed.
    * Bridging is performed only in this technical-analysis layer.
      No synthetic price_adjustments row is written to SQLite.
    """

    if (
        start is not None
        and end is not None
        and end < start
    ):
        raise ValueError(
            "end must be on or after start"
        )

    price_sql = """
        SELECT
            date,
            open,
            high,
            low,
            close,
            volume,
            source
        FROM daily_prices
        WHERE security_id = ?
    """

    price_params: list[object] = [
        security_id,
    ]

    if start is not None:
        price_sql += " AND date >= ?"
        price_params.append(
            start.isoformat()
        )

    if end is not None:
        price_sql += " AND date <= ?"
        price_params.append(
            end.isoformat()
        )

    price_sql += " ORDER BY date"

    price_rows = conn.execute(
        price_sql,
        tuple(price_params),
    ).fetchall()

    adjustment_sql = """
        SELECT
            date,
            adj_close,
            adjustment_factor,
            dividend,
            stock_split,
            source
        FROM price_adjustments
        WHERE security_id = ?
    """

    adjustment_params: list[object] = [
        security_id,
    ]

    # Preserve adjustment history before ``start`` so the first
    # requested BIST_THB bar can still use a valid previous Yahoo
    # factor. Never read beyond ``end``: that would introduce
    # look-ahead into historical/as-of analysis.
    if end is not None:
        adjustment_sql += " AND date <= ?"
        adjustment_params.append(
            end.isoformat()
        )

    adjustment_sql += " ORDER BY date, source"

    adjustment_rows = conn.execute(
        adjustment_sql,
        tuple(adjustment_params),
    ).fetchall()

    exact_adjustments: dict[
        tuple[date, str],
        tuple[object, object, object, object],
    ] = {}

    yahoo_adjustments: dict[
        date,
        tuple[object, object, object, object],
    ] = {}

    for row in adjustment_rows:
        adjustment_day = date.fromisoformat(
            row[0]
        )
        source = str(
            row[5]
        )

        values = (
            row[1],
            row[2],
            row[3],
            row[4],
        )

        exact_adjustments[
            (adjustment_day, source)
        ] = values

        if source == YAHOO_SOURCE:
            yahoo_adjustments[
                adjustment_day
            ] = values

    yahoo_days = sorted(
        yahoo_adjustments
    )

    vendor_bars: list[VendorPriceBar] = []

    for row in price_rows:
        day = date.fromisoformat(
            row[0]
        )

        raw_open = float(
            row[1]
        )
        raw_high = float(
            row[2]
        )
        raw_low = float(
            row[3]
        )
        raw_close = float(
            row[4]
        )
        volume = row[5]
        price_source = str(
            row[6]
        )

        exact = exact_adjustments.get(
            (
                day,
                price_source,
            )
        )

        if exact is not None:
            vendor_bars.append(
                _exact_vendor_bar(
                    security_id=security_id,
                    day=day,
                    raw_open=raw_open,
                    raw_high=raw_high,
                    raw_low=raw_low,
                    raw_close=raw_close,
                    volume=volume,
                    adjustment=exact,
                )
            )
            continue

        if price_source != BIST_THB_SOURCE:
            raise ValueError(
                f"missing adjustment metadata for "
                f"security_id={security_id} "
                f"on {day.isoformat()} "
                f"source={price_source}"
            )

        # BIST_THB has no same-source adjustment. Look for strictly
        # surrounding Yahoo adjustment factors.
        previous_index = (
            bisect_left(
                yahoo_days,
                day,
            )
            - 1
        )

        next_index = bisect_right(
            yahoo_days,
            day,
        )

        previous_day = (
            yahoo_days[previous_index]
            if previous_index >= 0
            else None
        )

        next_day = (
            yahoo_days[next_index]
            if next_index < len(yahoo_days)
            else None
        )

        if (
            previous_day is None
            and next_day is not None
        ):
            # This is safe only as an unsupported leading prefix.
            # Do not invent an adjustment factor before Yahoo history
            # starts.
            if not vendor_bars:
                continue

            raise ValueError(
                f"internal one-sided BIST_THB adjustment bridge for "
                f"security_id={security_id} "
                f"on {day.isoformat()}"
            )

        if (
            previous_day is not None
            and next_day is None
        ):
            raise ValueError(
                f"trailing one-sided BIST_THB adjustment bridge for "
                f"security_id={security_id} "
                f"on {day.isoformat()}"
            )

        if (
            previous_day is None
            and next_day is None
        ):
            raise ValueError(
                f"no Yahoo adjustment neighbors for "
                f"security_id={security_id} "
                f"on {day.isoformat()}"
            )

        assert previous_day is not None
        assert next_day is not None

        previous_values = (
            yahoo_adjustments[
                previous_day
            ]
        )
        next_values = (
            yahoo_adjustments[
                next_day
            ]
        )

        previous_factor_raw = (
            previous_values[1]
        )
        next_factor_raw = (
            next_values[1]
        )

        if (
            previous_factor_raw is None
            or next_factor_raw is None
        ):
            raise ValueError(
                f"missing Yahoo bridge adjustment factor for "
                f"security_id={security_id} "
                f"on {day.isoformat()}"
            )

        previous_factor = float(
            previous_factor_raw
        )
        next_factor = float(
            next_factor_raw
        )

        if (
            not math.isfinite(previous_factor)
            or previous_factor <= 0
            or not math.isfinite(next_factor)
            or next_factor <= 0
        ):
            raise ValueError(
                f"invalid Yahoo bridge adjustment factor for "
                f"security_id={security_id} "
                f"on {day.isoformat()}"
            )

        if not math.isclose(
            previous_factor,
            next_factor,
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise ValueError(
                f"factor boundary across BIST_THB fallback for "
                f"security_id={security_id} "
                f"on {day.isoformat()}"
            )

        previous_gap = (
            day - previous_day
        ).days
        next_gap = (
            next_day - day
        ).days

        if (
            previous_gap > MAX_BRIDGE_GAP_DAYS
            or next_gap > MAX_BRIDGE_GAP_DAYS
        ):
            raise ValueError(
                f"Yahoo bridge gap exceeds "
                f"{MAX_BRIDGE_GAP_DAYS} days for "
                f"security_id={security_id} "
                f"on {day.isoformat()}"
            )

        vendor_bars.append(
            _bridged_vendor_bar(
                security_id=security_id,
                day=day,
                raw_open=raw_open,
                raw_high=raw_high,
                raw_low=raw_low,
                raw_close=raw_close,
                volume=volume,
                factor=previous_factor,
            )
        )

    return build_technical_prices(
        vendor_bars,
        material_change_tolerance_pct=(
            material_change_tolerance_pct
        ),
    )
