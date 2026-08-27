#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROLLOUT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

mkdir -p "$TMP_ROOT/dataset/0"
printf '[default]\n' > "$TMP_ROOT/s3cfg"

cat > "$TMP_ROOT/config.env" <<EOF
RL_DATASET_NAME=test-dataset
RL_DATASET_ROOT=$TMP_ROOT/dataset
RL_MODEL_NAME=custom/test
RL_API_BASE=http://10.100.184.46/v1
RL_API_KEY_MODE=static
RL_MAX_CONCURRENT=2
RL_WORKERS=2
RL_AGENT=claude-code
RL_PORT=19001
YICLOUD_PROJECT_NAME=test-project
YICLOUD_SANDBOX_ENVIRONMENT_ID=env-test
YICLOUD_SANDBOX_UPLOAD_BACKEND=s3
YICLOUD_SANDBOX_S3_BUCKET=test-bucket
YICLOUD_SANDBOX_S3_CONFIG=$TMP_ROOT/s3cfg
EOF

cat > "$TMP_ROOT/config.local.env" <<'EOF'
RL_API_KEY=test-model-key
ROLLOUT_MODEL_BACKEND=127.0.0.1:8000
YICLOUD_PUBLIC_KEY=test-public-key
YICLOUD_SECRET_KEY=test-secret-key
EOF

ROLLOUT_CONFIG_FILE="$TMP_ROOT/config.env" \
ROLLOUT_LOCAL_CONFIG="$TMP_ROOT/config.local.env" \
  bash "$ROLLOUT_DIR/rollout.sh" check > "$TMP_ROOT/check.out"
grep -Fq '[OK] rollout configuration is valid' "$TMP_ROOT/check.out"

if env -u RL_API_KEY -u ROLLOUT_MODEL_BACKEND -u MODEL_REQUEST_CONFIG_JSON \
  -u YICLOUD_PUBLIC_KEY -u YICLOUD_SECRET_KEY \
  ROLLOUT_CONFIG_FILE="$TMP_ROOT/config.env" \
  ROLLOUT_LOCAL_CONFIG=/dev/null \
  bash "$ROLLOUT_DIR/rollout.sh" check > "$TMP_ROOT/missing.out" 2>&1; then
  echo 'missing credentials unexpectedly passed validation' >&2
  exit 1
fi
grep -Fq 'required rollout setting is missing: RL_API_KEY' "$TMP_ROOT/missing.out"

printf 'rollout launcher tests passed\n'
