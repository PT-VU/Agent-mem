from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile


def _load_metrics_module():
    cur = Path(__file__).resolve()
    while cur.name != "SWE-bench" and cur.parent != cur:
        cur = cur.parent
    path = cur / "PDDL_work_mem" / "06_artificial_intelligence" / "experiments" / "common" / "collect_run_metrics.py"
    spec = importlib.util.spec_from_file_location("collect_run_metrics", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[arg-type]
    return mod


def _inject_query(hints: list[str]) -> list[dict[str, str]]:
    lines = [
        "[AgentMem Hints]",
        "Treat matching hints as high-priority guidance for this attempt.",
        "Avoid over-exploration: reuse validated repro/fix paths first, and once a minimal plausible patch exists, validate it before broadening the search.",
    ]
    for i, h in enumerate(hints, start=1):
        lines.append(f"{i}. {h}")
    return [{"role": "user", "content": "\n".join(lines)}]


def test_intervention_quality_metrics_basic():
    mod = _load_metrics_module()
    payload = {
        "trajectory": [
            {"action": "ls -la", "observation": "Traceback: file not found", "query": []},
            {
                "action": "pytest -q",
                "observation": "ok",
                "query": _inject_query(["run pytest -q before submission"]),
            },
            {"action": "str_replace_editor replace", "observation": "done", "query": []},
        ]
    }
    out = mod._compute_intervention_quality([payload])
    assert out["total_injection_events"] == 1
    assert out["accepted_injection_events"] == 1
    assert out["hint_accept_rate"] == 1.0
    assert out["recovery_candidates_after_injection"] == 1
    assert out["recovered_after_injection"] == 1
    assert out["post_injection_recovery_rate"] == 1.0


def test_intervention_quality_repeated_action_drop():
    mod = _load_metrics_module()
    payload = {
        "trajectory": [
            {"action": "ls", "observation": "", "query": []},
            {"action": "ls", "observation": "", "query": []},
            {"action": "pytest -q", "observation": "", "query": _inject_query(["run tests"])},
            {"action": "str_replace_editor replace", "observation": "", "query": []},
        ]
    }
    out = mod._compute_intervention_quality([payload])
    assert out["trajectories_with_injection"] == 1
    assert out["repeated_action_drop_rate"] >= 0.0


def test_event_log_traceability_stats():
    mod = _load_metrics_module()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "events.jsonl"
        rows = [
            {
                "tool": "HOOK",
                "payload": {
                    "event": "memory_injected",
                    "hint_count": 1,
                    "selected_memory_ids": ["card-1"],
                    "selected_trace_ids": ["run:inst:1:e:1"],
                    "trace_id_missing": False,
                },
            },
            {
                "tool": "HOOK",
                "payload": {
                    "event": "memory_injected",
                    "hint_count": 1,
                    "selected_memory_ids": ["card-2"],
                    "selected_trace_ids": [],
                    "trace_id_missing": True,
                },
            },
        ]
        p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        out = mod._parse_event_logs([p])
        tr = out["injection_traceability"]
        assert tr["injected_events_total"] == 2
        assert tr["injected_traceable_events"] == 1
        assert tr["injected_trace_missing_events"] == 1
        assert tr["effective_interventions_traceable"] == 1
