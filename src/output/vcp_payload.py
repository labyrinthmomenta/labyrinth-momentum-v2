from __future__ import annotations

from dataclasses import asdict

from src.strategy.vcp_analysis import VCPAnalysisResult


def build_vcp_screener_fields(
    result: VCPAnalysisResult,
) -> dict:
    """Build compact descriptive VCP fields for screener publication."""

    return {
        "vcp_status": "OK",
        "vcp_status_message": None,
        "vcp_state": result.state.state.value,
        "vcp_confirmed_contractions": (
            result.geometry.confirmed_contraction_count
        ),
        "vcp_pivot": (
            result.geometry.pivot.price
            if result.geometry.pivot is not None
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


def build_vcp_detail_payload(
    result: VCPAnalysisResult,
) -> dict:
    """Build full audit-friendly VCP detail publication payload."""

    return {
        "status": "OK",
        "status_message": None,
        "state": result.state.as_dict(),
        "geometry": asdict(result.geometry),
        "features": result.features.as_dict(),
        "breakout": result.breakout.as_dict(),
        "follow_through": result.follow_through.as_dict(),
        "swings": asdict(result.swings),
    }


def unavailable_vcp_screener_fields(
    message: str | None = None,
) -> dict:
    """Build stable screener fields when VCP analysis is unavailable."""

    return {
        "vcp_status": "NOT_AVAILABLE",
        "vcp_status_message": message,
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


def unavailable_vcp_detail_payload(
    message: str | None = None,
) -> dict:
    """Build stable detail payload when VCP analysis is unavailable."""

    return {
        "status": "NOT_AVAILABLE",
        "status_message": message,
        "state": None,
        "geometry": None,
        "features": None,
        "breakout": None,
        "follow_through": None,
        "swings": None,
    }
