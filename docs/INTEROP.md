# INTEROP — trade-regime contracts

How `trade-regime` connects to the rest of the suite.  Everything
crossing a boundary is plain data (JSON-serializable dicts); no
sibling imports, ever.

## What trade-regime owns

1. **The fused snapshot** (`schema_version: 1`): `conviction` (0–100,
   hysteresis-smoothed), `composite_raw`, per-component
   sub-convictions + weights used, hysteresis state/reason,
   advisory `exposure_scale`, `missing`, provenance.  Enforced
   JSON-serializable by `json.dumps` inside `assess()`.
2. **The component readers** (`signals.py`): macro / breadth / vol,
   each mapping a plain snapshot dict to a 0–100 sub-conviction
   (never raising — `ComponentUnavailable` on bad input).
3. **The session component** (`session.py`, new in v0.2.1): graded
   session-liquidity sub-conviction wired through the `extra`
   extension slot.  Snapshot shape:

   ```python
   {"now": <aware datetime | ISO-8601 str | None>,
    "asset_class": "equities" | "futures" | "crypto",
    "calendar": {"holidays": ["YYYY-MM-DD", ...]} | None}
   ```

   Fusion weights with session: `session_weights()` →
   macro 0.34 / breadth 0.2975 / vol 0.2125 / session 0.15
   (pro-rata rebalance of `DEFAULT_WEIGHTS`; max session drag
   14.25 pts — below the 20-pt confirm band, so the session
   component tempers but never teleports conviction).
   Full model: `docs/SESSION.md`.

## Who consumes what

| Consumer | Reads | Contract |
|---|---|---|
| trade-agents (desk) | fused snapshot via `market_context_provider` | `normalize_regime_context()` → `conviction_size_scale()` → `PM.size_orders(size_scale=...)`. **No changes needed for the session component**: the drag flows through `conviction → exposure_scale` automatically. |
| trade-risk | `risk_regime_input` (advisory) | `exposure_scale` is advisory only; trade-risk owns final sizing/vetoes and takes no regime input in its sizers (no double-scaling). |
| trade-hedge | `hedge_tilt_input` | defensive/aggressive tilt in [−1, +1]; direction and magnitude only. |

## Extension contract (for future components)

`read_all(..., extra={"name": (snapshot, reader)})` where `reader`
takes a snapshot dict and returns `Component | ComponentUnavailable`.
Misbehaving readers are contained (become `ComponentUnavailable`,
never exceptions).  `fuse()` drops unavailable components and
renormalizes the remaining weights — documented in `missing`, never
silent.  Give the component a weight via `RegimeArbiter(weights=...)`
(`validate_weights` allows extra names); `session_weights()` is the
worked example of pro-rata rebalancing.

## Versioning

- Snapshot `schema_version` is 1; additive fields are fine, removals
  or renames bump the version.
- `trade_regime.__version__` tracks releases (semver).
