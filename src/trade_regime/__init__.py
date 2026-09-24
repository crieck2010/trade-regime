"""trade-regime: the regime arbiter for the trade-suite.

The suite already has regime *engines* — trade-macro, trade-breadth,
trade-volforecast.  This package is the *arbiter*: it fuses their
continuous scores into one graded conviction number (0-100%) with
hysteresis, and maps conviction to exposure.

Per explicit design direction: graded conviction *sizing*, not more
labeled buckets.  Buckets cut from noisy signals are false precision.
Stance labels exist for display only — no decision is ever taken on a
label; decisions use the score and the conviction number.

Pure-Python, stdlib-only engine. Plain data in/out (dicts of JSON-safe
values). Research/backtesting/paper-trading only — never live trading.
"""

from __future__ import annotations

from .adapters import hedge_trigger, pm_context, risk_caps
from .arbiter import (
    DEFAULT_BAND,
    DEFAULT_THRESHOLD,
    DEFAULT_WEIGHTS,
    STANCE_LABELS,
    RegimeArbiter,
    conviction_of,
    fuse,
    next_stance,
)
from .demo import run_demo
from .history import RegimeHistory
from .presets import PRESETS
from .signals import (
    Signal,
    SignalUnavailable,
    breadth_score,
    macro_score,
    vol_score,
)
from .sizing import (
    STAND_DOWN_FLOOR,
    exposure_scale,
    sleeve_scale,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "DEFAULT_BAND",
    "DEFAULT_THRESHOLD",
    "DEFAULT_WEIGHTS",
    "STAND_DOWN_FLOOR",
    "STANCE_LABELS",
    "PRESETS",
    "RegimeArbiter",
    "RegimeHistory",
    "Signal",
    "SignalUnavailable",
    "breadth_score",
    "conviction_of",
    "exposure_scale",
    "fuse",
    "hedge_trigger",
    "macro_score",
    "next_stance",
    "pm_context",
    "risk_caps",
    "run_demo",
    "sleeve_scale",
    "vol_score",
]
