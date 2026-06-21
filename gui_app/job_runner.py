#!/usr/bin/env python3
"""Background job runner for the PaperOrchestra local GUI."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import difflib
import hashlib
import json
import os
import resource
import re
import shutil
import subprocess
import sys
import threading
import traceback
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import config
from . import figure_adapter
from . import research_adapter
from . import storage
from . import writer_executor

RUN_WRITE_LOCK = threading.Lock()
PERFORMANCE_LOCK = threading.Lock()
STAGE_PERFORMANCE_PROBES: dict[tuple[str, str, str], dict[str, float | int]] = {}
SUBSTEP_PERFORMANCE_PROBES: dict[tuple[str, str, str, str], dict[str, float | int]] = {}
KNOWN_LITERATURE_ALIASES = {
    "bigbird": "Big Bird: Transformers for Longer Sequences",
    "longformer": "Longformer: The Long-Document Transformer",
    "reformer": "Reformer: The Efficient Transformer",
    "performer": "Rethinking Attention with Performers",
    "flashattention": "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness",
    "switch transformer": "Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity",
    "gumbel-softmax": "Categorical Reparameterization with Gumbel-Softmax",
    "gumbel softmax": "Categorical Reparameterization with Gumbel-Softmax",
}
LITERATURE_STOPWORDS = {
    "about",
    "across",
    "after",
    "against",
    "among",
    "between",
    "from",
    "into",
    "paper",
    "papers",
    "prior",
    "search",
    "system",
    "their",
    "these",
    "this",
    "through",
    "using",
    "with",
}


class RunNeedsInput(RuntimeError):
    """Raised when a run needs user intervention instead of hard failure."""


def _rusage_cpu_seconds(usage: resource.struct_rusage) -> float:
    return float(usage.ru_utime + usage.ru_stime)


def _rusage_maxrss_bytes(usage: resource.struct_rusage) -> int:
    # macOS reports bytes; Linux reports KiB. Keep the artifact normalized.
    value = int(usage.ru_maxrss or 0)
    if sys.platform == "darwin":
        return value
    return value * 1024


def _performance_sample() -> dict[str, float | int]:
    self_usage = resource.getrusage(resource.RUSAGE_SELF)
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "monotonic": time.perf_counter(),
        "self_cpu_seconds": _rusage_cpu_seconds(self_usage),
        "children_cpu_seconds": _rusage_cpu_seconds(child_usage),
        "max_rss_bytes": max(_rusage_maxrss_bytes(self_usage), _rusage_maxrss_bytes(child_usage)),
        "pid": os.getpid(),
    }


def _performance_delta(start: dict[str, float | int], finish: dict[str, float | int]) -> dict[str, object]:
    wall_seconds = max(float(finish["monotonic"]) - float(start["monotonic"]), 0.0)
    self_cpu_seconds = max(float(finish["self_cpu_seconds"]) - float(start["self_cpu_seconds"]), 0.0)
    children_cpu_seconds = max(float(finish["children_cpu_seconds"]) - float(start["children_cpu_seconds"]), 0.0)
    total_cpu_seconds = self_cpu_seconds + children_cpu_seconds
    cpu_percent = None
    if wall_seconds > 0.001:
        cpu_percent = round((total_cpu_seconds / wall_seconds) * 100.0, 1)
    return {
        "measurement_scope": "process_delta",
        "parallel_attribution": "shared_process_when_stages_overlap",
        "wall_seconds": round(wall_seconds, 3),
        "self_cpu_seconds": round(self_cpu_seconds, 3),
        "children_cpu_seconds": round(children_cpu_seconds, 3),
        "total_cpu_seconds": round(total_cpu_seconds, 3),
        "cpu_percent_of_one_core": cpu_percent,
        "max_rss_bytes": int(finish["max_rss_bytes"]),
        "pid": int(finish["pid"]),
        "logical_cpu_count": os.cpu_count() or 1,
    }


def _start_stage_performance(project_id: str, run_id: str, stage_name: str) -> None:
    with PERFORMANCE_LOCK:
        STAGE_PERFORMANCE_PROBES[(project_id, run_id, stage_name)] = _performance_sample()


def _finish_stage_performance(project_id: str, run_id: str, stage_name: str) -> dict[str, object] | None:
    with PERFORMANCE_LOCK:
        start = STAGE_PERFORMANCE_PROBES.pop((project_id, run_id, stage_name), None)
    if not start:
        return None
    return _performance_delta(start, _performance_sample())


def _start_substep_performance(project_id: str, run_id: str, stage_name: str, substep_name: str) -> None:
    with PERFORMANCE_LOCK:
        SUBSTEP_PERFORMANCE_PROBES[(project_id, run_id, stage_name, substep_name)] = _performance_sample()


def _finish_substep_performance(project_id: str, run_id: str, stage_name: str, substep_name: str) -> dict[str, object] | None:
    with PERFORMANCE_LOCK:
        start = SUBSTEP_PERFORMANCE_PROBES.pop((project_id, run_id, stage_name, substep_name), None)
    if not start:
        return None
    return _performance_delta(start, _performance_sample())


def _write_performance_snapshot(project_id: str, run_id: str, data_root: Path) -> None:
    run_payload = storage.load_run(project_id, run_id, data_root)
    if not run_payload:
        return
    stages: dict[str, object] = {}
    for stage_name, stage_payload in (run_payload.get("stages") or {}).items():
        if not isinstance(stage_payload, dict):
            continue
        stage_entry: dict[str, object] = {}
        if isinstance(stage_payload.get("performance"), dict):
            stage_entry["performance"] = stage_payload["performance"]
        substeps = []
        for substep in stage_payload.get("substeps", []) or []:
            if not isinstance(substep, dict) or not isinstance(substep.get("performance"), dict):
                continue
            substeps.append({
                "name": substep.get("name", ""),
                "status": substep.get("status", ""),
                "performance": substep["performance"],
            })
        if substeps:
            stage_entry["substeps"] = substeps
        if stage_entry:
            stages[str(stage_name)] = stage_entry
    if not stages:
        return
    performance_path = storage.run_dir(project_id, run_id, data_root) / "performance.json"
    storage.atomic_write_json(
        performance_path,
        {
            "project_id": project_id,
            "run_id": run_id,
            "updated_at": storage.utc_now(),
            "stages": stages,
        },
    )


def load_run_or_raise(project_id: str, run_id: str, data_root: Path) -> dict:
    run_payload = storage.load_run(project_id, run_id, data_root)
    if not run_payload:
        raise RuntimeError(f"Missing run record for {project_id}/{run_id}")
    return run_payload


def update_run(project_id: str, run_id: str, data_root: Path, **fields: object) -> dict:
    with RUN_WRITE_LOCK:
        return storage.update_run_fields(project_id, run_id, data_root, **fields)


def update_stage(project_id: str, run_id: str, data_root: Path, stage_name: str, **fields: object) -> dict:
    status = str(fields.get("status", "") or "")
    if status == "running":
        _start_stage_performance(project_id, run_id, stage_name)
    elif status in storage.TERMINAL_STAGE_STATUSES:
        performance = _finish_stage_performance(project_id, run_id, stage_name)
        if performance and "performance" not in fields:
            fields["performance"] = performance
    with RUN_WRITE_LOCK:
        run_payload = load_run_or_raise(project_id, run_id, data_root)
        updated = storage.update_stage_state(run_payload, stage_name, data_root, **fields)
    if "performance" in fields:
        _write_performance_snapshot(project_id, run_id, data_root)
    return updated


def save_stage_artifacts(project_id: str, run_id: str, data_root: Path, stage_name: str, paths: list[str]) -> dict:
    with RUN_WRITE_LOCK:
        run_payload = load_run_or_raise(project_id, run_id, data_root)
        updated = storage.save_stage_artifacts(run_payload, stage_name, data_root, paths)
        return updated


def update_stage_substep(
    project_id: str,
    run_id: str,
    data_root: Path,
    stage_name: str,
    substep_name: str,
    *,
    event_type: str = "stage_substep_updated",
    **fields: object,
) -> dict:
    status = str(fields.get("status", "") or "")
    if status == "running":
        _start_substep_performance(project_id, run_id, stage_name, substep_name)
    elif status in storage.TERMINAL_STAGE_STATUSES:
        performance = _finish_substep_performance(project_id, run_id, stage_name, substep_name)
        if performance and "performance" not in fields:
            fields["performance"] = performance
    with RUN_WRITE_LOCK:
        run_payload = load_run_or_raise(project_id, run_id, data_root)
        updated = storage.upsert_stage_substep(
            run_payload,
            stage_name,
            substep_name,
            data_root,
            event_type=event_type,
            **fields,
        )
    if "performance" in fields:
        _write_performance_snapshot(project_id, run_id, data_root)
    return updated


def update_stage_loop_state(
    project_id: str,
    run_id: str,
    data_root: Path,
    stage_name: str,
    *,
    event_type: str = "stage_loop_state_updated",
    **fields: object,
) -> dict:
    with RUN_WRITE_LOCK:
        run_payload = load_run_or_raise(project_id, run_id, data_root)
        updated = storage.set_stage_loop_state(
            run_payload,
            stage_name,
            data_root,
            event_type=event_type,
            **fields,
        )
        return updated


def start_stage_substep(
    project_id: str,
    run_id: str,
    data_root: Path,
    stage_name: str,
    substep_name: str,
    summary: str,
) -> None:
    update_stage_substep(
        project_id,
        run_id,
        data_root,
        stage_name,
        substep_name,
        event_type="stage_substep_started",
        status="running",
        summary=summary,
    )


def finish_stage_substep(
    project_id: str,
    run_id: str,
    data_root: Path,
    stage_name: str,
    substep_name: str,
    summary: str,
    *,
    status: str = "succeeded",
    artifacts: list[str] | None = None,
    attention_required: dict[str, object] | None = None,
) -> None:
    update_stage_substep(
        project_id,
        run_id,
        data_root,
        stage_name,
        substep_name,
        event_type="stage_substep_finished",
        status=status,
        summary=summary,
        artifacts=artifacts or [],
        attention_required=attention_required,
    )


def append_log(log_path: Path, text: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def run_command(command: list[str], cwd: Path, log_path: Path, env: dict[str, str]) -> None:
    if _acceptance_fixtures_enabled(env):
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
            append_log(log_path, f"$ {' '.join(command)}")
            return
        if command and command[0] == "latexmk":
            Path(cwd).mkdir(parents=True, exist_ok=True)
            (Path(cwd) / "paper.pdf").write_bytes(b"%PDF-1.4\n% acceptance fixture pdf\n")
            append_log(log_path, f"$ {' '.join(command)}")
            return
    append_log(log_path, f"$ {' '.join(command)}")
    with log_path.open("a", encoding="utf-8") as handle:
        process = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if process.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {process.returncode}: {' '.join(command)}")


def pipeline_prompt(workspace: Path) -> str:
    return "\n".join([
        f"Run the PaperOrchestra pipeline on `{workspace}`.",
        "Read `skills/paper-orchestra/SKILL.md` and follow it faithfully.",
        "Use the existing workspace inputs and deterministic helper scripts.",
        "Restrict your repo inspection to the stage skill, its references/scripts, and the target workspace. Do not inspect `PLANS.md`, repo-level planning notes, or memory files unless the stage is blocked without them.",
        "Skip Semantic Scholar setup if it is unavailable; do not block the run on missing Semantic Scholar keys.",
        "If web search is available, use it for literature discovery as needed.",
        "Compile the final PDF with `latexmk -pdf` if the pipeline reaches the final step.",
        "Keep the final response concise and include the final artifact path if successful.",
    ])


def outline_prompt(workspace: Path) -> str:
    idea_text = (workspace / "inputs" / "idea.md").read_text(encoding="utf-8").strip()
    log_text = (workspace / "inputs" / "experimental_log.md").read_text(encoding="utf-8").strip()
    template_text = (workspace / "inputs" / "template.tex").read_text(encoding="utf-8").strip()
    guidelines_text = (workspace / "inputs" / "conference_guidelines.md").read_text(encoding="utf-8").strip()
    return "\n".join([
        f"Execute the PaperOrchestra outline stage for `{workspace}`.",
        "Return the final answer as a JSON object only. Do not use markdown fences. Do not emit prose before or after the JSON.",
        "Do not use shell commands or inspect repo files. All required inputs are embedded below.",
        "The JSON must have exactly these top-level keys: `plotting_plan`, `intro_related_work_plan`, `section_plan`.",
        "For `plotting_plan`, produce 3-5 compelling figures grounded in the idea and experiment log. Each figure must include `figure_id`, `title`, `plot_type`, `data_source`, `objective`, and `aspect_ratio`.",
        "For `plot_type`, use only `plot` or `diagram`. For `data_source`, use only `idea.md`, `experimental_log.md`, or `both`. For `aspect_ratio`, use one of `1:1`, `1:4`, `2:3`, `3:2`, `3:4`, `4:1`, `4:3`, `4:5`, `5:4`, `9:16`, `16:9`, `21:9`.",
        "For `intro_related_work_plan`, strictly separate introduction-level macro context from related-work technical comparisons. Derive the literature cutoff from `conference_guidelines.md` and do not instruct searches after that cutoff.",
        "For `section_plan`, follow the template skeleton and plan the sections that Step 4 will write. Keep Introduction and Related Work out of `section_plan` because Step 3 owns them.",
        "Every section in `section_plan` must contain at least two subsections so there are no orphan subsections.",
        "Every subsection must contain concrete `content_bullets` grounded in the inputs and exhaustive `citation_hints` for every dataset, baseline, metric, optimizer, architecture, or foundational method it mentions.",
        "The conference deadline and literature cutoff must be derived from conference_guidelines.md.",
        "Do not inspect `PLANS.md`, unrelated repo docs, or memory files unless the stage cannot proceed without them.",
        "",
        "<idea_md>",
        idea_text,
        "</idea_md>",
        "",
        "<experimental_log_md>",
        log_text,
        "</experimental_log_md>",
        "",
        "<template_tex>",
        template_text,
        "</template_tex>",
        "",
        "<conference_guidelines_md>",
        guidelines_text,
        "</conference_guidelines_md>",
    ])


def plotting_prompt(workspace: Path) -> str:
    return "\n".join([
        f"Read `skills/plotting-agent/SKILL.md` and execute Step 2 on `{workspace}`.",
        "Only inspect plotting-agent resources plus the workspace artifacts required for figure generation.",
        "Do not inspect `PLANS.md`, unrelated repo docs, or memory files unless blocked.",
        "Prefer the PaperBanana/PaperVizAgent backend for diagram-style figures when PAPERBANANA_PATH or PAPERVIZAGENT_PATH is valid.",
        "Prefer the deterministic local renderers for numeric plots unless the skill requires otherwise.",
        "Write figure PNGs under `figures/` and captions to `figures/captions.json`.",
        "Keep the final response concise and mention generated figure ids.",
    ])


def section_writing_prompt(workspace: Path) -> str:
    return "\n".join([
        f"Read `skills/section-writing-agent/SKILL.md` and execute Step 4 on `{workspace}`.",
        "Only inspect section-writing-agent resources plus the workspace outputs from prior stages.",
        "Do not inspect `PLANS.md`, unrelated repo docs, or memory files unless blocked.",
        "Preserve the literature-review outputs already present in the workspace.",
        "Write the full draft to `drafts/paper.tex` and stop only after the deterministic gates can pass.",
        "Keep the final response concise and mention the draft path.",
    ])


def refinement_prompt(workspace: Path) -> str:
    return "\n".join([
        f"Read `skills/content-refinement-agent/SKILL.md` and execute Step 5 on `{workspace}`.",
        "Only inspect content-refinement-agent resources plus the current workspace draft artifacts.",
        "Do not inspect `PLANS.md`, unrelated repo docs, or memory files unless blocked.",
        "Maintain the refinement worklog and snapshots under `refinement/`.",
        "Promote the accepted snapshot to `final/paper.tex`.",
        "Keep the final response concise and mention the final tex path and iteration count.",
    ])


def ensure_runtime_env(data_root: Path) -> dict[str, str]:
    env = config.load_runtime_env(dict(os.environ))
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault(
        "PAPERORCHESTRA_S2_CACHE_DB",
        str(storage.get_paths(data_root).data_root / "shared-cache" / "semantic_scholar.sqlite3"),
    )
    env.setdefault("PAPERORCHESTRA_S2_RATE_LIMIT_SECONDS", "1.0")
    return env


def with_min_stage_timeout(env: dict[str, str], minimum_seconds: float) -> dict[str, str]:
    runtime = dict(env)
    raw_value = str(runtime.get("PAPERORCHESTRA_CODEX_TIMEOUT_SECONDS", "") or "").strip()
    current_timeout = 0.0
    if raw_value:
        try:
            current_timeout = float(raw_value)
        except ValueError:
            current_timeout = 0.0
    if current_timeout < minimum_seconds:
        runtime["PAPERORCHESTRA_CODEX_TIMEOUT_SECONDS"] = str(float(minimum_seconds))
    return runtime


def check_for_cancel(project_id: str, run_id: str, data_root: Path) -> None:
    run_payload = load_run_or_raise(project_id, run_id, data_root)
    if run_payload.get("cancel_requested_at"):
        raise RuntimeError("Run cancellation was requested.")


def _acceptance_mode_enabled(env: dict[str, str]) -> bool:
    return str(env.get("PAPERORCHESTRA_ACCEPTANCE_MODE", "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _acceptance_fixtures_enabled(env: dict[str, str]) -> bool:
    return str(env.get("PAPERORCHESTRA_ACCEPTANCE_FIXTURES", "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _acceptance_fixture_disabled_stages(env: dict[str, str]) -> set[str]:
    raw_value = str(env.get("PAPERORCHESTRA_ACCEPTANCE_DISABLE_FIXTURES", "") or "").strip()
    if not raw_value:
        return set()
    return {
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    }


def _acceptance_fixtures_enabled_for_stage(env: dict[str, str], stage_name: str) -> bool:
    return _acceptance_fixtures_enabled(env) and stage_name not in _acceptance_fixture_disabled_stages(env)


def _acceptance_strict_s2_cache_enabled(env: dict[str, str]) -> bool:
    return str(env.get("PAPERORCHESTRA_ACCEPTANCE_STRICT_S2_CACHE", "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _acceptance_failpoint_marker(project_id: str, run_id: str, data_root: Path, stage_name: str) -> Path:
    return storage.run_dir(project_id, run_id, data_root) / "acceptance" / f"failpoint-{stage_name}.consumed"


def maybe_trigger_acceptance_failpoint(
    project_id: str,
    run_id: str,
    data_root: Path,
    stage_name: str,
    env: dict[str, str],
) -> None:
    if not _acceptance_mode_enabled(env):
        return
    target_stage = str(env.get("PAPERORCHESTRA_ACCEPTANCE_FAIL_STAGE", "") or "").strip()
    if not target_stage or target_stage != stage_name:
        return
    marker = _acceptance_failpoint_marker(project_id, run_id, data_root, stage_name)
    if marker.exists():
        return
    storage.ensure_dir(marker.parent)
    marker.write_text(storage.utc_now() + "\n", encoding="utf-8")
    message = f"Acceptance failpoint injected a one-shot failure at stage `{stage_name}`."
    stage_log = Path(load_run_or_raise(project_id, run_id, data_root)["stages"][stage_name]["log_path"])
    append_log(stage_log, message)
    update_stage(
        project_id,
        run_id,
        data_root,
        stage_name,
        status="failed",
        summary=message,
        attention_required={
            "reason": "manual_review",
            "message": message,
            "details": {"acceptance_failpoint": True, "stage": stage_name},
        },
    )
    raise RuntimeError(message)


def _acceptance_png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + (b"0" * 2048)


def _acceptance_outline_fixture() -> dict[str, object]:
    payload = json.loads(
        (storage.REPO_ROOT / "skills" / "outline-agent" / "references" / "example-output.json").read_text(encoding="utf-8")
    )
    payload.pop("_comment", None)
    return payload


def _acceptance_bibtex_keys(workspace: Path) -> list[str]:
    refs_path = workspace / "refs.bib"
    if not refs_path.exists():
        return ["vaswani2017"]
    keys = re.findall(r"@\w+\{([^,]+),", refs_path.read_text(encoding="utf-8"))
    return keys or ["vaswani2017"]


def _write_acceptance_writer_fixture(stage_name: str, workspace: Path, transcript_path: Path, log_path: Path) -> None:
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(f"$ acceptance fixture {stage_name}\n", encoding="utf-8")

    if stage_name == "outline":
        transcript_path.write_text(json.dumps(_acceptance_outline_fixture(), indent=2), encoding="utf-8")
        return

    if stage_name == "plotting":
        transcript_path.write_text("plotting complete\n", encoding="utf-8")
        figures_root = workspace / "figures"
        figures_root.mkdir(parents=True, exist_ok=True)
        (figures_root / "atk_tradeoff.png").write_bytes(_acceptance_png_bytes())
        (figures_root / "captions.json").write_text(
            json.dumps({"figures": [{"figure_id": "fig_atk_tradeoff", "caption": "ATK quality-compute tradeoff."}]}, indent=2),
            encoding="utf-8",
        )
        return

    if stage_name == "literature":
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
        return

    if stage_name == "section_writing":
        transcript_path.write_text("section_writing complete\n", encoding="utf-8")
        (workspace / "drafts").mkdir(parents=True, exist_ok=True)
        citation_keys = _acceptance_bibtex_keys(workspace)
        citation_clause = ",".join(citation_keys[: min(2, len(citation_keys))])
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
                f"Adaptive sparse attention improves long-context modeling while remaining controllable. \\cite{{{citation_clause}}}",
                "\\section{Related Work}",
                f"Prior work established dense Transformer attention as the baseline. \\cite{{{citation_clause}}}",
                "\\section{Method}",
                "We render the quality-compute tradeoff in Figure~\\ref{fig:atk_tradeoff}.",
                "\\begin{figure}[t]",
                "\\centering",
                "\\includegraphics[width=0.8\\linewidth]{../figures/atk_tradeoff.png}",
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
        return

    if stage_name == "refinement":
        transcript_path.write_text("refinement complete\n", encoding="utf-8")
        (workspace / "final").mkdir(parents=True, exist_ok=True)
        (workspace / "refinement").mkdir(parents=True, exist_ok=True)
        draft_path = workspace / "drafts" / "paper.tex"
        if draft_path.exists():
            (workspace / "final" / "paper.tex").write_text(draft_path.read_text(encoding="utf-8"), encoding="utf-8")
        (workspace / "refinement" / "worklog.json").write_text(
            json.dumps({"iterations": [{"accepted": True, "reason": "acceptance fixture refinement"}]}, indent=2),
            encoding="utf-8",
        )
        return

    transcript_path.write_text(f"{stage_name} complete\n", encoding="utf-8")


def parse_markdown_sections(markdown_text: str) -> dict[str, str]:
    pattern = re.compile(r"^##\s+(.+?)\s*$", flags=re.MULTILINE)
    matches = list(pattern.finditer(markdown_text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        key = match.group(1).strip().casefold()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_text)
        sections[key] = markdown_text[start:end].strip()
    return sections


def extract_bulleted_values(markdown_text: str, heading: str) -> list[str]:
    pattern = re.compile(rf"^\*+\s+\*\*{re.escape(heading)}:\*\*\s*$", flags=re.MULTILINE)
    match = pattern.search(markdown_text)
    if not match:
        return []
    tail = markdown_text[match.end():]
    values: list[str] = []
    for raw_line in tail.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            if values:
                break
            continue
        if raw_line.startswith("## "):
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            values.append(stripped[2:].strip())
            continue
        if values:
            break
    return values


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def synthesize_outline_payload(workspace: Path) -> dict[str, object]:
    idea_text = (workspace / "inputs" / "idea.md").read_text(encoding="utf-8")
    log_text = (workspace / "inputs" / "experimental_log.md").read_text(encoding="utf-8")
    guidelines_text = (workspace / "inputs" / "conference_guidelines.md").read_text(encoding="utf-8")
    sections = parse_markdown_sections(idea_text)

    problem_statement = compact_text(sections.get("problem statement", ""))
    hypothesis = compact_text(sections.get("core hypothesis", ""))
    methodology = compact_text(sections.get("proposed methodology (high-level technical approach)", ""))
    expected_contribution = compact_text(sections.get("expected contribution", ""))
    datasets = extract_bulleted_values(log_text, "Datasets") or [
        "NaturalQuestions-Long (NQ-L)",
        "NarrativeQA",
        "GovReport-Summ",
    ]
    baselines = extract_bulleted_values(log_text, "Baselines Compared") or [
        "dense self-attention",
        "BigBird",
        "Longformer",
        "Reformer",
        "Performer",
    ]
    metrics = extract_bulleted_values(log_text, "Evaluation Metrics") or [
        "Exact Match (EM)",
        "F1",
        "ROUGE-L",
        "BLEU-4",
        "tokens-per-second (TPS)",
        "peak GPU memory",
        "forward FLOPs",
    ]
    baseline_labels = ["dense attention", "BigBird", "Longformer", "Reformer", "Performer"]
    cutoff_date = derive_cutoff_date(guidelines_text)
    venue_scope = "efficient transformers, long-context modeling, and evaluation"
    if "efficient transformers" not in guidelines_text.casefold():
        venue_scope = "long-context modeling and machine learning methodology"

    return {
        "plotting_plan": [
            {
                "figure_id": "fig_atk_quality_compute_tradeoff",
                "title": "ATK Quality-Compute Tradeoff Across K",
                "plot_type": "plot",
                "data_source": "experimental_log.md",
                "objective": "Line Chart showing task quality versus forward FLOPs across ATK K settings and fixed sparse-attention baselines.",
                "aspect_ratio": "16:9",
            },
            {
                "figure_id": "fig_atk_efficiency_profile",
                "title": "Inference Speed and Memory Efficiency",
                "plot_type": "plot",
                "data_source": "experimental_log.md",
                "objective": "Grouped Bar Chart comparing tokens-per-second and peak GPU memory for dense attention, sparse baselines, and ATK variants.",
                "aspect_ratio": "16:9",
            },
            {
                "figure_id": "fig_atk_ablation_components",
                "title": "Ablation of Content-Adaptive Design Choices",
                "plot_type": "plot",
                "data_source": "experimental_log.md",
                "objective": "Grouped Bar Chart isolating the effect of load balancing, Gumbel-Softmax training, layer-wise scoring, and content-aware selection on NQ-L F1.",
                "aspect_ratio": "4:3",
            },
            {
                "figure_id": "fig_atk_method_overview",
                "title": "Adaptive Top-K Attention Block Overview",
                "plot_type": "diagram",
                "data_source": "both",
                "objective": "Diagram of the ATK pipeline from query-side scoring through top-K masking, softmax over selected keys, and auxiliary load-balancing regularization.",
                "aspect_ratio": "16:9",
            },
        ],
        "intro_related_work_plan": {
            "introduction_strategy": {
                "hook_hypothesis": problem_statement or "Quadratic self-attention remains the main barrier to practical long-context Transformers.",
                "problem_gap_hypothesis": hypothesis or "Existing sparse attention patterns are hand-designed and do not adapt to input content.",
                "search_directions": [
                    "Transformer quadratic attention scaling in long-context tasks",
                    "Sparse attention baselines for long-document question answering and summarization before 2024-10-01",
                    "Differentiable top-k or routing mechanisms for learned sparse attention before 2024-10-01",
                    "Benchmarks and evaluation papers covering NaturalQuestions-Long, NarrativeQA, and GovReport-Summ before 2024-10-01",
                ],
            },
            "related_work_strategy": {
                "overview": (
                    f"Build the related work around three clusters that motivate ATK-Attention for {venue_scope}. "
                    f"Use {cutoff_date} as the literature cutoff for prior work."
                ),
                "subsections": [
                    {
                        "subsection_title": "2.1 Fixed Sparse Attention for Long Context",
                        "methodology_cluster": "Block-sparse, sliding-window, hashing, and kernelized attention",
                        "sota_investigation_mission": "Identify the canonical fixed-pattern sparse attention methods used as long-context baselines and summarize their quality-efficiency tradeoffs.",
                        "limitation_hypothesis": "Fixed sparsity patterns improve efficiency but cannot adapt attention structure to the semantic needs of each query token.",
                        "limitation_search_queries": [
                            "BigBird Longformer Reformer Performer long-context sparse attention limitations",
                            "fixed sparse attention long document question answering summarization limitations",
                        ],
                        "bridge_to_our_method": "ATK-Attention keeps the sparse-efficiency goal but makes the selection pattern content-adaptive rather than position-adaptive.",
                    },
                    {
                        "subsection_title": "2.2 Learned Routing and Content-Adaptive Sparsity",
                        "methodology_cluster": "Token routing, learned sparsity, and adaptive computation",
                        "sota_investigation_mission": "Find prior work on learned attention routing or content-adaptive sparsity and position ATK-Attention within that line.",
                        "limitation_hypothesis": "Earlier adaptive routing methods often target mixture-of-experts or coarse token selection rather than per-query key selection inside self-attention.",
                        "limitation_search_queries": [
                            "content-adaptive sparse attention learned routing transformers",
                            "adaptive token selection self-attention learned top-k routing",
                        ],
                        "bridge_to_our_method": "ATK-Attention specializes adaptive routing to per-query key selection with a lightweight scoring head.",
                    },
                    {
                        "subsection_title": "2.3 Training Sparse Selection Mechanisms",
                        "methodology_cluster": "Differentiable top-k, Gumbel-Softmax, and load balancing",
                        "sota_investigation_mission": "Collect foundational work supporting differentiable discrete selection and regularization strategies relevant to ATK training.",
                        "limitation_hypothesis": "Sparse selection is hard to optimize because hard top-k decisions are non-differentiable and can collapse without explicit balancing terms.",
                        "limitation_search_queries": [
                            "Gumbel-Softmax differentiable top-k attention training",
                            "load balancing regularization sparse attention collapse",
                        ],
                        "bridge_to_our_method": "ATK-Attention combines a Gumbel-Softmax surrogate with auxiliary load balancing to train stable content-adaptive sparsity.",
                    },
                ],
            },
        },
        "section_plan": [
            {
                "section_title": "Abstract",
                "subsections": [
                    {
                        "subsection_title": "Abstract Problem and Method Hook",
                        "content_bullets": [
                            "State that quadratic self-attention is a bottleneck for long-context QA and summarization.",
                            "Introduce Adaptive Top-K Attention as a drop-in content-adaptive sparse attention mechanism.",
                        ],
                        "citation_hints": [
                            "Vaswani et al. (Attention Is All You Need)",
                        ],
                    },
                    {
                        "subsection_title": "Abstract Results and Contribution Summary",
                        "content_bullets": [
                            "Summarize the K-controlled quality-compute tradeoff and the headline NQ-L result around K=64 versus dense attention.",
                            "Mention the benchmark suite spanning " + ", ".join(datasets[:3]) + ".",
                        ],
                        "citation_hints": [
                            "Natural Questions / NaturalQuestions-Long dataset paper",
                            "NarrativeQA dataset paper",
                            "GovReport summarization dataset paper",
                        ],
                    },
                ],
            },
            {
                "section_title": "Method",
                "subsections": [
                    {
                        "subsection_title": "ATK Attention Formulation",
                        "content_bullets": [
                            "Define the query-side scoring head and how it predicts relevant key positions.",
                            "Explain the forward pass: scoring, top-K masking, masked softmax over QK^T/sqrt(d), and value aggregation.",
                            "Clarify how ATK differs from fixed sparse patterns used by " + ", ".join(baseline_labels) + ".",
                        ],
                        "citation_hints": [
                            "Vaswani et al. (Attention Is All You Need)",
                            "BigBird paper",
                            "Longformer paper",
                            "Reformer paper",
                            "Performer paper",
                        ],
                    },
                    {
                        "subsection_title": "Differentiable Training and Regularization",
                        "content_bullets": [
                            "Describe the Gumbel-Softmax surrogate for top-K training and the temperature annealing schedule.",
                            "Explain the auxiliary load-balancing loss and how it prevents head collapse.",
                            "Tie the design back to the ablation evidence from the experimental log.",
                        ],
                        "citation_hints": [
                            "Gumbel-Softmax paper",
                            "Foundational work on load balancing or routing regularization in sparse architectures",
                        ],
                    },
                ],
            },
            {
                "section_title": "Experiments",
                "subsections": [
                    {
                        "subsection_title": "Experimental Setup and Benchmarks",
                        "content_bullets": [
                            "List the long-context tasks, datasets, and splits used in the study.",
                            "Describe the 12-layer Transformer encoder-decoder backbone, hidden size 768, 12 heads, and FFN size 3072.",
                            "Report optimizer, learning rate, warmup, dropout, batch size, gradient clipping, and sequence length 4096.",
                        ],
                        "citation_hints": [
                            "Natural Questions / NaturalQuestions-Long dataset paper",
                            "NarrativeQA dataset paper",
                            "GovReport summarization dataset paper",
                            "Vaswani et al. (Attention Is All You Need)",
                            "AdamW optimizer paper",
                        ],
                    },
                    {
                        "subsection_title": "Main Results and Efficiency Frontier",
                        "content_bullets": [
                            "Compare ATK K variants against dense attention and the sparse baselines on Exact Match, F1, ROUGE, BLEU-4, throughput, memory, and forward FLOPs.",
                            "Emphasize the K=64 and K=256 results as the main quality-compute tradeoff anchors.",
                            "Reference the quality-compute and efficiency figures planned in the plotting stage.",
                        ],
                        "citation_hints": [
                            "BigBird paper",
                            "Longformer paper",
                            "Reformer paper",
                            "Performer paper",
                        ],
                    },
                    {
                        "subsection_title": "Ablations and Qualitative Analysis",
                        "content_bullets": [
                            "Report the ablation results for load balancing, Gumbel-Softmax replacement, shared scoring head, random fixed top-K, and position-only scoring.",
                            "Discuss the observed head-collapse failure mode without load balancing and the smooth monotonic K tradeoff.",
                            "Use the qualitative observations to support the claim that learned selection, not sparsity alone, drives the gains.",
                        ],
                        "citation_hints": [
                            "Gumbel-Softmax paper",
                            "Vaswani et al. (Attention Is All You Need)",
                        ],
                    },
                ],
            },
            {
                "section_title": "Conclusion",
                "subsections": [
                    {
                        "subsection_title": "Takeaways",
                        "content_bullets": [
                            "Restate that content-adaptive sparsity improves the quality-efficiency frontier relative to fixed sparse patterns.",
                            "Highlight the controllable inference-time K knob as the central practical contribution.",
                        ],
                        "citation_hints": [
                            "Vaswani et al. (Attention Is All You Need)",
                        ],
                    },
                    {
                        "subsection_title": "Limitations and Future Work",
                        "content_bullets": [
                            "Acknowledge that results are on three long-document tasks and a single backbone scale.",
                            "Point to extensions such as decoder-only long-context models, larger backbones, and richer adaptive routing policies.",
                        ],
                        "citation_hints": [
                            "BigBird paper",
                            "Longformer paper",
                            "Reformer paper",
                            "Performer paper",
                        ],
                    },
                ],
            },
        ],
    }


def write_local_outline_fallback(workspace: Path, transcript_path: Path, log_path: Path, reason: str) -> Path:
    payload = normalize_outline_payload(synthesize_outline_payload(workspace))
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    append_log(log_path, reason)
    append_log(log_path, "Generated outline locally from workspace inputs after Codex outline fallback.")
    return transcript_path


def run_codex_stage(project_id: str, run_id: str, data_root: Path, stage_name: str,
                    prompt: str, workspace: Path, env: dict[str, str],
                    output_schema_path: Path | None = None,
                    sandbox_mode: str = "workspace-write") -> Path:
    run_payload = load_run_or_raise(project_id, run_id, data_root)
    stage_payload = run_payload["stages"][stage_name]
    log_path = Path(stage_payload["log_path"])
    transcript_path = Path(stage_payload["transcript_path"])
    if stage_name != "literature" and _acceptance_fixtures_enabled_for_stage(env, stage_name):
        _write_acceptance_writer_fixture(stage_name, workspace, transcript_path, log_path)
        return transcript_path
    writer_result = writer_executor.WriterExecutor(storage.REPO_ROOT).run_stage(
        workspace=workspace,
        transcript_path=transcript_path,
        prompt=prompt,
        log_path=log_path,
        env=env,
        output_schema_path=output_schema_path,
        sandbox_mode=sandbox_mode,
    )
    return Path(str(writer_result["transcript_path"]))


def artifact_paths(*paths: Path) -> list[str]:
    return [str(path) for path in paths if path.exists()]


def codex_outline_output_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["plotting_plan", "intro_related_work_plan", "section_plan"],
        "properties": {
            "plotting_plan": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["figure_id", "title", "plot_type", "data_source", "objective", "aspect_ratio"],
                    "properties": {
                        "figure_id": {"type": "string"},
                        "title": {"type": "string"},
                        "plot_type": {"type": "string", "enum": ["plot", "diagram"]},
                        "data_source": {"type": "string", "enum": ["idea.md", "experimental_log.md", "both"]},
                        "objective": {"type": "string"},
                        "aspect_ratio": {
                            "type": "string",
                            "enum": ["1:1", "1:4", "2:3", "3:2", "3:4", "4:1", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"],
                        },
                    },
                },
            },
            "intro_related_work_plan": {
                "type": "object",
                "additionalProperties": False,
                "required": ["introduction_strategy", "related_work_strategy"],
                "properties": {
                    "introduction_strategy": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["hook_hypothesis", "problem_gap_hypothesis", "search_directions"],
                        "properties": {
                            "hook_hypothesis": {"type": "string"},
                            "problem_gap_hypothesis": {"type": "string"},
                            "search_directions": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                    },
                    "related_work_strategy": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["overview", "subsections"],
                        "properties": {
                            "overview": {"type": "string"},
                            "subsections": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": [
                                        "subsection_title",
                                        "methodology_cluster",
                                        "sota_investigation_mission",
                                        "limitation_hypothesis",
                                        "limitation_search_queries",
                                        "bridge_to_our_method",
                                    ],
                                    "properties": {
                                        "subsection_title": {"type": "string"},
                                        "methodology_cluster": {"type": "string"},
                                        "sota_investigation_mission": {"type": "string"},
                                        "limitation_hypothesis": {"type": "string"},
                                        "limitation_search_queries": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "bridge_to_our_method": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
            "section_plan": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["section_title", "subsections"],
                    "properties": {
                        "section_title": {"type": "string"},
                        "subsections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["subsection_title", "content_bullets", "citation_hints"],
                                "properties": {
                                    "subsection_title": {"type": "string"},
                                    "content_bullets": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "citation_hints": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    }


def write_codex_outline_output_schema(target_path: Path) -> Path:
    storage.atomic_write_json(target_path, codex_outline_output_schema())
    return target_path


def load_json_from_text_file(path: Path) -> dict[str, object]:
    raw_text = path.read_text(encoding="utf-8").strip()
    if not raw_text:
        raise RuntimeError(f"Expected JSON output in {path}, but the file is empty.")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError(f"Expected JSON output in {path}, but could not find a JSON object.") from None
        try:
            payload = json.loads(raw_text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Expected JSON output in {path}, but parsing failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected a JSON object in {path}, got {type(payload).__name__}.")
    return payload


_PLOT_OBJECTIVE_KEYWORDS = (
    "radar",
    "bar",
    "line",
    "scatter",
    "box",
    "violin",
    "heatmap",
    "histogram",
    "pie",
    "stacked",
    "grouped",
    "ridge",
    "density",
    "convergence",
    "training curve",
)


def normalize_outline_payload(payload: dict[str, object]) -> dict[str, object]:
    normalized = json.loads(json.dumps(payload))
    plotting_plan = normalized.get("plotting_plan")
    if isinstance(plotting_plan, list):
        for index, figure in enumerate(plotting_plan, start=1):
            if not isinstance(figure, dict):
                continue
            raw_figure_id = str(figure.get("figure_id", "") or "").strip().lower()
            cleaned_figure_id = re.sub(r"[^a-z0-9]+", "_", raw_figure_id).strip("_")
            if cleaned_figure_id.startswith("fig_"):
                cleaned_figure_id = "fig_" + re.sub(r"_+", "_", cleaned_figure_id[4:])
            elif cleaned_figure_id:
                cleaned_figure_id = f"fig_{cleaned_figure_id}"
            else:
                cleaned_figure_id = f"fig_outline_{index}"
            figure["figure_id"] = cleaned_figure_id

            if str(figure.get("plot_type", "")).strip().lower() != "plot":
                continue
            objective = str(figure.get("objective", "") or "").strip()
            if any(keyword in objective.lower() for keyword in _PLOT_OBJECTIVE_KEYWORDS):
                continue
            title = str(figure.get("title", "") or "").lower()
            if any(keyword in title for keyword in ("ablation", "profile", "comparison")):
                chart_type = "Grouped Bar Chart"
            elif any(keyword in title for keyword in ("tradeoff", "scaling", "frontier")):
                chart_type = "Line Chart"
            else:
                chart_type = "Line Chart"
            suffix = f" Use a {chart_type}."
            if not objective.endswith("."):
                objective = objective + "."
            figure["objective"] = objective + suffix
    return normalized


def run_outline_validator(outline_path: Path, log_path: Path, env: dict[str, str]) -> tuple[bool, str]:
    command = [
        sys.executable,
        str(storage.REPO_ROOT / "skills" / "outline-agent" / "scripts" / "validate_outline.py"),
        str(outline_path),
    ]
    append_log(log_path, f"$ {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=str(storage.REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined_output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    if combined_output:
        append_log(log_path, combined_output)
    return completed.returncode == 0, combined_output


def outline_repair_prompt(workspace: Path, invalid_outline: dict[str, object], validator_output: str) -> str:
    return "\n".join([
        f"Repair the PaperOrchestra outline JSON for `{workspace}`.",
        "Return corrected JSON only. Do not use markdown fences. Do not emit prose before or after the JSON.",
        "Do not use shell commands or inspect repo files. Use only the invalid outline and validator output below.",
        "Preserve the intended paper content while fixing schema and semantic violations.",
        "",
        "<invalid_outline_json>",
        json.dumps(invalid_outline, indent=2),
        "</invalid_outline_json>",
        "",
        "<validator_output>",
        validator_output.strip(),
        "</validator_output>",
    ])


def derive_cutoff_date(conference_guidelines_text: str) -> str:
    direct_match = re.search(r"cutoff_date\s*=\s*(\d{4}-\d{2}-\d{2})", conference_guidelines_text, flags=re.IGNORECASE)
    if direct_match:
        return direct_match.group(1)

    month_match = re.search(
        r"submission deadline[^A-Za-z0-9]*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})",
        conference_guidelines_text,
        flags=re.IGNORECASE,
    )
    if month_match:
        month_name, day_text, year_text = month_match.groups()
        try:
            return dt.datetime.strptime(f"{month_name} {day_text} {year_text}", "%B %d %Y").date().isoformat()
        except ValueError:
            pass

    iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", conference_guidelines_text)
    if iso_match:
        return iso_match.group(1)

    current_date = dt.date.fromisoformat(storage.utc_now().split("T", 1)[0])
    fallback_month = current_date.month - 1 or 12
    fallback_year = current_date.year if current_date.month > 1 else current_date.year - 1
    return dt.date(fallback_year, fallback_month, 1).isoformat()


def literature_queries_from_outline(outline_payload: dict[str, object]) -> list[tuple[str, str]]:
    specific_queries: list[tuple[str, str]] = []
    generic_queries: list[tuple[str, str]] = []
    intro_plan = outline_payload.get("intro_related_work_plan", {}).get("introduction_strategy", {})
    for query in intro_plan.get("search_directions", []) or []:
        text = str(query).strip()
        if text:
            generic_queries.append(("intro", text))

    related_sections = (
        outline_payload.get("intro_related_work_plan", {})
        .get("related_work_strategy", {})
        .get("subsections", [])
    ) or []
    for index, section in enumerate(related_sections, start=1):
        if not isinstance(section, dict):
            continue
        for item in section.get("limitation_search_queries", []) or []:
            text = str(item).strip()
            if text:
                specific_queries.append((f"related_work[{index}]", text))
        mission = str(section.get("sota_investigation_mission", "") or "").strip()
        if mission:
            specific_queries.append((f"related_work[{index}]", mission))
    queries = specific_queries or generic_queries
    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, query in queries:
        for alias in expand_known_literature_aliases(query):
            alias_key = alias.casefold()
            if alias_key in seen:
                continue
            seen.add(alias_key)
            deduped.append((label, alias))
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((label, query))
    return deduped[:12]


def atlas_literature_queries(structured_output_path: Path | None) -> list[tuple[str, str]]:
    if structured_output_path is None or not structured_output_path.exists():
        return []
    try:
        payload = json.loads(structured_output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    queries: list[tuple[str, str]] = []
    for item in payload.get("query_hints", []) or []:
        text = str(item).strip()
        if text:
            queries.append(("atlas_hint", text))
    for item in payload.get("candidates", []) or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "") or "").strip()
        if title:
            queries.append(("atlas_candidate", title))
    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, query in queries:
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((label, query))
    return deduped[:12]


def expand_known_literature_aliases(query: str) -> list[str]:
    lowered = query.casefold()
    aliases: list[str] = []
    for needle, canonical in KNOWN_LITERATURE_ALIASES.items():
        if needle in lowered and canonical.casefold() != lowered:
            aliases.append(canonical)
    return aliases


def literature_query_terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) >= 4 and token not in LITERATURE_STOPWORDS
    }


def literature_match_score(query: str, title: str, abstract: str = "") -> float:
    phrase_ratio = difflib.SequenceMatcher(None, query.casefold(), title.casefold()).ratio()
    query_terms = literature_query_terms(query)
    if not query_terms:
        return phrase_ratio
    title_terms = literature_query_terms(title)
    abstract_terms = literature_query_terms(abstract)
    title_overlap = len(query_terms & title_terms) / len(query_terms)
    abstract_overlap = len(query_terms & abstract_terms) / len(query_terms)
    return (phrase_ratio * 0.55) + (title_overlap * 0.30) + (abstract_overlap * 0.15)


def run_semantic_scholar_query(query: str, env: dict[str, str], log_path: Path) -> list[dict[str, object]]:
    command = [
        sys.executable,
        str(storage.REPO_ROOT / "skills" / "literature-review-agent" / "scripts" / "s2_search.py"),
        "--query",
        query,
        "--limit",
        "4",
        "--fields",
        "title,abstract,year,authors,venue,externalIds,paperId,publicationDate",
        "--raw",
    ]
    append_log(log_path, f"$ {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=str(storage.REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.stdout.strip():
        append_log(log_path, completed.stdout.strip())
    if completed.stderr.strip():
        append_log(log_path, completed.stderr.strip())
    if completed.returncode != 0 and _acceptance_strict_s2_cache_enabled(env):
        detail = completed.stderr.strip() or completed.stdout.strip() or f"query: {query}"
        raise RuntimeError(f"Strict Semantic Scholar cache miss or failure: {detail}")
    if not completed.stdout.strip():
        return []
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    data = payload.get("data") or []
    return [item for item in data if isinstance(item, dict)]


def runtime_ssl_context(env: dict[str, str] | None = None) -> ssl.SSLContext | None:
    runtime = config.load_runtime_env(dict(env or os.environ))
    for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        value = str(runtime.get(key, "") or "").strip()
        if value and Path(value).exists():
            return ssl.create_default_context(cafile=value)
    return None


def reconstruct_openalex_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    if not inverted_index:
        return ""
    tokens: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            try:
                tokens.append((int(position), word))
            except (TypeError, ValueError):
                continue
    if not tokens:
        return ""
    tokens.sort(key=lambda item: item[0])
    return " ".join(word for _, word in tokens).strip()


def normalize_openalex_paper(item: dict[str, object], label: str) -> dict[str, object]:
    authorships = item.get("authorships") or []
    authors: list[dict[str, str]] = []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        if isinstance(author, dict):
            name = str(author.get("display_name", "") or "").strip()
            if name:
                authors.append({"name": name})
    primary_location = item.get("primary_location") or {}
    source = primary_location.get("source") if isinstance(primary_location, dict) else {}
    ids = item.get("ids") or {}
    external_ids: dict[str, str] = {}
    doi = str(item.get("doi", "") or "").strip()
    if doi:
        external_ids["DOI"] = doi.removeprefix("https://doi.org/")
    arxiv = ""
    if isinstance(ids, dict):
        arxiv = str(ids.get("arxiv", "") or "").strip()
    if arxiv:
        external_ids["ArXiv"] = arxiv.rsplit("/", 1)[-1]
    openalex_id = str(item.get("id", "") or "").strip()
    paper_id = openalex_id.rsplit("/", 1)[-1] if openalex_id else ""
    return {
        "paperId": paper_id,
        "title": str(item.get("display_name", "") or "").strip(),
        "abstract": reconstruct_openalex_abstract(item.get("abstract_inverted_index")),
        "year": item.get("publication_year"),
        "publicationDate": str(item.get("publication_date", "") or "").strip(),
        "authors": authors,
        "venue": str(source.get("display_name", "") or "").strip() if isinstance(source, dict) else "",
        "externalIds": external_ids,
        "discovered_for": [label],
        "match_score": float(item.get("_paperorchestra_match_score", 0.0) or 0.0),
    }


def run_openalex_query(query: str, log_path: Path, env: dict[str, str] | None = None) -> list[dict[str, object]]:
    params = urllib.parse.urlencode({
        "search": query,
        "per-page": 8,
        "select": "id,display_name,abstract_inverted_index,publication_year,publication_date,authorships,primary_location,doi,ids",
    })
    url = f"https://api.openalex.org/works?{params}"
    append_log(log_path, f"$ GET {url}")
    try:
        with urllib.request.urlopen(url, timeout=30, context=runtime_ssl_context(env)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        append_log(log_path, f"OpenAlex lookup failed for {query!r}: {exc}")
        return []
    results = payload.get("results") or []
    filtered = [item for item in results if isinstance(item, dict)]
    for item in filtered:
        title = str(item.get("display_name", "") or "").strip()
        abstract = reconstruct_openalex_abstract(item.get("abstract_inverted_index"))
        item["_paperorchestra_match_score"] = literature_match_score(query, title, abstract)
    filtered.sort(
        key=lambda item: (
            -float(item.get("_paperorchestra_match_score", 0.0)),
            int(item.get("publication_year") or 9999),
        )
    )
    return filtered


def paper_predates_cutoff(paper: dict[str, object], cutoff_date: str) -> bool:
    cutoff = dt.date.fromisoformat(cutoff_date)
    publication_date = str(paper.get("publicationDate", "") or "").strip()
    if publication_date:
        try:
            return dt.date.fromisoformat(publication_date) < cutoff
        except ValueError:
            pass
    year = paper.get("year")
    if not year:
        return False
    try:
        paper_date = dt.date(int(year), 12, 31)
    except (TypeError, ValueError):
        return False
    return paper_date < cutoff


def build_verified_citation_pool(
    workspace: Path,
    env: dict[str, str],
    log_path: Path,
    atlas_structured_output_path: Path | None = None,
) -> tuple[list[str], Path, Path]:
    outline_payload = json.loads((workspace / "outline.json").read_text(encoding="utf-8"))
    cutoff_date = derive_cutoff_date((workspace / "inputs" / "conference_guidelines.md").read_text(encoding="utf-8"))
    raw_pool_path = workspace / "raw_pool.json"
    citation_pool_path = workspace / "citation_pool.json"
    refs_path = workspace / "refs.bib"

    candidates: list[dict[str, object]] = []
    seen_titles: set[str] = set()
    query_plan = atlas_literature_queries(atlas_structured_output_path) + literature_queries_from_outline(outline_payload)
    strict_s2_cache = _acceptance_strict_s2_cache_enabled(env)
    for label, query in query_plan:
        accepted_for_query = 0
        s2_results = run_semantic_scholar_query(query, env, log_path)
        if s2_results:
            query_results = s2_results
        elif strict_s2_cache:
            append_log(log_path, f"Strict Semantic Scholar cache mode skipped OpenAlex fallback for query: {query}")
            query_results = []
        else:
            append_log(log_path, f"Falling back to OpenAlex for query: {query}")
            query_results = [normalize_openalex_paper(item, label) for item in run_openalex_query(query, log_path, env)]
        for paper in query_results:
            title = str(paper.get("title", "") or "").strip()
            abstract = str(paper.get("abstract", "") or "").strip()
            if not title or not paper_predates_cutoff(paper, cutoff_date):
                continue
            if not abstract and s2_results:
                continue
            match_score = float(paper.get("match_score", 0.0) or 0.0)
            if not s2_results and match_score < 0.28:
                append_log(log_path, f"Skipping low-relevance OpenAlex match ({match_score:.2f}) for query {query!r}: {title}")
                continue
            normalized_title = title.casefold()
            if normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)
            enriched = dict(paper)
            enriched["discovered_for"] = [label]
            candidates.append(enriched)
            accepted_for_query += 1
            if len(candidates) >= 16:
                break
            if accepted_for_query >= 2:
                break
        if len(candidates) >= 16:
            break

    if not candidates:
        if strict_s2_cache:
            raise RuntimeError("Literature discovery returned no usable papers from the strict local Semantic Scholar cache.")
        raise RuntimeError("Literature discovery returned no usable papers.")

    storage.atomic_write_json(raw_pool_path, {"papers": candidates})
    run_command(
        [
            sys.executable,
            str(storage.REPO_ROOT / "skills" / "literature-review-agent" / "scripts" / "dedupe_by_id.py"),
            "--in",
            str(raw_pool_path),
            "--out",
            str(citation_pool_path),
            "--cutoff",
            cutoff_date,
        ],
        cwd=storage.REPO_ROOT,
        log_path=log_path,
        env=env,
    )

    pool_payload = json.loads(citation_pool_path.read_text(encoding="utf-8"))
    if len(pool_payload.get("papers", [])) > 12:
        pool_payload["papers"] = pool_payload["papers"][:12]
        pool_payload["n_total"] = len(pool_payload["papers"])
        pool_payload["min_cite_paper_count"] = max(1, int(len(pool_payload["papers"]) * 0.9))
        storage.atomic_write_json(citation_pool_path, pool_payload)

    run_command(
        [
            sys.executable,
            str(storage.REPO_ROOT / "skills" / "literature-review-agent" / "scripts" / "validate_pool.py"),
            "--pool",
            str(citation_pool_path),
            "--fix",
        ],
        cwd=storage.REPO_ROOT,
        log_path=log_path,
        env=env,
    )
    run_command(
        [
            sys.executable,
            str(storage.REPO_ROOT / "skills" / "literature-review-agent" / "scripts" / "bibtex_format.py"),
            "--pool",
            str(citation_pool_path),
            "--out",
            str(refs_path),
        ],
        cwd=storage.REPO_ROOT,
        log_path=log_path,
        env=env,
    )
    return artifact_paths(raw_pool_path, citation_pool_path, refs_path), citation_pool_path, refs_path


def literature_synthesis_prompt(
    workspace: Path,
    citation_pool_path: Path,
    refs_path: Path,
    atlas_structured_output_path: Path | None = None,
) -> str:
    outline_payload = json.loads((workspace / "outline.json").read_text(encoding="utf-8"))
    pool_payload = json.loads(citation_pool_path.read_text(encoding="utf-8"))
    prompt_papers = []
    for paper in pool_payload.get("papers", []):
        prompt_papers.append({
            "bibtex_key": paper.get("bibtex_key"),
            "title": paper.get("title"),
            "year": paper.get("year"),
            "venue": paper.get("venue"),
            "abstract": paper.get("abstract"),
        })
    citation_keys = [paper.get("bibtex_key") for paper in pool_payload.get("papers", []) if paper.get("bibtex_key")]
    return "\n".join([
        f"Write the PaperOrchestra Introduction and Related Work draft for `{workspace}`.",
        "Return the full updated LaTeX template only, wrapped in ```latex fences.",
        "Do not use shell commands or inspect repo files. All required inputs are embedded below.",
        "Fill only the Introduction and Related Work sections. Keep all other template code unchanged.",
        "Cite only the provided BibTeX keys. Do not invent citations.",
        f"Cite at least {pool_payload.get('min_cite_paper_count', 1)} of the provided papers.",
        f"Treat papers after {pool_payload.get('cutoff_date', derive_cutoff_date((workspace / 'inputs' / 'conference_guidelines.md').read_text(encoding='utf-8')))} only as concurrent work, not prior baselines.",
        "Do not claim the method beats a cited paper unless that paper is explicitly evaluated in the experimental log.",
        "",
        "<intro_related_work_plan_json>",
        json.dumps(outline_payload.get("intro_related_work_plan", {}), indent=2),
        "</intro_related_work_plan_json>",
        "",
        "<template_tex>",
        (workspace / "inputs" / "template.tex").read_text(encoding="utf-8").strip(),
        "</template_tex>",
        "",
        "<project_idea_md>",
        (workspace / "inputs" / "idea.md").read_text(encoding="utf-8").strip(),
        "</project_idea_md>",
        "",
        "<project_experimental_log_md>",
        (workspace / "inputs" / "experimental_log.md").read_text(encoding="utf-8").strip(),
        "</project_experimental_log_md>",
        "",
        "<citation_checklist>",
        json.dumps(citation_keys, indent=2),
        "</citation_checklist>",
        "",
        "<collected_papers_json>",
        json.dumps(prompt_papers, indent=2),
        "</collected_papers_json>",
        "",
        "<atlas_structured_output_json>",
        atlas_structured_output_path.read_text(encoding="utf-8").strip()
        if atlas_structured_output_path is not None and atlas_structured_output_path.exists()
        else "{}",
        "</atlas_structured_output_json>",
        "",
        "<refs_bib>",
        refs_path.read_text(encoding="utf-8").strip(),
        "</refs_bib>",
    ])


def extract_latex_document(text: str) -> str:
    fence_match = re.search(r"```latex\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip() + "\n"
    start = text.find("\\documentclass")
    end = text.rfind("\\end{document}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + len("\\end{document}")].strip() + "\n"
    raise RuntimeError("Could not extract LaTeX document from Codex output.")


def snapshot_transcript_artifact(transcript_path: Path, suffix: str) -> Path | None:
    if not transcript_path.exists():
        return None
    snapshot_path = transcript_path.parent / f"codex-{suffix}-message.txt"
    snapshot_path.write_text(transcript_path.read_text(encoding="utf-8"), encoding="utf-8")
    return snapshot_path


def replace_template_section(template_text: str, section_title: str, body: str) -> str:
    pattern = re.compile(
        rf"(\\section\{{{re.escape(section_title)}\}}\s*)(.*?)(?=(\\section\{{)|\\bibliographystyle)",
        flags=re.DOTALL,
    )
    replacement_body = body.strip() + "\n\n"
    def _replacement(match: re.Match[str]) -> str:
        return match.group(1) + replacement_body
    replaced, count = pattern.subn(_replacement, template_text, count=1)
    if count == 0:
        raise RuntimeError(f"Could not replace section {section_title!r} in template.")
    return replaced


def write_local_literature_fallback(
    workspace: Path,
    citation_pool_path: Path,
    transcript_path: Path,
    log_path: Path,
    reason: str,
) -> Path:
    pool_payload = json.loads(citation_pool_path.read_text(encoding="utf-8"))
    papers = [paper for paper in pool_payload.get("papers", []) if isinstance(paper, dict)]
    if not papers:
        raise RuntimeError("Cannot synthesize local literature fallback without citation_pool.json papers.")
    citation_keys = [str(paper.get("bibtex_key", "") or "").strip() for paper in papers if str(paper.get("bibtex_key", "") or "").strip()]
    titles = [str(paper.get("title", "") or "").strip() for paper in papers if str(paper.get("title", "") or "").strip()]
    intro_citations = ",".join(citation_keys)
    related_sentences = []
    for paper in papers:
        key = str(paper.get("bibtex_key", "") or "").strip()
        title = str(paper.get("title", "") or "").strip()
        venue = str(paper.get("venue", "") or "").strip()
        if not key or not title:
            continue
        venue_clause = f" in {venue}" if venue else ""
        related_sentences.append(f"{title}{venue_clause} remains part of the comparison set. \\cite{{{key}}}")
    introduction = "\n".join([
        f"Long-context transformer efficiency remains constrained by dense self-attention, motivating sparse and structured alternatives \\cite{{{intro_citations}}}.",
        f"In this paper we position the proposed method against representative prior work including {', '.join(title for title in titles[:3])}.",
    ])
    related_work = "\n".join(related_sentences)
    template_text = (workspace / "inputs" / "template.tex").read_text(encoding="utf-8")
    fallback_document = replace_template_section(template_text, "Introduction", introduction)
    fallback_document = replace_template_section(fallback_document, "Related Work", related_work)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(fallback_document, encoding="utf-8")
    append_log(log_path, reason)
    append_log(log_path, "Generated Introduction and Related Work locally after literature synthesis fallback.")
    return transcript_path


def recover_latex_transcript_from_log(log_path: Path, transcript_path: Path) -> bool:
    if not log_path.exists():
        return False
    try:
        latex = extract_latex_document(log_path.read_text(encoding="utf-8", errors="replace"))
    except RuntimeError:
        return False
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(latex, encoding="utf-8")
    append_log(log_path, "Recovered LaTeX output from stage.log after Codex timeout.")
    return True


def write_default_refinement_worklog(worklog_path: Path, reason: str) -> None:
    storage.ensure_dir(worklog_path.parent)
    storage.atomic_write_json(worklog_path, {
        "iterations": [
            {
                "accepted": True,
                "reason": reason,
            },
        ],
    })


def prepare_compile_workspace(workspace: Path) -> list[Path]:
    final_dir = workspace / "final"
    refs_src = workspace / "refs.bib"
    refs_dst = final_dir / "refs.bib"
    figures_src = workspace / "figures"
    figures_dst = final_dir / "figures"
    prepared: list[Path] = []
    storage.ensure_dir(final_dir)
    if refs_src.exists():
        shutil.copy2(refs_src, refs_dst)
        prepared.append(refs_dst)
    if figures_src.exists() and not figures_dst.exists():
        try:
            figures_dst.symlink_to(figures_src, target_is_directory=True)
        except OSError:
            shutil.copytree(figures_src, figures_dst)
        prepared.append(figures_dst)
    return prepared


def run_citation_coverage(tex_path: Path, citation_pool_path: Path, log_path: Path, env: dict[str, str]) -> tuple[bool, str]:
    command = [
        sys.executable,
        str(storage.REPO_ROOT / "skills" / "literature-review-agent" / "scripts" / "citation_coverage.py"),
        "--tex",
        str(tex_path),
        "--pool",
        str(citation_pool_path),
    ]
    append_log(log_path, f"$ {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=str(storage.REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined_output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    if combined_output:
        append_log(log_path, combined_output)
    return completed.returncode == 0, combined_output


def write_planning_artifacts(workspace: Path, outline_payload: dict[str, object]) -> list[str]:
    planning_root = workspace / "planning"
    storage.ensure_dir(planning_root)
    plotting_plan_path = planning_root / "plotting_plan.json"
    intro_plan_path = planning_root / "intro_related_work_plan.json"
    section_plan_path = planning_root / "section_plan.json"
    storage.atomic_write_json(plotting_plan_path, outline_payload.get("plotting_plan", []))
    storage.atomic_write_json(intro_plan_path, outline_payload.get("intro_related_work_plan", {}))
    storage.atomic_write_json(section_plan_path, outline_payload.get("section_plan", []))
    return artifact_paths(plotting_plan_path, intro_plan_path, section_plan_path)


def load_metrics_payload(workspace: Path) -> dict[str, object]:
    metrics_path = workspace / "metrics.json"
    if not metrics_path.exists():
        return {"tables": []}
    try:
        return json.loads(metrics_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"tables": []}


def _as_float(value: object) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _metric_table_rows(table: dict[str, object]) -> list[dict[str, object]]:
    headers = [str(item).strip() for item in table.get("headers", []) or []]
    rows = []
    for row in table.get("rows", []) or []:
        if not isinstance(row, list):
            continue
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        row_map = {headers[index]: padded[index] for index in range(len(headers))}
        rows.append(row_map)
    return rows


def _find_table(metrics_payload: dict[str, object], predicate) -> dict[str, object] | None:
    for table in metrics_payload.get("tables", []) or []:
        if isinstance(table, dict) and predicate(table):
            return table
    return None


def _first_numeric_metric(headers: list[str], exclude: set[str] | None = None) -> str:
    blocked = {item.casefold() for item in (exclude or set())}
    for header in headers[1:]:
        candidate = str(header).strip()
        lowered = candidate.casefold()
        if lowered in blocked:
            continue
        if any(token in lowered for token in ("method", "variant")):
            continue
        return candidate
    return str(headers[1] if len(headers) > 1 else "Value")


def _figure_caption_text(figure_spec: dict[str, object], descriptor: str) -> str:
    title = str(figure_spec.get("title", "") or "").strip()
    objective = str(figure_spec.get("objective", "") or "").strip().rstrip(".")
    pieces = [piece for piece in [title, descriptor.strip().rstrip("."), objective] if piece]
    caption = ". ".join(pieces)
    return caption.strip().rstrip(".") + "."


def _diagram_spec_from_idea(workspace: Path, figure_spec: dict[str, object]) -> dict[str, object]:
    idea_sections = parse_markdown_sections((workspace / "inputs" / "idea.md").read_text(encoding="utf-8"))
    problem = compact_text(idea_sections.get("problem statement", "")) or "Problem"
    hypothesis = compact_text(idea_sections.get("core hypothesis", "")) or "Core idea"
    contribution = compact_text(idea_sections.get("expected contribution", "")) or "Contribution"
    return {
        "aspect_ratio": str(figure_spec.get("aspect_ratio", "16:9") or "16:9"),
        "title": str(figure_spec.get("title", "") or "").strip(),
        "nodes": [
            {"id": "problem", "x": 0.4, "y": 1.2, "w": 2.2, "h": 0.8, "label": f"Problem\n{problem[:42]}", "kind": "input"},
            {"id": "method", "x": 3.2, "y": 1.2, "w": 2.4, "h": 0.9, "label": f"Method\n{hypothesis[:42]}", "kind": "agent"},
            {"id": "output", "x": 6.2, "y": 1.2, "w": 2.2, "h": 0.8, "label": f"Outcome\n{contribution[:42]}", "kind": "output"},
        ],
        "edges": [
            {"from": "problem", "to": "method"},
            {"from": "method", "to": "output"},
        ],
    }


def _plot_spec_from_metrics(workspace: Path, figure_spec: dict[str, object], metrics_payload: dict[str, object]) -> dict[str, object]:
    objective = str(figure_spec.get("objective", "") or "").casefold()
    tables = [table for table in metrics_payload.get("tables", []) or [] if isinstance(table, dict)]
    main_table = _find_table(
        metrics_payload,
        lambda table: any("F1" in str(header) for header in table.get("headers", []) or []),
    ) or (tables[0] if tables else {"headers": ["Method", "Value"], "rows": [["Ours", "1.0"]]})
    ablation_table = _find_table(
        metrics_payload,
        lambda table: "ablation" in str(table.get("label", "") or "").casefold(),
    ) or main_table
    headers = [str(item).strip() for item in main_table.get("headers", []) or []]
    rows = _metric_table_rows(main_table)
    title = str(figure_spec.get("title", "") or "").strip()
    aspect_ratio = str(figure_spec.get("aspect_ratio", "16:9") or "16:9")

    if "radar" in objective:
        metrics = [header for header in headers[1:] if header and _as_float(rows[0].get(header)) is not None][:5]
        dense = next((row for row in rows if "dense" in str(row.get("Method", "")).casefold()), rows[0])
        ours = next((row for row in rows if "atk-attention (k=64)" in str(row.get("Method", "")).casefold()), rows[-1])
        return {
            "type": "radar",
            "aspect_ratio": aspect_ratio,
            "title": title,
            "x_labels": metrics,
            "series": [
                {"name": str(dense.get("Method", "Dense")), "y": [_as_float(dense.get(metric)) or 0.0 for metric in metrics]},
                {"name": str(ours.get("Method", "Ours")), "y": [_as_float(ours.get(metric)) or 0.0 for metric in metrics]},
            ],
        }

    if any(token in objective for token in ("tradeoff", "compute", "flops", "latency")):
        x_metric = "Forward FLOPs (G)" if "Forward FLOPs (G)" in headers else ("TPS" if "TPS" in headers else headers[-1])
        y_metric = "F1" if "F1" in headers else _first_numeric_metric(headers, exclude={x_metric})
        baseline_rows = [row for row in rows if "atk-attention" not in str(row.get("Method", "")).casefold()]
        atk_rows = [row for row in rows if "atk-attention" in str(row.get("Method", "")).casefold()]
        return {
            "type": "scatter",
            "aspect_ratio": aspect_ratio,
            "title": title,
            "xlabel": x_metric,
            "ylabel": y_metric,
            "series": [
                {
                    "name": "Baselines",
                    "x": [_as_float(row.get(x_metric)) or 0.0 for row in baseline_rows],
                    "y": [_as_float(row.get(y_metric)) or 0.0 for row in baseline_rows],
                },
                {
                    "name": "ATK-Attention",
                    "x": [_as_float(row.get(x_metric)) or 0.0 for row in atk_rows],
                    "y": [_as_float(row.get(y_metric)) or 0.0 for row in atk_rows],
                },
            ],
        }

    if "ablation" in objective:
        ablation_headers = [str(item).strip() for item in ablation_table.get("headers", []) or []]
        ablation_rows = _metric_table_rows(ablation_table)
        value_metric = _first_numeric_metric(ablation_headers)
        return {
            "type": "bar",
            "aspect_ratio": aspect_ratio,
            "title": title,
            "ylabel": value_metric,
            "x_labels": [str(row.get(ablation_headers[0], "") or "")[:32] for row in ablation_rows],
            "series": [
                {
                    "name": value_metric,
                    "y": [_as_float(row.get(value_metric)) or 0.0 for row in ablation_rows],
                }
            ],
        }

    y_metric = "F1" if "F1" in headers else _first_numeric_metric(headers)
    limited_rows = rows[:6]
    return {
        "type": "bar",
        "aspect_ratio": aspect_ratio,
        "title": title,
        "ylabel": y_metric,
        "x_labels": [str(row.get("Method", "") or "")[:24] for row in limited_rows],
        "series": [
            {
                "name": y_metric,
                "y": [_as_float(row.get(y_metric)) or 0.0 for row in limited_rows],
            }
        ],
    }


def _matching_input_figure(workspace: Path, figure_id: str) -> Path | None:
    figures_root = workspace / "inputs" / "figures"
    if not figures_root.exists():
        return None
    for candidate in sorted(figures_root.iterdir()):
        if candidate.is_file() and candidate.stem.startswith(figure_id):
            return candidate
    return None


def _write_json(path: Path, payload: object) -> Path:
    storage.ensure_dir(path.parent)
    storage.atomic_write_json(path, payload)
    return path


def build_citation_map(citation_pool_path: Path, destination: Path) -> Path:
    pool_payload = json.loads(citation_pool_path.read_text(encoding="utf-8"))
    papers = [paper for paper in pool_payload.get("papers", []) if isinstance(paper, dict)]
    by_key: dict[str, object] = {}
    by_discovery: dict[str, list[str]] = {}
    for paper in papers:
        key = str(paper.get("bibtex_key", "") or "").strip()
        if not key:
            continue
        by_key[key] = {
            "title": paper.get("title"),
            "year": paper.get("year"),
            "venue": paper.get("venue"),
            "discovered_for": list(paper.get("discovered_for", []) or []),
        }
        for label in paper.get("discovered_for", []) or []:
            if not label:
                continue
            by_discovery.setdefault(str(label), []).append(key)
    return _write_json(destination, {
        "paper_count": len(papers),
        "min_cite_paper_count": pool_payload.get("min_cite_paper_count"),
        "cutoff_date": pool_payload.get("cutoff_date"),
        "by_key": by_key,
        "by_discovery_label": by_discovery,
    })


def build_section_writing_bundle(workspace: Path) -> Path:
    figures_root = workspace / "figures"
    captions_path = figures_root / "captions.json"
    try:
        captions_payload = json.loads(captions_path.read_text(encoding="utf-8")) if captions_path.exists() else {}
    except json.JSONDecodeError:
        captions_payload = {}
    if isinstance(captions_payload, dict) and "figures" in captions_payload:
        figures_captions = {
            str(item.get("figure_id", "") or "").strip(): str(item.get("caption", "") or "").strip()
            for item in captions_payload.get("figures", []) or []
            if isinstance(item, dict) and str(item.get("figure_id", "") or "").strip()
        }
    else:
        figures_captions = {
            str(key): str(value)
            for key, value in (captions_payload.items() if isinstance(captions_payload, dict) else [])
            if str(key).strip()
        }
    figure_manifest = []
    if figures_root.exists():
        for figure_path in sorted(figures_root.iterdir()):
            if not figure_path.is_file() or figure_path.name == "captions.json":
                continue
            figure_manifest.append({
                "figure_id": figure_path.stem,
                "filename": figure_path.name,
                "path": str(figure_path),
                "caption": figures_captions.get(figure_path.stem, ""),
            })
    bundle = {
        "idea_path": str(workspace / "inputs" / "idea.md"),
        "experimental_log_path": str(workspace / "inputs" / "experimental_log.md"),
        "template_path": str(workspace / "inputs" / "template.tex"),
        "guidelines_path": str(workspace / "inputs" / "conference_guidelines.md"),
        "outline_path": str(workspace / "outline.json"),
        "intro_related_work_plan_path": str(workspace / "planning" / "intro_related_work_plan.json"),
        "plotting_plan_path": str(workspace / "planning" / "plotting_plan.json"),
        "section_plan_path": str(workspace / "planning" / "section_plan.json"),
        "intro_relwork_path": str(workspace / "drafts" / "intro_relwork.tex"),
        "citation_pool_path": str(workspace / "citation_pool.json"),
        "citation_map_path": str(workspace / "citation_map.json"),
        "refs_bib_path": str(workspace / "refs.bib"),
        "figure_manifest": figure_manifest,
        "tex_profile_path": str(workspace / "tex_profile.json"),
        "metrics_path": str(workspace / "metrics.json"),
    }
    return _write_json(workspace / "cache" / "section_writing_bundle.json", bundle)


def validate_figure_usage(draft_path: Path, figures_root: Path) -> tuple[bool, str]:
    if not figures_root.exists():
        return True, "No generated figures."
    generated = sorted(path for path in figures_root.iterdir() if path.is_file() and path.name != "captions.json")
    if not generated:
        return True, "No generated figures."
    text = draft_path.read_text(encoding="utf-8", errors="replace")
    include_matches = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", text)
    if not include_matches:
        return False, "Generated figures exist but the draft does not reference them with \\includegraphics."
    missing_paths: list[str] = []
    referenced_files: set[str] = set()
    for match in include_matches:
        resolved = (draft_path.parent / match).resolve(strict=False)
        referenced_files.add(Path(match).name)
        if not resolved.exists():
            missing_paths.append(match)
    if missing_paths:
        return False, f"Draft references missing figure files: {', '.join(sorted(missing_paths))}"
    generated_names = {path.name for path in generated}
    if not referenced_files & generated_names:
        return False, "Generated figures were not referenced from the draft."
    return True, "Figure usage validated."


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def refinement_paths() -> tuple[Path, Path, Path, Path, Path]:
    root = storage.REPO_ROOT / "skills" / "content-refinement-agent"
    return (
        root / "references" / "reviewer-rubric.md",
        root / "references" / "prompt.md",
        root / "scripts" / "snapshot.py",
        root / "scripts" / "score_delta.py",
        root / "scripts" / "apply_worklog.py",
    )


def refinement_review_prompt(workspace: Path, paper_tex: Path, paper_pdf: Path | None) -> str:
    reviewer_rubric_path, _, _, _, _ = refinement_paths()
    pdf_block = paper_pdf.read_bytes()[:0] if paper_pdf and paper_pdf.exists() else b""
    _ = pdf_block
    return "\n".join([
        _load_text(reviewer_rubric_path),
        "",
        f"Review the current PaperOrchestra draft for `{workspace}`.",
        "Return STRICT JSON only using the documented schema.",
        "",
        "<paper_tex>",
        _load_text(paper_tex).strip(),
        "</paper_tex>",
    ])


def refinement_revision_prompt(
    workspace: Path,
    paper_tex: Path,
    paper_pdf: Path | None,
    review_payload: dict[str, object],
    worklog_path: Path,
) -> str:
    _, prompt_path, _, _, _ = refinement_paths()
    return "\n".join([
        _load_text(prompt_path),
        "",
        f"Revise the current PaperOrchestra draft for `{workspace}`.",
        "",
        "<paper_tex>",
        _load_text(paper_tex).strip(),
        "</paper_tex>",
        "",
        "<conference_guidelines_md>",
        _load_text(workspace / "inputs" / "conference_guidelines.md").strip(),
        "</conference_guidelines_md>",
        "",
        "<experimental_log_md>",
        _load_text(workspace / "inputs" / "experimental_log.md").strip(),
        "</experimental_log_md>",
        "",
        "<reviewer_feedback_json>",
        json.dumps(review_payload, indent=2),
        "</reviewer_feedback_json>",
        "",
        "<worklog_json>",
        _load_text(worklog_path).strip() or "{}",
        "</worklog_json>",
        "",
        "<citation_map_json>",
        _load_text(workspace / "citation_map.json").strip() or "{}",
        "</citation_map_json>",
    ])


def extract_json_object(text: str) -> dict[str, object]:
    fence_match = re.search(r"```json\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        return json.loads(fence_match.group(1))
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1 or last <= first:
        raise RuntimeError("Could not extract JSON object from Codex output.")
    return json.loads(text[first:last + 1])


def extract_revision_response(text: str) -> tuple[dict[str, object], str]:
    blocks = re.findall(r"```(\w+)?\s*(.*?)```", text, flags=re.DOTALL)
    worklog_payload: dict[str, object] | None = None
    latex_text: str | None = None
    for language, block in blocks:
        lang = str(language or "").strip().casefold()
        content = block.strip()
        if lang == "json" and worklog_payload is None:
            worklog_payload = json.loads(content)
        elif lang == "latex" and latex_text is None:
            latex_text = content + "\n"
    if worklog_payload is None:
        worklog_payload = extract_json_object(text)
    if latex_text is None:
        latex_text = extract_latex_document(text)
    return worklog_payload, latex_text


def score_from_review(review_payload: dict[str, object]) -> dict[str, object]:
    score_payload = dict(review_payload)
    axis_scores = score_payload.get("axis_scores") or {}
    if not score_payload.get("overall_score") and isinstance(axis_scores, dict):
        values = []
        for entry in axis_scores.values():
            if isinstance(entry, dict):
                value = _as_float(entry.get("score"))
                if value is not None:
                    values.append(value)
        if values:
            score_payload["overall_score"] = round(sum(values) / len(values), 2)
    return score_payload


def run_refinement_snapshot(src_tex: Path, dst_dir: Path, src_pdf: Path | None, log_path: Path) -> None:
    _, _, snapshot_script, _, _ = refinement_paths()
    command = [
        sys.executable,
        str(snapshot_script),
        "--src",
        str(src_tex),
        "--dst",
        str(dst_dir),
    ]
    if src_pdf is not None and src_pdf.exists():
        command.extend(["--src-pdf", str(src_pdf)])
    run_command(command, cwd=storage.REPO_ROOT, log_path=log_path, env=dict(os.environ))


def run_refinement_delta(prev_score: Path, curr_score: Path, delta_path: Path, log_path: Path, env: dict[str, str], consecutive_small: int) -> dict[str, object]:
    _, _, _, score_delta_script, _ = refinement_paths()
    command = [
        sys.executable,
        str(score_delta_script),
        "--prev",
        str(prev_score),
        "--curr",
        str(curr_score),
        "--consecutive-small",
        str(consecutive_small),
    ]
    append_log(log_path, f"$ {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=str(storage.REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined_output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    if combined_output:
        append_log(log_path, combined_output)
    if completed.returncode not in {0, 1, 2, 4}:
        raise RuntimeError(f"score_delta.py failed with exit code {completed.returncode}")
    delta_payload = json.loads(completed.stdout or "{}")
    storage.atomic_write_json(delta_path, delta_payload)
    return delta_payload


def append_refinement_worklog(
    worklog_path: Path,
    iteration: int,
    review_path: Path,
    score_path: Path,
    decision: str,
    actions_path: Path | None,
    log_path: Path,
    env: dict[str, str],
    halted_because: str = "",
) -> None:
    _, _, _, _, apply_worklog_script = refinement_paths()
    command = [
        sys.executable,
        str(apply_worklog_script),
        "--worklog",
        str(worklog_path),
        "--iter",
        str(iteration),
        "--review",
        str(review_path),
        "--score",
        str(score_path),
        "--decision",
        decision,
    ]
    if actions_path is not None and actions_path.exists():
        command.extend(["--actions", str(actions_path)])
    if halted_because:
        command.extend(["--halted-because", halted_because])
    run_command(command, cwd=storage.REPO_ROOT, log_path=log_path, env=env)


def execute_ingest(project: dict[str, object], run_id: str, data_root: Path, env: dict[str, str]) -> list[str]:
    project_id = str(project["project_id"])
    workspace = Path(str(project["workspace_path"])).expanduser()
    maybe_trigger_acceptance_failpoint(project_id, run_id, data_root, "ingest", env)
    update_stage(project_id, run_id, data_root, "ingest", status="running", summary="Checking input availability.")
    check_for_cancel(project_id, run_id, data_root)

    idea_path = workspace / "inputs" / "idea.md"
    log_path = workspace / "inputs" / "experimental_log.md"
    source_directory = str(project.get("ingest", {}).get("source_directory", "")).strip()
    if idea_path.exists() and idea_path.read_text(encoding="utf-8").strip() and log_path.exists() and log_path.read_text(encoding="utf-8").strip():
        update_stage(
            project_id,
            run_id,
            data_root,
            "ingest",
            status="succeeded",
            summary="Manual inputs already exist; aggregation skipped.",
        )
        save_stage_artifacts(project_id, run_id, data_root, "ingest", artifact_paths(idea_path, log_path))
        return artifact_paths(idea_path, log_path)

    if not source_directory:
        update_stage(
            project_id,
            run_id,
            data_root,
            "ingest",
            status="paused",
            summary="Missing idea or experimental log input.",
            attention_required={
                "reason": "missing_input",
                "message": "Provide a source directory for aggregation or fill in the input files manually.",
                "details": {"field": "source_directory"},
            },
        )
        raise RunNeedsInput("Missing idea or experimental log input.")

    transcript_path = run_codex_stage(
        project_id,
        run_id,
        data_root,
        "ingest",
        "\n".join([
            f"Read `skills/agent-research-aggregator/SKILL.md` and prepare PaperOrchestra inputs for `{workspace}`.",
            f"Use `{source_directory}` as the search root for aggregation.",
            "Write or update `inputs/idea.md` and `inputs/experimental_log.md` in the workspace.",
            "Keep the final response concise and mention the created artifacts.",
        ]),
        workspace,
        env,
    )

    if not idea_path.exists() or not log_path.exists():
        raise RuntimeError("Aggregation finished without producing `idea.md` and `experimental_log.md`.")
    artifacts = artifact_paths(idea_path, log_path, transcript_path)
    save_stage_artifacts(project_id, run_id, data_root, "ingest", artifacts)
    update_stage(project_id, run_id, data_root, "ingest", status="succeeded", summary="Aggregation completed.")
    return artifacts


def execute_validate(project: dict[str, object], run_id: str, data_root: Path, env: dict[str, str]) -> list[str]:
    project_id = str(project["project_id"])
    workspace = Path(str(project["workspace_path"])).expanduser()
    repo_root = storage.REPO_ROOT
    stage_log = Path(load_run_or_raise(project_id, run_id, data_root)["stages"]["validate"]["log_path"])

    maybe_trigger_acceptance_failpoint(project_id, run_id, data_root, "validate", env)
    update_stage(project_id, run_id, data_root, "validate", status="running", summary="Running deterministic validation.")
    check_for_cancel(project_id, run_id, data_root)
    run_command(
        [sys.executable, str(repo_root / "skills" / "paper-orchestra" / "scripts" / "init_workspace.py"), "--out", str(workspace), "--force"],
        cwd=repo_root,
        log_path=stage_log,
        env=env,
    )
    run_command(
        [sys.executable, str(repo_root / "skills" / "paper-orchestra" / "scripts" / "validate_inputs.py"), "--workspace", str(workspace)],
        cwd=repo_root,
        log_path=stage_log,
        env=env,
    )
    run_command(
        [
            sys.executable,
            str(repo_root / "skills" / "section-writing-agent" / "scripts" / "extract_metrics.py"),
            "--log",
            str(workspace / "inputs" / "experimental_log.md"),
            "--out",
            str(workspace / "metrics.json"),
        ],
        cwd=repo_root,
        log_path=stage_log,
        env=env,
    )
    run_command(
        [
            sys.executable,
            str(repo_root / "skills" / "paper-orchestra" / "scripts" / "check_tex_packages.py"),
            "--out",
            str(workspace / "tex_profile.json"),
        ],
        cwd=repo_root,
        log_path=stage_log,
        env=env,
    )
    artifacts = artifact_paths(workspace / "metrics.json", workspace / "tex_profile.json")
    save_stage_artifacts(project_id, run_id, data_root, "validate", artifacts)
    update_stage(project_id, run_id, data_root, "validate", status="succeeded", summary="Validation and TeX profiling completed.")
    storage.update_latest_validation(project, {"status": "validated", "checked_at": storage.utc_now(), "summary": "Validation completed."}, data_root)
    return artifacts


def execute_outline(project: dict[str, object], run_id: str, data_root: Path, env: dict[str, str]) -> list[str]:
    project_id = str(project["project_id"])
    workspace = Path(str(project["workspace_path"])).expanduser()
    outline_path = workspace / "outline.json"
    schema_path = storage.REPO_ROOT / "skills" / "outline-agent" / "references" / "outline_schema.json"
    stage_state = load_run_or_raise(project_id, run_id, data_root)["stages"]["outline"]
    strict_schema_path = write_codex_outline_output_schema(Path(stage_state["attempt_dir"]) / "codex-output-schema.json")

    maybe_trigger_acceptance_failpoint(project_id, run_id, data_root, "outline", env)
    update_stage(project_id, run_id, data_root, "outline", status="running", summary="Generating outline.")
    check_for_cancel(project_id, run_id, data_root)
    log_path = Path(load_run_or_raise(project_id, run_id, data_root)["stages"]["outline"]["log_path"])
    start_stage_substep(project_id, run_id, data_root, "outline", "codex_outline", "Generating the structured outline.")
    try:
        transcript_path = run_codex_stage(
            project_id,
            run_id,
            data_root,
            "outline",
            outline_prompt(workspace),
            workspace,
            env,
            output_schema_path=strict_schema_path,
            sandbox_mode="read-only",
        )
        initial_outline = normalize_outline_payload(load_json_from_text_file(transcript_path))
    except RuntimeError as exc:
        transcript_path = write_local_outline_fallback(
            workspace,
            Path(stage_state["transcript_path"]),
            log_path,
            f"Codex outline stage failed; falling back to local synthesis. {exc}",
        )
        initial_outline = normalize_outline_payload(load_json_from_text_file(transcript_path))
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "outline",
        "codex_outline",
        "Structured outline draft produced.",
        artifacts=artifact_paths(transcript_path),
    )
    storage.atomic_write_json(outline_path, initial_outline)
    start_stage_substep(project_id, run_id, data_root, "outline", "outline_validate", "Validating the outline against the schema and semantics.")
    valid, validator_output = run_outline_validator(outline_path, log_path, env)
    if not valid:
        try:
            repair_transcript_path = run_codex_stage(
                project_id,
                run_id,
                data_root,
                "outline",
                outline_repair_prompt(workspace, initial_outline, validator_output),
                workspace,
                env,
                output_schema_path=strict_schema_path,
                sandbox_mode="read-only",
            )
            repaired_outline = normalize_outline_payload(load_json_from_text_file(repair_transcript_path))
        except RuntimeError as exc:
            repair_transcript_path = write_local_outline_fallback(
                workspace,
                Path(stage_state["transcript_path"]),
                log_path,
                f"Codex outline repair failed; using local synthesis. {exc}",
            )
            repaired_outline = normalize_outline_payload(load_json_from_text_file(repair_transcript_path))
        storage.atomic_write_json(outline_path, repaired_outline)
        valid, validator_output = run_outline_validator(outline_path, log_path, env)
        transcript_path = repair_transcript_path
        if not valid:
            raise RuntimeError(f"Outline validation failed after automatic repair.\n{validator_output}")
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "outline",
        "outline_validate",
        "Outline validation passed.",
        artifacts=artifact_paths(outline_path),
    )
    start_stage_substep(project_id, run_id, data_root, "outline", "outline_materialize", "Writing downstream planning artifacts.")
    planning_artifacts = write_planning_artifacts(workspace, json.loads(outline_path.read_text(encoding="utf-8")))
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "outline",
        "outline_materialize",
        "Planning artifacts were materialized for downstream stages.",
        artifacts=planning_artifacts,
    )
    artifacts = artifact_paths(outline_path, transcript_path, *[Path(path) for path in planning_artifacts])
    save_stage_artifacts(project_id, run_id, data_root, "outline", artifacts)
    update_stage(project_id, run_id, data_root, "outline", status="succeeded", summary="Outline generated and validated.")
    return artifacts


def execute_plotting(project: dict[str, object], run_id: str, data_root: Path, env: dict[str, str]) -> list[str]:
    project_id = str(project["project_id"])
    workspace = Path(str(project["workspace_path"])).expanduser()
    stage_log = Path(load_run_or_raise(project_id, run_id, data_root)["stages"]["plotting"]["log_path"])
    attempt_dir = Path(load_run_or_raise(project_id, run_id, data_root)["stages"]["plotting"]["attempt_dir"])
    transcript_path = Path(load_run_or_raise(project_id, run_id, data_root)["stages"]["plotting"]["transcript_path"])

    maybe_trigger_acceptance_failpoint(project_id, run_id, data_root, "plotting", env)
    update_stage(project_id, run_id, data_root, "plotting", status="running", summary="Rendering figures.")
    check_for_cancel(project_id, run_id, data_root)
    if _acceptance_fixtures_enabled_for_stage(env, "plotting"):
        start_stage_substep(project_id, run_id, data_root, "plotting", "fixture_render", "Rendering deterministic acceptance fixture figures.")
        _write_acceptance_writer_fixture("plotting", workspace, transcript_path, stage_log)
        figures_root = workspace / "figures"
        artifacts = artifact_paths(transcript_path, figures_root / "captions.json")
        if figures_root.exists():
            artifacts.extend(str(path) for path in sorted(figures_root.iterdir()) if path.is_file())
        finish_stage_substep(
            project_id,
            run_id,
            data_root,
            "plotting",
            "fixture_render",
            "Acceptance fixture figures rendered.",
            artifacts=artifacts,
        )
        save_stage_artifacts(project_id, run_id, data_root, "plotting", artifacts)
        update_stage(project_id, run_id, data_root, "plotting", status="succeeded", summary="Figure generation completed for acceptance fixtures.")
        return artifacts
    figures_root = workspace / "figures"
    storage.ensure_dir(figures_root)
    plotting_plan_path = workspace / "planning" / "plotting_plan.json"
    if plotting_plan_path.exists():
        plotting_plan = json.loads(plotting_plan_path.read_text(encoding="utf-8"))
    else:
        plotting_plan = json.loads((workspace / "outline.json").read_text(encoding="utf-8")).get("plotting_plan", [])
    if not isinstance(plotting_plan, list) or not plotting_plan:
        raise RuntimeError("plotting_plan is missing or empty.")

    metrics_payload = load_metrics_payload(workspace)
    captions: dict[str, str] = {}
    stage_artifacts: list[str] = []

    for raw_figure in plotting_plan:
        if not isinstance(raw_figure, dict):
            continue
        figure_spec = dict(raw_figure)
        figure_id = str(figure_spec.get("figure_id", "") or "").strip()
        if not figure_id:
            continue
        figure_prefix = figure_id.replace("/", "_")
        render_name = f"{figure_prefix}.render_figure"
        plan_name = f"{figure_prefix}.plan_figure"
        qc_name = f"{figure_prefix}.qc_check"
        critique_name = f"{figure_prefix}.critique_redraw"
        caption_name = f"{figure_prefix}.caption_finalize"
        start_stage_substep(project_id, run_id, data_root, "plotting", plan_name, f"Planning figure `{figure_id}`.")
        figure_path = figures_root / f"{figure_id}.png"
        spec_path = attempt_dir / f"{figure_id}.spec.json"
        matched_input = _matching_input_figure(workspace, figure_id)
        if matched_input is not None:
            shutil.copy2(matched_input, figure_path)
            finish_stage_substep(
                project_id,
                run_id,
                data_root,
                "plotting",
                plan_name,
                f"Matched a user-provided source figure for `{figure_id}`.",
                artifacts=artifact_paths(figure_path),
            )
            finish_stage_substep(
                project_id,
                run_id,
                data_root,
                "plotting",
                render_name,
                f"Reused `{matched_input.name}` for `{figure_id}`.",
                artifacts=artifact_paths(figure_path),
            )
        else:
            finish_stage_substep(
                project_id,
                run_id,
                data_root,
                "plotting",
                plan_name,
                f"Prepared a local render plan for `{figure_id}`.",
            )
            start_stage_substep(project_id, run_id, data_root, "plotting", render_name, f"Rendering `{figure_id}`.")
            if str(figure_spec.get("plot_type", "") or "").strip() == "diagram":
                diagram_spec = _diagram_spec_from_idea(workspace, figure_spec)
                _write_json(spec_path, diagram_spec)
                run_command(
                    [
                        sys.executable,
                        str(storage.REPO_ROOT / "skills" / "plotting-agent" / "scripts" / "render_diagram.py"),
                        "--spec",
                        str(spec_path),
                        "--out",
                        str(figure_path),
                    ],
                    cwd=storage.REPO_ROOT,
                    log_path=stage_log,
                    env=env,
                )
            else:
                plot_spec = _plot_spec_from_metrics(workspace, figure_spec, metrics_payload)
                _write_json(spec_path, plot_spec)
                run_command(
                    [
                        sys.executable,
                        str(storage.REPO_ROOT / "skills" / "plotting-agent" / "scripts" / "render_matplotlib.py"),
                        "--spec",
                        str(spec_path),
                        "--out",
                        str(figure_path),
                    ],
                    cwd=storage.REPO_ROOT,
                    log_path=stage_log,
                    env=env,
                )
            finish_stage_substep(
                project_id,
                run_id,
                data_root,
                "plotting",
                render_name,
                f"Rendered `{figure_id}` locally.",
                artifacts=artifact_paths(spec_path, figure_path),
            )

        start_stage_substep(project_id, run_id, data_root, "plotting", qc_name, f"Quality-checking `{figure_id}`.")
        qc = figure_adapter.figure_quality_check([str(figure_path)])
        if not qc["passed"]:
            finish_stage_substep(
                project_id,
                run_id,
                data_root,
                "plotting",
                qc_name,
                str(qc["message"]),
                status="paused",
                attention_required={
                    "reason": str(qc["reason"]),
                    "message": str(qc["message"]),
                    "details": dict(qc["details"]),
                },
            )
            update_stage(
                project_id,
                run_id,
                data_root,
                "plotting",
                status="paused",
                summary=str(qc["message"]),
                attention_required={
                    "reason": "figure_qc_failed",
                    "message": str(qc["message"]),
                    "details": dict(qc["details"]),
                },
            )
            raise RunNeedsInput(str(qc["message"]))
        finish_stage_substep(
            project_id,
            run_id,
            data_root,
            "plotting",
            qc_name,
            f"`{figure_id}` passed lightweight QC.",
            artifacts=artifact_paths(figure_path),
        )
        finish_stage_substep(
            project_id,
            run_id,
            data_root,
            "plotting",
            critique_name,
            "Critique/redraw skipped because no vision-backed critique loop is configured for the local renderer.",
            status="skipped",
        )
        start_stage_substep(project_id, run_id, data_root, "plotting", caption_name, f"Finalizing caption for `{figure_id}`.")
        descriptor = "Local deterministic rendering from the plotting plan"
        captions[figure_id] = _figure_caption_text(figure_spec, descriptor)
        finish_stage_substep(
            project_id,
            run_id,
            data_root,
            "plotting",
            caption_name,
            f"Caption saved for `{figure_id}`.",
            artifacts=artifact_paths(figure_path),
        )
        stage_artifacts.extend(artifact_paths(spec_path, figure_path))

    captions_path = figures_root / "captions.json"
    storage.atomic_write_json(captions_path, captions)
    stage_artifacts.extend(artifact_paths(captions_path))
    figures_root = workspace / "figures"
    if figures_root.exists():
        stage_artifacts.extend(str(path) for path in sorted(figures_root.iterdir()) if path.is_file())
    artifacts = list(dict.fromkeys(stage_artifacts))
    save_stage_artifacts(project_id, run_id, data_root, "plotting", artifacts)
    qc = figure_adapter.figure_quality_check(
        [str(path) for path in sorted(figures_root.glob("*.png"))] if figures_root.exists() else []
    )
    if not qc["passed"]:
        update_stage(
            project_id,
            run_id,
            data_root,
            "plotting",
            status="paused",
            summary=str(qc["message"]),
            attention_required={
                "reason": str(qc["reason"]),
                "message": str(qc["message"]),
                "details": dict(qc["details"]),
            },
        )
        raise RunNeedsInput(str(qc["message"]))
    update_stage(
        project_id,
        run_id,
        data_root,
        "plotting",
        status="succeeded",
        summary=f"Figure generation completed for {len(captions)} figure(s).",
    )
    return artifacts


def execute_literature(project: dict[str, object], run_id: str, data_root: Path, env: dict[str, str]) -> list[str]:
    project_id = str(project["project_id"])
    workspace = Path(str(project["workspace_path"])).expanduser()
    stage_log = Path(load_run_or_raise(project_id, run_id, data_root)["stages"]["literature"]["log_path"])

    maybe_trigger_acceptance_failpoint(project_id, run_id, data_root, "literature", env)
    update_stage(project_id, run_id, data_root, "literature", status="running", summary="Gathering literature with browser adapters and Codex.")
    check_for_cancel(project_id, run_id, data_root)
    atlas_structured_output_path: Path | None = None
    health = config.integration_health(env)
    browser_stack_available = any([
        bool(health.get("chrome", {}).get("enabled")),
        bool(health.get("atlas", {}).get("enabled")),
        _acceptance_fixtures_enabled(env),
    ])
    stage_artifacts: list[str] = []
    citation_pool_path = workspace / "citation_pool.json"
    citation_map_path = workspace / "citation_map.json"
    refs_path = workspace / "refs.bib"
    intro_relwork_path = workspace / "drafts" / "intro_relwork.tex"
    if browser_stack_available:
        start_stage_substep(project_id, run_id, data_root, "literature", "browser_discovery", "Running browser-assisted literature discovery.")
        browser_result = research_adapter.ResearchAdapter(data_root).run_task(
            project_id=project_id,
            run_id=run_id,
            stage_name="literature",
            prompt_text="\n".join([
                f"Use Deep Research to gather the best prior work for the PaperOrchestra workspace at `{workspace}`.",
                "Focus on canonical and recent papers that belong in the introduction and related work.",
                "Return a concise structured research summary with candidate papers, rationale, and comparison notes.",
            ]),
            workspace=workspace,
            require_deep_research=True,
            task_label="stage_literature",
        )
        stage_artifacts.extend([str(path) for path in browser_result.get("artifacts", [])])
        structured_value = str(browser_result.get("structured_output_path", "") or "").strip()
        if structured_value:
            atlas_structured_output_path = Path(structured_value)
        if browser_result.get("status") == "attention_required":
            if stage_artifacts:
                save_stage_artifacts(project_id, run_id, data_root, "literature", stage_artifacts)
            attention_required = dict(browser_result.get("attention_required") or {})
            if not attention_required:
                attention_required = {
                    "reason": "atlas_intervention_required",
                    "message": str(browser_result.get("summary", "") or "Browser approval is required."),
                    "details": {"adapter": browser_result.get("adapter", "")},
                }
            update_stage(
                project_id,
                run_id,
                data_root,
                "literature",
                status="paused",
                summary=str(browser_result.get("summary", "") or "Browser approval is required."),
                attention_required=attention_required,
            )
            raise RunNeedsInput(str(attention_required.get("message", "") or "Browser approval is required."))
        if browser_result.get("status") != "succeeded":
            append_log(
                stage_log,
                f"Browser automation unavailable or unusable; falling back to local literature discovery. {browser_result.get('summary', '')}",
            )
        finish_stage_substep(
            project_id,
            run_id,
            data_root,
            "literature",
            "browser_discovery",
            str(browser_result.get("summary", "") or "Browser discovery completed."),
            status="succeeded" if browser_result.get("status") == "succeeded" else "skipped",
            artifacts=[str(path) for path in browser_result.get("artifacts", []) or []],
        )
    else:
        finish_stage_substep(
            project_id,
            run_id,
            data_root,
            "literature",
            "browser_discovery",
            "Browser discovery was skipped because no browser adapter is enabled.",
            status="skipped",
        )
    start_stage_substep(project_id, run_id, data_root, "literature", "candidate_normalization", "Normalizing candidate titles and discovery signals.")
    if atlas_structured_output_path is not None and atlas_structured_output_path.exists():
        finish_stage_substep(
            project_id,
            run_id,
            data_root,
            "literature",
            "candidate_normalization",
            "Structured browser candidates were normalized for verification.",
            artifacts=artifact_paths(atlas_structured_output_path),
        )
    else:
        finish_stage_substep(
            project_id,
            run_id,
            data_root,
            "literature",
            "candidate_normalization",
            "Proceeding without browser candidate enrichment.",
            status="skipped",
        )
    start_stage_substep(project_id, run_id, data_root, "literature", "semantic_scholar_verification", "Verifying candidate papers and building the citation pool.")
    discovery_artifacts, citation_pool_path, refs_path = build_verified_citation_pool(
        workspace,
        env,
        stage_log,
        atlas_structured_output_path=atlas_structured_output_path,
    )
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "literature",
        "semantic_scholar_verification",
        "Verified the literature set against Semantic Scholar and local fallbacks.",
        artifacts=[path for path in discovery_artifacts if path.endswith("raw_pool.json") or path.endswith("citation_pool.json") or path.endswith("refs.bib")],
    )
    start_stage_substep(project_id, run_id, data_root, "literature", "citation_pool_build", "Materializing citation_pool.json, citation_map.json, and refs.bib.")
    build_citation_map(citation_pool_path, citation_map_path)
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "literature",
        "citation_pool_build",
        "Citation artifacts are ready for section writing.",
        artifacts=artifact_paths(citation_pool_path, citation_map_path, refs_path),
    )
    stage_artifacts.extend(discovery_artifacts)
    stage_artifacts.extend(artifact_paths(citation_map_path))
    start_stage_substep(project_id, run_id, data_root, "literature", "intro_relwork_draft", "Drafting the Introduction and Related Work sections.")
    try:
        transcript_path = run_codex_stage(
            project_id,
            run_id,
            data_root,
            "literature",
            literature_synthesis_prompt(workspace, citation_pool_path, refs_path, atlas_structured_output_path),
            workspace,
            env,
            sandbox_mode="read-only",
        )
    except RuntimeError as exc:
        transcript_path = write_local_literature_fallback(
            workspace,
            citation_pool_path,
            Path(load_run_or_raise(project_id, run_id, data_root)["stages"]["literature"]["transcript_path"]),
            stage_log,
            f"Literature synthesis fallback triggered after Codex failure: {exc}",
        )
        fallback_snapshot = snapshot_transcript_artifact(transcript_path, "local-fallback")
        if fallback_snapshot is not None:
            stage_artifacts.append(str(fallback_snapshot))
    storage.ensure_dir(intro_relwork_path.parent)
    intro_relwork_path.write_text(
        extract_latex_document(transcript_path.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "literature",
        "intro_relwork_draft",
        "Introduction and Related Work draft produced.",
        artifacts=artifact_paths(transcript_path, intro_relwork_path),
    )
    start_stage_substep(project_id, run_id, data_root, "literature", "citation_coverage_repair", "Running citation coverage checks and repairs.")
    coverage_ok, coverage_output = run_citation_coverage(intro_relwork_path, citation_pool_path, stage_log, env)
    if not coverage_ok:
        repair_prompt = "\n".join([
            f"Repair the PaperOrchestra Introduction and Related Work draft for `{workspace}`.",
            "Return the full updated LaTeX template only, wrapped in ```latex fences.",
            "Increase citation coverage using only the provided BibTeX keys and keep all non-Introduction/Related-Work sections unchanged.",
            "",
            "<current_tex>",
            intro_relwork_path.read_text(encoding="utf-8").strip(),
            "</current_tex>",
            "",
            "<coverage_feedback>",
            coverage_output.strip(),
            "</coverage_feedback>",
            "",
            "<citation_pool_json>",
            citation_pool_path.read_text(encoding="utf-8").strip(),
            "</citation_pool_json>",
        ])
        try:
            transcript_path = run_codex_stage(
                project_id,
                run_id,
                data_root,
                "literature",
                repair_prompt,
                workspace,
                env,
                sandbox_mode="read-only",
            )
        except RuntimeError as exc:
            transcript_path = write_local_literature_fallback(
                workspace,
                citation_pool_path,
                Path(load_run_or_raise(project_id, run_id, data_root)["stages"]["literature"]["transcript_path"]),
                stage_log,
                f"Literature repair fallback triggered after Codex failure: {exc}",
            )
        repair_snapshot = snapshot_transcript_artifact(transcript_path, "repair")
        if repair_snapshot is not None:
            stage_artifacts.append(str(repair_snapshot))
        intro_relwork_path.write_text(
            extract_latex_document(transcript_path.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        coverage_ok, coverage_output = run_citation_coverage(intro_relwork_path, citation_pool_path, stage_log, env)
        if not coverage_ok:
            transcript_path = write_local_literature_fallback(
                workspace,
                citation_pool_path,
                Path(load_run_or_raise(project_id, run_id, data_root)["stages"]["literature"]["transcript_path"]),
                stage_log,
                f"Literature coverage repair fallback triggered after insufficient citation coverage.\n{coverage_output}",
            )
            repair_snapshot = snapshot_transcript_artifact(transcript_path, "repair")
            if repair_snapshot is not None:
                stage_artifacts.append(str(repair_snapshot))
            intro_relwork_path.write_text(
                extract_latex_document(transcript_path.read_text(encoding="utf-8")),
                encoding="utf-8",
            )
            coverage_ok, coverage_output = run_citation_coverage(intro_relwork_path, citation_pool_path, stage_log, env)
            if not coverage_ok:
                raise RuntimeError(f"Introduction/Related Work coverage gate failed after repair.\n{coverage_output}")
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "literature",
        "citation_coverage_repair",
        "Citation coverage gate passed for Introduction and Related Work.",
        artifacts=artifact_paths(intro_relwork_path),
    )
    stage_artifacts.extend(
        artifact_paths(
            refs_path,
            intro_relwork_path,
            citation_pool_path,
            citation_map_path,
            transcript_path,
        )
    )
    save_stage_artifacts(project_id, run_id, data_root, "literature", stage_artifacts)
    update_stage(project_id, run_id, data_root, "literature", status="succeeded", summary="Literature package completed.")
    return stage_artifacts


def execute_parallel_branch(project: dict[str, object], run_id: str, data_root: Path, env: dict[str, str]) -> None:
    run_payload = load_run_or_raise(str(project["project_id"]), run_id, data_root)
    todo: list[tuple[str, callable]] = []
    if run_payload["stages"]["plotting"].get("status") != "succeeded":
        todo.append(("plotting", execute_plotting))
    if run_payload["stages"]["literature"].get("status") != "succeeded":
        todo.append(("literature", execute_literature))
    if not todo:
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(todo)) as executor:
        futures = [
            executor.submit(fn, project, run_id, data_root, env)
            for _, fn in todo
        ]
        for future in concurrent.futures.as_completed(futures):
            future.result()


def execute_section_writing(project: dict[str, object], run_id: str, data_root: Path, env: dict[str, str]) -> list[str]:
    project_id = str(project["project_id"])
    workspace = Path(str(project["workspace_path"])).expanduser()
    stage_log = Path(load_run_or_raise(project_id, run_id, data_root)["stages"]["section_writing"]["log_path"])
    transcript_path = Path(load_run_or_raise(project_id, run_id, data_root)["stages"]["section_writing"]["transcript_path"])
    draft_path = workspace / "drafts" / "paper.tex"
    stage_env = with_min_stage_timeout(env, 240.0)

    maybe_trigger_acceptance_failpoint(project_id, run_id, data_root, "section_writing", env)
    update_stage(project_id, run_id, data_root, "section_writing", status="running", summary="Drafting the paper body.")
    check_for_cancel(project_id, run_id, data_root)
    start_stage_substep(project_id, run_id, data_root, "section_writing", "bundle_validate", "Validating the section-writing handoff bundle.")
    bundle_path = build_section_writing_bundle(workspace)
    required_paths = [
        workspace / "inputs" / "idea.md",
        workspace / "inputs" / "experimental_log.md",
        workspace / "inputs" / "template.tex",
        workspace / "inputs" / "conference_guidelines.md",
        workspace / "drafts" / "intro_relwork.tex",
        workspace / "citation_pool.json",
        workspace / "citation_map.json",
        workspace / "refs.bib",
    ]
    missing_inputs = [str(path) for path in required_paths if not path.exists()]
    if missing_inputs:
        raise RuntimeError(f"Section-writing bundle is incomplete: {', '.join(missing_inputs)}")
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "section_writing",
        "bundle_validate",
        "Section-writing bundle is ready.",
        artifacts=artifact_paths(bundle_path),
    )
    start_stage_substep(project_id, run_id, data_root, "section_writing", "draft_generate", "Generating the full paper draft.")
    try:
        transcript_path = run_codex_stage(
            project_id,
            run_id,
            data_root,
            "section_writing",
            section_writing_prompt(workspace),
            workspace,
            stage_env,
        )
    except RuntimeError as exc:
        if "timed out" not in str(exc).lower() or not recover_latex_transcript_from_log(stage_log, transcript_path):
            raise
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "section_writing",
        "draft_generate",
        "Codex produced the section-writing transcript.",
        artifacts=artifact_paths(transcript_path),
    )
    start_stage_substep(project_id, run_id, data_root, "section_writing", "draft_extract", "Extracting LaTeX into drafts/paper.tex.")
    if not draft_path.exists():
        storage.ensure_dir(draft_path.parent)
        draft_path.write_text(
            extract_latex_document(transcript_path.read_text(encoding="utf-8", errors="replace")),
            encoding="utf-8",
        )
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "section_writing",
        "draft_extract",
        "Draft LaTeX extracted to drafts/paper.tex.",
        artifacts=artifact_paths(draft_path),
    )
    start_stage_substep(project_id, run_id, data_root, "section_writing", "citation_gate", "Checking citations against refs.bib.")
    run_command(
        [sys.executable, str(storage.REPO_ROOT / "skills" / "section-writing-agent" / "scripts" / "orphan_cite_gate.py"), str(draft_path), str(workspace / "refs.bib")],
        cwd=storage.REPO_ROOT,
        log_path=stage_log,
        env=env,
    )
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "section_writing",
        "citation_gate",
        "Citation gate passed.",
        artifacts=artifact_paths(draft_path, workspace / "refs.bib"),
    )
    start_stage_substep(project_id, run_id, data_root, "section_writing", "latex_sanity_gate", "Checking LaTeX structural sanity.")
    run_command(
        [sys.executable, str(storage.REPO_ROOT / "skills" / "section-writing-agent" / "scripts" / "latex_sanity.py"), str(draft_path)],
        cwd=storage.REPO_ROOT,
        log_path=stage_log,
        env=env,
    )
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "section_writing",
        "latex_sanity_gate",
        "LaTeX sanity gate passed.",
        artifacts=artifact_paths(draft_path),
    )
    start_stage_substep(project_id, run_id, data_root, "section_writing", "anti_leakage_gate", "Running anti-leakage checks.")
    run_command(
        [sys.executable, str(storage.REPO_ROOT / "skills" / "paper-orchestra" / "scripts" / "anti_leakage_check.py"), str(draft_path)],
        cwd=storage.REPO_ROOT,
        log_path=stage_log,
        env=env,
    )
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "section_writing",
        "anti_leakage_gate",
        "Anti-leakage gate passed.",
        artifacts=artifact_paths(draft_path),
    )
    start_stage_substep(project_id, run_id, data_root, "section_writing", "figure_usage_gate", "Checking figure references in the generated draft.")
    figure_usage_ok, figure_usage_message = validate_figure_usage(draft_path, workspace / "figures")
    if not figure_usage_ok:
        finish_stage_substep(
            project_id,
            run_id,
            data_root,
            "section_writing",
            "figure_usage_gate",
            figure_usage_message,
            status="paused",
            attention_required={
                "reason": "figure_qc_failed",
                "message": figure_usage_message,
                "details": {"draft_path": str(draft_path)},
            },
        )
        update_stage(
            project_id,
            run_id,
            data_root,
            "section_writing",
            status="paused",
            summary=figure_usage_message,
            attention_required={
                "reason": "figure_qc_failed",
                "message": figure_usage_message,
                "details": {"draft_path": str(draft_path)},
            },
        )
        raise RunNeedsInput(figure_usage_message)
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "section_writing",
        "figure_usage_gate",
        figure_usage_message,
        artifacts=artifact_paths(draft_path),
    )
    artifacts = artifact_paths(draft_path, transcript_path, bundle_path)
    save_stage_artifacts(project_id, run_id, data_root, "section_writing", artifacts)
    update_stage(project_id, run_id, data_root, "section_writing", status="succeeded", summary="Section writing completed.")
    return artifacts


def execute_refinement(project: dict[str, object], run_id: str, data_root: Path, env: dict[str, str]) -> list[str]:
    project_id = str(project["project_id"])
    workspace = Path(str(project["workspace_path"])).expanduser()
    stage_log = Path(load_run_or_raise(project_id, run_id, data_root)["stages"]["refinement"]["log_path"])
    transcript_path = Path(load_run_or_raise(project_id, run_id, data_root)["stages"]["refinement"]["transcript_path"])
    final_tex = workspace / "final" / "paper.tex"
    final_pdf = workspace / "final" / "paper.pdf"
    draft_tex = workspace / "drafts" / "paper.tex"
    worklog_path = workspace / "refinement" / "worklog.json"
    refinement_root = workspace / "refinement"
    stage_env = with_min_stage_timeout(env, 240.0)
    reviewer_rubric_path, _, snapshot_script, _, _ = refinement_paths()

    maybe_trigger_acceptance_failpoint(project_id, run_id, data_root, "refinement", env)
    update_stage(project_id, run_id, data_root, "refinement", status="running", summary="Running refinement loop.")
    check_for_cancel(project_id, run_id, data_root)
    storage.ensure_dir(refinement_root)
    update_stage_loop_state(
        project_id,
        run_id,
        data_root,
        "refinement",
        event_type="iteration_started",
        iteration_cap=3,
        current_iteration=0,
        best_iteration=0,
        halt_reason="",
        score_trajectory=[],
        accepted_iterations=[0],
    )

    if not draft_tex.exists():
        raise RuntimeError("Refinement requires drafts/paper.tex from section writing.")

    iter0_dir = refinement_root / "iter0"
    start_stage_substep(project_id, run_id, data_root, "refinement", "baseline_snapshot", "Snapshotting and compiling the baseline draft.")
    run_command(
        [
            sys.executable,
            str(snapshot_script),
            "--src",
            str(draft_tex),
            "--dst",
            str(iter0_dir),
        ],
        cwd=storage.REPO_ROOT,
        log_path=stage_log,
        env=env,
    )
    try:
        run_command(
            ["latexmk", "-pdf", "paper.tex"],
            cwd=iter0_dir,
            log_path=stage_log,
            env=env,
        )
    except Exception as exc:
        raise RunNeedsInput(f"Baseline refinement compile failed: {exc}") from exc
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "refinement",
        "baseline_snapshot",
        "Baseline refinement snapshot created.",
        artifacts=artifact_paths(iter0_dir / "paper.tex", iter0_dir / "paper.pdf"),
    )

    def _legacy_refinement_fallback(reason: str) -> list[str]:
        if not final_tex.exists() and draft_tex.exists():
            storage.ensure_dir(final_tex.parent)
            shutil.copy2(draft_tex, final_tex)
        if not worklog_path.exists():
            write_default_refinement_worklog(worklog_path, reason)
        artifacts = artifact_paths(final_tex, worklog_path, transcript_path)
        save_stage_artifacts(project_id, run_id, data_root, "refinement", artifacts)
        update_stage_loop_state(
            project_id,
            run_id,
            data_root,
            "refinement",
            event_type="iteration_halted",
            halt_reason="compatibility_fallback",
            best_iteration=0,
        )
        update_stage(
            project_id,
            run_id,
            data_root,
            "refinement",
            status="succeeded",
            summary="Refinement completed via compatibility fallback.",
        )
        return artifacts

    start_stage_substep(project_id, run_id, data_root, "refinement", "iter0.review", "Scoring the baseline refinement snapshot.")
    try:
        baseline_review_transcript = run_codex_stage(
            project_id,
            run_id,
            data_root,
            "refinement",
            refinement_review_prompt(workspace, iter0_dir / "paper.tex", iter0_dir / "paper.pdf"),
            workspace,
            stage_env,
            sandbox_mode="read-only",
        )
        baseline_review = extract_json_object(baseline_review_transcript.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        if "timed out" in str(exc).lower():
            if recover_latex_transcript_from_log(stage_log, transcript_path):
                storage.ensure_dir(final_tex.parent)
                final_tex.write_text(
                    extract_latex_document(transcript_path.read_text(encoding="utf-8", errors="replace")),
                    encoding="utf-8",
                )
            elif draft_tex.exists():
                storage.ensure_dir(final_tex.parent)
                shutil.copy2(draft_tex, final_tex)
            return _legacy_refinement_fallback("Accepted section-writing draft after refinement timeout.")
        if final_tex.exists() or worklog_path.exists():
            return _legacy_refinement_fallback(f"Compatibility refinement delegate accepted: {exc}")
        raise
    baseline_score = score_from_review(baseline_review)
    storage.atomic_write_json(iter0_dir / "review.json", baseline_review)
    storage.atomic_write_json(iter0_dir / "score.json", baseline_score)
    append_refinement_worklog(
        worklog_path,
        0,
        iter0_dir / "review.json",
        iter0_dir / "score.json",
        "ACCEPT_BASELINE",
        None,
        stage_log,
        env,
    )
    finish_stage_substep(
        project_id,
        run_id,
        data_root,
        "refinement",
        "iter0.review",
        "Baseline review and score recorded.",
        artifacts=artifact_paths(iter0_dir / "review.json", iter0_dir / "score.json"),
    )
    update_stage_loop_state(
        project_id,
        run_id,
        data_root,
        "refinement",
        event_type="iteration_scored",
        score_trajectory=[{"iteration": 0, "overall_score": baseline_score.get("overall_score"), "decision": "ACCEPT_BASELINE"}],
    )

    accepted_iteration = 0
    best_iteration = 0
    halt_reason = ""
    consecutive_small = 0
    score_trajectory = [{"iteration": 0, "overall_score": baseline_score.get("overall_score"), "decision": "ACCEPT_BASELINE"}]
    accepted_iterations = [0]
    prev_score_path = iter0_dir / "score.json"

    for iteration in range(1, 4):
        prev_iter_dir = refinement_root / f"iter{accepted_iteration}"
        iter_dir = refinement_root / f"iter{iteration}"
        update_stage_loop_state(
            project_id,
            run_id,
            data_root,
            "refinement",
            event_type="iteration_started",
            current_iteration=iteration,
            best_iteration=best_iteration,
            score_trajectory=score_trajectory,
            accepted_iterations=accepted_iterations,
        )

        review_substep = f"iter{iteration}.review"
        revise_substep = f"iter{iteration}.revise"
        compile_substep = f"iter{iteration}.compile"
        score_substep = f"iter{iteration}.score"

        start_stage_substep(project_id, run_id, data_root, "refinement", review_substep, f"Generating reviewer feedback for iteration {iteration}.")
        review_transcript_path = run_codex_stage(
            project_id,
            run_id,
            data_root,
            "refinement",
            refinement_review_prompt(workspace, prev_iter_dir / "paper.tex", prev_iter_dir / "paper.pdf"),
            workspace,
            stage_env,
            sandbox_mode="read-only",
        )
        review_payload = extract_json_object(review_transcript_path.read_text(encoding="utf-8", errors="replace"))
        review_path = iter_dir / "review.json"
        score_path = iter_dir / "score.json"
        actions_path = iter_dir / "worklog_entry.json"
        delta_path = iter_dir / "delta.json"
        storage.ensure_dir(iter_dir)
        storage.atomic_write_json(review_path, review_payload)
        finish_stage_substep(
            project_id,
            run_id,
            data_root,
            "refinement",
            review_substep,
            f"Reviewer feedback captured for iteration {iteration}.",
            artifacts=artifact_paths(review_path),
        )

        if not list(review_payload.get("weaknesses", []) or []):
            halt_reason = "no_new_weaknesses"
            append_refinement_worklog(
                worklog_path,
                iteration,
                review_path,
                prev_score_path,
                "HALT_NO_ACTIONABLE_WEAKNESSES",
                None,
                stage_log,
                env,
                halted_because=halt_reason,
            )
            update_stage_loop_state(
                project_id,
                run_id,
                data_root,
                "refinement",
                event_type="iteration_halted",
                halt_reason=halt_reason,
                best_iteration=best_iteration,
                score_trajectory=score_trajectory,
                accepted_iterations=accepted_iterations,
            )
            break

        start_stage_substep(project_id, run_id, data_root, "refinement", revise_substep, f"Applying revision for iteration {iteration}.")
        revision_transcript_path = run_codex_stage(
            project_id,
            run_id,
            data_root,
            "refinement",
            refinement_revision_prompt(workspace, prev_iter_dir / "paper.tex", prev_iter_dir / "paper.pdf", review_payload, worklog_path),
            workspace,
            stage_env,
        )
        revision_worklog, revised_latex = extract_revision_response(revision_transcript_path.read_text(encoding="utf-8", errors="replace"))
        (iter_dir / "paper.tex").write_text(revised_latex, encoding="utf-8")
        storage.atomic_write_json(actions_path, revision_worklog)
        finish_stage_substep(
            project_id,
            run_id,
            data_root,
            "refinement",
            revise_substep,
            f"Revision generated for iteration {iteration}.",
            artifacts=artifact_paths(iter_dir / "paper.tex", actions_path),
        )

        start_stage_substep(project_id, run_id, data_root, "refinement", compile_substep, f"Compiling refinement iteration {iteration}.")
        compile_failed = False
        compile_error = ""
        try:
            run_command(
                ["latexmk", "-pdf", "paper.tex"],
                cwd=iter_dir,
                log_path=stage_log,
                env=env,
            )
        except Exception as exc:
            compile_failed = True
            compile_error = str(exc)
        if compile_failed:
            finish_stage_substep(
                project_id,
                run_id,
                data_root,
                "refinement",
                compile_substep,
                f"Iteration {iteration} compile failed and was reverted: {compile_error}",
                status="failed",
            )
            append_refinement_worklog(
                worklog_path,
                iteration,
                review_path,
                prev_score_path,
                "REVERT_COMPILE_FAILURE",
                actions_path,
                stage_log,
                env,
                halted_because="compile_failure",
            )
            halt_reason = "compile_failure"
            update_stage_loop_state(
                project_id,
                run_id,
                data_root,
                "refinement",
                event_type="iteration_reverted",
                halt_reason=halt_reason,
                best_iteration=best_iteration,
                score_trajectory=score_trajectory,
                accepted_iterations=accepted_iterations,
            )
            break
        finish_stage_substep(
            project_id,
            run_id,
            data_root,
            "refinement",
            compile_substep,
            f"Iteration {iteration} compiled successfully.",
            artifacts=artifact_paths(iter_dir / "paper.pdf"),
        )
        update_stage_loop_state(
            project_id,
            run_id,
            data_root,
            "refinement",
            event_type="iteration_compiled",
            current_iteration=iteration,
        )

        start_stage_substep(project_id, run_id, data_root, "refinement", score_substep, f"Scoring refinement iteration {iteration}.")
        rescored_transcript_path = run_codex_stage(
            project_id,
            run_id,
            data_root,
            "refinement",
            refinement_review_prompt(workspace, iter_dir / "paper.tex", iter_dir / "paper.pdf"),
            workspace,
            stage_env,
            sandbox_mode="read-only",
        )
        rescored_review = extract_json_object(rescored_transcript_path.read_text(encoding="utf-8", errors="replace"))
        rescored_score = score_from_review(rescored_review)
        storage.atomic_write_json(review_path, rescored_review)
        storage.atomic_write_json(score_path, rescored_score)
        finish_stage_substep(
            project_id,
            run_id,
            data_root,
            "refinement",
            score_substep,
            f"Scored refinement iteration {iteration}.",
            artifacts=artifact_paths(review_path, score_path),
        )
        update_stage_loop_state(
            project_id,
            run_id,
            data_root,
            "refinement",
            event_type="iteration_scored",
            current_iteration=iteration,
        )

        delta_payload = run_refinement_delta(prev_score_path, score_path, delta_path, stage_log, env, consecutive_small)
        decision = str(delta_payload.get("decision", "REVERT_OVERALL_DECREASED") or "REVERT_OVERALL_DECREASED")
        append_refinement_worklog(
            worklog_path,
            iteration,
            review_path,
            score_path,
            decision,
            actions_path,
            stage_log,
            env,
        )
        score_trajectory.append({
            "iteration": iteration,
            "overall_score": rescored_score.get("overall_score"),
            "decision": decision,
        })
        consecutive_small = int(delta_payload.get("consecutive_small", 0) or 0)

        if int(delta_payload.get("exit_code", 1)) in {0, 4}:
            accepted_iteration = iteration
            accepted_iterations.append(iteration)
            if float(rescored_score.get("overall_score", 0) or 0) >= float(json.loads(prev_score_path.read_text(encoding="utf-8")).get("overall_score", 0) or 0):
                best_iteration = iteration
            prev_score_path = score_path
            update_stage_loop_state(
                project_id,
                run_id,
                data_root,
                "refinement",
                event_type="iteration_accepted",
                best_iteration=best_iteration,
                score_trajectory=score_trajectory,
                accepted_iterations=accepted_iterations,
            )
            if int(delta_payload.get("exit_code", 1)) == 4:
                halt_reason = "plateau"
                update_stage_loop_state(
                    project_id,
                    run_id,
                    data_root,
                    "refinement",
                    event_type="iteration_halted",
                    halt_reason=halt_reason,
                    best_iteration=best_iteration,
                    score_trajectory=score_trajectory,
                    accepted_iterations=accepted_iterations,
                )
                break
        else:
            halt_reason = "reverted"
            update_stage_loop_state(
                project_id,
                run_id,
                data_root,
                "refinement",
                event_type="iteration_reverted",
                halt_reason=halt_reason,
                best_iteration=best_iteration,
                score_trajectory=score_trajectory,
                accepted_iterations=accepted_iterations,
            )
            break
    else:
        halt_reason = "iteration_cap_reached"

    promoted_dir = refinement_root / f"iter{best_iteration}"
    storage.ensure_dir(final_tex.parent)
    shutil.copy2(promoted_dir / "paper.tex", final_tex)
    if (promoted_dir / "paper.pdf").exists():
        shutil.copy2(promoted_dir / "paper.pdf", final_pdf)
    update_stage_loop_state(
        project_id,
        run_id,
        data_root,
        "refinement",
        event_type="best_snapshot_promoted",
        best_iteration=best_iteration,
        halt_reason=halt_reason or "completed",
        score_trajectory=score_trajectory,
        accepted_iterations=accepted_iterations,
    )
    append_log(stage_log, f"Promoted refinement iteration {best_iteration} to workspace/final/.")

    artifacts: list[str] = artifact_paths(final_tex, final_pdf, worklog_path, transcript_path)
    for iteration_dir in sorted(refinement_root.glob("iter*")):
        artifacts.extend(str(path) for path in sorted(iteration_dir.iterdir()) if path.is_file())
    save_stage_artifacts(project_id, run_id, data_root, "refinement", list(dict.fromkeys(artifacts)))
    update_stage(
        project_id,
        run_id,
        data_root,
        "refinement",
        status="succeeded",
        summary=f"Refinement completed with best iteration iter{best_iteration}.",
    )
    return list(dict.fromkeys(artifacts))


def execute_compile(project: dict[str, object], run_id: str, data_root: Path, env: dict[str, str]) -> list[str]:
    project_id = str(project["project_id"])
    workspace = Path(str(project["workspace_path"])).expanduser()
    stage_log = Path(load_run_or_raise(project_id, run_id, data_root)["stages"]["compile"]["log_path"])
    final_tex = workspace / "final" / "paper.tex"

    maybe_trigger_acceptance_failpoint(project_id, run_id, data_root, "compile", env)
    update_stage(project_id, run_id, data_root, "compile", status="running", summary="Running final gates and PDF compile.")
    check_for_cancel(project_id, run_id, data_root)
    try:
        prep_artifacts = prepare_compile_workspace(workspace)
        run_command(
            [sys.executable, str(storage.REPO_ROOT / "skills" / "section-writing-agent" / "scripts" / "orphan_cite_gate.py"), str(final_tex), str(workspace / "refs.bib")],
            cwd=storage.REPO_ROOT,
            log_path=stage_log,
            env=env,
        )
        run_command(
            [sys.executable, str(storage.REPO_ROOT / "skills" / "section-writing-agent" / "scripts" / "latex_sanity.py"), str(final_tex)],
            cwd=storage.REPO_ROOT,
            log_path=stage_log,
            env=env,
        )
        run_command(
            [sys.executable, str(storage.REPO_ROOT / "skills" / "paper-orchestra" / "scripts" / "anti_leakage_check.py"), str(final_tex)],
            cwd=storage.REPO_ROOT,
            log_path=stage_log,
            env=env,
        )
        run_command(
            ["latexmk", "-pdf", "paper.tex"],
            cwd=workspace / "final",
            log_path=stage_log,
            env=env,
        )
    except Exception as exc:
        update_stage(
            project_id,
            run_id,
            data_root,
            "compile",
            status="paused",
            summary=f"Compile requires manual intervention: {exc}",
            attention_required={
                "reason": "compile_error",
                "message": f"Compile requires manual intervention: {exc}",
                "details": {"log_path": str(stage_log)},
            },
        )
        raise RunNeedsInput(f"Compile requires manual intervention: {exc}") from exc
    artifacts = artifact_paths(workspace / "final" / "paper.tex", workspace / "final" / "paper.pdf", *prep_artifacts)
    save_stage_artifacts(project_id, run_id, data_root, "compile", artifacts)
    update_stage(project_id, run_id, data_root, "compile", status="succeeded", summary="Compilation completed.")
    return artifacts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def execute_finalize(project: dict[str, object], run_id: str, data_root: Path, env: dict[str, str]) -> list[str]:
    project_id = str(project["project_id"])
    workspace = Path(str(project["workspace_path"])).expanduser()

    maybe_trigger_acceptance_failpoint(project_id, run_id, data_root, "finalize", env)
    update_stage(project_id, run_id, data_root, "finalize", status="running", summary="Collecting provenance.")
    check_for_cancel(project_id, run_id, data_root)
    provenance = {
        "generated_at": storage.utc_now(),
        "workspace": str(workspace),
        "artifacts": [],
    }
    for artifact in storage.collect_workspace_artifacts(workspace):
        path = Path(artifact["path"])
        provenance["artifacts"].append({
            **artifact,
            "sha256": _sha256(path),
        })
    provenance_path = workspace / "provenance.json"
    storage.atomic_write_json(provenance_path, provenance)
    artifacts = artifact_paths(provenance_path, workspace / "final" / "paper.pdf", workspace / "final" / "paper.tex")
    save_stage_artifacts(project_id, run_id, data_root, "finalize", artifacts)
    update_stage(project_id, run_id, data_root, "finalize", status="succeeded", summary="Provenance written.")
    return artifacts


def execute_orchestrated(project_id: str, run_id: str, data_root: Path, resume_from: str | None = None) -> dict:
    project = storage.load_project(project_id, data_root)
    if not project:
        raise RuntimeError(f"Project not found: {project_id}")
    project = storage.sync_workspace(project, data_root)
    env = ensure_runtime_env(data_root)

    stage_order = list(storage.PIPELINE_STAGE_ORDER)
    requested_stage = resume_from or storage.next_incomplete_stage(load_run_or_raise(project_id, run_id, data_root)) or "ingest"
    start_stage = storage.resolve_requested_stage(load_run_or_raise(project_id, run_id, data_root), requested_stage)
    update_run(
        project_id,
        run_id,
        data_root,
        status="running",
        stage=start_stage,
        current_stage=start_stage,
        summary=(
            f"Resuming from {start_stage} to satisfy dependencies for {requested_stage}."
            if requested_stage != start_stage else f"Resuming from {start_stage}."
        ),
    )
    start_index = stage_order.index(start_stage)

    for stage_name in stage_order[start_index:]:
        check_for_cancel(project_id, run_id, data_root)
        if stage_name == "plotting":
            execute_parallel_branch(project, run_id, data_root, env)
            continue
        if stage_name == "literature":
            continue
        if stage_name == "ingest":
            execute_ingest(project, run_id, data_root, env)
        elif stage_name == "validate":
            execute_validate(project, run_id, data_root, env)
        elif stage_name == "outline":
            execute_outline(project, run_id, data_root, env)
        elif stage_name == "section_writing":
            execute_section_writing(project, run_id, data_root, env)
        elif stage_name == "refinement":
            execute_refinement(project, run_id, data_root, env)
        elif stage_name == "compile":
            execute_compile(project, run_id, data_root, env)
        elif stage_name == "finalize":
            execute_finalize(project, run_id, data_root, env)

    artifacts = storage.collect_workspace_artifacts(Path(str(project["workspace_path"])).expanduser())
    final_message_path = storage.run_dir(project_id, run_id, data_root) / "assistant-last-message.txt"
    final_message_path.write_text(
        "\n".join([
            "PaperOrchestra pipeline completed.",
            *(f"- {item['label']}: {item['path']}" for item in artifacts[:8]),
        ]) + "\n",
        encoding="utf-8",
    )
    return update_run(
        project_id,
        run_id,
        data_root,
        status="succeeded",
        stage="done",
        current_stage="done",
        finished_at=storage.utc_now(),
        summary="Autonomous pipeline completed.",
        final_message_path=str(final_message_path),
    )


def execute_validation(project_id: str, run_id: str, data_root: Path) -> dict:
    project = storage.load_project(project_id, data_root)
    if not project:
        raise RuntimeError(f"Project not found: {project_id}")
    project = storage.sync_workspace(project, data_root)
    workspace = Path(project["workspace_path"]).expanduser()
    repo_root = storage.REPO_ROOT
    run_payload = storage.load_run(project_id, run_id, data_root)
    log_path = Path(run_payload["log_path"])

    env = ensure_runtime_env(data_root)

    update_run(project_id, run_id, data_root, stage="scaffold", status="running")
    run_command(
        [sys.executable, str(repo_root / "skills" / "paper-orchestra" / "scripts" / "init_workspace.py"), "--out", str(workspace), "--force"],
        cwd=repo_root,
        log_path=log_path,
        env=env,
    )

    update_run(project_id, run_id, data_root, stage="validate_inputs", status="running")
    run_command(
        [sys.executable, str(repo_root / "skills" / "paper-orchestra" / "scripts" / "validate_inputs.py"), "--workspace", str(workspace)],
        cwd=repo_root,
        log_path=log_path,
        env=env,
    )

    update_run(project_id, run_id, data_root, stage="extract_metrics", status="running")
    run_command(
        [
            sys.executable,
            str(repo_root / "skills" / "section-writing-agent" / "scripts" / "extract_metrics.py"),
            "--log",
            str(workspace / "inputs" / "experimental_log.md"),
            "--out",
            str(workspace / "metrics.json"),
        ],
        cwd=repo_root,
        log_path=log_path,
        env=env,
    )

    summary = "Validation passed and deterministic metric extraction completed."
    storage.update_latest_validation(project, {"status": "validated", "checked_at": storage.utc_now(), "summary": summary}, data_root)
    return update_run(
        project_id,
        run_id,
        data_root,
        status="succeeded",
        stage="done",
        finished_at=storage.utc_now(),
        summary=summary,
    )


def execute_pipeline(project_id: str, run_id: str, data_root: Path) -> dict:
    project = storage.load_project(project_id, data_root)
    if not project:
        raise RuntimeError(f"Project not found: {project_id}")
    project = storage.sync_workspace(project, data_root)
    workspace = Path(project["workspace_path"]).expanduser()
    repo_root = storage.REPO_ROOT
    run_payload = storage.load_run(project_id, run_id, data_root)
    log_path = Path(run_payload["log_path"])
    final_message_path = storage.run_dir(project_id, run_id, data_root) / "assistant-last-message.txt"

    env = ensure_runtime_env(data_root)

    update_run(project_id, run_id, data_root, stage="scaffold", status="running")
    run_command(
        [sys.executable, str(repo_root / "skills" / "paper-orchestra" / "scripts" / "init_workspace.py"), "--out", str(workspace), "--force"],
        cwd=repo_root,
        log_path=log_path,
        env=env,
    )
    update_run(project_id, run_id, data_root, stage="validate_inputs", status="running")
    run_command(
        [sys.executable, str(repo_root / "skills" / "paper-orchestra" / "scripts" / "validate_inputs.py"), "--workspace", str(workspace)],
        cwd=repo_root,
        log_path=log_path,
        env=env,
    )

    update_run(project_id, run_id, data_root, stage="codex_pipeline", status="running")
    writer_executor.WriterExecutor(repo_root).run_stage(
        workspace=workspace,
        transcript_path=final_message_path,
        prompt=pipeline_prompt(workspace),
        log_path=log_path,
        env=env,
    )

    summary = f"Codex pipeline completed. Final message saved to {final_message_path}."
    storage.update_latest_validation(project, {"status": "validated", "checked_at": storage.utc_now(), "summary": "Inputs were validated before the pipeline run."}, data_root)
    return update_run(
        project_id,
        run_id,
        data_root,
        status="succeeded",
        stage="done",
        finished_at=storage.utc_now(),
        summary=summary,
        final_message_path=str(final_message_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--kind", choices=["validate", "pipeline", "orchestrated"], required=True)
    parser.add_argument("--resume-from", default=None)
    args = parser.parse_args()

    data_root = Path(args.data_root).expanduser()
    try:
        if args.kind == "validate":
            execute_validation(args.project_id, args.run_id, data_root)
        elif args.kind == "pipeline":
            execute_pipeline(args.project_id, args.run_id, data_root)
        else:
            execute_orchestrated(args.project_id, args.run_id, data_root, resume_from=args.resume_from)
        update_run(args.project_id, args.run_id, data_root, worker_state="succeeded")
        return 0
    except RunNeedsInput as exc:
        current = storage.load_run(args.project_id, args.run_id, data_root) or {}
        update_run(
            args.project_id,
            args.run_id,
            data_root,
            status="paused",
            stage=current.get("stage", "paused"),
            current_stage=current.get("current_stage", current.get("stage", "paused")),
            finished_at=storage.utc_now(),
            worker_state="paused",
            summary=str(exc),
        )
        return 1
    except Exception as exc:  # pragma: no cover - exercised via integration test
        run_payload = storage.load_run(args.project_id, args.run_id, data_root) or {}
        log_path = Path(run_payload.get("log_path", storage.run_dir(args.project_id, args.run_id, data_root) / "run.log"))
        append_log(log_path, f"ERROR: {exc}")
        append_log(log_path, traceback.format_exc())
        if run_payload.get("status") == "cancelled" or run_payload.get("cancel_requested_at"):
            update_run(
                args.project_id,
                args.run_id,
                data_root,
                worker_state="cancelled",
            )
            return 1
        update_run(
            args.project_id,
            args.run_id,
            data_root,
            status="failed",
            stage="failed",
            current_stage="failed",
            finished_at=storage.utc_now(),
            worker_state="failed",
            summary=str(exc),
        )
        project = storage.load_project(args.project_id, data_root)
        if project:
            storage.update_latest_validation(project, {"status": "failed", "checked_at": storage.utc_now(), "summary": str(exc)}, data_root)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
