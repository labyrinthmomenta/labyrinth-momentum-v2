from __future__ import annotations

import json

import pytest

from src.reporting.trader_view import (
    TraderViewError,
    build_trader_view,
    load_trader_view,
    render_trader_view,
)


def _manifest(**overrides):
    payload = {
        "status": "PASS",
        "dry_run": False,
        "as_of": "2026-10-09",
        "securities_published": 4,
        "files": {"screener": "screener.json"},
    }
    payload.update(overrides)
    return payload


def _row(
    ticker,
    *,
    all_rank,
    viop_rank=None,
    quality_all=50.0,
    quality_viop=None,
    is_viop=False,
    data_status="OK",
    ranking_status="OK",
    core_ready=True,
    vcp_status="NOT_AVAILABLE",
    vcp_state=None,
):
    return {
        "ticker": ticker,
        "name": f"{ticker} A.S.",
        "sector": "TEST",
        "is_viop": is_viop,
        "as_of": "2026-10-09",
        "data_status": data_status,
        "ranking_status": ranking_status,
        "core_ready": core_ready,
        "core_momentum_pct_all": all_rank,
        "core_quality_pct_all": quality_all,
        "momentum_126_pct_all": all_rank,
        "momentum_63_pct_all": all_rank,
        "momentum_21_pct_all": all_rank,
        "acceleration_21_63_all": all_rank - 50.0,
        "acceleration_63_126_all": all_rank - 40.0,
        "core_momentum_pct_viop": viop_rank,
        "core_quality_pct_viop": quality_viop,
        "momentum_126_pct_viop": viop_rank,
        "momentum_63_pct_viop": viop_rank,
        "momentum_21_pct_viop": viop_rank,
        "acceleration_21_63_viop": None,
        "acceleration_63_126_viop": None,
        "fip_12_1": -0.25,
        "vcp_status": vcp_status,
        "vcp_state": vcp_state,
    }


def test_all_view_uses_published_all_rank():
    rows = [
        _row("AAA", all_rank=95.0),
        _row("BBB", all_rank=20.0),
        _row("CCC", all_rank=75.0),
        _row("DDD", all_rank=5.0),
    ]

    view = build_trader_view(_manifest(), rows, top=2)

    assert view.universe == "ALL"
    assert view.eligible_count == 4
    assert [row.ticker for row in view.strong] == ["AAA", "CCC"]
    assert [row.ticker for row in view.weak] == ["DDD", "BBB"]


def test_viop_view_filters_universe_and_uses_viop_rank():
    rows = [
        _row("AAA", all_rank=95.0, viop_rank=10.0, is_viop=True),
        _row("BBB", all_rank=20.0, viop_rank=90.0, is_viop=True),
        _row("CCC", all_rank=99.0, is_viop=False),
        _row("DDD", all_rank=5.0, viop_rank=50.0, is_viop=True),
    ]

    view = build_trader_view(_manifest(), rows, viop=True, top=2)

    assert view.universe == "VIOP"
    assert view.eligible_count == 3
    assert [row.ticker for row in view.strong] == ["BBB", "DDD"]
    assert [row.ticker for row in view.weak] == ["AAA", "DDD"]


def test_ineligible_rows_are_excluded():
    rows = [
        _row("AAA", all_rank=95.0),
        _row("BBB", all_rank=80.0, data_status="INSUFFICIENT_TRADING_DATA"),
        _row("CCC", all_rank=70.0, ranking_status="NOT_AVAILABLE"),
        _row("DDD", all_rank=60.0, core_ready=False),
    ]

    view = build_trader_view(_manifest(), rows, top=10)

    assert view.eligible_count == 1
    assert [row.ticker for row in view.strong] == ["AAA"]
    assert [row.ticker for row in view.weak] == ["AAA"]


def test_vcp_does_not_affect_momentum_ordering():
    rows = [
        _row(
            "AAA",
            all_rank=90.0,
            vcp_status="NOT_AVAILABLE",
            vcp_state=None,
        ),
        _row(
            "BBB",
            all_rank=10.0,
            vcp_status="OK",
            vcp_state="BREAKOUT",
        ),
        _row("CCC", all_rank=70.0),
        _row("DDD", all_rank=30.0),
    ]

    view = build_trader_view(_manifest(), rows, top=2)

    assert [row.ticker for row in view.strong] == ["AAA", "CCC"]
    assert [row.ticker for row in view.weak] == ["BBB", "DDD"]


def test_non_pass_manifest_fails_closed():
    rows = [
        _row("AAA", all_rank=95.0),
        _row("BBB", all_rank=20.0),
        _row("CCC", all_rank=75.0),
        _row("DDD", all_rank=5.0),
    ]

    with pytest.raises(TraderViewError, match="not PASS"):
        build_trader_view(
            _manifest(status="FAIL"),
            rows,
        )


def test_dry_run_manifest_fails_closed():
    rows = [
        _row("AAA", all_rank=95.0),
        _row("BBB", all_rank=20.0),
        _row("CCC", all_rank=75.0),
        _row("DDD", all_rank=5.0),
    ]

    with pytest.raises(TraderViewError, match="non-dry-run"):
        build_trader_view(
            _manifest(dry_run=True),
            rows,
        )


def test_as_of_mismatch_fails_closed():
    rows = [
        _row("AAA", all_rank=95.0),
        _row("BBB", all_rank=20.0),
        _row("CCC", all_rank=75.0),
        _row("DDD", all_rank=5.0),
    ]
    rows[2]["as_of"] = "2026-10-08"

    with pytest.raises(TraderViewError, match="as_of"):
        build_trader_view(_manifest(), rows)


def test_published_count_mismatch_fails_closed():
    rows = [
        _row("AAA", all_rank=95.0),
        _row("BBB", all_rank=20.0),
    ]

    with pytest.raises(TraderViewError, match="row count"):
        build_trader_view(
            _manifest(securities_published=4),
            rows,
        )


def test_load_trader_view_reads_only_published_json(tmp_path):
    rows = [
        _row("AAA", all_rank=95.0),
        _row("BBB", all_rank=20.0),
        _row("CCC", all_rank=75.0),
        _row("DDD", all_rank=5.0),
    ]

    (tmp_path / "manifest.json").write_text(
        json.dumps(_manifest()),
        encoding="utf-8",
    )
    (tmp_path / "screener.json").write_text(
        json.dumps(rows),
        encoding="utf-8",
    )

    view = load_trader_view(tmp_path, top=1)

    assert view.as_of == "2026-10-09"
    assert [row.ticker for row in view.strong] == ["AAA"]
    assert [row.ticker for row in view.weak] == ["DDD"]


def test_top_must_be_positive():
    rows = [
        _row("AAA", all_rank=95.0),
        _row("BBB", all_rank=20.0),
        _row("CCC", all_rank=75.0),
        _row("DDD", all_rank=5.0),
    ]

    with pytest.raises(TraderViewError, match="at least 1"):
        build_trader_view(_manifest(), rows, top=0)



def test_render_trader_view_is_descriptive():
    rows = [
        _row("AAA", all_rank=95.0, quality_all=90.0),
        _row("BBB", all_rank=20.0, quality_all=30.0),
        _row("CCC", all_rank=75.0, quality_all=70.0),
        _row("DDD", all_rank=5.0, quality_all=10.0),
    ]

    view = build_trader_view(
        _manifest(),
        rows,
        top=1,
    )

    output = render_trader_view(view)

    assert "LABYRINTH TRADER VIEW" in output
    assert "Universe: ALL" in output
    assert "STRONG MOMENTUM" in output
    assert "WEAK MOMENTUM" in output
    assert "AAA" in output
    assert "DDD" in output
    assert "not a buy/sell or long/short signal" in output.lower()
