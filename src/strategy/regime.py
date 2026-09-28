from __future__ import annotations

from dataclasses import asdict, dataclass

from src.strategy.index_features import IndexFeatures
from src.strategy.market_context import MarketBreadth


@dataclass(frozen=True)
class MarketRegimeComponents:
    """Descriptive market-context classification.

    This layer does not create Long/Short signals.

    Thresholds intentionally use only natural reference
    points:
      - zero for momentum / distance
      - 50% for market breadth majority

    More optimized thresholds belong to later historical
    validation, not this base classification layer.
    """

    xu030_short_trend: str
    xu030_medium_backdrop: str

    xu100_short_trend: str
    xu100_medium_backdrop: str

    relative_leadership: str

    breadth_state: str
    long_term_breadth_state: str

    breadth_change_state: str

    def as_dict(self) -> dict:
        return asdict(self)


def _short_trend(
    features: IndexFeatures,
) -> str:
    required = (
        features.momentum_21,
        features.momentum_63,
        features.distance_to_sma50_pct,
    )

    if any(value is None for value in required):
        return "INSUFFICIENT_DATA"

    if (
        features.momentum_21 > 0
        and features.momentum_63 > 0
        and features.distance_to_sma50_pct > 0
    ):
        return "POSITIVE"

    if (
        features.momentum_21 < 0
        and features.momentum_63 < 0
        and features.distance_to_sma50_pct < 0
    ):
        return "NEGATIVE"

    return "MIXED"


def _medium_backdrop(
    features: IndexFeatures,
) -> str:
    if (
        features.momentum_126 is None
        or features.close is None
        or features.sma150 is None
    ):
        return "INSUFFICIENT_DATA"

    distance_sma150 = (
        features.close
        / features.sma150
        - 1.0
    )

    if (
        features.momentum_126 > 0
        and distance_sma150 > 0
    ):
        return "POSITIVE"

    if (
        features.momentum_126 < 0
        and distance_sma150 < 0
    ):
        return "NEGATIVE"

    return "MIXED"


def _relative_leadership(
    xu030: IndexFeatures,
    xu100: IndexFeatures,
) -> str:
    values_30 = (
        xu030.momentum_21,
        xu030.momentum_63,
        xu030.momentum_126,
        xu030.distance_to_sma50_pct,
    )

    values_100 = (
        xu100.momentum_21,
        xu100.momentum_63,
        xu100.momentum_126,
        xu100.distance_to_sma50_pct,
    )

    if (
        any(value is None for value in values_30)
        or any(value is None for value in values_100)
    ):
        return "INSUFFICIENT_DATA"

    comparisons = [
        left > right
        for left, right
        in zip(values_30, values_100)
    ]

    reverse = [
        left < right
        for left, right
        in zip(values_30, values_100)
    ]

    if all(comparisons):
        return "XU030_LEADS"

    if all(reverse):
        return "XU100_LEADS"

    return "MIXED"


def _breadth_state(
    breadth: MarketBreadth,
) -> str:
    values = (
        breadth.momentum_21_positive_pct,
        breadth.momentum_63_positive_pct,
        breadth.above_sma50_pct,
    )

    if any(value is None for value in values):
        return "INSUFFICIENT_DATA"

    if all(value > 50.0 for value in values):
        return "BROAD_POSITIVE"

    if all(value < 50.0 for value in values):
        return "BROAD_NEGATIVE"

    return "MIXED"


def _long_term_breadth_state(
    breadth: MarketBreadth,
) -> str:
    value = breadth.above_sma200_pct

    if value is None:
        return "INSUFFICIENT_DATA"

    if value > 50.0:
        return "POSITIVE"

    if value < 50.0:
        return "NEGATIVE"

    return "NEUTRAL"


def _breadth_change_state(
    breadth: MarketBreadth,
) -> str:
    positive_pct = (
        breadth.acceleration_21_63_positive_pct
    )

    median_accel = (
        breadth.acceleration_21_63_median
    )

    if (
        positive_pct is None
        or median_accel is None
    ):
        return "INSUFFICIENT_DATA"

    if (
        positive_pct > 50.0
        and median_accel > 0
    ):
        return "IMPROVING_RELATIVE"

    if (
        positive_pct < 50.0
        and median_accel < 0
    ):
        return "DETERIORATING_RELATIVE"

    return "MIXED"


def classify_market_regime_components(
    xu030: IndexFeatures,
    xu100: IndexFeatures,
    breadth: MarketBreadth,
) -> MarketRegimeComponents:
    """Classify descriptive market-context components."""

    return MarketRegimeComponents(
        xu030_short_trend=_short_trend(
            xu030
        ),

        xu030_medium_backdrop=_medium_backdrop(
            xu030
        ),

        xu100_short_trend=_short_trend(
            xu100
        ),

        xu100_medium_backdrop=_medium_backdrop(
            xu100
        ),

        relative_leadership=_relative_leadership(
            xu030,
            xu100,
        ),

        breadth_state=_breadth_state(
            breadth
        ),

        long_term_breadth_state=(
            _long_term_breadth_state(
                breadth
            )
        ),

        breadth_change_state=(
            _breadth_change_state(
                breadth
            )
        ),
    )
