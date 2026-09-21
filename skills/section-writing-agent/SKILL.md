---
name: section-writing-agent
description: Step 4 of the PaperOrchestra pipeline (arXiv:2604.05018). ONE single multimodal LLM call that drafts the remaining paper sections (Abstract, Methodology, Experiments, Conclusion), extracts numeric values from experimental_log.md into LaTeX booktabs tables, splices the generated figures from Step 2, and merges everything into the template that already contains Intro + Related Work from Step 3. TRIGGER when the orchestrator delegates Step 4 or when the user asks to "write the methodology and experiments sections" or "fill in the rest of the paper".
---

# Section Writing Agent (Step 4)

Faithful implementation of the Section Writing Agent from PaperOrchestra
(Song et al., 2026, arXiv:2604.05018, §4 Step 4, App. F.1 pp. 47–49).

**Cost: ONE LLM call** (App. B: "Section Writing Agent (1 call): A single,
comprehensive multimodal call to draft and compile the complete LaTeX
manuscript"). Do NOT split this into per-section calls — the paper
explicitly designs it as one comprehensive call so the model can maintain
global coherence across sections.

## Inputs

- `workspace/outline.json` — the master plan
- `workspace/inputs/idea.md` — technical details
- `workspace/inputs/experimental_log.md` — raw data for tables and qualitative analysis
- `workspace/drafts/intro_relwork.tex` — the template **with Intro + Related
  Work already filled in by Step 3**. This is your starting point. The
  preamble, package list, style, and the two pre-filled sections must be
  preserved verbatim.
- `workspace/citation_pool.json` — the citation map (`{key, title, abstract}`
  for each verified paper)
- `workspace/refs.bib` — the BibTeX file
- `workspace/inputs/conference_guidelines.md` — formatting rules
- `workspace/figures/` — the actual PNG files from Step 2 (used as
  multimodal vision input!)
- `workspace/figures/captions.json` — caption text per figure_id
- `workspace/tex_profile.json` — TeX package availability flags (written by
  `check_tex_packages.py` at Step 0). **Read this before generating any
  LaTeX.** It tells you which packages are installed so you select the right
  cross-reference pattern, font packages, etc. before you write — not after
  you try to compile.

## Output

- `workspace/drafts/paper.tex` — the complete LaTeX paper, with all sections
  filled. The Step 5 Refinement Agent will iterate on this file.

## How to do it

### 0.5. Read tex_profile.json and select LaTeX patterns

Before composing the prompt, read `workspace/tex_profile.json` and apply
these rules to every LaTeX choice in the generated paper:

| Profile flag | True → use | False → use instead |
|---|---|---|
| `use_cleveref` | `\cref{fig:X}`, `\cref{tab:Y}` | `Figure~\ref{fig:X}`, `Table~\ref{tab:Y}` |
| `use_nicefrac` | `\nicefrac{a}{b}` | `$a/b$` |
| `use_microtype` | `\usepackage{microtype}` | omit the line |
| `use_t1_fontenc` | `\usepackage[T1]{fontenc}` | omit the line |

If `tex_profile.json` does not exist (old workspace), default to the safe
fallback column (no cleveref, no nicefrac, no microtype, no T1 fontenc).

### 1. Pre-extract metrics from the experimental log

Run the deterministic helper:

```bash
python skills/section-writing-agent/scripts/extract_metrics.py \
    --log workspace/inputs/experimental_log.md \
    --out workspace/metrics.json
```

This parses the `## 2. Raw Numeric Data` section's markdown tables into
structured JSON. The Section Writing Agent uses this to construct LaTeX
booktabs tables without re-deriving values from raw text. Read
`references/latex-table-patterns.md` for the booktabs conventions.

### 2. Compose the prompt and make ONE multimodal call

Load `references/prompt.md` (verbatim Section Writing Agent prompt from App.
F.1). Prepend the Anti-Leakage Prompt from
`../paper-orchestra/references/anti-leakage-prompt.md`.

Then append the **craft constraints** for the sections being drafted. Pull
them from `skills/shared/section_rhetoric.md` — the global rules plus only
the templates for Abstract, Method, Experiments, and Conclusion (Intro and
Related Work are already written by Step 3; do not re-open them). The App.
F.1 prompt specifies what each section must *contain*; the rhetoric
templates specify the paragraph roles and their order. Without them the
model produces content-complete sections whose paragraphs all make the same
kind of move, which the Step 5 reviewer scores down on Logical Flow.

The user message contains:

- `outline.json` — full content
- `idea.md` — full content
- `experimental_log.md` — full content (tables AND prose)
- `intro_relwork.tex` — full content (this becomes `template.tex` for the prompt)
- `citation_pool.json` — full content (becomes `citation_map.json`)
- `conference_guidelines.md` — full content
- `figures_list` — array of `{figure_id, filename, caption}` from
  `captions.json` and the file listing
- **The actual figure PNGs** as multimodal image inputs, so the model can
  visually inspect them and write accurate descriptions / refer to them
  correctly in the prose.

If your host LLM has no vision input, fall back to text-only mode: pass the
captions in `captions.json` as descriptions and tell the agent it cannot see
the images directly. Quality drops noticeably (the paper notes that visual
grounding measurably improves figure-text alignment), but the pipeline
still completes.

### 3. Save the output

The agent's response is wrapped in `\`\`\`latex ... \`\`\`` fences. Extract
the LaTeX code and save to `workspace/drafts/paper.tex`.

### 4. Run the deterministic gates

```bash
# Orphan citation gate: every \cite{KEY} must exist in refs.bib
python skills/section-writing-agent/scripts/orphan_cite_gate.py \
    workspace/drafts/paper.tex workspace/refs.bib

# Latex sanity: matched braces, matched begin/end, no unescaped specials
python skills/section-writing-agent/scripts/latex_sanity.py \
    workspace/drafts/paper.tex

# Anti-leakage post-check: no author names, emails, affiliations
python skills/paper-orchestra/scripts/anti_leakage_check.py \
    workspace/drafts/paper.tex
```

If any gate fails, **re-prompt the writing call** with the gate's error
report appended to the user message and ask the agent to fix the specific
issues. Do NOT try to fix the gate violations by hand — the model needs to
see its own mistakes.

## Critical rules from the prompt

These are excerpted from `references/prompt.md` (App. F.1, pp. 47-49). The
host agent MUST honor them on the writing call:

### Existing-content preservation

- DO NOT modify the text, style, or content of sections that are already
  filled in `intro_relwork.tex`. Preserve Intro + Related Work verbatim.
- Keep the preamble (packages, document class, style) **exactly** as is.
- Come up with a good title if one is missing. Fill author names if missing
  (but the Anti-Leakage Prompt says not to invent real ones — use a
  placeholder like "Anonymous Authors" for double-blind).

### Data and tables

- Build LaTeX tables for the experimental results.
- Extract numeric values directly from `experimental_log.md`. **Do not
  hallucinate numbers** — use the exact values in the log.
- Use the `booktabs` package format: `\toprule`, `\midrule`, `\bottomrule`.
- All tables must appear before the Conclusion section, unless they are
  explicitly placed in an Appendix.

### Citations

- The `outline.json` provides citation_hints per subsection. For each hint,
  find the matching key in `citation_pool.json` (by title or content) and
  use that exact key in `\cite{...}`.
- **Use ONLY keys from `refs.bib`.** Inventing or guessing keys violates the
  Lit Review Agent's verified pool.
- **Read the abstract** from `citation_pool.json` for the papers you cite.
  Use the abstract context to write specific, accurate sentences about
  those works — not generic "[A, B] proposed methods for X".

### Writing content

- Write the missing sections following `outline.json`'s `section_plan`
  structure exactly. Hierarchy rule: if 4.1 exists, 4.2 must exist.
- Use formal mathematical equations, notations, and definitions where
  appropriate AND directly supported by `idea.md` or `experimental_log.md`.
  **Do not hallucinate math.** Do not use complex math just for the sake
  of it.
- Always provide detailed ablation studies and qualitative analysis of the
  experimental results: what worked, what does not, and why.
- Optional: discuss limitations and future work at the end.
- If you put anything in the Appendix, the Appendix section appears AFTER
  the References section, on a fresh new page.

### Figures and visual fidelity

- You are being given the actual image files of the figures. You MUST
  describe them faithfully and accurately. Do NOT hallucinate
  interpretations that contradict the visual evidence in the plots.
- Use ALL of the figures provided in `figures/`. Use the exact filenames
  including extensions (e.g., `.png`) in your `\includegraphics` commands.
- DO NOT merge or group multiple figures into one display.
- If the paper is in a 2-column format, prefer single-column figures
  (`\begin{figure}`) unless they are very wide.
- All figures must appear before the Conclusion section, unless explicitly
  in the Appendix.
- Refine the captions if necessary, but they are already provided in
  `captions.json` and should generally be used as-is.
- Do NOT include "Figure X" in the caption text — LaTeX handles numbering.

### Rhetorical structure

Templates and checklists live in `skills/shared/section_rhetoric.md`. The
constraints the writing call must honor:

- **One paragraph, one message, stated in the first sentence.** A paragraph
  whose point arrives in sentence five is a paragraph reviewers skim.
- **Abstract** follows one of three templates, chosen by contribution count:
  Challenge→Contribution, Challenge→Insight→Contribution, or
  multiple-contributions (each contribution paired with its advantage *in the
  same sentence*).
- **Method subsections carry the triad** — design (the forward process as
  `input → step → step → output`), then motivation (*because X fails, we
  design Y*), then technical advantage. Design-only subsections read as a
  system manual; motivation-only subsections read as a pitch.
- **Experiments answers three questions**: better than strong baselines,
  which design choices produce the gain (ablations as deltas), and how far it
  generalizes. Every contribution claimed in the Introduction maps to at
  least one experiment.
- **Conclusion limitations are scope boundaries, not defects.** "We evaluate
  only on short sequences" bounds the method; "we did not tune the learning
  rate" invites rejection.
- **Terminology is frozen** across Abstract→Conclusion. One name per concept.

### Style

- Adopt the tone of a top-tier ML conference paper: dense, objective,
  technical.
- Match the indentation and spacing style of the original `template.tex`.
  Do not change the overall LaTeX style.

### LaTeX integrity

- The output must compile flawlessly out-of-the-box.
- All `\begin{X}` must match a `\end{X}` (e.g., `\begin{figure*}` must be
  closed with `\end{figure*}`, not `\end{figure}`).
- DO NOT change `\usepackage[capitalize]{cleveref}` to
  `\usepackage[capitalize]{cleverref}` — there is no `cleverref.sty`.
- **Always emit `\clearpage` immediately before `\bibliographystyle{...}`.**
  Without it, figures deferred by LaTeX's float algorithm will appear inside
  or after the References section — a hard-to-spot layout defect that only
  shows up in the compiled PDF. `\clearpage` forces all pending floats to be
  output before the bibliography starts. See
  `references/latex-table-patterns.md` for details.
- **Cross-references**: prefer `Figure~\ref{fig:X}` and `Table~\ref{tab:Y}`
  over bare `\ref{fig:X}`. This is necessary when `cleveref` is unavailable
  and produces readable prose in all cases. Use `\cref{...}` only when
  `cleveref.sty` is confirmed present.

### Output format

- Wrap the full updated `template.tex` in `\`\`\`latex ... \`\`\``.
- The previously empty sections should now be filled.
- Previously filled sections (Intro, Related Work) should remain mostly
  untouched; only adjust for consistency purposes.

## Resources

- `references/prompt.md` — verbatim Section Writing Agent prompt from App. F.1
- `references/latex-table-patterns.md` — booktabs rules + table-from-log examples
- `references/figure-integration.md` — `\includegraphics`, 2-column handling, placement
- `scripts/extract_metrics.py` — markdown tables in experimental_log → JSON
- `scripts/latex_sanity.py` — unmatched braces, env mismatches, specials
- `scripts/orphan_cite_gate.py` — every `\cite{KEY}` exists in refs.bib
- `skills/shared/section_rhetoric.md` — **NEW** per-section structural templates (abstract variants, module triad, experiment questions) + checklists
