#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ROLLOUT_CONFIG_FILE="${ROLLOUT_CONFIG_FILE:-$SCRIPT_DIR/config.env}"
ROLLOUT_LOCAL_CONFIG="${ROLLOUT_LOCAL_CONFIG:-$SCRIPT_DIR/config.local.env}"

load_rollout_config() {
  local entry file name
  local -a caller_env=()

  while IFS= read -r name; do
    caller_env+=("$name=${!name-}")
  done < <(compgen -e)

  for file in "$ROLLOUT_CONFIG_FILE" "$ROLLOUT_LOCAL_CONFIG"; do
    if [[ -f "$file" ]]; then
      set -a
      # shellcheck source=/dev/null
      source "$file"
      set +a
    fi
  done

  for entry in "${caller_env[@]}"; do
    name="${entry%%=*}"
    [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    export "$entry"
  done

  export ROLLOUT=1
  export RUN_ID="${RUN_ID:-agent-fleet-rollout}"
  export OUTPUT_ROOT="${OUTPUT_ROOT:-/data/agent-fleet-rollout/runs}"
  export AGENT="${AGENT:-claude-code}"
  export RL_AGENT="${RL_AGENT:-$AGENT}"
  export RL_SERVER_LOG="${RL_SERVER_LOG:-${OUTPUT_ROOT}/${RUN_ID}/runtime/${AGENT}/rl-rollout-server.log}"
}

configure_model_route() {
  if [[ -n "${MODEL_REQUEST_CONFIG_JSON:-}" || -z "${ROLLOUT_MODEL_BACKEND:-}" ]]; then
    return 0
  fi
  MODEL_REQUEST_CONFIG_JSON="$(
    python3 - "${ROLLOUT_MODEL_BACKEND}" <<'PY'
import json
import sys

print(json.dumps({"version": 1, "headers": {"set": {"X-Backend": sys.argv[1]}}}))
PY
  )"
  export MODEL_REQUEST_CONFIG_JSON
}

require_value() {
  local name="$1" value="${!1:-}"
  if [[ -z "$value" || "$value" == replace-* || "$value" == your-* ]]; then
    printf '[ERROR] required rollout setting is missing: %s\n' "$name" >&2
    return 1
  fi
}

validate_config() {
  local failed=0 name
  local -a required=(
    RL_DATASET_NAME RL_DATASET_ROOT RL_MODEL_NAME RL_API_BASE
    YICLOUD_PUBLIC_KEY YICLOUD_SECRET_KEY YICLOUD_PROJECT_NAME
    YICLOUD_SANDBOX_ENVIRONMENT_ID
  )
  if [[ "${RL_API_KEY_MODE:-static}" == "static" ]]; then
    required+=(RL_API_KEY)
  fi
  for name in "${required[@]}"; do
    require_value "$name" || failed=1
  done

  if [[ -n "${RL_DATASET_ROOT:-}" && ! -d "$RL_DATASET_ROOT" ]]; then
    printf '[ERROR] RL_DATASET_ROOT does not exist: %s\n' "$RL_DATASET_ROOT" >&2
    failed=1
  fi
  if [[ "${RL_API_BASE:-}" == http://10.100.184.46/* \
    && -z "${MODEL_REQUEST_CONFIG_JSON:-}" ]]; then
    printf '[ERROR] set ROLLOUT_MODEL_BACKEND for the shared CPU model proxy\n' >&2
    failed=1
  fi
  if [[ "${YICLOUD_SANDBOX_UPLOAD_BACKEND:-http}" == "s3" ]]; then
    require_value YICLOUD_SANDBOX_S3_BUCKET || failed=1
    if [[ -z "${YICLOUD_SANDBOX_S3_CONFIG:-}" \
      || ! -s "$YICLOUD_SANDBOX_S3_CONFIG" ]]; then
      printf '[ERROR] S3 config is missing or empty: %s\n' \
        "${YICLOUD_SANDBOX_S3_CONFIG:-<unset>}" >&2
      failed=1
    fi
  fi
  if [[ "${RL_MAX_CONCURRENT:-}" != "${RL_WORKERS:-}" ]]; then
    printf '[ERROR] RL_MAX_CONCURRENT and RL_WORKERS must match\n' >&2
    failed=1
  fi
  if [[ ! "${RL_WORKERS:-}" =~ ^[1-9][0-9]*$ ]]; then
    printf '[ERROR] RL_WORKERS must be a positive integer\n' >&2
    failed=1
  fi
  (( failed == 0 )) || return 1

  python3 "$REPO_ROOT/Agents/utils/rl/rollout_worker_utils.py" \
    request-headers >/dev/null
  printf '[OK] rollout configuration is valid\n'
  printf '[OK] dataset=%s workers=%s agent=%s port=%s\n' \
    "$RL_DATASET_NAME" "$RL_WORKERS" "$RL_AGENT" "$RL_PORT"
}

load_runtime_paths() {
  # shellcheck source=../../scripts/prerequisites.sh
  source "$REPO_ROOT/scripts/prerequisites.sh"
  agent_fleet_prerequisite_init_path
  agent_fleet_prerequisite_init_runtime
}

ensure_prerequisites() {
  if agent_fleet_check_core >/dev/null 2>&1 \
    && agent_fleet_check_harbor >/dev/null 2>&1; then
    return 0
  fi
  printf '[INFO] installing missing managed rollout prerequisites\n'
  agent_fleet_bootstrap_setup_prerequisites
}

start_rollout() {
  validate_config
  ensure_prerequisites
  mkdir -p "$OUTPUT_ROOT"
  ROLLOUT=1 bash "$REPO_ROOT/Agents/utils/common/Harbor/start.sh" --detach
  curl -fsS --max-time 5 "http://127.0.0.1:${RL_PORT}/health"
  printf '\n[OK] rollout listener: http://%s:%s\n' "$RL_HOST" "$RL_PORT"
}

stop_rollout() {
  bash "$REPO_ROOT/Agents/utils/rl/run_rl_rollout_server.sh" --stop
  printf '[OK] rollout listener stopped\n'
}

status_rollout() {
  if curl -fsS --max-time 3 "http://127.0.0.1:${RL_PORT}/health"; then
    printf '\n[OK] rollout listener is healthy\n'
    return 0
  fi
  printf '[ERROR] rollout listener is not healthy on port %s\n' "$RL_PORT" >&2
  return 1
}

usage() {
  cat <<'EOF'
Usage: deploy/rollout/rollout.sh <check|start|stop|restart|status|logs>
EOF
}

load_rollout_config
configure_model_route
load_runtime_paths

case "${1:-}" in
  check) validate_config ;;
  start) start_rollout ;;
  stop) stop_rollout ;;
  restart) stop_rollout; start_rollout ;;
  status) status_rollout ;;
  logs) tail -F "${RL_SERVER_LOG}" ;;
  *) usage; exit 2 ;;
esac
