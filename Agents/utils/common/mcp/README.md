# Exa Web MCP
Enable automatic preparation alongside the agent dependency cache:
```bash
export HARBOR_CC_WEB_MCP_ENABLED=1
```

The bundled Python sources produce a deterministic, content-addressed zipapp in
`LOCAL_WHEEL_DIR`. Unchanged sources reuse it; source changes select a new artifact
without overwriting artifacts in use. OpenSandbox checks/reuses the existing S3
object or uploads it through the existing transport. Docker uses the existing
local artifact mount. This does not upload to a remote HTTP cache.

Managed E2B/qz backends do not support MCP artifact delivery. Enabling this
switch on either backend is rejected during configuration loading, before
dependency preparation or Sandbox launch, even when a local artifact is cached.

Anonymous Exa access is the default. Set `EXA_API_KEY` in private runtime
configuration to use your own key; keys are never embedded in the artifact.
Anonymous access can be rate-limited and is not guaranteed to support a benchmark.

`HARBOR_CC_WEB_MCP_ENABLED` is the only MCP enable switch. Its default is `0`.
`HARBOR_CC_WEB_MCP_SOURCE` is an internally derived cache path, not user
configuration: an old exported value is ignored, including when MCP is disabled.
For a standalone build outside Agent Fleet:
```bash
python3 Agents/utils/common/mcp/build.py /data/mcp-cache
```
