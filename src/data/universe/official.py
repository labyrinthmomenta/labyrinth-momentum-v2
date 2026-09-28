from __future__ import annotations

"""Official-source BIST equity universe acquisition.

Current equity identities come from KAP's market page (linked by Borsa Istanbul's
"İşlem Gören Şirketler" page). First-trade dates are enriched from Borsa
Istanbul's documented ``ilkislem.zip`` report. The hidden report URL is
discovered from Borsa Istanbul's official ``DataFilePaths.zip`` catalogue so
we do not depend on an undocumented static path.

All network/file-format failures are fail-closed: a broken upstream source must
not silently shrink or corrupt the canonical universe.
"""

from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from io import BytesIO
import csv
import io
import json
import re
from pathlib import PurePosixPath
import urllib.parse
import urllib.request
import zipfile
from typing import Callable, Iterable

from openpyxl import load_workbook

from .manager import UniverseRecord, UniverseManager

KAP_MARKETS_URL = "https://www.kap.org.tr/tr/Pazarlar"
KAP_SECTORS_URL = "https://www.kap.org.tr/tr/Sektorler"
BIST_DATA_PATHS_URL = "https://www.borsaistanbul.com/files/DataFilePaths.zip"
BIST_EQUITY_DATA_URL = "https://www.borsaistanbul.com/en/data/equity-market-data"
BIST_VIOP_UNDERLYINGS_URL = "https://www.borsaistanbul.com/piyasalar/viop/sozlesme-ozellikleri/dayanak-varliklar"

# Company-share markets. Instrument/fund-only markets are intentionally omitted.
EQUITY_MARKETS = {
    "YILDIZ PAZAR",
    "ANA PAZAR",
    "ALT PAZAR",
    "YAKIN İZLEME PAZARI",
    "PİYASA ÖNCESİ İŞLEM PLATFORMU",
}

_TICKER_RE = re.compile(r"^[A-Z0-9]{2,12}$")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


class OfficialUniverseError(RuntimeError):
    pass


@dataclass(frozen=True)
class OfficialUniverseSnapshot:
    records: list[UniverseRecord]
    kap_records: int
    first_trade_records: int
    first_trade_url: str
    source_date: str
    market_counts: dict[str, int]


@dataclass(frozen=True)
class MarketRow:
    ticker: str
    name: str
    market: str


@dataclass(frozen=True)
class SectorClassification:
    sector: str
    industry: str | None


class _TableParser(HTMLParser):
    """Small dependency-free HTML table parser for server-rendered KAP rows."""

    def __init__(self):
        super().__init__()
        self.in_tr = False
        self.in_cell = False
        self.cell_parts: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self.in_tr = True
            self.row = []
        elif self.in_tr and tag in {"td", "th"}:
            self.in_cell = True
            self.cell_parts = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.in_tr and tag in {"td", "th"} and self.in_cell:
            text = " ".join("".join(self.cell_parts).split())
            self.row.append(text)
            self.in_cell = False
        elif tag == "tr" and self.in_tr:
            if self.row:
                self.rows.append(self.row)
            self.in_tr = False
            self.row = []

    def handle_data(self, data):
        if self.in_cell:
            self.cell_parts.append(data)


def _clean_market(text: str) -> str | None:
    upper = " ".join(text.upper().split())
    for market in EQUITY_MARKETS:
        if market in upper:
            return market
    # Explicit non-equity headings reset the parser so rows beneath them cannot
    # inherit the previous equity market.
    if "PAZAR" in upper or "PİYASASI" in upper or "PLATFORM" in upper:
        return "__OTHER__"
    return None


def parse_kap_markets_html(html: str) -> list[MarketRow]:
    parser = _TableParser()
    parser.feed(html)
    current_market: str | None = None
    output: list[MarketRow] = []
    seen: set[str] = set()

    for cells in parser.rows:
        joined = " ".join(cells)
        market = _clean_market(joined)
        if market is not None and len(cells) <= 3:
            current_market = market
            # A heading row can still carry a company row in unusual HTML; do
            # not continue until ticker extraction below has had a chance.

        # Typical KAP row: [Sıra, Kod, Şirket / Fon Adı]. Tolerate extra cells.
        ticker = None
        ticker_index = None
        for index, raw in enumerate(cells):
            candidate = raw.strip().upper().replace(".IS", "")
            if _TICKER_RE.fullmatch(candidate) and not candidate.isdigit():
                ticker = candidate
                ticker_index = index
                break
        if not ticker or ticker in {"KOD", "SIRA"}:
            continue
        if current_market not in EQUITY_MARKETS:
            continue

        name = ""
        for raw in cells[(ticker_index or 0) + 1 :]:
            value = " ".join(raw.split())
            if value and value.upper() not in {"ŞİRKET / FON ADI", "ŞİRKET", "FON"}:
                name = value
                break
        if not name:
            continue
        if ticker in seen:
            raise OfficialUniverseError(f"Duplicate ticker in KAP market source: {ticker}")
        seen.add(ticker)
        output.append(MarketRow(ticker=ticker, name=name, market=current_market))

    return output


def _is_data_member(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return not name.endswith("/") and not any(
        part == "__MACOSX" or part.startswith(".") for part in parts
    )


def _validate_zip(data: bytes, source: str, content_type: str = "") -> None:
    mime = content_type.split(";", 1)[0].strip().lower()
    allowed = {"", "application/zip", "application/x-zip-compressed",
               "application/octet-stream", "binary/octet-stream"}
    if (mime not in allowed or not data.startswith((b"PK\x03\x04", b"PK\x05\x06"))
            or not zipfile.is_zipfile(BytesIO(data))):
        raise OfficialUniverseError(
            f"Invalid ZIP from {source}: content-type={mime or 'missing'}, "
            f"bytes={len(data)}, magic={data[:8].hex()}"
        )


class _ReportLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {"href", "dosya-yolu"} and value:
                self.links.append(value)


def _discover_report_from_page(html: bytes) -> str:
    parser = _ReportLinkParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    for link in parser.links:
        url = urllib.parse.urljoin(BIST_EQUITY_DATA_URL, link)
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme == "https" and parsed.hostname in
                {"borsaistanbul.com", "www.borsaistanbul.com"}
                and not parsed.username and not parsed.password
                and parsed.port in {None, 443}
                and parsed.path.lower().endswith("/ilkislem.zip")):
            return url
    raise OfficialUniverseError("Official BIST equity page has no trusted ilkislem.zip link")


def _fetch_first_trade(http_get, data_paths_url):
    failures = []
    attempted = set()
    try:
        url = discover_ilkislem_url(http_get(data_paths_url), base_url=data_paths_url)
        attempted.add(url)
        data = http_get(url)
        _validate_zip(data, url)
        return parse_first_trade_zip(data), url
    except Exception as exc:
        failures.append(f"catalogue/report via {data_paths_url}: {exc}")
    # Only an explicitly linked report on the official page is an acceptable
    # fallback. Never publish a KAP-only or cached/stale universe on failure.
    try:
        url = _discover_report_from_page(http_get(BIST_EQUITY_DATA_URL))
        if url in attempted:
            raise OfficialUniverseError(f"Fallback repeats failed report URL: {url}")
        data = http_get(url)
        _validate_zip(data, url)
        return parse_first_trade_zip(data), url
    except Exception as exc:
        failures.append(f"fallback via {BIST_EQUITY_DATA_URL}: {exc}")
    raise OfficialUniverseError("Official first-trade sources failed: " + " | ".join(failures))


def _iter_text_from_xlsx(data: bytes) -> Iterable[str]:
    workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(values_only=True):
                # Directory and filename are separate cells in the live catalogue.
                values = [str(value).strip() for value in row if value is not None]
                for index, value in enumerate(values):
                    if value.lower() == "ilkislem.zip" and index:
                        directory = values[index - 1]
                        if directory.endswith("/"):
                            yield directory + value
                yield from values
    finally:
        workbook.close()


def _iter_catalog_strings(data: bytes) -> Iterable[str]:
    """Yield strings from DataFilePaths.zip without assuming its inner format."""
    _validate_zip(data, "BIST catalogue")
    with zipfile.ZipFile(BytesIO(data)) as archive:
        for name in archive.namelist():
            if not _is_data_member(name):
                continue
            raw = archive.read(name)
            suffix = PurePosixPath(name).suffix.lower()
            if suffix in {".xlsx", ".xlsm"}:
                yield from _iter_text_from_xlsx(raw)
            else:
                for encoding in ("utf-8-sig", "cp1254", "latin-1"):
                    try:
                        text = raw.decode(encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    continue
                yield from text.splitlines()


def discover_ilkislem_url(catalog_zip: bytes, *, base_url: str = BIST_DATA_PATHS_URL) -> str:
    candidates: list[str] = []
    for text in _iter_catalog_strings(catalog_zip):
        if "ilkislem" not in text.lower():
            continue
        candidates.extend(_URL_RE.findall(text))
        # Semicolon/tab separated catalogues sometimes provide a relative path.
        for token in re.split(r"[;\t, ]+", text):
            cleaned = token.strip().strip('"\'')
            if "ilkislem" in cleaned.lower() and cleaned.lower().endswith(".zip"):
                candidates.append(cleaned)
    for candidate in candidates:
        # A bare filename provides no directory; never infer /files/ from the
        # catalogue URL. Use the official market page fallback instead.
        if "/" not in candidate:
            continue
        url = urllib.parse.urljoin(base_url, candidate)
        if "ilkislem" in url.lower() and url.lower().endswith(".zip"):
            return url
    raise OfficialUniverseError("BIST DataFilePaths catalogue does not expose ilkislem.zip")


def _parse_date(value: object) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _first_trade_ticker(value: object) -> str:
    ticker = str(value or "").strip().upper()
    # BIST equity instruments carry .E; .F funds and other instrument
    # suffixes must not be collapsed into equity identities.
    for suffix in (".IS", ".E"):
        if ticker.endswith(suffix):
            return ticker[:-len(suffix)]
    return ticker


def parse_first_trade_zip(data: bytes) -> dict[str, str]:
    """Parse BIST ilkislem.zip -> current ticker -> first trading date."""
    result: dict[str, str] = {}
    _validate_zip(data, "BIST first-trade report")
    with zipfile.ZipFile(BytesIO(data)) as archive:
        members = [n for n in archive.namelist() if _is_data_member(n)]
        if not members:
            raise OfficialUniverseError("ilkislem.zip is empty")
        target = next((n for n in members if n.lower().endswith((".xlsx", ".xlsm"))), None)
        if target is not None:
            workbook = load_workbook(BytesIO(archive.read(target)), read_only=True, data_only=True)
            try:
                for sheet in workbook.worksheets:
                    for row in sheet.iter_rows(values_only=True):
                        values = list(row)
                        if len(values) < 5:
                            continue
                        ticker = _first_trade_ticker(values[1])
                        first_day = _parse_date(values[4])
                        if _TICKER_RE.fullmatch(ticker) and first_day:
                            result[ticker] = first_day
            finally:
                workbook.close()
        else:
            target = members[0]
            raw = archive.read(target)
            text = None
            for encoding in ("utf-8-sig", "cp1254", "latin-1"):
                try:
                    text = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    pass
            if text is None:
                raise OfficialUniverseError("Unsupported ilkislem.zip inner format")
            reader = csv.reader(io.StringIO(text), delimiter=";")
            for row in reader:
                if len(row) < 5:
                    continue
                ticker = _first_trade_ticker(row[1])
                first_day = _parse_date(row[4])
                if _TICKER_RE.fullmatch(ticker) and first_day:
                    result[ticker] = first_day
    if not result:
        raise OfficialUniverseError("No first-trade records parsed from ilkislem.zip")
    return result



def parse_viop_underlyings_html(
    html: str,
    *,
    min_underlyings: int = 20,
    max_underlyings: int = 100,
) -> set[str]:
    """Parse equity underlyings from Borsa Istanbul's official VIOP page.

    Only the ``Pay Senetleri`` section is accepted. Parsing stops when the
    following ``Endeks`` section begins so index, FX, metals and other VIOP
    underlyings can never enter the equity universe.

    The count guard is deliberately broad. It is not a hard-coded expectation
    of today's membership; it only prevents a broken upstream page/parser from
    silently marking the whole equity universe as non-VIOP.
    """

    parser = _TableParser()
    parser.feed(html)

    in_equities = False
    found_equity_section = False
    tickers: set[str] = set()

    for cells in parser.rows:
        normalized_cells = [
            " ".join(cell.upper().split())
            for cell in cells
        ]

        # Official heading: "Pay Senetleri | Kod/Açıklama"
        if any(cell == "PAY SENETLERI" for cell in normalized_cells):
            in_equities = True
            found_equity_section = True
            continue

        if not in_equities:
            continue

        # The official page places Endeks immediately after Pay Senetleri.
        # Stop here rather than trying to classify all later VIOP asset types.
        if any(cell == "ENDEKS" for cell in normalized_cells):
            break

        for raw in cells:
            candidate = raw.strip().upper().replace(".IS", "")

            if (
                _TICKER_RE.fullmatch(candidate)
                and not candidate.isdigit()
                and candidate not in {"KOD", "SIRA"}
            ):
                tickers.add(candidate)

    if not found_equity_section:
        raise OfficialUniverseError(
            "BIST VIOP page does not contain a Pay Senetleri section"
        )

    if not (min_underlyings <= len(tickers) <= max_underlyings):
        raise OfficialUniverseError(
            "BIST VIOP equity-underlying count outside safety bounds: "
            f"{len(tickers)} not in [{min_underlyings}, {max_underlyings}]"
        )

    return tickers


def _decode_next_f_chunks(html: str) -> list[str]:
    """Decode string payloads embedded in Next.js Flight push records."""

    pattern = re.compile(
        r'self\.__next_f\.push\(\[1,("(?:\\.|[^"\\])*")\]\)',
        re.DOTALL,
    )

    chunks: list[str] = []

    for match in pattern.finditer(html):
        try:
            chunks.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            # Ignore unrelated or malformed Flight chunks. The sector parser
            # below still fails closed if the expected payload cannot be found.
            continue

    return chunks


def _json_value_after(text: str, marker: str):
    position = text.find(marker)

    if position == -1:
        raise OfficialUniverseError(
            f"KAP sector payload marker not found: {marker}"
        )

    try:
        value, _ = json.JSONDecoder().raw_decode(
            text[position + len(marker):]
        )
    except json.JSONDecodeError as exc:
        raise OfficialUniverseError(
            f"Malformed KAP sector payload after {marker}"
        ) from exc

    return value


def parse_kap_sectors_html(
    html: str,
    *,
    valid_tickers: set[str] | None = None,
) -> dict[str, SectorClassification]:
    """Parse KAP's embedded BIST sector hierarchy.

    KAP currently renders sector metadata inside a Next.js Flight payload.
    Each company can appear both under its specific child industry and again
    in aggregate main-sector content. The specific non-null industry wins.

    If valid_tickers is supplied, legacy ticker aliases exposed by KAP are
    ignored and full coverage of the supplied current universe is required.
    """

    chunks = _decode_next_f_chunks(html)

    sector_chunk = next(
        (
            chunk
            for chunk in chunks
            if '"sectorTitles":' in chunk
            and '"bistSectorsTable":' in chunk
        ),
        None,
    )

    if sector_chunk is None:
        raise OfficialUniverseError(
            "KAP sector Next.js payload not found"
        )

    table_position = sector_chunk.find('"bistSectorsTable":')

    sector_data = _json_value_after(
        sector_chunk[table_position:],
        '"data":',
    )

    if not isinstance(sector_data, list):
        raise OfficialUniverseError(
            "KAP sector data is not a hierarchy list"
        )

    valid = None

    if valid_tickers is not None:
        valid = {
            str(ticker).strip().upper().replace(".IS", "")
            for ticker in valid_tickers
        }

    result: dict[str, SectorClassification] = {}

    def add_mapping(
        stock_codes: object,
        sector: str,
        industry: str | None,
    ) -> None:
        for raw_ticker in str(stock_codes or "").split(","):
            ticker = (
                raw_ticker
                .strip()
                .upper()
                .replace(".IS", "")
            )

            if not _TICKER_RE.fullmatch(ticker):
                continue

            if valid is not None and ticker not in valid:
                # KAP can publish historical/current codes together, e.g.
                # "FIN, QNBTR". Only the authoritative current universe wins.
                continue

            incoming = SectorClassification(
                sector=sector,
                industry=industry,
            )

            previous = result.get(ticker)

            if previous is None:
                result[ticker] = incoming
                continue

            if previous == incoming:
                continue

            if previous.sector == incoming.sector:
                # KAP repeats companies in aggregate main-sector content.
                # Prefer the more specific child-industry classification.
                if (
                    previous.industry is None
                    and incoming.industry is not None
                ):
                    result[ticker] = incoming
                    continue

                if (
                    previous.industry is not None
                    and incoming.industry is None
                ):
                    continue

            raise OfficialUniverseError(
                "Conflicting KAP sector classification for "
                f"{ticker}: "
                f"{previous.sector!r}/{previous.industry!r} vs "
                f"{incoming.sector!r}/{incoming.industry!r}"
            )

    for main in sector_data:
        if not isinstance(main, dict):
            continue

        sector = " ".join(
            str(main.get("title") or "").split()
        )

        if not sector:
            continue

        children = main.get("children")

        if isinstance(children, dict):
            for child in children.values():
                if not isinstance(child, dict):
                    continue

                industry = " ".join(
                    str(child.get("title") or "").split()
                ) or None

                for company in child.get("content") or []:
                    if not isinstance(company, dict):
                        continue

                    add_mapping(
                        company.get("stockCode"),
                        sector,
                        industry,
                    )

        # KAP also publishes aggregate main-sector content.
        for company in main.get("content") or []:
            if not isinstance(company, dict):
                continue

            add_mapping(
                company.get("stockCode"),
                sector,
                None,
            )

    if not result:
        raise OfficialUniverseError(
            "KAP sector source produced no classifications"
        )

    if valid is not None:
        missing = sorted(valid - set(result))

        if missing:
            preview = ", ".join(missing[:20])

            raise OfficialUniverseError(
                "KAP sector coverage incomplete: "
                f"{len(missing)}/{len(valid)} current equities missing"
                + (f": {preview}" if preview else "")
            )

    return result


def default_http_get(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "LabyrinthMomentumV2/1.0 (+https://github.com/)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        if urllib.parse.urlsplit(final_url).scheme != "https":
            raise OfficialUniverseError(f"Unsafe HTTP redirect: {url} -> {final_url}")
        data = response.read()
        if urllib.parse.urlsplit(url).path.lower().endswith(".zip"):
            _validate_zip(data, f"{url} -> {final_url}", response.headers.get("Content-Type", ""))
        return data


def fetch_official_universe(
    *,
    http_get: Callable[[str], bytes] = default_http_get,
    kap_url: str = KAP_MARKETS_URL,
    sectors_url: str = KAP_SECTORS_URL,
    data_paths_url: str = BIST_DATA_PATHS_URL,
    viop_url: str = BIST_VIOP_UNDERLYINGS_URL,
    min_equities: int = 400,
) -> OfficialUniverseSnapshot:
    try:
        kap_html = http_get(kap_url).decode("utf-8", errors="replace")
        market_rows = parse_kap_markets_html(kap_html)
        if len(market_rows) < min_equities:
            raise OfficialUniverseError(
                f"KAP equity universe unexpectedly small: {len(market_rows)} < {min_equities}"
            )

        current_tickers = {
            row.ticker
            for row in market_rows
        }

        sectors_html = http_get(
            sectors_url
        ).decode("utf-8", errors="replace")

        sector_metadata = parse_kap_sectors_html(
            sectors_html,
            valid_tickers=current_tickers,
        )

        first_trade, first_trade_url = _fetch_first_trade(
            http_get,
            data_paths_url,
        )

        viop_html = http_get(viop_url).decode("utf-8", errors="replace")
        viop_tickers = parse_viop_underlyings_html(viop_html)
    except OfficialUniverseError:
        raise
    except Exception as exc:
        raise OfficialUniverseError(f"Official universe download failed: {exc}") from exc

    source_date = date.today().isoformat()

    market_counts: dict[str, int] = {}
    for row in market_rows:
        market_counts[row.market] = market_counts.get(row.market, 0) + 1

    records = [
        UniverseRecord(
            ticker=row.ticker,
            name=row.name,
            instrument_type="EQUITY",
            sector=sector_metadata[row.ticker].sector,
            industry=sector_metadata[row.ticker].industry,
            first_trade_date=first_trade.get(row.ticker),
            status="ACTIVE",
            active=1,
            is_viop=1 if row.ticker in viop_tickers else 0,
            viop_source="BIST_VIOP_UNDERLYINGS",
            viop_as_of=source_date,
        )
        for row in market_rows
    ]
    return OfficialUniverseSnapshot(
        records=records,
        kap_records=len(market_rows),
        first_trade_records=len(first_trade),
        first_trade_url=first_trade_url,
        source_date=source_date,
        market_counts=market_counts,
    )


def guard_universe_change(
    conn,
    records: Iterable[UniverseRecord],
    *,
    max_drop_fraction: float = 0.08,
    min_equities: int = 400,
) -> None:
    """Fail closed on suspicious source shrinkage before marking anything inactive."""
    records = list(records)
    incoming = {UniverseManager.normalize_ticker(r.ticker) for r in records if r.instrument_type == "EQUITY" and r.active}
    if len(incoming) < min_equities:
        raise OfficialUniverseError(f"Incoming equity universe below safety floor: {len(incoming)}")
    current = {
        row[0]
        for row in conn.execute(
            """SELECT si.ticker FROM securities s
               JOIN security_identifiers si ON si.security_id=s.security_id
               WHERE s.instrument_type='EQUITY' AND s.active=1 AND si.is_current=1"""
        ).fetchall()
    }
    if current:
        missing = current - incoming
        fraction = len(missing) / len(current)
        if fraction > max_drop_fraction:
            raise OfficialUniverseError(
                f"Suspicious universe shrinkage: {len(missing)}/{len(current)} active equities missing "
                f"({fraction:.1%} > {max_drop_fraction:.1%})"
            )
