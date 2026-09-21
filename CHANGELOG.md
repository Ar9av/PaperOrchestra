# Changelog

All notable changes to PaperOrchestra are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added

- **`table_lint.py`** (section-writing-agent) — checks generated tables against the booktabs conventions. ERRORs: vertical rules, `\hline`/`\cline`, missing `\toprule`/`\bottomrule`, caption below the tabular, missing caption, `table` environment with no tabular. WARNs: no `\label`, six-word captions, numeric columns with no `↑`/`↓` direction marker, mixed decimal precision within a numeric column, tables placed after the Conclusion. Runs as a Step 4 gate alongside `orphan_cite_gate.py` and `latex_sanity.py`.
- **`test_table_lint.py`** — 19 stdlib-only tests, one per rule.
- **Readability rules section in `references/latex-table-patterns.md`** — metric direction in headers, units in headers rather than cells, constant decimal precision per column, one-table-one-message, `\multicolumn` + `\cmidrule` grouping instead of vertical separators, restrained highlighting, and what a caption is for.

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
