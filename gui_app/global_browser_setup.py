#!/usr/bin/env python3
"""Global Codex setup helpers for Chrome DevTools MCP."""

from __future__ import annotations

import json
import os
import plistlib
import re
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_DEBUG_PORT = 9333
DEFAULT_STABLE_DEBUG_PORT = 9222
DEFAULT_MCP_ROOT = Path.home() / ".paperorchestra" / "adapters" / "chrome-devtools-mcp-main"
DEFAULT_CHROME_FOR_TESTING_PROFILE_DIR = Path.home() / "Library" / "Application Support" / "Google" / "Chrome for Testing"
DEFAULT_STABLE_PROFILE_DIR = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
DEFAULT_DEBUG_PROFILE_DIR = DEFAULT_CHROME_FOR_TESTING_PROFILE_DIR
DEFAULT_DEBUG_BROWSER_APP = Path("/Applications/Google Chrome for Testing.app")
DEFAULT_STABLE_BROWSER_APP = Path("/Applications/Google Chrome.app")


def _runtime(env: dict[str, str] | None = None) -> dict[str, str]:
    return dict(env or os.environ)


def codex_home(env: dict[str, str] | None = None) -> Path:
    runtime = _runtime(env)
    explicit = str(runtime.get("CODEX_HOME", "") or "").strip()
    return Path(explicit).expanduser() if explicit else Path.home() / ".codex"


def codex_config_path(env: dict[str, str] | None = None) -> Path:
    return codex_home(env) / "config.toml"


def codex_bin_dir(env: dict[str, str] | None = None) -> Path:
    return codex_home(env) / "bin"


def wrapper_path(env: dict[str, str] | None = None) -> Path:
    return codex_bin_dir(env) / "chrome-devtools-mcp-wrapper"


def debug_helper_path(env: dict[str, str] | None = None) -> Path:
    return codex_bin_dir(env) / "chrome-debug-profile"


def local_mcp_root(env: dict[str, str] | None = None) -> Path:
    runtime = _runtime(env)
    explicit = str(runtime.get("PAPERORCHESTRA_CHROME_MCP_PATH", "") or "").strip()
    return Path(explicit).expanduser() if explicit else DEFAULT_MCP_ROOT


def local_mcp_entrypoint(env: dict[str, str] | None = None) -> Path:
    return local_mcp_root(env) / "build" / "src" / "bin" / "chrome-devtools-mcp.js"


def chrome_for_testing_profile_root(env: dict[str, str] | None = None) -> Path:
    runtime = _runtime(env)
    explicit = str(runtime.get("PAPERORCHESTRA_CHROME_FOR_TESTING_PROFILE_ROOT", "") or "").strip()
    return Path(explicit).expanduser() if explicit else DEFAULT_CHROME_FOR_TESTING_PROFILE_DIR


def chrome_stable_profile_root(env: dict[str, str] | None = None) -> Path:
    runtime = _runtime(env)
    explicit = str(runtime.get("PAPERORCHESTRA_CHROME_STABLE_PROFILE_ROOT", "") or "").strip()
    return Path(explicit).expanduser() if explicit else DEFAULT_STABLE_PROFILE_DIR


def debug_profile_dir(env: dict[str, str] | None = None) -> Path:
    runtime = _runtime(env)
    explicit = str(runtime.get("PAPERORCHESTRA_CHROME_DEBUG_PROFILE_DIR", "") or "").strip()
    return Path(explicit).expanduser() if explicit else DEFAULT_DEBUG_PROFILE_DIR


def debug_browser_url(env: dict[str, str] | None = None) -> str:
    runtime = _runtime(env)
    explicit = str(runtime.get("PAPERORCHESTRA_CHROME_DEBUG_BROWSER_URL", "") or "").strip()
    return explicit or f"http://127.0.0.1:{DEFAULT_DEBUG_PORT}"


def stable_browser_url(env: dict[str, str] | None = None) -> str:
    runtime = _runtime(env)
    explicit = str(runtime.get("PAPERORCHESTRA_CHROME_STABLE_BROWSER_URL", "") or "").strip()
    return explicit or f"http://127.0.0.1:{DEFAULT_STABLE_DEBUG_PORT}"


def chrome_for_testing_app_path(env: dict[str, str] | None = None) -> Path:
    runtime = _runtime(env)
    explicit = str(runtime.get("PAPERORCHESTRA_CHROME_FOR_TESTING_APP_PATH", "") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    if DEFAULT_DEBUG_BROWSER_APP.exists():
        return DEFAULT_DEBUG_BROWSER_APP
    managed = Path.home() / ".codex" / "tools" / "chrome" / "current" / "chrome" / "mac_arm-147.0.7727.57" / "chrome-mac-arm64" / "Google Chrome for Testing.app"
    return managed if managed.exists() else DEFAULT_DEBUG_BROWSER_APP


def chrome_stable_app_path(env: dict[str, str] | None = None) -> Path:
    runtime = _runtime(env)
    explicit = str(runtime.get("PAPERORCHESTRA_CHROME_STABLE_APP_PATH", "") or "").strip()
    return Path(explicit).expanduser() if explicit else DEFAULT_STABLE_BROWSER_APP


def debug_browser_app_path(env: dict[str, str] | None = None) -> Path:
    runtime = _runtime(env)
    explicit = str(runtime.get("PAPERORCHESTRA_CHROME_DEBUG_APP_PATH", "") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    cft = chrome_for_testing_app_path(runtime)
    if cft.exists():
        return cft
    return chrome_stable_app_path(runtime)


def preferred_browser_app_path(env: dict[str, str] | None = None) -> Path:
    cft = chrome_for_testing_app_path(env)
    if cft.exists():
        return cft
    return chrome_stable_app_path(env)


def chrome_executable_path(app_path: Path) -> Path:
    if app_path.suffix != ".app":
        return app_path
    executable_name = app_path.stem
    candidate = app_path / "Contents" / "MacOS" / executable_name
    if candidate.exists():
        return candidate
    fallback_dir = app_path / "Contents" / "MacOS"
    if fallback_dir.exists():
        executables = sorted(path for path in fallback_dir.iterdir() if path.is_file())
        if executables:
            return executables[0]
    return app_path


def _write_executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _read_app_version(app_path: Path) -> str:
    info_path = app_path / "Contents" / "Info.plist"
    if not info_path.exists():
        return ""
    try:
        with info_path.open("rb") as handle:
            payload = plistlib.load(handle)
    except Exception:
        return ""
    return str(payload.get("CFBundleShortVersionString", "") or "").strip()


def _read_local_state(profile_root: Path) -> dict[str, object]:
    local_state_path = profile_root / "Local State"
    if not local_state_path.exists():
        return {}
    try:
        return json.loads(local_state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _extract_account_label(local_state: dict[str, object]) -> str:
    profile = local_state.get("profile")
    if isinstance(profile, dict):
        info_cache = profile.get("info_cache")
        if isinstance(info_cache, dict):
            for payload in info_cache.values():
                if not isinstance(payload, dict):
                    continue
                for key in ("gaia_name", "user_name", "name"):
                    value = str(payload.get(key, "") or "").strip()
                    if value:
                        return value
    accounts = local_state.get("account_info")
    if isinstance(accounts, list):
        for payload in accounts:
            if not isinstance(payload, dict):
                continue
            label = str(payload.get("full_name", "") or payload.get("email", "") or "").strip()
            if label:
                return label
    return ""


def _account_present(local_state: dict[str, object]) -> bool:
    if _extract_account_label(local_state):
        return True
    accounts = local_state.get("account_info")
    return isinstance(accounts, list) and bool(accounts)


def _process_listing() -> str:
    completed = subprocess.run(
        ["ps", "ax", "-o", "command="],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout if completed.returncode == 0 else ""


def _browser_running(app_path: Path) -> bool:
    if not app_path.exists():
        return False
    listing = _process_listing()
    executable = chrome_executable_path(app_path)
    candidates = [
        str(app_path),
        app_path.name,
        app_path.stem,
        str(executable),
        executable.name,
        executable.stem,
    ]
    return any(candidate and candidate in listing for candidate in candidates)


def _port_is_open(browser_url: str) -> bool:
    match = re.match(r"^http://127\.0\.0\.1:(\d+)$", str(browser_url or "").strip())
    if not match:
        return False
    port = int(match.group(1))
    completed = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0 and bool(completed.stdout.strip())


def _debug_version_payload(browser_url: str, timeout_seconds: float = 0.75) -> dict[str, object]:
    url = str(browser_url or "").strip().rstrip("/")
    if not url:
        return {}
    try:
        with urllib.request.urlopen(f"{url}/json/version", timeout=timeout_seconds) as response:
            if response.status != 200:
                return {}
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        try:
            exc.close()
        except Exception:
            pass
        return {}
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _usable_debug_endpoint(browser_url: str) -> tuple[str, str]:
    url = str(browser_url or "").strip().rstrip("/")
    payload = _debug_version_payload(url)
    if not payload:
        return "", ""
    ws_endpoint = str(payload.get("webSocketDebuggerUrl", "") or "").strip()
    return url, ws_endpoint


def _browser_targets_from_profile(profile_root: Path, fallback_url: str) -> tuple[str, str]:
    active_port = profile_root / "DevToolsActivePort"
    if active_port.exists():
        try:
            lines = [line.strip() for line in active_port.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        except Exception:
            lines = []
        if lines and lines[0].isdigit():
            port = lines[0]
            browser_url = f"http://127.0.0.1:{port}"
            usable_url, usable_ws_endpoint = _usable_debug_endpoint(browser_url)
            if usable_url:
                return usable_url, usable_ws_endpoint
    usable_fallback_url, usable_fallback_ws_endpoint = _usable_debug_endpoint(fallback_url)
    if usable_fallback_url:
        return usable_fallback_url, usable_fallback_ws_endpoint
    return "", ""


def _runtime_health(
    runtime_name: str,
    app_path: Path,
    profile_root: Path,
    fallback_url: str,
) -> dict[str, object]:
    local_state = _read_local_state(profile_root)
    installed = app_path.exists()
    running = _browser_running(app_path)
    browser_url, ws_endpoint = _browser_targets_from_profile(profile_root, fallback_url)
    debuggable = bool(browser_url or ws_endpoint)
    return {
        "runtime": runtime_name,
        "app_path": str(app_path),
        "installed": installed,
        "version": _read_app_version(app_path) if installed else "",
        "profile_root": str(profile_root),
        "profile_exists": profile_root.exists(),
        "account_present": _account_present(local_state),
        "account_label": _extract_account_label(local_state),
        "running": running,
        "debuggable": debuggable,
        "browser_url": browser_url,
        "ws_endpoint": ws_endpoint,
        "relaunch_required": bool(installed and running and not debuggable),
    }


def _wrapper_script_text(env: dict[str, str] | None = None) -> str:
    local_root = local_mcp_root(env)
    cft_app = chrome_for_testing_app_path(env)
    cft_executable = chrome_executable_path(cft_app)
    cft_profile = chrome_for_testing_profile_root(env)
    return "\n".join([
        "#!/bin/zsh",
        "set -euo pipefail",
        f'MCP_ROOT="${{PAPERORCHESTRA_CHROME_MCP_PATH:-{local_root}}}"',
        'ENTRYPOINT="$MCP_ROOT/build/src/bin/chrome-devtools-mcp.js"',
        f'CFT_APP="${{PAPERORCHESTRA_CHROME_FOR_TESTING_APP_PATH:-{cft_app}}}"',
        f'CFT_EXECUTABLE="${{PAPERORCHESTRA_CHROME_FOR_TESTING_EXECUTABLE_PATH:-{cft_executable}}}"',
        f'CFT_PROFILE="${{PAPERORCHESTRA_CHROME_FOR_TESTING_PROFILE_ROOT:-{cft_profile}}}"',
        'STABLE_CHANNEL="${PAPERORCHESTRA_CHROME_STABLE_CHANNEL:-stable}"',
        'if [[ $# -eq 0 ]]; then',
        '  if [[ -f "$CFT_PROFILE/DevToolsActivePort" ]]; then',
        '    PORT="$(head -n 1 "$CFT_PROFILE/DevToolsActivePort" | tr -d \'\\r\')"',
        '    WS_PATH="$(sed -n \'2p\' "$CFT_PROFILE/DevToolsActivePort" | tr -d \'\\r\')"',
        '    if [[ "$PORT" =~ ^[0-9]+$ ]]; then',
        '      if [[ "$WS_PATH" == /* ]]; then',
        '        set -- "--wsEndpoint=ws://127.0.0.1:$PORT$WS_PATH"',
        '      else',
        '        set -- "--browserUrl=http://127.0.0.1:$PORT"',
        '      fi',
        "    fi",
        '  elif [[ -d "$CFT_PROFILE" ]] && [[ -e "$CFT_APP" ]]; then',
        '    if ! ps ax -o command= | grep -F "$CFT_EXECUTABLE" | grep -v grep >/dev/null 2>&1; then',
        '      set -- "--executablePath=$CFT_EXECUTABLE" "--userDataDir=$CFT_PROFILE"',
        "    fi",
        "  fi",
        '  if [[ $# -eq 0 ]]; then',
        '    set -- "--autoConnect" "--channel=$STABLE_CHANNEL"',
        "  fi",
        "fi",
        'if [[ -f "$ENTRYPOINT" ]]; then',
        '  exec node "$ENTRYPOINT" --no-usage-statistics "$@"',
        "fi",
        'exec npx -y chrome-devtools-mcp@latest --no-usage-statistics "$@"',
        "",
    ])


def _debug_helper_script_text(env: dict[str, str] | None = None) -> str:
    profile_dir = debug_profile_dir(env)
    browser_app = debug_browser_app_path(env)
    browser_executable = chrome_executable_path(browser_app)
    return "\n".join([
        "#!/bin/zsh",
        "set -euo pipefail",
        f'PROFILE_DIR="${{PAPERORCHESTRA_CHROME_DEBUG_PROFILE_DIR:-${{PAPERORCHESTRA_CHROME_FOR_TESTING_PROFILE_ROOT:-{profile_dir}}}}}"',
        f'PORT="${{PAPERORCHESTRA_CHROME_DEBUG_PORT:-{DEFAULT_DEBUG_PORT}}}"',
        f'APP_PATH="${{PAPERORCHESTRA_CHROME_DEBUG_APP_PATH:-${{PAPERORCHESTRA_CHROME_FOR_TESTING_APP_PATH:-{browser_app}}}}}"',
        f'EXECUTABLE_PATH="${{PAPERORCHESTRA_CHROME_DEBUG_EXECUTABLE_PATH:-{browser_executable}}}"',
        'mkdir -p "$PROFILE_DIR"',
        'exec "$EXECUTABLE_PATH" \\',
        '  "--remote-debugging-port=$PORT" \\',
        '  "--user-data-dir=$PROFILE_DIR" \\',
        '  --no-first-run \\',
        '  --no-default-browser-check \\',
        "  about:blank",
        "",
    ])


def _managed_mcp_block(wrapper: Path) -> str:
    return "\n".join([
        "",
        "# Managed by PaperOrchestra Chrome DevTools MCP installer.",
        "[mcp_servers.chrome-devtools]",
        f'command = "{wrapper}"',
        "args = []",
        "",
    ])


def ensure_mcp_server_block(config_text: str, wrapper: Path) -> str:
    block = _managed_mcp_block(wrapper)
    pattern = re.compile(
        r"(?ms)^\s*# Managed by PaperOrchestra Chrome DevTools MCP installer\.\n\[mcp_servers\.chrome-devtools\]\n(?:.*?\n)*?(?=^\[|^\s*# Managed by PaperOrchestra Chrome DevTools MCP installer\.|\Z)"
    )
    if pattern.search(config_text):
        updated = pattern.sub(block, config_text)
    else:
        stripped = config_text.rstrip()
        updated = (stripped + "\n" if stripped else "") + block
    return updated.lstrip("\n")


def _verify_with_codex_mcp_list(env: dict[str, str] | None = None) -> list[str]:
    runtime = _runtime(env)
    completed = subprocess.run(
        ["codex", "mcp", "list"],
        env=runtime,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return []
    names: list[str] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("Name") or set(line) == {"-"}:
            continue
        names.append(line.split()[0])
    return names


def global_setup_health(env: dict[str, str] | None = None) -> dict[str, object]:
    runtime = _runtime(env)
    config_path = codex_config_path(runtime)
    wrapper = wrapper_path(runtime)
    helper = debug_helper_path(runtime)
    local_root = local_mcp_root(runtime)
    local_entrypoint = local_mcp_entrypoint(runtime)
    debug_app = debug_browser_app_path(runtime)
    registered = False
    if config_path.exists():
        registered = "[mcp_servers.chrome-devtools]" in config_path.read_text(encoding="utf-8", errors="replace")
    return {
        "registered": registered,
        "wrapper_exists": wrapper.exists(),
        "helper_exists": helper.exists(),
        "wrapper_path": str(wrapper),
        "helper_path": str(helper),
        "config_path": str(config_path),
        "local_root": str(local_root),
        "local_root_exists": local_root.exists(),
        "local_build_exists": local_entrypoint.exists(),
        "default_browser_url": debug_browser_url(runtime),
        "debug_browser_app_path": str(debug_app),
        "debug_browser_app_exists": debug_app.exists(),
        "chrome_for_testing": _runtime_health(
            "chrome_for_testing",
            chrome_for_testing_app_path(runtime),
            chrome_for_testing_profile_root(runtime),
            debug_browser_url(runtime),
        ),
        "chrome_stable": _runtime_health(
            "chrome_stable",
            chrome_stable_app_path(runtime),
            chrome_stable_profile_root(runtime),
            stable_browser_url(runtime),
        ),
    }


def install_or_repair(env: dict[str, str] | None = None) -> dict[str, object]:
    runtime = _runtime(env)
    config_path = codex_config_path(runtime)
    wrapper = _write_executable(wrapper_path(runtime), _wrapper_script_text(runtime))
    helper = _write_executable(debug_helper_path(runtime), _debug_helper_script_text(runtime))
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing_text = config_path.read_text(encoding="utf-8", errors="replace") if config_path.exists() else ""
    updated_text = ensure_mcp_server_block(existing_text, wrapper)
    config_path.write_text(updated_text, encoding="utf-8")
    registered_servers = _verify_with_codex_mcp_list(runtime)
    return {
        "mcp_server_name": "chrome-devtools",
        "wrapper_path": str(wrapper),
        "helper_path": str(helper),
        "config_path": str(config_path),
        "registered_servers": registered_servers,
    }


def launch_debug_profile(env: dict[str, str] | None = None) -> subprocess.Popen[bytes]:
    runtime = _runtime(env)
    helper = debug_helper_path(runtime)
    if not helper.exists():
        _write_executable(helper, _debug_helper_script_text(runtime))
    profile_dir = debug_profile_dir(runtime)
    profile_dir.mkdir(parents=True, exist_ok=True)
    debug_app = debug_browser_app_path(runtime)
    debug_executable = chrome_executable_path(debug_app)
    command = [
        str(debug_executable),
        f"--remote-debugging-port={runtime.get('PAPERORCHESTRA_CHROME_DEBUG_PORT', DEFAULT_DEBUG_PORT)}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    process = subprocess.Popen(
        command,
        env=runtime,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def _move_window() -> None:
        app_name = debug_app.stem
        script = f'''
tell application "System Events"
  repeat 30 times
    try
      if exists process "{app_name}" then
        tell process "{app_name}"
          if (count of windows) > 0 then
            repeat with w in windows
              set position of w to {{-2480, 330}}
              set size of w to {{1500, 900}}
            end repeat
            exit repeat
          end if
        end tell
      end if
    end try
    delay 0.3
  end repeat
end tell
'''
        time.sleep(0.3)
        try:
            subprocess.run(["osascript", "-e", script], capture_output=True, check=False, timeout=12.0)
        except subprocess.TimeoutExpired:
            pass

    threading.Thread(target=_move_window, daemon=True).start()
    return process
