"""Interop adapters: lazy, plain-data bridges to sibling suite modules.

Every adapter takes a trade-regime *snapshot dict* and returns a plain
dict shaped for one consumer.  Nothing is imported -- no sibling
packages, no optional dependencies -- so trade-regime stays stdlib-only
and importable anywhere.  Downstream code programs against these
shapes, not against our internals.

Hook specs (the contracts downstream code should program against):

- ``market_context_provider(snapshot)`` -> the canonical fused market
  context for trade-agents.  This **supersedes wiring trade-breadth /
  trade-macro snapshots into the agents individually**: one fused
  conviction number replaces two (or three) partially-redundant
  regime reads.  The direct breadth/macro paths keep working
  unchanged -- nothing is removed, the arbiter is simply the preferred
  wiring for the PM decision layer.
- ``risk_regime_input(snapshot)`` -> advisory regime input for
  trade-risk.  The ``exposure_scale`` is explicitly advisory:
  **trade-risk owns final sizing**; this input is one voice among
  its constraints.
- ``hedge_tilt_input(snapshot)`` -> defensive/aggressive tilt for
  trade-hedge (-1..+1; positive = lean defensive).  trade-hedge owns
  the response (propose overlays, never execute); this only suggests
  direction and magnitude.

All three adapters share a base shape emitted by ``_base()``:

- ``source`` / ``schema_version`` -- provenance, always ``1``
- ``conviction`` / ``composite_raw`` -- the hysteresis-smoothed and
  raw 0-100 numbers
- ``timestamp`` / ``snapshot_id`` / ``missing`` -- snapshot metadata
- ``hysteresis_state`` -- ``"held"`` or ``"updated"``
- ``hysteresis_reason`` -- the arbiter's plain-text reason for the
  hysteresis decision (e.g. ``"within deadband (+/-10 pts)"``);
  ``None`` when the snapshot carries no hysteresis block
- ``hysteresis_prior_conviction`` -- the arbiter's conviction before
  this assessment (``None`` on first assessment); ``None`` when the
  snapshot carries no hysteresis block

Both hysteresis fields are additive (schema_version stays 1) and
None-tolerant: downstream code should treat a missing hysteresis
block as "no hysteresis information", never as an error.
"""

from __future__ import annotations


def _base(snapshot: dict) -> dict:
    conviction = float(snapshot["conviction"])
    return {
        "source": "trade-regime",
        "schema_version": 1,
        "conviction": conviction,
        "composite_raw": float(snapshot.get("composite_raw", conviction)),
        "timestamp": snapshot.get("timestamp"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "missing": list(snapshot.get("missing", [])),
        "hysteresis_state": snapshot.get("hysteresis", {}).get("state"),
        "hysteresis_reason": snapshot.get("hysteresis", {}).get("reason"),
        "hysteresis_prior_conviction": snapshot.get("hysteresis", {}).get(
            "prior_conviction"),
    }


# ------------------------------------------------------------ trade-agents

def market_context_provider(snapshot: dict) -> dict:
    """Canonical fused market context for the trade-agents PM.

    Supersedes wiring trade-breadth / trade-macro snapshots into the
    agents individually: instead of N partially-redundant regime
    reads, the PM gets one hysteresis-smoothed conviction number plus
    the per-component breakdown for drill-down.  No labeled buckets
    anywhere -- the agents threshold the continuous conviction
    themselves if they want thresholds.
    """
    ctx = _base(snapshot)
    ctx.update({
        "exposure_scale_advisory": float(snapshot.get("exposure_scale", 0.0)),
        "components": {n: c["sub_conviction"]
                       for n, c in snapshot.get("components", {}).items()},
        "note": ("Fused conviction supersedes individual breadth/macro "
                 "wiring; direct engine paths remain available unchanged."),
    })
    return ctx


# ---------------------------------------------------------------- trade-risk

def risk_regime_input(snapshot: dict) -> dict:
    """Advisory regime input for trade-risk.

    ``exposure_scale_advisory`` is a *suggestion* in [0, 1].  trade-risk
    owns final sizing and may override, floor, or ignore it -- the
    arbiter does not know position-level constraints, liquidity, or
    mandate limits.
    """
    ctx = _base(snapshot)
    vol_detail = snapshot.get("components", {}).get("vol", {})
    ctx.update({
        "exposure_scale_advisory": float(snapshot.get("exposure_scale", 0.0)),
        "vol_sub_conviction": vol_detail.get("sub_conviction"),
        "note": "Advisory only -- trade-risk owns final sizing.",
    })
    return ctx


# --------------------------------------------------------------- trade-hedge

def hedge_tilt_input(snapshot: dict) -> dict:
    """Defensive/aggressive tilt suggestion for trade-hedge.

    ``defensive_tilt`` in [-1, +1]: positive = lean defensive (conviction
    below 50), negative = lean aggressive (conviction above 50), 0 =
    neutral.  Linear in conviction -- the hedge engine maps it to its
    own proposal sizes; this function never sizes anything.
    """
    ctx = _base(snapshot)
    conviction = ctx["conviction"]
    tilt = max(-1.0, min(1.0, (50.0 - conviction) / 50.0))
    ctx.update({
        "defensive_tilt": round(tilt, 4),
        "note": "Direction/magnitude suggestion only -- trade-hedge "
                "proposes overlays; it never executes.",
    })
    return ctx
