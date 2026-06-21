#!/usr/bin/env python3
"""FastAPI web app for the Codex-first PaperOrchestra control room."""

from __future__ import annotations

import asyncio
import datetime as dt
import mimetypes
import os
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


def create_app(data_root: Path | None = None) -> FastAPI:
    config.load_runtime_env()
    app = FastAPI(title="PaperOrchestra Control Room")
    configured_root = data_root or Path(
        os.environ.get("PAPERORCHESTRA_GUI_DATA_ROOT", str(storage.DEFAULT_DATA_ROOT))
    ).expanduser()
    app.state.data_root = str(storage.get_paths(configured_root).data_root)
    app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")

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

    @app.post("/projects/{project_id}/runs/{run_id}/retry/{stage_name}")
    async def retry_stage(project_id: str, run_id: str, stage_name: str) -> RedirectResponse:
        orchestrator.retry_stage(project_id, run_id, stage_name, _data_root(app))
        return RedirectResponse(f"/projects/{project_id}?step=run&run_id={run_id}", status_code=303)

    @app.post("/projects/{project_id}/runs/{run_id}/resume")
    async def resume_run(project_id: str, run_id: str) -> RedirectResponse:
        orchestrator.resume_run(project_id, run_id, _data_root(app))
        return RedirectResponse(f"/projects/{project_id}?step=run&run_id={run_id}", status_code=303)

    @app.post("/projects/{project_id}/runs/{run_id}/cancel")
    async def cancel_run(project_id: str, run_id: str) -> RedirectResponse:
        orchestrator.cancel_run(project_id, run_id, _data_root(app))
        return RedirectResponse(f"/projects/{project_id}?step=run&run_id={run_id}", status_code=303)

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
        run_payload = storage.load_run(project_id, run_id, _data_root(app))
        if not run_payload:
            raise HTTPException(status_code=404, detail="Run not found.")
        stage_payload = run_payload.get("stages", {}).get(stage_name)
        if not stage_payload:
            raise HTTPException(status_code=404, detail="Stage not found.")
        log_path = Path(stage_payload["log_path"])
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
