from __future__ import annotations

import json
import os
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    import pytest
except ModuleNotFoundError:  # pragma: no cover - runtime-only fallback
    pytest = None


def _ensure_runtime_deps() -> None:
    missing = [name for name in ("swerex", "sweagent") if importlib.util.find_spec(name) is None]
    if not missing:
        return
    if pytest is not None:
        for name in missing:
            pytest.importorskip(name)
        return
    print(f"SMOKE TEST SKIPPED: missing dependencies: {', '.join(missing)}")
    raise SystemExit(0)


_ensure_runtime_deps()

from swerex.deployment.config import DummyDeploymentConfig
from swerex.exceptions import SwerexException
from swerex.runtime.abstract import Action, BashObservation, Observation
from swerex.runtime.dummy import DummyRuntime

from sweagent.agent.agents import DefaultAgent, DefaultAgentConfig
from sweagent.agent.hooks.plugin_loader import add_external_agent_hook_from_env
from sweagent.agent.models import InstantEmptySubmitModelConfig, PredeterminedTestModel
from sweagent.agent.problem_statement import EmptyProblemStatement
from sweagent.environment.swe_env import EnvironmentConfig, SWEEnv
from sweagent.tools.parsing import Identity
from sweagent.tools.tools import ToolConfig


class RuntimeRaisesOnCommand(DummyRuntime):
    async def run_in_session(self, action: Action) -> Observation:
        if action.action_type == "bash" and action.command == "raise":
            raise SwerexException("forced command error")
        return await super().run_in_session(action)


class RuntimeReturnsNonZero(DummyRuntime):
    async def run_in_session(self, action: Action) -> Observation:
        if action.action_type == "bash" and action.command == "failcmd":
            return BashObservation(output="simulated command error", exit_code=1)
        return await super().run_in_session(action)


def _make_agent(outputs: list[str]) -> DefaultAgent:
    agent = DefaultAgent.from_config(
        DefaultAgentConfig(
            model=InstantEmptySubmitModelConfig(),
            tools=ToolConfig(parse_function=Identity()),
        )
    )
    loaded = add_external_agent_hook_from_env(agent)
    assert loaded, "External hook was not loaded. Check environment variables."
    agent.model = PredeterminedTestModel(outputs)  # type: ignore[assignment]
    return agent


def _run_case(agent: DefaultAgent, runtime: DummyRuntime, expected_exit: str) -> None:
    env = SWEEnv.from_config(EnvironmentConfig(deployment=DummyDeploymentConfig(), repo=None))
    env.start()
    env.deployment.runtime = runtime  # type: ignore[attr-defined]
    with TemporaryDirectory() as td:
        result = agent.run(problem_statement=EmptyProblemStatement(), env=env, output_dir=Path(td))
        assert result.info["exit_status"] == expected_exit, result.info
    env.close()


def _load_logs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _assert_with_mem_logs(logs: list[dict]) -> dict[str, int]:
    tool_a_count = sum(1 for item in logs if item.get("tool") == "A")
    has_b_env_error = any(
        item.get("tool") == "B" and item.get("payload", {}).get("error_type") == "environment_error" for item in logs
    )
    has_b_nonzero = any(
        item.get("tool") == "B" and item.get("payload", {}).get("error_type") == "command_nonzero_exit"
        for item in logs
    )
    assert tool_a_count >= 3, f"Expected >=3 Tool A calls, got {tool_a_count}"
    assert has_b_env_error, "Missing Tool B call for environment_error"
    assert has_b_nonzero, "Missing Tool B call for command_nonzero_exit"
    return {"tool_a_count": tool_a_count}


def _assert_no_mem_logs(logs: list[dict]) -> dict[str, int]:
    baseline_records = [item for item in logs if item.get("tool") == "BASELINE"]
    plan_count = sum(1 for item in baseline_records if item.get("payload", {}).get("event") == "plan_generated")
    has_env_error = any(
        item.get("payload", {}).get("event") == "action_error"
        and item.get("payload", {}).get("error_type") == "environment_error"
        for item in baseline_records
    )
    has_nonzero = any(
        item.get("payload", {}).get("event") == "action_error"
        and item.get("payload", {}).get("error_type") == "command_nonzero_exit"
        for item in baseline_records
    )
    has_run_done = any(item.get("payload", {}).get("event") == "run_done" for item in baseline_records)
    assert plan_count >= 3, f"Expected >=3 baseline plan events, got {plan_count}"
    assert has_env_error, "Missing baseline action_error for environment_error"
    assert has_nonzero, "Missing baseline action_error for command_nonzero_exit"
    assert has_run_done, "Missing baseline run_done summary event"
    return {"baseline_plan_count": plan_count}


def main() -> int:
    log_path = Path(os.getenv("SWE_AGENT_EXT_TOOLS_LOG_FILE", "/tmp/sweagent_ext_tools.log"))
    run_mode = os.getenv("SWE_AGENT_EXT_MODE", "with-mem").strip() or "with-mem"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    _run_case(
        agent=_make_agent(["echo ok", "raise"]),
        runtime=RuntimeRaisesOnCommand(),
        expected_exit="exit_environment_error",
    )
    _run_case(
        agent=_make_agent(["failcmd", "raise_cost"]),
        runtime=RuntimeReturnsNonZero(),
        expected_exit="exit_cost",
    )

    logs = _load_logs(log_path)
    if run_mode == "with-mem":
        metrics = _assert_with_mem_logs(logs)
    elif run_mode == "no-mem":
        metrics = _assert_no_mem_logs(logs)
    else:
        raise AssertionError(f"Unsupported SWE_AGENT_EXT_MODE={run_mode!r}")

    print(f"SMOKE TEST PASS mode={run_mode}")
    print(f"log_file={log_path}")
    for k, v in metrics.items():
        print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
