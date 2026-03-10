#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_ids(base_dir: Path):
    data = load_json(base_dir / "cache" / "instance_ids.json")
    if isinstance(data, dict):
        return list(data.get("instance_ids", []))
    return list(data)


def load_summary(path: Path):
    if not path.exists():
        return None
    return load_json(path)


def find_raw_report(base_dir: Path, mode: str, attempt_tag: str):
    raw_dir = base_dir / "official_eval" / "raw_reports"
    matches = sorted(raw_dir.glob(f"{mode}_attempt_{attempt_tag}.*.json"))
    return matches[-1] if matches else None


def has_nonempty_patch(pred_path: Path) -> bool:
    if not pred_path.exists():
        return False
    text = pred_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return False
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return bool(str(obj.get("model_patch", "") or "").strip())
        except Exception:
            return True
    return True


def collect_attempt_matrix(base_dir: Path, instance_ids: list[str], repeats: int):
    matrix = {"no_mem": {}, "with_mem": {}}
    for mode in matrix:
        out_root = base_dir / mode / "outputs"
        for iid in instance_ids:
            attempts = []
            for attempt in range(1, repeats + 1):
                tag = f"{attempt:02d}"
                pred_path = out_root / iid / f"attempt_{tag}" / iid / f"{iid}.pred"
                traj_path = out_root / iid / f"attempt_{tag}" / iid / f"{iid}.traj"
                attempts.append(
                    {
                        "attempt": attempt,
                        "pred_nonempty": has_nonempty_patch(pred_path),
                        "traj_exists": traj_path.exists(),
                    }
                )
            matrix[mode][iid] = attempts
    return matrix


def main():
    ap = argparse.ArgumentParser(description="Analyze partial repeat eval coverage and partial official results.")
    ap.add_argument("--base-dir", required=True)
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--output-json", required=True)
    ap.add_argument("--output-md", required=True)
    args = ap.parse_args()

    base_dir = Path(args.base_dir).resolve()
    instance_ids = read_ids(base_dir)
    attempt_matrix = collect_attempt_matrix(base_dir, instance_ids, args.repeats)

    per_attempt = []
    for attempt in range(1, args.repeats + 1):
        tag = f"{attempt:02d}"
        no_summary = load_summary(base_dir / "official_eval" / "summary_by_attempt" / f"no_mem_attempt_{tag}.json")
        with_summary = load_summary(base_dir / "official_eval" / "summary_by_attempt" / f"with_mem_attempt_{tag}.json")
        no_raw_path = find_raw_report(base_dir, "no_mem", tag)
        with_raw_path = find_raw_report(base_dir, "with_mem", tag)
        no_raw = load_json(no_raw_path) if no_raw_path else None
        with_raw = load_json(with_raw_path) if with_raw_path else None

        no_submitted = set((no_raw or {}).get("submitted_ids", []))
        with_submitted = set((with_raw or {}).get("submitted_ids", []))
        common_submitted = sorted(no_submitted & with_submitted)
        no_resolved = set((no_raw or {}).get("resolved_ids", []))
        with_resolved = set((with_raw or {}).get("resolved_ids", []))

        common_count = len(common_submitted)
        no_common_resolved = len(no_resolved & set(common_submitted))
        with_common_resolved = len(with_resolved & set(common_submitted))

        row = {
            "attempt": attempt,
            "no_mem_summary": no_summary,
            "with_mem_summary": with_summary,
            "no_mem_raw_report": str(no_raw_path) if no_raw_path else None,
            "with_mem_raw_report": str(with_raw_path) if with_raw_path else None,
            "common_submitted_ids": common_submitted,
            "common_submitted_count": common_count,
            "no_mem_common_resolved": no_common_resolved,
            "with_mem_common_resolved": with_common_resolved,
            "no_mem_common_resolved_rate": round(no_common_resolved / common_count, 6) if common_count else None,
            "with_mem_common_resolved_rate": round(with_common_resolved / common_count, 6) if common_count else None,
        }
        per_attempt.append(row)

    per_instance = []
    for iid in instance_ids:
        no_attempts = [a["attempt"] for a in attempt_matrix["no_mem"][iid] if a["pred_nonempty"]]
        with_attempts = [a["attempt"] for a in attempt_matrix["with_mem"][iid] if a["pred_nonempty"]]
        common_attempts = sorted(set(no_attempts) & set(with_attempts))
        per_instance.append(
            {
                "instance_id": iid,
                "no_mem_available_attempts": no_attempts,
                "with_mem_available_attempts": with_attempts,
                "common_available_attempts": common_attempts,
                "common_available_attempt_count": len(common_attempts),
            }
        )

    result = {
        "report_version": "v1",
        "base_dir": str(base_dir),
        "repeats": args.repeats,
        "instance_count": len(instance_ids),
        "per_attempt": per_attempt,
        "per_instance": per_instance,
    }

    out_json = Path(args.output_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = []
    lines.append("# 部分评测与缺失覆盖对比报告")
    lines.append("")
    lines.append("## 结论")
    lines.append("- 这是基于当前真实已有产物的部分评测，不是完整 25x10 对比。")
    lines.append("- `Missing predictions` 的根因不是 ID 配置错，而是该 attempt 没有产生可评测 patch。")
    lines.append("- 下表优先看三类指标：`submitted`、`resolved/submitted`、`common submitted`。")
    lines.append("")
    lines.append("## 按 Attempt 部分官方评测")
    lines.append("")
    lines.append("| attempt | no submitted | no resolved | no rate/submitted | with submitted | with resolved | with rate/submitted | common submitted | no common resolved | with common resolved |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in per_attempt:
        no_summary = row["no_mem_summary"] or {}
        with_summary = row["with_mem_summary"] or {}
        no_sub = int(no_summary.get("submitted_instances", 0) or 0)
        no_res = int(no_summary.get("resolved_instances", 0) or 0)
        no_rate_sub = float(no_summary.get("solved_rate_on_submitted", 0.0) or 0.0)
        with_sub = int(with_summary.get("submitted_instances", 0) or 0)
        with_res = int(with_summary.get("resolved_instances", 0) or 0)
        with_rate_sub = float(with_summary.get("solved_rate_on_submitted", 0.0) or 0.0)
        lines.append(
            f"| {row['attempt']} | {no_sub} | {no_res} | {no_rate_sub:.2%} | {with_sub} | {with_res} | {with_rate_sub:.2%} | {row['common_submitted_count']} | {row['no_mem_common_resolved']} | {row['with_mem_common_resolved']} |"
        )

    lines.append("")
    lines.append("## 按 Instance 共同可比覆盖")
    lines.append("")
    lines.append("| instance | no_mem attempts | with_mem attempts | common comparable attempts |")
    lines.append("|---|---|---|---:|")
    for row in per_instance:
        lines.append(
            f"| {row['instance_id']} | {','.join(map(str, row['no_mem_available_attempts'])) or '-'} | {','.join(map(str, row['with_mem_available_attempts'])) or '-'} | {row['common_available_attempt_count']} |"
        )

    out_md = Path(args.output_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(out_md))


if __name__ == "__main__":
    main()
