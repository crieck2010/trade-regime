"""Seeded demonstration: planted regime shifts through the arbiter.

Three acts over 300 days: constructive expansion, a noisy
deterioration (hysteresis must NOT flap), then a contraction with a
vol spike (stand-down must fire), then recovery.  Deterministic under
``seed`` — the same seed always yields the same stance timeline.
"""

from __future__ import annotations

import random

from .arbiter import RegimeArbiter
from .history import RegimeHistory
from .presets import arbiter_kwargs
from .signals import read_all

N_DAYS = 300


def _phase(day: int) -> str:
    if day < 100:
        return "expansion"
    if day < 200:
        return "deterioration"
    if day < 250:
        return "contraction"
    return "recovery"


def demo_signals(seed: int = 7, n_days: int = N_DAYS) -> list[dict]:
    """One signal-dict per day with planted regime shifts.

    Returns the raw ``read_all(...)`` dicts (Signal/SignalUnavailable
    objects), ready for ``RegimeArbiter.assess_series``.
    """
    rng = random.Random(seed)
    out = []
    for day in range(n_days):
        phase = _phase(day)
        if phase == "expansion":
            z = 1.5 + rng.uniform(-0.3, 0.3)
            rs, frag = 0.75 + rng.uniform(-0.15, 0.15), 0.15 + rng.uniform(0, 0.1)
            vpct = 0.25 + rng.uniform(-0.08, 0.08)
        elif phase == "deterioration":
            # Noisy oscillation around the engage boundary: the arbiter
            # must hold its stance, not flap.
            z = 0.35 + rng.uniform(-0.55, 0.55)
            rs, frag = 0.25 + rng.uniform(-0.35, 0.35), 0.35 + rng.uniform(0, 0.2)
            vpct = 0.50 + rng.uniform(-0.12, 0.12)
        elif phase == "contraction":
            z = -1.8 + rng.uniform(-0.3, 0.3)
            rs, frag = -0.8 + rng.uniform(-0.15, 0.15), 0.75 + rng.uniform(0, 0.15)
            vpct = 0.90 + rng.uniform(-0.06, 0.06)
        else:  # recovery
            z = 0.9 + rng.uniform(-0.3, 0.3)
            rs, frag = 0.5 + rng.uniform(-0.15, 0.15), 0.25 + rng.uniform(0, 0.1)
            vpct = 0.40 + rng.uniform(-0.08, 0.08)
        vpct = max(0.0, min(1.0, vpct))
        macro_snap = {"z_score": z,
                      "regime": "EXPANSION" if z > 0.5 else ("CONTRACTION" if z < -0.5 else "NEUTRAL"),
                      "date": f"day-{day:03d}"}
        breadth_snap = {"regime_score": rs, "fragility": max(0.0, min(1.0, frag)),
                        "regime": "BROADENING" if rs > 0.5 else ("NARROWING" if rs < -0.5 else "NEUTRAL"),
                        "date": f"day-{day:03d}"}
        vol_summary = {"current_vol": 0.10 + 0.40 * vpct,
                       "vol_min": 0.10, "vol_max": 0.50}
        out.append(read_all(macro_snap, breadth_snap, vol_summary))
    return out


def run_demo(seed: int = 7, preset: str = "balanced") -> dict:
    """Run the planted-shift history through the arbiter."""
    arbiter = RegimeArbiter(**arbiter_kwargs(preset))
    history = RegimeHistory()
    for sig in demo_signals(seed=seed):
        history.record(arbiter.assess(sig))
    transitions = history.transitions()
    stand_down_days = [r["seq"] for r in history.records
                       if r["conviction"] < 25.0]
    return {
        "seed": seed,
        "preset": preset,
        "n_days": len(history),
        "records": history.records,
        "transitions": [(t["seq"], t["prev_stance"], t["stance"]) for t in transitions],
        "n_transitions": len(transitions),
        "stand_down_days": stand_down_days,
        "final": history.latest(),
    }


def timeline(demo: dict, stride: int = 10) -> list[str]:
    """Compact human-readable stance timeline, one line per stride days."""
    labels = {-1: "DEF", 0: "NEU", 1: "CON"}
    lines = []
    for r in demo["records"][::stride]:
        lines.append(
            f"day {r['seq']:3d}  score {r['score']:+.2f}  conv {r['conviction']:5.1f}%  "
            f"stance {labels[r['stance']]}" + ("  <-- transition" if r["transition"] else "")
        )
    return lines
