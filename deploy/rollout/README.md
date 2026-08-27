# CPU Rollout Service

This profile starts Agent Fleet as a long-running Claude Code rollout service
for SWE-Rebench-V2 tasks on YiCloud OpenSandbox. It uses S3 for task and agent
artifacts and leaves Opik disabled.

## First Deployment

Clone the configured branch and create the two private credential files:

```bash
git clone -b personal-config ssh://git@ssh.github.com:443/LongHanyu/agent-fleet.git
cd agent-fleet

cp deploy/rollout/config.local.env.example deploy/rollout/config.local.env
chmod 600 deploy/rollout/config.local.env
vim deploy/rollout/config.local.env

cp deploy/rollout/s3cfg.example ~/.s3cfg
chmod 600 ~/.s3cfg
vim ~/.s3cfg
```

`config.local.env` requires the model API key, the current model backend behind
the shared CPU proxy, and the two YiCloud API credentials. `~/.s3cfg` requires
the S3 access and secret keys. Neither populated file is tracked by Git.

Validate and start the listener:

```bash
bash deploy/rollout/rollout.sh check
bash deploy/rollout/rollout.sh start
```

`start` installs the repository-managed `zellij` and `uv` only when they are
missing, using the configured GitHub release mirror on restricted CPU hosts.
Task Sandboxes use the pinned Node.js 22.14 archive from npmmirror under the
Sandbox user's `$HOME/.local`; the image's system Node.js is not modified. The
launcher then prepares the Claude Code runtime, starts the listener in detached
mode, and checks `/health` before returning.

## Operations

```bash
bash deploy/rollout/rollout.sh status
bash deploy/rollout/rollout.sh logs
bash deploy/rollout/rollout.sh restart
bash deploy/rollout/rollout.sh stop
```

The stable run ID is `agent-fleet-rollout`, so all commands address the same
listener after a shell reconnect or CPU reboot. Runtime data is under
`/data/agent-fleet-rollout` by default.

## Overrides

Edit `deploy/rollout/config.local.env` to override any committed default. The
most common changes are `RL_DATASET_ROOT`, `RL_MODEL_NAME`, `RL_API_BASE`,
`RL_MAX_CONCURRENT`, `RL_WORKERS`, and `RL_PORT`. Keep
`RL_MAX_CONCURRENT` and `RL_WORKERS` equal.

The default concurrency is 16 because the validated CPU host has 49 GiB RAM
and no swap; a 200-worker control plane previously exhausted that host. Scale
in stages while watching host memory and OpenSandbox scheduling latency.
