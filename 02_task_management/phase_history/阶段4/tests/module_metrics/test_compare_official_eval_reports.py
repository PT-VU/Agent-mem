from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


def _load_module():
    cur = Path(__file__).resolve()
    while cur.name != "SWE-bench" and cur.parent != cur:
        cur = cur.parent
    path = (
        cur
        / "PDDL_work_mem"
        / "06_artificial_intelligence"
        / "experiments"
        / "common"
        / "compare_official_eval_reports.py"
    )
    spec = importlib.util.spec_from_file_location("compare_official_eval_reports", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[arg-type]
    return mod


def test_build_diff_report():
    mod = _load_module()
    no_report = {
        "total_instances": 5,
        "resolved_instances": 2,
        "resolved_ids": ["a", "b"],
        "unresolved_ids": ["c", "d", "e"],
    }
    with_report = {
        "total_instances": 5,
        "resolved_instances": 3,
        "resolved_ids": ["a", "c", "d"],
        "unresolved_ids": ["b", "e"],
    }
    report = mod.build_diff_report(no_report, with_report, ["a", "b", "c", "d", "e"])
    assert report["delta_solved_rate"] == 0.2
    assert report["only_with"] == ["c", "d"]
    assert report["only_no"] == ["b"]
    assert report["both_resolved"] == ["a"]
    assert report["both_unresolved"] == ["e"]


def test_load_instance_ids_fallback_union():
    mod = _load_module()
    with tempfile.TemporaryDirectory() as td:
        no_report = {"resolved_ids": ["x"], "unresolved_ids": ["y"]}
        with_report = {"resolved_ids": ["z"], "completed_ids": ["x", "z", "w"]}
        ids = mod._load_instance_ids(Path(td) / "missing.json", no_report, with_report)
        assert ids == ["w", "x", "y", "z"]

