#!/usr/bin/env python3
"""
tavily_search.py — Optional Tavily (https://tavily.com) backend for the
literature review agent's Phase 1 (parallel candidate discovery) step.

Tavily is a search API designed for LLMs, enabling AI applications to
access real-time web data. It is OPTIONAL — the literature-review-agent
works fine with any host coding agent's native web search tool. Use
Tavily only if:

  - Your host has no built-in web search (e.g., Aider, OpenCode, generic
    CLI agents).
  - You want an LLM-optimized search backend with high relevance scoring.
  - You're running the pipeline in batch / non-interactive mode and want
    a deterministic, scriptable backend.

This helper reads TAVILY_API_KEY from the environment. The key is YOUR
responsibility to provide; this repo never commits one. Get a key at
https://app.tavily.com (1,000 free credits/month).

Usage:
    export TAVILY_API_KEY="tvly-your-key-here"
    python tavily_search.py --query "Sparse attention long context" --num-results 15
    python tavily_search.py --query "..." --raw                       # full JSON
    python tavily_search.py --query "..." --discovered-for "related_work[2.1]"

Default output: JSON candidates in the literature-review-agent format, ready
to be merged into raw_candidates.json before Phase 2 verification.

Exit codes:
    0  query succeeded
    1  TAVILY_API_KEY missing, HTTP error, network error, or empty results
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

TAVILY_ENDPOINT = "https://api.tavily.com/search"
DEFAULT_NUM = 10
MAX_NUM = 20
SNIPPET_CAP = 1500

# Academic domains to boost research-paper results
ACADEMIC_DOMAINS = [
    "arxiv.org",
    "scholar.google.com",
    "semanticscholar.org",
    "aclanthology.org",
    "openreview.net",
]


def search(query: str, num_results: int, topic: str,
           include_domains: list[str] | None) -> dict:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        print(
            "ERROR: TAVILY_API_KEY environment variable not set.\n"
            "Get a key at https://app.tavily.com and run:\n"
            '  export TAVILY_API_KEY="tvly-your-key-here"\n'
            "Then retry. The literature-review-agent also works without\n"
            "Tavily — see references/discovery-pipeline.md for the default\n"
            "host-native web search path.",
            file=sys.stderr,
        )
        sys.exit(1)

    body: dict = {
        "query":        query,
        "max_results":  num_results,
        "search_depth": "advanced",
        "topic":        topic,
    }
    if include_domains:
        body["include_domains"] = include_domains

    req = urllib.request.Request(
        TAVILY_ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:500]
        print(f"ERROR: Tavily HTTP {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"ERROR: Tavily network error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def normalize(tavily_response: dict, discovered_for: list[str]) -> list[dict]:
    """Convert Tavily results into the literature-review-agent candidate format."""
    candidates: list[dict] = []
    for r in tavily_response.get("results", []):
        title = (r.get("title") or "").strip()
        url = r.get("url") or ""
        content = (r.get("content") or "").strip()
        snippet = content[:SNIPPET_CAP]
        candidates.append({
            "title":          title,
            "snippet":        snippet,
            "source_url":     url,
            "discovered_for": list(discovered_for),
            "_tavily_score":  r.get("score"),
        })
    return candidates


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
                   help='Tavily topic filter (default "general"; '
                        'use "news" for recent results)')
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
                   help="Print the full Tavily response JSON unmodified "
                        "instead of normalized candidates")
    args = p.parse_args()

    n = max(1, min(MAX_NUM, args.num_results))
    include_domains = ACADEMIC_DOMAINS if args.academic else None

    response = search(args.query, n, args.topic, include_domains)
    if not response.get("results"):
        print(f"WARN: Tavily returned 0 results for query: {args.query!r}",
              file=sys.stderr)
        return 1

    if args.raw:
        json.dump(response, sys.stdout, indent=2, ensure_ascii=False)
    else:
        candidates = normalize(response, [args.discovered_for])
        json.dump({"candidates": candidates}, sys.stdout, indent=2,
                  ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
