"""Tests for interop adapter shapes (plain data, no sibling imports)."""

import json
import sys

import pytest

from trade_regime.adapters import (
    hedge_tilt_input,
    market_context_provider,
    risk_regime_input,
)
from trade_regime.presets import arbiter_kwargs
from trade_regime.arbiter import RegimeArbiter
from trade_regime.signals import read_all


@pytest.fixture()
def snapshot():
    arbiter = RegimeArbiter(**arbiter_kwargs("balanced"))
    comps = read_all({"regime": "EXPANSION", "z_score": 1.5},
                     {"regime": "BROADENING", "fragility": 0.1},
                     {"current_vol": 0.12, "vol_min": 0.10, "vol_max": 0.45})
    return arbiter.assess(comps)


def test_no_sibling_imports():
    """Adapters must not import trade_* packages -- stdlib-only guarantee."""
    for mod in ("trade_macro", "trade_breadth", "trade_volforecast",
                "trade_agents", "trade_risk", "trade_hedge"):
        assert mod not in sys.modules


def test_market_context_provider_shape(snapshot):
    ctx = market_context_provider(snapshot)
    assert ctx["source"] == "trade-regime"
    assert ctx["schema_version"] == 1
    assert ctx["conviction"] == pytest.approx(snapshot["conviction"])
    assert set(ctx["components"]) == {"macro", "breadth", "vol"}
    assert "supersede" in ctx["note"].lower() or "supersedes" in ctx["note"]
    json.dumps(ctx)


def test_market_context_provider_no_labels(snapshot):
    blob = json.dumps(market_context_provider(snapshot)).upper()
    assert "DEFENSIVE" not in blob and "CONSTRUCTIVE" not in blob


def test_risk_regime_input_advisory(snapshot):
    r = risk_regime_input(snapshot)
    assert r["source"] == "trade-regime"
    assert r["schema_version"] == 1
    assert 0.0 <= r["exposure_scale_advisory"] <= 1.0
    assert "advisory" in r["note"].lower()
    assert r["vol_sub_conviction"] is not None
    json.dumps(r)


def test_hedge_tilt_input_direction(snapshot):
    h = hedge_tilt_input(snapshot)
    assert h["source"] == "trade-regime"
    assert -1.0 <= h["defensive_tilt"] <= 1.0
    # high conviction in the fixture -> lean aggressive (negative tilt)
    assert h["defensive_tilt"] < 0
    json.dumps(h)


def test_hedge_tilt_defensive_when_conviction_low():
    arbiter = RegimeArbiter(**arbiter_kwargs("balanced"))
    comps = read_all({"regime": "CONTRACTION", "z_score": -2.0},
                     {"regime": "NARROWING", "fragility": 0.9},
                     {"current_vol": 0.44, "vol_min": 0.10, "vol_max": 0.45,
                      "forecast_vol": 0.44})
    snap = arbiter.assess(comps)
    h = hedge_tilt_input(snap)
    assert h["defensive_tilt"] > 0


def test_all_adapters_carry_hysteresis_detail(snapshot):
    """Reason + prior conviction flow into all three adapters."""
    h = snapshot["hysteresis"]
    for out in (market_context_provider(snapshot),
                risk_regime_input(snapshot),
                hedge_tilt_input(snapshot)):
        assert out["hysteresis_state"] == h["state"]
        assert out["hysteresis_reason"] == h["reason"]
        assert out["hysteresis_prior_conviction"] == h["prior_conviction"]
        assert isinstance(out["hysteresis_reason"], str)
        json.dumps(out)


def test_hysteresis_fields_none_tolerant_without_hysteresis_block():
    """Missing hysteresis block -> None fields, never KeyError."""
    snapshot = {"conviction": 72.5, "composite_raw": 74.1,
                "timestamp": "2026-09-26T20:00:00+00:00",
                "snapshot_id": "abc123", "missing": [],
                "components": {}}
    for out in (market_context_provider(snapshot),
                risk_regime_input(snapshot),
                hedge_tilt_input(snapshot)):
        assert out["hysteresis_state"] is None
        assert out["hysteresis_reason"] is None
        assert out["hysteresis_prior_conviction"] is None
        json.dumps(out)


def test_market_context_provider_pinned_contract_keys(snapshot):
    """market_context_provider output matches the cross-repo contract."""
    keys = set(market_context_provider(snapshot))
    assert keys == {"source", "schema_version", "conviction",
                    "composite_raw", "timestamp", "snapshot_id", "missing",
                    "hysteresis_state", "hysteresis_reason",
                    "hysteresis_prior_conviction",
                    "exposure_scale_advisory", "components", "note"}
