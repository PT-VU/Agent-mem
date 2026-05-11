# 同题 NoMem Docker 失败待重跑清单

## 1. 清单用途

这份清单记录 `phase8_same_only_001` 中 `same_problem/nomem` 里所有明确命中以下错误模式的 attempts：

- `DockerPullError`
- `The command 'docker' could not be found in this WSL 2 distro`

这些 attempts 当前不应直接视为 agent 解题失败，而应视为 **基础设施失败**，后续应单独重跑。

## 2. 总数

- 失败实例数：`6`
- 失败 attempts 总数：`58`

## 3. 待重跑实例与 attempts

### django__django-11620

- `attempt_01`
- `attempt_02`
- `attempt_03`
- `attempt_04`
- `attempt_05`
- `attempt_06`
- `attempt_07`
- `attempt_08`
- `attempt_09`
- `attempt_10`

### django__django-11848

- `attempt_01`
- `attempt_02`
- `attempt_03`
- `attempt_04`
- `attempt_05`
- `attempt_06`
- `attempt_07`

### django__django-12284

- `attempt_10`

### matplotlib__matplotlib-18869

- `attempt_01`
- `attempt_02`
- `attempt_03`
- `attempt_04`
- `attempt_05`
- `attempt_06`
- `attempt_07`
- `attempt_08`
- `attempt_09`
- `attempt_10`

### scikit-learn__scikit-learn-13439

- `attempt_01`
- `attempt_02`
- `attempt_03`
- `attempt_04`
- `attempt_05`
- `attempt_06`
- `attempt_07`
- `attempt_08`
- `attempt_09`
- `attempt_10`

### sympy__sympy-11897

- `attempt_01`
- `attempt_02`
- `attempt_03`
- `attempt_04`
- `attempt_05`
- `attempt_06`
- `attempt_07`
- `attempt_08`
- `attempt_09`
- `attempt_10`

### sympy__sympy-15308

- `attempt_01`
- `attempt_02`
- `attempt_03`
- `attempt_04`
- `attempt_05`
- `attempt_06`
- `attempt_07`
- `attempt_08`
- `attempt_09`
- `attempt_10`

## 4. 后续使用建议

后续重跑时建议：

1. 保持实例和 attempt 号不变，单独定向重跑。
2. 将这 `58` 个 attempts 单独统计，不与正常完成的 attempts 混在同一轮结论里。
3. 后续对比 `NoMem` 与 `WithMem` 时，至少保留两套口径：
   - 原始口径
   - 剔除基础设施失败后的净口径
