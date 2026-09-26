"""The regime arbiter: fuse sub-convictions into one graded conviction number.

Pipeline: component transforms (0-100 each) -> weighted composite
(0-100) -> hysteresis on the conviction number itself ->
``snapshot`` dict (schema_version 1).

Design rules (user-directed):
- **Graded conviction, continuous 0-100%** -- the arbiter outputs a
  number; consumers threshold if they want.  No labeled buckets:
  buckets cut from noisy signals are false precision.
- **Hysteresis on conviction, not on labels.**  ``conviction_t`` holds
  ``conviction_{t-1}`` unless the raw composite moves beyond a deadband
  (default +/-10 pts) -- in which case a *large* move acts at once --
  or persists beyond the band edge for N consecutive observations
  (default 3), which releases smaller-but-stubborn moves.  A max
  per-assessment change (default 25 pts) rate-limits even released
  moves.  Why: daily regime reads are noisy; without memory the
  downstream sizing layer whipsaws on boundary noise.
- ``assess()`` is a pure function of (components, prior memory), so the
  only state a ``RegimeArbiter`` carries is the held conviction plus a
  persistence counter.  That state serializes to a tiny dict, so a
  restarted process (or the CLI) rebuilds it exactly.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .licensing import CURRENT_VERSION
from .signals import Component, ComponentUnavailable

SCHEMA_VERSION = 1

#: Default fusion weights.  Rationale: macro (copper/gold) is the
#: slowest-moving, most fundamental read -- it anchors.  Breadth
#: (participation + fragility) confirms or contradicts price action.
#: Vol is the fastest and noisiest; it gets the smallest weight so a
#: single vol spike can temper the composite but never flip it alone.
DEFAULT_WEIGHTS = {"macro": 0.40, "breadth": 0.35, "vol": 0.25}

#: Hysteresis geometry (conviction points, 0-100 scale).
#: - deadband: raw moves within +/- this of the held conviction are
#:   ignored (noise).
#: - confirm_band: raw moves beyond this act *immediately* (with rate
#:   limiting) -- a violent regime break should not wait for
#:   confirmation.
#: - persistence_n: raw moves beyond the deadband but inside the
#:   confirm band need this many consecutive same-direction
#:   observations to release -- stubborn small moves earn trust.
DEFAULT_DEADBAND = 10.0
DEFAULT_CONFIRM_BAND = 20.0
DEFAULT_PERSISTENCE_N = 3

#: Max conviction change per assessment, even on release.  Regime
#: changes are real but sizing should never teleport.
DEFAULT_MAX_DAILY_CHANGE = 25.0

#: All components missing -> composite falls back to neutral.  No
#: information is neutral, not risk-off; risk-off requires *evidence*.
NEUTRAL_FALLBACK = 50.0


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_weights(weights: dict) -> dict:
    """Validate a weight map; raise ValueError on nonsense.

    Extra component names are allowed (the extension slot) -- they
    simply get no weight unless configured.
    """
    if not isinstance(weights, dict) or not weights:
        raise ValueError("weights must be a non-empty dict")
    clean = {}
    for name, w in weights.items():
        try:
            wf = float(w)
        except (TypeError, ValueError):
            raise ValueError(f"weight for {name!r} is not a number: {w!r}")
        if wf < 0:
            raise ValueError(f"weight for {name!r} is negative: {wf}")
        clean[name] = wf
    if sum(clean.values()) <= 0:
        raise ValueError("weights sum to zero -- nothing to fuse")
    return clean


def fuse(components: dict, weights: dict | None = None):
    """Weighted fusion of available components into a 0-100 composite.

    Returns ``(composite, contributions, missing)``.  Unavailable
    components are dropped and the remaining weights renormalized --
    documented, not silent: every missing name lands in ``missing``
    and only the weights actually used appear in ``contributions``.

    All-missing -> composite 50.0 (neutral fallback).
    """
    weights = validate_weights(dict(DEFAULT_WEIGHTS) if weights is None else weights)
    available = [(n, c) for n, c in components.items() if isinstance(c, Component)]
    missing = sorted(n for n, c in components.items()
                     if isinstance(c, ComponentUnavailable))
    w = {n: weights.get(n, 0.0) for n, _ in available}
    total = sum(w.values())
    if total <= 0 or not available:
        return NEUTRAL_FALLBACK, {}, missing
    contributions = {}
    composite = 0.0
    for n, c in available:
        w_used = w[n] / total
        contrib = w_used * c.sub_conviction
        composite += contrib
        contributions[n] = {
            "sub_conviction": round(c.sub_conviction, 2),
            "weight": round(w_used, 4),
            "contribution": round(contrib, 2),
            "detail": c.detail,
        }
    composite = max(0.0, min(100.0, composite))
    return round(composite, 2), contributions, missing


def exposure_scale(conviction: float) -> float:
    """Advisory 0-1 exposure scale from conviction.

    Linear: ``conviction / 100``.  Deliberately dumb -- the arbiter
    suggests, **trade-risk owns final sizing**.  Any floor, curve, or
    stand-down rule lives downstream, not here.
    """
    return round(max(0.0, min(1.0, float(conviction) / 100.0)), 4)


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


class RegimeArbiter:
    """Stateful arbiter: carries conviction memory across assessments.

    ``assess(components)`` -> snapshot dict (schema_version 1,
    JSON-serializable).  The only memory is the held conviction plus
    the persistence counter -- see ``memory_dict`` / ``restore`` for
    the exact serializable state.
    """

    def __init__(self, weights: dict | None = None,
                 deadband: float = DEFAULT_DEADBAND,
                 confirm_band: float = DEFAULT_CONFIRM_BAND,
                 persistence_n: int = DEFAULT_PERSISTENCE_N,
                 max_daily_change: float = DEFAULT_MAX_DAILY_CHANGE,
                 preset_name: str = "custom"):
        self.weights = validate_weights(dict(DEFAULT_WEIGHTS) if weights is None else weights)
        if not (0 <= deadband <= confirm_band):
            raise ValueError(
                f"need 0 <= deadband <= confirm_band, got {deadband}, {confirm_band}")
        if persistence_n < 1:
            raise ValueError(f"persistence_n must be >= 1, got {persistence_n}")
        if max_daily_change <= 0:
            raise ValueError(f"max_daily_change must be > 0, got {max_daily_change}")
        self.deadband = float(deadband)
        self.confirm_band = float(confirm_band)
        self.persistence_n = int(persistence_n)
        self.max_daily_change = float(max_daily_change)
        self.preset_name = preset_name
        self.conviction: float | None = None
        self._persist_count = 0
        self._persist_dir = 0

    # ------------------------------------------------------------ memory

    def memory_dict(self) -> dict:
        """Serializable hysteresis memory (for CLI --state round-trips)."""
        return {"conviction": self.conviction,
                "persist_count": self._persist_count,
                "persist_dir": self._persist_dir}

    def restore(self, memory: dict) -> None:
        """Restore hysteresis memory from ``memory_dict()`` output."""
        self.conviction = (None if memory.get("conviction") is None
                           else float(memory["conviction"]))
        self._persist_count = int(memory.get("persist_count", 0))
        self._persist_dir = int(memory.get("persist_dir", 0))

    def reset(self) -> None:
        """Drop hysteresis memory (fresh start)."""
        self.conviction = None
        self._persist_count = 0
        self._persist_dir = 0

    # ------------------------------------------------------------ assess

    def _apply_hysteresis(self, raw: float):
        """Return ``(conviction, state, reason)`` for one raw composite."""
        held = self.conviction
        if held is None:
            self.conviction = round(raw, 1)
            return self.conviction, "updated", "initialization"

        delta = raw - held
        adelta = abs(delta)

        if adelta <= self.deadband:
            self._persist_count = 0
            self._persist_dir = 0
            return (round(held, 1), "held",
                    f"within deadband (+/-{self.deadband:g} pts)")

        if adelta > self.confirm_band:
            self._persist_count = 0
            self._persist_dir = 0
            new = held + _sign(delta) * min(adelta, self.max_daily_change)
            self.conviction = round(max(0.0, min(100.0, new)), 1)
            return (self.conviction, "updated",
                    f"large move beyond confirm band (+/-{self.confirm_band:g} pts), "
                    f"rate-limited to {self.max_daily_change:g} pts")

        direction = _sign(delta)
        if direction == self._persist_dir:
            self._persist_count += 1
        else:
            self._persist_dir = direction
            self._persist_count = 1
        if self._persist_count >= self.persistence_n:
            self._persist_count = 0
            self._persist_dir = 0
            new = held + direction * min(adelta, self.max_daily_change)
            self.conviction = round(max(0.0, min(100.0, new)), 1)
            return (self.conviction, "updated",
                    f"persistent move beyond band edge "
                    f"({self.persistence_n}/{self.persistence_n} consecutive obs), "
                    f"rate-limited to {self.max_daily_change:g} pts")
        return (round(held, 1), "held",
                f"beyond deadband, awaiting persistence "
                f"({self._persist_count}/{self.persistence_n})")

    def assess(self, components: dict, provenance: dict | None = None) -> dict:
        """Fuse components, apply hysteresis, return the snapshot dict."""
        composite, contributions, missing = fuse(components, self.weights)
        prior = self.conviction
        conviction, h_state, h_reason = self._apply_hysteresis(composite)
        snap = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": uuid.uuid4().hex,
            "timestamp": _utcnow(),
            "conviction": conviction,
            "composite_raw": composite,
            "components": contributions,
            "weights_configured": {k: round(float(v), 4)
                                   for k, v in self.weights.items()},
            "hysteresis": {
                "state": h_state,
                "reason": h_reason,
                "prior_conviction": (None if prior is None else round(prior, 1)),
                "deadband": self.deadband,
                "confirm_band": self.confirm_band,
                "persistence": f"{self._persist_count}/{self.persistence_n}",
                "max_daily_change": self.max_daily_change,
            },
            "exposure_scale": exposure_scale(conviction),
            "missing": missing,
            "provenance": {
                "input_snapshot_ids": (provenance or {}).get("input_snapshot_ids", {}),
                "input_schema_versions": (provenance or {}).get("input_schema_versions", {}),
                "trade_regime_version": CURRENT_VERSION,
                "preset": self.preset_name,
            },
        }
        json.dumps(snap)  # contract enforcement: must survive JSON
        return snap

    def assess_series(self, series: list[dict],
                      provenances: list[dict] | None = None) -> list[dict]:
        """Assess a sequence of component-dicts in order (history replay)."""
        provenances = provenances or [None] * len(series)
        return [self.assess(c, p) for c, p in zip(series, provenances)]
