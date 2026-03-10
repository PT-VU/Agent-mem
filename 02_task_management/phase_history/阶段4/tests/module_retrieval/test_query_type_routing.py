from __future__ import annotations

import sys
import tempfile
from pathlib import Path


def _bootstrap_path() -> None:
    cur = Path(__file__).resolve()
    while cur.name != "SWE-bench" and cur.parent != cur:
        cur = cur.parent
    pkg_root = cur / "PDDL_work_mem" / "source_code" / "sweagent_external_tools"
    if str(pkg_root) not in sys.path:
        sys.path.insert(0, str(pkg_root))


_bootstrap_path()

from agent_mem.core.problem_file import ActionType, Outcome, ProblemFile  # noqa: E402
from agent_mem.retrieval.memory_agent import MemoryAgent  # noqa: E402
from agent_mem.storage.graph_store import GraphStore  # noqa: E402


def test_query_type_routing_uses_failure_card():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = GraphStore(storage_dir=tmpdir)
        store.upsert_failure_card_v2(
            {
                "task_id": "stage4_query_task",
                "error_signature": {"error_type": "test_failure"},
                "candidate_fix_actions": ["run_related_tests_first_then_apply_targeted_fix"],
                "verification_commands": ["pytest -q"],
                "confidence": 0.7,
                "evidence_refs": ["a1"],
            }
        )

        agent = MemoryAgent(store)
        pf = ProblemFile(
            task_id="stage4_query_task",
            action_type=ActionType.RUN_TEST,
            action_family="test_failure_fix",
            intent_text="run tests",
            action_text="pytest -q",
            outcome=Outcome.FAIL,
        )
        result = agent.retrieve_for_query_type(
            query_type="test_failure_fix",
            current_action="pytest -q",
            current_problem_file=pf,
            error_type="test_failure",
            error_message="AssertionError: expected 1 got 0",
        )

        assert result["retrieval_debug"]["query_type"] == "test_failure_fix"
        assert any(rec.get("type") == "failure_card_v2" for rec in result.get("recommendations", []))
