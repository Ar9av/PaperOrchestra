#!/usr/bin/env python3
"""Helpers for selecting figure backends and validating generated outputs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

_MIN_FIGURE_BYTES = 1024


def _backend_root(raw_path: str) -> Path | None:
    value = raw_path.strip()
    if not value:
        return None
    candidate = Path(value).expanduser()
    if not (candidate / "utils" / "paperviz_processor.py").exists():
        return None
    return candidate


def figure_backend_status(env: dict[str, str] | None = None) -> dict[str, object]:
    runtime = dict(env or os.environ)
    paperbanana_root = _backend_root(runtime.get("PAPERBANANA_PATH", ""))
    papervizagent_root = _backend_root(runtime.get("PAPERVIZAGENT_PATH", ""))

    selected_backend = ""
    selected_root = ""
    if paperbanana_root is not None:
        selected_backend = "paperbanana"
        selected_root = str(paperbanana_root)
    elif papervizagent_root is not None:
        selected_backend = "papervizagent"
        selected_root = str(papervizagent_root)

    return {
        "configured": bool(runtime.get("PAPERBANANA_PATH", "").strip() or runtime.get("PAPERVIZAGENT_PATH", "").strip()),
        "valid": bool(selected_root),
        "selected_backend": selected_backend,
        "selected_root": selected_root,
        "paperbanana_root": str(paperbanana_root) if paperbanana_root else "",
        "papervizagent_root": str(papervizagent_root) if papervizagent_root else "",
    }


def select_figure_engine(plot_type: str, env: dict[str, str] | None = None) -> dict[str, object]:
    normalized = plot_type.strip().lower()
    backend = figure_backend_status(env)
    if normalized == "plot":
        return {"engine": "local_matplotlib", "reason": "numeric plots default to deterministic rendering"}
    if backend["valid"]:
        return {
            "engine": str(backend["selected_backend"]),
            "reason": "conceptual diagrams prefer the PaperBanana/PaperVizAgent backend",
            "backend": backend,
        }
    return {"engine": "local_diagram", "reason": "no external figure backend available", "backend": backend}


def figure_quality_check(paths: Iterable[str]) -> dict[str, object]:
    candidates = [Path(path).expanduser() for path in paths]
    existing = [path for path in candidates if path.exists()]
    if not existing:
        return {
            "passed": False,
            "reason": "figure_qc_failed",
            "message": "No generated figure outputs were found.",
            "details": {"checked_paths": [str(path) for path in candidates]},
        }

    for path in existing:
        if path.stat().st_size < _MIN_FIGURE_BYTES:
            return {
                "passed": False,
                "reason": "figure_qc_failed",
                "message": f"Generated figure {path.name} is too small to trust.",
                "details": {"path": str(path), "size_bytes": path.stat().st_size},
            }
        if path.suffix.lower() == ".png":
            header = path.read_bytes()[:8]
            if header != b"\x89PNG\r\n\x1a\n":
                return {
                    "passed": False,
                    "reason": "figure_qc_failed",
                    "message": f"Generated figure {path.name} is not a valid PNG.",
                    "details": {"path": str(path)},
                }

    return {
        "passed": True,
        "reason": "",
        "message": "Figure outputs passed the lightweight QC gate.",
        "details": {"count": len(existing), "paths": [str(path) for path in existing]},
    }
