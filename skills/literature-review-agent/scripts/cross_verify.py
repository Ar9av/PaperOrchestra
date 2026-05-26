#!/usr/bin/env python3
"""
cross_verify.py — Cross-index corroboration for a verified citation pool.

Semantic Scholar verification (Levenshtein title match + cutoff + dedup) is the
pipeline's first gate. This script adds a second: every paper that S2 accepted
is re-checked against two *independent* scholarly indices — Crossref and
OpenAlex. A genuine paper turns up in all three with matching metadata; a
hallucinated or mis-attributed record typically does not. This is the practical
defense against the well-documented problem of fabricated citations leaking
into AI-assisted writing.

The script is a WARN gate, not a hard gate (mirrors validate_consistency.py):
it annotates the pool and writes a report, but exits non-zero only to draw the
host agent's attention to flagged entries — it does not block the pipeline.
The host agent reviews flagged citations and decides whether to drop them.

Confidence tiers written onto each paper's `cross_verification` field:
    high      corroborated by >=1 external index, no metadata conflicts
    medium    corroborated, but publication year disagrees beyond tolerance
    low       NOT found in Crossref or OpenAlex — phantom/hallucination risk
    conflict  a DOI present in the pool disagrees with the external index's DOI

Network etiquette: queries are throttled (--sleep, default 1.0s between papers)
and identify via a polite-pool email if PAPER_ORCHESTRA_MAILTO (or the
per-service CROSSREF_MAILTO / OPENALEX_MAILTO) is set. If an index is
unreachable the script degrades gracefully — it disables that index, notes it
in the report, and continues with whatever indices remain.

Usage:
    python cross_verify.py --pool workspace/citation_pool.json
    python cross_verify.py --pool workspace/citation_pool.json --inplace
    python cross_verify.py --pool workspace/citation_pool.json \\
        --out workspace/cross_verification_report.json \\
        --indices crossref,openalex --threshold 70 --year-tolerance 1 --sleep 1.0

Exit codes:
    0  every paper corroborated (all high/medium), no flags
    1  one or more papers flagged low/conflict, OR an index was unavailable (WARN)
    2  usage error / pool unreadable
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crossref_client  # noqa: E402
import openalex_client  # noqa: E402

try:
    import Levenshtein  # noqa: E402

    def _ratio(a: str, b: str) -> int:
        return int(round(Levenshtein.ratio(a, b) * 100))
except ImportError:  # graceful fallback — stdlib only
    from difflib import SequenceMatcher

    def _ratio(a: str, b: str) -> int:
        return int(round(SequenceMatcher(None, a, b).ratio() * 100))


def _normalize(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def title_ratio(a: str, b: str) -> int:
    return _ratio(_normalize(a), _normalize(b))


def _bare_doi(doi: str | None) -> str:
    if not doi:
        return ""
    d = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d


def pool_doi(paper: dict) -> str:
    """Extract a DOI from a pool record, tolerating several shapes."""
    ext = paper.get("externalIds") or {}
    for k in ("DOI", "doi", "Doi"):
        if ext.get(k):
            return _bare_doi(ext[k])
    if paper.get("doi"):
        return _bare_doi(paper["doi"])
    return ""


def best_match(title: str, hits: list[dict]) -> dict | None:
    """Pick the external hit whose title best matches `title`."""
    best, best_r = None, -1
    for h in hits:
        r = title_ratio(title, h.get("title", ""))
        if r > best_r:
            best, best_r = h, r
    if best is None:
        return None
    out = dict(best)
    out["title_ratio"] = best_r
    return out


def _safe(fn, *args):
    """Call a client function, converting its SystemExit (network/HTTP error)
    into a None so cross_verify can degrade instead of dying."""
    try:
        return fn(*args)
    except SystemExit:
        return None


def check_index(module, paper: dict, threshold: int, strong_threshold: int, limit: int) -> dict:
    """Look one paper up in a single external index. Returns a per-index dict,
    or {"available": False} if the index could not be reached.

    Two match strengths are recorded:
      found  — title_ratio > threshold (lenient): "something like this exists"
      strong — title_ratio >= strong_threshold, or an exact DOI hit: "this is
               confidently the same paper". Only `strong` matches are trusted
               for year/DOI conflict downgrades, so a noisy near-title hit
               (e.g. a different paper with a similar name) cannot pollute the
               metadata-conflict checks.
    """
    title = paper.get("title", "")
    doi = pool_doi(paper)

    result = None
    via = "title"
    if doi:
        r = _safe(module.lookup_doi, doi)
        if r is None:
            return {"available": False}
        if r["data"]:
            result = r["data"][0]
            result["title_ratio"] = title_ratio(title, result.get("title", ""))
            via = "doi"
    if result is None:
        r = _safe(module.search, title, limit)
        if r is None:
            return {"available": False}
        result = best_match(title, r["data"])

    if result is None:
        return {"available": True, "found": False, "strong": False}

    tr = result.get("title_ratio", 0)
    found = tr > threshold or via == "doi"
    strong = tr >= strong_threshold or via == "doi"
    ext_doi = _bare_doi(result.get("doi"))
    doi_state = "n/a"
    if doi and ext_doi:
        doi_state = "agree" if doi == ext_doi else "conflict"
    return {
        "available": True,
        "found": bool(found),
        "strong": bool(strong),
        "via": via,
        "matched_title": result.get("title", ""),
        "title_ratio": tr,
        "matched_year": result.get("year"),
        "matched_doi": ext_doi,
        "doi_state": doi_state,
    }


def classify(paper: dict, per_index: dict, year_tolerance: int) -> dict:
    found_in = [name for name, r in per_index.items() if r.get("found")]
    # Only confident same-paper matches can trigger a metadata-conflict downgrade.
    doi_conflict = any(
        r.get("doi_state") == "conflict" and r.get("strong") for r in per_index.values()
    )

    year = paper.get("year")
    year_conflict = False
    if year is not None:
        for r in per_index.values():
            my = r.get("matched_year")
            if r.get("strong") and my is not None and abs(int(my) - int(year)) > year_tolerance:
                year_conflict = True

    notes = []
    if doi_conflict:
        confidence = "conflict"
        notes.append("DOI in pool disagrees with external index — verify this record")
    elif not found_in:
        confidence = "low"
        notes.append("not found in Crossref or OpenAlex — possible phantom citation")
    elif year_conflict:
        confidence = "medium"
        notes.append("corroborated, but publication year disagrees beyond tolerance")
    else:
        confidence = "high"

    return {
        "confidence": confidence,
        "indices_found": found_in,
        "doi_conflict": doi_conflict,
        "year_conflict": year_conflict,
        "per_index": per_index,
        "notes": notes,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--pool", required=True, help="citation_pool.json path")
    p.add_argument("--out", default=None,
                   help="Report path (default: <pool dir>/cross_verification_report.json)")
    p.add_argument("--inplace", action="store_true",
                   help="Annotate each paper in the pool with its cross_verification result")
    p.add_argument("--indices", default="crossref,openalex",
                   help="Comma-separated external indices to check (default both)")
    p.add_argument("--threshold", type=int, default=70,
                   help="Levenshtein title-match threshold for corroboration "
                        "(default 70, matches S2 gate)")
    p.add_argument("--strong-threshold", type=int, default=90,
                   help="Stricter title-match threshold before an external record's "
                        "year/DOI is trusted for a conflict downgrade (default 90)")
    p.add_argument("--year-tolerance", type=int, default=1,
                   help="Allowed |year| difference before flagging (default 1)")
    p.add_argument("--limit", type=int, default=5, help="Max hits per title search")
    p.add_argument("--sleep", type=float, default=1.0,
                   help="Seconds to pause between papers (politeness, default 1.0)")
    args = p.parse_args()

    try:
        with open(args.pool) as f:
            pool = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read pool: {exc}", file=sys.stderr)
        return 2

    papers = pool.get("papers", [])
    if not papers:
        print("ERROR: pool['papers'] is empty or missing", file=sys.stderr)
        return 2

    modules = {"crossref": crossref_client, "openalex": openalex_client}
    requested = [x.strip() for x in args.indices.split(",") if x.strip()]
    unknown = [x for x in requested if x not in modules]
    if unknown:
        print(f"ERROR: unknown index/indices: {', '.join(unknown)}", file=sys.stderr)
        return 2

    disabled: set[str] = set()
    summary = {"high": 0, "medium": 0, "low": 0, "conflict": 0}
    flagged = []

    for i, paper in enumerate(papers):
        per_index = {}
        for name in requested:
            if name in disabled:
                continue
            res = check_index(modules[name], paper, args.threshold,
                              args.strong_threshold, args.limit)
            if res.get("available") is False:
                disabled.add(name)
                print(f"WARN: index '{name}' unreachable — disabling for the rest of this run.",
                      file=sys.stderr)
                continue
            per_index[name] = res

        verdict = classify(paper, per_index, args.year_tolerance)
        summary[verdict["confidence"]] += 1
        if verdict["confidence"] in ("low", "conflict"):
            flagged.append({
                "bibtex_key": paper.get("bibtex_key") or paper.get("key"),
                "title": paper.get("title"),
                "confidence": verdict["confidence"],
                "notes": verdict["notes"],
            })
        if args.inplace:
            paper["cross_verification"] = verdict

        # Throttle between papers (skip after the last one).
        if i < len(papers) - 1 and args.sleep > 0 and requested != list(disabled):
            time.sleep(args.sleep)

    report = {
        "total_papers": len(papers),
        "indices_checked": [x for x in requested if x not in disabled],
        "indices_unavailable": sorted(disabled),
        "summary": summary,
        "flagged": flagged,
    }

    out_path = args.out or os.path.join(os.path.dirname(os.path.abspath(args.pool)),
                                        "cross_verification_report.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    if args.inplace:
        with open(args.pool, "w") as f:
            json.dump(pool, f, indent=2, ensure_ascii=False)

    # Human-readable summary to stdout.
    print(f"Cross-index verification ({', '.join(report['indices_checked']) or 'none'}):")
    print(f"  {len(papers)} papers  |  high={summary['high']} "
          f"medium={summary['medium']} low={summary['low']} conflict={summary['conflict']}")
    print(f"  report → {out_path}")
    if flagged:
        print(f"\nWARN: {len(flagged)} citation(s) need review:")
        for f_ in flagged:
            print(f"  [{f_['confidence'].upper()}] {f_['bibtex_key']}: {f_['title']}")
            for note in f_["notes"]:
                print(f"      → {note}")
        print("\nReview these before building refs.bib. Drop any you cannot corroborate.")

    if disabled:
        print(f"\nNote: {', '.join(sorted(disabled))} unavailable this run — "
              "corroboration is partial.", file=sys.stderr)

    return 1 if (flagged or disabled) else 0


if __name__ == "__main__":
    sys.exit(main())
