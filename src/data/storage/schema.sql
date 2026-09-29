PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS securities (
    security_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    sector TEXT,
    industry TEXT,
    is_viop INTEGER NOT NULL DEFAULT 0 CHECK (is_viop IN (0,1)),
    viop_source TEXT,
    viop_as_of TEXT,
    instrument_type TEXT NOT NULL DEFAULT 'EQUITY',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    first_trade_date TEXT,
    last_trade_date TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS security_identifiers (
    identifier_id INTEGER PRIMARY KEY,
    security_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)),
    source TEXT,
    FOREIGN KEY (security_id) REFERENCES securities(security_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_current_ticker
ON security_identifiers(ticker) WHERE is_current = 1;
CREATE INDEX IF NOT EXISTS idx_identifiers_ticker ON security_identifiers(ticker);
CREATE INDEX IF NOT EXISTS idx_identifiers_validity ON security_identifiers(security_id, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS ticker_history (
    id INTEGER PRIMARY KEY,
    security_id INTEGER NOT NULL,
    old_ticker TEXT,
    new_ticker TEXT,
    effective_date TEXT NOT NULL,
    reason TEXT,
    source TEXT,
    FOREIGN KEY (security_id) REFERENCES securities(security_id)
);

CREATE TABLE IF NOT EXISTS daily_prices (
    security_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    ticker_at_date TEXT,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (security_id, date),
    FOREIGN KEY (security_id) REFERENCES securities(security_id),
    CHECK (open IS NULL OR open >= 0),
    CHECK (high IS NULL OR high >= 0),
    CHECK (low IS NULL OR low >= 0),
    CHECK (close IS NULL OR close >= 0),
    CHECK (volume IS NULL OR volume >= 0)
);
CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(date);
CREATE INDEX IF NOT EXISTS idx_daily_prices_security_date ON daily_prices(security_id, date);

CREATE TABLE IF NOT EXISTS price_adjustments (
    security_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    adj_close REAL,
    adjustment_factor REAL,
    dividend REAL,
    stock_split REAL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (security_id, date),
    FOREIGN KEY (security_id) REFERENCES securities(security_id),
    CHECK (adj_close IS NULL OR adj_close >= 0),
    CHECK (adjustment_factor IS NULL OR adjustment_factor > 0),
    CHECK (dividend IS NULL OR dividend >= 0),
    CHECK (stock_split IS NULL OR stock_split >= 0)
);

CREATE INDEX IF NOT EXISTS idx_price_adjustments_date
ON price_adjustments(date);

CREATE INDEX IF NOT EXISTS idx_price_adjustments_security_date
ON price_adjustments(security_id, date);

-- Market indices are intentionally stored separately from equity securities.
-- They have their own lifecycle and must not participate in the equity universe.

CREATE TABLE IF NOT EXISTS market_indices (
    index_code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS index_daily_prices (
    index_code TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (index_code, date),
    FOREIGN KEY (index_code) REFERENCES market_indices(index_code),
    CHECK (open IS NULL OR open >= 0),
    CHECK (high IS NULL OR high >= 0),
    CHECK (low IS NULL OR low >= 0),
    CHECK (close IS NULL OR close >= 0),
    CHECK (volume IS NULL OR volume >= 0)
);

CREATE INDEX IF NOT EXISTS idx_index_daily_prices_date
ON index_daily_prices(date);

CREATE INDEX IF NOT EXISTS idx_index_daily_prices_code_date
ON index_daily_prices(index_code, date);

CREATE TABLE IF NOT EXISTS trading_days (
    date TEXT PRIMARY KEY,
    is_trading_day INTEGER NOT NULL CHECK (is_trading_day IN (0,1)),
    session_type TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS data_sources (
    source_id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL UNIQUE,
    source_type TEXT,
    url TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    securities_checked INTEGER DEFAULT 0,
    prices_inserted INTEGER DEFAULT 0,
    prices_updated INTEGER DEFAULT 0,
    fetched_bars INTEGER DEFAULT 0,
    provider_calls INTEGER DEFAULT 0,
    validation_status TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS security_data_status (
    run_id INTEGER NOT NULL,
    security_id INTEGER NOT NULL,
    as_of_date TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('OK', 'PROVIDER_UNAVAILABLE', 'INSUFFICIENT_TRADING_DATA')),
    message TEXT,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (run_id, security_id),
    FOREIGN KEY (run_id) REFERENCES pipeline_runs(run_id),
    FOREIGN KEY (security_id) REFERENCES securities(security_id)
);
CREATE INDEX IF NOT EXISTS idx_security_data_status_security_date
ON security_data_status(security_id, as_of_date);

-- Legacy V1 audit layer.
-- V1 Excel/JSON contain daily returns, not OHLCV. Never reverse-engineer prices
-- from these returns; preserve them separately for migration and regression tests.
CREATE TABLE IF NOT EXISTS legacy_daily_returns (
    security_id INTEGER,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    return_decimal REAL NOT NULL,
    source_file TEXT NOT NULL,
    source_type TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    PRIMARY KEY (ticker, date, source_type),
    FOREIGN KEY (security_id) REFERENCES securities(security_id)
);
CREATE INDEX IF NOT EXISTS idx_legacy_returns_security_date
ON legacy_daily_returns(security_id, date);
CREATE INDEX IF NOT EXISTS idx_legacy_returns_ticker_date
ON legacy_daily_returns(ticker, date);

CREATE TABLE IF NOT EXISTS legacy_indicator_snapshots (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    as_of_date TEXT,
    momentum REAL,
    fip REAL,
    source_file TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_legacy_indicator_ticker_date
ON legacy_indicator_snapshots(ticker, as_of_date);
