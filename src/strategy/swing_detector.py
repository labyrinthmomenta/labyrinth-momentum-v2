from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from typing import Literal, Sequence


SwingKind = Literal["HIGH", "LOW"]


@dataclass(frozen=True)
class SwingBar:
    date: date
    high: float
    low: float
    close: float
    atr_pct: float


@dataclass(frozen=True)
class SwingDetectorConfig:
    reversal_multiplier: float = 1.50
    absolute_floor_pct: float = 1.50
    min_leg_sessions: int = 2

    def __post_init__(self) -> None:
        if self.reversal_multiplier <= 0:
            raise ValueError("reversal_multiplier must be positive")
        if self.absolute_floor_pct < 0:
            raise ValueError("absolute_floor_pct cannot be negative")
        if self.min_leg_sessions < 1:
            raise ValueError("min_leg_sessions must be at least 1")


@dataclass(frozen=True)
class SwingPivot:
    kind: SwingKind
    price: float
    extreme_date: date
    confirmation_date: date | None
    threshold_pct: float


@dataclass(frozen=True)
class SwingDetectionResult:
    confirmed: tuple[SwingPivot, ...]
    provisional: SwingPivot | None


def _threshold_pct(
    atr_pct: float,
    config: SwingDetectorConfig,
) -> float:
    return max(
        config.absolute_floor_pct,
        config.reversal_multiplier * atr_pct,
    )


def _validate_bar(bar: SwingBar) -> None:
    values = {
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "atr_pct": bar.atr_pct,
    }

    for name, value in values.items():
        if not math.isfinite(value):
            raise ValueError(
                f"{name} must be finite on {bar.date}"
            )

    if bar.high <= 0 or bar.low <= 0 or bar.close <= 0:
        raise ValueError(
            f"prices must be positive on {bar.date}"
        )

    if bar.high < bar.low:
        raise ValueError(
            f"high cannot be below low on {bar.date}"
        )

    if not (bar.low <= bar.close <= bar.high):
        raise ValueError(
            f"close must lie within daily high/low on {bar.date}"
        )

    if bar.atr_pct < 0:
        raise ValueError(
            f"atr_pct cannot be negative on {bar.date}"
        )


def detect_swings(
    bars: Sequence[SwingBar],
    config: SwingDetectorConfig | None = None,
) -> SwingDetectionResult:
    """Detect causal ATR-adaptive swing highs and lows.

    Design principles
    -----------------
    * Extreme points use intraday HIGH / LOW.
    * Reversal confirmation uses CLOSE only.
    * Reversal threshold is:

          max(
              absolute_floor_pct,
              reversal_multiplier * atr_pct,
          )

    * The threshold attached to a candidate extreme is frozen using
      the ATR% observed on the date that extreme occurred.
    * Confirmed pivots never move after confirmation.
    * The currently developing extreme is returned separately as
      ``provisional``.
    * After a pivot is confirmed, the next leg starts on the next
      daily bar. This avoids assuming an unknown intraday ordering
      inside the confirmation bar.
    """

    if config is None:
        config = SwingDetectorConfig()

    if not bars:
        return SwingDetectionResult(
            confirmed=(),
            provisional=None,
        )

    ordered = list(bars)

    for previous, current in zip(ordered, ordered[1:]):
        if current.date <= previous.date:
            raise ValueError(
                "bars must be strictly increasing by date"
            )

    for bar in ordered:
        _validate_bar(bar)

    if len(ordered) == 1:
        return SwingDetectionResult(
            confirmed=(),
            provisional=None,
        )

    confirmed: list[SwingPivot] = []

    # SEEKING:
    # We do not assume whether the first meaningful leg is upward
    # or downward. A close-based move away from the initial anchor
    # must first clear the adaptive threshold.
    mode: Literal["SEEKING", "UP", "DOWN"] = "SEEKING"

    anchor_close = ordered[0].close
    anchor_threshold_pct = _threshold_pct(
        ordered[0].atr_pct,
        config,
    )

    candidate_price: float | None = None
    candidate_date: date | None = None
    candidate_index: int | None = None
    candidate_threshold_pct: float | None = None

    # Once a pivot is confirmed, the opposite candidate starts on
    # the NEXT daily bar rather than reusing the confirmation bar.
    start_new_leg_next_bar = False

    last_confirmed_extreme_index: int | None = None

    for index, bar in enumerate(ordered[1:], start=1):

        if start_new_leg_next_bar:
            start_new_leg_next_bar = False

            if mode == "UP":
                candidate_price = bar.high
            else:
                candidate_price = bar.low

            candidate_date = bar.date
            candidate_index = index
            candidate_threshold_pct = _threshold_pct(
                bar.atr_pct,
                config,
            )
            continue

        if mode == "SEEKING":
            up_move_pct = (
                (bar.close / anchor_close) - 1.0
            ) * 100.0

            down_move_pct = (
                1.0 - (bar.close / anchor_close)
            ) * 100.0

            if up_move_pct >= anchor_threshold_pct:
                mode = "UP"

                # Include all bars observed from the anchor through
                # the directional confirmation bar when locating the
                # first provisional extreme.
                window = ordered[: index + 1]
                extreme_offset = max(
                    range(len(window)),
                    key=lambda i: window[i].high,
                )
                extreme_bar = window[extreme_offset]

                candidate_price = extreme_bar.high
                candidate_date = extreme_bar.date
                candidate_index = extreme_offset
                candidate_threshold_pct = _threshold_pct(
                    extreme_bar.atr_pct,
                    config,
                )
                continue

            if down_move_pct >= anchor_threshold_pct:
                mode = "DOWN"

                window = ordered[: index + 1]
                extreme_offset = min(
                    range(len(window)),
                    key=lambda i: window[i].low,
                )
                extreme_bar = window[extreme_offset]

                candidate_price = extreme_bar.low
                candidate_date = extreme_bar.date
                candidate_index = extreme_offset
                candidate_threshold_pct = _threshold_pct(
                    extreme_bar.atr_pct,
                    config,
                )
                continue

            continue

        assert candidate_price is not None
        assert candidate_date is not None
        assert candidate_index is not None
        assert candidate_threshold_pct is not None

        if mode == "UP":
            if bar.high > candidate_price:
                candidate_price = bar.high
                candidate_date = bar.date
                candidate_index = index
                candidate_threshold_pct = _threshold_pct(
                    bar.atr_pct,
                    config,
                )

            reversal_level = candidate_price * (
                1.0 - candidate_threshold_pct / 100.0
            )

            leg_is_long_enough = (
                last_confirmed_extreme_index is None
                or (
                    candidate_index
                    - last_confirmed_extreme_index
                    >= config.min_leg_sessions
                )
            )

            if (
                bar.close <= reversal_level
                and leg_is_long_enough
            ):
                confirmed.append(
                    SwingPivot(
                        kind="HIGH",
                        price=candidate_price,
                        extreme_date=candidate_date,
                        confirmation_date=bar.date,
                        threshold_pct=candidate_threshold_pct,
                    )
                )

                last_confirmed_extreme_index = candidate_index

                mode = "DOWN"
                candidate_price = None
                candidate_date = None
                candidate_index = None
                candidate_threshold_pct = None
                start_new_leg_next_bar = True

            continue

        # mode == "DOWN"
        if bar.low < candidate_price:
            candidate_price = bar.low
            candidate_date = bar.date
            candidate_index = index
            candidate_threshold_pct = _threshold_pct(
                bar.atr_pct,
                config,
            )

        reversal_level = candidate_price * (
            1.0 + candidate_threshold_pct / 100.0
        )

        leg_is_long_enough = (
            last_confirmed_extreme_index is None
            or (
                candidate_index
                - last_confirmed_extreme_index
                >= config.min_leg_sessions
            )
        )

        if (
            bar.close >= reversal_level
            and leg_is_long_enough
        ):
            confirmed.append(
                SwingPivot(
                    kind="LOW",
                    price=candidate_price,
                    extreme_date=candidate_date,
                    confirmation_date=bar.date,
                    threshold_pct=candidate_threshold_pct,
                )
            )

            last_confirmed_extreme_index = candidate_index

            mode = "UP"
            candidate_price = None
            candidate_date = None
            candidate_index = None
            candidate_threshold_pct = None
            start_new_leg_next_bar = True

    provisional: SwingPivot | None = None

    if (
        mode in {"UP", "DOWN"}
        and candidate_price is not None
        and candidate_date is not None
        and candidate_threshold_pct is not None
    ):
        provisional = SwingPivot(
            kind="HIGH" if mode == "UP" else "LOW",
            price=candidate_price,
            extreme_date=candidate_date,
            confirmation_date=None,
            threshold_pct=candidate_threshold_pct,
        )

    return SwingDetectionResult(
        confirmed=tuple(confirmed),
        provisional=provisional,
    )
