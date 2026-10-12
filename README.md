# Labyrinth Momentum V2

Labyrinth Momentum V2 is the next-generation BIST momentum screener architecture. It replaces the V1 Excel-centric calculation flow with a canonical SQLite/OHLCV data model, explicit validation gates, reproducible indicator calculations, and guarded GitHub Actions automation.

> **Status:** production-ready V2 decision-support release. V1 remains untouched and is retained only as an immutable migration/regression reference.

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


## Cross-sectional ranking

Production publication includes descriptive cross-sectional percentile ranks.

The ranking layer does **not** create autonomous Long/Short, Buy/Sell, or execution decisions.

Published ranking context includes:

- Core momentum percentile across the full eligible BIST equity universe
- Core momentum percentile within the VIOP subset
- FIP-based momentum-quality percentile
- 126 / 63 / 21-session momentum percentiles
- 21-vs-63 and 63-vs-126 acceleration context
- 63-session sector-relative momentum context

The full-universe ranking is calculated only when the complete active equity universe is available. Partial dry-run subsets do not receive misleading production ranks.

`core_ready` means that the required published momentum/FIP inputs are available for descriptive ranking. It does **not** mean that the security is trade-ready.

## Trader View

Trader View is a read-only presentation layer over the published production artifacts.

It does not fetch market data, update SQLite, recompute indicators, modify rankings, or publish new JSON.

Default full-universe view:

```bash
python run.py trader-view
```

Show a different number of names:

```bash
python run.py trader-view --top 15
```

VIOP-only view:

```bash
python run.py trader-view --viop --top 15
```

Trader View requires:

- production manifest status `PASS`
- `dry_run = false`
- screener and manifest `as_of` consistency
- `data_status = OK`
- `ranking_status = OK`
- `core_ready = true`

If these publication-contract conditions are not met, Trader View fails closed.

The `STRONG MOMENTUM` and `WEAK MOMENTUM` sections are descriptive ends of the published momentum-ranking distribution. They are **not** Buy/Sell or Long/Short signals.

Key columns:

- `Mom%` — published core momentum percentile
- `FIP-Q%` — published FIP-based momentum-quality percentile
- `M126%` — 126-session momentum percentile
- `M63%` — 63-session momentum percentile
- `M21%` — 21-session momentum percentile
- `FIP12-1` — published 12-1 FIP value
- `VCP` — production VCP status/state when available

With `--viop`, VIOP-specific published percentile fields are used.

## VCP production boundary

VCP is structurally integrated into the publication contract but remains independent from the production momentum ranking.

VCP does not increase, decrease, or otherwise alter the published momentum rank.

When no explicit production VCP configuration is supplied, VCP is published as `NOT_AVAILABLE` / `N/A` rather than silently applying research thresholds.

Research-only VCP quality scores, shadow-selection fields, prospective OOS outcomes, forward returns, benchmark-relative returns, MFE/MAE, and similar outcome variables are prohibited from leaking into production publication.

## Prospective OOS research boundary

Prospective VCP validation is intentionally separated from production ranking.

The repository contains write-once prospective snapshots and sealed shadow selections. OOS results must not be evaluated before their pre-registered maturity horizon.

Research findings do not automatically change production defaults. They must pass the explicit production-integration boundary before affecting published behavior.

## Intended use

Labyrinth Momentum V2 is a decision-support screener for discretionary swing-trading research.

Typical workflow:

1. Complete the production update after the most recently completed BIST session.
2. Confirm manifest and data-quality status.
3. Review the full-universe Trader View.
4. Review the VIOP-specific Trader View when selecting futures candidates.
5. Use momentum rank, FIP quality, shorter-horizon momentum, acceleration, sector context, VCP context, and market regime as separate descriptive inputs.
6. Perform chart review, entry planning, stop placement, position sizing, execution, and trade management outside the screener.

The system intentionally does **not**:

- place orders
- size positions
- choose entries or stops
- manage open trades
- issue autonomous Buy/Sell or Long/Short signals
- convert research/OOS outcomes directly into production rules

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
src/reporting/            audit reporting and read-only Trader View
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

`docs/data` is generated production data output. The supported human-facing decision-support interface for this release is the read-only CLI Trader View. A web frontend/`docs/index.html` is not part of the frozen V2 production release unless it is separately reviewed, validated, and committed.
