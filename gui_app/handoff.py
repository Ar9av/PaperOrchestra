#!/usr/bin/env python3
"""Legacy ChatGPT Pro handoff bundle generation for the local GUI.

This module exists for compatibility with ``gui_app.server``. It is not part of
the supported path, which runs through ``gui_app.web`` and
``scripts/launch_gui.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import storage


CHATGPT_APP = Path("/Applications/ChatGPT.app")
ATLAS_APP = Path("/Applications/ChatGPT Atlas.app")


def ensure_handoff_bundle(project: dict, data_root: Path | None = None) -> dict[str, str]:
    project = storage.sync_workspace(project, data_root)
    workspace = Path(project["workspace_path"]).expanduser()
    handoff_dir = workspace / "chatgpt_handoff"
    handoff_dir.mkdir(parents=True, exist_ok=True)

    policy = {
        "required_execution_host": "ChatGPT Pro desktop session",
        "required_reasoning_mode": "Extended thinking for outline, writing, and refinement",
        "required_literature_mode": "Deep Research for literature discovery and synthesis",
        "disallowed_fallback": "Do not use Codex exec as the primary research or writing host",
    }

    files = {
        "README.md": handoff_readme(project),
        "01_outline_and_plan.md": outline_prompt(project),
        "02_deep_research_literature.md": deep_research_prompt(project),
        "03_plotting_and_assets.md": plotting_prompt(project),
        "04_section_writing.md": section_writing_prompt(project),
        "05_refinement.md": refinement_prompt(project),
        "import_back_checklist.md": import_checklist(project),
    }

    for filename, content in files.items():
        (handoff_dir / filename).write_text(content, encoding="utf-8")

    (handoff_dir / "policy.json").write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")

    project["chatgpt_policy"] = {
        "status": "handoff_ready",
        "prepared_at": storage.utc_now(),
        "handoff_dir": str(handoff_dir),
        "required_host": "chatgpt_pro",
        "literature_mode": "deep_research",
        "reasoning_mode": "extended_thinking",
    }
    project["last_status"] = "handoff_ready"
    storage.save_project(project, data_root)

    return {
        "handoff_dir": str(handoff_dir),
        "outline_prompt": str(handoff_dir / "01_outline_and_plan.md"),
        "literature_prompt": str(handoff_dir / "02_deep_research_literature.md"),
        "writing_prompt": str(handoff_dir / "04_section_writing.md"),
    }


def handoff_readme(project: dict) -> str:
    workspace = Path(project["workspace_path"]).expanduser()
    return f"""# ChatGPT Pro Execution Policy

This project is configured to follow a strict execution policy:

- Use **ChatGPT Pro** as the reasoning host.
- Use **extended thinking** for outline generation, section writing, and refinement.
- Use **Deep Research** for the literature search stage.
- Do **not** treat local Codex execution as a substitute for the required ChatGPT Pro + Deep Research workflow.

## Workspace

- Workspace root: `{workspace}`
- Inputs directory: `{workspace / "inputs"}`
- Final output target: `{workspace / "final" / "paper.pdf"}`

## Stage order

1. Use `01_outline_and_plan.md` in ChatGPT with extended thinking.
2. Use `02_deep_research_literature.md` in ChatGPT Deep Research.
3. Use `03_plotting_and_assets.md` if figures need manual prompting support.
4. Use `04_section_writing.md` in ChatGPT with extended thinking.
5. Use `05_refinement.md` in ChatGPT with extended thinking.
6. Import the produced files back into the workspace using `import_back_checklist.md`.
"""


def outline_prompt(project: dict) -> str:
    workspace = Path(project["workspace_path"]).expanduser()
    return f"""# Stage 1: Outline And Plan

Use this in **ChatGPT Pro** with **extended thinking enabled**.

Objective: produce `outline.json` for the PaperOrchestra workspace below.

Workspace: `{workspace}`

Inputs to use:
- `{workspace / "inputs" / "idea.md"}`
- `{workspace / "inputs" / "experimental_log.md"}`
- `{workspace / "inputs" / "template.tex"}`
- `{workspace / "inputs" / "conference_guidelines.md"}`

Required behavior:
- Follow the PaperOrchestra outline agent contract.
- Keep the outline grounded only in the workspace inputs.
- Respect the target venue and template structure.
- Produce a plotting plan, literature review plan, and section plan.

Required output:
- Write or return a valid `outline.json` matching the PaperOrchestra schema.
"""


def deep_research_prompt(project: dict) -> str:
    workspace = Path(project["workspace_path"]).expanduser()
    return f"""# Stage 2: Literature Search With Deep Research

Use this in **ChatGPT Pro** with **Deep Research enabled**. This stage must not be run as a normal chat search.

Objective: build the literature review package for the PaperOrchestra workspace below.

Workspace: `{workspace}`

Inputs to use:
- `{workspace / "outline.json"}` if available
- `{workspace / "inputs" / "idea.md"}`
- `{workspace / "inputs" / "experimental_log.md"}`
- `{workspace / "inputs" / "conference_guidelines.md"}`

Required behavior:
- Use Deep Research to find, compare, and synthesize relevant prior work.
- Respect the venue cutoff date implied by the conference guidelines.
- Prefer primary sources and canonical papers.
- Produce grounded citations rather than speculative references.

Required outputs:
- `refs.bib`
- `drafts/intro_relwork.tex`
- Optional: a citation pool artifact or research notes you want to preserve

Important:
- This stage is governed by a strict policy requiring Deep Research.
- If Deep Research is not available in the current ChatGPT session, stop and switch to a session where it is available.
- In Atlas, switch the mode/control for this chat to **Deep Research** immediately before submitting the staged prompt.
"""


def plotting_prompt(project: dict) -> str:
    workspace = Path(project["workspace_path"]).expanduser()
    return f"""# Stage 3: Plotting And Assets

Use this in ChatGPT if you want help planning or refining figures, but keep the outputs aligned with the local PaperOrchestra workspace.

Workspace: `{workspace}`

Expected outputs:
- `figures/*.png`
- `figures/captions.json`

Ground the figures only in:
- `{workspace / "inputs" / "experimental_log.md"}`
- `{workspace / "inputs" / "idea.md"}`
- `{workspace / "outline.json"}` if available
"""


def section_writing_prompt(project: dict) -> str:
    workspace = Path(project["workspace_path"]).expanduser()
    return f"""# Stage 4: Section Writing

Use this in **ChatGPT Pro** with **extended thinking enabled**.

Objective: draft the full paper body while preserving the literature review outputs.

Workspace: `{workspace}`

Inputs:
- `{workspace / "outline.json"}`
- `{workspace / "inputs" / "idea.md"}`
- `{workspace / "inputs" / "experimental_log.md"}`
- `{workspace / "drafts" / "intro_relwork.tex"}`
- `{workspace / "refs.bib"}`
- `{workspace / "inputs" / "template.tex"}`
- `{workspace / "inputs" / "conference_guidelines.md"}`

Required outputs:
- `drafts/paper.tex`

Required behavior:
- Use extended thinking.
- Keep citations grounded in the Deep Research output.
- Preserve intro and related work content unless there is a strong grounded reason to revise them.
"""


def refinement_prompt(project: dict) -> str:
    workspace = Path(project["workspace_path"]).expanduser()
    return f"""# Stage 5: Refinement

Use this in **ChatGPT Pro** with **extended thinking enabled**.

Objective: iteratively refine the draft while keeping the work grounded in the existing workspace artifacts.

Workspace: `{workspace}`

Inputs:
- `{workspace / "drafts" / "paper.tex"}`
- `{workspace / "refs.bib"}`
- `{workspace / "inputs" / "conference_guidelines.md"}`
- Any generated figures under `{workspace / "figures"}`

Required outputs:
- improved `final/paper.tex`
- reviewer notes or revision rationale if helpful

Rules:
- Prefer clarity, alignment, and correctness over new unsupported claims.
- Do not invent new experiments or citations.
- Keep the paper anonymized and venue-compliant.
"""


def import_checklist(project: dict) -> str:
    workspace = Path(project["workspace_path"]).expanduser()
    return f"""# Import Back Checklist

After running the ChatGPT Pro stages:

1. Save `outline.json` to `{workspace / "outline.json"}`
2. Save `refs.bib` to `{workspace / "refs.bib"}`
3. Save `drafts/intro_relwork.tex` to `{workspace / "drafts" / "intro_relwork.tex"}`
4. Save `drafts/paper.tex` to `{workspace / "drafts" / "paper.tex"}`
5. Save refined `paper.tex` to `{workspace / "final" / "paper.tex"}`
6. Run local validation and LaTeX compilation from the GUI or terminal

Recommended local checks:

```bash
cd ~/paper-orchestra
python skills/section-writing-agent/scripts/orphan_cite_gate.py "{workspace / "final" / "paper.tex"}" "{workspace / "refs.bib"}"
python skills/section-writing-agent/scripts/latex_sanity.py "{workspace / "final" / "paper.tex"}"
python skills/paper-orchestra/scripts/anti_leakage_check.py "{workspace / "final" / "paper.tex"}"
cd "{workspace / "final"}" && latexmk -pdf paper.tex
```
"""
