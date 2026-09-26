"""Tests for the seeded demo arc and conviction history."""

import json

import pytest

from trade_regime.demo import demo_arc, run_demo
from trade_regime.history import ConvictionHistory


def test_demo_arc_phases():
    arc = demo_arc(seed=7)
    assert len(arc) == 120
    assert arc[0]["phase"] == "bull"
    assert arc[40]["phase"] == "narrowing"
    assert arc[70]["phase"] == "vol-spike"
    assert arc[90]["phase"] == "recovery"
    assert arc[70]["macro"]["regime"] == "CONTRACTION"
    assert arc[0]["breadth"]["regime"] == "BROADENING"


def test_demo_deterministic():
    a1 = demo_arc(seed=7)
    a2 = demo_arc(seed=7)
    assert a1 == a2
    a3 = demo_arc(seed=8)
    assert a3 != a1


def test_run_demo_deterministic():
    _, snaps1, _ = run_demo(seed=7)
    _, snaps2, _ = run_demo(seed=7)
    c1 = [s["conviction"] for s in snaps1]
    c2 = [s["conviction"] for s in snaps2]
    assert c1 == c2


def test_demo_hysteresis_holds_through_narrowing_noise():
    arc, snaps, _ = run_demo(seed=7)
    narrowing = [s for inp, s in zip(arc, snaps) if inp["phase"] == "narrowing"]
    held = [s for s in narrowing if s["hysteresis"]["state"] == "held"]
    # most of the noisy narrowing phase should hold, not flap
    assert len(held) / len(narrowing) > 0.6


def test_demo_vol_spike_releases_downward():
    arc, snaps, _ = run_demo(seed=7)
    bull_conv = snaps[39]["conviction"]
    spike = [s for inp, s in zip(arc, snaps) if inp["phase"] == "vol-spike"]
    assert min(s["conviction"] for s in spike) < bull_conv - 10


def test_demo_recovery_climbs_back():
    arc, snaps, _ = run_demo(seed=7)
    spike_min = min(s["conviction"] for inp, s in zip(arc, snaps)
                    if inp["phase"] == "vol-spike")
    assert snaps[-1]["conviction"] > spike_min


def test_demo_provenance_recorded():
    _, snaps, _ = run_demo(seed=7)
    prov = snaps[0]["provenance"]
    assert prov["input_snapshot_ids"]["macro"] == "demo-7-000"
    assert prov["input_schema_versions"] == {"macro": 1, "breadth": 1, "vol": 1}


# ------------------------------------------------------------- history

def test_history_record_and_latest():
    h = ConvictionHistory()
    e = h.record({"conviction": 70.0, "hysteresis": {"state": "held"}})
    assert e["seq"] == 0
    assert len(h) == 1
    assert h.latest()["conviction"] == 70.0


def test_history_updates_filters():
    h = ConvictionHistory()
    h.record({"conviction": 70.0, "hysteresis": {"state": "held"}})
    h.record({"conviction": 72.0, "hysteresis": {"state": "updated"}})
    assert len(h.updates()) == 1
    assert h.updates()[0]["conviction"] == 72.0


def test_history_jsonl_round_trip(tmp_path):
    path = str(tmp_path / "hist.jsonl")
    h = ConvictionHistory(path=path)
    h.record({"conviction": 70.0, "hysteresis": {"state": "held"}})
    h2 = ConvictionHistory(path=path)
    assert len(h2) == 1
    assert h2.latest()["conviction"] == 70.0
    # appended lines are valid JSON
    line = open(path, encoding="utf-8").readline()
    assert json.loads(line)["conviction"] == 70.0
