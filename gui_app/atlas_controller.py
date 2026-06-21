#!/usr/bin/env python3
"""Helpers for driving ChatGPT Atlas as the primary browser handoff surface."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict
from dataclasses import dataclass
from colorsys import rgb_to_hsv
from typing import Callable
from pathlib import Path

from PIL import Image

from . import storage


ATLAS_APP_NAME = "ChatGPT Atlas"
ATLAS_APP_ID = "com.openai.atlas.web"
ATLAS_APP_PATH = "/Applications/ChatGPT Atlas.app"
SCREENSHOT_ROOT = Path(tempfile.gettempdir()) / "atlas-automation"
OSASCRIPT_TIMEOUT_SECONDS = 5.0

GENERATION_ACTIVE_MARKERS = (
    "stop",
    "stop generating",
    "thinking",
    "researching",
)
GENERATION_IDLE_MARKERS = (
    "regenerate",
    "copy",
    "edit",
    "share",
)
ACCESSIBILITY_NOISE_MARKERS = {
    "",
    ATLAS_APP_NAME.lower(),
    "chatgpt",
    "new chat",
    "search chats",
    "temporary chat",
    "more",
    "copy",
    "edit",
    "share",
    "stop",
    "stop generating",
}


@dataclass
class AtlasLiteratureRunResult:
    deep_research_enabled: bool
    verification_method: str
    submitted: bool
    mode_used: str
    fallback_reason: str
    screenshot_paths: list[str]
    action_sequence: list[str]
    started_at: str
    finished_at: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class AtlasQueryOptions:
    timeout_seconds: float = 90.0
    poll_seconds: float = 1.0
    stable_polls: int = 2
    save_screenshots_dir: str | None = None
    pre_submit_callback: Callable[[], dict[str, object]] | None = None


@dataclass
class AtlasQueryRunResult:
    submitted: bool
    response_text: str
    response_detected: bool
    completion_state: str
    wait_strategy_used: str
    extraction_method: str
    screenshot_paths: list[str]
    action_sequence: list[str]
    started_at: str
    finished_at: str
    error_message: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class AtlasTaskOptions:
    require_deep_research: bool = False
    timeout_seconds: float = 90.0
    poll_seconds: float = 1.0
    stable_polls: int = 2
    save_screenshots_dir: str | None = None
    task_label: str = "atlas_task"


def _run_osascript(script: str) -> str:
    try:
        completed = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=OSASCRIPT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return ""
    return completed.stdout.strip()


def activate_atlas() -> None:
    _run_osascript(f'tell application id "{ATLAS_APP_ID}" to activate')


def open_target_in_atlas(target: str) -> None:
    subprocess.run(["open", "-a", ATLAS_APP_NAME, target], check=False)
    activate_atlas()


def open_file_in_atlas(path: str | Path) -> None:
    open_target_in_atlas(Path(path).expanduser().resolve().as_uri())


def open_chatgpt_home() -> None:
    open_target_in_atlas("https://chatgpt.com/")


def copy_text_to_clipboard(text: str) -> None:
    subprocess.run(["pbcopy"], input=text, text=True, check=False)


def copy_file_to_clipboard(path: str | Path) -> None:
    copy_text_to_clipboard(Path(path).expanduser().read_text(encoding="utf-8"))


def _run_chatgpt_keystrokes(lines: list[str], delay_seconds: float = 0.25) -> None:
    try:
        subprocess.run(
            ["osascript", "-e", "\n".join(lines)],
            check=False,
            timeout=OSASCRIPT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return
    time.sleep(delay_seconds)


def focus_chatgpt_input() -> None:
    activate_atlas()
    time.sleep(0.3)
    if _click_window_relative(0.59, 0.57):
        return
    _run_chatgpt_keystrokes([
        f'tell application id "{ATLAS_APP_ID}" to activate',
        "delay 0.5",
        'tell application "System Events"',
        f'  tell process "{ATLAS_APP_NAME}"',
        '    keystroke "/" using command down',
        "    delay 0.2",
        '    keystroke "l" using command down',
        "    delay 0.2",
        "    key code 53",
        "    delay 0.2",
        "    key code 48",
        "    delay 0.2",
        "    key code 48",
        "    delay 0.2",
        "    key code 48",
        "  end tell",
        "end tell",
    ], delay_seconds=0.6)


def focus_composer_for_submission() -> bool:
    activate_atlas()
    time.sleep(0.2)
    return _click_window_relative(0.55, 0.90)


def paste_into_chatgpt(prompt_text: str) -> None:
    copy_text_to_clipboard(prompt_text)
    open_chatgpt_home()
    focus_chatgpt_input()
    _run_chatgpt_keystrokes([
        f'tell application id "{ATLAS_APP_ID}" to activate',
        "delay 0.3",
        'tell application "System Events"',
        f'  tell process "{ATLAS_APP_NAME}"',
        '    keystroke "v" using command down',
        "  end tell",
        "end tell",
    ], delay_seconds=0.6)


def paste_file_into_chatgpt(path_or_text: str | Path) -> None:
    candidate = Path(str(path_or_text)).expanduser()
    if candidate.exists():
        paste_into_chatgpt(candidate.read_text(encoding="utf-8"))
        return
    paste_into_chatgpt(str(path_or_text))


def show_notification(title: str, message: str) -> None:
    safe_title = title.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')
    _run_osascript(f'display notification "{safe_message}" with title "{safe_title}"')


def _atlas_window_geometry() -> tuple[int, int, int, int] | None:
    output = _run_osascript(
        f'''
        tell application "System Events"
          tell process "{ATLAS_APP_NAME}"
            set frontmost to true
            try
              set targetWindow to first window
              set p to position of targetWindow
              set s to size of targetWindow
              return (item 1 of p as text) & "," & (item 2 of p as text) & "," & (item 1 of s as text) & "," & (item 2 of s as text)
            on error
              return ""
            end try
          end tell
        end tell
        '''
    )
    if not output:
        return None
    try:
        x_pos, y_pos, width, height = [int(part) for part in output.split(",")]
    except ValueError:
        return None
    return x_pos, y_pos, width, height


def _click_window_relative(rel_x: float, rel_y: float) -> bool:
    geometry = _atlas_window_geometry()
    if not geometry:
        return False
    x_pos, y_pos, width, height = geometry
    click_x = int(x_pos + (width * rel_x))
    click_y = int(y_pos + (height * rel_y))
    _run_osascript(
        f'''
        tell application "System Events"
          click at {{{click_x}, {click_y}}}
        end tell
        '''
    )
    time.sleep(0.5)
    return True


def _capture_screenshot(label: str) -> str:
    storage.ensure_dir(SCREENSHOT_ROOT)
    path = SCREENSHOT_ROOT / f"{int(time.time() * 1000)}-{label}.png"
    subprocess.run(["screencapture", "-x", str(path)], check=False)
    return str(path)


def _capture_window_region(label: str) -> tuple[Path | None, tuple[int, int, int, int] | None]:
    geometry = _atlas_window_geometry()
    if not geometry:
        return None, None
    x_pos, y_pos, width, height = geometry
    storage.ensure_dir(SCREENSHOT_ROOT)
    path = SCREENSHOT_ROOT / f"{int(time.time() * 1000)}-{label}.png"
    subprocess.run(
        ["screencapture", "-x", "-R", f"{x_pos},{y_pos},{width},{height}", str(path)],
        check=False,
    )
    return path, geometry


def _ocr_text(path: str | Path) -> str:
    tesseract = shutil.which("tesseract")
    if not tesseract:
        return ""
    completed = subprocess.run(
        [tesseract, str(path), "stdout", "--psm", "11"],
        check=False,
        capture_output=True,
    )
    return completed.stdout.decode("utf-8", errors="replace")


def _capture_response_region_screenshot(save_screenshots_dir: str | None = None) -> tuple[list[str], str]:
    capture_path, _geometry = _capture_window_region("response-check")
    if capture_path is None:
        return [], ""
    with Image.open(capture_path) as image:
        width, height = image.size
        crop_box = (
            int(width * 0.30),
            int(height * 0.12),
            int(width * 0.94),
            int(height * 0.78),
        )
        cropped = image.crop(crop_box)
        cropped.save(capture_path)
    saved_paths = [str(capture_path)]
    if save_screenshots_dir:
        target_dir = Path(save_screenshots_dir).expanduser()
        storage.ensure_dir(target_dir)
        target = target_dir / capture_path.name
        shutil.copy2(capture_path, target)
        saved_paths = [str(target)]
    return saved_paths, _ocr_text(capture_path)


def _accessibility_snapshot() -> str:
    output = _run_osascript(
        f'''
        tell application "System Events"
          tell process "{ATLAS_APP_NAME}"
            set frontmost to true
            set collected to {{}}
            repeat with w in windows
              try
                set end of collected to (name of w as text)
              end try
              try
                repeat with t in static texts of w
                  try
                    set end of collected to (value of t as text)
                  end try
                end repeat
              end try
              try
                repeat with b in buttons of w
                  try
                    set end of collected to (name of b as text)
                  end try
                end repeat
              end try
            end repeat
            return collected as text
          end tell
        end tell
        '''
    )
    return output


def _read_clipboard_text() -> str:
    completed = subprocess.run(
        ["pbpaste"],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def focus_transcript_area() -> bool:
    activate_atlas()
    time.sleep(0.2)
    return _click_window_relative(0.52, 0.40)


def copy_transcript_text() -> str:
    if not focus_transcript_area():
        return ""
    _run_chatgpt_keystrokes([
        f'tell application id "{ATLAS_APP_ID}" to activate',
        "delay 0.2",
        'tell application "System Events"',
        f'  tell process "{ATLAS_APP_NAME}"',
        '    keystroke "a" using command down',
        "    delay 0.15",
        '    keystroke "c" using command down',
        "  end tell",
        "end tell",
    ], delay_seconds=0.4)
    return _read_clipboard_text()


def _normalize_response_text(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        if line.lower() in ACCESSIBILITY_NOISE_MARKERS:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _extract_response_from_accessibility_snapshot(snapshot: str) -> str:
    return _normalize_response_text(snapshot)


def _choose_response_text(
    accessibility_response: str,
    clipboard_response: str,
    ocr_response: str,
) -> tuple[str, str]:
    normalized_ocr = _normalize_response_text(ocr_response)
    if normalized_ocr:
        return normalized_ocr, "screenshot_ocr"

    normalized_accessibility = _normalize_response_text(accessibility_response)
    if normalized_accessibility:
        return normalized_accessibility, "accessibility"

    normalized_clipboard = _normalize_response_text(clipboard_response)
    if normalized_clipboard:
        return normalized_clipboard, "clipboard"
    return "", "none"


def _subtract_baseline_response(candidate_text: str, baseline_text: str) -> str:
    normalized_candidate = _normalize_response_text(candidate_text)
    normalized_baseline = _normalize_response_text(baseline_text)
    if not normalized_baseline:
        return normalized_candidate
    if normalized_candidate == normalized_baseline:
        return ""
    if normalized_candidate.startswith(normalized_baseline):
        remainder = normalized_candidate[len(normalized_baseline):].lstrip()
        return _normalize_response_text(remainder)
    return normalized_candidate


def _text_has_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _capture_recovery_screenshot(label: str, save_screenshots_dir: str | None = None) -> str:
    path = _capture_screenshot(label)
    if not save_screenshots_dir:
        return path
    target_dir = Path(save_screenshots_dir).expanduser()
    storage.ensure_dir(target_dir)
    source = Path(path)
    target = target_dir / source.name
    shutil.copy2(source, target)
    return str(target)


def _capture_atlas_response_sources(save_screenshots_dir: str | None = None) -> dict[str, object]:
    snapshot = _accessibility_snapshot()
    accessibility_response = _extract_response_from_accessibility_snapshot(snapshot)
    generation_active = _text_has_any_marker(snapshot, GENERATION_ACTIVE_MARKERS)
    idle_detected = _text_has_any_marker(snapshot, GENERATION_IDLE_MARKERS)

    clipboard_response = ""
    screenshot_paths, ocr_response = _capture_response_region_screenshot(save_screenshots_dir)
    generation_active = generation_active or _text_has_any_marker(ocr_response, GENERATION_ACTIVE_MARKERS)
    idle_detected = idle_detected or _text_has_any_marker(ocr_response, GENERATION_IDLE_MARKERS)

    return {
        "accessibility_response": accessibility_response,
        "clipboard_response": clipboard_response,
        "ocr_response": ocr_response,
        "generation_active": generation_active,
        "idle_detected": idle_detected,
        "screenshot_paths": screenshot_paths,
    }


def _find_purple_action_button_center(
    image_path: str | Path,
    window_geometry: tuple[int, int, int, int],
) -> tuple[int, int] | None:
    with Image.open(image_path) as image:
        rgba = image.convert("RGBA")
        width, height = rgba.size
        search_left = int(width * 0.72)
        search_top = int(height * 0.38)
        search_right = int(width * 0.99)
        search_bottom = int(height * 0.72)
        pixels = rgba.load()
        matches: list[tuple[int, int]] = []
        for pixel_y in range(search_top, search_bottom):
            for pixel_x in range(search_left, search_right):
                red, green, blue, alpha = pixels[pixel_x, pixel_y]
                if alpha < 200:
                    continue
                hue, saturation, value = rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
                if 0.70 <= hue <= 0.86 and saturation >= 0.30 and value >= 0.45:
                    matches.append((pixel_x, pixel_y))
    if len(matches) < 150:
        return None
    centroid_x = sum(pixel_x for pixel_x, _pixel_y in matches) / len(matches)
    centroid_y = sum(pixel_y for _pixel_x, pixel_y in matches) / len(matches)
    _x_pos, _y_pos, window_width, window_height = window_geometry
    scale_x = width / max(window_width, 1)
    scale_y = height / max(window_height, 1)
    return int(round(centroid_x / scale_x)), int(round(centroid_y / scale_y))


def _click_send_button() -> bool:
    capture_path, geometry = _capture_window_region("send-button-check")
    if capture_path is None or geometry is None:
        return False
    local_point = _find_purple_action_button_center(capture_path, geometry)
    if local_point is None:
        return False
    x_pos, y_pos, _width, _height = geometry
    click_x = x_pos + local_point[0]
    click_y = y_pos + local_point[1]
    _run_osascript(
        f'''
        tell application "System Events"
          click at {{{click_x}, {click_y}}}
        end tell
        '''
    )
    time.sleep(0.8)
    return True


def _wait_for_atlas_response_completion(
    timeout_seconds: float = 90.0,
    poll_seconds: float = 1.0,
    stable_polls: int = 2,
    save_screenshots_dir: str | None = None,
    baseline_response_text: str = "",
) -> dict[str, object]:
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    seen_screenshots: list[str] = []
    previous_text = ""
    stable_count = 0
    response_detected = False
    extraction_method = "none"

    while True:
        sources = _capture_atlas_response_sources(save_screenshots_dir)
        for screenshot_path in sources.get("screenshot_paths", []):
            if screenshot_path not in seen_screenshots:
                seen_screenshots.append(str(screenshot_path))

        response_text, extraction_method = _choose_response_text(
            str(sources.get("accessibility_response", "")),
            str(sources.get("clipboard_response", "")),
            str(sources.get("ocr_response", "")),
        )
        response_text = _subtract_baseline_response(response_text, baseline_response_text)
        generation_active = bool(sources.get("generation_active"))
        idle_detected = bool(sources.get("idle_detected"))

        if response_text:
            response_detected = True
            stable_count = stable_count + 1 if response_text == previous_text else 1
            previous_text = response_text
            if stable_count >= max(stable_polls, 1) and (idle_detected or not generation_active):
                return {
                    "response_text": response_text,
                    "response_detected": True,
                    "completion_state": "completed",
                    "wait_strategy_used": "stability_then_idle",
                    "extraction_method": extraction_method,
                    "screenshot_paths": seen_screenshots,
                    "action_sequence": ["wait_for_response_completion"],
                    "error_message": "",
                }

        if time.monotonic() >= deadline:
            return {
                "response_text": previous_text,
                "response_detected": response_detected,
                "completion_state": "timeout",
                "wait_strategy_used": "stability_then_idle",
                "extraction_method": extraction_method,
                "screenshot_paths": seen_screenshots,
                "action_sequence": ["wait_for_response_completion"],
                "error_message": "" if response_detected else "Timed out waiting for a non-empty Atlas response.",
            }
        time.sleep(max(poll_seconds, 0.0))


def dismiss_transient_overlays() -> list[str]:
    dismissed: list[str] = []
    for label in ("Allow", "OK", "Done", "Close"):
        output = _run_osascript(
            f'''
            tell application "System Events"
              tell process "{ATLAS_APP_NAME}"
                set frontmost to true
                try
                  click button "{label}" of window 1
                  return "{label}"
                on error
                  return ""
                end try
              end tell
            end tell
            '''
        )
        if output:
            dismissed.append(output)
            time.sleep(0.4)
    return dismissed


def attempt_open_mode_control() -> bool:
    activate_atlas()
    time.sleep(0.5)
    # Composer mode control sits near the lower-left area of the composer row.
    return _click_window_relative(0.24, 0.885)


def select_deep_research_mode() -> bool:
    # When the mode menu opens, "Deep research" appears above the composer row.
    return _click_window_relative(0.20, 0.77)


def verify_deep_research_enabled() -> dict[str, object]:
    snapshot = _accessibility_snapshot()
    screenshot_paths: list[str] = []
    if "deep research" in snapshot.lower():
        return {
            "enabled": True,
            "method": "accessibility",
            "screenshot_paths": screenshot_paths,
        }

    screenshot_path = _capture_screenshot("deep-research-check")
    screenshot_paths.append(screenshot_path)
    ocr = _ocr_text(screenshot_path)
    if "deep research" in ocr.lower():
        return {
            "enabled": True,
            "method": "screenshot_ocr",
            "screenshot_paths": screenshot_paths,
        }
    return {
        "enabled": False,
        "method": "unverified",
        "screenshot_paths": screenshot_paths,
    }


def submit_staged_prompt() -> None:
    if _click_send_button():
        return
    _run_chatgpt_keystrokes([
        f'tell application id "{ATLAS_APP_ID}" to activate',
        "delay 0.2",
        'tell application "System Events"',
        f'  tell process "{ATLAS_APP_NAME}"',
        "    key code 36",
        "  end tell",
        "end tell",
    ], delay_seconds=0.8)


def send_query_and_capture_response(
    prompt_text: str,
    options: AtlasQueryOptions | None = None,
) -> dict[str, object]:
    return _stage_and_send_query(
        lambda: paste_into_chatgpt(prompt_text),
        options=options,
        staged_action="stage_prompt",
    )


def _stage_and_send_query(
    stage_prompt: Callable[[], None],
    options: AtlasQueryOptions | None = None,
    staged_action: str = "stage_prompt",
) -> dict[str, object]:
    query_options = options or AtlasQueryOptions()
    action_sequence: list[str] = []
    screenshot_paths: list[str] = []
    error_message = ""
    started_at = storage.utc_now()

    open_chatgpt_home()
    action_sequence.append("open_chatgpt_home")
    dismiss_transient_overlays()
    action_sequence.append("dismiss_transient_overlays")
    stage_prompt()
    action_sequence.append(staged_action)
    dismiss_transient_overlays()
    action_sequence.append("dismiss_transient_overlays")
    baseline_sources = _capture_atlas_response_sources(query_options.save_screenshots_dir)
    for screenshot_path in baseline_sources.get("screenshot_paths", []):
        screenshot_paths.append(str(screenshot_path))
    baseline_response_text, _baseline_method = _choose_response_text(
        str(baseline_sources.get("accessibility_response", "")),
        str(baseline_sources.get("clipboard_response", "")),
        str(baseline_sources.get("ocr_response", "")),
    )
    focus_composer_for_submission()

    if query_options.pre_submit_callback is not None:
        callback_payload = query_options.pre_submit_callback()
        action_sequence.extend(str(step) for step in callback_payload.get("action_sequence", []))
        screenshot_paths.extend(str(path) for path in callback_payload.get("screenshot_paths", []))

    submit_staged_prompt()
    action_sequence.append("submit_prompt")

    wait_result = _wait_for_atlas_response_completion(
        timeout_seconds=query_options.timeout_seconds,
        poll_seconds=query_options.poll_seconds,
        stable_polls=query_options.stable_polls,
        save_screenshots_dir=query_options.save_screenshots_dir,
        baseline_response_text=baseline_response_text,
    )
    action_sequence.extend(str(step) for step in wait_result.get("action_sequence", []))
    screenshot_paths.extend(str(path) for path in wait_result.get("screenshot_paths", []))
    error_message = str(wait_result.get("error_message", ""))

    result = AtlasQueryRunResult(
        submitted=True,
        response_text=str(wait_result.get("response_text", "")),
        response_detected=bool(wait_result.get("response_detected")),
        completion_state=str(wait_result.get("completion_state", "unknown")),
        wait_strategy_used=str(wait_result.get("wait_strategy_used", "stability_then_idle")),
        extraction_method=str(wait_result.get("extraction_method", "none")),
        screenshot_paths=screenshot_paths,
        action_sequence=action_sequence,
        started_at=started_at,
        finished_at=storage.utc_now(),
        error_message=error_message,
    )
    return result.as_dict()


def run_literature_prompt_in_atlas(prompt_path: str | Path) -> dict[str, object]:
    prompt_text = Path(prompt_path).expanduser().read_text(encoding="utf-8")
    verification: dict[str, object] = {
        "enabled": False,
        "method": "unverified",
        "screenshot_paths": [],
    }

    def _prepare_deep_research() -> dict[str, object]:
        nonlocal verification
        action_sequence = ["open_mode_control", "select_deep_research_mode"]
        screenshot_paths: list[str] = []
        attempt_open_mode_control()
        select_deep_research_mode()
        verification = verify_deep_research_enabled()
        screenshot_paths.extend([str(path) for path in verification.get("screenshot_paths", [])])
        return {
            "action_sequence": action_sequence,
            "screenshot_paths": screenshot_paths,
            "verification": verification,
        }

    query_result = _stage_and_send_query(
        lambda: paste_file_into_chatgpt(prompt_text),
        options=AtlasQueryOptions(pre_submit_callback=_prepare_deep_research),
        staged_action="stage_literature_prompt",
    )
    screenshot_paths = [str(path) for path in verification.get("screenshot_paths", [])]
    screenshot_paths.extend([str(path) for path in query_result.get("screenshot_paths", [])])
    deep_research_enabled = bool(verification.get("enabled"))
    verification_method = str(verification.get("method", "unverified"))
    mode_used = "deep_research" if deep_research_enabled else "normal"
    fallback_reason = ""
    if not deep_research_enabled:
        fallback_reason = "Unable to verify Deep Research after Atlas automation; submitted in normal mode fallback."
    action_sequence = [str(step) for step in query_result.get("action_sequence", [])]
    if not deep_research_enabled:
        action_sequence.append("fallback_normal_mode")

    result = AtlasLiteratureRunResult(
        deep_research_enabled=deep_research_enabled,
        verification_method=verification_method,
        submitted=bool(query_result.get("submitted")),
        mode_used=mode_used,
        fallback_reason=fallback_reason,
        screenshot_paths=screenshot_paths,
        action_sequence=action_sequence,
        started_at=str(query_result.get("started_at", storage.utc_now())),
        finished_at=str(query_result.get("finished_at", storage.utc_now())),
    )
    return result.as_dict()


def run_atlas_task(prompt_text: str, options: AtlasTaskOptions | None = None) -> dict[str, object]:
    task_options = options or AtlasTaskOptions()
    verification: dict[str, object] = {
        "enabled": False,
        "method": "not_requested",
        "screenshot_paths": [],
    }
    if task_options.require_deep_research:
        attempt_open_mode_control()
        select_deep_research_mode()
        verification = verify_deep_research_enabled()

    query_result = _stage_and_send_query(
        lambda: paste_into_chatgpt(prompt_text),
        options=AtlasQueryOptions(
            timeout_seconds=task_options.timeout_seconds,
            poll_seconds=task_options.poll_seconds,
            stable_polls=task_options.stable_polls,
            save_screenshots_dir=task_options.save_screenshots_dir,
        ),
        staged_action=task_options.task_label,
    )
    screenshot_paths = [str(path) for path in verification.get("screenshot_paths", [])]
    screenshot_paths.extend([str(path) for path in query_result.get("screenshot_paths", [])])
    deep_research_enabled = bool(verification.get("enabled"))
    verification_method = str(verification.get("method", "not_requested"))
    fallback_reason = ""
    if task_options.require_deep_research and not deep_research_enabled:
        fallback_reason = "Unable to verify Deep Research after Atlas automation; continuing in normal mode."

    return {
        **query_result,
        "mode_used": "deep_research" if deep_research_enabled else "normal",
        "deep_research_enabled": deep_research_enabled,
        "verification_method": verification_method,
        "fallback_reason": fallback_reason,
        "task_label": task_options.task_label,
        "screenshot_paths": screenshot_paths,
    }


def attempt_enable_deep_research() -> None:
    open_chatgpt_home()
    attempt_open_mode_control()
    show_notification(
        "Confirm Deep Research",
        "Atlas attempted to open the chat mode control. Confirm Deep Research is selected before submitting the staged literature prompt.",
    )
