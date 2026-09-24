"""Tests for signal normalization formulas."""

import pytest

from trade_regime.signals import (
    Signal,
    SignalUnavailable,
    breadth_score,
    macro_score,
    read_all,
    vol_score,
)


# ------------------------------------------------------------------ macro

def test_macro_z_full_scale():
    assert macro_score({"z_score": 3.0}).score == pytest.approx(1.0)
    assert macro_score({"z_score": -3.0}).score == pytest.approx(-1.0)
    assert macro_score({"z_score": 0.0}).score == pytest.approx(0.0)
    assert macro_score({"z_score": 1.5}).score == pytest.approx(0.5)


def test_macro_z_clamps():
    assert macro_score({"z_score": 9.0}).score == pytest.approx(1.0)
    assert macro_score({"z_score": -12.0}).score == pytest.approx(-1.0)


def test_macro_regime_fallback_is_half_scale():
    assert macro_score({"regime": "EXPANSION"}).score == pytest.approx(0.5)
    assert macro_score({"regime": "CONTRACTION"}).score == pytest.approx(-0.5)
    assert macro_score({"regime": "NEUTRAL"}).score == pytest.approx(0.0)


def test_macro_z_beats_label():
    s = macro_score({"z_score": 0.3, "regime": "EXPANSION"})
    assert s.score == pytest.approx(0.1)
    assert s.detail["basis"] == "z_score/3"


def test_macro_unavailable():
    for bad in (None, {}, {"regime": "BOGUS"}, {"z_score": "junk"}):
        s = macro_score(bad)
        assert isinstance(s, SignalUnavailable)
        assert not s


# ----------------------------------------------------------------- breadth

def test_breadth_full_scale():
    s = breadth_score({"regime_score": 1.5, "fragility": 0.0})
    assert s.score == pytest.approx(1.0)
    s = breadth_score({"regime_score": -1.5, "fragility": 0.0})
    assert s.score == pytest.approx(-1.0)


def test_breadth_fragility_drags_only_toward_risk_off():
    clean = breadth_score({"regime_score": 1.5, "fragility": 0.0}).score
    fragile = breadth_score({"regime_score": 1.5, "fragility": 1.0}).score
    assert fragile == pytest.approx(clean - 0.5)
    # maximally fragile market can never score above +0.5
    assert fragile <= 0.5


def test_breadth_fragility_floor_clamps():
    s = breadth_score({"regime_score": -1.5, "fragility": 1.0})
    assert s.score == pytest.approx(-1.0)


def test_breadth_regime_fallback():
    s = breadth_score({"regime": "BROADENING", "fragility": 0.2})
    assert s.score == pytest.approx(0.5 - 0.5 * 0.2)
    s = breadth_score({"regime": "NARROWING", "fragility": 0.0})
    assert s.score == pytest.approx(-0.5)


def test_breadth_unavailable():
    assert isinstance(breadth_score(None), SignalUnavailable)
    assert isinstance(breadth_score({"fragility": "junk"}), SignalUnavailable)
    assert isinstance(breadth_score({"fragility": 0.1}), SignalUnavailable)


# --------------------------------------------------------------------- vol

def test_vol_percentile_mapping():
    base = {"vol_min": 0.10, "vol_max": 0.50}
    assert vol_score({**base, "current_vol": 0.10}).score == pytest.approx(1.0)
    assert vol_score({**base, "current_vol": 0.50}).score == pytest.approx(-1.0)
    assert vol_score({**base, "current_vol": 0.30}).score == pytest.approx(0.0)


def test_vol_flat_history_is_neutral():
    s = vol_score({"current_vol": 0.2, "vol_min": 0.2, "vol_max": 0.2})
    assert isinstance(s, Signal) and s.score == pytest.approx(0.0)


def test_vol_unavailable():
    assert isinstance(vol_score(None), SignalUnavailable)
    assert isinstance(vol_score({"current_vol": 0.2}), SignalUnavailable)


# ----------------------------------------------------------------- read_all

def test_read_all_never_raises():
    out = read_all(None, None, None)
    assert set(out) == {"macro", "breadth", "vol"}
    assert all(isinstance(v, SignalUnavailable) for v in out.values())
