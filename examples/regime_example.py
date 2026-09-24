"""End-to-end walkthrough: signals -> arbiter -> sizing -> adapters."""

from trade_regime.adapters import hedge_trigger, pm_context, risk_caps
from trade_regime.arbiter import RegimeArbiter
from trade_regime.demo import run_demo, timeline
from trade_regime.history import RegimeHistory
from trade_regime.signals import read_all
from trade_regime.sizing import sleeve_scales

# 1. One assessment from hand-built engine snapshots.
signals = read_all(
    macro_snapshot={"z_score": 1.8, "regime": "EXPANSION"},
    breadth_snapshot={"regime_score": 0.9, "fragility": 0.2},
    vol_summary={"current_vol": 0.14, "vol_min": 0.10, "vol_max": 0.45},
)
arbiter = RegimeArbiter()
state = arbiter.assess(signals)
print(f"score {state['score']:+.3f}  conviction {state['conviction']:.1f}%  "
      f"stance {state['stance_label']}")
print("sleeves:", sleeve_scales(state["conviction"])["sleeves"])

# 2. What the PM agent, risk desk, and hedge desk each read.
print("\npm_context keys:", sorted(pm_context(state)))
print("risk_caps:", risk_caps(state))
print("hedge_trigger:", hedge_trigger(state))

# 3. Missing engines degrade gracefully (re-weighted, never an exception).
thin = RegimeArbiter().assess(read_all({"z_score": -2.2}, None, None))
print(f"\nmacro-only: score {thin['score']:+.3f}  missing {thin['missing']}")

# 4. The planted-shift demo: expansion -> noisy deterioration ->
#    contraction + vol spike -> recovery.
demo = run_demo(seed=7)
print(f"\ndemo: {demo['n_transitions']} transitions, "
      f"{len(demo['stand_down_days'])} stand-down days")
for line in timeline(demo, stride=75):
    print(line)

# 5. History replays stance exactly.
history = RegimeHistory()
for r in demo["records"]:
    history.record(r)
print(f"\nhistory: {len(history)} records, "
      f"{len(history.transitions())} transitions")
