"""Tests for conviction -> exposure sizing curves."""

import pytest

from trade_regime.sizing import (
    STAND_DOWN_FLOOR,
    exposure_scale,
    sleeve_scale,
    sleeve_scales,
    stand_down,
)


def test_stand_down_floor():
    assert stand_down(STAND_DOWN_FLOOR - 0.1) is True
    assert stand_down(STAND_DOWN_FLOOR) is False
    assert stand_down(100.0) is False


def test_exposure_scale_boundaries():
    assert exposure_scale(0.0) == 0.0
    assert exposure_scale(24.9) == 0.0
    assert exposure_scale(25.0) == pytest.approx(0.2)  # re-enter small
    assert exposure_scale(100.0) == pytest.approx(1.0)
    assert exposure_scale(62.5) == pytest.approx(0.6)


def test_exposure_scale_monotone():
    prev = -1.0
    for c in range(0, 101):
        v = exposure_scale(float(c))
        assert v >= prev
        prev = v


def test_mean_reversion_shuts_first():
    # Dead below 40 while trend still runs.
    assert sleeve_scale("mean_reversion", 39.0) == 0.0
    assert sleeve_scale("trend", 39.0) > 0.0
    assert sleeve_scale("mean_reversion", 50.0) == pytest.approx(0.3333, abs=1e-4)
    assert sleeve_scale("mean_reversion", 70.0) == pytest.approx(1.0)
    # Ordering holds through the danger zone (conviction 25-57): mr never
    # exceeds trend while conviction is low.  (mr ramps (c-40)/30 vs trend
    # c/100; they cross at c≈57 — above that both sleeves are rebuilding.)
    for c in range(25, 58):
        assert sleeve_scale("mean_reversion", float(c)) <= sleeve_scale("trend", float(c))


def test_trend_tapers_linearly():
    assert sleeve_scale("trend", 50.0) == pytest.approx(0.5)
    assert sleeve_scale("trend", 100.0) == pytest.approx(1.0)
    assert sleeve_scale("trend", 25.0) == pytest.approx(0.25)


def test_short_vol_needs_high_conviction():
    assert sleeve_scale("short_vol", 64.9) == 0.0
    assert sleeve_scale("short_vol", 65.0) == 0.0
    assert sleeve_scale("short_vol", 77.5) == pytest.approx(0.5)
    assert sleeve_scale("short_vol", 90.0) == pytest.approx(1.0)
    # short_vol is the last to turn on: at 70, mr is full but sv is dead.
    assert sleeve_scale("mean_reversion", 70.0) == 1.0
    assert sleeve_scale("short_vol", 70.0) == pytest.approx(0.2)


def test_stand_down_zeroes_everything():
    scales = sleeve_scales(10.0)
    assert scales["stand_down"] is True
    assert scales["exposure_scale"] == 0.0
    assert all(v == 0.0 for v in scales["sleeves"].values())


def test_sleeve_scales_bundle():
    scales = sleeve_scales(80.0)
    assert scales["stand_down"] is False
    assert set(scales["sleeves"]) == {"trend", "mean_reversion", "short_vol"}
    assert all(0.0 <= v <= 1.0 for v in scales["sleeves"].values())


def test_unknown_sleeve_raises():
    with pytest.raises(ValueError):
        sleeve_scale("crypto_moon", 80.0)
