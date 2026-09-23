# Labyrinth Momentum V2

Labyrinth Momentum V2 is the next-generation BIST momentum screener architecture. It replaces the V1 Excel-centric calculation flow with a canonical SQLite/OHLCV data model, explicit validation gates, reproducible indicator calculations, and guarded GitHub Actions automation.

> **Status:** repository-ready release candidate. V1 remains untouched and is retained only as an immutable migration/regression reference.

## Architecture

```text
Official BIST/KAP universe
        ↓
BIST trading calendar
        ↓
Yahoo Finance OHLCV
        ↓
SQLite canonical database
        ↓
Data-quality validation
        ↓
Calculation engine
        ↓
Staged JSON output
        ↓
Publication gate
        ↓
Generated docs/data
```

## Core principles

- V1 repository is never modified by V2.
- SQLite is the canonical V2 market-data store.
- OHLCV is canonical; returns are derived from closing prices.
- Security identity is `security_id`, not ticker.
- Ticker changes preserve historical identity and price history.
- IPOs receive no fabricated pre-listing history.
- Missing history produces `NULL`, never synthetic zeroes.
- Suspended/illiquid observations are not silently treated as delistings.
- A partial ticker subset may run only in dry-run mode.
- Public output is promoted only after the complete active equity universe passes validation.
- External-source or schema failures are fail-closed.

## Indicators

V2 calculates:

- Momentum: 252 / 126 / 63 / 21 trading-day windows
- FIP: 252 / 126 / 63 / 21 using
  `sign(Momentum) × (negative_days - positive_days) / N`
- ATR14%: `Wilder ATR(14) / Close × 100`
- ΔMomentum 21/63: `M21 - M63`
- ΔFIP 21/63: `FIP21 - FIP63`
- Monthly context: last completed calendar month

A 252-return calculation requires 253 consecutive valid BIST closes. See `docs/CALCULATION_METHODS.md`.

## Official universe and calendar

The production universe is sourced from official KAP/Borsa İstanbul material. Ordinary company shares are taken from the supported Pay Market segments; non-equity fund markets are excluded. First-trade dates are enriched from Borsa İstanbul's documented `ilkislem` report discovered via the official data-file catalogue.

The checked-in trading-calendar reference currently covers 2023-2026 and distinguishes `FULL`, `HALF`, and `CLOSED` sessions. Unknown calendar years fail closed instead of being guessed.

## Market-data updates

The Yahoo adapter uses raw, unadjusted OHLC (`auto_adjust=False`) so price and ATR validation remain explicit.

Production updates are incremental:

1. Determine the required BIST sessions.
2. Detect missing sessions per security.
3. Respect ticker-validity periods.
4. Batch securities sharing the same missing date range.
5. Stage all fetched data.
6. Validate the complete staged universe.
7. Commit prices atomically only if every selected security passes.

The Yahoo provider currently batches up to 50 tickers per vendor download by default, materially reducing full-universe call volume compared with one request per security.

## V1 migration safety layer

`migration/legacy/` contains the archived V1 reference material used for audit only. V1 daily returns are never reverse-engineered into V2 OHLCV.

The archived regression snapshot currently verifies:

- 594 V1 detail JSON files checked
- 594/594 V1 Excel ↔ published JSON Momentum/FIP matches
- 0 legacy regression failures
- published V1 anchor date: 2026-09-21

Run the audit with:

```bash
python run.py legacy-report \
  --legacy-detail-dir migration/legacy/json \
  --legacy-excel migration/legacy/excel/Claude_Momentum_Screener_BIST_Labyrinth.xlsx \
  --as-of 2026-09-21
```

## Local setup

Python 3.12 is the reference runtime used by CI.

```bash
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS / Linux
# source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
```

Initialize a local database if needed:

```bash
python run.py init
```

## Safe live-source preflight

Preflight checks the official universe plus a small Yahoo sample without mutating the canonical database or public output:

```bash
python run.py preflight \
  --as-of 2026-09-21 \
  --tickers A1CAP,ASELS,THYAO
```

Use the most recently **completed** BIST trading day when running during market hours.

## Dry-run

A ticker subset is intentionally restricted to dry-run mode:

```bash
python run.py dry-run \
  --as-of 2026-09-21 \
  --official-universe \
  --tickers A1CAP,ASELS,THYAO
```

Dry-run output is written outside the public `docs/data` path and the canonical SQLite database is not mutated.

## Full production run

```bash
python run.py daily --official-universe
```

The guarded path is:

```text
Official universe
→ calendar sync
→ incremental OHLCV
→ staging validation
→ atomic SQLite commit
→ validated calculations
→ staged JSON
→ publication gate
→ docs/data
```

A production run with a partial ticker subset is rejected.

## GitHub Actions

Two workflows are included:

- `.github/workflows/validation.yml` — tests every push and pull request.
- `.github/workflows/daily_update.yml` — weekday production update at 20:15 `Europe/Istanbul`, plus manual `workflow_dispatch`.

The production workflow runs tests and live preflight first, then executes the full official-universe pipeline, rebuilds the legacy audit, verifies the publication manifest, and only then commits the canonical database plus generated output.

See `docs/REPOSITORY_SETUP.md` before the first push.

## Repository layout

```text
.github/workflows/        CI and production automation
data/reference/           verified BIST calendar reference
src/calculation/          calculation engine
src/data/                 universe, calendar, providers, storage
src/indicators/           Momentum, FIP, ATR, acceleration
src/output/               JSON generation and publication gate
src/pipeline/             preflight, incremental and daily orchestration
src/reporting/            V1/V2 audit reporting
src/validation/           quality and regression rules
tests/                    unit/integration tests
migration/legacy/         immutable V1 audit material
migration/reports/        machine-readable validation reports
docs/                     methodology and generated public data
run.py                    CLI entry point
```

## Documentation

- `docs/CALCULATION_METHODS.md`
- `docs/TRADING_CALENDAR_AND_DATA_QUALITY.md`
- `docs/INCREMENTAL_UPDATE_PIPELINE.md`
- `docs/END_TO_END_DAILY_PIPELINE.md`
- `docs/PRODUCTION_AUTOMATION.md`
- `docs/LIVE_VALIDATION.md`
- `docs/LEGACY_REGRESSION.md`
- `docs/REPOSITORY_SETUP.md`
- `docs/RELEASE_CHECKLIST.md`

## Important publication note

`docs/data` is generated data output. A full V2 web frontend/`docs/index.html` is intentionally not enabled in this repository-ready milestone. GitHub Pages should be enabled only after the V2 frontend is added and its data contract is validated.
