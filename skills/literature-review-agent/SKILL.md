---
name: literature-review-agent
description: Step 3 of the PaperOrchestra pipeline (arXiv:2604.05018). Execute the literature search strategy from outline.json — discover candidate papers via web search, verify them through Semantic Scholar (Levenshtein > 70 fuzzy title match, temporal cutoff, dedup by paperId), cross-corroborate against Crossref + OpenAlex to flag hallucinated citations, build a BibTeX file, and draft Introduction + Related Work using ≥90% of the verified pool. Runs in parallel with the plotting-agent. TRIGGER when the orchestrator delegates Step 3 or when the user asks to "find citations for my paper", "draft the related work", or "build the bibliography".
---

# Literature Review Agent (Step 3)

Faithful implementation of the Hybrid Literature Agent from PaperOrchestra
(Song et al., 2026, arXiv:2604.05018, §4 Step 3, App. D.3, App. F.1 p.46).

**Cost: ~20–30 LLM calls.** This is one of the two longest steps (the other is
plotting). Wall-time floor is set by Semantic Scholar's 1 QPS verification
limit.

## Inputs

- `workspace/outline.json` — specifically `intro_related_work_plan` with the
  Introduction search directions and the 2-4 Related Work methodology
  clusters
- `workspace/inputs/conference_guidelines.md` — used to derive `cutoff_date`
- `workspace/inputs/idea.md`, `workspace/inputs/experimental_log.md` — for
  framing the Intro and grounding the Related Work positioning

## Outputs

- `workspace/citation_pool.json` — verified Semantic Scholar metadata for
  every paper that survived verification
- `workspace/refs.bib` — BibTeX file generated from the verified pool
- `workspace/drafts/intro_relwork.tex` — drafted Introduction and Related
  Work sections, written into the template, with the rest of the template
  preserved verbatim

## Two-phase pipeline (App. D.3)

```
PHASE 1 — Parallel Candidate Discovery
   For each search direction in introduction_strategy.search_directions:
   For each limitation_search_query in each related_work cluster:
     - Use the host's web search tool to discover up to ~10 candidate papers.
     - Run up to 10 discovery queries in parallel (host-permitting).
     - Collect (title, snippet, url) tuples — no verification yet.
   → PRE-DEDUP before Phase 2 (see Step 1.5 below)

PHASE 2 — Sequential Citation Verification (1 QPS, with cache)
   For each candidate (after pre-dedup), sequentially:
     0. Check s2_cache.json first (scripts/s2_cache.py --check).
        If HIT: use cached response, skip live S2 call. No throttle needed.
        If MISS: proceed with live request below.
     1. Query Semantic Scholar by title:
          GET https://api.semanticscholar.org/graph/v1/paper/search?query=<title>
              &fields=title,abstract,year,authors,venue,externalIds&limit=5
        (Public endpoint, no key. Throttle to 1 QPS for live requests only.)
     2. Store the S2 response in cache: s2_cache.py --store.
     3. Pick the top hit. Check Levenshtein title ratio against the original
        candidate title. If ratio < 70: discard.
     4. Bonus: if year and venue exactly align with hints, add a +5 point
        match-quality bonus.
     5. Require: abstract is non-empty.
     6. Require: paper.year (or month if known) strictly predates cutoff_date.
        Months default to day-1: e.g., "October 2024" → 2024-10-01.
     7. If all checks pass, add to verified pool.
   After all candidates are verified, dedup by Semantic Scholar paperId.
```

The host agent does the LLM/web work; the deterministic helpers in `scripts/`
do the math.

## Step-by-step

### 0. Derive `cutoff_date`

Parse `conference_guidelines.md` for the submission deadline. The paper aligns
research cutoff with venue submission deadline (App. D.1):

| Venue | Cutoff |
|---|---|
| CVPR 2025 | Nov 2024 |
| ICLR 2025 | Oct 2024 |
| Other | One month before the stated submission deadline |

Encode as `YYYY-MM-DD`. Months default to day-1 (e.g., `2024-10-01`).

### 1. Phase 1: Parallel Candidate Discovery

From `outline.json`:

- All `introduction_strategy.search_directions` (3-5 queries)
- For each cluster in `related_work_strategy.subsections`:
  - The cluster's `sota_investigation_mission` becomes a search query
  - All `limitation_search_queries` (1-3 each)

For each query, **use your host's web search tool** (e.g., `WebSearch` in
Claude Code, `@web` in Cursor, the search tool in Antigravity). Collect the
top ~10 candidates per query: title, abstract snippet, source URL.

If your host supports parallel sub-tasks, fire up to 10 concurrent search
queries. If not, run sequentially — slower but functionally equivalent.

#### Optional: Exa as a Phase 1 backend

If your host has no native web search, OR you want a research-paper-focused
backend with better signal-to-noise, you can use [Exa](https://exa.ai) via
the bundled `scripts/exa_search.py` helper. It is **opt-in** and reads
`EXA_API_KEY` from the environment — the repo never commits a key.

```bash
export EXA_API_KEY="your-key-here"   # get one at https://dashboard.exa.ai/
python skills/literature-review-agent/scripts/exa_search.py \
    --query "Sparse attention long context transformers" \
    --num-results 15 \
    --discovered-for "related_work[2.1]"
```

Output is a normalized candidate list ready to merge into
`raw_candidates.json`. Phase 2 verification (Semantic Scholar fuzzy match,
cutoff, dedup) is unchanged. See `references/exa-search-cookbook.md` for
the full recipe, query patterns, cost estimates, and security notes.

Combine all discovered candidates into a single working list. Tag each with
the originating query ID so you can later attribute it to "intro" vs
"related_work[i]".

### 1.5. Pre-dedup before Phase 2

**Always run this before starting Phase 2.** Multiple search queries routinely
return the same papers (e.g., "Attention is All You Need" appears in almost
every NLP discovery query). Verifying duplicates wastes 30-40% of S2 quota
at 1 QPS.

```bash
python skills/literature-review-agent/scripts/pre_dedup_candidates.py \
    --in workspace/raw_candidates.json \
    --out workspace/deduped_candidates.json
# Prints: "150 candidates → 97 unique (53 duplicates removed)"
```

Use `workspace/deduped_candidates.json` as input to Phase 2.

### 2. Phase 2: Sequential Verification via Semantic Scholar (with cache)

For each candidate in `deduped_candidates.json`, in **sequential** order:

**Step A — check cache first** (no S2 call, no throttle needed):
```bash
python skills/literature-review-agent/scripts/s2_cache.py \
    --cache workspace/cache/s2_cache.json \
    --check "<candidate title>"
# exit 0 + prints JSON → use cached response, skip Step B
# exit 1 → proceed to Step B
```

**Step B — live S2 request** (cache MISS only, throttle to 1 QPS):

**Preferred:** use the bundled `scripts/s2_search.py` helper — it handles
auth, retries, and 429 back-off automatically:

```bash
python skills/literature-review-agent/scripts/s2_search.py \
    --query "<URL-decoded candidate title>" --limit 5
# If SEMANTIC_SCHOLAR_API_KEY is set the key is forwarded automatically.
# If not, the public unauthenticated endpoint is used (≤1 QPS, still works).
```

Check whether the key is configured before starting Phase 2:

```bash
python skills/literature-review-agent/scripts/s2_search.py --check-key
```

**Fallback:** if you prefer your host's URL fetch tool, GET:
```
https://api.semanticscholar.org/graph/v1/paper/search?query=<URL-encoded title>&limit=5&fields=title,abstract,year,authors,venue,externalIds
```
Add header `x-api-key: <SEMANTIC_SCHOLAR_API_KEY>` if the env var is set.
Be polite: ≤1 request per second for live requests. Cache hits are free.

**Step C — store in cache** (after every successful live request):
```bash
python skills/literature-review-agent/scripts/s2_cache.py \
    --cache workspace/cache/s2_cache.json \
    --store "<candidate title>" \
    --response '<full S2 JSON response>'
```

For the top hit:

```bash
python skills/literature-review-agent/scripts/levenshtein_match.py \
    --candidate "Original candidate title" \
    --found "S2 returned title"
# prints integer 0-100. Discard if < 70.
```

Then check the temporal cutoff:

```bash
python skills/literature-review-agent/scripts/check_cutoff.py \
    --paper-year 2024 \
    --paper-month 9 \
    --cutoff 2024-10-01
# exit 0 if strictly predates, exit 1 if not
```

If both checks pass AND the abstract is non-empty, append the paper's full
S2 metadata to the verified pool.

### 3. Dedup and assemble the pool

After all candidates are verified:

```bash
python skills/literature-review-agent/scripts/dedupe_by_id.py \
    --in raw_pool.json \
    --out workspace/citation_pool.json
```

The dedupe script keys on `paperId` (Semantic Scholar's internal unique ID),
falling back to `externalIds.DOI`, then `externalIds.ArXiv`, then a
normalized title.

The script also computes and writes `min_cite_paper_count` =
`floor(0.9 * len(papers))` — the minimum number of papers the writing step
must cite (the paper's ≥90% integration rule, App. D.3).

**Immediately after dedupe_by_id.py**, validate and auto-fix the pool schema:

```bash
python skills/literature-review-agent/scripts/validate_pool.py \
    --pool workspace/citation_pool.json --fix
# Catches and fixes authors-as-strings, reports missing required fields.
# Must pass before proceeding to Step 4.
```

### 3.5. Cross-index verification (Crossref + OpenAlex)

Semantic Scholar is one index and can return a plausible record for a paper
that does not exist, or attach wrong metadata. Re-check every S2-verified
paper against two **independent** indices before building the bibliography —
this is the practical defense against hallucinated citations leaking in.

```bash
# Optional but recommended: a polite-pool email gives faster, more reliable
# service. The repo never commits an address.
export PAPER_ORCHESTRA_MAILTO="you@example.com"

python skills/literature-review-agent/scripts/cross_verify.py \
    --pool workspace/citation_pool.json --inplace
# Annotates each paper with a `cross_verification` field and writes
# workspace/cross_verification_report.json.
# exit 0 = all corroborated; exit 1 = WARN (something flagged or an index
# was unreachable); exit 2 = usage error.
```

This is a **WARN gate, not a hard gate** (like `validate_consistency.py`): it
flags suspicious citations but does not block the pipeline or delete anything.
Review the `low` and `conflict` tiers in the report:

- `high` — corroborated by ≥1 external index → keep.
- `medium` — corroborated but year disagrees → keep, spot-check the year.
- `low` — not found in Crossref or OpenAlex → **review by hand**. Note that
  arXiv-only preprints (no DOI) are a common benign cause; `low` means
  "could not corroborate," not "fabricated." S2 already confirmed it exists.
- `conflict` — pool DOI disagrees with the external DOI → likely wrong record.

Drop only the entries you genuinely cannot corroborate, then re-run
`dedupe_by_id.py` onward. If both indices are unreachable (offline), the script
degrades gracefully and the pipeline continues on S2 verification alone.

See `references/cross-index-verification.md` for the full rationale, confidence
tiers, and the arXiv false-positive note.

### 4. Build the BibTeX file

```bash
python skills/literature-review-agent/scripts/bibtex_format.py \
    --pool workspace/citation_pool.json \
    --out workspace/refs.bib
```

The script generates citation keys deterministically from `firstauthor + year
+ first significant word of title` (e.g., `vaswani2017attention`). It writes
out only `@article` / `@inproceedings` / `@misc` entries — never invents
fields. It also writes the canonical `bibtex_key` back into each paper record
in `citation_pool.json`.

**Immediately after bibtex_format.py**, sync keys in `intro_relwork.tex`:

```bash
python skills/literature-review-agent/scripts/sync_keys.py \
    --pool workspace/citation_pool.json \
    --tex  workspace/drafts/intro_relwork.tex \
    --inplace
# Replaces every \cite{agent_key} with \cite{canonical_bibtex_key}.
# Eliminates citation_coverage gate failures caused by key mismatch.
```

These two steps replace the manual Python snippets that were previously
required. The pipeline is now:

```
dedupe_by_id → validate_pool --fix → cross_verify --inplace → bibtex_format → sync_keys
```

### 5. Draft Introduction + Related Work

This is where you (the host agent) actually write text. Load the
**verbatim Literature Review Agent prompt** at `references/prompt.md`.
Substitute the template placeholders:

| Placeholder | Value |
|---|---|
| `intro_related_work_plan` | full JSON object from `outline.json` |
| `project_idea` | contents of `idea.md` |
| `project_experimental_log` | contents of `experimental_log.md` |
| `citation_checklist` | the BibTeX keys from `refs.bib` |
| `collected_papers` | list of `{key, title, abstract}` from `citation_pool.json` |
| `paper_count` | `len(citation_pool.papers)` |
| `min_cite_paper_count` | from `citation_pool.json` |
| `cutoff_date` | the date you derived in Step 0 |

**Also prepend the Anti-Leakage Prompt** from
`../paper-orchestra/references/anti-leakage-prompt.md`.

Run your LLM with the combined prompt against `template.tex`. The agent's
job is to fill in the empty Introduction and Related Work sections of the
template **and leave everything else untouched**. Output: the full
`template.tex` with those two sections filled. Save to
`workspace/drafts/intro_relwork.tex`.

### 6. Verify ≥90% citation coverage

```bash
python skills/literature-review-agent/scripts/citation_coverage.py \
    --tex workspace/drafts/intro_relwork.tex \
    --pool workspace/citation_pool.json
# exit 0 if ≥90% of pool is cited; exit 1 otherwise
```

If the gate fails, re-prompt the writing step explicitly listing the missing
keys and asking the agent to integrate them where contextually appropriate.

## Critical rules from the prompt

These are excerpted from `references/prompt.md`. The host agent MUST honor
them on the writing call:

- **Cite ONLY from `collected_papers`.** Never invent BibTeX keys, never
  reference papers not in the pool.
- **Cite at least `min_cite_paper_count` of them** in Intro + Related Work
  combined.
- **TIMELINE RULE**: Do not treat any papers published after `cutoff_date`
  as prior baselines to beat. They are concurrent work only.
- **EVALUATION RULE**: Do not claim our method beats / achieves SOTA over a
  specific cited paper UNLESS that paper is explicitly evaluated against in
  `experimental_log.md`. Frame other recent papers strictly as concurrent,
  orthogonal, or conceptual work.
- **Output format**: return the full code for the updated `template.tex`,
  with the two empty sections (Introduction and Related Work) filled in,
  and **all the other code** (packages, styles, other sections) **identical
  to the original** template.tex.
- Wrap output in ```` ```latex ... ``` ```` fences.
- Do not change `\usepackage[capitalize]{cleveref}` to `cleverref` (there is
  no `cleverref.sty`).

## Degraded mode (no web search)

If your host has no web search tool, switch to degraded mode:

1. If the user has placed a pre-built `workspace/inputs/refs.bib` in the
   workspace, load it directly into `workspace/refs.bib` and skip Phase 1
   and Phase 2.
2. Otherwise, emit `workspace/drafts/intro_relwork.tex` containing the
   template with two TODO markers in the Intro and Related Work sections,
   and tell the user the pipeline cannot complete Step 3 without web search.

## Resources

- `references/prompt.md` — verbatim Literature Review Agent prompt from App. F.1
- `references/discovery-pipeline.md` — Phase 1 + Phase 2 explained in detail
- `references/verification-rules.md` — Levenshtein cutoff, year alignment, dedup
- `references/citation-density-rule.md` — the ≥90% integration rule
- `references/s2-api-cookbook.md` — Semantic Scholar URLs, fields, rate limits
- `references/cross-index-verification.md` — Crossref + OpenAlex corroboration, confidence tiers, arXiv false-positive note
- `references/exa-search-cookbook.md` — optional Exa backend for Phase 1 (research-paper-focused web search)
- `scripts/pre_dedup_candidates.py` — **NEW** dedup Phase 1 candidates before Phase 2 (saves 30-40% S2 quota)
- `scripts/s2_cache.py` — **NEW** persistent S2 response cache (eliminates re-verification on re-runs)
- `scripts/validate_pool.py` — **NEW** validate & auto-fix citation_pool.json schema (authors format)
- `scripts/sync_keys.py` — **NEW** sync cite keys in .tex with canonical bibtex_keys after bibtex_format.py
- `scripts/levenshtein_match.py` — fuzzy title match (ratio > 70)
- `scripts/check_cutoff.py` — date cmp w/ month → day-1 default
- `scripts/dedupe_by_id.py` — dedup verified pool by S2 paperId
- `scripts/bibtex_format.py` — build refs.bib from JSON pool
- `scripts/citation_coverage.py` — ≥90% citation coverage gate
- `scripts/s2_search.py` — **NEW** Semantic Scholar title-search helper; reads `SEMANTIC_SCHOLAR_API_KEY` from env (optional — falls back to unauthenticated)
- `scripts/exa_search.py` — optional Exa Phase 1 backend (reads `EXA_API_KEY` from env)
- `scripts/crossref_client.py` — **NEW** Crossref title/DOI lookup for cross-index corroboration (no key; reads `CROSSREF_MAILTO` / `PAPER_ORCHESTRA_MAILTO`)
- `scripts/openalex_client.py` — **NEW** OpenAlex title/DOI lookup for cross-index corroboration (no key; reads `OPENALEX_MAILTO` / `PAPER_ORCHESTRA_MAILTO`)
- `scripts/cross_verify.py` — **NEW** cross-corroborate the S2-verified pool against Crossref + OpenAlex; flags hallucinated citations (WARN gate)
