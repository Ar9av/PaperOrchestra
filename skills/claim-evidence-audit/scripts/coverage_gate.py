#!/usr/bin/env python3
"""
coverage_gate.py — fail when too few claims have evidence.

Coverage = supported claims / total claims (from claim_evidence_map.json).
`partial` claims do not count unless --count-partial is given. Claims whose
only citation evidence was rejected by the citation audit (not_supported) are
already `unmapped` in the map.

Usage:
    python coverage_gate.py --map workspace/claim_audit/claim_evidence_map.json \\
        [--threshold 80] [--count-partial] [--max-unmapped N]

Default threshold: 80 (percent). Exit codes: 0 pass, 1 below threshold,
2 input error. An empty claim list passes (nothing to support).
"""
import argparse
import json
import sys

DEFAULT_THRESHOLD = 80.0


def coverage(doc: dict, count_partial: bool = False) -> float:
    entries = doc.get("claims", [])
    if not entries:
        return 100.0
    ok = sum(1 for e in entries if e["status"] == "supported"
             or (count_partial and e["status"] == "partial"))
    return 100.0 * ok / len(entries)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", required=True)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help="minimum coverage percent (default %(default)s)")
    ap.add_argument("--count-partial", action="store_true")
    ap.add_argument("--max-unmapped", type=int, help="also fail if unmapped claims exceed this count")
    args = ap.parse_args()
    if not 0 <= args.threshold <= 100:
        print("ERROR: --threshold must be within 0..100", file=sys.stderr)
        return 2
    try:
        with open(args.map, encoding="utf-8") as f:
            doc = json.load(f)
        cov = coverage(doc, args.count_partial)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"ERROR: cannot read map {args.map}: {e!r}", file=sys.stderr)
        return 2
    unmapped = [e for e in doc["claims"] if e["status"] == "unmapped"]
    ok = cov + 1e-9 >= args.threshold and (args.max_unmapped is None or len(unmapped) <= args.max_unmapped)
    print(f"Claim coverage: {cov:.1f}% (threshold {args.threshold:g}%) "
          f"unmapped={len(unmapped)} -> {'PASS' if ok else 'FAIL'}")
    if not ok:
        for e in unmapped:
            print(f"  UNMAPPED {e['claim_id']} {e['section']}:{e['line']}  {e['text'][:90]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
