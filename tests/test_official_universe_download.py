"""Offline regressions for the live BIST catalogue and invalid HTTP payloads."""
from io import BytesIO
from email.message import Message

import pytest
from openpyxl import Workbook

from src.data.universe import official as o
from test_official_universe import zip_bytes, first_trade_zip, kap_html


def catalogue_with_metadata():
    workbook = Workbook()
    workbook.active.append(["First Trading Date", "/datum/", "ilkislem.zip"])
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return zip_bytes({
        # Deliberately first: AppleDouble is not an XLSX despite its suffix.
        "__MACOSX/._VerilerDosyaIsimleri.xlsx": b"\x00\x05\x16\x07AppleDouble",
        "._other.xlsx": b"metadata",
        "VerilerDosyaIsimleri.xlsx": buffer.getvalue(),
    })


def test_live_catalogue_shape_ignores_appledouble_and_joins_directory():
    assert o.discover_ilkislem_url(catalogue_with_metadata()) == (
        "https://www.borsaistanbul.com/datum/ilkislem.zip"
    )


def test_bare_filename_does_not_invent_files_directory():
    with pytest.raises(o.OfficialUniverseError, match="does not expose"):
        o.discover_ilkislem_url(zip_bytes({"paths.txt": b"ilkislem.zip"}))


def test_report_ignores_appledouble_before_real_workbook():
    import zipfile
    report = first_trade_zip([("AAA", "Alpha", "02.01.2024")])
    with zipfile.ZipFile(BytesIO(report)) as archive:
        data = archive.read("ilkislem.xlsx")
    assert o.parse_first_trade_zip(zip_bytes({
        "__MACOSX/._ilkislem.xlsx": b"metadata", "ilkislem.xlsx": data,
    })) == {"AAA": "2024-01-02"}


@pytest.mark.parametrize("bad", [b"<html>Not found</html>", b"", b"PK\x03\x04broken", b'{"error":1}'])
def test_invalid_catalogue_uses_official_page_fallback(bad):
    url = "https://www.borsaistanbul.com/datum/ilkislem.zip"
    mapping = {
        o.KAP_MARKETS_URL: kap_html([("AAA", "Alpha")]).encode(),
        o.BIST_DATA_PATHS_URL: bad,
        o.BIST_EQUITY_DATA_URL: b'<button dosya-yolu="/datum/ilkislem.zip"></button>',
        url: first_trade_zip([("AAA", "Alpha", "02.01.2024")]),
    }
    snapshot = o.fetch_official_universe(http_get=mapping.__getitem__, min_equities=1)
    assert snapshot.first_trade_url == url
    assert snapshot.records[0].first_trade_date == "2024-01-02"


def test_invalid_report_uses_different_official_page_link():
    old = "https://www.borsaistanbul.com/old/ilkislem.zip"
    new = "https://www.borsaistanbul.com/datum/ilkislem.zip"
    mapping = {
        o.BIST_DATA_PATHS_URL: zip_bytes({"paths.txt": old.encode()}),
        old: b"<html>Not found</html>",
        o.BIST_EQUITY_DATA_URL: b'<a href="/datum/ilkislem.zip">Report</a>',
        new: first_trade_zip([("AAA", "Alpha", "02.01.2024")]),
    }
    assert o._fetch_first_trade(mapping.__getitem__, o.BIST_DATA_PATHS_URL)[1] == new


@pytest.mark.parametrize("link", ["https://evil.example/ilkislem.zip", "http://www.borsaistanbul.com/ilkislem.zip", "https://www.borsaistanbul.com.evil.example/ilkislem.zip", "https://user@www.borsaistanbul.com/ilkislem.zip"])
def test_fallback_rejects_untrusted_links(link):
    with pytest.raises(o.OfficialUniverseError, match="no trusted"):
        o._discover_report_from_page(f'<a href="{link}">Report</a>'.encode())


def test_both_sources_fail_closed_with_context():
    mapping = {
        o.KAP_MARKETS_URL: kap_html([("AAA", "Alpha")]).encode(),
        o.BIST_DATA_PATHS_URL: b"<html>error</html>",
        o.BIST_EQUITY_DATA_URL: b"<html>error</html>",
    }
    with pytest.raises(o.OfficialUniverseError) as error:
        o.fetch_official_universe(http_get=mapping.__getitem__, min_equities=1)
    assert o.BIST_DATA_PATHS_URL in str(error.value)
    assert o.BIST_EQUITY_DATA_URL in str(error.value)
    assert "Invalid ZIP" in str(error.value)


@pytest.mark.parametrize("mime,payload,valid", [
    ("text/html", b"<html>blocked</html>", False),
    ("application/zip", b"<html>blocked</html>", False),
    ("text/html", zip_bytes({"a.txt": b"x"}), False),
    ("application/zip", b"PK\x03\x04broken", False),
    ("application/zip", zip_bytes({"a.txt": b"x"}), True),
    ("application/octet-stream", zip_bytes({"a.txt": b"x"}), True),
    ("", zip_bytes({"a.txt": b"x"}), True),
])
def test_http_validates_mime_and_real_zip(monkeypatch, mime, payload, valid):
    class Response(BytesIO):
        headers = Message()
        def geturl(self):
            return o.BIST_DATA_PATHS_URL
    response = Response(payload)
    response.headers["Content-Type"] = mime
    monkeypatch.setattr(o.urllib.request, "urlopen", lambda *a, **kw: response)
    if valid:
        assert o.default_http_get(o.BIST_DATA_PATHS_URL) == payload
    else:
        with pytest.raises(o.OfficialUniverseError, match="Invalid ZIP.*content-type=.*magic="):
            o.default_http_get(o.BIST_DATA_PATHS_URL)


@pytest.mark.parametrize("xlsx", [True, False])
def test_bist_equity_suffix_is_normalized_but_funds_are_excluded(xlsx):
    rows = [("AAA.E", "Alpha", "02.01.2024"), ("ETF1.F", "Fund", "03.01.2024")]
    if xlsx:
        data = first_trade_zip(rows)
    else:
        data = zip_bytes({"ilkislem.csv": b"AAA.E;AAA.E;Alpha;01.01.2024;02.01.2024\nETF1.F;ETF1.F;Fund;01.01.2024;03.01.2024"})
    assert o.parse_first_trade_zip(data) == {"AAA": "2024-01-02"}
