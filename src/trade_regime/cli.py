"""Command-line interface for trade-regime.

Commands:
  demo        run the seeded multi-regime arc (bull -> narrowing ->
              vol spike -> recovery) and show hysteresis holding
              through noise
  conviction  assess one set of engine snapshots (JSON files) and print
              the snapshot; --state keeps hysteresis memory across runs
  components  show the per-component sub-convictions for one input set
  presets     list the named risk postures with their rationale
  license / update-check   suite-wide hooks
"""

from __future__ import annotations

import argparse
import json
import os

from . import __version__
from .arbiter import RegimeArbiter, fuse
from .demo import run_demo
from .history import ConvictionHistory
from .licensing import check_license, check_update
from .presets import PRESETS, arbiter_kwargs, get_preset
from .signals import read_all


def _load_json(path: str | None):
    if not path:
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _provenance_from_files(paths: dict) -> dict:
    ids, vers = {}, {}
    for name, path in paths.items():
        if not path:
            continue
        snap = _load_json(path) or {}
        if isinstance(snap, dict):
            if snap.get("snapshot_id"):
                ids[name] = snap["snapshot_id"]
            if snap.get("schema_version"):
                vers[name] = snap["schema_version"]
    return {"input_snapshot_ids": ids, "input_schema_versions": vers}


def _fmt_snapshot(snap: dict) -> str:
    h = snap["hysteresis"]
    lines = [
        f"conviction      {snap['conviction']:6.1f}  (raw composite {snap['composite_raw']:6.1f})",
        f"hysteresis      {h['state']:7s}  {h['reason']}",
        f"exposure_scale  {snap['exposure_scale']:.2f}  (advisory -- trade-risk owns sizing)",
        "components:",
    ]
    for name, c in snap["components"].items():
        lines.append(
            f"  {name:8s} sub={c['sub_conviction']:6.1f} "
            f"w={c['weight']:.2f} contrib={c['contribution']:6.1f}")
    if snap["missing"]:
        lines.append(f"missing: {', '.join(snap['missing'])}")
    return "\n".join(lines)


def _add_input_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--macro", help="trade-macro snapshot JSON file")
    p.add_argument("--breadth", help="trade-breadth snapshot JSON file")
    p.add_argument("--vol", help="trade-volforecast summary JSON file")
    p.add_argument("--preset", choices=sorted(PRESETS), default="balanced")


def _arbiter_from_args(args) -> RegimeArbiter:
    arbiter = RegimeArbiter(**arbiter_kwargs(args.preset))
    state_path = getattr(args, "state", None)
    if state_path and os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as fh:
            arbiter.restore(json.load(fh))
    return arbiter


def _save_state(arbiter: RegimeArbiter, state_path: str | None) -> None:
    if state_path:
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(arbiter.memory_dict(), fh, indent=2)


def cmd_conviction(args: argparse.Namespace) -> int:
    paths = {"macro": args.macro, "breadth": args.breadth, "vol": args.vol}
    components = read_all(_load_json(args.macro), _load_json(args.breadth),
                          _load_json(args.vol))
    arbiter = _arbiter_from_args(args)
    snap = arbiter.assess(components, provenance=_provenance_from_files(paths))
    _save_state(arbiter, getattr(args, "state", None))
    if getattr(args, "history", None):
        ConvictionHistory(args.history).record(snap)
    if args.format == "json":
        print(json.dumps(snap, indent=2))
    else:
        print(_fmt_snapshot(snap))
    return 0


def cmd_components(args: argparse.Namespace) -> int:
    if args.demo:
        from .demo import demo_arc
        day = demo_arc(seed=args.seed)[args.day]
        macro, breadth, vol = day["macro"], day["breadth"], day["vol"]
        print(f"# demo day {args.day} ({day['phase']}, seed {args.seed})")
    else:
        macro, breadth, vol = (_load_json(args.macro), _load_json(args.breadth),
                              _load_json(args.vol))
    components = read_all(macro, breadth, vol)
    arbiter = RegimeArbiter(**arbiter_kwargs(args.preset))
    composite, contributions, missing = fuse(components, arbiter.weights)
    for name, comp in components.items():
        if hasattr(comp, "sub_conviction"):
            c = contributions[name]
            print(f"{name:8s} sub-conviction {comp.sub_conviction:6.1f}  "
                  f"weight {c['weight']:.2f}  contribution {c['contribution']:6.1f}")
            for k, v in comp.detail.items():
                print(f"           {k}={v}")
        else:
            print(f"{name:8s} UNAVAILABLE: {comp.reason}")
    print(f"raw composite: {composite:.1f}")
    if missing:
        print(f"missing: {', '.join(missing)}")
    return 0


def cmd_presets(args: argparse.Namespace) -> int:
    for name in sorted(PRESETS):
        p = get_preset(name)
        print(f"[{name}] {p['description']}")
        print(f"  rationale: {p['rationale']}")
        print(f"  weights: {p['weights']}")
        print(f"  deadband={p['deadband']} confirm_band={p['confirm_band']} "
              f"persistence={p['persistence_n']} max_daily_change={p['max_daily_change']}")
        print()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    arc, snapshots, _ = run_demo(seed=args.seed, preset=args.preset)
    print(f"# trade-regime demo: 120-day seeded arc "
          f"(seed {args.seed}, preset {args.preset})")
    print("# bull -> narrowing/fragile -> vol spike -> recovery")
    print(f"{'day':>4} {'phase':>10} {'raw':>6} {'conv':>6} {'h/u':>3}  reason")
    held = updated = 0
    for i, (inp, snap) in enumerate(zip(arc, snapshots)):
        if i % args.stride:
            continue
        h = snap["hysteresis"]
        mark = "H" if h["state"] == "held" else "U"
        if h["state"] == "held":
            held += 1
        else:
            updated += 1
        print(f"{inp['day']:>4} {inp['phase']:>10} "
              f"{snap['composite_raw']:>6.1f} {snap['conviction']:>6.1f} "
              f"{mark:>3}  {h['reason']}")
    n = len(range(0, len(arc), args.stride))
    print(f"# shown {n} of {len(arc)} days: {held} held, {updated} updated -- "
          "hysteresis absorbs the noise, releases on real breaks")
    return 0


def cmd_license(args: argparse.Namespace) -> int:
    print(json.dumps(check_license(args.key), indent=2))
    return 0


def cmd_update_check(args: argparse.Namespace) -> int:
    print(json.dumps(check_update(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trade-regime",
                                description="Regime arbiter: graded conviction with hysteresis")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("conviction", help="assess one set of engine snapshots")
    _add_input_args(c)
    c.add_argument("--state", help="JSON file carrying hysteresis memory across runs")
    c.add_argument("--history", help="JSONL file to append the snapshot to")
    c.add_argument("--format", choices=("table", "json"), default="table")
    c.set_defaults(func=cmd_conviction)

    k = sub.add_parser("components", help="show per-component sub-convictions")
    _add_input_args(k)
    k.add_argument("--demo", action="store_true", help="use the seeded demo arc")
    k.add_argument("--day", type=int, default=50, help="demo day to inspect")
    k.add_argument("--seed", type=int, default=7)
    k.set_defaults(func=cmd_components)

    d = sub.add_parser("demo", help="run the seeded multi-regime arc")
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--preset", choices=sorted(PRESETS), default="balanced")
    d.add_argument("--stride", type=int, default=5)
    d.set_defaults(func=cmd_demo)

    pr = sub.add_parser("presets", help="list arbiter presets with rationale")
    pr.set_defaults(func=cmd_presets)

    li = sub.add_parser("license", help="check license key")
    li.add_argument("--key")
    li.set_defaults(func=cmd_license)

    up = sub.add_parser("update-check", help="check for a newer release")
    up.set_defaults(func=cmd_update_check)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
