from __future__ import annotations

from datetime import date
from io import BytesIO
import json
import zipfile

import pytest
from openpyxl import Workbook

from src.data.storage.database import Database
from src.data.universe.manager import UniverseManager, UniverseRecord
from src.data.universe.official import (
    BIST_DATA_PATHS_URL,
    BIST_VIOP_UNDERLYINGS_URL,
    KAP_MARKETS_URL,
    KAP_SECTORS_URL,
    OfficialUniverseError,
    discover_ilkislem_url,
    fetch_official_universe,
    guard_universe_change,
    parse_first_trade_zip,
    parse_kap_markets_html,
    parse_viop_underlyings_html,
)


def kap_html(rows):
    pieces = ["<table><tr><td>PAY PİYASASI</td></tr>", "<tr><td>YILDIZ PAZAR 2 Şirket / Fon Bulundu</td></tr>"]
    for i, (ticker, name) in enumerate(rows, 1):
        pieces.append(f"<tr><td>{i}</td><td>{ticker}</td><td>{name}</td></tr>")
    pieces += [
        "<tr><td>YAPILANDIRILMIŞ ÜRÜNLER VE FON PAZARI</td></tr>",
        "<tr><td>1</td><td>ETF1</td><td>Example ETF</td></tr>",
        "</table>",
    ]
    return "".join(pieces)


def zip_bytes(files: dict[str, bytes]) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


def first_trade_zip(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["İlk Kod", "Cari Kod", "Cari Ünvan", "Pazar Açılış Tarihi", "İlk İşlem Günü", "Kapanış"])
    for ticker, name, dt in rows:
        ws.append([ticker, ticker, name, dt, dt, 10.0])
    buf = BytesIO()
    wb.save(buf)
    wb.close()
    return zip_bytes({"ilkislem.xlsx": buf.getvalue()})



def viop_html(tickers):
    members = list(dict.fromkeys(tickers))
    padding_index = 0
    while len(members) < 20:
        candidate = f"V{padding_index:03d}"
        padding_index += 1
        if candidate not in members:
            members.append(candidate)

    rows = [
        "<table>",
        "<tr><th>Pay Senetleri</th><th>Kod/Açıklama</th></tr>",
    ]
    for ticker in members:
        rows.append(f"<tr><td>{ticker} Company</td><td>{ticker}</td></tr>")
    rows += [
        "<tr><th>Endeks</th><th>Kod/Açıklama</th></tr>",
        "<tr><td>BIST 30</td><td>XU030D</td></tr>",
        "</table>",
    ]
    return "".join(rows)



def simple_sector_html(tickers):
    """Minimal KAP Next.js sector payload for current tickers."""

    companies = [
        {
            "stockCode": ticker,
            "title": f"{ticker} Company",
        }
        for ticker in tickers
    ]

    data = [
        {
            "title": "TEST SECTOR",
            "children": {
                "test-industry": {
                    "title": "TEST INDUSTRY",
                    "children": None,
                    "content": companies,
                }
            },
            "content": [
                {"stockCode": ticker}
                for ticker in tickers
            ],
        }
    ]

    payload = (
        '14:["$","div",null,{"sectorTitles":[],'
        '"bistSectorsTable":{},'
        '"data":'
        + json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "}]"
    )

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
    )

    return (
        "<html><body><script>"
        f"self.__next_f.push([1,{encoded}])"
        "</script></body></html>"
    ).encode("utf-8")

def test_kap_parser_keeps_company_share_markets_and_excludes_fund_market():
    rows = parse_kap_markets_html(kap_html([("AAA", "Alpha A.Ş."), ("BBB", "Beta A.Ş.")]))
    assert [r.ticker for r in rows] == ["AAA", "BBB"]


def test_catalog_discovers_ilkislem_url_from_relative_path():
    catalog = zip_bytes({"paths.csv": b"FirstTrade;/downloads/ilkislem.zip\n"})
    url = discover_ilkislem_url(catalog)
    assert url == "https://www.borsaistanbul.com/downloads/ilkislem.zip"


def test_first_trade_zip_parser_uses_current_ticker_and_first_trading_day():
    parsed = parse_first_trade_zip(first_trade_zip([("AAA", "Alpha", "02.01.2024")]))
    assert parsed == {"AAA": "2024-01-02"}


def test_official_source_merges_kap_universe_and_bist_first_trade_metadata():
    html = kap_html([("AAA", "Alpha A.Ş."), ("BBB", "Beta A.Ş.")]).encode()
    catalog = zip_bytes({"paths.txt": b"https://data.example/ilkislem.zip\n"})
    first = first_trade_zip([
        ("AAA", "Alpha A.Ş.", "02.01.2024"),
        ("BBB", "Beta A.Ş.", "03.01.2024"),
    ])
    mapping = {
        KAP_MARKETS_URL: html,
        KAP_SECTORS_URL: simple_sector_html(["AAA", "BBB"]),
        BIST_VIOP_UNDERLYINGS_URL: viop_html(["AAA"]).encode(),
        BIST_DATA_PATHS_URL: catalog,
        "https://data.example/ilkislem.zip": first,
    }
    snapshot = fetch_official_universe(http_get=mapping.__getitem__, min_equities=2)
    assert snapshot.kap_records == 2
    records = {
        record.ticker: record
        for record in snapshot.records
    }

    assert records["AAA"].sector == "TEST SECTOR"
    assert records["AAA"].industry == "TEST INDUSTRY"
    assert records["BBB"].sector == "TEST SECTOR"
    assert records["BBB"].industry == "TEST INDUSTRY"

    assert {r.ticker: r.first_trade_date for r in snapshot.records} == {
        "AAA": "2024-01-02",
        "BBB": "2024-01-03",
    }


def test_official_source_fails_closed_on_implausibly_small_universe():
    mapping = {
        KAP_MARKETS_URL: kap_html([("AAA", "Alpha")]).encode(),
        BIST_VIOP_UNDERLYINGS_URL: viop_html(["AAA"]).encode(),
    }
    with pytest.raises(OfficialUniverseError, match="unexpectedly small"):
        fetch_official_universe(http_get=mapping.__getitem__, min_equities=2)


def test_universe_shrink_guard_blocks_large_drop(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    db.initialize()
    mgr = UniverseManager(db.conn)
    mgr.sync([UniverseRecord(f"A{i:03d}", f"Company {i}") for i in range(100)], as_of="2026-09-23")
    incoming = [UniverseRecord(f"A{i:03d}", f"Company {i}") for i in range(80)]
    with pytest.raises(OfficialUniverseError, match="Suspicious universe shrinkage"):
        guard_universe_change(db.conn, incoming, min_equities=1, max_drop_fraction=0.08)
    db.close()


def test_kap_parser_excludes_girisim_sermayesi_pazari_funds():
    html = """<table>
    <tr><td>YILDIZ PAZAR 1 Şirket / Fon Bulundu</td></tr>
    <tr><td>1</td><td>AAA</td><td>Alpha A.Ş.</td></tr>
    <tr><td>GİRİŞİM SERMAYESİ PAZARI 1 Şirket / Fon Bulundu</td></tr>
    <tr><td>1</td><td>FUND1</td><td>Örnek Girişim Sermayesi Yatırım Fonu</td></tr>
    </table>"""
    rows = parse_kap_markets_html(html)
    assert [r.ticker for r in rows] == ["AAA"]


def test_official_snapshot_reports_market_breakdown():
    html = """<table>
    <tr><td>YILDIZ PAZAR 1 Şirket / Fon Bulundu</td></tr>
    <tr><td>1</td><td>AAA</td><td>Alpha A.Ş.</td></tr>
    <tr><td>ANA PAZAR 1 Şirket / Fon Bulundu</td></tr>
    <tr><td>1</td><td>BBB</td><td>Beta A.Ş.</td></tr>
    </table>""".encode()
    catalog = zip_bytes({"paths.txt": b"https://data.example/ilkislem.zip\n"})
    first = first_trade_zip([("AAA", "Alpha A.Ş.", "02.01.2024"), ("BBB", "Beta A.Ş.", "03.01.2024")])
    mapping = {
        KAP_MARKETS_URL: html,
        KAP_SECTORS_URL: simple_sector_html(["AAA", "BBB"]),
        BIST_DATA_PATHS_URL: catalog,
        BIST_VIOP_UNDERLYINGS_URL: viop_html(["AAA"]).encode(),
        "https://data.example/ilkislem.zip": first,
    }
    snapshot = fetch_official_universe(http_get=mapping.__getitem__, min_equities=2)
    assert snapshot.market_counts == {"YILDIZ PAZAR": 1, "ANA PAZAR": 1}



def test_viop_parser_keeps_only_pay_senetleri():
    html = """
    <table>
      <tr><th>Pay Senetleri</th><th>Kod/Açıklama</th></tr>
      <tr><td>Alpha A.Ş.</td><td>AAA</td></tr>
      <tr><td>Beta A.Ş.</td><td>BBB</td></tr>

      <tr><th>Endeks</th><th>Kod/Açıklama</th></tr>
      <tr><td>BIST 30 Fiyat Endeksi</td><td>XU030D</td></tr>

      <tr><th>Döviz</th><th>Kod/Açıklama</th></tr>
      <tr><td>Türk Lirası / ABD Doları</td><td>USDTRY</td></tr>
    </table>
    """

    parsed = parse_viop_underlyings_html(
        html,
        min_underlyings=1,
        max_underlyings=10,
    )

    assert parsed == {"AAA", "BBB"}
    assert "XU030D" not in parsed
    assert "USDTRY" not in parsed


def test_viop_parser_fails_closed_without_pay_senetleri():
    html = """
    <table>
      <tr><th>Endeks</th><th>Kod/Açıklama</th></tr>
      <tr><td>BIST 30</td><td>XU030D</td></tr>
    </table>
    """

    with pytest.raises(
        OfficialUniverseError,
        match="Pay Senetleri",
    ):
        parse_viop_underlyings_html(
            html,
            min_underlyings=1,
            max_underlyings=10,
        )


def test_viop_parser_fails_closed_on_implausibly_small_result():
    html = """
    <table>
      <tr><th>Pay Senetleri</th><th>Kod/Açıklama</th></tr>
      <tr><td>Alpha A.Ş.</td><td>AAA</td></tr>
      <tr><th>Endeks</th><th>Kod/Açıklama</th></tr>
    </table>
    """

    with pytest.raises(
        OfficialUniverseError,
        match="outside safety bounds",
    ):
        parse_viop_underlyings_html(html)



def test_official_snapshot_enriches_viop_membership():
    html = kap_html([
        ("AAA", "Alpha A.Ş."),
        ("BBB", "Beta A.Ş."),
    ]).encode()

    catalog = zip_bytes({
        "paths.txt": b"https://data.example/ilkislem.zip\n"
    })

    first = first_trade_zip([
        ("AAA", "Alpha A.Ş.", "02.01.2024"),
        ("BBB", "Beta A.Ş.", "03.01.2024"),
    ])

    mapping = {
        KAP_MARKETS_URL: html,
        KAP_SECTORS_URL: simple_sector_html(["AAA", "BBB"]),
        BIST_DATA_PATHS_URL: catalog,
        BIST_VIOP_UNDERLYINGS_URL: viop_html(["BBB"]).encode(),
        "https://data.example/ilkislem.zip": first,
    }

    snapshot = fetch_official_universe(
        http_get=mapping.__getitem__,
        min_equities=2,
    )

    records = {record.ticker: record for record in snapshot.records}

    assert records["AAA"].is_viop == 0
    assert records["BBB"].is_viop == 1

    assert records["AAA"].viop_source == "BIST_VIOP_UNDERLYINGS"
    assert records["BBB"].viop_source == "BIST_VIOP_UNDERLYINGS"

    assert records["AAA"].viop_as_of == snapshot.source_date
    assert records["BBB"].viop_as_of == snapshot.source_date
