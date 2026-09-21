# Claim-Evidence Map

Every quantitative statement in a paper is one of three things:

1. **Our result** — the number must appear in `experimental_log.md`.
2. **Someone else's result** — the sentence must carry a citation.
3. **A fabrication** — the number appears in neither place.

The third category is the failure mode that ends careers, and it is the one a
language model produces most naturally: a plausible-looking figure generated
to make a sentence land. Treating claim-evidence alignment as a hard
constraint — rather than as something the reviewer might notice — is the
single highest-value gate in the refinement loop.

## Running it

```bash
python skills/paper-orchestra/scripts/claim_evidence_gate.py \
    --paper  workspace/drafts/paper.tex \
    --log    workspace/inputs/experimental_log.md \
    --out    workspace/claim_evidence_report.json \
    --out-md workspace/claim_evidence_map.md
```

Exit codes: `0` PASS, `1` WARN (unsupported claims present), `2` ERROR (input
missing). This is a WARN gate — it never halts the pipeline.

## The three statuses

| Status | Meaning | Action |
|---|---|---|
| `supported` | The value occurs in `experimental_log.md` | None |
| `attributed` | The sentence carries a `\cite`, or a prior-work cue such as "prior work" / "et al." / "according to" | Spot-check that the citation actually contains the number |
| `needs evidence` | Neither | Verify against the log, attribute it to a source, or remove it |

`needs evidence` does not mean "wrong". A number computed from two logged
values (a ratio, a percentage delta) is legitimately absent from the log. The
gate cannot arithmetic, so it reports; the revision agent decides. What the
gate guarantees is that no such number passes through unexamined.

## Using the map in the loop

Read `workspace/claim_evidence_map.md` at Step 0 and pass every
`needs evidence` row to the revision agent as an explicit agenda item:

> The following values appear in the paper but cannot be corroborated in
> `experimental_log.md` and carry no citation. For each: restate it from
> logged values, attribute it to a cited source, or remove the claim.
> Do not weaken the sentence into vagueness to make the number defensible.

Re-run the gate after the iteration. A `needs evidence` row that survives two
iterations is a signal to delete the sentence, not to keep rewording it.

## What the gate does not check

- Whether a number is **correctly derived** from the logged values.
- Whether the cited paper actually reports the attributed number.
- Whether a **qualitative** claim ("substantially outperforms") is supported.
  The five-dimension self-review in `references/reviewer-rubric.md` covers
  those; this gate only covers numbers.

## Provenance

The claim-evidence contract (`Claim | Evidence | Status`, with
claim-evidence alignment treated as a hard constraint for Abstract and
Introduction) follows the output contract in
[Master-cai/Research-Paper-Writing-Skills](https://github.com/Master-cai/Research-Paper-Writing-Skills)
(MIT). The deterministic extraction, LaTeX normalization, and attribution
detection are PaperOrchestra's.
