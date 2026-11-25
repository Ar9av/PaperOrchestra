---
name: claim-evidence-audit
description: OPTIONAL claim-level audit gate for the PaperOrchestra pipeline (arXiv:2604.05018), run after Step 5 (content refinement) and before final output. Extracts atomic claims (numeric results, comparisons, "we show / we outperform" statements, cited facts) from drafts/paper.tex with section and line numbers, maps each claim to evidence (experimental_log.md numbers or table rows, figures, tables, citation keys present in the verified refs.bib), flags unmapped claims, checks every number in the paper against the log, and enforces a coverage threshold. Includes an opt-in pass where the host agent fetches each cited source and judges supported / partially_supported / not_supported / cannot_verify with a locator. TRIGGER when the orchestrator reaches the optional audit gate or when the user asks to "audit the claims", "check that every claim is backed by evidence", "verify the numbers against the log", "build a claim-evidence map", or "check that citations actually support what we say".
---

# Claim-Evidence Audit (optional gate after Step 5)

PaperOrchestra already checks that citations *exist* (Semantic Scholar) and that a
simulated reviewer likes the draft. Neither shows that each claim in the paper is
**backed**: by the experimental log for our results, or by what the cited paper
actually says for cited facts. This skill adds that claim-level check.

**Cost: 0 LLM calls for the deterministic core; one reasoning pass by the host
agent to review claims, plus an opt-in source-reading pass for cited facts.**
All scripts are stdlib-only, deterministic, and make no network or LLM calls.
Fetching and judging cited sources is done by you, the host agent.

## Safety rule (non-negotiable)

Refinement and audit must never game the evaluator or invent evidence.
**Unsupported claims get softened or removed. Support is never fabricated.**

- Do not add a number to the experimental log, a bib entry, or a locator in order
  to make a claim pass. Do not edit the log to match the paper.
- Do not choose a verdict because it makes the coverage gate pass. If you cannot
  read the source, the verdict is `cannot_verify`, not `supported`.
- Fix a failing claim by weakening its wording ("improves" to "is comparable to"),
  attributing it correctly, or deleting it. Then re-run the audit.
- Derived numbers (ratios, deltas) absent from the log are acceptable only if you
  can show the arithmetic from logged values; otherwise remove them.

## Relation to existing gates

`skills/paper-orchestra/scripts/claim_evidence_gate.py` (Step 4/5 pre-flight) is a
quick WARN gate for numeric claims only. This skill is the fuller, opt-in audit:
section/line-tagged claims, figure/table/citation evidence, rounding-aware
number matching, a coverage threshold, and the cited-source pass.

## Inputs

- `workspace/final/paper.tex` (or `workspace/drafts/paper.tex`) - draft to audit
- `workspace/inputs/experimental_log.md` - ground truth for our numbers
- `workspace/refs.bib` - the **verified** bibliography from Step 3

## Outputs (all under `workspace/claim_audit/`)

| File | Producer |
|---|---|
| `claims.json` | `extract_claims.py`, then reviewed by you |
| `claim_evidence_map.json` / `.md` | `build_evidence_map.py` |
| `numeric_report.json` | `numeric_consistency.py` |
| `citation_audit.json` | you (opt-in Phase 4) |
| `audit_report.md` | `audit_report.py` |

Schemas: `references/schemas.md`. Citation-audit procedure: `references/citation-audit.md`.

## Procedure

Set `A=workspace/claim_audit` and `S=skills/claim-evidence-audit/scripts`.

### Phase 1 - Extract and review claims

```bash
python $S/extract_claims.py --paper workspace/final/paper.tex --out $A/claims.json
```

The extractor is a heuristic. Its output is **candidates**. Open `claims.json`
and, as the host agent:

1. Delete non-claims (setup descriptions, definitions, hedged motivation).
2. Split compound sentences into atomic claims (one number or one assertion each);
   give new claims fresh unique ids `C###`, and keep `section` and `line`.
3. Add missed claims (e.g. a comparison phrased without a trigger word).
4. For each `cited_fact`, make sure `cite_keys` lists every key the sentence relies on.
5. Set `"reviewed": true`, then validate:

```bash
python $S/validate_schema.py --claims $A/claims.json
```

### Phase 2 - Map claims to evidence

```bash
python $S/build_evidence_map.py --claims $A/claims.json \
    --log workspace/inputs/experimental_log.md --bib workspace/refs.bib \
    --paper workspace/final/paper.tex \
    --out-json $A/claim_evidence_map.json --out-md $A/claim_evidence_map.md
python $S/numeric_consistency.py --paper workspace/final/paper.tex \
    --log workspace/inputs/experimental_log.md --out $A/numeric_report.json
```

Evidence kinds: `log_number`, `log_table_row`, `figure`, `table`, `citation`
(key present in the verified `.bib`). A claim is `supported`, `partial` (some
number nothing accounts for), or `unmapped`. Number matching allows the paper to
round the log value to its own precision and reconciles `87.4%` with `0.874`;
the paper may not claim more precision than the log. `numeric_consistency.py`
lists every number in the paper (prose, captions, table cells) absent from the log.

### Phase 3 - Resolve gaps

For every `unmapped` / `partial` claim and every number reported "NOT IN LOG":
find real support in the log or sources, otherwise soften or delete the claim in
the paper (see Safety rule). Keep a one-line note of each change. Re-run Phase 2.

### Phase 4 - Citation audit (opt-in)

Run only when the user asks for it or the venue is citation-sensitive. Follow
`references/citation-audit.md`: for each `cited_fact` claim, fetch each cited
source with your own tools, judge it `supported` / `partially_supported` /
`not_supported` / `cannot_verify`, and record a locator (section, page, or quote
anchor) in `$A/citation_audit.json`. Then re-run Phase 2 with
`--audit $A/citation_audit.json`. `not_supported` rejects the citation as
evidence; `partially_supported` downgrades the claim to `partial`.
Fix those claims by softening, re-attributing, or removing - never by editing the
verdict.

### Phase 5 - Gate and report

```bash
python $S/validate_schema.py --claims $A/claims.json --map $A/claim_evidence_map.json \
    [--audit $A/citation_audit.json]
python $S/coverage_gate.py --map $A/claim_evidence_map.json --threshold 80
python $S/audit_report.py --map $A/claim_evidence_map.json \
    --numeric $A/numeric_report.json [--audit $A/citation_audit.json] --out $A/audit_report.md
```

`coverage_gate.py` exits 1 below the threshold (default 80%; `--count-partial`,
`--max-unmapped N` available). If it fails, repeat Phase 3. If it still fails
after two rounds, stop and report the remaining claims to the user rather than
lowering the threshold silently. After any edit to the paper, re-run the
Step 6 compile.

## Exit codes

| Script | 0 | 1 | 2 |
|---|---|---|---|
| `extract_claims.py`, `build_evidence_map.py`, `audit_report.py` | written | - | input error |
| `validate_schema.py` | valid | schema violations | file unreadable |
| `numeric_consistency.py` | all numbers in log | numbers not in log | input error |
| `coverage_gate.py` | coverage >= threshold | below threshold | input error |

## Tests

```bash
python3 skills/claim-evidence-audit/scripts/test_claim_evidence_audit.py
```

Fixtures live in `skills/claim-evidence-audit/fixtures/`.

## Resources

- `references/schemas.md` - `claims.json`, `claim_evidence_map.json`, `citation_audit.json`
- `references/citation-audit.md` - the opt-in cited-source judging procedure
- `scripts/claimlib.py` - shared LaTeX scan, number parsing, rounding-aware matching
- `scripts/extract_claims.py`, `build_evidence_map.py`, `numeric_consistency.py`,
  `validate_schema.py`, `coverage_gate.py`, `audit_report.py`
