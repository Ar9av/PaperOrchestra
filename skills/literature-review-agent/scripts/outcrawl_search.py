#!/usr/bin/env python3
"""
outcrawl_search.py: Optional Outcrawl (https://outcrawl.ai) backend for the
literature review agent's Phase 1 (parallel candidate discovery) step.

Outcrawl is web infrastructure for AI agents; its search endpoint returns
ranked web results (URL, title, snippet) as JSON. It is OPTIONAL: the
literature-review-agent works fine with any host coding agent's native web
search tool. Use Outcrawl only if:

  - Your host has no built-in web search (e.g., Aider, OpenCode, generic
    CLI agents).
  - You want `site:` filters for research-focused discovery.
  - You're running the pipeline in batch / non-interactive mode and want
    a deterministic, scriptable backend.

This helper reads OUTCRAWL_API_KEY from the environment. The key is YOUR
responsibility to provide; this repo never commits one. Get a key at
https://outcrawl.ai (docs: https://outcrawl.ai/docs/search/overview; the free tier includes
1,000 credits a month).

Usage:
    export OUTCRAWL_API_KEY="your-key-here"
    python outcrawl_search.py --query "Sparse attention long context" --num-results 10
    python outcrawl_search.py --query "..." --raw                       # full JSON
    python outcrawl_search.py --query "..." --discovered-for "related_work[2.1]"

Default output: JSON candidates in the literature-review-agent format, ready
to be merged into raw_candidates.json before Phase 2 verification.

Exit codes:
    0  query succeeded
    1  OUTCRAWL_API_KEY missing, HTTP error, network error, or empty results
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

OUTCRAWL_ENDPOINT = "https://api.outcrawl.ai/v1/search"
USER_AGENT = "PaperOrchestra"
DEFAULT_NUM = 10
MAX_NUM = 20  # Outcrawl accepts a limit of 1-20 results per call
SNIPPET_CAP = 1500

# Academic domains to boost research-paper results (applied as site: operators)
ACADEMIC_DOMAINS = [
    "arxiv.org",
    "scholar.google.com",
    "semanticscholar.org",
    "aclanthology.org",
    "openreview.net",
]


def build_query(query: str, include_domains: list[str] | None) -> str:
    if not include_domains:
        return query
    return query + " (" + " OR ".join(f"site:{d}" for d in include_domains) + ")"


def search(query: str, num_results: int,
           include_domains: list[str] | None) -> dict:
    api_key = os.environ.get("OUTCRAWL_API_KEY")
    if not api_key:
        print(
            "ERROR: OUTCRAWL_API_KEY environment variable not set.\n"
            "Get a key at https://outcrawl.ai and run:\n"
            '  export OUTCRAWL_API_KEY="your-key-here"\n'
            "Then retry. The literature-review-agent also works without\n"
            "Outcrawl; see references/discovery-pipeline.md for the default\n"
            "host-native web search path.",
            file=sys.stderr,
        )
        sys.exit(1)

    body = {
        "query": build_query(query, include_domains),
        "limit": num_results,
    }
    req = urllib.request.Request(
        OUTCRAWL_ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # api.outcrawl.ai rejects the default Python-urllib user agent.
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:500]
        print(f"ERROR: Outcrawl HTTP {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"ERROR: Outcrawl network error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def normalize(outcrawl_response: dict, discovered_for: list[str],
              limit: int) -> list[dict]:
    """Convert Outcrawl hits into the literature-review-agent candidate format."""
    candidates: list[dict] = []
    for r in outcrawl_response.get("hits", []):
        url = r.get("url") or ""
        if not url.startswith(("http://", "https://")):
            continue
        title = (r.get("title") or "").strip()
        content = (r.get("snippet") or "").strip()
        snippet = content[:SNIPPET_CAP]
        candidates.append({
            "title":          title,
            "snippet":        snippet,
            "source_url":     url,
            "discovered_for": list(discovered_for),
            "_outcrawl_rank": r.get("rank"),
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
                   help="Print the full Outcrawl response JSON unmodified "
                        "instead of normalized candidates")
    args = p.parse_args()

    n = max(1, min(MAX_NUM, args.num_results))
    include_domains = ACADEMIC_DOMAINS if args.academic else None

    response = search(args.query, n, include_domains)
    if not response.get("hits"):
        print(f"WARN: Outcrawl returned 0 results for query: {args.query!r}",
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
