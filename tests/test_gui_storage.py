#!/usr/bin/env python3
"""Tests for the PaperOrchestra local GUI helpers."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
import os
from PIL import Image
from PIL import ImageDraw
from pathlib import Path
from unittest import mock

from gui_app import atlas_controller
from gui_app import handoff
from gui_app import storage
from gui_app import server
from gui_app.server import new_run_id
from gui_app.server import parse_markdown_sections
from http.server import ThreadingHTTPServer


class GuiStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tempdir.name) / "gui-data"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _serve_gui(self) -> tuple[ThreadingHTTPServer, threading.Thread, int]:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.GuiHandler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return httpd, thread, port

    def test_create_project_and_sync_workspace(self) -> None:
        template_src = Path(self.tempdir.name) / "template.tex"
        template_src.write_text("\\documentclass{article}\\begin{document}\\section{Intro}\\end{document}\n", encoding="utf-8")

        project = storage.create_project(
            title="Adaptive Top-K Attention",
            venue="ICLR 2027",
            description="Test project",
            data_root=self.data_root,
        )
        project["idea"]["problem_statement"] = "Long-context attention is expensive."
        project["idea"]["core_hypothesis"] = "Adaptive sparsity can preserve quality."
        project["idea"]["methodology"] = "Learn a top-k selector."
        project["idea"]["expected_contribution"] = "A controllable efficiency-quality tradeoff."
        project["experimental"]["log_text"] = "## 1. Experimental Setup\n\nSetup\n\n## 2. Raw Numeric Data\n\nData"
        project["guidelines"]["guidelines_text"] = "9 page limit. Submission deadline: October 1, 2026."
        project["uploads"]["template_tex"] = str(template_src)

        synced = storage.sync_workspace(project, self.data_root)
        workspace = Path(synced["workspace_path"])

        self.assertTrue((workspace / "inputs" / "idea.md").exists())
        self.assertIn("## Problem Statement", (workspace / "inputs" / "idea.md").read_text(encoding="utf-8"))
        self.assertEqual(
            (workspace / "inputs" / "template.tex").read_text(encoding="utf-8"),
            template_src.read_text(encoding="utf-8"),
        )

    def test_create_project_initializes_input_workbench_state(self) -> None:
        project = storage.create_project(
            title="Workbench Project",
            venue="ICLR 2027",
            description="Workbench coverage",
            data_root=self.data_root,
        )

        self.assertEqual(project["wizard_step"], "setup")
        self.assertEqual(project["idea"]["editor_mode"], "structured")
        self.assertIn("raw_markdown", project["idea"])
        self.assertEqual(project["experimental"]["editor_mode"], "structured")
        self.assertIn("setup_text", project["experimental"])
        self.assertEqual(project["guidelines"]["editor_mode"], "structured")
        self.assertIn("deadline", project["guidelines"])
        self.assertEqual(project["template"]["editor_mode"], "raw")
        self.assertIn("text", project["template"])

    def test_sync_workspace_prefers_canonical_text_fields(self) -> None:
        project = storage.create_project(
            title="Canonical Input Sync",
            venue="ICLR 2027",
            description="Canonical text sync coverage",
            data_root=self.data_root,
        )
        project["idea"]["raw_markdown"] = (
            "## Problem Statement\n\nCanonical idea text.\n\n"
            "## Core Hypothesis\n\nCanonical hypothesis.\n"
        )
        project["experimental"]["log_text"] = (
            "# Experimental Log\n\n## 1. Experimental Setup\n\nSetup text\n\n"
            "## 2. Raw Numeric Data\n\n| Method | Score |\n| --- | --- |\n| Ours | 91.2 |\n\n"
            "## 3. Qualitative Observations\n\n- Stable convergence\n"
        )
        project["guidelines"]["guidelines_text"] = (
            "# Venue Rules\n\nPage limit: 9 pages.\nSubmission deadline: October 1, 2026.\n"
        )
        project["template"]["text"] = "\\documentclass{article}\n\\begin{document}\n\\section{Introduction}\n\\end{document}\n"

        synced = storage.sync_workspace(project, self.data_root)
        workspace = Path(synced["workspace_path"])

        self.assertEqual(
            (workspace / "inputs" / "idea.md").read_text(encoding="utf-8"),
            project["idea"]["raw_markdown"],
        )
        self.assertEqual(
            (workspace / "inputs" / "template.tex").read_text(encoding="utf-8"),
            project["template"]["text"],
        )

    def test_validate_project_inputs_reports_per_input_messages(self) -> None:
        project = storage.create_project(
            title="Validation State",
            venue="ICLR 2027",
            description="Validation coverage",
            data_root=self.data_root,
        )
        synced = storage.sync_workspace(project, self.data_root)

        validation = storage.validate_project_inputs(synced, self.data_root)

        self.assertIn("inputs", validation)
        self.assertIn("template", validation["inputs"])
        self.assertTrue(validation["inputs"]["template"]["has_blockers"])
        self.assertTrue(any("MISSING" in item for item in validation["inputs"]["template"]["messages"]))

    def test_dashboard_empty_state_renders_without_projects(self) -> None:
        original_data_root = server.DATA_ROOT
        httpd: ThreadingHTTPServer | None = None
        thread: threading.Thread | None = None
        try:
            server.DATA_ROOT = self.data_root
            httpd, thread, port = self._serve_gui()
            response = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            body = response.read().decode("utf-8")
            self.assertIn("No saved projects yet", body)
            self.assertIn("Create new project", body)
        finally:
            server.DATA_ROOT = original_data_root
            if httpd is not None:
                httpd.shutdown()
                httpd.server_close()
            if thread is not None:
                thread.join(timeout=2)

    def test_reconcile_marks_stale_run_interrupted(self) -> None:
        project = storage.create_project("Test Paper", "", "", data_root=self.data_root)
        run = {
            "project_id": project["project_id"],
            "run_id": "pipeline-old",
            "status": "running",
            "stage": "codex_pipeline",
            "pid": 999999,
            "started_at": storage.utc_now(),
            "log_path": str(storage.run_dir(project["project_id"], "pipeline-old", self.data_root) / "run.log"),
        }
        storage.save_run(run, self.data_root)
        reconciled = storage.reconcile_run(run, self.data_root)
        self.assertEqual(reconciled["status"], "interrupted")
        storage.run_state_file(project["project_id"], "pipeline-old", self.data_root).unlink()
        rebuilt = storage.load_run(project["project_id"], "pipeline-old", self.data_root)
        self.assertIsNotNone(rebuilt)
        self.assertEqual(rebuilt["status"], "interrupted")

    def test_is_pid_running_treats_zombie_process_as_inactive(self) -> None:
        with mock.patch.object(storage.os, "kill", return_value=None):
            with mock.patch.object(storage.subprocess, "run", return_value=mock.Mock(stdout="Z+\n", returncode=0)):
                self.assertFalse(storage.is_pid_running(12345))

    def test_stage_performance_metadata_persists_and_resets(self) -> None:
        project = storage.create_project("Performance Paper", "", "", data_root=self.data_root)
        run = storage.create_pipeline_run(project["project_id"], self.data_root)
        stage_performance = {
            "measurement_scope": "process_delta",
            "wall_seconds": 1.23,
            "total_cpu_seconds": 0.45,
        }
        substep_performance = {
            "measurement_scope": "process_delta",
            "wall_seconds": 0.8,
            "total_cpu_seconds": 0.3,
        }
        updated = storage.update_stage_state(
            run,
            "outline",
            self.data_root,
            status="succeeded",
            performance=stage_performance,
        )
        storage.upsert_stage_substep(
            updated,
            "outline",
            "outline_generate",
            self.data_root,
            status="succeeded",
            summary="Generated outline.",
            performance=substep_performance,
        )

        storage.run_state_file(project["project_id"], run["run_id"], self.data_root).unlink()
        reloaded = storage.load_run(project["project_id"], run["run_id"], self.data_root)

        self.assertIsNotNone(reloaded)
        assert reloaded is not None
        self.assertEqual(reloaded["stages"]["outline"]["performance"]["wall_seconds"], 1.23)
        self.assertEqual(
            reloaded["stages"]["outline"]["substeps"][0]["performance"]["total_cpu_seconds"],
            0.3,
        )

        storage.reset_stage_state(reloaded, "outline", self.data_root)

        self.assertIsNone(reloaded["stages"]["outline"]["performance"])
        self.assertEqual(reloaded["stages"]["outline"]["substeps"], [])

    def test_markdown_upload_parser_extracts_expected_sections(self) -> None:
        sections = parse_markdown_sections(
            "## Problem Statement\n\nProblem\n\n## Core Hypothesis\n\nHypothesis\n\n## Expected Contribution\n\nContribution"
        )
        self.assertEqual(sections["problem statement"], "Problem")
        self.assertEqual(sections["core hypothesis"], "Hypothesis")
        self.assertEqual(sections["expected contribution"], "Contribution")

    def test_prepare_handoff_bundle_writes_required_files_and_policy(self) -> None:
        template_src = Path(self.tempdir.name) / "template.tex"
        template_src.write_text("\\documentclass{article}\\begin{document}Draft\\end{document}\n", encoding="utf-8")

        project = storage.create_project(
            title="Atlas Guided Paper",
            venue="ICLR 2027",
            description="Atlas handoff coverage",
            data_root=self.data_root,
        )
        project["experimental"]["log_text"] = "## 1. Experimental Setup\n\nSetup"
        project["guidelines"]["guidelines_text"] = "Submission deadline: October 1, 2026."
        project["uploads"]["template_tex"] = str(template_src)

        bundle = handoff.ensure_handoff_bundle(project, self.data_root)
        handoff_dir = Path(bundle["handoff_dir"])

        self.assertTrue((handoff_dir / "README.md").exists())
        self.assertTrue((handoff_dir / "02_deep_research_literature.md").exists())
        self.assertIn(
            "Deep Research enabled",
            (handoff_dir / "02_deep_research_literature.md").read_text(encoding="utf-8"),
        )
        policy = (handoff_dir / "policy.json").read_text(encoding="utf-8")
        self.assertIn('"required_literature_mode": "Deep Research for literature discovery and synthesis"', policy)

        saved = storage.load_project(project["project_id"], self.data_root)
        self.assertEqual(saved["chatgpt_policy"]["status"], "handoff_ready")
        self.assertEqual(saved["last_status"], "handoff_ready")

    def test_legacy_modules_are_marked_compatibility_only(self) -> None:
        self.assertIn("Legacy", server.__doc__ or "")
        self.assertIn("supported UI is the FastAPI control room", server.__doc__ or "")
        self.assertIn("Legacy", handoff.__doc__ or "")
        self.assertIn("supported path", handoff.__doc__ or "")

    def test_new_run_id_stays_unique_within_same_second(self) -> None:
        generated = {new_run_id("validate") for _ in range(8)}
        self.assertEqual(len(generated), 8)
        for run_id in generated:
            self.assertTrue(run_id.startswith("validate-"))

    def test_repo_python_executable_prefers_repo_venv(self) -> None:
        original_root = storage.REPO_ROOT
        try:
            fake_root = Path(self.tempdir.name) / "repo"
            python_bin = fake_root / ".venv" / "bin" / "python"
            python_bin.parent.mkdir(parents=True, exist_ok=True)
            python_bin.write_text("#!/bin/sh\n", encoding="utf-8")
            storage.REPO_ROOT = fake_root
            chosen = storage.repo_python_executable("/usr/bin/python3")
            self.assertEqual(chosen, python_bin)
        finally:
            storage.REPO_ROOT = original_root

    @mock.patch("gui_app.atlas_controller._run_chatgpt_keystrokes")
    @mock.patch("gui_app.atlas_controller._click_window_relative", return_value=True)
    @mock.patch("gui_app.atlas_controller.open_chatgpt_home")
    @mock.patch("gui_app.atlas_controller.copy_text_to_clipboard")
    def test_paste_into_chatgpt_copies_prompt_and_issues_paste_flow(
        self,
        copy_text_to_clipboard: mock.Mock,
        open_chatgpt_home: mock.Mock,
        click_window_relative: mock.Mock,
        run_chatgpt_keystrokes: mock.Mock,
    ) -> None:
        atlas_controller.paste_into_chatgpt("hello atlas")

        copy_text_to_clipboard.assert_called_once_with("hello atlas")
        open_chatgpt_home.assert_called_once()
        click_window_relative.assert_called_once_with(0.59, 0.57)
        self.assertEqual(run_chatgpt_keystrokes.call_count, 1)

    def test_choose_response_text_prefers_cropped_ocr_then_accessibility_then_clipboard(self) -> None:
        text, method = atlas_controller._choose_response_text(
            accessibility_response="Accessibility answer",
            clipboard_response="Clipboard answer",
            ocr_response="OCR answer",
        )
        self.assertEqual(text, "OCR answer")
        self.assertEqual(method, "screenshot_ocr")

        text, method = atlas_controller._choose_response_text(
            accessibility_response="Accessibility answer",
            clipboard_response="Clipboard answer",
            ocr_response="",
        )
        self.assertEqual(text, "Accessibility answer")
        self.assertEqual(method, "accessibility")

        text, method = atlas_controller._choose_response_text(
            accessibility_response="",
            clipboard_response="Clipboard answer",
            ocr_response="",
        )
        self.assertEqual(text, "Clipboard answer")
        self.assertEqual(method, "clipboard")

        text, method = atlas_controller._choose_response_text(
            accessibility_response="",
            clipboard_response="",
            ocr_response="OCR answer",
        )
        self.assertEqual(text, "OCR answer")
        self.assertEqual(method, "screenshot_ocr")

    def test_subtract_baseline_response_drops_staged_prompt_echo(self) -> None:
        self.assertEqual(
            atlas_controller._subtract_baseline_response(
                "Reply with exactly ATLAS_SMOKE_OK and nothing else.",
                "Reply with exactly ATLAS_SMOKE_OK and nothing else.",
            ),
            "",
        )
        self.assertEqual(
            atlas_controller._subtract_baseline_response(
                "Reply with exactly ATLAS_SMOKE_OK and nothing else.\nATLAS_SMOKE_OK",
                "Reply with exactly ATLAS_SMOKE_OK and nothing else.",
            ),
            "ATLAS_SMOKE_OK",
        )

    def test_find_purple_action_button_center_locates_send_orb(self) -> None:
        image_path = Path(self.tempdir.name) / "atlas-window.png"
        image = Image.new("RGBA", (400, 240), "white")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((40, 140, 360, 210), radius=20, outline="#dddddd", width=3)
        draw.ellipse((332, 160, 380, 208), fill=(145, 82, 247, 255))
        image.save(image_path)

        point = atlas_controller._find_purple_action_button_center(
            image_path,
            (1200, 300, 200, 120),
        )

        self.assertIsNotNone(point)
        assert point is not None
        self.assertGreaterEqual(point[0], 165)
        self.assertLessEqual(point[0], 195)
        self.assertGreaterEqual(point[1], 75)
        self.assertLessEqual(point[1], 105)

    @mock.patch("gui_app.atlas_controller._run_chatgpt_keystrokes")
    @mock.patch("gui_app.atlas_controller._click_send_button", return_value=True)
    def test_submit_staged_prompt_prefers_click_send_button(
        self,
        click_send_button: mock.Mock,
        run_chatgpt_keystrokes: mock.Mock,
    ) -> None:
        atlas_controller.submit_staged_prompt()

        click_send_button.assert_called_once()
        run_chatgpt_keystrokes.assert_not_called()

    @mock.patch("gui_app.atlas_controller._run_chatgpt_keystrokes")
    @mock.patch("gui_app.atlas_controller._click_send_button", return_value=False)
    def test_submit_staged_prompt_falls_back_to_keyboard_submit(
        self,
        click_send_button: mock.Mock,
        run_chatgpt_keystrokes: mock.Mock,
    ) -> None:
        atlas_controller.submit_staged_prompt()

        click_send_button.assert_called_once()
        run_chatgpt_keystrokes.assert_called_once()

    @mock.patch("gui_app.atlas_controller.time.sleep", return_value=None)
    @mock.patch("gui_app.atlas_controller._capture_atlas_response_sources")
    def test_wait_for_atlas_response_completion_detects_growth_then_stability(
        self,
        capture_sources: mock.Mock,
        _sleep: mock.Mock,
    ) -> None:
        capture_sources.side_effect = [
            {
                "accessibility_response": "",
                "clipboard_response": "",
                "ocr_response": "",
                "generation_active": True,
                "idle_detected": False,
                "screenshot_paths": [],
            },
            {
                "accessibility_response": "Draft answer",
                "clipboard_response": "",
                "ocr_response": "",
                "generation_active": True,
                "idle_detected": False,
                "screenshot_paths": [],
            },
            {
                "accessibility_response": "Draft answer complete",
                "clipboard_response": "",
                "ocr_response": "",
                "generation_active": False,
                "idle_detected": True,
                "screenshot_paths": ["/tmp/atlas-response.png"],
            },
            {
                "accessibility_response": "Draft answer complete",
                "clipboard_response": "",
                "ocr_response": "",
                "generation_active": False,
                "idle_detected": True,
                "screenshot_paths": ["/tmp/atlas-response.png"],
            },
        ]

        result = atlas_controller._wait_for_atlas_response_completion(
            timeout_seconds=5.0,
            poll_seconds=0.01,
            stable_polls=2,
        )

        self.assertTrue(result["response_detected"])
        self.assertEqual(result["completion_state"], "completed")
        self.assertEqual(result["response_text"], "Draft answer complete")
        self.assertEqual(result["extraction_method"], "accessibility")
        self.assertIn("/tmp/atlas-response.png", result["screenshot_paths"])

    @mock.patch("gui_app.atlas_controller.time.monotonic")
    @mock.patch("gui_app.atlas_controller.time.sleep", return_value=None)
    @mock.patch("gui_app.atlas_controller._capture_atlas_response_sources")
    def test_wait_for_atlas_response_completion_ignores_unchanged_baseline_prompt(
        self,
        capture_sources: mock.Mock,
        _sleep: mock.Mock,
        monotonic: mock.Mock,
    ) -> None:
        states = iter([
            {
                "accessibility_response": "Reply with exactly ATLAS_SMOKE_OK and nothing else.",
                "clipboard_response": "",
                "ocr_response": "",
                "generation_active": False,
                "idle_detected": True,
                "screenshot_paths": [],
            },
            {
                "accessibility_response": "Reply with exactly ATLAS_SMOKE_OK and nothing else.\nATLAS_SMOKE_OK",
                "clipboard_response": "",
                "ocr_response": "",
                "generation_active": False,
                "idle_detected": True,
                "screenshot_paths": [],
            },
            {
                "accessibility_response": "Reply with exactly ATLAS_SMOKE_OK and nothing else.\nATLAS_SMOKE_OK",
                "clipboard_response": "",
                "ocr_response": "",
                "generation_active": False,
                "idle_detected": True,
                "screenshot_paths": [],
            },
        ])
        capture_sources.side_effect = lambda *_args, **_kwargs: next(states)
        monotonic.side_effect = [0.0, 0.0, 0.0, 0.01]

        result = atlas_controller._wait_for_atlas_response_completion(
            timeout_seconds=1.0,
            poll_seconds=0.0,
            stable_polls=2,
            baseline_response_text="Reply with exactly ATLAS_SMOKE_OK and nothing else.",
        )

        self.assertTrue(result["response_detected"])
        self.assertEqual(result["completion_state"], "completed")
        self.assertEqual(result["response_text"], "ATLAS_SMOKE_OK")

    @mock.patch("gui_app.atlas_controller.time.monotonic")
    @mock.patch("gui_app.atlas_controller.time.sleep", return_value=None)
    @mock.patch("gui_app.atlas_controller._capture_atlas_response_sources")
    def test_wait_for_atlas_response_completion_times_out_without_response(
        self,
        capture_sources: mock.Mock,
        _sleep: mock.Mock,
        monotonic: mock.Mock,
    ) -> None:
        states = iter([
            {
                "accessibility_response": "",
                "clipboard_response": "",
                "ocr_response": "",
                "generation_active": True,
                "idle_detected": False,
                "screenshot_paths": [],
            },
            {
                "accessibility_response": "",
                "clipboard_response": "",
                "ocr_response": "",
                "generation_active": False,
                "idle_detected": True,
                "screenshot_paths": ["/tmp/atlas-timeout.png"],
            },
        ])
        capture_sources.side_effect = lambda *_args, **_kwargs: next(
            states,
            {
                "accessibility_response": "",
                "clipboard_response": "",
                "ocr_response": "",
                "generation_active": False,
                "idle_detected": True,
                "screenshot_paths": ["/tmp/atlas-timeout.png"],
            },
        )
        monotonic.side_effect = [0.0, 0.0, 0.02]

        result = atlas_controller._wait_for_atlas_response_completion(
            timeout_seconds=0.01,
            poll_seconds=0.0,
            stable_polls=2,
        )

        self.assertFalse(result["response_detected"])
        self.assertEqual(result["completion_state"], "timeout")
        self.assertEqual(result["response_text"], "")
        self.assertIn("/tmp/atlas-timeout.png", result["screenshot_paths"])

    @mock.patch("gui_app.atlas_controller._stage_and_send_query")
    def test_send_query_and_capture_response_returns_generic_result_shape(
        self,
        stage_and_send_query: mock.Mock,
    ) -> None:
        stage_and_send_query.return_value = {
            "submitted": True,
            "response_text": "Atlas bridge answer",
            "response_detected": True,
            "completion_state": "completed",
            "wait_strategy_used": "stability_then_idle",
            "extraction_method": "accessibility",
            "screenshot_paths": ["/tmp/atlas-query.png"],
            "action_sequence": ["wait_for_response_completion"],
            "started_at": "2026-04-17T00:00:00+00:00",
            "finished_at": "2026-04-17T00:01:00+00:00",
            "error_message": "",
        }

        result = atlas_controller.send_query_and_capture_response("Bridge this prompt")

        stage_and_send_query.assert_called_once()
        self.assertTrue(result["submitted"])
        self.assertEqual(result["response_text"], "Atlas bridge answer")
        self.assertEqual(result["completion_state"], "completed")
        self.assertEqual(result["wait_strategy_used"], "stability_then_idle")
        self.assertEqual(result["extraction_method"], "accessibility")
        self.assertEqual(result["error_message"], "")
        self.assertIn("started_at", result)
        self.assertIn("finished_at", result)

    @mock.patch("gui_app.atlas_controller.send_query_and_capture_response")
    def test_atlas_bridge_cli_prints_json_result(self, send_query_and_capture_response: mock.Mock) -> None:
        send_query_and_capture_response.return_value = {
            "submitted": True,
            "response_text": "Atlas bridge answer",
            "response_detected": True,
            "completion_state": "completed",
            "wait_strategy_used": "stability_then_idle",
            "extraction_method": "accessibility",
            "screenshot_paths": [],
            "action_sequence": ["submit_prompt", "wait_for_response_completion"],
            "started_at": storage.utc_now(),
            "finished_at": storage.utc_now(),
            "error_message": "",
        }
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "atlas_bridge.py"
        spec = importlib.util.spec_from_file_location("atlas_bridge_script", script_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["atlas_bridge.py", "--prompt", "Hello Atlas", "--json"]):
            with mock.patch("sys.stdout", stdout):
                exit_code = module.main()

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["response_text"], "Atlas bridge answer")
        send_query_and_capture_response.assert_called_once()

    @mock.patch("gui_app.atlas_controller.show_notification")
    @mock.patch("gui_app.atlas_controller.attempt_open_mode_control")
    @mock.patch("gui_app.atlas_controller.open_chatgpt_home")
    def test_attempt_enable_deep_research_opens_chat_and_notifies(
        self,
        open_chatgpt_home: mock.Mock,
        attempt_open_mode_control: mock.Mock,
        show_notification: mock.Mock,
    ) -> None:
        atlas_controller.attempt_enable_deep_research()

        open_chatgpt_home.assert_called_once()
        attempt_open_mode_control.assert_called_once()
        show_notification.assert_called_once()
        args, _kwargs = show_notification.call_args
        self.assertIn("Deep Research", args[0])
        self.assertIn("Deep Research", args[1])

    @mock.patch("gui_app.atlas_controller._stage_and_send_query")
    @mock.patch("gui_app.atlas_controller.verify_deep_research_enabled")
    @mock.patch("gui_app.atlas_controller.select_deep_research_mode")
    @mock.patch("gui_app.atlas_controller.attempt_open_mode_control")
    def test_run_literature_prompt_in_atlas_returns_verified_deep_research_result(
        self,
        attempt_open_mode_control: mock.Mock,
        select_deep_research_mode: mock.Mock,
        verify_deep_research_enabled: mock.Mock,
        stage_and_send_query: mock.Mock,
    ) -> None:
        prompt_path = Path(self.tempdir.name) / "research.md"
        prompt_path.write_text("prompt", encoding="utf-8")
        verify_deep_research_enabled.return_value = {
            "enabled": True,
            "method": "accessibility",
            "screenshot_paths": ["/tmp/atlas-1.png"],
        }
        def fake_stage_and_send_query(_stage_prompt, options=None, staged_action="stage_prompt"):
            assert options is not None
            if options.pre_submit_callback is not None:
                options.pre_submit_callback()
            return {
                "submitted": True,
                "response_text": "Atlas answer",
                "response_detected": True,
                "completion_state": "completed",
                "wait_strategy_used": "stability_then_idle",
                "extraction_method": "accessibility",
                "screenshot_paths": [],
                "action_sequence": [staged_action, "submit_prompt"],
                "started_at": "2026-04-17T00:00:00+00:00",
                "finished_at": "2026-04-17T00:01:00+00:00",
                "error_message": "",
            }
        stage_and_send_query.side_effect = fake_stage_and_send_query

        result = atlas_controller.run_literature_prompt_in_atlas(prompt_path)

        self.assertTrue(result["deep_research_enabled"])
        self.assertEqual(result["verification_method"], "accessibility")
        self.assertEqual(result["mode_used"], "deep_research")
        self.assertTrue(result["submitted"])
        self.assertEqual(result["fallback_reason"], "")
        self.assertIn("/tmp/atlas-1.png", result["screenshot_paths"])

    @mock.patch("gui_app.atlas_controller._stage_and_send_query")
    @mock.patch("gui_app.atlas_controller.verify_deep_research_enabled")
    @mock.patch("gui_app.atlas_controller.select_deep_research_mode")
    @mock.patch("gui_app.atlas_controller.attempt_open_mode_control")
    def test_run_literature_prompt_in_atlas_falls_back_to_normal_mode_when_unverified(
        self,
        attempt_open_mode_control: mock.Mock,
        select_deep_research_mode: mock.Mock,
        verify_deep_research_enabled: mock.Mock,
        stage_and_send_query: mock.Mock,
    ) -> None:
        prompt_path = Path(self.tempdir.name) / "research.md"
        prompt_path.write_text("prompt", encoding="utf-8")
        verify_deep_research_enabled.return_value = {
            "enabled": False,
            "method": "unverified",
            "screenshot_paths": ["/tmp/atlas-unverified.png"],
        }
        def fake_stage_and_send_query(_stage_prompt, options=None, staged_action="stage_prompt"):
            assert options is not None
            if options.pre_submit_callback is not None:
                options.pre_submit_callback()
            return {
                "submitted": True,
                "response_text": "",
                "response_detected": False,
                "completion_state": "timeout",
                "wait_strategy_used": "stability_then_idle",
                "extraction_method": "none",
                "screenshot_paths": [],
                "action_sequence": [staged_action, "submit_prompt"],
                "started_at": "2026-04-17T00:00:00+00:00",
                "finished_at": "2026-04-17T00:01:00+00:00",
                "error_message": "Timed out waiting for a non-empty Atlas response.",
            }
        stage_and_send_query.side_effect = fake_stage_and_send_query

        result = atlas_controller.run_literature_prompt_in_atlas(prompt_path)

        self.assertFalse(result["deep_research_enabled"])
        self.assertEqual(result["verification_method"], "unverified")
        self.assertEqual(result["mode_used"], "normal")
        self.assertTrue(result["submitted"])
        self.assertIn("Unable to verify", result["fallback_reason"])
        self.assertIn("/tmp/atlas-unverified.png", result["screenshot_paths"])

    def test_record_atlas_literature_run_persists_project_and_run_metadata(self) -> None:
        project = storage.create_project("Atlas Paper", "", "", data_root=self.data_root)
        result = {
            "deep_research_enabled": True,
            "verification_method": "accessibility",
            "submitted": True,
            "mode_used": "deep_research",
            "fallback_reason": "",
            "screenshot_paths": ["/tmp/atlas-verified.png"],
            "action_sequence": ["activate_atlas", "submit_prompt"],
            "started_at": storage.utc_now(),
            "finished_at": storage.utc_now(),
        }

        run_payload = storage.record_atlas_literature_run(project, result, self.data_root)
        saved_project = storage.load_project(project["project_id"], self.data_root)

        self.assertEqual(run_payload["kind"], "atlas_literature")
        self.assertEqual(run_payload["status"], "succeeded")
        self.assertEqual(run_payload["stage"], "atlas_deep_research")
        self.assertTrue(Path(run_payload["result_path"]).exists())
        self.assertEqual(saved_project["latest_atlas_result"]["mode_used"], "deep_research")
        self.assertEqual(saved_project["latest_atlas_result"]["run_id"], run_payload["run_id"])

    def test_run_page_exposes_attempt_deep_research_control(self) -> None:
        project = storage.create_project("Atlas UI", "", "", data_root=self.data_root)

        original_data_root = server.DATA_ROOT
        httpd: ThreadingHTTPServer | None = None
        thread: threading.Thread | None = None
        try:
            server.DATA_ROOT = self.data_root
            httpd, thread, port = self._serve_gui()
            response = urllib.request.urlopen(f"http://127.0.0.1:{port}/projects/{project['project_id']}?step=run")
            body = response.read().decode("utf-8")
            self.assertIn("/atlas/attempt_deep_research", body)
            self.assertIn("Attempt Deep Research enable", body)
        finally:
            server.DATA_ROOT = original_data_root
            if httpd is not None:
                httpd.shutdown()
                httpd.server_close()
            if thread is not None:
                thread.join(timeout=2)

    @mock.patch("gui_app.server.atlas_controller.attempt_enable_deep_research")
    def test_attempt_deep_research_route_redirects_and_calls_controller(
        self,
        attempt_enable_deep_research: mock.Mock,
    ) -> None:
        project = storage.create_project("Atlas Attempt Route", "", "", data_root=self.data_root)

        original_data_root = server.DATA_ROOT
        httpd: ThreadingHTTPServer | None = None
        thread: threading.Thread | None = None
        try:
            server.DATA_ROOT = self.data_root
            httpd, thread, port = self._serve_gui()
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/projects/{project['project_id']}/atlas/attempt_deep_research",
                method="POST",
                data=b"",
            )
            opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
            response = opener.open(request)

            self.assertEqual(response.geturl(), f"http://127.0.0.1:{port}/projects/{project['project_id']}?step=outputs")
            attempt_enable_deep_research.assert_called_once()
        finally:
            server.DATA_ROOT = original_data_root
            if httpd is not None:
                httpd.shutdown()
                httpd.server_close()
            if thread is not None:
                thread.join(timeout=2)

    def test_project_file_route_serves_workspace_file_and_rejects_outside_paths(self) -> None:
        project = storage.create_project("File Route", "", "", data_root=self.data_root)
        synced = storage.sync_workspace(project, self.data_root)
        workspace = Path(synced["workspace_path"])
        idea_path = workspace / "inputs" / "idea.md"
        idea_path.write_text("workspace content\n", encoding="utf-8")
        outside_path = Path(self.tempdir.name) / "outside.txt"
        outside_path.write_text("outside content\n", encoding="utf-8")

        original_data_root = server.DATA_ROOT
        httpd: ThreadingHTTPServer | None = None
        thread: threading.Thread | None = None
        try:
            server.DATA_ROOT = self.data_root
            httpd, thread, port = self._serve_gui()

            allowed_url = (
                f"http://127.0.0.1:{port}/projects/{project['project_id']}/file"
                f"?path={urllib.request.pathname2url(str(idea_path))}"
            )
            with urllib.request.urlopen(allowed_url) as response:
                self.assertEqual(response.read().decode("utf-8"), "workspace content\n")

            forbidden_url = (
                f"http://127.0.0.1:{port}/projects/{project['project_id']}/file"
                f"?path={urllib.request.pathname2url(str(outside_path))}"
            )
            try:
                urllib.request.urlopen(forbidden_url)
                self.fail("Expected forbidden outside-path request to raise HTTPError")
            except urllib.error.HTTPError as exc:
                self.assertEqual(exc.code, 403)
                exc.close()
        finally:
            server.DATA_ROOT = original_data_root
            if httpd is not None:
                httpd.shutdown()
                httpd.server_close()
            if thread is not None:
                thread.join(timeout=2)

    def test_run_log_route_serves_saved_log_contents(self) -> None:
        project = storage.create_project("Run Log Route", "", "", data_root=self.data_root)
        run_id = "validate-123"
        log_path = storage.run_dir(project["project_id"], run_id, self.data_root) / "run.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("log line one\nlog line two\n", encoding="utf-8")
        storage.save_run(
            {
                "project_id": project["project_id"],
                "run_id": run_id,
                "kind": "validate",
                "status": "succeeded",
                "stage": "done",
                "started_at": storage.utc_now(),
                "finished_at": storage.utc_now(),
                "summary": "done",
                "log_path": str(log_path),
                "pid": None,
            },
            self.data_root,
        )

        original_data_root = server.DATA_ROOT
        httpd: ThreadingHTTPServer | None = None
        thread: threading.Thread | None = None
        try:
            server.DATA_ROOT = self.data_root
            httpd, thread, port = self._serve_gui()
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/projects/{project['project_id']}/runs/{run_id}/log"
            ) as response:
                self.assertEqual(response.read().decode("utf-8"), "log line one\nlog line two\n")
        finally:
            server.DATA_ROOT = original_data_root
            if httpd is not None:
                httpd.shutdown()
                httpd.server_close()
            if thread is not None:
                thread.join(timeout=2)

    def test_missing_project_route_returns_404_error_page(self) -> None:
        original_data_root = server.DATA_ROOT
        httpd: ThreadingHTTPServer | None = None
        thread: threading.Thread | None = None
        try:
            server.DATA_ROOT = self.data_root
            httpd, thread, port = self._serve_gui()
            with self.assertRaises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/projects/does-not-exist")
            self.assertEqual(exc.exception.code, 404)
            body = exc.exception.read().decode("utf-8")
            self.assertIn("Project not found.", body)
            exc.exception.close()
        finally:
            server.DATA_ROOT = original_data_root
            if httpd is not None:
                httpd.shutdown()
                httpd.server_close()
            if thread is not None:
                thread.join(timeout=2)

    def test_invalid_page_returns_404_error_page(self) -> None:
        original_data_root = server.DATA_ROOT
        httpd: ThreadingHTTPServer | None = None
        thread: threading.Thread | None = None
        try:
            server.DATA_ROOT = self.data_root
            httpd, thread, port = self._serve_gui()
            with self.assertRaises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/not-a-real-page")
            self.assertEqual(exc.exception.code, 404)
            body = exc.exception.read().decode("utf-8")
            self.assertIn("Page not found.", body)
            exc.exception.close()
        finally:
            server.DATA_ROOT = original_data_root
            if httpd is not None:
                httpd.shutdown()
                httpd.server_close()
            if thread is not None:
                thread.join(timeout=2)

    @mock.patch("gui_app.server.GuiHandler.start_job")
    def test_validate_route_redirects_and_starts_validation_job(self, start_job: mock.Mock) -> None:
        project = storage.create_project("Validate Route", "", "", data_root=self.data_root)
        start_job.return_value = "validate-test"

        original_data_root = server.DATA_ROOT
        httpd: ThreadingHTTPServer | None = None
        thread: threading.Thread | None = None
        try:
            server.DATA_ROOT = self.data_root
            httpd, thread, port = self._serve_gui()
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/projects/{project['project_id']}/validate",
                method="POST",
                data=b"",
            )
            opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
            response = opener.open(request)

            self.assertEqual(response.geturl(), f"http://127.0.0.1:{port}/projects/{project['project_id']}?step=run")
            start_job.assert_called_once()
            called_project, called_kind = start_job.call_args.args
            self.assertEqual(called_project["project_id"], project["project_id"])
            self.assertEqual(called_kind, "validate")
        finally:
            server.DATA_ROOT = original_data_root
            if httpd is not None:
                httpd.shutdown()
                httpd.server_close()
            if thread is not None:
                thread.join(timeout=2)

    def test_dashboard_renders_running_project_status_from_latest_run(self) -> None:
        project = storage.create_project("Dashboard Status", "ICLR 2027", "status coverage", data_root=self.data_root)
        storage.save_run(
            {
                "project_id": project["project_id"],
                "run_id": "validate-running",
                "kind": "validate",
                "status": "running",
                "stage": "starting",
                "started_at": storage.utc_now(),
                "finished_at": None,
                "summary": "Validation is in progress",
                "log_path": str(storage.run_dir(project["project_id"], "validate-running", self.data_root) / "run.log"),
                "pid": os.getpid(),
            },
            self.data_root,
        )

        original_data_root = server.DATA_ROOT
        httpd: ThreadingHTTPServer | None = None
        thread: threading.Thread | None = None
        try:
            server.DATA_ROOT = self.data_root
            httpd, thread, port = self._serve_gui()
            response = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            body = response.read().decode("utf-8")
            self.assertIn("Dashboard Status", body)
            self.assertIn('<div class="status running">Running</div>', body)
        finally:
            server.DATA_ROOT = original_data_root
            if httpd is not None:
                httpd.shutdown()
                httpd.server_close()
            if thread is not None:
                thread.join(timeout=2)

    @mock.patch("gui_app.server.atlas_controller.run_literature_prompt_in_atlas")
    def test_atlas_run_research_route_returns_redirect_and_persists_result(
        self,
        run_literature_prompt_in_atlas: mock.Mock,
    ) -> None:
        template_src = Path(self.tempdir.name) / "template.tex"
        template_src.write_text("\\documentclass{article}\\begin{document}Draft\\end{document}\n", encoding="utf-8")

        project = storage.create_project("Atlas Route Paper", "ICLR 2027", "Route coverage", data_root=self.data_root)
        project["experimental"]["log_text"] = "## 1. Experimental Setup\n\nSetup"
        project["guidelines"]["guidelines_text"] = "Submission deadline: October 1, 2026."
        project["uploads"]["template_tex"] = str(template_src)
        storage.save_project(project, self.data_root)

        run_literature_prompt_in_atlas.return_value = {
            "deep_research_enabled": True,
            "verification_method": "accessibility",
            "submitted": True,
            "mode_used": "deep_research",
            "fallback_reason": "",
            "screenshot_paths": ["/tmp/atlas-route.png"],
            "action_sequence": ["activate_atlas", "submit_prompt"],
            "started_at": storage.utc_now(),
            "finished_at": storage.utc_now(),
        }

        original_data_root = server.DATA_ROOT
        httpd: ThreadingHTTPServer | None = None
        thread: threading.Thread | None = None
        try:
            server.DATA_ROOT = self.data_root
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.GuiHandler)
            port = httpd.server_address[1]
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()

            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/projects/{project['project_id']}/atlas/run_research",
                method="POST",
                data=b"",
            )
            opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
            response = opener.open(request)

            self.assertEqual(response.geturl(), f"http://127.0.0.1:{port}/projects/{project['project_id']}?step=outputs")
            saved_project = storage.load_project(project["project_id"], self.data_root)
            self.assertEqual(saved_project["latest_atlas_result"]["verification_method"], "accessibility")
            runs = storage.list_runs(project["project_id"], self.data_root)
            self.assertEqual(runs[0]["kind"], "atlas_literature")
        finally:
            server.DATA_ROOT = original_data_root
            if httpd is not None:
                httpd.shutdown()
                httpd.server_close()
            if thread is not None:
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
