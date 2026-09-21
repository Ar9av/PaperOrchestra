# Changelog

All notable changes to PaperOrchestra are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added

- **`figure_lint.py`** (plotting-agent) — makes the Step 2 hard rules checkable. ERRORs: rendered figure with no caption, caption with no file, empty caption, raster too small to print. WARNs: under ~300 DPI at single-column width, aspect ratio past 4:1, self-numbering captions (`Figure 3: ...`), captions under eight words, and a figure set containing no architecture/pipeline figure. `--paper` cross-checks that the draft uses every rendered figure and references no missing file. PNG geometry is read from the IHDR/pHYs chunks directly, so no imaging dependency is added.
- **`test_figure_lint.py`** — 19 stdlib-only tests; PNG fixtures are synthesized in a temp directory rather than committed as binaries.

### Fixed

- **`examples/agentic-security-report`: `fig_attack_success_rates` had no entry in `captions.json`** while being referenced by the paper — found by the new linter on its first run. Caption added from the figure's own `\caption` text.

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
