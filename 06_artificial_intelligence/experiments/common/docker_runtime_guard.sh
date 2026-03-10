#!/usr/bin/env bash
set -euo pipefail

runtime_guard_preflight() {
  local log_file="$1"
  {
    echo "[preflight] $(date -Is) docker info"
    docker info >/dev/null
    echo "[preflight] docker ok"
  } >>"${log_file}" 2>&1
}

runtime_guard_capture_diag() {
  local log_file="$1"
  local image_pattern="$2"
  {
    echo "[diag] $(date -Is) docker ps -a"
    docker ps -a --format '{{.ID}} {{.Image}} {{.Status}} {{.Names}}'
    echo "[diag] matching containers for ${image_pattern}"
    docker ps -a --format '{{.ID}} {{.Image}} {{.Names}}' | grep -F "${image_pattern}" || true
    while read -r cid _; do
      [ -z "${cid}" ] && continue
      echo "[diag] docker inspect ${cid}"
      docker inspect "${cid}" || true
      echo "[diag] docker logs ${cid}"
      docker logs --tail 200 "${cid}" || true
    done < <(docker ps -a --format '{{.ID}} {{.Image}}' | grep -F "${image_pattern}" || true)
  } >>"${log_file}" 2>&1
}

runtime_guard_cleanup_pattern() {
  local log_file="$1"
  local image_pattern="$2"
  {
    echo "[cleanup] $(date -Is) image pattern=${image_pattern}"
    while read -r cid _ name; do
      [ -z "${cid}" ] && continue
      echo "[cleanup] removing container ${cid} ${name}"
      docker rm -f "${cid}" || true
    done < <(docker ps -a --format '{{.ID}} {{.Image}} {{.Names}}' | grep -F "${image_pattern}" || true)
  } >>"${log_file}" 2>&1
}
