from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from typing import Literal, Sequence


AdjustmentStatus = Literal[
    "OK",
    "UNEXPLAINED_ADJUSTMENT",
]


@dataclass(frozen=True)
class VendorPriceBar:
    """Vendor-supplied OHLCV plus corporate-action metadata."""

    date: date

    open: float
    high: float
    low: float
    close: float

    adj_close: float
    volume: float

    dividend: float = 0.0
    stock_split: float = 0.0


@dataclass(frozen=True)
class TechnicalPriceBar:
    """Corporate-action-safe price bar for technical analysis.

    Technical OHLC is derived with:

        adjustment_factor = adj_close / raw_close

    The same factor is applied to Open, High, Low and Close.

    Volume is intentionally preserved as supplied by the vendor.
    Stock-split metadata is NOT applied to prices a second time.
    """

    date: date

    # Technical / adjusted OHLC
    open: float
    high: float
    low: float
    close: float

    # Vendor volume remains unchanged
    volume: float

    # Original vendor fields retained for auditability
    raw_open: float
    raw_high: float
    raw_low: float
    raw_close: float
    adj_close: float

    dividend: float
    stock_split: float

    adjustment_factor: float
    adjustment_status: AdjustmentStatus


def _require_finite(
    name: str,
    value: float,
    day: date,
) -> None:
    if not math.isfinite(value):
        raise ValueError(
            f"{name} must be finite on {day}"
        )


def _validate_vendor_bar(
    bar: VendorPriceBar,
) -> None:
    values = {
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "adj_close": bar.adj_close,
        "volume": bar.volume,
        "dividend": bar.dividend,
        "stock_split": bar.stock_split,
    }

    for name, value in values.items():
        _require_finite(
            name,
            value,
            bar.date,
        )

    if (
        bar.open <= 0
        or bar.high <= 0
        or bar.low <= 0
        or bar.close <= 0
        or bar.adj_close <= 0
    ):
        raise ValueError(
            f"price fields must be positive on {bar.date}"
        )

    if bar.high < bar.low:
        raise ValueError(
            f"high cannot be below low on {bar.date}"
        )

    if not (
        bar.low
        <= bar.open
        <= bar.high
    ):
        raise ValueError(
            f"open must lie within high/low on {bar.date}"
        )

    if not (
        bar.low
        <= bar.close
        <= bar.high
    ):
        raise ValueError(
            f"close must lie within high/low on {bar.date}"
        )

    if bar.volume < 0:
        raise ValueError(
            f"volume cannot be negative on {bar.date}"
        )

    if bar.dividend < 0:
        raise ValueError(
            f"dividend cannot be negative on {bar.date}"
        )

    if bar.stock_split < 0:
        raise ValueError(
            f"stock_split cannot be negative on {bar.date}"
        )


def _factor(
    bar: VendorPriceBar,
) -> float:
    factor = (
        bar.adj_close
        / bar.close
    )

    if (
        not math.isfinite(factor)
        or factor <= 0
    ):
        raise ValueError(
            f"invalid adjustment factor on {bar.date}"
        )

    return factor


def _material_factor_change_pct(
    previous: float,
    current: float,
) -> float:
    if previous <= 0:
        raise ValueError(
            "previous adjustment factor must be positive"
        )

    return abs(
        (current / previous) - 1.0
    ) * 100.0


def build_technical_prices(
    bars: Sequence[VendorPriceBar],
    *,
    material_change_tolerance_pct: float = 0.05,
) -> tuple[TechnicalPriceBar, ...]:
    """Build technical-analysis OHLC from vendor price data.

    Policy
    ------
    1. Vendor OHLC is preserved as raw audit data.
    2. Technical OHLC uses Adj Close / Close as one common factor.
    3. Volume is never multiplied or divided by that factor.
    4. Stock Splits metadata does not trigger an additional price
       transformation because validated Yahoo BIST history already
       presents split-normalized OHLC.
    5. A material factor change is accepted when the current bar
       contains dividend or split metadata.
    6. A material factor change without such metadata is retained
       but flagged UNEXPLAINED_ADJUSTMENT.
    7. Invalid or missing-equivalent numeric inputs fail closed;
       factor=1 is never silently invented.
    """

    if material_change_tolerance_pct < 0:
        raise ValueError(
            "material_change_tolerance_pct cannot be negative"
        )

    if not bars:
        return ()

    ordered = tuple(bars)

    for previous, current in zip(
        ordered,
        ordered[1:],
    ):
        if current.date <= previous.date:
            raise ValueError(
                "bars must be strictly increasing by date"
            )

    factors: list[float] = []

    for bar in ordered:
        _validate_vendor_bar(bar)
        factors.append(
            _factor(bar)
        )

    output: list[TechnicalPriceBar] = []

    for index, (bar, factor) in enumerate(
        zip(
            ordered,
            factors,
        )
    ):
        status: AdjustmentStatus = "OK"

        if index > 0:
            change_pct = (
                _material_factor_change_pct(
                    factors[index - 1],
                    factor,
                )
            )

            corporate_action_present = (
                bar.dividend != 0.0
                or bar.stock_split != 0.0
            )

            if (
                change_pct
                > material_change_tolerance_pct
                and not corporate_action_present
            ):
                status = (
                    "UNEXPLAINED_ADJUSTMENT"
                )

        technical_open = (
            bar.open
            * factor
        )
        technical_high = (
            bar.high
            * factor
        )
        technical_low = (
            bar.low
            * factor
        )
        technical_close = (
            bar.close
            * factor
        )

        # Technical close should equal vendor Adj Close apart from
        # ordinary floating-point representation.
        if not math.isclose(
            technical_close,
            bar.adj_close,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "derived technical close does not match "
                f"adj_close on {bar.date}"
            )

        output.append(
            TechnicalPriceBar(
                date=bar.date,

                open=technical_open,
                high=technical_high,
                low=technical_low,
                close=technical_close,

                volume=bar.volume,

                raw_open=bar.open,
                raw_high=bar.high,
                raw_low=bar.low,
                raw_close=bar.close,
                adj_close=bar.adj_close,

                dividend=bar.dividend,
                stock_split=bar.stock_split,

                adjustment_factor=factor,
                adjustment_status=status,
            )
        )

    return tuple(output)
