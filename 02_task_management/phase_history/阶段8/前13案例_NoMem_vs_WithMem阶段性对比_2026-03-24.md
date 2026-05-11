# 前 13 案例 NoMem vs WithMem 阶段性对比（2026-03-24）

## 1. 结论摘要

- 本文只比较 same-only 实验前 13 个实例。
- 截至 2026-03-24，这 13 个实例在两条线中都已经完整跑满 `10 attempts`，总样本量都是 `130 attempts`。
- 前 13 个实例上的整体真值：
  - `NoMem`: `73 resolved / 130 = 56.15%`
  - `WithMem`: `70 resolved / 130 = 53.85%`
- 但 `WithMem` 的 incomplete 明显更少：
  - `NoMem`: `21 incomplete / 130 = 16.15%`
  - `WithMem`: `6 incomplete / 130 = 4.62%`

也就是说：

- 现阶段前 13 个案例上，`NoMem` 的最终 resolved 总数略高。
- `WithMem` 的主要优势不是“总 resolved 更多”，而是“中途挂掉/空结果更少，运行稳定性更好”。

## 2. 数据口径

- 数据来源：
  - `same_problem/nomem/metrics/attempt_summaries/*.summary.json`
  - `same_problem/with_mem/<instance>/candidates/<instance>/metrics/attempt_summaries/*.summary.json`
- 比较范围：
  - 前 13 个实例
  - 每个实例固定 `10 attempts`
- 率的定义：
  - `resolve率 = resolved_attempts / 10`
  - `incomplete率 = incomplete_attempts / 10`
- attempt 级比较：
  - 对 `attempt 1/2/3/4`，分别统计 13 个实例中该次尝试的 `resolved` 数，再除以 `13`

## 3. 前 13 个实例清单

1. `django__django-16139`
2. `sympy__sympy-13773`
3. `django__django-12497`
4. `django__django-15320`
5. `django__django-12284`
6. `sympy__sympy-15308`
7. `scikit-learn__scikit-learn-13439`
8. `matplotlib__matplotlib-18869`
9. `django__django-11620`
10. `sympy__sympy-11897`
11. `django__django-11848`
12. `sympy__sympy-24066`
13. `django__django-15996`

## 4. 每题对比：resolve率 / incomplete率

| # | instance | NoMem resolved | NoMem incomplete | WithMem resolved | WithMem incomplete | 备注 |
|---|---|---:|---:|---:|---:|---|
| 1 | `django__django-16139` | 1.0 | 0.0 | 1.0 | 0.0 | 两边都满分 |
| 2 | `sympy__sympy-13773` | 0.1 | 0.0 | 0.1 | 0.0 | 两边都弱 |
| 3 | `django__django-12497` | 1.0 | 0.0 | 1.0 | 0.0 | 两边都满分 |
| 4 | `django__django-15320` | 0.4 | 0.0 | 0.6 | 0.0 | WithMem 更好 |
| 5 | `django__django-12284` | 1.0 | 0.0 | 0.9 | 0.1 | NoMem 更稳，WithMem 有 1 次 incomplete |
| 6 | `sympy__sympy-15308` | 0.0 | 1.0 | 0.0 | 0.0 | WithMem 消除了全量 incomplete，但仍未解出 |
| 7 | `scikit-learn__scikit-learn-13439` | 1.0 | 0.0 | 1.0 | 0.0 | 两边都满分 |
| 8 | `matplotlib__matplotlib-18869` | 0.0 | 0.0 | 0.0 | 0.0 | 两边都全 unresolved |
| 9 | `django__django-11620` | 0.9 | 0.1 | 0.9 | 0.1 | 两边一致 |
| 10 | `sympy__sympy-11897` | 0.0 | 1.0 | 0.0 | 0.3 | WithMem 较少 incomplete，但仍未解出 |
| 11 | `django__django-11848` | 0.9 | 0.0 | 0.5 | 0.0 | NoMem 明显更好 |
| 12 | `sympy__sympy-24066` | 1.0 | 0.0 | 1.0 | 0.0 | 两边都满分 |
| 13 | `django__django-15996` | 0.0 | 0.0 | 0.0 | 0.1 | WithMem 第 10 次为 incomplete |

## 5. 按 attempt 次数对比成功率

统计对象：前 13 个实例，分别比较 `attempt_01` 到 `attempt_04` 的 `resolved` 比率和 `incomplete` 比率。

| attempt | NoMem resolve率 | NoMem incomplete率 | WithMem resolve率 | WithMem incomplete率 |
|---|---:|---:|---:|---:|
| 1 | 0.5385 | 0.1538 | 0.5385 | 0.0000 |
| 2 | 0.6154 | 0.1538 | 0.6154 | 0.0000 |
| 3 | 0.6154 | 0.1538 | 0.6154 | 0.0000 |
| 4 | 0.5385 | 0.1538 | 0.5385 | 0.0769 |

## 6. 阶段性解读

### 6.1 前 13 个实例上，WithMem 并没有形成压倒性胜势

- `WithMem` 明显更好的实例：
  - `django__django-15320`
- `NoMem` 明显更好的实例：
  - `django__django-11848`
  - `django__django-12284`（更少 incomplete）
- 大量实例上两者持平：
  - `django__django-16139`
  - `django__django-12497`
  - `scikit-learn__scikit-learn-13439`
  - `sympy__sympy-24066`
  - `matplotlib__matplotlib-18869`
  - `django__django-11620`

### 6.2 WithMem 的更稳定收益，当前主要体现在“降低 incomplete”

- 在 `attempt 1~3` 上，`WithMem` 与 `NoMem` 的 resolve 率完全相同。
- 但 `NoMem` 在 `attempt 1~3` 上都有 `15.38%` 的 incomplete 率。
- `WithMem` 在 `attempt 1~3` 上把 incomplete 降到了 `0%`。

这说明：

- 当前记忆系统对“更早解出来”的帮助还不稳定。
- 但它对“让 attempt 真正跑完、减少中途挂掉/空结果”的帮助已经可见。

### 6.3 WithMem 在后期个别题上仍然会转成 incomplete

- `django__django-12284`
- `django__django-11620`
- `sympy__sympy-11897`
- `django__django-15996`

这些题说明：

- 记忆系统并没有彻底解决后期失败问题。
- 当前收益更像是“前期把流程稳定住”，而不是“所有题后期都更稳”。

## 7. 当前实验推进状态

截至写文档时：

- `NoMem` 主实验已完成。
- `NoMem` 的 58 个 Docker 失败定向重跑也已完成：`58 done / 0 failed`。
- `WithMem` 已在后台恢复并继续推进：
  - 前 13 个实例现已全部完成
  - 当前已经切到第 14 个实例：`sphinx-doc__sphinx-8713`
  - 当前在跑：`attempt_01`

因此，整个 `WithMem` 剩余工作量已经从原来的 `21 attempts` 降为：

- 第 14 个实例：`10 attempts`
- 第 15 个实例：`10 attempts`
- 合计：`20 attempts`

## 8. 下一步建议

1. 继续让 `WithMem` 把最后 2 个实例跑完，不要中断。
2. 等 `WithMem` 全部 `150/150` 后，再做一次完整总表：
   - overall resolved rate
   - overall incomplete rate
   - per-attempt resolved curve
   - token / step / runtime 对比
3. 后续分析时要重点看：
   - `WithMem` 是否主要减少 incomplete
   - `WithMem` 是否在后段 attempts 才体现收益
   - 哪些 repo/topic 上记忆效果最明显
