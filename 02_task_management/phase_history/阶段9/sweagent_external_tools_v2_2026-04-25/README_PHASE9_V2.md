# 阶段9-v2 升级框架（2026-04-25）

本目录是 `PDDL_work_mem/source_code/sweagent_external_tools/` 的**完整副本**，
在副本上落实了 `阶段9_稳定复用与失败屏蔽升级方案_2026-04-25.md` 中提出的 5 个模块。

**原始框架未做任何改动**——回滚=直接弃用本副本。

---

## 1. 与原框架的位置关系

```
PDDL_work_mem/
├── source_code/
│   └── sweagent_external_tools/                        ← 原框架（保持不变）
└── 02_task_management/phase_history/阶段9/
    ├── 阶段9_稳定复用与失败屏蔽升级方案_2026-04-25.md   ← 设计方案
    └── sweagent_external_tools_v2_2026-04-25/         ← ★ 本副本，含 v2 改动
        ├── README_PHASE9_V2.md                         ← 本文件
        ├── agent_mem/...                               ← 已修改
        └── bridge_hook.py                              ← 已修改
```

副本里**只有 4 个文件**真正改动；其余均为原文件的逐字节复制（已剔除 `venv/`、`__pycache__/`、`*.egg-info/`）。

| 已修改文件 | 改动模块 |
|---|---|
| `agent_mem/types.py` | 模块 B：CompilerCardType 新增 `BUG_ANTI_PATTERN` |
| `agent_mem/processing/evaluation_feedback.py` | 模块 A、B：BugInvariantCard schema 扩展 + 新增 `_write_bug_anti_pattern_card` + 共享 helpers + unresolved 分支补 patch_signature_hash |
| `agent_mem/storage/graph_store.py` | 模块 B、E：BugAntiPatternCard 检索加分、`adjust_card` 方法、disabled 状态过滤 |
| `bridge_hook.py` | 模块 C、D、E：PatchConsistencyGate、ReuseExploreScheduler、L3 强制提交、local_effective 反馈接回 |

---

## 2. 全部默认 OFF —— 通过环境变量逐项启用

所有 v2 行为**默认关闭**，框架表现与原版完全一致。开启每个模块走对应环境变量：

| 环境变量 | 默认 | 取值 | 功能 |
|---|---|---|---|
| `AGENT_MEM_BUG_INVARIANT_VERBATIM` | `0` | `0`/`1` | **模块 A**：BugInvariantCard 写入时附带 verbatim_diff + anchors + signature_hash |
| `AGENT_MEM_BUG_ANTI_PATTERN` | `0` | `0`/`1` | **模块 B**：unresolved 时写一张对称的 BugAntiPatternCard，并在 FailureCardV2 的 error_signature 中写入 patch_signature_hash |
| `AGENT_MEM_PATCH_CONSISTENCY_GATE` | `off` | `off` / `advise` / `enforce` | **模块 C**：提交前的 patch 一致性检查。`advise` 仅注入提示，`enforce` 真正改写 / 阻断 |
| `AGENT_MEM_REUSE_EXPLORE` | `off` | `off` / `auto` | **模块 D**：ReuseExploreScheduler。`auto` 按概率切换 VERBATIM_REUSE / EXPLORE_AROUND_INVARIANT / explore_fresh |
| `AGENT_MEM_FORCE_STRATEGY` | `auto` | `auto` / `reuse` / `explore` | **模块 D 消融**：强制策略，便于做单变量实验 |
| `AGENT_MEM_LOCAL_EFFECTIVE_FEEDBACK` | `0` | `0`/`1` | **模块 E**：attempt 收尾时按 success/error 事件比，发出 `v2_card_feedback_request` 事件供下游 adjust_card |
| `AGENT_MEM_L3_FORCE_SUBMIT` | `off` | `off` / `dry_run` / `enforce` | **模块 E**：L3 Hard Stop 升级为强制提交。`dry_run` 仅记录事件，`enforce` 真正改写 step.action |

辅助阈值（沿用原阶段 9）：

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `AGENT_MEM_STEP_GUARDRAIL_NO_EDIT` | 15 | 模块 D 进入 VERBATIM_REUSE 时被收紧到 8 |
| `AGENT_MEM_STEP_STRONG_NO_PATCH` | 25 | L2 阈值 |
| `AGENT_MEM_STEP_HARD_STOP_TOTAL` | 50 | L3 阈值 |

---

## 3. 推荐启用顺序（与方案 §6.1 一致）

```bash
# Batch 1：Schema 扩展（低风险，纯加字段）
export AGENT_MEM_BUG_INVARIANT_VERBATIM=1

# Batch 2：失败侧对称卡（中风险，新增数据但不改决策）
export AGENT_MEM_BUG_ANTI_PATTERN=1

# Batch 3：先 advise，看 gate 是否会误判
export AGENT_MEM_PATCH_CONSISTENCY_GATE=advise
# 跑一两次 attempt，看日志 v2_patch_consistency_gate 事件
# 没问题再升 enforce
export AGENT_MEM_PATCH_CONSISTENCY_GATE=enforce

# Batch 4：开调度器，先用强制 override 做消融
export AGENT_MEM_REUSE_EXPLORE=auto
# 或: export AGENT_MEM_FORCE_STRATEGY=reuse  ← 强制 verbatim 复用
# 或: export AGENT_MEM_FORCE_STRATEGY=explore ← 强制探索

# Batch 5：闭环
export AGENT_MEM_LOCAL_EFFECTIVE_FEEDBACK=1
export AGENT_MEM_L3_FORCE_SUBMIT=dry_run    # 先观察
export AGENT_MEM_L3_FORCE_SUBMIT=enforce    # 确认无误后切 enforce
```

---

## 4. 模块和事件对应表（便于在日志里检索）

每个 v2 行为都会发一个 `event` 字段以 `v2_` 开头的 HOOK 日志：

| 事件名 | 来源模块 | 含义 |
|---|---|---|
| `v2_reuse_explore_decision` | 模块 D | 本 attempt 决策的 strategy / p_reuse |
| `v2_patch_consistency_gate` | 模块 C | gate 判决（allow / rewrite / force_reuse） |
| `v2_action_rewritten` | 模块 C / E | 动作被强制改写（apply invariant 或 force submit） |
| `v2_l3_dry_run` | 模块 E | L3 dry_run 模式下记录"本应强制提交" |
| `v2_card_feedback_request` | 模块 E | attempt 结束时发出的卡片置信度调整请求，供下游消费 |

新增指标（在 `memory_gate_evaluation` 的 metrics 字段里）：
`v2_gate_allow / v2_gate_rewrite / v2_gate_force_reuse / v2_l3_force_submit / v2_l3_force_reuse / v2_card_demoted / v2_card_reinforced`。

---

## 5. 卡片 schema 变化

启用 `AGENT_MEM_BUG_INVARIANT_VERBATIM=1` 后，BugInvariantCard 在 `compiler_cards_v21.json` 中新增字段：

```json
{
  "card_type": "BugInvariantCard",
  "minimal_patch_signature": {
    "files_touched": [...],
    "change_type": "...",
    "key_lines": [...],
    "anchors": [
      {"file": "...", "symbol_kind": "function", "symbol_name": "represent_as",
       "parent": "NDUncertainty", "param_signature": ["self", "other_uncert"]}
    ],
    "key_added_lines": [...],
    "key_added_lines_hash": "sha1:...",
    "verbatim_diff": "<unified diff, ≤8KB>"
  },
  "validation_invariant": {"primary": "...", "commands": [...]},
  "reuse_template": {"mode": "verbatim_first_then_anchor_align", "fallback_anchor": {...}},
  "signature_hash": "sha1:...",
  "metadata": {"schema_version": "1.1", "v2_features_enabled": true, ...}
}
```

启用 `AGENT_MEM_BUG_ANTI_PATTERN=1` 后，新增整张卡：

```json
{
  "card_type": "BugAntiPatternCard",
  "failed_patch_signature": {
    "files_touched": [...], "anchors": [...],
    "key_added_lines": [...], "key_added_lines_hash": "sha1:...",
    "param_signature": [...], "verbatim_diff": "..."
  },
  "failure_reason": {"official_eval_status": "unresolved",
                      "failing_tests": [...], "stderr_excerpt": "..."},
  "support_count": <累计同签名失败次数>,
  "confidence": <随 support_count 上调，cap 0.95>,
  "governance_hardness": "guardrail|strong",
  "signature_hash": "sha1:..."
}
```

`graph_store.adjust_card(card_id, delta_confidence=..., demote_if_below=..., reason=...)` 会在 metadata.v2_confidence_history 中追加调整记录；当置信度跌破 demote_if_below 时设 `v2_state="disabled"`，下次 `query_compiler_cards_v21` 自动过滤。

---

## 6. 验证

副本目录下已通过：
- `python -m py_compile` 全部修改文件
- 整个 pytest 套件 **89 passed, 5 skipped**（与原框架基线一致；`tests/test_phase6_metrics.py` 因路径硬编码无法在新位置运行，与 v2 改动无关）
- 单元级 smoke：anchor 抽取、签名哈希区分（`other_uncert` vs `other_class` 哈希不等）、`adjust_card` 衰减到 disabled 状态

`v2_*` 行为只在对应环境变量被设置时触发；任意环境变量未设置时，框架表现与原版完全一致。

---

## 7. 回滚

直接停止使用本目录即可：
- 切回原框架：使用 `PDDL_work_mem/source_code/sweagent_external_tools/`
- 卡片库已经写过 BugAntiPatternCard：原框架的 `query_compiler_cards_v21` 不识别该 card_type，但不会报错——它会被打分但带不到加成；`v2_state` 字段也会被忽略
- 数据是兼容的——原框架可以读 v2 写出的存储而无需改动

---

## 8. 一句话

> v2 = 原框架 + 4 个文件改动 + 7 个默认 OFF 的环境开关。
> 每开一个开关推进一项目标 A/B 的兑现度，每关一个开关回到原行为。
