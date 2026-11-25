#!/usr/bin/env python3
"""
audit_report.py — one-page markdown audit report.

Combines claim_evidence_map.json with (optional) numeric_report.json and
citation_audit.json into a single markdown report.

Usage:
    python audit_report.py --map workspace/claim_audit/claim_evidence_map.json \\
        [--numeric workspace/claim_audit/numeric_report.json] \\
        [--audit workspace/claim_audit/citation_audit.json] \\
        --out workspace/claim_audit/audit_report.md [--threshold 80]

Exit codes: 0 report written, 2 input error. The report itself does not gate;
use coverage_gate.py for that.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coverage_gate import DEFAULT_THRESHOLD, coverage  # noqa: E402

SAFETY = ("Unsupported claims are softened or removed. Support is never fabricated, and the "
          "audit must not be gamed to satisfy a gate or an evaluator.")


def render(map_doc, numeric=None, audit=None, threshold=DEFAULT_THRESHOLD) -> str:
    s = map_doc["summary"]
    cov = coverage(map_doc)
    out = ["# Claim-Evidence Audit Report", "",
           f"**Coverage:** {cov:.1f}% (threshold {threshold:g}%) - "
           f"{'PASS' if cov + 1e-9 >= threshold else 'FAIL'}", "",
           f"- Claims: {s['total']} (supported {s['supported']}, partial {s['partial']}, "
           f"unmapped {s['unmapped']})",
           f"- Cited-fact claims awaiting source audit: {s['needs_citation_audit']}"]
    if numeric:
        ns = numeric["summary"]
        out.append(f"- Numbers checked against log: {ns['checked']} "
                   f"({ns['unmatched']} not found in log)")
    out.append("")
    needs = [e for e in map_doc["claims"] if e["status"] != "supported"]
    out += ["## Claims needing action", ""]
    if needs:
        out += ["| ID | Status | Where | Claim | Why |", "|---|---|---|---|---|"]
        for e in sorted(needs, key=lambda e: (e["status"] != "unmapped", e["line"])):
            why = []
            if e["unmatched_numbers"]:
                why.append("numbers not in log: " + ", ".join(e["unmatched_numbers"]))
            if e["missing_bib_keys"]:
                why.append("cite key not in verified bib: " + ", ".join(e["missing_bib_keys"]))
            rej = [x["detail"] for x in e["evidence"] if x.get("rejected")]
            if rej:
                why.append("citation judged not_supported: " + ", ".join(rej))
            if not why:
                why.append("no evidence found")
            t = e["text"].replace("|", "\\|")
            out.append(f"| {e['claim_id']} | {e['status']} | {e['section']}:{e['line']} | "
                       f"{t[:120]} | {'; '.join(why)} |")
    else:
        out.append("None.")
    out += ["", "## Citation audit", ""]
    audits = (audit or {}).get("audits", [])
    if audits:
        counts = {}
        for a in audits:
            counts[a["verdict"]] = counts.get(a["verdict"], 0) + 1
        out.append("Verdicts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        out += ["", "| Claim | Cite key | Verdict | Locator | Notes |", "|---|---|---|---|---|"]
        for a in audits:
            loc = a.get("locator") or {}
            out.append(f"| {a['claim_id']} | {a['cite_key']} | {a['verdict']} | "
                       f"{loc.get('type', '-')}: {str(loc.get('value', '-'))[:60]} | "
                       f"{str(a.get('notes', '-'))[:80]} |")
    else:
        out.append("Citation audit not run (opt-in pass; see references/citation-audit.md).")
    if numeric and numeric["unmatched"]:
        out += ["", "## Numbers in the paper but not in the experimental log", "",
                "| Number | Where |", "|---|---|"]
        for u in numeric["unmatched"]:
            out.append(f"| {u['number']} | {u['section']}:{u['line']} |")
        out.append("")
        out.append("Derived values (ratios, deltas) may be legitimately absent; confirm each is "
                   "computable from logged values, otherwise remove it.")
    out += ["", "---", SAFETY, ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", required=True)
    ap.add_argument("--numeric")
    ap.add_argument("--audit")
    ap.add_argument("--out", required=True)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = ap.parse_args()
    try:
        load = lambda p: json.load(open(p, encoding="utf-8")) if p else None  # noqa: E731
        md = render(load(args.map), load(args.numeric), load(args.audit), args.threshold)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"ERROR: {e!r}", file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
