# Calculation Methods — Labyrinth Momentum V2

## Canonical principle

V2 derives all indicators from canonical OHLCV stored in SQLite. Daily return is **not** stored as a primary market-data field; it is derived as:

`R_t = Close_t / Close_(t-1) - 1`

A 252-return calculation therefore requires at least 253 valid closing prices.

## Momentum

V2 computes compounded momentum over the latest completed return observations:

- M252: 252 trading returns
- M126: 126 trading returns
- M63: 63 trading returns
- M21: 21 trading returns

`Momentum_N = product(1 + R_t) - 1`

Insufficient history returns `NULL`/`None`; it is never converted to zero.

## FIP

Selected methodology:

`FIP_N = sign(Momentum_N) × (N_negative - N_positive) / N`

Flat days remain in denominator `N` but are neither positive nor negative.
The magnitude of Momentum does not scale FIP; only Momentum's sign determines the direction of the FIP score.

This convention was independently regression-checked against the A1CAP V1 detail JSON. For the completed 12-month V1 window 2025-09 through 2026-08, 251 observations (136 negative, 111 positive, 4 flat) reproduce:

- V1 Momentum: `-0.156294` after rounding
- V1 FIP: `-0.099602` after rounding

## ATR14%

True Range:

`TR_t = max(High_t - Low_t, abs(High_t - Close_(t-1)), abs(Low_t - Close_(t-1)))`

ATR(14) uses Wilder smoothing. The screener field is:

`ATR14% = ATR(14) / Close × 100`

## Momentum/FIP acceleration fields

- `ΔMom 21/63 = M21 - M63`
- `ΔFIP 21/63 = FIP21 - FIP63`

These are descriptive acceleration/quality-change measurements, not standalone trading signals.

## Monthly context

The UI/reporting field "1M" means the **last completed calendar month**. It is deliberately separate from M21, which always means the latest 21 trading returns.

## Trading-calendar requirement

The pure calculation engine operates on ordered observations and is intentionally provider-agnostic. Before production publication, the pipeline must validate price dates against the canonical BIST trading calendar. Missing sessions must not be silently compressed into a shorter observation sequence.

## V1 vs V2 regression roles

V1 is immutable legacy evidence. Two validations are kept separate:

1. **Legacy reconstruction:** prove that archived V1 daily returns reproduce archived V1 Momentum/FIP values.
2. **V2 methodology tests:** prove that fixed 252/126/63/21 calculations, ATR and delta fields follow the approved V2 definitions.

A future provider-level parity test can then compare V2 OHLC-derived returns with V1 return history on overlapping dates without allowing V1 Excel to become the V2 calculation engine.
