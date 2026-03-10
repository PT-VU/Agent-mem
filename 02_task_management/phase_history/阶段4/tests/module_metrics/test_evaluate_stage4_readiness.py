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
        / "evaluate_stage4_readiness.py"
    )
    spec = importlib.util.spec_from_file_location("evaluate_stage4_readiness", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[arg-type]
    return mod


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_stage4_readiness_passes_with_two_positive_pairs():
    mod = _load_module()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        pairs = []
        for i in range(2):
            pair_id = f"pair_{i+1}"
            no_eval = _write(
                root / f"{pair_id}_no_eval.json",
                {"solved_rate_on_planned": 0.60},
            )
            with_eval = _write(
                root / f"{pair_id}_with_eval.json",
                {"solved_rate_on_planned": 0.70},
            )
            no_metrics = _write(
                root / f"{pair_id}_no_metrics.json",
                {
                    "trajectory_diagnostics": {
                        "tool_failed_actions": 100,
                        "step_count_distribution": {"mean": 120},
                        "instance_cost_distribution": {"total": 10.0},
                    }
                },
            )
            with_metrics = _write(
                root / f"{pair_id}_with_metrics.json",
                {
                    "trajectory_diagnostics": {
                        "tool_failed_actions": 80,
                        "step_count_distribution": {"mean": 110},
                        "instance_cost_distribution": {"total": 9.0},
                    }
                },
            )
            diff = _write(
                root / f"{pair_id}_diff.json",
                {"only_with": ["id_1", "id_2", "id_3", "id_4", "id_5"], "only_no": [], "both_resolved": ["id_6"]},
            )
            ids = root / f"{pair_id}_ids.json"
            ids.write_text(json.dumps([f"id_{j}" for j in range(1, 11)]), encoding="utf-8")
            pairs.append(
                mod.PairInput(
                    pair_id=pair_id,
                    no_mem_eval=no_eval,
                    with_mem_eval=with_eval,
                    no_mem_metrics=no_metrics,
                    with_mem_metrics=with_metrics,
                    diff_report=diff,
                    instance_ids=ids,
                )
            )

        out = mod.evaluate_pairs(pairs, bootstrap_samples=2000, bootstrap_seed=7)
        assert out["pair_count"] == 2
        assert out["rules"]["rerun_count_at_least_2"] is True
        assert out["rules"]["delta_solved_rate_positive_in_all_pairs"] is True
        assert out["rules"]["bootstrap_ci95_lower_ge_0"] is True
        assert out["stage4_stats_gate_passed"] is True


def test_stage4_readiness_fails_with_single_pair():
    mod = _load_module()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        no_eval = _write(root / "no_eval.json", {"solved_rate_on_planned": 0.64})
        with_eval = _write(root / "with_eval.json", {"solved_rate_on_planned": 0.68})
        no_metrics = _write(
            root / "no_metrics.json",
            {
                "trajectory_diagnostics": {
                    "tool_failed_actions": 91,
                    "step_count_distribution": {"mean": 104.3},
                    "instance_cost_distribution": {"total": 6.09},
                }
            },
        )
        with_metrics = _write(
            root / "with_metrics.json",
            {
                "trajectory_diagnostics": {
                    "tool_failed_actions": 66,
                    "step_count_distribution": {"mean": 103.9},
                    "instance_cost_distribution": {"total": 5.79},
                }
            },
        )
        diff = _write(root / "diff.json", {"only_with": ["id_1"], "only_no": ["id_2"], "both_resolved": []})
        ids = root / "ids.json"
        ids.write_text(json.dumps([f"id_{j}" for j in range(1, 11)]), encoding="utf-8")

        out = mod.evaluate_pairs(
            [
                mod.PairInput(
                    pair_id="pair_1",
                    no_mem_eval=no_eval,
                    with_mem_eval=with_eval,
                    no_mem_metrics=no_metrics,
                    with_mem_metrics=with_metrics,
                    diff_report=diff,
                    instance_ids=ids,
                )
            ],
            bootstrap_samples=500,
            bootstrap_seed=3,
        )
        assert out["pair_count"] == 1
        assert out["rules"]["rerun_count_at_least_2"] is False
        assert out["stage4_stats_gate_passed"] is False
