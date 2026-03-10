from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_path() -> None:
    cur = Path(__file__).resolve()
    while cur.name != "SWE-bench" and cur.parent != cur:
        cur = cur.parent
    pkg_root = cur / "PDDL_work_mem" / "source_code" / "sweagent_external_tools"
    if str(pkg_root) not in sys.path:
        sys.path.insert(0, str(pkg_root))


_bootstrap_path()

from agent_mem.core.observation_kg import ObservationKG  # noqa: E402
from agent_mem.processing.rca_agent import ErrorType, RCAAgent  # noqa: E402


def test_rank_candidates_tie_breaks_by_earliest_step():
    rca = RCAAgent(ObservationKG())
    failure_node = {"id": "f3", "data": {"step_index": 3, "touched_files": ["a.py"], "outcome": "fail"}}
    # Two candidates with same info except step_index.
    c1 = {
        "id": "c1",
        "data": {
            "step_index": 1,
            "outcome": "fail",
            "intent_text": "run pytest",
            "failure_signature": {"error_type": "test_failure"},
            "touched_files": ["a.py"],
        },
    }
    c2 = {
        "id": "c2",
        "data": {
            "step_index": 2,
            "outcome": "fail",
            "intent_text": "run pytest",
            "failure_signature": {"error_type": "test_failure"},
            "touched_files": ["a.py"],
        },
    }
    ranked = rca._rank_root_cause_candidates(
        root_cause_candidates=[c2, c1],
        failure_node=failure_node,
        task_subgraph={"nodes": [c1, c2, failure_node], "edges": []},
        error_type=ErrorType.TEST_FAILURE,
    )
    assert len(ranked) >= 2
    assert ranked[0]["node_id"] == "c1"
    assert "decisive_score" in ranked[0]


def test_analyze_returns_rca_v2_core_fields():
    rca = RCAAgent(ObservationKG())
    task_subgraph = {
        "nodes": [
            {
                "id": "a1",
                "data": {
                    "step_index": 1,
                    "outcome": "fail",
                    "intent_text": "edit file",
                    "failure_signature": {"error_type": "import_error"},
                    "touched_files": ["main.py"],
                },
            },
            {
                "id": "a2",
                "data": {
                    "step_index": 2,
                    "outcome": "fail",
                    "intent_text": "run pytest",
                    "failure_signature": {"error_type": "import_error"},
                    "touched_files": ["main.py"],
                },
            },
        ],
        "edges": [{"source": "a1", "target": "a2", "edge_type": "success_next"}],
    }
    # Use private single-failure path for deterministic test.
    single = rca._analyze_single_failure(task_subgraph["nodes"][1], task_subgraph)
    assert "root_cause_nodes" in single
    assert "propagation_chain" in single
    assert "error_module" in single
    assert "evidence_refs" in single
