#!/usr/bin/env bash
set -euo pipefail

WS_ROOT="${WS_ROOT:-/home/pt/SWE-bench}"
SWE_AGENT_ROOT="${SWE_AGENT_ROOT:-${WS_ROOT}/SWE-agent}"
PYTHON_BIN="${PYTHON_BIN:-${SWE_AGENT_ROOT}/.venv/bin/python}"
COMMON_DIR="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/common"
EXP_DIR="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/with_mem"
NO_MEM_EXP_DIR="${WS_ROOT}/PDDL_work_mem/06_artificial_intelligence/experiments/03_run_outputs_full_first50_nomem_20min/no_mem"

OUTDIR="${OUTDIR:-${EXP_DIR}/outputs/run_outputs_full_first50_with_mem_20min}"
CACHE_FILE="${CACHE_FILE:-${EXP_DIR}/cache/full_test_instances_cache.json}"
METRICS_DIR="${METRICS_DIR:-${EXP_DIR}/metrics}"
NOTES_DIR="${NOTES_DIR:-${EXP_DIR}/notes}"
mkdir -p "${METRICS_DIR}" "${NOTES_DIR}"

PREDS_FIXED="${PREDS_FIXED:-${OUTDIR}/preds_full50_withmem_eval_fixed.json}"
RUN_ID="${RUN_ID:-exp02_full_first50_withmem_20min_official_eval_$(date +%Y%m%d_%H%M%S)}"
MAX_WORKERS="${MAX_WORKERS:-4}"
TIMEOUT_SEC="${TIMEOUT_SEC:-1200}"

NO_MEM_REPORT_JSON="${NO_MEM_REPORT_JSON:-${NO_MEM_EXP_DIR}/metrics/run_outputs_full_first50_nomem_20min.exp01_full_first50_nomem_20min_official_eval_fixed_20260227.json}"
NO_MEM_SUMMARY_JSON="${NO_MEM_SUMMARY_JSON:-${NO_MEM_EXP_DIR}/metrics/official_eval_summary_exp01_full_first50_nomem_20min.json}"
WITH_SUMMARY_JSON="${WITH_SUMMARY_JSON:-${METRICS_DIR}/official_eval_summary_exp02_full_first50_withmem_20min.json}"
WITH_REPORT_JSON_LINK="${WITH_REPORT_JSON_LINK:-${METRICS_DIR}/official_eval_report_exp02_full_first50_withmem_20min.json}"
DIFF_OUT="${DIFF_OUT:-${NOTES_DIR}/official_eval_instance_diff_full_first50_20min.json}"

echo "[1/6] rebuild predictions: ${PREDS_FIXED}"
"${PYTHON_BIN}" "${COMMON_DIR}/rebuild_eval_predictions.py" \
  --output-dir "${OUTDIR}" \
  --cache-file "${CACHE_FILE}" \
  --default-model-name "run_outputs_full_first50_with_mem_20min" \
  --out "${PREDS_FIXED}"

echo "[2/6] prepare instance id list from cache"
mapfile -t INSTANCE_IDS < <("${PYTHON_BIN}" - <<'PY' "${CACHE_FILE}"
import json, pathlib, sys
ids = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
for iid in ids:
    print(iid)
PY
)

if [[ "${#INSTANCE_IDS[@]}" -eq 0 ]]; then
  echo "No instance ids found in cache: ${CACHE_FILE}" >&2
  exit 2
fi

echo "[3/6] run official evaluation (run_id=${RUN_ID})"
"${PYTHON_BIN}" -m swebench.harness.run_evaluation \
  --dataset_name SWE-bench/SWE-bench \
  --split test \
  --predictions_path "${PREDS_FIXED}" \
  --max_workers "${MAX_WORKERS}" \
  --timeout "${TIMEOUT_SEC}" \
  --cache_level env \
  --clean false \
  --run_id "${RUN_ID}" \
  --instance_ids "${INSTANCE_IDS[@]}"

echo "[4/6] locate generated raw report json"
RAW_REPORT_JSON="$(ls -1t "${WS_ROOT}"/*.${RUN_ID}.json 2>/dev/null | head -n 1 || true)"
if [[ -z "${RAW_REPORT_JSON}" ]]; then
  echo "Cannot find report json '*.${RUN_ID}.json' under ${WS_ROOT}" >&2
  exit 2
fi
cp -f "${RAW_REPORT_JSON}" "${WITH_REPORT_JSON_LINK}"
echo "raw_report=${RAW_REPORT_JSON}"
echo "raw_report_link=${WITH_REPORT_JSON_LINK}"

echo "[5/6] build with_mem summary"
"${PYTHON_BIN}" "${COMMON_DIR}/summarize_official_eval.py" \
  --report-json "${RAW_REPORT_JSON}" \
  --run-id "${RUN_ID}" \
  --dataset "SWE-bench/SWE-bench test" \
  --scope "Full First50 with_mem 20min" \
  --summary-out "${WITH_SUMMARY_JSON}"

echo "[6/6] compare no_mem/with_mem official reports"
"${PYTHON_BIN}" "${COMMON_DIR}/compare_official_eval_reports.py" \
  --no-mem-report "${NO_MEM_REPORT_JSON}" \
  --with-mem-report "${RAW_REPORT_JSON}" \
  --instance-ids-json "${CACHE_FILE}" \
  --output "${DIFF_OUT}"

echo "done"
echo "with_summary=${WITH_SUMMARY_JSON}"
echo "diff_out=${DIFF_OUT}"
echo "no_mem_summary=${NO_MEM_SUMMARY_JSON}"
