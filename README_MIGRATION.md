# V1 → V2 Migration

## Principle

V1's `BIST D Return Data` contains daily percentage returns. It does **not** contain enough information to reconstruct reliable OHLCV. V2 therefore never converts V1 returns back into prices.

Instead:

- V1 workbook/JSON files remain immutable legacy evidence.
- Their daily returns are imported into `legacy_daily_returns`.
- Their top-level Momentum/FIP values are imported into `legacy_indicator_snapshots`.
- V2 `daily_prices` is populated only from a real OHLCV provider.
- Migration is idempotent for the same ticker/date/source type.

## Excel layout currently supported

The importer follows the V1 structure documented in the legacy code:

- `BIST D Return Data`: dates on row 3; ticker on column D; daily percentage returns from row 6.
- `MOMENTUM SCREENER`: ticker in column E, type in B, industry in C, name in F.

This is intentionally kept close to the existing V1 implementation rather than silently redesigning the legacy source.

## Important regression note

A1CAP's V1 JSON contains the known snapshot `Momentum = -0.156294` and `FIP = -0.099602`. The migration layer preserves those values exactly as legacy reference values. It does not assume that preserving a V1 number means the V2 formula is correct; the independent V2 calculation must pass its own methodology tests before publication.
