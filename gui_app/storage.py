#!/usr/bin/env python3
"""Persistence helpers for the PaperOrchestra local browser GUI."""

from __future__ import annotations

import json
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_ROOT = Path.home() / ".paperorchestra" / "gui"
FALLBACK_DATA_ROOT = REPO_ROOT / ".paperorchestra-gui"
PIPELINE_STAGE_ORDER = (
    "ingest",
    "validate",
    "outline",
    "plotting",
    "literature",
    "section_writing",
    "refinement",
    "compile",
    "finalize",
)
STAGE_DEPENDENCIES = {
    "ingest": [],
    "validate": ["ingest"],
    "outline": ["validate"],
    "plotting": ["outline"],
    "literature": ["outline"],
    "section_writing": ["plotting", "literature"],
    "refinement": ["section_writing"],
    "compile": ["refinement"],
    "finalize": ["compile"],
}
RUN_STATUS_ALIASES = {
    "completed": "succeeded",
    "attention_required": "paused",
}
STAGE_STATUS_ALIASES = {
    "completed": "succeeded",
    "needs_input": "paused",
    "attention_required": "paused",
}
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "paused", "interrupted", "cancelled"}
TERMINAL_STAGE_STATUSES = {"succeeded", "failed", "paused", "cancelled", "skipped"}
PARALLEL_STAGE_GROUP = {"plotting", "literature"}
_VALIDATOR_MODULE: Any | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def repo_python_executable(default: str | None = None) -> Path:
    candidate = REPO_ROOT / ".venv" / "bin" / "python"
    if candidate.exists():
        return candidate
    if default:
        return Path(default)
    return Path("python3")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "paper-project"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, path)


def _ensure_trailing_newline(text: str) -> str:
    stripped = str(text or "").strip()
    return stripped + ("\n" if stripped else "")


def _default_validation_state() -> dict[str, Any]:
    return {
        "messages": [],
        "has_blockers": False,
        "updated_at": None,
    }


def _parse_markdown_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_key: str | None = None
    buffer: list[str] = []
    for raw_line in str(text or "").splitlines():
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$", raw_line)
        if heading:
            if current_key is not None:
                sections[current_key] = "\n".join(buffer).strip()
            current_key = heading.group(1).strip().lower()
            buffer = []
            continue
        if current_key is not None:
            buffer.append(raw_line)
    if current_key is not None:
        sections[current_key] = "\n".join(buffer).strip()
    return sections


def _build_idea_markdown_from_fields(idea: dict[str, Any]) -> str:
    sections = [
        ("Problem Statement", idea.get("problem_statement", "")),
        ("Core Hypothesis", idea.get("core_hypothesis", "")),
        ("Proposed Methodology (High-Level Technical Approach)", idea.get("methodology", "")),
        ("Expected Contribution", idea.get("expected_contribution", "")),
    ]
    chunks = [f"## {heading}\n\n{str(body or '').strip() or '_To be completed._'}" for heading, body in sections]
    notes = str(idea.get("notes", "") or "").strip()
    if notes:
        chunks.append(f"## Additional Notes\n\n{notes}")
    return _ensure_trailing_newline("\n\n".join(chunks))


def parse_idea_markdown(text: str) -> dict[str, str]:
    sections = _parse_markdown_sections(text)
    return {
        "problem_statement": sections.get("problem statement", ""),
        "core_hypothesis": sections.get("core hypothesis", ""),
        "methodology": (
            sections.get("proposed methodology (high-level technical approach)")
            or sections.get("proposed methodology (detailed technical approach)")
            or ""
        ),
        "expected_contribution": sections.get("expected contribution", ""),
        "notes": sections.get("additional notes", ""),
    }


def _build_experimental_markdown_from_fields(experimental: dict[str, Any]) -> str:
    setup_text = str(experimental.get("setup_text", "") or "").strip()
    raw_numeric_data = str(experimental.get("raw_numeric_data", "") or "").strip()
    qualitative_observations = str(experimental.get("qualitative_observations", "") or "").strip()
    document = "\n\n".join([
        "# Experimental Log",
        f"## 1. Experimental Setup\n\n{setup_text or '_To be completed._'}",
        f"## 2. Raw Numeric Data\n\n{raw_numeric_data or '_To be completed._'}",
        f"## 3. Qualitative Observations\n\n{qualitative_observations or '_To be completed._'}",
    ])
    return _ensure_trailing_newline(document)


def parse_experimental_log(text: str) -> dict[str, str]:
    sections = _parse_markdown_sections(text)
    return {
        "setup_text": sections.get("1. experimental setup", ""),
        "raw_numeric_data": sections.get("2. raw numeric data", ""),
        "qualitative_observations": sections.get("3. qualitative observations", ""),
    }


def _build_guidelines_markdown_from_fields(guidelines: dict[str, Any]) -> str:
    page_limit = str(guidelines.get("page_limit", "") or "").strip()
    deadline = str(guidelines.get("deadline", "") or "").strip()
    required_sections = str(guidelines.get("required_sections", "") or "").strip()
    formatting_notes = str(guidelines.get("formatting_notes", "") or "").strip()
    parts = ["# Conference Guidelines"]
    if page_limit:
        parts.append(f"Page limit: {page_limit}")
    if deadline:
        parts.append(f"Submission deadline: {deadline}")
    if required_sections:
        parts.append(f"Required sections: {required_sections}")
    if formatting_notes:
        parts.append(f"Formatting notes:\n{formatting_notes}")
    return _ensure_trailing_newline("\n\n".join(parts))


def parse_guidelines_text(text: str) -> dict[str, str]:
    raw_text = str(text or "")
    page_limit_match = re.search(r"(\d+)\s*page", raw_text, re.IGNORECASE)
    deadline_match = re.search(
        r"(?:(?:submission\s+)?deadline|cutoff|submission)\s*[:\-]?\s*([^\n.]+)",
        raw_text,
        re.IGNORECASE,
    )
    required_sections_match = re.search(r"required sections?\s*[:\-]?\s*([^\n]+)", raw_text, re.IGNORECASE)
    formatting_match = re.search(r"formatting(?:\s+notes?)?\s*[:\-]?\s*([\s\S]+)$", raw_text, re.IGNORECASE)
    return {
        "page_limit": page_limit_match.group(1).strip() if page_limit_match else "",
        "deadline": deadline_match.group(1).strip() if deadline_match else "",
        "required_sections": required_sections_match.group(1).strip() if required_sections_match else "",
        "formatting_notes": formatting_match.group(1).strip() if formatting_match else "",
    }


def _validator_module() -> Any:
    global _VALIDATOR_MODULE
    if _VALIDATOR_MODULE is None:
        module_path = REPO_ROOT / "skills" / "paper-orchestra" / "scripts" / "validate_inputs.py"
        spec = importlib.util.spec_from_file_location("paperorchestra_validate_inputs", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load validator module from {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _VALIDATOR_MODULE = module
    return _VALIDATOR_MODULE


def _normalize_project_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault("wizard_step", "setup")
    normalized.setdefault("latest_validation", None)
    normalized.setdefault("latest_run_id", None)
    normalized.setdefault("latest_browser_result", None)
    normalized.setdefault("latest_atlas_result", None)
    normalized.setdefault("last_status", "draft")
    normalized.setdefault("setup", {})
    normalized.setdefault("ingest", {"source_directory": "", "enabled": False})
    normalized.setdefault("uploads", {})
    normalized["uploads"].setdefault("template_tex", "")
    normalized["uploads"].setdefault("figures", [])

    idea = dict(normalized.get("idea", {}))
    idea.setdefault("problem_statement", "")
    idea.setdefault("core_hypothesis", "")
    idea.setdefault("methodology", "")
    idea.setdefault("expected_contribution", "")
    idea.setdefault("notes", "")
    idea.setdefault("editor_mode", "structured")
    idea.setdefault("validation", _default_validation_state())
    if not str(idea.get("raw_markdown", "") or "").strip():
        idea["raw_markdown"] = _build_idea_markdown_from_fields(idea)
    normalized["idea"] = idea

    experimental = dict(normalized.get("experimental", {}))
    experimental.setdefault("log_text", "")
    experimental.setdefault("source_filename", "")
    experimental.setdefault("editor_mode", "structured")
    experimental.setdefault("validation", _default_validation_state())
    parsed_experimental = parse_experimental_log(experimental.get("log_text", ""))
    experimental.setdefault("setup_text", parsed_experimental.get("setup_text", ""))
    experimental.setdefault("raw_numeric_data", parsed_experimental.get("raw_numeric_data", ""))
    experimental.setdefault("qualitative_observations", parsed_experimental.get("qualitative_observations", ""))
    if not str(experimental.get("log_text", "") or "").strip():
        experimental["log_text"] = _build_experimental_markdown_from_fields(experimental)
    normalized["experimental"] = experimental

    guidelines = dict(normalized.get("guidelines", {}))
    guidelines.setdefault("guidelines_text", "")
    guidelines.setdefault("source_filename", "")
    guidelines.setdefault("editor_mode", "structured")
    guidelines.setdefault("validation", _default_validation_state())
    parsed_guidelines = parse_guidelines_text(guidelines.get("guidelines_text", ""))
    guidelines.setdefault("deadline", parsed_guidelines.get("deadline", ""))
    guidelines.setdefault("page_limit", parsed_guidelines.get("page_limit", ""))
    guidelines.setdefault("required_sections", parsed_guidelines.get("required_sections", ""))
    guidelines.setdefault("formatting_notes", parsed_guidelines.get("formatting_notes", ""))
    normalized["guidelines"] = guidelines

    template = dict(normalized.get("template", {}))
    template.setdefault("text", "")
    template.setdefault("source_filename", "")
    template.setdefault("editor_mode", "raw")
    template.setdefault("validation", _default_validation_state())
    template_upload = normalized.get("uploads", {}).get("template_tex", "")
    upload_path = Path(str(template_upload)).expanduser() if template_upload else None
    if not str(template.get("text", "") or "").strip() and upload_path and upload_path.exists():
        template["text"] = upload_path.read_text(encoding="utf-8", errors="replace")
        template["source_filename"] = template.get("source_filename") or upload_path.name
    normalized["template"] = template
    return normalized


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def append_jsonl(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


@dataclass(frozen=True)
class GuiPaths:
    data_root: Path

    @property
    def projects_root(self) -> Path:
        return self.data_root / "projects"

    @property
    def workspaces_root(self) -> Path:
        return self.data_root / "workspaces"

    @property
    def uploads_root(self) -> Path:
        return self.data_root / "uploads"

    @property
    def index_path(self) -> Path:
        return self.data_root / "projects_index.json"


def get_paths(data_root: Path | None = None) -> GuiPaths:
    requested_root = (data_root or DEFAULT_DATA_ROOT).expanduser()
    for candidate in (requested_root, FALLBACK_DATA_ROOT):
        try:
            root = ensure_dir(candidate)
            paths = GuiPaths(root)
            ensure_dir(paths.projects_root)
            ensure_dir(paths.workspaces_root)
            ensure_dir(paths.uploads_root)
            if not paths.index_path.exists():
                atomic_write_json(paths.index_path, {"projects": []})
            else:
                load_json(paths.index_path, {"projects": []})
            return paths
        except OSError:
            continue
    raise RuntimeError("Unable to initialize a writable GUI data directory.")


def project_dir(project_id: str, data_root: Path | None = None) -> Path:
    return get_paths(data_root).projects_root / project_id


def project_file(project_id: str, data_root: Path | None = None) -> Path:
    return project_dir(project_id, data_root) / "project.json"


def run_dir(project_id: str, run_id: str, data_root: Path | None = None) -> Path:
    return project_dir(project_id, data_root) / "runs" / run_id


def run_state_file(project_id: str, run_id: str, data_root: Path | None = None) -> Path:
    return run_dir(project_id, run_id, data_root) / "state.json"


def run_events_file(project_id: str, run_id: str, data_root: Path | None = None) -> Path:
    return run_dir(project_id, run_id, data_root) / "events.jsonl"


def legacy_run_file(project_id: str, run_id: str, data_root: Path | None = None) -> Path:
    return run_dir(project_id, run_id, data_root) / "run.json"


def run_file(project_id: str, run_id: str, data_root: Path | None = None) -> Path:
    return run_state_file(project_id, run_id, data_root)


def stage_dir(project_id: str, run_id: str, stage_name: str, data_root: Path | None = None) -> Path:
    return run_dir(project_id, run_id, data_root) / "stages" / stage_name


def stage_attempt_dir(project_id: str, run_id: str, stage_name: str, attempt: int,
                      data_root: Path | None = None) -> Path:
    return stage_dir(project_id, run_id, stage_name, data_root) / f"attempt-{attempt:03d}"


def stage_log_file(project_id: str, run_id: str, stage_name: str, data_root: Path | None = None,
                   attempt: int = 1) -> Path:
    return stage_attempt_dir(project_id, run_id, stage_name, attempt, data_root) / "stage.log"


def stage_transcript_file(project_id: str, run_id: str, stage_name: str, data_root: Path | None = None,
                          attempt: int = 1) -> Path:
    return stage_attempt_dir(project_id, run_id, stage_name, attempt, data_root) / "codex-last-message.txt"


def list_projects(data_root: Path | None = None) -> list[dict[str, Any]]:
    paths = get_paths(data_root)
    index = load_json(paths.index_path, {"projects": []})
    projects: list[dict[str, Any]] = []
    for project_id in index.get("projects", []):
        payload = load_project(project_id, data_root)
        if payload:
            projects.append(payload)
    projects.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return projects


def load_project(project_id: str, data_root: Path | None = None) -> dict[str, Any] | None:
    path = project_file(project_id, data_root)
    if not path.exists():
        return None
    payload = _normalize_project_payload(load_json(path, {}))
    if not payload:
        return None
    payload.setdefault("project_id", project_id)
    return payload


def save_project(payload: dict[str, Any], data_root: Path | None = None) -> dict[str, Any]:
    paths = get_paths(data_root)
    payload = _normalize_project_payload(payload)
    project_id = payload["project_id"]
    ensure_dir(project_dir(project_id, data_root))
    payload["updated_at"] = utc_now()
    atomic_write_json(project_file(project_id, data_root), payload)

    index = load_json(paths.index_path, {"projects": []})
    if project_id not in index["projects"]:
        index["projects"].append(project_id)
        atomic_write_json(paths.index_path, index)
    return payload


def _normalize_run_status(status: str) -> str:
    return RUN_STATUS_ALIASES.get(status, status)


def _normalize_stage_status(status: str) -> str:
    return STAGE_STATUS_ALIASES.get(status, status)


def _canonical_attempt(project_id: str, run_id: str, stage_name: str, data_root: Path | None,
                       attempt: int) -> tuple[int, Path, Path, Path]:
    canonical_attempt = max(int(attempt or 1), 1)
    attempt_root = ensure_dir(stage_attempt_dir(project_id, run_id, stage_name, canonical_attempt, data_root))
    return (
        canonical_attempt,
        attempt_root,
        attempt_root / "stage.log",
        attempt_root / "codex-last-message.txt",
    )


def _normalize_substep_payload(substep_payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(substep_payload or {})
    normalized["name"] = str(normalized.get("name", "") or "").strip()
    normalized["status"] = _normalize_stage_status(str(normalized.get("status", "pending") or "pending"))
    normalized["started_at"] = normalized.get("started_at")
    normalized["finished_at"] = normalized.get("finished_at")
    normalized["summary"] = str(normalized.get("summary", "") or "")
    normalized["artifacts"] = [path for path in normalized.get("artifacts", []) if path]
    normalized["attention_required"] = normalized.get("attention_required")
    normalized["performance"] = normalized.get("performance")
    return normalized


def _normalize_loop_state(loop_state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not loop_state:
        return None
    normalized = dict(loop_state)
    normalized.setdefault("iteration_cap", None)
    normalized.setdefault("current_iteration", None)
    normalized.setdefault("best_iteration", None)
    normalized.setdefault("halt_reason", "")
    normalized["score_trajectory"] = list(normalized.get("score_trajectory", []) or [])
    normalized["accepted_iterations"] = list(normalized.get("accepted_iterations", []) or [])
    return normalized


def _normalize_stage_payload(project_id: str, run_id: str, stage_name: str,
                             stage_payload: dict[str, Any], data_root: Path | None = None) -> dict[str, Any]:
    canonical_attempt, attempt_root, log_path, transcript_path = _canonical_attempt(
        project_id,
        run_id,
        stage_name,
        data_root,
        int(stage_payload.get("attempt", 1) or 1),
    )
    return {
        "name": stage_name,
        "status": _normalize_stage_status(str(stage_payload.get("status", "pending"))),
        "started_at": stage_payload.get("started_at"),
        "finished_at": stage_payload.get("finished_at"),
        "summary": stage_payload.get("summary", ""),
        "log_path": str(stage_payload.get("log_path") or log_path),
        "artifacts": [path for path in stage_payload.get("artifacts", []) if path],
        "attempt": canonical_attempt,
        "attempt_dir": str(stage_payload.get("attempt_dir") or attempt_root),
        "attention_required": stage_payload.get("attention_required"),
        "transcript_path": str(stage_payload.get("transcript_path") or transcript_path),
        "dependencies": list(stage_payload.get("dependencies", STAGE_DEPENDENCIES.get(stage_name, []))),
        "performance": stage_payload.get("performance"),
        "substeps": [
            _normalize_substep_payload(item)
            for item in stage_payload.get("substeps", []) or []
            if isinstance(item, dict) and str(item.get("name", "") or "").strip()
        ],
        "loop_state": _normalize_loop_state(stage_payload.get("loop_state")),
    }


def _normalize_run_payload(payload: dict[str, Any], data_root: Path | None = None) -> dict[str, Any]:
    project_id = payload["project_id"]
    run_id = payload["run_id"]
    stage_order = list(payload.get("stage_order", list(PIPELINE_STAGE_ORDER)))
    normalized = dict(payload)
    normalized["status"] = _normalize_run_status(str(payload.get("status", "queued")))
    normalized["stage"] = payload.get("stage", payload.get("current_stage", "queued"))
    normalized["current_stage"] = payload.get("current_stage", normalized["stage"])
    normalized["stage_order"] = stage_order
    normalized["artifacts"] = [path for path in payload.get("artifacts", []) if path]
    normalized["attention_required"] = payload.get("attention_required")
    normalized["created_at"] = payload.get("created_at", payload.get("started_at", utc_now()))
    normalized["updated_at"] = payload.get("updated_at", normalized["created_at"])
    stages: dict[str, Any] = {}
    for stage_name in stage_order:
        source = dict(payload.get("stages", {}).get(stage_name, {}))
        stages[stage_name] = _normalize_stage_payload(project_id, run_id, stage_name, source, data_root)
    normalized["stages"] = stages
    return normalized


def _event_payload(run_payload: dict[str, Any], event_type: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "at": utc_now(),
        "type": event_type,
        "project_id": run_payload["project_id"],
        "run_id": run_payload["run_id"],
        "details": details or {},
        "state": run_payload,
    }


def append_run_event(run_payload: dict[str, Any], event_type: str, data_root: Path | None = None,
                     details: dict[str, Any] | None = None) -> dict[str, Any]:
    append_jsonl(
        run_events_file(run_payload["project_id"], run_payload["run_id"], data_root),
        _event_payload(run_payload, event_type, details),
    )
    return run_payload


def materialize_run_from_events(project_id: str, run_id: str, data_root: Path | None = None) -> dict[str, Any] | None:
    events = load_jsonl(run_events_file(project_id, run_id, data_root))
    if not events:
        return None
    last_event = events[-1]
    state = dict(last_event.get("state", {}))
    if not state:
        return None
    normalized = _normalize_run_payload(state, data_root)
    atomic_write_json(run_state_file(project_id, run_id, data_root), normalized)
    return normalized


def load_run(project_id: str, run_id: str, data_root: Path | None = None) -> dict[str, Any] | None:
    path = run_state_file(project_id, run_id, data_root)
    if path.exists():
        return _normalize_run_payload(load_json(path, {}), data_root)
    legacy_path = legacy_run_file(project_id, run_id, data_root)
    if legacy_path.exists():
        payload = _normalize_run_payload(load_json(legacy_path, {}), data_root)
        atomic_write_json(path, payload)
        return payload
    return materialize_run_from_events(project_id, run_id, data_root)


def save_run(payload: dict[str, Any], data_root: Path | None = None) -> dict[str, Any]:
    ensure_dir(run_dir(payload["project_id"], payload["run_id"], data_root))
    normalized = _normalize_run_payload(payload, data_root)
    normalized["updated_at"] = utc_now()
    atomic_write_json(run_state_file(payload["project_id"], payload["run_id"], data_root), normalized)
    return normalized


def update_run_fields(project_id: str, run_id: str, data_root: Path | None = None,
                      event_type: str = "run_updated", **fields: Any) -> dict[str, Any]:
    run_payload = load_run(project_id, run_id, data_root)
    if not run_payload:
        raise RuntimeError(f"Run not found: {project_id}/{run_id}")
    run_payload.update(fields)
    saved = save_run(run_payload, data_root)
    return append_run_event(saved, event_type, data_root, {"fields": fields})


def list_runs(project_id: str, data_root: Path | None = None) -> list[dict[str, Any]]:
    runs_root = project_dir(project_id, data_root) / "runs"
    if not runs_root.exists():
        return []
    runs: list[dict[str, Any]] = []
    for child in runs_root.iterdir():
        if child.is_dir():
            payload = load_run(project_id, child.name, data_root)
            if payload:
                runs.append(payload)
    runs.sort(key=lambda item: item.get("started_at", ""), reverse=True)
    return runs


def build_default_workspace(title: str, data_root: Path | None = None) -> Path:
    paths = get_paths(data_root)
    base = slugify(title)
    candidate = paths.workspaces_root / base
    suffix = 2
    while candidate.exists():
        candidate = paths.workspaces_root / f"{base}-{suffix}"
        suffix += 1
    return candidate


def create_project(title: str, venue: str, description: str, workspace_path: str | None = None,
                   data_root: Path | None = None, source_directory: str = "") -> dict[str, Any]:
    now = utc_now()
    project_id = uuid.uuid4().hex[:12]
    workspace = Path(workspace_path).expanduser() if workspace_path else build_default_workspace(title, data_root)
    payload = {
        "project_id": project_id,
        "created_at": now,
        "updated_at": now,
        "title": title.strip() or "Untitled Paper",
        "venue": venue.strip(),
        "description": description.strip(),
        "workspace_path": str(workspace),
        "wizard_step": "setup",
        "latest_validation": None,
        "latest_run_id": None,
        "last_status": "draft",
        "setup": {
            "title": title.strip(),
            "venue": venue.strip(),
            "description": description.strip(),
        },
        "ingest": {
            "source_directory": source_directory.strip(),
            "enabled": bool(source_directory.strip()),
        },
        "idea": {
            "problem_statement": "",
            "core_hypothesis": "",
            "methodology": "",
            "expected_contribution": "",
            "notes": "",
            "raw_markdown": "",
            "editor_mode": "structured",
            "validation": _default_validation_state(),
        },
        "experimental": {
            "log_text": "",
            "source_filename": "",
            "setup_text": "",
            "raw_numeric_data": "",
            "qualitative_observations": "",
            "editor_mode": "structured",
            "validation": _default_validation_state(),
        },
        "guidelines": {
            "guidelines_text": "",
            "source_filename": "",
            "deadline": "",
            "page_limit": "",
            "required_sections": "",
            "formatting_notes": "",
            "editor_mode": "structured",
            "validation": _default_validation_state(),
        },
        "template": {
            "text": "",
            "source_filename": "",
            "editor_mode": "raw",
            "validation": _default_validation_state(),
        },
        "uploads": {
            "template_tex": "",
            "figures": [],
        },
    }
    return save_project(payload, data_root)


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text.strip() + ("\n" if text.strip() else ""), encoding="utf-8")


def copy_upload(src: Path, dest: Path) -> None:
    ensure_dir(dest.parent)
    shutil.copy2(src, dest)


def idea_markdown(project: dict[str, Any]) -> str:
    idea = _normalize_project_payload(project).get("idea", {})
    raw_markdown = str(idea.get("raw_markdown", "") or "").strip()
    if raw_markdown:
        return _ensure_trailing_newline(raw_markdown)
    return _build_idea_markdown_from_fields(idea)


def experimental_markdown(project: dict[str, Any]) -> str:
    experimental = _normalize_project_payload(project).get("experimental", {})
    log_text = str(experimental.get("log_text", "") or "").strip()
    if log_text:
        return _ensure_trailing_newline(log_text)
    return _build_experimental_markdown_from_fields(experimental)


def guidelines_markdown(project: dict[str, Any]) -> str:
    guidelines = _normalize_project_payload(project).get("guidelines", {})
    guidelines_text = str(guidelines.get("guidelines_text", "") or "").strip()
    if guidelines_text:
        return _ensure_trailing_newline(guidelines_text)
    return _build_guidelines_markdown_from_fields(guidelines)


def template_text(project: dict[str, Any]) -> str:
    template = _normalize_project_payload(project).get("template", {})
    text = str(template.get("text", "") or "").strip()
    return _ensure_trailing_newline(text)


def sync_workspace(project: dict[str, Any], data_root: Path | None = None) -> dict[str, Any]:
    project = _normalize_project_payload(project)
    workspace = Path(project["workspace_path"]).expanduser()
    ensure_dir(workspace / "inputs" / "figures")
    ensure_dir(workspace / "drafts")
    ensure_dir(workspace / "final")
    ensure_dir(workspace / "refinement")
    ensure_dir(workspace / "figures")
    ensure_dir(workspace / "cache")

    write_text(workspace / "inputs" / "idea.md", idea_markdown(project))
    write_text(workspace / "inputs" / "experimental_log.md", experimental_markdown(project))
    write_text(workspace / "inputs" / "conference_guidelines.md", guidelines_markdown(project))

    template_target = workspace / "inputs" / "template.tex"
    canonical_template_text = template_text(project)
    template_upload = project.get("uploads", {}).get("template_tex", "")
    if canonical_template_text:
        write_text(template_target, canonical_template_text)
    elif template_upload:
        copy_upload(Path(template_upload), template_target)
    elif template_target.exists():
        template_target.unlink()

    figures_root = workspace / "inputs" / "figures"
    for existing in figures_root.iterdir():
        if existing.is_file():
            existing.unlink()
    for figure_path in project.get("uploads", {}).get("figures", []):
        source = Path(figure_path)
        if source.exists():
            copy_upload(source, figures_root / source.name)

    project["workspace_path"] = str(workspace)
    return save_project(project, data_root)


def validate_project_inputs(project: dict[str, Any], data_root: Path | None = None) -> dict[str, Any]:
    synced = sync_workspace(project, data_root)
    workspace = Path(synced["workspace_path"]).expanduser()
    inputs_root = workspace / "inputs"
    validator = _validator_module()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        checks = {
            "idea": validator.check_idea_md(inputs_root / "idea.md"),
            "experimental": validator.check_experimental_log(inputs_root / "experimental_log.md"),
            "template": validator.check_template(inputs_root / "template.tex"),
            "guidelines": validator.check_guidelines(inputs_root / "conference_guidelines.md"),
        }

    figures_messages: list[str] = []
    for figure_path in synced.get("uploads", {}).get("figures", []):
        candidate = Path(str(figure_path)).expanduser()
        if not candidate.exists():
            figures_messages.append(f"MISSING: {candidate}")
        elif candidate.stat().st_size == 0:
            figures_messages.append(f"EMPTY: {candidate}")
    checks["figures"] = figures_messages

    inputs: dict[str, Any] = {}
    blocker_count = 0
    for name, messages in checks.items():
        cleaned = [str(item) for item in messages if str(item).strip()]
        has_blockers = any(item.startswith(("ERROR", "MISSING", "EMPTY")) for item in cleaned)
        if has_blockers:
            blocker_count += 1
        inputs[name] = {
            "messages": cleaned,
            "has_blockers": has_blockers,
            "completed": not has_blockers and name != "figures",
        }

    summary = "All required inputs are ready." if blocker_count == 0 else f"{blocker_count} input area(s) need attention."
    result = {
        "status": "validated" if blocker_count == 0 else "needs_attention",
        "summary": summary,
        "updated_at": utc_now(),
        "has_blockers": blocker_count > 0,
        "inputs": inputs,
    }
    return result


def new_run_id(prefix: str = "pipeline") -> str:
    timestamp = utc_now().replace(":", "").replace("-", "").replace("+00:00", "").replace("T", "-")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:6]}"


def default_stage_state(project_id: str, run_id: str, stage_name: str,
                        data_root: Path | None = None) -> dict[str, Any]:
    attempt, attempt_root, log_path, transcript_path = _canonical_attempt(project_id, run_id, stage_name, data_root, 1)
    return {
        "name": stage_name,
        "status": "pending",
        "started_at": None,
        "finished_at": None,
        "summary": "",
        "log_path": str(log_path),
        "artifacts": [],
        "attempt": attempt,
        "attempt_dir": str(attempt_root),
        "attention_required": None,
        "transcript_path": str(transcript_path),
        "dependencies": list(STAGE_DEPENDENCIES.get(stage_name, [])),
        "performance": None,
        "substeps": [],
        "loop_state": None,
    }


def create_pipeline_run(project_id: str, data_root: Path | None = None, run_id: str | None = None) -> dict[str, Any]:
    pipeline_run_id = run_id or new_run_id("pipeline")
    ensure_dir(run_dir(project_id, pipeline_run_id, data_root))
    project = load_project(project_id, data_root) or {}
    payload = {
        "project_id": project_id,
        "run_id": pipeline_run_id,
        "kind": "pipeline_v2",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "status": "queued",
        "current_stage": "queued",
        "stage": "queued",
        "stage_order": list(PIPELINE_STAGE_ORDER),
        "started_at": utc_now(),
        "finished_at": None,
        "summary": "",
        "workspace_path": str(project.get("workspace_path", "")),
        "log_path": str(run_dir(project_id, pipeline_run_id, data_root) / "logs" / "run.log"),
        "pid": None,
        "cancel_requested_at": None,
        "final_message_path": None,
        "artifacts": [],
        "attention_required": None,
        "stages": {
            stage_name: default_stage_state(project_id, pipeline_run_id, stage_name, data_root)
            for stage_name in PIPELINE_STAGE_ORDER
        },
    }
    saved = save_run(payload, data_root)
    append_run_event(saved, "run_created", data_root, {"status": saved["status"]})
    return saved


def save_stage_artifacts(run_payload: dict[str, Any], stage_name: str, data_root: Path | None = None,
                         paths: list[str] | None = None) -> dict[str, Any]:
    stage_payload = run_payload["stages"][stage_name]
    previous_artifacts = {str(path) for path in stage_payload.get("artifacts", []) if path}
    stage_payload["artifacts"] = [path for path in (paths or []) if path]
    saved = save_run(run_payload, data_root)
    for artifact_path in stage_payload["artifacts"]:
        if artifact_path in previous_artifacts:
            continue
        append_run_event(
            saved,
            "artifact_written",
            data_root,
            {"stage": stage_name, "path": artifact_path},
        )
    return append_run_event(
        saved,
        "stage_artifacts_updated",
        data_root,
        {"stage": stage_name, "artifacts": stage_payload["artifacts"]},
    )


def update_stage_state(run_payload: dict[str, Any], stage_name: str, data_root: Path | None = None,
                       **fields: Any) -> dict[str, Any]:
    stage_payload = run_payload["stages"][stage_name]
    if "status" in fields:
        status = _normalize_stage_status(str(fields["status"]))
        fields["status"] = status
        if status == "running" and not fields.get("started_at"):
            fields["started_at"] = utc_now()
            fields.setdefault("finished_at", None)
        if status in TERMINAL_STAGE_STATUSES and "finished_at" not in fields:
            fields["finished_at"] = utc_now()
    stage_payload.update(fields)
    run_payload["stage"] = stage_name
    run_payload["current_stage"] = stage_name
    if stage_payload.get("status") == "paused":
        run_payload["status"] = "paused"
        run_payload["attention_required"] = stage_payload.get("attention_required")
    elif stage_payload.get("status") == "failed":
        run_payload["status"] = "failed"
        run_payload["attention_required"] = stage_payload.get("attention_required")
    elif stage_payload.get("status") == "running":
        run_payload["status"] = "running"
        run_payload["attention_required"] = None
    elif all(run_payload["stages"][name].get("status") == "succeeded" for name in run_payload.get("stage_order", [])):
        run_payload["status"] = "succeeded"
        run_payload["finished_at"] = run_payload.get("finished_at") or utc_now()
        run_payload["attention_required"] = None
    saved = save_run(run_payload, data_root)
    return append_run_event(saved, "stage_updated", data_root, {"stage": stage_name, "fields": fields})


def upsert_stage_substep(
    run_payload: dict[str, Any],
    stage_name: str,
    substep_name: str,
    data_root: Path | None = None,
    event_type: str = "stage_substep_updated",
    **fields: Any,
) -> dict[str, Any]:
    stage_payload = run_payload["stages"][stage_name]
    substeps = list(stage_payload.get("substeps", []) or [])
    existing: dict[str, Any] | None = None
    existing_index = -1
    for index, item in enumerate(substeps):
        if str(item.get("name", "") or "") == substep_name:
            existing = dict(item)
            existing_index = index
            break
    substep_payload = existing or {"name": substep_name}
    if "status" in fields:
        status = _normalize_stage_status(str(fields["status"]))
        fields["status"] = status
        if status == "running" and not fields.get("started_at"):
            fields["started_at"] = utc_now()
            fields.setdefault("finished_at", None)
        if status in TERMINAL_STAGE_STATUSES and "finished_at" not in fields:
            fields["finished_at"] = utc_now()
    substep_payload.update(fields)
    normalized = _normalize_substep_payload(substep_payload)
    if existing_index >= 0:
        substeps[existing_index] = normalized
    else:
        substeps.append(normalized)
    stage_payload["substeps"] = substeps
    saved = save_run(run_payload, data_root)
    return append_run_event(
        saved,
        event_type,
        data_root,
        {"stage": stage_name, "substep": substep_name, "fields": fields},
    )


def set_stage_loop_state(
    run_payload: dict[str, Any],
    stage_name: str,
    data_root: Path | None = None,
    event_type: str = "stage_loop_state_updated",
    **fields: Any,
) -> dict[str, Any]:
    stage_payload = run_payload["stages"][stage_name]
    current = dict(stage_payload.get("loop_state") or {})
    current.update(fields)
    stage_payload["loop_state"] = _normalize_loop_state(current)
    saved = save_run(run_payload, data_root)
    return append_run_event(saved, event_type, data_root, {"stage": stage_name, "fields": fields})


def _increment_stage_attempt(run_payload: dict[str, Any], stage_name: str,
                             data_root: Path | None = None) -> None:
    stage_payload = run_payload["stages"][stage_name]
    attempt, attempt_root, log_path, transcript_path = _canonical_attempt(
        run_payload["project_id"],
        run_payload["run_id"],
        stage_name,
        data_root,
        int(stage_payload.get("attempt", 1) or 1) + 1,
    )
    stage_payload["attempt"] = attempt
    stage_payload["attempt_dir"] = str(attempt_root)
    stage_payload["log_path"] = str(log_path)
    stage_payload["transcript_path"] = str(transcript_path)


def reset_stage_state(run_payload: dict[str, Any], stage_name: str,
                      data_root: Path | None = None, increment_attempt: bool = False) -> None:
    stage_payload = run_payload["stages"][stage_name]
    if increment_attempt:
        _increment_stage_attempt(run_payload, stage_name, data_root)
    stage_payload.update({
        "status": "pending",
        "started_at": None,
        "finished_at": None,
        "summary": "",
        "artifacts": [],
        "attention_required": None,
        "performance": None,
        "substeps": [],
        "loop_state": None,
    })


def reset_pipeline_run_from_stage(run_payload: dict[str, Any], stage_name: str,
                                  data_root: Path | None = None) -> dict[str, Any]:
    stage_order = run_payload.get("stage_order", list(PIPELINE_STAGE_ORDER))
    if stage_name not in stage_order:
        raise ValueError(f"Unknown stage: {stage_name}")

    start_index = stage_order.index(stage_name)
    for candidate in stage_order[start_index:]:
        if (
            stage_name in PARALLEL_STAGE_GROUP
            and candidate in PARALLEL_STAGE_GROUP
            and candidate != stage_name
            and run_payload["stages"][candidate].get("status") == "succeeded"
        ):
            continue
        existing_status = run_payload["stages"][candidate].get("status")
        reset_stage_state(
            run_payload,
            candidate,
            data_root,
            increment_attempt=existing_status not in {None, "pending"},
        )

    run_payload["status"] = "queued"
    run_payload["current_stage"] = stage_name
    run_payload["stage"] = stage_name
    run_payload["finished_at"] = None
    run_payload["summary"] = f"Queued retry from {stage_name}."
    run_payload["cancel_requested_at"] = None
    run_payload["attention_required"] = None
    saved = save_run(run_payload, data_root)
    return append_run_event(saved, "stage_retry_queued", data_root, {"stage": stage_name})


def _dependency_closure(stage_name: str) -> set[str]:
    closure: set[str] = set()
    queue = list(STAGE_DEPENDENCIES.get(stage_name, []))
    while queue:
        candidate = queue.pop(0)
        if candidate in closure:
            continue
        closure.add(candidate)
        queue.extend(STAGE_DEPENDENCIES.get(candidate, []))
    return closure


def resolve_requested_stage(run_payload: dict[str, Any], stage_name: str) -> str:
    stage_order = run_payload.get("stage_order", list(PIPELINE_STAGE_ORDER))
    if stage_name not in stage_order:
        raise ValueError(f"Unknown stage: {stage_name}")

    required = _dependency_closure(stage_name)
    for candidate in stage_order:
        if candidate in required and run_payload["stages"][candidate].get("status") != "succeeded":
            return candidate
    return stage_name


def next_incomplete_stage(run_payload: dict[str, Any]) -> str | None:
    for stage_name in run_payload.get("stage_order", list(PIPELINE_STAGE_ORDER)):
        if run_payload["stages"][stage_name].get("status") != "succeeded":
            return stage_name
    return None


def workspace_artifact_candidates(workspace: Path) -> list[tuple[str, Path]]:
    return [
        ("Final PDF", workspace / "final" / "paper.pdf"),
        ("Final TeX", workspace / "final" / "paper.tex"),
        ("Draft TeX", workspace / "drafts" / "paper.tex"),
        ("Intro + Related Work", workspace / "drafts" / "intro_relwork.tex"),
        ("Outline JSON", workspace / "outline.json"),
        ("Bibliography", workspace / "refs.bib"),
        ("Citation Pool", workspace / "citation_pool.json"),
        ("Metrics JSON", workspace / "metrics.json"),
        ("TeX Profile", workspace / "tex_profile.json"),
        ("Provenance", workspace / "provenance.json"),
    ]


def collect_workspace_artifacts(workspace: Path) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for label, candidate in workspace_artifact_candidates(workspace):
        if candidate.exists():
            artifacts.append({"label": label, "path": str(candidate)})
    figures_root = workspace / "figures"
    if figures_root.exists():
        for candidate in sorted(figures_root.iterdir()):
            if candidate.is_file():
                artifacts.append({"label": f"Figure: {candidate.name}", "path": str(candidate)})
    return artifacts


def store_uploaded_file(project_id: str, field_name: str, filename: str, data: bytes,
                        data_root: Path | None = None) -> str:
    safe_name = Path(filename).name or f"{field_name}.bin"
    target = get_paths(data_root).uploads_root / project_id / field_name / safe_name
    ensure_dir(target.parent)
    target.write_bytes(data)
    return str(target)


def update_latest_validation(project: dict[str, Any], result: dict[str, Any],
                             data_root: Path | None = None) -> dict[str, Any]:
    project["latest_validation"] = result
    project["last_status"] = result.get("status", project.get("last_status", "draft"))
    return save_project(project, data_root)


def record_atlas_literature_run(project: dict[str, Any], result: dict[str, Any],
                                data_root: Path | None = None) -> dict[str, Any]:
    run_id = f"atlas-literature-{uuid.uuid4().hex[:10]}"
    run_root = run_dir(project["project_id"], run_id, data_root)
    ensure_dir(run_root)
    persisted_result = dict(result)
    persisted_screenshots: list[str] = []
    for screenshot_path in result.get("screenshot_paths", []):
        source = Path(str(screenshot_path)).expanduser()
        if not source.exists():
            continue
        target = run_root / "screenshots" / source.name
        ensure_dir(target.parent)
        shutil.copy2(source, target)
        persisted_screenshots.append(str(target))
    persisted_result["screenshot_paths"] = persisted_screenshots
    result_path = run_root / "atlas_result.json"
    atomic_write_json(result_path, persisted_result)
    response_path = run_root / "atlas_response.md"
    response_text = str(persisted_result.get("response_text", "") or "").strip()
    response_path.write_text(response_text + ("\n" if response_text else ""), encoding="utf-8")

    mode_used = persisted_result.get("mode_used", "normal")
    summary = "Atlas literature prompt submitted with Deep Research verification."
    stage = "atlas_deep_research"
    if mode_used != "deep_research":
        summary = persisted_result.get("fallback_reason", "") or "Atlas literature prompt submitted in normal-mode fallback."
        stage = "atlas_normal_fallback"

    log_path = run_root / "atlas.log"
    log_path.write_text(summary + "\n", encoding="utf-8")

    payload = {
        "project_id": project["project_id"],
        "run_id": run_id,
        "kind": "atlas_literature",
        "status": "succeeded" if persisted_result.get("submitted") else "failed",
        "stage": stage,
        "started_at": persisted_result.get("started_at", utc_now()),
        "finished_at": persisted_result.get("finished_at", utc_now()),
        "summary": summary,
        "log_path": str(log_path),
        "pid": None,
        "result_path": str(result_path),
        "mode_used": mode_used,
        "verification_method": persisted_result.get("verification_method", "unverified"),
    }
    save_run(payload, data_root)

    project["latest_run_id"] = run_id
    project["latest_atlas_result"] = {
        **persisted_result,
        "run_id": run_id,
        "result_path": str(result_path),
        "summary": summary,
    }
    project["latest_browser_result"] = {
        **project["latest_atlas_result"],
        "adapter": "atlas",
        "raw_response_path": str(response_path),
        "response_path": str(response_path),
        "attention_required": None,
    }
    project["last_status"] = "handoff_ready" if persisted_result.get("submitted") else "failed"
    save_project(project, data_root)
    return payload


def is_pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        completed = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(int(pid))],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return True
    status = completed.stdout.strip()
    if not status:
        return False
    if status.startswith("Z"):
        return False
    return True


def reconcile_run(run_payload: dict[str, Any], data_root: Path | None = None) -> dict[str, Any]:
    if run_payload.get("status") in TERMINAL_RUN_STATUSES:
        return run_payload
    pid = run_payload.get("pid")
    if is_pid_running(pid):
        return run_payload
    run_payload["status"] = "interrupted"
    run_payload["finished_at"] = utc_now()
    run_payload.setdefault("summary", "The job stopped before reporting completion.")
    saved = save_run(run_payload, data_root)
    return append_run_event(saved, "run_interrupted", data_root, {"pid": pid})


def reconcile_project_runs(project: dict[str, Any], data_root: Path | None = None) -> dict[str, Any]:
    runs = [reconcile_run(run, data_root) for run in list_runs(project["project_id"], data_root)]
    project["runs"] = runs
    project["latest_run"] = runs[0] if runs else None
    if runs:
        project["latest_run_id"] = runs[0]["run_id"]
        if runs[0]["status"] == "succeeded":
            project["last_status"] = "succeeded"
        elif runs[0]["status"] in {"running", "queued"}:
            project["last_status"] = "running"
        elif runs[0]["status"] in {"failed", "interrupted", "cancelled", "paused"}:
            project["last_status"] = runs[0]["status"]
    return project
