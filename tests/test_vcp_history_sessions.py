from datetime import date
from types import SimpleNamespace

from src.research.vcp_replay import build_replay_snapshot


AS_OF = date(2026, 7, 31)


def test_replay_snapshot_history_sessions_equals_causal_technical_bar_count():
    technical_bars = (
        SimpleNamespace(
            date=date(2026, 7, 27)
        ),
        SimpleNamespace(
            date=date(2026, 7, 28)
        ),
        SimpleNamespace(
            date=date(2026, 7, 29)
        ),
        SimpleNamespace(
            date=date(2026, 7, 30)
        ),
        SimpleNamespace(
            date=AS_OF
        ),
    )

    analysis = SimpleNamespace(
        technical_bars=technical_bars,

        state=SimpleNamespace(
            state=SimpleNamespace(
                value="VCP_CONTRACTING"
            )
        ),

        geometry=SimpleNamespace(
            confirmed_contraction_count=2,
            contractions=(
                SimpleNamespace(
                    depth_pct=18.0
                ),
                SimpleNamespace(
                    depth_pct=9.0
                ),
            ),
        ),

        validity=SimpleNamespace(
            structurally_valid=True,
            final_to_first_depth_ratio=0.50,
            decreasing_step_fraction=1.0,
        ),

        features=SimpleNamespace(
            range_5_pct=4.0,
            true_range_compression_10_40=0.80,
            final_contraction_volume_ratio_50=0.70,
            distance_to_pivot_pct=-3.0,
            distance_to_pivot_atr=-1.0,
        ),

        base_features=SimpleNamespace(
            base_duration_sessions=30,
            base_depth_pct=18.0,
            base_atr_compression_ratio=0.80,
            base_volume_dryup_ratio=0.70,
        ),

        breakout=SimpleNamespace(
            pivot_price=120.0,
            first_intraday_breach_date=None,
            first_close_break_date=None,
            pivot_broken_by_close=False,
            breakout_volume_ratio_20=None,
        ),
    )

    snapshot = build_replay_snapshot(
        security_id=1,
        ticker="TEST",
        as_of=AS_OF,
        analysis=analysis,
    )

    assert snapshot.history_sessions == len(
        technical_bars
    )

    assert snapshot.history_sessions == 5
