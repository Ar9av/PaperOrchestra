#!/usr/bin/env python3
"""
crossref_client.py — Crossref REST API title/DOI lookup for cross-index
citation corroboration.

Used by cross_verify.py as a second opinion alongside Semantic Scholar:
if a paper that S2 "verified" cannot be found in Crossref *or* OpenAlex, it is
flagged as a potential phantom record (hallucination risk). See
references/cross-index-verification.md for the rationale.

No API key is required. Crossref offers a "polite pool" with better
reliability when you identify yourself via an email address. Set one of:
    export CROSSREF_MAILTO="you@example.com"
    export PAPER_ORCHESTRA_MAILTO="you@example.com"   # shared fallback
The email is sent only as a `mailto` query parameter / User-Agent, per
Crossref's etiquette guidelines. The repo never commits an address.

Usage:
    # title search
    python crossref_client.py --query "Attention is All You Need"

    # direct DOI lookup (exact)
    python crossref_client.py --doi 10.5555/3295222.3295349

    # raw Crossref JSON
    python crossref_client.py --query "BERT pre-training" --raw

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

CROSSREF_BASE = "https://api.crossref.org/works"
DEFAULT_LIMIT = 5
MAX_LIMIT = 20
_RETRY_SLEEP = 5  # seconds to wait after a 429 before retrying
SELECT_FIELDS = "DOI,title,author,published,published-print,published-online,issued,container-title,type"


def _mailto() -> str:
    return (
        os.environ.get("CROSSREF_MAILTO", "").strip()
        or os.environ.get("PAPER_ORCHESTRA_MAILTO", "").strip()
    )


def _build_request(url: str) -> urllib.request.Request:
    mailto = _mailto()
    ua = "paper-orchestra/1.0 (https://github.com/Ar9av/paper-orchestra)"
    if mailto:
        ua = f"paper-orchestra/1.0 (mailto:{mailto})"
    return urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": ua}, method="GET"
    )


def _get(url: str, retries: int = 3) -> dict:
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(_build_request(url), timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"message": {"items": []}}
            if exc.code == 429 and attempt < retries:
                print(f"WARN: Crossref rate-limited (429). Sleeping {_RETRY_SLEEP}s "
                      f"before retry {attempt + 1}/{retries}.", file=sys.stderr)
                time.sleep(_RETRY_SLEEP)
                continue
            if exc.code in (500, 502, 503) and attempt < retries:
                print(f"WARN: Crossref server error ({exc.code}). Retrying.", file=sys.stderr)
                time.sleep(10)
                continue
            print(f"ERROR: Crossref HTTP {exc.code}", file=sys.stderr)
            sys.exit(1)
        except urllib.error.URLError as exc:
            print(f"ERROR: Network error reaching Crossref: {exc.reason}", file=sys.stderr)
            sys.exit(1)
    sys.exit(1)


def _year_from(work: dict) -> int | None:
    for key in ("published", "published-print", "published-online", "issued"):
        dp = (work.get(key) or {}).get("date-parts")
        if dp and dp[0] and dp[0][0]:
            return int(dp[0][0])
    return None


def _normalize_work(work: dict) -> dict:
    titles = work.get("title") or []
    venues = work.get("container-title") or []
    authors = []
    for a in work.get("author", []) or []:
        name = " ".join(p for p in [a.get("given"), a.get("family")] if p).strip()
        if name:
            authors.append(name)
    doi = (work.get("DOI") or "").lower().strip()
    return {
        "title": titles[0] if titles else "",
        "year": _year_from(work),
        "doi": doi,
        "venue": venues[0] if venues else "",
        "authors": authors,
        "type": work.get("type", ""),
    }


def search(query: str, limit: int) -> dict:
    params = {"query.bibliographic": query, "rows": limit, "select": SELECT_FIELDS}
    mailto = _mailto()
    if mailto:
        params["mailto"] = mailto
    url = f"{CROSSREF_BASE}?{urllib.parse.urlencode(params)}"
    resp = _get(url)
    items = (resp.get("message") or {}).get("items") or []
    return {"raw": resp, "data": [_normalize_work(w) for w in items]}


def lookup_doi(doi: str) -> dict:
    url = f"{CROSSREF_BASE}/{urllib.parse.quote(doi)}"
    mailto = _mailto()
    if mailto:
        url += f"?mailto={urllib.parse.quote(mailto)}"
    resp = _get(url)
    msg = resp.get("message")
    data = [_normalize_work(msg)] if msg else []
    return {"raw": resp, "data": data}


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--query", help="Paper title (bibliographic search)")
    p.add_argument("--doi", help="Look up an exact DOI instead of a title search")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                   help=f"Max hits (default {DEFAULT_LIMIT}, max {MAX_LIMIT})")
    p.add_argument("--raw", action="store_true", help="Print full Crossref JSON")
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
