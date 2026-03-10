from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
import types


def _bootstrap_path() -> None:
    cur = Path(__file__).resolve()
    while cur.name != "SWE-bench" and cur.parent != cur:
        cur = cur.parent
    if str(cur) not in sys.path:
        sys.path.insert(0, str(cur))


_bootstrap_path()

# Minimal sweagent stubs for isolated unit testing.
if "sweagent" not in sys.modules:
    sweagent_mod = types.ModuleType("sweagent")
    sys.modules["sweagent"] = sweagent_mod
    sys.modules["sweagent.agent"] = types.ModuleType("sweagent.agent")
    sys.modules["sweagent.agent.hooks"] = types.ModuleType("sweagent.agent.hooks")
    abs_mod = types.ModuleType("sweagent.agent.hooks.abstract")

    class _AbstractAgentHook:
        pass

    abs_mod.AbstractAgentHook = _AbstractAgentHook
    sys.modules["sweagent.agent.hooks.abstract"] = abs_mod

    types_mod = types.ModuleType("sweagent.types")
    types_mod.AgentInfo = dict
    types_mod.StepOutput = object
    types_mod.Trajectory = list
    sys.modules["sweagent.types"] = types_mod

    sys.modules["sweagent.utils"] = types.ModuleType("sweagent.utils")
    log_mod = types.ModuleType("sweagent.utils.log")

    class _DummyLogger:
        def info(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

    def _get_logger(*args, **kwargs):
        return _DummyLogger()

    log_mod.get_logger = _get_logger
    sys.modules["sweagent.utils.log"] = log_mod

from PDDL_work_mem.source_code.sweagent_external_tools.bridge_hook import (  # noqa: E402
    ExternalToolBridgeHook,
)


def test_c1_triggers_first_failure_consecutive_and_before_submit():
    hook = ExternalToolBridgeHook(tool_a_cmd=None, tool_b_cmd=None, timeout_sec=0.1)

    # before_submit trigger
    hook._scan_proactive_triggers("submit final patch")
    assert any(t.startswith("before_submit") for t in hook._recent_triggers)

    # first_failure + consecutive_failures triggers
    step = SimpleNamespace(action="pytest -q", thought="run tests", observation="error")
    hook.on_action_error(step=step, error_type="test_failure", error_message="AssertionError")
    assert any(t.startswith("first_failure:") for t in hook._recent_triggers)
    hook.on_action_error(step=step, error_type="test_failure", error_message="AssertionError")
    assert any(t.startswith("consecutive_failures:2") for t in hook._recent_triggers)


def test_trace_id_bound_intervention_logging():
    import PDDL_work_mem.source_code.sweagent_external_tools.bridge_hook as hook_mod

    hook = ExternalToolBridgeHook(tool_a_cmd=None, tool_b_cmd=None, timeout_sec=0.1)
    hook._step_index = 5
    hook._pending_memory_hints.append(
        {
            "hint": "run pytest -q before submit",
            "memory_id": "card-1",
            "trace_id": "runX:instY:5:action_error:9",
            "source_event": "action_error",
            "confidence": 0.9,
        }
    )
    msgs: list[dict[str, str]] = []
    captured: list[tuple[str, dict]] = []
    original = hook_mod.append_json_log
    hook_mod.append_json_log = lambda tool, payload: captured.append((tool, payload))
    try:
        hook.on_model_query(messages=msgs, agent="test-agent")
    finally:
        hook_mod.append_json_log = original
    assert msgs and "[AgentMem Hints]" in msgs[-1]["content"]
    injected = [row for row in captured if row[1].get("event") == "memory_injected"]
    assert injected
    payload = injected[-1][1]
    assert payload.get("trace_id_missing") is False
    assert payload.get("selected_trace_ids") == ["runX:instY:5:action_error:9"]
    interventions = payload.get("selected_interventions") or []
    assert interventions and interventions[0]["trace_id"] == "runX:instY:5:action_error:9"
    assert interventions[0]["intervention_id"].startswith("intv:runX:instY:5:action_error:9:")
