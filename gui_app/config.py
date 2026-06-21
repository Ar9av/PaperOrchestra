#!/usr/bin/env python3
"""Runtime configuration helpers for the PaperOrchestra GUI."""

from __future__ import annotations

import os
import plistlib
import shutil
from pathlib import Path

from . import figure_adapter
from . import global_browser_setup

REPO_ROOT = Path(__file__).resolve().parent.parent
GLOBAL_CONFIG_PATH = Path.home() / ".paperorchestra" / "config"
ATLAS_APP_PATH = Path("/Applications/ChatGPT Atlas.app")
CHROME_APP_PATH = Path("/Applications/Google Chrome.app")


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _default_ca_bundle() -> str:
    try:
        import certifi
    except ImportError:
        return ""
    try:
        bundle = Path(certifi.where())
    except Exception:
        return ""
    return str(bundle) if bundle.exists() else ""


def load_runtime_env(env: dict[str, str] | None = None) -> dict[str, str]:
    target = env if env is not None else os.environ
    for source in (GLOBAL_CONFIG_PATH, REPO_ROOT / ".env"):
        for key, value in _parse_env_file(source).items():
            if value and not target.get(key):
                target[key] = value
    ca_bundle = _default_ca_bundle()
    if ca_bundle:
        target.setdefault("SSL_CERT_FILE", ca_bundle)
        target.setdefault("REQUESTS_CA_BUNDLE", ca_bundle)
        target.setdefault("CURL_CA_BUNDLE", ca_bundle)
    return target


def _mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "****"
    return value[:4] + "..." + value[-4:]


def _env_flag(runtime: dict[str, str], key: str, default: bool = True) -> bool:
    raw_value = str(runtime.get(key, "") or "").strip().lower()
    if not raw_value:
        return default
    return raw_value not in {"0", "false", "no", "off"}


def _read_app_version(app_path: Path) -> str:
    info_path = app_path / "Contents" / "Info.plist"
    if not info_path.exists():
        return ""
    try:
        with info_path.open("rb") as handle:
            payload = plistlib.load(handle)
    except Exception:
        return ""
    version = str(payload.get("CFBundleShortVersionString", "") or "").strip()
    return version


def _version_major(version: str) -> int:
    head = str(version or "").strip().split(".", 1)[0]
    try:
        return int(head)
    except ValueError:
        return 0


def _fallback_order(runtime: dict[str, str]) -> list[str]:
    raw_value = str(runtime.get("PAPERORCHESTRA_BROWSER_FALLBACK_ORDER", "") or "").strip()
    if not raw_value:
        return ["chrome_for_testing", "chrome_stable", "atlas", "local"]
    items = [item.strip() for item in raw_value.split(",") if item.strip()]
    return items or ["chrome_for_testing", "chrome_stable", "atlas", "local"]


def integration_health(env: dict[str, str] | None = None) -> dict[str, object]:
    runtime = load_runtime_env(dict(env or os.environ))
    backend = figure_adapter.figure_backend_status(runtime)
    paperbanana_path = runtime.get("PAPERBANANA_PATH", "").strip()
    papervizagent_path = runtime.get("PAPERVIZAGENT_PATH", "").strip()
    semantic_scholar_key = runtime.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    exa_key = runtime.get("EXA_API_KEY", "").strip()
    codex_path = shutil.which("codex", path=runtime.get("PATH"))
    node_path = shutil.which("node", path=runtime.get("PATH"))
    npx_path = shutil.which("npx", path=runtime.get("PATH"))
    atlas_enabled = _env_flag(runtime, "PAPERORCHESTRA_ATLAS_ENABLED", default=True)
    atlas_available = atlas_enabled and ATLAS_APP_PATH.exists()
    chrome_enabled = _env_flag(runtime, "PAPERORCHESTRA_CHROME_ENABLED", default=True)
    chrome_mcp_available = bool(node_path and npx_path)
    global_health = global_browser_setup.global_setup_health(runtime)
    chrome_for_testing = dict(global_health.get("chrome_for_testing") or {})
    chrome_stable = dict(global_health.get("chrome_stable") or {})
    chrome_version = str(
        chrome_for_testing.get("version")
        or chrome_stable.get("version")
        or (_read_app_version(CHROME_APP_PATH) if chrome_enabled else "")
    ).strip()
    chrome_available = chrome_enabled and bool(
        chrome_for_testing.get("installed")
        or chrome_stable.get("installed")
        or bool(chrome_version)
        or CHROME_APP_PATH.exists()
    )
    chrome_compatible = _version_major(chrome_version) >= 144 if chrome_version else False
    attach_mode = str(runtime.get("PAPERORCHESTRA_CHROME_ATTACH_MODE", "chrome_for_testing_first") or "chrome_for_testing_first").strip() or "chrome_for_testing_first"
    browser_strategy = str(runtime.get("PAPERORCHESTRA_BROWSER_STRATEGY", "chrome_for_testing_first") or "chrome_for_testing_first").strip() or "chrome_for_testing_first"
    browser_primary = str(runtime.get("PAPERORCHESTRA_BROWSER_PRIMARY", "chrome_devtools") or "chrome_devtools").strip() or "chrome_devtools"
    atlas_fallback_enabled = _env_flag(runtime, "PAPERORCHESTRA_ATLAS_FALLBACK_ENABLED", default=True)
    local_fallback_enabled = _env_flag(runtime, "PAPERORCHESTRA_LOCAL_FALLBACK_ENABLED", default=True)
    fallback_order = _fallback_order(runtime)
    plausibly_attachable = bool(
        chrome_mcp_available
        and (
            chrome_for_testing.get("debuggable")
            or chrome_stable.get("debuggable")
            or chrome_for_testing.get("installed")
            or chrome_stable.get("installed")
        )
    )

    return {
        "chrome": {
            "available": chrome_available,
            "enabled": chrome_enabled,
            "compatible": chrome_compatible,
            "version": chrome_version,
            "path": str(global_browser_setup.preferred_browser_app_path(runtime)),
            "mcp_available": chrome_mcp_available,
            "attach_mode": attach_mode,
            "plausibly_attachable": plausibly_attachable,
            "global_registered": bool(global_health["registered"]),
            "wrapper_exists": bool(global_health["wrapper_exists"]),
            "helper_exists": bool(global_health["helper_exists"]),
            "wrapper_path": str(global_health["wrapper_path"]),
            "helper_path": str(global_health["helper_path"]),
            "config_path": str(global_health["config_path"]),
            "local_root": str(global_health["local_root"]),
            "local_root_exists": bool(global_health["local_root_exists"]),
            "local_build_exists": bool(global_health["local_build_exists"]),
            "default_browser_url": str(global_health["default_browser_url"]),
            "debug_browser_app_path": str(global_health["debug_browser_app_path"]),
            "debug_browser_app_exists": bool(global_health["debug_browser_app_exists"]),
        },
        "chrome_for_testing": chrome_for_testing,
        "chrome_stable": chrome_stable,
        "browser_adapter": {
            "strategy": browser_strategy,
            "primary": browser_primary,
            "attach_mode": attach_mode,
            "fallback_order": fallback_order,
            "atlas_fallback_enabled": atlas_fallback_enabled,
            "local_fallback_enabled": local_fallback_enabled,
        },
        "atlas": {
            "available": atlas_available,
            "enabled": atlas_enabled,
            "path": str(ATLAS_APP_PATH),
        },
        "codex": {
            "available": bool(codex_path),
            "path": codex_path or "",
        },
        "semantic_scholar": {
            "configured": bool(semantic_scholar_key),
            "masked": _mask_secret(semantic_scholar_key) if semantic_scholar_key else "",
        },
        "exa": {
            "configured": bool(exa_key),
            "masked": _mask_secret(exa_key) if exa_key else "",
        },
        "paperbanana": {
            "configured": bool(paperbanana_path),
            "valid": bool(backend["paperbanana_root"]),
            "path": paperbanana_path,
            "codex_image_handoff": _env_flag(runtime, "PAPERBANANA_CODEX_IMAGE_HANDOFF", default=True),
            "codex_model": str(runtime.get("PAPERBANANA_CODEX_MODEL", "") or runtime.get("PAPERORCHESTRA_CODEX_MODEL", "") or "gpt-5.5"),
            "codex_reasoning_effort": str(runtime.get("PAPERBANANA_CODEX_REASONING_EFFORT", "") or runtime.get("PAPERORCHESTRA_CODEX_REASONING_EFFORT", "") or "xhigh"),
        },
        "papervizagent": {
            "configured": bool(papervizagent_path),
            "valid": bool(backend["papervizagent_root"]),
            "path": papervizagent_path,
        },
        "figure_backend": backend,
    }
