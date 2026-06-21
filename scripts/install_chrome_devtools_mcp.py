#!/usr/bin/env python3
"""Install or repair the global Chrome DevTools MCP setup for Codex."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gui_app import global_browser_setup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", ""))
    parser.add_argument("--mcp-root", default=os.environ.get("PAPERORCHESTRA_CHROME_MCP_PATH", ""))
    parser.add_argument("--debug-browser-app-path", default=os.environ.get("PAPERORCHESTRA_CHROME_DEBUG_APP_PATH", ""))
    parser.add_argument("--print-json", action="store_true")
    args = parser.parse_args()

    env = dict(os.environ)
    if args.codex_home:
        env["CODEX_HOME"] = args.codex_home
    if args.mcp_root:
        env["PAPERORCHESTRA_CHROME_MCP_PATH"] = args.mcp_root
    if args.debug_browser_app_path:
        env["PAPERORCHESTRA_CHROME_DEBUG_APP_PATH"] = args.debug_browser_app_path

    result = global_browser_setup.install_or_repair(env)
    health = global_browser_setup.global_setup_health(env)
    payload = {
        **result,
        "debug_browser_app_path": health["debug_browser_app_path"],
        "debug_browser_app_exists": health["debug_browser_app_exists"],
    }
    if args.print_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Chrome DevTools MCP setup complete.")
        print(f"MCP server: {payload['mcp_server_name']}")
        print(f"Wrapper: {payload['wrapper_path']}")
        print(f"Debug helper: {payload['helper_path']}")
        print(f"Config: {payload['config_path']}")
        print(f"Debug browser app: {payload['debug_browser_app_path']}")
        print(f"Registered servers: {', '.join(payload.get('registered_servers', [])) or 'none reported'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
