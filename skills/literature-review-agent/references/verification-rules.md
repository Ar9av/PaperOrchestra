# Verification Rules

Source: arXiv:2604.05018, App. D.3 ("Citation Verification"), verbatim
specifications below.

## Rule 1 — Fuzzy title match (Levenshtein > 70)

> Each candidate must resolve to a valid Semantic Scholar entity via a fuzzy
> title match (Levenshtein distance ratio > 70 [Levenshtein, 1965]),
> augmented by a point bonus for exact year alignment.

Implementation: `scripts/levenshtein_match.py` uses
`Levenshtein.ratio(a, b) * 100` from the `python-Levenshtein` package and
returns the integer ratio. Threshold: **strictly greater than 70**.

Examples:

| Candidate title | S2 title | Ratio | Verdict |
|---|---|---|---|
| "Attention Is All You Need" | "Attention Is All You Need" | 100 | accept |
| "Attention Is All You Need" | "Attention is All You Need." | 96 | accept |
| "Sparse Attention for Transformers" | "Sparse Attention in Transformers" | 88 | accept |
| "Self-Attention" | "Attention Is All You Need" | 47 | reject |
| "Linformer" | "Linformer: Self-Attention with Linear Complexity" | 28 | reject |

The Linformer case is the canonical false-negative: a short query against
a long title. Workaround: when the candidate title looks abbreviated
(< 4 words) and the S2 hit's title contains the candidate as a substring,
override the ratio check. The paper does not specify this workaround
explicitly; we add it as a soft safety net to avoid losing legitimate
short-title hits. See `levenshtein_match.py --substring-bypass`.

## Rule 2 — Abstract must exist

> To enter the final context pool, the entity must possess a retrievable
> abstract...

Discard any verified hit where `abstract` is null, empty, or `"N/A"`. The
Section Writing Agent uses the abstract to ground its citations contextually
(per the Section Writing Agent prompt: "Read the abstract provided in
citation_map.json for the papers you are citing. Use this context to write
accurate, specific sentences about those works.").

## Rule 3 — Strict temporal cutoff

> ...and strictly predate the research cutoff (when specified down to the
> month, the system defaults to the first day of that month).

Implementation: `scripts/check_cutoff.py`. Comparison rules:

- Cutoff is given as `YYYY-MM-DD`. The paper aligns it to venue submission
  deadline (Nov 2024 for CVPR 2025, Oct 2024 for ICLR 2025 — App. D.1).
- Paper year is required. Paper month is optional.
- If paper has only year: assume month=12, day=31 (worst case for the paper —
  must still be < cutoff).
- If paper has year + month: assume day=1 of that month.
- "Strictly predate" means `paper_date < cutoff_date`. Equality fails.

Examples (cutoff = 2024-10-01):

| Paper year | Paper month | Verdict |
|---|---|---|
| 2017 | — | accept |
| 2024 | 9 | accept (2024-09-01 < 2024-10-01) |
| 2024 | 10 | reject (2024-10-01 not strictly < 2024-10-01) |
| 2024 | — (only year) | reject (2024-12-31 ≥ 2024-10-01) |

The strict comparison is intentional: it prevents leakage of papers from
the same submission cycle as the target venue.

## Rule 4 — Dedup by Semantic Scholar paperId

> Finally, gathered citations are deduplicated using unique paper ID keys.

Implementation: `scripts/dedupe_by_id.py`. Key precedence:

1. `paperId` (S2's internal unique ID, always present on a verified hit)
2. `externalIds.DOI` (lowercased)
3. `externalIds.ArXiv` (without version suffix)
4. Normalized title (lowercased, alphanumeric only) — fallback only

When two candidates collide, keep the one with the higher `match_score`.

## Rule 5 — ≥90% citation integration

> The system constrains the model to cite only the provided verified papers,
> explicitly mandating that at least 90% of the gathered literature pool must
> be actively integrated and cited when synthesizing the Introduction and
> Related Work sections.

Implementation: `scripts/citation_coverage.py`. After the Lit Review writing
call produces `intro_relwork.tex`, this script:

1. Extracts every `\cite{KEY}` and `\citep{KEY}` (and variants) from the
   `.tex` file.
2. Counts unique cited keys against `len(citation_pool.papers)`.
3. Requires `cited / total ≥ 0.90`. Exits non-zero if not.

If the gate fails, the host agent must re-prompt the writing step,
explicitly listing the un-cited keys and asking the agent to integrate them.

## Rule 6 — Cross-index corroboration (supplementary)

Rules 1–4 verify candidates against a single index (Semantic Scholar). Rule 6
adds an independent second opinion: every paper that survives S2 verification is
re-checked against **Crossref** and **OpenAlex** before the bibliography is
built. This is not in the source paper — it is an addition that targets
hallucinated citations, which a single index can fail to catch.

Implementation: `scripts/cross_verify.py` (+ `crossref_client.py`,
`openalex_client.py`). It is a **WARN gate**: it annotates each pool paper with
a `cross_verification` confidence tier (`high` / `medium` / `low` / `conflict`)
and writes `cross_verification_report.json`, but never deletes citations — the
host agent reviews the `low` and `conflict` tiers and decides.

Matching reuses the same Levenshtein title threshold as Rule 1 (`> 70`); a DOI
present in the pool is looked up exactly first, falling back to title search.

⚠️ `low` means "could not corroborate," not "fabricated": arXiv-only preprints
without a DOI are a common benign cause. See `cross-index-verification.md` for
the full tier definitions, polite-pool env vars, and the false-positive note.
