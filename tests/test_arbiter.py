"""Tests for fusion math, conviction curve, and Schmitt-trigger hysteresis."""

import json

import pytest

from trade_regime.arbiter import (
    DEFAULT_WEIGHTS,
    RegimeArbiter,
    conviction_of,
    fuse,
    next_stance,
    validate_weights,
)
from trade_regime.signals import Signal, SignalUnavailable

SIG = lambda name, score: Signal(name, score)  # noqa: E731


def _signals(macro=1.0, breadth=0.5, vol=-0.5):
    return {"macro": SIG("macro", macro),
            "breadth": SIG("breadth", breadth),
            "vol": SIG("vol", vol)}


# ------------------------------------------------------------------- fusion

def test_fusion_hand_computed():
    # 0.4*1.0 + 0.35*0.5 + 0.25*(-0.5) = 0.45
    score, contrib, missing = fuse(_signals())
    assert score == pytest.approx(0.45)
    assert missing == []
    assert contrib["macro"]["contribution"] == pytest.approx(0.40)
    assert contrib["breadth"]["weight"] == pytest.approx(0.35)
    assert sum(c["weight"] for c in contrib.values()) == pytest.approx(1.0)


def test_fusion_reweights_missing_signals():
    sigs = _signals()
    sigs["macro"] = SignalUnavailable("macro", "not installed")
    score, contrib, missing = fuse(sigs)
    # (0.35*0.5 + 0.25*(-0.5)) / 0.60 = 0.0833 (rounded to 4dp)
    assert score == pytest.approx(0.0833)
    assert missing == ["macro"]
    assert set(contrib) == {"breadth", "vol"}
    assert sum(c["weight"] for c in contrib.values()) == pytest.approx(1.0)


def test_fusion_all_missing_is_neutral_not_risk_off():
    sigs = {n: SignalUnavailable(n, "x") for n in ("macro", "breadth", "vol")}
    score, contrib, missing = fuse(sigs)
    assert score == pytest.approx(0.0)
    assert sorted(missing) == ["breadth", "macro", "vol"]


def test_fusion_custom_weights():
    score, _, _ = fuse(_signals(), {"macro": 1.0, "breadth": 0.0, "vol": 0.0})
    assert score == pytest.approx(1.0)


def test_validate_weights_rejects_nonsense():
    with pytest.raises(ValueError):
        validate_weights({"macro": -0.5})
    with pytest.raises(ValueError):
        validate_weights({"macro": 0.0, "breadth": 0.0})
    with pytest.raises(ValueError):
        validate_weights({"macro": "junk"})
    with pytest.raises(ValueError):
        validate_weights({})


# --------------------------------------------------------------- conviction

def test_conviction_boundaries():
    assert conviction_of(0.0) == 0.0
    assert conviction_of(0.8) == 100.0
    assert conviction_of(1.0) == 100.0
    assert conviction_of(-1.0) == 100.0
    assert conviction_of(0.4) == 50.0


def test_conviction_monotone_in_abs_score():
    prev = -1.0
    for s in [i / 20 for i in range(21)]:
        c = conviction_of(s)
        assert c >= prev
        prev = c
    assert conviction_of(0.3) == conviction_of(-0.3)


# ------------------------------------------------------- Schmitt-trigger

def test_engage_thresholds():
    assert next_stance(0, 0.39) == 0
    assert next_stance(0, 0.40) == 1
    assert next_stance(0, -0.39) == 0
    assert next_stance(0, -0.40) == -1


def test_no_flap_on_noisy_boundary():
    # Oscillating inside the dead zone must not move the stance.
    stance = 0
    for score in (0.41, 0.35, 0.44, 0.30, 0.42, 0.36):
        stance = next_stance(stance, score)
    assert stance == 1  # engaged once, never released
    for score in (0.11, 0.20, 0.11, 0.30):
        stance = next_stance(stance, score)
    assert stance == 1  # release needs <= 0.10


def test_release_threshold():
    assert next_stance(1, 0.11) == 1
    assert next_stance(1, 0.10) == 0
    assert next_stance(-1, -0.11) == -1
    assert next_stance(-1, -0.10) == 0


def test_violent_reversal_walks_through_neutral():
    assert next_stance(1, -0.95) == 0  # not -1: must cross the dead zone
    assert next_stance(0, -0.95) == -1  # next assessment completes the flip


def test_bad_prev_stance_raises():
    with pytest.raises(ValueError):
        next_stance(2, 0.5)


# ------------------------------------------------------------------ arbiter

def test_assess_contract():
    arb = RegimeArbiter()
    state = arb.assess(_signals())
    assert state["schema_version"] == 1
    assert state["score"] == pytest.approx(0.45)
    assert state["conviction"] == pytest.approx(56.2, abs=0.1)
    assert state["stance"] == 1  # 0.45 >= 0.40 engage
    assert state["stance_label"] == "CONSTRUCTIVE"
    assert state["transition"] is True  # 0 -> 1
    json.dumps(state)  # must survive JSON


def test_arbiter_stance_memory():
    arb = RegimeArbiter()
    arb.assess(_signals())  # stance -> 1
    weak = {"macro": SIG("macro", 0.1), "breadth": SIG("breadth", 0.1),
            "vol": SIG("vol", 0.1)}
    s2 = arb.assess(weak)  # score 0.1 <= release 0.10 -> neutral
    assert s2["stance"] == 0 and s2["transition"] is True
    s3 = arb.assess(weak)
    assert s3["transition"] is False  # already neutral: no repeated flag


def test_arbiter_reset():
    arb = RegimeArbiter()
    arb.assess(_signals())
    arb.reset()
    assert arb.stance == 0


def test_arbiter_bad_geometry_rejected():
    with pytest.raises(ValueError):
        RegimeArbiter(band=0.3, threshold=0.2)


def test_default_weights_documented_sum():
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)
