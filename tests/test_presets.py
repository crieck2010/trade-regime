"""Tests for named risk postures."""

import pytest

from trade_regime.arbiter import RegimeArbiter
from trade_regime.presets import PRESETS, arbiter_kwargs, get_preset


def test_all_presets_present():
    assert sorted(PRESETS) == ["aggressive", "balanced", "conservative"]


def test_presets_carry_rationale():
    for name, p in PRESETS.items():
        assert p["rationale"].strip(), name
        assert p["description"].strip(), name


def test_preset_weights_positive_and_sane():
    for name, p in PRESETS.items():
        assert all(w > 0 for w in p["weights"].values()), name
        assert set(p["weights"]) == {"macro", "breadth", "vol"}, name


def test_conservative_slower_than_aggressive():
    cons = get_preset("conservative")
    aggr = get_preset("aggressive")
    assert cons["deadband"] > aggr["deadband"]
    assert cons["persistence_n"] > aggr["persistence_n"]
    assert cons["max_daily_change"] < aggr["max_daily_change"]
    assert cons["weights"]["macro"] > aggr["weights"]["macro"]


def test_unknown_preset_raises():
    with pytest.raises(ValueError):
        get_preset("reckless")


def test_get_preset_returns_copy():
    p = get_preset("balanced")
    p["weights"]["macro"] = 999.0
    assert get_preset("balanced")["weights"]["macro"] != 999.0


def test_arbiter_kwargs_builds_arbiter():
    for name in PRESETS:
        a = RegimeArbiter(**arbiter_kwargs(name))
        assert a.preset_name == name


def test_balanced_is_default_geometry():
    from trade_regime.arbiter import (DEFAULT_CONFIRM_BAND, DEFAULT_DEADBAND,
                                      DEFAULT_MAX_DAILY_CHANGE, DEFAULT_PERSISTENCE_N,
                                      DEFAULT_WEIGHTS)
    b = get_preset("balanced")
    assert b["weights"] == DEFAULT_WEIGHTS
    assert b["deadband"] == DEFAULT_DEADBAND
    assert b["confirm_band"] == DEFAULT_CONFIRM_BAND
    assert b["persistence_n"] == DEFAULT_PERSISTENCE_N
    assert b["max_daily_change"] == DEFAULT_MAX_DAILY_CHANGE
