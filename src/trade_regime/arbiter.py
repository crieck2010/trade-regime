"""The regime arbiter: fuse signal scores into one conviction number.

Pipeline: weighted fusion -> composite score in [-1, +1] ->
graded conviction 0-100% -> Schmitt-trigger stance with hysteresis ->
``RegimeState`` plain-data dict.

Design rules (user-directed):
- graded conviction *sizing*, not labeled buckets;
- stance labels are display-only, derived from the score, never used
  for decisions;
- ``assess()`` is a pure function of (signals, previous stance) so it
  is trivially parallelizable; ``RegimeArbiter`` just carries stance.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .signals import Signal, SignalUnavailable

SCHEMA_VERSION = 1

#: Default fusion weights.  Rationale: macro (copper/gold) is the
#: slowest-moving, most fundamental read — it anchors.  Breadth
#: (participation + fragility) confirms or contradicts price action.
#: Vol is the fastest and noisiest; it gets the smallest weight so a
#: single vol spike cannot flip the arbiter by itself.
DEFAULT_WEIGHTS = {"macro": 0.40, "breadth": 0.35, "vol": 0.25}

#: |score| at which conviction saturates at 100.  A composite of ±0.8
#: needs strong agreement across signals; beyond that, extra score is
#: not extra information.
CONVICTION_SATURATION = 0.80

#: Schmitt-trigger geometry.  From neutral, the composite must reach
#: ±(threshold + band) = ±0.40 to take a stance; a taken stance is
#: released back to neutral at ±(threshold - band) = ±0.10.  The dead
#: zone between 0.10 and 0.40 is where noise lives — and where the
#: arbiter refuses to flap.
DEFAULT_THRESHOLD = 0.25
DEFAULT_BAND = 0.15

#: Display-only labels.  Decisions use score/conviction, never these.
STANCE_LABELS = {-1: "DEFENSIVE", 0: "NEUTRAL", 1: "CONSTRUCTIVE"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_weights(weights: dict) -> dict:
    """Validate a weight map; raise ValueError on nonsense."""
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
        raise ValueError("weights sum to zero — nothing to fuse")
    return clean


def fuse(signals: dict, weights: dict | None = None):
    """Weighted fusion of available signals.

    Returns ``(score, contributions, missing)`` where ``score`` is in
    [-1, +1].  Missing/unavailable signals are dropped and the
    remaining weights renormalized to sum to 1 — documented, not
    silent: every missing name lands in ``missing`` and only the
    weights actually used appear in ``contributions``.

    All-missing -> score 0.0 (no information is neutral, not
    risk-off; risk-off requires *evidence*).
    """
    weights = validate_weights(dict(DEFAULT_WEIGHTS) if weights is None else weights)
    available = [(n, s) for n, s in signals.items() if isinstance(s, Signal)]
    missing = sorted(n for n, s in signals.items()
                     if isinstance(s, SignalUnavailable))
    # Ignore unknown junk gracefully, but note truly-unknown names are
    # not part of the contract: only weight keys and signal names fuse.
    w = {n: weights.get(n, 0.0) for n, _ in available}
    total = sum(w.values())
    if total <= 0 or not available:
        return 0.0, {}, missing
    w_used = {n: wi / total for n, wi in w.items()}
    contributions = {}
    score = 0.0
    for n, s in available:
        c = w_used[n] * s.score
        score += c
        contributions[n] = {
            "score": round(s.score, 4),
            "weight": round(w_used[n], 4),
            "contribution": round(c, 4),
            "detail": s.detail,
        }
    score = max(-1.0, min(1.0, score))
    return round(score, 4), contributions, missing


def conviction_of(score: float) -> float:
    """Graded conviction 0-100% from |score|.

    Piecewise-linear: ``100 * min(1, |score| / 0.8)``.  Monotone in
    |score| by construction — more agreement can never mean less
    conviction.  Linear (not logistic): every unit of score buys the
    same unit of conviction, which keeps the sizing layer honest about
    what it's responding to.
    """
    return round(100.0 * min(1.0, abs(float(score)) / CONVICTION_SATURATION), 1)


def next_stance(prev: int, score: float,
                threshold: float = DEFAULT_THRESHOLD,
                band: float = DEFAULT_BAND) -> int:
    """Schmitt-trigger stance update.

    - From 0: take +1 at score >= threshold+band, -1 at <= -(threshold+band).
    - From ±1: release to 0 when the score decays past ±(threshold-band).
    - A violent reversal walks *through* neutral (two assessments), it
      never teleports from +1 to -1: the dead zone must be crossed.

    Pure function — the hysteresis memory is exactly ``prev``.
    """
    if prev not in (-1, 0, 1):
        raise ValueError(f"prev stance must be -1/0/1, got {prev!r}")
    engage = threshold + band
    release = threshold - band
    if prev == 0:
        if score >= engage:
            return 1
        if score <= -engage:
            return -1
        return 0
    if prev == 1:
        return 0 if score <= release else 1
    return 0 if score >= -release else -1


class RegimeArbiter:
    """Stateful arbiter: carries the hysteresis stance across assessments.

    ``assess(signals)`` -> ``RegimeState`` dict (schema_version 1,
    JSON-serializable).  The only state is ``self.stance``; everything
    else is recomputed, so a stale process can be rebuilt from history.
    """

    def __init__(self, weights: dict | None = None,
                 threshold: float = DEFAULT_THRESHOLD,
                 band: float = DEFAULT_BAND):
        self.weights = validate_weights(dict(DEFAULT_WEIGHTS) if weights is None else weights)
        if not (0 <= band <= threshold):
            raise ValueError(
                f"need 0 <= band <= threshold, got band={band}, threshold={threshold}")
        self.threshold = float(threshold)
        self.band = float(band)
        self.stance = 0

    def assess(self, signals: dict) -> dict:
        """Fuse signals, update stance, return the RegimeState dict."""
        score, contributions, missing = fuse(signals, self.weights)
        conviction = conviction_of(score)
        prev = self.stance
        self.stance = next_stance(prev, score, self.threshold, self.band)
        state = {
            "schema_version": SCHEMA_VERSION,
            "ts": _utcnow(),
            "score": score,
            "conviction": conviction,
            "stance": self.stance,
            "stance_label": STANCE_LABELS[self.stance],  # display only
            "prev_stance": prev,
            "transition": self.stance != prev,
            "contributions": contributions,
            "weights_used": {n: c["weight"] for n, c in contributions.items()},
            "missing": missing,
            "n_signals": len(contributions),
            "config": {
                "threshold": self.threshold,
                "band": self.band,
                "engage_at": round(self.threshold + self.band, 4),
                "release_at": round(self.threshold - self.band, 4),
            },
        }
        json.dumps(state)  # contract enforcement: must survive JSON
        return state

    def assess_series(self, series: list[dict]) -> list[dict]:
        """Assess a sequence of signal-dicts in order (history replay)."""
        return [self.assess(s) for s in series]

    def reset(self) -> None:
        """Drop hysteresis memory back to neutral."""
        self.stance = 0
