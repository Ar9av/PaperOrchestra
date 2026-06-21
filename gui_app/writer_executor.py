#!/usr/bin/env python3
"""Codex execution wrapper used by the PaperOrchestra orchestrator."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class WriterExecutor:
    """Run Codex stage prompts and capture transcripts through one surface."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root).expanduser()

    @staticmethod
    def _model(env: dict[str, str]) -> str:
        return env.get("PAPERORCHESTRA_CODEX_MODEL", "").strip() or "gpt-5.4"

    @staticmethod
    def _reasoning_effort(env: dict[str, str]) -> str:
        return env.get("PAPERORCHESTRA_CODEX_REASONING_EFFORT", "").strip() or "medium"

    @staticmethod
    def _structured_timeout_seconds(env: dict[str, str]) -> float:
        raw_value = env.get("PAPERORCHESTRA_CODEX_OUTPUT_TIMEOUT_SECONDS", "").strip()
        if not raw_value:
            return 90.0
        try:
            return max(float(raw_value), 1.0)
        except ValueError:
            return 90.0

    @classmethod
    def _command_timeout_seconds(cls, env: dict[str, str], structured: bool) -> float | None:
        raw_value = env.get("PAPERORCHESTRA_CODEX_TIMEOUT_SECONDS", "").strip()
        if raw_value:
            try:
                return max(float(raw_value), 1.0)
            except ValueError:
                return cls._structured_timeout_seconds(env) if structured else None
        if structured:
            return cls._structured_timeout_seconds(env)
        return None

    @staticmethod
    def _extract_json_object(text: str, required_keys: set[str] | None = None) -> dict[str, Any] | None:
        decoder = json.JSONDecoder()
        candidate: dict[str, Any] | None = None
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                payload, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            if required_keys and not required_keys.issubset(payload.keys()):
                continue
            candidate = payload
        return candidate

    def _recover_structured_output(self, log_path: Path, transcript_path: Path) -> bool:
        if not log_path.exists():
            return False
        payload = self._extract_json_object(
            log_path.read_text(encoding="utf-8"),
            required_keys={"plotting_plan", "intro_related_work_plan", "section_plan"},
        )
        if payload is None:
            return False
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("Recovered structured output from stage.log after Codex timeout.\n")
        return True

    def build_command(
        self,
        workspace: Path,
        transcript_path: Path,
        prompt: str,
        env: dict[str, str],
        output_schema_path: Path | None = None,
        sandbox_mode: str = "workspace-write",
    ) -> list[str]:
        codex_bin = env.get("CODEX_BIN", "").strip() or "codex"
        command = [
            codex_bin,
            "exec",
            "-m",
            self._model(env),
            "-c",
            f'model_reasoning_effort="{self._reasoning_effort(env)}"',
            "--sandbox",
            sandbox_mode,
            "-C",
            str(self.repo_root),
            "--add-dir",
            str(workspace),
            "-o",
            str(transcript_path),
        ]
        if output_schema_path is not None:
            command.extend(["--output-schema", str(output_schema_path)])
        command.append(prompt)
        return command

    def run_stage(
        self,
        workspace: Path,
        transcript_path: Path,
        prompt: str,
        log_path: Path,
        env: dict[str, str],
        output_schema_path: Path | None = None,
        sandbox_mode: str = "workspace-write",
    ) -> dict[str, Any]:
        command = self.build_command(
            workspace,
            transcript_path,
            prompt,
            env,
            output_schema_path=output_schema_path,
            sandbox_mode=sandbox_mode,
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"$ {' '.join(command)}\n")
            try:
                process = subprocess.run(
                    command,
                    cwd=str(self.repo_root),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                    timeout=self._command_timeout_seconds(env, structured=output_schema_path is not None),
                )
            except subprocess.TimeoutExpired as exc:
                if output_schema_path is not None and self._recover_structured_output(log_path, transcript_path):
                    return {
                        "command": command,
                        "transcript_path": str(transcript_path),
                        "recovered_from_log": True,
                    }
                raise RuntimeError(f"Command timed out after {exc.timeout} seconds: {' '.join(command)}") from exc
        if process.returncode != 0:
            raise RuntimeError(f"Command failed with exit code {process.returncode}: {' '.join(command)}")
        return {
            "command": command,
            "transcript_path": str(transcript_path),
        }
