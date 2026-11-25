# PaperOrchestra Pipeline

Reference for the orchestrator. Source: arXiv:2604.05018, §4 and Fig. 1.

## The 5 steps

```
                  ┌──────────────────────────────────────────────────┐
                  │  Inputs: I (idea.md), E (experimental_log.md),    │
                  │          T (template.tex), G (guidelines.md),     │
                  │          F (figures/, optional)                   │
                  └────────────────────┬─────────────────────────────┘
                                       │
                                       ▼
                  ┌──────────────────────────────────────────────────┐
                  │  Step 1: Outline Agent              (1 LLM call) │
                  │  outline.json = {                                 │
                  │    plotting_plan,                                 │
                  │    intro_related_work_plan,                       │
                  │    section_plan                                   │
                  │  }                                                │
                  └────────────────────┬─────────────────────────────┘
                                       │
                          ┌────────────┴────────────┐
                          │ PARALLEL                 │
                          ▼                          ▼
        ┌──────────────────────────┐  ┌──────────────────────────────┐
        │ Step 2: Plotting Agent    │  │ Step 3: Lit Review Agent     │
        │ ~20-30 calls              │  │ ~20-30 calls                 │
        │ - few-shot retrieval      │  │ - parallel candidate         │
        │ - visual planning         │  │   discovery (10 workers)     │
        │ - render                  │  │ - sequential S2 verify       │
        │ - VLM critique loop       │  │   (1 QPS, Levenshtein > 70)  │
        │ - caption                 │  │ - dedup by S2 paperId        │
        │ → figures/*.png           │  │ - draft Intro + Related Work │
        │ → figures/captions.json   │  │   (≥90% citation integration)│
        │                           │  │ → drafts/intro_relwork.tex   │
        │                           │  │ → refs.bib                   │
        └──────────────┬───────────┘  └──────────────┬──────────────┘
                       └────────────┬─────────────────┘
                                    ▼
                  ┌──────────────────────────────────────────────────┐
                  │  Step 4: Section Writing Agent      (1 LLM call) │
                  │  ONE single multimodal call:                      │
                  │  - extracts numeric values from E                 │
                  │  - builds booktabs LaTeX tables                   │
                  │  - drafts Abstract / Methodology / Experiments /  │
                  │    Conclusion (preserves Intro + Related Work)    │
                  │  - splices figures from F                         │
                  │  → drafts/paper.tex                               │
                  └────────────────────┬─────────────────────────────┘
                                       │
                                       ▼
                  ┌──────────────────────────────────────────────────┐
                  │  Step 5: Content Refinement Agent  (~5-7 calls)  │
                  │  Loop (≤ ~3 iterations):                          │
                  │    1. simulated reviewer scores current draft     │
                  │    2. apply revision targeting weaknesses         │
                  │    3. re-score                                    │
                  │    4. accept or revert per halt rules             │
                  │  → final/paper.tex + final/paper.pdf              │
                  └──────────────────────────────────────────────────┘
```

## Optional gate: Claim-Evidence Audit (after Step 5, before final output)

```
  Step 5 output (final/paper.tex)
          │
          ▼
  ┌──────────────────────────────────────────────────┐
  │  OPTIONAL: claim-evidence-audit (0 core LLM calls)│
  │  - extract atomic claims (section + line)         │
  │  - map claims → log numbers / figures / verified  │
  │    citation keys; flag unmapped claims            │
  │  - numeric consistency: paper vs experimental log │
  │  - coverage gate (default ≥ 80% claims supported) │
  │  - opt-in: judge cited sources, with locators     │
  │  → workspace/claim_audit/*                        │
  └──────────────────────────────────────────────────┘
          │  unsupported claims are softened or removed,
          ▼  never backed with invented evidence
  Step 6: compile + provenance
```

Skipped by default. Run it when the user asks for claim verification or the
target venue is strict about unsupported claims. It is not part of the paper's
five-agent pipeline and adds no calls to the App. B budget. See
`skills/claim-evidence-audit/SKILL.md`.

## Parallelism rules

- **Steps 2 and 3 are independent** and have no shared state. They MUST run in
  parallel when the host supports it. If not, run Step 3 first because its
  wall-time floor is set by Semantic Scholar's 1 QPS verification limit.
- Within Step 2: figure rendering jobs are independent and can be parallelized
  per `figure_id`. The VLM critique loop within a single figure is sequential
  (render → critique → redraw).
- Within Step 3: candidate **discovery** is parallel (10 concurrent web search
  workers in the paper, but the host can use whatever its tool supports).
  Candidate **verification** via Semantic Scholar must be sequential at ≤1 QPS
  to respect the public API rate limit. See `s2-api-cookbook.md`.

## Step 5 halt rules (verbatim from `content-refinement-agent/references/halt-rules.md`)

The refinement loop accepts a revision iff:

```
ACCEPT  if  overall_new > overall_prev
ACCEPT  if  overall_new == overall_prev  AND  net_subaxis_delta >= 0
REVERT  otherwise
```

The loop halts when any of the following becomes true:

1. **Iteration cap reached** (default = 3).
2. **Overall score decreased** vs previous iteration → revert to previous snapshot.
3. **Overall score tied** but net sub-axis change is negative → revert, halt.
4. **No new actionable weaknesses** in the simulated reviewer output.

The "best" snapshot at termination is copied to `workspace/final/`.

## Anti-Leakage prompt

Every LLM call that **writes paper content** (Outline, Lit Review draft,
Section Writing, Refinement) MUST be prefixed with the verbatim Anti-Leakage
Prompt at `anti-leakage-prompt.md`. The Plotting Agent and Caption Generation
calls are exempt because they don't generate paper text.

## Cost budget per agent (from App. B)

| Agent | LLM calls |
|---|---|
| Outline Agent | 1 |
| Plotting Agent | ~20–30 |
| Hybrid Literature Agent | ~20–30 |
| Section Writing Agent | 1 |
| Content Refinement Agent | ~5–7 |
| **Total** | **~60–70** |

Mean wall-clock per paper: ~39.6 minutes (paper Table 7) on parallel
infrastructure. Sequential execution will be 2-3x slower.
