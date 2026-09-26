"""Tests for component transforms: 0-100 sub-convictions."""

import pytest

from trade_regime.signals import (
    Component,
    ComponentUnavailable,
    breadth_component,
    macro_component,
    read_all,
    vol_component,
)


# ---------------------------------------------------------------- breadth

def test_breadth_broadening_base():
    c = breadth_component({"regime": "BROADENING", "fragility": 0.0})
    assert isinstance(c, Component)
    assert c.sub_conviction == 75.0


def test_breadth_narrowing_base():
    c = breadth_component({"regime": "NARROWING", "fragility": 0.0})
    assert c.sub_conviction == 25.0


def test_breadth_neutral_base():
    c = breadth_component({"regime": "NEUTRAL"})
    assert c.sub_conviction == 50.0


def test_breadth_fragility_drag():
    c = breadth_component({"regime": "BROADENING", "fragility": 1.0})
    assert c.sub_conviction == 25.0  # 75 - 50
    assert c.detail["fragility_drag"] == 50.0


def test_breadth_fragility_clamped():
    c = breadth_component({"regime": "NARROWING", "fragility": 99.0})
    assert c.sub_conviction == 0.0  # clamped, never negative


def test_breadth_thrust_bonus():
    plain = breadth_component({"regime": "BROADENING", "fragility": 0.0})
    thrust = breadth_component({"regime": "BROADENING", "fragility": 0.0,
                                "thrusts": True})
    assert thrust.sub_conviction == plain.sub_conviction + 10.0


def test_breadth_divergence_penalty():
    plain = breadth_component({"regime": "NEUTRAL"})
    div = breadth_component({"regime": "NEUTRAL", "divergence_warning": True})
    assert div.sub_conviction == plain.sub_conviction - 10.0


def test_breadth_unknown_regime_unavailable():
    c = breadth_component({"regime": "BULLISH"})
    assert isinstance(c, ComponentUnavailable)
    assert not c


def test_breadth_missing_snapshot_unavailable():
    assert isinstance(breadth_component(None), ComponentUnavailable)


def test_breadth_unparseable_fragility_unavailable():
    c = breadth_component({"regime": "NEUTRAL", "fragility": "lots"})
    assert isinstance(c, ComponentUnavailable)


# ------------------------------------------------------------------ macro

def test_macro_expansion_base():
    c = macro_component({"regime": "EXPANSION"})
    assert c.sub_conviction == 75.0


def test_macro_contraction_base():
    c = macro_component({"regime": "CONTRACTION"})
    assert c.sub_conviction == 25.0


def test_macro_z_adjustment():
    c = macro_component({"regime": "NEUTRAL", "z_score": 2.0})
    assert c.sub_conviction == 60.0  # 50 + 10
    c2 = macro_component({"regime": "NEUTRAL", "z_score": -2.0})
    assert c2.sub_conviction == 40.0


def test_macro_z_saturates():
    c = macro_component({"regime": "NEUTRAL", "z_score": 10.0})
    assert c.sub_conviction == 60.0  # adjustment capped at +/-10


def test_macro_z_partial():
    c = macro_component({"regime": "EXPANSION", "z_score": 1.0})
    assert c.sub_conviction == 80.0  # 75 + 5


def test_macro_transition_alert_nudge():
    base = macro_component({"regime": "NEUTRAL"})
    alert = macro_component({"regime": "NEUTRAL",
                             "transition_alerts": ["CONTRACTION"]})
    assert alert.sub_conviction == base.sub_conviction - 5.0


def test_macro_unknown_regime_unavailable():
    assert isinstance(macro_component({"regime": "BOOM"}), ComponentUnavailable)


def test_macro_unparseable_z_unavailable():
    c = macro_component({"regime": "NEUTRAL", "z_score": "high"})
    assert isinstance(c, ComponentUnavailable)


# --------------------------------------------------------------------- vol

def _vol(current, vmin=0.10, vmax=0.45, **kw):
    d = {"current_vol": current, "vol_min": vmin, "vol_max": vmax}
    d.update(kw)
    return vol_component(d)


def test_vol_low_is_risk_on():
    c = _vol(0.10)
    assert c.sub_conviction == 100.0


def test_vol_high_is_risk_off():
    c = _vol(0.45)
    assert c.sub_conviction == 0.0


def test_vol_mid_is_neutral():
    c = _vol(0.275)
    assert c.sub_conviction == pytest.approx(50.0)


def test_vol_inverted_monotone():
    subs = [_vol(v).sub_conviction for v in (0.10, 0.20, 0.30, 0.45)]
    assert subs == sorted(subs, reverse=True)


def test_vol_accepts_realized_vol_alias():
    c = vol_component({"realized_vol": 0.10, "vol_min": 0.10, "vol_max": 0.45})
    assert isinstance(c, Component)
    assert c.sub_conviction == 100.0


def test_vol_flat_history_neutral():
    c = _vol(0.20, vmin=0.20, vmax=0.20)
    assert c.sub_conviction == 50.0


def test_vol_forecast_tempers_spot():
    spot_only = _vol(0.40)
    with_cool_forecast = _vol(0.40, forecast_vol=0.15)
    # forecast 0.15 -> f_pct ~0.143; stress = .6*pct + .4*f_pct < pct
    assert with_cool_forecast.sub_conviction > spot_only.sub_conviction


def test_vol_acceleration_penalty():
    base = _vol(0.20, forecast_vol=0.20)
    accel = _vol(0.20, forecast_vol=0.30)  # 1.5x current -> accelerating
    assert accel.sub_conviction < base.sub_conviction
    assert accel.detail["acceleration"] is True


def test_vol_of_vol_penalty():
    base = _vol(0.20)
    unstable = _vol(0.20, vol_of_vol=0.8)
    assert unstable.sub_conviction < base.sub_conviction
    assert unstable.detail["vol_of_vol_penalty"] is True


def test_vol_missing_keys_unavailable():
    assert isinstance(vol_component({"current_vol": 0.2}), ComponentUnavailable)
    assert isinstance(vol_component(None), ComponentUnavailable)


# ---------------------------------------------------------------- read_all

def test_read_all_never_raises():
    comps = read_all(None, None, None)
    assert set(comps) == {"macro", "breadth", "vol"}
    assert all(isinstance(c, ComponentUnavailable) for c in comps.values())


def test_read_all_extra_slot():
    def my_reader(snap):
        return Component("sentiment", 62.5, {"basis": "test"})

    comps = read_all(None, None, None,
                     extra={"sentiment": ({"x": 1}, my_reader)})
    assert isinstance(comps["sentiment"], Component)
    assert comps["sentiment"].sub_conviction == 62.5


def test_read_all_extra_reader_crash_contained():
    def bad_reader(snap):
        raise RuntimeError("boom")

    comps = read_all(None, None, None, extra={"bad": ({}, bad_reader)})
    assert isinstance(comps["bad"], ComponentUnavailable)
