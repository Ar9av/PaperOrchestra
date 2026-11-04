#!/usr/bin/env python3
"""
keenable_search.py — Optional Keenable (https://keenable.ai) backend for the
literature review agent's Phase 1 (parallel candidate discovery) step.

Keenable is a web search API that works WITHOUT an API key. It is OPTIONAL:
the literature-review-agent works fine with any host coding agent's native
web search tool. Use Keenable if:

  - Your host has no built-in web search (e.g., Aider, OpenCode, generic
    CLI agents) and you don't want to sign up for a key.
  - You're running the pipeline in batch / non-interactive mode and want
    a deterministic, scriptable backend.

With no KEENABLE_API_KEY set, the helper calls Keenable's keyless public
endpoint. If KEENABLE_API_KEY is set, it calls the keyed endpoint (higher
rate limits). This repo never commits a key.

Usage:
    python keenable_search.py --query "Sparse attention long context" --num-results 15
    python keenable_search.py --query "..." --raw                       # full JSON
    python keenable_search.py --query "..." --discovered-for "related_work[2.1]"

Default output: JSON candidates in the literature-review-agent format, ready
to be merged into raw_candidates.json before Phase 2 verification.

Exit codes:
    0  query succeeded
    1  HTTP error, network error, or empty results
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

KEENABLE_PUBLIC_ENDPOINT = "https://api.keenable.ai/v1/search/public"
KEENABLE_KEYED_ENDPOINT = "https://api.keenable.ai/v1/search"
DEFAULT_NUM = 10
MAX_NUM = 20
SNIPPET_CAP = 1500


def build_request(query: str, num_results: int,
                  api_key: str | None) -> urllib.request.Request:
    headers = {
        "Content-Type": "application/json",
        "X-Keenable-Title": "PaperOrchestra",
    }
    if api_key:
        headers["X-API-Key"] = api_key
        endpoint = KEENABLE_KEYED_ENDPOINT
    else:
        endpoint = KEENABLE_PUBLIC_ENDPOINT
    body = {"query": query, "max_results": num_results}
    return urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )


def search(query: str, num_results: int) -> dict:
    api_key = (os.environ.get("KEENABLE_API_KEY") or "").strip() or None
    req = build_request(query, num_results, api_key)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:500]
        print(f"ERROR: Keenable HTTP {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"ERROR: Keenable network error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def normalize(keenable_response: dict, discovered_for: list[str]) -> list[dict]:
    """Convert Keenable results into the literature-review-agent candidate format.

    Uses the result description when present, otherwise the page snippet
    truncated to SNIPPET_CAP characters. Results without a URL are dropped.
    """
    candidates: list[dict] = []
    for r in keenable_response.get("results", []):
        url = r.get("url") or ""
        if not url:
            continue
        snippet = (r.get("description") or "").strip()
        if not snippet:
            snippet = (r.get("snippet") or "").strip()[:SNIPPET_CAP]
        candidates.append({
            "title":          (r.get("title") or "").strip(),
            "snippet":        snippet,
            "source_url":     url,
            "discovered_for": list(discovered_for),
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
    p.add_argument("--discovered-for", default="intro",
                   help='Tag to attach to each candidate '
                        '(default "intro"). Use "related_work[2.1]" or '
                        'similar for cluster-specific queries so the '
                        'downstream citation_coverage gate can attribute '
                        'the citation to the right section.')
    p.add_argument("--raw", action="store_true",
                   help="Print the full Keenable response JSON unmodified "
                        "instead of normalized candidates")
    args = p.parse_args()

    n = max(1, min(MAX_NUM, args.num_results))
    response = search(args.query, n)
    if not response.get("results"):
        print(f"WARN: Keenable returned 0 results for query: {args.query!r}",
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
