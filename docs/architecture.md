# Architecture

A deep-dive on how the skill pack composes to implement the
PaperOrchestra pipeline (arXiv:2604.05018) without any embedded API
clients.

## The core idea

Skills are **markdown instruction documents** plus **deterministic local
helpers**. The host coding agent (Claude Code, Cursor, Antigravity, Cline,
Aider, OpenCode, etc.) reads the instructions and uses its own native
tools to execute them.

```
┌────────────────────────────────────────────────────────────┐
│                    HOST CODING AGENT                        │
│  (Claude Code / Cursor / Antigravity / Cline / Aider ...)   │
│                                                              │
│  Tools provided by the host:                                 │
│    • LLM (the agent's own model)                             │
│    • Web search                                              │
│    • URL fetch                                               │
│    • File read/write                                         │
│    • Bash / shell                                            │
│    • Vision input (optional)                                 │
└──────────────────────┬─────────────────────────────────────┘
                       │   reads SKILL.md, follows instructions
                       │   calls deterministic scripts
                       ▼
┌────────────────────────────────────────────────────────────┐
│                    SKILL PACK (this repo)                   │
│                                                              │
│  skills/paper-orchestra/        — orchestrator               │
│  skills/outline-agent/          — Step 1                     │
│  skills/plotting-agent/         — Step 2 (parallel w/ 3)     │
│  skills/literature-review-agent/— Step 3 (parallel w/ 2)     │
│  skills/section-writing-agent/  — Step 4                     │
│  skills/content-refinement-agent/— Step 5                    │
│  skills/paper-writing-bench/    — §3 evaluation harness      │
│  skills/paper-autoraters/       — App. F.3 autoraters        │
└────────────────────────────────────────────────────────────┘
```

## Why no API keys

The PaperOrchestra paper uses Gemini-3.1-Pro and Semantic Scholar via
Google Cloud Vertex AI. A faithful re-implementation could ship an
embedded LLM client and a Semantic Scholar client. We deliberately don't,
for three reasons:

1. **Pluggability.** A coding agent already has an LLM (its own). Forcing
   the user to configure another provider is friction. Letting the agent
   reuse its existing capabilities means the same skill pack works under
   any host.
2. **Security.** No API keys means no secret management, no `.env` files
   to leak, no rate-limit bookkeeping.
3. **Honesty.** The deterministic parts (Levenshtein matching, dedup,
   citation gates, BibTeX formatting, JSON validation) are trivially
   replicated, never wrong, and don't depend on a model. The
   non-deterministic parts (writing, search, judgment) belong in the host
   LLM where the user already trusts the model. Pretending we can wrap
   the LLM and "make it deterministic" would be misleading.

## Anatomy of a skill

Every skill follows the same structure:

```
skills/<name>/
├── SKILL.md                    # frontmatter + instructions
├── references/
│   ├── prompt.md               # verbatim prompt from arXiv:2604.05018 App. F
│   ├── *.md                    # supplementary references (schemas, rules)
│   └── *.json                  # machine-readable schemas
└── scripts/
    └── *.py                    # deterministic helpers, all with argparse CLIs
```

`SKILL.md` always begins with YAML frontmatter:

```yaml
---
name: outline-agent
description: Step 1 of the PaperOrchestra pipeline... TRIGGER when ...
---
```

The `description` includes a `TRIGGER` clause so the host agent's skill
loader can detect when to invoke this skill from natural-language user
requests.

## Deterministic vs delegated

The split is strict and explicit. Anything that can be done **without** an
LLM goes into a script. Anything that needs reasoning goes into a SKILL.md
instruction the host agent follows.

| Concern | Delegated to host LLM | Deterministic script |
|---|---|---|
| Synthesizing inputs into an outline | ✓ outline-agent SKILL.md | — |
| Outline schema validation | — | `validate_outline.py` |
| Web search for candidate papers | ✓ literature-review-agent SKILL.md | — |
| Fuzzy title match (Levenshtein) | — | `levenshtein_match.py` |
| Date cutoff comparison | — | `check_cutoff.py` |
| Dedup by S2 paperId | — | `dedupe_by_id.py` |
| BibTeX entry formatting | — | `bibtex_format.py` |
| ≥90% citation coverage check | — | `citation_coverage.py` |
| Drafting Intro + Related Work | ✓ literature-review-agent SKILL.md | — |
| Generating matplotlib code | ✓ plotting-agent SKILL.md | — |
| Rendering a JSON plot spec | — | `render_matplotlib.py` |
| VLM critique of a rendered figure | ✓ plotting-agent SKILL.md (host vision) | — |
| Single-call multimodal section writing | ✓ section-writing-agent SKILL.md | — |
| Extracting metrics from md tables | — | `extract_metrics.py` |
| LaTeX brace/env sanity | — | `latex_sanity.py` |
| Orphan-cite gate | — | `orphan_cite_gate.py` |
| Anti-leakage grep | — | `anti_leakage_check.py` |
| Simulated peer review | ✓ content-refinement-agent SKILL.md | — |
| Accept/revert decision | — | `score_delta.py` |
| Worklog append | — | `apply_worklog.py` |
| Iteration snapshot | — | `snapshot.py` |
| Citation F1 computation | — | `compute_f1.py` |
| LitReview Quality scoring | ✓ paper-autoraters SKILL.md | — |

## Pipeline data flow

```
inputs/                         user-provided
  ├── idea.md                          ──┐
  ├── experimental_log.md              ──┤
  ├── template.tex                     ──┤
  └── conference_guidelines.md         ──┘
                                          │
                                          ▼
                                  Step 1: Outline
                                          │
                                          ▼
                                  outline.json
                                  ┌───────┴───────┐
                          ┌───────┘               └───────┐
                          ▼                                ▼
               Step 2: Plotting                Step 3: Lit Review
            (parallel branch A)                (parallel branch B)
                          │                                │
                          ▼                                ▼
              figures/*.png                    refs.bib + citation_pool.json
              figures/captions.json            drafts/intro_relwork.tex
                          │                                │
                          └────────────┬───────────────────┘
                                       ▼
                            Step 4: Section Writing
                            (one multimodal call,
                             reads all of the above)
                                       │
                                       ▼
                              drafts/paper.tex
                                       │
                                       ▼
                            Step 5: Content Refinement
                            (loop ≤3 iterations)
                            ┌──────────┼──────────┐
                            ▼          ▼          ▼
                        iter1/      iter2/     iter3/
                            └──────────┼──────────┘
                                       ▼
                            promote best snapshot
                                       │
                                       ▼
                          final/paper.tex + final/paper.pdf
```

## Parallelism

Steps 2 and 3 are independent. They share no input (Step 2 uses
`plotting_plan` from `outline.json`, Step 3 uses `intro_related_work_plan`)
and no output (Step 2 writes to `figures/`, Step 3 writes to `refs.bib`
and `drafts/intro_relwork.tex`). Run them in parallel when the host
supports it.

Within Step 2, individual figure-rendering jobs are independent and can
also be parallelized per `figure_id`.

Within Step 3, **discovery** is parallel (10 concurrent web search workers
in the paper) but **verification** is strictly sequential (1 QPS Semantic
Scholar limit).

## Refinement loop semantics

Step 5 runs a strict accept/revert loop with halt conditions encoded in
`score_delta.py`. See `skills/content-refinement-agent/references/halt-rules.md`
for the formal pseudocode. Snapshots are real (physical file copies via
`snapshot.py`), not symbolic — reverts roll back the actual `.tex` file.

## Out-of-paper improvements

This repo adds a few hardening scripts on top of the paper. Each is
clearly marked in `paper-fidelity.md`:

| Script | Purpose | Why |
|---|---|---|
| `anti_leakage_check.py` | Grep final draft for author names, emails, affiliations | The Anti-Leakage Prompt (App. D.4) is aspirational; this is enforcement |
| `orphan_cite_gate.py` | Verify every `\cite{KEY}` exists in `refs.bib` | The Section Writing prompt mandates this; this enforces it mechanically |
| `citation_coverage.py` | Verify ≥90% citation integration rule | App. D.3 mandates this; this enforces it mechanically |
| `snapshot.py` | Physical copy of paper.tex per refinement iteration | Halt rules require real rollback, not symbolic |
| `provenance.json` (orchestrator) | Hashes of inputs and final outputs | Reproducibility — out of paper |
| `levenshtein_match.py --substring-bypass` | Soft override for short candidate titles | Catches the Linformer false-negative case the paper doesn't address |

These improvements are *additions*, not deviations. Removing any of them
would still produce a faithful PaperOrchestra implementation; they make
the implementation more robust in practice.
