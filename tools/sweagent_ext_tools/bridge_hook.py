from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from sweagent.agent.hooks.abstract import AbstractAgentHook
from sweagent.types import AgentInfo, StepOutput, Trajectory
from sweagent.utils.log import get_logger

from .tools.io_utils import append_json_log


class ExternalToolBridgeHook(AbstractAgentHook):
    """Bridge hook that calls external Tool A/Tool B commands.

    The event payload is serialized to `SWE_AGENT_EXT_EVENT_JSON`.
    """

    def __init__(
        self,
        *,
        tool_a_cmd: str | None = None,
        tool_b_cmd: str | None = None,
        timeout_sec: float | None = None,
    ):
        self.tool_a_cmd = tool_a_cmd or os.getenv("SWE_AGENT_EXT_TOOL_A_CMD", "").strip() or None
        self.tool_b_cmd = tool_b_cmd or os.getenv("SWE_AGENT_EXT_TOOL_B_CMD", "").strip() or None
        if timeout_sec is None:
            timeout_raw = os.getenv("SWE_AGENT_EXT_TOOL_TIMEOUT_SEC", "2.0")
            timeout_sec = float(timeout_raw)
        self.timeout_sec = timeout_sec
        self._agent_name = "unknown"
        self._logger = get_logger("swea-ext-bridge", emoji="🧩")

    def on_init(self, *, agent):
        self._agent_name = agent.name

    def _run_cmd(self, *, cmd: str | None, tool_name: str, payload: dict[str, Any]) -> None:
        if not cmd:
            return
        env = os.environ.copy()
        env["SWE_AGENT_EXT_EVENT_JSON"] = json.dumps(payload, ensure_ascii=False)
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                check=False,
                text=True,
                capture_output=True,
                timeout=self.timeout_sec,
                env=env,
            )
        except subprocess.TimeoutExpired:
            self._logger.warning("External %s timed out after %.2fs", tool_name, self.timeout_sec)
            return
        except Exception as e:
            self._logger.warning("External %s failed: %s", tool_name, e)
            return

        if result.stdout.strip():
            self._logger.info("[%s stdout] %s", tool_name, result.stdout.strip())
        if result.stderr.strip():
            self._logger.warning("[%s stderr] %s", tool_name, result.stderr.strip())
        if result.returncode != 0:
            self._logger.warning("External %s exit code=%d", tool_name, result.returncode)

    def on_actions_generated(self, *, step: StepOutput):
        self._run_cmd(
            cmd=self.tool_a_cmd,
            tool_name="tool_a",
            payload={
                "version": "v1",
                "event": "plan_generated",
                "agent": self._agent_name,
                "instance_id": self._agent_name,
                "run_id": os.getenv("SWE_AGENT_EXT_RUN_ID", ""),
                "thought": step.thought,
                "action": step.action,
            },
        )

    def on_action_error(self, *, step: StepOutput, error_type: str, error_message: str):
        self._run_cmd(
            cmd=self.tool_b_cmd,
            tool_name="tool_b",
            payload={
                "version": "v1",
                "event": "action_error",
                "agent": self._agent_name,
                "instance_id": self._agent_name,
                "run_id": os.getenv("SWE_AGENT_EXT_RUN_ID", ""),
                "error_type": error_type,
                "error_message": error_message,
                "thought": step.thought,
                "action": step.action,
            },
        )

    def on_run_done(self, *, trajectory: Trajectory, info: AgentInfo):
        self._run_cmd(
            cmd=self.tool_b_cmd or self.tool_a_cmd,
            tool_name="tool_b",
            payload={
                "version": "v1",
                "event": "run_done",
                "agent": self._agent_name,
                "instance_id": self._agent_name,
                "run_id": os.getenv("SWE_AGENT_EXT_RUN_ID", ""),
                "trajectory_steps": len(trajectory),
                "exit_status": info.get("exit_status"),
                "has_submission": bool(info.get("submission")),
            },
        )
        append_json_log(
            "HOOK",
            {
                "version": "v1",
                "event": "run_done",
                "agent": self._agent_name,
                "trajectory_steps": len(trajectory),
                "exit_status": info.get("exit_status"),
                "has_submission": bool(info.get("submission")),
            },
        )
