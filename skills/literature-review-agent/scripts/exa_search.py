#!/usr/bin/env python3
"""
exa_search.py — Optional Exa (https://exa.ai) backend for the literature
review agent's Phase 1 (parallel candidate discovery) step.

Exa is a search engine optimized for finding academic papers and other
high-quality content. It is OPTIONAL — the literature-review-agent works
fine with any host coding agent's native web search tool. Use Exa only if:

  - Your host has no built-in web search (e.g., Aider, OpenCode, generic
    CLI agents).
  - You want a research-paper-focused search backend with better
    signal-to-noise than general web search.
  - You're running the pipeline in batch / non-interactive mode and want
    a deterministic, scriptable backend.

This helper reads EXA_API_KEY from the environment. The key is YOUR
responsibility to provide; this repo never commits one. Get a key at
https://dashboard.exa.ai/.

Usage:
    export EXA_API_KEY="your-key-here"
    python exa_search.py --query "Sparse attention long context" --num-results 15
    python exa_search.py --query "..." --raw                       # full JSON
    python exa_search.py --query "..." --discovered-for "related_work[2.1]"

Default output: JSON candidates in the literature-review-agent format, ready
to be merged into raw_candidates.json before Phase 2 verification.

Exit codes:
    0  query succeeded
    1  EXA_API_KEY missing, HTTP error, network error, or empty results
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

EXA_ENDPOINT = "https://api.exa.ai/search"
DEFAULT_NUM = 10
MAX_NUM = 20      # the user explicitly asked for a 10-20 range
SNIPPET_CAP = 1500


def search(query: str, num_results: int, category: str | None,
           highlight_max_chars: int) -> dict:
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        print(
            "ERROR: EXA_API_KEY environment variable not set.\n"
            "Get a key at https://dashboard.exa.ai/ and run:\n"
            '  export EXA_API_KEY="your-key-here"\n'
            "Then retry. The literature-review-agent also works without\n"
            "Exa — see references/discovery-pipeline.md for the default\n"
            "host-native web search path.",
            file=sys.stderr,
        )
        sys.exit(1)

    body: dict = {
        "query":      query,
        "numResults": num_results,
        "type":       "auto",
        "contents":   {"highlights": {"maxCharacters": highlight_max_chars}},
    }
    if category:
        body["category"] = category

    req = urllib.request.Request(
        EXA_ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key":    api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:500]
        print(f"ERROR: Exa HTTP {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"ERROR: Exa network error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def normalize(exa_response: dict, discovered_for: list[str]) -> list[dict]:
    """Convert Exa results into the literature-review-agent candidate format."""
    candidates: list[dict] = []
    for r in exa_response.get("results", []):
        title = (r.get("title") or "").strip()
        url = r.get("url") or r.get("id") or ""
        highlights = r.get("highlights") or []
        snippet = " ".join(h.strip() for h in highlights)[:SNIPPET_CAP]
        candidates.append({
            "title":          title,
            "snippet":        snippet,
            "source_url":     url,
            "discovered_for": list(discovered_for),
            "_exa_id":             r.get("id"),
            "_exa_published_date": r.get("publishedDate"),
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
    p.add_argument("--category", default="research paper",
                   help='Exa category filter (default "research paper"; '
                        'pass an empty string to disable)')
    p.add_argument("--highlight-chars", type=int, default=4000,
                   help="Max characters per highlight (default 4000)")
    p.add_argument("--discovered-for", default="intro",
                   help='Tag to attach to each candidate '
                        '(default "intro"). Use "related_work[2.1]" or '
                        'similar for cluster-specific queries so the '
                        'downstream citation_coverage gate can attribute '
                        'the citation to the right section.')
    p.add_argument("--raw", action="store_true",
                   help="Print the full Exa response JSON unmodified "
                        "instead of normalized candidates")
    args = p.parse_args()

    n = max(1, min(MAX_NUM, args.num_results))
    category = args.category or None

    response = search(args.query, n, category, args.highlight_chars)
    if not response.get("results"):
        print(f"WARN: Exa returned 0 results for query: {args.query!r}",
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
