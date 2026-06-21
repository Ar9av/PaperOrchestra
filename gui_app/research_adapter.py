#!/usr/bin/env python3
"""Browser-backed research adapter for the PaperOrchestra orchestrator."""

from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from . import atlas_controller
from . import chrome_devtools_adapter
from . import config
from . import storage

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_BULLET_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)$")


def _acceptance_fixtures_enabled() -> bool:
    return str(os.environ.get("PAPERORCHESTRA_ACCEPTANCE_FIXTURES", "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _clean_candidate_text(value: str) -> str:
    text = value.strip()
    text = _MARKDOWN_LINK_RE.sub(lambda match: match.group(1), text)
    text = text.replace("`", "")
    text = text.replace("**", "")
    text = text.replace("__", "")
    text = re.sub(r"\s+[.-]\s+.*$", "", text)
    text = re.sub(r"\s+[—-]\s+.*$", "", text)
    text = re.sub(r"\s+\([^)]*\)\s*$", "", text)
    return text.strip(" .")


def _normalize_candidate(title: str, url: str = "", notes: str = "", source_line: str = "") -> dict[str, str]:
    return {
        "title": title.strip(),
        "url": url.strip(),
        "notes": notes.strip(),
        "source_line": source_line.strip(),
    }


def _extract_literature_candidates(response_text: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for raw_line in response_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        bullet_match = _BULLET_RE.match(line)
        content = bullet_match.group(1).strip() if bullet_match else line
        links = _MARKDOWN_LINK_RE.findall(content)
        if links:
            for label, url in links:
                title = _clean_candidate_text(label)
                if not title:
                    continue
                key = title.casefold()
                if key in seen_titles:
                    continue
                seen_titles.add(key)
                notes = _clean_candidate_text(_MARKDOWN_LINK_RE.sub("", content))
                candidates.append(_normalize_candidate(title=title, url=url, notes=notes, source_line=line))
            continue
        if not bullet_match:
            continue
        title = _clean_candidate_text(content)
        if len(title.split()) < 3:
            continue
        key = title.casefold()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        candidates.append(_normalize_candidate(title=title, source_line=line))
    return candidates[:12]


def _structured_literature_output(
    response_text: str,
    response_path: Path,
    result_path: Path,
    screenshot_paths: list[str],
    result: dict[str, Any],
) -> dict[str, Any]:
    candidates = _extract_literature_candidates(response_text)
    query_hints: list[str] = []
    seen_hints: set[str] = set()
    for candidate in candidates:
        title = candidate.get("title", "").strip()
        if not title:
            continue
        key = title.casefold()
        if key in seen_hints:
            continue
        seen_hints.add(key)
        query_hints.append(title)
    summary = response_text.strip().splitlines()[0].strip() if response_text.strip() else ""
    return {
        "task_type": "literature",
        "status": "succeeded"
        if result.get("submitted") and str(result.get("completion_state", "") or "").strip().lower() == "completed" and response_text.strip()
        else "failed",
        "mode_used": str(result.get("mode_used", "normal")),
        "deep_research_enabled": bool(result.get("deep_research_enabled")),
        "verification_method": str(result.get("verification_method", "unverified")),
        "summary": summary,
        "response_path": str(response_path),
        "result_path": str(result_path),
        "screenshot_paths": screenshot_paths,
        "query_hints": query_hints,
        "candidates": candidates,
    }


def _acceptance_literature_result(task_label: str, require_deep_research: bool) -> dict[str, Any]:
    mode = "deep_research" if require_deep_research else "normal"
    response_text = "\n".join([
        "# Atlas Deep Research summary",
        "- [Attention Is All You Need](https://arxiv.org/abs/1706.03762) - transformer baseline",
        "- [Longformer: The Long-Document Transformer](https://arxiv.org/abs/2004.05150) - sparse long-context attention",
    ])
    now = storage.utc_now()
    return {
        "submitted": True,
        "response_text": response_text,
        "response_detected": True,
        "completion_state": "completed",
        "wait_strategy_used": "acceptance_fixture",
        "extraction_method": "acceptance_fixture",
        "screenshot_paths": [],
        "action_sequence": ["acceptance_fixture"],
        "started_at": now,
        "finished_at": now,
        "error_message": "",
        "mode_used": mode,
        "deep_research_enabled": bool(require_deep_research),
        "verification_method": "acceptance_fixture",
        "fallback_reason": "",
        "task_label": task_label,
    }


class ResearchAdapter:
    """Normalize Chrome/Atlas task execution into durable literature artifacts."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).expanduser()

    def _runtime(self) -> dict[str, str]:
        return config.load_runtime_env(dict(os.environ))

    def _atlas_root(self, project_id: str, run_id: str, stage_name: str) -> Path:
        return storage.stage_dir(project_id, run_id, stage_name, self.data_root) / "atlas"

    def _browser_root(self, project_id: str, run_id: str, stage_name: str, adapter: str) -> Path:
        return storage.stage_dir(project_id, run_id, stage_name, self.data_root) / "browser" / adapter

    def _record_project_browser_result(self, project_id: str, persisted: dict[str, Any]) -> None:
        project = storage.load_project(project_id, self.data_root)
        if not project:
            return
        project["latest_browser_result"] = dict(persisted)
        if str(persisted.get("adapter", "") or "") == "atlas":
            project["latest_atlas_result"] = dict(persisted)
        storage.save_project(project, self.data_root)

    def _persist_normalized_browser_result(
        self,
        project_id: str,
        run_id: str,
        stage_name: str,
        workspace: Path,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        adapter = str(result.get("adapter", "chrome_devtools") or "chrome_devtools")
        stage_root = self._browser_root(project_id, run_id, stage_name, adapter)
        workspace_root = workspace / "cache" / "browser" / adapter
        storage.ensure_dir(stage_root)
        storage.ensure_dir(workspace_root)

        screenshot_paths: list[str] = []
        for candidate in result.get("screenshot_paths", []) or []:
            source = Path(str(candidate)).expanduser()
            if not source.exists():
                continue
            target = stage_root / source.name
            shutil.copy2(source, target)
            screenshot_paths.append(str(target))

        response_text = str(result.get("response_text", "") or "").strip()
        response_path = ""
        source_response_path = str(result.get("response_path") or result.get("raw_response_path") or "").strip()
        if response_text:
            response_target = workspace_root / "response.md"
            response_target.write_text(response_text + "\n", encoding="utf-8")
            response_path = str(response_target)
        elif source_response_path:
            source = Path(source_response_path).expanduser()
            if source.exists():
                target = workspace_root / "response.md"
                shutil.copy2(source, target)
                response_path = str(target)
            else:
                response_path = source_response_path

        structured_output_path = str(result.get("structured_output_path", "") or "").strip()
        if structured_output_path:
            source = Path(structured_output_path).expanduser()
            if source.exists():
                target = workspace_root / "structured_output.json"
                shutil.copy2(source, target)
                structured_output_path = str(target)

        transcript_path = str(result.get("transcript_path", "") or "").strip()
        if transcript_path:
            source = Path(transcript_path).expanduser()
            if source.exists():
                target = stage_root / "transcript.txt"
                shutil.copy2(source, target)
                transcript_path = str(target)
        elif response_path:
            transcript_path = response_path

        persisted = {
            "task_id": str(result.get("task_id", "") or f"{adapter}-{uuid.uuid4().hex[:10]}"),
            "task_type": str(result.get("task_type", "literature") or "literature"),
            "adapter": adapter,
            "status": str(result.get("status", "failed") or "failed"),
            "started_at": str(result.get("started_at", "") or storage.utc_now()),
            "finished_at": str(result.get("finished_at", "") or storage.utc_now()),
            "mode_used": str(result.get("mode_used", "") or ""),
            "summary": str(result.get("summary", "") or "Browser task completed."),
            "prompt_path": str(result.get("prompt_path", "") or ""),
            "raw_response_path": response_path,
            "response_path": response_path,
            "structured_output_path": structured_output_path,
            "transcript_path": transcript_path,
            "screenshot_paths": screenshot_paths,
            "artifacts": [path for path in [response_path, structured_output_path, transcript_path, *screenshot_paths] if path],
            "fallback_reason": str(result.get("fallback_reason", "") or ""),
            "attention_required": result.get("attention_required"),
        }
        result_path = stage_root / "browser_result.json"
        storage.atomic_write_json(result_path, persisted)
        persisted["result_path"] = str(result_path)
        persisted["artifacts"] = [str(result_path), *persisted["artifacts"]]
        self._record_project_browser_result(project_id, persisted)
        return persisted

    def _persist_atlas_result(
        self,
        project_id: str,
        run_id: str,
        stage_name: str,
        workspace: Path,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        atlas_root = self._atlas_root(project_id, run_id, stage_name)
        storage.ensure_dir(atlas_root)
        workspace_atlas_root = workspace / "cache" / "atlas"
        storage.ensure_dir(workspace_atlas_root)

        persisted_raw = dict(result)
        screenshot_paths: list[str] = []
        for candidate in result.get("screenshot_paths", []):
            source = Path(str(candidate)).expanduser()
            if not source.exists():
                continue
            target = atlas_root / source.name
            shutil.copy2(source, target)
            screenshot_paths.append(str(target))

        response_text = str(result.get("response_text", "")).strip()
        response_path = workspace_atlas_root / "literature_response.md"
        response_path.write_text(response_text + ("\n" if response_text else ""), encoding="utf-8")

        persisted_raw["screenshot_paths"] = screenshot_paths
        raw_result_path = atlas_root / "atlas_result.json"
        storage.atomic_write_json(raw_result_path, persisted_raw)

        structured_payload = _structured_literature_output(
            response_text=response_text,
            response_path=response_path,
            result_path=raw_result_path,
            screenshot_paths=screenshot_paths,
            result=result,
        )
        stage_structured_path = atlas_root / "literature_structured.json"
        workspace_structured_path = workspace_atlas_root / "literature_structured.json"
        storage.atomic_write_json(stage_structured_path, structured_payload)
        storage.atomic_write_json(workspace_structured_path, structured_payload)

        task_succeeded = bool(
            result.get("submitted")
            and str(result.get("completion_state", "") or "").strip().lower() == "completed"
            and response_text
        )
        summary = "Atlas task completed."
        if task_succeeded and result.get("mode_used") == "deep_research":
            summary = "Atlas Deep Research task completed."
        elif result.get("fallback_reason"):
            summary = str(result["fallback_reason"])
        elif not task_succeeded:
            summary = str(result.get("error_message", "") or "Atlas task did not yield a usable response.")

        persisted = {
            "task_id": str(result.get("task_label", "") or f"atlas-{uuid.uuid4().hex[:10]}"),
            "task_type": "literature",
            "adapter": "atlas",
            "status": "succeeded" if task_succeeded else "failed",
            "started_at": str(result.get("started_at", "") or storage.utc_now()),
            "finished_at": str(result.get("finished_at", "") or storage.utc_now()),
            "mode_used": str(result.get("mode_used", "normal")),
            "deep_research_enabled": bool(result.get("deep_research_enabled")),
            "verification_method": str(result.get("verification_method", "unverified")),
            "fallback_reason": str(result.get("fallback_reason", "")),
            "completion_state": str(result.get("completion_state", "unknown")),
            "prompt_path": "",
            "result_path": str(raw_result_path),
            "raw_response_path": str(response_path),
            "response_path": str(response_path),
            "structured_output_path": str(workspace_structured_path),
            "screenshot_paths": screenshot_paths,
            "transcript_path": str(response_path),
            "summary": summary,
            "artifacts": [
                str(raw_result_path),
                str(response_path),
                str(stage_structured_path),
                str(workspace_structured_path),
                *screenshot_paths,
            ],
            "attention_required": None,
        }
        self._record_project_browser_result(project_id, persisted)
        return persisted

    def persist_result(
        self,
        project_id: str,
        run_id: str,
        stage_name: str,
        workspace: Path,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if str(result.get("adapter", "") or "").strip():
            return self._persist_normalized_browser_result(project_id, run_id, stage_name, workspace, result)
        return self._persist_atlas_result(project_id, run_id, stage_name, workspace, result)

    def _chrome_unavailable_result(self, health: dict[str, Any], task_label: str) -> dict[str, Any]:
        reasons: list[str] = []
        chrome = health.get("chrome", {})
        chrome_for_testing = health.get("chrome_for_testing", {})
        chrome_stable = health.get("chrome_stable", {})
        if not chrome.get("enabled"):
            reasons.append("Chrome adapter is disabled.")
        if not chrome.get("available"):
            reasons.append("No Chrome runtime is available.")
        if not chrome.get("compatible"):
            reasons.append("Chrome 144+ is required for DevTools automation.")
        if not chrome.get("mcp_available"):
            reasons.append("Node.js and npx are required for chrome-devtools-mcp.")
        if chrome_for_testing and not chrome_for_testing.get("installed") and not chrome_stable.get("installed"):
            reasons.append("Neither Chrome for Testing nor stable Chrome is installed.")
        summary = " ".join(reasons) or "Chrome DevTools MCP is unavailable."
        return {
            "task_id": task_label,
            "task_type": "literature",
            "adapter": "chrome_devtools",
            "status": "failed",
            "started_at": storage.utc_now(),
            "finished_at": storage.utc_now(),
            "mode_used": str(health.get("browser_adapter", {}).get("attach_mode", "chrome_for_testing_first") or "chrome_for_testing_first"),
            "summary": summary,
            "prompt_path": "",
            "raw_response_path": "",
            "structured_output_path": "",
            "transcript_path": "",
            "screenshot_paths": [],
            "artifacts": [],
            "fallback_reason": summary,
            "attention_required": None,
        }

    def run_task(
        self,
        project_id: str,
        run_id: str,
        stage_name: str,
        prompt_text: str,
        workspace: Path,
        require_deep_research: bool = False,
        task_label: str = "atlas_task",
    ) -> dict[str, Any]:
        if _acceptance_fixtures_enabled():
            result = _acceptance_literature_result(task_label, require_deep_research)
            return self._persist_atlas_result(project_id, run_id, stage_name, workspace, result)

        runtime = self._runtime()
        health = config.integration_health(runtime)
        browser_adapter = health.get("browser_adapter", {})
        chrome_result: dict[str, Any] | None = None

        if browser_adapter.get("primary") == "chrome_devtools" and health.get("chrome", {}).get("enabled"):
            if (
                health.get("chrome", {}).get("available")
                and health.get("chrome", {}).get("compatible")
                and health.get("chrome", {}).get("mcp_available")
            ):
                chrome_result = chrome_devtools_adapter.ChromeDevToolsAdapter(self.data_root, runtime).run_task(
                    project_id=project_id,
                    run_id=run_id,
                    stage_name=stage_name,
                    prompt_text=prompt_text,
                    workspace=workspace,
                    require_deep_research=require_deep_research,
                    task_label=task_label,
                )
            else:
                chrome_result = self.persist_result(
                    project_id,
                    run_id,
                    stage_name,
                    workspace,
                    self._chrome_unavailable_result(health, task_label),
                )

            if chrome_result.get("status") in {"succeeded", "attention_required"}:
                return chrome_result

        can_fallback_to_atlas = bool(browser_adapter.get("atlas_fallback_enabled", True) and health.get("atlas", {}).get("enabled"))
        if can_fallback_to_atlas:
            try:
                atlas_result = atlas_controller.run_atlas_task(
                    prompt_text,
                    atlas_controller.AtlasTaskOptions(
                        require_deep_research=require_deep_research,
                        task_label=task_label,
                    ),
                )
            except Exception as exc:
                atlas_result = {
                    "submitted": False,
                    "response_text": "",
                    "response_detected": False,
                    "completion_state": "failed",
                    "wait_strategy_used": "none",
                    "extraction_method": "none",
                    "screenshot_paths": [],
                    "action_sequence": [],
                    "started_at": "",
                    "finished_at": "",
                    "error_message": f"Atlas automation failed: {exc}",
                    "mode_used": "deep_research" if require_deep_research else "normal",
                    "deep_research_enabled": False,
                    "verification_method": "unverified",
                    "fallback_reason": "Atlas automation was unavailable; falling back to local literature discovery.",
                    "task_label": task_label,
                }
            if (
                chrome_result
                and chrome_result.get("status") == "failed"
                and bool(atlas_result.get("submitted"))
            ):
                atlas_result["fallback_reason"] = str(
                    chrome_result.get("fallback_reason")
                    or "Chrome attach failed; falling back to Atlas."
                )
            return self._persist_atlas_result(project_id, run_id, stage_name, workspace, atlas_result)

        if chrome_result is not None:
            return chrome_result

        return self.persist_result(
            project_id,
            run_id,
            stage_name,
            workspace,
            {
                "task_id": task_label,
                "task_type": "literature",
                "adapter": "chrome_devtools",
                "status": "failed",
                "started_at": storage.utc_now(),
                "finished_at": storage.utc_now(),
                "mode_used": str(browser_adapter.get("attach_mode", "auto_connect") or "auto_connect"),
                "summary": "No browser adapter was available; falling back to local literature discovery.",
                "prompt_path": "",
                "raw_response_path": "",
                "structured_output_path": "",
                "transcript_path": "",
                "screenshot_paths": [],
                "artifacts": [],
                "fallback_reason": "No browser adapter was available; falling back to local literature discovery.",
                "attention_required": None,
            },
        )
