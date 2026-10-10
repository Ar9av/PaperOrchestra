#!/usr/bin/env python3
"""
serply_search.py — Optional Serply (https://serply.io) backend for the
literature review agent's Phase 1 (parallel candidate discovery) step.

Serply is a Google SERP API: it returns live Google search results as
JSON, with no scraping, proxies or CAPTCHAs to manage on your side. It is
OPTIONAL — the literature-review-agent works fine with any host coding
agent's native web search tool. Use Serply only if:

  - Your host has no built-in web search (e.g., Aider, OpenCode, generic
    CLI agents).
  - You want real Google results, including `site:` and date filters.
  - You're running the pipeline in batch / non-interactive mode and want
    a deterministic, scriptable backend.

This helper reads SERPLY_API_KEY from the environment. The key is YOUR
responsibility to provide; this repo never commits one. Get a key at
https://serply.io (docs: https://serply.io/docs; new accounts get free
trial credits).

Usage:
    export SERPLY_API_KEY="your-key-here"
    python serply_search.py --query "Sparse attention long context" --num-results 10
    python serply_search.py --query "..." --raw                       # full JSON
    python serply_search.py --query "..." --discovered-for "related_work[2.1]"

Default output: JSON candidates in the literature-review-agent format, ready
to be merged into raw_candidates.json before Phase 2 verification.

Exit codes:
    0  query succeeded
    1  SERPLY_API_KEY missing, HTTP error, network error, or empty results
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

SERPLY_ENDPOINT = "https://api.serply.io/v1/search"
USER_AGENT = "PaperOrchestra"
DEFAULT_NUM = 10
MAX_NUM = 10  # Serply returns at most one SERP page (~10 rows) per call
SNIPPET_CAP = 1500

# Academic domains to boost research-paper results (applied as site: operators)
ACADEMIC_DOMAINS = [
    "arxiv.org",
    "scholar.google.com",
    "semanticscholar.org",
    "aclanthology.org",
    "openreview.net",
]

# Serply passes Google's `tbm=nws` through, which returns news articles in
# the same results[] shape.
TOPIC_PARAMS = {
    "general": {},
    "news": {"tbm": "nws"},
}


def search(query: str, num_results: int, topic: str,
           include_domains: list[str] | None) -> dict:
    api_key = os.environ.get("SERPLY_API_KEY")
    if not api_key:
        print(
            "ERROR: SERPLY_API_KEY environment variable not set.\n"
            "Get a key at https://serply.io and run:\n"
            '  export SERPLY_API_KEY="your-key-here"\n'
            "Then retry. The literature-review-agent also works without\n"
            "Serply — see references/discovery-pipeline.md for the default\n"
            "host-native web search path.",
            file=sys.stderr,
        )
        sys.exit(1)

    q = query
    if include_domains:
        q += " (" + " OR ".join(f"site:{d}" for d in include_domains) + ")"
    params = {"q": q, "num": num_results, **TOPIC_PARAMS[topic]}

    req = urllib.request.Request(
        f"{SERPLY_ENDPOINT}?{urllib.parse.urlencode(params)}",
        headers={
            "X-Api-Key": api_key,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:500]
        print(f"ERROR: Serply HTTP {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"ERROR: Serply network error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def normalize(serply_response: dict, discovered_for: list[str],
              limit: int) -> list[dict]:
    """Convert Serply results into the literature-review-agent candidate format."""
    candidates: list[dict] = []
    for r in serply_response.get("results", []):
        url = r.get("link") or ""
        # Rare cached rows carry an opaque token instead of a URL; skip them.
        if not url.startswith(("http://", "https://")):
            continue
        title = (r.get("title") or "").strip()
        content = (r.get("description") or "").strip()
        snippet = content[:SNIPPET_CAP]
        candidates.append({
            "title":          title,
            "snippet":        snippet,
            "source_url":     url,
            "discovered_for": list(discovered_for),
            "_serply_position": r.get("position"),
        })
    return candidates[:limit]


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--query", required=True, help="Search query")
    p.add_argument("--num-results", type=int, default=DEFAULT_NUM,
                   help=f"Number of results to fetch "
                        f"(default {DEFAULT_NUM}, clamped to [1, {MAX_NUM}])")
    p.add_argument("--topic", default="general",
                   choices=["general", "news"],
                   help='Result type (default "general"; '
                        'use "news" for recent news articles)')
    p.add_argument("--academic", action="store_true",
                   help="Restrict results to academic domains "
                        "(arxiv.org, scholar.google.com, etc.)")
    p.add_argument("--discovered-for", default="intro",
                   help='Tag to attach to each candidate '
                        '(default "intro"). Use "related_work[2.1]" or '
                        'similar for cluster-specific queries so the '
                        'downstream citation_coverage gate can attribute '
                        'the citation to the right section.')
    p.add_argument("--raw", action="store_true",
                   help="Print the full Serply response JSON unmodified "
                        "instead of normalized candidates")
    args = p.parse_args()

    n = max(1, min(MAX_NUM, args.num_results))
    include_domains = ACADEMIC_DOMAINS if args.academic else None

    response = search(args.query, n, args.topic, include_domains)
    if not response.get("results"):
        print(f"WARN: Serply returned 0 results for query: {args.query!r}",
              file=sys.stderr)
        return 1

    if args.raw:
        json.dump(response, sys.stdout, indent=2, ensure_ascii=False)
    else:
        candidates = normalize(response, [args.discovered_for], n)
        json.dump({"candidates": candidates}, sys.stdout, indent=2,
                  ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
