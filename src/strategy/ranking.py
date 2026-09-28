from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from statistics import median
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class CrossSectionalRanks:
    ticker: str

    core_ready: bool

    core_momentum_pct_all: float | None
    core_quality_pct_all: float | None

    momentum_126_pct_all: float | None
    momentum_63_pct_all: float | None
    momentum_21_pct_all: float | None

    acceleration_21_63_all: float | None
    acceleration_63_126_all: float | None

    core_momentum_pct_viop: float | None
    core_quality_pct_viop: float | None

    momentum_126_pct_viop: float | None
    momentum_63_pct_viop: float | None
    momentum_21_pct_viop: float | None

    acceleration_21_63_viop: float | None
    acceleration_63_126_viop: float | None

    momentum_63_pct_sector: float | None
    sector_momentum_63_median: float | None
    momentum_63_vs_sector_median: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(number):
        return None

    return number


def _percentile_ranks(
    values: dict[str, float],
) -> dict[str, float]:
    """Return 0-100 percentile ranks with average ranks for ties.

    Higher raw values always receive higher percentile ranks.
    A one-member universe receives a neutral 50 percentile.
    """

    if not values:
        return {}

    ordered = sorted(
        values.items(),
        key=lambda item: item[1],
    )

    n = len(ordered)

    if n == 1:
        return {
            ordered[0][0]: 50.0
        }

    result: dict[str, float] = {}

    i = 0

    while i < n:
        j = i

        while (
            j + 1 < n
            and ordered[j + 1][1] == ordered[i][1]
        ):
            j += 1

        average_index = (i + j) / 2.0

        percentile = (
            average_index
            / (n - 1)
            * 100.0
        )

        for k in range(i, j + 1):
            result[ordered[k][0]] = percentile

        i = j + 1

    return result


def _rank_field(
    rows: Sequence[dict],
    field: str,
    *,
    invert: bool = False,
) -> dict[str, float]:
    values: dict[str, float] = {}

    for row in rows:
        value = _number(
            row.get(field)
        )

        if value is None:
            continue

        values[row["ticker"]] = (
            -value if invert else value
        )

    return _percentile_ranks(values)


def _difference(
    left: float | None,
    right: float | None,
) -> float | None:
    if left is None or right is None:
        return None

    return left - right


def compute_cross_sectional_ranks(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, CrossSectionalRanks]:
    """Calculate descriptive cross-sectional momentum ranks.

    No Long/Short decision is made here.

    ALL ranks use the complete supplied equity universe.
    VIOP ranks use only rows where is_viop=True.
    Sector ranks compare M63 only with peers in the same sector.

    FIP is treated as momentum quality rather than direction:
    more-negative FIP receives a higher quality percentile.
    """

    prepared = [
        dict(row)
        for row in rows
    ]

    tickers = [
        str(row.get("ticker") or "")
        for row in prepared
    ]

    if (
        not tickers
        or any(not ticker for ticker in tickers)
    ):
        raise ValueError(
            "Every ranking row must have a ticker"
        )

    if len(tickers) != len(set(tickers)):
        raise ValueError(
            "Duplicate tickers are not allowed"
        )

    viop_rows = [
        row
        for row in prepared
        if row.get("is_viop") in (True, 1)
    ]

    # --------------------------------------------------------
    # ALL-EQUITY ranks
    # --------------------------------------------------------

    core_all = _rank_field(
        prepared,
        "momentum_12_1",
    )

    quality_all = _rank_field(
        prepared,
        "fip_12_1",
        invert=True,
    )

    m126_all = _rank_field(
        prepared,
        "momentum_126",
    )

    m63_all = _rank_field(
        prepared,
        "momentum_63",
    )

    m21_all = _rank_field(
        prepared,
        "momentum_21",
    )

    # --------------------------------------------------------
    # VIOP-only ranks
    # --------------------------------------------------------

    core_viop = _rank_field(
        viop_rows,
        "momentum_12_1",
    )

    quality_viop = _rank_field(
        viop_rows,
        "fip_12_1",
        invert=True,
    )

    m126_viop = _rank_field(
        viop_rows,
        "momentum_126",
    )

    m63_viop = _rank_field(
        viop_rows,
        "momentum_63",
    )

    m21_viop = _rank_field(
        viop_rows,
        "momentum_21",
    )

    # --------------------------------------------------------
    # Sector M63 context
    # --------------------------------------------------------

    sector_rows: dict[str, list[dict]] = {}

    for row in prepared:
        sector = row.get("sector")

        if not sector:
            continue

        sector_rows.setdefault(
            str(sector),
            [],
        ).append(row)

    sector_rank_by_ticker: dict[str, float] = {}
    sector_median_by_ticker: dict[str, float] = {}

    for sector, members in sector_rows.items():
        del sector  # descriptive only

        ranks = _rank_field(
            members,
            "momentum_63",
        )

        sector_rank_by_ticker.update(
            ranks
        )

        values = [
            _number(
                row.get("momentum_63")
            )
            for row in members
        ]

        numeric_values = [
            value
            for value in values
            if value is not None
        ]

        if not numeric_values:
            continue

        sector_median = float(
            median(numeric_values)
        )

        for row in members:
            ticker = row["ticker"]

            if _number(
                row.get("momentum_63")
            ) is not None:
                sector_median_by_ticker[
                    ticker
                ] = sector_median

    # --------------------------------------------------------
    # Final typed output
    # --------------------------------------------------------

    output: dict[str, CrossSectionalRanks] = {}

    for row in prepared:
        ticker = row["ticker"]

        m63_value = _number(
            row.get("momentum_63")
        )

        sector_median = (
            sector_median_by_ticker.get(
                ticker
            )
        )

        core_value = _number(
            row.get("momentum_12_1")
        )

        core_fip = _number(
            row.get("fip_12_1")
        )

        output[ticker] = CrossSectionalRanks(
            ticker=ticker,

            core_ready=(
                core_value is not None
                and core_fip is not None
            ),

            core_momentum_pct_all=core_all.get(
                ticker
            ),

            core_quality_pct_all=quality_all.get(
                ticker
            ),

            momentum_126_pct_all=m126_all.get(
                ticker
            ),

            momentum_63_pct_all=m63_all.get(
                ticker
            ),

            momentum_21_pct_all=m21_all.get(
                ticker
            ),

            acceleration_21_63_all=_difference(
                m21_all.get(ticker),
                m63_all.get(ticker),
            ),

            acceleration_63_126_all=_difference(
                m63_all.get(ticker),
                m126_all.get(ticker),
            ),

            core_momentum_pct_viop=core_viop.get(
                ticker
            ),

            core_quality_pct_viop=quality_viop.get(
                ticker
            ),

            momentum_126_pct_viop=m126_viop.get(
                ticker
            ),

            momentum_63_pct_viop=m63_viop.get(
                ticker
            ),

            momentum_21_pct_viop=m21_viop.get(
                ticker
            ),

            acceleration_21_63_viop=_difference(
                m21_viop.get(ticker),
                m63_viop.get(ticker),
            ),

            acceleration_63_126_viop=_difference(
                m63_viop.get(ticker),
                m126_viop.get(ticker),
            ),

            momentum_63_pct_sector=(
                sector_rank_by_ticker.get(
                    ticker
                )
            ),

            sector_momentum_63_median=(
                sector_median
            ),

            momentum_63_vs_sector_median=(
                None
                if (
                    m63_value is None
                    or sector_median is None
                )
                else (
                    m63_value
                    - sector_median
                )
            ),
        )

    return output
