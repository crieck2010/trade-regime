"""End-to-end walkthrough: components -> arbiter -> hysteresis -> adapters.

Run from the repo root with the package importable:
    PYTHONPATH=src python3 examples/regime_example.py
"""

from trade_regime.adapters import (
    hedge_tilt_input,
    market_context_provider,
    risk_regime_input,
)
from trade_regime.arbiter import RegimeArbiter
from trade_regime.demo import run_demo
from trade_regime.presets import arbiter_kwargs
from trade_regime.signals import read_all

print("== 1. one assessment from plain snapshot dicts ==")
components = read_all(
    macro_snapshot={"regime": "EXPANSION", "z_score": 1.8},
    breadth_snapshot={"regime": "BROADENING", "fragility": 0.15},
    vol_summary={"current_vol": 0.13, "vol_min": 0.10, "vol_max": 0.45,
                 "forecast_vol": 0.13},
)
arbiter = RegimeArbiter(**arbiter_kwargs("balanced"))
snap = arbiter.assess(components)
for name, c in snap["components"].items():
    print(f"  {name:8s} sub-conviction {c['sub_conviction']:6.1f}")
print(f"  raw composite {snap['composite_raw']:.1f} -> "
      f"conviction {snap['conviction']:.1f} "
      f"({snap['hysteresis']['state']}: {snap['hysteresis']['reason']})")
print(f"  exposure_scale (advisory): {snap['exposure_scale']}")

print("\n== 2. hysteresis: noise holds, persistent breaks release ==")
from trade_regime.signals import Component

arbiter2 = RegimeArbiter(**arbiter_kwargs("balanced"))


def _raw(v):
    # single synthetic component at sub-conviction v -> raw composite == v
    return {"macro": Component("macro", v, {})}


s0 = arbiter2.assess(_raw(70.0))
print(f"  day 0: conviction {s0['conviction']:.1f}")
# noisy wobble around the band edge: holds (direction keeps flipping)
for i, raw in enumerate((82, 58, 83, 57), start=1):
    s = arbiter2.assess(_raw(raw))
    print(f"  day {i}: raw {s['composite_raw']:.1f} -> {s['conviction']:.1f} "
          f"[{s['hysteresis']['state']}] {s['hysteresis']['reason']}")
# persistent drift beyond the edge: releases on the 3rd consecutive obs
for i in range(5, 8):
    s = arbiter2.assess(_raw(84.0))
    print(f"  day {i}: raw {s['composite_raw']:.1f} -> {s['conviction']:.1f} "
          f"[{s['hysteresis']['state']}] {s['hysteresis']['reason']}")
# violent break: releases immediately, rate-limited
s = arbiter2.assess(_raw(10.0))
print(f"  day 8: raw {s['composite_raw']:.1f} -> {s['conviction']:.1f} "
      f"[{s['hysteresis']['state']}] {s['hysteresis']['reason']}")

print("\n== 3. seeded 120-day arc: bull -> narrowing -> vol spike -> recovery ==")
arc, snaps, _ = run_demo(seed=7)
for day in (0, 39, 55, 70, 75, 89, 119):
    s = snaps[day]
    print(f"  day {day:3d} ({arc[day]['phase']:9s}): raw {s['composite_raw']:5.1f} "
          f"-> conviction {s['conviction']:5.1f} [{s['hysteresis']['state']}]")

print("\n== 4. adapters: one snapshot, three consumers ==")
ctx = market_context_provider(snaps[75])
print(f"  trade-agents market_context: conviction={ctx['conviction']:.1f}, "
      f"components={ctx['components']}")
risk = risk_regime_input(snaps[75])
print(f"  trade-risk input: exposure_scale_advisory={risk['exposure_scale_advisory']}")
tilt = hedge_tilt_input(snaps[75])
print(f"  trade-hedge tilt: defensive_tilt={tilt['defensive_tilt']} "
      "(positive = lean defensive)")

print("\n== 5. memory survives a restart (CLI --state pattern) ==")
mem = arbiter2.memory_dict()
fresh = RegimeArbiter(**arbiter_kwargs("balanced"))
fresh.restore(mem)
print(f"  restored conviction={fresh.memory_dict()['conviction']:.1f}, "
      f"persist={fresh.memory_dict()['persist_count']}/"
      f"{fresh.memory_dict()['persist_dir']}")
print("\ndone.")
