# Live Source Validation — 2026-09-23

The current KAP market page was reviewed against the production universe assumptions.

- Ordinary share universe markets: Yıldız, Ana, Alt, Yakın İzleme, Piyasa Öncesi İşlem Platformu.
- Observed counts: 278 + 267 + 49 + 18 + 19 = **631** EQUITY records.
- `GİRİŞİM SERMAYESİ PAZARI` is intentionally excluded from `EQUITY_MARKETS`: the current KAP page lists 31 investment-fund records there.
- A1CAP, ASELS and THYAO were confirmed in the current official KAP share universe.
- Borsa İstanbul documentation confirms `ilkislem.zip -> ilkislem.xlsx` as the first-trading-date/current-code report used for listing metadata.

## Runtime preflight

Use:

```bash
python run.py preflight --as-of 2026-09-21 --tickers A1CAP,ASELS,THYAO
```

The command does not mutate SQLite or `docs/data`. It checks the official universe, sample-ticker membership, Yahoo OHLCV structure and provider freshness. The production GitHub Actions workflow runs this step before the full daily pipeline.

In the current build environment the command correctly failed closed because external DNS is unavailable. This is recorded as an environment limitation, not a passing live Yahoo test.
