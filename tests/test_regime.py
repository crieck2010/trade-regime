"""Tests for history, adapters, demo determinism, and the CLI."""

import json

import pytest

from trade_regime.adapters import assess_live, hedge_trigger, pm_context, risk_caps
from trade_regime.arbiter import RegimeArbiter
from trade_regime.demo import run_demo
from trade_regime.history import RegimeHistory
from trade_regime.signals import Signal, read_all


def _state(conviction=80.0, score=0.6, stance=1, transition=False):
    return {
        "schema_version": 1, "ts": "2026-01-01T00:00:00+00:00",
        "score": score, "conviction": conviction, "stance": stance,
        "stance_label": "CONSTRUCTIVE", "prev_stance": 0,
        "transition": transition, "contributions": {},
        "weights_used": {}, "missing": [], "n_signals": 3,
    }


# ------------------------------------------------------------------ history

def test_history_record_and_transitions():
    h = RegimeHistory()
    arb = RegimeArbiter()
    strong = read_all({"z_score": 2.4}, {"regime_score": 1.2, "fragility": 0.1},
                      {"current_vol": 0.12, "vol_min": 0.1, "vol_max": 0.5})
    weak = read_all({"z_score": 0.0}, {"regime_score": 0.0, "fragility": 0.2},
                    {"current_vol": 0.3, "vol_min": 0.1, "vol_max": 0.5})
    h.record(arb.assess(strong))
    h.record(arb.assess(weak))
    assert len(h) == 2
    assert h.records[0]["seq"] == 0
    assert h.latest()["seq"] == 1
    assert {t["stance"] for t in h.transitions()} == {0, 1}
    assert h.stance_at(0) == 1


def test_history_jsonl_round_trip(tmp_path):
    p = str(tmp_path / "regime.jsonl")
    h = RegimeHistory(path=p)
    h.record(_state())
    h2 = RegimeHistory(path=p)
    assert len(h2) == 1
    assert h2.latest()["conviction"] == 80.0
    q = str(tmp_path / "dump.jsonl")
    assert h.to_jsonl(q) == 1


# ----------------------------------------------------------------- adapters

def test_pm_context_hook_spec():
    ctx = pm_context(_state())
    assert ctx["source"] == "trade-regime"
    assert ctx["conviction"] == 80.0
    assert ctx["exposure_scale"] == pytest.approx(0.7867, abs=1e-3)
    assert set(ctx["sleeve_scales"]) == {"trend", "mean_reversion", "short_vol"}
    assert ctx["stand_down"] is False
    json.dumps(ctx)


def test_pm_context_stand_down():
    ctx = pm_context(_state(conviction=10.0, stance=0))
    assert ctx["stand_down"] is True
    assert ctx["exposure_scale"] == 0.0


def test_risk_caps_tighten_with_conviction():
    full = risk_caps(_state(conviction=100.0))
    assert full["max_gross_exposure"] == 1.0
    assert full["max_leverage"] == 2.0
    flat = risk_caps(_state(conviction=10.0))
    assert flat["max_gross_exposure"] == 0.0
    assert flat["max_position_pct"] == 0.0
    assert flat["stand_down"] is True


def test_hedge_trigger_stand_down():
    trig = hedge_trigger(_state(conviction=10.0))
    assert trig["event"] == "STAND_DOWN"


def test_hedge_trigger_defensive_flip():
    trig = hedge_trigger(_state(conviction=60.0, stance=-1, transition=True))
    assert trig["event"] == "DEFENSIVE_STANCE"


def test_hedge_trigger_quiet_when_calm():
    assert hedge_trigger(_state(conviction=80.0, stance=1)) is None


def test_assess_live_fail_soft_without_engines():
    # Siblings are not installed in the test env: must not raise.
    state, notes = assess_live()
    assert state["schema_version"] == 1
    assert set(state["missing"]) == {"breadth", "macro", "vol"}
    assert state["score"] == 0.0
    assert "trade_macro" in notes["engines"]


# --------------------------------------------------------------------- demo

def test_demo_deterministic():
    a, b = run_demo(seed=7), run_demo(seed=7)
    assert a["transitions"] == b["transitions"]
    assert a["final"]["score"] == b["final"]["score"]
    assert a["stand_down_days"] == b["stand_down_days"]


def test_demo_detects_planted_shifts():
    d = run_demo(seed=7)
    stances = [r["stance"] for r in d["records"]]
    assert max(stances[:100]) == 1, "expansion must engage constructive"
    assert min(stances[200:250]) == -1, "contraction must engage defensive"
    assert d["final"]["stance"] == 0, "recovery releases to neutral"
    assert len(d["stand_down_days"]) > 0, "noisy deterioration must fire stand-down"


def test_demo_no_flapping():
    d = run_demo(seed=7)
    # Four deliberate phase changes; allow two extra, no more.
    assert d["n_transitions"] <= 6, d["transitions"]


# ----------------------------------------------------------------------- cli

def test_cli_demo_and_presets(capsys):
    from trade_regime.cli import main
    assert main(["demo", "--seed", "7", "--stride", "100"]) == 0
    out = capsys.readouterr().out
    assert "trade-regime demo" in out
    assert main(["presets"]) == 0
    assert "conservative" in capsys.readouterr().out


def test_cli_assess_demo_json(capsys):
    from trade_regime.cli import main
    assert main(["assess", "--demo", "--format", "json"]) == 0
    state = json.loads(capsys.readouterr().out)
    assert state["schema_version"] == 1


def test_cli_weights_validate(capsys):
    from trade_regime.cli import main
    assert main(["weights", "--validate", "macro=0.5,breadth=0.3,vol=0.2"]) == 0
    assert "valid" in capsys.readouterr().out
