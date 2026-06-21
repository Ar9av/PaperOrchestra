#!/usr/bin/env python3
"""Run the PaperOrchestra acceptance walkthrough against the local FastAPI app."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gui_app import storage


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def timestamp_slug() -> str:
    return storage.utc_now().replace(":", "").replace("-", "").replace("+00:00", "").replace("T", "-")


def _cache_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _acceptance_s2_response() -> dict[str, object]:
    return {
        "total": 2,
        "data": [
            {
                "paperId": "vaswani2017",
                "title": "Attention Is All You Need",
                "abstract": "The Transformer replaces recurrence with self-attention for sequence modeling.",
                "year": 2017,
                "publicationDate": "2017-06-12",
                "authors": [{"name": "Ashish Vaswani"}],
                "venue": "NeurIPS",
                "externalIds": {"DOI": "10.5555/3295222.3295349"},
            },
            {
                "paperId": "beltagy2020",
                "title": "Longformer: The Long-Document Transformer",
                "abstract": "Longformer combines windowed attention with task-motivated global attention.",
                "year": 2020,
                "publicationDate": "2020-04-10",
                "authors": [{"name": "Iz Beltagy"}],
                "venue": "arXiv",
                "externalIds": {"ArXiv": "2004.05150"},
            },
        ],
    }


def seed_acceptance_s2_cache(db_path: Path) -> Path:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path))
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                key TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        payload = json.dumps(_acceptance_s2_response(), ensure_ascii=False)
        now = time.time()
        for query in (
            "Attention Is All You Need",
            "Longformer: The Long-Document Transformer",
            "Transformer quadratic attention scaling in long-context tasks",
            "Sparse attention baselines for long-document question answering and summarization before 2024-10-01",
            "Differentiable top-k or routing mechanisms for learned sparse attention before 2024-10-01",
            "Benchmarks and evaluation papers covering NaturalQuestions-Long, NarrativeQA, and GovReport-Summ before 2024-10-01",
        ):
            connection.execute(
                """
                INSERT INTO cache_entries(key, response_json, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    response_json = excluded.response_json,
                    updated_at = excluded.updated_at
                """,
                (_cache_key(query), payload, now),
            )
        connection.commit()
    finally:
        connection.close()
    return db_path


def parse_launcher_stdout(stdout: str) -> dict[str, object]:
    url_match = re.search(r"PaperOrchestra GUI started at (\S+) \(pid (\d+)\)", stdout)
    if not url_match:
        raise RuntimeError(f"Could not parse launcher output:\n{stdout}")
    return {
        "base_url": str(url_match.group(1)),
        "pid": int(url_match.group(2)),
    }


def dashboard_url(base_url: str, project_id: str, run_id: str | None = None) -> str:
    query = {"step": "run"}
    if run_id:
        query["run_id"] = run_id
    return f"{base_url}/projects/{urllib.parse.quote(project_id, safe='')}?{urllib.parse.urlencode(query)}"


def run_api_url(base_url: str, project_id: str, run_id: str) -> str:
    return (
        f"{base_url}/api/projects/{urllib.parse.quote(project_id, safe='')}"
        f"/runs/{urllib.parse.quote(run_id, safe='')}"
    )


def launch_app(host: str, port: int, data_root: Path, env: dict[str, str]) -> dict[str, object]:
    command = [
        str(storage.repo_python_executable(sys.executable)),
        "scripts/launch_gui.py",
        "--no-browser",
        "--host",
        host,
        "--port",
        str(port),
        "--data-root",
        str(data_root),
    ]
    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Failed to launch the app.")
    launched = parse_launcher_stdout(completed.stdout)
    launched["stdout"] = completed.stdout
    return launched


def require_playwright():
    try:
        module = importlib.import_module("playwright.sync_api")
    except ModuleNotFoundError as exc:
        python = str(storage.repo_python_executable(sys.executable))
        raise RuntimeError(
            "Playwright browser automation is not installed in the repo virtualenv. "
            f"Run `{python} -m pip install playwright` and `{python} -m playwright install chromium`, then retry."
        ) from exc
    return module.sync_playwright


def save_browser_screenshot(page, output_root: Path, name: str) -> None:
    storage.ensure_dir(output_root)
    page.screenshot(path=str(output_root / name), full_page=True)


def bootstrap_via_browser(base_url: str, output_root: Path, examples_root: Path) -> dict[str, object]:
    sync_playwright = require_playwright()
    title = f"Acceptance Walkthrough {int(time.time())}"
    with sync_playwright() as playwright:
        browser = None
        page = None
        try:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(base_url, wait_until="domcontentloaded")
            save_browser_screenshot(page, output_root, "01-dashboard.png")
            page.locator('input[name="title"]').fill(title)
            page.locator('input[name="venue"]').fill("ToyConf Acceptance")
            page.locator('textarea[name="description"]').fill("Acceptance walkthrough project")
            page.locator('form[action="/projects"] button').click()
            page.wait_for_url(re.compile(r"/projects/[^?]+\?step=setup"))

            project_match = re.search(r"/projects/([^/?]+)", page.url)
            if not project_match:
                raise RuntimeError("Could not determine project id from setup URL.")
            project_id = project_match.group(1)

            save_browser_screenshot(page, output_root, "02-setup.png")
            page.locator('input[name="title"]').fill(title)
            page.locator('input[name="venue"]').fill("ToyConf Acceptance")
            page.locator('textarea[name="description"]').fill("Acceptance walkthrough project")
            page.locator('form[action$="/save/setup"] button').click()
            page.wait_for_url(re.compile(rf"/projects/{re.escape(project_id)}\?step=inputs&panel=idea"))

            save_browser_screenshot(page, output_root, "03-inputs-idea.png")
            page.locator('input[name="idea_upload"]').set_input_files(str(examples_root / "idea.md"))
            page.locator('form[action$="/save/input/idea"] button').click()
            page.wait_for_url(re.compile(rf"/projects/{re.escape(project_id)}\?step=inputs&panel=idea"))

            page.goto(f"{base_url}/projects/{project_id}?step=inputs&panel=experimental", wait_until="domcontentloaded")
            save_browser_screenshot(page, output_root, "04-inputs-experimental.png")
            page.locator('input[name="experimental_upload"]').set_input_files(str(examples_root / "experimental_log.md"))
            page.locator('form[action$="/save/input/experimental"] button').click()
            page.wait_for_url(re.compile(rf"/projects/{re.escape(project_id)}\?step=inputs&panel=experimental"))

            page.goto(f"{base_url}/projects/{project_id}?step=inputs&panel=template", wait_until="domcontentloaded")
            save_browser_screenshot(page, output_root, "05-inputs-template.png")
            page.locator('input[name="template_upload"]').set_input_files(str(examples_root / "template.tex"))
            page.locator('form[action$="/save/input/template"] button').click()
            page.wait_for_url(re.compile(rf"/projects/{re.escape(project_id)}\?step=inputs&panel=template"))

            page.goto(f"{base_url}/projects/{project_id}?step=inputs&panel=guidelines", wait_until="domcontentloaded")
            save_browser_screenshot(page, output_root, "06-inputs-guidelines.png")
            page.locator('input[name="guidelines_upload"]').set_input_files(str(examples_root / "conference_guidelines.md"))
            page.locator('form[action$="/save/input/guidelines"] button').click()
            page.wait_for_url(re.compile(rf"/projects/{re.escape(project_id)}\?step=inputs&panel=guidelines"))

            page.goto(f"{base_url}/projects/{project_id}?step=review", wait_until="domcontentloaded")
            page.wait_for_url(re.compile(rf"/projects/{re.escape(project_id)}\?step=review"))

            save_browser_screenshot(page, output_root, "07-review.png")
            page.get_by_role("button", name="Start autonomous run").click()
            page.wait_for_url(re.compile(rf"/projects/{re.escape(project_id)}\?step=run"))
            save_browser_screenshot(page, output_root, "08-run-started.png")

            match = re.search(r"[?&]run_id=([^&]+)", page.url)
            run_id = urllib.parse.unquote(match.group(1)) if match else ""
            if not run_id:
                body_text = page.locator("body").inner_text()
                match = re.search(r"Run id:\s*([A-Za-z0-9._:-]+)", body_text)
                run_id = match.group(1) if match else ""
            if not run_id:
                raise RuntimeError("Could not determine run id from run dashboard.")

            return {
                "project_id": project_id,
                "run_id": run_id,
                "run_url": dashboard_url(base_url, project_id, run_id),
                "project_url": f"{base_url}/projects/{project_id}",
            }
        except Exception as exc:
            if page is not None:
                try:
                    save_browser_screenshot(page, output_root, "bootstrap-failure.png")
                except Exception:
                    pass
            if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
                python = str(storage.repo_python_executable(sys.executable))
                raise RuntimeError(
                    "Playwright Chromium is not installed in the repo virtualenv. "
                    f"Run `{python} -m playwright install chromium` and retry."
                ) from exc
            raise
        finally:
            if browser is not None:
                browser.close()


def retry_stage_via_browser(base_url: str, output_root: Path, project_id: str, run_id: str, stage_name: str) -> dict[str, object]:
    sync_playwright = require_playwright()
    with sync_playwright() as playwright:
        browser = None
        page = None
        try:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(dashboard_url(base_url, project_id, run_id), wait_until="domcontentloaded")
            save_browser_screenshot(page, output_root, f"retry-{stage_name}-before.png")
            action = f"/projects/{project_id}/runs/{run_id}/retry/{stage_name}"
            action_url = urllib.parse.urljoin(base_url, action)
            with page.expect_response(lambda response: response.request.method == "POST" and response.url == action_url):
                page.locator(f'form[action="{action}"] button').click()
            page.wait_for_load_state("networkidle")
            save_browser_screenshot(page, output_root, f"retry-{stage_name}-after.png")
            return {"retried_stage": stage_name, "run_id": run_id}
        except Exception as exc:
            if page is not None:
                try:
                    save_browser_screenshot(page, output_root, f"retry-{stage_name}-failure.png")
                except Exception:
                    pass
            if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
                python = str(storage.repo_python_executable(sys.executable))
                raise RuntimeError(
                    "Playwright Chromium is not installed in the repo virtualenv. "
                    f"Run `{python} -m playwright install chromium` and retry."
                ) from exc
            raise
        finally:
            if browser is not None:
                browser.close()


def fetch_json(url: str, timeout_seconds: float = 5.0) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str, timeout_seconds: float = 5.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8", errors="replace")


def wait_for_run(base_url: str, project_id: str, run_id: str, timeout_seconds: float = 900.0) -> tuple[dict[str, object], list[dict[str, object]]]:
    url = run_api_url(base_url, project_id, run_id)
    deadline = time.monotonic() + max(timeout_seconds, 1.0)
    snapshots: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        payload = fetch_json(url, timeout_seconds=10.0)
        snapshots.append({
            "at": storage.utc_now(),
            "status": payload.get("status"),
            "current_stage": payload.get("current_stage"),
            "updated_at": payload.get("updated_at"),
        })
        if str(payload.get("status")) in storage.TERMINAL_RUN_STATUSES:
            return payload, snapshots
        time.sleep(1.0)
    raise RuntimeError(f"Timed out waiting for run {run_id} to reach a terminal state.")


def wait_until_run_inactive(data_root: Path, project_id: str, run_id: str, timeout_seconds: float = 30.0) -> dict[str, object]:
    deadline = time.monotonic() + max(timeout_seconds, 1.0)
    while time.monotonic() < deadline:
        payload = storage.load_run(project_id, run_id, data_root)
        if payload and not storage.is_pid_running(payload.get("pid")):
            return payload
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for run {run_id} to become inactive.")


def wait_for_retry_start(base_url: str, project_id: str, run_id: str, stage_name: str,
                         previous_attempt: int, timeout_seconds: float = 60.0) -> dict[str, object]:
    url = run_api_url(base_url, project_id, run_id)
    deadline = time.monotonic() + max(timeout_seconds, 1.0)
    while time.monotonic() < deadline:
        payload = fetch_json(url, timeout_seconds=10.0)
        stage_payload = payload.get("stages", {}).get(stage_name, {})
        attempt = int(stage_payload.get("attempt", 0) or 0)
        if attempt > previous_attempt or str(payload.get("status")) == "running":
            return payload
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for retry of stage `{stage_name}` to begin.")


def verify_parallel_join(data_root: Path, project_id: str, run_id: str) -> None:
    events = storage.load_jsonl(storage.run_events_file(project_id, run_id, data_root))
    section_running_index = next(
        index for index, item in enumerate(events)
        if item.get("type") == "stage_updated"
        and item.get("details", {}).get("stage") == "section_writing"
        and item.get("details", {}).get("fields", {}).get("status") == "running"
    )
    plotting_done_index = next(
        index for index, item in enumerate(events)
        if item.get("type") == "stage_updated"
        and item.get("details", {}).get("stage") == "plotting"
        and item.get("details", {}).get("fields", {}).get("status") == "succeeded"
    )
    literature_done_index = next(
        index for index, item in enumerate(events)
        if item.get("type") == "stage_updated"
        and item.get("details", {}).get("stage") == "literature"
        and item.get("details", {}).get("fields", {}).get("status") == "succeeded"
    )
    if not (plotting_done_index < section_running_index and literature_done_index < section_running_index):
        raise RuntimeError("Section writing started before plotting and literature had both completed.")


def verify_targeted_retry(before_retry: dict[str, object], after_retry: dict[str, object], stage_name: str) -> None:
    stages_before = before_retry.get("stages", {})
    stages_after = after_retry.get("stages", {})
    for sibling in ("plotting", "literature"):
        if sibling == stage_name:
            continue
        if stages_before.get(sibling, {}).get("status") == "succeeded":
            if stages_after.get(sibling, {}).get("attempt") != stages_before.get(sibling, {}).get("attempt"):
                raise RuntimeError(f"Targeted retry unexpectedly reran succeeded sibling stage `{sibling}`.")
    if stages_after.get(stage_name, {}).get("attempt", 0) <= stages_before.get(stage_name, {}).get("attempt", 0):
        raise RuntimeError(f"Retry did not create a new attempt for `{stage_name}`.")


def resolve_final_pdf_href(base_url: str, project_id: str, run_id: str, output_root: Path) -> str:
    sync_playwright = require_playwright()
    with sync_playwright() as playwright:
        browser = None
        page = None
        try:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(dashboard_url(base_url, project_id, run_id), wait_until="domcontentloaded")
            save_browser_screenshot(page, output_root, "final-pdf-link.png")
            href = page.get_by_role("link", name="Open final PDF").first.get_attribute("href") or ""
            if not href:
                raise RuntimeError("Could not find the final PDF link on the run dashboard.")
            if href.startswith("http://") or href.startswith("https://"):
                return href
            return urllib.parse.urljoin(base_url, href)
        except Exception as exc:
            if page is not None:
                try:
                    save_browser_screenshot(page, output_root, "final-pdf-link-failure.png")
                except Exception:
                    pass
            if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
                python = str(storage.repo_python_executable(sys.executable))
                raise RuntimeError(
                    "Playwright Chromium is not installed in the repo virtualenv. "
                    f"Run `{python} -m playwright install chromium` and retry."
                ) from exc
            raise
        finally:
            if browser is not None:
                browser.close()


def fetch_final_pdf(url: str, output_root: Path) -> Path:
    target = output_root / "final-paper.pdf"
    with urllib.request.urlopen(url, timeout=20.0) as response:
        target.write_bytes(response.read())
    if not target.read_bytes().startswith(b"%PDF"):
        raise RuntimeError("Fetched final PDF does not look like a valid PDF.")
    return target


def write_summary_and_capture_artifacts(output_root: Path, project_id: str, run_id: str, data_root: Path,
                                        summary: dict[str, object]) -> Path:
    storage.ensure_dir(output_root)
    run_root = storage.run_dir(project_id, run_id, data_root)
    copied_root = output_root / "run-artifacts"
    if copied_root.exists():
        shutil.rmtree(copied_root)
    if run_root.exists():
        shutil.copytree(run_root, copied_root)
    summary_path = output_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary_path


def terminate_process_group(pid: int | None) -> None:
    if not pid:
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-root", default="")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--examples-root", default=str(REPO_ROOT / "examples" / "minimal" / "inputs"))
    parser.add_argument("--forced-failure-stage", default="compile")
    parser.add_argument("--keep-artifacts-on-failure", action="store_true")
    args = parser.parse_args(argv)

    host = args.host
    port = args.port or free_port()
    examples_root = Path(args.examples_root).expanduser()
    output_root = Path(args.output_root).expanduser() if args.output_root else REPO_ROOT / "output" / "acceptance" / timestamp_slug()
    data_root = Path(args.data_root).expanduser() if args.data_root else Path(tempfile.mkdtemp(prefix="paper-orchestra-acceptance-data-"))
    created_temp_data_root = not bool(args.data_root)
    storage.ensure_dir(output_root)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PAPERORCHESTRA_ACCEPTANCE_FIXTURES"] = "1"
    env["PAPERORCHESTRA_ACCEPTANCE_DISABLE_FIXTURES"] = "outline"
    env.setdefault("PAPERORCHESTRA_CODEX_OUTPUT_TIMEOUT_SECONDS", "8")
    env.setdefault("PAPERORCHESTRA_CODEX_TIMEOUT_SECONDS", "8")
    env["PAPERORCHESTRA_S2_CACHE_DB"] = str(seed_acceptance_s2_cache(data_root / "shared-cache" / "semantic_scholar.sqlite3"))
    forced_failure_stage = str(args.forced_failure_stage or "").strip().lower()
    if forced_failure_stage and forced_failure_stage not in {"none", "off", "false"}:
        env["PAPERORCHESTRA_ACCEPTANCE_MODE"] = "1"
        env["PAPERORCHESTRA_ACCEPTANCE_FAIL_STAGE"] = forced_failure_stage
    else:
        forced_failure_stage = ""
        env.pop("PAPERORCHESTRA_ACCEPTANCE_MODE", None)
        env.pop("PAPERORCHESTRA_ACCEPTANCE_FAIL_STAGE", None)

    launched: dict[str, object] | None = None
    project_id = ""
    run_id = ""
    summary: dict[str, object] = {
        "status": "failed",
        "host": host,
        "port": port,
        "data_root": str(data_root),
        "output_root": str(output_root),
        "forced_failure_stage": forced_failure_stage or None,
    }
    try:
        launched = launch_app(host=host, port=port, data_root=data_root, env=env)
        base_url = str(launched["base_url"])
        bootstrap = bootstrap_via_browser(base_url, output_root / "browser", examples_root)
        project_id = str(bootstrap["project_id"])
        run_id = str(bootstrap["run_id"])

        first_run, first_snapshots = wait_for_run(base_url, project_id, run_id)
        summary["initial_snapshots"] = first_snapshots

        if forced_failure_stage:
            if first_run.get("status") != "failed":
                raise RuntimeError(f"Expected forced-failure run to fail at `{forced_failure_stage}`, got `{first_run.get('status')}`.")
            failed_stage = first_run.get("stages", {}).get(forced_failure_stage, {})
            if failed_stage.get("status") != "failed":
                raise RuntimeError(f"Expected stage `{forced_failure_stage}` to be failed after failpoint.")
            wait_until_run_inactive(data_root, project_id, run_id)
            retry_stage_via_browser(
                base_url=base_url,
                output_root=output_root / "browser",
                project_id=project_id,
                run_id=run_id,
                stage_name=forced_failure_stage,
            )
            wait_for_retry_start(
                base_url=base_url,
                project_id=project_id,
                run_id=run_id,
                stage_name=forced_failure_stage,
                previous_attempt=int(failed_stage.get("attempt", 0) or 0),
            )
            final_run, final_snapshots = wait_for_run(base_url, project_id, run_id)
            verify_targeted_retry(first_run, final_run, forced_failure_stage)
            summary["retry_snapshots"] = final_snapshots
        else:
            final_run = first_run

        if final_run.get("status") != "succeeded":
            raise RuntimeError(f"Acceptance walkthrough ended in `{final_run.get('status')}` instead of `succeeded`.")
        verify_parallel_join(data_root, project_id, run_id)

        final_pdf_url = resolve_final_pdf_href(base_url, project_id, run_id, output_root / "browser")
        final_pdf_path = fetch_final_pdf(final_pdf_url, output_root)

        summary.update({
            "status": "succeeded",
            "base_url": base_url,
            "project_id": project_id,
            "run_id": run_id,
            "final_pdf_url": final_pdf_url,
            "final_pdf_path": str(final_pdf_path),
            "final_run_status": final_run.get("status"),
        })
        summary_path = write_summary_and_capture_artifacts(output_root, project_id, run_id, data_root, summary)
        print(f"Acceptance walkthrough succeeded. Summary written to {summary_path}")
        return 0
    except Exception as exc:
        summary["error"] = str(exc)
        if launched:
            summary["base_url"] = launched.get("base_url")
        if project_id:
            summary["project_id"] = project_id
        if run_id:
            summary["run_id"] = run_id
            summary_path = write_summary_and_capture_artifacts(output_root, project_id, run_id, data_root, summary)
            print(f"Acceptance walkthrough failed. Summary written to {summary_path}", file=sys.stderr)
        else:
            summary_path = output_root / "summary.json"
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"Acceptance walkthrough failed. Summary written to {summary_path}", file=sys.stderr)
        return 1
    finally:
        terminate_process_group(int(launched["pid"]) if launched else None)
        if created_temp_data_root and not (args.keep_artifacts_on_failure and summary.get("status") != "succeeded"):
            shutil.rmtree(data_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
