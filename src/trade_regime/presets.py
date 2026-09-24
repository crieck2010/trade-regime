"""Lazy, fail-soft presets for the arbiter and sizing layer.

A preset is a named bundle of (weights, threshold, band,
stand_down_floor) so the CLI, dashboards, and research code share the
same three risk postures instead of hand-rolling numbers.
"""

from __future__ import annotations

from .arbiter import DEFAULT_BAND, DEFAULT_THRESHOLD, DEFAULT_WEIGHTS
from .sizing import STAND_DOWN_FLOOR

PRESETS = {
    "balanced": {
        "description": "Default posture: engage at ±0.40, release at ±0.10.",
        "weights": dict(DEFAULT_WEIGHTS),
        "threshold": DEFAULT_THRESHOLD,
        "band": DEFAULT_BAND,
        "stand_down_floor": STAND_DOWN_FLOOR,
    },
    "conservative": {
        "description": ("Slow to engage, quick to stand down. For live "
                        "capital and field-day autonomy."),
        "weights": {"macro": 0.45, "breadth": 0.35, "vol": 0.20},
        "threshold": 0.30,
        "band": 0.15,  # engage ±0.45, release ±0.15
        "stand_down_floor": 35.0,
    },
    "aggressive": {
        "description": ("Fast to engage, slower to stand down. Research "
                        "and high-conviction books only."),
        "weights": {"macro": 0.35, "breadth": 0.35, "vol": 0.30},
        "threshold": 0.20,
        "band": 0.10,  # engage ±0.30, release ±0.10
        "stand_down_floor": 15.0,
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
    return {"weights": p["weights"], "threshold": p["threshold"], "band": p["band"]}
