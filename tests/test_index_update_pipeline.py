from datetime import date
from pathlib import Path
import sqlite3

import pytest

from src.calculation.engine import PriceBar
from src.pipeline.index_update import update_market_indices


SCHEMA = Path(
    "src/data/storage/schema.sql"
)


def make_conn():
    conn = sqlite3.connect(":memory:")

    conn.executescript(
        SCHEMA.read_text()
    )

    return conn


def bar(
    value_date,
    close,
):
    return PriceBar(
        date=value_date,
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=1000.0,
    )


class FakeProvider:
    source_name = "TEST_PROVIDER"

    def __init__(
        self,
        bars_by_ticker=None,
        fail_on=None,
    ):
        self.bars_by_ticker = (
            bars_by_ticker
            or {}
        )

        self.fail_on = fail_on
        self.calls = []

    def fetch(
        self,
        ticker,
        start,
        end,
    ):
        self.calls.append(
            (
                ticker,
                start,
                end,
            )
        )

        if ticker == self.fail_on:
            raise RuntimeError(
                f"fetch failed for {ticker}"
            )

        return list(
            self.bars_by_ticker.get(
                ticker,
                [],
            )
        )


def test_update_market_indices_populates_core_indices_and_prices():
    conn = make_conn()

    as_of = date(
        2026,
        7,
        1,
    )

    provider = FakeProvider({
        "XU030": [
            bar(
                as_of,
                16660.8,
            )
        ],
        "XU100": [
            bar(
                as_of,
                14350.6,
            )
        ],
    })

    summary = update_market_indices(
        conn,
        provider,
        start=as_of,
        end=as_of,
    )

    assert summary.indices_processed == 2
    assert summary.bars_fetched == 2
    assert summary.inserted == 2
    assert summary.updated == 0

    indices = conn.execute(
        """
        SELECT index_code
        FROM market_indices
        ORDER BY index_code
        """
    ).fetchall()

    assert indices == [
        ("XU030",),
        ("XU100",),
    ]

    prices = conn.execute(
        """
        SELECT
            index_code,
            date,
            close,
            source
        FROM index_daily_prices
        ORDER BY index_code
        """
    ).fetchall()

    assert prices == [
        (
            "XU030",
            "2026-07-01",
            pytest.approx(
                16660.8
            ),
            "TEST_PROVIDER",
        ),
        (
            "XU100",
            "2026-07-01",
            pytest.approx(
                14350.6
            ),
            "TEST_PROVIDER",
        ),
    ]

    assert provider.calls == [
        (
            "XU030",
            as_of,
            as_of,
        ),
        (
            "XU100",
            as_of,
            as_of,
        ),
    ]


def test_update_market_indices_is_idempotent():
    conn = make_conn()

    as_of = date(
        2026,
        7,
        1,
    )

    provider = FakeProvider({
        "XU030": [
            bar(
                as_of,
                16660.8,
            )
        ],
        "XU100": [
            bar(
                as_of,
                14350.6,
            )
        ],
    })

    first = update_market_indices(
        conn,
        provider,
        start=as_of,
        end=as_of,
    )

    second = update_market_indices(
        conn,
        provider,
        start=as_of,
        end=as_of,
    )

    assert first.inserted == 2
    assert first.updated == 0

    assert second.inserted == 0
    assert second.updated == 2

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM index_daily_prices
        """
    ).fetchone()[0]

    assert count == 2


def test_update_market_indices_rejects_bar_outside_requested_range():
    conn = make_conn()

    start = date(
        2026,
        7,
        1,
    )

    end = date(
        2026,
        7,
        10,
    )

    provider = FakeProvider({
        "XU030": [
            bar(
                date(
                    2026,
                    6,
                    30,
                ),
                16000.0,
            )
        ],
        "XU100": [],
    })

    with pytest.raises(
        ValueError,
        match="outside requested range",
    ):
        update_market_indices(
            conn,
            provider,
            start=start,
            end=end,
        )

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM index_daily_prices
        """
    ).fetchone()[0]

    assert count == 0


def test_update_market_indices_is_atomic_on_provider_failure():
    conn = make_conn()

    as_of = date(
        2026,
        7,
        1,
    )

    provider = FakeProvider(
        bars_by_ticker={
            "XU030": [
                bar(
                    as_of,
                    16660.8,
                )
            ],
        },
        fail_on="XU100",
    )

    with pytest.raises(
        RuntimeError,
        match="XU100",
    ):
        update_market_indices(
            conn,
            provider,
            start=as_of,
            end=as_of,
        )

    prices = conn.execute(
        """
        SELECT COUNT(*)
        FROM index_daily_prices
        """
    ).fetchone()[0]

    assert prices == 0


def test_update_market_indices_rejects_reversed_range():
    conn = make_conn()

    provider = FakeProvider()

    with pytest.raises(
        ValueError,
        match="start",
    ):
        update_market_indices(
            conn,
            provider,
            start=date(
                2026,
                7,
                2,
            ),
            end=date(
                2026,
                7,
                1,
            ),
        )

    assert provider.calls == []


def test_update_market_indices_rejects_duplicate_dates():
    conn = make_conn()

    as_of = date(
        2026,
        7,
        1,
    )

    provider = FakeProvider({
        "XU030": [
            bar(
                as_of,
                16660.8,
            ),
            bar(
                as_of,
                16661.0,
            ),
        ],
        "XU100": [
            bar(
                as_of,
                14350.6,
            ),
        ],
    })

    with pytest.raises(
        ValueError,
        match="duplicate",
    ):
        update_market_indices(
            conn,
            provider,
            start=as_of,
            end=as_of,
        )

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM index_daily_prices
        """
    ).fetchone()[0]

    assert count == 0


def test_update_market_indices_rejects_invalid_ohlc():
    conn = make_conn()

    as_of = date(
        2026,
        7,
        1,
    )

    invalid_bar = PriceBar(
        date=as_of,
        open=100.0,
        high=99.0,
        low=98.0,
        close=100.0,
        volume=1000.0,
    )

    provider = FakeProvider({
        "XU030": [
            invalid_bar,
        ],
        "XU100": [
            bar(
                as_of,
                14350.6,
            ),
        ],
    })

    with pytest.raises(
        ValueError,
        match="OHLC",
    ):
        update_market_indices(
            conn,
            provider,
            start=as_of,
            end=as_of,
        )

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM index_daily_prices
        """
    ).fetchone()[0]

    assert count == 0


def test_update_market_indices_rejects_nonfinite_ohlc():
    conn = make_conn()

    as_of = date(
        2026,
        7,
        1,
    )

    invalid_bar = PriceBar(
        date=as_of,
        open=100.0,
        high=float("nan"),
        low=98.0,
        close=99.0,
        volume=1000.0,
    )

    provider = FakeProvider({
        "XU030": [
            invalid_bar,
        ],
        "XU100": [
            bar(
                as_of,
                14350.6,
            ),
        ],
    })

    with pytest.raises(
        ValueError,
        match="OHLC",
    ):
        update_market_indices(
            conn,
            provider,
            start=as_of,
            end=as_of,
        )

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM index_daily_prices
        """
    ).fetchone()[0]

    assert count == 0


def test_update_market_indices_rejects_negative_volume():
    conn = make_conn()

    as_of = date(
        2026,
        7,
        1,
    )

    invalid_bar = PriceBar(
        date=as_of,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=-1.0,
    )

    provider = FakeProvider({
        "XU030": [
            invalid_bar,
        ],
        "XU100": [
            bar(
                as_of,
                14350.6,
            ),
        ],
    })

    with pytest.raises(
        ValueError,
        match="volume",
    ):
        update_market_indices(
            conn,
            provider,
            start=as_of,
            end=as_of,
        )

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM index_daily_prices
        """
    ).fetchone()[0]

    assert count == 0
