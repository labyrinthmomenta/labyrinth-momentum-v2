# End-to-End Daily Pipeline

Labyrinth Momentum V2 now exposes one guarded daily path:

`Universe sync (optional authoritative snapshot) -> BIST calendar sync -> incremental OHLCV update -> data-quality gate -> validated calculations -> staged JSON -> publication gate`

## Safety rules

1. **Partial ticker runs are dry-run only.** A subset can never replace `docs/data`.
2. **Dry-run never mutates the canonical SQLite database.** It uses SQLite backup into a temporary working database.
3. **All active EQUITY securities must pass before publication.** One provider/data/calculation failure prevents promotion.
4. **JSON is derived output, never canonical data.** It is built into an isolated stage directory first.
5. **Public output promotion is rollback-safe.** The previous `docs/data` directory is kept until the validated stage has been moved into place.
6. **IPO lookback is listing-aware.** Pre-listing BIST sessions are not treated as missing; unavailable 252/126/63 windows remain `null`.
7. **Universe sync must be authoritative.** Do not feed a 3–5 ticker sample to `UniverseManager.sync`, because absence from that snapshot intentionally marks existing equities inactive. Use the ticker filter in dry-run instead.

## Output layout

```text
docs/data/
  manifest.json
  screener.json
  details/
    A1CAP.json
    ...
```

Each detail file contains security metadata, the current indicator snapshot, and the recent canonical close/volume/daily-return series used by the calculation layer.

## Production versus dry-run

Production publication is full-universe only. Dry-run can target a small ticker set and writes derived output to a non-public directory such as `migration/dry_runs/...` while leaving the canonical DB and `docs/data` unchanged.
