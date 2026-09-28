"""Tests for the session/time-of-day component."""

import json
from datetime import datetime, timezone

import pytest

from trade_regime import RegimeArbiter, fuse, read_all
from trade_regime.session import (
    SESSION_WEIGHT,
    Component,
    ComponentUnavailable,
    read_session,
    session_component,
    session_extra,
    session_weights,
)

# September 2026: US Eastern is EDT (UTC-4).  A Monday (28th), the
# preceding Saturday (26th); July 2026: Friday 3rd (Independence Day
# observed -- NYSE holiday), Friday 10th (normal session).
MON_0300_ET = datetime(2026, 9, 28, 7, 0, tzinfo=timezone.utc)
MON_0930_ET = datetime(2026, 9, 28, 13, 30, tzinfo=timezone.utc)
MON_1000_ET = datetime(2026, 9, 28, 14, 0, tzinfo=timezone.utc)
SAT_1200_ET = datetime(2026, 9, 26, 16, 0, tzinfo=timezone.utc)
FRI_HOLIDAY_1000_ET = datetime(2026, 7, 3, 14, 0, tzinfo=timezone.utc)
FRI_NORMAL_1000_ET = datetime(2026, 7, 10, 14, 0, tzinfo=timezone.utc)


def eq_session(dt, **kw):
    return read_session(now=dt, asset_class="equities", **kw)


# ---------------------------------------------------------------- anchors

def test_regular_session_neutral():
    assert eq_session(MON_0930_ET).sub_conviction == 100.0
    assert eq_session(MON_1000_ET).sub_conviction == 100.0


def test_boundary_ramp_no_cliff():
    """9:29 -> 9:30 -> 9:45 must be continuous: no step at the open."""
    v_0929 = eq_session(datetime(2026, 9, 28, 13, 29, tzinfo=timezone.utc)).sub_conviction
    v_0930 = eq_session(MON_0930_ET).sub_conviction
    v_0945 = eq_session(datetime(2026, 9, 28, 13, 45, tzinfo=timezone.utc)).sub_conviction
    assert v_0930 == 100.0
    assert v_0945 == 100.0
    assert abs(v_0929 - v_0930) < 1.0  # smooth ramp, not a cliff
    assert v_0929 < 100.0  # ramp genuinely in progress just before the open


def test_close_ramp_no_cliff():
    v_1559 = eq_session(datetime(2026, 9, 28, 19, 59, tzinfo=timezone.utc)).sub_conviction
    v_1600 = eq_session(datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)).sub_conviction
    assert v_1559 == 100.0
    assert v_1600 == 100.0


def test_premarket_grades_down():
    # 04:00 ET -> 30; halfway to the open (06:45) -> 65.
    v_0400 = eq_session(datetime(2026, 9, 28, 8, 0, tzinfo=timezone.utc)).sub_conviction
    v_0645 = eq_session(datetime(2026, 9, 28, 10, 45, tzinfo=timezone.utc)).sub_conviction
    assert v_0400 == 30.0
    assert v_0645 == pytest.approx(65.0)


def test_overnight_deep_drag():
    assert eq_session(MON_0300_ET).sub_conviction == 10.0
    midnight = eq_session(datetime(2026, 9, 28, 4, 0, tzinfo=timezone.utc)).sub_conviction
    assert midnight == 10.0


def test_weekend_stand_down():
    c = eq_session(SAT_1200_ET)
    assert c.sub_conviction == 5.0
    assert c.detail["weekend"] is True


def test_holiday_treated_like_weekend():
    c = eq_session(FRI_HOLIDAY_1000_ET)
    assert c.sub_conviction == 5.0
    assert c.detail["holiday"] is True
    # ...while a normal Friday at the same time is a full session.
    assert eq_session(FRI_NORMAL_1000_ET).sub_conviction == 100.0


def test_custom_calendar_injection():
    cal = {"holidays": ["2026-07-10"]}
    c = eq_session(FRI_NORMAL_1000_ET, calendar=cal)
    assert c.sub_conviction == 5.0
    assert c.detail["holiday"] is True


# ---------------------------------------------------------------- asset classes

def test_crypto_always_neutral():
    # 3am on a Saturday: no session concept -> 100.
    c = read_session(now=SAT_1200_ET, asset_class="crypto")
    assert c.sub_conviction == 100.0
    c2 = read_session(now=MON_0300_ET, asset_class="crypto")
    assert c2.sub_conviction == 100.0


def test_futures_cash_overlap_full():
    c = read_session(now=MON_1000_ET, asset_class="futures")
    assert c.sub_conviction == 100.0


def test_futures_daily_halt_drags():
    # 17:30 ET: halfway through the 17:00-18:00 halt ramp -> 47.5.
    c = read_session(
        now=datetime(2026, 9, 28, 21, 30, tzinfo=timezone.utc),
        asset_class="futures")
    assert c.sub_conviction == pytest.approx(47.5)


def test_futures_weekend_closed():
    c = read_session(now=SAT_1200_ET, asset_class="futures")
    assert c.sub_conviction == 5.0


def test_unknown_asset_class_unavailable():
    c = read_session(now=MON_1000_ET, asset_class="forex")
    assert isinstance(c, ComponentUnavailable)


# ---------------------------------------------------------------- input handling

def test_naive_datetime_assumed_utc_loudly():
    naive = datetime(2026, 9, 28, 14, 0)  # 14:00 naive -> assumed UTC = 10:00 ET
    c = eq_session(naive)
    assert isinstance(c, Component)
    assert c.sub_conviction == 100.0
    assert c.detail["tz_assumption"] == "naive datetime assumed UTC"


def test_iso_string_with_z():
    c = eq_session("2026-09-28T14:00:00Z")
    assert isinstance(c, Component)
    assert c.sub_conviction == 100.0


def test_none_now_means_right_now():
    c = read_session(now=None)
    assert isinstance(c, Component)
    assert 0.0 <= c.sub_conviction <= 100.0


def test_garbage_inputs_unavailable_not_raised():
    assert isinstance(session_component(None), ComponentUnavailable)
    assert isinstance(session_component({"now": object()}), ComponentUnavailable)
    assert isinstance(session_component({"now": "not-a-date"}), ComponentUnavailable)
    assert isinstance(session_component({"now": MON_1000_ET, "calendar": "nope"}),
                      ComponentUnavailable)


def test_detail_is_json_safe():
    c = eq_session(MON_1000_ET)
    json.dumps(c.detail)


# ---------------------------------------------------------------- weights & fusion

def test_session_weights_rebalance_proportionally():
    w = session_weights()
    assert w == {"macro": 0.34, "breadth": 0.2975, "vol": 0.2125,
                 "session": 0.15}
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert SESSION_WEIGHT == 0.15


def test_fusion_with_session_exact_maths():
    macro = {"regime": "EXPANSION", "z_score": 2.0}          # 75 + 10 = 85
    breadth = {"regime": "BROADENING", "fragility": 0.0}      # 75
    vol = {"current_vol": 0.12, "vol_min": 0.10, "vol_max": 0.45}  # 94.29
    comps = read_all(macro, breadth, vol,
                     extra=session_extra(now=MON_0300_ET))     # session = 10
    composite, contributions, missing = fuse(comps, session_weights())
    # 0.34*85 + 0.2975*75 + 0.2125*94.29 + 0.15*10
    assert composite == pytest.approx(72.75, abs=0.01)
    assert contributions["session"]["weight"] == 0.15
    assert contributions["session"]["sub_conviction"] == 10.0
    assert missing == []


def test_graceful_degradation_session_missing():
    comps = read_all(
        {"regime": "EXPANSION"}, {"regime": "BROADENING"},
        {"current_vol": 0.12, "vol_min": 0.10, "vol_max": 0.45},
        extra={"session": ({"now": MON_1000_ET, "asset_class": "forex"},
                           session_component)})
    composite, contributions, missing = fuse(comps, session_weights())
    assert missing == ["session"]
    # Renormalized over the three market-risk components only.
    assert abs(sum(c["weight"] for c in contributions.values()) - 1.0) < 1e-9
    assert "session" not in contributions


def test_session_drag_bounded_below_confirm_band():
    """Max session drag (weekend, 5.0) is 0.15*95 = 14.25 pts --
    below the 20-pt confirm band: the session component alone can
    never trigger an immediate conviction move."""
    assert SESSION_WEIGHT * (100.0 - 5.0) < 20.0


# ---------------------------------------------------------------- hysteresis

def _hyst_comps(session_val: float) -> dict:
    """All market-risk components pinned at 100; session varies."""
    return {
        "macro": Component("macro", 100.0, {}),
        "breadth": Component("breadth", 100.0, {}),
        "vol": Component("vol", 100.0, {}),
        "session": Component("session", session_val, {}),
    }


def test_hysteresis_holds_single_3am_read():
    """One 3am read drags the raw composite but hysteresis holds."""
    arb = RegimeArbiter(weights=session_weights())
    snap = arb.assess(_hyst_comps(100.0))
    assert snap["conviction"] == 100.0
    night = arb.assess(_hyst_comps(10.0))
    # raw = 0.85*100 + 0.15*10 = 86.5; delta -13.5: beyond deadband,
    # inside confirm band -> held awaiting persistence.
    assert night["composite_raw"] == pytest.approx(86.5)
    assert night["conviction"] == 100.0
    assert night["hysteresis"]["state"] == "held"


def test_hysteresis_releases_persistent_3am_drag():
    """Three consecutive 3am reads release the session drag."""
    arb = RegimeArbiter(weights=session_weights())
    arb.assess(_hyst_comps(100.0))
    snaps = arb.assess_series([_hyst_comps(10.0) for _ in range(3)])
    assert snaps[0]["hysteresis"]["state"] == "held"
    assert snaps[1]["hysteresis"]["state"] == "held"
    assert snaps[2]["hysteresis"]["state"] == "updated"
    assert snaps[2]["conviction"] == pytest.approx(86.5)
    assert snaps[2]["exposure_scale"] == pytest.approx(0.865)
