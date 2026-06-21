#!/usr/bin/env python3
"""Legacy Atlas-handoff browser GUI for PaperOrchestra.

This module is retained temporarily for compatibility and reference only. The
supported UI is the FastAPI control room in ``gui_app.web``, launched via
``scripts/launch_gui.py``. Do not target this module for new product work.
"""

from __future__ import annotations

import argparse
import html
import mimetypes
import os
import re
import subprocess
import sys
import urllib.parse
import uuid
import webbrowser
from datetime import datetime
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import atlas_controller
from . import handoff
from . import storage

DATA_ROOT = Path(os.environ.get("PAPERORCHESTRA_GUI_DATA_ROOT", storage.DEFAULT_DATA_ROOT)).expanduser()
STEPS = ["setup", "idea", "experimental", "materials", "review", "run", "outputs"]


def parse_markdown_sections(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", text, flags=re.M))
    for idx, match in enumerate(matches):
        heading = match.group(1).strip().lower()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        found[heading] = text[start:end].strip()
    return found


def format_timestamp(raw: str | None) -> str:
    if not raw:
        return "n/a"
    try:
        return datetime.fromisoformat(raw).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return raw


def new_run_id(kind: str) -> str:
    timestamp = storage.utc_now().replace(":", "").replace("-", "").replace("+00:00", "").replace("T", "-")
    return f"{kind}-{timestamp}-{uuid.uuid4().hex[:6]}"


def html_page(title: str, body: str) -> bytes:
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f5f1e8;
      --paper: #fffdf8;
      --ink: #1f2430;
      --muted: #5a6272;
      --line: #d8cfbf;
      --accent: #0d6b63;
      --accent-soft: #e0f1ee;
      --warning: #8f5a1f;
      --danger: #9b2d30;
      --shadow: 0 18px 50px rgba(31, 36, 48, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(13,107,99,0.10), transparent 30%),
        linear-gradient(180deg, #f9f4ea 0%, var(--bg) 100%);
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .shell {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 20px 60px;
    }}
    .hero, .card {{
      background: rgba(255, 253, 248, 0.92);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(216, 207, 191, 0.9);
      border-radius: 20px;
      box-shadow: var(--shadow);
    }}
    .hero {{
      padding: 28px;
      margin-bottom: 24px;
    }}
    .hero h1 {{ margin: 0 0 10px; font-size: 2rem; }}
    .hero p {{ margin: 0; color: var(--muted); line-height: 1.55; max-width: 80ch; }}
    .grid {{
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    }}
    .card {{
      padding: 20px;
    }}
    .card h2, .card h3 {{ margin-top: 0; }}
    .muted {{ color: var(--muted); }}
    .mono {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.95rem;
      background: #f7f7f4;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 12px;
      overflow-x: auto;
    }}
    .tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 18px;
    }}
    .tab {{
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #fff;
    }}
    .tab.active {{
      background: var(--accent-soft);
      border-color: rgba(13,107,99,0.35);
      color: var(--accent);
      font-weight: 700;
    }}
    form {{ display: grid; gap: 14px; }}
    label {{ display: grid; gap: 6px; font-weight: 700; }}
    input[type=text], textarea {{
      width: 100%;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      font: inherit;
    }}
    textarea {{ min-height: 180px; resize: vertical; line-height: 1.45; }}
    input[type=file] {{ font: inherit; }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 6px;
    }}
    button, .button {{
      appearance: none;
      border: none;
      border-radius: 999px;
      padding: 12px 16px;
      background: var(--accent);
      color: white;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    .button.secondary, button.secondary {{
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
    }}
    .status {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 0.9rem;
      background: #f4f3ef;
      border: 1px solid var(--line);
    }}
    .status.validated, .status.completed {{ background: #e7f4ef; color: #185b45; }}
    .status.running {{ background: #eef6ff; color: #285ea8; }}
    .status.failed, .status.interrupted {{ background: #fff0ef; color: var(--danger); }}
    .hint {{
      margin: 0;
      padding: 12px 14px;
      border-radius: 14px;
      background: #f8f6f1;
      border: 1px solid var(--line);
      color: var(--muted);
      line-height: 1.55;
    }}
    .split {{
      display: grid;
      gap: 18px;
      grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
      align-items: start;
    }}
    .file-list, .meta-list {{
      display: grid;
      gap: 10px;
    }}
    .file-item {{
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #fff;
    }}
    pre.log {{
      margin: 0;
      min-height: 220px;
      max-height: 520px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    @media (max-width: 860px) {{
      .split {{ grid-template-columns: 1fr; }}
      .hero h1 {{ font-size: 1.65rem; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    {body}
  </main>
</body>
</html>"""
    return page.encode("utf-8")


class GuiHandler(BaseHTTPRequestHandler):
    server_version = "PaperOrchestraGUI/0.1"

    def parse_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(content_length) if content_length else b""
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            mime = BytesParser(policy=default).parsebytes(
                f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + raw
            )
            payload: dict[str, Any] = {}
            for part in mime.iter_parts():
                if part.get_content_disposition() != "form-data":
                    continue
                name = part.get_param("name", header="content-disposition")
                if not name:
                    continue
                filename = part.get_filename()
                value: Any
                if filename:
                    value = {"filename": filename, "content": part.get_payload(decode=True) or b""}
                else:
                    value = part.get_content()
                if name in payload:
                    if not isinstance(payload[name], list):
                        payload[name] = [payload[name]]
                    payload[name].append(value)
                else:
                    payload[name] = value
            return payload
        parsed = urllib.parse.parse_qs(raw.decode("utf-8"), keep_blank_values=True)
        return {key: values[-1] for key, values in parsed.items()}

    def send_html(self, title: str, body: str, status: int = 200) -> None:
        data = html_page(title, body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def render_error(self, message: str, status: int = 404) -> None:
        self.send_html("PaperOrchestra GUI", f"""
        <section class="hero">
          <h1>PaperOrchestra Local Browser GUI</h1>
          <p>{html.escape(message)}</p>
          <div class="actions"><a class="button secondary" href="/">Back to dashboard</a></div>
        </section>
        """, status=status)

    def project_or_404(self, project_id: str) -> dict[str, Any] | None:
        project = storage.load_project(project_id, DATA_ROOT)
        if not project:
            self.render_error("Project not found.")
            return None
        return storage.reconcile_project_runs(project, DATA_ROOT)

    def start_job(self, project: dict[str, Any], kind: str) -> str:
        run_id = new_run_id(kind)
        run_root = storage.run_dir(project["project_id"], run_id, DATA_ROOT)
        run_root.mkdir(parents=True, exist_ok=True)
        log_path = run_root / "run.log"
        payload = {
            "project_id": project["project_id"],
            "run_id": run_id,
            "kind": kind,
            "status": "queued",
            "stage": "queued",
            "started_at": storage.utc_now(),
            "finished_at": None,
            "summary": "",
            "log_path": str(log_path),
            "pid": None,
        }
        storage.save_run(payload, DATA_ROOT)
        process = subprocess.Popen(
            [
                str(storage.repo_python_executable(sys.executable)),
                "-m",
                "gui_app.job_runner",
                "--data-root",
                str(DATA_ROOT),
                "--project-id",
                project["project_id"],
                "--run-id",
                run_id,
                "--kind",
                kind,
            ],
            cwd=str(storage.REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        payload["pid"] = process.pid
        payload["status"] = "running"
        payload["stage"] = "starting"
        storage.save_run(payload, DATA_ROOT)

        project["latest_run_id"] = run_id
        project["last_status"] = "running"
        storage.save_project(project, DATA_ROOT)
        return run_id

    def workspace_outputs(self, project: dict[str, Any]) -> list[tuple[str, Path]]:
        workspace = Path(project["workspace_path"]).expanduser()
        candidates = [
            ("Final PDF", workspace / "final" / "paper.pdf"),
            ("Final TeX", workspace / "final" / "paper.tex"),
            ("Draft TeX", workspace / "drafts" / "paper.tex"),
            ("Intro + Related Work", workspace / "drafts" / "intro_relwork.tex"),
            ("Outline JSON", workspace / "outline.json"),
            ("Bibliography", workspace / "refs.bib"),
            ("Metrics JSON", workspace / "metrics.json"),
        ]
        handoff_dir = workspace / "chatgpt_handoff"
        if handoff_dir.exists():
            candidates.extend([
                ("ChatGPT policy README", handoff_dir / "README.md"),
                ("Deep Research prompt", handoff_dir / "02_deep_research_literature.md"),
                ("Section writing prompt", handoff_dir / "04_section_writing.md"),
            ])
        return [(label, path) for label, path in candidates if path.exists()]

    def nav(self, project: dict[str, Any], active: str) -> str:
        pills = []
        for step in STEPS:
            classes = "tab active" if step == active else "tab"
            pills.append(
                f'<a class="{classes}" href="/projects/{project["project_id"]}?step={step}">{html.escape(step.title())}</a>'
            )
        return f'<nav class="tabs">{"".join(pills)}</nav>'

    def render_dashboard(self) -> None:
        cards = []
        for project in storage.list_projects(DATA_ROOT):
            project = storage.reconcile_project_runs(project, DATA_ROOT)
            latest = project.get("latest_run")
            latest_label = latest.get("status", project.get("last_status", "draft")) if latest else project.get("last_status", "draft")
            cards.append(f"""
              <article class="card">
                <div class="status {html.escape(latest_label)}">{html.escape(latest_label.title())}</div>
                <h2>{html.escape(project.get("title", "Untitled Paper"))}</h2>
                <p class="muted">{html.escape(project.get("description", "No description yet."))}</p>
                <div class="meta-list">
                  <div><strong>Venue:</strong> {html.escape(project.get("venue", "") or "Not set")}</div>
                  <div><strong>Workspace:</strong> <span class="mono">{html.escape(project.get("workspace_path", ""))}</span></div>
                  <div><strong>Updated:</strong> {html.escape(format_timestamp(project.get("updated_at")))}</div>
                </div>
                <div class="actions">
                  <a class="button" href="/projects/{project["project_id"]}">Open project</a>
                </div>
              </article>
            """)
        if not cards:
            cards.append("""
              <article class="card">
                <h2>No saved projects yet</h2>
                <p class="muted">Create a paper project and the GUI will keep its workspace, uploads, and run history under <code>~/.paperorchestra/gui</code>.</p>
              </article>
            """)
        self.send_html("PaperOrchestra GUI", f"""
        <section class="hero">
          <h1>PaperOrchestra Legacy Atlas-Handoff GUI</h1>
          <p>This legacy browser app is retained only for compatibility. The supported UI is the FastAPI control room in <code>gui_app.web</code>, launched via <code>scripts/launch_gui.py</code>. This surface can still prepare Atlas handoff bundles, but it is not the supported product path.</p>
          <div class="actions">
            <a class="button" href="/projects/new">Create new project</a>
          </div>
        </section>
        <section class="grid">
          {''.join(cards)}
        </section>
        """)

    def render_new_project(self) -> None:
        self.send_html("New Paper Project", """
        <section class="hero">
          <h1>Create a new paper project</h1>
          <p>Start with a working title, venue, and optional description. The GUI will create a restart-safe project entry and assign a default workspace under <code>~/.paperorchestra/gui/workspaces/</code> unless you choose a custom path.</p>
        </section>
        <section class="card">
          <form method="post" action="/projects/new">
            <label>Working title
              <input type="text" name="title" placeholder="Adaptive Top-K Attention for Long-Context Transformers" required>
            </label>
            <label>Target venue
              <input type="text" name="venue" placeholder="ICLR 2027">
            </label>
            <label>Project description
              <textarea name="description" placeholder="A short plain-language summary of the paper's goal, audience, and stage of readiness."></textarea>
            </label>
            <label>Custom workspace path (optional)
              <input type="text" name="workspace_path" placeholder="Leave blank to use ~/.paperorchestra/gui/workspaces/...">
            </label>
            <div class="actions">
              <button type="submit">Create project</button>
              <a class="button secondary" href="/">Cancel</a>
            </div>
          </form>
        </section>
        """)

    def render_project(self, project: dict[str, Any], step: str) -> None:
        project = storage.reconcile_project_runs(project, DATA_ROOT)
        latest_run = project.get("latest_run")
        validation = project.get("latest_validation") or {}
        workspace = Path(project["workspace_path"]).expanduser()

        sidebar = f"""
        <aside class="card">
          <h3>Project snapshot</h3>
          <div class="meta-list">
            <div><strong>Status:</strong> <span class="status {html.escape(project.get("last_status", "draft"))}">{html.escape(project.get("last_status", "draft").title())}</span></div>
            <div><strong>Venue:</strong> {html.escape(project.get("venue", "") or "Not set")}</div>
            <div><strong>Workspace:</strong> <span class="mono">{html.escape(str(workspace))}</span></div>
            <div><strong>Validation:</strong> {html.escape(validation.get("summary", "Not run yet"))}</div>
            <div><strong>Latest run:</strong> {html.escape((latest_run or {}).get("summary", "No jobs yet"))}</div>
          </div>
        </aside>
        """

        if step == "setup":
            content = self.setup_form(project)
        elif step == "idea":
            content = self.idea_form(project)
        elif step == "experimental":
            content = self.experimental_form(project)
        elif step == "materials":
            content = self.materials_form(project)
        elif step == "review":
            content = self.review_panel(project)
        elif step == "run":
            content = self.run_panel(project)
        else:
            content = self.outputs_panel(project)

        self.send_html(project.get("title", "Paper project"), f"""
        <section class="hero">
          <h1>{html.escape(project.get("title", "Untitled Paper"))}</h1>
          <p>{html.escape(project.get("description", "Use the steps below to gather the four PaperOrchestra inputs, validate them, and launch the pipeline."))}</p>
        </section>
        {self.nav(project, step)}
        <section class="split">
          <div>{content}</div>
          {sidebar}
        </section>
        """)

    def setup_form(self, project: dict[str, Any]) -> str:
        setup = project.get("setup", {})
        return f"""
        <section class="card">
          <h2>1. Project setup</h2>
          <p class="hint">Enter the paper title, target venue, and a short summary. This screen controls the dashboard metadata and the workspace location the pipeline will use.</p>
          <form method="post" action="/projects/{project["project_id"]}/save/setup">
            <label>Working title
              <input type="text" name="title" value="{html.escape(setup.get("title", ""))}" required>
            </label>
            <label>Target venue
              <input type="text" name="venue" value="{html.escape(setup.get("venue", ""))}" placeholder="ICLR 2027">
            </label>
            <label>Project description
              <textarea name="description" placeholder="Summarize what this paper is about and what is already available.">{html.escape(setup.get("description", ""))}</textarea>
            </label>
            <label>Workspace path
              <input type="text" name="workspace_path" value="{html.escape(project.get("workspace_path", ""))}">
            </label>
            <div class="actions">
              <button type="submit">Save project setup</button>
            </div>
          </form>
        </section>
        """

    def idea_form(self, project: dict[str, Any]) -> str:
        idea = project.get("idea", {})
        return f"""
        <section class="card">
          <h2>2. Research idea</h2>
          <p class="hint">Describe the paper the way a strong <code>idea.md</code> should read: what problem matters, what you believe, how you plan to approach it, and what the contribution is. You can paste structured text here or upload an existing <code>idea.md</code>.</p>
          <form method="post" action="/projects/{project["project_id"]}/save/idea" enctype="multipart/form-data">
            <label>Problem statement
              <textarea name="problem_statement" placeholder="What limitation or open problem is this work addressing?">{html.escape(idea.get("problem_statement", ""))}</textarea>
            </label>
            <label>Core hypothesis
              <textarea name="core_hypothesis" placeholder="What do you believe will happen, and why?">{html.escape(idea.get("core_hypothesis", ""))}</textarea>
            </label>
            <label>High-level technical approach
              <textarea name="methodology" placeholder="Describe the proposed method, system, or experiment design.">{html.escape(idea.get("methodology", ""))}</textarea>
            </label>
            <label>Expected contribution
              <textarea name="expected_contribution" placeholder="What should reviewers remember as the paper's main contributions?">{html.escape(idea.get("expected_contribution", ""))}</textarea>
            </label>
            <label>Additional notes (optional)
              <textarea name="notes" placeholder="Anything else the outline or writing stages should know.">{html.escape(idea.get("notes", ""))}</textarea>
            </label>
            <label>Upload existing idea document (optional)
              <input type="file" name="idea_upload" accept=".md,.txt">
            </label>
            <div class="actions">
              <button type="submit">Save idea</button>
            </div>
          </form>
        </section>
        """

    def experimental_form(self, project: dict[str, Any]) -> str:
        experimental = project.get("experimental", {})
        return f"""
        <section class="card">
          <h2>3. Experimental evidence</h2>
          <p class="hint">Paste or upload the experimental log that will become <code>experimental_log.md</code>. Include setup, baselines, raw metrics, ablations, and qualitative observations. The validator expects headings like <code>## 1. Experimental Setup</code> and <code>## 2. Raw Numeric Data</code>.</p>
          <form method="post" action="/projects/{project["project_id"]}/save/experimental" enctype="multipart/form-data">
            <label>Experimental log
              <textarea name="log_text" placeholder="Paste the full experimental log in markdown form.">{html.escape(experimental.get("log_text", ""))}</textarea>
            </label>
            <label>Upload experimental log (optional)
              <input type="file" name="experimental_upload" accept=".md,.txt">
            </label>
            <div class="actions">
              <button type="submit">Save experimental log</button>
            </div>
          </form>
        </section>
        """

    def materials_form(self, project: dict[str, Any]) -> str:
        uploads = project.get("uploads", {})
        template_value = uploads.get("template_tex", "")
        figure_items = "".join(
            f'<div class="file-item">{html.escape(Path(path).name)}</div>'
            for path in uploads.get("figures", [])
        ) or '<div class="file-item muted">No optional figure uploads yet.</div>'
        guidelines = project.get("guidelines", {})
        return f"""
        <section class="card">
          <h2>4. Template, guidelines, and supporting material</h2>
          <p class="hint">Upload the conference <code>template.tex</code>, then paste or upload the venue guidelines. Optional figure uploads are copied into <code>workspace/inputs/figures/</code>.</p>
          <form method="post" action="/projects/{project["project_id"]}/save/materials" enctype="multipart/form-data">
            <label>Upload template.tex
              <input type="file" name="template_upload" accept=".tex">
            </label>
            <div class="mono">{html.escape(Path(template_value).name if template_value else "No template uploaded yet")}</div>
            <label>Conference guidelines text
              <textarea name="guidelines_text" placeholder="Paste page limits, required sections, deadlines, and formatting rules.">{html.escape(guidelines.get("guidelines_text", ""))}</textarea>
            </label>
            <label>Upload conference guidelines (optional)
              <input type="file" name="guidelines_upload" accept=".md,.txt,.pdf">
            </label>
            <label>Optional source figures
              <input type="file" name="figure_uploads" accept=".png,.jpg,.jpeg,.pdf" multiple>
            </label>
            <div class="file-list">{figure_items}</div>
            <div class="actions">
              <button type="submit">Save materials</button>
            </div>
          </form>
        </section>
        """

    def review_panel(self, project: dict[str, Any]) -> str:
        workspace = Path(project["workspace_path"]).expanduser()
        validation = project.get("latest_validation") or {}
        return f"""
        <section class="card">
          <h2>5. Review and validate</h2>
          <p class="hint">This screen shows the canonical workspace path and lets you run the deterministic checks before preparing the legacy Atlas handoff bundle.</p>
          <div class="meta-list">
            <div><strong>Workspace:</strong> <span class="mono">{html.escape(str(workspace))}</span></div>
            <div><strong>idea.md:</strong> <span class="mono">{html.escape(str(workspace / "inputs" / "idea.md"))}</span></div>
            <div><strong>experimental_log.md:</strong> <span class="mono">{html.escape(str(workspace / "inputs" / "experimental_log.md"))}</span></div>
            <div><strong>template.tex:</strong> <span class="mono">{html.escape(str(workspace / "inputs" / "template.tex"))}</span></div>
            <div><strong>conference_guidelines.md:</strong> <span class="mono">{html.escape(str(workspace / "inputs" / "conference_guidelines.md"))}</span></div>
          </div>
          <p class="hint">{html.escape(validation.get("summary", "Validation has not been run yet."))}</p>
          <form method="post" action="/projects/{project["project_id"]}/validate">
            <div class="actions">
              <button type="submit">Run validation + smoke extraction</button>
            </div>
          </form>
        </section>
        """

    def run_panel(self, project: dict[str, Any]) -> str:
        latest = project.get("latest_run")
        log_preview = ""
        if latest and latest.get("log_path") and Path(latest["log_path"]).exists():
            log_preview = Path(latest["log_path"]).read_text(encoding="utf-8", errors="replace")[-12000:]
        status = (latest or {}).get("status", "idle")
        chatgpt_policy = project.get("chatgpt_policy", {})
        handoff_dir = chatgpt_policy.get("handoff_dir", str(Path(project["workspace_path"]).expanduser() / "chatgpt_handoff"))
        atlas_result = project.get("latest_atlas_result") or {}
        screenshot_items = "".join(
            f'<div class="file-item"><a href="/projects/{project["project_id"]}/file?path={urllib.parse.quote(str(Path(path)))}" target="_blank">{html.escape(Path(path).name)}</a></div>'
            for path in atlas_result.get("screenshot_paths", [])
            if Path(path).exists()
        ) or '<div class="file-item muted">No Atlas screenshots captured yet.</div>'
        atlas_result_block = f"""
          <div class="card" style="margin-top:18px;">
            <h3>Latest Atlas literature automation</h3>
            <div class="meta-list">
              <div><strong>Mode used:</strong> {html.escape(str(atlas_result.get("mode_used", "Not run yet")))}</div>
              <div><strong>Verified:</strong> {html.escape("Yes" if atlas_result.get("deep_research_enabled") else "No")}</div>
              <div><strong>Verification method:</strong> {html.escape(str(atlas_result.get("verification_method", "n/a")))}</div>
              <div><strong>Submitted:</strong> {html.escape("Yes" if atlas_result.get("submitted") else "No")}</div>
              <div><strong>Fallback reason:</strong> {html.escape(str(atlas_result.get("fallback_reason", "") or "None"))}</div>
              <div><strong>Result record:</strong> <span class="mono">{html.escape(str(atlas_result.get("result_path", "n/a")))}</span></div>
            </div>
            <div class="file-list" style="margin-top:12px;">{screenshot_items}</div>
          </div>
        """ if atlas_result else ""
        return f"""
        <section class="card">
          <h2>6. Legacy Atlas-Handoff Workflow</h2>
          <p class="hint">This legacy surface is kept only for compatibility and debugging. The supported UI is the FastAPI control room in <code>gui_app.web</code>, where Codex remains the primary orchestrator and Atlas is a secondary adapter-backed control surface.</p>
          <div class="meta-list">
            <div><strong>Validation state:</strong> <span class="status {html.escape(status)}">{html.escape(status.title())}</span></div>
            <div><strong>Latest validation stage:</strong> {html.escape((latest or {}).get("stage", "Not started"))}</div>
            <div><strong>Summary:</strong> {html.escape((latest or {}).get("summary", "No validation run yet."))}</div>
            <div><strong>Execution policy:</strong> ChatGPT Pro required, extended thinking for outline/writing/refinement, Deep Research required for literature search.</div>
            <div><strong>Handoff bundle:</strong> <span class="mono">{html.escape(handoff_dir)}</span></div>
          </div>
          <div class="actions">
            <form method="post" action="/projects/{project["project_id"]}/prepare_handoff"><button type="submit">Prepare Atlas handoff bundle</button></form>
            <form method="post" action="/projects/{project["project_id"]}/atlas/run_research"><button type="submit">Run literature search in Atlas</button></form>
            <form method="post" action="/projects/{project["project_id"]}/atlas/open_home"><button class="secondary" type="submit">Open Atlas on ChatGPT</button></form>
            <form method="post" action="/projects/{project["project_id"]}/atlas/attempt_deep_research"><button class="secondary" type="submit">Attempt Deep Research enable</button></form>
            <form method="post" action="/projects/{project["project_id"]}/atlas/open_outline"><button class="secondary" type="submit">Open outline prompt in Atlas</button></form>
            <form method="post" action="/projects/{project["project_id"]}/atlas/open_research"><button class="secondary" type="submit">Open Deep Research prompt in Atlas</button></form>
            <form method="post" action="/projects/{project["project_id"]}/atlas/open_writing"><button class="secondary" type="submit">Open writing prompt in Atlas</button></form>
            <form method="post" action="/projects/{project["project_id"]}/atlas/open_handoff"><button class="secondary" type="submit">Open handoff folder</button></form>
          </div>
          <div class="actions" style="margin-top:14px;">
            <form method="post" action="/projects/{project["project_id"]}/atlas/copy_outline"><button class="secondary" type="submit">Copy outline prompt</button></form>
            <form method="post" action="/projects/{project["project_id"]}/atlas/copy_research"><button class="secondary" type="submit">Copy Deep Research prompt</button></form>
            <form method="post" action="/projects/{project["project_id"]}/atlas/copy_writing"><button class="secondary" type="submit">Copy writing prompt</button></form>
            <form method="post" action="/projects/{project["project_id"]}/atlas/stage_outline"><button class="secondary" type="submit">Stage outline prompt in Atlas</button></form>
            <form method="post" action="/projects/{project["project_id"]}/atlas/stage_research"><button class="secondary" type="submit">Stage Deep Research prompt in Atlas</button></form>
            <form method="post" action="/projects/{project["project_id"]}/atlas/stage_writing"><button class="secondary" type="submit">Stage writing prompt in Atlas</button></form>
          </div>
          <div class="card" style="margin-top:18px;">
            <h3>Recent validation log tail</h3>
            <pre class="mono log">{html.escape(log_preview or "No validation log yet.")}</pre>
          </div>
          {atlas_result_block}
        </section>
        """

    def outputs_panel(self, project: dict[str, Any]) -> str:
        files = "".join(
            f'<div class="file-item"><strong>{html.escape(label)}:</strong> <a href="/projects/{project["project_id"]}/file?path={urllib.parse.quote(str(path))}" target="_blank">{html.escape(str(path))}</a></div>'
            for label, path in self.workspace_outputs(project)
        ) or '<div class="file-item muted">No output artifacts found yet.</div>'
        latest = project.get("latest_run")
        final_message = ""
        if latest and latest.get("final_message_path"):
            message_path = Path(latest["final_message_path"])
            if message_path.exists():
                final_message = message_path.read_text(encoding="utf-8", errors="replace")
        return f"""
        <section class="card">
          <h2>7. Outputs and artifacts</h2>
          <p class="hint">Open generated files directly from the real workspace. Legacy Atlas handoff prompt files are still listed here for compatibility, but they are not part of the supported browser workflow.</p>
          <div class="file-list">{files}</div>
          <div class="card" style="margin-top:18px;">
            <h3>Latest Codex completion message</h3>
            <pre class="mono log">{html.escape(final_message or "No saved completion message yet.")}</pre>
          </div>
        </section>
        """

    def read_upload_text(self, field: dict[str, Any]) -> str:
        content = field.get("content", b"")
        return content.decode("utf-8", errors="replace")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if path == "/":
            self.render_dashboard()
            return
        if path == "/projects/new":
            self.render_new_project()
            return
        if path.startswith("/projects/") and path.endswith("/file"):
            project_id = path.split("/")[2]
            project = self.project_or_404(project_id)
            if not project:
                return
            target = Path((query.get("path") or [""])[0]).expanduser()
            workspace = Path(project["workspace_path"]).expanduser().resolve()
            try:
                target_resolved = target.resolve()
            except FileNotFoundError:
                self.render_error("Requested file does not exist.", status=404)
                return
            allowed_roots = [workspace.resolve(), storage.project_dir(project_id, DATA_ROOT).resolve()]
            if not any(str(target_resolved).startswith(str(root)) for root in allowed_roots):
                self.render_error("Refusing to serve files outside the project workspace.", status=403)
                return
            if not target_resolved.exists():
                self.render_error("Requested file does not exist.", status=404)
                return
            content_type = mimetypes.guess_type(str(target_resolved))[0] or "application/octet-stream"
            data = target_resolved.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path.startswith("/projects/") and "/runs/" in path and path.endswith("/log"):
            parts = path.strip("/").split("/")
            project_id, run_id = parts[1], parts[3]
            project = self.project_or_404(project_id)
            if not project:
                return
            run_payload = storage.load_run(project_id, run_id, DATA_ROOT)
            if not run_payload:
                self.render_error("Run log not found.", status=404)
                return
            log_path = Path(run_payload["log_path"])
            data = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            encoded = data.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return
        if path.startswith("/projects/"):
            project_id = path.split("/")[2]
            project = self.project_or_404(project_id)
            if not project:
                return
            step = (query.get("step") or ["setup"])[0]
            if step not in STEPS:
                step = "setup"
            self.render_project(project, step)
            return
        self.render_error("Page not found.", status=404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        form = self.parse_body()

        if path == "/projects/new":
            project = storage.create_project(
                title=str(form.get("title", "")),
                venue=str(form.get("venue", "")),
                description=str(form.get("description", "")),
                workspace_path=str(form.get("workspace_path", "")).strip() or None,
                data_root=DATA_ROOT,
            )
            storage.sync_workspace(project, DATA_ROOT)
            self.redirect(f"/projects/{project['project_id']}?step=setup")
            return

        if not path.startswith("/projects/"):
            self.render_error("Unknown action.", status=404)
            return

        project_id = path.split("/")[2]
        project = storage.load_project(project_id, DATA_ROOT)
        if not project:
            self.render_error("Project not found.", status=404)
            return

        if path.endswith("/save/setup"):
            project["setup"] = {
                "title": str(form.get("title", "")),
                "venue": str(form.get("venue", "")),
                "description": str(form.get("description", "")),
            }
            project["title"] = project["setup"]["title"] or project["title"]
            project["venue"] = project["setup"]["venue"]
            project["description"] = project["setup"]["description"]
            project["workspace_path"] = str(form.get("workspace_path", project["workspace_path"])).strip() or project["workspace_path"]
            storage.sync_workspace(project, DATA_ROOT)
            self.redirect(f"/projects/{project_id}?step=idea")
            return

        if path.endswith("/save/idea"):
            idea = project.get("idea", {})
            idea.update({
                "problem_statement": str(form.get("problem_statement", "")),
                "core_hypothesis": str(form.get("core_hypothesis", "")),
                "methodology": str(form.get("methodology", "")),
                "expected_contribution": str(form.get("expected_contribution", "")),
                "notes": str(form.get("notes", "")),
            })
            upload = form.get("idea_upload")
            if isinstance(upload, dict) and upload.get("content"):
                text = self.read_upload_text(upload)
                sections = parse_markdown_sections(text)
                idea["problem_statement"] = sections.get("problem statement", idea["problem_statement"])
                idea["core_hypothesis"] = sections.get("core hypothesis", idea["core_hypothesis"])
                idea["methodology"] = sections.get("proposed methodology (high-level technical approach)", idea["methodology"])
                idea["expected_contribution"] = sections.get("expected contribution", idea["expected_contribution"])
                idea["notes"] = text
            project["idea"] = idea
            storage.sync_workspace(project, DATA_ROOT)
            self.redirect(f"/projects/{project_id}?step=experimental")
            return

        if path.endswith("/save/experimental"):
            experimental = project.get("experimental", {})
            experimental["log_text"] = str(form.get("log_text", ""))
            upload = form.get("experimental_upload")
            if isinstance(upload, dict) and upload.get("content"):
                experimental["log_text"] = self.read_upload_text(upload)
                experimental["source_filename"] = upload.get("filename", "")
            project["experimental"] = experimental
            storage.sync_workspace(project, DATA_ROOT)
            self.redirect(f"/projects/{project_id}?step=materials")
            return

        if path.endswith("/save/materials"):
            uploads = project.get("uploads", {})
            template = form.get("template_upload")
            if isinstance(template, dict) and template.get("content"):
                uploads["template_tex"] = storage.store_uploaded_file(
                    project_id, "template", template.get("filename", "template.tex"), template["content"], DATA_ROOT
                )

            guidelines = project.get("guidelines", {})
            guidelines["guidelines_text"] = str(form.get("guidelines_text", ""))
            guidelines_upload = form.get("guidelines_upload")
            if isinstance(guidelines_upload, dict) and guidelines_upload.get("content"):
                stored_path = storage.store_uploaded_file(
                    project_id, "guidelines", guidelines_upload.get("filename", "conference_guidelines.txt"), guidelines_upload["content"], DATA_ROOT
                )
                guidelines["source_filename"] = guidelines_upload.get("filename", "")
                if guidelines_upload.get("filename", "").lower().endswith(".pdf"):
                    guidelines["guidelines_text"] = (
                        guidelines["guidelines_text"]
                        or f"[PDF uploaded at {stored_path}. Paste a text summary here for the validator and pipeline.]"
                    )
                else:
                    guidelines["guidelines_text"] = self.read_upload_text(guidelines_upload)

            figure_uploads = form.get("figure_uploads")
            if figure_uploads:
                uploads.setdefault("figures", [])
                items = figure_uploads if isinstance(figure_uploads, list) else [figure_uploads]
                uploads["figures"] = []
                for item in items:
                    if isinstance(item, dict) and item.get("content"):
                        uploads["figures"].append(
                            storage.store_uploaded_file(
                                project_id,
                                "figures",
                                item.get("filename", "figure.bin"),
                                item["content"],
                                DATA_ROOT,
                            )
                        )
            project["uploads"] = uploads
            project["guidelines"] = guidelines
            storage.sync_workspace(project, DATA_ROOT)
            self.redirect(f"/projects/{project_id}?step=review")
            return

        if path.endswith("/validate"):
            storage.sync_workspace(project, DATA_ROOT)
            self.start_job(project, "validate")
            self.redirect(f"/projects/{project_id}?step=run")
            return

        if path.endswith("/prepare_handoff"):
            handoff.ensure_handoff_bundle(project, DATA_ROOT)
            self.redirect(f"/projects/{project_id}?step=run")
            return

        if "/atlas/" in path:
            bundle = handoff.ensure_handoff_bundle(project, DATA_ROOT)
            if path.endswith("/atlas/open_home"):
                atlas_controller.open_chatgpt_home()
            elif path.endswith("/atlas/run_research"):
                result = atlas_controller.run_literature_prompt_in_atlas(bundle["literature_prompt"])
                storage.record_atlas_literature_run(project, result, DATA_ROOT)
            elif path.endswith("/atlas/attempt_deep_research"):
                atlas_controller.attempt_enable_deep_research()
            elif path.endswith("/atlas/open_outline"):
                atlas_controller.open_file_in_atlas(bundle["outline_prompt"])
            elif path.endswith("/atlas/open_research"):
                atlas_controller.open_file_in_atlas(bundle["literature_prompt"])
            elif path.endswith("/atlas/open_writing"):
                atlas_controller.open_file_in_atlas(bundle["writing_prompt"])
            elif path.endswith("/atlas/open_handoff"):
                subprocess.Popen(["open", bundle["handoff_dir"]])
            elif path.endswith("/atlas/copy_outline"):
                atlas_controller.copy_file_to_clipboard(bundle["outline_prompt"])
            elif path.endswith("/atlas/copy_research"):
                atlas_controller.copy_file_to_clipboard(bundle["literature_prompt"])
            elif path.endswith("/atlas/copy_writing"):
                atlas_controller.copy_file_to_clipboard(bundle["writing_prompt"])
            elif path.endswith("/atlas/stage_outline"):
                atlas_controller.paste_file_into_chatgpt(bundle["outline_prompt"])
            elif path.endswith("/atlas/stage_research"):
                atlas_controller.paste_file_into_chatgpt(bundle["literature_prompt"])
                atlas_controller.show_notification(
                    "Atlas Deep Research",
                    "The literature prompt is staged in ChatGPT Atlas. Switch the mode to Deep Research before submitting it.",
                )
            elif path.endswith("/atlas/stage_writing"):
                atlas_controller.paste_file_into_chatgpt(bundle["writing_prompt"])
            else:
                self.render_error("Unknown Atlas action.", status=404)
                return
            self.redirect(f"/projects/{project_id}?step=outputs")
            return

        self.render_error("Unknown action.", status=404)


def serve(host: str, port: int, open_browser: bool) -> None:
    storage.get_paths(DATA_ROOT)
    url = f"http://{host}:{port}"
    if open_browser:
        webbrowser.open(url)
    httpd = ThreadingHTTPServer((host, port), GuiHandler)
    print(f"PaperOrchestra GUI listening on {url}")
    print(f"Data root: {DATA_ROOT}")
    httpd.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    serve(args.host, args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
