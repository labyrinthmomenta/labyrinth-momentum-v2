from datetime import date, timedelta

from src.output.vcp_payload import (
    build_vcp_detail_payload,
    build_vcp_screener_fields,
    unavailable_vcp_detail_payload,
    unavailable_vcp_screener_fields,
)
from src.strategy.technical_prices import TechnicalPriceBar
from src.strategy.vcp_analysis import analyze_vcp
from src.strategy.vcp_state import VCPStateConfig


BASE_DATE = date(2026, 1, 2)


def _state_config() -> VCPStateConfig:
    return VCPStateConfig(
        tightening_range_5_max_pct=5.0,
        tightening_true_range_compression_max=0.75,
        tightening_final_volume_ratio_max=0.75,
        near_pivot_max_distance_pct=5.0,
        breakout_volume_expansion_min_ratio=1.50,
    )


def _bar(
    index: int,
    close: float,
) -> TechnicalPriceBar:
    day = BASE_DATE + timedelta(days=index)

    high = close * 1.02
    low = close * 0.98
    open_price = close * 0.995

    return TechnicalPriceBar(
        date=day,

        open=open_price,
        high=high,
        low=low,
        close=close,

        volume=1_000_000.0 + index * 10_000,

        raw_open=open_price,
        raw_high=high,
        raw_low=low,
        raw_close=close,
        adj_close=close,

        dividend=0.0,
        stock_split=0.0,

        adjustment_factor=1.0,
        adjustment_status="OK",
    )


def _analysis():
    closes = (
        100, 102, 104, 106, 108,
        110, 107, 104, 101, 98,
        100, 103, 106, 109, 112,
        109, 106, 103, 101, 99,
        101, 104, 107, 109, 111,
        109, 107, 105, 103, 102,
        104, 106, 108, 109, 110,
        108, 107, 106, 105, 104,
        105, 106, 107, 108, 109,
        110, 111, 112, 113, 114,
        113, 112, 111, 110, 109,
        110, 111, 112, 113, 115,
    )

    bars = tuple(
        _bar(index, float(close))
        for index, close in enumerate(closes)
    )

    return analyze_vcp(
        bars,
        state_config=_state_config(),
    )


def test_vcp_screener_fields_expose_compact_descriptive_result():
    result = _analysis()

    payload = build_vcp_screener_fields(
        result
    )

    assert payload == {
        "vcp_status": "OK",
        "vcp_status_message": None,
        "vcp_state": result.state.state.value,
        "vcp_confirmed_contractions": (
            result.geometry.confirmed_contraction_count
        ),
        "vcp_pivot": (
            result.geometry.pivot.price
            if result.geometry.pivot
            else None
        ),
        "vcp_distance_to_pivot_pct": (
            result.features.distance_to_pivot_pct
        ),
        "vcp_distance_to_pivot_atr": (
            result.features.distance_to_pivot_atr
        ),
        "vcp_range_5_pct": (
            result.features.range_5_pct
        ),
        "vcp_true_range_compression_10_40": (
            result.features.true_range_compression_10_40
        ),
        "vcp_final_contraction_volume_ratio_50": (
            result.features.final_contraction_volume_ratio_50
        ),
        "vcp_pivot_broken_by_close": (
            result.breakout.pivot_broken_by_close
        ),
        "vcp_breakout_volume_ratio_20": (
            result.breakout.breakout_volume_ratio_20
        ),
    }


def test_vcp_detail_payload_preserves_full_analysis_components():
    result = _analysis()

    payload = build_vcp_detail_payload(
        result
    )

    assert payload["status"] == "OK"
    assert payload["status_message"] is None

    assert payload["state"] == result.state.as_dict()
    assert payload["features"] == result.features.as_dict()
    assert payload["breakout"] == result.breakout.as_dict()
    assert (
        payload["follow_through"]
        == result.follow_through.as_dict()
    )

    assert (
        payload["geometry"]["confirmed_contraction_count"]
        == result.geometry.confirmed_contraction_count
    )

    assert (
        len(payload["swings"]["confirmed"])
        == len(result.swings.confirmed)
    )


def test_unavailable_vcp_screener_fields_keep_stable_schema():
    payload = unavailable_vcp_screener_fields(
        "insufficient history"
    )

    assert payload == {
        "vcp_status": "NOT_AVAILABLE",
        "vcp_status_message": "insufficient history",
        "vcp_state": None,
        "vcp_confirmed_contractions": None,
        "vcp_pivot": None,
        "vcp_distance_to_pivot_pct": None,
        "vcp_distance_to_pivot_atr": None,
        "vcp_range_5_pct": None,
        "vcp_true_range_compression_10_40": None,
        "vcp_final_contraction_volume_ratio_50": None,
        "vcp_pivot_broken_by_close": None,
        "vcp_breakout_volume_ratio_20": None,
    }


def test_unavailable_vcp_detail_payload_keeps_stable_schema():
    payload = unavailable_vcp_detail_payload(
        "provider unavailable"
    )

    assert payload == {
        "status": "NOT_AVAILABLE",
        "status_message": "provider unavailable",
        "state": None,
        "geometry": None,
        "features": None,
        "breakout": None,
        "follow_through": None,
        "swings": None,
    }
