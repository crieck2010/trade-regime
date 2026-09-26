"""Named risk postures for the arbiter.

A preset is a named bundle of (weights, deadband, confirm_band,
persistence_n, max_daily_change) so the CLI, dashboards, and research
code share the same three risk postures instead of hand-rolling
numbers.  Every number below carries its rationale -- weights and
bands are *policy choices*, not discovered constants (see the README's
"Honest limitations").
"""

from __future__ import annotations

from .arbiter import (
    DEFAULT_CONFIRM_BAND,
    DEFAULT_DEADBAND,
    DEFAULT_MAX_DAILY_CHANGE,
    DEFAULT_PERSISTENCE_N,
    DEFAULT_WEIGHTS,
)

PRESETS = {
    "balanced": {
        "description": "Default posture.",
        "rationale": (
            "Macro (copper/gold) anchors: it is the slowest-moving, most "
            "fundamental read. Breadth confirms or contradicts what price "
            "action claims. Vol is the fastest and noisiest input, so it "
            "gets the smallest weight -- a single vol spike can temper the "
            "composite but never flip it alone. Deadband +/-10 pts ignores "
            "day-to-day noise in the raw composite; a move beyond +/-20 "
            "acts immediately (a violent break should not wait); smaller "
            "excursions need 3 consecutive same-direction observations. "
            "Conviction moves at most 25 pts per assessment so downstream "
            "sizing never teleports."
        ),
        "weights": dict(DEFAULT_WEIGHTS),
        "deadband": DEFAULT_DEADBAND,
        "confirm_band": DEFAULT_CONFIRM_BAND,
        "persistence_n": DEFAULT_PERSISTENCE_N,
        "max_daily_change": DEFAULT_MAX_DAILY_CHANGE,
    },
    "conservative": {
        "description": "Slow to engage, respectful of risk-off. For live capital.",
        "rationale": (
            "Overweights macro (0.50) -- the slowest signal -- and "
            "underweights vol (0.20), so fast noise moves the dial least. "
            "Wider deadband (+/-15) and a 4-observation persistence rule "
            "mean the arbiter only moves on sustained evidence; the 15-pt "
            "rate limit keeps position sizing gradual. The price is "
            "lateness: in a genuine regime break the conservative arbiter "
            "is the last to know, by design."
        ),
        "weights": {"macro": 0.50, "breadth": 0.30, "vol": 0.20},
        "deadband": 15.0,
        "confirm_band": 30.0,
        "persistence_n": 4,
        "max_daily_change": 15.0,
    },
    "aggressive": {
        "description": "Fast to engage. Research and high-conviction books only.",
        "rationale": (
            "Overweights breadth (0.40) -- the fastest *fundamental* read "
            "(participation leads price at turns) -- and gives vol a full "
            "0.30 voice. Tighter deadband (+/-7), 2-observation "
            "persistence, and a 40-pt rate limit let conviction track the "
            "raw composite closely. Expect whipsaw: this preset trades "
            "stability for speed and will flap in choppy regimes."
        ),
        "weights": {"macro": 0.30, "breadth": 0.40, "vol": 0.30},
        "deadband": 7.0,
        "confirm_band": 14.0,
        "persistence_n": 2,
        "max_daily_change": 40.0,
    },
}


def get_preset(name: str) -> dict:
    """Return a copy of the named preset; ValueError on unknown name."""
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; choose from {sorted(PRESETS)}")
    p = PRESETS[name]
    return {**p, "weights": dict(p["weights"])}


def arbiter_kwargs(name: str) -> dict:
    """Kwargs for ``RegimeArbiter(...)`` from a preset name."""
    p = get_preset(name)
    return {
        "weights": p["weights"],
        "deadband": p["deadband"],
        "confirm_band": p["confirm_band"],
        "persistence_n": p["persistence_n"],
        "max_daily_change": p["max_daily_change"],
        "preset_name": name,
    }
