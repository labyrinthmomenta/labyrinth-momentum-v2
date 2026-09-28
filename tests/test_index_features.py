from datetime import date, timedelta

from src.calculation.engine import PriceBar
from src.strategy.index_features import (
    compute_index_features,
    contiguous_trading_tail,
)


class EveryDayCalendar:
    def is_trading_day(self, day):
        return True


def make_bars(
    count: int,
    *,
    start: date = date(2026, 1, 1),
) -> list[PriceBar]:
    bars = []

    close = 100.0

    for i in range(count):
        close *= 1.001

        bars.append(
            PriceBar(
                date=start + timedelta(days=i),
                open=close,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=None,
            )
        )

    return bars


def test_contiguous_tail_stops_at_nearest_missing_session():
    calendar = EveryDayCalendar()

    bars = make_bars(200)

    missing_day = bars[100].date

    bars = [
        bar
        for bar in bars
        if bar.date != missing_day
    ]

    tail, gap = contiguous_trading_tail(
        bars,
        calendar,
        as_of=date(2026, 7, 19),
    )

    assert gap == missing_day

    assert tail[0].date == (
        missing_day
        + timedelta(days=1)
    )

    assert len(tail) == 99


def test_momentum_requires_window_plus_one_closes():
    calendar = EveryDayCalendar()

    bars_126 = make_bars(126)

    features = compute_index_features(
        bars_126,
        calendar,
        as_of=bars_126[-1].date,
    )

    assert features.momentum_126 is None

    bars_127 = make_bars(127)

    features = compute_index_features(
        bars_127,
        calendar,
        as_of=bars_127[-1].date,
    )

    assert features.momentum_126 is not None


def test_186_contiguous_closes_support_regime_v1_windows():
    calendar = EveryDayCalendar()

    bars = make_bars(186)

    features = compute_index_features(
        bars,
        calendar,
        as_of=bars[-1].date,
    )

    assert features.contiguous_observations == 186

    assert features.momentum_21 is not None
    assert features.momentum_63 is not None
    assert features.momentum_126 is not None

    assert features.sma50 is not None
    assert features.sma150 is not None

    assert features.momentum_252 is None
    assert features.sma200 is None
    assert features.sma200_slope_20 is None


def test_gap_before_tail_does_not_get_silently_skipped():
    calendar = EveryDayCalendar()

    bars = make_bars(300)

    missing_day = bars[113].date

    bars = [
        bar
        for bar in bars
        if bar.date != missing_day
    ]

    features = compute_index_features(
        bars,
        calendar,
        as_of=bars[-1].date,
    )

    # 300 total intended days:
    # gap at index 113,
    # tail is index 114 through 299 = 186 closes.
    assert features.contiguous_observations == 186
    assert features.last_gap_date == missing_day

    assert features.momentum_126 is not None
    assert features.momentum_252 is None

    assert features.sma150 is not None
    assert features.sma200 is None


def test_as_of_excludes_future_bars():
    calendar = EveryDayCalendar()

    bars = make_bars(200)

    as_of = bars[149].date

    features = compute_index_features(
        bars,
        calendar,
        as_of=as_of,
    )

    assert features.total_observations == 150
    assert features.contiguous_observations == 150
    assert features.close == bars[149].close

    assert features.sma150 is not None
    assert features.sma200 is None
