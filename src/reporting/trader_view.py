"""Read-only trader view built from the published production screener.

This module intentionally does not recompute momentum, FIP, VCP, or rankings.
The published production JSON is the source of truth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


class TraderViewError(RuntimeError):
    """Raised when the published production payload is unsafe to present."""


@dataclass(frozen=True)
class TraderViewRow:
    ticker: str
    name: str | None
    sector: str | None
    is_viop: bool
    core_momentum_pct: float
    core_quality_pct: float | None
    momentum_126_pct: float | None
    momentum_63_pct: float | None
    momentum_21_pct: float | None
    acceleration_21_63: float | None
    acceleration_63_126: float | None
    fip_12_1: float | None
    vcp_status: str | None
    vcp_state: str | None


@dataclass(frozen=True)
class TraderView:
    as_of: str
    universe: str
    eligible_count: int
    strong: tuple[TraderViewRow, ...]
    weak: tuple[TraderViewRow, ...]


def _require_manifest_safe(manifest: Mapping[str, Any]) -> str:
    if manifest.get("status") != "PASS":
        raise TraderViewError(
            f"production manifest status is not PASS: {manifest.get('status')!r}"
        )

    if manifest.get("dry_run") is not False:
        raise TraderViewError("Trader View requires a non-dry-run production manifest")

    as_of = manifest.get("as_of")
    if not isinstance(as_of, str) or not as_of:
        raise TraderViewError("production manifest has no valid as_of")

    return as_of


def _validate_publication_consistency(
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
) -> None:
    expected = manifest.get("securities_published")
    if expected is not None and expected != len(rows):
        raise TraderViewError(
            "published screener row count does not match manifest: "
            f"manifest={expected!r} screener={len(rows)}"
        )

    mismatched = sorted(
        str(row.get("ticker", "<UNKNOWN>"))
        for row in rows
        if row.get("as_of") != as_of
    )
    if mismatched:
        preview = ", ".join(mismatched[:5])
        raise TraderViewError(
            "screener as_of does not match production manifest "
            f"for {len(mismatched)} row(s): {preview}"
        )


def _eligible(row: Mapping[str, Any], *, viop: bool) -> bool:
    if row.get("data_status") != "OK":
        return False
    if row.get("ranking_status") != "OK":
        return False
    if row.get("core_ready") is not True:
        return False
    if viop and row.get("is_viop") is not True:
        return False
    return True


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _build_row(
    row: Mapping[str, Any],
    *,
    viop: bool,
) -> TraderViewRow | None:
    suffix = "viop" if viop else "all"

    core_momentum = _to_float(row.get(f"core_momentum_pct_{suffix}"))
    if core_momentum is None:
        return None

    return TraderViewRow(
        ticker=str(row["ticker"]),
        name=row.get("name"),
        sector=row.get("sector"),
        is_viop=bool(row.get("is_viop")),
        core_momentum_pct=core_momentum,
        core_quality_pct=_to_float(row.get(f"core_quality_pct_{suffix}")),
        momentum_126_pct=_to_float(row.get(f"momentum_126_pct_{suffix}")),
        momentum_63_pct=_to_float(row.get(f"momentum_63_pct_{suffix}")),
        momentum_21_pct=_to_float(row.get(f"momentum_21_pct_{suffix}")),
        acceleration_21_63=_to_float(
            row.get(f"acceleration_21_63_{suffix}")
        ),
        acceleration_63_126=_to_float(
            row.get(f"acceleration_63_126_{suffix}")
        ),
        fip_12_1=_to_float(row.get("fip_12_1")),
        vcp_status=row.get("vcp_status"),
        vcp_state=row.get("vcp_state"),
    )


def build_trader_view(
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    viop: bool = False,
    top: int = 10,
) -> TraderView:
    """Build a descriptive strong/weak momentum view from published ranks."""

    if top < 1:
        raise TraderViewError("top must be at least 1")

    as_of = _require_manifest_safe(manifest)
    _validate_publication_consistency(manifest, rows, as_of=as_of)

    candidates: list[TraderViewRow] = []

    for row in rows:
        if not _eligible(row, viop=viop):
            continue

        built = _build_row(row, viop=viop)
        if built is not None:
            candidates.append(built)

    strong = tuple(
        sorted(
            candidates,
            key=lambda item: (-item.core_momentum_pct, item.ticker),
        )[:top]
    )

    weak = tuple(
        sorted(
            candidates,
            key=lambda item: (item.core_momentum_pct, item.ticker),
        )[:top]
    )

    return TraderView(
        as_of=as_of,
        universe="VIOP" if viop else "ALL",
        eligible_count=len(candidates),
        strong=strong,
        weak=weak,
    )


def load_trader_view(
    data_dir: str | Path = "docs/data",
    *,
    viop: bool = False,
    top: int = 10,
) -> TraderView:
    """Load the immutable published JSON artifacts and build Trader View."""

    root = Path(data_dir)
    manifest_path = root / "manifest.json"

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TraderViewError(
            f"could not read production manifest: {manifest_path}"
        ) from exc

    screener_name = manifest.get("files", {}).get("screener", "screener.json")
    screener_path = root / screener_name

    try:
        rows = json.loads(screener_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TraderViewError(
            f"could not read production screener: {screener_path}"
        ) from exc

    if not isinstance(rows, list):
        raise TraderViewError("production screener payload must be a list")

    return build_trader_view(
        manifest,
        rows,
        viop=viop,
        top=top,
    )


def _format_percentile(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}"


def _format_fip(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.3f}"


def _format_vcp(row: TraderViewRow) -> str:
    if row.vcp_status != "OK":
        return "N/A"
    return row.vcp_state or "OK"


def _render_rows(rows: Sequence[TraderViewRow]) -> list[str]:
    if not rows:
        return ["(none)"]

    lines = [
        (
            f"{'Ticker':<10}"
            f"{'Mom%':>7}"
            f"{'FIP-Q%':>8}"
            f"{'M126%':>8}"
            f"{'M63%':>8}"
            f"{'M21%':>8}"
            f"{'FIP12-1':>11}"
            f"  VCP"
        )
    ]

    for row in rows:
        lines.append(
            f"{row.ticker:<10}"
            f"{_format_percentile(row.core_momentum_pct):>7}"
            f"{_format_percentile(row.core_quality_pct):>8}"
            f"{_format_percentile(row.momentum_126_pct):>8}"
            f"{_format_percentile(row.momentum_63_pct):>8}"
            f"{_format_percentile(row.momentum_21_pct):>8}"
            f"{_format_fip(row.fip_12_1):>11}"
            f"  {_format_vcp(row)}"
        )

    return lines


def render_trader_view(view: TraderView) -> str:
    """Render a compact descriptive terminal view."""

    lines = [
        "LABYRINTH TRADER VIEW",
        f"As of: {view.as_of}",
        f"Universe: {view.universe}",
        f"Eligible: {view.eligible_count}",
        "DESCRIPTIVE ONLY - not a buy/sell or long/short signal.",
        "",
        "STRONG MOMENTUM",
        *_render_rows(view.strong),
        "",
        "WEAK MOMENTUM",
        *_render_rows(view.weak),
    ]

    return "\n".join(lines)
