from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class FigureAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _backend_root(self, name: str) -> Path:
        root = self.root / name
        (root / "utils").mkdir(parents=True, exist_ok=True)
        (root / "utils" / "paperviz_processor.py").write_text("# stub\n", encoding="utf-8")
        return root

    def test_prefers_paperbanana_over_papervizagent_when_both_are_configured(self) -> None:
        from gui_app import figure_adapter

        paperbanana = self._backend_root("PaperBanana")
        papervizagent = self._backend_root("PaperVizAgent")
        status = figure_adapter.figure_backend_status({
            "PAPERBANANA_PATH": str(paperbanana),
            "PAPERVIZAGENT_PATH": str(papervizagent),
        })

        self.assertTrue(status["configured"])
        self.assertTrue(status["valid"])
        self.assertEqual(status["selected_backend"], "paperbanana")
        self.assertEqual(status["selected_root"], str(paperbanana))

    def test_numeric_plots_default_to_local_renderer(self) -> None:
        from gui_app import figure_adapter

        paperbanana = self._backend_root("PaperBanana")
        diagram_choice = figure_adapter.select_figure_engine("diagram", {
            "PAPERBANANA_PATH": str(paperbanana),
        })
        plot_choice = figure_adapter.select_figure_engine("plot", {
            "PAPERBANANA_PATH": str(paperbanana),
        })

        self.assertEqual(diagram_choice["engine"], "paperbanana")
        self.assertEqual(plot_choice["engine"], "local_matplotlib")

    def test_quality_check_flags_missing_and_tiny_figure_outputs(self) -> None:
        from gui_app import figure_adapter

        missing = figure_adapter.figure_quality_check([])
        self.assertFalse(missing["passed"])
        self.assertEqual(missing["reason"], "figure_qc_failed")

        tiny = self.root / "tiny.png"
        tiny.write_bytes(b"\x89PNG\r\n\x1a\n")
        tiny_result = figure_adapter.figure_quality_check([str(tiny)])
        self.assertFalse(tiny_result["passed"])
        self.assertEqual(tiny_result["reason"], "figure_qc_failed")

    def test_plotting_wrapper_accepts_papervizagent_path_as_backend(self) -> None:
        script = _load_module(
            "paperbanana_render_test",
            Path("/Users/jeff/paper-orchestra/skills/plotting-agent/scripts/paperbanana_render.py"),
        )
        papervizagent = self._backend_root("PaperVizAgent")

        with mock.patch.dict(os.environ, {"PAPERBANANA_PATH": "", "PAPERVIZAGENT_PATH": str(papervizagent)}, clear=False):
            selected = script._paperbanana_path()

        self.assertEqual(selected, papervizagent)

    def test_codex_image_handoff_uses_gpt55_xhigh_and_validates_png(self) -> None:
        script = _load_module(
            "paperbanana_render_handoff_test",
            Path("/Users/jeff/paper-orchestra/skills/plotting-agent/scripts/paperbanana_render.py"),
        )
        content_file = self.root / "content.md"
        content_file.write_text("Method content", encoding="utf-8")
        out_path = self.root / "figure.png"

        def fake_run(command, **kwargs):
            out_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 2048)
            result = mock.Mock()
            result.returncode = 0
            result.args = command
            return result

        with mock.patch.dict(os.environ, {
            "PAPERBANANA_CODEX_MODEL": "",
            "PAPERBANANA_CODEX_REASONING_EFFORT": "",
            "PAPERORCHESTRA_CODEX_MODEL": "",
            "PAPERORCHESTRA_CODEX_REASONING_EFFORT": "",
        }, clear=False):
            with mock.patch.object(script.subprocess, "run", side_effect=fake_run) as run_mock:
                code = script._run_codex_image_handoff(
                    figure_id="fig_smoke",
                    caption="Smoke figure",
                    content="Method content",
                    content_file=content_file,
                    task="diagram",
                    aspect_ratio="16:9",
                    out_path=out_path,
                )

        self.assertEqual(code, 0)
        command = run_mock.call_args.args[0]
        self.assertIn("gpt-5.5", command)
        self.assertIn('model_reasoning_effort="xhigh"', command)
        self.assertIn("--add-dir", command)
        self.assertTrue((out_path.parent / ".paperbanana_codex_handoff" / "figure.prompt.md").exists())


class SemanticScholarSharedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.shared_path = Path("/Users/jeff/paper-orchestra/skills/literature-review-agent/scripts/s2_shared.py")
        self.search_path = Path("/Users/jeff/paper-orchestra/skills/literature-review-agent/scripts/s2_search.py")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_shared_cache_short_circuits_live_network_calls(self) -> None:
        shared = _load_module("s2_shared_test", self.shared_path)
        s2_search = _load_module("s2_search_test", self.search_path)
        db_path = self.root / "s2.sqlite3"

        shared.store_cached_response(db_path, "Attention Is All You Need", {
            "total": 1,
            "data": [{"title": "Attention Is All You Need"}],
        })

        with mock.patch.dict(os.environ, {"PAPERORCHESTRA_S2_CACHE_DB": str(db_path)}, clear=False):
            with mock.patch.object(s2_search.urllib.request, "urlopen", side_effect=AssertionError("network should not be used")):
                response = s2_search.search("Attention Is All You Need", 5, s2_search.DEFAULT_FIELDS)

        self.assertEqual(response["data"][0]["title"], "Attention Is All You Need")

    def test_rate_limiter_waits_across_calls(self) -> None:
        shared = _load_module("s2_shared_rate_test", self.shared_path)
        db_path = self.root / "s2.sqlite3"

        shared.wait_for_rate_limit(db_path, interval_seconds=0.02)
        started = time.monotonic()
        shared.wait_for_rate_limit(db_path, interval_seconds=0.02)
        elapsed = time.monotonic() - started

        self.assertGreaterEqual(elapsed, 0.015)

    def test_search_uses_explicit_ssl_context_when_cert_bundle_is_available(self) -> None:
        s2_search = _load_module("s2_search_ssl_test", self.search_path)
        cert_path = self.root / "cert.pem"
        cert_path.write_text("dummy cert", encoding="utf-8")
        ssl_context = object()

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"total": 1, "data": [{"title": "Transformers"}]}'

        with mock.patch.dict(os.environ, {"SSL_CERT_FILE": str(cert_path)}, clear=False):
            with mock.patch.object(s2_search.ssl, "create_default_context", return_value=ssl_context):
                with mock.patch.object(s2_search.urllib.request, "urlopen", return_value=_Response()) as urlopen_mock:
                    response = s2_search.search("transformers", 1, "title", retries=1)

        self.assertEqual(response["data"][0]["title"], "Transformers")
        self.assertIs(urlopen_mock.call_args.kwargs["context"], ssl_context)


class WriterExecutorTests(unittest.TestCase):
    def test_build_command_uses_repo_root_workspace_and_transcript(self) -> None:
        from gui_app import writer_executor

        executor = writer_executor.WriterExecutor(Path("/tmp/repo"))
        command = executor.build_command(
            workspace=Path("/tmp/workspace"),
            transcript_path=Path("/tmp/out.txt"),
            prompt="Run the stage",
            env={"CODEX_BIN": "/usr/local/bin/codex"},
        )

        self.assertEqual(command[0], "/usr/local/bin/codex")
        self.assertNotIn("--search", command)
        self.assertIn("/tmp/repo", command)
        self.assertIn("/tmp/workspace", command)
        self.assertIn("/tmp/out.txt", command)
        self.assertEqual(command[-1], "Run the stage")

    def test_build_command_honors_model_and_reasoning_env_overrides(self) -> None:
        from gui_app import writer_executor

        executor = writer_executor.WriterExecutor(Path("/tmp/repo"))
        command = executor.build_command(
            workspace=Path("/tmp/workspace"),
            transcript_path=Path("/tmp/out.txt"),
            prompt="Run the stage",
            env={
                "CODEX_BIN": "codex",
                "PAPERORCHESTRA_CODEX_MODEL": "gpt-5.4-mini",
                "PAPERORCHESTRA_CODEX_REASONING_EFFORT": "low",
            },
        )

        self.assertIn("gpt-5.4-mini", command)
        self.assertIn('model_reasoning_effort="low"', command)

    def test_build_command_includes_output_schema_when_requested(self) -> None:
        from gui_app import writer_executor

        executor = writer_executor.WriterExecutor(Path("/tmp/repo"))
        command = executor.build_command(
            workspace=Path("/tmp/workspace"),
            transcript_path=Path("/tmp/out.txt"),
            prompt="Return JSON only",
            env={"CODEX_BIN": "codex"},
            output_schema_path=Path("/tmp/schema.json"),
        )

        self.assertIn("--output-schema", command)
        self.assertIn("/tmp/schema.json", command)

    def test_build_command_allows_sandbox_override(self) -> None:
        from gui_app import writer_executor

        executor = writer_executor.WriterExecutor(Path("/tmp/repo"))
        command = executor.build_command(
            workspace=Path("/tmp/workspace"),
            transcript_path=Path("/tmp/out.txt"),
            prompt="Return JSON only",
            env={"CODEX_BIN": "codex"},
            sandbox_mode="read-only",
        )

        sandbox_index = command.index("--sandbox")
        self.assertEqual(command[sandbox_index + 1], "read-only")

    def test_run_stage_disables_stdin_inheritance(self) -> None:
        from gui_app import writer_executor

        executor = writer_executor.WriterExecutor(Path("/tmp/repo"))
        with tempfile.TemporaryDirectory() as tempdir:
            log_path = Path(tempdir) / "stage.log"
            transcript_path = Path(tempdir) / "out.txt"

            with mock.patch("gui_app.writer_executor.subprocess.run") as run_mock:
                run_mock.return_value.returncode = 0
                executor.run_stage(
                    workspace=Path("/tmp/workspace"),
                    transcript_path=transcript_path,
                    prompt="Run the stage",
                    log_path=log_path,
                    env={"CODEX_BIN": "codex"},
                )

        self.assertEqual(run_mock.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_run_stage_recovers_structured_output_from_log_after_timeout(self) -> None:
        from gui_app import writer_executor

        executor = writer_executor.WriterExecutor(Path("/tmp/repo"))
        with tempfile.TemporaryDirectory() as tempdir:
            log_path = Path(tempdir) / "stage.log"
            transcript_path = Path(tempdir) / "out.json"
            log_path.write_text(
                "\n".join([
                    "$ codex exec ...",
                    json.dumps({
                        "plotting_plan": [],
                        "intro_related_work_plan": {},
                        "section_plan": [],
                    }),
                ]) + "\n",
                encoding="utf-8",
            )

            with mock.patch("gui_app.writer_executor.subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 5.0)):
                result = executor.run_stage(
                    workspace=Path("/tmp/workspace"),
                    transcript_path=transcript_path,
                    prompt="Return the outline JSON",
                    log_path=log_path,
                    env={
                        "CODEX_BIN": "codex",
                        "PAPERORCHESTRA_CODEX_OUTPUT_TIMEOUT_SECONDS": "5",
                    },
                    output_schema_path=Path("/tmp/schema.json"),
                )

            self.assertTrue(transcript_path.exists())
            self.assertTrue(result["recovered_from_log"])
            recovered = json.loads(transcript_path.read_text(encoding="utf-8"))
            self.assertIn("plotting_plan", recovered)

    def test_global_timeout_override_applies_to_all_stage_runs(self) -> None:
        from gui_app import writer_executor

        executor = writer_executor.WriterExecutor(Path("/tmp/repo"))
        with tempfile.TemporaryDirectory() as tempdir:
            log_path = Path(tempdir) / "stage.log"
            transcript_path = Path(tempdir) / "out.txt"

            with mock.patch("gui_app.writer_executor.subprocess.run") as run_mock:
                run_mock.return_value.returncode = 0
                executor.run_stage(
                    workspace=Path("/tmp/workspace"),
                    transcript_path=transcript_path,
                    prompt="Run the stage",
                    log_path=log_path,
                    env={
                        "CODEX_BIN": "codex",
                        "PAPERORCHESTRA_CODEX_TIMEOUT_SECONDS": "12",
                    },
                )

        self.assertEqual(run_mock.call_args.kwargs["timeout"], 12.0)


class ConfigTests(unittest.TestCase):
    def test_atlas_can_be_disabled_via_env(self) -> None:
        from gui_app import config

        health = config.integration_health({"PAPERORCHESTRA_ATLAS_ENABLED": "0"})

        self.assertFalse(health["atlas"]["enabled"])
        self.assertFalse(health["atlas"]["available"])

    def test_integration_health_reports_chrome_runtime_and_browser_defaults(self) -> None:
        from gui_app import config

        fake_global_health = {
            "registered": True,
            "wrapper_exists": True,
            "helper_exists": True,
            "wrapper_path": "/Users/jeff/.codex/bin/chrome-devtools-mcp-wrapper",
            "helper_path": "/Users/jeff/.codex/bin/chrome-debug-profile",
            "config_path": "/Users/jeff/.codex/config.toml",
            "local_root": "/Users/jeff/.paperorchestra/adapters/chrome-devtools-mcp-main",
            "local_root_exists": True,
            "local_build_exists": True,
            "default_browser_url": "http://127.0.0.1:9333",
            "debug_browser_app_path": "/Applications/Google Chrome for Testing.app",
            "debug_browser_app_exists": True,
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": True,
                "version": "147.0.7727.57",
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": True,
                "account_present": True,
                "account_label": "Jeffrey",
                "running": True,
                "debuggable": True,
                "browser_url": "http://127.0.0.1:9333",
                "ws_endpoint": "ws://127.0.0.1:9333/devtools/browser/example",
                "relaunch_required": False,
            },
            "chrome_stable": {
                "runtime": "chrome_stable",
                "app_path": "/Applications/Google Chrome.app",
                "installed": True,
                "version": "147.0.7727.57",
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
                "profile_exists": True,
                "account_present": True,
                "account_label": "Jeffrey",
                "running": True,
                "debuggable": True,
                "browser_url": "http://127.0.0.1:9222",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
        }

        with mock.patch.object(config, "CHROME_APP_PATH", Path("/Applications/Google Chrome.app")):
            with mock.patch.object(config, "_read_app_version", return_value="147.0.7727.57"):
                with mock.patch.object(config.shutil, "which", side_effect=lambda name, path=None: {
                    "codex": "/opt/homebrew/bin/codex",
                    "node": "/opt/homebrew/bin/node",
                    "npx": "/opt/homebrew/bin/npx",
                }.get(name)):
                    with mock.patch("gui_app.config.global_browser_setup.global_setup_health", return_value=fake_global_health):
                        health = config.integration_health({})

        self.assertTrue(health["chrome"]["available"])
        self.assertTrue(health["chrome"]["compatible"])
        self.assertTrue(health["chrome"]["mcp_available"])
        self.assertEqual(health["chrome"]["attach_mode"], "chrome_for_testing_first")
        self.assertEqual(health["browser_adapter"]["primary"], "chrome_devtools")
        self.assertEqual(health["browser_adapter"]["attach_mode"], "chrome_for_testing_first")
        self.assertEqual(
            health["browser_adapter"]["fallback_order"],
            ["chrome_for_testing", "chrome_stable", "atlas", "local"],
        )
        self.assertTrue(health["chrome_for_testing"]["installed"])
        self.assertTrue(health["chrome_for_testing"]["debuggable"])
        self.assertEqual(health["chrome_for_testing"]["browser_url"], "http://127.0.0.1:9333")
        self.assertTrue(health["chrome_stable"]["debuggable"])

    def test_integration_health_reports_global_chrome_setup(self) -> None:
        from gui_app import config

        fake_global_health = {
            "registered": True,
            "wrapper_exists": True,
            "helper_exists": True,
            "wrapper_path": "/Users/jeff/.codex/bin/chrome-devtools-mcp-wrapper",
            "helper_path": "/Users/jeff/.codex/bin/chrome-debug-profile",
            "config_path": "/Users/jeff/.codex/config.toml",
            "local_root": "/Users/jeff/.paperorchestra/adapters/chrome-devtools-mcp-main",
            "local_root_exists": True,
            "local_build_exists": True,
            "default_browser_url": "http://127.0.0.1:9333",
            "debug_browser_app_path": "/Applications/Google Chrome for Testing.app",
            "debug_browser_app_exists": True,
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": True,
                "version": "147.0.7727.57",
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": True,
                "account_present": True,
                "account_label": "Jeffrey",
                "running": True,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": True,
            },
            "chrome_stable": {
                "runtime": "chrome_stable",
                "app_path": "/Applications/Google Chrome.app",
                "installed": True,
                "version": "147.0.7727.57",
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
                "profile_exists": True,
                "account_present": True,
                "account_label": "Jeffrey",
                "running": True,
                "debuggable": True,
                "browser_url": "http://127.0.0.1:9222",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
        }

        with mock.patch("gui_app.config.global_browser_setup.global_setup_health", return_value=fake_global_health):
            health = config.integration_health({})

        self.assertTrue(health["chrome"]["global_registered"])
        self.assertTrue(health["chrome"]["wrapper_exists"])
        self.assertTrue(health["chrome"]["helper_exists"])
        self.assertTrue(health["chrome"]["local_build_exists"])
        self.assertEqual(health["chrome"]["wrapper_path"], fake_global_health["wrapper_path"])
        self.assertEqual(health["chrome"]["debug_browser_app_path"], fake_global_health["debug_browser_app_path"])
        self.assertTrue(health["chrome_for_testing"]["relaunch_required"])
        self.assertEqual(health["chrome_stable"]["browser_url"], "http://127.0.0.1:9222")


class GlobalBrowserSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_install_or_repair_writes_wrapper_helper_and_mcp_block(self) -> None:
        from gui_app import global_browser_setup

        codex_home = self.root / ".codex"
        config_path = codex_home / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            '[mcp_servers.openaiDeveloperDocs]\nurl = "https://developers.openai.com/mcp"\n',
            encoding="utf-8",
        )
        local_root = self.root / "chrome-devtools-mcp-main"
        build_bin = local_root / "build" / "src" / "bin"
        build_bin.mkdir(parents=True, exist_ok=True)
        (local_root / "package.json").write_text('{"name":"chrome-devtools-mcp"}\n', encoding="utf-8")
        (build_bin / "chrome-devtools-mcp.js").write_text("console.log('ok')\n", encoding="utf-8")

        with mock.patch("gui_app.global_browser_setup._verify_with_codex_mcp_list", return_value=["chrome-devtools"]):
            result = global_browser_setup.install_or_repair({
                "CODEX_HOME": str(codex_home),
                "PAPERORCHESTRA_CHROME_MCP_PATH": str(local_root),
            })

        wrapper_path = codex_home / "bin" / "chrome-devtools-mcp-wrapper"
        helper_path = codex_home / "bin" / "chrome-debug-profile"
        self.assertTrue(wrapper_path.exists())
        self.assertTrue(helper_path.exists())
        self.assertTrue(os.access(wrapper_path, os.X_OK))
        self.assertTrue(os.access(helper_path, os.X_OK))
        config_text = config_path.read_text(encoding="utf-8")
        self.assertIn("[mcp_servers.chrome-devtools]", config_text)
        self.assertIn(str(wrapper_path), config_text)
        self.assertEqual(result["mcp_server_name"], "chrome-devtools")
        self.assertIn("Google Chrome for Testing.app", wrapper_path.read_text(encoding="utf-8"))
        self.assertIn("Library/Application Support/Google/Chrome for Testing", wrapper_path.read_text(encoding="utf-8"))

        with mock.patch("gui_app.global_browser_setup._verify_with_codex_mcp_list", return_value=["chrome-devtools"]):
            global_browser_setup.install_or_repair({
                "CODEX_HOME": str(codex_home),
                "PAPERORCHESTRA_CHROME_MCP_PATH": str(local_root),
            })
        self.assertEqual(
            config_path.read_text(encoding="utf-8").count("[mcp_servers.chrome-devtools]"),
            1,
        )

    def test_launch_debug_profile_uses_dedicated_port_and_profile(self) -> None:
        from gui_app import global_browser_setup

        codex_home = self.root / ".codex"
        app = self.root / "Google Chrome for Testing.app"
        executable = app / "Contents" / "MacOS" / "Google Chrome for Testing"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("", encoding="utf-8")
        with mock.patch("gui_app.global_browser_setup.subprocess.Popen") as popen_mock:
            global_browser_setup.launch_debug_profile({
                "CODEX_HOME": str(codex_home),
                "PAPERORCHESTRA_CHROME_DEBUG_APP_PATH": str(app),
            })

        command = popen_mock.call_args.args[0]
        self.assertIn("--remote-debugging-port=9333", command)
        self.assertTrue(any("Library/Application Support/Google/Chrome for Testing" in item for item in command))
        self.assertEqual(command[0], str(executable))

    def test_launch_debug_profile_prefers_configured_debug_browser_app(self) -> None:
        from gui_app import global_browser_setup

        codex_home = self.root / ".codex"
        debug_app = self.root / "Google Chrome for Testing.app"
        debug_executable = debug_app / "Contents" / "MacOS" / "Google Chrome for Testing"
        debug_executable.parent.mkdir(parents=True, exist_ok=True)
        debug_executable.write_text("", encoding="utf-8")
        with mock.patch("gui_app.global_browser_setup.subprocess.Popen") as popen_mock:
            global_browser_setup.launch_debug_profile({
                "CODEX_HOME": str(codex_home),
                "PAPERORCHESTRA_CHROME_DEBUG_APP_PATH": str(debug_app),
            })

        command = popen_mock.call_args.args[0]
        self.assertEqual(command[0], str(debug_executable))

    def test_browser_running_matches_executable_path_for_app_bundle(self) -> None:
        from gui_app import global_browser_setup

        app = self.root / "Google Chrome for Testing.app"
        executable = app / "Contents" / "MacOS" / "Google Chrome for Testing"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("", encoding="utf-8")

        with mock.patch("gui_app.global_browser_setup._process_listing", return_value=f"{executable} --user-data-dir=/tmp/profile\n"):
            self.assertTrue(global_browser_setup._browser_running(app))

    def test_browser_url_from_profile_requires_live_debug_http_endpoint(self) -> None:
        from gui_app import global_browser_setup

        profile = self.root / "Chrome for Testing"
        profile.mkdir(parents=True, exist_ok=True)
        (profile / "DevToolsActivePort").write_text("9333\n/devtools/browser/example\n", encoding="utf-8")

        with mock.patch("gui_app.global_browser_setup._debug_version_payload", return_value={}):
            self.assertEqual(global_browser_setup._browser_targets_from_profile(profile, "http://127.0.0.1:9333"), ("", ""))

    def test_browser_targets_from_profile_uses_active_port_when_http_ready(self) -> None:
        from gui_app import global_browser_setup

        profile = self.root / "Chrome for Testing"
        profile.mkdir(parents=True, exist_ok=True)
        (profile / "DevToolsActivePort").write_text("9222\n/devtools/browser/example\n", encoding="utf-8")

        with mock.patch(
            "gui_app.global_browser_setup._debug_version_payload",
            return_value={"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/example"},
        ):
            self.assertEqual(
                global_browser_setup._browser_targets_from_profile(profile, "http://127.0.0.1:9333"),
                ("http://127.0.0.1:9222", "ws://127.0.0.1:9222/devtools/browser/example"),
            )


class ChromeDevToolsAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_mcp_client_initializes_and_lists_tools(self) -> None:
        from gui_app import chrome_devtools_adapter

        def frame(payload: dict[str, object]) -> bytes:
            return (json.dumps(payload) + "\n").encode("utf-8")

        responses = b"".join([
            frame({
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "serverInfo": {"name": "chrome-devtools-mcp", "version": "0.21.0"},
                },
            }),
            frame({
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "tools": [
                        {"name": "new_page"},
                        {"name": "take_snapshot"},
                        {"name": "evaluate_script"},
                    ],
                },
            }),
        ])

        class _FakeProcess:
            def __init__(self) -> None:
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO(responses)
                self.stderr = io.BytesIO()
                self.returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.returncode = 0
                return 0

            def terminate(self):
                self.returncode = 0

            def kill(self):
                self.returncode = -9

        with mock.patch("gui_app.chrome_devtools_adapter.subprocess.Popen", return_value=_FakeProcess()):
            client = chrome_devtools_adapter.ChromeDevToolsMcpClient(
                env={"PAPERORCHESTRA_CHROME_MCP_PATH": str(self.root / "missing")},
            )
            with client.session(timeout_seconds=5.0) as session:
                session.initialize()
                tools = session.list_tools()

        self.assertIn("new_page", tools)
        self.assertIn("take_snapshot", tools)

    def test_mcp_stdio_session_uses_newline_delimited_json(self) -> None:
        from gui_app import chrome_devtools_adapter

        class _NoFilenoBytesIO(io.BytesIO):
            def fileno(self):
                raise io.UnsupportedOperation("no fileno")

        class _FakeProcess:
            def __init__(self) -> None:
                self.stdin = io.BytesIO()
                self.stdout = _NoFilenoBytesIO(
                    (json.dumps({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"protocolVersion": "2025-03-26"},
                    }) + "\n").encode("utf-8")
                )
                self.stderr = io.BytesIO()

        process = _FakeProcess()
        session = chrome_devtools_adapter.McpStdioSession(process, timeout_seconds=1.0)
        response = session._request("initialize", {"protocolVersion": "2025-03-26"})

        self.assertEqual(response["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(
            process.stdin.getvalue().decode("utf-8"),
            json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26"},
            }) + "\n",
        )

    def test_extract_json_payload_parses_fenced_evaluate_script_output(self) -> None:
        from gui_app import chrome_devtools_adapter

        payload = {
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": 'Script ran on page and returned:\n```json\n{"composerFound":true,"authRequired":false}\n```',
                    }
                ]
            }
        }

        parsed = chrome_devtools_adapter._extract_json_payload(payload)

        self.assertEqual(parsed, {"composerFound": True, "authRequired": False})

    def test_parse_pages_text_extracts_chatgpt_pages(self) -> None:
        from gui_app import chrome_devtools_adapter

        payload = {
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": "## Pages\n1: about:blank\n2: https://chatgpt.com/ [selected]\n3: https://example.com/\n",
                    }
                ]
            }
        }

        pages = chrome_devtools_adapter._parse_pages_text(payload)

        self.assertEqual(pages[1]["page_id"], 2)
        self.assertEqual(pages[1]["url"], "https://chatgpt.com/")
        self.assertTrue(pages[1]["selected"])

    def test_classify_chatgpt_readiness_detects_composer_ready(self) -> None:
        from gui_app import chrome_devtools_adapter

        readiness = chrome_devtools_adapter._classify_chatgpt_readiness(
            {
                "title": "ChatGPT",
                "url": "https://chatgpt.com/c/example",
                "composerFound": True,
                "textPreview": "ChatGPT conversation",
            },
            'textbox "Chat with ChatGPT"\nbutton "Send prompt"\n',
        )

        self.assertEqual(readiness["state"], "composer_ready")

    def test_classify_chatgpt_readiness_detects_challenge_block(self) -> None:
        from gui_app import chrome_devtools_adapter

        readiness = chrome_devtools_adapter._classify_chatgpt_readiness(
            {
                "title": "Just a moment...",
                "url": "https://chatgpt.com/",
                "composerFound": False,
                "textPreview": "Checking your browser before accessing ChatGPT",
            },
            "",
        )

        self.assertEqual(readiness["state"], "challenge_blocked")

    def test_classify_chatgpt_readiness_detects_auth_wall(self) -> None:
        from gui_app import chrome_devtools_adapter

        readiness = chrome_devtools_adapter._classify_chatgpt_readiness(
            {
                "title": "Welcome back",
                "url": "https://chatgpt.com/auth/login",
                "composerFound": False,
                "textPreview": "Log in to continue with Google",
            },
            "",
        )

        self.assertEqual(readiness["state"], "auth_blocked")

    def test_classify_chatgpt_response_state_detects_waiting_and_missing_output(self) -> None:
        from gui_app import chrome_devtools_adapter

        waiting = chrome_devtools_adapter._classify_chatgpt_response_state(
            'heading "ChatGPT said:"\nbutton "Stop streaming"\nStaticText "Researching sources"\n',
            "",
        )
        missing = chrome_devtools_adapter._classify_chatgpt_response_state(
            'textbox "Chat with ChatGPT"\nbutton "Send prompt"\n',
            "",
        )
        captured = chrome_devtools_adapter._classify_chatgpt_response_state(
            'heading "ChatGPT said:"\nStaticText "Paper A: useful summary"\n',
            "Paper A: useful summary",
        )
        sidebar_only = chrome_devtools_adapter._classify_chatgpt_response_state(
            'button "Search chats"\nlink "Deep research meta prompts"\ntextbox "Chat with ChatGPT"\n',
            "",
        )

        self.assertEqual(waiting["state"], "submitted_waiting")
        self.assertEqual(waiting["reason"], "chatgpt_submitted_waiting")
        self.assertEqual(missing["state"], "response_not_extractable")
        self.assertEqual(missing["reason"], "chatgpt_response_not_extractable")
        self.assertEqual(captured["state"], "response_captured")
        self.assertEqual(captured["reason"], "chatgpt_response_captured")
        self.assertEqual(sidebar_only["state"], "response_not_extractable")

    def test_extract_assistant_text_from_page_state_prefers_dom_assistant_text(self) -> None:
        from gui_app import chrome_devtools_adapter

        text = chrome_devtools_adapter._assistant_text_from_page_state({
            "assistantText": " Paper A: relevant evidence. ",
            "pending": False,
        })

        self.assertEqual(text, "Paper A: relevant evidence.")

    def test_client_prefers_local_built_checkout_when_available(self) -> None:
        from gui_app import chrome_devtools_adapter

        local_root = self.root / "chrome-devtools-mcp-main"
        build_bin = local_root / "build" / "src" / "bin"
        build_bin.mkdir(parents=True, exist_ok=True)
        (local_root / "package.json").write_text('{"name":"chrome-devtools-mcp"}\n', encoding="utf-8")
        (build_bin / "chrome-devtools-mcp.js").write_text("console.log('ok')\n", encoding="utf-8")

        client = chrome_devtools_adapter.ChromeDevToolsMcpClient(
            env={"PAPERORCHESTRA_CHROME_MCP_PATH": str(local_root)},
        )
        command = client.command()

        self.assertEqual(command[0], "node")
        self.assertEqual(command[1], str(build_bin / "chrome-devtools-mcp.js"))
        self.assertIn("--autoConnect", command)

    def test_browser_url_attach_omits_conflicting_launch_flags(self) -> None:
        from gui_app import chrome_devtools_adapter

        client = chrome_devtools_adapter.ChromeDevToolsMcpClient(
            attach_mode="browser_url",
            browser_url="http://127.0.0.1:9222",
            executable_path="/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
            user_data_dir="/Users/jeff/Library/Application Support/Google/Chrome",
        )

        command = client.command()

        self.assertIn("--browserUrl=http://127.0.0.1:9222", command)
        self.assertFalse(any(flag.startswith("--executablePath=") for flag in command))
        self.assertFalse(any(flag.startswith("--userDataDir=") for flag in command))

    def test_ws_endpoint_attach_prefers_websocket_over_browser_url(self) -> None:
        from gui_app import chrome_devtools_adapter

        client = chrome_devtools_adapter.ChromeDevToolsMcpClient(
            attach_mode="ws_endpoint",
            browser_url="http://127.0.0.1:9222",
            ws_endpoint="ws://127.0.0.1:9222/devtools/browser/example",
            executable_path="/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
            user_data_dir="/Users/jeff/Library/Application Support/Google/Chrome for Testing",
        )

        command = client.command()

        self.assertIn("--wsEndpoint=ws://127.0.0.1:9222/devtools/browser/example", command)
        self.assertFalse(any(flag.startswith("--browserUrl=") for flag in command))
        self.assertFalse(any(flag.startswith("--executablePath=") for flag in command))
        self.assertFalse(any(flag.startswith("--userDataDir=") for flag in command))

    @mock.patch("gui_app.chrome_devtools_adapter.global_browser_setup.global_setup_health")
    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsMcpClient")
    def test_run_task_prefers_ws_endpoint_for_debuggable_cft(
        self,
        client_cls: mock.Mock,
        global_health: mock.Mock,
    ) -> None:
        from gui_app import chrome_devtools_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        global_health.return_value = {
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": True,
                "running": True,
                "debuggable": True,
                "browser_url": "http://127.0.0.1:9222",
                "ws_endpoint": "ws://127.0.0.1:9222/devtools/browser/example",
                "relaunch_required": False,
            },
            "chrome_stable": {
                "runtime": "chrome_stable",
                "app_path": "/Applications/Google Chrome.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
                "profile_exists": True,
                "running": False,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
        }
        client = client_cls.return_value
        client.attach_mode = "ws_endpoint"
        client.run_chatgpt_prompt.return_value = {
            "task_type": "literature",
            "response_text": "Chrome for Testing response",
            "summary": "Chrome for Testing task completed.",
            "browser_runtime": "chrome_for_testing",
            "attach_transport": "ws_endpoint",
            "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
        }

        adapter = chrome_devtools_adapter.ChromeDevToolsAdapter(self.root / "gui-data")
        result = adapter.run_task(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            prompt_text="Find literature",
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["browser_runtime"], "chrome_for_testing")
        self.assertEqual(result["attach_transport"], "ws_endpoint")
        self.assertEqual(client_cls.call_args.kwargs["attach_mode"], "ws_endpoint")
        self.assertEqual(
            client_cls.call_args.kwargs["ws_endpoint"],
            "ws://127.0.0.1:9222/devtools/browser/example",
        )
        self.assertEqual(client_cls.call_args.kwargs["browser_url"], "http://127.0.0.1:9222")

    @mock.patch("gui_app.chrome_devtools_adapter.global_browser_setup.global_setup_health")
    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsMcpClient")
    def test_run_task_empty_chatgpt_response_becomes_attention_required(
        self,
        client_cls: mock.Mock,
        global_health: mock.Mock,
    ) -> None:
        from gui_app import chrome_devtools_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        global_health.return_value = {
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": True,
                "running": True,
                "debuggable": True,
                "browser_url": "http://127.0.0.1:9222",
                "ws_endpoint": "ws://127.0.0.1:9222/devtools/browser/example",
                "relaunch_required": False,
            },
            "chrome_stable": {
                "runtime": "chrome_stable",
                "app_path": "/Applications/Google Chrome.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
                "profile_exists": True,
                "running": False,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
        }
        client = client_cls.return_value
        client.attach_mode = "ws_endpoint"
        client.run_chatgpt_prompt.return_value = {
            "task_type": "literature",
            "status": "succeeded",
            "response_text": "",
            "raw_response_path": "",
            "summary": "Chrome DevTools MCP submitted a browser task.",
            "browser_runtime": "chrome_for_testing",
            "attach_transport": "ws_endpoint",
            "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
            "readiness_state": "composer_ready",
            "readiness_message": "ChatGPT composer is ready.",
            "tab_reused": True,
        }

        adapter = chrome_devtools_adapter.ChromeDevToolsAdapter(self.root / "gui-data")
        result = adapter.run_task(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            prompt_text="Find literature",
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )

        self.assertEqual(result["status"], "attention_required")
        self.assertEqual(result["readiness_state"], "response_not_extractable")
        self.assertEqual(result["attention_required"]["reason"], "chatgpt_response_not_extractable")
        self.assertEqual(result["raw_response_path"], "")
        self.assertEqual(result["browser_runtime"], "chrome_for_testing")

    @mock.patch("gui_app.chrome_devtools_adapter.global_browser_setup.global_setup_health")
    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsMcpClient")
    def test_run_task_prefers_stable_attach_before_cft_cold_launch(
        self,
        client_cls: mock.Mock,
        global_health: mock.Mock,
    ) -> None:
        from gui_app import chrome_devtools_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        global_health.return_value = {
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": True,
                "running": False,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
            "chrome_stable": {
                "runtime": "chrome_stable",
                "app_path": "/Applications/Google Chrome.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
                "profile_exists": True,
                "running": True,
                "debuggable": True,
                "browser_url": "http://127.0.0.1:9222",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
        }
        client = client_cls.return_value
        client.attach_mode = "browser_url"
        client.run_chatgpt_prompt.return_value = {
            "task_type": "literature",
            "response_text": "Stable Chrome response",
            "summary": "Stable Chrome task completed.",
            "browser_runtime": "chrome_stable",
            "attach_transport": "browser_url",
            "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
        }

        adapter = chrome_devtools_adapter.ChromeDevToolsAdapter(self.root / "gui-data")
        result = adapter.run_task(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            prompt_text="Find literature",
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["browser_runtime"], "chrome_stable")
        self.assertEqual(result["attach_transport"], "browser_url")
        self.assertEqual(result["profile_root"], "/Users/jeff/Library/Application Support/Google/Chrome")
        self.assertEqual(client_cls.call_args.kwargs["attach_mode"], "browser_url")
        self.assertEqual(client_cls.call_args.kwargs["browser_url"], "http://127.0.0.1:9222")

    @mock.patch("gui_app.chrome_devtools_adapter.global_browser_setup.global_setup_health")
    def test_build_runtime_attempts_does_not_add_stable_auto_connect_cold_start(
        self,
        global_health: mock.Mock,
    ) -> None:
        from gui_app import chrome_devtools_adapter

        global_health.return_value = {
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": True,
                "running": False,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
            "chrome_stable": {
                "runtime": "chrome_stable",
                "app_path": "/Applications/Google Chrome.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
                "profile_exists": True,
                "running": False,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
        }

        adapter = chrome_devtools_adapter.ChromeDevToolsAdapter(self.root / "gui-data")
        attempts, _ = adapter._build_runtime_attempts()

        self.assertEqual(attempts, [])

    @mock.patch("gui_app.chrome_devtools_adapter.global_browser_setup.global_setup_health")
    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsMcpClient")
    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsAdapter._launch_cft_debug_helper_if_needed")
    def test_run_task_bootstraps_cft_helper_when_no_debuggable_browser_exists(
        self,
        launch_helper: mock.Mock,
        client_cls: mock.Mock,
        global_health: mock.Mock,
    ) -> None:
        from gui_app import chrome_devtools_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        cold_health = {
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": True,
                "running": False,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
            "chrome_stable": {
                "runtime": "chrome_stable",
                "app_path": "/Applications/Google Chrome.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
                "profile_exists": True,
                "running": False,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
        }
        warm_health = {
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": True,
                "running": True,
                "debuggable": True,
                "browser_url": "http://127.0.0.1:9222",
                "ws_endpoint": "ws://127.0.0.1:9222/devtools/browser/example",
                "relaunch_required": False,
            },
            "chrome_stable": {
                "runtime": "chrome_stable",
                "app_path": "/Applications/Google Chrome.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
                "profile_exists": True,
                "running": False,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
        }
        global_health.side_effect = [cold_health, warm_health, warm_health]
        launch_helper.return_value = True
        client = client_cls.return_value
        client.attach_mode = "ws_endpoint"
        client.run_chatgpt_prompt.return_value = {
            "task_type": "literature",
            "response_text": "Chrome for Testing response",
            "summary": "Chrome for Testing task completed.",
            "browser_runtime": "chrome_for_testing",
            "attach_transport": "ws_endpoint",
            "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
        }

        adapter = chrome_devtools_adapter.ChromeDevToolsAdapter(self.root / "gui-data")
        result = adapter.run_task(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            prompt_text="Find literature",
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )

        self.assertEqual(result["status"], "succeeded")
        launch_helper.assert_called_once()
        self.assertEqual(client_cls.call_args.kwargs["attach_mode"], "ws_endpoint")
        self.assertEqual(client_cls.call_args.kwargs["ws_endpoint"], "ws://127.0.0.1:9222/devtools/browser/example")

    @mock.patch("gui_app.chrome_devtools_adapter.global_browser_setup.global_setup_health")
    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsMcpClient")
    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsAdapter._launch_cft_debug_helper_if_needed")
    def test_run_task_bootstraps_cft_after_stable_transport_timeout(
        self,
        launch_helper: mock.Mock,
        client_cls: mock.Mock,
        global_health: mock.Mock,
    ) -> None:
        from gui_app import chrome_devtools_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        stable_first_health = {
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": True,
                "running": False,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
            "chrome_stable": {
                "runtime": "chrome_stable",
                "app_path": "/Applications/Google Chrome.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
                "profile_exists": True,
                "running": True,
                "debuggable": True,
                "browser_url": "http://127.0.0.1:9222",
                "ws_endpoint": "ws://127.0.0.1:9222/devtools/browser/stable",
                "relaunch_required": False,
            },
        }
        cft_ready_health = {
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": True,
                "running": True,
                "debuggable": True,
                "browser_url": "http://127.0.0.1:9333",
                "ws_endpoint": "ws://127.0.0.1:9333/devtools/browser/cft",
                "relaunch_required": False,
            },
            "chrome_stable": stable_first_health["chrome_stable"],
        }
        global_health.side_effect = [
            stable_first_health,
            stable_first_health,
            stable_first_health,
            cft_ready_health,
        ]
        launch_helper.return_value = True
        stable_client = mock.Mock()
        stable_client.attach_mode = "ws_endpoint"
        stable_client.run_chatgpt_prompt.side_effect = TimeoutError("Timed out waiting for MCP response header.")
        cft_client = mock.Mock()
        cft_client.attach_mode = "ws_endpoint"
        cft_client.run_chatgpt_prompt.return_value = {
            "task_type": "literature",
            "response_text": "Chrome for Testing response",
            "summary": "Chrome for Testing task completed.",
            "browser_runtime": "chrome_for_testing",
            "attach_transport": "ws_endpoint",
            "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
            "readiness_state": "composer_ready",
            "readiness_message": "ChatGPT composer is ready.",
            "tab_reused": True,
        }
        client_cls.side_effect = [stable_client, cft_client]

        adapter = chrome_devtools_adapter.ChromeDevToolsAdapter(self.root / "gui-data")
        result = adapter.run_task(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            prompt_text="Find literature",
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["browser_runtime"], "chrome_for_testing")
        self.assertEqual(client_cls.call_count, 2)
        launch_helper.assert_called_once()

    @mock.patch("gui_app.chrome_devtools_adapter.global_browser_setup.global_setup_health")
    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsMcpClient")
    def test_run_task_falls_back_to_stable_when_cft_requires_relaunch(
        self,
        client_cls: mock.Mock,
        global_health: mock.Mock,
    ) -> None:
        from gui_app import chrome_devtools_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        global_health.return_value = {
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": True,
                "running": True,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": True,
            },
            "chrome_stable": {
                "runtime": "chrome_stable",
                "app_path": "/Applications/Google Chrome.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
                "profile_exists": True,
                "running": True,
                "debuggable": True,
                "browser_url": "http://127.0.0.1:9222",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
        }
        stable_client = mock.Mock()
        stable_client.attach_mode = "browser_url"
        stable_client.run_chatgpt_prompt.return_value = {
            "task_type": "literature",
            "response_text": "Stable Chrome response",
            "summary": "Stable Chrome task completed.",
            "browser_runtime": "chrome_stable",
            "attach_transport": "browser_url",
            "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
            "fallback_reason": "Chrome for Testing must be relaunched in debug mode; falling back to stable Chrome.",
        }
        client_cls.side_effect = [stable_client]

        adapter = chrome_devtools_adapter.ChromeDevToolsAdapter(self.root / "gui-data")
        result = adapter.run_task(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            prompt_text="Find literature",
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["browser_runtime"], "chrome_stable")
        self.assertEqual(result["attach_transport"], "browser_url")
        self.assertIn("Chrome for Testing must be relaunched", result["fallback_reason"])
        self.assertEqual(client_cls.call_args.kwargs["browser_url"], "http://127.0.0.1:9222")

    @mock.patch("gui_app.chrome_devtools_adapter.global_browser_setup.global_setup_health")
    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsMcpClient")
    def test_run_task_tries_stable_after_cft_challenge_blocked(
        self,
        client_cls: mock.Mock,
        global_health: mock.Mock,
    ) -> None:
        from gui_app import chrome_devtools_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        global_health.return_value = {
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": True,
                "running": True,
                "debuggable": True,
                "browser_url": "http://127.0.0.1:9222",
                "ws_endpoint": "ws://127.0.0.1:9222/devtools/browser/cft",
                "relaunch_required": False,
            },
            "chrome_stable": {
                "runtime": "chrome_stable",
                "app_path": "/Applications/Google Chrome.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
                "profile_exists": True,
                "running": True,
                "debuggable": True,
                "browser_url": "http://127.0.0.1:9333",
                "ws_endpoint": "ws://127.0.0.1:9333/devtools/browser/stable",
                "relaunch_required": False,
            },
        }
        cft_client = mock.Mock()
        cft_client.attach_mode = "ws_endpoint"
        cft_client.run_chatgpt_prompt.return_value = {
            "task_type": "literature",
            "status": "attention_required",
            "summary": "ChatGPT is blocked behind a browser challenge.",
            "browser_runtime": "chrome_for_testing",
            "attach_transport": "ws_endpoint",
            "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
            "readiness_state": "challenge_blocked",
            "readiness_message": "ChatGPT is blocked behind a browser challenge.",
            "tab_reused": True,
            "attention_required": {
                "reason": "chatgpt_challenge_blocked",
                "message": "Complete the challenge once.",
                "details": {"adapter": "chrome_devtools"},
            },
        }
        stable_client = mock.Mock()
        stable_client.attach_mode = "ws_endpoint"
        stable_client.run_chatgpt_prompt.return_value = {
            "task_type": "literature",
            "response_text": "Stable Chrome response",
            "summary": "Stable Chrome task completed.",
            "browser_runtime": "chrome_stable",
            "attach_transport": "ws_endpoint",
            "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
            "readiness_state": "composer_ready",
            "readiness_message": "ChatGPT composer is ready.",
            "tab_reused": True,
        }
        client_cls.side_effect = [cft_client, stable_client]

        adapter = chrome_devtools_adapter.ChromeDevToolsAdapter(self.root / "gui-data")
        result = adapter.run_task(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            prompt_text="Find literature",
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["browser_runtime"], "chrome_stable")
        self.assertEqual(client_cls.call_count, 2)

    @mock.patch("gui_app.chrome_devtools_adapter.global_browser_setup.global_setup_health")
    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsMcpClient")
    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsAdapter._launch_cft_debug_helper_if_needed")
    def test_run_task_returns_relaunch_required_when_no_stable_fallback_exists(
        self,
        launch_helper: mock.Mock,
        client_cls: mock.Mock,
        global_health: mock.Mock,
    ) -> None:
        from gui_app import chrome_devtools_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        launch_helper.return_value = False
        global_health.return_value = {
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": True,
                "running": True,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": True,
            },
            "chrome_stable": {
                "runtime": "chrome_stable",
                "app_path": "/Applications/Google Chrome.app",
                "installed": False,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
                "profile_exists": True,
                "running": False,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
        }

        adapter = chrome_devtools_adapter.ChromeDevToolsAdapter(self.root / "gui-data")
        result = adapter.run_task(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            prompt_text="Find literature",
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )

        self.assertEqual(result["status"], "attention_required")
        self.assertEqual(result["browser_runtime"], "chrome_for_testing")
        self.assertEqual(result["attention_required"]["reason"], "browser_bootstrap_failed")
        client_cls.assert_not_called()

    @mock.patch("gui_app.chrome_devtools_adapter.global_browser_setup.global_setup_health")
    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsAdapter._launch_cft_debug_helper_if_needed")
    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsMcpClient")
    def test_run_task_surfaces_bootstrap_failure_without_atlas_style_fallback(
        self,
        client_cls: mock.Mock,
        launch_helper: mock.Mock,
        global_health: mock.Mock,
    ) -> None:
        from gui_app import chrome_devtools_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        cold_health = {
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": True,
                "running": False,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
            "chrome_stable": {
                "runtime": "chrome_stable",
                "app_path": "/Applications/Google Chrome.app",
                "installed": False,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
                "profile_exists": False,
                "running": False,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
        }
        global_health.side_effect = [cold_health, cold_health]
        launch_helper.return_value = False

        adapter = chrome_devtools_adapter.ChromeDevToolsAdapter(self.root / "gui-data")
        result = adapter.run_task(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            prompt_text="Find literature",
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )

        self.assertEqual(result["status"], "attention_required")
        self.assertEqual(result["attention_required"]["reason"], "browser_bootstrap_failed")
        client_cls.assert_not_called()

    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsMcpClient")
    def test_run_task_timeout_surfaces_browser_approval_required(self, client_cls: mock.Mock) -> None:
        from gui_app import chrome_devtools_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        client = client_cls.return_value
        client.run_chatgpt_prompt.side_effect = TimeoutError("Timed out waiting for Chrome remote debugging approval")

        adapter = chrome_devtools_adapter.ChromeDevToolsAdapter(self.root / "gui-data")
        result = adapter.run_task(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            prompt_text="Find literature",
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )

        self.assertEqual(result["status"], "attention_required")
        self.assertEqual(result["adapter"], "chrome_devtools")
        self.assertEqual(result["attention_required"]["reason"], "browser_approval_required")
        self.assertIn("Chrome remote debugging", result["attention_required"]["message"])

    @mock.patch("gui_app.chrome_devtools_adapter.global_browser_setup.global_setup_health")
    @mock.patch("gui_app.chrome_devtools_adapter.ChromeDevToolsMcpClient")
    def test_run_task_generic_mcp_timeout_surfaces_bootstrap_attention(
        self,
        client_cls: mock.Mock,
        global_health: mock.Mock,
    ) -> None:
        from gui_app import chrome_devtools_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        global_health.return_value = {
            "chrome_for_testing": {
                "runtime": "chrome_for_testing",
                "app_path": "/Applications/Google Chrome for Testing.app",
                "installed": False,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
                "profile_exists": False,
                "running": False,
                "debuggable": False,
                "browser_url": "",
                "ws_endpoint": "",
                "relaunch_required": False,
            },
            "chrome_stable": {
                "runtime": "chrome_stable",
                "app_path": "/Applications/Google Chrome.app",
                "installed": True,
                "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome",
                "profile_exists": True,
                "running": True,
                "debuggable": True,
                "browser_url": "http://127.0.0.1:9222",
                "ws_endpoint": "ws://127.0.0.1:9222/devtools/browser/stable",
                "relaunch_required": False,
            },
        }
        client = client_cls.return_value
        client.attach_mode = "ws_endpoint"
        client.run_chatgpt_prompt.side_effect = TimeoutError("Timed out waiting for MCP response header.")

        adapter = chrome_devtools_adapter.ChromeDevToolsAdapter(self.root / "gui-data")
        result = adapter.run_task(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            prompt_text="Find literature",
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )

        self.assertEqual(result["status"], "attention_required")
        self.assertEqual(result["adapter"], "chrome_devtools")
        self.assertEqual(result["attention_required"]["reason"], "browser_bootstrap_failed")
        self.assertIn("did not respond to browser commands", result["readiness_message"])


class ResearchAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_persists_structured_result_response_and_screenshots(self) -> None:
        from gui_app import research_adapter

        screenshot = self.root / "source-shot.png"
        screenshot.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"0" * 2048))
        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        adapter = research_adapter.ResearchAdapter(self.root / "gui-data")
        persisted = adapter.persist_result(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            workspace=workspace,
            result={
                "submitted": True,
                "completion_state": "completed",
                "response_text": "Atlas summary",
                "mode_used": "deep_research",
                "deep_research_enabled": True,
                "verification_method": "accessibility",
                "fallback_reason": "",
                "screenshot_paths": [str(screenshot)],
            },
        )

        self.assertEqual(persisted["status"], "succeeded")
        self.assertTrue(Path(persisted["result_path"]).exists())
        self.assertTrue(Path(persisted["response_path"]).exists())
        self.assertTrue(Path(persisted["structured_output_path"]).exists())
        self.assertEqual(Path(persisted["response_path"]).read_text(encoding="utf-8"), "Atlas summary\n")
        self.assertEqual(len(persisted["screenshot_paths"]), 1)
        payload = json.loads(Path(persisted["result_path"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["mode_used"], "deep_research")
        structured = json.loads(Path(persisted["structured_output_path"]).read_text(encoding="utf-8"))
        self.assertEqual(structured["task_type"], "literature")
        self.assertEqual(structured["response_path"], persisted["response_path"])

    def test_structured_literature_output_extracts_candidates_and_links(self) -> None:
        from gui_app import research_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        adapter = research_adapter.ResearchAdapter(self.root / "gui-data")
        persisted = adapter.persist_result(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            workspace=workspace,
            result={
                "submitted": True,
                "completion_state": "completed",
                "response_text": "\n".join([
                    "# Candidate papers",
                    "- [Attention Is All You Need](https://arxiv.org/abs/1706.03762) — transformer baseline",
                    "- [Longformer: The Long-Document Transformer](https://arxiv.org/abs/2004.05150) — long-context sparse attention",
                ]),
                "mode_used": "deep_research",
                "deep_research_enabled": True,
                "verification_method": "accessibility",
                "fallback_reason": "",
                "screenshot_paths": [],
            },
        )

        structured = json.loads(Path(persisted["structured_output_path"]).read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(structured["candidates"]), 2)
        self.assertEqual(structured["candidates"][0]["title"], "Attention Is All You Need")
        self.assertEqual(structured["candidates"][0]["url"], "https://arxiv.org/abs/1706.03762")
        self.assertIn("Attention Is All You Need", structured["query_hints"])
        self.assertIn("Longformer: The Long-Document Transformer", structured["query_hints"])

    @mock.patch("gui_app.research_adapter.atlas_controller.run_atlas_task", side_effect=RuntimeError("AppleEvent timed out"))
    @mock.patch("gui_app.research_adapter.chrome_devtools_adapter.ChromeDevToolsAdapter.run_task")
    def test_run_task_normalizes_atlas_exception_into_failed_result(
        self,
        chrome_run_task: mock.Mock,
        run_atlas_task: mock.Mock,
    ) -> None:
        from gui_app import research_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        chrome_run_task.return_value = {
            "task_id": "chrome-task-1",
            "task_type": "literature",
            "adapter": "chrome_devtools",
            "status": "failed",
            "started_at": "2026-04-17T00:00:00+00:00",
            "finished_at": "2026-04-17T00:00:01+00:00",
            "mode_used": "chrome_for_testing_attach",
            "summary": "Chrome DevTools MCP warm-up failed.",
            "prompt_path": "",
            "raw_response_path": "",
            "structured_output_path": "",
            "transcript_path": "",
            "screenshot_paths": [],
            "artifacts": [],
            "fallback_reason": "Chrome warm-up failed; falling back to Atlas.",
            "attention_required": None,
        }
        adapter = research_adapter.ResearchAdapter(self.root / "gui-data")

        persisted = adapter.run_task(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            prompt_text="Find literature",
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )

        self.assertEqual(persisted["status"], "failed")
        self.assertEqual(persisted["completion_state"], "failed")
        self.assertIn("falling back to local literature discovery", persisted["summary"].lower())
        self.assertTrue(Path(persisted["result_path"]).exists())
        self.assertTrue(Path(persisted["response_path"]).exists())
        payload = json.loads(Path(persisted["result_path"]).read_text(encoding="utf-8"))
        self.assertFalse(payload["submitted"])
        self.assertIn("AppleEvent timed out", payload["error_message"])
        chrome_run_task.assert_called_once()
        run_atlas_task.assert_called_once()

    @mock.patch("gui_app.research_adapter.atlas_controller.run_atlas_task")
    @mock.patch("gui_app.research_adapter.chrome_devtools_adapter.ChromeDevToolsAdapter.run_task")
    def test_run_task_falls_back_to_atlas_when_chrome_fails(
        self,
        chrome_run_task: mock.Mock,
        atlas_run_task: mock.Mock,
    ) -> None:
        from gui_app import research_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        chrome_run_task.return_value = {
            "task_id": "chrome-task-1",
            "task_type": "literature",
            "adapter": "chrome_devtools",
            "status": "failed",
            "started_at": "2026-04-17T00:00:00+00:00",
            "finished_at": "2026-04-17T00:00:01+00:00",
            "mode_used": "deep_research",
            "summary": "Chrome DevTools MCP attach failed.",
            "prompt_path": "",
            "raw_response_path": "",
            "structured_output_path": "",
            "transcript_path": "",
            "screenshot_paths": [],
            "artifacts": [],
            "fallback_reason": "Chrome attach failed; falling back to Atlas.",
            "attention_required": None,
        }
        atlas_run_task.return_value = {
            "submitted": True,
            "completion_state": "completed",
            "response_text": "Atlas summary",
            "mode_used": "deep_research",
            "deep_research_enabled": True,
            "verification_method": "accessibility",
            "fallback_reason": "",
            "screenshot_paths": [],
            "started_at": "2026-04-17T00:00:02+00:00",
            "finished_at": "2026-04-17T00:00:03+00:00",
            "error_message": "",
        }

        adapter = research_adapter.ResearchAdapter(self.root / "gui-data")
        persisted = adapter.run_task(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            prompt_text="Find literature",
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )

        self.assertEqual(persisted["status"], "succeeded")
        self.assertEqual(persisted["adapter"], "atlas")
        self.assertEqual(persisted["fallback_reason"], "Chrome attach failed; falling back to Atlas.")
        chrome_run_task.assert_called_once()
        atlas_run_task.assert_called_once()

    @mock.patch("gui_app.research_adapter.atlas_controller.run_atlas_task")
    @mock.patch("gui_app.research_adapter.chrome_devtools_adapter.ChromeDevToolsAdapter.run_task")
    def test_run_task_stops_on_chrome_attention_required_without_atlas_fallback(
        self,
        chrome_run_task: mock.Mock,
        atlas_run_task: mock.Mock,
    ) -> None:
        from gui_app import research_adapter

        workspace = self.root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        chrome_run_task.return_value = {
            "task_id": "chrome-task-1",
            "task_type": "literature",
            "adapter": "chrome_devtools",
            "status": "attention_required",
            "started_at": "2026-04-17T00:00:00+00:00",
            "finished_at": "2026-04-17T00:00:10+00:00",
            "mode_used": "auto_connect",
            "summary": "Approve Chrome remote debugging dialog.",
            "prompt_path": "",
            "raw_response_path": "",
            "structured_output_path": "",
            "transcript_path": "",
            "screenshot_paths": [],
            "artifacts": [],
            "fallback_reason": "",
            "attention_required": {
                "reason": "browser_approval_required",
                "message": "Approve Chrome remote debugging dialog.",
                "details": {"adapter": "chrome_devtools"},
            },
        }

        adapter = research_adapter.ResearchAdapter(self.root / "gui-data")
        persisted = adapter.run_task(
            project_id="project-1",
            run_id="run-1",
            stage_name="literature",
            prompt_text="Find literature",
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )

        self.assertEqual(persisted["status"], "attention_required")
        self.assertEqual(persisted["adapter"], "chrome_devtools")
        self.assertEqual(persisted["attention_required"]["reason"], "browser_approval_required")
        chrome_run_task.assert_called_once()
        atlas_run_task.assert_not_called()
