from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import tempfile
import urllib.request
import unittest
from pathlib import Path
from unittest import mock

from gui_app import job_runner
from gui_app import storage
from gui_app.server import parse_markdown_sections


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


class BackendIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tempdir.name) / "gui-data"
        self.examples_root = storage.REPO_ROOT / "examples" / "minimal" / "inputs"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _example_project(self) -> dict[str, object]:
        idea_text = (self.examples_root / "idea.md").read_text(encoding="utf-8")
        sections = parse_markdown_sections(idea_text)
        project = storage.create_project(
            "Minimal Example",
            "ToyConf",
            "Backend integration coverage",
            data_root=self.data_root,
        )
        project["idea"].update({
            "problem_statement": sections.get("problem statement", ""),
            "core_hypothesis": sections.get("core hypothesis", ""),
            "methodology": sections.get("proposed methodology (high-level technical approach)", ""),
            "expected_contribution": sections.get("expected contribution", ""),
            "notes": "",
        })
        project["experimental"]["log_text"] = (self.examples_root / "experimental_log.md").read_text(encoding="utf-8")
        project["guidelines"]["guidelines_text"] = (self.examples_root / "conference_guidelines.md").read_text(encoding="utf-8")
        project["uploads"]["template_tex"] = str(self.examples_root / "template.tex")
        return storage.sync_workspace(project, self.data_root)

    def _outline_fixture(self) -> dict[str, object]:
        payload = json.loads(
            (storage.REPO_ROOT / "skills" / "outline-agent" / "references" / "example-output.json").read_text(encoding="utf-8")
        )
        payload.pop("_comment", None)
        return payload

    def _png_bytes(self) -> bytes:
        return b"\x89PNG\r\n\x1a\n" + (b"0" * 2048)

    def _fake_writer_stage(self, *args, **kwargs) -> dict[str, object]:
        workspace = Path(kwargs["workspace"])
        transcript_path = Path(kwargs["transcript_path"])
        log_path = Path(kwargs["log_path"])
        stage_name = transcript_path.parent.parent.name

        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(f"$ mocked {stage_name}\n", encoding="utf-8")

        if stage_name == "outline":
            transcript_path.write_text(json.dumps(self._outline_fixture(), indent=2), encoding="utf-8")
        elif stage_name == "plotting":
            transcript_path.write_text(f"{stage_name} complete\n", encoding="utf-8")
            figures_root = workspace / "figures"
            figures_root.mkdir(parents=True, exist_ok=True)
            (figures_root / "atk_tradeoff.png").write_bytes(self._png_bytes())
            (figures_root / "captions.json").write_text(
                json.dumps({"figures": [{"figure_id": "fig_atk_tradeoff", "caption": "ATK quality-compute tradeoff."}]}, indent=2),
                encoding="utf-8",
            )
        elif stage_name == "literature":
            transcript_path.write_text(
                "\n".join([
                    "\\documentclass{article}",
                    "\\begin{document}",
                    "\\section{Introduction}",
                    "Adaptive sparse attention builds on Transformer attention but focuses on controllable sparsity.\\cite{vaswani2017}",
                    "\\section{Related Work}",
                    "Dense Transformer attention remains the baseline for long-context comparison.\\cite{vaswani2017}",
                    "\\end{document}",
                    "",
                ]),
                encoding="utf-8",
            )
            (workspace / "drafts").mkdir(parents=True, exist_ok=True)
            (workspace / "refs.bib").write_text(
                "\n".join([
                    "@inproceedings{vaswani2017,",
                    "  title={Attention Is All You Need},",
                    "  author={Vaswani, Ashish and others},",
                    "  booktitle={NeurIPS},",
                    "  year={2017}",
                    "}",
                    "",
                ]),
                encoding="utf-8",
            )
            (workspace / "drafts" / "intro_relwork.tex").write_text(
                "Adaptive sparse attention builds on Transformer attention but focuses on controllable sparsity.\\cite{vaswani2017}\n",
                encoding="utf-8",
            )
            (workspace / "citation_pool.json").write_text(
                json.dumps({"papers": [{"title": "Attention Is All You Need", "bibtex_key": "vaswani2017"}]}, indent=2),
                encoding="utf-8",
            )
        elif stage_name == "section_writing":
            transcript_path.write_text(f"{stage_name} complete\n", encoding="utf-8")
            (workspace / "drafts").mkdir(parents=True, exist_ok=True)
            figures_root = workspace / "figures"
            figure_files = sorted(path for path in figures_root.glob("*.png")) if figures_root.exists() else []
            figure_name = figure_files[0].name if figure_files else "atk_tradeoff.png"
            (workspace / "drafts" / "paper.tex").write_text(
                "\n".join([
                    "\\documentclass{article}",
                    "\\usepackage{booktabs}",
                    "\\usepackage{graphicx}",
                    "\\title{Adaptive Top-K Attention}",
                    "\\author{Anonymous Authors}",
                    "\\date{}",
                    "\\begin{document}",
                    "\\maketitle",
                    "\\begin{abstract}",
                    "Adaptive Top-K Attention preserves long-context quality while reducing compute.",
                    "\\end{abstract}",
                    "\\section{Introduction}",
                    "Adaptive sparse attention improves long-context modeling while remaining controllable. \\cite{vaswani2017}",
                    "\\section{Related Work}",
                    "Prior work established dense Transformer attention as the baseline. \\cite{vaswani2017}",
                    "\\section{Method}",
                    "We render the quality-compute tradeoff in Figure~\\ref{fig:atk_tradeoff}.",
                    "\\begin{figure}[t]",
                    "\\centering",
                    f"\\includegraphics[width=0.8\\linewidth]{{../figures/{figure_name}}}",
                    "\\caption{ATK tradeoff figure.}",
                    "\\label{fig:atk_tradeoff}",
                    "\\end{figure}",
                    "\\section{Experiments}",
                    "Table~\\ref{tab:nq} summarizes the main NaturalQuestions-Long result.",
                    "\\begin{table}[t]",
                    "\\centering",
                    "\\begin{tabular}{lr}",
                    "\\toprule",
                    "Method & F1 \\\\",
                    "\\midrule",
                    "ATK-Attention (K=64) & 57.9 \\\\",
                    "\\bottomrule",
                    "\\end{tabular}",
                    "\\caption{Main NQ-L result.}",
                    "\\label{tab:nq}",
                    "\\end{table}",
                    "\\section{Conclusion}",
                    "ATK-Attention provides a smooth quality-compute tradeoff.",
                    "\\bibliographystyle{plain}",
                    "\\bibliography{refs}",
                    "\\end{document}",
                    "",
                ]),
                encoding="utf-8",
            )
        elif stage_name == "refinement":
            transcript_path.write_text(f"{stage_name} complete\n", encoding="utf-8")
            (workspace / "final").mkdir(parents=True, exist_ok=True)
            (workspace / "refinement").mkdir(parents=True, exist_ok=True)
            (workspace / "final" / "paper.tex").write_text(
                (workspace / "drafts" / "paper.tex").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (workspace / "refinement" / "worklog.json").write_text(
                json.dumps({"iterations": [{"accepted": True, "reason": "mocked refinement"}]}, indent=2),
                encoding="utf-8",
            )
        else:
            transcript_path.write_text(f"{stage_name} complete\n", encoding="utf-8")

        return {
            "command": ["codex", "exec"],
            "transcript_path": str(transcript_path),
        }

    def _fake_research_task(self, *args, **kwargs) -> dict[str, object]:
        project_id = kwargs["project_id"]
        run_id = kwargs["run_id"]
        stage_name = kwargs["stage_name"]
        workspace = Path(kwargs["workspace"])
        atlas_root = storage.stage_dir(project_id, run_id, stage_name, self.data_root) / "atlas"
        storage.ensure_dir(atlas_root)
        storage.ensure_dir(workspace / "cache" / "atlas")

        screenshot_path = atlas_root / "atlas-shot.png"
        screenshot_path.write_bytes(self._png_bytes())
        response_path = workspace / "cache" / "atlas" / "literature_response.md"
        response_path.write_text("Atlas Deep Research summary.\n", encoding="utf-8")
        result_path = atlas_root / "atlas_result.json"
        storage.atomic_write_json(result_path, {
            "submitted": True,
            "mode_used": "deep_research",
            "deep_research_enabled": True,
            "verification_method": "accessibility",
            "response_text": "Atlas Deep Research summary.",
        })
        return {
            "status": "succeeded",
            "mode_used": "deep_research",
            "deep_research_enabled": True,
            "verification_method": "accessibility",
            "fallback_reason": "",
            "result_path": str(result_path),
            "response_path": str(response_path),
            "screenshot_paths": [str(screenshot_path)],
            "transcript_path": str(response_path),
            "summary": "Atlas Deep Research task completed.",
            "artifacts": [str(result_path), str(response_path), str(screenshot_path)],
        }

    def _fake_failed_research_task(self, *args, **kwargs) -> dict[str, object]:
        project_id = kwargs["project_id"]
        run_id = kwargs["run_id"]
        stage_name = kwargs["stage_name"]
        workspace = Path(kwargs["workspace"])
        atlas_root = storage.stage_dir(project_id, run_id, stage_name, self.data_root) / "atlas"
        storage.ensure_dir(atlas_root)
        storage.ensure_dir(workspace / "cache" / "atlas")

        screenshot_path = atlas_root / "atlas-shot.png"
        screenshot_path.write_bytes(self._png_bytes())
        response_path = workspace / "cache" / "atlas" / "literature_response.md"
        response_path.write_text("", encoding="utf-8")
        result_path = atlas_root / "atlas_result.json"
        storage.atomic_write_json(result_path, {
            "submitted": False,
            "mode_used": "deep_research",
            "deep_research_enabled": False,
            "verification_method": "unverified",
            "response_text": "",
            "completion_state": "failed",
            "fallback_reason": "Atlas automation was unavailable; falling back to local literature discovery.",
        })
        return {
            "status": "failed",
            "mode_used": "deep_research",
            "deep_research_enabled": False,
            "verification_method": "unverified",
            "fallback_reason": "Atlas automation was unavailable; falling back to local literature discovery.",
            "completion_state": "failed",
            "result_path": str(result_path),
            "response_path": str(response_path),
            "screenshot_paths": [str(screenshot_path)],
            "transcript_path": str(response_path),
            "summary": "Atlas automation was unavailable; falling back to local literature discovery.",
            "artifacts": [str(result_path), str(response_path), str(screenshot_path)],
        }

    def _fake_research_task_with_structured_output(self, *args, **kwargs) -> dict[str, object]:
        payload = self._fake_research_task(*args, **kwargs)
        workspace = Path(kwargs["workspace"])
        structured_path = workspace / "cache" / "atlas" / "literature_structured.json"
        structured_path.parent.mkdir(parents=True, exist_ok=True)
        structured_path.write_text(
            json.dumps({
                "task_type": "literature",
                "query_hints": [
                    "Attention Is All You Need",
                    "Longformer: The Long-Document Transformer",
                ],
                "candidates": [
                    {
                        "title": "Attention Is All You Need",
                        "url": "https://arxiv.org/abs/1706.03762",
                        "notes": "Transformer baseline.",
                    },
                    {
                        "title": "Longformer: The Long-Document Transformer",
                        "url": "https://arxiv.org/abs/2004.05150",
                        "notes": "Sparse long-context attention.",
                    },
                ],
                "response_path": payload["response_path"],
                "result_path": payload["result_path"],
            }, indent=2),
            encoding="utf-8",
        )
        payload["structured_output_path"] = str(structured_path)
        payload["artifacts"] = [*payload["artifacts"], str(structured_path)]
        return payload

    def _sample_semantic_scholar_hits(self) -> list[dict[str, object]]:
        return [
            {
                "paperId": "vaswani2017",
                "title": "Attention Is All You Need",
                "abstract": "The Transformer replaces recurrence with self-attention for sequence modeling.",
                "year": 2017,
                "publicationDate": "2017-06-12",
                "authors": [{"name": "Ashish Vaswani"}],
                "venue": "NeurIPS",
                "externalIds": {"DOI": "10.5555/3295222.3295349"},
            },
            {
                "paperId": "beltagy2020",
                "title": "Longformer: The Long-Document Transformer",
                "abstract": "Longformer combines windowed attention with task-motivated global attention.",
                "year": 2020,
                "publicationDate": "2020-04-10",
                "authors": [{"name": "Iz Beltagy"}],
                "venue": "arXiv",
                "externalIds": {"ArXiv": "2004.05150"},
            },
        ]

    def _wrapped_run_command(self, original, command, cwd, log_path, env) -> None:
        if len(command) >= 2 and Path(command[1]).name == "check_tex_packages.py":
            out_path = Path(command[command.index("--out") + 1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps({
                    "available": ["booktabs", "graphicx"],
                    "missing": [],
                    "use_cleveref": False,
                    "use_nicefrac": False,
                    "use_microtype": False,
                    "use_t1_fontenc": True,
                    "tex_binary": "/usr/bin/pdflatex",
                }, indent=2),
                encoding="utf-8",
            )
            job_runner.append_log(log_path, "$ " + " ".join(command))
            return
        if command and command[0] == "latexmk":
            Path(cwd).mkdir(parents=True, exist_ok=True)
            (Path(cwd) / "paper.pdf").write_bytes(b"%PDF-1.4\n% mocked pdf\n")
            job_runner.append_log(log_path, "$ " + " ".join(command))
            return
        return original(command, cwd, log_path, env)

    def test_execute_orchestrated_minimal_run_succeeds(self) -> None:
        project = self._example_project()
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        original_run_command = job_runner.run_command

        with mock.patch("gui_app.job_runner.research_adapter.ResearchAdapter.run_task", side_effect=self._fake_research_task):
            with mock.patch("gui_app.job_runner.writer_executor.WriterExecutor.run_stage", side_effect=self._fake_writer_stage):
                with mock.patch("gui_app.job_runner.run_semantic_scholar_query", return_value=self._sample_semantic_scholar_hits()):
                    with mock.patch(
                        "gui_app.job_runner.run_command",
                        side_effect=lambda command, cwd, log_path, env: self._wrapped_run_command(
                            original_run_command, command, cwd, log_path, env
                        ),
                    ):
                        result = job_runner.execute_orchestrated(project["project_id"], run_payload["run_id"], self.data_root)

        self.assertEqual(result["status"], "succeeded")
        updated = storage.load_run(project["project_id"], run_payload["run_id"], self.data_root)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["status"], "succeeded")
        self.assertTrue((Path(project["workspace_path"]) / "final" / "paper.pdf").exists())
        self.assertEqual(updated["stages"]["plotting"]["status"], "succeeded")
        self.assertEqual(updated["stages"]["literature"]["status"], "succeeded")
        self.assertEqual(updated["stages"]["section_writing"]["status"], "succeeded")
        self.assertEqual(updated["stages"]["compile"]["status"], "succeeded")
        outline_performance = updated["stages"]["outline"]["performance"]
        self.assertEqual(outline_performance["measurement_scope"], "process_delta")
        self.assertGreaterEqual(outline_performance["wall_seconds"], 0)
        self.assertIn("total_cpu_seconds", outline_performance)
        outline_substeps = updated["stages"]["outline"]["substeps"]
        self.assertTrue(any(isinstance(item.get("performance"), dict) for item in outline_substeps))

        performance_path = storage.run_dir(project["project_id"], run_payload["run_id"], self.data_root) / "performance.json"
        self.assertTrue(performance_path.exists())
        performance_payload = json.loads(performance_path.read_text(encoding="utf-8"))
        self.assertIn("outline", performance_payload["stages"])
        self.assertIn("performance", performance_payload["stages"]["outline"])

        events = storage.load_jsonl(storage.run_events_file(project["project_id"], run_payload["run_id"], self.data_root))
        section_running_index = next(
            index for index, item in enumerate(events)
            if item.get("type") == "stage_updated"
            and item.get("details", {}).get("stage") == "section_writing"
            and item.get("details", {}).get("fields", {}).get("status") == "running"
        )
        plotting_done_index = next(
            index for index, item in enumerate(events)
            if item.get("type") == "stage_updated"
            and item.get("details", {}).get("stage") == "plotting"
            and item.get("details", {}).get("fields", {}).get("status") == "succeeded"
        )
        literature_done_index = next(
            index for index, item in enumerate(events)
            if item.get("type") == "stage_updated"
            and item.get("details", {}).get("stage") == "literature"
            and item.get("details", {}).get("fields", {}).get("status") == "succeeded"
        )
        self.assertLess(plotting_done_index, section_running_index)
        self.assertLess(literature_done_index, section_running_index)

    def test_compile_failure_surfaces_as_paused_run(self) -> None:
        project = self._example_project()
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        original_run_command = job_runner.run_command

        def failing_run_command(command, cwd, log_path, env):
            if command and command[0] == "latexmk" and Path(cwd).name == "final":
                raise RuntimeError("latexmk failed")
            return self._wrapped_run_command(original_run_command, command, cwd, log_path, env)

        with mock.patch("gui_app.job_runner.research_adapter.ResearchAdapter.run_task", side_effect=self._fake_research_task):
            with mock.patch("gui_app.job_runner.writer_executor.WriterExecutor.run_stage", side_effect=self._fake_writer_stage):
                with mock.patch("gui_app.job_runner.run_semantic_scholar_query", return_value=self._sample_semantic_scholar_hits()):
                    with mock.patch("gui_app.job_runner.run_command", side_effect=failing_run_command):
                        with self.assertRaises(job_runner.RunNeedsInput):
                            job_runner.execute_orchestrated(project["project_id"], run_payload["run_id"], self.data_root)

        updated = storage.load_run(project["project_id"], run_payload["run_id"], self.data_root)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["status"], "paused")
        self.assertEqual(updated["stages"]["compile"]["status"], "paused")
        self.assertEqual(updated["stages"]["compile"]["attention_required"]["reason"], "compile_error")

    def test_execute_literature_falls_back_when_atlas_result_is_unusable(self) -> None:
        project = self._example_project()
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        workspace = Path(str(project["workspace_path"]))
        (workspace / "outline.json").write_text(json.dumps(self._outline_fixture(), indent=2), encoding="utf-8")

        with mock.patch("gui_app.job_runner.research_adapter.ResearchAdapter.run_task", side_effect=self._fake_failed_research_task):
            with mock.patch("gui_app.job_runner.writer_executor.WriterExecutor.run_stage", side_effect=self._fake_writer_stage):
                with mock.patch("gui_app.job_runner.run_semantic_scholar_query", return_value=self._sample_semantic_scholar_hits()):
                    artifacts = job_runner.execute_literature(project, run_payload["run_id"], self.data_root, dict(os.environ))

        self.assertIn(str(workspace / "refs.bib"), artifacts)
        self.assertIn(str(workspace / "citation_pool.json"), artifacts)
        self.assertIn(str(workspace / "drafts" / "intro_relwork.tex"), artifacts)
        self.assertTrue((workspace / "refs.bib").exists())
        self.assertTrue((workspace / "citation_pool.json").exists())
        self.assertIn("Adaptive sparse attention", (workspace / "drafts" / "intro_relwork.tex").read_text(encoding="utf-8"))

        updated = storage.load_run(project["project_id"], run_payload["run_id"], self.data_root)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["stages"]["literature"]["status"], "succeeded")
        atlas_result_path = storage.stage_dir(project["project_id"], run_payload["run_id"], "literature", self.data_root) / "atlas" / "atlas_result.json"
        self.assertTrue(atlas_result_path.exists())

    def test_execute_literature_writes_citation_map_and_substeps(self) -> None:
        project = self._example_project()
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        workspace = Path(str(project["workspace_path"]))
        (workspace / "outline.json").write_text(json.dumps(self._outline_fixture(), indent=2), encoding="utf-8")

        with mock.patch("gui_app.job_runner.research_adapter.ResearchAdapter.run_task", side_effect=self._fake_failed_research_task):
            with mock.patch("gui_app.job_runner.writer_executor.WriterExecutor.run_stage", side_effect=self._fake_writer_stage):
                with mock.patch("gui_app.job_runner.run_semantic_scholar_query", return_value=self._sample_semantic_scholar_hits()):
                    artifacts = job_runner.execute_literature(project, run_payload["run_id"], self.data_root, dict(os.environ))

        citation_map_path = workspace / "citation_map.json"
        self.assertTrue(citation_map_path.exists())
        self.assertIn(str(citation_map_path), artifacts)
        payload = json.loads(citation_map_path.read_text(encoding="utf-8"))
        self.assertIn("by_key", payload)
        updated = storage.load_run(project["project_id"], run_payload["run_id"], self.data_root)
        self.assertIsNotNone(updated)
        assert updated is not None
        substep_names = [item["name"] for item in updated["stages"]["literature"]["substeps"]]
        self.assertIn("citation_pool_build", substep_names)
        self.assertIn("citation_coverage_repair", substep_names)

    def test_execute_literature_pauses_when_browser_approval_is_required(self) -> None:
        project = self._example_project()
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        workspace = Path(str(project["workspace_path"]))
        (workspace / "outline.json").write_text(json.dumps(self._outline_fixture(), indent=2), encoding="utf-8")

        with mock.patch(
            "gui_app.job_runner.research_adapter.ResearchAdapter.run_task",
            return_value={
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
            },
        ):
            with self.assertRaises(job_runner.RunNeedsInput):
                job_runner.execute_literature(project, run_payload["run_id"], self.data_root, dict(os.environ))

        updated = storage.load_run(project["project_id"], run_payload["run_id"], self.data_root)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["status"], "paused")
        self.assertEqual(updated["stages"]["literature"]["status"], "paused")
        self.assertEqual(updated["stages"]["literature"]["attention_required"]["reason"], "browser_approval_required")

    def test_execute_literature_atlas_success_still_builds_verified_pool_from_structured_artifact(self) -> None:
        project = self._example_project()
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        workspace = Path(str(project["workspace_path"]))
        (workspace / "outline.json").write_text(json.dumps(self._outline_fixture(), indent=2), encoding="utf-8")

        def citation_keys_from_prompt(prompt: str) -> list[str]:
            match = re.search(r"<citation_checklist>\s*(.*?)\s*</citation_checklist>", prompt, flags=re.DOTALL)
            self.assertIsNotNone(match)
            return json.loads(match.group(1)) if match else []

        def fake_run_codex_stage(project_id, run_id, data_root, stage_name, prompt, workspace, env, output_schema_path=None, sandbox_mode="workspace-write"):
            citation_keys = citation_keys_from_prompt(prompt)
            transcript_path = Path(
                storage.load_run(project_id, run_id, data_root)["stages"][stage_name]["transcript_path"]
            )
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            transcript_path.write_text(
                "\n".join([
                    "\\documentclass{article}",
                    "\\begin{document}",
                    "\\section{Introduction}",
                    f"Sparse attention papers motivate efficient long-context modeling. \\cite{{{','.join(citation_keys)}}}",
                    "\\section{Related Work}",
                    f"Transformer baselines and long-document sparse attention remain core reference points. \\cite{{{','.join(citation_keys)}}}",
                    "\\end{document}",
                    "",
                ]),
                encoding="utf-8",
            )
            return transcript_path

        with mock.patch("gui_app.job_runner.research_adapter.ResearchAdapter.run_task", side_effect=self._fake_research_task_with_structured_output):
            with mock.patch("gui_app.job_runner.run_semantic_scholar_query", return_value=self._sample_semantic_scholar_hits()):
                with mock.patch("gui_app.job_runner.run_codex_stage", side_effect=fake_run_codex_stage):
                    artifacts = job_runner.execute_literature(project, run_payload["run_id"], self.data_root, dict(os.environ))

        self.assertIn(str(workspace / "refs.bib"), artifacts)
        self.assertIn(str(workspace / "citation_pool.json"), artifacts)
        self.assertIn(str(workspace / "drafts" / "intro_relwork.tex"), artifacts)
        structured_output_path = workspace / "cache" / "atlas" / "literature_structured.json"
        self.assertIn(str(structured_output_path), artifacts)
        self.assertTrue(structured_output_path.exists())
        citation_pool = json.loads((workspace / "citation_pool.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(citation_pool["papers"]), 2)
        pool_titles = {paper["title"] for paper in citation_pool["papers"]}
        self.assertIn("Attention Is All You Need", pool_titles)
        self.assertIn("Longformer: The Long-Document Transformer", pool_titles)

    def test_execute_literature_falls_back_to_local_synthesis_after_codex_timeout(self) -> None:
        project = self._example_project()
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        workspace = Path(str(project["workspace_path"]))
        (workspace / "outline.json").write_text(json.dumps(self._outline_fixture(), indent=2), encoding="utf-8")

        calls: list[str] = []

        def citation_keys_from_prompt(prompt: str) -> list[str]:
            checklist_match = re.search(r"<citation_checklist>\s*(.*?)\s*</citation_checklist>", prompt, flags=re.DOTALL)
            if checklist_match:
                return json.loads(checklist_match.group(1))
            pool_match = re.search(r"<citation_pool_json>\s*(.*?)\s*</citation_pool_json>", prompt, flags=re.DOTALL)
            if not pool_match:
                return []
            pool_payload = json.loads(pool_match.group(1))
            return [paper["bibtex_key"] for paper in pool_payload.get("papers", []) if paper.get("bibtex_key")]

        def fake_run_codex_stage(project_id, run_id, data_root, stage_name, prompt, workspace, env, output_schema_path=None, sandbox_mode="workspace-write"):
            calls.append(prompt)
            transcript_path = Path(
                storage.load_run(project_id, run_id, data_root)["stages"][stage_name]["transcript_path"]
            )
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            if len(calls) == 1:
                raise RuntimeError("Command timed out after 8 seconds: codex exec ...")
            citation_keys = citation_keys_from_prompt(prompt)
            transcript_path.write_text(
                "\n".join([
                    "\\documentclass{article}",
                    "\\begin{document}",
                    "\\section{Introduction}",
                    f"Recovered introduction with full citation coverage. \\cite{{{','.join(citation_keys)}}}",
                    "\\section{Related Work}",
                    f"Recovered related work covers both papers. \\cite{{{','.join(citation_keys)}}}",
                    "\\end{document}",
                    "",
                ]),
                encoding="utf-8",
            )
            return transcript_path

        with mock.patch("gui_app.job_runner.research_adapter.ResearchAdapter.run_task", side_effect=self._fake_failed_research_task):
            with mock.patch("gui_app.job_runner.run_semantic_scholar_query", return_value=self._sample_semantic_scholar_hits()):
                with mock.patch("gui_app.job_runner.run_codex_stage", side_effect=fake_run_codex_stage):
                    artifacts = job_runner.execute_literature(project, run_payload["run_id"], self.data_root, dict(os.environ))

        self.assertTrue((workspace / "refs.bib").exists())
        self.assertTrue((workspace / "citation_pool.json").exists())
        repaired_path = workspace / "drafts" / "intro_relwork.tex"
        self.assertTrue(repaired_path.exists())
        repaired_tex = repaired_path.read_text(encoding="utf-8")
        self.assertRegex(repaired_tex, r"\\cite\{[^}]+\}")
        self.assertIn(str(repaired_path), artifacts)
        self.assertTrue(any("local-fallback" in Path(path).name for path in artifacts))
        updated = storage.load_run(project["project_id"], run_payload["run_id"], self.data_root)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["stages"]["literature"]["status"], "succeeded")

    def test_execute_literature_records_repair_transcript_when_coverage_needs_fixing(self) -> None:
        project = self._example_project()
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        workspace = Path(str(project["workspace_path"]))
        (workspace / "outline.json").write_text(json.dumps(self._outline_fixture(), indent=2), encoding="utf-8")
        semantic_hits = self._sample_semantic_scholar_hits() + [
            {
                "paperId": "zaheer2020",
                "title": "Big Bird: Transformers for Longer Sequences",
                "abstract": "BigBird extends Transformer context using sparse global and random attention.",
                "year": 2020,
                "publicationDate": "2020-12-01",
                "authors": [{"name": "Manzil Zaheer"}],
                "venue": "NeurIPS",
                "externalIds": {"ArXiv": "2007.14062"},
            },
        ]

        calls: list[str] = []

        def citation_keys_from_prompt(prompt: str) -> list[str]:
            checklist_match = re.search(r"<citation_checklist>\s*(.*?)\s*</citation_checklist>", prompt, flags=re.DOTALL)
            if checklist_match:
                return json.loads(checklist_match.group(1))
            pool_match = re.search(r"<citation_pool_json>\s*(.*?)\s*</citation_pool_json>", prompt, flags=re.DOTALL)
            if not pool_match:
                return []
            pool_payload = json.loads(pool_match.group(1))
            return [paper["bibtex_key"] for paper in pool_payload.get("papers", []) if paper.get("bibtex_key")]

        def fake_run_codex_stage(project_id, run_id, data_root, stage_name, prompt, workspace, env, output_schema_path=None, sandbox_mode="workspace-write"):
            calls.append(prompt)
            transcript_path = Path(
                storage.load_run(project_id, run_id, data_root)["stages"][stage_name]["transcript_path"]
            )
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            citation_keys = citation_keys_from_prompt(prompt)
            if len(calls) == 1:
                cited_keys = citation_keys[:1]
                transcript_path.write_text(
                    "\n".join([
                        "\\documentclass{article}",
                        "\\begin{document}",
                        "\\section{Introduction}",
                        f"Under-cited introduction draft. \\cite{{{','.join(cited_keys)}}}",
                        "\\section{Related Work}",
                        f"Under-cited related work draft. \\cite{{{','.join(cited_keys)}}}",
                        "\\end{document}",
                        "",
                    ]),
                    encoding="utf-8",
                )
                return transcript_path
            transcript_path.write_text(
                "\n".join([
                    "\\documentclass{article}",
                    "\\begin{document}",
                    "\\section{Introduction}",
                    f"Repaired introduction draft. \\cite{{{','.join(citation_keys)}}}",
                    "\\section{Related Work}",
                    f"Repaired related work draft. \\cite{{{','.join(citation_keys)}}}",
                    "\\end{document}",
                    "",
                ]),
                encoding="utf-8",
            )
            return transcript_path

        with mock.patch("gui_app.job_runner.research_adapter.ResearchAdapter.run_task", side_effect=self._fake_failed_research_task):
            with mock.patch("gui_app.job_runner.run_semantic_scholar_query", return_value=semantic_hits):
                with mock.patch("gui_app.job_runner.run_codex_stage", side_effect=fake_run_codex_stage):
                    artifacts = job_runner.execute_literature(project, run_payload["run_id"], self.data_root, dict(os.environ))

        self.assertTrue(any("repair" in Path(path).name for path in artifacts))
        self.assertEqual(len(calls), 2)

    def test_acceptance_failpoint_triggers_once_and_targeted_retry_preserves_completed_siblings(self) -> None:
        project = self._example_project()
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        original_run_command = job_runner.run_command

        with mock.patch.dict(os.environ, {
            "PAPERORCHESTRA_ACCEPTANCE_MODE": "1",
            "PAPERORCHESTRA_ACCEPTANCE_FAIL_STAGE": "compile",
        }, clear=False):
            with mock.patch("gui_app.job_runner.research_adapter.ResearchAdapter.run_task", side_effect=self._fake_research_task):
                with mock.patch("gui_app.job_runner.writer_executor.WriterExecutor.run_stage", side_effect=self._fake_writer_stage):
                    with mock.patch("gui_app.job_runner.run_semantic_scholar_query", return_value=self._sample_semantic_scholar_hits()):
                        with mock.patch(
                            "gui_app.job_runner.run_command",
                            side_effect=lambda command, cwd, log_path, env: self._wrapped_run_command(
                                original_run_command, command, cwd, log_path, env
                            ),
                        ):
                            with self.assertRaises(RuntimeError):
                                job_runner.execute_orchestrated(project["project_id"], run_payload["run_id"], self.data_root)

        failed = storage.load_run(project["project_id"], run_payload["run_id"], self.data_root)
        self.assertIsNotNone(failed)
        assert failed is not None
        self.assertEqual(failed["stages"]["compile"]["status"], "failed")
        self.assertEqual(failed["stages"]["plotting"]["attempt"], 1)
        self.assertEqual(failed["stages"]["literature"]["attempt"], 1)
        self.assertEqual(failed["stages"]["compile"]["attempt"], 1)

        reset = storage.reset_pipeline_run_from_stage(failed, "compile", self.data_root)
        with mock.patch.dict(os.environ, {
            "PAPERORCHESTRA_ACCEPTANCE_MODE": "1",
            "PAPERORCHESTRA_ACCEPTANCE_FAIL_STAGE": "compile",
        }, clear=False):
            with mock.patch("gui_app.job_runner.research_adapter.ResearchAdapter.run_task", side_effect=self._fake_research_task):
                with mock.patch("gui_app.job_runner.writer_executor.WriterExecutor.run_stage", side_effect=self._fake_writer_stage):
                    with mock.patch("gui_app.job_runner.run_semantic_scholar_query", return_value=self._sample_semantic_scholar_hits()):
                        with mock.patch(
                            "gui_app.job_runner.run_command",
                            side_effect=lambda command, cwd, log_path, env: self._wrapped_run_command(
                                original_run_command, command, cwd, log_path, env
                            ),
                        ):
                            result = job_runner.execute_orchestrated(
                                project["project_id"],
                                reset["run_id"],
                                self.data_root,
                                resume_from="compile",
                            )

        self.assertEqual(result["status"], "succeeded")
        retried = storage.load_run(project["project_id"], run_payload["run_id"], self.data_root)
        self.assertIsNotNone(retried)
        assert retried is not None
        self.assertEqual(retried["stages"]["plotting"]["attempt"], 1)
        self.assertEqual(retried["stages"]["literature"]["attempt"], 1)
        self.assertEqual(retried["stages"]["compile"]["attempt"], 2)
        self.assertEqual(retried["stages"]["finalize"]["attempt"], 1)

    def test_acceptance_failpoint_is_ignored_when_acceptance_mode_is_disabled(self) -> None:
        project = self._example_project()
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        original_run_command = job_runner.run_command

        with mock.patch.dict(os.environ, {
            "PAPERORCHESTRA_ACCEPTANCE_FAIL_STAGE": "compile",
        }, clear=False):
            with mock.patch("gui_app.job_runner.research_adapter.ResearchAdapter.run_task", side_effect=self._fake_research_task):
                with mock.patch("gui_app.job_runner.writer_executor.WriterExecutor.run_stage", side_effect=self._fake_writer_stage):
                    with mock.patch("gui_app.job_runner.run_semantic_scholar_query", return_value=self._sample_semantic_scholar_hits()):
                        with mock.patch(
                            "gui_app.job_runner.run_command",
                            side_effect=lambda command, cwd, log_path, env: self._wrapped_run_command(
                                original_run_command, command, cwd, log_path, env
                            ),
                        ):
                            result = job_runner.execute_orchestrated(project["project_id"], run_payload["run_id"], self.data_root)

        self.assertEqual(result["status"], "succeeded")

    def test_execute_outline_falls_back_to_local_synthesis_after_timeout(self) -> None:
        project = self._example_project()
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        workspace = Path(str(project["workspace_path"]))

        with mock.patch("gui_app.job_runner.run_codex_stage", side_effect=RuntimeError("Command timed out after 90.0 seconds: codex exec ...")):
            artifacts = job_runner.execute_outline(project, run_payload["run_id"], self.data_root, dict(os.environ))

        outline_path = workspace / "outline.json"
        self.assertIn(str(outline_path), artifacts)
        self.assertTrue(outline_path.exists())
        payload = json.loads(outline_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(payload["plotting_plan"]), 3)
        self.assertEqual(payload["intro_related_work_plan"]["introduction_strategy"]["search_directions"][0], "Transformer quadratic attention scaling in long-context tasks")
        self.assertEqual(payload["section_plan"][0]["section_title"], "Abstract")
        updated = storage.load_run(project["project_id"], run_payload["run_id"], self.data_root)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["stages"]["outline"]["status"], "succeeded")

    def test_execute_outline_materializes_planning_handoffs(self) -> None:
        project = self._example_project()
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        workspace = Path(str(project["workspace_path"]))

        with mock.patch("gui_app.job_runner.run_codex_stage", side_effect=RuntimeError("Command timed out after 90.0 seconds: codex exec ...")):
            artifacts = job_runner.execute_outline(project, run_payload["run_id"], self.data_root, dict(os.environ))

        self.assertIn(str(workspace / "planning" / "plotting_plan.json"), artifacts)
        self.assertIn(str(workspace / "planning" / "intro_related_work_plan.json"), artifacts)
        self.assertIn(str(workspace / "planning" / "section_plan.json"), artifacts)
        updated = storage.load_run(project["project_id"], run_payload["run_id"], self.data_root)
        self.assertIsNotNone(updated)
        assert updated is not None
        substep_names = [item["name"] for item in updated["stages"]["outline"]["substeps"]]
        self.assertIn("outline_materialize", substep_names)

    def test_section_writing_recovers_latex_from_timeout_log(self) -> None:
        project = self._example_project()
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        workspace = Path(str(project["workspace_path"]))
        (workspace / "drafts").mkdir(parents=True, exist_ok=True)
        (workspace / "drafts" / "intro_relwork.tex").write_text(
            "\\section{Introduction}\nIntro text.\\cite{vaswani2017}\n",
            encoding="utf-8",
        )
        (workspace / "citation_pool.json").write_text(
            json.dumps({"papers": [{"title": "Attention Is All You Need", "bibtex_key": "vaswani2017"}]}, indent=2),
            encoding="utf-8",
        )
        (workspace / "citation_map.json").write_text(
            json.dumps({"by_key": {"vaswani2017": {"title": "Attention Is All You Need"}}}, indent=2),
            encoding="utf-8",
        )
        (workspace / "refs.bib").write_text(
            "@article{vaswani2017, title={Attention Is All You Need}, year={2017}}\n",
            encoding="utf-8",
        )
        stage_log = Path(run_payload["stages"]["section_writing"]["log_path"])
        transcript_path = Path(run_payload["stages"]["section_writing"]["transcript_path"])

        def fake_run_codex_stage(*args, **kwargs):
            stage_log.parent.mkdir(parents=True, exist_ok=True)
            stage_log.write_text(
                "\n".join([
                    "$ codex exec ...",
                    "\\documentclass{article}",
                    "\\begin{document}",
                    "\\section{Method}",
                    "Recovered draft text. \\cite{vaswani2017}",
                    "\\end{document}",
                ]),
                encoding="utf-8",
            )
            raise RuntimeError("Command timed out after 180.0 seconds: codex exec ...")

        with mock.patch("gui_app.job_runner.run_codex_stage", side_effect=fake_run_codex_stage):
            with mock.patch("gui_app.job_runner.run_command", return_value=None):
                artifacts = job_runner.execute_section_writing(project, run_payload["run_id"], self.data_root, dict(os.environ))

        self.assertIn(str(transcript_path), artifacts)
        draft_path = workspace / "drafts" / "paper.tex"
        self.assertTrue(draft_path.exists())
        self.assertIn("Recovered draft text.", draft_path.read_text(encoding="utf-8"))

    def test_refinement_falls_back_to_draft_after_timeout(self) -> None:
        project = self._example_project()
        run_payload = storage.create_pipeline_run(project["project_id"], self.data_root)
        workspace = Path(str(project["workspace_path"]))
        draft_path = workspace / "drafts" / "paper.tex"
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(
            "\n".join([
                "\\documentclass{article}",
                "\\begin{document}",
                "Draft content.",
                "\\end{document}",
            ]),
            encoding="utf-8",
        )

        with mock.patch("gui_app.job_runner.run_codex_stage", side_effect=RuntimeError("Command timed out after 180.0 seconds: codex exec ...")):
            artifacts = job_runner.execute_refinement(project, run_payload["run_id"], self.data_root, dict(os.environ))

        final_path = workspace / "final" / "paper.tex"
        self.assertIn(str(final_path), artifacts)
        self.assertTrue(final_path.exists())
        self.assertIn("Draft content.", final_path.read_text(encoding="utf-8"))
        worklog_path = workspace / "refinement" / "worklog.json"
        self.assertTrue(worklog_path.exists())


class JobRunnerHelperTests(unittest.TestCase):
    def test_codex_outline_output_schema_is_strict_and_concrete(self) -> None:
        strict = job_runner.codex_outline_output_schema()

        self.assertFalse(strict["additionalProperties"])
        self.assertEqual(strict["required"], ["plotting_plan", "intro_related_work_plan", "section_plan"])
        figure_spec = strict["properties"]["plotting_plan"]["items"]
        self.assertFalse(figure_spec["additionalProperties"])
        self.assertEqual(
            figure_spec["required"],
            ["figure_id", "title", "plot_type", "data_source", "objective", "aspect_ratio"],
        )
        self.assertEqual(figure_spec["properties"]["plot_type"]["enum"], ["plot", "diagram"])

    def test_normalize_outline_payload_repairs_figure_ids_and_plot_objectives(self) -> None:
        normalized = job_runner.normalize_outline_payload({
            "plotting_plan": [
                {
                    "figure_id": "fig:tradeoff",
                    "title": "Tradeoff Frontier",
                    "plot_type": "plot",
                    "data_source": "experimental_log.md",
                    "objective": "Show the main tradeoff",
                    "aspect_ratio": "16:9",
                },
            ],
            "intro_related_work_plan": {"introduction_strategy": {}, "related_work_strategy": {}},
            "section_plan": [],
        })

        figure = normalized["plotting_plan"][0]
        self.assertEqual(figure["figure_id"], "fig_tradeoff")
        self.assertIn("Line Chart", figure["objective"])

    def test_recover_latex_transcript_from_log_extracts_document(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            log_path = Path(tempdir) / "stage.log"
            transcript_path = Path(tempdir) / "codex-last-message.txt"
            log_path.write_text(
                "\n".join([
                    "prefix",
                    "\\documentclass{article}",
                    "\\begin{document}",
                    "Recovered body.",
                    "\\end{document}",
                ]),
                encoding="utf-8",
            )

            recovered = job_runner.recover_latex_transcript_from_log(log_path, transcript_path)

            self.assertTrue(recovered)
            self.assertTrue(transcript_path.exists())
            self.assertIn("Recovered body.", transcript_path.read_text(encoding="utf-8"))

    def test_prepare_compile_workspace_mirrors_refs_and_figures(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir) / "workspace"
            figures_dir = workspace / "figures"
            figures_dir.mkdir(parents=True, exist_ok=True)
            (workspace / "refs.bib").write_text("@article{key, title={Title}, year={2024}}\n", encoding="utf-8")
            (figures_dir / "figure.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

            prepared = job_runner.prepare_compile_workspace(workspace)

            self.assertIn(workspace / "final" / "refs.bib", prepared)
            self.assertTrue((workspace / "final" / "refs.bib").exists())
            self.assertTrue((workspace / "final" / "figures").exists())

    def test_literature_queries_prioritize_specific_queries_and_expand_aliases(self) -> None:
        queries = job_runner.literature_queries_from_outline({
            "intro_related_work_plan": {
                "introduction_strategy": {
                    "search_directions": [
                        "Long-context efficiency motivation and scaling limits for Transformers",
                    ],
                },
                "related_work_strategy": {
                    "subsections": [
                        {
                            "sota_investigation_mission": "Compare BigBird and Longformer",
                            "limitation_search_queries": [
                                "BigBird sparse attention baseline long context",
                                "Longformer sliding window global attention long context",
                            ],
                        },
                    ],
                },
            },
        })

        self.assertEqual(queries[0][1], "Big Bird: Transformers for Longer Sequences")
        self.assertEqual(queries[1][1], "BigBird sparse attention baseline long context")
        self.assertEqual(queries[2][1], "Longformer: The Long-Document Transformer")
        self.assertFalse(any(query == "Long-context efficiency motivation and scaling limits for Transformers" for _, query in queries))

    def test_literature_match_score_penalizes_irrelevant_openalex_titles(self) -> None:
        relevant = job_runner.literature_match_score(
            "flashattention efficient long context transformers",
            "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness",
            "FlashAttention accelerates transformer attention with exact IO-aware kernels.",
        )
        irrelevant = job_runner.literature_match_score(
            "flashattention efficient long context transformers",
            "Brain tumor segmentation with transformer priors",
            "We study medical image segmentation with transformer backbones.",
        )

        self.assertGreater(relevant, 0.40)
        self.assertLess(irrelevant, relevant)

    def test_with_min_stage_timeout_raises_low_global_timeout(self) -> None:
        updated = job_runner.with_min_stage_timeout({"PAPERORCHESTRA_CODEX_TIMEOUT_SECONDS": "180"}, 360.0)
        self.assertEqual(updated["PAPERORCHESTRA_CODEX_TIMEOUT_SECONDS"], "360.0")

        unchanged = job_runner.with_min_stage_timeout({"PAPERORCHESTRA_CODEX_TIMEOUT_SECONDS": "900"}, 360.0)
        self.assertEqual(unchanged["PAPERORCHESTRA_CODEX_TIMEOUT_SECONDS"], "900")

    def test_build_verified_citation_pool_falls_back_to_openalex_when_s2_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir) / "workspace"
            inputs = workspace / "inputs"
            inputs.mkdir(parents=True, exist_ok=True)
            (inputs / "conference_guidelines.md").write_text(
                "Submission deadline: 2025-01-15\nLiterature cutoff: 2024-10-01\n",
                encoding="utf-8",
            )
            (workspace / "outline.json").write_text(
                json.dumps({
                    "plotting_plan": [],
                    "intro_related_work_plan": {
                        "introduction_strategy": {
                            "hook_hypothesis": "Hook",
                            "problem_gap_hypothesis": "Gap",
                            "search_directions": ["attention mechanisms"],
                        },
                        "related_work_strategy": {
                            "subsections": [
                                {
                                    "section_title": "Dense attention",
                                    "comparison_axis": "architecture",
                                    "sota_investigation_mission": "attention is all you need",
                                    "limitation_search_queries": [],
                                },
                            ],
                        },
                    },
                    "section_plan": [],
                }, indent=2),
                encoding="utf-8",
            )
            log_path = Path(tempdir) / "literature.log"
            openalex_result = {
                "id": "https://openalex.org/W2626778328",
                "display_name": "Attention Is All You Need",
                "abstract_inverted_index": {
                    "Attention": [0],
                    "replaces": [1],
                    "recurrence": [2],
                },
                "publication_year": 2017,
                "publication_date": "2017-06-12",
                "authorships": [{"author": {"display_name": "Ashish Vaswani"}}],
                "primary_location": {"source": {"display_name": "NeurIPS"}},
                "doi": "https://doi.org/10.5555/3295222.3295349",
                "ids": {},
                "_paperorchestra_match_score": 0.55,
            }

            with mock.patch("gui_app.job_runner.run_semantic_scholar_query", return_value=[]):
                with mock.patch("gui_app.job_runner.run_openalex_query", return_value=[openalex_result]) as openalex:
                    artifacts, citation_pool_path, refs_path = job_runner.build_verified_citation_pool(
                        workspace,
                        env={**os.environ, "PAPERORCHESTRA_ACCEPTANCE_STRICT_S2_CACHE": "0"},
                        log_path=log_path,
                    )
            openalex.assert_called()
            self.assertIn(str(citation_pool_path), artifacts)
            self.assertIn(str(refs_path), artifacts)
            pool = json.loads(citation_pool_path.read_text(encoding="utf-8"))
            self.assertEqual(pool["papers"][0]["title"], "Attention Is All You Need")
            self.assertEqual(pool["papers"][0]["authors"][0]["name"], "Ashish Vaswani")
            self.assertTrue(refs_path.read_text(encoding="utf-8").startswith("% Generated by"))

    def test_build_verified_citation_pool_strict_cache_skips_openalex_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir) / "workspace"
            inputs = workspace / "inputs"
            inputs.mkdir(parents=True, exist_ok=True)
            (inputs / "conference_guidelines.md").write_text(
                "Submission deadline: 2025-01-15\nLiterature cutoff: 2024-10-01\n",
                encoding="utf-8",
            )
            (workspace / "outline.json").write_text(
                json.dumps({
                    "plotting_plan": [],
                    "intro_related_work_plan": {
                        "introduction_strategy": {
                            "hook_hypothesis": "Hook",
                            "problem_gap_hypothesis": "Gap",
                            "search_directions": ["attention mechanisms"],
                        },
                        "related_work_strategy": {
                            "subsections": [
                                {
                                    "section_title": "Dense attention",
                                    "comparison_axis": "architecture",
                                    "sota_investigation_mission": "attention is all you need",
                                    "limitation_search_queries": [],
                                },
                            ],
                        },
                    },
                    "section_plan": [],
                }, indent=2),
                encoding="utf-8",
            )
            log_path = Path(tempdir) / "literature.log"

            with mock.patch("gui_app.job_runner.run_semantic_scholar_query", return_value=[]):
                with mock.patch("gui_app.job_runner.run_openalex_query") as openalex:
                    with self.assertRaises(RuntimeError) as raised:
                        job_runner.build_verified_citation_pool(
                            workspace,
                            env={**os.environ, "PAPERORCHESTRA_ACCEPTANCE_STRICT_S2_CACHE": "1"},
                            log_path=log_path,
                        )

            openalex.assert_not_called()
            self.assertIn("strict local Semantic Scholar cache", str(raised.exception))
            self.assertIn("Strict Semantic Scholar cache mode skipped OpenAlex", log_path.read_text(encoding="utf-8"))

    def test_run_semantic_scholar_query_strict_cache_propagates_miss(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["s2_search.py"],
            returncode=1,
            stdout="",
            stderr="ERROR: strict acceptance Semantic Scholar cache miss for query: attention mechanisms\n",
        )
        with tempfile.TemporaryDirectory() as tempdir:
            log_path = Path(tempdir) / "literature.log"
            with mock.patch("gui_app.job_runner.subprocess.run", return_value=completed):
                with self.assertRaises(RuntimeError) as raised:
                    job_runner.run_semantic_scholar_query(
                        "attention mechanisms",
                        {"PAPERORCHESTRA_ACCEPTANCE_STRICT_S2_CACHE": "1"},
                        log_path,
                    )

        self.assertIn("Strict Semantic Scholar cache miss or failure", str(raised.exception))


class LauncherSmokeTests(unittest.TestCase):
    def test_launcher_starts_server_and_reports_health(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            port = _free_port()
            data_root = Path(tempdir) / "launcher-data"
            completed = subprocess.run(
                [
                    str(storage.repo_python_executable()),
                    "scripts/launch_gui.py",
                    "--no-browser",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--data-root",
                    str(data_root),
                ],
                cwd=str(storage.REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            match = re.search(r"pid (\d+)", completed.stdout)
            self.assertIsNotNone(match, msg=completed.stdout)
            pid = int(match.group(1))

            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5.0) as response:
                    self.assertEqual(response.status, 200)
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["status"], "ok")
                self.assertEqual(Path(payload["data_root"]).resolve(), data_root.resolve())
            finally:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except OSError:
                    pass
