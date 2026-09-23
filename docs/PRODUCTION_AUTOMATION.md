# Production automation

## Official-source universe

Production can be invoked with:

```bash
python run.py daily --official-universe
```

The universe layer is fail-closed and uses two official-source paths:

1. KAP `Pazarlar` for the current Pay Market company/ticker set. Borsa Istanbul's
   listed-companies page links to KAP for full company information.
2. Borsa Istanbul `DataFilePaths.zip` to discover the current location of the
   documented `ilkislem.zip -> ilkislem.xlsx` report. That report enriches each
   current ticker with its first trading day.

Company-share markets are included explicitly; the Structured Products and Fund
Market is excluded so ETFs/funds do not enter the equity screener.

Before sync, a universe guard blocks implausible source shrinkage. The absolute
number of BIST equities is not hard-coded; the floor only protects against an
obviously broken upstream response, while the relative-drop guard compares the
new snapshot with the canonical DB.

## Daily GitHub Action

`.github/workflows/daily_update.yml` runs on weekdays at 20:15 using the explicit
`Europe/Istanbul` IANA timezone and can also be started manually. It performs:

1. tests,
2. official universe acquisition,
3. trading-calendar sync,
4. incremental/batched Yahoo OHLCV update,
5. data-quality validation,
6. indicator calculation,
7. full-universe publication staging,
8. publication gate verification,
9. commit of the canonical SQLite DB and derived `docs/data` output.

A failed source, provider, validation, calculation, or publication check stops the
workflow before the public output is promoted or committed.

## V1/V2 comparison

```bash
python run.py legacy-report \
  --legacy-detail-dir migration/legacy/json \
  --legacy-report-out migration/reports/v1_v2_comparison.json
```

The report has two distinct purposes:

- **V1 internal regression:** reconstruct V1's legacy 12-1 calendar-month
  Momentum/FIP from its own daily returns and verify that the top-level V1 values
  are reproduced. This is a PASS/FAIL check.
- **V1 vs V2 observation:** show V1 values next to V2 fixed-252-trading-day values.
  These are different methodologies, so their difference is descriptive and is
  deliberately **not** a PASS/FAIL criterion.
