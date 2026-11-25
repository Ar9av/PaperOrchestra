#!/usr/bin/env python3
"""
numeric_consistency.py — numbers in the paper vs numbers in the experimental log.

Scans the paper body (prose, captions AND tabular cells; math environments,
comments, citations, \\ref/\\label arguments, years and 'Table 3'-style
references are skipped) and reports every number with no counterpart in
experimental_log.md.

Matching rules (see claimlib.numbers_match):
  - the paper may round the log value to the paper's own precision
    (log 87.43 matches paper 87.4 and 87; log 87.4 does NOT match paper 87.43)
  - percent and fraction forms reconcile (paper 87.4% ~ log 0.874, and back)
  - --abs-tol / --rel-tol widen the window if you accept additional slack
  - plain integers <= --min-int (default 10) are ignored as counts/indices

A number that is derived (a ratio, a delta, a mean of logged values) is
legitimately absent from the log; the report lists it so the host agent can
confirm it is computable from logged values. The script does not do arithmetic.

Usage:
    python numeric_consistency.py --paper workspace/drafts/paper.tex \\
        --log workspace/inputs/experimental_log.md \\
        [--out workspace/claim_audit/numeric_report.json] [--min-int 10]

Exit codes: 0 all numbers found in log, 1 unmatched numbers reported, 2 input error.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claimlib as cl  # noqa: E402


def check(tex: str, log_text: str, min_int=cl.TRIVIAL_INT_MAX, abs_tol=0.0, rel_tol=0.0) -> dict:
    log_numbers = cl.parse_log(log_text)
    scan = cl.scan_tex(tex)
    matched, unmatched = [], []
    for ln in scan["lines"]:
        if ln["envs"] & (cl.MATH_ENVS | cl.OTHER_SKIP_ENVS):
            continue
        text = ln["text"]
        if text.lstrip().startswith(("\\usepackage", "\\documentclass", "\\bibliograph",
                                     "\\setlength", "\\hspace", "\\vspace",
                                     "\\renewcommand", "\\newcommand")):
            continue
        # drop tabular column specs and graphics options
        text = re.sub(r"\\begin\{(?:tabular|tabularx|longtable)\*?\}(?:\{[^}]*\})+", " ", text)
        text = re.sub(r"\\(?:begin|end)\{[^}]*\}", " ", text)
        text = re.sub(r"\\(?:includegraphics|multicolumn|multirow)(?:\[[^\]]*\])?(?:\{[^}]*\})?", " ", text)
        text = re.sub(r"\b(?:width|height|scale)\s*=\s*[\d.]+", " ", text)
        for n in cl.parse_numbers(text):
            if not n["percent"] and n["decimals"] == 0 and n["value"] <= min_int:
                continue
            hit = next((l for l in log_numbers if cl.numbers_match(n, l, abs_tol, rel_tol)), None)
            rec = {"number": n["raw"], "value": n["value"], "section": ln["section"],
                   "line": ln["line"]}
            if hit:
                rec["log_line"] = hit["line"]
                matched.append(rec)
            else:
                unmatched.append(rec)
    return {"matched": matched, "unmatched": unmatched,
            "summary": {"checked": len(matched) + len(unmatched), "matched": len(matched),
                        "unmatched": len(unmatched), "min_int": min_int,
                        "abs_tol": abs_tol, "rel_tol": rel_tol}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paper", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--out")
    ap.add_argument("--min-int", type=int, default=cl.TRIVIAL_INT_MAX,
                    help="ignore plain integers <= this (default %(default)s)")
    ap.add_argument("--abs-tol", type=float, default=0.0)
    ap.add_argument("--rel-tol", type=float, default=0.0)
    args = ap.parse_args()
    try:
        tex = open(args.paper, encoding="utf-8").read()
        log = open(args.log, encoding="utf-8").read()
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    rep = check(tex, log, args.min_int, args.abs_tol, args.rel_tol)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
            f.write("\n")
    s = rep["summary"]
    print(f"Numeric consistency: {s['checked']} numbers checked, {s['matched']} in log, "
          f"{s['unmatched']} NOT in log")
    for u in rep["unmatched"]:
        print(f"  NOT IN LOG  {u['number']:>10}  {u['section']}:{u['line']}")
    return 1 if rep["unmatched"] else 0


if __name__ == "__main__":
    sys.exit(main())
