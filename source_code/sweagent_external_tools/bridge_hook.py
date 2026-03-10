from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections import deque
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
            timeout_raw = os.getenv("SWE_AGENT_EXT_TOOL_TIMEOUT_SEC", "8.0")
            timeout_sec = float(timeout_raw)
        self.timeout_sec = timeout_sec
        self.tool_a_timeout_sec = self._read_float_env(
            "SWE_AGENT_EXT_TOOL_A_TIMEOUT_SEC",
            default=max(45.0, self.timeout_sec * 3.0),
        )
        self.tool_b_timeout_sec = self._read_float_env("SWE_AGENT_EXT_TOOL_B_TIMEOUT_SEC", default=self.timeout_sec)
        self.retry_timeout_sec = self._read_float_env(
            "SWE_AGENT_EXT_TOOL_RETRY_TIMEOUT_SEC",
            default=max(60.0, self.tool_a_timeout_sec * 2.0, self.timeout_sec * 2.5),
        )
        self.max_retries = self._read_int_env("SWE_AGENT_EXT_TOOL_MAX_RETRIES", default=1, minimum=0)
        self.enable_stale_fallback = self._read_bool_env("SWE_AGENT_EXT_TOOL_ENABLE_STALE_FALLBACK", default=True)
        self.enable_adaptive_timeout = self._read_bool_env("SWE_AGENT_EXT_TOOL_ADAPTIVE_TIMEOUT", default=True)
        self.tool_circuit_threshold = self._read_int_env("SWE_AGENT_EXT_TOOL_CIRCUIT_THRESHOLD", default=8, minimum=1)
        self.tool_circuit_cooldown_sec = self._read_float_env("SWE_AGENT_EXT_TOOL_CIRCUIT_COOLDOWN_SEC", default=30.0)
        self.inject_enabled = self._read_bool_env("SWE_AGENT_MEM_INJECT_ENABLED", default=True)
        # Soft cap: 0 means "no fixed count cap" and selection is driven by budget/quality.
        self.max_hints = self._read_int_env("SWE_AGENT_MEM_MAX_HINTS", default=0, minimum=0)
        self.min_confidence = self._read_float_env("SWE_AGENT_MEM_MIN_CONFIDENCE", default=0.6)
        self.min_item_confidence = self._read_float_env("SWE_AGENT_MEM_MIN_ITEM_CONFIDENCE", default=0.0)
        self.max_hint_chars = self._read_int_env("SWE_AGENT_MEM_MAX_HINT_CHARS", default=900, minimum=120)
        self.hint_char_budget = self._read_int_env("SWE_AGENT_MEM_HINT_CHAR_BUDGET", default=2400, minimum=480)
        self.family_cooldown_steps = self._read_int_env("SWE_AGENT_MEM_FAMILY_COOLDOWN_STEPS", default=4, minimum=0)
        self.max_hints_per_family_per_attempt = self._read_int_env(
            "SWE_AGENT_MEM_MAX_HINTS_PER_FAMILY_PER_ATTEMPT",
            default=1,
            minimum=0,
        )
        self.intervention_window_steps = self._read_int_env("SWE_AGENT_MEM_INTERVENTION_WINDOW_STEPS", default=5, minimum=1)
        self.require_trigger_for_injection = self._read_bool_env(
            "SWE_AGENT_MEM_REQUIRE_TRIGGER_FOR_INJECTION",
            default=False,
        )
        self.gate_min_external_ratio = self._read_float_env("SWE_AGENT_MEM_GATE_MIN_EXTERNAL_RATIO", default=0.35)
        self.gate_min_buffer_ratio = self._read_float_env("SWE_AGENT_MEM_GATE_MIN_BUFFER_RATIO", default=0.15)
        self.gate_min_action_error_coverage = self._read_float_env(
            "SWE_AGENT_MEM_GATE_MIN_ACTION_ERROR_COVERAGE",
            default=0.60,
        )
        self.gate_hard_fail = self._read_bool_env("SWE_AGENT_MEM_GATE_HARD_FAIL", default=False)
        self._pending_memory_hints: deque[dict[str, Any]] = deque()
        self._recent_hint_fingerprints: set[str] = set()
        self._hint_family_last_injected_step: dict[str, int] = {}
        self._hint_family_injected_count: dict[str, int] = {}
        self._recent_triggers: deque[str] = deque(maxlen=16)
        self._seen_files: set[str] = set()
        self._ad_hoc_script_names: set[str] = set()
        self._closure_active = False
        self._active_interventions: list[dict[str, Any]] = []
        self._consecutive_failures = 0
        self._step_index = 0
        self._event_seq = 0
        self._agent_name = "unknown"
        self._instance_id = "unknown"
        self._attempt_id = os.getenv("SWE_AGENT_EXT_ATTEMPT_ID", "attempt-0").strip() or "attempt-0"
        self._run_id = os.getenv("SWE_AGENT_EXT_RUN_ID", "").strip()
        self._adaptive_timeout_by_tool: dict[str, float] = {}
        self._tool_failure_streak: dict[str, int] = {}
        self._tool_circuit_open_until: dict[str, float] = {}
        self._last_success_payload_by_event: dict[str, dict[str, Any]] = {}
        self._metrics: dict[str, int] = {
            "plan_generated": 0,
            "action_error_events": 0,
            "error_like_observation": 0,
            "external_tool_response": 0,
            "memory_hint_buffered": 0,
            "memory_injected": 0,
            "tool_timeout_events": 0,
        }
        self._logger = get_logger("swea-ext-bridge", emoji="🧩")

    def on_init(self, *, agent):
        self._agent_name = getattr(agent, "name", "unknown")
        self._run_id = os.getenv("SWE_AGENT_EXT_RUN_ID", "").strip()
        self._attempt_id = os.getenv("SWE_AGENT_EXT_ATTEMPT_ID", self._attempt_id).strip() or self._attempt_id
        env_instance_id = os.getenv("SWE_AGENT_EXT_INSTANCE_ID", "").strip()
        if env_instance_id:
            self._instance_id = env_instance_id
            return
        for attr_name in ("_problem_statement", "problem_statement"):
            try:
                ps = getattr(agent, attr_name, None)
                inst = getattr(ps, "id", None)
                if isinstance(inst, str) and inst.strip():
                    self._instance_id = inst.strip()
                    return
            except Exception:
                continue
        self._instance_id = self._agent_name

    @staticmethod
    def _read_bool_env(name: str, *, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() not in {"0", "false", "no", "off"}

    @staticmethod
    def _read_int_env(name: str, *, default: int, minimum: int) -> int:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            return max(minimum, int(raw.strip()))
        except Exception:
            return default

    @staticmethod
    def _read_float_env(name: str, *, default: float) -> float:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            return float(raw.strip())
        except Exception:
            return default

    @staticmethod
    def _try_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except Exception:
            return None

    def _extract_json_payload(self, text: str) -> dict[str, Any] | None:
        content = text.strip()
        if not content:
            return None
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass

        left = content.find("{")
        right = content.rfind("}")
        if left < 0 or right <= left:
            return None
        try:
            parsed = json.loads(content[left : right + 1])
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _hint_from_item(self, item: Any) -> str | None:
        if isinstance(item, str):
            text = item.strip()
            return text[:280] if text else None
        if not isinstance(item, dict):
            return None

        for key in ("recommendation", "repair_action", "next_step_fix", "recommend", "summary"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:280]

        if item.get("pattern") == "failure_followed_by_repair":
            val = item.get("repair_action")
            if isinstance(val, str) and val.strip():
                return val.strip()[:280]
        return None

    @staticmethod
    def _memory_id_from_item(item: Any) -> str | None:
        if not isinstance(item, dict):
            return None
        for key in ("summary_id", "card_id", "experience_id", "belief_id", "pattern_id", "rule_id", "action_id"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return None

    def _resolve_confidence(self, payload: dict[str, Any], items: list[Any]) -> float:
        candidates: list[float] = []
        top = self._try_float(payload.get("confidence"))
        if top is not None:
            candidates.append(top)
        for item in items:
            if isinstance(item, dict):
                v = self._try_float(item.get("confidence"))
                if v is not None:
                    candidates.append(v)
        return max(candidates) if candidates else 0.0

    def _collect_hint_items(self, payload: dict[str, Any]) -> list[Any]:
        event_name = payload.get("event_handled")
        items: list[Any] = []
        if event_name == "plan_generated":
            hints = payload.get("planning_tips", [])
            if isinstance(hints, list):
                items.extend(hints)
        elif event_name == "action_error":
            hints = payload.get("repair_suggestions", [])
            if isinstance(hints, list):
                items.extend(hints)
            next_fix = payload.get("next_step_fix")
            if isinstance(next_fix, str) and next_fix.strip():
                items.append(next_fix.strip())
        recs = payload.get("recommendations")
        if isinstance(recs, list):
            items.extend(recs)
        return items

    @staticmethod
    def _hint_family_from_item(item: Any) -> str | None:
        if not isinstance(item, dict):
            return None
        for key in ("family_id",):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        rtype = str(item.get("type", "")).strip().lower()
        if rtype:
            if rtype == "failure_card_v2":
                err = item.get("error_signature") if isinstance(item.get("error_signature"), dict) else {}
                err_type = str(err.get("error_type", "")).strip().lower()
                rec = str(item.get("recommendation", "")).strip().lower()[:80]
                family = f"failure_card:{err_type}:{rec}"
                return family if family.strip(":") else None
            if rtype == "belief_tip":
                belief_type = str(item.get("belief_type", "")).strip().lower()
                rec = str(item.get("recommendation", "")).strip().lower()[:80]
                family = f"belief_tip:{belief_type}:{rec}"
                return family if family.strip(":") else None
            rec = str(
                item.get("recommendation")
                or item.get("repair_action")
                or item.get("summary")
                or ""
            ).strip().lower()[:80]
            family = f"{rtype}:{rec}"
            return family if family.strip(":") else None
        return None

    @staticmethod
    def _hint_selection_score(item: Any, *, batch_confidence: float) -> float:
        if not isinstance(item, dict):
            return batch_confidence
        selection = ExternalToolBridgeHook._try_float(item.get("selection_score")) or 0.0
        helpfulness = ExternalToolBridgeHook._try_float(item.get("helpfulness_score")) or 0.0
        novelty = ExternalToolBridgeHook._try_float(item.get("novelty_score")) or 0.0
        item_conf = ExternalToolBridgeHook._try_float(item.get("confidence")) or 0.0
        return max(selection, 0.45 * helpfulness + 0.25 * novelty + 0.20 * item_conf + 0.10 * batch_confidence)

    def _buffer_memory_hints(self, payload: dict[str, Any]) -> int:
        items = self._collect_hint_items(payload)
        if not items:
            return 0

        batch_confidence = self._resolve_confidence(payload, items)
        if batch_confidence < self.min_confidence:
            return 0

        added = 0
        for item in items:
            item_conf = None
            if isinstance(item, dict):
                item_conf = self._try_float(item.get("confidence"))
            if item_conf is not None and item_conf < self.min_item_confidence:
                continue
            hint = self._hint_from_item(item)
            if not hint:
                continue
            family_id = self._hint_family_from_item(item)
            if family_id.startswith("workflow_step:") and self._step_index > 3:
                continue
            key = hint.lower()
            if key in self._recent_hint_fingerprints:
                continue
            self._pending_memory_hints.append(
                {
                    "hint": hint,
                    "memory_id": self._memory_id_from_item(item),
                    "family_id": family_id,
                    "source_event": payload.get("event_handled"),
                    "source_event_id": payload.get("trace_id"),
                    "trace_id": payload.get("trace_id"),
                    "item_confidence": item_conf,
                    "batch_confidence": self._try_float(payload.get("confidence")),
                    "selection_score": self._hint_selection_score(item, batch_confidence=batch_confidence),
                    "type": item.get("type") if isinstance(item, dict) else None,
                    "normalized_pattern_type": item.get("normalized_pattern_type") if isinstance(item, dict) else None,
                }
            )
            self._recent_hint_fingerprints.add(key)
            added += 1

        soft_cap = self.max_hints if self.max_hints > 0 else 25
        max_pending = max(20, soft_cap * 8)
        while len(self._pending_memory_hints) > max_pending:
            self._pending_memory_hints.popleft()

        if len(self._recent_hint_fingerprints) > 2000:
            # Keep dedup state bounded in long runs.
            self._recent_hint_fingerprints = {
                str(h.get("hint", "")).lower()
                for h in list(self._pending_memory_hints)
                if str(h.get("hint", "")).strip()
            }
        if added > 0:
            self._metric_inc("memory_hint_buffered", added)
        return added

    def _append_tool_response_summary(self, *, tool_name: str, payload: dict[str, Any]) -> None:
        event_name = str(payload.get("event_handled", "unknown"))
        retrieval_debug = payload.get("retrieval_debug")
        summary: dict[str, Any] = {
            "version": "v1",
            "event": "external_tool_response",
            "agent": self._agent_name,
            "instance_id": self._instance_id,
            "attempt_id": self._attempt_id,
            "source_tool": tool_name,
            "source_event": event_name,
            "trace_id": payload.get("trace_id"),
            "confidence": payload.get("confidence"),
            "step_index": self._step_index,
        }
        if isinstance(retrieval_debug, dict):
            summary["retrieval_debug"] = {
                "query_type": retrieval_debug.get("query_type"),
                "embedding_view": retrieval_debug.get("embedding_view"),
                "candidate_count_before_filter": retrieval_debug.get("candidate_count_before_filter", 0),
                "candidate_count_after_filter": retrieval_debug.get("candidate_count_after_filter", 0),
                "candidate_task_count": retrieval_debug.get("candidate_task_count", 0),
                "selected_subgraph_count": retrieval_debug.get("selected_subgraph_count", 0),
                "recommendation_count": retrieval_debug.get("recommendation_count", 0),
                "injection_candidate_count": retrieval_debug.get("injection_candidate_count", 0),
                "injection_selected_count": retrieval_debug.get("injection_selected_count", 0),
            }

        if event_name == "plan_generated":
            tips = payload.get("planning_tips", [])
            summary["suggestion_count"] = len(tips) if isinstance(tips, list) else 0
        elif event_name == "action_error":
            recs = payload.get("repair_suggestions", [])
            summary["suggestion_count"] = len(recs) if isinstance(recs, list) else 0
            summary["error_type"] = payload.get("error_type")
        elif event_name == "run_done":
            summary["task_id"] = payload.get("task_id")
            summary["cleared"] = bool(payload.get("cleared", False))
        self._metric_inc("external_tool_response", 1)
        append_json_log("HOOK", summary)

    def _record_trigger(self, trigger: str, detail: str = "") -> None:
        marker = trigger if not detail else f"{trigger}:{detail}"
        self._recent_triggers.append(marker)
        if trigger == "over_exploration":
            self._closure_active = True
        append_json_log(
            "HOOK",
            {
                "version": "v1",
                "event": "proactive_trigger",
                "agent": self._agent_name,
                "instance_id": self._instance_id,
                "attempt_id": self._attempt_id,
                "trigger": trigger,
                "detail": detail,
                "step_index": self._step_index,
            },
        )

    def _has_recent_trigger(self, prefix: str) -> bool:
        return any(str(marker).startswith(prefix) for marker in self._recent_triggers)

    def _runtime_guard_payload(self) -> dict[str, Any]:
        blocked_families: list[str] = []
        if self._closure_active:
            blocked_families.extend(["workflow_step", "planning_loop"])
        return {
            "closure_active": self._closure_active,
            "ad_hoc_script_count": len(self._ad_hoc_script_names),
            "recent_triggers": list(self._recent_triggers)[-8:],
            "blocked_families": blocked_families,
        }

    def _enqueue_system_hint(
        self,
        *,
        hint: str,
        family_id: str,
        normalized_pattern_type: str,
        selection_score: float,
    ) -> None:
        key = hint.strip().lower()
        if not key or key in self._recent_hint_fingerprints:
            return
        self._pending_memory_hints.append(
            {
                "hint": hint.strip(),
                "memory_id": None,
                "family_id": family_id,
                "source_event": "hook_generated",
                "source_event_id": None,
                "trace_id": None,
                "item_confidence": 0.9,
                "batch_confidence": 0.9,
                "selection_score": selection_score,
                "type": "abstract_pattern",
                "normalized_pattern_type": normalized_pattern_type,
            }
        )
        self._recent_hint_fingerprints.add(key)

    def _build_trace_id(self, event_name: str) -> str:
        self._event_seq += 1
        run_id = str(self._run_id or "norun")
        instance_id = self._instance_id or self._agent_name or "unknown"
        return f"{run_id}:{instance_id}:{self._step_index}:{event_name}:{self._event_seq}"

    def _build_event_payload(self, event_name: str, **extra: Any) -> dict[str, Any]:
        payload = {
            "version": "v1",
            "event": event_name,
            "event_type": event_name,
            "source": "bridge_hook",
            "agent": self._agent_name,
            "instance_id": self._instance_id,
            "run_id": self._run_id,
            "attempt_id": self._attempt_id,
            "step_index": self._step_index,
            "timestamp": time.time(),
        }
        payload.update(extra)
        return payload

    def _metric_inc(self, key: str, amount: int = 1) -> None:
        self._metrics[key] = self._metrics.get(key, 0) + max(0, amount)

    @staticmethod
    def _is_error_like_observation(text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        patterns = (
            "error",
            "exception",
            "traceback",
            "assert",
            "failed",
            "no such file",
            "timed out",
            "non-zero",
        )
        return any(p in lowered for p in patterns)

    def _is_circuit_open(self, tool_name: str) -> bool:
        now = time.monotonic()
        until = float(self._tool_circuit_open_until.get(tool_name, 0.0))
        if until <= 0:
            return False
        if now >= until:
            self._tool_circuit_open_until.pop(tool_name, None)
            self._tool_failure_streak[tool_name] = 0
            return False
        return True

    def _record_tool_failure(self, tool_name: str) -> None:
        streak = self._tool_failure_streak.get(tool_name, 0) + 1
        self._tool_failure_streak[tool_name] = streak
        if streak >= self.tool_circuit_threshold:
            self._tool_circuit_open_until[tool_name] = time.monotonic() + max(1.0, self.tool_circuit_cooldown_sec)

    def _record_tool_success(self, tool_name: str) -> None:
        self._tool_failure_streak[tool_name] = 0
        self._tool_circuit_open_until.pop(tool_name, None)

    def _emit_tool_result(self, *, tool_name: str, payload: dict[str, Any], status: str, detail: str = "") -> None:
        append_json_log(
            "HOOK",
            {
                "version": "v1",
                "event": "external_tool_result",
                "agent": self._agent_name,
                "instance_id": self._instance_id,
                "attempt_id": self._attempt_id,
                "source_tool": tool_name,
                "source_event": payload.get("event"),
                "trace_id": payload.get("trace_id"),
                "step_index": self._step_index,
                "status": status,
                "detail": detail,
                "failure_streak": self._tool_failure_streak.get(tool_name, 0),
            },
        )

    def _default_timeout_for_tool(self, tool_name: str) -> float:
        if tool_name == "tool_a":
            return self.tool_a_timeout_sec
        if tool_name == "tool_b":
            return self.tool_b_timeout_sec
        return self.timeout_sec

    def _effective_timeout_for_tool(self, tool_name: str) -> float:
        timeout = self._adaptive_timeout_by_tool.get(tool_name)
        if timeout is not None:
            return timeout
        return self._default_timeout_for_tool(tool_name)

    def _handle_parsed_tool_payload(self, *, tool_name: str, parsed: dict[str, Any]) -> None:
        event_name = str(parsed.get("event_handled", "")).strip().lower()
        if event_name:
            self._last_success_payload_by_event[event_name] = parsed

        self._append_tool_response_summary(tool_name=tool_name, payload=parsed)
        if not self.inject_enabled:
            return
        buffered = self._buffer_memory_hints(parsed)
        if buffered <= 0:
            return
        self._logger.info(
            "Buffered %d memory hints from %s (pending=%d, min_conf=%.2f)",
            buffered,
            tool_name,
            len(self._pending_memory_hints),
            self.min_confidence,
        )
        append_json_log(
            "HOOK",
            {
                "version": "v1",
                "event": "memory_hint_buffered",
                "agent": self._agent_name,
                "instance_id": self._instance_id,
                "attempt_id": self._attempt_id,
                "source_event": parsed.get("event_handled"),
                "source_tool": tool_name,
                "buffered_count": buffered,
                "pending_count": len(self._pending_memory_hints),
                "confidence": parsed.get("confidence"),
                "buffered_memory_ids": [
                    str(item.get("memory_id"))
                    for item in list(self._pending_memory_hints)[-buffered:]
                    if str(item.get("memory_id", "")).strip()
                ],
                "buffered_family_ids": [
                    str(item.get("family_id"))
                    for item in list(self._pending_memory_hints)[-buffered:]
                    if str(item.get("family_id", "")).strip()
                ],
            },
        )

    def _emit_timeout_event(self, *, tool_name: str, payload: dict[str, Any], timeout: float, attempt: int) -> None:
        self._metric_inc("tool_timeout_events", 1)
        append_json_log(
            "HOOK",
            {
                "version": "v1",
                "event": "external_tool_timeout",
                "agent": self._agent_name,
                "instance_id": self._instance_id,
                "attempt_id": self._attempt_id,
                "source_tool": tool_name,
                "source_event": payload.get("event"),
                "trace_id": payload.get("trace_id"),
                "step_index": self._step_index,
                "attempt": attempt,
                "timeout_sec": timeout,
            },
        )

    def _try_stale_fallback(self, *, tool_name: str, payload: dict[str, Any]) -> bool:
        if not self.enable_stale_fallback:
            return False
        source_event = str(payload.get("event", "")).strip().lower()
        if not source_event:
            return False
        stale = self._last_success_payload_by_event.get(source_event)
        if not stale:
            return False
        stale_payload = dict(stale)
        stale_payload["stale_fallback"] = True
        self._logger.warning(
            "External %s fallback to stale response for event=%s trace=%s",
            tool_name,
            source_event,
            payload.get("trace_id"),
        )
        self._handle_parsed_tool_payload(tool_name=f"{tool_name}_stale", parsed=stale_payload)
        append_json_log(
            "HOOK",
            {
                "version": "v1",
                "event": "external_tool_stale_fallback",
                "agent": self._agent_name,
                "instance_id": self._instance_id,
                "attempt_id": self._attempt_id,
                "source_tool": tool_name,
                "source_event": source_event,
                "trace_id": payload.get("trace_id"),
                "step_index": self._step_index,
            },
        )
        self._emit_tool_result(tool_name=tool_name, payload=payload, status="stale_fallback")
        return True

    def _scan_proactive_triggers(self, action_text: str) -> None:
        action_l = action_text.lower()
        if re.search(r"\b(pytest|unittest|tox|nox|nose|python\s+-m\s+pytest|make\s+test)\b", action_l):
            self._record_trigger("before_test_run")
        if re.search(r"\b(submit|submission|create[_\s-]?pr|open[_\s-]?pr|final answer|final patch)\b", action_l):
            self._record_trigger("before_submit")

        for m in re.finditer(
            r"\b[\w.\-]+\.(?:py|js|ts|java|go|rs|cpp|h|md|txt|json|yaml|yml|toml|ini|cfg|sh)\b",
            action_text,
            flags=re.IGNORECASE,
        ):
            fn = m.group(0).lower()
            if fn not in self._seen_files:
                self._seen_files.add(fn)
                self._record_trigger("first_file_access", detail=fn)
            if re.match(r"(?:test_|reproduce_|debug_).+\.py$", fn):
                self._ad_hoc_script_names.add(fn)
                if len(self._ad_hoc_script_names) >= 2:
                    self._record_trigger("over_exploration", detail=str(len(self._ad_hoc_script_names)))
                    self._enqueue_system_hint(
                        hint="Stop expanding ad-hoc scripts. Validate the minimal fix against the target failing path, then either submit or terminate.",
                        family_id="closure_signal:over_exploration_after_key_signal",
                        normalized_pattern_type="closure_signal",
                        selection_score=0.98,
                    )

    @staticmethod
    def _extract_ad_hoc_script_names(action_text: str) -> list[str]:
        names: list[str] = []
        for m in re.finditer(r"\b(?:test_|reproduce_|debug_)[\w.\-]+\.py\b", action_text, flags=re.IGNORECASE):
            names.append(m.group(0).lower())
        return names

    def _is_new_ad_hoc_script_creation(self, action_text: str) -> bool:
        if not self._closure_active:
            return False
        lowered = action_text.lower()
        if not any(tok in lowered for tok in ("cat ", "tee ", "touch ", "printf ", "echo ", "apply_patch")):
            return False
        for name in self._extract_ad_hoc_script_names(action_text):
            if name not in self._ad_hoc_script_names:
                return True
        return False

    def _soft_block_ad_hoc_script_creation(self, step: StepOutput) -> None:
        original_action = step.action
        step.action = (
            "printf '%s\\n' "
            "'Runtime guard blocked new ad-hoc script creation after closure. "
            "Validate the current minimal fix or stop.'"
        )
        append_json_log(
            "HOOK",
            {
                "version": "v1",
                "event": "runtime_guard_block",
                "agent": self._agent_name,
                "instance_id": self._instance_id,
                "attempt_id": self._attempt_id,
                "step_index": self._step_index + 1,
                "block_type": "new_ad_hoc_script_after_closure",
                "original_action": original_action,
                "replacement_action": step.action,
                "runtime_guard": self._runtime_guard_payload(),
            },
        )

    def _run_cmd(self, *, cmd: str | None, tool_name: str, payload: dict[str, Any]) -> None:
        if not cmd:
            return
        if self._is_circuit_open(tool_name):
            self._emit_tool_result(
                tool_name=tool_name,
                payload=payload,
                status="circuit_open",
                detail=f"cooldown_sec={self.tool_circuit_cooldown_sec}",
            )
            self._try_stale_fallback(tool_name=tool_name, payload=payload)
            return
        env = os.environ.copy()
        env["SWE_AGENT_EXT_EVENT_JSON"] = json.dumps(payload, ensure_ascii=False)
        attempts = max(1, self.max_retries + 1)
        success = False
        last_failure = "unknown"
        timeout_base = self._effective_timeout_for_tool(tool_name)

        for attempt in range(1, attempts + 1):
            timeout_for_attempt = timeout_base if attempt == 1 else max(timeout_base, self.retry_timeout_sec)
            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    check=False,
                    text=True,
                    capture_output=True,
                    timeout=timeout_for_attempt,
                    env=env,
                )
            except subprocess.TimeoutExpired:
                last_failure = f"timeout@{timeout_for_attempt:.2f}s"
                self._logger.warning(
                    "External %s timed out after %.2fs (attempt %d/%d)",
                    tool_name,
                    timeout_for_attempt,
                    attempt,
                    attempts,
                )
                self._emit_timeout_event(
                    tool_name=tool_name,
                    payload=payload,
                    timeout=timeout_for_attempt,
                    attempt=attempt,
                )
                self._record_tool_failure(tool_name)
                if self.enable_adaptive_timeout and timeout_for_attempt < self.retry_timeout_sec:
                    self._adaptive_timeout_by_tool[tool_name] = self.retry_timeout_sec
                continue
            except Exception as e:
                last_failure = f"exception:{e}"
                self._logger.warning("External %s failed: %s (attempt %d/%d)", tool_name, e, attempt, attempts)
                self._record_tool_failure(tool_name)
                continue

            parsed_ok = False
            if result.stdout.strip():
                self._logger.info("[%s stdout] %s", tool_name, result.stdout.strip())
                parsed = self._extract_json_payload(result.stdout)
                if parsed:
                    self._handle_parsed_tool_payload(tool_name=tool_name, parsed=parsed)
                    parsed_ok = True
            if result.stderr.strip():
                self._logger.warning("[%s stderr] %s", tool_name, result.stderr.strip())

            if result.returncode == 0:
                success = True
                self._record_tool_success(tool_name)
                self._emit_tool_result(tool_name=tool_name, payload=payload, status="ok")
                break

            last_failure = f"exit_code:{result.returncode}"
            self._logger.warning(
                "External %s exit code=%d (attempt %d/%d)",
                tool_name,
                result.returncode,
                attempt,
                attempts,
            )
            self._record_tool_failure(tool_name)
            if parsed_ok:
                # Accept parsed response even when helper exits non-zero.
                success = True
                self._record_tool_success(tool_name)
                self._emit_tool_result(
                    tool_name=tool_name,
                    payload=payload,
                    status="ok_with_nonzero_exit",
                    detail=f"exit_code={result.returncode}",
                )
                break

        if success:
            return
        if self._try_stale_fallback(tool_name=tool_name, payload=payload):
            return
        self._emit_tool_result(tool_name=tool_name, payload=payload, status="failed", detail=last_failure)
        self._logger.warning("External %s failed after %d attempts (%s)", tool_name, attempts, last_failure)

    def _select_hints_for_injection(self) -> list[dict[str, Any]]:
        if not self._pending_memory_hints:
            return []

        char_budget = max(self.max_hint_chars, self.hint_char_budget)
        selected: list[dict[str, Any]] = []
        kept: list[dict[str, Any]] = []
        used = 0
        family_selected: set[str] = set()
        bucket_selected: dict[str, int] = {}

        ordered_items = sorted(
            list(self._pending_memory_hints),
            key=lambda row: (
                self._hint_bucket_priority(row),
                float(row.get("selection_score", 0.0) or 0.0),
                float(row.get("item_confidence") or row.get("batch_confidence") or 0.0),
            ),
            reverse=True,
        )

        for item in ordered_items:
            hint = str(item.get("hint", "")).strip()
            if not hint:
                continue

            if self.require_trigger_for_injection and not self._recent_triggers:
                confidence = self._try_float(item.get("item_confidence"))
                if confidence is None:
                    confidence = self._try_float(item.get("batch_confidence"))
                if confidence is None or confidence < max(self.min_confidence, 0.7):
                    kept.append(item)
                    continue

            family_id = str(item.get("family_id", "")).strip()
            bucket = self._hint_bucket(item)
            if bucket == "workflow" and (self._step_index > 3 or self._has_recent_trigger("over_exploration")):
                continue
            if family_id:
                if family_id in family_selected:
                    kept.append(item)
                    continue
                if self.max_hints_per_family_per_attempt > 0:
                    injected_count = self._hint_family_injected_count.get(family_id, 0)
                    if injected_count >= self.max_hints_per_family_per_attempt:
                        continue
                if self.family_cooldown_steps > 0:
                    last_step = self._hint_family_last_injected_step.get(family_id)
                    if last_step is not None and (self._step_index - last_step) < self.family_cooldown_steps:
                        kept.append(item)
                        continue

            bucket_limit = 1 if bucket in {"closure", "repair", "validation", "workflow"} else 2
            if bucket_selected.get(bucket, 0) >= bucket_limit:
                kept.append(item)
                continue

            hint_cost = len(hint) + 8
            soft_cap_reached = self.max_hints > 0 and len(selected) >= self.max_hints
            budget_reached = selected and (used + hint_cost > char_budget)
            if soft_cap_reached or budget_reached:
                kept.append(item)
                continue

            selected.append(item)
            if family_id:
                family_selected.add(family_id)
            bucket_selected[bucket] = bucket_selected.get(bucket, 0) + 1
            used += hint_cost
            if used >= char_budget:
                continue

        selected_ids = {id(item) for item in selected}
        self._pending_memory_hints = deque([item for item in kept if id(item) not in selected_ids])
        return selected

    @staticmethod
    def _hint_bucket(item: dict[str, Any]) -> str:
        rtype = str(item.get("type", "")).strip().lower()
        family_id = str(item.get("family_id", "")).strip().lower()
        pattern = str(item.get("normalized_pattern_type", "")).strip().lower()
        if pattern == "closure_signal" or family_id.startswith("closure_signal:"):
            return "closure"
        if rtype in {"repair_pattern_v2", "failure_card_v2"} or pattern in {"negative_strategy", "patch_risk"}:
            return "repair"
        if pattern in {"validation_gap", "validation_guard"}:
            return "validation"
        if rtype == "belief_tip" or family_id.startswith("belief_tip:") or family_id.startswith("workflow_step:") or pattern == "planning_loop":
            return "workflow"
        return "general"

    @classmethod
    def _hint_bucket_priority(cls, item: dict[str, Any]) -> int:
        bucket = cls._hint_bucket(item)
        order = {
            "closure": 5,
            "repair": 4,
            "validation": 3,
            "general": 2,
            "workflow": 1,
        }
        return order.get(bucket, 0)

    def _register_interventions(self, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for idx, item in enumerate(selected, start=1):
            trace_id = str(item.get("trace_id", "") or "")
            intervention_id = f"intv:{trace_id or 'missing'}:{self._step_index}:{idx}"
            state = {
                "intervention_id": intervention_id,
                "trace_id": trace_id or None,
                "memory_id": item.get("memory_id"),
                "created_step": self._step_index,
                "remaining_steps": self.intervention_window_steps,
                "observed_events": [],
                "success_events": 0,
                "error_events": 0,
                "closed": False,
            }
            self._active_interventions.append(state)
            rows.append(
                {
                    "intervention_id": intervention_id,
                    "trace_id": trace_id or None,
                    "memory_id": item.get("memory_id"),
                }
            )
        return rows

    def _advance_interventions(self, *, event: str, detail: str = "") -> None:
        if not self._active_interventions:
            return
        to_close: list[dict[str, Any]] = []
        for row in self._active_interventions:
            if row.get("closed"):
                continue
            row["observed_events"].append(event if not detail else f"{event}:{detail}")
            if event == "action_error":
                row["error_events"] = int(row.get("error_events", 0)) + 1
            elif event == "action_success":
                row["success_events"] = int(row.get("success_events", 0)) + 1
            row["remaining_steps"] = int(row.get("remaining_steps", 0)) - 1
            if int(row["remaining_steps"]) <= 0:
                to_close.append(row)

        if not to_close:
            return

        survivors: list[dict[str, Any]] = []
        for row in self._active_interventions:
            if row in to_close:
                row["closed"] = True
                append_json_log(
                    "HOOK",
                    {
                        "version": "v1",
                        "event": "memory_intervention_feedback",
                        "agent": self._agent_name,
                        "instance_id": self._instance_id,
                        "attempt_id": self._attempt_id,
                        "intervention_id": row.get("intervention_id"),
                        "trace_id": row.get("trace_id"),
                        "memory_id": row.get("memory_id"),
                        "created_step": row.get("created_step"),
                        "closed_step": self._step_index,
                        "success_events": row.get("success_events", 0),
                        "error_events": row.get("error_events", 0),
                        "observed_events": row.get("observed_events", [])[-20:],
                        "local_effective": int(row.get("success_events", 0)) > 0 and int(row.get("error_events", 0)) == 0,
                        "evaluation_effective": None,
                        "feedback_stage": "local",
                        "effective": int(row.get("success_events", 0)) > 0 and int(row.get("error_events", 0)) == 0,
                    },
                )
            else:
                survivors.append(row)
        self._active_interventions = survivors

    def _emit_gate_evaluation(self) -> None:
        plan_generated = max(1, self._metrics.get("plan_generated", 0))
        external_resp = self._metrics.get("external_tool_response", 0)
        hint_buffered = self._metrics.get("memory_hint_buffered", 0)
        error_like = self._metrics.get("error_like_observation", 0)
        action_error = self._metrics.get("action_error_events", 0)

        external_ratio = external_resp / plan_generated
        buffer_ratio = (hint_buffered / external_resp) if external_resp > 0 else 0.0
        action_error_coverage = (action_error / error_like) if error_like > 0 else 1.0
        gates = {
            "external_ratio": external_ratio >= self.gate_min_external_ratio,
            "buffer_ratio": buffer_ratio >= self.gate_min_buffer_ratio,
            "action_error_coverage": action_error_coverage >= self.gate_min_action_error_coverage,
        }
        passed = all(gates.values())
        payload = {
            "version": "v1",
            "event": "memory_gate_evaluation",
            "agent": self._agent_name,
            "instance_id": self._instance_id,
            "attempt_id": self._attempt_id,
            "metrics": dict(self._metrics),
            "ratios": {
                "external_tool_response_over_plan_generated": round(external_ratio, 6),
                "memory_hint_buffered_over_external_tool_response": round(buffer_ratio, 6),
                "action_error_over_error_like_observation": round(action_error_coverage, 6),
            },
            "thresholds": {
                "external_ratio": self.gate_min_external_ratio,
                "buffer_ratio": self.gate_min_buffer_ratio,
                "action_error_coverage": self.gate_min_action_error_coverage,
            },
            "gates": gates,
            "passed": passed,
            "hard_fail_enabled": self.gate_hard_fail,
        }
        append_json_log("HOOK", payload)
        if self.gate_hard_fail and not passed:
            append_json_log(
                "HOOK",
                {
                    "version": "v1",
                    "event": "memory_gate_hard_fail",
                    "agent": self._agent_name,
                    "instance_id": self._instance_id,
                    "attempt_id": self._attempt_id,
                    "reason": "threshold_not_met",
                    "gates": gates,
                },
            )

    def on_model_query(self, *, messages: list[dict[str, str]], agent: str):
        if not self.inject_enabled or not self._pending_memory_hints:
            return

        selected = self._select_hints_for_injection()
        if not selected:
            return

        lines = [
            "[AgentMem Hints]",
            "Use these hints only when relevant to the current repository state.",
        ]
        for idx, item in enumerate(selected, start=1):
            hint = str(item.get("hint", "")).strip()
            if not hint:
                continue
            lines.append(f"{idx}. {hint}")
        content = "\n".join(lines)
        if len(content) > self.max_hint_chars:
            content = content[: self.max_hint_chars - 3].rstrip() + "..."

        messages.append({"role": "user", "content": content})

        self._logger.info("Injected memory hints: count=%d agent=%s", len(selected), agent)
        trigger_markers = list(self._recent_triggers)
        self._recent_triggers.clear()
        selected_memory_ids = [str(item.get("memory_id")) for item in selected if item.get("memory_id")]
        selected_trace_ids = [str(item.get("trace_id")) for item in selected if item.get("trace_id")]
        selected_family_ids = [str(item.get("family_id")) for item in selected if str(item.get("family_id", "")).strip()]
        trace_id_missing = any(not str(item.get("trace_id", "")).strip() for item in selected)
        selected_interventions = self._register_interventions(selected)
        hints_preview = [str(item.get("hint", ""))[:120] for item in selected if str(item.get("hint", "")).strip()]
        for family_id in selected_family_ids:
            self._hint_family_last_injected_step[family_id] = self._step_index
            self._hint_family_injected_count[family_id] = self._hint_family_injected_count.get(family_id, 0) + 1
        self._metric_inc("memory_injected", len(selected))
        append_json_log(
            "HOOK",
            {
                "version": "v1",
                "event": "memory_injected",
                "agent": self._agent_name,
                "instance_id": self._instance_id,
                "attempt_id": self._attempt_id,
                "target_agent": agent,
                "hint_count": len(selected),
                "selected_memory_ids": selected_memory_ids,
                "selected_trace_ids": selected_trace_ids,
                "selected_family_ids": selected_family_ids,
                "selected_interventions": selected_interventions,
                "trace_id_missing": trace_id_missing,
                "hints_preview": hints_preview,
                "step_index": self._step_index,
                "max_hints": self.max_hints,
                "hint_char_budget": self.hint_char_budget,
                "max_hint_chars": self.max_hint_chars,
                "family_cooldown_steps": self.family_cooldown_steps,
                "max_hints_per_family_per_attempt": self.max_hints_per_family_per_attempt,
                "min_confidence": self.min_confidence,
                "triggers": trigger_markers,
            },
        )

    def on_actions_generated(self, *, step: StepOutput):
        if self._is_new_ad_hoc_script_creation(step.action):
            self._soft_block_ad_hoc_script_creation(step)
        self._step_index += 1
        self._metric_inc("plan_generated", 1)
        self._scan_proactive_triggers(step.action)
        trace_id = self._build_trace_id("plan_generated")
        payload = self._build_event_payload(
            "plan_generated",
            trace_id=trace_id,
            thought=step.thought,
            action=step.action,
            runtime_guard=self._runtime_guard_payload(),
        )
        self._run_cmd(
            cmd=self.tool_a_cmd,
            tool_name="tool_a",
            payload=payload,
        )

    def on_action_error(self, *, step: StepOutput, error_type: str, error_message: str):
        self._consecutive_failures += 1
        self._metric_inc("action_error_events", 1)
        self._advance_interventions(event="action_error", detail=error_type or "unknown")
        if self._consecutive_failures == 1:
            self._record_trigger("first_failure", detail=error_type or "unknown")
        if self._consecutive_failures >= 2:
            self._record_trigger("consecutive_failures", detail=str(self._consecutive_failures))
        trace_id = self._build_trace_id("action_error")
        payload = self._build_event_payload(
            "action_error",
            trace_id=trace_id,
            error_type=error_type,
            error_message=error_message,
            thought=step.thought,
            action=step.action,
        )
        self._run_cmd(
            cmd=self.tool_b_cmd,
            tool_name="tool_b",
            payload=payload,
        )

    def on_action_executed(self, *, step: StepOutput):
        observation = str(step.observation)
        if self._is_error_like_observation(observation):
            self._metric_inc("error_like_observation", 1)
        # Reset failure streak on normal command observations.
        if "simulated command error" not in observation.lower():
            if self._consecutive_failures > 0:
                self._record_trigger("after_success", detail=str(self._consecutive_failures))
            self._consecutive_failures = 0
        self._advance_interventions(event="action_success")

    def on_run_done(self, *, trajectory: Trajectory, info: AgentInfo):
        trace_id = self._build_trace_id("run_done")
        payload = self._build_event_payload(
            "run_done",
            trace_id=trace_id,
            trajectory_steps=len(trajectory),
            exit_status=info.get("exit_status"),
            has_submission=bool(info.get("submission")),
        )
        self._run_cmd(
            cmd=self.tool_b_cmd or self.tool_a_cmd,
            tool_name="tool_b",
            payload=payload,
        )
        # Close all still-open interventions at run end.
        for row in self._active_interventions:
            row["remaining_steps"] = 0
        self._advance_interventions(event="run_done")
        self._emit_gate_evaluation()
        append_json_log(
            "HOOK",
            {
                "version": "v1",
                "event": "run_done",
                "agent": self._agent_name,
                "instance_id": self._instance_id,
                "attempt_id": self._attempt_id,
                "trajectory_steps": len(trajectory),
                "exit_status": info.get("exit_status"),
                "has_submission": bool(info.get("submission")),
            },
        )
