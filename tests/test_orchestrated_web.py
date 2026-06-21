from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from gui_app import atlas_controller
from gui_app import orchestrator
from gui_app import storage


class RuntimeConfigTests(unittest.TestCase):
    def test_load_runtime_env_reads_repo_env_without_overwriting_existing(self) -> None:
        from gui_app import config

        with tempfile.TemporaryDirectory() as tempdir:
            repo_root = Path(tempdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            global_config = Path(tempdir) / "global-config"
            (repo_root / ".env").write_text(
                "SEMANTIC_SCHOLAR_API_KEY=repo-key\nEXA_API_KEY=repo-exa\n",
                encoding="utf-8",
            )

            with mock.patch.object(config, "REPO_ROOT", repo_root), mock.patch.object(config, "GLOBAL_CONFIG_PATH", global_config):
                env = {"EXA_API_KEY": "existing-exa"}
                loaded = config.load_runtime_env(env)

            self.assertEqual(loaded["SEMANTIC_SCHOLAR_API_KEY"], "repo-key")
            self.assertEqual(loaded["EXA_API_KEY"], "existing-exa")

    def test_load_runtime_env_bootstraps_ca_bundle_from_certifi(self) -> None:
        from gui_app import config

        with tempfile.TemporaryDirectory() as tempdir:
            global_config = Path(tempdir) / "global-config"
            with mock.patch.object(config, "GLOBAL_CONFIG_PATH", global_config), mock.patch.object(config, "_default_ca_bundle", return_value="/tmp/certifi.pem"):
                loaded = config.load_runtime_env({})

        self.assertEqual(loaded["SSL_CERT_FILE"], "/tmp/certifi.pem")
        self.assertEqual(loaded["REQUESTS_CA_BUNDLE"], "/tmp/certifi.pem")
        self.assertEqual(loaded["CURL_CA_BUNDLE"], "/tmp/certifi.pem")


class StoragePipelineRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tempdir.name) / "gui-data"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_create_pipeline_run_initializes_stage_state(self) -> None:
        project = storage.create_project("Test Paper", "", "", data_root=self.data_root)

        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)

        self.assertEqual(run_payload["kind"], "pipeline_v2")
        self.assertEqual(run_payload["status"], "queued")
        self.assertEqual(run_payload["current_stage"], "queued")
        self.assertTrue((storage.run_dir(project["project_id"], run_payload["run_id"], self.data_root) / "state.json").exists())
        self.assertTrue((storage.run_dir(project["project_id"], run_payload["run_id"], self.data_root) / "events.jsonl").exists())
        self.assertEqual(
            run_payload["stage_order"],
            list(storage.PIPELINE_STAGE_ORDER),
        )
        self.assertEqual(
            list(run_payload["stages"].keys()),
            list(storage.PIPELINE_STAGE_ORDER),
        )
        self.assertEqual(run_payload["stages"]["plotting"]["status"], "pending")
        self.assertEqual(run_payload["stages"]["literature"]["attempt"], 1)
        self.assertTrue(Path(run_payload["stages"]["literature"]["attempt_dir"]).exists())

    def test_load_run_rebuilds_state_from_event_log_when_snapshot_is_missing(self) -> None:
        project = storage.create_project("Replay Paper", "", "", data_root=self.data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        storage.update_stage_state(
            run_payload,
            "validate",
            self.data_root,
            status="running",
            summary="validation started",
        )
        storage.update_stage_state(
            run_payload,
            "validate",
            self.data_root,
            status="succeeded",
            summary="validation finished",
        )

        storage.run_state_file(project["project_id"], run_payload["run_id"], self.data_root).unlink()
        rebuilt = storage.load_run(project["project_id"], run_payload["run_id"], self.data_root)

        self.assertIsNotNone(rebuilt)
        self.assertEqual(rebuilt["stages"]["validate"]["status"], "succeeded")
        self.assertEqual(rebuilt["stages"]["validate"]["summary"], "validation finished")
        self.assertTrue(storage.run_state_file(project["project_id"], run_payload["run_id"], self.data_root).exists())

    def test_stage_state_replays_substeps_and_loop_state(self) -> None:
        project = storage.create_project("Nested Replay", "", "", data_root=self.data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        storage.upsert_stage_substep(
            run_payload,
            "refinement",
            "iter1.review",
            self.data_root,
            status="succeeded",
            summary="Review complete",
        )
        storage.set_stage_loop_state(
            run_payload,
            "refinement",
            self.data_root,
            current_iteration=1,
            best_iteration=0,
            halt_reason="",
            score_trajectory=[{"iteration": 0, "overall_score": 62.5, "decision": "ACCEPT_BASELINE"}],
            accepted_iterations=[0],
        )

        storage.run_state_file(project["project_id"], run_payload["run_id"], self.data_root).unlink()
        rebuilt = storage.load_run(project["project_id"], run_payload["run_id"], self.data_root)

        self.assertIsNotNone(rebuilt)
        assert rebuilt is not None
        self.assertEqual(rebuilt["stages"]["refinement"]["substeps"][0]["name"], "iter1.review")
        self.assertEqual(rebuilt["stages"]["refinement"]["substeps"][0]["status"], "succeeded")
        self.assertEqual(rebuilt["stages"]["refinement"]["loop_state"]["current_iteration"], 1)
        self.assertEqual(rebuilt["stages"]["refinement"]["loop_state"]["accepted_iterations"], [0])

    def test_reset_pipeline_run_from_stage_preserves_completed_sibling(self) -> None:
        project = storage.create_project("Retry Paper", "", "", data_root=self.data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)

        for stage_name in ("ingest", "validate", "outline", "literature"):
            storage.update_stage_state(
                run_payload,
                stage_name,
                self.data_root,
                status="succeeded",
                summary=f"{stage_name} done",
            )
        storage.update_stage_state(
            run_payload,
            "plotting",
            self.data_root,
            status="failed",
            summary="plotting failed",
            attention_required={"reason": "manual_review", "message": "plotting failed", "details": {}},
        )
        storage.update_stage_state(
            run_payload,
            "section_writing",
            self.data_root,
            status="failed",
            summary="downstream blocked",
        )

        reset = storage.reset_pipeline_run_from_stage(run_payload, "plotting", self.data_root)

        self.assertEqual(reset["status"], "queued")
        self.assertEqual(reset["stages"]["plotting"]["status"], "pending")
        self.assertEqual(reset["stages"]["plotting"]["attempt"], 2)
        self.assertIsNone(reset["stages"]["plotting"]["attention_required"])
        self.assertTrue(reset["stages"]["plotting"]["attempt_dir"].endswith("attempt-002"))
        self.assertTrue(Path(reset["stages"]["plotting"]["attempt_dir"]).exists())
        self.assertEqual(reset["stages"]["literature"]["status"], "succeeded")
        self.assertEqual(reset["stages"]["section_writing"]["status"], "pending")

    def test_save_stage_artifacts_emits_per_artifact_events_and_rebuilds_state(self) -> None:
        project = storage.create_project("Artifact Replay", "", "", data_root=self.data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        artifact_one = str(Path(self.tempdir.name) / "one.txt")
        artifact_two = str(Path(self.tempdir.name) / "two.txt")

        storage.save_stage_artifacts(
            run_payload,
            "outline",
            self.data_root,
            [artifact_one, artifact_two],
        )

        events = storage.load_jsonl(storage.run_events_file(project["project_id"], run_payload["run_id"], self.data_root))
        artifact_events = [item for item in events if item.get("type") == "artifact_written"]
        self.assertEqual(len(artifact_events), 2)
        self.assertEqual(artifact_events[0]["details"]["stage"], "outline")
        self.assertEqual(artifact_events[0]["details"]["path"], artifact_one)
        self.assertEqual(artifact_events[1]["details"]["path"], artifact_two)

        storage.run_state_file(project["project_id"], run_payload["run_id"], self.data_root).unlink()
        rebuilt = storage.load_run(project["project_id"], run_payload["run_id"], self.data_root)

        self.assertIsNotNone(rebuilt)
        assert rebuilt is not None
        self.assertEqual(rebuilt["stages"]["outline"]["artifacts"], [artifact_one, artifact_two])


class AtlasTaskTests(unittest.TestCase):
    @mock.patch("gui_app.atlas_controller._stage_and_send_query")
    def test_run_task_uses_deep_research_when_requested(self, stage_and_send_query: mock.Mock) -> None:
        stage_and_send_query.return_value = {
            "submitted": True,
            "response_text": "Research summary",
            "response_detected": True,
            "completion_state": "completed",
            "wait_strategy_used": "stability_then_idle",
            "extraction_method": "accessibility",
            "screenshot_paths": ["/tmp/a.png"],
            "action_sequence": ["submit_prompt"],
            "started_at": "2026-04-17T00:00:00+00:00",
            "finished_at": "2026-04-17T00:01:00+00:00",
            "error_message": "",
        }

        with mock.patch("gui_app.atlas_controller.verify_deep_research_enabled", return_value={
            "enabled": True,
            "method": "accessibility",
            "screenshot_paths": ["/tmp/verify.png"],
        }):
            result = atlas_controller.run_atlas_task(
                "Find papers",
                atlas_controller.AtlasTaskOptions(require_deep_research=True),
            )

        self.assertTrue(result["submitted"])
        self.assertEqual(result["mode_used"], "deep_research")
        self.assertTrue(result["deep_research_enabled"])
        self.assertEqual(result["verification_method"], "accessibility")
        self.assertIn("/tmp/verify.png", result["screenshot_paths"])


class WebAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tempdir.name) / "gui-data"
        from gui_app import web

        self.app = web.create_app(data_root=self.data_root)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.tempdir.cleanup()

    def test_dashboard_renders_and_create_project_redirects(self) -> None:
        from gui_app import web

        mocked_integrations = {
            "codex": {"available": True},
            "atlas": {"available": False},
            "semantic_scholar": {"configured": True},
            "figure_backend": {"valid": False, "selected_backend": ""},
        }

        with mock.patch.object(web, "_integration_summary", return_value=mocked_integrations):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("PaperOrchestra Control Room", response.text)
        self.assertIn(">Reachable</span>", response.text)
        self.assertIn(">Unreachable</span>", response.text)
        self.assertIn(">Active</span>", response.text)
        self.assertIn(">Inactive</span>", response.text)
        self.assertNotIn(">Available</span>", response.text)
        self.assertNotIn(">Configured</span>", response.text)

        create = self.client.post(
            "/projects",
            data={
                "title": "Autonomous Paper",
                "venue": "ICLR 2027",
                "description": "Control room test",
                "source_directory": "",
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 303)
        self.assertIn("/projects/", create.headers["location"])

    def test_health_endpoint_reports_ok(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertIn("integrations", payload)

    def test_api_create_project_returns_json_and_persists_ingest_source(self) -> None:
        source_directory = str(Path(self.tempdir.name) / "source")

        response = self.client.post(
            "/api/projects",
            json={
                "title": "Native API Paper",
                "venue": "ICLR 2027",
                "description": "Created by a native client.",
                "source_directory": source_directory,
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        project = payload["project"]
        self.assertEqual(project["title"], "Native API Paper")
        self.assertEqual(project["venue"], "ICLR 2027")
        self.assertEqual(project["ingest"]["source_directory"], source_directory)
        self.assertTrue(project["ingest"]["enabled"])
        self.assertTrue((self.data_root / "projects" / project["project_id"] / "project.json").exists())

        list_response = self.client.get("/api/projects")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["projects"][0]["project_id"], project["project_id"])

    def test_api_setup_updates_project_and_syncs_workspace(self) -> None:
        project = storage.create_project("Draft Paper", "", "", data_root=self.data_root)
        source_directory = str(Path(self.tempdir.name) / "source-materials")

        response = self.client.post(
            f"/api/projects/{project['project_id']}/setup",
            json={
                "title": "Ready Paper",
                "venue": "NeurIPS 2027",
                "description": "Ready for native inputs.",
                "source_directory": source_directory,
            },
        )

        self.assertEqual(response.status_code, 200)
        saved = storage.load_project(project["project_id"], self.data_root)
        self.assertEqual(saved["title"], "Ready Paper")
        self.assertEqual(saved["wizard_step"], "inputs")
        self.assertEqual(saved["ingest"]["source_directory"], source_directory)
        self.assertTrue(Path(saved["workspace_path"], "inputs", "idea.md").exists())

    def test_api_save_input_idea_raw_updates_canonical_text_and_validation(self) -> None:
        project = storage.create_project("Native Input Paper", "", "", data_root=self.data_root)
        raw_markdown = (
            "## Problem Statement\n\nNative project setup needs a JSON API.\n\n"
            "## Core Hypothesis\n\nShared backend actions prevent drift.\n\n"
            "## Proposed Methodology (High-Level Technical Approach)\n\nRoute native actions through FastAPI.\n\n"
            "## Expected Contribution\n\nA cleaner native integration boundary.\n"
        )

        response = self.client.post(
            f"/api/projects/{project['project_id']}/inputs/idea",
            json={
                "editor_mode": "raw",
                "raw_markdown": raw_markdown,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("validation", payload)
        self.assertIn("input", payload)
        saved = storage.load_project(project["project_id"], self.data_root)
        self.assertEqual(saved["idea"]["raw_markdown"], raw_markdown)
        self.assertEqual(saved["idea"]["problem_statement"], "Native project setup needs a JSON API.")
        self.assertEqual(
            Path(saved["workspace_path"], "inputs", "idea.md").read_text(encoding="utf-8"),
            raw_markdown,
        )

    def test_api_save_input_accepts_template_upload(self) -> None:
        project = storage.create_project("Native Upload Paper", "", "", data_root=self.data_root)
        template_text = "\\documentclass{article}\n\\begin{document}\nUploaded template\n\\end{document}\n"

        response = self.client.post(
            f"/api/projects/{project['project_id']}/inputs/template",
            data={"template_text": "will be replaced by upload"},
            files={"template_upload": ("template.tex", template_text.encode("utf-8"), "text/x-tex")},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("validation", payload)
        saved = storage.load_project(project["project_id"], self.data_root)
        self.assertEqual(saved["template"]["text"], template_text)
        self.assertEqual(saved["template"]["source_filename"], "template.tex")
        self.assertTrue(Path(saved["uploads"]["template_tex"]).exists())
        self.assertEqual(
            Path(saved["workspace_path"], "inputs", "template.tex").read_text(encoding="utf-8"),
            template_text,
        )

    def test_api_save_input_accepts_multiple_figure_uploads_and_remove(self) -> None:
        project = storage.create_project("Native Figure Upload Paper", "", "", data_root=self.data_root)

        response = self.client.post(
            f"/api/projects/{project['project_id']}/inputs/figures",
            files=[
                ("figure_uploads", ("figure-a.png", b"png-a", "image/png")),
                ("figure_uploads", ("figure-b.png", b"png-b", "image/png")),
            ],
        )

        self.assertEqual(response.status_code, 200)
        saved = storage.load_project(project["project_id"], self.data_root)
        figures = saved["uploads"]["figures"]
        self.assertEqual(len(figures), 2)
        self.assertTrue(all(Path(path).exists() for path in figures))
        workspace_figures = Path(saved["workspace_path"], "inputs", "figures")
        self.assertTrue((workspace_figures / "figure-a.png").exists())
        self.assertTrue((workspace_figures / "figure-b.png").exists())

        remove_response = self.client.post(
            f"/api/projects/{project['project_id']}/inputs/figures/remove",
            json={"path": figures[0]},
        )

        self.assertEqual(remove_response.status_code, 200)
        saved_after_remove = storage.load_project(project["project_id"], self.data_root)
        self.assertEqual(saved_after_remove["uploads"]["figures"], [figures[1]])
        self.assertFalse((workspace_figures / "figure-a.png").exists())
        self.assertTrue((workspace_figures / "figure-b.png").exists())

    def test_api_start_run_reports_validation_blockers_as_conflict(self) -> None:
        project = storage.create_project("Blocked API Start", "", "", data_root=self.data_root)

        response = self.client.post(f"/api/projects/{project['project_id']}/runs/start")

        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["error"], "inputs_blocked")
        self.assertEqual(payload["detail"], "Project inputs have blockers.")
        self.assertTrue(payload["validation"]["has_blockers"])

    def test_api_start_run_returns_decorated_run_state(self) -> None:
        project = storage.create_project("Runnable API Paper", "", "", data_root=self.data_root)

        def fake_validation(_project: dict[str, object], _data_root: Path) -> dict[str, object]:
            return {
                "status": "validated",
                "summary": "All required inputs are ready.",
                "updated_at": storage.utc_now(),
                "has_blockers": False,
                "inputs": {},
            }

        def fake_start(project_id: str, data_root: Path) -> str:
            run_payload = storage.create_pipeline_run(project_id, data_root)
            run_payload = storage.update_run_fields(
                project_id,
                run_payload["run_id"],
                data_root,
                event_type="run_started",
                pid=12345,
                status="running",
                current_stage="starting",
                stage="starting",
                summary="Pipeline run started.",
            )
            saved_project = storage.load_project(project_id, data_root)
            saved_project["latest_run_id"] = run_payload["run_id"]
            saved_project["last_status"] = "running"
            storage.save_project(saved_project, data_root)
            return run_payload["run_id"]

        with mock.patch("gui_app.web.storage.validate_project_inputs", side_effect=fake_validation):
            with mock.patch("gui_app.web.orchestrator.start_run", side_effect=fake_start):
                with mock.patch("gui_app.storage.is_pid_running", side_effect=lambda pid: bool(pid)):
                    response = self.client.post(f"/api/projects/{project['project_id']}/runs/start")

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["run"]["status"], "running")
        self.assertEqual(payload["run"]["summary"], "Pipeline run started.")
        self.assertIn("validate", payload["run"]["stages"])

    def test_api_retry_resume_and_cancel_run_return_updated_state(self) -> None:
        project = storage.create_project("Run Action API Paper", "", "", data_root=self.data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        for stage_name in ("ingest", "validate", "outline"):
            run_payload = storage.update_stage_state(
                run_payload,
                stage_name,
                self.data_root,
                status="succeeded",
                summary=f"{stage_name} done",
            )
        storage.update_stage_state(
            run_payload,
            "plotting",
            self.data_root,
            status="failed",
            summary="plotting failed",
        )

        with mock.patch("gui_app.orchestrator._spawn_worker", return_value=23456):
            with mock.patch("gui_app.storage.is_pid_running", side_effect=lambda pid: bool(pid)):
                retry_response = self.client.post(
                    f"/api/projects/{project['project_id']}/runs/{run_payload['run_id']}/retry/plotting"
                )

        self.assertEqual(retry_response.status_code, 202)
        retry_payload = retry_response.json()["run"]
        self.assertEqual(retry_payload["status"], "running")
        self.assertEqual(retry_payload["current_stage"], "plotting")

        with mock.patch("gui_app.orchestrator._spawn_worker", return_value=34567):
            with mock.patch("gui_app.storage.is_pid_running", side_effect=lambda pid: pid == 34567):
                resume_response = self.client.post(
                    f"/api/projects/{project['project_id']}/runs/{run_payload['run_id']}/resume"
                )

        self.assertEqual(resume_response.status_code, 200)
        self.assertIn("run", resume_response.json())

        with mock.patch("gui_app.storage.is_pid_running", return_value=False):
            cancel_response = self.client.post(
                f"/api/projects/{project['project_id']}/runs/{run_payload['run_id']}/cancel"
            )

        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_response.json()["run"]["status"], "cancelled")

    def test_api_artifacts_returns_workspace_and_run_artifacts(self) -> None:
        project = storage.create_project("Artifact API Paper", "", "", data_root=self.data_root)
        project = storage.sync_workspace(project, self.data_root)
        workspace = Path(project["workspace_path"])
        final_pdf = workspace / "final" / "paper.pdf"
        final_pdf.parent.mkdir(parents=True, exist_ok=True)
        final_pdf.write_bytes(b"%PDF-1.4\n")
        stage_artifact = workspace / "outline.json"
        stage_artifact.write_text('{"ok": true}\n', encoding="utf-8")
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        storage.save_stage_artifacts(
            run_payload,
            "outline",
            self.data_root,
            [str(stage_artifact)],
        )
        project["latest_run_id"] = run_payload["run_id"]
        storage.save_project(project, self.data_root)

        response = self.client.get(f"/api/projects/{project['project_id']}/artifacts")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        workspace_paths = {item["path"] for item in payload["workspace_artifacts"]}
        run_paths = {item["path"] for item in payload["run_artifacts"]}
        self.assertIn(str(final_pdf), workspace_paths)
        self.assertIn(str(stage_artifact), run_paths)

    def test_api_workspace_snapshot_returns_native_read_model(self) -> None:
        project = storage.create_project("Snapshot API Paper", "", "", data_root=self.data_root)
        project["idea"]["editor_mode"] = "raw"
        project["idea"]["raw_markdown"] = "## Problem Statement\n\nNative read model"
        validation = {
            "status": "validated",
            "summary": "All required inputs are ready.",
            "updated_at": "2026-06-21T00:00:00+00:00",
            "has_blockers": False,
            "inputs": {
                "idea": {"messages": [], "has_blockers": False, "completed": True},
                "experimental": {"messages": [], "has_blockers": False, "completed": True},
                "template": {"messages": [], "has_blockers": False, "completed": True},
                "guidelines": {"messages": [], "has_blockers": False, "completed": True},
                "figures": {"messages": [], "has_blockers": False, "completed": False},
            },
        }
        project = storage.save_project(project, self.data_root)
        storage.update_latest_validation(project, validation, self.data_root)
        project = storage.sync_workspace(storage.load_project(project["project_id"], self.data_root), self.data_root)
        workspace = Path(project["workspace_path"])
        final_pdf = workspace / "final" / "paper.pdf"
        final_pdf.parent.mkdir(parents=True, exist_ok=True)
        final_pdf.write_bytes(b"%PDF-1.4\n")
        stage_artifact = workspace / "outline.json"
        stage_artifact.write_text('{"ok": true}\n', encoding="utf-8")
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        run_payload = storage.update_stage_state(
            run_payload,
            "outline",
            self.data_root,
            status="succeeded",
            summary="Outline ready",
            performance={"wall_seconds": 3.2, "total_cpu_seconds": 1.25, "cpu_percent_of_one_core": 42.0},
        )
        run_payload = storage.save_stage_artifacts(
            run_payload,
            "outline",
            self.data_root,
            [str(stage_artifact), str(workspace / "missing.log")],
        )
        project["latest_run_id"] = run_payload["run_id"]
        storage.save_project(project, self.data_root)

        from gui_app import web

        mocked_integrations = {
            "codex": {"available": True, "path": "/usr/local/bin/codex"},
            "atlas": {"available": False},
            "browser_adapter": {"primary": "local"},
            "figure_backend": {"selected_backend": "local"},
        }

        with mock.patch.object(web, "_integration_summary", return_value=mocked_integrations):
            response = self.client.get(
                "/api/workspace/snapshot",
                params={
                    "selected_project_id": project["project_id"],
                    "selected_run_id": run_payload["run_id"],
                    "selected_stage_name": "outline",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["selected_project"]["id"], project["project_id"])
        self.assertEqual(payload["selected_project_inputs"]["idea"]["raw_markdown"], "## Problem Statement\n\nNative read model")
        self.assertTrue(payload["selected_project_inputs"]["idea"]["validation"]["completed"])
        self.assertEqual(payload["selected_run"]["id"], run_payload["run_id"])
        self.assertEqual(payload["selected_stage"]["name"], "outline")
        self.assertEqual(payload["selected_stage"]["performance_summary"], "3.20s wall · 1.25s CPU · 42% of one core")
        artifact_paths = {item["path"] for item in payload["selected_run"]["artifacts"]}
        self.assertIn(str(final_pdf.resolve(strict=False)), artifact_paths)
        self.assertIn(str(stage_artifact.resolve(strict=False)), artifact_paths)
        missing_path = str((workspace / "missing.log").resolve(strict=False))
        self.assertIn(missing_path, artifact_paths)
        missing = next(item for item in payload["selected_run"]["artifacts"] if item["path"] == missing_path)
        self.assertFalse(missing["exists"])
        self.assertEqual(payload["selected_run"]["diagnostics"]["events_log_path"], str(storage.run_dir(project["project_id"], run_payload["run_id"], self.data_root) / "events.jsonl"))
        self.assertTrue(payload["integrations"]["backend_reachable"])
        self.assertTrue(payload["integrations"]["repo_configured"])
        self.assertTrue(payload["integrations"]["python_configured"])
        self.assertTrue(payload["integrations"]["data_root_readable"])
        self.assertEqual(payload["integrations"]["data_root"], str(self.data_root))
        self.assertEqual(payload["integrations"]["codex"]["path"], "/usr/local/bin/codex")
        self.assertEqual(payload["integrations"]["browser_adapter"]["primary"], "local")

    def test_api_workspace_snapshot_guards_out_of_scope_worker_logs(self) -> None:
        project = storage.create_project("Snapshot Guard Paper", "", "", data_root=self.data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        secret_log = Path(self.tempdir.name) / "secret-worker.log"
        secret_stderr_log = Path(self.tempdir.name) / "secret-worker.err.log"
        secret_log.write_text("TOP-SECRET-WORKER-LOG\n", encoding="utf-8")
        secret_stderr_log.write_text("TOP-SECRET-WORKER-STDERR\n", encoding="utf-8")
        run_payload["worker_stdout_log_path"] = str(secret_log)
        run_payload["worker_stderr_log_path"] = str(secret_stderr_log)
        run_payload = storage.save_run(run_payload, self.data_root)
        storage.append_run_event(
            run_payload,
            "worker_path_snapshot",
            self.data_root,
            {"stdout": str(secret_log), "stderr": str(secret_stderr_log)},
        )
        project["latest_run_id"] = run_payload["run_id"]
        storage.save_project(project, self.data_root)

        response = self.client.get(
            "/api/workspace/snapshot",
            params={
                "selected_project_id": project["project_id"],
                "selected_run_id": run_payload["run_id"],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        response_text = json.dumps(payload)
        self.assertNotIn("TOP-SECRET-WORKER-LOG", response_text)
        self.assertNotIn("TOP-SECRET-WORKER-STDERR", response_text)
        self.assertNotIn(str(secret_log), response_text)
        self.assertNotIn(str(secret_stderr_log), response_text)
        self.assertEqual(payload["selected_run"]["diagnostics"]["stdout_log_path"], secret_log.name)
        self.assertEqual(payload["selected_run"]["diagnostics"]["stderr_log_path"], secret_stderr_log.name)
        stdout_log = next(item for item in payload["selected_run"]["diagnostics"]["logs"] if item["kind"] == "stdout")
        self.assertEqual(stdout_log["text"], "")
        self.assertEqual(stdout_log["path"], secret_log.name)
        self.assertIn("outside the selected project", stdout_log["error_message"])
        stderr_log = next(item for item in payload["selected_run"]["diagnostics"]["logs"] if item["kind"] == "stderr")
        self.assertEqual(stderr_log["text"], "")
        self.assertEqual(stderr_log["path"], secret_stderr_log.name)
        self.assertIn("outside the selected project", stderr_log["error_message"])
        events_log = next(item for item in payload["selected_run"]["diagnostics"]["logs"] if item["kind"] == "events")
        self.assertNotIn(str(secret_log), events_log["text"])
        self.assertNotIn(str(secret_stderr_log), events_log["text"])
        self.assertIn(secret_log.name, events_log["text"])
        self.assertIn(secret_stderr_log.name, events_log["text"])

    def test_inputs_step_renders_workbench_and_sections(self) -> None:
        project = storage.create_project("Inputs UI Paper", "", "", data_root=self.data_root)

        response = self.client.get(f"/projects/{project['project_id']}?step=inputs")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Input Workbench", response.text)
        self.assertIn("Next incomplete input", response.text)
        self.assertIn("Experimental Log", response.text)
        self.assertIn("Template", response.text)
        self.assertIn("Guidelines", response.text)
        self.assertIn("Figures", response.text)

    def test_legacy_input_steps_redirect_to_inputs_panels(self) -> None:
        project = storage.create_project("Legacy Step Paper", "", "", data_root=self.data_root)

        response = self.client.get(
            f"/projects/{project['project_id']}?step=idea",
            follow_redirects=False,
        )

        self.assertIn(response.status_code, {302, 303, 307, 308})
        self.assertIn("?step=inputs&panel=idea", response.headers["location"])

    def test_inputs_status_endpoint_reports_missing_template(self) -> None:
        project = storage.create_project("Input Status Paper", "", "", data_root=self.data_root)

        response = self.client.get(f"/api/projects/{project['project_id']}/inputs/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("template", payload["inputs"])
        self.assertTrue(payload["inputs"]["template"]["has_blockers"])

    def test_save_input_idea_raw_updates_canonical_text_and_workspace(self) -> None:
        project = storage.create_project("Idea Save Paper", "", "", data_root=self.data_root)
        raw_markdown = (
            "## Problem Statement\n\nLong-context attention is expensive.\n\n"
            "## Core Hypothesis\n\nAdaptive sparsity preserves quality.\n\n"
            "## Proposed Methodology (High-Level Technical Approach)\n\nLearn a top-k selector.\n\n"
            "## Expected Contribution\n\nBetter efficiency-quality tradeoffs.\n"
        )

        response = self.client.post(
            f"/projects/{project['project_id']}/save/input/idea",
            data={
                "editor_mode": "raw",
                "raw_markdown": raw_markdown,
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("?step=inputs&panel=idea", response.headers["location"])
        saved = storage.load_project(project["project_id"], self.data_root)
        self.assertEqual(saved["idea"]["raw_markdown"], raw_markdown)
        self.assertEqual(saved["idea"]["problem_statement"], "Long-context attention is expensive.")
        self.assertEqual(
            (Path(saved["workspace_path"]) / "inputs" / "idea.md").read_text(encoding="utf-8"),
            raw_markdown,
        )

    def test_run_events_returns_stage_payload(self) -> None:
        project = storage.create_project("Events Paper", "", "", data_root=self.data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        storage.update_stage_state(
            run_payload,
            "validate",
            self.data_root,
            status="succeeded",
            summary="validated",
        )

        response = self.client.get(f"/api/projects/{project['project_id']}/runs/{run_payload['run_id']}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["run_id"], run_payload["run_id"])
        self.assertEqual(payload["stages"]["validate"]["summary"], "validated")

    def test_stage_detail_endpoint_returns_nested_stage_state(self) -> None:
        project = storage.create_project("Stage Detail Paper", "", "", data_root=self.data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        storage.upsert_stage_substep(
            run_payload,
            "refinement",
            "iter1.review",
            self.data_root,
            status="succeeded",
            summary="Review complete",
        )
        storage.set_stage_loop_state(
            run_payload,
            "refinement",
            self.data_root,
            current_iteration=1,
            best_iteration=0,
            halt_reason="",
            score_trajectory=[{"iteration": 0, "overall_score": 62.5, "decision": "ACCEPT_BASELINE"}],
            accepted_iterations=[0],
        )

        response = self.client.get(
            f"/api/projects/{project['project_id']}/runs/{run_payload['run_id']}/stages/refinement"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["substeps"][0]["name"], "iter1.review")
        self.assertEqual(payload["loop_state"]["current_iteration"], 1)
        self.assertIn("trajectory_labels", payload["loop_state"])

    def test_run_events_sse_streams_snapshot(self) -> None:
        project = storage.create_project("SSE Paper", "", "", data_root=self.data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)

        response = self.client.get(
            f"/api/projects/{project['project_id']}/runs/{run_payload['run_id']}/events"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertIn("retry: 1500", response.text)
        self.assertIn("event: snapshot", response.text)
        self.assertIn(run_payload["run_id"], response.text)

    def test_run_dashboard_surfaces_final_pdf_and_recent_artifacts(self) -> None:
        project = storage.create_project("Artifacts Paper", "", "", data_root=self.data_root)
        project = storage.sync_workspace(project, self.data_root)
        workspace = Path(project["workspace_path"])
        (workspace / "final").mkdir(parents=True, exist_ok=True)
        (workspace / "final" / "paper.pdf").write_bytes(b"%PDF-1.4\n")

        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        storage.update_stage_state(
            run_payload,
            "finalize",
            self.data_root,
            status="succeeded",
            summary="finalized",
        )
        storage.save_stage_artifacts(
            run_payload,
            "finalize",
            self.data_root,
            [str(workspace / "final" / "paper.pdf")],
        )
        project["latest_run_id"] = run_payload["run_id"]
        storage.save_project(project, self.data_root)

        response = self.client.get(f"/projects/{project['project_id']}?step=run")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Open final PDF", response.text)
        self.assertIn("Recent artifacts", response.text)
        self.assertIn("paper.pdf", response.text)

    def test_run_dashboard_surfaces_atlas_result_and_selected_figure_backend(self) -> None:
        from gui_app import config

        project = storage.create_project("Atlas UI Paper", "", "", data_root=self.data_root)
        project = storage.sync_workspace(project, self.data_root)
        workspace = Path(project["workspace_path"])
        atlas_cache = workspace / "cache" / "atlas"
        atlas_cache.mkdir(parents=True, exist_ok=True)
        result_path = atlas_cache / "atlas_result.json"
        response_path = atlas_cache / "literature_response.md"
        screenshot_path = atlas_cache / "atlas-shot.png"
        result_path.write_text('{"ok": true}\n', encoding="utf-8")
        response_path.write_text("Atlas synthesized research summary.\n", encoding="utf-8")
        screenshot_path.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"0" * 2048))

        project["latest_atlas_result"] = {
            "mode_used": "deep_research",
            "deep_research_enabled": True,
            "verification_method": "accessibility",
            "summary": "Atlas Deep Research task completed.",
            "fallback_reason": "",
            "result_path": str(result_path),
            "response_path": str(response_path),
            "screenshot_paths": [str(screenshot_path)],
        }
        storage.save_project(project, self.data_root)

        with mock.patch.object(config, "integration_health", return_value={
            "atlas": {"available": True, "enabled": True, "path": "/Applications/ChatGPT Atlas.app"},
            "codex": {"available": True, "path": "/opt/homebrew/bin/codex"},
            "semantic_scholar": {"configured": True, "masked": "secr...alue"},
            "exa": {"configured": False, "masked": ""},
            "paperbanana": {"configured": True, "valid": True, "path": "/tmp/PaperBanana"},
            "papervizagent": {"configured": False, "valid": False, "path": ""},
            "figure_backend": {
                "configured": True,
                "valid": True,
                "selected_backend": "paperbanana",
                "selected_root": "/tmp/PaperBanana",
                "paperbanana_root": "/tmp/PaperBanana",
                "papervizagent_root": "",
            },
        }):
            response = self.client.get(f"/projects/{project['project_id']}?step=run")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Atlas Status", response.text)
        self.assertIn("Atlas Deep Research task completed.", response.text)
        self.assertIn("Figure backend", response.text)
        self.assertIn(">Active</span>", response.text)
        self.assertIn("/tmp/PaperBanana", response.text)
        self.assertIn("Open Atlas result", response.text)
        self.assertIn("Open Atlas response", response.text)

    def test_run_dashboard_frames_manual_atlas_controls_as_debug_surface(self) -> None:
        project = storage.create_project("Atlas Messaging Paper", "", "", data_root=self.data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        project["latest_run_id"] = run_payload["run_id"]
        storage.save_project(project, self.data_root)

        response = self.client.get(f"/projects/{project['project_id']}?step=run")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Codex is the primary orchestrator.", response.text)
        self.assertIn("Manual Atlas literature task", response.text)
        self.assertIn("debug and override use only", response.text)

    def test_run_dashboard_surfaces_browser_adapter_health_and_latest_browser_result(self) -> None:
        from gui_app import config

        project = storage.create_project("Browser UI Paper", "", "", data_root=self.data_root)
        project = storage.sync_workspace(project, self.data_root)
        workspace = Path(project["workspace_path"])
        browser_cache = workspace / "cache" / "browser" / "chrome_devtools"
        browser_cache.mkdir(parents=True, exist_ok=True)
        result_path = browser_cache / "browser_result.json"
        response_path = browser_cache / "response.md"
        screenshot_path = browser_cache / "chrome-shot.png"
        result_path.write_text('{"ok": true}\n', encoding="utf-8")
        response_path.write_text("Chrome response\n", encoding="utf-8")
        screenshot_path.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"0" * 2048))

        project["latest_browser_result"] = {
            "adapter": "chrome_devtools",
            "status": "attention_required",
            "mode_used": "chrome_for_testing_launch",
            "summary": "ChatGPT is blocked behind a browser challenge.",
            "fallback_reason": "",
            "result_path": str(result_path),
            "raw_response_path": str(response_path),
            "response_path": str(response_path),
            "screenshot_paths": [str(screenshot_path)],
            "browser_runtime": "chrome_for_testing",
            "attach_transport": "launched_executable",
            "profile_root": "/Users/jeff/Library/Application Support/Google/Chrome for Testing",
            "readiness_state": "challenge_blocked",
            "readiness_message": "ChatGPT is blocked behind a browser challenge. Open the restored ChatGPT tab and complete the challenge once.",
            "tab_reused": True,
            "attention_required": {
                "reason": "chatgpt_challenge_blocked",
                "message": "ChatGPT is blocked behind a browser challenge. Open the restored ChatGPT tab and complete the challenge once.",
                "details": {"adapter": "chrome_devtools"},
            },
        }
        storage.save_project(project, self.data_root)

        with mock.patch.object(config, "integration_health", return_value={
            "chrome": {
                "available": True,
                "enabled": True,
                "compatible": True,
                "version": "147.0.7727.57",
                "path": "/Applications/Google Chrome.app",
                "mcp_available": True,
                "attach_mode": "chrome_for_testing_first",
                "plausibly_attachable": True,
                "global_registered": True,
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
            },
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
                "relaunch_required": False,
            },
            "browser_adapter": {
                "strategy": "chrome_for_testing_first",
                "primary": "chrome_devtools",
                "attach_mode": "chrome_for_testing_first",
                "fallback_order": ["chrome_for_testing", "chrome_stable", "atlas", "local"],
                "atlas_fallback_enabled": True,
                "local_fallback_enabled": True,
            },
            "atlas": {"available": True, "enabled": True, "path": "/Applications/ChatGPT Atlas.app"},
            "codex": {"available": True, "path": "/opt/homebrew/bin/codex"},
            "semantic_scholar": {"configured": True, "masked": "secr...alue"},
            "exa": {"configured": False, "masked": ""},
            "paperbanana": {"configured": False, "valid": False, "path": ""},
            "papervizagent": {"configured": False, "valid": False, "path": ""},
            "figure_backend": {
                "configured": False,
                "valid": False,
                "selected_backend": "",
                "selected_root": "",
                "paperbanana_root": "",
                "papervizagent_root": "",
            },
        }):
            response = self.client.get(f"/projects/{project['project_id']}?step=run")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Browser Adapter Status", response.text)
        self.assertIn("chrome_devtools", response.text)
        self.assertIn("ChatGPT is blocked behind a browser challenge.", response.text)
        self.assertIn("chrome_for_testing_launch", response.text)
        self.assertIn("Readiness state:", response.text)
        self.assertIn("Challenge Blocked", response.text)
        self.assertIn("ChatGPT tab reused:", response.text)
        self.assertIn("Codex-global Chrome DevTools MCP", response.text)
        self.assertIn("Install/repair Chrome MCP", response.text)
        self.assertIn("Relaunch Chrome for Testing in Debug Mode", response.text)
        self.assertIn("Retry browser attach", response.text)
        self.assertIn("/Users/jeff/.codex/bin/chrome-devtools-mcp-wrapper", response.text)
        self.assertIn("/Applications/Google Chrome for Testing.app", response.text)
        self.assertIn("http://127.0.0.1:9333", response.text)
        self.assertIn("/Users/jeff/Library/Application Support/Google/Chrome for Testing", response.text)
        self.assertIn("http://127.0.0.1:9222", response.text)
        self.assertIn("Primary runtime", response.text)
        self.assertIn("Chrome for Testing", response.text)
        self.assertIn("complete the challenge once", response.text)
        self.assertIn("Open browser result", response.text)
        self.assertIn("Open browser response", response.text)

    def test_install_repair_browser_route_calls_global_setup(self) -> None:
        project = storage.create_project("Install Browser MCP", "", "", data_root=self.data_root)

        with mock.patch("gui_app.web.global_browser_setup.install_or_repair", return_value={
            "mcp_server_name": "chrome-devtools",
            "wrapper_path": "/Users/jeff/.codex/bin/chrome-devtools-mcp-wrapper",
            "helper_path": "/Users/jeff/.codex/bin/chrome-debug-profile",
            "config_path": "/Users/jeff/.codex/config.toml",
            "registered_servers": ["chrome-devtools"],
        }) as install_mock:
            response = self.client.post(
                f"/projects/{project['project_id']}/browser/install_repair",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("?step=run", response.headers["location"])
        install_mock.assert_called_once()

    def test_launch_debug_helper_route_calls_global_setup(self) -> None:
        project = storage.create_project("Debug Browser MCP", "", "", data_root=self.data_root)

        with mock.patch("gui_app.web.global_browser_setup.launch_debug_profile") as launch_mock:
            response = self.client.post(
                f"/projects/{project['project_id']}/browser/launch_debug_helper",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("?step=run", response.headers["location"])
        launch_mock.assert_called_once()

    def test_retry_browser_attach_uses_debug_browser_url_for_one_shot_retry(self) -> None:
        project = storage.create_project("Retry Browser MCP", "", "", data_root=self.data_root)
        project = storage.sync_workspace(project, self.data_root)

        captured: dict[str, str] = {}

        def _fake_run_task(*args, **kwargs):
            captured["attach_mode"] = os.environ.get("PAPERORCHESTRA_CHROME_ATTACH_MODE", "")
            captured["browser_url"] = os.environ.get("PAPERORCHESTRA_CHROME_BROWSER_URL", "")
            captured["ws_endpoint"] = os.environ.get("PAPERORCHESTRA_CHROME_WS_ENDPOINT", "")
            return {
                "adapter": "chrome_devtools",
                "status": "failed",
                "summary": "retry attempted",
            }

        with mock.patch("gui_app.web.global_browser_setup.debug_browser_url", return_value="http://127.0.0.1:9333"):
            with mock.patch("gui_app.web.global_browser_setup.global_setup_health", return_value={"chrome_for_testing": {"ws_endpoint": ""}}):
                with mock.patch("gui_app.web.research_adapter.ResearchAdapter.run_task", side_effect=_fake_run_task) as run_task_mock:
                    response = self.client.post(
                        f"/projects/{project['project_id']}/browser/retry_attach",
                        follow_redirects=False,
                    )

        self.assertEqual(response.status_code, 303)
        self.assertIn("?step=run", response.headers["location"])
        self.assertEqual(captured["attach_mode"], "browser_url")
        self.assertEqual(captured["browser_url"], "http://127.0.0.1:9333")
        self.assertEqual(captured["ws_endpoint"], "")
        self.assertNotIn("PAPERORCHESTRA_CHROME_ATTACH_MODE", os.environ)
        self.assertNotIn("PAPERORCHESTRA_CHROME_BROWSER_URL", os.environ)
        self.assertNotIn("PAPERORCHESTRA_CHROME_WS_ENDPOINT", os.environ)
        run_task_mock.assert_called_once()

    def test_retry_browser_attach_prefers_ws_endpoint_when_available(self) -> None:
        project = storage.create_project("Retry Browser MCP WS", "", "", data_root=self.data_root)
        project = storage.sync_workspace(project, self.data_root)

        captured: dict[str, str] = {}

        def _fake_run_task(*args, **kwargs):
            captured["attach_mode"] = os.environ.get("PAPERORCHESTRA_CHROME_ATTACH_MODE", "")
            captured["browser_url"] = os.environ.get("PAPERORCHESTRA_CHROME_BROWSER_URL", "")
            captured["ws_endpoint"] = os.environ.get("PAPERORCHESTRA_CHROME_WS_ENDPOINT", "")
            return {
                "adapter": "chrome_devtools",
                "status": "failed",
                "summary": "retry attempted",
            }

        with mock.patch("gui_app.web.global_browser_setup.debug_browser_url", return_value="http://127.0.0.1:9333"):
            with mock.patch(
                "gui_app.web.global_browser_setup.global_setup_health",
                return_value={"chrome_for_testing": {"ws_endpoint": "ws://127.0.0.1:9333/devtools/browser/cft"}},
            ):
                with mock.patch("gui_app.web.research_adapter.ResearchAdapter.run_task", side_effect=_fake_run_task) as run_task_mock:
                    response = self.client.post(
                        f"/projects/{project['project_id']}/browser/retry_attach",
                        follow_redirects=False,
                    )

        self.assertEqual(response.status_code, 303)
        self.assertIn("?step=run", response.headers["location"])
        self.assertEqual(captured["attach_mode"], "ws_endpoint")
        self.assertEqual(captured["browser_url"], "http://127.0.0.1:9333")
        self.assertEqual(captured["ws_endpoint"], "ws://127.0.0.1:9333/devtools/browser/cft")
        self.assertNotIn("PAPERORCHESTRA_CHROME_ATTACH_MODE", os.environ)
        self.assertNotIn("PAPERORCHESTRA_CHROME_BROWSER_URL", os.environ)
        self.assertNotIn("PAPERORCHESTRA_CHROME_WS_ENDPOINT", os.environ)
        run_task_mock.assert_called_once()

    def test_run_dashboard_formats_stage_timing_as_compact_labels(self) -> None:
        project = storage.create_project("Timing UI Paper", "", "", data_root=self.data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        run_payload["status"] = "running"
        run_payload["current_stage"] = "outline"
        run_payload["stages"]["outline"]["status"] = "succeeded"
        run_payload["stages"]["outline"]["summary"] = "Outline generated."
        run_payload["stages"]["outline"]["attempt"] = 2
        run_payload["stages"]["outline"]["started_at"] = "2026-04-17T19:24:22+00:00"
        run_payload["stages"]["outline"]["finished_at"] = "2026-04-17T19:24:30+00:00"
        run_payload["stages"]["literature"]["status"] = "running"
        run_payload["stages"]["literature"]["summary"] = "Gathering literature."
        run_payload["stages"]["literature"]["attempt"] = 1
        run_payload["stages"]["literature"]["started_at"] = "2026-04-17T19:24:30+00:00"
        storage.save_run(run_payload, self.data_root)
        project["latest_run_id"] = run_payload["run_id"]
        storage.save_project(project, self.data_root)

        response = self.client.get(f"/projects/{project['project_id']}?step=run")

        self.assertEqual(response.status_code, 200)
        self.assertIn('meta-pill-label">Attempt</span>2', response.text)
        self.assertIn('meta-pill-label">Started</span>', response.text)
        self.assertIn('meta-pill-label">Finished</span>', response.text)
        self.assertIn('meta-pill-label">Duration</span>8s', response.text)
        self.assertIn('meta-pill-label">State</span>Running', response.text)
        self.assertNotIn("2026-04-17T19:24:22+00:00", response.text)

    def test_run_dashboard_renders_stage_timeline_with_parallel_branch_labels(self) -> None:
        project = storage.create_project("Timeline UI Paper", "", "", data_root=self.data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        run_payload["status"] = "running"
        run_payload["current_stage"] = "literature"
        run_payload["stages"]["ingest"]["status"] = "succeeded"
        run_payload["stages"]["ingest"]["started_at"] = "2026-04-17T19:24:10+00:00"
        run_payload["stages"]["ingest"]["finished_at"] = "2026-04-17T19:24:12+00:00"
        run_payload["stages"]["plotting"]["status"] = "running"
        run_payload["stages"]["plotting"]["started_at"] = "2026-04-17T19:24:30+00:00"
        run_payload["stages"]["literature"]["status"] = "running"
        run_payload["stages"]["literature"]["started_at"] = "2026-04-17T19:24:30+00:00"
        storage.save_run(run_payload, self.data_root)
        project["latest_run_id"] = run_payload["run_id"]
        storage.save_project(project, self.data_root)

        response = self.client.get(f"/projects/{project['project_id']}?step=run")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Stage timeline", response.text)
        self.assertIn("Pipeline order, current focus, and quick timing for each stage.", response.text)
        self.assertIn("Plotting and literature run in parallel", response.text)
        self.assertIn("timeline-step\">Step 1", response.text)
        self.assertIn("timeline-title\">Ingest", response.text)
        self.assertIn("timeline-title\">Plotting", response.text)
        self.assertIn("timeline-title\">Literature", response.text)
        self.assertGreaterEqual(response.text.count("timeline-note\">Parallel"), 2)
        self.assertIn('data-run-timeline-track="true"', response.text)
        self.assertIn('data-stage-name="literature"', response.text)
        self.assertIn('data-timeline-current="true"', response.text)
        self.assertIn('aria-current="step"', response.text)

    @mock.patch("gui_app.web.orchestrator.start_run")
    def test_start_run_route_uses_orchestrator(self, start_run: mock.Mock) -> None:
        project = storage.create_project("Start Paper", "", "", data_root=self.data_root)
        project["idea"]["raw_markdown"] = (
            "## Problem Statement\n\nProblem.\n\n## Core Hypothesis\n\nHypothesis.\n\n"
            "## Proposed Methodology (High-Level Technical Approach)\n\nMethod.\n\n"
            "## Expected Contribution\n\nContribution.\n"
        )
        project["experimental"]["log_text"] = (
            "# Experimental Log\n\n## 1. Experimental Setup\n\nSetup\n\n"
            "## 2. Raw Numeric Data\n\n| Method | Score |\n| --- | --- |\n| Ours | 1.0 |\n\n"
            "## 3. Qualitative Observations\n\n- Observation\n"
        )
        project["guidelines"]["guidelines_text"] = "Page limit: 9 pages.\nSubmission deadline: October 1, 2026.\n"
        project["template"]["text"] = "\\documentclass{article}\n\\begin{document}\n\\section{Introduction}\n\\end{document}\n"
        storage.save_project(project, self.data_root)
        start_run.return_value = "pipeline-123"

        response = self.client.post(
            f"/projects/{project['project_id']}/runs/start",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        start_run.assert_called_once_with(project["project_id"], self.data_root)

    @mock.patch("gui_app.web.orchestrator.retry_stage")
    def test_retry_stage_route_uses_orchestrator(self, retry_stage: mock.Mock) -> None:
        project = storage.create_project("Retry Route Paper", "", "", data_root=self.data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        retry_stage.return_value = run_payload["run_id"]

        response = self.client.post(
            f"/projects/{project['project_id']}/runs/{run_payload['run_id']}/retry/plotting",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        retry_stage.assert_called_once_with(project["project_id"], run_payload["run_id"], "plotting", self.data_root)

    def test_integrations_endpoint_reports_presence_without_echoing_secrets(self) -> None:
        from gui_app import config

        with mock.patch.object(config, "load_runtime_env", return_value={
            "SEMANTIC_SCHOLAR_API_KEY": "secret-value",
            "PAPERBANANA_PATH": "/tmp/paperbanana",
        }):
            response = self.client.get("/api/integrations")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["semantic_scholar"]["configured"])
        self.assertNotIn("secret-value", json.dumps(payload))

    def test_project_page_uses_live_state_integration_vocabulary(self) -> None:
        project = storage.create_project("Integration Vocabulary", "", "", data_root=self.data_root)
        mocked_integrations = {
            "codex": {"available": True},
            "chrome_for_testing": {"installed": False},
            "chrome_stable": {"installed": True},
            "atlas": {"available": False, "enabled": True, "path": "/Applications/ChatGPT Atlas.app"},
            "semantic_scholar": {"configured": True},
            "figure_backend": {"valid": False, "selected_backend": "", "selected_root": ""},
            "browser_adapter": {"attach_mode": "chrome_for_testing_first"},
            "paperbanana": {"configured": False},
            "papervizagent": {"configured": False},
            "chrome": {
                "global_registered": True,
                "wrapper_exists": True,
                "helper_exists": True,
                "local_build_exists": True,
                "wrapper_path": "/tmp/wrapper",
                "helper_path": "/tmp/helper",
                "config_path": "/tmp/config",
                "debug_browser_app_path": "/Applications/Google Chrome for Testing.app",
                "default_browser_url": "http://127.0.0.1:9333",
                "version": "147.0.0.0",
                "mcp_available": True,
                "compatible": True,
                "plausibly_attachable": True,
            },
        }

        with mock.patch("gui_app.web._integration_summary", return_value=mocked_integrations):
            response = self.client.get(f"/projects/{project['project_id']}?step=setup")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Codex</span>", response.text)
        self.assertIn(">Reachable</span>", response.text)
        self.assertIn("Chrome for Testing</span>", response.text)
        self.assertIn(">Inactive</span>", response.text)
        self.assertIn("Stable Chrome</span>", response.text)
        self.assertIn(">Active</span>", response.text)
        self.assertIn("Atlas</span>", response.text)
        self.assertIn(">Unreachable</span>", response.text)
        self.assertNotIn(">Available</span>", response.text)
        self.assertNotIn(">Configured</span>", response.text)


class OrchestratorReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tempdir.name) / "gui-data"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @mock.patch("gui_app.orchestrator._spawn_worker", return_value=42424)
    def test_start_run_rebuilds_running_state_from_events(self, spawn_worker: mock.Mock) -> None:
        project = storage.create_project("Replay Start", "", "", data_root=self.data_root)

        run_id = orchestrator.start_run(project["project_id"], self.data_root)
        storage.run_state_file(project["project_id"], run_id, self.data_root).unlink()
        rebuilt = storage.load_run(project["project_id"], run_id, self.data_root)

        self.assertIsNotNone(rebuilt)
        self.assertEqual(rebuilt["status"], "running")
        self.assertEqual(rebuilt["pid"], 42424)
        self.assertEqual(rebuilt["current_stage"], "starting")
        spawn_worker.assert_called_once()

    @mock.patch("gui_app.orchestrator._spawn_worker", return_value=51515)
    def test_cancel_run_rebuilds_cancelled_state_from_events(self, _spawn_worker: mock.Mock) -> None:
        project = storage.create_project("Replay Cancel", "", "", data_root=self.data_root)
        run_id = orchestrator.start_run(project["project_id"], self.data_root)

        with mock.patch("gui_app.storage.is_pid_running", return_value=False):
            orchestrator.cancel_run(project["project_id"], run_id, self.data_root)

        storage.run_state_file(project["project_id"], run_id, self.data_root).unlink()
        rebuilt = storage.load_run(project["project_id"], run_id, self.data_root)

        self.assertIsNotNone(rebuilt)
        self.assertEqual(rebuilt["status"], "cancelled")

    @mock.patch("gui_app.orchestrator._spawn_worker", return_value=62626)
    def test_retry_stage_rewinds_to_earliest_unsatisfied_dependency(self, spawn_worker: mock.Mock) -> None:
        project = storage.create_project("Replay Dependency", "", "", data_root=self.data_root)
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        for stage_name in ("ingest", "validate"):
            storage.update_stage_state(
                run_payload,
                stage_name,
                self.data_root,
                status="succeeded",
                summary=f"{stage_name} done",
            )
        storage.update_stage_state(
            run_payload,
            "outline",
            self.data_root,
            status="failed",
            summary="outline failed",
        )

        orchestrator.retry_stage(project["project_id"], run_payload["run_id"], "section_writing", self.data_root)
        updated = storage.load_run(project["project_id"], run_payload["run_id"], self.data_root)

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["current_stage"], "outline")
        self.assertEqual(updated["stages"]["outline"]["status"], "pending")
        spawn_worker.assert_called_once_with(project["project_id"], run_payload["run_id"], self.data_root, resume_from="outline")


class CliSmokeTests(unittest.TestCase):
    def test_s2_search_check_key_works_without_query(self) -> None:
        env = dict(os.environ)
        env["SEMANTIC_SCHOLAR_API_KEY"] = "dummy-key-value"
        completed = subprocess.run(
            [
                str(storage.repo_python_executable()),
                "skills/literature-review-agent/scripts/s2_search.py",
                "--check-key",
            ],
            cwd=str(storage.REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("SEMANTIC_SCHOLAR_API_KEY is set", completed.stdout)

    def test_launch_gui_help_exits_cleanly(self) -> None:
        completed = subprocess.run(
            [str(storage.repo_python_executable()), "scripts/launch_gui.py", "--help"],
            cwd=str(storage.REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("Launch the PaperOrchestra FastAPI control room", completed.stdout)

    def test_install_chrome_devtools_mcp_help_exits_cleanly(self) -> None:
        completed = subprocess.run(
            [str(storage.repo_python_executable()), "scripts/install_chrome_devtools_mcp.py", "--help"],
            cwd=str(storage.REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("Install or repair the global Chrome DevTools MCP setup for Codex", completed.stdout)


class DocumentationGuardTests(unittest.TestCase):
    def test_readme_marks_supported_and_legacy_ui_surfaces(self) -> None:
        readme = (storage.REPO_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("scripts/launch_gui.py", readme)
        self.assertIn("gui_app.web", readme)
        self.assertIn("gui_app.server", readme)
        self.assertIn("gui_app.handoff", readme)
        self.assertIn("legacy", readme.lower())
        self.assertIn("not the supported ui", readme.lower())

    def test_supported_launcher_source_targets_fastapi_web_module(self) -> None:
        launch_source = (storage.REPO_ROOT / "scripts" / "launch_gui.py").read_text(encoding="utf-8")

        self.assertIn('"-m", "gui_app.web"', launch_source)
