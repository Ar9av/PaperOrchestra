#!/usr/bin/env python3
"""Launch the PaperOrchestra FastAPI control room."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gui_app import config
from gui_app import storage


def wait_for_health(url: str, timeout_seconds: float = 10.0) -> dict[str, object] | None:
    deadline = time.monotonic() + max(timeout_seconds, 0.1)
    health_url = f"{url}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as response:
                if response.status == 200:
                    return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(0.25)
            continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("PAPERORCHESTRA_GUI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PAPERORCHESTRA_GUI_PORT", "8765")))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data-root", default=os.environ.get("PAPERORCHESTRA_GUI_DATA_ROOT", ""))
    args = parser.parse_args()

    config.load_runtime_env()
    repo_root = REPO_ROOT
    python_bin = storage.repo_python_executable(sys.executable)
    gui_data_root = storage.get_paths().data_root

    host = args.host
    port = args.port
    url = f"http://{host}:{port}"

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env["PAPERORCHESTRA_GUI_HOST"] = host
    env["PAPERORCHESTRA_GUI_PORT"] = str(port)
    if args.data_root:
        gui_data_root = storage.get_paths(Path(args.data_root).expanduser()).data_root
        env["PAPERORCHESTRA_GUI_DATA_ROOT"] = str(gui_data_root)

    process = subprocess.Popen(
        [str(python_bin), "-m", "gui_app.web"],
        cwd=str(repo_root),
        env=env,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    health_payload = wait_for_health(url)
    if not health_payload:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except OSError:
            pass
        print(f"PaperOrchestra GUI failed to start at {url}", file=sys.stderr)
        return 1

    if not args.no_browser:
        webbrowser.open(url)
    print(f"PaperOrchestra GUI started at {url} (pid {process.pid})")
    print(f"Project data persists under {health_payload.get('data_root', str(gui_data_root))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
