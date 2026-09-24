"""Signal readers: normalize each regime engine's snapshot to [-1, +1].

Convention: -1 = fully risk-off, +1 = fully risk-on, 0 = neutral or
unknown.  Every formula is documented here and derived in the README's
"The maths" section.

Readers take *plain snapshot dicts* (the engines' schema_version: 1
contracts) so they are testable without the engines installed.  They
never raise on bad input — they return ``SignalUnavailable``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


class SignalUnavailable:
    """Sentinel: the engine's signal could not be produced.

    Falsy so ``if signal:`` guards work; carries a human-readable
    ``reason`` for diagnostics.  Never raised — always returned.
    """

    def __init__(self, name: str, reason: str):
        self.name = name
        self.reason = reason

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return False

    def __repr__(self) -> str:
        return f"SignalUnavailable({self.name!r}, reason={self.reason!r})"


@dataclass(frozen=True)
class Signal:
    """One normalized regime signal."""

    name: str
    score: float  # in [-1, +1]; -1 risk-off, +1 risk-on
    detail: dict = field(default_factory=dict)

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return True


# --------------------------------------------------------------------------
# trade-macro: copper/gold regime
# --------------------------------------------------------------------------

_MACRO_REGIME_FALLBACK = {
    "EXPANSION": 0.5,
    "CONTRACTION": -0.5,
    "NEUTRAL": 0.0,
}

#: z-score magnitude mapped to a full-scale signal.  A |z| of 3 is a
#: ~3-sigma macro regime — about as extreme as this indicator gets.
MACRO_Z_FULL_SCALE = 3.0


def macro_score(snapshot: dict | None) -> Signal | SignalUnavailable:
    """Normalize a trade-macro snapshot to [-1, +1].

    Primary: ``score = clamp(z_252 / 3)``.  A 3-sigma copper/gold
    deviation is a full-scale regime read; linear inside, saturating
    outside (extremes beyond 3 sigma carry no extra information — the
    indicator is already screaming).

    Fallback (no z-score, e.g. warm-up): map the regime label to
    ±0.5 / 0.0.  Deliberately half-scale: a bare label without the
    continuous z behind it is a weaker statement.
    """
    if not isinstance(snapshot, dict):
        return SignalUnavailable("macro", "no snapshot supplied")
    z = snapshot.get("z_score")
    if z is not None:
        try:
            score = _clamp(float(z) / MACRO_Z_FULL_SCALE)
        except (TypeError, ValueError):
            return SignalUnavailable("macro", f"unparseable z_score {z!r}")
        return Signal("macro", score, {"basis": "z_score/3",
                                       "z_score": z,
                                       "regime": snapshot.get("regime")})
    regime = snapshot.get("regime")
    if regime in _MACRO_REGIME_FALLBACK:
        return Signal("macro", _MACRO_REGIME_FALLBACK[regime],
                      {"basis": "regime-label-fallback", "regime": regime})
    return SignalUnavailable("macro", "snapshot has neither z_score nor regime")


# --------------------------------------------------------------------------
# trade-breadth: participation regime + fragility
# --------------------------------------------------------------------------

#: The breadth regime_score is a trailing-252d z composite with ±0.5
#: classification thresholds.  Full scale at 1.5 keeps the ±0.5
#: "official" boundary at one-third of the dial — classification-grade
#: evidence, not max conviction.
BREADTH_SCORE_FULL_SCALE = 1.5

#: Fragility drag: fragility is [0,1]; half of it is subtracted from the
#: breadth score.  Fragile markets are dangerous even when participation
#: looks fine — the drag is asymmetric by design (it only ever pushes
#: toward risk-off).
BREADTH_FRAGILITY_DRAG = 0.5

_BREADTH_REGIME_FALLBACK = {
    "BROADENING": 0.5,
    "NARROWING": -0.5,
    "NEUTRAL": 0.0,
}


def breadth_score(snapshot: dict | None) -> Signal | SignalUnavailable:
    """Normalize a trade-breadth snapshot to [-1, +1].

    ``score = clamp(clamp(regime_score / 1.5) - 0.5 * fragility)``.

    The fragility term is the point of the breadth signal: a market can
    read NEUTRAL on participation while concentration risk quietly
    builds.  Subtracting half the fragility gauge means a maximally
    fragile market can never score above +0.5 no matter what the
    regime_score says.
    """
    if not isinstance(snapshot, dict):
        return SignalUnavailable("breadth", "no snapshot supplied")
    fragility = snapshot.get("fragility")
    try:
        fragility_f = 0.0 if fragility is None else float(fragility)
    except (TypeError, ValueError):
        return SignalUnavailable("breadth", f"unparseable fragility {fragility!r}")
    fragility_f = _clamp(fragility_f, 0.0, 1.0)

    rs = snapshot.get("regime_score")
    if rs is not None:
        try:
            base = _clamp(float(rs) / BREADTH_SCORE_FULL_SCALE)
        except (TypeError, ValueError):
            return SignalUnavailable("breadth", f"unparseable regime_score {rs!r}")
        basis = "regime_score/1.5"
    else:
        regime = snapshot.get("regime")
        if regime not in _BREADTH_REGIME_FALLBACK:
            return SignalUnavailable("breadth",
                                     "snapshot has neither regime_score nor regime")
        base = _BREADTH_REGIME_FALLBACK[regime]
        basis = "regime-label-fallback"
    score = _clamp(base - BREADTH_FRAGILITY_DRAG * fragility_f)
    return Signal("breadth", score,
                  {"basis": basis, "regime_score": rs,
                   "regime": snapshot.get("regime"),
                   "fragility": fragility_f})


# --------------------------------------------------------------------------
# trade-volforecast: volatility percentile -> risk appetite
# --------------------------------------------------------------------------

def vol_score(vol_summary: dict | None) -> Signal | SignalUnavailable:
    """Normalize a trade-volforecast summary to [-1, +1].

    ``percentile = (current - min) / (max - min)`` over the trailing
    window; ``score = 1 - 2 * percentile``.  Low vol (complacent but
    tradable markets) scores risk-on; high vol scores risk-off.
    Linear in percentile — vol is already the fastest, noisiest input,
    so no extra curvature is warranted.

    Flat history (max == min) yields 0.0: no dispersion, no information.
    """
    if not isinstance(vol_summary, dict):
        return SignalUnavailable("vol", "no vol summary supplied")
    try:
        current = float(vol_summary["current_vol"])
        vmin = float(vol_summary["vol_min"])
        vmax = float(vol_summary["vol_max"])
    except (KeyError, TypeError, ValueError):
        return SignalUnavailable(
            "vol", "summary needs current_vol/vol_min/vol_max")
    if vmax <= vmin:
        return Signal("vol", 0.0, {"basis": "flat-history", "percentile": None})
    pct = _clamp((current - vmin) / (vmax - vmin), 0.0, 1.0)
    return Signal("vol", _clamp(1.0 - 2.0 * pct),
                  {"basis": "percentile", "percentile": pct,
                   "current_vol": current})


def read_all(macro_snapshot: dict | None = None,
             breadth_snapshot: dict | None = None,
             vol_summary: dict | None = None) -> dict:
    """Read every signal; missing engines become ``SignalUnavailable``.

    Never raises.  The arbiter re-weights whatever is available.
    """
    return {
        "macro": macro_score(macro_snapshot),
        "breadth": breadth_score(breadth_snapshot),
        "vol": vol_score(vol_summary),
    }
