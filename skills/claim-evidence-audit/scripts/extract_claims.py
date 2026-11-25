#!/usr/bin/env python3
"""
extract_claims.py — deterministic candidate-claim extractor for a LaTeX draft.

Splits the prose of the draft into sentences and keeps the ones that look like
atomic claims. These are CANDIDATES: the host agent must review claims.json,
split compound sentences, and drop or add claims before mapping evidence.

Claim types (a sentence can carry several):
  numeric_result  non-trivial number (decimal, %, or integer > 10)
  comparison      outperform / better than / improves / faster / vs. ...
  show_claim      "we show / demonstrate / achieve / find ..." statements
  cited_fact      sentence containing \\cite{...}

Usage:
    python extract_claims.py --paper workspace/drafts/paper.tex \\
        --out workspace/claim_audit/claims.json [--sections "Abstract,Introduction"]

Exit codes: 0 OK (even if zero claims), 2 input missing/unreadable.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claimlib as cl  # noqa: E402

COMPARISON_RE = re.compile(
    r"\b(outperform\w*|surpass\w*|exceed\w*|beat\w*|better|worse|superior|inferior|"
    r"improv\w+|gain\w*|faster|slower|higher|lower|reduc\w+|fewer|more accurate|"
    r"state[- ]of[- ]the[- ]art|sota|compared (?:to|with)|versus|vs\.?|than|"
    r"speed-?up|regress\w*|degrad\w+)\b", re.I)
SHOW_RE = re.compile(
    r"\b(we|our|this paper|this work)\b[^.]{0,80}?\b(show\w*|demonstrat\w+|prove\w*|achiev\w+|"
    r"find|found|observe\w*|establish\w*|confirm\w*|outperform\w*|obtain\w*|reach\w*|"
    r"reveal\w*|verif\w+)\b", re.I)


def classify(sentence: str, numbers: list, cites: list) -> list:
    types = []
    if any(not n["trivial"] for n in numbers):
        types.append("numeric_result")
    if COMPARISON_RE.search(sentence):
        types.append("comparison")
    if SHOW_RE.search(sentence):
        types.append("show_claim")
    if cites:
        types.append("cited_fact")
    return types


def extract(tex: str, only_sections=None) -> list:
    scan = cl.scan_tex(tex)
    claims = []
    for sent, line, section in cl.split_sentences(scan["lines"]):
        if only_sections and section.lower() not in only_sections:
            continue
        if re.match(r"\\(?:caption|label|bibliography|usepackage|documentclass)\b", sent):
            continue
        cites = []
        for m in cl.CITE_RE.finditer(sent):
            cites.extend(cl.split_keys(m.group(1)))
        refs = []
        for m in cl.REF_RE.finditer(sent):
            refs.extend(cl.split_keys(m.group(1)))
        numbers = cl.parse_numbers(sent)
        types = classify(sent, numbers, cites)
        # A bare comparison word or show-verb with nothing else is a claim only
        # if it is a first-person/result statement; keep, host prunes.
        if not types:
            continue
        claims.append({
            "section": section, "line": line, "text": sent, "types": types,
            "numbers": numbers, "cite_keys": list(dict.fromkeys(cites)),
            "refs": list(dict.fromkeys(refs)),
        })
    return [{"id": f"C{i:03d}", **c} for i, c in enumerate(claims, 1)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paper", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sections", help="comma-separated section titles to restrict to")
    args = ap.parse_args()
    try:
        with open(args.paper, encoding="utf-8") as f:
            tex = f.read()
    except OSError as e:
        print(f"ERROR: cannot read {args.paper}: {e}", file=sys.stderr)
        return 2
    only = {s.strip().lower() for s in args.sections.split(",")} if args.sections else None
    claims = extract(tex, only)
    doc = {"version": 1, "source": args.paper, "reviewed": False, "claims": claims}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    by_type = {}
    for c in claims:
        for t in c["types"]:
            by_type[t] = by_type.get(t, 0) + 1
    print(f"Extracted {len(claims)} candidate claims -> {args.out}")
    print("  by type: " + (", ".join(f"{k}={v}" for k, v in sorted(by_type.items())) or "none"))
    print("  Next: the host agent reviews/refines claims.json (set \"reviewed\": true).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
