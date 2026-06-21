#!/usr/bin/env python3
"""Submit a prompt to ChatGPT Atlas and print the captured response."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gui_app import atlas_controller


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bridge Codex and ChatGPT Atlas through macOS UI automation.",
    )
    parser.add_argument("--prompt", help="Prompt text to send to Atlas.")
    parser.add_argument("--prompt-file", help="Path to a UTF-8 prompt file.")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=90.0,
        help="Maximum time to wait for a non-empty Atlas response.",
    )
    parser.add_argument(
        "--save-screenshots-dir",
        help="Optional directory to copy recovery screenshots into.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full bridge result as JSON instead of plain response text.",
    )
    return parser.parse_args()


def _load_prompt(args: argparse.Namespace) -> str:
    if bool(args.prompt) == bool(args.prompt_file):
        raise SystemExit("Provide exactly one of --prompt or --prompt-file.")
    if args.prompt:
        return str(args.prompt)
    return Path(args.prompt_file).expanduser().read_text(encoding="utf-8")


def main() -> int:
    args = _parse_args()
    prompt_text = _load_prompt(args)
    result = atlas_controller.send_query_and_capture_response(
        prompt_text,
        atlas_controller.AtlasQueryOptions(
            timeout_seconds=args.timeout_seconds,
            save_screenshots_dir=args.save_screenshots_dir,
        ),
    )
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    response_text = str(result.get("response_text", ""))
    if response_text:
        print(response_text)
        return 0

    error_message = str(result.get("error_message", "") or "Atlas did not return any response text.")
    print(error_message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
