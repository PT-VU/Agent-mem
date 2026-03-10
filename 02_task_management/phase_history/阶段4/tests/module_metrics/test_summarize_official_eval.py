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
        / "summarize_official_eval.py"
    )
    spec = importlib.util.spec_from_file_location("summarize_official_eval", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[arg-type]
    return mod


def test_summarize_official_eval_roundtrip():
    _load_module()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        report = {
            "total_instances": 10,
            "submitted_instances": 9,
            "completed_instances": 9,
            "resolved_instances": 4,
            "unresolved_instances": 5,
            "error_instances": 0,
            "incomplete_ids": ["x1"],
        }
        report_path = root / "report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        out = root / "summary.json"

        import subprocess

        repo = Path(__file__).resolve()
        while repo.name != "SWE-bench" and repo.parent != repo:
            repo = repo.parent
        cmd = [
            sys.executable,
            str(repo / "PDDL_work_mem" / "06_artificial_intelligence" / "experiments" / "common" / "summarize_official_eval.py"),
            "--report-json",
            str(report_path),
            "--run-id",
            "r1",
            "--dataset",
            "SWE-bench/SWE-bench test",
            "--scope",
            "scope1",
            "--summary-out",
            str(out),
        ]
        subprocess.check_call(cmd)
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["resolved_instances"] == 4
        assert payload["planned_instances"] == 10
        assert payload["solved_rate_on_planned"] == 0.4
