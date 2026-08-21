#!/usr/bin/env bash
set -euo pipefail

RL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
worker="$RL_DIR/run_rl_rollout_worker.sh"
monitor="$RL_DIR/monitor_rl_rollout.sh"

bash -n "$worker"
bash -n "$monitor"

idle_block="$(sed -n '/^idle_wait()/,/^}/p' "$worker")"
queue_block="$(sed -n '/if \[\[ -z "${request_file:-}" \]\]/,/^[[:space:]]*fi/p' "$worker")"

[[ "$idle_block" == *'[[ -t 0 ]]'* ]]
[[ "$idle_block" == *'read -r -t'* ]]
[[ "$queue_block" == *'idle_wait'* ]]
[[ "$queue_block" != *'sleep '* ]]
[[ "$queue_block" != *'$(claim_request'* ]]
grep -F 'sleep "${RL_MONITOR_INTERVAL_SEC:-2}"' "$monitor" >/dev/null

echo "rollout worker idle wait test passed"
