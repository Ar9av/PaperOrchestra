#!/usr/bin/env python3
"""FastAPI web app for the Codex-first PaperOrchestra control room."""

from __future__ import annotations

import asyncio
import datetime as dt
import mimetypes
import os
import shutil
import urllib.parse
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import atlas_controller
from . import chrome_devtools_adapter
from . import config
from . import global_browser_setup
from . import orchestrator
from . import research_adapter
from . import storage
from .server import parse_markdown_sections

STEPS = ["setup", "inputs", "review", "run", "outputs"]
INPUT_PANELS = ["idea", "experimental", "template", "guidelines", "figures"]
LEGACY_STEP_PANELS = {
    "idea": "idea",
    "experimental": "experimental",
    "materials": "template",
}
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def _data_root(app: FastAPI) -> Path:
    return Path(app.state.data_root).expanduser()


def _project_or_404(project_id: str, data_root: Path) -> dict[str, Any]:
    project = storage.load_project(project_id, data_root)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return storage.reconcile_project_runs(project, data_root)


def _same_origin_request(origin: str, request: Request) -> bool:
    parsed = urllib.parse.urlparse(origin)
    if not parsed.scheme or not parsed.hostname:
        return False
    request_port = request.url.port or (443 if request.url.scheme == "https" else 80)
    origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return (
        parsed.scheme == request.url.scheme
        and parsed.hostname == request.url.hostname
        and origin_port == request_port
    )


def _workspace_outputs(project: dict[str, Any]) -> list[dict[str, str]]:
    workspace = Path(project["workspace_path"]).expanduser()
    artifacts = storage.collect_workspace_artifacts(workspace)
    atlas_result = project.get("latest_atlas_result") or {}
    result_path = atlas_result.get("result_path")
    if result_path and Path(str(result_path)).exists():
        artifacts.append({"label": "Latest Atlas result", "path": str(result_path)})
    for artifact in artifacts:
        artifact["url_path"] = urllib.parse.quote(artifact["path"])
    return artifacts


def _run_artifacts(run_payload: dict[str, Any] | None) -> list[dict[str, str]]:
    if not run_payload:
        return []
    seen: set[str] = set()
    artifacts: list[dict[str, str]] = []
    for stage_name in run_payload.get("stage_order", []):
        stage_payload = run_payload.get("stages", {}).get(stage_name, {})
        for path in stage_payload.get("artifacts", []):
            candidate = str(path)
            if not candidate or candidate in seen or not Path(candidate).exists():
                continue
            seen.add(candidate)
            artifacts.append({
                "label": f"{stage_name.replace('_', ' ').title()} artifact",
                "path": candidate,
                "url_path": urllib.parse.quote(candidate),
            })
    return artifacts


def _safe_snapshot_path(path: str, allowed_roots: list[Path] | None = None) -> tuple[Path, bool, str | None]:
    candidate = Path(str(path)).expanduser()
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as error:
        return candidate, False, f"Unable to resolve path: {error}"
    if not allowed_roots:
        return resolved, True, None
    resolved_roots: list[Path] = []
    for root in allowed_roots:
        try:
            resolved_roots.append(root.expanduser().resolve(strict=False))
        except OSError:
            continue
    if any(root == resolved or root in resolved.parents for root in resolved_roots):
        return resolved, True, None
    return resolved, False, "Path is outside the selected project workspace and run data."


def _snapshot_path_display(path: str | None, allowed_roots: list[Path]) -> str | None:
    if not path:
        return None
    candidate, allowed, _ = _safe_snapshot_path(str(path), allowed_roots)
    if allowed:
        return str(candidate)
    return candidate.name or None


def _native_sanitize_log_text(text: str, allowed_roots: list[Path]) -> str:
    sanitized_lines: list[str] = []
    for line in text.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            sanitized_lines.append(line)
            continue
        sanitized_lines.append(json.dumps(_native_sanitize_json_value(payload, allowed_roots), ensure_ascii=False))
    return "\n".join(sanitized_lines)


def _native_sanitize_json_value(value: Any, allowed_roots: list[Path]) -> Any:
    if isinstance(value, dict):
        return {key: _native_sanitize_json_value(item, allowed_roots) for key, item in value.items()}
    if isinstance(value, list):
        return [_native_sanitize_json_value(item, allowed_roots) for item in value]
    if isinstance(value, str) and _looks_like_absolute_path(value):
        return _snapshot_path_display(value, allowed_roots) or ""
    return value


def _looks_like_absolute_path(value: str) -> bool:
    if not value or "\n" in value:
        return False
    return Path(value).expanduser().is_absolute()


def _native_artifact_snapshot(label: str, path: str, allowed_roots: list[Path] | None = None) -> dict[str, Any]:
    candidate, allowed, access_issue = _safe_snapshot_path(path, allowed_roots)
    if not allowed:
        return {
            "label": label,
            "path": candidate.name or label,
            "file_name": candidate.name or label,
            "file_extension": candidate.suffix[1:].lower(),
            "exists": False,
            "size_label": "Unavailable",
            "parent_folder": "",
            "last_modified_label": None,
            "access_issue": access_issue,
        }
    try:
        exists = candidate.exists()
    except OSError as error:
        exists = False
        access_issue = f"Unable to inspect path: {error}"
    size_label = "Missing file"
    last_modified_label = None
    if exists:
        try:
            stat = candidate.stat()
            size_label = f"{stat.st_size} bytes"
            last_modified_label = dt.datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="minutes")
        except OSError as error:
            exists = False
            size_label = "Unavailable"
            access_issue = f"Unable to inspect path: {error}"
    return {
        "label": label,
        "path": str(candidate),
        "file_name": candidate.name or label,
        "file_extension": candidate.suffix[1:].lower(),
        "exists": exists,
        "size_label": size_label,
        "parent_folder": str(candidate.parent),
        "last_modified_label": last_modified_label,
        "access_issue": access_issue,
    }


def _native_project_snapshot(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(project.get("project_id", "")),
        "title": str(project.get("title", "") or "Untitled Project"),
        "wizard_step": str(project.get("wizard_step", "") or "setup"),
        "last_status": str(project.get("last_status", "") or "draft"),
        "workspace_path": str(project.get("workspace_path", "") or ""),
        "latest_run_id": project.get("latest_run_id"),
        "updated_at": str(project.get("updated_at", "") or ""),
    }


def _native_validation_snapshot(entry: dict[str, Any] | None, default_completed: bool = False) -> dict[str, Any]:
    payload = dict(entry or {})
    has_blockers = bool(payload.get("has_blockers"))
    return {
        "messages": list(payload.get("messages", []) or []),
        "has_blockers": has_blockers,
        "completed": bool(payload.get("completed", default_completed)) and not has_blockers,
        "updated_at": payload.get("updated_at"),
    }


def _native_input_snapshot(project: dict[str, Any], data_root: Path) -> dict[str, Any]:
    latest_validation = dict(project.get("latest_validation") or {})
    latest_inputs = dict(latest_validation.get("inputs") or {})
    idea = dict(project.get("idea") or {})
    experimental = dict(project.get("experimental") or {})
    template = dict(project.get("template") or {})
    guidelines = dict(project.get("guidelines") or {})
    uploads = dict(project.get("uploads") or {})
    workspace = Path(str(project.get("workspace_path", ""))).expanduser()
    allowed_roots = [workspace, storage.project_dir(str(project.get("project_id", "")), data_root), data_root / "uploads"]
    figures = [_native_figure_snapshot(str(path), allowed_roots) for path in uploads.get("figures", []) or []]
    return {
        "status": str(latest_validation.get("status", "") or "draft"),
        "summary": str(latest_validation.get("summary", "") or ""),
        "has_blockers": bool(latest_validation.get("has_blockers")),
        "updated_at": latest_validation.get("updated_at"),
        "idea": {
            "editor_mode": str(idea.get("editor_mode", "") or "structured"),
            "problem_statement": str(idea.get("problem_statement", "") or ""),
            "core_hypothesis": str(idea.get("core_hypothesis", "") or ""),
            "methodology": str(idea.get("methodology", "") or ""),
            "expected_contribution": str(idea.get("expected_contribution", "") or ""),
            "notes": str(idea.get("notes", "") or ""),
            "raw_markdown": str(idea.get("raw_markdown", "") or ""),
            "validation": _native_validation_snapshot(latest_inputs.get("idea")),
        },
        "experimental": {
            "editor_mode": str(experimental.get("editor_mode", "") or "structured"),
            "setup_text": str(experimental.get("setup_text", "") or ""),
            "raw_numeric_data": str(experimental.get("raw_numeric_data", "") or ""),
            "qualitative_observations": str(experimental.get("qualitative_observations", "") or ""),
            "log_text": str(experimental.get("log_text", "") or ""),
            "source_filename": str(experimental.get("source_filename", "") or ""),
            "validation": _native_validation_snapshot(latest_inputs.get("experimental")),
        },
        "template": {
            "editor_mode": str(template.get("editor_mode", "") or "raw"),
            "text": str(template.get("text", "") or ""),
            "source_filename": str(template.get("source_filename", "") or ""),
            "validation": _native_validation_snapshot(latest_inputs.get("template")),
        },
        "guidelines": {
            "editor_mode": str(guidelines.get("editor_mode", "") or "structured"),
            "deadline": str(guidelines.get("deadline", "") or ""),
            "page_limit": str(guidelines.get("page_limit", "") or ""),
            "required_sections": str(guidelines.get("required_sections", "") or ""),
            "formatting_notes": str(guidelines.get("formatting_notes", "") or ""),
            "guidelines_text": str(guidelines.get("guidelines_text", "") or ""),
            "source_filename": str(guidelines.get("source_filename", "") or ""),
            "validation": _native_validation_snapshot(latest_inputs.get("guidelines")),
        },
        "figures": {
            "items": figures,
            "validation": _native_validation_snapshot(latest_inputs.get("figures"), default_completed=not figures),
        },
    }


def _native_figure_snapshot(path: str, allowed_roots: list[Path]) -> dict[str, Any]:
    artifact = _native_artifact_snapshot(Path(path).name, path, allowed_roots=allowed_roots)
    return {
        "name": artifact["file_name"],
        "path": artifact["path"],
        "size_label": artifact["size_label"],
        "is_missing": not artifact["exists"],
    }


def _native_performance_summary(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    parts: list[str] = []
    if payload.get("wall_seconds") not in {None, ""}:
        parts.append(f"{_native_format_seconds(float(payload['wall_seconds']))} wall")
    if payload.get("total_cpu_seconds") not in {None, ""}:
        parts.append(f"{_native_format_seconds(float(payload['total_cpu_seconds']))} CPU")
    if payload.get("cpu_percent_of_one_core") not in {None, ""}:
        parts.append(f"{round(float(payload['cpu_percent_of_one_core']))}% of one core")
    return " · ".join(parts) or None


def _native_format_seconds(value: float) -> str:
    if value < 10:
        return f"{value:.2f}s"
    if value < 60:
        return f"{value:.1f}s"
    return f"{value:.0f}s"


def _native_substep_snapshot(substep: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(substep.get("name", "") or ""),
        "status": str(substep.get("status", "") or "pending"),
        "summary": str(substep.get("summary", "") or ""),
        "attention_message": (substep.get("attention_required") or {}).get("message"),
        "performance_summary": _native_performance_summary(substep.get("performance")),
    }


def _native_stage_snapshot(name: str, stage_payload: dict[str, Any], allowed_roots: list[Path]) -> dict[str, Any]:
    artifacts = [
        _native_artifact_snapshot(Path(str(path)).name, str(path), allowed_roots=allowed_roots)
        for path in stage_payload.get("artifacts", []) or []
        if str(path)
    ]
    return {
        "name": name,
        "status": str(stage_payload.get("status", "") or "pending"),
        "summary": str(stage_payload.get("summary", "") or ""),
        "attention_message": (stage_payload.get("attention_required") or {}).get("message"),
        "artifacts": artifacts,
        "substeps": [
            _native_substep_snapshot(substep)
            for substep in stage_payload.get("substeps", []) or []
            if isinstance(substep, dict)
        ],
        "performance_summary": _native_performance_summary(stage_payload.get("performance")),
    }


def _native_top_roadblocks(stages: list[dict[str, Any]]) -> list[dict[str, str]]:
    roadblocks: list[dict[str, str]] = []
    for stage in stages:
        message = str(stage.get("attention_message") or "")
        status = str(stage.get("status") or "")
        if not message and status in {"failed", "paused", "interrupted"}:
            message = str(stage.get("summary") or "Stage requires attention.")
        if message:
            roadblocks.append({
                "stage_name": str(stage.get("name") or ""),
                "message": message,
                "status": status,
            })
    return roadblocks[:3]


def _native_log_snapshot(kind: str, path: str, allowed_roots: list[Path]) -> dict[str, Any]:
    candidate, allowed, access_issue = _safe_snapshot_path(path, allowed_roots)
    if not allowed:
        return {
            "kind": kind,
            "path": candidate.name or kind,
            "text": "",
            "line_count": 0,
            "is_truncated": False,
            "error_message": access_issue,
        }
    if not candidate.exists():
        return {
            "kind": kind,
            "path": str(candidate),
            "text": "",
            "line_count": 0,
            "is_truncated": False,
            "error_message": "Log file does not exist.",
        }
    if not candidate.is_file():
        return {
            "kind": kind,
            "path": str(candidate),
            "text": "",
            "line_count": 0,
            "is_truncated": False,
            "error_message": "Log path is not a regular file.",
        }
    try:
        raw = candidate.read_bytes()
    except OSError as error:
        return {
            "kind": kind,
            "path": str(candidate),
            "text": "",
            "line_count": 0,
            "is_truncated": False,
            "error_message": f"Unable to read log file: {error}",
        }
    is_truncated = len(raw) > 65536
    text = raw[-65536:].decode("utf-8", errors="replace")
    if kind == "events":
        text = _native_sanitize_log_text(text, allowed_roots)
    lines = text.splitlines()
    if len(lines) > 80:
        is_truncated = True
        lines = lines[-80:]
    return {
        "kind": kind,
        "path": str(candidate),
        "text": "\n".join(lines),
        "line_count": len(lines),
        "is_truncated": is_truncated,
        "error_message": None,
    }


def _native_last_event(path: Path) -> tuple[str | None, str | None]:
    if not path.exists():
        return None, None
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return None, None
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None, None
    return payload.get("type"), payload.get("at")


def _native_run_diagnostics(project_id: str, run_payload: dict[str, Any], data_root: Path, allowed_roots: list[Path]) -> dict[str, Any]:
    run_id = str(run_payload.get("run_id", "") or "")
    run_root = storage.run_dir(project_id, run_id, data_root)
    events_log_path = run_root / "events.jsonl"
    last_event_type, last_event_at = _native_last_event(events_log_path)
    stdout_path = run_payload.get("worker_stdout_log_path")
    stderr_path = run_payload.get("worker_stderr_log_path")
    logs: list[dict[str, Any]] = []
    if stdout_path:
        logs.append(_native_log_snapshot("stdout", str(stdout_path), allowed_roots))
    if stderr_path:
        logs.append(_native_log_snapshot("stderr", str(stderr_path), allowed_roots))
    logs.append(_native_log_snapshot("events", str(events_log_path), allowed_roots))
    pid_value = run_payload.get("worker_pid") or run_payload.get("pid")
    return {
        "worker_state": str(run_payload.get("worker_state") or ("missing" if not pid_value else run_payload.get("status", "unknown"))),
        "pid": str(pid_value) if pid_value is not None else None,
        "started_at": run_payload.get("worker_started_at") or run_payload.get("started_at"),
        "stdout_log_path": _snapshot_path_display(str(stdout_path), allowed_roots) if stdout_path else None,
        "stderr_log_path": _snapshot_path_display(str(stderr_path), allowed_roots) if stderr_path else None,
        "run_folder_path": str(run_root),
        "events_log_path": str(events_log_path),
        "last_event_type": last_event_type,
        "last_event_at": last_event_at,
        "attention_message": (run_payload.get("attention_required") or {}).get("message"),
        "logs": logs,
    }


def _native_run_snapshot(project: dict[str, Any], run_payload: dict[str, Any] | None, data_root: Path) -> dict[str, Any] | None:
    if not run_payload:
        return None
    project_id = str(project.get("project_id", "") or "")
    workspace_path = Path(str(project.get("workspace_path", ""))).expanduser()
    run_root = storage.run_dir(project_id, str(run_payload.get("run_id", "") or ""), data_root)
    allowed_roots = [workspace_path, storage.project_dir(project_id, data_root), run_root]
    stage_names = list(run_payload.get("stage_order", []) or run_payload.get("stages", {}).keys())
    stages = [
        _native_stage_snapshot(stage_name, run_payload.get("stages", {}).get(stage_name, {}), allowed_roots)
        for stage_name in stage_names
    ]
    artifacts: list[dict[str, Any]] = []
    for item in _workspace_outputs(project):
        artifacts.append(_native_artifact_snapshot(str(item.get("label", "")), str(item.get("path", "")), allowed_roots=allowed_roots))
    for stage in stages:
        artifacts.extend(stage.get("artifacts", []) or [])
    for key, label in [("result_path", "Atlas Result"), ("log_path", "Run Log")]:
        if run_payload.get(key):
            artifacts.append(_native_artifact_snapshot(label, str(run_payload[key]), allowed_roots=allowed_roots))
    for path in run_payload.get("screenshot_paths", []) or []:
        artifacts.append(_native_artifact_snapshot(Path(str(path)).name, str(path), allowed_roots=allowed_roots))
    deduped_artifacts: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for artifact in artifacts:
        path = str(artifact.get("path", ""))
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        deduped_artifacts.append(artifact)
    final_pdf_path = workspace_path / "final" / "paper.pdf"
    return {
        "id": str(run_payload.get("run_id", "") or ""),
        "source": "pipeline" if run_payload.get("kind") == "pipeline_v2" else "atlasLegacy",
        "status": str(run_payload.get("status", "") or "queued"),
        "current_stage": str(run_payload.get("current_stage") or run_payload.get("stage") or ""),
        "summary": str(run_payload.get("summary", "") or ""),
        "final_pdf_path": str(final_pdf_path) if final_pdf_path.exists() else None,
        "artifacts": deduped_artifacts,
        "stages": stages,
        "top_roadblocks": _native_top_roadblocks(stages),
        "diagnostics": _native_run_diagnostics(project_id, run_payload, data_root, allowed_roots),
    }


def _native_integration_snapshot(request: Request, data_root: Path) -> dict[str, Any]:
    health = _integration_summary()
    python_executable = storage.repo_python_executable()
    python_configured = python_executable.exists() or shutil.which(str(python_executable)) is not None
    data_root_readable = not data_root.exists() or os.access(data_root, os.R_OK)
    data_root_issue = None
    if not data_root_readable:
        data_root_issue = f"The PaperOrchestra data root exists at {data_root} but is not readable by the current user."
    return {
        "backend_reachable": True,
        "repo_configured": storage.REPO_ROOT.exists(),
        "python_configured": python_configured,
        "data_root_readable": data_root_readable,
        "data_root_issue": data_root_issue,
        "data_root": str(data_root),
        "host": request.url.hostname or "127.0.0.1",
        "port": request.url.port or 0,
        "codex": health.get("codex", {}),
        "atlas": health.get("atlas", {}),
        "browser_adapter": health.get("browser_adapter", {}),
        "figure_backend": health.get("figure_backend", {}),
    }


def _integration_summary() -> dict[str, object]:
    summary = dict(config.integration_health())
    summary.setdefault("chrome", {
        "available": False,
        "enabled": False,
        "compatible": False,
        "version": "",
        "path": "",
        "mcp_available": False,
        "attach_mode": "chrome_for_testing_first",
        "plausibly_attachable": False,
    })
    summary.setdefault("chrome_for_testing", {
        "runtime": "chrome_for_testing",
        "installed": False,
        "version": "",
        "profile_root": "",
        "profile_exists": False,
        "account_present": False,
        "account_label": "",
        "running": False,
        "debuggable": False,
        "browser_url": "",
        "relaunch_required": False,
    })
    summary.setdefault("chrome_stable", {
        "runtime": "chrome_stable",
        "installed": False,
        "version": "",
        "profile_root": "",
        "profile_exists": False,
        "account_present": False,
        "account_label": "",
        "running": False,
        "debuggable": False,
        "browser_url": "",
        "relaunch_required": False,
    })
    summary.setdefault("browser_adapter", {
        "strategy": "chrome_for_testing_first",
        "primary": "chrome_devtools",
        "attach_mode": "chrome_for_testing_first",
        "fallback_order": ["chrome_for_testing", "chrome_stable", "atlas", "local"],
        "atlas_fallback_enabled": True,
        "local_fallback_enabled": True,
    })
    return summary


def _normalize_input_panel(panel: str | None) -> str:
    candidate = str(panel or "").strip().lower()
    if candidate in INPUT_PANELS:
        return candidate
    return "idea"


def _project_input_validation(project: dict[str, Any], data_root: Path) -> dict[str, Any]:
    latest = project.get("latest_validation")
    if latest and latest.get("inputs"):
        return latest
    validation = storage.validate_project_inputs(project, data_root)
    storage.update_latest_validation(project, validation, data_root)
    return validation


def _figure_manifest(project: dict[str, Any]) -> list[dict[str, str]]:
    manifest: list[dict[str, str]] = []
    for path in project.get("uploads", {}).get("figures", []):
        candidate = Path(str(path))
        if not candidate.exists():
            continue
        manifest.append({
            "name": candidate.name,
            "path": str(candidate),
            "url_path": urllib.parse.quote(str(candidate)),
            "size_label": f"{candidate.stat().st_size} bytes",
        })
    return manifest


def _input_panels(project: dict[str, Any], validation: dict[str, Any]) -> list[dict[str, Any]]:
    status_map = validation.get("inputs", {})
    labels = {
        "idea": "Idea",
        "experimental": "Experimental Log",
        "template": "Template",
        "guidelines": "Guidelines",
        "figures": "Figures",
    }
    panels: list[dict[str, Any]] = []
    for name in INPUT_PANELS:
        entry = status_map.get(name, {})
        messages = list(entry.get("messages", []))
        panels.append({
            "name": name,
            "label": labels[name],
            "messages": messages,
            "has_blockers": bool(entry.get("has_blockers")),
            "completed": bool(entry.get("completed")) and not bool(entry.get("has_blockers")),
        })
    return panels


def _parse_iso_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_clock_label(value: str | None) -> str:
    parsed = _parse_iso_timestamp(value)
    if parsed is None:
        return ""
    local_value = parsed.astimezone()
    hour = local_value.strftime("%I").lstrip("0") or "0"
    return f"{hour}:{local_value.strftime('%M:%S %p')}"


def _format_duration_label(started_at: str | None, finished_at: str | None) -> str:
    started = _parse_iso_timestamp(started_at)
    finished = _parse_iso_timestamp(finished_at)
    if started is None or finished is None or finished < started:
        return ""
    total_seconds = int((finished - started).total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _decorate_stage_payload(stage_payload: dict[str, Any]) -> dict[str, Any]:
    started_label = _format_clock_label(stage_payload.get("started_at"))
    finished_label = _format_clock_label(stage_payload.get("finished_at"))
    duration_label = _format_duration_label(stage_payload.get("started_at"), stage_payload.get("finished_at"))
    decorated = dict(stage_payload)
    decorated["timing_items"] = [
        {"label": "Attempt", "value": str(stage_payload.get("attempt", 1) or 1)},
    ]
    if started_label:
        decorated["timing_items"].append({"label": "Started", "value": started_label})
    elif str(stage_payload.get("status", "") or "") == "pending":
        decorated["timing_items"].append({"label": "State", "value": "Pending"})
    if finished_label:
        decorated["timing_items"].append({"label": "Finished", "value": finished_label})
    elif str(stage_payload.get("status", "") or "") == "running":
        decorated["timing_items"].append({"label": "State", "value": "Running"})
    if duration_label:
        decorated["timing_items"].append({"label": "Duration", "value": duration_label})
    substeps: list[dict[str, Any]] = []
    for substep in stage_payload.get("substeps", []) or []:
        started = _format_clock_label(substep.get("started_at"))
        finished = _format_clock_label(substep.get("finished_at"))
        duration = _format_duration_label(substep.get("started_at"), substep.get("finished_at"))
        decorated_substep = dict(substep)
        decorated_substep["timing_label"] = " · ".join(
            item
            for item in [started, finished, duration]
            if item
        )
        substeps.append(decorated_substep)
    decorated["substeps"] = substeps
    loop_state = dict(stage_payload.get("loop_state") or {})
    if loop_state:
        trajectory = []
        for item in loop_state.get("score_trajectory", []) or []:
            if not isinstance(item, dict):
                continue
            iteration = item.get("iteration")
            score = item.get("overall_score")
            decision = str(item.get("decision", "") or "").replace("_", " ").title()
            label = f"iter{iteration}"
            if score not in {None, ""}:
                label += f" {score}"
            if decision:
                label += f" · {decision}"
            trajectory.append(label)
        loop_state["trajectory_labels"] = trajectory
    decorated["loop_state"] = loop_state or None
    return decorated


def _decorate_run_payload(run_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not run_payload:
        return None
    decorated = dict(run_payload)
    stages: dict[str, Any] = {}
    for stage_name in run_payload.get("stage_order", []):
        stages[stage_name] = _decorate_stage_payload(run_payload.get("stages", {}).get(stage_name, {}))
    decorated["stages"] = stages
    return decorated


def _timeline_detail(stage_payload: dict[str, Any]) -> str:
    for substep in stage_payload.get("substeps", []) or []:
        if str(substep.get("status", "") or "") == "running":
            return str(substep.get("summary", "") or substep.get("name", "") or "")
    for item in stage_payload.get("timing_items", []):
        if item.get("label") == "Duration":
            return str(item.get("value", ""))
    for item in stage_payload.get("timing_items", []):
        if item.get("label") in {"Finished", "Started", "State"}:
            return str(item.get("value", ""))
    return ""


def _decorated_run_or_404(project_id: str, run_id: str, data_root: Path) -> dict[str, Any]:
    run_payload = storage.load_run(project_id, run_id, data_root)
    if not run_payload:
        raise HTTPException(status_code=404, detail="Run not found.")
    return _decorate_run_payload(storage.reconcile_run(run_payload, data_root)) or {}


def _run_timeline_items(run_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not run_payload:
        return []
    items: list[dict[str, Any]] = []
    current_stage = str(run_payload.get("current_stage", "") or "")
    for stage_name in run_payload.get("stage_order", []):
        stage_payload = run_payload.get("stages", {}).get(stage_name, {})
        items.append({
            "name": stage_name,
            "label": stage_name.replace("_", " ").title(),
            "status": str(stage_payload.get("status", "pending") or "pending"),
            "is_current": stage_name == current_stage,
            "is_parallel": stage_name in {"plotting", "literature"},
            "detail": _timeline_detail(stage_payload),
        })
    return items


def _project_context(project: dict[str, Any], data_root: Path, step: str | None = None, panel: str | None = None) -> dict[str, Any]:
    latest_run = _decorate_run_payload(project.get("latest_run"))
    integrations = _integration_summary()
    effective_step = step or project.get("wizard_step", "setup")
    validation = project.get("latest_validation") or {}
    if effective_step in {"inputs", "review"}:
        validation = _project_input_validation(project, data_root)
    panels = _input_panels(project, validation) if effective_step in {"inputs", "review"} else []
    next_incomplete = next((item["name"] for item in panels if not item["completed"]), "idea")
    atlas_result = project.get("latest_atlas_result") or {}
    atlas_result_copy = dict(atlas_result)
    if atlas_result_copy.get("result_path"):
        atlas_result_copy["result_url"] = urllib.parse.quote(str(atlas_result_copy["result_path"]))
    if atlas_result_copy.get("response_path"):
        atlas_result_copy["response_url"] = urllib.parse.quote(str(atlas_result_copy["response_path"]))
    screenshot_items: list[dict[str, str]] = []
    for index, path in enumerate(atlas_result_copy.get("screenshot_paths", []) or [], start=1):
        candidate = str(path)
        if not candidate or not Path(candidate).exists():
            continue
        screenshot_items.append({
            "label": f"Atlas screenshot {index}",
            "path": candidate,
            "url_path": urllib.parse.quote(candidate),
        })
    atlas_result_copy["screenshots"] = screenshot_items
    browser_result = project.get("latest_browser_result") or {}
    browser_result_copy = dict(browser_result)
    if browser_result_copy.get("result_path"):
        browser_result_copy["result_url"] = urllib.parse.quote(str(browser_result_copy["result_path"]))
    response_candidate = str(
        browser_result_copy.get("response_path")
        or browser_result_copy.get("raw_response_path")
        or ""
    ).strip()
    if response_candidate:
        browser_result_copy["response_url"] = urllib.parse.quote(response_candidate)
    browser_screenshots: list[dict[str, str]] = []
    for index, path in enumerate(browser_result_copy.get("screenshot_paths", []) or [], start=1):
        candidate = str(path)
        if not candidate or not Path(candidate).exists():
            continue
        browser_screenshots.append({
            "label": f"Browser screenshot {index}",
            "path": candidate,
            "url_path": urllib.parse.quote(candidate),
        })
    browser_result_copy["screenshots"] = browser_screenshots
    final_message = ""
    if latest_run and latest_run.get("final_message_path"):
        message_path = Path(str(latest_run["final_message_path"]))
        if message_path.exists():
            final_message = message_path.read_text(encoding="utf-8", errors="replace")
    final_pdf = ""
    if latest_run:
        workspace_path = Path(str(project["workspace_path"])).expanduser()
        final_pdf_path = workspace_path / "final" / "paper.pdf"
        if final_pdf_path.exists():
            final_pdf = urllib.parse.quote(str(final_pdf_path))
    return {
        "project": project,
        "step": effective_step,
        "steps": STEPS,
        "active_input_panel": _normalize_input_panel(panel or next_incomplete),
        "input_panels": panels,
        "input_validation": validation,
        "next_input_panel": next_incomplete,
        "figure_manifest": _figure_manifest(project),
        "integrations": integrations,
        "browser_result": browser_result_copy,
        "atlas_result": atlas_result_copy,
        "artifacts": _workspace_outputs(project),
        "run_artifacts": _run_artifacts(latest_run),
        "latest_run": latest_run,
        "run_timeline_items": _run_timeline_items(latest_run),
        "final_message": final_message,
        "final_pdf_url": final_pdf,
        "run_stream_url": (
            f"/api/projects/{project['project_id']}/runs/{latest_run['run_id']}/events"
            if latest_run else ""
        ),
    }


def _manual_browser_literature_prompt(workspace: Path, mode_label: str = "configured browser adapter stack") -> str:
    return "\n".join([
        f"Use the {mode_label} for the PaperOrchestra workspace at `{workspace}`.",
        "Find the strongest citations and summarize how they relate to the proposed work.",
        "Return a concise research brief that can be post-processed into refs.bib and intro/related-work text.",
    ])


@contextmanager
def _temporary_browser_attach_mode(attach_mode: str, browser_url: str = "", ws_endpoint: str = ""):
    previous_attach_mode = os.environ.get("PAPERORCHESTRA_CHROME_ATTACH_MODE")
    previous_browser_url = os.environ.get("PAPERORCHESTRA_CHROME_BROWSER_URL")
    previous_ws_endpoint = os.environ.get("PAPERORCHESTRA_CHROME_WS_ENDPOINT")
    os.environ["PAPERORCHESTRA_CHROME_ATTACH_MODE"] = attach_mode
    if browser_url:
        os.environ["PAPERORCHESTRA_CHROME_BROWSER_URL"] = browser_url
    else:
        os.environ.pop("PAPERORCHESTRA_CHROME_BROWSER_URL", None)
    if ws_endpoint:
        os.environ["PAPERORCHESTRA_CHROME_WS_ENDPOINT"] = ws_endpoint
    else:
        os.environ.pop("PAPERORCHESTRA_CHROME_WS_ENDPOINT", None)
    try:
        yield
    finally:
        if previous_attach_mode is None:
            os.environ.pop("PAPERORCHESTRA_CHROME_ATTACH_MODE", None)
        else:
            os.environ["PAPERORCHESTRA_CHROME_ATTACH_MODE"] = previous_attach_mode
        if previous_browser_url is None:
            os.environ.pop("PAPERORCHESTRA_CHROME_BROWSER_URL", None)
        else:
            os.environ["PAPERORCHESTRA_CHROME_BROWSER_URL"] = previous_browser_url
        if previous_ws_endpoint is None:
            os.environ.pop("PAPERORCHESTRA_CHROME_WS_ENDPOINT", None)
        else:
            os.environ["PAPERORCHESTRA_CHROME_WS_ENDPOINT"] = previous_ws_endpoint


async def _read_upload(upload: Any) -> tuple[str, bytes] | None:
    if upload is None:
        return None
    filename = getattr(upload, "filename", "") or ""
    if not filename:
        return None
    data = await upload.read()
    if not data:
        return None
    return filename, data


async def _json_payload(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object.")
    return payload


def _payload_value(payload: dict[str, Any], key: str, default: str = "") -> str:
    fields = payload.get("fields")
    if isinstance(fields, dict) and key in fields:
        raw = fields[key]
    else:
        raw = payload.get(key, default)
    if isinstance(raw, list):
        raw = raw[0] if raw else default
    if raw is None:
        return default
    return str(raw)


async def _input_payload(request: Request) -> tuple[dict[str, Any], dict[str, list[tuple[str, bytes]]]]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        return await _json_payload(request), {}

    form = await request.form()
    payload: dict[str, Any] = {"fields": {}}
    uploads: dict[str, list[tuple[str, bytes]]] = {}
    fields = payload["fields"]
    for key, value in form.multi_items():
        parsed = await _read_upload(value)
        if parsed:
            uploads.setdefault(key, []).append(parsed)
            continue
        fields.setdefault(key, []).append(str(value))
    return payload, uploads


def _first_upload(
    uploads: dict[str, list[tuple[str, bytes]]],
    field_name: str,
) -> tuple[str, bytes] | None:
    items = uploads.get(field_name, [])
    return items[0] if items else None


def _save_input_uploads(
    project: dict[str, Any],
    input_name: str,
    uploads: dict[str, list[tuple[str, bytes]]],
    data_root: Path,
) -> None:
    project_id = str(project["project_id"])

    if input_name == "idea":
        upload = _first_upload(uploads, "idea_upload")
        if upload:
            _, content = upload
            raw_markdown = content.decode("utf-8", errors="replace")
            idea = project.get("idea", {})
            idea.update(storage.parse_idea_markdown(raw_markdown))
            idea["raw_markdown"] = raw_markdown
            project["idea"] = idea

    elif input_name == "experimental":
        upload = _first_upload(uploads, "experimental_upload")
        if upload:
            filename, content = upload
            experimental = project.get("experimental", {})
            experimental["log_text"] = content.decode("utf-8", errors="replace")
            experimental["source_filename"] = filename
            experimental.update(storage.parse_experimental_log(experimental["log_text"]))
            project["experimental"] = experimental

    elif input_name == "template":
        upload = _first_upload(uploads, "template_upload")
        if upload:
            filename, content = upload
            template = project.get("template", {})
            project.setdefault("uploads", {})
            project["uploads"]["template_tex"] = storage.store_uploaded_file(project_id, "template", filename, content, data_root)
            template["text"] = content.decode("utf-8", errors="replace")
            template["source_filename"] = filename
            project["template"] = template

    elif input_name == "guidelines":
        upload = _first_upload(uploads, "guidelines_upload")
        if upload:
            filename, content = upload
            guidelines = project.get("guidelines", {})
            stored_path = storage.store_uploaded_file(project_id, "guidelines", filename, content, data_root)
            guidelines["source_filename"] = filename
            if filename.lower().endswith(".pdf"):
                guidelines["guidelines_text"] = guidelines.get("guidelines_text") or f"[PDF uploaded at {stored_path}. Paste a text summary here for the pipeline.]"
            else:
                guidelines["guidelines_text"] = content.decode("utf-8", errors="replace")
                guidelines.update(storage.parse_guidelines_text(guidelines["guidelines_text"]))
            project["guidelines"] = guidelines

    elif input_name == "figures":
        uploaded_figures = uploads.get("figure_uploads", [])
        if uploaded_figures:
            project.setdefault("uploads", {})
            current_figures = list(project["uploads"].get("figures", []))
            for filename, content in uploaded_figures:
                current_figures.append(storage.store_uploaded_file(project_id, "figures", filename, content, data_root))
            project["uploads"]["figures"] = current_figures


def _json_project_response(project: dict[str, Any], data_root: Path) -> JSONResponse:
    return JSONResponse({
        "project": storage.reconcile_project_runs(project, data_root),
    })


def _save_setup_payload(project: dict[str, Any], payload: dict[str, Any], data_root: Path) -> dict[str, Any]:
    project["setup"].update({
        "title": _payload_value(payload, "title"),
        "venue": _payload_value(payload, "venue"),
        "description": _payload_value(payload, "description"),
    })
    project["title"] = project["setup"]["title"] or project["title"]
    project["venue"] = project["setup"]["venue"]
    project["description"] = project["setup"]["description"]
    project.setdefault("ingest", {})
    project["ingest"]["source_directory"] = _payload_value(payload, "source_directory").strip()
    project["ingest"]["enabled"] = bool(project["ingest"]["source_directory"])
    project["wizard_step"] = "inputs"
    storage.save_project(project, data_root)
    return storage.sync_workspace(project, data_root)


def _save_input_payload(
    project: dict[str, Any],
    input_name: str,
    payload: dict[str, Any],
    data_root: Path,
) -> dict[str, Any]:
    project["wizard_step"] = "inputs"

    if input_name == "idea":
        idea = project.get("idea", {})
        editor_mode = _payload_value(payload, "editor_mode", "structured") or "structured"
        idea["editor_mode"] = editor_mode
        if editor_mode == "raw":
            raw_markdown = _payload_value(payload, "raw_markdown")
            idea.update(storage.parse_idea_markdown(raw_markdown))
            idea["raw_markdown"] = raw_markdown
        else:
            idea.update({
                "problem_statement": _payload_value(payload, "problem_statement"),
                "core_hypothesis": _payload_value(payload, "core_hypothesis"),
                "methodology": _payload_value(payload, "methodology"),
                "expected_contribution": _payload_value(payload, "expected_contribution"),
                "notes": _payload_value(payload, "notes"),
            })
            idea["raw_markdown"] = storage.idea_markdown({"idea": idea})
        project["idea"] = idea

    elif input_name == "experimental":
        experimental = project.get("experimental", {})
        editor_mode = _payload_value(payload, "editor_mode", "structured") or "structured"
        experimental["editor_mode"] = editor_mode
        if editor_mode == "raw":
            raw_markdown = _payload_value(payload, "raw_markdown")
            experimental.update(storage.parse_experimental_log(raw_markdown))
            experimental["log_text"] = raw_markdown
        else:
            experimental.update({
                "setup_text": _payload_value(payload, "setup_text"),
                "raw_numeric_data": _payload_value(payload, "raw_numeric_data"),
                "qualitative_observations": _payload_value(payload, "qualitative_observations"),
            })
            experimental["log_text"] = storage.experimental_markdown({"experimental": experimental})
        project["experimental"] = experimental

    elif input_name == "template":
        template = project.get("template", {})
        template["editor_mode"] = "raw"
        template["text"] = _payload_value(payload, "template_text", _payload_value(payload, "text"))
        project["template"] = template

    elif input_name == "guidelines":
        guidelines = project.get("guidelines", {})
        editor_mode = _payload_value(payload, "editor_mode", "structured") or "structured"
        guidelines["editor_mode"] = editor_mode
        if editor_mode == "raw":
            raw_text = _payload_value(payload, "guidelines_text")
            guidelines["guidelines_text"] = raw_text
            guidelines.update(storage.parse_guidelines_text(raw_text))
        else:
            guidelines.update({
                "deadline": _payload_value(payload, "deadline"),
                "page_limit": _payload_value(payload, "page_limit"),
                "required_sections": _payload_value(payload, "required_sections"),
                "formatting_notes": _payload_value(payload, "formatting_notes"),
            })
            guidelines["guidelines_text"] = storage.guidelines_markdown({"guidelines": guidelines})
        project["guidelines"] = guidelines

    elif input_name == "figures":
        uploads = project.get("uploads", {})
        figure_values = payload.get("figures", uploads.get("figures", []))
        if not isinstance(figure_values, list):
            raise HTTPException(status_code=400, detail="figures must be a list of paths.")
        uploads["figures"] = [str(item) for item in figure_values if str(item).strip()]
        project["uploads"] = uploads

    else:
        raise HTTPException(status_code=404, detail="Unknown input.")

    storage.save_project(project, data_root)
    validation = storage.validate_project_inputs(project, data_root)
    refreshed = storage.load_project(project["project_id"], data_root) or project
    storage.update_latest_validation(refreshed, validation, data_root)
    return storage.load_project(project["project_id"], data_root) or refreshed


def _api_run_response(project_id: str, run_id: str, data_root: Path, status_code: int = 200) -> JSONResponse:
    return JSONResponse({
        "run": _decorated_run_or_404(project_id, run_id, data_root),
    }, status_code=status_code)


def create_app(data_root: Path | None = None) -> FastAPI:
    config.load_runtime_env()
    app = FastAPI(title="PaperOrchestra Control Room")
    configured_root = data_root or Path(
        os.environ.get("PAPERORCHESTRA_GUI_DATA_ROOT", str(storage.DEFAULT_DATA_ROOT))
    ).expanduser()
    app.state.data_root = str(storage.get_paths(configured_root).data_root)
    app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")

    @app.middleware("http")
    async def reject_cross_origin_mutations(request: Request, call_next):
        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and not _same_origin_request(origin, request):
                return JSONResponse(
                    {"error": "cross_origin_forbidden", "message": "Cross-origin mutation requests are not allowed."},
                    status_code=403,
                )
        return await call_next(request)

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "data_root": str(_data_root(app)),
            "integrations": _integration_summary(),
        })

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        projects = [storage.reconcile_project_runs(project, _data_root(app)) for project in storage.list_projects(_data_root(app))]
        return TEMPLATES.TemplateResponse(
            request,
            "dashboard.html",
            {
                "projects": projects,
                "integrations": _integration_summary(),
            },
        )

    @app.post("/projects")
    async def create_project(request: Request) -> RedirectResponse:
        form = await request.form()
        project = storage.create_project(
            title=str(form.get("title", "")),
            venue=str(form.get("venue", "")),
            description=str(form.get("description", "")),
            data_root=_data_root(app),
            source_directory=str(form.get("source_directory", "")),
        )
        return RedirectResponse(f"/projects/{project['project_id']}?step=setup", status_code=303)

    @app.get("/api/projects")
    async def api_projects() -> JSONResponse:
        projects = [
            storage.reconcile_project_runs(project, _data_root(app))
            for project in storage.list_projects(_data_root(app))
        ]
        return JSONResponse({"projects": projects})

    @app.post("/api/projects")
    async def api_create_project(request: Request) -> JSONResponse:
        payload = await _json_payload(request)
        project = storage.create_project(
            title=_payload_value(payload, "title"),
            venue=_payload_value(payload, "venue"),
            description=_payload_value(payload, "description"),
            workspace_path=_payload_value(payload, "workspace_path") or None,
            data_root=_data_root(app),
            source_directory=_payload_value(payload, "source_directory"),
        )
        return JSONResponse({"project": storage.reconcile_project_runs(project, _data_root(app))}, status_code=201)

    @app.get("/api/projects/{project_id}")
    async def api_project(project_id: str) -> JSONResponse:
        return _json_project_response(_project_or_404(project_id, _data_root(app)), _data_root(app))

    @app.post("/api/projects/{project_id}/setup")
    async def api_save_setup(project_id: str, request: Request) -> JSONResponse:
        project = _project_or_404(project_id, _data_root(app))
        payload = await _json_payload(request)
        saved = _save_setup_payload(project, payload, _data_root(app))
        return _json_project_response(saved, _data_root(app))

    @app.post("/api/projects/{project_id}/inputs/{input_name}")
    async def api_save_input(project_id: str, input_name: str, request: Request) -> JSONResponse:
        if input_name not in INPUT_PANELS:
            raise HTTPException(status_code=404, detail="Unknown input.")
        project = _project_or_404(project_id, _data_root(app))
        payload, uploads = await _input_payload(request)
        saved = _save_input_payload(project, input_name, payload, _data_root(app))
        _save_input_uploads(saved, input_name, uploads, _data_root(app))
        saved = storage.save_project(saved, _data_root(app))
        validation = storage.validate_project_inputs(saved, _data_root(app))
        saved = storage.load_project(project_id, _data_root(app)) or saved
        storage.update_latest_validation(saved, validation, _data_root(app))
        saved = storage.load_project(project_id, _data_root(app)) or saved
        validation = saved.get("latest_validation") or {}
        return JSONResponse({
            "project": storage.reconcile_project_runs(saved, _data_root(app)),
            "validation": validation,
            "input": validation.get("inputs", {}).get(input_name, {}),
        })

    @app.post("/api/projects/{project_id}/inputs/figures/remove")
    async def api_remove_figure(project_id: str, request: Request) -> JSONResponse:
        project = _project_or_404(project_id, _data_root(app))
        payload = await _json_payload(request)
        remove_path = _payload_value(payload, "path").strip()
        uploads = project.get("uploads", {})
        uploads["figures"] = [item for item in uploads.get("figures", []) if str(item) != remove_path]
        project["uploads"] = uploads
        storage.save_project(project, _data_root(app))
        validation = storage.validate_project_inputs(project, _data_root(app))
        refreshed = storage.load_project(project_id, _data_root(app)) or project
        storage.update_latest_validation(refreshed, validation, _data_root(app))
        refreshed = storage.load_project(project_id, _data_root(app)) or refreshed
        return JSONResponse({
            "project": storage.reconcile_project_runs(refreshed, _data_root(app)),
            "validation": refreshed.get("latest_validation") or {},
            "input": (refreshed.get("latest_validation") or {}).get("inputs", {}).get("figures", {}),
        })

    @app.get("/api/projects/{project_id}/artifacts")
    async def api_project_artifacts(project_id: str) -> JSONResponse:
        project = _project_or_404(project_id, _data_root(app))
        latest_run = project.get("latest_run")
        return JSONResponse({
            "workspace_artifacts": _workspace_outputs(project),
            "run_artifacts": _run_artifacts(latest_run),
        })

    @app.get("/api/workspace/snapshot")
    async def api_workspace_snapshot(
        request: Request,
        selected_project_id: str = "",
        selected_run_id: str = "",
        selected_stage_name: str = "",
    ) -> JSONResponse:
        data_root = _data_root(app)
        projects = [
            storage.reconcile_project_runs(project, data_root)
            for project in storage.list_projects(data_root)
        ]
        selected_project = next(
            (project for project in projects if project.get("project_id") == selected_project_id),
            projects[0] if projects else None,
        )
        selected_run_payload = None
        if selected_project:
            if selected_run_id:
                raw_run = storage.load_run(str(selected_project["project_id"]), selected_run_id, data_root)
                if raw_run:
                    selected_run_payload = _decorate_run_payload(storage.reconcile_run(raw_run, data_root))
            else:
                selected_run_payload = _decorate_run_payload(selected_project.get("latest_run"))
        selected_run = _native_run_snapshot(selected_project, selected_run_payload, data_root) if selected_project else None
        selected_stage = None
        if selected_run:
            stages = selected_run.get("stages", [])
            selected_stage = next(
                (stage for stage in stages if stage.get("name") == selected_stage_name),
                next((stage for stage in stages if stage.get("name") == selected_run.get("current_stage")), stages[0] if stages else None),
            )
        return JSONResponse({
            "projects": [_native_project_snapshot(project) for project in projects],
            "selected_project": _native_project_snapshot(selected_project) if selected_project else None,
            "selected_project_inputs": _native_input_snapshot(selected_project, data_root) if selected_project else None,
            "selected_run": selected_run,
            "selected_stage": selected_stage,
            "integrations": _native_integration_snapshot(request, data_root),
        })

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    async def project_page(project_id: str, request: Request, step: str = "setup", panel: str = "") -> HTMLResponse:
        project = _project_or_404(project_id, _data_root(app))
        if step in LEGACY_STEP_PANELS:
            legacy_panel = LEGACY_STEP_PANELS[step]
            return RedirectResponse(f"/projects/{project_id}?step=inputs&panel={legacy_panel}", status_code=307)
        return TEMPLATES.TemplateResponse(request, "project.html", _project_context(project, _data_root(app), step, panel))

    def _persist_inputs(project: dict[str, Any]) -> dict[str, Any]:
        storage.save_project(project, _data_root(app))
        validation = storage.validate_project_inputs(project, _data_root(app))
        refreshed = storage.load_project(project["project_id"], _data_root(app)) or project
        storage.update_latest_validation(refreshed, validation, _data_root(app))
        return storage.load_project(project["project_id"], _data_root(app)) or refreshed

    @app.post("/projects/{project_id}/save/setup")
    async def save_setup(project_id: str, request: Request) -> RedirectResponse:
        project = _project_or_404(project_id, _data_root(app))
        form = await request.form()
        project["setup"].update({
            "title": str(form.get("title", "")),
            "venue": str(form.get("venue", "")),
            "description": str(form.get("description", "")),
        })
        project["title"] = project["setup"]["title"] or project["title"]
        project["venue"] = project["setup"]["venue"]
        project["description"] = project["setup"]["description"]
        project.setdefault("ingest", {})
        project["ingest"]["source_directory"] = str(form.get("source_directory", "")).strip()
        project["ingest"]["enabled"] = bool(project["ingest"]["source_directory"])
        project["wizard_step"] = "inputs"
        storage.save_project(project, _data_root(app))
        storage.sync_workspace(project, _data_root(app))
        return RedirectResponse(f"/projects/{project_id}?step=inputs&panel=idea", status_code=303)

    @app.post("/projects/{project_id}/save/input/{input_name}")
    async def save_input(project_id: str, input_name: str, request: Request) -> RedirectResponse:
        project = _project_or_404(project_id, _data_root(app))
        form = await request.form()
        project["wizard_step"] = "inputs"

        if input_name == "idea":
            idea = project.get("idea", {})
            editor_mode = str(form.get("editor_mode", "structured") or "structured")
            idea["editor_mode"] = editor_mode
            upload = await _read_upload(form.get("idea_upload"))
            if upload:
                _, content = upload
                raw_markdown = content.decode("utf-8", errors="replace")
                idea.update(storage.parse_idea_markdown(raw_markdown))
                idea["raw_markdown"] = raw_markdown
            elif editor_mode == "raw":
                raw_markdown = str(form.get("raw_markdown", ""))
                idea.update(storage.parse_idea_markdown(raw_markdown))
                idea["raw_markdown"] = raw_markdown
            else:
                idea.update({
                    "problem_statement": str(form.get("problem_statement", "")),
                    "core_hypothesis": str(form.get("core_hypothesis", "")),
                    "methodology": str(form.get("methodology", "")),
                    "expected_contribution": str(form.get("expected_contribution", "")),
                    "notes": str(form.get("notes", "")),
                })
                idea["raw_markdown"] = storage.idea_markdown({"idea": idea})
            project["idea"] = idea
            _persist_inputs(project)
            return RedirectResponse(f"/projects/{project_id}?step=inputs&panel=idea", status_code=303)

        if input_name == "experimental":
            experimental = project.get("experimental", {})
            editor_mode = str(form.get("editor_mode", "structured") or "structured")
            experimental["editor_mode"] = editor_mode
            if editor_mode == "raw":
                raw_markdown = str(form.get("raw_markdown", ""))
                experimental.update(storage.parse_experimental_log(raw_markdown))
                experimental["log_text"] = raw_markdown
            else:
                experimental.update({
                    "setup_text": str(form.get("setup_text", "")),
                    "raw_numeric_data": str(form.get("raw_numeric_data", "")),
                    "qualitative_observations": str(form.get("qualitative_observations", "")),
                })
                experimental["log_text"] = storage.experimental_markdown({"experimental": experimental})
            upload = await _read_upload(form.get("experimental_upload"))
            if upload:
                filename, content = upload
                experimental["log_text"] = content.decode("utf-8", errors="replace")
                experimental["source_filename"] = filename
                experimental.update(storage.parse_experimental_log(experimental["log_text"]))
            project["experimental"] = experimental
            _persist_inputs(project)
            return RedirectResponse(f"/projects/{project_id}?step=inputs&panel=experimental", status_code=303)

        if input_name == "template":
            template = project.get("template", {})
            template["editor_mode"] = "raw"
            template["text"] = str(form.get("template_text", ""))
            upload = await _read_upload(form.get("template_upload"))
            if upload:
                filename, content = upload
                project.setdefault("uploads", {})
                project["uploads"]["template_tex"] = storage.store_uploaded_file(project_id, "template", filename, content, _data_root(app))
                template["text"] = content.decode("utf-8", errors="replace")
                template["source_filename"] = filename
            project["template"] = template
            _persist_inputs(project)
            return RedirectResponse(f"/projects/{project_id}?step=inputs&panel=template", status_code=303)

        if input_name == "guidelines":
            guidelines = project.get("guidelines", {})
            editor_mode = str(form.get("editor_mode", "structured") or "structured")
            guidelines["editor_mode"] = editor_mode
            if editor_mode == "raw":
                raw_text = str(form.get("guidelines_text", ""))
                guidelines["guidelines_text"] = raw_text
                guidelines.update(storage.parse_guidelines_text(raw_text))
            else:
                guidelines.update({
                    "deadline": str(form.get("deadline", "")),
                    "page_limit": str(form.get("page_limit", "")),
                    "required_sections": str(form.get("required_sections", "")),
                    "formatting_notes": str(form.get("formatting_notes", "")),
                })
                guidelines["guidelines_text"] = storage.guidelines_markdown({"guidelines": guidelines})
            guidelines_upload = await _read_upload(form.get("guidelines_upload"))
            if guidelines_upload:
                filename, content = guidelines_upload
                stored_path = storage.store_uploaded_file(project_id, "guidelines", filename, content, _data_root(app))
                guidelines["source_filename"] = filename
                if filename.lower().endswith(".pdf"):
                    guidelines["guidelines_text"] = guidelines["guidelines_text"] or f"[PDF uploaded at {stored_path}. Paste a text summary here for the pipeline.]"
                else:
                    guidelines["guidelines_text"] = content.decode("utf-8", errors="replace")
                    guidelines.update(storage.parse_guidelines_text(guidelines["guidelines_text"]))
            project["guidelines"] = guidelines
            _persist_inputs(project)
            return RedirectResponse(f"/projects/{project_id}?step=inputs&panel=guidelines", status_code=303)

        if input_name == "figures":
            uploads = project.get("uploads", {})
            current_figures = list(uploads.get("figures", []))
            for item in form.getlist("figure_uploads"):
                parsed = await _read_upload(item)
                if not parsed:
                    continue
                filename, content = parsed
                current_figures.append(
                    storage.store_uploaded_file(project_id, "figures", filename, content, _data_root(app))
                )
            uploads["figures"] = current_figures
            project["uploads"] = uploads
            _persist_inputs(project)
            return RedirectResponse(f"/projects/{project_id}?step=inputs&panel=figures", status_code=303)

        raise HTTPException(status_code=404, detail="Unknown input.")

    @app.post("/projects/{project_id}/save/input/figures/remove")
    async def remove_figure(project_id: str, request: Request) -> RedirectResponse:
        project = _project_or_404(project_id, _data_root(app))
        form = await request.form()
        remove_path = str(form.get("path", ""))
        uploads = project.get("uploads", {})
        uploads["figures"] = [item for item in uploads.get("figures", []) if str(item) != remove_path]
        project["uploads"] = uploads
        _persist_inputs(project)
        return RedirectResponse(f"/projects/{project_id}?step=inputs&panel=figures", status_code=303)

    @app.post("/projects/{project_id}/save/idea")
    async def save_idea(project_id: str, request: Request) -> RedirectResponse:
        project = _project_or_404(project_id, _data_root(app))
        form = await request.form()
        idea = project.get("idea", {})
        idea.update({
            "problem_statement": str(form.get("problem_statement", "")),
            "core_hypothesis": str(form.get("core_hypothesis", "")),
            "methodology": str(form.get("methodology", "")),
            "expected_contribution": str(form.get("expected_contribution", "")),
            "notes": str(form.get("notes", "")),
            "editor_mode": "structured",
        })
        upload = await _read_upload(form.get("idea_upload"))
        if upload:
            _, content = upload
            text = content.decode("utf-8", errors="replace")
            sections = parse_markdown_sections(text)
            idea["problem_statement"] = sections.get("problem statement", idea["problem_statement"])
            idea["core_hypothesis"] = sections.get("core hypothesis", idea["core_hypothesis"])
            idea["methodology"] = sections.get("proposed methodology (high-level technical approach)", idea["methodology"])
            idea["expected_contribution"] = sections.get("expected contribution", idea["expected_contribution"])
            idea["notes"] = text
            idea["raw_markdown"] = text
        else:
            idea["raw_markdown"] = storage.idea_markdown({"idea": idea})
        project["idea"] = idea
        _persist_inputs(project)
        return RedirectResponse(f"/projects/{project_id}?step=inputs&panel=experimental", status_code=303)

    @app.post("/projects/{project_id}/save/experimental")
    async def save_experimental(project_id: str, request: Request) -> RedirectResponse:
        project = _project_or_404(project_id, _data_root(app))
        form = await request.form()
        experimental = project.get("experimental", {})
        experimental["log_text"] = str(form.get("log_text", ""))
        experimental["editor_mode"] = "raw"
        experimental.update(storage.parse_experimental_log(experimental["log_text"]))
        upload = await _read_upload(form.get("experimental_upload"))
        if upload:
            filename, content = upload
            experimental["log_text"] = content.decode("utf-8", errors="replace")
            experimental["source_filename"] = filename
            experimental.update(storage.parse_experimental_log(experimental["log_text"]))
        project["experimental"] = experimental
        _persist_inputs(project)
        return RedirectResponse(f"/projects/{project_id}?step=inputs&panel=template", status_code=303)

    @app.post("/projects/{project_id}/save/materials")
    async def save_materials(project_id: str, request: Request) -> RedirectResponse:
        project = _project_or_404(project_id, _data_root(app))
        form = await request.form()
        uploads = project.get("uploads", {})
        guidelines = project.get("guidelines", {})
        template = project.get("template", {})

        template_upload = await _read_upload(form.get("template_upload"))
        if template_upload:
            filename, content = template_upload
            uploads["template_tex"] = storage.store_uploaded_file(project_id, "template", filename, content, _data_root(app))
            template["text"] = content.decode("utf-8", errors="replace")
            template["source_filename"] = filename
            template["editor_mode"] = "raw"

        guidelines["guidelines_text"] = str(form.get("guidelines_text", ""))
        guidelines["editor_mode"] = "raw"
        guidelines.update(storage.parse_guidelines_text(guidelines["guidelines_text"]))
        guidelines_upload = await _read_upload(form.get("guidelines_upload"))
        if guidelines_upload:
            filename, content = guidelines_upload
            stored_path = storage.store_uploaded_file(project_id, "guidelines", filename, content, _data_root(app))
            guidelines["source_filename"] = filename
            if filename.lower().endswith(".pdf"):
                guidelines["guidelines_text"] = guidelines["guidelines_text"] or f"[PDF uploaded at {stored_path}. Paste a text summary here for the pipeline.]"
            else:
                guidelines["guidelines_text"] = content.decode("utf-8", errors="replace")
                guidelines.update(storage.parse_guidelines_text(guidelines["guidelines_text"]))

        figure_items = form.getlist("figure_uploads")
        uploads["figures"] = list(uploads.get("figures", []))
        for item in figure_items:
            parsed = await _read_upload(item)
            if not parsed:
                continue
            filename, content = parsed
            uploads["figures"].append(
                storage.store_uploaded_file(project_id, "figures", filename, content, _data_root(app))
            )

        project["uploads"] = uploads
        project["guidelines"] = guidelines
        project["template"] = template
        _persist_inputs(project)
        return RedirectResponse(f"/projects/{project_id}?step=review", status_code=303)

    @app.get("/api/projects/{project_id}/inputs/status")
    async def inputs_status(project_id: str) -> JSONResponse:
        project = _project_or_404(project_id, _data_root(app))
        validation = storage.validate_project_inputs(project, _data_root(app))
        refreshed = storage.load_project(project_id, _data_root(app)) or project
        storage.update_latest_validation(refreshed, validation, _data_root(app))
        return JSONResponse(validation)

    @app.post("/api/projects/{project_id}/inputs/{input_name}/validate")
    async def validate_input(project_id: str, input_name: str) -> JSONResponse:
        if input_name not in INPUT_PANELS:
            raise HTTPException(status_code=404, detail="Unknown input.")
        project = _project_or_404(project_id, _data_root(app))
        validation = storage.validate_project_inputs(project, _data_root(app))
        refreshed = storage.load_project(project_id, _data_root(app)) or project
        storage.update_latest_validation(refreshed, validation, _data_root(app))
        return JSONResponse(validation.get("inputs", {}).get(input_name, {}))

    @app.post("/projects/{project_id}/runs/start")
    async def start_run(project_id: str) -> RedirectResponse:
        project = _project_or_404(project_id, _data_root(app))
        validation = storage.validate_project_inputs(project, _data_root(app))
        refreshed = storage.load_project(project_id, _data_root(app)) or project
        storage.update_latest_validation(refreshed, validation, _data_root(app))
        if validation.get("has_blockers"):
            return RedirectResponse(f"/projects/{project_id}?step=review", status_code=303)
        run_id = orchestrator.start_run(project_id, _data_root(app))
        return RedirectResponse(f"/projects/{project_id}?step=run&run_id={run_id}", status_code=303)

    @app.post("/api/projects/{project_id}/runs/start")
    async def api_start_run(project_id: str) -> JSONResponse:
        project = _project_or_404(project_id, _data_root(app))
        validation = storage.validate_project_inputs(project, _data_root(app))
        refreshed = storage.load_project(project_id, _data_root(app)) or project
        storage.update_latest_validation(refreshed, validation, _data_root(app))
        if validation.get("has_blockers"):
            return JSONResponse({
                "status": "blocked",
                "error": "inputs_blocked",
                "detail": "Project inputs have blockers.",
                "validation": validation,
            }, status_code=409)
        run_id = orchestrator.start_run(project_id, _data_root(app))
        return _api_run_response(project_id, run_id, _data_root(app), status_code=202)

    @app.post("/projects/{project_id}/runs/{run_id}/retry/{stage_name}")
    async def retry_stage(project_id: str, run_id: str, stage_name: str) -> RedirectResponse:
        orchestrator.retry_stage(project_id, run_id, stage_name, _data_root(app))
        return RedirectResponse(f"/projects/{project_id}?step=run&run_id={run_id}", status_code=303)

    @app.post("/api/projects/{project_id}/runs/{run_id}/retry/{stage_name}")
    async def api_retry_stage(project_id: str, run_id: str, stage_name: str) -> JSONResponse:
        try:
            orchestrator.retry_stage(project_id, run_id, stage_name, _data_root(app))
        except RuntimeError as error:
            return JSONResponse({"error": "retry_failed", "message": str(error)}, status_code=409)
        return _api_run_response(project_id, run_id, _data_root(app), status_code=202)

    @app.post("/projects/{project_id}/runs/{run_id}/resume")
    async def resume_run(project_id: str, run_id: str) -> RedirectResponse:
        orchestrator.resume_run(project_id, run_id, _data_root(app))
        return RedirectResponse(f"/projects/{project_id}?step=run&run_id={run_id}", status_code=303)

    @app.post("/api/projects/{project_id}/runs/{run_id}/resume")
    async def api_resume_run(project_id: str, run_id: str) -> JSONResponse:
        try:
            orchestrator.resume_run(project_id, run_id, _data_root(app))
        except RuntimeError as error:
            return JSONResponse({"error": "resume_failed", "message": str(error)}, status_code=409)
        return _api_run_response(project_id, run_id, _data_root(app))

    @app.post("/projects/{project_id}/runs/{run_id}/cancel")
    async def cancel_run(project_id: str, run_id: str) -> RedirectResponse:
        orchestrator.cancel_run(project_id, run_id, _data_root(app))
        return RedirectResponse(f"/projects/{project_id}?step=run&run_id={run_id}", status_code=303)

    @app.post("/api/projects/{project_id}/runs/{run_id}/cancel")
    async def api_cancel_run(project_id: str, run_id: str) -> JSONResponse:
        try:
            orchestrator.cancel_run(project_id, run_id, _data_root(app))
        except RuntimeError as error:
            return JSONResponse({"error": "cancel_failed", "message": str(error)}, status_code=409)
        return _api_run_response(project_id, run_id, _data_root(app))

    @app.get("/api/projects/{project_id}/runs/{run_id}")
    async def run_events(project_id: str, run_id: str) -> JSONResponse:
        return JSONResponse(_decorated_run_or_404(project_id, run_id, _data_root(app)))

    @app.get("/api/projects/{project_id}/runs/{run_id}/stages/{stage_name}")
    async def run_stage_detail(project_id: str, run_id: str, stage_name: str) -> JSONResponse:
        run_payload = _decorated_run_or_404(project_id, run_id, _data_root(app))
        stage_payload = run_payload.get("stages", {}).get(stage_name)
        if not stage_payload:
            raise HTTPException(status_code=404, detail="Stage not found.")
        return JSONResponse(stage_payload)

    @app.get("/api/projects/{project_id}/runs/{run_id}/events")
    async def run_events_sse(project_id: str, run_id: str) -> StreamingResponse:
        run_payload = _decorated_run_or_404(project_id, run_id, _data_root(app))

        async def _event_stream():
            yield "retry: 1500\n"
            latest = run_payload
            payload = json.dumps(latest, ensure_ascii=False)
            yield "event: snapshot\n"
            yield f"data: {payload}\n\n"

            if latest.get("status") != "running":
                return

            last_updated = str(latest.get("updated_at", ""))
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 30.0
            while loop.time() < deadline:
                await asyncio.sleep(1.0)
                try:
                    refreshed = _decorated_run_or_404(project_id, run_id, _data_root(app))
                except HTTPException:
                    break
                next_updated = str(refreshed.get("updated_at", ""))
                if next_updated != last_updated:
                    last_updated = next_updated
                    payload = json.dumps(refreshed, ensure_ascii=False)
                    yield "event: snapshot\n"
                    yield f"data: {payload}\n\n"
                else:
                    yield ": keepalive\n\n"
                if refreshed.get("status") != "running":
                    break

        return StreamingResponse(_event_stream(), media_type="text/event-stream")

    @app.get("/api/projects/{project_id}/runs/{run_id}/logs/{stage_name}")
    async def stage_log(project_id: str, run_id: str, stage_name: str) -> PlainTextResponse:
        data_root = _data_root(app)
        project = _project_or_404(project_id, data_root)
        run_payload = storage.load_run(project_id, run_id, data_root)
        if not run_payload:
            raise HTTPException(status_code=404, detail="Run not found.")
        stage_payload = run_payload.get("stages", {}).get(stage_name)
        if not stage_payload:
            raise HTTPException(status_code=404, detail="Stage not found.")
        raw_log_path = stage_payload.get("log_path")
        if not raw_log_path:
            return PlainTextResponse("")
        workspace_root = Path(str(project.get("workspace_path", ""))).expanduser()
        allowed_roots = [workspace_root, storage.project_dir(project_id, data_root), storage.run_dir(project_id, run_id, data_root)]
        log_path, allowed, access_issue = _safe_snapshot_path(str(raw_log_path), allowed_roots)
        if not allowed:
            raise HTTPException(status_code=403, detail=access_issue or "Path is outside the project workspace.")
        if log_path.exists() and not log_path.is_file():
            raise HTTPException(status_code=400, detail="Log path is not a regular file.")
        text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        return PlainTextResponse(text[-12000:])

    @app.get("/api/integrations")
    async def integrations() -> JSONResponse:
        return JSONResponse(_integration_summary())

    @app.get("/projects/{project_id}/file", response_model=None)
    async def file_route(project_id: str, path: str):
        project = _project_or_404(project_id, _data_root(app))
        candidate = Path(path).expanduser()
        resolved = candidate.resolve(strict=False)
        workspace_root = Path(project["workspace_path"]).expanduser().resolve(strict=False)
        run_root = storage.project_dir(project_id, _data_root(app)).resolve(strict=False)
        if workspace_root not in [resolved, *resolved.parents] and run_root not in [resolved, *resolved.parents]:
            raise HTTPException(status_code=403, detail="Path is outside the project workspace.")
        if not resolved.exists():
            raise HTTPException(status_code=404, detail="File not found.")
        mime, _ = mimetypes.guess_type(str(resolved))
        if mime and (mime.startswith("text/") or resolved.suffix in {".md", ".json", ".tex", ".bib", ".log"}):
            return PlainTextResponse(resolved.read_text(encoding="utf-8", errors="replace"))
        return FileResponse(resolved)

    @app.post("/projects/{project_id}/atlas/open_home")
    async def atlas_open_home(project_id: str) -> RedirectResponse:
        _project_or_404(project_id, _data_root(app))
        atlas_controller.open_chatgpt_home()
        return RedirectResponse(f"/projects/{project_id}?step=run", status_code=303)

    @app.post("/projects/{project_id}/browser/open_chrome")
    async def browser_open_chrome(project_id: str) -> RedirectResponse:
        _project_or_404(project_id, _data_root(app))
        chrome_devtools_adapter.open_google_chrome()
        return RedirectResponse(f"/projects/{project_id}?step=run", status_code=303)

    @app.post("/projects/{project_id}/browser/install_repair")
    async def browser_install_repair(project_id: str) -> RedirectResponse:
        _project_or_404(project_id, _data_root(app))
        global_browser_setup.install_or_repair()
        return RedirectResponse(f"/projects/{project_id}?step=run", status_code=303)

    @app.post("/projects/{project_id}/browser/launch_debug_helper")
    async def browser_launch_debug_helper(project_id: str) -> RedirectResponse:
        _project_or_404(project_id, _data_root(app))
        global_browser_setup.launch_debug_profile()
        return RedirectResponse(f"/projects/{project_id}?step=run", status_code=303)

    @app.post("/projects/{project_id}/browser/run_literature")
    async def browser_run_literature(project_id: str) -> RedirectResponse:
        project = _project_or_404(project_id, _data_root(app))
        workspace = Path(project["workspace_path"]).expanduser()
        research_adapter.ResearchAdapter(_data_root(app)).run_task(
            project_id=project_id,
            run_id=f"browser-manual-{storage.utc_now().replace(':', '').replace('-', '')}",
            stage_name="literature",
            prompt_text=_manual_browser_literature_prompt(workspace),
            workspace=workspace,
            require_deep_research=True,
            task_label="manual_browser_literature",
        )
        return RedirectResponse(f"/projects/{project_id}?step=run", status_code=303)

    @app.post("/projects/{project_id}/browser/retry_attach")
    async def browser_retry_attach(project_id: str) -> RedirectResponse:
        project = _project_or_404(project_id, _data_root(app))
        workspace = Path(project["workspace_path"]).expanduser()
        debug_url = global_browser_setup.debug_browser_url()
        ws_endpoint = str(global_browser_setup.global_setup_health().get("chrome_for_testing", {}).get("ws_endpoint", "") or "")
        attach_mode = "ws_endpoint" if ws_endpoint else "browser_url"
        with _temporary_browser_attach_mode(attach_mode, debug_url, ws_endpoint):
            research_adapter.ResearchAdapter(_data_root(app)).run_task(
                project_id=project_id,
                run_id=f"browser-retry-{storage.utc_now().replace(':', '').replace('-', '')}",
                stage_name="literature",
                prompt_text=_manual_browser_literature_prompt(workspace, mode_label="Chrome for Testing debug relaunch"),
                workspace=workspace,
                require_deep_research=True,
                task_label="manual_browser_retry_attach",
            )
        return RedirectResponse(f"/projects/{project_id}?step=run", status_code=303)

    @app.post("/projects/{project_id}/atlas/run_literature")
    async def atlas_run_literature(project_id: str) -> RedirectResponse:
        project = _project_or_404(project_id, _data_root(app))
        workspace = Path(project["workspace_path"]).expanduser()
        result = atlas_controller.run_atlas_task(
            "\n".join([
                f"Use Deep Research for the PaperOrchestra workspace at `{workspace}`.",
                "Find the strongest citations and summarize how they relate to the proposed work.",
                "Return a concise research brief that can be post-processed into refs.bib and intro/related-work text.",
            ]),
            atlas_controller.AtlasTaskOptions(require_deep_research=True, task_label="manual_literature"),
        )
        storage.record_atlas_literature_run(project, result, _data_root(app))
        return RedirectResponse(f"/projects/{project_id}?step=run", status_code=303)

    return app


def main() -> int:
    config.load_runtime_env()
    host = os.environ.get("PAPERORCHESTRA_GUI_HOST", "127.0.0.1")
    port = int(os.environ.get("PAPERORCHESTRA_GUI_PORT", "8765"))
    uvicorn.run("gui_app.web:create_app", host=host, port=port, factory=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
