from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


def _load_compare_module():
    cur = Path(__file__).resolve()
    while cur.name != "SWE-bench" and cur.parent != cur:
        cur = cur.parent
    path = cur / "PDDL_work_mem" / "06_artificial_intelligence" / "experiments" / "common" / "compare_trajectories.py"
    spec = importlib.util.spec_from_file_location("compare_trajectories", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[arg-type]
    return mod


def _write_traj(base: Path, instance_id: str, payload: dict) -> None:
    inst_dir = base / instance_id
    inst_dir.mkdir(parents=True, exist_ok=True)
    (inst_dir / f"{instance_id}.traj").write_text(json.dumps(payload), encoding="utf-8")


def _inject_msg() -> list[dict[str, str]]:
    return [
        {
            "role": "user",
            "content": "[AgentMem Hints]\nTreat matching hints as high-priority guidance for this attempt.\nAvoid over-exploration: reuse validated repro/fix paths first, and once a minimal plausible patch exists, validate it before broadening the search.\n1. run pytest -q first",
        }
    ]


def test_compare_report_contains_c3_fields():
    mod = _load_compare_module()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with_dir = root / "with"
        no_dir = root / "no"
        with_dir.mkdir()
        no_dir.mkdir()

        # Case A: effective intervention (with_mem success + fewer steps)
        _write_traj(
            with_dir,
            "repo__a-1",
            {
                "trajectory": [
                    {"action": "pytest -q", "observation": "ok", "query": _inject_msg()},
                    {"action": "submit", "observation": "done", "query": []},
                ],
                "info": {"exit_status": "submitted", "submission": "patch"},
            },
        )
        _write_traj(
            no_dir,
            "repo__a-1",
            {
                "trajectory": [
                    {"action": "ls", "observation": "error: not found", "query": []},
                    {"action": "cat x", "observation": "error", "query": []},
                    {"action": "submit", "observation": "done", "query": []},
                ],
                "info": {"exit_status": "failed", "submission": ""},
            },
        )

        # Case B: mem unique failure
        _write_traj(
            with_dir,
            "repo__a-2",
            {
                "trajectory": [{"action": "ls", "observation": "error", "query": _inject_msg()}],
                "info": {"exit_status": "failed", "submission": ""},
            },
        )
        _write_traj(
            no_dir,
            "repo__a-2",
            {
                "trajectory": [{"action": "submit", "observation": "done", "query": []}],
                "info": {"exit_status": "submitted", "submission": "patch"},
            },
        )

        report = mod.build_report(with_dir, no_dir)
        summary = report["summary"]
        assert "mem_unique_failures" in summary
        assert "effective_interventions" in summary
        assert summary["mem_unique_failures"] >= 1
        assert summary["effective_interventions"] >= 1
        assert "mem_unique_failures_top" in report
        assert "effective_interventions_top" in report
