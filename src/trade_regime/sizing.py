"""Conviction -> exposure: how the arbiter's number becomes position size.

Two layers:

1. ``exposure_scale(conviction)``: the master dial in [0, 1] — what
   fraction of the book's *normal* gross exposure is allowed.
2. ``sleeve_scale(sleeve, conviction)``: per-strategy-sleeve response
   curves.  Sleeves die in a deliberate order as conviction falls;
   the order encodes *why* each sleeve is fragile.

The hard STAND_DOWN rule: conviction below the floor -> every scale is
0.  Flat is a position.
"""

from __future__ import annotations

#: Conviction below this -> full stand-down, all exposures zero.
#: 25% means "the arbiter can barely tell which regime we're in" —
#: trading on that is noise-trading.
STAND_DOWN_FLOOR = 25.0

SLEEVES = ("trend", "mean_reversion", "short_vol")


def stand_down(conviction: float) -> bool:
    """True when conviction is below the floor: go flat, no debate."""
    return float(conviction) < STAND_DOWN_FLOOR


def exposure_scale(conviction: float) -> float:
    """Master exposure dial in [0, 1].

    0 below the stand-down floor; then 0.2 at the floor ramping
    linearly to 1.0 at conviction 100.  The 0.2 intercept is
    deliberate: crossing back above the floor re-enters *small*.
    Re-entry after a stand-down should be tentative, not triumphant.
    """
    c = float(conviction)
    if c < STAND_DOWN_FLOOR:
        return 0.0
    return round(0.2 + 0.8 * (c - STAND_DOWN_FLOOR) / (100.0 - STAND_DOWN_FLOOR), 4)


def sleeve_scale(sleeve: str, conviction: float) -> float:
    """Per-sleeve response in [0, 1].  Shutdown order is the design:

    - ``mean_reversion`` dies first (dead below 40, full at 70).
      Rationale: mean reversion needs a stable, two-sided market.  It
      is the first thing regime change kills — ranges break, and the
      sleeve that fades extremes starts catching falling knives.
    - ``trend`` tapers linearly with conviction (conviction/100).
      Rationale: trends exist in every regime; only the *size* should
      change.  Never binary — cutting trend to zero on a wobble
      discards the sleeve with the best crisis alpha.
    - ``short_vol`` needs high conviction (dead below 65, full at 90).
      Rationale: short vol is picking up pennies in front of a
      steamroller.  It is only paid when the regime is strongly
      constructive and vol is priced to stay low.
    """
    if sleeve not in SLEEVES:
        raise ValueError(f"unknown sleeve {sleeve!r}; choose from {SLEEVES}")
    c = float(conviction)
    if c < STAND_DOWN_FLOOR:
        return 0.0
    if sleeve == "mean_reversion":
        if c < 40.0:
            return 0.0
        return round(min(1.0, (c - 40.0) / 30.0), 4)
    if sleeve == "trend":
        return round(c / 100.0, 4)
    # short_vol
    if c < 65.0:
        return 0.0
    return round(min(1.0, (c - 65.0) / 25.0), 4)


def sleeve_scales(conviction: float) -> dict:
    """All sleeve scales at once, plus the master dial."""
    return {
        "exposure_scale": exposure_scale(conviction),
        "stand_down": stand_down(conviction),
        "sleeves": {s: sleeve_scale(s, conviction) for s in SLEEVES},
    }
