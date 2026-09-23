from __future__ import annotations

from datetime import date
from io import BytesIO
import zipfile

import pytest
from openpyxl import Workbook

from src.data.storage.database import Database
from src.data.universe.manager import UniverseManager, UniverseRecord
from src.data.universe.official import (
    BIST_DATA_PATHS_URL,
    KAP_MARKETS_URL,
    OfficialUniverseError,
    discover_ilkislem_url,
    fetch_official_universe,
    guard_universe_change,
    parse_first_trade_zip,
    parse_kap_markets_html,
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
        BIST_DATA_PATHS_URL: catalog,
        "https://data.example/ilkislem.zip": first,
    }
    snapshot = fetch_official_universe(http_get=mapping.__getitem__, min_equities=2)
    assert snapshot.kap_records == 2
    assert {r.ticker: r.first_trade_date for r in snapshot.records} == {
        "AAA": "2024-01-02",
        "BBB": "2024-01-03",
    }


def test_official_source_fails_closed_on_implausibly_small_universe():
    mapping = {KAP_MARKETS_URL: kap_html([("AAA", "Alpha")]).encode()}
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
    mapping = {KAP_MARKETS_URL: html, BIST_DATA_PATHS_URL: catalog, "https://data.example/ilkislem.zip": first}
    snapshot = fetch_official_universe(http_get=mapping.__getitem__, min_equities=2)
    assert snapshot.market_counts == {"YILDIZ PAZAR": 1, "ANA PAZAR": 1}
