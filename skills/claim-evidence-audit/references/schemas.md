# Schemas

All files are UTF-8 JSON. `scripts/validate_schema.py` enforces them.

## claims.json

```json
{
  "version": 1,
  "source": "workspace/final/paper.tex",
  "reviewed": false,
  "claims": [
    {
      "id": "C004",
      "section": "Experiments",
      "line": 11,
      "text": "SparseLong achieves 87.4\\% exact match on NQ-L, outperforming BigBird at 85.1\\%.",
      "types": ["numeric_result", "comparison"],
      "numbers": [{"raw": "87.4%", "value": 87.4, "percent": true, "decimals": 1, "trivial": false}],
      "cite_keys": [],
      "refs": []
    }
  ]
}
```

| Field | Rule |
|---|---|
| `id` | `C` + 3 or more digits, unique |
| `section` | non-empty; `Abstract` for the abstract environment |
| `line` | integer >= 1, line in the audited `.tex` where the claim starts |
| `types` | non-empty subset of `numeric_result`, `comparison`, `show_claim`, `cited_fact` |
| `numbers` | each `{raw, value, percent, decimals, trivial}`; `trivial` = plain integer <= 10 (ignored when matching) |
| `cite_keys` | BibTeX keys in the sentence; required non-empty for `cited_fact` |
| `refs` | `\ref` labels in the sentence (used to find figure/table evidence) |

`reviewed` is set to `true` by the host agent after Phase 1.

## claim_evidence_map.json

```json
{
  "version": 1,
  "claims": [
    {
      "claim_id": "C004", "text": "...", "section": "Experiments", "line": 11,
      "types": ["numeric_result", "comparison"],
      "status": "supported",
      "evidence": [
        {"kind": "log_table_row", "detail": "87.4% ~ 0.8743",
         "locator": "experimental_log.md:7", "excerpt": "| SparseLong | 0.8743 | ..."}
      ],
      "unmatched_numbers": [],
      "missing_bib_keys": [],
      "needs_citation_audit": false
    }
  ],
  "summary": {"total": 8, "supported": 6, "partial": 0, "unmapped": 2,
              "coverage_pct": 75.0, "needs_citation_audit": 2}
}
```

- `status`: `supported`, `partial`, `unmapped`. `supported`/`partial` need at least
  one evidence entry that is not `rejected`; `unmapped` must have none.
- `evidence[].kind`: `log_number`, `log_table_row`, `figure`, `table`, `citation`.
  Citation entries may carry `audit_verdict`, `audit_locator`, and `rejected: true`.
- `summary` counts must equal the entries (checked by the validator).
- `coverage_pct` = supported / total.

## citation_audit.json

Written by the host agent in Phase 4. One record per (claim, cite key).

```json
{
  "audits": [
    {"claim_id": "C002", "cite_key": "vaswani2017attention",
     "verdict": "supported",
     "locator": {"type": "section", "value": "Sec. 3.2, para 1"},
     "notes": ""}
  ]
}
```

| Field | Rule |
|---|---|
| `verdict` | `supported`, `partially_supported`, `not_supported`, `cannot_verify` |
| `locator` | `{type: "section"\|"page"\|"quote", value: str}`; required unless `cannot_verify` |
| `notes` | required (non-empty) for every verdict except `supported` |
