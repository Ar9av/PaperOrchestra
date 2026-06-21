from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gui_app import storage


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class AcceptanceWalkthroughTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.script = _load_module(
            "acceptance_walkthrough_script",
            storage.REPO_ROOT / "scripts" / "acceptance_walkthrough.py",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_launch_app_uses_supported_launcher_and_parses_pid(self) -> None:
        launcher_stdout = "\n".join([
            "PaperOrchestra GUI started at http://127.0.0.1:8811 (pid 43210)",
            "Project data persists under /tmp/gui-data",
            "",
        ])

        with mock.patch.object(self.script.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=launcher_stdout, stderr="")) as run:
            launched = self.script.launch_app(
                host="127.0.0.1",
                port=8811,
                data_root=Path("/tmp/gui-data"),
                env={"PYTHONUNBUFFERED": "1"},
            )

        self.assertEqual(launched["pid"], 43210)
        self.assertEqual(launched["base_url"], "http://127.0.0.1:8811")
        invoked = run.call_args.args[0]
        self.assertIn("scripts/launch_gui.py", invoked)
        self.assertIn("--no-browser", invoked)

    def test_parse_launcher_stdout_rejects_unexpected_output(self) -> None:
        with self.assertRaises(RuntimeError):
            self.script.parse_launcher_stdout("launcher did not report a pid")

    def test_require_playwright_reports_install_steps(self) -> None:
        with mock.patch.object(self.script.importlib, "import_module", side_effect=ModuleNotFoundError("No module named 'playwright'")):
            with self.assertRaises(RuntimeError) as raised:
                self.script.require_playwright()

        self.assertIn("python -m pip install -r requirements.txt", str(raised.exception))
        self.assertIn("python -m playwright install chromium", str(raised.exception))

    def test_verify_playwright_ready_reports_missing_chromium(self) -> None:
        class FakeChromium:
            def launch(self, **_: object) -> object:
                raise RuntimeError("Executable doesn't exist at /tmp/chromium")

        class FakePlaywright:
            chromium = FakeChromium()

        class FakeSyncPlaywright:
            def __enter__(self) -> FakePlaywright:
                return FakePlaywright()

            def __exit__(self, *_: object) -> None:
                return None

        with mock.patch.object(self.script, "require_playwright", return_value=lambda: FakeSyncPlaywright()):
            with self.assertRaises(RuntimeError) as raised:
                self.script.verify_playwright_ready()

        self.assertIn("Playwright Chromium is not installed", str(raised.exception))
        self.assertIn("python -m playwright install chromium", str(raised.exception))

    def test_verify_playwright_ready_reports_missing_python_package(self) -> None:
        with mock.patch.object(self.script.importlib, "import_module", side_effect=ModuleNotFoundError("No module named 'playwright'")):
            with self.assertRaises(RuntimeError) as raised:
                self.script.verify_playwright_ready()

        self.assertIn("Playwright browser automation is not installed", str(raised.exception))
        self.assertNotIn("Playwright Chromium is not installed", str(raised.exception))

    def test_configure_acceptance_environment_local_only_disables_external_surfaces(self) -> None:
        data_root = self.root / "gui-data"
        env = {"CODEX_BIN": "codex"}

        self.script.configure_acceptance_environment(env, data_root, local_only=True)

        self.assertEqual(env["PAPERORCHESTRA_ACCEPTANCE_FIXTURES"], "1")
        self.assertEqual(env["PAPERORCHESTRA_CHROME_ENABLED"], "0")
        self.assertEqual(env["PAPERORCHESTRA_ATLAS_ENABLED"], "0")
        self.assertEqual(env["PAPERORCHESTRA_ATLAS_FALLBACK_ENABLED"], "0")
        self.assertEqual(env["PAPERORCHESTRA_BROWSER_PRIMARY"], "local")
        self.assertEqual(env["PAPERORCHESTRA_BROWSER_FALLBACK_ORDER"], "local")
        self.assertEqual(env["PAPERORCHESTRA_ACCEPTANCE_STRICT_S2_CACHE"], "1")
        self.assertNotEqual(env["CODEX_BIN"], "codex")
        self.assertTrue(Path(env["PAPERORCHESTRA_S2_CACHE_DB"]).exists())

    def test_validate_examples_root_reports_missing_inputs(self) -> None:
        examples_root = self.root / "missing-examples"
        examples_root.mkdir()

        with self.assertRaises(RuntimeError) as raised:
            self.script.validate_examples_root(examples_root)

        self.assertIn("Acceptance examples root is incomplete", str(raised.exception))
        self.assertIn("idea.md", str(raised.exception))

    def test_write_summary_and_capture_run_artifacts(self) -> None:
        data_root = self.root / "gui-data"
        project = storage.create_project("Acceptance", "", "", data_root=data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], data_root)
        run_root = storage.run_dir(project["project_id"], run_payload["run_id"], data_root)
        (run_root / "events.jsonl").write_text(json.dumps({"type": "run_created"}) + "\n", encoding="utf-8")
        (run_root / "state.json").write_text(json.dumps({"run_id": run_payload["run_id"]}) + "\n", encoding="utf-8")

        output_root = self.root / "output"
        summary_path = self.script.write_summary_and_capture_artifacts(
            output_root=output_root,
            project_id=project["project_id"],
            run_id=run_payload["run_id"],
            data_root=data_root,
            summary={
                "status": "succeeded",
                "project_id": project["project_id"],
                "run_id": run_payload["run_id"],
            },
        )

        self.assertTrue(summary_path.exists())
        self.assertTrue((output_root / "run-artifacts" / "events.jsonl").exists())
        self.assertTrue((output_root / "run-artifacts" / "state.json").exists())
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "succeeded")

    def test_help_exits_cleanly(self) -> None:
        completed = self.script.subprocess.run(
            [str(storage.repo_python_executable()), "scripts/acceptance_walkthrough.py", "--help"],
            cwd=str(storage.REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("Run the PaperOrchestra acceptance walkthrough", completed.stdout)

    def test_main_preflights_playwright_before_launch_app(self) -> None:
        examples_root = self.root / "examples"
        examples_root.mkdir()
        for name in ("idea.md", "experimental_log.md", "template.tex", "conference_guidelines.md"):
            (examples_root / name).write_text("fixture\n", encoding="utf-8")
        output_root = self.root / "output"

        with (
            mock.patch.object(self.script, "verify_playwright_ready", side_effect=RuntimeError("missing chromium")),
            mock.patch.object(self.script, "launch_app") as launch_app,
        ):
            exit_code = self.script.main([
                "--examples-root",
                str(examples_root),
                "--output-root",
                str(output_root),
            ])

        self.assertEqual(exit_code, 1)
        launch_app.assert_not_called()
        summary = json.loads((output_root / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "failed")
        self.assertIn("missing chromium", summary["error"])

    def test_script_invocation_succeeds_end_to_end(self) -> None:
        if importlib.util.find_spec("playwright.sync_api") is None:
            self.skipTest("playwright is not installed in the repo virtualenv")
        try:
            self.script.verify_playwright_ready()
        except RuntimeError as exc:
            self.skipTest(str(exc))

        output_root = self.root / "acceptance-output"
        completed = self.script.subprocess.run(
            [
                str(storage.repo_python_executable()),
                "scripts/acceptance_walkthrough.py",
                "--output-root",
                str(output_root),
                "--local-only",
            ],
            cwd=str(storage.REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )

        if completed.returncode != 0:
            self.fail(completed.stderr or completed.stdout)

        summary = json.loads((output_root / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "succeeded")
        self.assertTrue((output_root / "final-paper.pdf").exists())
        self.assertTrue((output_root / "run-artifacts" / "state.json").exists())
