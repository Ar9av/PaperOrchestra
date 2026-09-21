# Changelog

All notable changes to PaperOrchestra are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Fixed

- **`claim_evidence_gate.py` extracted almost nothing from real LaTeX.** Three compounding bugs: `\%` was treated as a comment start (deleting the rest of every line containing a percentage), percentages/multipliers/bounds were matched against plain-text forms that never occur in LaTeX (`3.2\%`, `2.13$\times$`, `${>}85\%$`), and `\cite{...}` was deleted before attribution detection ran, so the citation cues in `PRIOR_WORK_CONTEXT` could never fire. On the bundled `agentic-security-report` example the gate found **1 claim**; it now finds **52**, and a fabricated uncited result injected into that paper is now caught (exit 1) where it previously passed.
- **Global value dedup let match order decide classification.** A number first seen in Related Work suppressed the identical number claimed in Experiments. Claims are now deduped on `(value, sentence)`.
- **`baseline` / `compared to` were attribution cues**, which reclassified our own comparative results ("improves over the strongest baseline by 3.2%") as someone else's numbers. Cues narrowed to citation markers and explicit ascriptions.
- **Removed the unreachable weak-support branch** and the `build_number_index()` helper that only fed it.
- **`examples/agentic-security-report`: `fig_attack_success_rates` had no entry in `captions.json`** while being referenced by the paper — found by the new linter on its first run. Caption added from the figure's own `\caption` text.

### Added

- **`skills/shared/section_rhetoric.md`** — per-section structural templates (three Abstract variants, the Introduction logic chain, the Related Work paragraph template, the Method module triad, the three Experiments questions, Conclusion scope-vs-defect limitations) plus per-section checklists. The App. F.1 prompts specify what each section must contain but not how its paragraphs should be shaped; this supplies that layer. Wired into Step 3 (Intro + Related Work), Step 4 (Abstract/Method/Experiments/Conclusion), and the Step 5 reviewer's Logical Flow axis. Templates adapted from [Master-cai/Research-Paper-Writing-Skills](https://github.com/Master-cai/Research-Paper-Writing-Skills) (MIT).
- **`--out-md` claim-evidence map** — `Value | Section | Claim | Evidence | Status` table ordered needs-evidence first, for direct use as a revision agenda. Claims are now tagged with the section they appear in (including `Abstract`).
- **`skills/paper-orchestra/scripts/test_claim_evidence_gate.py`** — 18 stdlib-only regression tests, one per bug above. Run: `python3 skills/paper-orchestra/scripts/test_claim_evidence_gate.py`.
- **`skills/content-refinement-agent/references/claim-evidence-map.md`** — the three claim statuses, what the gate does not check, and how Step 0 feeds findings into the revision agenda.
- **`reverse_outline.py`** (content-refinement-agent) — strips a draft to one topic sentence per paragraph and flags `no-topic-sentence` (opens on a connective, or too short to carry a message), `overlong`, `multi-pivot`, `orphan`, and `citation-dump`. Run-in bold headings are merged forward so the convention does not register as a missing topic sentence. Advisory by default; `--strict` exits 1 on any flag.
- Wired as **Gate C** in the pre-refinement sequence (research brief becomes Gate D) and into every reviewer call, where the topic-sentence sequence is the input for the rubric's Logical Flow axis.
- **`references/reverse-outline.md`** — flag semantics and the four questions to ask of a topic-sentence sequence.
- **`test_reverse_outline.py`** — 16 stdlib-only tests covering preamble/float stripping, run-in heading merges, and each flag.
- **`table_lint.py`** (section-writing-agent) — checks generated tables against the booktabs conventions. ERRORs: vertical rules, `\hline`/`\cline`, missing `\toprule`/`\bottomrule`, caption below the tabular, missing caption, `table` environment with no tabular. WARNs: no `\label`, six-word captions, numeric columns with no `↑`/`↓` direction marker, mixed decimal precision within a numeric column, tables placed after the Conclusion. Runs as a Step 4 gate alongside `orphan_cite_gate.py` and `latex_sanity.py`.
- **`test_table_lint.py`** — 19 stdlib-only tests, one per rule.
- **Readability rules section in `references/latex-table-patterns.md`** — metric direction in headers, units in headers rather than cells, constant decimal precision per column, one-table-one-message, `\multicolumn` + `\cmidrule` grouping instead of vertical separators, restrained highlighting, and what a caption is for.
- **`figure_lint.py`** (plotting-agent) — makes the Step 2 hard rules checkable. ERRORs: rendered figure with no caption, caption with no file, empty caption, raster too small to print. WARNs: under ~300 DPI at single-column width, aspect ratio past 4:1, self-numbering captions (`Figure 3: ...`), captions under eight words, and a figure set containing no architecture/pipeline figure. `--paper` cross-checks that the draft uses every rendered figure and references no missing file. PNG geometry is read from the IHDR/pHYs chunks directly, so no imaging dependency is added.
- **`test_figure_lint.py`** — 19 stdlib-only tests; PNG fixtures are synthesized in a temp directory rather than committed as binaries.

---

## [v0.2.0] — 2026-04-25

### Added

- **`agent-research-aggregator` skill** — new multi-agent skill that orchestrates parallel sub-agents to aggregate and synthesise research findings across multiple papers (#3).
- **Auto-detection for `agent-research-aggregator`** — the skill is now opt-in and activates only when the host environment supports multi-agent spawning, so single-agent setups are unaffected.
- **`setup.sh`** — one-shot setup script that wires the multi-agent skills integration into the host environment (#2).
- **`build_pdf.py`** — reportlab-based fallback PDF builder for environments where LaTeX is unavailable; the plotting-agent can now produce a PDF without a full TeX installation.
- **PaperBanana backbone for plotting-agent** — optional integration that routes figure-generation through PaperBanana's hosted rendering service.
- **OpenRouter / Google key support for PaperBanana** — the PaperBanana integration now accepts an OpenRouter key or a Google (Gemini) key in addition to the original Gemini-only path.
- **Semantic Scholar API key integration** — optional `SEMANTIC_SCHOLAR_API_KEY` support raises the literature-review-agent's rate limit from the anonymous tier.
- **Exa search backend for `literature-review-agent`** — alternative search path using the Exa semantic-search API; activated by setting `EXA_API_KEY`.

### Fixed

- **Pipeline bottlenecks in CitationRL end-to-end run** — resolved several performance issues identified during a full CitationRL benchmark pass: redundant re-fetch loops, blocking I/O in the citation-gate helper, and a slow-path in the refinement halt logic.

### Changed

- Simplified PaperBanana integration surface; added upstream citation in `CITATION.cff`.
- Project renamed to **PaperOrchestra** in all README headings (was previously referred to by its earlier working name).

### Documentation

- Added paper preview thumbnail, performance metrics table, skills explanation section, and OOS-metrics achievement badge to `README.md`.
- General README refactoring for clarity and formatting.

---

## [v0.1.0] — 2026-04-09

Initial public release.

Seven composable skills mirroring the PaperOrchestra five-agent pipeline
(Song et al. 2026, arXiv:2604.05018) plus a benchmark harness and four
autoraters. Verbatim reproductions of all 13 prompts from the paper's
appendices with per-page citations. Deterministic Python helpers only —
no embedded LLM clients, no API keys required at the skill layer.

[v0.2.0]: https://github.com/Ar9av/PaperOrchestra/compare/v0.1.0...v0.2.0
[v0.1.0]: https://github.com/Ar9av/PaperOrchestra/releases/tag/v0.1.0
