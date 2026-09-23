# Trading Calendar & Data Quality

## Purpose

V2 must never interpret "252 available observations" as "252 BIST trading-day returns" when a market session is missing. Calendar alignment is therefore a blocking validation step before indicator calculation and publication.

## Canonical session types

- `FULL`: normal BIST Pay Market session; counts as a trading day.
- `HALF`: official half-day session; **also counts as a trading day**.
- `CLOSED`: weekend or official full closure; does not count as a trading day.

Verified official holiday exceptions are stored in `data/reference/bist_calendar_exceptions.csv`. The initial checked-in coverage is 2023-2026 and is sourced from Borsa İstanbul's official holiday calendar.

The calendar intentionally raises `CalendarCoverageError` outside the verified years. It must not guess future holiday dates.

## Lookback rule

A momentum/FIP window of `N` returns requires `N+1` consecutive BIST trading-day closes. Therefore:

- 252-day return window -> 253 valid closes
- 126-day return window -> 127 valid closes
- 63-day return window -> 64 valid closes
- 21-day return window -> 22 valid closes

If any required trading session is absent, validation fails. An older observation cannot be pulled into the window to hide the gap.

## Blocking data-quality checks

The quality layer checks:

- duplicate dates
- non-monotonic dates
- future-dated bars
- bars on closed BIST sessions
- missing required BIST trading sessions
- stale latest bar
- missing/non-finite/non-positive OHLC
- impossible OHLC relationships (`High` below Open/Close/Low or `Low` above Open/Close/High)
- negative volume

Zero volume is warning-only because it can reflect illiquidity or suspension and must be investigated rather than rewritten.

## Production calculation path

Use `src.calculation.validated.compute_validated_snapshot`. It runs calendar/data-quality validation first and only then calls the calculation engine.

Direct use of `compute_snapshot` remains available for isolated unit tests and legacy regression analysis, but publication code should use the validated entry point.

## SQLite calendar table

`src.data.calendar_store.sync_trading_days` populates the existing `trading_days` table with `FULL`, `HALF`, and `CLOSED` sessions. This gives the update pipeline and audit layer a persistent canonical calendar.

## Update policy

Before a new calendar year is used in production, add the official Borsa İstanbul holiday schedule and expand the verified coverage. Until this is done, the pipeline should fail closed rather than assume ordinary weekdays are trading days.
