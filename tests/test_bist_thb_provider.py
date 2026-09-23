from __future__ import annotations

from datetime import date
from io import BytesIO
from zipfile import ZipFile

from src.data.providers.bist_thb import BISTTHBProvider


def _bulletin(day: str, ticker: str, o: str, low: str, high: str, close: str, volume: str) -> bytes:
    csv_text = (
        "TARIH;ISLEM  KODU;ACILIS FIYATI;EN DUSUK FIYAT;"
        "EN YUKSEK FIYAT;KAPANIS FIYATI;TOPLAM ISLEM ADEDI\n"
        "TRADE DATE;INSTRUMENT SERIES CODE;OPENING PRICE;LOWEST PRICE;"
        "HIGHEST PRICE;CLOSING PRICE;TOTAL TRADED VOLUME\n"
        f"{day};{ticker}.E;{o};{low};{high};{close};{volume}\n"
    )

    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(f"thb{day.replace('-', '')}1.csv", csv_text.encode("utf-8"))
    return buffer.getvalue()


def test_atatr_official_bulletin_recovery():
    payloads = {
        "https://www.borsaistanbul.com/data/thb/2026/02/thb202602191.zip":
            _bulletin("2026-02-19", "ATATR", "12.32", "12.32", "12.32", "12.32", "2365275"),
        "https://www.borsaistanbul.com/data/thb/2026/02/thb202602201.zip":
            _bulletin("2026-02-20", "ATATR", "13.55", "13.55", "13.55", "13.55", "2368514"),
    }

    calls = []

    def http_get(url: str) -> bytes:
        calls.append(url)
        return payloads[url]

    provider = BISTTHBProvider(http_get=http_get)

    bars = provider.fetch(
        "ATATR",
        date(2026, 2, 19),
        date(2026, 2, 20),
    )

    assert len(bars) == 2

    assert bars[0].date == date(2026, 2, 19)
    assert bars[0].open == 12.32
    assert bars[0].high == 12.32
    assert bars[0].low == 12.32
    assert bars[0].close == 12.32
    assert bars[0].volume == 2365275

    assert bars[1].date == date(2026, 2, 20)
    assert bars[1].open == 13.55
    assert bars[1].high == 13.55
    assert bars[1].low == 13.55
    assert bars[1].close == 13.55
    assert bars[1].volume == 2368514

    assert calls == [
        "https://www.borsaistanbul.com/data/thb/2026/02/thb202602191.zip",
        "https://www.borsaistanbul.com/data/thb/2026/02/thb202602201.zip",
    ]


def test_unknown_ticker_returns_no_bar():
    payload = _bulletin(
        "2026-02-19",
        "ATATR",
        "12.32",
        "12.32",
        "12.32",
        "12.32",
        "2365275",
    )

    provider = BISTTHBProvider(http_get=lambda _: payload)

    bars = provider.fetch(
        "OTHER",
        date(2026, 2, 19),
        date(2026, 2, 19),
    )

    assert bars == []


def test_blank_official_ohlc_is_not_fabricated():
    payload = _bulletin(
        "2026-02-19",
        "ATATR",
        "",
        "",
        "",
        "",
        "0",
    )

    provider = BISTTHBProvider(http_get=lambda _: payload)

    bars = provider.fetch(
        "ATATR",
        date(2026, 2, 19),
        date(2026, 2, 19),
    )

    assert bars == []
