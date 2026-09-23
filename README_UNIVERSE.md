# BIST Universe Manager

The universe layer treats BIST as the authoritative source for instrument identity and status, while market-data providers supply OHLCV only.

## Design rules
- Equity universe is selected with `instrument_type = 'EQUITY'`.
- ETF/BYF and other Pay Piyasası instruments are retained separately but are not included in the momentum screener.
- Ticker changes create a new identifier interval under the same `security_id`.
- Historical prices remain attached to `security_id`; historical ticker is stored in `daily_prices.ticker_at_date`.
- Missing from a current snapshot means `active=0`, not automatically `DELISTED`.
- No fabricated history for IPOs.
