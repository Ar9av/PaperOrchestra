---
name: paper-orchestra
description: Orchestrate the full PaperOrchestra (Song et al., 2026, arXiv:2604.05018) five-agent pipeline to turn unstructured research materials (idea, experimental log, LaTeX template, conference guidelines, optional figures) into a submission-ready LaTeX manuscript and compiled PDF. TRIGGER when the user asks to "write a paper from my experiments", "turn this idea and these results into a paper", "generate a conference submission", "run paper-orchestra on X", or otherwise wants the end-to-end paper-writing pipeline. Coordinates the outline-agent, plotting-agent, literature-review-agent, section-writing-agent, and content-refinement-agent skills.
---

# paper-orchestra (Orchestrator)

Top-level driver for the PaperOrchestra pipeline. Read this document and follow
the steps below. The detailed prompts and rules live in each sub-skill's
`SKILL.md` and `references/` directories — you (the host agent) will load them
as you go.

> Source paper: Song et al., *PaperOrchestra: A Multi-Agent Framework for
> Automated AI Research Paper Writing*, arXiv:2604.05018, 2026.
> <https://arxiv.org/pdf/2604.05018>

## What this skill produces

A complete submission package `P = (paper.tex, paper.pdf)` written into
`workspace/final/`, plus a full audit trail under `workspace/` (outline,
figures, refs, drafts, refinement worklog, provenance snapshot).

## Inputs (the (I, E, T, G, F) tuple from the paper)

The workspace MUST contain:

| File | Symbol | Required | Description |
|---|---|---|---|
| `workspace/inputs/idea.md` | `I` | yes | Idea Summary (Sparse or Dense variant — see `references/io-contract.md`) |
| `workspace/inputs/experimental_log.md` | `E` | yes | Experimental Log: setup, raw numeric data, qualitative observations |
| `workspace/inputs/template.tex` | `T` | yes | LaTeX template for the target conference (with `\section{...}` commands) |
| `workspace/inputs/conference_guidelines.md` | `G` | yes | Formatting rules, page limit, mandatory sections |
| `workspace/inputs/figures/` | `F` | no | Optional pre-existing figures. If empty, the plotting agent generates everything. |

`scripts/init_workspace.py` will scaffold this layout. `scripts/validate_inputs.py`
will check it before the pipeline runs.

## Pipeline (read `references/pipeline.md` for the full diagram)

```
Step 1: Outline           ──▶  outline.json                       (1 LLM call)
Step 2: Plotting     ─┐
                      ├──▶  figures/*.png + captions.json         (~20-30 calls)
Step 3: Lit Review   ─┘                                           (~20-30 calls)
                          intro_relwork.tex + refs.bib

Step 4: Section Writing  ──▶  drafts/paper.tex                    (1 LLM call)
Step 5: Content Refine   ──▶  final/paper.tex + final/paper.pdf   (~5-7 calls, ~3 iters)
```

Step 2 and Step 3 are independent and **MUST run in parallel** when your host
supports parallel sub-agents. If not, run Step 3 first (it has the longer wall
time due to Semantic Scholar rate limits) and Step 2 second.

## Critical pre-instruction (read once, apply always)

Before any LLM call that *writes* paper content (outline, intro/related work,
section writing, refinement), you MUST prepend the **Anti-Leakage Prompt** at
`references/anti-leakage-prompt.md` to your system prompt. This is verbatim
from Appendix D.4 of the paper and prevents pre-training-data leakage. The
paper applies it uniformly across all baselines for fair comparison; we apply
it for fidelity *and* to keep generated papers grounded in the user's inputs.

## Step-by-step execution

### 0. Scaffold, check for missing inputs, and validate

```bash
python skills/paper-orchestra/scripts/init_workspace.py --out workspace/
python skills/paper-orchestra/scripts/validate_inputs.py --workspace workspace/
```

**Before failing on missing inputs**, check whether aggregation can supply them:

| Inputs state | Action |
|---|---|
| `idea.md` and `experimental_log.md` both present and non-empty | Continue to Step 1. |
| Either is missing/empty, and the user mentioned a directory | Load and run `agent-research-aggregator` with that directory as `--search-roots`, then re-validate. |
| Either is missing/empty, no directory mentioned | Ask the user: "Your workspace is missing `idea.md` / `experimental_log.md`. Do you have a folder with research notes or agent history I can aggregate from? If so, tell me the path — or drop the files manually into `workspace/inputs/`." |

If validation still fails after aggregation (e.g. `template.tex` or `conference_guidelines.md` are missing), stop and tell the user exactly which files remain outstanding.

**Also probe the TeX installation** (once per workspace, result cached):

```bash
python skills/paper-orchestra/scripts/check_tex_packages.py \
    --out workspace/tex_profile.json
```

The Section Writing Agent reads `tex_profile.json` to decide which LaTeX
patterns to use (e.g., `Figure~\ref{}` vs `\cref{}`, whether to include
`\usepackage{microtype}`, etc.). This eliminates compile-time package
failures that previously required iterative manual edits.

### 1. Outline (Step 1 — 1 LLM call)

Load `skills/outline-agent/SKILL.md` and follow it. Output: `workspace/outline.json`.
Validate with `python skills/outline-agent/scripts/validate_outline.py workspace/outline.json`.
**Halt the pipeline if validation fails** — every downstream agent depends on the schema.

### 2 ∥ 3. Plotting and Literature Review (in parallel)

Parse `outline.json`. Extract:
- `outline.plotting_plan` → drives Step 2
- `outline.intro_related_work_plan` → drives Step 3

If your host supports parallel sub-agents (Claude Code's Agent tool with multiple
concurrent calls; Cursor's parallel agents; Antigravity's worker pool), spawn
**two concurrent sub-tasks**:

- Sub-task A: load `skills/plotting-agent/SKILL.md`, execute the plotting plan,
  produce `workspace/figures/<figure_id>.png` for every entry, plus
  `workspace/figures/captions.json`.
- Sub-task B: load `skills/literature-review-agent/SKILL.md`, execute the
  research strategy, produce `workspace/drafts/intro_relwork.tex` and
  `workspace/refs.bib`.

If your host does not support parallel sub-agents, run Sub-task B first (it has
slower wall-clock due to Semantic Scholar QPS limits) then Sub-task A. The
artifacts are independent, so order doesn't affect correctness.

### 4. Section Writing (Step 4 — ONE single multimodal LLM call)

Load `skills/section-writing-agent/SKILL.md` and follow it. This is **one
single call** in the paper (App. B: "Section Writing Agent (1 call)") — do
*not* split it per section. The agent receives:

- `outline.json`
- `idea.md`, `experimental_log.md`
- `intro_relwork.tex` (already-filled from Step 3 — preserve verbatim)
- `refs.bib` (the citation map)
- `conference_guidelines.md`
- The actual figure image files from `workspace/figures/` (multimodal input)

Output: `workspace/drafts/paper.tex` (a complete LaTeX document).

Then run the deterministic gates:

```bash
python skills/section-writing-agent/scripts/orphan_cite_gate.py workspace/drafts/paper.tex workspace/refs.bib
python skills/section-writing-agent/scripts/latex_sanity.py workspace/drafts/paper.tex
python skills/paper-orchestra/scripts/anti_leakage_check.py workspace/drafts/paper.tex
```

If any gate fails, the host agent must fix the issue (re-prompting the writing
step with the gate's error report) before proceeding.

### 5. Content Refinement (Step 5 — ~3 iterations, ~5-7 calls)

Load `skills/content-refinement-agent/SKILL.md` and follow it. The skill
implements the loop with strict halt rules from `halt-rules.md`. Maintain
`workspace/refinement/worklog.json` and snapshot each iteration into
`workspace/refinement/iter<N>/`.

Halt conditions (any one triggers the loop to stop and accept the current
best snapshot):

1. Iteration count reaches the cap (default 3, see `halt-rules.md`).
2. Overall score from the simulated reviewer **decreases** vs the previous
   iteration → revert to previous snapshot, halt.
3. Overall score **ties** but at least one sub-axis **decreases** while none
   gain compensatingly (negative net sub-axis change) → revert, halt.
4. Reviewer issues no new actionable weaknesses.

The accepted snapshot is copied to `workspace/final/paper.tex`.

### 6. Compile and finalize

```bash
cd workspace/final && latexmk -pdf paper.tex
```

Then write `workspace/provenance.json` capturing input file hashes, outline
hash, refs hash, figure hashes, and final tex/pdf hashes (helper:
`scripts/snapshot.py` in the orchestrator scripts dir if you want a one-shot;
otherwise the host agent computes hashes inline).

Report to the user: the path to `workspace/final/paper.pdf`, a brief summary of
which sections were drafted, citation count, refinement iterations completed,
and any gates that failed mid-pipeline.

## Workspace layout

See `references/io-contract.md`. Summary:

```
workspace/
├── inputs/                          # user-provided
│   ├── idea.md
│   ├── experimental_log.md
│   ├── template.tex
│   ├── conference_guidelines.md
│   └── figures/                     # optional pre-existing figures
├── outline.json                     # Step 1 output
├── figures/                         # Step 2 output
│   ├── <figure_id>.png
│   └── captions.json
├── refs.bib                         # Step 3 output
├── drafts/                          # Step 3 + Step 4 output
│   ├── intro_relwork.tex
│   └── paper.tex
├── refinement/                      # Step 5 working dir
│   ├── worklog.json
│   ├── iter1/
│   ├── iter2/
│   └── iter3/
├── final/                           # accepted snapshot + compiled PDF
│   ├── paper.tex
│   └── paper.pdf
└── provenance.json                  # input/output hashes for reproducibility
```

## Cost budget (from paper App. B)

Total: ~60–70 LLM calls per paper, ~40 minutes wall-time on the paper's setup.
Budget breakdown:

| Step | Calls |
|---|---|
| Outline | 1 |
| Plotting | ~20–30 |
| Literature Review | ~20–30 |
| Section Writing | 1 |
| Content Refinement | ~5–7 |

## Host integration

See `references/host-integration.md` for per-host invocation details (Claude
Code, Cursor, Antigravity, Cline, Aider, OpenCode).

## Resources

- `references/pipeline.md` — full step-by-step flow + parallelism rules + halt rules
- `references/io-contract.md` — workspace layout, input file schemas
- `references/anti-leakage-prompt.md` — verbatim from App. D.4, prepend to every writing call
- `references/paper-summary.md` — 1-page distillation of arXiv:2604.05018
- `references/host-integration.md` — per-host invocation guide
- `scripts/init_workspace.py` — scaffold workspace dir tree
- `scripts/validate_inputs.py` — verify (I, E, T, G) before running
- `scripts/anti_leakage_check.py` — grep draft for leaked author names/emails/affils
