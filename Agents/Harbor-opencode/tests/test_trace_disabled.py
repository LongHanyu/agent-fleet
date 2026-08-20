from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

MODULE_DIR = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeOpenCode:
    def __init__(
        self,
        *args,
        model_name: str | None = None,
        extra_env: dict[str, str] | None = None,
        fake_opencode_present: bool = True,
        fake_config_content: str | None = None,
        **kwargs,
    ) -> None:
        self.model_name = model_name
        self._extra_env = extra_env or {}
        self.fake_opencode_present = fake_opencode_present
        self.fake_config_content = fake_config_content
        self.root_commands: list[dict[str, object]] = []
        self.agent_commands: list[dict[str, object]] = []

    async def exec_as_root(self, environment, **kwargs) -> None:
        self.root_commands.append(kwargs)

    async def exec_as_agent(self, environment, **kwargs) -> None:
        self.agent_commands.append(kwargs)
        command = str(kwargs.get("command", ""))
        if not self.fake_opencode_present and "node --version" in command:
            raise RuntimeError("opencode is not installed")

    def _build_register_skills_command(self):
        return None

    def _build_register_config_command(self):
        if self.fake_config_content is None:
            return None
        return (
            "mkdir -p ~/.config/opencode && echo "
            f"{self.fake_config_content!r} > ~/.config/opencode/opencode.json"
        )


class FakeEnvironment:
    def __init__(self) -> None:
        self.uploads: list[tuple[Path, str]] = []
        self.uploaded_contents: dict[str, str] = {}

    async def upload_file(self, source: Path, destination: str) -> None:
        self.uploads.append((source, destination))
        if not source.is_file():
            raise FileNotFoundError(source)
        self.uploaded_contents[destination] = source.read_text(encoding="utf-8")


def make_harbor_stubs() -> dict[str, types.ModuleType]:
    stubs: dict[str, types.ModuleType] = {}
    for name in (
        "harbor",
        "harbor.agents",
        "harbor.agents.installed",
        "harbor.environments",
        "harbor.models",
        "harbor.models.agent",
    ):
        module = types.ModuleType(name)
        module.__path__ = []
        stubs[name] = module

    installed_base = types.ModuleType("harbor.agents.installed.base")
    installed_base.with_prompt_template = lambda function: function
    stubs[installed_base.__name__] = installed_base

    installed_opencode = types.ModuleType("harbor.agents.installed.opencode")
    installed_opencode.OpenCode = FakeOpenCode
    stubs[installed_opencode.__name__] = installed_opencode

    environments_base = types.ModuleType("harbor.environments.base")
    environments_base.BaseEnvironment = object
    stubs[environments_base.__name__] = environments_base

    context = types.ModuleType("harbor.models.agent.context")
    context.AgentContext = object
    stubs[context.__name__] = context
    return stubs


class OpenCodeTraceDisabledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module_name = "test_opik_opencode_harbor"
        with mock.patch.dict(sys.modules, make_harbor_stubs()):
            cls.module = load_module(
                cls.module_name,
                MODULE_DIR / "opik_opencode_harbor.py",
            )

    @classmethod
    def tearDownClass(cls) -> None:
        sys.modules.pop(cls.module_name, None)

    def make_agent(self, trace: str, *, opencode_present: bool = True):
        return self.module.OpikOpenCodeHarbor(
            logs_dir=Path("/tmp/test-opencode-logs"),
            model_name="custom/test-model",
            extra_env={
                "TRACE_TO_OPIK": trace,
                "CC_NODE_DIST_URL": (
                    "https://registry.npmmirror.com/-/binary/node/"
                    "v22.14.0/node-v22.14.0-linux-x64.tar.gz"
                ),
                "HARBOR_LOCAL_DOWNLOAD_HEADER": "X-Backend: 127.0.0.1:18765",
                "NPM_CONFIG_REGISTRY": "https://registry.npmmirror.com",
                "OPIK_URL": "http://localhost:5173",
                "OPIK_URL_OVERRIDE": "http://localhost:5173/api",
            },
            fake_opencode_present=opencode_present,
        )

    def test_trace_switch_matches_shell_semantics(self) -> None:
        self.assertFalse(self.module._trace_to_opik_enabled({"TRACE_TO_OPIK": "false"}))
        self.assertFalse(self.module._trace_to_opik_enabled({"TRACE_TO_OPIK": "0"}))
        self.assertTrue(self.module._trace_to_opik_enabled({"TRACE_TO_OPIK": "true"}))
        self.assertTrue(self.module._trace_to_opik_enabled({"TRACE_TO_OPIK": "unexpected"}))

    def test_install_skips_opik_dependencies_and_missing_plugin_files(self) -> None:
        agent = self.make_agent("false")
        environment = FakeEnvironment()

        asyncio.run(agent.install(environment))

        self.assertEqual(environment.uploads, [])
        commands = "\n".join(
            str(item.get("command", "")) for item in agent.agent_commands
        )
        self.assertNotIn("mods = ('opik', 'uuid6', 'socksio')", commands)
        self.assertNotIn("opik-trace.ts", commands)

    def test_install_uses_sandbox_reachable_node_dist_before_apt(self) -> None:
        agent = self.make_agent("false", opencode_present=False)

        asyncio.run(agent.install(FakeEnvironment()))

        install_command = next(
            str(item.get("command", ""))
            for item in agent.agent_commands
            if "opencode_version=" in str(item.get("command", ""))
        )
        self.assertIn("${CC_NODE_DIST_URL:-}", install_command)
        self.assertIn(
            'if download_file "$CC_NODE_DIST_URL" "$node_dist_tgz" '
            '    && [ -s "$node_dist_tgz" ]; then',
            install_command,
        )
        self.assertIn(
            'if extract_archive "$node_dist_tgz" "$node_dir"; then',
            install_command,
        )
        self.assertIn('curl -fsSL -H "$header"', install_command)
        self.assertIn('wget -q --header="$header"', install_command)
        self.assertLess(
            install_command.index("CC_NODE_DIST_URL"),
            install_command.index("apt-get update"),
        )
        self.assertIn('npm install -g "opencode-ai@${opencode_version}"', install_command)
        bash_check = subprocess.run(
            ["bash", "-n"],
            input=install_command,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(bash_check.returncode, 0, bash_check.stderr)

    def test_install_trace_on_keeps_opik_dependencies_and_plugin_files(self) -> None:
        agent = self.make_agent("true")
        environment = FakeEnvironment()

        with tempfile.TemporaryDirectory() as tmp:
            plugin = Path(tmp) / "opik-trace.ts"
            hook = Path(tmp) / "opencode_realtime_trace.py"
            plugin.touch()
            hook.touch()
            with (
                mock.patch.object(self.module, "PLUGIN_TS", plugin),
                mock.patch.object(self.module, "HOOK_PY", hook),
            ):
                asyncio.run(agent.install(environment))

        destinations = [destination for _, destination in environment.uploads]
        self.assertEqual(
            destinations,
            [
                "/tmp/opik-trace.ts",
                "/tmp/opencode_realtime_trace.py",
                "/tmp/finalize_opencode_sessions.py",
            ],
        )
        commands = "\n".join(
            str(item.get("command", "")) for item in agent.agent_commands
        )
        self.assertIn("mods = ('opik', 'uuid6', 'socksio')", commands)

    def test_run_skips_plugin_registration_and_finalizer(self) -> None:
        agent = self.make_agent("false")

        asyncio.run(agent.run("solve the task", FakeEnvironment(), object()))

        commands = "\n".join(
            str(item.get("command", "")) for item in agent.agent_commands
        )
        self.assertNotIn("opik-trace.ts", commands)
        self.assertNotIn("finalize_opencode_sessions.py", commands)
        self.assertNotIn(
            "OC_OPIK_LOGS_DIR",
            agent.agent_commands[-1].get("env", {}),
        )
        self.assertNotIn(
            "OPENCODE_FAKE_VCS",
            agent.agent_commands[-1].get("env", {}),
        )

    def test_run_uploads_config_without_logging_secret(self) -> None:
        secret = "secret-api-key"
        agent = self.module.OpikOpenCodeHarbor(
            logs_dir=Path("/tmp/test-opencode-logs"),
            model_name="custom/test-model",
            extra_env={"TRACE_TO_OPIK": "false"},
            fake_config_content=f'{{"apiKey":"{secret}"}}',
        )
        environment = FakeEnvironment()

        with mock.patch.dict(
            os.environ,
            {"HARBOR_ANTHROPIC_AUTH_TOKEN": secret},
            clear=False,
        ):
            asyncio.run(agent.run("solve the task", environment, object()))

        config_path = self.module.CONTAINER_CONFIG_PATH
        self.assertEqual(
            environment.uploaded_contents[config_path],
            f'{{"apiKey":"{secret}"}}',
        )
        commands = "\n".join(
            str(item.get("command", "")) for item in agent.agent_commands
        )
        self.assertNotIn(secret, commands)
        self.assertIn(config_path, commands)
        self.assertIn('${XDG_CONFIG_HOME:-$HOME/.config}/opencode', commands)
        self.assertEqual(
            agent.agent_commands[-1]["env"][self.module.OPENCODE_API_KEY_ENV],
            secret,
        )

    def test_run_trace_on_keeps_plugin_registration_and_finalizer(self) -> None:
        agent = self.make_agent("true")

        asyncio.run(agent.run("solve the task", FakeEnvironment(), object()))

        commands = "\n".join(
            str(item.get("command", "")) for item in agent.agent_commands
        )
        self.assertIn("opik-trace.ts", commands)
        self.assertIn("finalize_opencode_sessions.py", commands)
        self.assertIn("XDG_CONFIG_HOME", commands)
        run_env = agent.agent_commands[-1].get("env", {})
        self.assertEqual(run_env.get("OC_OPIK_LOGS_DIR"), "/logs/agent")
        self.assertEqual(
            run_env.get("OPIK_URL"),
            "http://host.docker.internal:5173/api/",
        )

    def test_run_applies_controlled_wall_clock_limit(self) -> None:
        agent = self.make_agent("false")

        with mock.patch.dict(
            os.environ,
            {"HARBOR_OPENCODE_RUN_TIMEOUT_SEC": "900"},
            clear=False,
        ):
            asyncio.run(agent.run("solve the task", FakeEnvironment(), object()))

        command = str(agent.agent_commands[-1]["command"])
        self.assertIn("timeout --signal=TERM --kill-after=30s 900s opencode", command)
        self.assertIn("OpenCode wall-clock limit reached after 900s", command)
        self.assertIn('opencode_rc=0', command)
        bash_check = subprocess.run(
            ["bash", "-n"],
            input=command,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(bash_check.returncode, 0, bash_check.stderr)

    def test_run_rejects_invalid_wall_clock_limit(self) -> None:
        agent = self.make_agent("false")

        with mock.patch.dict(
            os.environ,
            {"HARBOR_OPENCODE_RUN_TIMEOUT_SEC": "0"},
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "positive integer"):
                asyncio.run(
                    agent.run("solve the task", FakeEnvironment(), object())
                )


class EnableTrackHarborTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module_name = "test_enable_track_harbor"
        cls.module = load_module(
            cls.module_name,
            MODULE_DIR / "enable_track_harbor.py",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        sys.modules.pop(cls.module_name, None)

    def run_main(self, trace: str, environment_type: str = "docker"):
        app = mock.Mock()
        patch_e2b_runtime = mock.Mock()
        harbor = types.ModuleType("harbor")
        harbor.__path__ = []
        harbor_cli = types.ModuleType("harbor.cli")
        harbor_cli.__path__ = []
        harbor_main = types.ModuleType("harbor.cli.main")
        harbor_main.app = app
        e2b_runtime = types.ModuleType("e2b_runtime")
        e2b_runtime.patch_e2b_runtime_from_env = patch_e2b_runtime
        modules = {
            "harbor": harbor,
            "harbor.cli": harbor_cli,
            "harbor.cli.main": harbor_main,
            "e2b_runtime": e2b_runtime,
        }

        with (
            mock.patch.dict(
                os.environ,
                {
                    "TRACE_TO_OPIK": trace,
                    "HARBOR_ENVIRONMENT_TYPE": environment_type,
                },
                clear=True,
            ),
            mock.patch.dict(sys.modules, modules),
            mock.patch.object(sys, "argv", ["enable_track_harbor.py", "--help"]),
            mock.patch.object(self.module, "_patch_opik_batch_tags") as patch_batch,
            mock.patch.object(self.module, "_install_track_harbor") as install_tracking,
            mock.patch.object(
                self.module,
                "_patch_trial_decorator_with_harbor_tags",
            ) as patch_tags,
        ):
            self.module.main()

        app.assert_called_once_with()
        return (patch_batch, install_tracking, patch_tags), patch_e2b_runtime

    def test_trace_off_uses_plain_harbor_entrypoint(self) -> None:
        tracking_calls, patch_e2b_runtime = self.run_main("false")
        for call in tracking_calls:
            call.assert_not_called()
        patch_e2b_runtime.assert_not_called()

    def test_trace_on_keeps_host_tracking(self) -> None:
        tracking_calls, patch_e2b_runtime = self.run_main("true")
        for call in tracking_calls:
            call.assert_called_once_with()
        patch_e2b_runtime.assert_not_called()

    def test_e2b_compatible_backends_apply_runtime_patches(self) -> None:
        for environment_type in ("e2b", "qz"):
            with self.subTest(environment_type=environment_type):
                _, patch_e2b_runtime = self.run_main(
                    "false", environment_type=environment_type
                )
                patch_e2b_runtime.assert_called_once_with()


class FinalizerTraceGateTest(unittest.TestCase):
    """Worker-side timeout replay must stay silent when tracing is off."""

    FINALIZER = MODULE_DIR / "finalize_opencode_sessions.py"

    def run_finalizer(self, env_overrides: dict[str, str]):
        env = os.environ.copy()
        env.pop("TRACE_TO_OPIK", None)
        env.pop("OPIK_TRACK_DISABLE", None)
        env.update(env_overrides)
        return subprocess.run(
            [
                sys.executable,
                str(self.FINALIZER),
                "--status",
                "timeout",
                "--logs-dir",
                "/nonexistent/trace-gate-probe",
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_trace_off_skips_timeout_finalization(self) -> None:
        result = self.run_finalizer({"TRACE_TO_OPIK": "false"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("finalize skipped", result.stdout)

    def test_opik_track_disable_skips_timeout_finalization(self) -> None:
        result = self.run_finalizer({"OPIK_TRACK_DISABLE": "true"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("finalize skipped", result.stdout)


if __name__ == "__main__":
    unittest.main()
