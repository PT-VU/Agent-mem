#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from statistics import mean


def pct(v: float) -> str:
    return f"{v * 100:.2f}%"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate markdown report from resolved_rate_by_attempt_with_vs_no_mem.json"
    )
    ap.add_argument("--input-json", required=True, help="Path to aggregated eval json")
    ap.add_argument("--output-md", required=True, help="Output markdown path")
    args = ap.parse_args()

    in_path = Path(args.input_json)
    out_path = Path(args.output_md)
    data = json.loads(in_path.read_text(encoding="utf-8"))
    rows = data.get("per_attempt", [])
    if not rows:
        raise SystemExit("No per_attempt records found.")

    better = sum(1 for r in rows if r.get("delta_resolved_rate", 0.0) > 0)
    equal = sum(1 for r in rows if r.get("delta_resolved_rate", 0.0) == 0)
    worse = sum(1 for r in rows if r.get("delta_resolved_rate", 0.0) < 0)

    no_rates = [float(r["no_mem"]["resolved_rate"]) for r in rows]
    with_rates = [float(r["with_mem"]["resolved_rate"]) for r in rows]
    deltas = [float(r.get("delta_resolved_rate", 0.0)) for r in rows]
    no_rates_sub = [float(r["no_mem"].get("resolved_rate_on_submitted", 0.0)) for r in rows]
    with_rates_sub = [float(r["with_mem"].get("resolved_rate_on_submitted", 0.0)) for r in rows]
    deltas_sub = [float(r.get("delta_resolved_rate_on_submitted", 0.0)) for r in rows]

    lines = []
    lines.append("# 重复求解实验官方评测报告")
    lines.append("")
    lines.append("## 核心结论")
    lines.append(
        f"- `with_mem` 在 {better}/{len(rows)} 个 attempt 上高于 `no_mem`，"
        f"{equal} 个持平，{worse} 个低于基线。"
    )
    lines.append(f"- `no_mem` 平均 resolved rate：{pct(mean(no_rates))}")
    lines.append(f"- `with_mem` 平均 resolved rate：{pct(mean(with_rates))}")
    lines.append(f"- 平均增益（with_mem - no_mem）：{pct(mean(deltas))}")
    lines.append(f"- `no_mem` 平均 submitted 内 resolved rate：{pct(mean(no_rates_sub))}")
    lines.append(f"- `with_mem` 平均 submitted 内 resolved rate：{pct(mean(with_rates_sub))}")
    lines.append(f"- 平均 submitted 内增益：{pct(mean(deltas_sub))}")
    lines.append("")
    lines.append("## 按 attempt 明细")
    lines.append("")
    lines.append("| attempt | no submitted | no resolved | no planned-rate | no submitted-rate | with submitted | with resolved | with planned-rate | with submitted-rate | delta planned | delta submitted |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        attempt = int(r["attempt"])
        no_cnt = int(r["no_mem"]["resolved_instances"])
        no_sub = int(r["no_mem"].get("submitted_instances", 0))
        no_rate = float(r["no_mem"]["resolved_rate"])
        no_rate_sub = float(r["no_mem"].get("resolved_rate_on_submitted", 0.0))
        w_cnt = int(r["with_mem"]["resolved_instances"])
        w_sub = int(r["with_mem"].get("submitted_instances", 0))
        w_rate = float(r["with_mem"]["resolved_rate"])
        w_rate_sub = float(r["with_mem"].get("resolved_rate_on_submitted", 0.0))
        d = float(r.get("delta_resolved_rate", 0.0))
        d_sub = float(r.get("delta_resolved_rate_on_submitted", 0.0))
        lines.append(
            f"| {attempt} | {no_sub} | {no_cnt} | {pct(no_rate)} | {pct(no_rate_sub)} | {w_sub} | {w_cnt} | {pct(w_rate)} | {pct(w_rate_sub)} | {pct(d)} | {pct(d_sub)} |"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
