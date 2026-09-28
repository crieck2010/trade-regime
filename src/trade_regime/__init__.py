"""trade-regime: the regime arbiter for the trade-suite.

The suite already has regime *engines* -- trade-macro, trade-breadth,
trade-volforecast.  This package is the *arbiter*: it fuses their
continuous reads into one graded conviction number (0-100%) with
hysteresis.

Per explicit design direction: **graded conviction, not labeled
buckets**.  Buckets cut from noisy signals are false precision.  The
arbiter outputs a number; consumers threshold it if they want.

Pure-Python, stdlib-only engine.  Plain data in/out (dicts of
JSON-safe values).  Research/backtesting/paper-trading only -- never
live trading.
"""

from __future__ import annotations

from .adapters import hedge_tilt_input, market_context_provider, risk_regime_input
from .arbiter import (
    DEFAULT_CONFIRM_BAND,
    DEFAULT_DEADBAND,
    DEFAULT_MAX_DAILY_CHANGE,
    DEFAULT_PERSISTENCE_N,
    DEFAULT_WEIGHTS,
    SCHEMA_VERSION,
    RegimeArbiter,
    exposure_scale,
    fuse,
    validate_weights,
)
from .demo import demo_arc, run_demo
from .history import ConvictionHistory
from .licensing import CURRENT_VERSION
from .presets import PRESETS, arbiter_kwargs, get_preset
from .session import (
    ASSET_CLASSES,
    SESSION_TZ,
    SESSION_WEIGHT,
    VENUE_CLOSED_VALUE,
    read_session,
    session_component,
    session_extra,
    session_weights,
)
from .signals import (
    READERS,
    Component,
    ComponentUnavailable,
    breadth_component,
    macro_component,
    read_all,
    vol_component,
)

__version__ = CURRENT_VERSION

__all__ = [
    "__version__",
    "SCHEMA_VERSION",
    "DEFAULT_WEIGHTS",
    "DEFAULT_DEADBAND",
    "DEFAULT_CONFIRM_BAND",
    "DEFAULT_PERSISTENCE_N",
    "DEFAULT_MAX_DAILY_CHANGE",
    "PRESETS",
    "READERS",
    "SESSION_TZ",
    "SESSION_WEIGHT",
    "ASSET_CLASSES",
    "Component",
    "ComponentUnavailable",
    "ConvictionHistory",
    "RegimeArbiter",
    "VENUE_CLOSED_VALUE",
    "arbiter_kwargs",
    "breadth_component",
    "demo_arc",
    "exposure_scale",
    "fuse",
    "get_preset",
    "hedge_tilt_input",
    "macro_component",
    "market_context_provider",
    "read_all",
    "read_session",
    "risk_regime_input",
    "run_demo",
    "session_component",
    "session_extra",
    "session_weights",
    "validate_weights",
    "vol_component",
]
