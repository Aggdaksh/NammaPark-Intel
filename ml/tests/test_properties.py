from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ml.features.network import compute_blockage_fraction, compute_bpr_delay
from ml.pipeline.etl import Validator


@given(
    lat=st.floats(min_value=10.0, max_value=16.0, allow_nan=False, allow_infinity=False),
    lon=st.floats(min_value=75.0, max_value=81.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=500)
def test_coordinate_validator_accept_reject_correctness(lat: float, lon: float) -> None:
    validator = Validator()
    expected = 12.7 <= lat <= 13.2 and 77.3 <= lon <= 77.8 and (lat, lon) != (0.0, 0.0)
    assert validator.validate_coordinates(lat, lon) is expected


@given(
    speed_kph=st.floats(min_value=1.0, max_value=120.0, allow_nan=False, allow_infinity=False),
    length_m=st.floats(min_value=1.0, max_value=5000.0, allow_nan=False, allow_infinity=False),
    blockage_fraction=st.floats(min_value=0.001, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=500)
def test_bpr_delay_non_negative(speed_kph: float, length_m: float, blockage_fraction: float) -> None:
    delay = compute_bpr_delay(speed_kph, length_m, blockage_fraction)
    assert delay >= 0.0
    assert math.isfinite(delay)


@given(
    severity_factor=st.floats(min_value=0.001, max_value=2.0, allow_nan=False, allow_infinity=False),
    lane_count=st.integers(min_value=1, max_value=8),
)
@settings(max_examples=500)
def test_blockage_fraction_range_invariant(severity_factor: float, lane_count: int) -> None:
    blockage = compute_blockage_fraction(severity_factor, lane_count)
    assert 0.0 < blockage <= 1.0


def test_hypothesis_is_active() -> None:
    pytest.importorskip("hypothesis")
