from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from typing import Sequence

from src.strategy.technical_prices import TechnicalPriceBar


@dataclass(frozen=True)
class VCPForwardOutcome:
    """Realized future performance after one historical snapshot.

    Values are decimal returns:
        0.10  -> +10%
       -0.05  -> -5%

    This object contains outcomes only. It must not contain or compute
    VCP strategy features.
    """

    reference_date: date
    reference_close: float

    forward_return_5: float | None
    forward_return_10: float | None
    forward_return_20: float | None
    forward_return_40: float | None

    mfe_40: float | None
    mae_40: float | None


def _forward_return(
    reference_close: float,
    future_bars: Sequence[TechnicalPriceBar],
    sessions: int,
) -> float | None:
    if len(future_bars) < sessions:
        return None

    future_close = float(
        future_bars[sessions - 1].close
    )

    return (
        future_close
        / reference_close
        - 1.0
    )


def compute_forward_outcome(
    reference_bar: TechnicalPriceBar,
    future_bars: Sequence[TechnicalPriceBar],
) -> VCPForwardOutcome:
    """Measure realized performance after ``reference_bar``.

    ``future_bars`` must contain only sessions strictly after the
    reference date and must be ordered by trading session.

    Session horizons are positional, not calendar-day based.
    No strategy analysis is performed here.
    """

    if reference_bar.adjustment_status != "OK":
        raise ValueError(
            "reference bar requires adjustment_status=OK"
        )

    reference_close = float(
        reference_bar.close
    )

    if (
        not math.isfinite(reference_close)
        or reference_close <= 0
    ):
        raise ValueError(
            "reference close must be finite and positive"
        )

    ordered = tuple(future_bars)

    previous_date = reference_bar.date

    for bar in ordered:
        if bar.date <= previous_date:
            raise ValueError(
                "future bars must be strictly increasing "
                "and after reference date"
            )

        if bar.adjustment_status != "OK":
            raise ValueError(
                "forward outcomes require adjustment_status=OK"
            )

        high = float(bar.high)
        low = float(bar.low)
        close = float(bar.close)

        if not all(
            math.isfinite(value)
            for value in (
                high,
                low,
                close,
            )
        ):
            raise ValueError(
                "future bar OHLC must be finite"
            )

        if high < low:
            raise ValueError(
                "future bar high cannot be below low"
            )

        if (
            high <= 0
            or low <= 0
            or close <= 0
        ):
            raise ValueError(
                "future bar prices must be positive"
            )

        if not (
            low <= close <= high
        ):
            raise ValueError(
                "future bar close must be within high/low"
            )

        previous_date = bar.date

    forward_return_5 = _forward_return(
        reference_close,
        ordered,
        5,
    )

    forward_return_10 = _forward_return(
        reference_close,
        ordered,
        10,
    )

    forward_return_20 = _forward_return(
        reference_close,
        ordered,
        20,
    )

    forward_return_40 = _forward_return(
        reference_close,
        ordered,
        40,
    )

    mfe_40: float | None = None
    mae_40: float | None = None

    if len(ordered) >= 40:
        horizon = ordered[:40]

        highest_high = max(
            float(bar.high)
            for bar in horizon
        )

        lowest_low = min(
            float(bar.low)
            for bar in horizon
        )

        mfe_40 = (
            highest_high
            / reference_close
            - 1.0
        )

        mae_40 = (
            lowest_low
            / reference_close
            - 1.0
        )

    return VCPForwardOutcome(
        reference_date=reference_bar.date,
        reference_close=reference_close,

        forward_return_5=forward_return_5,
        forward_return_10=forward_return_10,
        forward_return_20=forward_return_20,
        forward_return_40=forward_return_40,

        mfe_40=mfe_40,
        mae_40=mae_40,
    )


from src.strategy.vcp_analysis import VCPAnalysisResult


@dataclass(frozen=True)
class VCPReplaySnapshot:
    """Causal VCP research snapshot for one security and one as-of date.

    This object only flattens an already-computed VCPAnalysisResult.
    It does not re-run or reinterpret strategy logic.
    """

    security_id: int
    ticker: str
    as_of: date

    vcp_state: str
    contraction_count: int
    structurally_valid: bool

    contraction_depths: tuple[float, ...]
    final_to_first_depth_ratio: float | None
    decreasing_step_fraction: float | None

    range_5_pct: float | None
    current_tr_compression_10_40: float | None

    final_contraction_volume_ratio_50: float | None

    base_duration_sessions: int | None
    base_depth_pct: float | None
    base_atr_compression_ratio: float | None
    base_volume_dryup_ratio: float | None

    pivot_price: float | None
    distance_to_pivot_pct: float | None
    distance_to_pivot_atr: float | None

    first_intraday_breach_date: date | None
    first_close_break_date: date | None
    pivot_broken_by_close: bool
    breakout_volume_ratio_20: float | None


def build_replay_snapshot(
    *,
    security_id: int,
    ticker: str,
    as_of: date,
    analysis: VCPAnalysisResult,
) -> VCPReplaySnapshot:
    """Flatten one causal VCP analysis into a research snapshot."""

    if not analysis.technical_bars:
        raise ValueError(
            "VCP analysis must contain technical price bars"
        )

    latest_date = analysis.technical_bars[-1].date

    if as_of != latest_date:
        raise ValueError(
            "as_of must match the latest technical bar"
        )

    return VCPReplaySnapshot(
        security_id=security_id,
        ticker=ticker,
        as_of=as_of,

        vcp_state=analysis.state.state.value,

        contraction_count=(
            analysis.geometry.confirmed_contraction_count
        ),

        structurally_valid=(
            analysis.validity.structurally_valid
        ),

        contraction_depths=tuple(
            contraction.depth_pct
            for contraction
            in analysis.geometry.contractions
        ),

        final_to_first_depth_ratio=(
            analysis.validity.final_to_first_depth_ratio
        ),

        decreasing_step_fraction=(
            analysis.validity.decreasing_step_fraction
        ),

        range_5_pct=(
            analysis.features.range_5_pct
        ),

        current_tr_compression_10_40=(
            analysis.features.true_range_compression_10_40
        ),

        final_contraction_volume_ratio_50=(
            analysis.features.final_contraction_volume_ratio_50
        ),

        base_duration_sessions=(
            analysis.base_features.base_duration_sessions
        ),

        base_depth_pct=(
            analysis.base_features.base_depth_pct
        ),

        base_atr_compression_ratio=(
            analysis.base_features.base_atr_compression_ratio
        ),

        base_volume_dryup_ratio=(
            analysis.base_features.base_volume_dryup_ratio
        ),

        pivot_price=(
            analysis.breakout.pivot_price
        ),

        distance_to_pivot_pct=(
            analysis.features.distance_to_pivot_pct
        ),

        distance_to_pivot_atr=(
            analysis.features.distance_to_pivot_atr
        ),

        first_intraday_breach_date=(
            analysis.breakout.first_intraday_breach_date
        ),

        first_close_break_date=(
            analysis.breakout.first_close_break_date
        ),

        pivot_broken_by_close=(
            analysis.breakout.pivot_broken_by_close
        ),

        breakout_volume_ratio_20=(
            analysis.breakout.breakout_volume_ratio_20
        ),
    )


@dataclass(frozen=True)
class VCPReplayRow:
    """One historical VCP research observation.

    ``snapshot`` contains only information available on the as-of date.

    ``outcome`` contains only realized information after that date.
    """

    snapshot: VCPReplaySnapshot
    outcome: VCPForwardOutcome


def build_replay_row(
    snapshot: VCPReplaySnapshot,
    outcome: VCPForwardOutcome,
) -> VCPReplayRow:
    """Combine one causal snapshot with its realized future outcome."""

    if snapshot.as_of != outcome.reference_date:
        raise ValueError(
            "snapshot as_of must match outcome reference_date"
        )

    return VCPReplayRow(
        snapshot=snapshot,
        outcome=outcome,
    )


import sqlite3

from src.data.storage.prices import (
    identifier_periods,
    ticker_for_date,
)
from src.pipeline.vcp import run_vcp_analysis
from src.strategy.swing_detector import SwingDetectorConfig
from src.strategy.technical_price_adapter import (
    load_technical_prices,
)
from src.strategy.vcp_state import VCPStateConfig


def _future_session_dates(
    conn: sqlite3.Connection,
    security_id: int,
    *,
    as_of: date,
    limit: int = 40,
) -> tuple[date, ...]:
    """Return canonical sessions strictly after ``as_of``.

    Session selection is based on stored market dates, never calendar
    arithmetic.
    """

    if limit <= 0:
        raise ValueError(
            "future session limit must be positive"
        )

    rows = conn.execute(
        """
        SELECT date
        FROM daily_prices
        WHERE security_id=?
          AND date>?
        ORDER BY date
        LIMIT ?
        """,
        (
            security_id,
            as_of.isoformat(),
            limit,
        ),
    ).fetchall()

    return tuple(
        date.fromisoformat(row[0])
        for row in rows
    )


def build_replay_snapshot_from_db(
    conn: sqlite3.Connection,
    security_id: int,
    *,
    as_of: date,
    state_config: VCPStateConfig,
    swing_config: SwingDetectorConfig | None = None,
    atr_period: int = 14,
) -> VCPReplaySnapshot:
    """Build the causal snapshot side of one replay observation."""

    periods = identifier_periods(
        conn,
        security_id,
    )

    ticker = ticker_for_date(
        periods,
        as_of,
    )

    if ticker is None:
        raise ValueError(
            "no ticker identifier is valid on as_of"
        )

    analysis = run_vcp_analysis(
        conn,
        security_id,
        as_of=as_of,
        state_config=state_config,
        swing_config=swing_config,
        atr_period=atr_period,
    )

    return build_replay_snapshot(
        security_id=security_id,
        ticker=ticker,
        as_of=as_of,
        analysis=analysis,
    )


def build_replay_row_from_db(
    conn: sqlite3.Connection,
    security_id: int,
    *,
    as_of: date,
    state_config: VCPStateConfig,
    swing_config: SwingDetectorConfig | None = None,
    atr_period: int = 14,
    snapshot: VCPReplaySnapshot | None = None,
) -> VCPReplayRow:
    """Build one complete historical VCP replay row.

    Snapshot information is causal through ``as_of``.

    Outcome information may use up to the next 40 stored trading
    sessions solely for realized performance labels.

    A pre-built snapshot may be supplied by the batch layer so
    snapshot coverage can be preserved independently of outcome
    availability.
    """

    if snapshot is None:
        snapshot = build_replay_snapshot_from_db(
            conn,
            security_id,
            as_of=as_of,
            state_config=state_config,
            swing_config=swing_config,
            atr_period=atr_period,
        )
    else:
        if snapshot.security_id != security_id:
            raise ValueError(
                "snapshot security_id does not match requested security"
            )

        if snapshot.as_of != as_of:
            raise ValueError(
                "snapshot as_of does not match requested as_of"
            )

    future_dates = _future_session_dates(
        conn,
        security_id,
        as_of=as_of,
        limit=40,
    )

    outcome_end = (
        future_dates[-1]
        if future_dates
        else as_of
    )

    # Reference and future bars are loaded together so all outcome
    # prices share one corporate-action-safe technical-price basis.
    outcome_bars = load_technical_prices(
        conn,
        security_id,
        start=as_of,
        end=outcome_end,
    )

    if not outcome_bars:
        raise ValueError(
            "no technical outcome bars available from as_of"
        )

    if outcome_bars[0].date != as_of:
        raise ValueError(
            "outcome technical series must begin exactly on as_of"
        )

    reference_bar = outcome_bars[0]

    future_bars = tuple(
        bar
        for bar in outcome_bars[1:]
        if bar.date > as_of
    )

    outcome = compute_forward_outcome(
        reference_bar,
        future_bars,
    )

    return build_replay_row(
        snapshot,
        outcome,
    )


@dataclass(frozen=True)
class HistoricalEquity:
    """One equity observable in the historical universe on ``as_of``."""

    security_id: int
    ticker: str
    first_trade_date: date | None


def historical_equities(
    conn: sqlite3.Connection,
    *,
    as_of: date,
) -> tuple[HistoricalEquity, ...]:
    """Resolve the observable equity universe on one historical date.

    Historical eligibility deliberately does NOT depend on today's
    ``active`` or ``status`` fields.

    A security is eligible only when:

    - it is an EQUITY,
    - its declared first_trade_date is not after ``as_of``,
    - an exact canonical daily_prices bar exists on ``as_of``,
    - a ticker identifier is valid on ``as_of``.

    This allows securities that are inactive/delisted today to remain
    in older replay universes and reduces survivorship bias.
    """

    rows = conn.execute(
        """
        SELECT
            s.security_id,
            s.first_trade_date
        FROM securities s
        WHERE s.instrument_type='EQUITY'
          AND (
                s.first_trade_date IS NULL
                OR s.first_trade_date <= ?
              )
          AND EXISTS (
                SELECT 1
                FROM daily_prices dp
                WHERE dp.security_id = s.security_id
                  AND dp.date = ?
              )
        ORDER BY s.security_id
        """,
        (
            as_of.isoformat(),
            as_of.isoformat(),
        ),
    ).fetchall()

    result: list[HistoricalEquity] = []

    for row in rows:
        security_id = int(row[0])

        first_trade_date = (
            date.fromisoformat(row[1])
            if row[1]
            else None
        )

        ticker = ticker_for_date(
            identifier_periods(
                conn,
                security_id,
            ),
            as_of,
        )

        if ticker is None:
            continue

        result.append(
            HistoricalEquity(
                security_id=security_id,
                ticker=ticker,
                first_trade_date=first_trade_date,
            )
        )

    return tuple(result)


@dataclass(frozen=True)
class VCPReplaySkip:
    """One replay component that could not be produced."""

    security_id: int
    ticker: str
    as_of: date

    # SNAPSHOT:
    # failure using information through as_of.
    #
    # OUTCOME:
    # causal snapshot exists, but future performance label
    # could not be produced.
    stage: str

    reason: str


@dataclass(frozen=True)
class VCPReplayBatch:
    """Replay results for one historical as-of date.

    ``snapshots`` measures causal research coverage independently
    from future-outcome availability.

    ``rows`` contains only observations having both a snapshot and
    a usable future outcome.
    """

    as_of: date
    snapshots: tuple[VCPReplaySnapshot, ...]
    rows: tuple[VCPReplayRow, ...]
    skips: tuple[VCPReplaySkip, ...]


def build_replay_batch(
    conn: sqlite3.Connection,
    *,
    as_of: date,
    state_config: VCPStateConfig,
    swing_config: SwingDetectorConfig | None = None,
    atr_period: int = 14,
) -> VCPReplayBatch:
    """Build replay observations for the historical equity universe.

    Snapshot failures and future-outcome failures remain separate.

    Only expected ValueError data/causality failures are converted
    into skip records. Unexpected programming errors are deliberately
    allowed to propagate.
    """

    universe = historical_equities(
        conn,
        as_of=as_of,
    )

    snapshots: list[VCPReplaySnapshot] = []
    rows: list[VCPReplayRow] = []
    skips: list[VCPReplaySkip] = []

    for security in universe:

        # ----------------------------------------------
        # Stage 1: causal snapshot
        # ----------------------------------------------

        try:
            snapshot = build_replay_snapshot_from_db(
                conn,
                security.security_id,
                as_of=as_of,
                state_config=state_config,
                swing_config=swing_config,
                atr_period=atr_period,
            )

        except ValueError as exc:
            skips.append(
                VCPReplaySkip(
                    security_id=security.security_id,
                    ticker=security.ticker,
                    as_of=as_of,
                    stage="SNAPSHOT",
                    reason=str(exc),
                )
            )
            continue

        snapshots.append(
            snapshot
        )

        # ----------------------------------------------
        # Stage 2: realized future outcome
        # ----------------------------------------------

        try:
            row = build_replay_row_from_db(
                conn,
                security.security_id,
                as_of=as_of,
                state_config=state_config,
                swing_config=swing_config,
                atr_period=atr_period,
                snapshot=snapshot,
            )

        except ValueError as exc:
            skips.append(
                VCPReplaySkip(
                    security_id=security.security_id,
                    ticker=security.ticker,
                    as_of=as_of,
                    stage="OUTCOME",
                    reason=str(exc),
                )
            )
            continue

        rows.append(
            row
        )

    return VCPReplayBatch(
        as_of=as_of,
        snapshots=tuple(snapshots),
        rows=tuple(rows),
        skips=tuple(skips),
    )


@dataclass(frozen=True)
class VCPReplayGrid:
    """Replay batches for an explicit ordered set of historical dates."""

    batches: tuple[VCPReplayBatch, ...]


def build_replay_grid(
    conn: sqlite3.Connection,
    *,
    as_of_dates: tuple[date, ...] | list[date],
    state_config: VCPStateConfig,
    swing_config: SwingDetectorConfig | None = None,
    atr_period: int = 14,
) -> VCPReplayGrid:
    """Build replay batches for explicit historical as-of dates.

    Date selection is deliberately outside this function. The caller
    decides which trading dates, month-ends, or research checkpoints
    belong in the experiment.

    Dates must be strictly increasing so duplicate observations and
    accidental temporal reordering fail closed.
    """

    dates = tuple(as_of_dates)

    if any(
        current <= previous
        for previous, current in zip(
            dates,
            dates[1:],
        )
    ):
        raise ValueError(
            "as_of_dates must be strictly increasing"
        )

    batches = tuple(
        build_replay_batch(
            conn,
            as_of=as_of,
            state_config=state_config,
            swing_config=swing_config,
            atr_period=atr_period,
        )
        for as_of in dates
    )

    return VCPReplayGrid(
        batches=batches,
    )
