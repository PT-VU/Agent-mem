# 回滚文档：Watchdog 计时豁免方案

**变更日期**: 2026-04-29  
**最后更新**: 2026-04-29（追加 v2 修复：process-group kill + BugInvariantCard 文件选取）  
**变更目的**: 让 with_mem 和 nomem 的 agent 推理时间公平对比——bridge_hook 内存查询耗时不计入 20 分钟 budget  
**变更状态**: 已部署（v2 修复已应用）

---

## 变更摘要

| 文件 | 操作 | 行号 |
|------|------|------|
| `sweagent_external_tools_v2_2026-04-25/bridge_hook.py` | 修改 `_run_cmd()` 添加 overhead 计时 | ~984-1039 |
| `sweagent_external_tools_v2_2026-04-25/bin/watchdog.py` | 新增文件；v2 修复：process-group kill | — |
| `run_lite_failedcase_repeat10_with_mem_closed_loop.sh` | 替换 shell `timeout` 为 watchdog | ~31, ~767-774 |
| `agent_mem/processing/evaluation_feedback.py` | 修复 BugInvariantCard 文件选取逻辑 | ~1029-1150 |

---

## 文件 1：bridge_hook.py

### 变更位置
函数 `_run_cmd()`，大约第 984 行起（搜索 `for attempt in range(1, attempts + 1):`）。

### 变更前（原始代码）

```python
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
```

### 变更后（新代码）

```python
        _overhead_file = os.environ.get("SWEAGENT_BRIDGE_OVERHEAD_FILE", "").strip()

        for attempt in range(1, attempts + 1):
            timeout_for_attempt = timeout_base if attempt == 1 else max(timeout_base, self.retry_timeout_sec)
            _t0_overhead = time.monotonic()
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
                if _overhead_file:
                    try:
                        with open(_overhead_file, "a", encoding="utf-8") as _fh:
                            _fh.write(f"{time.monotonic() - _t0_overhead:.6f}\n")
                    except Exception:
                        pass
                if self.enable_adaptive_timeout and timeout_for_attempt < self.retry_timeout_sec:
                    self._adaptive_timeout_by_tool[tool_name] = self.retry_timeout_sec
                continue
            except Exception as e:
                last_failure = f"exception:{e}"
                self._logger.warning("External %s failed: %s (attempt %d/%d)", tool_name, e, attempt, attempts)
                self._record_tool_failure(tool_name)
                if _overhead_file:
                    try:
                        with open(_overhead_file, "a", encoding="utf-8") as _fh:
                            _fh.write(f"{time.monotonic() - _t0_overhead:.6f}\n")
                    except Exception:
                        pass
                continue

            if _overhead_file:
                try:
                    with open(_overhead_file, "a", encoding="utf-8") as _fh:
                        _fh.write(f"{time.monotonic() - _t0_overhead:.6f}\n")
                except Exception:
                    pass

            parsed_ok = False
```

### 回滚操作

将上述"变更后"代码**替换回"变更前"代码**。即：删除 `_overhead_file = ...` 那一行，删除 `_t0_overhead = ...` 那一行，删除三处 `if _overhead_file:` 写文件块（每处约 6 行）。

---

## 文件 2：bin/watchdog.py（新增文件）

### 回滚操作

```bash
rm /home/pt/SWE-bench/PDDL_work_mem/02_task_management/phase_history/阶段9/sweagent_external_tools_v2_2026-04-25/bin/watchdog.py
```

---

## 文件 3：run_lite_failedcase_repeat10_with_mem_closed_loop.sh

### 变更位置 A：顶部变量声明（约第 31 行）

**变更前**（删除这一行）：
```bash
WATCHDOG_PY="${WATCHDOG_PY:-${WS_ROOT}/PDDL_work_mem/sweagent_external_tools_v2/bin/watchdog.py}"
```

### 变更位置 B：timeout 执行块（约第 767-774 行）

**变更前（原始代码）**：
```bash
      if (( INSTANCE_TOTAL_EXEC_TIMEOUT_SEC > 0 )); then
        timeout --foreground -k 45s "${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}s" "${run_cmd[@]}" 2>&1 | tee -a "${run_log}"
      else
        "${run_cmd[@]}" 2>&1 | tee -a "${run_log}"
      fi
```

**变更后（新代码）**：
```bash
      if (( INSTANCE_TOTAL_EXEC_TIMEOUT_SEC > 0 )); then
        # Per-attempt bridge-overhead file: cleared by watchdog at startup.
        _bridge_overhead_file="${run_log%.log}.bridge_overhead.tmp"
        export SWEAGENT_BRIDGE_OVERHEAD_FILE="${_bridge_overhead_file}"
        "${PYTHON_BIN}" "${WATCHDOG_PY}" \
          --budget "${INSTANCE_TOTAL_EXEC_TIMEOUT_SEC}" \
          --overhead-file "${_bridge_overhead_file}" \
          -- "${run_cmd[@]}" 2>&1 | tee -a "${run_log}"
        unset SWEAGENT_BRIDGE_OVERHEAD_FILE
      else
        "${run_cmd[@]}" 2>&1 | tee -a "${run_log}"
      fi
```

### 回滚操作

将"变更后"代码**替换回"变更前"代码**：
- 删除 `WATCHDOG_PY=...` 行
- 把 `if (( INSTANCE_TOTAL_EXEC_TIMEOUT_SEC > 0 ))` 块内的 watchdog 调用，换回 `timeout --foreground -k 45s ...` 原始写法

---

## 快速回滚命令

```bash
# 1. 删除 watchdog.py
rm /home/pt/SWE-bench/PDDL_work_mem/02_task_management/phase_history/阶段9/sweagent_external_tools_v2_2026-04-25/bin/watchdog.py

# 2. bridge_hook.py：用 git diff 或手动对照上方"变更前/后"还原
#    关键搜索词：SWEAGENT_BRIDGE_OVERHEAD_FILE / _t0_overhead / _overhead_file

# 3. run_lite_failedcase_repeat10_with_mem_closed_loop.sh：
#    删除 WATCHDOG_PY=... 行；
#    把 watchdog 调用块换回 timeout --foreground -k 45s ... 原始写法
```

---

## 回滚验证

回滚后运行以下检查：

```bash
# bridge_hook.py 不含 overhead 关键字
grep -c "SWEAGENT_BRIDGE_OVERHEAD_FILE" \
  /home/pt/SWE-bench/PDDL_work_mem/02_task_management/phase_history/阶段9/sweagent_external_tools_v2_2026-04-25/bridge_hook.py
# 期望输出: 0

# run 脚本中含有原始 timeout 命令
grep "timeout --foreground" \
  /home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/multi-try_experiment/with_mem/scripts/run_lite_failedcase_repeat10_with_mem_closed_loop.sh
# 期望输出: 1 行 timeout --foreground -k 45s ...

# watchdog.py 不存在
ls /home/pt/SWE-bench/PDDL_work_mem/02_task_management/phase_history/阶段9/sweagent_external_tools_v2_2026-04-25/bin/watchdog.py 2>&1
# 期望输出: No such file or directory
```

---

## 已知限制（不影响回滚决策）

- watchdog 轮询间隔 1 秒，budget 的实际精度为 ±1 秒
- 若 `SWEAGENT_BRIDGE_OVERHEAD_FILE` 写入失败（权限问题等），watchdog 退化为普通 wall-clock timeout，等价于回滚状态
- nomem 模式下 bridge_hook 不运行，overhead file 始终为空，watchdog 行为与原始 `timeout` 完全一致

---

## v2 修复（2026-04-29）

实验观测到两个追加 bug，已修复。

### 修复 B-v2：Watchdog process-group kill

**问题**：`proc.kill()` 只杀 direct child（shell wrapper），sweagent 是孙进程（不同 process group），继续运行直到自然退出，记录 `sweagent_exit_0` 但无 patch 提交。

**变更前（原始代码）**：
```python
proc = subprocess.Popen(cmd)
# ...
proc.kill()
try:
    proc.wait(timeout=45)
except subprocess.TimeoutExpired:
    proc.terminate()
```

**变更后（新代码）**：
```python
proc = subprocess.Popen(cmd, start_new_session=True)

def _kill_group() -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=45)
    except subprocess.TimeoutExpired:
        pass
# (替换所有 proc.kill() / proc.terminate() 调用为 _kill_group())
```

新增 `import signal`。

**回滚操作**：将上述代码还原，删除 `import signal` 行。

---

### 修复 A-v2：BugInvariantCard 代表性文件选取

**文件**：`agent_mem/processing/evaluation_feedback.py`

**问题**：commit 同时修改了 `AUTHORS`（贡献者名单）和 `model_checks.py`（实际 bug fix）时，`changed_files[0]` 按字母序返回 `AUTHORS`，导致：
- BugInvariantCard 的 hint 显示 "at AUTHORS. Key change: Can Sarıgöl"（完全错误）
- SuccessPathCard 的 hint 显示 "keep the patch family centered on AUTHORS"（指向错误文件）
- 模型在整个 attempt 中都在 AUTHORS 里搜索，从未修改 model_checks.py

**变更内容（新增常量）**：
```python
_NON_CODE_BASENAMES = frozenset({
    "AUTHORS", "CHANGELOG", "CHANGES", "NEWS", "NOTICE",
    "LICENSE", "COPYING", "CREDITS", "CONTRIBUTORS",
})
_NON_CODE_EXTENSIONS = frozenset({
    ".md", ".rst", ".txt", ".cfg", ".ini",
    ".yaml", ".yml", ".json", ".xml", ".html", ".css",
})
_PREFERRED_CODE_EXTENSION = ".py"
```

**变更内容（新增方法）**：
- `_pick_representative_file(changed_files)` — 从 changed_files 中选出最具代表性的文件（.py > 其他代码 > 非代码文件，完全非代码时 fallback 到 `changed_files[0]`）
- `_extract_key_added_lines_preferring_code(patch_text)` — 解析 diff 各文件 section，跳过非代码文件 section 后再提取 added lines（fallback：若所有 section 均为非代码，则退化为原始行为）

**变更内容（修改方法）**：
- `_build_bug_semantic`: `changed_files[0]` → `_pick_representative_file(changed_files)`
- `_build_success_path_hint`: `changed_files[0]` → `_pick_representative_file(changed_files)`
- `_write_bug_invariant_card` 中 `_extract_key_added_lines` → `_extract_key_added_lines_preferring_code`

**回滚操作**：
1. 删除模块顶部的三个 `_NON_CODE_*` 常量
2. 删除 `_pick_representative_file` 和 `_extract_key_added_lines_preferring_code` 两个静态方法
3. 将 `_build_bug_semantic` 还原：`file_hint = changed_files[0].split("/")[-1] if changed_files else "target file"`
4. 将 `_build_success_path_hint` 还原：`file_hint = changed_files[0] if changed_files else "the localized file"`
5. 将 `_write_bug_invariant_card` 中还原：`key_lines = self._extract_key_added_lines(patch_text)`
