# 实验01记录

- 实验编号: 实验01
- 目标: SWEAgent 在 `no-mem` 模式下跑 1 次 SWEBench Lite 基线并记录指标（不拉取实例镜像）
- 模型平台: deepseek
- 模型名: deepseek/deepseek-chat

## 结果摘要
- 总任务数: 1
- 成功任务数: 1
- 整体任务成功率: 1.0
- 工具调用成功率: 1.0

## 关键现象
- 已切换到本地部署（`deployment: local` + `preexisting repo`），不再触发 Docker 镜像拉取。
- 本轮退出状态: `submitted (exit_cost)`，产出了 `traj` 和 `preds.json`。
- baseline hook 日志统计: `plan_generated=6`、`action_error=0`、`run_done=1`。
- 为支持本地模式，修复了 SWE-agent 中若干 `/root/*` 硬编码路径并改为运行时可配置路径。
- 说明: 这里的“成功”表示流程运行成功并完成提交，不代表 SWEBench 官方判分意义上的“已解题”。

## 关于实例数量
- 本实验只跑了 1 个实例，不是完整 SWE-bench Lite。
- 原因:
  - `instances_lite_exp01_local.yaml` 只包含 1 条 expert 实例（`django__django-16255`）。
  - 运行命令使用了 `--instances.slice :1`。
  - 运行类型是 `expert_file`，且 repo 指向 `/home/pt/SWE-bench/SWE-agent`，属于接入验证 smoke run。
- 参考计数（HF 数据集）:
  - `SWE-bench_Lite dev = 23`
  - `SWE-bench_Lite test = 300`

## sentence-transformers 检验
- 见 `sentence_transformers_check.json`。
- 当前状态为“主运行环境可导入，但离线缓存模型不可用（offline/cache-only 加载失败）”。

## 产物
- `instances_lite_exp01_local.yaml`
- `run_outputs_local_nomem_fixed/`
- `no_mem_tool_events_fixed.jsonl`
- `metrics_experiment01.json`
- `sentence_transformers_check.json`
