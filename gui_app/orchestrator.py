#!/usr/bin/env python3
"""Run orchestration helpers for the FastAPI PaperOrchestra app."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from . import config
from . import storage


def _worker_command(project_id: str, run_id: str, data_root: Path, resume_from: str | None = None) -> list[str]:
    command = [
        str(storage.repo_python_executable(sys.executable)),
        "-m",
        "gui_app.job_runner",
        "--data-root",
        str(data_root),
        "--project-id",
        project_id,
        "--run-id",
        run_id,
        "--kind",
        "orchestrated",
    ]
    if resume_from:
        command.extend(["--resume-from", resume_from])
    return command


def _spawn_worker(project_id: str, run_id: str, data_root: Path, resume_from: str | None = None) -> int:
    env = config.load_runtime_env(dict(os.environ))
    env.setdefault("PYTHONUNBUFFERED", "1")
    process = subprocess.Popen(
        _worker_command(project_id, run_id, data_root, resume_from),
        cwd=str(storage.REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return process.pid


def start_run(project_id: str, data_root: Path | None = None) -> str:
    root = Path(data_root or storage.DEFAULT_DATA_ROOT).expanduser()
    project = storage.load_project(project_id, root)
    if not project:
        raise RuntimeError(f"Project not found: {project_id}")

    project = storage.sync_workspace(project, root)
    run_payload = storage.create_pipeline_run(project_id, root)
    pid = _spawn_worker(project_id, run_payload["run_id"], root)
    run_payload = storage.update_run_fields(
        project_id,
        run_payload["run_id"],
        root,
        event_type="run_started",
        pid=pid,
        status="running",
        current_stage="starting",
        stage="starting",
        summary="Pipeline run started.",
    )

    project["latest_run_id"] = run_payload["run_id"]
    project["last_status"] = "running"
    storage.save_project(project, root)
    return run_payload["run_id"]


def retry_stage(project_id: str, run_id: str, stage_name: str, data_root: Path | None = None) -> str:
    root = Path(data_root or storage.DEFAULT_DATA_ROOT).expanduser()
    run_payload = storage.load_run(project_id, run_id, root)
    if not run_payload:
        raise RuntimeError(f"Run not found: {project_id}/{run_id}")
    if storage.is_pid_running(run_payload.get("pid")):
        raise RuntimeError("Cannot retry a stage while the run is still active.")

    effective_stage = storage.resolve_requested_stage(run_payload, stage_name)
    run_payload = storage.reset_pipeline_run_from_stage(run_payload, effective_stage, root)
    pid = _spawn_worker(project_id, run_id, root, resume_from=effective_stage)
    run_payload = storage.update_run_fields(
        project_id,
        run_id,
        root,
        event_type="run_restarted",
        pid=pid,
        status="running",
        current_stage=effective_stage,
        stage=effective_stage,
        summary=(
            f"Retry requested for {stage_name}; resuming from {effective_stage}."
            if effective_stage != stage_name else f"Retry requested for {stage_name}."
        ),
    )

    project = storage.load_project(project_id, root)
    if project:
        project["latest_run_id"] = run_id
        project["last_status"] = "running"
        storage.save_project(project, root)
    return run_id


def resume_run(project_id: str, run_id: str, data_root: Path | None = None) -> str:
    root = Path(data_root or storage.DEFAULT_DATA_ROOT).expanduser()
    run_payload = storage.load_run(project_id, run_id, root)
    if not run_payload:
        raise RuntimeError(f"Run not found: {project_id}/{run_id}")
    if storage.is_pid_running(run_payload.get("pid")):
        return run_id

    next_stage = storage.next_incomplete_stage(run_payload)
    if not next_stage:
        return run_id
    return retry_stage(project_id, run_id, next_stage, root)


def cancel_run(project_id: str, run_id: str, data_root: Path | None = None) -> str:
    root = Path(data_root or storage.DEFAULT_DATA_ROOT).expanduser()
    run_payload = storage.load_run(project_id, run_id, root)
    if not run_payload:
        raise RuntimeError(f"Run not found: {project_id}/{run_id}")

    pid = run_payload.get("pid")
    cancel_requested_at = storage.utc_now()
    if pid and storage.is_pid_running(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            pass
    run_payload = storage.update_run_fields(
        project_id,
        run_id,
        root,
        event_type="run_cancelled",
        cancel_requested_at=cancel_requested_at,
        status="cancelled",
        finished_at=storage.utc_now(),
        summary="Run cancelled from the web app.",
    )

    project = storage.load_project(project_id, root)
    if project:
        project["last_status"] = "cancelled"
        storage.save_project(project, root)
    return run_id
