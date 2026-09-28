"""Session/time-of-day component: a graded liquidity sub-conviction.

Why this exists: the arbiter fuses market-risk reads (macro, breadth,
vol) but had no notion of *when* a read was taken.  A 3am equity
assessment could still size at x0.75 because nothing in the composite
knew the session was dead.  This module adds a fourth component
through the documented ``extra`` extension slot -- no core arbiter
changes, no new buckets.

Convention (shared with signals.py): 0 = fully risk-off, 100 = fully
risk-on, 50 = neutral.  For the session component, 100 means "session
liquidity is normal -- defer to the market-risk components"; low
values mean "the session itself is the risk" (illiquid hours,
weekends, holidays).

Design rules (same as the arbiter):
- **Graded and continuous.**  Piecewise-linear anchor tables give a
  value for every minute; there are no step discontinuities at session
  boundaries (the 9:29 -> 9:30 -> 9:45 walk is smooth by construction).
- **A tempering input, not a veto.**  Default weight 0.15: the maximum
  session drag is 0.15 x 95 = 14.25 conviction points (weekend), which
  is *below* the 20-pt confirm band -- the session component alone can
  never teleport conviction.  It must persist (3 observations) or
  combine with market-risk moves.  A hard session veto belongs
  downstream (desk scheduling / trade-risk limits), not in the arbiter.
- **Never raises.**  Bad snapshots become ``ComponentUnavailable``;
  ``fuse()`` renormalizes over whatever is available (graceful
  degradation is inherited, not reimplemented).

Stdlib only (``datetime``, ``zoneinfo``).  Plain data in/out.
"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py3.9 fallback, never hit on 3.10+
    ZoneInfo = None  # type: ignore[assignment]

from .arbiter import DEFAULT_WEIGHTS
from .signals import Component, ComponentUnavailable

#: US equity session clock.  All session boundaries are stated in this
#: timezone; inputs in other zones are converted.
SESSION_TZ = "America/New_York"

#: Default fusion weight for the session component.  Rationale: large
#: enough to matter (a dead session visibly tempers the composite),
#: small enough that it can never flip conviction alone -- see the
#: module docstring maths (max drag 14.25 pts < 20-pt confirm band).
SESSION_WEIGHT = 0.15

#: Supported asset classes.  Unknown values -> ComponentUnavailable.
ASSET_CLASSES = ("equities", "futures", "crypto")

# --------------------------------------------------------------------------
# Holiday table
# --------------------------------------------------------------------------
#
# NYSE holidays, verified against weekday calendars.  Kept minimal and
# explicit: 2026-2027 only.  Years outside the table are an *explicit
# limitation* -- weekends still score ~5, but a holiday in an uncovered
# year scores as a normal weekday.  Pass ``calendar={"holidays": [...]}``
# to inject a full calendar (the seam for a proper exchange-calendar
# dependency later).  Early closes (day after Thanksgiving, Christmas
# Eve, ...) are NOT modeled -- treated as full sessions; documented as
# a limitation, not silently "handled".

_NYSE_HOLIDAYS_2026_2027 = frozenset({
    # 2026
    "2026-01-01",  # New Year's Day (Thu)
    "2026-01-19",  # Martin Luther King Jr. Day (Mon)
    "2026-02-16",  # Presidents' Day (Mon)
    "2026-04-03",  # Good Friday (Fri)
    "2026-05-25",  # Memorial Day (Mon)
    "2026-06-19",  # Juneteenth (Fri)
    "2026-07-03",  # Independence Day observed (Fri; Jul 4 = Sat)
    "2026-09-07",  # Labor Day (Mon)
    "2026-11-26",  # Thanksgiving (Thu)
    "2026-12-25",  # Christmas Day (Fri)
    # 2027
    "2027-01-01",  # New Year's Day (Fri)
    "2027-01-18",  # Martin Luther King Jr. Day (Mon)
    "2027-02-15",  # Presidents' Day (Mon)
    "2027-03-26",  # Good Friday (Fri)
    "2027-05-31",  # Memorial Day (Mon)
    "2027-06-18",  # Juneteenth observed (Fri; Jun 19 = Sat)
    "2027-07-05",  # Independence Day observed (Mon; Jul 4 = Sun)
    "2027-09-06",  # Labor Day (Mon)
    "2027-11-25",  # Thanksgiving (Thu)
    "2027-12-24",  # Christmas Day observed (Fri; Dec 25 = Sat)
})

#: Value used when the venue is closed (weekend / holiday, equities).
VENUE_CLOSED_VALUE = 5.0

# --------------------------------------------------------------------------
# Anchor tables: (minutes since midnight ET, sub-conviction)
# --------------------------------------------------------------------------
#
# Piecewise-linear interpolation between anchors.  Continuity is
# structural: adjacent anchors share endpoints, so there are kinks
# (slope changes) but never cliffs.  The overnight ramps are explicit
# one-hour segments (20:00->21:00 down, 03:00->04:00 up) rather than
# instantaneous drops.

#: US equities.  Regular session 09:30-16:00 ET scores 100 (neutral --
#: defers to market-risk components).  Pre-market (04:00-09:30) grades
#: 30 -> 100; after-hours (16:00-20:00) grades 100 -> 30; the deep
#: overnight (21:00-03:00) sits at 10.
_EQUITIES_ANCHORS = (
    (0, 10.0),
    (180, 10.0),    # 03:00 -- deep overnight
    (240, 30.0),    # 04:00 -- pre-market open
    (570, 100.0),   # 09:30 -- regular open
    (960, 100.0),   # 16:00 -- regular close
    (1200, 30.0),   # 20:00 -- after-hours close
    (1260, 10.0),   # 21:00 -- ramped down to deep overnight
    (1440, 10.0),   # 24:00
)

#: CME-style equity-index futures (defensible simplification, not a
#: venue spec): near-24/5.  US cash overlap 09:30-16:00 scores 100;
#: overnight electronic session scores 70 (trades, but thinner and
#: news-driven); the 17:00-18:00 ET daily trading halt ramps down to
#: 25; weekends score ~5 (closed).
_FUTURES_ANCHORS = (
    (0, 70.0),
    (570, 100.0),   # 09:30 -- cash overlap
    (960, 100.0),   # 16:00 -- cash close
    (1020, 25.0),   # 17:00 -- daily halt begins
    (1080, 70.0),   # 18:00 -- halt ends, overnight resumes
    (1440, 70.0),
)

#: Crypto has no session concept: 24/7 -> neutral 100 always.
_CRYPTO_VALUE = 100.0

_ANCHORS = {
    "equities": _EQUITIES_ANCHORS,
    "futures": _FUTURES_ANCHORS,
}


def _interp(anchors: tuple, minutes: float) -> float:
    """Piecewise-linear interpolation over (minute, value) anchors."""
    minutes = max(0.0, min(1440.0, minutes))
    for (m0, v0), (m1, v1) in zip(anchors, anchors[1:]):
        if m0 <= minutes <= m1:
            if m1 == m0:
                return v0
            frac = (minutes - m0) / (m1 - m0)
            return v0 + frac * (v1 - v0)
    return anchors[-1][1]  # pragma: no cover - clamped above


def _parse_now(now) -> datetime:
    """Parse ``now`` to an aware datetime; raise ValueError if hopeless."""
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        return now
    if isinstance(now, str):
        text = now.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            raise ValueError(f"unparseable now timestamp: {now!r}")
    raise ValueError(f"now must be a datetime, ISO string, or None; got {type(now)}")


def _resolve_calendar(calendar) -> frozenset:
    """Resolve the holiday set: injected calendar wins, else the table."""
    if calendar is None:
        return _NYSE_HOLIDAYS_2026_2027
    if isinstance(calendar, dict):
        holidays = calendar.get("holidays")
        if holidays is None:
            return _NYSE_HOLIDAYS_2026_2027
        try:
            return frozenset(str(d) for d in holidays)
        except TypeError:
            raise ValueError("calendar['holidays'] must be an iterable of YYYY-MM-DD strings")
    raise ValueError("calendar must be a dict with optional 'holidays' or None")


def _et_parts(dt_utc: datetime) -> tuple:
    """Convert to America/New_York; return (date_str, weekday, minutes)."""
    if ZoneInfo is None:  # pragma: no cover
        raise ValueError("zoneinfo unavailable; cannot resolve session time")
    et = dt_utc.astimezone(ZoneInfo(SESSION_TZ))
    minutes = et.hour * 60 + et.minute + et.second / 60.0
    return et.date().isoformat(), et.weekday(), minutes, et


def session_component(snapshot: dict | None) -> Component | ComponentUnavailable:
    """Normalize a session snapshot to a 0-100 sub-conviction.

    Snapshot shape (plain data)::

        {"now": <aware datetime | ISO-8601 str | None>,
         "asset_class": "equities" | "futures" | "crypto",
         "calendar": {"holidays": ["2026-07-03", ...]} | None}

    - ``now=None`` means "right now" (UTC clock).
    - Naive datetimes are assumed UTC -- recorded loudly in ``detail``
      (``tz_assumption``), never silently.
    - ``calendar=None`` uses the built-in 2026-2027 NYSE table;
      inject ``{"holidays": [...]}`` to override (the seam for a full
      exchange calendar).

    Never raises on bad input -- returns ``ComponentUnavailable``.
    Register via the ``extra`` slot::

        read_all(macro, breadth, vol,
                 extra={"session": (snap, session_component)})
    """
    if not isinstance(snapshot, dict):
        return ComponentUnavailable("session", "no snapshot supplied")
    asset_class = snapshot.get("asset_class", "equities")
    if asset_class not in ASSET_CLASSES:
        return ComponentUnavailable(
            "session", f"unknown asset_class {asset_class!r}; want {ASSET_CLASSES}")
    try:
        dt = _parse_now(snapshot.get("now"))
    except ValueError as exc:
        return ComponentUnavailable("session", str(exc))
    try:
        holidays = _resolve_calendar(snapshot.get("calendar"))
    except ValueError as exc:
        return ComponentUnavailable("session", str(exc))

    tz_assumption = None
    if dt.tzinfo is None:
        tz_assumption = "naive datetime assumed UTC"
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        date_str, weekday, minutes, et = _et_parts(dt)
    except ValueError as exc:
        return ComponentUnavailable("session", str(exc))

    weekend = weekday >= 5
    holiday = date_str in holidays

    if asset_class == "crypto":
        value, basis = _CRYPTO_VALUE, "no-session-concept"
    elif weekend or (holiday and asset_class == "equities"):
        value, basis = VENUE_CLOSED_VALUE, "venue-closed"
    else:
        value, basis = _interp(_ANCHORS[asset_class], minutes), "session-anchors"

    detail = {
        "basis": basis,
        "asset_class": asset_class,
        "et_time": et.isoformat(timespec="seconds"),
        "et_date": date_str,
        "weekday": weekday,
        "weekend": weekend,
        "holiday": holiday,
        "tz_assumption": tz_assumption,
    }
    return Component("session", round(value, 2), detail)


def read_session(now=None, asset_class: str = "equities",
                calendar: dict | None = None) -> Component | ComponentUnavailable:
    """Convenience wrapper: build the snapshot and read the component.

    ``read_session(now=datetime.now(timezone.utc))`` -> ``Component``.
    Drop the result straight into ``extra``::

        extra={"session": ({"now": now}, session_component)}
    """
    return session_component({"now": now, "asset_class": asset_class,
                              "calendar": calendar})


def session_extra(now=None, asset_class: str = "equities",
                 calendar: dict | None = None) -> dict:
    """Build the ``extra=`` mapping for ``read_all()``.

    Usage::

        from trade_regime import read_all
        from trade_regime.session import session_extra, session_weights
        from trade_regime import RegimeArbiter

        comps = read_all(macro, breadth, vol,
                         extra=session_extra(asset_class="equities"))
        arbiter = RegimeArbiter(weights=session_weights())
        snap = arbiter.assess(comps)
    """
    return {"session": ({"now": now, "asset_class": asset_class,
                         "calendar": calendar}, session_component)}


def session_weights(base: dict | None = None) -> dict:
    """Fusion weights with the session component included.

    ``w_i' = w_i * (1 - SESSION_WEIGHT)`` for the market-risk
    components, ``w_session = SESSION_WEIGHT`` (0.15).  Pro-rata
    rebalancing keeps the *relative* voice of macro/breadth/vol
    identical to ``DEFAULT_WEIGHTS`` -- the session component buys its
    weight from all three equally, it does not demote any one of them.

    Default: macro 0.34, breadth 0.2975, vol 0.2125, session 0.15.
    """
    b = dict(DEFAULT_WEIGHTS) if base is None else dict(base)
    scale = 1.0 - SESSION_WEIGHT
    out = {k: round(float(v) * scale, 4) for k, v in b.items()}
    out["session"] = SESSION_WEIGHT
    return out
