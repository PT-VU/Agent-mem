#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
WITH_MEM_RUN_SCRIPT="${WITH_MEM_RUN_SCRIPT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/scripts/run_full_first50_with_mem_20min.sh}"
WITH_MEM_EVAL_SCRIPT="${WITH_MEM_EVAL_SCRIPT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/scripts/run_official_eval_full50_withmem_20min.sh}"
READINESS_SCRIPT="${READINESS_SCRIPT:-${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/common/evaluate_stage4_readiness.py}"

PAIRS_CONFIG="${PAIRS_CONFIG:-${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段4/stage4_pairs_config.json}"
READINESS_OUT="${READINESS_OUT:-${WS_ROOT}/PDDL_work_mem/02_task_management/phase_history/阶段4/stage4_readiness_report_latest.json}"

PYTHON_BIN="${PYTHON_BIN:-${WS_ROOT}/SWE-agent/.venv/bin/python}"
BOOTSTRAP_SAMPLES="${BOOTSTRAP_SAMPLES:-10000}"
BOOTSTRAP_SEED="${BOOTSTRAP_SEED:-42}"

START_INDEX="${START_INDEX:-auto}"
STOP_INDEX="${STOP_INDEX:-50}"
AUTO_CONTINUE="${AUTO_CONTINUE:-1}"
WINDOW_SIZE="${WINDOW_SIZE:-25}"
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT:-0}"
REDO_EXISTING="${REDO_EXISTING:-0}"

PAIR_ID_FULL50="${PAIR_ID_FULL50:-pair_20260228_full_first50_20min}"
NO_MEM_EVAL="${NO_MEM_EVAL:-PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/no_mem/metrics/official_eval_summary_exp01_full_first50_nomem_20min.json}"
WITH_MEM_EVAL="${WITH_MEM_EVAL:-PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/metrics/official_eval_summary_exp02_full_first50_withmem_20min.json}"
NO_MEM_METRICS="${NO_MEM_METRICS:-PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/no_mem/metrics/metrics_experiment01_full_first50_nomem_20min.json}"
WITH_MEM_METRICS="${WITH_MEM_METRICS:-PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/metrics/metrics_experiment02_full_first50_withmem_20min.json}"
DIFF_REPORT="${DIFF_REPORT:-PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/notes/official_eval_instance_diff_full_first50_20min.json}"
INSTANCE_IDS="${INSTANCE_IDS:-PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem/cache/full_test_instances_cache.json}"

log() {
  printf '[stage4-closure] %s\n' "$*"
}

require_file() {
  local f="$1"
  if [[ ! -f "${f}" ]]; then
    echo "missing file: ${f}" >&2
    exit 2
  fi
}

cd "${WS_ROOT}"

log "Step 1/4: resume with_mem full-first50 run"
START_INDEX="${START_INDEX}" \
STOP_INDEX="${STOP_INDEX}" \
AUTO_CONTINUE="${AUTO_CONTINUE}" \
WINDOW_SIZE="${WINDOW_SIZE}" \
PER_INSTANCE_CALL_LIMIT="${PER_INSTANCE_CALL_LIMIT}" \
REDO_EXISTING="${REDO_EXISTING}" \
"${WITH_MEM_RUN_SCRIPT}"

log "Step 2/4: run official evaluation for with_mem full-first50"
"${WITH_MEM_EVAL_SCRIPT}"

log "Step 3/4: upsert stage4 pair config with full-first50 pair"
require_file "${PAIRS_CONFIG}"
require_file "${WS_ROOT}/${NO_MEM_EVAL}"
require_file "${WS_ROOT}/${WITH_MEM_EVAL}"
require_file "${WS_ROOT}/${NO_MEM_METRICS}"
require_file "${WS_ROOT}/${WITH_MEM_METRICS}"
require_file "${WS_ROOT}/${DIFF_REPORT}"
require_file "${WS_ROOT}/${INSTANCE_IDS}"

"${PYTHON_BIN}" - "${PAIRS_CONFIG}" "${PAIR_ID_FULL50}" "${NO_MEM_EVAL}" "${WITH_MEM_EVAL}" "${NO_MEM_METRICS}" "${WITH_MEM_METRICS}" "${DIFF_REPORT}" "${INSTANCE_IDS}" <<'PY'
import json
import pathlib
import sys

cfg_path = pathlib.Path(sys.argv[1])
pair_id = sys.argv[2]
row = {
    "pair_id": pair_id,
    "no_mem_eval": sys.argv[3],
    "with_mem_eval": sys.argv[4],
    "no_mem_metrics": sys.argv[5],
    "with_mem_metrics": sys.argv[6],
    "diff_report": sys.argv[7],
    "instance_ids": sys.argv[8],
}

raw = json.loads(cfg_path.read_text(encoding="utf-8"))
if not isinstance(raw, list):
    raise SystemExit("pairs config must be a JSON array")

updated = False
for i, item in enumerate(raw):
    if isinstance(item, dict) and item.get("pair_id") == pair_id:
        raw[i] = row
        updated = True
        break

if not updated:
    raw.append(row)

cfg_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
print(cfg_path)
PY

log "Step 4/4: recompute stage4 readiness gates"
"${PYTHON_BIN}" "${READINESS_SCRIPT}" \
  --pairs-config "${PAIRS_CONFIG}" \
  --output "${READINESS_OUT}" \
  --bootstrap-samples "${BOOTSTRAP_SAMPLES}" \
  --bootstrap-seed "${BOOTSTRAP_SEED}"

log "Readiness summary:"
"${PYTHON_BIN}" - "${READINESS_OUT}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
print(f"pair_count={data.get('pair_count')}")
print(f"stage4_stats_gate_passed={data.get('stage4_stats_gate_passed')}")
rules = data.get("rules", {})
for k in sorted(rules):
    print(f"{k}={rules[k]}")
PY

