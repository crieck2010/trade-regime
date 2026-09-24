"""Interop adapters: lazy, fail-soft bridges to sibling suite modules.

Nothing is imported at module top level — every sibling import lives
inside a function behind try/except ImportError, so trade-regime stays
importable and testable with zero siblings installed.

Hook specs (the contracts downstream code should program against):

- ``pm_context(state)`` -> dict the trade-agents portfolio manager
  reads each decision cycle: score, conviction, stance label (display),
  exposure dial, per-sleeve scales, stand-down flag.
- ``risk_caps(state)`` -> dict for trade-risk: gross/net exposure caps,
  per-position cap, leverage cap — all functions of conviction.
- ``hedge_trigger(state)`` -> None, or a stand-down event dict for
  trade-hedge when conviction is below the floor or the stance just
  flipped defensive.
- ``assess_live(...)`` -> best-effort live assessment from installed
  engines' demo snapshots (research wiring, not production data).
"""

from __future__ import annotations

from .arbiter import RegimeArbiter
from .signals import read_all
from .sizing import SLEEVES, exposure_scale, sleeve_scale, stand_down


# ------------------------------------------------------------ live wiring

def assess_live(weights: dict | None = None, seed: int = 7,
                preset: str = "balanced") -> tuple[dict, dict]:
    """Best-effort assessment from installed engines' demo data.

    Returns ``(state, notes)``.  Never raises for missing engines —
    missing signals are re-weighted and listed in ``state["missing"]``.
    This is research wiring; production should feed real snapshots
    into ``RegimeArbiter.assess`` directly.
    """
    import importlib

    from .presets import arbiter_kwargs

    notes = {"seed": seed, "preset": preset, "engines": {}}
    macro_snap = breadth_snap = vol_summary = None

    try:
        tm = importlib.import_module("trade_macro")
        series = tm.demo.demo_series(seed=seed)
        macro_snap = tm.snapshot(series["copper"], series["gold"], source="synthetic")
        notes["engines"]["trade_macro"] = "demo snapshot"
    except Exception as exc:  # noqa: BLE001
        notes["engines"]["trade_macro"] = f"unavailable: {exc}"

    try:
        tb = importlib.import_module("trade_breadth")
        universe, weights_map = tb.demo_universe(seed=seed)
        breadth_snap = tb.snapshot(universe, weights=weights_map)
        notes["engines"]["trade_breadth"] = "demo snapshot"
    except Exception as exc:  # noqa: BLE001
        notes["engines"]["trade_breadth"] = f"unavailable: {exc}"

    try:
        tv = importlib.import_module("trade_volforecast")
        bars = tv.demo.demo_bars(n=750, seed=seed)
        vol_summary = tv.adapters.vol_for_risk(bars, window=21)
        notes["engines"]["trade_volforecast"] = "demo vol summary"
    except Exception as exc:  # noqa: BLE001
        notes["engines"]["trade_volforecast"] = f"unavailable: {exc}"

    arbiter = RegimeArbiter(**arbiter_kwargs(preset) if weights is None else {"weights": weights})
    state = arbiter.assess(read_all(macro_snap, breadth_snap, vol_summary))
    return state, notes


# ------------------------------------------------------------ trade-agents

def pm_context(state: dict) -> dict:
    """Portfolio-manager context: what the PM agent reads each cycle.

    Hook spec for trade-agents: merge this into ``market_context``
    before idea generation / debate.  ``stance_label`` is display-only;
    the tradable fields are ``conviction``, ``exposure_scale`` and
    ``sleeve_scales``.
    """
    conviction = float(state["conviction"])
    return {
        "source": "trade-regime",
        "schema_version": 1,
        "regime_score": state["score"],
        "conviction": conviction,
        "stance": state["stance"],
        "stance_label": state["stance_label"],  # display only
        "exposure_scale": exposure_scale(conviction),
        "sleeve_scales": {s: sleeve_scale(s, conviction) for s in SLEEVES},
        "stand_down": stand_down(conviction),
        "missing_signals": state.get("missing", []),
    }


# ---------------------------------------------------------------- trade-risk

def risk_caps(state: dict) -> dict:
    """Regime-conditional risk caps for trade-risk.

    Caps tighten as conviction falls.  At full conviction the book may
    run its normal limits; in stand-down everything is zero.
    """
    conviction = float(state["conviction"])
    scale = exposure_scale(conviction)
    return {
        "source": "trade-regime",
        "schema_version": 1,
        "max_gross_exposure": round(scale, 4),
        "max_net_exposure": round(scale, 4),
        "max_position_pct": round(0.10 * scale, 4),  # 10% name cap at full scale
        "max_leverage": round(1.0 + 1.0 * scale, 4),  # 1x flat -> 2x full
        "stand_down": stand_down(conviction),
    }


# --------------------------------------------------------------- trade-hedge

def hedge_trigger(state: dict) -> dict | None:
    """Stand-down / defensive event for trade-hedge, or None.

    Fires when conviction is below the floor, or on the assessment
    where the stance flips to defensive.  trade-hedge owns the
    response (propose hedges, never execute); this only raises the
    flag.
    """
    conviction = float(state["conviction"])
    if stand_down(conviction):
        return {
            "event": "STAND_DOWN",
            "source": "trade-regime",
            "conviction": conviction,
            "score": state["score"],
            "action": "flatten book; hedge desk may propose defensive overlays",
        }
    if state.get("transition") and state.get("stance") == -1:
        return {
            "event": "DEFENSIVE_STANCE",
            "source": "trade-regime",
            "conviction": conviction,
            "score": state["score"],
            "action": "defensive tilt advised; review hedge proposals",
        }
    return None
