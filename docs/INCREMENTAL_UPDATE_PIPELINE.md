# Incremental Market-Data Update Pipeline

## Goal

The canonical V2 database must never be left half-updated. Market data is therefore fetched into an in-memory staging layer, validated against the verified BIST calendar, and committed to `daily_prices` only after every selected active equity passes validation.

## Flow

```text
Active BIST equities
        ↓
Required BIST sessions (max window + 1 close)
        ↓
Compare with SQLite daily_prices
        ↓
Fetch only missing sessions
        ↓
Group equal date ranges + batch provider requests when supported
        ↓
Resolve ticker valid on each missing date
        ↓
Stage + validate OHLCV/calendar continuity
        ↓
ALL PASS?
   ├── No  → write FAILED audit row; daily_prices unchanged
   └── Yes → one SQLite transaction → commit all staged bars
```

## Incremental behavior

For the 252-return window the engine needs 253 consecutive BIST closes. If all 253 are already present, the provider is not called. If only the latest session is missing, only that session is requested. Re-running a successful update for the same `as_of` date is idempotent.

## IPO behavior

`first_trade_date` is a hard lower boundary. Sessions before that date are not treated as missing data. A new listing can therefore pass data-quality validation with a short history while 252/126/63-day indicators remain `NULL` until enough observations exist.

## Ticker changes

`security_identifiers.valid_to` is interpreted as an **exclusive** boundary. If a symbol changes on 2026-06-01, the old identifier applies before 2026-06-01 and the new identifier applies from 2026-06-01 onward. Missing dates are grouped by the identifier valid on those dates, so bootstrap/incremental requests can use both old and new Yahoo symbols without rewriting historical identity.

## Atomicity

`daily_prices` mutation uses a single `BEGIN IMMEDIATE` transaction after staging. Any provider or validation failure before that point causes no canonical price mutation. Any exception during the commit block causes an explicit rollback. `pipeline_runs` is still updated to `FAILED` so the failure remains auditable.

## Provider boundary

The pipeline depends on the `MarketDataProvider` protocol rather than directly on yfinance. `YahooProvider` is the first adapter and explicitly requests raw OHLC (`auto_adjust=False`) so ATR and validation use unadjusted vendor values. The adapter can later be replaced by another licensed vendor without changing the storage/calculation layers.

Providers may optionally expose `fetch_many`. The update planner groups requests that share the same start/end date and lets the provider download those tickers together. `YahooProvider` chunks these groups at 50 tickers per vendor call by default. Providers without batch support continue to use the original single-ticker `fetch` fallback. `pipeline_runs.provider_calls` records the underlying provider call count reported by the adapter.

## Local commands

Initialize:

```bash
python run.py init
```

Run an update:

```bash
python run.py update --as-of 2026-09-23
```

For production, run only after the official BIST universe has been synchronized and the requested year is within the verified calendar coverage.
