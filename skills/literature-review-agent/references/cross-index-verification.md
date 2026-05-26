# Cross-Index Citation Verification

Supplementary verification layer that runs *after* the Semantic Scholar gate
(Rules 1–4 in `verification-rules.md`) and *before* `bibtex_format.py`. It
re-checks every S2-verified paper against two independent scholarly indices —
**Crossref** and **OpenAlex** — and flags any that cannot be corroborated.

## Why

A single index can return a plausible-looking record for a paper that does not
exist, or attach the wrong metadata to a real title. Triangulating across three
independent indices is the standard practical defense: a genuine paper appears
in all three with consistent metadata, while a fabricated or mis-attributed
record usually does not survive the cross-check. This directly targets the
documented failure mode where AI-assisted writing introduces hallucinated
citations into the bibliography.

S2 verification answers "does a paper with this title plausibly exist?"
Cross-index verification answers "do *other* indices agree it exists, with the
same year and DOI?"

## Scripts

| Script | Role |
|---|---|
| `scripts/crossref_client.py` | Crossref REST API title/DOI lookup, normalized output |
| `scripts/openalex_client.py` | OpenAlex API title/DOI lookup, normalized output |
| `scripts/cross_verify.py` | Orchestrates both, classifies confidence, writes report |

All three are stdlib-only (`urllib`), need **no API key**, and degrade
gracefully if an index is unreachable (the index is disabled for the run and
noted in the report; remaining indices still run).

## Polite pool (recommended, not required)

Crossref and OpenAlex give faster, more reliable service when you identify
yourself by email. Set one shared address:

```bash
export PAPER_ORCHESTRA_MAILTO="you@example.com"
```

or per-service `CROSSREF_MAILTO` / `OPENALEX_MAILTO`. The email is sent only as
a `mailto` query parameter / User-Agent per each service's etiquette docs. The
repo never commits an address.

## Confidence tiers

`cross_verify.py --inplace` writes a `cross_verification` object onto each pool
paper, and a summary report to `workspace/cross_verification_report.json`:

| Tier | Meaning | Host action |
|---|---|---|
| `high` | Corroborated by ≥1 external index, no metadata conflicts | keep |
| `medium` | Corroborated, but publication year disagrees beyond `--year-tolerance` | keep; spot-check the year used in prose |
| `low` | Not found in Crossref **or** OpenAlex | **review** — see false-positive note below |
| `conflict` | A DOI in the pool disagrees with the external index's DOI | **review** — likely wrong record |

Two thresholds keep the tiers honest:

- **Corroboration** uses the lenient `> 70` (`--threshold`, same as the S2
  gate): "an entry like this exists in the index."
- **Conflict downgrades** (`medium`/`conflict`) require a strict `>= 90`
  (`--strong-threshold`) or an exact DOI hit before an external record's year
  or DOI is trusted. This stops a noisy near-title hit — a *different* paper
  with a similar name — from polluting the metadata checks and falsely
  downgrading a correctly-matched paper.

A DOI present in the pool is looked up exactly first; only on a miss does the
script fall back to title search.

## This is a WARN gate, not a hard gate

`cross_verify.py` mirrors `validate_consistency.py`: it exits non-zero (1) when
anything is flagged or an index was unavailable, but it **does not block the
pipeline**. Hallucination removal is a judgment call, so the gate surfaces
candidates for the host agent to review — it never deletes citations itself.

Exit codes: `0` all corroborated · `1` flags present or an index unavailable
(WARN) · `2` usage error / unreadable pool.

## Known false positive: arXiv-only preprints

Crossref does not index most arXiv preprints (they have no Crossref DOI), and
OpenAlex title search may not rank an arXiv-only work in its top hits. A
legitimate, S2-verified preprint (e.g. *Proximal Policy Optimization
Algorithms*, arXiv:1707.06347) can therefore land in the `low` tier.

**`low` means "could not corroborate," not "fabricated."** S2 already confirmed
the record exists. Treat `low`/`conflict` as a prompt to look closer:
- If the paper is a well-known arXiv preprint you recognize → keep it.
- If you cannot find it anywhere by hand → drop it from the pool and re-run
  `dedupe_by_id.py` onward.

Do **not** auto-delete `low`-tier papers.

## Where it fits in the pipeline

```
dedupe_by_id → validate_pool --fix → cross_verify --inplace → bibtex_format → sync_keys
```

See SKILL.md Step 3.5.
