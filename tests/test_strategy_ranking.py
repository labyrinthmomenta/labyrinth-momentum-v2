import math

import pytest

from src.strategy.ranking import compute_cross_sectional_ranks


def row(
    ticker,
    *,
    sector="TEST",
    is_viop=False,
    core=None,
    fip=None,
    m126=None,
    m63=None,
    m21=None,
):
    return {
        "ticker": ticker,
        "sector": sector,
        "is_viop": is_viop,
        "momentum_12_1": core,
        "fip_12_1": fip,
        "momentum_126": m126,
        "momentum_63": m63,
        "momentum_21": m21,
    }


def test_higher_momentum_gets_higher_percentile():
    ranks = compute_cross_sectional_ranks([
        row("AAA", core=0.10),
        row("BBB", core=0.20),
        row("CCC", core=0.30),
    ])

    assert ranks["AAA"].core_momentum_pct_all == 0.0
    assert ranks["BBB"].core_momentum_pct_all == 50.0
    assert ranks["CCC"].core_momentum_pct_all == 100.0


def test_fip_quality_rank_rewards_more_negative_values():
    ranks = compute_cross_sectional_ranks([
        row("AAA", fip=-0.50),
        row("BBB", fip=-0.10),
        row("CCC", fip=0.20),
    ])

    assert ranks["AAA"].core_quality_pct_all == 100.0
    assert ranks["BBB"].core_quality_pct_all == 50.0
    assert ranks["CCC"].core_quality_pct_all == 0.0


def test_ties_receive_average_percentile():
    ranks = compute_cross_sectional_ranks([
        row("AAA", m63=0.10),
        row("BBB", m63=0.10),
        row("CCC", m63=0.30),
    ])

    assert ranks["AAA"].momentum_63_pct_all == 25.0
    assert ranks["BBB"].momentum_63_pct_all == 25.0
    assert ranks["CCC"].momentum_63_pct_all == 100.0


def test_acceleration_is_rank_difference_not_raw_return_difference():
    ranks = compute_cross_sectional_ranks([
        row(
            "AAA",
            m126=0.10,
            m63=0.20,
            m21=0.30,
        ),
        row(
            "BBB",
            m126=0.20,
            m63=0.30,
            m21=0.10,
        ),
        row(
            "CCC",
            m126=0.30,
            m63=0.10,
            m21=0.20,
        ),
    ])

    # AAA: M63 is middle-ranked (50), M21 is highest-ranked (100).
    assert ranks["AAA"].acceleration_21_63_all == 50.0

    # BBB: M63 highest (100), M21 lowest (0).
    assert ranks["BBB"].acceleration_21_63_all == -100.0


def test_viop_ranking_uses_only_viop_members():
    ranks = compute_cross_sectional_ranks([
        row(
            "AAA",
            is_viop=True,
            m63=0.10,
        ),
        row(
            "BBB",
            is_viop=True,
            m63=0.20,
        ),
        row(
            "SPOT",
            is_viop=False,
            m63=5.00,
        ),
    ])

    assert ranks["AAA"].momentum_63_pct_viop == 0.0
    assert ranks["BBB"].momentum_63_pct_viop == 100.0

    assert ranks["SPOT"].momentum_63_pct_viop is None


def test_viop_integer_flag_is_supported():
    ranks = compute_cross_sectional_ranks([
        row(
            "AAA",
            is_viop=1,
            m63=0.10,
        ),
        row(
            "BBB",
            is_viop=1,
            m63=0.20,
        ),
    ])

    assert ranks["AAA"].momentum_63_pct_viop == 0.0
    assert ranks["BBB"].momentum_63_pct_viop == 100.0


def test_sector_context_is_calculated_within_sector():
    ranks = compute_cross_sectional_ranks([
        row(
            "AAA",
            sector="BANK",
            m63=0.10,
        ),
        row(
            "BBB",
            sector="BANK",
            m63=0.20,
        ),
        row(
            "CCC",
            sector="BANK",
            m63=0.30,
        ),
        row(
            "DDD",
            sector="TECH",
            m63=-0.50,
        ),
    ])

    assert ranks["AAA"].momentum_63_pct_sector == 0.0
    assert ranks["BBB"].momentum_63_pct_sector == 50.0
    assert ranks["CCC"].momentum_63_pct_sector == 100.0

    assert math.isclose(
        ranks["BBB"].sector_momentum_63_median,
        0.20,
        abs_tol=1e-12,
    )

    assert math.isclose(
        ranks["CCC"].momentum_63_vs_sector_median,
        0.10,
        abs_tol=1e-12,
    )

    # Single-member sector receives neutral percentile.
    assert ranks["DDD"].momentum_63_pct_sector == 50.0


def test_missing_values_remain_missing_not_zero_ranked():
    ranks = compute_cross_sectional_ranks([
        row(
            "AAA",
            core=0.20,
            fip=-0.20,
        ),
        row(
            "BBB",
            core=None,
            fip=None,
        ),
    ])

    assert ranks["AAA"].core_ready is True

    assert ranks["BBB"].core_ready is False
    assert ranks["BBB"].core_momentum_pct_all is None
    assert ranks["BBB"].core_quality_pct_all is None


def test_duplicate_ticker_is_rejected():
    with pytest.raises(
        ValueError,
        match="Duplicate tickers",
    ):
        compute_cross_sectional_ranks([
            row("AAA"),
            row("AAA"),
        ])
