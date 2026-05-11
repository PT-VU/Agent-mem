# Comparison Report: with-mem vs Historical no-mem (first50, unlimited steps, 20min)

- Generated at: 2026-03-07T11:47:22

## 1) Comparison Scope

- with-mem: official evaluation result from the latest completed run.
- no-mem: historical result from `official_eval_summary_exp01_full_first50_nomem_20min.json`.

## 2) Core Results

| Metric | with-mem | no-mem | Delta (with - no) |
|---|---:|---:|---:|
| resolved_instances | 37 | 15 | 22 |
| solved_rate_on_planned | 0.7400 | 0.3000 | +0.4400 |
| solved_rate_on_submitted | 0.7400 | 0.3125 | +0.4275 |

## 3) Conclusion

- Against the historical no-mem baseline you specified, this with-mem run is higher on both resolved count and solved rate.
- resolved: 37 vs 15 (+22)
- solved_rate_on_planned: 74.00% vs 30.00% (+44.00%)

## 4) Comparability Boundaries (Important)

- The current with-mem result is from `Lite First50` run artifacts; the historical no-mem baseline is from `Full First50`.
- Because the dataset subsets differ, this comparison is suitable for trend observation, not strict A/B conclusions.
- For strict conclusions, rerun both arms with the same dataset, identical instance list, and identical hyperparameters.

## 5) Data Sources

- with-mem summary: `/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/02_first50_unlimited/notes/official_eval_runs/withmem_only_eval_20260307_112438/official_summary_with_mem.json`
- no-mem summary: `/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/no_mem/metrics/official_eval_summary_exp01_full_first50_nomem_20min.json`
- comparison json: `/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/02_first50_unlimited/notes/official_eval_runs/withmem_only_eval_20260307_112438/comparison_with_previous_nomem_full50_20min_2026-03-07.json`

## 6) Process-Level Statistics (Step / Token / Time)

- Population: first50 for each arm, with trajectory coverage `50/50` for both.
- Step definition: `len(trajectory)` (action count per instance).
- Token definition: from `info.model_stats`, `tokens_total = tokens_sent + tokens_received`.
- Time definition: `sum(trajectory[*].execution_time)`; this is a command-execution proxy, not full end-to-end wall-clock.

### 6.1 Step Statistics

| Metric | with-mem | no-mem | Delta (with-no) |
|---|---:|---:|---:|
| Mean | 102.42 | 104.46 | -2.04 |
| Median | 109.50 | 103.50 | +6.00 |
| Minimum | 12.00 | 12.00 | +0.00 |
| Maximum | 164.00 | 176.00 | -12.00 |
| Std Dev | 28.39 | 33.48 | -5.09 |

### 6.2 Token Statistics (Total)

| Metric | with-mem | no-mem | Delta (with-no) |
|---|---:|---:|---:|
| Mean | 3,085,521.12 | 3,561,300.76 | -475,779.64 |
| Median | 3,158,731.50 | 3,288,795.50 | -130,064.00 |
| Minimum | 79,509.00 | 54,521.00 | +24,988.00 |
| Maximum | 5,981,817.00 | 11,318,814.00 | -5,336,997.00 |
| Std Dev | 1,243,907.09 | 1,836,142.82 | -592,235.73 |

Additional split (input/output):
- `tokens_sent` mean: with-mem `3,079,348.20` vs no-mem `3,553,803.62`
- `tokens_received` mean: with-mem `6,172.92` vs no-mem `7,497.14`

### 6.3 Time Statistics (sum of execution_time, seconds)

| Metric | with-mem | no-mem | Delta (with-no) |
|---|---:|---:|---:|
| Mean | 66.90 | 49.44 | +17.46 |
| Median | 43.88 | 49.40 | -5.52 |
| Minimum | 9.14 | 3.09 | +6.05 |
| Maximum | 405.47 | 103.41 | +302.06 |
| Std Dev | 70.32 | 18.22 | +52.10 |

### 6.4 Statistical Interpretation (Process Layer)

- Step: with-mem is lower on mean steps (-1.95%), but higher on median (+5.80%), indicating structural distribution differences.
- Token: with-mem is lower on mean total tokens (-13.36%) and median total tokens (-3.95%), and has a much lower extreme maximum.
- Time (execution-time proxy): with-mem is lower on median (-11.17%) but higher on mean (+35.32%), mainly due to long-tail instances (max 405.47s).

### 6.5 Data File for This Section

- extended stats json: `/home/pt/SWE-bench/PDDL_work_mem/06_artificial_intelligence/experiments/02_first50_unlimited/notes/official_eval_runs/withmem_only_eval_20260307_112438/extended_stats_withmem_vs_nomem_step_token_time_2026-03-07.json`
