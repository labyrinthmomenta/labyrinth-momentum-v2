from datetime import date
from pathlib import Path

from src.validation.regression import reconstruct_v1_12_1_from_detail


def test_a1cap_v1_12_1_reconstruction_matches_published_json():
    fixture = Path(__file__).parent / "fixtures" / "A1CAP.json"
    result = reconstruct_v1_12_1_from_detail(fixture, as_of=date(2026, 9, 21))

    assert result.ticker == "A1CAP"
    assert result.window_start == "2025-09"
    assert result.window_end == "2026-08"
    assert result.observations == 251
    assert result.negative_days == 136
    assert result.positive_days == 111
    assert result.flat_days == 4
    assert result.momentum_match
    assert result.fip_match
    assert abs(result.momentum - (-0.156294)) < 1e-6
    assert abs(result.fip - (-0.099602)) < 1e-6
