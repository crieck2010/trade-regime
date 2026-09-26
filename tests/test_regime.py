"""Contract tests: the snapshot shape downstream code programs against."""

import json

import pytest

from trade_regime.arbiter import SCHEMA_VERSION, RegimeArbiter, fuse
from trade_regime.presets import arbiter_kwargs
from trade_regime.signals import Component, ComponentUnavailable, read_all


def _snapshot(**kw):
    arbiter = RegimeArbiter(**arbiter_kwargs("balanced"))
    comps = read_all({"regime": "EXPANSION", "z_score": 1.0},
                     {"regime": "BROADENING", "fragility": 0.2},
                     {"current_vol": 0.13, "vol_min": 0.10, "vol_max": 0.45})
    return arbiter.assess(comps, **kw)


def test_schema_version_is_1():
    assert SCHEMA_VERSION == 1
    assert _snapshot()["schema_version"] == 1


def test_required_top_level_keys():
    snap = _snapshot()
    assert set(("schema_version", "snapshot_id", "timestamp", "conviction",
                "composite_raw", "components", "weights_configured",
                "hysteresis", "exposure_scale", "missing",
                "provenance")) <= set(snap)


def test_component_entry_shape():
    snap = _snapshot()
    for name, c in snap["components"].items():
        assert set(("sub_conviction", "weight", "contribution",
                    "detail")) <= set(c), name
        assert 0.0 <= c["sub_conviction"] <= 100.0
    total_w = sum(c["weight"] for c in snap["components"].values())
    assert total_w == pytest.approx(1.0)


def test_hysteresis_entry_shape():
    h = _snapshot()["hysteresis"]
    assert h["state"] in ("held", "updated")
    assert isinstance(h["reason"], str) and h["reason"]
    for key in ("prior_conviction", "deadband", "confirm_band",
                "persistence", "max_daily_change"):
        assert key in h, key


def test_json_round_trip_stable():
    snap = _snapshot()
    assert json.loads(json.dumps(snap))["snapshot_id"] == snap["snapshot_id"]


def test_snapshot_ids_unique():
    assert _snapshot()["snapshot_id"] != _snapshot()["snapshot_id"]


def test_fuse_contributions_sum_to_composite():
    comps = {"macro": Component("macro", 80.0, {}),
             "breadth": Component("breadth", 60.0, {}),
             "vol": ComponentUnavailable("vol", "x")}
    composite, contributions, _ = fuse(comps)
    total = sum(c["contribution"] for c in contributions.values())
    assert total == pytest.approx(composite, abs=0.02)  # rounding tolerance
