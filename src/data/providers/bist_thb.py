from __future__ import annotations

import csv
import io
import math
from datetime import date, timedelta
from typing import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

from src.calculation.engine import PriceBar


class BISTTHBProviderError(RuntimeError):
    pass


def _default_http_get(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/zip,*/*",
        },
    )
    with urlopen(request, timeout=20) as response:
        return response.read()


class BISTTHBProvider:
    """Official Borsa Istanbul daily bulletin (THB) fallback provider.

    File convention:
        /data/thb/YYYY/MM/thbYYYYMMDD1.zip

    THB is used only as an authoritative recovery source for isolated
    sessions missing from the primary market-data provider.
    """

    source_name = "BIST_THB"
    base_url = "https://www.borsaistanbul.com"

    def __init__(self, http_get: Callable[[str], bytes] | None = None):
        self._http_get = http_get or _default_http_get

    @classmethod
    def bulletin_url(cls, day: date) -> str:
        stamp = day.strftime("%Y%m%d")
        return (
            f"{cls.base_url}/data/thb/{day:%Y}/{day:%m}/"
            f"thb{stamp}1.zip"
        )

    def fetch(self, ticker: str, start: date, end: date) -> list[PriceBar]:
        if end < start:
            raise ValueError("end must be on or after start")

        clean_ticker = ticker.strip().upper().replace(".IS", "")
        output: list[PriceBar] = []

        day = start
        while day <= end:
            bar = self._fetch_day(clean_ticker, day)
            if bar is not None:
                output.append(bar)
            day += timedelta(days=1)

        return output

    def _fetch_day(self, ticker: str, day: date) -> PriceBar | None:
        url = self.bulletin_url(day)

        try:
            payload = self._http_get(url)
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise BISTTHBProviderError(
                f"BIST THB download failed for {day.isoformat()}: HTTP {exc.code}"
            ) from exc

        return self._parse_zip(payload, ticker=ticker, day=day)

    @staticmethod
    def _decode_csv(raw: bytes) -> str:
        for encoding in ("utf-8-sig", "cp1254", "latin1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise BISTTHBProviderError("BIST THB CSV encoding could not be decoded")

    @staticmethod
    def _normalise_header(value: str) -> str:
        return " ".join(value.strip().upper().split())

    @staticmethod
    def _number(value: str, *, required: bool) -> float | None:
        text = value.strip()
        if not text:
            if required:
                return None
            return None

        try:
            number = float(text.replace(",", "."))
        except ValueError:
            return None

        if not math.isfinite(number):
            return None
        return number

    @classmethod
    def _parse_zip(
        cls,
        payload: bytes,
        *,
        ticker: str,
        day: date,
    ) -> PriceBar | None:
        try:
            archive = ZipFile(io.BytesIO(payload))
        except BadZipFile as exc:
            raise BISTTHBProviderError(
                f"BIST THB response for {day.isoformat()} is not a valid ZIP"
            ) from exc

        csv_names = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".csv")
            and not name.startswith("__MACOSX/")
        ]

        if not csv_names:
            raise BISTTHBProviderError(
                f"BIST THB ZIP for {day.isoformat()} contains no CSV"
            )

        raw = archive.read(csv_names[0])
        text = cls._decode_csv(raw)
        reader = csv.reader(io.StringIO(text), delimiter=";")

        try:
            header = next(reader)
        except StopIteration as exc:
            raise BISTTHBProviderError(
                f"BIST THB CSV for {day.isoformat()} is empty"
            ) from exc

        columns = {
            cls._normalise_header(name): index
            for index, name in enumerate(header)
        }

        required = (
            "TARIH",
            "ISLEM KODU",
            "ACILIS FIYATI",
            "EN DUSUK FIYAT",
            "EN YUKSEK FIYAT",
            "KAPANIS FIYATI",
            "TOPLAM ISLEM ADEDI",
        )

        missing_columns = [name for name in required if name not in columns]
        if missing_columns:
            raise BISTTHBProviderError(
                "BIST THB CSV missing required column(s): "
                + ", ".join(missing_columns)
            )

        wanted_series = f"{ticker}.E"
        highest_index = max(columns[name] for name in required)

        for row in reader:
            if len(row) <= highest_index:
                continue

            if row[columns["TARIH"]].strip() != day.isoformat():
                continue

            if row[columns["ISLEM KODU"]].strip().upper() != wanted_series:
                continue

            open_price = cls._number(
                row[columns["ACILIS FIYATI"]],
                required=True,
            )
            low = cls._number(
                row[columns["EN DUSUK FIYAT"]],
                required=True,
            )
            high = cls._number(
                row[columns["EN YUKSEK FIYAT"]],
                required=True,
            )
            close = cls._number(
                row[columns["KAPANIS FIYATI"]],
                required=True,
            )
            volume = cls._number(
                row[columns["TOPLAM ISLEM ADEDI"]],
                required=False,
            )

            # Do not fabricate a bar when the official bulletin itself
            # contains no usable OHLC values (for example a suspension).
            if any(
                value is None
                for value in (open_price, high, low, close)
            ):
                return None

            return PriceBar(
                day,
                float(open_price),
                float(high),
                float(low),
                float(close),
                None if volume is None else float(volume),
            )

        return None
