# 对比报告：with-mem vs 历史 no-mem（first50，不限步数，20min）

- 生成时间：2026-03-07T11:47:22

## 1) 对比口径

- with-mem：本次官方评测结果（刚完成）。
- no-mem：历史已跑结果 `official_eval_summary_exp01_full_first50_nomem_20min.json`。

## 2) 核心结果

| 指标 | with-mem | no-mem | 差值 (with - no) |
|---|---:|---:|---:|
| resolved_instances | 37 | 15 | 22 |
| solved_rate_on_planned | 0.7400 | 0.3000 | +0.4400 |
| solved_rate_on_submitted | 0.7400 | 0.3125 | +0.4275 |

## 3) 结论

- 按你指定的历史 no-mem 基线，本次 with-mem 的 resolved 与 solved_rate 均更高。
- resolved：37 vs 15（+22）
- solved_rate_on_planned：74.00% vs 30.00%（+44.00%）

## 4) 可比性边界（必须注意）

- 本次 with-mem 评测来自 `Lite First50` 运行产物；历史 no-mem 基线来自 `Full First50`。
- 因数据子集来源不同，该对比可用于“趋势观察”，不应作为严格 A/B 结论。
- 若要严格结论，需要同一数据集、同一实例列表、同一超参重新双跑并评测。

## 5) 数据来源

- with-mem summary: `/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/02_first50_unlimited/notes/official_eval_runs/withmem_only_eval_20260307_112438/official_summary_with_mem.json`
- no-mem summary: `/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/no_mem/metrics/official_eval_summary_exp01_full_first50_nomem_20min.json`
- comparison json: `/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/02_first50_unlimited/notes/official_eval_runs/withmem_only_eval_20260307_112438/comparison_with_previous_nomem_full50_20min_2026-03-07.json`

## 6) 过程指标统计对比（Step / Token / 用时）

- 统计对象：两组各 first50，轨迹覆盖均为 `50/50`。
- Step 定义：`len(trajectory)`（每实例 action 步数）。
- Token 定义：来自 `info.model_stats`，`tokens_total=tokens_sent+tokens_received`。
- 用时定义：`sum(trajectory[*].execution_time)`，是命令执行耗时代理，不是完整端到端 wall-clock。

### 6.1 Step 统计

| 指标 | with-mem | no-mem | 差值 (with-no) |
|---|---:|---:|---:|
| 平均数 mean | 102.42 | 104.46 | -2.04 |
| 中位数 median | 109.50 | 103.50 | +6.00 |
| 最小值 min | 12.00 | 12.00 | +0.00 |
| 最大值 max | 164.00 | 176.00 | -12.00 |
| 标准差 std | 28.39 | 33.48 | -5.09 |

### 6.2 Token 统计（总量）

| 指标 | with-mem | no-mem | 差值 (with-no) |
|---|---:|---:|---:|
| 平均数 mean | 3,085,521.12 | 3,561,300.76 | -475,779.64 |
| 中位数 median | 3,158,731.50 | 3,288,795.50 | -130,064.00 |
| 最小值 min | 79,509.00 | 54,521.00 | +24,988.00 |
| 最大值 max | 5,981,817.00 | 11,318,814.00 | -5,336,997.00 |
| 标准差 std | 1,243,907.09 | 1,836,142.82 | -592,235.73 |

补充（输入/输出拆分）：
- `tokens_sent` 均值：with-mem `3,079,348.20` vs no-mem `3,553,803.62`
- `tokens_received` 均值：with-mem `6,172.92` vs no-mem `7,497.14`

### 6.3 用时统计（execution_time 求和，秒）

| 指标 | with-mem | no-mem | 差值 (with-no) |
|---|---:|---:|---:|
| 平均数 mean | 66.90 | 49.44 | +17.46 |
| 中位数 median | 43.88 | 49.40 | -5.52 |
| 最小值 min | 9.14 | 3.09 | +6.05 |
| 最大值 max | 405.47 | 103.41 | +302.06 |
| 标准差 std | 70.32 | 18.22 | +52.10 |

### 6.4 统计解读（过程层）

- Step：with-mem 在均值上更少（-1.95%），但中位数更高（+5.80%），说明分布有结构性差异。
- Token：with-mem 在均值上更低（-13.36%），中位数也更低（-3.95%），且极端最大值显著更低。
- 用时（执行耗时代理）：with-mem 中位数更低（-11.17%），但均值更高（+35.32%），主要受长尾实例影响（最大值 405.47s）。

### 6.5 本节数据文件

- extended stats json: `/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/02_first50_unlimited/notes/official_eval_runs/withmem_only_eval_20260307_112438/extended_stats_withmem_vs_nomem_step_token_time_2026-03-07.json`
