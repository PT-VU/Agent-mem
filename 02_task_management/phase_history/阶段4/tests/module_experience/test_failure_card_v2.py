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

from agent_mem.processing.failure_card_builder import FailureCardBuilder  # noqa: E402
from agent_mem.core.problem_file import ActionType, Outcome, ProblemFile  # noqa: E402


def test_failure_card_v2_minimal_contract():
    builder = FailureCardBuilder()
    actions = [
        ProblemFile(
            task_id="stage4_task",
            action_type=ActionType.TOOL_CALL,
            action_family="planning",
            intent_text="inspect files",
            action_text="ls -la",
            outcome=Outcome.SUCCESS,
            step_index=1,
        ),
        ProblemFile(
            task_id="stage4_task",
            action_type=ActionType.RUN_TEST,
            action_family="test_failure_fix",
            intent_text="run pytest -q",
            action_text="pytest -q",
            outcome=Outcome.FAIL,
            step_index=2,
        ),
    ]
    card = builder.build_from_unresolved(task_id="stage4_task", actions=actions)
    payload = card.to_dict()

    assert payload["schema_version"] == "2.0"
    assert payload["task_id"] == "stage4_task"
    assert isinstance(payload["candidate_fix_actions"], list)
    assert isinstance(payload["verification_commands"], list)
