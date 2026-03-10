from __future__ import annotations

from collections import deque
from types import SimpleNamespace

import pytest

pytest.importorskip("sweagent")

from bridge_hook import ExternalToolBridgeHook


def _hint(hint: str, *, family_id: str, score: float) -> dict:
    return {
        "hint": hint,
        "family_id": family_id,
        "selection_score": score,
        "item_confidence": 0.8,
        "batch_confidence": 0.8,
        "trace_id": f"trace:{family_id}:{score}",
    }


def test_bridge_hook_injects_one_hint_per_family_and_tracks_family_state(monkeypatch):
    monkeypatch.setenv("SWE_AGENT_MEM_INJECT_ENABLED", "1")
    monkeypatch.setenv("SWE_AGENT_MEM_MIN_CONFIDENCE", "0")
    monkeypatch.setenv("SWE_AGENT_MEM_FAMILY_COOLDOWN_STEPS", "4")
    monkeypatch.setenv("SWE_AGENT_MEM_MAX_HINTS_PER_FAMILY_PER_ATTEMPT", "1")

    hook = ExternalToolBridgeHook()
    hook._pending_memory_hints = deque(
        [
            _hint(
                "Add a state transition guard so planning moves into execution.",
                family_id="planning_loop__planning_transition_failure__force_progression_transition",
                score=0.91,
            ),
            _hint(
                "Track planning progress and enforce an execution step.",
                family_id="planning_loop__planning_transition_failure__force_progression_transition",
                score=0.82,
            ),
            _hint(
                "Run a focused validation command before changing more files.",
                family_id="validation_gap__missing_validation__add_local_validation",
                score=0.77,
            ),
        ]
    )
    hook._step_index = 5

    messages: list[dict[str, str]] = []
    hook.on_model_query(messages=messages, agent="main")

    assert len(messages) == 1
    content = messages[0]["content"]
    assert "Add a state transition guard" in content
    assert "Run a focused validation command" in content
    assert "Track planning progress" not in content
    assert hook._hint_family_injected_count[
        "planning_loop__planning_transition_failure__force_progression_transition"
    ] == 1
    assert hook._hint_family_last_injected_step[
        "planning_loop__planning_transition_failure__force_progression_transition"
    ] == 5


def test_bridge_hook_blocks_repeat_family_by_cooldown_and_attempt_limit(monkeypatch):
    monkeypatch.setenv("SWE_AGENT_MEM_INJECT_ENABLED", "1")
    monkeypatch.setenv("SWE_AGENT_MEM_MIN_CONFIDENCE", "0")
    monkeypatch.setenv("SWE_AGENT_MEM_FAMILY_COOLDOWN_STEPS", "4")
    monkeypatch.setenv("SWE_AGENT_MEM_MAX_HINTS_PER_FAMILY_PER_ATTEMPT", "1")

    hook = ExternalToolBridgeHook()
    family_id = "planning_loop__planning_transition_failure__force_progression_transition"
    hook._hint_family_last_injected_step[family_id] = 5
    hook._hint_family_injected_count[family_id] = 1

    hook._pending_memory_hints = deque(
        [
            _hint(
                "Use a state transition guard before planning again.",
                family_id=family_id,
                score=0.88,
            )
        ]
    )

    hook._step_index = 7
    assert hook._select_hints_for_injection() == []
    assert len(hook._pending_memory_hints) == 1

    hook._step_index = 12
    assert hook._select_hints_for_injection() == []


def test_bridge_hook_prefers_repair_and_validation_before_belief(monkeypatch):
    monkeypatch.setenv("SWE_AGENT_MEM_INJECT_ENABLED", "1")
    monkeypatch.setenv("SWE_AGENT_MEM_MIN_CONFIDENCE", "0")
    monkeypatch.setenv("SWE_AGENT_MEM_MAX_HINTS", "3")

    hook = ExternalToolBridgeHook()
    hook._pending_memory_hints = deque(
        [
            {
                **_hint("Use the targeted repair pattern.", family_id="repair_pattern:123", score=0.81),
                "type": "repair_pattern_v2",
            },
            {
                **_hint("Run focused validation before resubmitting.", family_id="validation_gap:abc", score=0.8),
                "type": "abstract_pattern",
                "normalized_pattern_type": "validation_gap",
            },
            {
                **_hint("Remember the old workflow order.", family_id="belief_tip:workflow:1", score=0.95),
                "type": "belief_tip",
            },
        ]
    )
    messages: list[dict[str, str]] = []
    hook.on_model_query(messages=messages, agent="main")
    content = messages[0]["content"]
    assert "Use the targeted repair pattern." in content
    assert "Run focused validation before resubmitting." in content
    assert "Remember the old workflow order." in content
    assert content.index("Use the targeted repair pattern.") < content.index("Remember the old workflow order.")


def test_bridge_hook_uses_problem_statement_id_when_available(monkeypatch):
    monkeypatch.delenv("SWE_AGENT_EXT_INSTANCE_ID", raising=False)
    hook = ExternalToolBridgeHook()

    class ProblemStatement:
        id = "astropy__astropy-11693"

    class Agent:
        name = "main"
        _problem_statement = ProblemStatement()

    hook.on_init(agent=Agent())
    assert hook._instance_id == "astropy__astropy-11693"


def test_bridge_hook_drops_workflow_hints_after_early_steps(monkeypatch):
    monkeypatch.setenv("SWE_AGENT_MEM_INJECT_ENABLED", "1")
    monkeypatch.setenv("SWE_AGENT_MEM_MIN_CONFIDENCE", "0")

    hook = ExternalToolBridgeHook()
    hook._step_index = 8
    hook._pending_memory_hints = deque(
        [
            {
                **_hint("Consider: Generate plan for task...", family_id="workflow_step:consider: generate plan for task...", score=0.9),
                "type": "workflow_step",
            },
            {
                **_hint("Validate the minimal fix before exploring more files.", family_id="validation_gap:add_local_validation", score=0.85),
                "type": "abstract_pattern",
                "normalized_pattern_type": "validation_gap",
            },
        ]
    )

    selected = hook._select_hints_for_injection()
    assert len(selected) == 1
    assert selected[0]["family_id"] == "validation_gap:add_local_validation"


def test_bridge_hook_enqueues_closure_hint_after_ad_hoc_script_sprawl(monkeypatch):
    monkeypatch.setenv("SWE_AGENT_MEM_INJECT_ENABLED", "1")
    hook = ExternalToolBridgeHook()
    hook._scan_proactive_triggers("python reproduce_error.py")
    hook._scan_proactive_triggers("python test_fix_comprehensive.py")

    family_ids = [str(item.get("family_id", "")) for item in hook._pending_memory_hints]
    assert "closure_signal:over_exploration_after_key_signal" in family_ids


def test_bridge_hook_runtime_guard_payload_reflects_closure_state(monkeypatch):
    hook = ExternalToolBridgeHook()
    hook._record_trigger("over_exploration", detail="2")
    payload = hook._runtime_guard_payload()
    assert payload["closure_active"] is True
    assert "workflow_step" in payload["blocked_families"]
    assert "planning_loop" in payload["blocked_families"]


def test_bridge_hook_soft_blocks_new_ad_hoc_script_creation_after_closure(monkeypatch):
    hook = ExternalToolBridgeHook()
    hook._closure_active = True
    hook._ad_hoc_script_names = {"reproduce_error.py", "test_fix_comprehensive.py"}
    step = SimpleNamespace(
        thought="create another debug script",
        action="cat > debug_more.py <<'PY'\nprint('x')\nPY",
    )
    captured = []

    def fake_run_cmd(*, cmd, tool_name, payload):
        captured.append(payload)

    monkeypatch.setattr(hook, "_run_cmd", fake_run_cmd)
    hook.on_actions_generated(step=step)
    assert "Runtime guard blocked new ad-hoc script creation after closure" in step.action
    assert captured
    assert captured[0]["runtime_guard"]["closure_active"] is True
