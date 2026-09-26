"""Tests for fusion math and conviction hysteresis."""

import json

import pytest

from trade_regime.arbiter import (
    DEFAULT_WEIGHTS,
    SCHEMA_VERSION,
    RegimeArbiter,
    exposure_scale,
    fuse,
    validate_weights,
)
from trade_regime.signals import Component, ComponentUnavailable, read_all


def _comps(macro=75.0, breadth=75.0, vol=75.0):
    return {
        "macro": Component("macro", macro, {}),
        "breadth": Component("breadth", breadth, {}),
        "vol": Component("vol", vol, {}),
    }


# ------------------------------------------------------------------- fuse

def test_fuse_weighted_average():
    composite, contributions, missing = fuse(_comps(100.0, 50.0, 0.0))
    expected = 0.40 * 100 + 0.35 * 50 + 0.25 * 0
    assert composite == pytest.approx(expected)
    assert missing == []
    assert contributions["macro"]["weight"] == pytest.approx(0.40)


def test_fuse_renormalizes_on_missing():
    comps = _comps(80.0, 60.0, 0.0)
    comps["vol"] = ComponentUnavailable("vol", "no data")
    composite, contributions, missing = fuse(comps)
    assert missing == ["vol"]
    expected = (0.40 * 80 + 0.35 * 60) / 0.75
    assert composite == pytest.approx(expected, abs=0.01)
    assert contributions["macro"]["weight"] == pytest.approx(0.40 / 0.75, abs=1e-4)


def test_fuse_all_missing_neutral():
    comps = {n: ComponentUnavailable(n, "x") for n in ("macro", "breadth", "vol")}
    composite, contributions, missing = fuse(comps)
    assert composite == 50.0
    assert contributions == {}
    assert sorted(missing) == ["breadth", "macro", "vol"]


def test_fuse_extra_component_weighted():
    comps = _comps(50.0, 50.0, 50.0)
    comps["sentiment"] = Component("sentiment", 100.0, {})
    composite, contributions, missing = fuse(
        comps, {"macro": 0.4, "breadth": 0.3, "vol": 0.2, "sentiment": 0.1})
    assert composite == pytest.approx(55.0)  # 45 + 10


def test_validate_weights_rejects_nonsense():
    with pytest.raises(ValueError):
        validate_weights({})
    with pytest.raises(ValueError):
        validate_weights({"macro": -1.0})
    with pytest.raises(ValueError):
        validate_weights({"macro": 0.0, "breadth": 0.0})
    with pytest.raises(ValueError):
        validate_weights({"macro": "lots"})


def test_exposure_scale_advisory():
    assert exposure_scale(0) == 0.0
    assert exposure_scale(50) == 0.5
    assert exposure_scale(100) == 1.0
    assert exposure_scale(150) == 1.0  # clamped


# -------------------------------------------------------------- hysteresis

def _arbiter(**kw):
    kw.setdefault("preset_name", "test")
    return RegimeArbiter(**kw)


def test_first_assessment_initializes():
    a = _arbiter()
    snap = a.assess(_comps(80.0, 80.0, 80.0))
    assert snap["conviction"] == pytest.approx(80.0)
    assert snap["hysteresis"]["state"] == "updated"
    assert snap["hysteresis"]["reason"] == "initialization"
    assert snap["hysteresis"]["prior_conviction"] is None


def test_holds_within_deadband():
    a = _arbiter(deadband=10.0)
    a.assess(_comps(70.0, 70.0, 70.0))          # conviction = 70
    snap = a.assess(_comps(79.0, 79.0, 79.0))   # raw 79, delta +9
    assert snap["hysteresis"]["state"] == "held"
    assert snap["conviction"] == pytest.approx(70.0)
    assert "deadband" in snap["hysteresis"]["reason"]


def test_deadband_edge_holds():
    a = _arbiter(deadband=10.0)
    a.assess(_comps(70.0, 70.0, 70.0))
    snap = a.assess(_comps(80.0, 80.0, 80.0))   # delta exactly 10
    assert snap["hysteresis"]["state"] == "held"


def test_large_move_releases_immediately():
    a = _arbiter(deadband=10.0, confirm_band=20.0, max_daily_change=25.0)
    a.assess(_comps(70.0, 70.0, 70.0))
    snap = a.assess(_comps(40.0, 40.0, 40.0))   # delta -30 > confirm band
    assert snap["hysteresis"]["state"] == "updated"
    assert "confirm band" in snap["hysteresis"]["reason"]
    # rate-limited: 70 - 25 = 45, not 40
    assert snap["conviction"] == pytest.approx(45.0)


def test_rate_limit_caps_release():
    a = _arbiter(max_daily_change=10.0)
    a.assess(_comps(50.0, 50.0, 50.0))
    snap = a.assess(_comps(100.0, 100.0, 100.0))
    assert snap["conviction"] == pytest.approx(60.0)


def test_persistence_releases_stubborn_move():
    a = _arbiter(deadband=10.0, confirm_band=20.0, persistence_n=3)
    a.assess(_comps(70.0, 70.0, 70.0))
    s1 = a.assess(_comps(82.0, 82.0, 82.0))   # +12: beyond deadband, inside confirm
    assert s1["hysteresis"]["state"] == "held"
    assert "1/3" in s1["hysteresis"]["reason"]
    s2 = a.assess(_comps(83.0, 83.0, 83.0))
    assert s2["hysteresis"]["state"] == "held"
    assert "2/3" in s2["hysteresis"]["reason"]
    s3 = a.assess(_comps(84.0, 84.0, 84.0))
    assert s3["hysteresis"]["state"] == "updated"
    assert "persistent" in s3["hysteresis"]["reason"]


def test_persistence_direction_flip_resets():
    a = _arbiter(deadband=10.0, confirm_band=20.0, persistence_n=3)
    a.assess(_comps(70.0, 70.0, 70.0))
    a.assess(_comps(82.0, 82.0, 82.0))   # +1
    a.assess(_comps(83.0, 83.0, 83.0))   # +1 (count 2)
    s = a.assess(_comps(58.0, 58.0, 58.0))  # -12: opposite direction
    assert s["hysteresis"]["state"] == "held"
    assert "1/3" in s["hysteresis"]["reason"]  # counter restarted


def test_noise_wobble_holds():
    """Alternating small moves around the band edge never release."""
    a = _arbiter(deadband=10.0, confirm_band=20.0, persistence_n=3)
    a.assess(_comps(70.0, 70.0, 70.0))
    for raw in (82, 58, 83, 57, 82, 58):
        snap = a.assess(_comps(raw, raw, raw))
        assert snap["hysteresis"]["state"] == "held"
        assert snap["conviction"] == pytest.approx(70.0)


def test_constructor_validates_geometry():
    with pytest.raises(ValueError):
        RegimeArbiter(deadband=20.0, confirm_band=10.0)
    with pytest.raises(ValueError):
        RegimeArbiter(persistence_n=0)
    with pytest.raises(ValueError):
        RegimeArbiter(max_daily_change=0)


def test_memory_round_trip():
    a = _arbiter()
    a.assess(_comps(70.0, 70.0, 70.0))
    a.assess(_comps(82.0, 82.0, 82.0))  # persistence 1/3
    mem = a.memory_dict()
    b = _arbiter()
    b.restore(mem)
    s = b.assess(_comps(83.0, 83.0, 83.0))
    assert "2/3" in s["hysteresis"]["reason"]  # memory carried the count


def test_reset_clears_memory():
    a = _arbiter()
    a.assess(_comps(70.0, 70.0, 70.0))
    a.reset()
    assert a.conviction is None
    snap = a.assess(_comps(80.0, 80.0, 80.0))
    assert snap["hysteresis"]["reason"] == "initialization"


# --------------------------------------------------------------- snapshot

def test_snapshot_contract():
    a = _arbiter(preset_name="balanced")
    comps = read_all({"regime": "EXPANSION", "z_score": 1.0},
                     {"regime": "BROADENING", "fragility": 0.1},
                     {"current_vol": 0.12, "vol_min": 0.10, "vol_max": 0.45})
    snap = a.assess(comps, provenance={
        "input_snapshot_ids": {"macro": "m1"},
        "input_schema_versions": {"macro": 1}})
    assert snap["schema_version"] == SCHEMA_VERSION == 1
    for key in ("snapshot_id", "timestamp", "conviction", "composite_raw",
                "components", "weights_configured", "hysteresis",
                "exposure_scale", "missing", "provenance"):
        assert key in snap, key
    assert set(snap["components"]) == {"macro", "breadth", "vol"}
    assert snap["provenance"]["input_snapshot_ids"] == {"macro": "m1"}
    assert snap["provenance"]["preset"] == "balanced"
    assert 0.0 <= snap["conviction"] <= 100.0
    assert 0.0 <= snap["exposure_scale"] <= 1.0
    json.dumps(snap)  # contract: JSON-serializable


def test_snapshot_no_labels():
    """The authoritative design: numbers only, no labeled buckets."""
    a = _arbiter()
    snap = a.assess(_comps())
    blob = json.dumps(snap).upper()
    for label in ("DEFENSIVE", "CONSTRUCTIVE", "BULLISH", "BEARISH", "RISK-ON"):
        assert label not in blob


def test_assess_series_replays_in_order():
    a = _arbiter()
    series = [_comps(v, v, v) for v in (70.0, 70.0, 70.0)]
    snaps = a.assess_series(series)
    assert len(snaps) == 3
    assert all(s["conviction"] == pytest.approx(70.0) for s in snaps)
