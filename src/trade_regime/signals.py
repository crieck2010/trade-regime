"""Component readers: normalize each regime engine's snapshot to a 0-100 sub-conviction.

Convention: 0 = fully risk-off, 100 = fully risk-on, 50 = neutral.
Every formula is documented here and derived in the README's "The maths"
section.

Readers take *plain snapshot dicts* (the engines' ``schema_version: 1``
contracts) so they are testable without the engines installed.  They
never raise on bad input -- they return ``ComponentUnavailable``.

Extension slot: ``read_all`` accepts ``extra={name: (snapshot, reader)}``
where ``reader`` is any callable taking a snapshot dict and returning a
``Component`` or ``ComponentUnavailable``.  That is the documented way
to add a fourth (or fifth) component without touching this module's
core readers -- see docs/METHODOLOGY.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _fnum(value, name: str):
    """Parse a float or raise ValueError with a useful message."""
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"unparseable {name}: {value!r}")


class ComponentUnavailable:
    """Sentinel: the engine's component could not be produced.

    Falsy so ``if component:`` guards work; carries a human-readable
    ``reason`` for diagnostics.  Never raised -- always returned.
    """

    def __init__(self, name: str, reason: str):
        self.name = name
        self.reason = reason

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return False

    def __repr__(self) -> str:
        return f"ComponentUnavailable({self.name!r}, reason={self.reason!r})"


@dataclass(frozen=True)
class Component:
    """One normalized regime component: a 0-100 sub-conviction."""

    name: str
    sub_conviction: float  # 0 risk-off .. 100 risk-on
    detail: dict = field(default_factory=dict)

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return True


# --------------------------------------------------------------------------
# trade-breadth: participation regime + fragility
# --------------------------------------------------------------------------

#: Regime-label base convictions.  Labels are coarse, so they sit at
#: quarter points -- never at the extremes.  Extremes must be *earned*
#: by the continuous adjustments below.
_BREADTH_REGIME_BASE = {
    "BROADENING": 75.0,
    "NEUTRAL": 50.0,
    "NARROWING": 25.0,
}

#: Fragility drag: fragility is [0, 1]; up to 50 points are subtracted.
#: Fragile markets are dangerous even when participation looks fine --
#: the drag is asymmetric by design (it only ever pushes toward
#: risk-off).  A maximally fragile market can never score above 50
#: before the thrust adjustments.
BREADTH_FRAGILITY_DRAG = 50.0

#: Zweig-style breadth thrust: rare, powerful, and worth +10 points.
BREADTH_THRUST_BONUS = 10.0

#: Narrowing-divergence warning (breadth deteriorating under the index):
#: -10 points.  Capped so one warning cannot single-handedly flip the
#: component.
BREADTH_DIVERGENCE_PENALTY = 10.0


def breadth_component(snapshot: dict | None) -> Component | ComponentUnavailable:
    """Normalize a trade-breadth snapshot to a 0-100 sub-conviction.

    ``sub = clamp(base(regime) - 50*fragility + 10*thrust - 10*divergence)``

    - ``base``: BROADENING 75 / NEUTRAL 50 / NARROWING 25 (labels are
      coarse -- quarter points, never extremes).
    - ``fragility`` [0, 1] (default 0): concentration risk drags toward
      risk-off, up to -50.
    - ``thrusts`` truthy (Zweig-style breadth thrust detected): +10.
    - ``divergence_warning`` truthy: -10.
    """
    if not isinstance(snapshot, dict):
        return ComponentUnavailable("breadth", "no snapshot supplied")
    regime = snapshot.get("regime")
    if regime not in _BREADTH_REGIME_BASE:
        return ComponentUnavailable(
            "breadth", f"unknown/missing regime {regime!r}; "
            "want BROADENING/NARROWING/NEUTRAL")
    base = _BREADTH_REGIME_BASE[regime]
    try:
        fragility = 0.0 if snapshot.get("fragility") is None else _fnum(
            snapshot.get("fragility"), "fragility")
    except ValueError as exc:
        return ComponentUnavailable("breadth", str(exc))
    fragility = max(0.0, min(1.0, fragility))
    thrust = bool(snapshot.get("thrusts"))
    divergence = bool(snapshot.get("divergence_warning"))
    sub = (base
           - BREADTH_FRAGILITY_DRAG * fragility
           + (BREADTH_THRUST_BONUS if thrust else 0.0)
           - (BREADTH_DIVERGENCE_PENALTY if divergence else 0.0))
    detail = {"basis": "regime-label-base", "regime": regime, "base": base,
              "fragility": round(fragility, 4),
              "fragility_drag": round(BREADTH_FRAGILITY_DRAG * fragility, 2),
              "thrust_bonus": BREADTH_THRUST_BONUS if thrust else 0.0,
              "divergence_penalty": BREADTH_DIVERGENCE_PENALTY if divergence else 0.0}
    return Component("breadth", round(_clamp(sub), 2), detail)


# --------------------------------------------------------------------------
# trade-macro: copper/gold regime
# --------------------------------------------------------------------------

_MACRO_REGIME_BASE = {
    "EXPANSION": 75.0,
    "NEUTRAL": 50.0,
    "CONTRACTION": 25.0,
}

#: z-score adjustment: +/-10 points at |z| = 2, linear inside,
#: saturating outside.  A 2-sigma copper/gold deviation is a strong
#: regime read; beyond that the indicator is already screaming.
MACRO_Z_FULL_SCALE = 2.0
MACRO_Z_WEIGHT = 10.0

#: Fresh transition alerts nudge the read: a just-fired CONTRACTION
#: alert is -5, a just-fired EXPANSION alert is +5.  Small on purpose --
#: alerts are discrete events, not continuous evidence.
MACRO_ALERT_NUDGE = 5.0


def macro_component(snapshot: dict | None) -> Component | ComponentUnavailable:
    """Normalize a trade-macro snapshot to a 0-100 sub-conviction.

    ``sub = clamp(base(regime) + 10*clamp(z/2, -1, 1) +/- 5*alerts)``

    - ``base``: EXPANSION 75 / NEUTRAL 50 / CONTRACTION 25.
    - ``z_score`` (copper/gold 252d z): +/-10 points at |z| = 2.
    - ``transition_alerts`` (list of strings): a fresh CONTRACTION
      alert -5, a fresh EXPANSION alert +5.
    """
    if not isinstance(snapshot, dict):
        return ComponentUnavailable("macro", "no snapshot supplied")
    regime = snapshot.get("regime")
    if regime not in _MACRO_REGIME_BASE:
        return ComponentUnavailable(
            "macro", f"unknown/missing regime {regime!r}; "
            "want EXPANSION/CONTRACTION/NEUTRAL")
    base = _MACRO_REGIME_BASE[regime]
    z_adj = 0.0
    z = snapshot.get("z_score")
    if z is not None:
        try:
            zf = _fnum(z, "z_score")
        except ValueError as exc:
            return ComponentUnavailable("macro", str(exc))
        z_adj = MACRO_Z_WEIGHT * max(-1.0, min(1.0, zf / MACRO_Z_FULL_SCALE))
    alert_adj = 0.0
    alerts = snapshot.get("transition_alerts") or []
    if isinstance(alerts, (list, tuple)):
        joined = " ".join(str(a) for a in alerts).upper()
        if "CONTRACTION" in joined:
            alert_adj -= MACRO_ALERT_NUDGE
        if "EXPANSION" in joined:
            alert_adj += MACRO_ALERT_NUDGE
    sub = base + z_adj + alert_adj
    detail = {"basis": "regime-label-base", "regime": regime, "base": base,
              "z_score": z, "z_adjustment": round(z_adj, 2),
              "alert_adjustment": round(alert_adj, 2)}
    return Component("macro", round(_clamp(sub), 2), detail)


# --------------------------------------------------------------------------
# trade-volforecast: volatility stress -> risk appetite
# --------------------------------------------------------------------------

#: Vol-of-vol penalty threshold: when the vol of vol exceeds 0.5 the
#: vol regime itself is unstable -- add stress.
VOL_OF_VOL_THRESHOLD = 0.5
VOL_OF_VOL_PENALTY = 0.10

#: Forecast acceleration: if the GARCH/HAR forecast exceeds 1.25x
#: current realized vol, vol is *accelerating* into the spike -- add
#: stress on top of the level read.
FORECAST_ACCEL_RATIO = 1.25
FORECAST_ACCEL_PENALTY = 0.15


def vol_component(vol_summary: dict | None) -> Component | ComponentUnavailable:
    """Normalize a trade-volforecast summary to a 0-100 sub-conviction.

    ``stress = 0.6*pct(current) + 0.4*pct(forecast) [+ 0.15 if
    forecast > 1.25*current] [+ 0.10 if vol_of_vol > 0.5]``;
    ``sub = 100 * (1 - stress)``.

    - ``current_vol`` (or ``realized_vol``) vs ``vol_min``/``vol_max``
      trailing window gives the level percentile.  High vol = risk-off
      pressure, hence the inversion.
    - ``forecast_vol`` (optional, GARCH/HAR): the forward read gets
      40% of the stress -- vol is mean-reverting, so the forecast
      tempers the spot read.  An accelerating forecast adds +0.15.
    - ``vol_of_vol`` (optional): unstable vol regimes add +0.10.
    - Flat history (max == min): percentile undefined -> 0.5
      (no dispersion, no information, neutral).
    """
    if not isinstance(vol_summary, dict):
        return ComponentUnavailable("vol", "no vol summary supplied")
    try:
        current = _fnum(vol_summary.get("current_vol",
                                        vol_summary.get("realized_vol")),
                        "current_vol/realized_vol")
        vmin = _fnum(vol_summary["vol_min"], "vol_min")
        vmax = _fnum(vol_summary["vol_max"], "vol_max")
    except (KeyError, ValueError) as exc:
        return ComponentUnavailable(
            "vol", f"summary needs current_vol, vol_min, vol_max ({exc})")
    if vmax <= vmin:
        pct = 0.5
        basis = "flat-history"
    else:
        pct = max(0.0, min(1.0, (current - vmin) / (vmax - vmin)))
        basis = "percentile"
    fcast = vol_summary.get("forecast_vol")
    accel = False
    if fcast is not None:
        try:
            fcast_f = _fnum(fcast, "forecast_vol")
        except ValueError as exc:
            return ComponentUnavailable("vol", str(exc))
        if vmax <= vmin:
            f_pct = 0.5
        else:
            f_pct = max(0.0, min(1.0, (fcast_f - vmin) / (vmax - vmin)))
        stress = 0.6 * pct + 0.4 * f_pct
        accel = current > 0 and fcast_f > FORECAST_ACCEL_RATIO * current
        if accel:
            stress += FORECAST_ACCEL_PENALTY
        detail_extra = {"forecast_vol": fcast_f, "forecast_percentile": round(f_pct, 4),
                        "acceleration": accel}
    else:
        stress = pct
        detail_extra = {"forecast_vol": None, "acceleration": False}
    vov = vol_summary.get("vol_of_vol")
    vov_penalty = False
    if vov is not None:
        try:
            vov_f = _fnum(vov, "vol_of_vol")
        except ValueError as exc:
            return ComponentUnavailable("vol", str(exc))
        if vov_f > VOL_OF_VOL_THRESHOLD:
            stress += VOL_OF_VOL_PENALTY
            vov_penalty = True
    stress = max(0.0, min(1.0, stress))
    detail = {"basis": basis, "percentile": round(pct, 4),
              "current_vol": current, "stress": round(stress, 4),
              "vol_of_vol_penalty": vov_penalty}
    detail.update(detail_extra)
    return Component("vol", round(_clamp(100.0 * (1.0 - stress)), 2), detail)


# --------------------------------------------------------------------------
# reader registry + read_all
# --------------------------------------------------------------------------

#: Built-in readers: component name -> reader function.
READERS: dict[str, Callable[[dict | None], Component | ComponentUnavailable]] = {
    "macro": macro_component,
    "breadth": breadth_component,
    "vol": vol_component,
}


def read_all(macro_snapshot: dict | None = None,
             breadth_snapshot: dict | None = None,
             vol_summary: dict | None = None,
             extra: dict | None = None) -> dict:
    """Read every component; missing engines become ``ComponentUnavailable``.

    ``extra`` is the extension slot: ``{name: (snapshot, reader)}``
    where ``reader`` takes a snapshot dict and returns a ``Component``
    or ``ComponentUnavailable``.  A misbehaving extra reader is
    contained -- it becomes ``ComponentUnavailable`` for that name,
    never an exception.

    Never raises.  The arbiter re-weights whatever is available.
    """
    snapshots = {"macro": macro_snapshot, "breadth": breadth_snapshot,
                 "vol": vol_summary}
    out: dict = {}
    for name, reader in READERS.items():
        try:
            out[name] = reader(snapshots[name])
        except Exception as exc:  # noqa: BLE001 - containment
            out[name] = ComponentUnavailable(name, f"reader crashed: {exc}")
    for name, spec in (extra or {}).items():
        try:
            snap, reader = spec
            comp = reader(snap)
            if not isinstance(comp, (Component, ComponentUnavailable)):
                raise TypeError(f"reader for {name!r} returned {type(comp)}")
            out[name] = comp
        except Exception as exc:  # noqa: BLE001 - containment
            out[name] = ComponentUnavailable(name, f"extra reader failed: {exc}")
    return out
