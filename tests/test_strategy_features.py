from datetime import date, timedelta
import math
from statistics import fmean, median

from src.calculation.engine import PriceBar
from src.strategy.features import compute_strategy_features


def bars_from_values(
    closes: list[float],
    volumes: list[float | None] | None = None,
) -> list[PriceBar]:
    if volumes is None:
        volumes = [1000.0] * len(closes)

    assert len(closes) == len(volumes)

    start = date(2025, 1, 1)

    return [
        PriceBar(
            date=start + timedelta(days=i),
            open=close,
            high=close + 1.0,
            low=max(0.01, close - 1.0),
            close=close,
            volume=volume,
        )
        for i, (close, volume)
        in enumerate(zip(closes, volumes))
    ]


def test_trend_features_use_exact_sma_windows():
    closes = [
        100.0 + i * 0.5
        for i in range(220)
    ]

    features = compute_strategy_features(
        bars_from_values(closes)
    )

    expected_sma50 = fmean(
        closes[-50:]
    )

    expected_sma150 = fmean(
        closes[-150:]
    )

    expected_sma200 = fmean(
        closes[-200:]
    )

    assert math.isclose(
        features.sma50,
        expected_sma50,
        abs_tol=1e-12,
    )

    assert math.isclose(
        features.sma150,
        expected_sma150,
        abs_tol=1e-12,
    )

    assert math.isclose(
        features.sma200,
        expected_sma200,
        abs_tol=1e-12,
    )

    assert math.isclose(
        features.distance_to_sma50_pct,
        (
            closes[-1]
            / expected_sma50
            - 1.0
        ) * 100.0,
        abs_tol=1e-12,
    )

    assert math.isclose(
        features.distance_to_sma200_pct,
        (
            closes[-1]
            / expected_sma200
            - 1.0
        ) * 100.0,
        abs_tol=1e-12,
    )


def test_sma_slopes_compare_current_with_20_sessions_ago():
    closes = [
        100.0 + i
        for i in range(220)
    ]

    features = compute_strategy_features(
        bars_from_values(closes)
    )

    current_sma50 = fmean(
        closes[-50:]
    )

    previous_end = len(closes) - 20

    previous_sma50 = fmean(
        closes[
            previous_end - 50:
            previous_end
        ]
    )

    current_sma200 = fmean(
        closes[-200:]
    )

    previous_sma200 = fmean(
        closes[:200]
    )

    assert math.isclose(
        features.sma50_slope_20,
        (
            current_sma50
            / previous_sma50
            - 1.0
        ) * 100.0,
        abs_tol=1e-12,
    )

    assert math.isclose(
        features.sma200_slope_20,
        (
            current_sma200
            / previous_sma200
            - 1.0
        ) * 100.0,
        abs_tol=1e-12,
    )


def test_insufficient_history_returns_none_per_feature():
    closes = [
        100.0 + i
        for i in range(60)
    ]

    features = compute_strategy_features(
        bars_from_values(closes)
    )

    assert features.sma50 is not None
    assert features.sma150 is None
    assert features.sma200 is None

    assert features.distance_to_sma50_pct is not None
    assert features.distance_to_sma200_pct is None

    # SMA50 slope requires 50 + 20 closes.
    assert features.sma50_slope_20 is None
    assert features.sma200_slope_20 is None


def test_volume_and_turnover_features_use_fixed_windows():
    closes = [
        100.0
        for _ in range(26)
    ]

    volumes = [
        float(i)
        for i in range(1, 27)
    ]

    features = compute_strategy_features(
        bars_from_values(
            closes,
            volumes,
        )
    )

    expected_volume20 = median(
        volumes[-20:]
    )

    expected_turnover20 = median(
        [
            100.0 * volume
            for volume in volumes[-20:]
        ]
    )

    expected_rvol = (
        volumes[-1]
        / median(volumes[-21:-1])
    )

    expected_dryup = (
        median(volumes[-5:])
        / median(volumes[-25:-5])
    )

    assert math.isclose(
        features.median_volume_20,
        expected_volume20,
        abs_tol=1e-12,
    )

    assert math.isclose(
        features.median_turnover_20,
        expected_turnover20,
        abs_tol=1e-12,
    )

    assert math.isclose(
        features.rvol20,
        expected_rvol,
        abs_tol=1e-12,
    )

    assert math.isclose(
        features.volume_dryup_5_20,
        expected_dryup,
        abs_tol=1e-12,
    )


def test_volume_dryup_detects_recent_contraction():
    closes = [
        100.0
        for _ in range(25)
    ]

    volumes = (
        [1000.0] * 20
        + [200.0] * 5
    )

    features = compute_strategy_features(
        bars_from_values(
            closes,
            volumes,
        )
    )

    assert math.isclose(
        features.volume_dryup_5_20,
        0.20,
        abs_tol=1e-12,
    )


def test_down_volume_share_uses_volume_on_negative_close_days():
    closes = [100.0]

    for i in range(20):
        if i % 2 == 0:
            closes.append(
                closes[-1] + 1.0
            )
        else:
            closes.append(
                closes[-1] - 1.0
            )

    volumes = [
        100.0
        for _ in closes
    ]

    features = compute_strategy_features(
        bars_from_values(
            closes,
            volumes,
        )
    )

    # 10 of the last 20 sessions are down days,
    # all with equal volume.
    assert math.isclose(
        features.down_volume_share_20,
        0.50,
        abs_tol=1e-12,
    )


def test_missing_volume_does_not_break_price_structure():
    closes = [
        100.0 + i * 0.1
        for i in range(220)
    ]

    volumes = [
        1000.0
        for _ in closes
    ]

    volumes[-1] = None

    features = compute_strategy_features(
        bars_from_values(
            closes,
            volumes,
        )
    )

    assert features.sma50 is not None
    assert features.sma150 is not None
    assert features.sma200 is not None

    assert features.median_volume_20 is None
    assert features.median_turnover_20 is None
    assert features.rvol20 is None
    assert features.volume_dryup_5_20 is None
    assert features.down_volume_share_20 is None
