#!/usr/bin/env python3
"""Chrome DevTools MCP browser adapter for PaperOrchestra."""

from __future__ import annotations

import json
import io
import os
import re
import select
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import global_browser_setup
from . import storage

MCP_PROTOCOL_VERSION = "2025-03-26"


def open_google_chrome() -> None:
    subprocess.run(["open", "-a", str(global_browser_setup.preferred_browser_app_path())], check=False)


def _candidate_local_roots(env: dict[str, str] | None = None) -> list[Path]:
    runtime = dict(env or os.environ)
    candidates: list[Path] = []
    explicit = str(runtime.get("PAPERORCHESTRA_CHROME_MCP_PATH", "") or "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.extend([
        global_browser_setup.local_mcp_root(runtime),
        storage.REPO_ROOT / ".vendor" / "chrome-devtools-mcp-main",
        storage.REPO_ROOT.parent / "chrome-devtools-mcp-main",
        storage.REPO_ROOT.parent / "chrome-devtools-mcp",
    ])
    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def resolve_local_mcp_root(env: dict[str, str] | None = None) -> Path | None:
    for candidate in _candidate_local_roots(env):
        if (candidate / "package.json").exists():
            return candidate
    return None


def resolve_local_mcp_entrypoint(env: dict[str, str] | None = None) -> Path | None:
    root = resolve_local_mcp_root(env)
    if root is None:
        return None
    entrypoint = root / "build" / "src" / "bin" / "chrome-devtools-mcp.js"
    return entrypoint if entrypoint.exists() else None


def _extract_text_from_tool_result(payload: dict[str, Any]) -> str:
    result = payload.get("result") or {}
    content = result.get("content") or []
    parts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                text = str(item.get("text", "") or "").strip()
                if text:
                    parts.append(text)
    return "\n\n".join(parts).strip()


def _extract_json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    text = _extract_text_from_tool_result(payload).strip()
    if not text:
        return {}
    candidates = [text]
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidates.extend(fenced)
    inline = re.findall(r"(\{.*\})", text, flags=re.DOTALL)
    candidates.extend(inline)
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate.startswith("{"):
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _extract_page_id(payload: dict[str, Any]) -> int | None:
    result = payload.get("result") or {}
    structured = result.get("structuredContent") or {}
    if isinstance(structured, dict):
        page_id = structured.get("pageId")
        if isinstance(page_id, int):
            return page_id
    text = _extract_text_from_tool_result(payload)
    match = re.search(r'"pageId"\s*:\s*(\d+)', text)
    if match:
        return int(match.group(1))
    return None


def _parse_pages_text(payload: dict[str, Any]) -> list[dict[str, Any]]:
    text = _extract_text_from_tool_result(payload)
    pages: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        match = re.match(r"^\s*(\d+):\s+(\S+)(?:\s+\[(selected)\])?\s*$", raw_line.strip())
        if not match:
            continue
        pages.append({
            "page_id": int(match.group(1)),
            "url": match.group(2),
            "selected": bool(match.group(3)),
        })
    return pages


def _snapshot_has_enabled_send_button(snapshot_text: str) -> bool:
    for line in str(snapshot_text or "").splitlines():
        if 'button "Send prompt"' not in line:
            continue
        if "disableable disabled" in line:
            return False
        return True
    return False


def _snapshot_is_streaming(snapshot_text: str) -> bool:
    return 'button "Stop streaming"' in str(snapshot_text or "")


def _snapshot_indicates_response_pending(snapshot_text: str) -> bool:
    text = str(snapshot_text or "")
    if _snapshot_is_streaming(text):
        return True
    return _contains_any(text, [
        "researching sources",
        "searching the web",
        "thinking for",
        "working on your request",
        "reading sources",
        "analyzing sources",
        "creating report",
        "deep research is in progress",
    ])


def _extract_assistant_text_from_snapshot(snapshot_text: str) -> str:
    lines = str(snapshot_text or "").splitlines()
    collecting = False
    parts: list[str] = []
    for line in lines:
        if 'heading "ChatGPT said:"' in line:
            collecting = True
            continue
        if not collecting:
            continue
        if 'textbox "Chat with ChatGPT"' in line:
            break
        if 'heading "You said:"' in line:
            break
        if 'StaticText "ChatGPT is AI and can make mistakes. Check important info."' in line:
            break
        match = re.search(r'StaticText "(.*)"', line)
        if not match:
            continue
        value = match.group(1).strip()
        if not value:
            continue
        parts.append(value)
    return "\n".join(parts).strip()


def _assistant_text_from_page_state(page_state: dict[str, Any]) -> str:
    return str(page_state.get("assistantText", "") or "").strip()


def _classify_chatgpt_response_state(snapshot_text: str, response_text: str) -> dict[str, str]:
    if str(response_text or "").strip():
        return {
            "state": "response_captured",
            "reason": "chatgpt_response_captured",
            "message": "ChatGPT response was captured and persisted.",
        }
    if _snapshot_indicates_response_pending(snapshot_text):
        return {
            "state": "submitted_waiting",
            "reason": "chatgpt_submitted_waiting",
            "message": "ChatGPT accepted the prompt and is still generating or researching. Wait, then retry response capture.",
        }
    return {
        "state": "response_not_extractable",
        "reason": "chatgpt_response_not_extractable",
        "message": "ChatGPT prompt submission completed, but no assistant response could be extracted from the browser snapshot.",
    }


def _contains_any(text: str, needles: list[str]) -> bool:
    haystack = str(text or "").casefold()
    return any(needle.casefold() in haystack for needle in needles)


def _classify_chatgpt_readiness(page_state: dict[str, Any], snapshot_text: str = "") -> dict[str, Any]:
    title = str(page_state.get("title", "") or "")
    url = str(page_state.get("url", "") or "")
    body_text = str(page_state.get("textPreview", "") or "")
    combined = "\n".join(part for part in [title, url, body_text, snapshot_text] if part)
    host_is_chatgpt = "chatgpt.com" in url.casefold()
    composer_found = bool(page_state.get("composerFound")) or _snapshot_has_enabled_send_button(snapshot_text)
    snapshot_has_chatgpt_box = 'textbox "Chat with ChatGPT"' in str(snapshot_text or "")

    if composer_found or (host_is_chatgpt and snapshot_has_chatgpt_box):
        return {
            "state": "composer_ready",
            "message": "ChatGPT composer is ready.",
        }

    challenge_hints = [
        "just a moment",
        "checking your browser",
        "cloudflare",
        "verify you are human",
        "unusual traffic",
        "/sorry/",
        "challenge-platform",
        "cf-chl",
    ]
    if _contains_any(combined, challenge_hints):
        return {
            "state": "challenge_blocked",
            "message": "ChatGPT is blocked behind a browser challenge. Open the restored ChatGPT tab and complete the challenge once.",
        }

    auth_hints = [
        "log in",
        "sign up",
        "continue with google",
        "continue with apple",
        "welcome back",
        "/auth",
    ]
    if _contains_any(combined, auth_hints):
        return {
            "state": "auth_blocked",
            "message": "ChatGPT requires sign-in in the selected browser runtime before browser discovery can continue.",
        }

    if host_is_chatgpt:
        return {
            "state": "unknown",
            "message": "ChatGPT is open but the composer is not ready yet. Wait for the restored tab to finish loading, then retry warm-up.",
        }

    return {
        "state": "unknown",
        "message": "No usable ChatGPT workspace is ready yet.",
    }


def _readiness_attention_payload(readiness_state: str, readiness_message: str) -> dict[str, Any]:
    reason_map = {
        "challenge_blocked": "chatgpt_challenge_blocked",
        "auth_blocked": "chatgpt_auth_required",
        "unknown": "chatgpt_not_ready",
    }
    return {
        "reason": str(reason_map.get(readiness_state, "chatgpt_not_ready")),
        "message": str(readiness_message or "ChatGPT is not ready yet."),
        "details": {
            "adapter": "chrome_devtools",
            "readiness_state": readiness_state,
        },
    }


def _response_attention_payload(response_state: dict[str, str]) -> dict[str, Any]:
    return {
        "reason": str(response_state.get("reason", "") or "chatgpt_response_not_extractable"),
        "message": str(response_state.get("message", "") or "ChatGPT response was not captured."),
        "details": {
            "adapter": "chrome_devtools",
            "readiness_state": str(response_state.get("state", "") or "response_not_extractable"),
        },
    }


class McpStdioSession:
    """Minimal JSON-RPC-over-stdio MCP client."""

    def __init__(self, process: subprocess.Popen[bytes], timeout_seconds: float = 8.0) -> None:
        self.process = process
        self.timeout_seconds = timeout_seconds
        self._next_id = 1

    def _send(self, payload: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise RuntimeError("MCP stdin is unavailable.")
        body = (json.dumps(payload) + "\n").encode("utf-8")
        self.process.stdin.write(body)
        self.process.stdin.flush()

    def _read_stderr_excerpt(self) -> str:
        handle = self.process.stderr
        if handle is None:
            return ""
        try:
            data = handle.read()
        except Exception:
            return ""
        if not data:
            return ""
        if isinstance(data, bytes):
            text = data.decode("utf-8", errors="replace")
        else:
            text = str(data)
        return text.strip()[:1000]

    def _read_message(self) -> dict[str, Any]:
        if self.process.stdout is None:
            raise RuntimeError("MCP stdout is unavailable.")
        try:
            stdout_fd = self.process.stdout.fileno()
        except (AttributeError, io.UnsupportedOperation):
            raw_line = bytearray()
            while b"\n" not in raw_line:
                chunk = self.process.stdout.read(1)
                if not chunk:
                    stderr_excerpt = self._read_stderr_excerpt()
                    message = "MCP server closed stdout unexpectedly."
                    if stderr_excerpt:
                        message = f"{message} stderr: {stderr_excerpt}"
                    raise RuntimeError(message)
                raw_line.extend(chunk)
            return json.loads(bytes(raw_line).decode("utf-8").strip())
        raw_line = bytearray()
        deadline = time.monotonic() + self.timeout_seconds
        while b"\n" not in raw_line:
            if time.monotonic() > deadline:
                raise TimeoutError("Timed out waiting for MCP response header.")
            remaining = max(deadline - time.monotonic(), 0.0)
            readable, _, _ = select.select([stdout_fd], [], [], remaining)
            if not readable:
                raise TimeoutError("Timed out waiting for MCP response header.")
            chunk = os.read(stdout_fd, 1)
            if not chunk:
                stderr_excerpt = self._read_stderr_excerpt()
                message = "MCP server closed stdout unexpectedly."
                if stderr_excerpt:
                    message = f"{message} stderr: {stderr_excerpt}"
                raise RuntimeError(message)
            raw_line.extend(chunk)
        return json.loads(bytes(raw_line).decode("utf-8").strip())

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        })
        while True:
            message = self._read_message()
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(str(message["error"]))
            return message

    def initialize(self) -> dict[str, Any]:
        response = self._request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "paperorchestra", "version": "0.1"},
        })
        self._send({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        })
        return response

    def list_tools(self) -> list[str]:
        response = self._request("tools/list", {})
        result = response.get("result") or {}
        tools = result.get("tools") or []
        names: list[str] = []
        if isinstance(tools, list):
            for tool in tools:
                if isinstance(tool, dict):
                    name = str(tool.get("name", "") or "").strip()
                    if name:
                        names.append(name)
        return names

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })


class ChromeDevToolsMcpClient:
    """Real MCP client for chrome-devtools-mcp."""

    def __init__(
        self,
        env: dict[str, str] | None = None,
        attach_mode: str = "auto_connect",
        channel: str = "stable",
        browser_url: str = "",
        ws_endpoint: str = "",
        executable_path: str = "",
        user_data_dir: str = "",
    ) -> None:
        self.env = dict(env or os.environ)
        self.attach_mode = str(attach_mode or "auto_connect").strip() or "auto_connect"
        self.channel = str(channel or "stable").strip() or "stable"
        self.browser_url = str(browser_url or "").strip()
        self.ws_endpoint = str(ws_endpoint or "").strip()
        self.executable_path = str(executable_path or "").strip()
        self.user_data_dir = str(user_data_dir or "").strip()

    def command(self) -> list[str]:
        local_entrypoint = resolve_local_mcp_entrypoint(self.env)
        wrapper = global_browser_setup.wrapper_path(self.env)
        if local_entrypoint is not None:
            command = ["node", str(local_entrypoint), "--no-usage-statistics"]
        elif wrapper.exists():
            command = [str(wrapper)]
        else:
            command = ["npx", "-y", "chrome-devtools-mcp@latest", "--no-usage-statistics"]
        if self.attach_mode == "auto_connect":
            command.append("--autoConnect")
            command.append(f"--channel={self.channel}")
        elif self.attach_mode == "ws_endpoint" and self.ws_endpoint:
            command.append(f"--wsEndpoint={self.ws_endpoint}")
        elif self.attach_mode == "browser_url" and self.browser_url:
            command.append(f"--browserUrl={self.browser_url}")
        elif self.ws_endpoint:
            command.append(f"--wsEndpoint={self.ws_endpoint}")
        elif self.browser_url:
            command.append(f"--browserUrl={self.browser_url}")
        if self.executable_path and not self.browser_url and not self.ws_endpoint and self.attach_mode != "auto_connect":
            command.append(f"--executablePath={self.executable_path}")
        if self.user_data_dir and not self.browser_url and not self.ws_endpoint:
            command.append(f"--userDataDir={self.user_data_dir}")
        return command

    @contextmanager
    def session(self, timeout_seconds: float = 8.0):
        process = subprocess.Popen(
            self.command(),
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            yield McpStdioSession(process, timeout_seconds=timeout_seconds)
        finally:
            try:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=2.0)
            except Exception:
                if process.poll() is None:
                    process.kill()
            for handle_name in ("stdin", "stdout", "stderr"):
                handle = getattr(process, handle_name, None)
                try:
                    if handle is not None:
                        handle.close()
                except Exception:
                    pass

    def _chatgpt_prompt_flow(
        self,
        session: McpStdioSession,
        prompt_text: str,
        require_deep_research: bool,
        artifact_dir: Path,
    ) -> dict[str, Any]:
        tools = set(session.list_tools())
        if "new_page" not in tools or "evaluate_script" not in tools:
            raise RuntimeError("Chrome DevTools MCP does not expose the required browser tools.")

        artifact_dir.mkdir(parents=True, exist_ok=True)
        page_id = None
        tab_reused = False
        if "list_pages" in tools and "select_page" in tools:
            try:
                pages_result = session.call_tool("list_pages", {})
                pages = _parse_pages_text(pages_result)
                existing = next(
                    (
                        page for page in pages
                        if "chatgpt.com" in str(page.get("url", "") or "")
                        and "/auth" not in str(page.get("url", "") or "")
                    ),
                    None,
                )
                if existing is not None:
                    page_id = int(existing["page_id"])
                    tab_reused = True
                    session.call_tool("select_page", {"pageId": page_id, "bringToFront": True})
            except Exception:
                page_id = None
        if page_id is None:
            new_page_result = session.call_tool("new_page", {"url": "https://chatgpt.com", "timeout": 30000})
            page_id = _extract_page_id(new_page_result)
            if page_id is not None and "select_page" in tools:
                session.call_tool("select_page", {"pageId": page_id, "bringToFront": True})

        snapshot_path = artifact_dir / "chatgpt-initial.snapshot.txt"
        if "take_snapshot" in tools:
            session.call_tool("take_snapshot", {"filePath": str(snapshot_path)})

        if "wait_for" in tools:
            try:
                session.call_tool("wait_for", {"text": ["ChatGPT", "Message ChatGPT", "Log in"], "timeout": 15000})
            except Exception:
                pass

        composer_wait_seconds = float(self.env.get("PAPERORCHESTRA_CHROME_COMPOSER_WAIT_SECONDS", "30") or "30")
        deadline = time.monotonic() + max(composer_wait_seconds, 0.0)
        state_payload: dict[str, Any] = {}
        readiness = {"state": "unknown", "message": "ChatGPT is not ready yet."}
        snapshot_text = ""
        while True:
            if "take_snapshot" in tools:
                try:
                    snapshot_payload = session.call_tool("take_snapshot", {})
                    snapshot_text = _extract_text_from_tool_result(snapshot_payload)
                except Exception:
                    snapshot_text = ""
            page_state = session.call_tool("evaluate_script", {
                "function": """() => {
                  const text = (document.body && document.body.innerText) || "";
                  const composer = document.querySelector('textarea[placeholder*="Message"]')
                    || document.querySelector('textarea[aria-label*="Message"]')
                    || document.querySelector('[data-testid*="composer"] textarea')
                    || document.querySelector('[data-testid*="composer"] [contenteditable="true"]')
                    || document.querySelector('[contenteditable="true"][data-lexical-editor="true"]')
                    || document.querySelector('form textarea');
                  return {
                    title: document.title,
                    url: location.href,
                    composerFound: Boolean(composer),
                    textPreview: text.slice(0, 1000),
                  };
                }""",
            })
            state_payload = _extract_json_payload(page_state)
            readiness = _classify_chatgpt_readiness(state_payload, snapshot_text)
            if readiness["state"] != "unknown":
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(2.0)
        if readiness["state"] != "composer_ready":
            return {
                "task_type": "literature",
                "status": "attention_required",
                "response_text": "",
                "raw_response_path": "",
                "structured_output_path": "",
                "transcript_path": str(snapshot_path) if snapshot_path.exists() else "",
                "screenshot_paths": [],
                "summary": str(readiness["message"] or "ChatGPT is not ready yet."),
                "mode_used": self.attach_mode,
                "attention_required": _readiness_attention_payload(readiness["state"], readiness["message"]),
                "readiness_state": readiness["state"],
                "readiness_message": readiness["message"],
                "tab_reused": tab_reused,
            }

        if require_deep_research:
            try:
                session.call_tool("evaluate_script", {
                    "function": """() => {
                      const candidates = [...document.querySelectorAll('button,[role="button"]')];
                      const target = candidates.find((button) => /deep research/i.test(button.innerText || ""));
                      if (target) {
                        target.click();
                        return {clicked: true};
                      }
                      return {clicked: false};
                    }""",
                })
            except Exception:
                pass

        transport = ""
        if "type_text" in tools:
            session.call_tool("type_text", {"text": prompt_text})
            transport = "type_text"
        else:
            raise RuntimeError("Chrome DevTools MCP does not expose the required text-input tools.")

        if "take_snapshot" in tools:
            post_type_snapshot = session.call_tool("take_snapshot", {})
            snapshot_text = _extract_text_from_tool_result(post_type_snapshot)
            if _snapshot_has_enabled_send_button(snapshot_text) and "press_key" in tools:
                session.call_tool("press_key", {"key": "Enter"})
                transport = "type_text+enter"
            elif "press_key" in tools:
                session.call_tool("press_key", {"key": "Enter"})
                transport = "type_text+enter"
        elif "press_key" in tools:
            session.call_tool("press_key", {"key": "Enter"})
            transport = "type_text+enter"
        else:
            raise RuntimeError("ChatGPT prompt submission failed because no submit transport is available.")

        time.sleep(2.0)
        assistant_snapshot_text = ""
        if "take_snapshot" in tools:
            wait_seconds = float(self.env.get("PAPERORCHESTRA_CHROME_RESPONSE_WAIT_SECONDS", "90") or "90")
            deadline = time.monotonic() + max(wait_seconds, 0.0)
            while True:
                assistant_snapshot = session.call_tool("take_snapshot", {})
                assistant_snapshot_text = _extract_text_from_tool_result(assistant_snapshot)
                assistant_text = _extract_assistant_text_from_snapshot(assistant_snapshot_text)
                page_response_state: dict[str, Any] = {}
                if "evaluate_script" in tools:
                    try:
                        page_response = session.call_tool("evaluate_script", {
                            "function": """() => {
                              const visibleText = (node) => ((node && node.innerText) || "").trim();
                              const assistantNodes = [
                                ...document.querySelectorAll('[data-message-author-role="assistant"]'),
                                ...document.querySelectorAll('[data-testid^="conversation-turn-"] [data-message-author-role="assistant"]'),
                                ...document.querySelectorAll('main article')
                              ];
                              const assistantTexts = assistantNodes
                                .map(visibleText)
                                .filter((text) => text && !/^ChatGPT can make mistakes/i.test(text));
                              const buttons = [...document.querySelectorAll('button,[role="button"]')]
                                .map(visibleText)
                                .join("\\n");
                              const body = visibleText(document.body);
                              return {
                                assistantText: (assistantTexts[assistantTexts.length - 1] || "").slice(0, 30000),
                                pending: /stop streaming|stop generating/i.test(buttons)
                                  || /researching sources|searching the web|working on your request|reading sources|creating report|deep research is in progress/i.test(body)
                              };
                            }""",
                        })
                        page_response_state = _extract_json_payload(page_response)
                        dom_assistant_text = _assistant_text_from_page_state(page_response_state)
                        if dom_assistant_text:
                            assistant_text = dom_assistant_text
                        if page_response_state.get("pending"):
                            assistant_snapshot_text = "\n".join(
                                part for part in [assistant_snapshot_text, "StaticText \"Researching sources\""]
                                if part
                            )
                    except Exception:
                        page_response_state = {}
                if assistant_text and not _snapshot_is_streaming(assistant_snapshot_text) and not page_response_state.get("pending"):
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(3.0)
        else:
            assistant_text = ""

        response_path = artifact_dir / "chatgpt-response.md"
        response_text = assistant_text if "take_snapshot" in tools else ""
        if response_text:
            response_path.write_text(response_text + "\n", encoding="utf-8")
        response_state = _classify_chatgpt_response_state(assistant_snapshot_text, response_text)

        screenshot_path = artifact_dir / "chatgpt.png"
        screenshot_paths: list[str] = []
        if "take_screenshot" in tools:
            try:
                session.call_tool("take_screenshot", {"filePath": str(screenshot_path), "fullPage": True})
                if screenshot_path.exists():
                    screenshot_paths.append(str(screenshot_path))
            except Exception:
                pass

        final_snapshot_path = artifact_dir / "chatgpt-final.snapshot.txt"
        if "take_snapshot" in tools:
            try:
                if assistant_snapshot_text:
                    final_snapshot_path.write_text(assistant_snapshot_text, encoding="utf-8")
                else:
                    session.call_tool("take_snapshot", {"filePath": str(final_snapshot_path)})
            except Exception:
                pass

        status = "succeeded" if response_state["state"] == "response_captured" else "attention_required"
        summary = response_text.splitlines()[0].strip() if response_text else response_state["message"]
        return {
            "task_type": "literature",
            "status": status,
            "response_text": response_text,
            "raw_response_path": str(response_path) if response_path.exists() else "",
            "structured_output_path": "",
            "transcript_path": str(final_snapshot_path) if final_snapshot_path.exists() else (str(snapshot_path) if snapshot_path.exists() else ""),
            "screenshot_paths": screenshot_paths,
            "summary": summary,
            "mode_used": transport,
            "attention_required": None if status == "succeeded" else _response_attention_payload(response_state),
            "readiness_state": response_state["state"],
            "readiness_message": response_state["message"],
            "tab_reused": tab_reused,
        }

    def run_chatgpt_prompt(
        self,
        prompt_text: str,
        require_deep_research: bool = False,
        timeout_seconds: float = 45.0,
    ) -> dict[str, Any]:
        artifact_dir = Path(tempfile.mkdtemp(prefix="paperorchestra-chrome-task-"))
        with self.session(timeout_seconds=timeout_seconds) as session:
            session.initialize()
            return self._chatgpt_prompt_flow(session, prompt_text, require_deep_research, artifact_dir)


class ChromeDevToolsAdapter:
    """Persist normalized Chrome task results for orchestrator use."""

    def __init__(self, data_root: Path, env: dict[str, str] | None = None) -> None:
        self.data_root = Path(data_root).expanduser()
        self.env = dict(env or os.environ)

    def _stage_root(self, project_id: str, run_id: str, stage_name: str) -> Path:
        return storage.stage_dir(project_id, run_id, stage_name, self.data_root) / "browser" / "chrome_devtools"

    def _workspace_root(self, workspace: Path) -> Path:
        return workspace / "cache" / "browser" / "chrome_devtools"

    def _copy_optional_file(self, source_value: str, target_path: Path) -> str:
        source = Path(str(source_value or "")).expanduser()
        if not source.exists():
            return ""
        storage.ensure_dir(target_path.parent)
        shutil.copy2(source, target_path)
        return str(target_path)

    def _normalize_attention_required(self, payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        details = payload.get("details")
        normalized_details = details if isinstance(details, dict) else {}
        return {
            "reason": str(payload.get("reason", "") or "").strip(),
            "message": str(payload.get("message", "") or "").strip(),
            "details": normalized_details,
        }

    def _launch_cft_debug_helper_if_needed(self) -> bool:
        health = global_browser_setup.global_setup_health(self.env)
        cft = dict(health.get("chrome_for_testing") or {})
        if not cft.get("installed"):
            return False
        if cft.get("debuggable") and cft.get("ws_endpoint"):
            return True
        global_browser_setup.launch_debug_profile(self.env)
        deadline = time.monotonic() + float(self.env.get("PAPERORCHESTRA_CHROME_HELPER_WAIT_SECONDS", "15") or "15")
        while time.monotonic() < deadline:
            refreshed = global_browser_setup.global_setup_health(self.env)
            cft_refreshed = dict(refreshed.get("chrome_for_testing") or {})
            if cft_refreshed.get("debuggable") and cft_refreshed.get("ws_endpoint"):
                return True
            time.sleep(1.0)
        return False

    def _should_bootstrap_cft_helper(self) -> bool:
        health = global_browser_setup.global_setup_health(self.env)
        cft = dict(health.get("chrome_for_testing") or {})
        stable = dict(health.get("chrome_stable") or {})
        if not cft.get("installed"):
            return False
        if cft.get("debuggable") and cft.get("ws_endpoint"):
            return False
        if stable.get("debuggable") and (stable.get("ws_endpoint") or stable.get("browser_url")):
            return False
        return True

    def _should_bootstrap_cft_helper_after_runtime_failure(self) -> bool:
        health = global_browser_setup.global_setup_health(self.env)
        cft = dict(health.get("chrome_for_testing") or {})
        if not cft.get("installed"):
            return False
        if cft.get("debuggable") and cft.get("ws_endpoint"):
            return False
        if cft.get("relaunch_required"):
            return False
        return True

    def _build_runtime_attempts(self) -> tuple[list[dict[str, str]], str]:
        health = global_browser_setup.global_setup_health(self.env)
        cft = dict(health.get("chrome_for_testing") or {})
        stable = dict(health.get("chrome_stable") or {})
        attempts: list[dict[str, str]] = []
        fallback_notes: list[str] = []

        if cft.get("installed"):
            if cft.get("debuggable") and (cft.get("browser_url") or cft.get("ws_endpoint")):
                attempts.append({
                    "runtime": "chrome_for_testing",
                    "mode_used": "chrome_for_testing_attach",
                    "attach_mode": "ws_endpoint" if cft.get("ws_endpoint") else "browser_url",
                    "attach_transport": "ws_endpoint" if cft.get("ws_endpoint") else "browser_url",
                    "browser_url": str(cft.get("browser_url", "") or ""),
                    "ws_endpoint": str(cft.get("ws_endpoint", "") or ""),
                    "profile_root": str(cft.get("profile_root", "") or ""),
                    "executable_path": str(
                        global_browser_setup.chrome_executable_path(Path(str(cft.get("app_path", "") or "")))
                    ),
                })
            elif cft.get("relaunch_required"):
                fallback_notes.append("Chrome for Testing must be relaunched in debug mode before DevTools can attach.")

        if stable.get("installed"):
            if stable.get("debuggable") and (stable.get("browser_url") or stable.get("ws_endpoint")):
                attempts.append({
                    "runtime": "chrome_stable",
                    "mode_used": "chrome_stable_attach",
                    "attach_mode": "ws_endpoint" if stable.get("ws_endpoint") else "browser_url",
                    "attach_transport": "ws_endpoint" if stable.get("ws_endpoint") else "browser_url",
                    "browser_url": str(stable.get("browser_url", "") or ""),
                    "ws_endpoint": str(stable.get("ws_endpoint", "") or ""),
                    "profile_root": str(stable.get("profile_root", "") or ""),
                    "executable_path": "",
                })

        fallback_reason = " ".join(note for note in fallback_notes if note).strip()
        return attempts, fallback_reason

    def _run_client_attempt(
        self,
        attempt: dict[str, str],
        prompt_text: str,
        require_deep_research: bool,
        task_label: str,
        started_at: str,
        fallback_reason: str,
    ) -> dict[str, Any]:
        client = ChromeDevToolsMcpClient(
            env=self.env,
            attach_mode=str(attempt.get("attach_mode", "auto_connect") or "auto_connect"),
            channel=str(self.env.get("PAPERORCHESTRA_CHROME_CHANNEL", "stable") or "stable"),
            browser_url=str(attempt.get("browser_url", "") or ""),
            ws_endpoint=str(attempt.get("ws_endpoint", "") or self.env.get("PAPERORCHESTRA_CHROME_WS_ENDPOINT", "") or ""),
            executable_path=str(attempt.get("executable_path", "") or ""),
            user_data_dir=str(attempt.get("profile_root", "") or ""),
        )
        try:
            raw_result = client.run_chatgpt_prompt(
                prompt_text,
                require_deep_research=require_deep_research,
                timeout_seconds=float(self.env.get("PAPERORCHESTRA_CHROME_TASK_TIMEOUT_SECONDS", "45") or "45"),
            )
        except TimeoutError as exc:
            message = str(exc)
            if "approval" in message.casefold() or "remote debugging dialog" in message.casefold():
                return {
                    "task_id": task_label,
                    "task_type": "literature",
                    "status": "attention_required",
                    "started_at": started_at,
                    "finished_at": storage.utc_now(),
                    "mode_used": str(attempt.get("mode_used", "") or client.attach_mode),
                    "browser_runtime": str(attempt.get("runtime", "") or "chrome_stable"),
                    "attach_transport": str(attempt.get("attach_transport", "") or client.attach_mode),
                    "profile_root": str(attempt.get("profile_root", "") or ""),
                    "summary": "Approve Chrome remote debugging dialog.",
                    "fallback_reason": fallback_reason,
                    "readiness_state": "unknown",
                    "readiness_message": "Chrome approval required before ChatGPT warm-up can continue.",
                    "tab_reused": False,
                    "attention_required": {
                        "reason": "browser_approval_required",
                        "message": "Approve Chrome remote debugging dialog and retry the browser task.",
                        "details": {
                            "adapter": "chrome_devtools",
                            "error": message,
                        },
                    },
                }
            raise
        raw_result.setdefault("task_id", task_label)
        raw_result.setdefault("task_type", "literature")
        raw_result.setdefault("status", "succeeded")
        raw_result.setdefault("started_at", started_at)
        raw_result.setdefault("finished_at", storage.utc_now())
        raw_result.setdefault("mode_used", str(attempt.get("mode_used", "") or client.attach_mode))
        raw_result.setdefault("browser_runtime", str(attempt.get("runtime", "") or "chrome_stable"))
        raw_result.setdefault("attach_transport", str(attempt.get("attach_transport", "") or client.attach_mode))
        raw_result.setdefault("profile_root", str(attempt.get("profile_root", "") or ""))
        raw_result.setdefault("readiness_state", "unknown")
        raw_result.setdefault("readiness_message", "")
        raw_result.setdefault("tab_reused", False)
        has_response_artifact = bool(
            str(raw_result.get("response_text", "") or "").strip()
            or str(raw_result.get("raw_response_path", "") or raw_result.get("response_path", "") or "").strip()
            or str(raw_result.get("structured_output_path", "") or "").strip()
        )
        if str(raw_result.get("status", "") or "").strip() == "succeeded" and not has_response_artifact:
            response_state = {
                "state": "response_not_extractable",
                "reason": "chatgpt_response_not_extractable",
                "message": "ChatGPT prompt submission completed, but no assistant response was captured.",
            }
            raw_result["status"] = "attention_required"
            raw_result["summary"] = response_state["message"]
            raw_result["readiness_state"] = response_state["state"]
            raw_result["readiness_message"] = response_state["message"]
            raw_result["attention_required"] = _response_attention_payload(response_state)
        if fallback_reason and not str(raw_result.get("fallback_reason", "") or "").strip():
            raw_result["fallback_reason"] = fallback_reason
        return raw_result

    def _transport_attention_result(
        self,
        task_label: str,
        started_at: str,
        runtime: str,
        attach_transport: str,
        profile_root: str,
        fallback_reason: str,
        error_message: str,
    ) -> dict[str, Any]:
        message = "Chrome DevTools attached but did not respond to browser commands. Relaunch Chrome for Testing in debug mode, wait for ChatGPT to restore, then retry."
        return {
            "task_id": task_label,
            "task_type": "literature",
            "status": "attention_required",
            "started_at": started_at,
            "finished_at": storage.utc_now(),
            "mode_used": str(attach_transport or "chrome_for_testing_first"),
            "browser_runtime": str(runtime or "chrome_for_testing"),
            "attach_transport": str(attach_transport or ""),
            "profile_root": str(profile_root or ""),
            "summary": message,
            "fallback_reason": " ".join(part for part in [fallback_reason, error_message] if part).strip(),
            "readiness_state": "unknown",
            "readiness_message": message,
            "tab_reused": False,
            "attention_required": {
                "reason": "browser_bootstrap_failed",
                "message": message,
                "details": {
                    "adapter": "chrome_devtools",
                    "error": error_message,
                    "debug_helper": global_browser_setup.debug_browser_url(self.env),
                },
            },
        }

    def _persist_result(
        self,
        project_id: str,
        run_id: str,
        stage_name: str,
        workspace: Path,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        stage_root = self._stage_root(project_id, run_id, stage_name)
        workspace_root = self._workspace_root(workspace)
        storage.ensure_dir(stage_root)
        storage.ensure_dir(workspace_root)

        response_text = str(result.get("response_text", "") or "").strip()
        raw_response_path = ""
        if response_text:
            response_target = workspace_root / "response.md"
            response_target.write_text(response_text + "\n", encoding="utf-8")
            raw_response_path = str(response_target)
        elif result.get("raw_response_path"):
            copied = self._copy_optional_file(str(result.get("raw_response_path", "")), workspace_root / "response.md")
            raw_response_path = copied or str(result.get("raw_response_path", ""))

        structured_output_path = ""
        if result.get("structured_output_path"):
            copied = self._copy_optional_file(
                str(result.get("structured_output_path", "")),
                workspace_root / "structured_output.json",
            )
            structured_output_path = copied or str(result.get("structured_output_path", ""))

        transcript_path = ""
        if result.get("transcript_path"):
            copied = self._copy_optional_file(str(result.get("transcript_path", "")), stage_root / "transcript.txt")
            transcript_path = copied or str(result.get("transcript_path", ""))
        elif raw_response_path:
            transcript_path = raw_response_path

        screenshot_paths: list[str] = []
        for candidate in result.get("screenshot_paths", []) or []:
            source = Path(str(candidate)).expanduser()
            if not source.exists():
                continue
            target = stage_root / source.name
            shutil.copy2(source, target)
            screenshot_paths.append(str(target))

        persisted = {
            "task_id": str(result.get("task_id", "") or f"chrome-task-{uuid.uuid4().hex[:10]}"),
            "task_type": str(result.get("task_type", "literature") or "literature"),
            "adapter": "chrome_devtools",
            "status": str(result.get("status", "failed") or "failed"),
            "started_at": str(result.get("started_at", "") or storage.utc_now()),
            "finished_at": str(result.get("finished_at", "") or storage.utc_now()),
            "mode_used": str(result.get("mode_used", self.env.get("PAPERORCHESTRA_CHROME_ATTACH_MODE", "chrome_for_testing_first")) or "chrome_for_testing_first"),
            "summary": str(result.get("summary", "") or "Chrome DevTools MCP task completed."),
            "prompt_path": str(result.get("prompt_path", "") or ""),
            "raw_response_path": raw_response_path,
            "response_path": raw_response_path,
            "structured_output_path": structured_output_path,
            "transcript_path": transcript_path,
            "screenshot_paths": screenshot_paths,
            "artifacts": [path for path in [raw_response_path, structured_output_path, transcript_path, *screenshot_paths] if path],
            "fallback_reason": str(result.get("fallback_reason", "") or ""),
            "attention_required": self._normalize_attention_required(result.get("attention_required")),
            "browser_runtime": str(result.get("browser_runtime", "") or ""),
            "attach_transport": str(result.get("attach_transport", "") or ""),
            "profile_root": str(result.get("profile_root", "") or ""),
            "readiness_state": str(result.get("readiness_state", "") or ""),
            "readiness_message": str(result.get("readiness_message", "") or ""),
            "tab_reused": bool(result.get("tab_reused")),
        }

        result_path = stage_root / "browser_result.json"
        storage.atomic_write_json(result_path, persisted)
        persisted["result_path"] = str(result_path)
        persisted["artifacts"] = [str(result_path), *persisted["artifacts"]]
        return persisted

    def run_task(
        self,
        project_id: str,
        run_id: str,
        stage_name: str,
        prompt_text: str,
        workspace: Path,
        require_deep_research: bool = False,
        task_label: str = "chrome_task",
    ) -> dict[str, Any]:
        started_at = storage.utc_now()
        helper_attempted = False
        helper_ready = False
        if self._should_bootstrap_cft_helper():
            helper_attempted = True
            helper_ready = self._launch_cft_debug_helper_if_needed()
        attempts, fallback_reason = self._build_runtime_attempts()
        last_error = ""
        last_attempt: dict[str, str] = {}
        last_attention_result: dict[str, Any] | None = None

        for attempt in attempts:
            try:
                raw_result = self._run_client_attempt(
                    attempt,
                    prompt_text,
                    require_deep_research,
                    task_label,
                    started_at,
                    fallback_reason,
                )
            except Exception as exc:
                last_error = str(exc)
                last_attempt = attempt
                continue
            if raw_result.get("status") == "attention_required":
                last_attention_result = raw_result
                continue
            return self._persist_result(project_id, run_id, stage_name, workspace, raw_result)

        if not helper_attempted and self._should_bootstrap_cft_helper_after_runtime_failure():
            helper_attempted = True
            helper_ready = self._launch_cft_debug_helper_if_needed()
            if helper_ready:
                refreshed_attempts, refreshed_fallback_reason = self._build_runtime_attempts()
                cft_attempts = [
                    attempt for attempt in refreshed_attempts
                    if str(attempt.get("runtime", "") or "") == "chrome_for_testing"
                ]
                fallback_reason = " ".join(
                    part for part in [fallback_reason, refreshed_fallback_reason] if part
                ).strip()
                for attempt in cft_attempts:
                    try:
                        raw_result = self._run_client_attempt(
                            attempt,
                            prompt_text,
                            require_deep_research,
                            task_label,
                            started_at,
                            fallback_reason,
                        )
                    except Exception as exc:
                        last_error = str(exc)
                        last_attempt = attempt
                        continue
                    if raw_result.get("status") == "attention_required":
                        last_attention_result = raw_result
                        continue
                    return self._persist_result(project_id, run_id, stage_name, workspace, raw_result)

        if last_attention_result is not None:
            return self._persist_result(project_id, run_id, stage_name, workspace, last_attention_result)

        if helper_attempted and not helper_ready and not attempts:
            raw_result = {
                "task_id": task_label,
                "task_type": "literature",
                "status": "attention_required",
                "started_at": started_at,
                "finished_at": storage.utc_now(),
                "mode_used": "chrome_for_testing_launch",
                "browser_runtime": "chrome_for_testing",
                "attach_transport": "launched_executable",
                "profile_root": str(global_browser_setup.chrome_for_testing_profile_root(self.env)),
                "summary": "Chrome bootstrap failed before ChatGPT warm-up could start.",
                "fallback_reason": fallback_reason,
                "readiness_state": "unknown",
                "readiness_message": "Chrome for Testing debug bootstrap failed. Relaunch the debug helper, wait for ChatGPT to restore, then retry.",
                "tab_reused": False,
                "attention_required": {
                    "reason": "browser_bootstrap_failed",
                    "message": "Chrome for Testing did not become debuggable. Relaunch the debug helper and retry.",
                    "details": {
                        "adapter": "chrome_devtools",
                        "debug_helper": global_browser_setup.debug_browser_url(self.env),
                    },
                },
            }
            return self._persist_result(project_id, run_id, stage_name, workspace, raw_result)

        if "timed out waiting for mcp response header" in last_error.casefold():
            raw_result = self._transport_attention_result(
                task_label=task_label,
                started_at=started_at,
                runtime=str(last_attempt.get("runtime", "") or "chrome_for_testing"),
                attach_transport=str(last_attempt.get("attach_transport", "") or last_attempt.get("attach_mode", "") or ""),
                profile_root=str(last_attempt.get("profile_root", "") or ""),
                fallback_reason=fallback_reason,
                error_message=last_error,
            )
            return self._persist_result(project_id, run_id, stage_name, workspace, raw_result)

        if fallback_reason and not attempts:
            raw_result = {
                "task_id": task_label,
                "task_type": "literature",
                "status": "attention_required",
                "started_at": started_at,
                "finished_at": storage.utc_now(),
                "mode_used": "chrome_for_testing_attach",
                "browser_runtime": "chrome_for_testing",
                "attach_transport": "browser_url",
                "profile_root": str(global_browser_setup.chrome_for_testing_profile_root(self.env)),
                "summary": "Relaunch Chrome for Testing in debug mode to attach DevTools.",
                "fallback_reason": fallback_reason,
                "readiness_state": "unknown",
                "readiness_message": "Chrome for Testing must be relaunched in debug mode before ChatGPT warm-up can continue.",
                "tab_reused": False,
                "attention_required": {
                    "reason": "chrome_relaunch_required",
                    "message": "Relaunch Chrome for Testing in debug mode and retry the browser task.",
                    "details": {
                        "adapter": "chrome_devtools",
                        "debug_helper": global_browser_setup.debug_browser_url(self.env),
                    },
                },
            }
            return self._persist_result(project_id, run_id, stage_name, workspace, raw_result)

        raw_result = {
            "task_id": task_label,
            "task_type": "literature",
            "status": "failed",
            "started_at": started_at,
            "finished_at": storage.utc_now(),
            "mode_used": "chrome_for_testing_first",
            "summary": f"Chrome DevTools MCP task failed: {last_error or 'no attachable Chrome runtime was available'}",
            "fallback_reason": " ".join(part for part in [fallback_reason, last_error] if part).strip(),
            "attention_required": None,
            "readiness_state": "unknown",
            "readiness_message": "",
            "tab_reused": False,
        }
        return self._persist_result(project_id, run_id, stage_name, workspace, raw_result)
