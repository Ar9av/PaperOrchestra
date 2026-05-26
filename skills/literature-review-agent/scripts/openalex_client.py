#!/usr/bin/env python3
"""
openalex_client.py — OpenAlex API title/DOI lookup for cross-index citation
corroboration.

The third index (alongside Semantic Scholar and Crossref) used by
cross_verify.py. Triangulating across three independent scholarly indices is
the practical defense against hallucinated citations: a fabricated paper may
slip past one index but is unlikely to appear in all three with matching
metadata. See references/cross-index-verification.md.

No API key is required. OpenAlex offers a faster "polite pool" when you
identify yourself via email. Set one of:
    export OPENALEX_MAILTO="you@example.com"
    export PAPER_ORCHESTRA_MAILTO="you@example.com"   # shared fallback
The email is sent only as the `mailto` query parameter, per OpenAlex docs.

Usage:
    python openalex_client.py --query "Attention is All You Need"
    python openalex_client.py --doi 10.5555/3295222.3295349
    python openalex_client.py --query "BERT pre-training" --raw

Output (normalized): {"total": N, "data": [{title, year, doi, venue, authors}, ...]}

Exit codes:
    0  at least one result returned
    1  HTTP error, network error, or zero results
    2  usage error (bad arguments)
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

OPENALEX_BASE = "https://api.openalex.org/works"
DEFAULT_LIMIT = 5
MAX_LIMIT = 25
_RETRY_SLEEP = 5


def _mailto() -> str:
    return (
        os.environ.get("OPENALEX_MAILTO", "").strip()
        or os.environ.get("PAPER_ORCHESTRA_MAILTO", "").strip()
    )


def _build_request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "paper-orchestra/1.0 (https://github.com/Ar9av/paper-orchestra)",
        },
        method="GET",
    )


def _get(url: str, retries: int = 3) -> dict:
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(_build_request(url), timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"results": []}
            if exc.code == 429 and attempt < retries:
                print(f"WARN: OpenAlex rate-limited (429). Sleeping {_RETRY_SLEEP}s "
                      f"before retry {attempt + 1}/{retries}.", file=sys.stderr)
                time.sleep(_RETRY_SLEEP)
                continue
            if exc.code in (500, 502, 503) and attempt < retries:
                print(f"WARN: OpenAlex server error ({exc.code}). Retrying.", file=sys.stderr)
                time.sleep(10)
                continue
            print(f"ERROR: OpenAlex HTTP {exc.code}", file=sys.stderr)
            sys.exit(1)
        except urllib.error.URLError as exc:
            print(f"ERROR: Network error reaching OpenAlex: {exc.reason}", file=sys.stderr)
            sys.exit(1)
    sys.exit(1)


def _bare_doi(doi_url: str | None) -> str:
    if not doi_url:
        return ""
    d = doi_url.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d


def _normalize_work(work: dict) -> dict:
    venue = ""
    loc = work.get("primary_location") or {}
    src = loc.get("source") or {}
    if src.get("display_name"):
        venue = src["display_name"]
    authors = []
    for a in work.get("authorships", []) or []:
        name = (a.get("author") or {}).get("display_name")
        if name:
            authors.append(name)
    return {
        "title": work.get("title") or work.get("display_name") or "",
        "year": work.get("publication_year"),
        "doi": _bare_doi(work.get("doi")),
        "venue": venue,
        "authors": authors,
        "type": work.get("type", ""),
    }


def _with_mailto(params: dict) -> dict:
    mailto = _mailto()
    if mailto:
        params["mailto"] = mailto
    return params


def search(query: str, limit: int) -> dict:
    params = _with_mailto({"search": query, "per-page": limit})
    url = f"{OPENALEX_BASE}?{urllib.parse.urlencode(params)}"
    resp = _get(url)
    results = resp.get("results") or []
    return {"raw": resp, "data": [_normalize_work(w) for w in results]}


def lookup_doi(doi: str) -> dict:
    # OpenAlex resolves a single work via the /works/doi:<doi> path.
    path = f"{OPENALEX_BASE}/doi:{urllib.parse.quote(doi)}"
    mailto = _mailto()
    if mailto:
        path += f"?mailto={urllib.parse.quote(mailto)}"
    resp = _get(path)
    # A single-work response is the work object itself, not a results list.
    if "results" in resp:
        works = resp["results"]
    elif resp.get("id"):
        works = [resp]
    else:
        works = []
    return {"raw": resp, "data": [_normalize_work(w) for w in works]}


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--query", help="Paper title (full-text search)")
    p.add_argument("--doi", help="Look up an exact DOI instead of a title search")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                   help=f"Max hits (default {DEFAULT_LIMIT}, max {MAX_LIMIT})")
    p.add_argument("--raw", action="store_true", help="Print full OpenAlex JSON")
    args = p.parse_args()

    if not args.query and not args.doi:
        print("ERROR: provide --query or --doi", file=sys.stderr)
        return 2

    if args.doi:
        result = lookup_doi(args.doi.lower())
    else:
        result = search(args.query, max(1, min(MAX_LIMIT, args.limit)))

    if args.raw:
        json.dump(result["raw"], sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0 if result["data"] else 1

    data = result["data"]
    json.dump({"total": len(data), "data": data}, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if data else 1


if __name__ == "__main__":
    sys.exit(main())
