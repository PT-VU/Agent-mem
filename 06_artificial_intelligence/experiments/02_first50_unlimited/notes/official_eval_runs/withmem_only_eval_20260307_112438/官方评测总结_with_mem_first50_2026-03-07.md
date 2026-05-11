# with-mem 官方评测总结（first50）

- 生成时间：2026-03-07T11:42:06
- run_id：`withmem_only_eval_withmem_only_eval_20260307_112438_retry1`
- 数据集：SWE-bench/SWE-bench test
- 范围：Lite First50 with-mem only (2026-03-07 rerun)

## 核心结果

- planned_instances：50
- submitted_instances：50
- completed_instances：50
- resolved_instances：37
- unresolved_instances：13
- error_instances：0
- solved_rate_on_planned：0.7400
- solved_rate_on_submitted：0.7400

## 结果解读

- 这次评测为官方 resolved 口径，不是仅看 `submitted`。
- 本次 50/50 都完成评测，结果具备完整可比性。
- 当前 solved rate 为 0.7400，说明记忆组在该批次 first50 上有可用提升空间。

## 样本列表

- resolved_ids（37）：`astropy__astropy-12907, astropy__astropy-14365, astropy__astropy-14995, astropy__astropy-6938, django__django-10914, django__django-11001, django__django-11039, django__django-11049, django__django-11099, django__django-11133, django__django-11179, django__django-11283, django__django-11422, django__django-11583, django__django-11620, django__django-11797, django__django-11815, django__django-11848, django__django-11964, django__django-11999` ...
- unresolved_ids（13）：`astropy__astropy-14182, astropy__astropy-7746, django__django-10924, django__django-11019, django__django-11564, django__django-11630, django__django-11742, django__django-11905, django__django-11910, django__django-12113, django__django-12470, django__django-12589, django__django-12747`
