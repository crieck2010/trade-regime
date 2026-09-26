"""Seeded demonstration arc: bull -> narrowing/fragile -> vol spike -> recovery.

Deterministic (``random.Random(seed)``) -- the same seed always yields
the same arc, so the demo doubles as a regression fixture.  The arc is
designed to exercise the hysteresis:

- days 0-39   BULL: expansion macro, broadening participation, low vol.
- days 40-69  NARROWING: participation narrows, fragility climbs, macro
              z fades toward zero.  Injected noise makes the raw
              composite wobble around the band edges -- the arbiter
              should HOLD through most of it.
- days 70-89  VOL SPIKE: vol jumps, macro flips to contraction with a
              transition alert.  The raw composite breaks the confirm
              band -- conviction releases downward, rate-limited.
- days 90-119 RECOVERY: vol mean-reverts, macro z recovers, breadth
              re-broadens with a thrust.  Conviction climbs back, again
              rate-limited.

Illustrative, not backtest evidence.
"""

from __future__ import annotations

import random

N_DAYS = 120


def _jitter(rng: random.Random, scale: float) -> float:
    return rng.gauss(0.0, scale)


def demo_arc(seed: int = 7, n: int = N_DAYS) -> list[dict]:
    """Return ``n`` days of engine-shaped input snapshots."""
    rng = random.Random(seed)
    arc = []
    for day in range(n):
        if day < 40:
            phase = "bull"
            macro = {"regime": "EXPANSION",
                     "z_score": round(1.5 + _jitter(rng, 0.4), 3)}
            breadth = {"regime": "BROADENING",
                       "fragility": round(max(0.0, 0.15 + _jitter(rng, 0.06)), 3),
                       "thrusts": day == 10}
            vol = {"current_vol": round(0.12 + _jitter(rng, 0.015), 4),
                   "vol_min": 0.10, "vol_max": 0.45,
                   "forecast_vol": round(0.12 + _jitter(rng, 0.01), 4)}
        elif day < 70:
            phase = "narrowing"
            t = (day - 40) / 30.0
            macro = {"regime": "EXPANSION" if t < 0.6 else "NEUTRAL",
                     "z_score": round(1.0 - 1.2 * t + _jitter(rng, 0.35), 3)}
            breadth = {"regime": "NARROWING",
                       "fragility": round(max(0.0, min(1.0, 0.25 + 0.5 * t + _jitter(rng, 0.08))), 3),
                       "divergence_warning": t > 0.5}
            vol = {"current_vol": round(0.14 + 0.06 * t + _jitter(rng, 0.02), 4),
                   "vol_min": 0.10, "vol_max": 0.45,
                   "forecast_vol": round(0.15 + 0.06 * t + _jitter(rng, 0.015), 4)}
        elif day < 90:
            phase = "vol-spike"
            macro = {"regime": "CONTRACTION",
                     "z_score": round(-1.5 + _jitter(rng, 0.4), 3),
                     "transition_alerts": ["CONTRACTION"] if day == 70 else []}
            breadth = {"regime": "NARROWING",
                       "fragility": round(max(0.0, min(1.0, 0.8 + _jitter(rng, 0.07))), 3),
                       "divergence_warning": True}
            vol = {"current_vol": round(0.38 + _jitter(rng, 0.03), 4),
                   "vol_min": 0.10, "vol_max": 0.45,
                   "forecast_vol": round(0.42 + _jitter(rng, 0.03), 4),
                   "vol_of_vol": 0.6}
        else:
            phase = "recovery"
            t = (day - 90) / 30.0
            macro = {"regime": "EXPANSION" if t > 0.4 else "NEUTRAL",
                     "z_score": round(-0.5 + 1.8 * t + _jitter(rng, 0.35), 3)}
            breadth = {"regime": "BROADENING" if t > 0.4 else "NEUTRAL",
                       "fragility": round(max(0.0, 0.5 - 0.35 * t + _jitter(rng, 0.06)), 3),
                       "thrusts": day == 100}
            vol = {"current_vol": round(0.36 - 0.20 * t + _jitter(rng, 0.02), 4),
                   "vol_min": 0.10, "vol_max": 0.45,
                   "forecast_vol": round(0.34 - 0.19 * t + _jitter(rng, 0.015), 4)}
        arc.append({"day": day, "phase": phase,
                    "macro": macro, "breadth": breadth, "vol": vol,
                    "snapshot_id": f"demo-{seed}-{day:03d}"})
    return arc


def run_demo(seed: int = 7, preset: str = "balanced", n: int = N_DAYS):
    """Run the seeded arc through a fresh arbiter.

    Returns ``(arc, snapshots, arbiter)``.
    """
    from .arbiter import RegimeArbiter
    from .presets import arbiter_kwargs
    from .signals import read_all

    arc = demo_arc(seed=seed, n=n)
    arbiter = RegimeArbiter(**arbiter_kwargs(preset))
    snapshots = []
    for inputs in arc:
        components = read_all(inputs["macro"], inputs["breadth"], inputs["vol"])
        provenance = {
            "input_snapshot_ids": {k: inputs["snapshot_id"] for k in ("macro", "breadth", "vol")},
            "input_schema_versions": {"macro": 1, "breadth": 1, "vol": 1},
        }
        snapshots.append(arbiter.assess(components, provenance=provenance))
    return arc, snapshots, arbiter
