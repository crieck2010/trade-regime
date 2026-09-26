"""Tests for the CLI: conviction/components/presets/demo."""

import json

import pytest

from trade_regime.cli import build_parser, main


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def _inputs(tmp_path):
    macro = _write(tmp_path / "macro.json",
                   {"regime": "EXPANSION", "z_score": 1.0, "snapshot_id": "m1",
                    "schema_version": 1})
    breadth = _write(tmp_path / "breadth.json",
                     {"regime": "BROADENING", "fragility": 0.1,
                      "snapshot_id": "b1", "schema_version": 1})
    vol = _write(tmp_path / "vol.json",
                 {"current_vol": 0.12, "vol_min": 0.10, "vol_max": 0.45,
                  "snapshot_id": "v1", "schema_version": 1})
    return macro, breadth, vol


def test_conviction_table(tmp_path, capsys):
    macro, breadth, vol = _inputs(tmp_path)
    rc = main(["conviction", "--macro", macro, "--breadth", breadth,
               "--vol", vol])
    assert rc == 0
    out = capsys.readouterr().out
    assert "conviction" in out and "hysteresis" in out and "components:" in out


def test_conviction_json(tmp_path, capsys):
    macro, breadth, vol = _inputs(tmp_path)
    rc = main(["conviction", "--macro", macro, "--breadth", breadth,
               "--vol", vol, "--format", "json"])
    assert rc == 0
    snap = json.loads(capsys.readouterr().out)
    assert snap["schema_version"] == 1
    assert snap["provenance"]["input_snapshot_ids"] == {
        "macro": "m1", "breadth": "b1", "vol": "v1"}
    assert snap["provenance"]["input_schema_versions"] == {
        "macro": 1, "breadth": 1, "vol": 1}


def test_conviction_missing_files_means_missing_components(tmp_path, capsys):
    rc = main(["conviction", "--format", "json"])
    assert rc == 0
    snap = json.loads(capsys.readouterr().out)
    assert sorted(snap["missing"]) == ["breadth", "macro", "vol"]
    assert snap["conviction"] == pytest.approx(50.0)


def test_state_file_carries_hysteresis(tmp_path, capsys):
    macro, breadth, vol = _inputs(tmp_path)
    state = str(tmp_path / "state.json")
    main(["conviction", "--macro", macro, "--breadth", breadth, "--vol", vol,
          "--state", state, "--format", "json"])
    first = json.loads(capsys.readouterr().out)
    mem = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert mem["conviction"] == pytest.approx(first["conviction"])
    # second run restores memory: still "updated"/initialization-free
    main(["conviction", "--macro", macro, "--breadth", breadth, "--vol", vol,
          "--state", state, "--format", "json"])
    second = json.loads(capsys.readouterr().out)
    assert second["hysteresis"]["prior_conviction"] == pytest.approx(first["conviction"])


def test_components_command(tmp_path, capsys):
    macro, breadth, vol = _inputs(tmp_path)
    rc = main(["components", "--macro", macro, "--breadth", breadth, "--vol", vol])
    assert rc == 0
    out = capsys.readouterr().out
    assert "macro" in out and "breadth" in out and "vol" in out
    assert "raw composite" in out


def test_components_demo_day(capsys):
    rc = main(["components", "--demo", "--day", "50"])
    assert rc == 0
    assert "demo day 50" in capsys.readouterr().out


def test_presets_lists_three(capsys):
    rc = main(["presets"])
    assert rc == 0
    out = capsys.readouterr().out
    for name in ("balanced", "conservative", "aggressive"):
        assert f"[{name}]" in out
    assert "rationale" in out


def test_demo_runs(capsys):
    rc = main(["demo", "--stride", "20"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "vol-spike" in out and "recovery" in out


def test_parser_has_expected_commands():
    p = build_parser()
    actions = p._subparsers._group_actions[0]
    assert set(actions.choices) >= {"demo", "conviction", "components",
                                   "presets", "license", "update-check"}
