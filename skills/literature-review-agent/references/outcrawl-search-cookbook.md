# Outcrawl Search Cookbook (optional Phase 1 backend)

[Outcrawl](https://outcrawl.ai) is web infrastructure for AI agents; its
search endpoint returns ranked web results (URL, title, snippet) as JSON
([API docs](https://outcrawl.ai/docs/search/overview)). The `literature-review-agent` can
use Outcrawl as an **OPTIONAL** backend for Phase 1 candidate discovery,
useful when your host coding agent has no native web search tool, or when
you want `site:` filters for research-focused queries.

> **Outcrawl is opt-in.** The literature-review-agent's default Phase 1
> path is "use your host agent's native web search tool" (`WebSearch` in
> Claude Code, `@web` in Cursor, the search tool in Antigravity, etc.).
> That requires zero configuration and no API key. Use Outcrawl only if
> you want to.

## Why use it

Outcrawl fills three gaps:

1. **Hosts with no built-in search.** Aider, OpenCode, and generic CLI
   agents often lack a native web search tool. Outcrawl gives them one.
2. **`site:` filters.** Search operators such as `site:` pass through, so
   the `--academic` flag restricts results to academic domains
   (arxiv.org, scholar.google.com, semanticscholar.org, aclanthology.org,
   openreview.net) for research-focused discovery.
3. **Batch / non-interactive runs.** When you want a deterministic,
   scriptable backend rather than going through the host agent's tool
   interface.

Outcrawl returns up to 20 results per call (the helper clamps to that
range), and each hit includes a `url`, `title`, `snippet`, and a `rank`
which the helper preserves as `_outcrawl_rank` for debugging.

## Get a key

1. Sign up at <https://outcrawl.ai>.
2. Copy your API key from the dashboard.
3. Set it in your environment:

   ```bash
   export OUTCRAWL_API_KEY="your-key-here"
   ```

   Or put it in a `.env` file (which is gitignored; the repo `.gitignore`
   blocks `*.env` and `.env*` patterns) and source it:

   ```bash
   set -a; source .env; set +a
   ```

**This repo never commits a key.** The helper reads `OUTCRAWL_API_KEY`
from the environment at runtime. The key is your responsibility to
provision and secure.

## Run the helper

```bash
python skills/literature-review-agent/scripts/outcrawl_search.py \
    --query "Sparse attention long context transformers" \
    --num-results 10 \
    --academic \
    --discovered-for "related_work[2.1]"
```

Output (default, normalized to the literature-review-agent candidate
format):

```json
{
  "candidates": [
    {
      "title": "[2504.17768] The Sparse Frontier: Sparse Attention Trade-offs in Transformer LLMs",
      "snippet": "Sparse attention offers a promising strategy to extend long-context capabilities in Transformer LLMs...",
      "source_url": "https://arxiv.org/abs/2504.17768",
      "discovered_for": ["related_work[2.1]"],
      "_outcrawl_rank": 3
    },
    ...
  ]
}
```

This JSON can be merged directly into `workspace/raw_candidates.json`
before the Phase 2 sequential verification step.

### Useful flags

| Flag | Default | Purpose |
|---|---|---|
| `--query` | (required) | Search query string |
| `--num-results` | `10` | 1-20; the helper clamps to this range |
| `--academic` | off | Restrict to academic domains (arxiv.org, scholar.google.com, etc.) |
| `--discovered-for` | `"intro"` | Tag attached to each candidate; use `"related_work[2.1]"` for cluster queries |
| `--raw` | off | Print the full Outcrawl response JSON instead of normalized candidates |

## Direct curl recipe

If you'd rather not use the Python helper (for one-off testing, or to
invoke from a host agent's `Bash` / `WebFetch` tool directly):

```bash
curl -X POST "https://api.outcrawl.ai/v1/search" \
  --header "Authorization: Bearer $OUTCRAWL_API_KEY" \
  --header "Content-Type: application/json" \
  --data '{"query": "PaperOrchestra automated paper writing (site:arxiv.org OR site:openreview.net)", "limit": 10}'
```

The `$OUTCRAWL_API_KEY` reference assumes the key is in your shell env.
**Do not** paste the literal key into the curl command in shell history
or chat; use the env var.

## Response shape

```json
{
  "hits": [
    {
      "url": "https://arxiv.org/abs/2604.05018",
      "title": "PaperOrchestra: A Multi-Agent Framework for ...",
      "snippet": "We present PaperOrchestra, a multi-agent framework...",
      "rank": 1
    }
  ],
  "usage": {"credits": "0.5"}
}
```

Errors come back as non-2xx HTTP statuses: 401 for an invalid key, 402
when the account is out of credits, and 429 when rate-limited.

## Mapping Outcrawl to the literature-review-agent candidate format

Phase 2 verification (Semantic Scholar fuzzy match, cutoff check, dedup)
expects candidates in this shape:

```json
{
  "title":          "...",
  "snippet":        "...",
  "source_url":     "...",
  "discovered_for": ["intro"]
}
```

`outcrawl_search.py` (the default mode) does this mapping:

| Outcrawl field | Candidate field |
|---|---|
| `hit.title` | `title` |
| `hit.url` | `source_url` |
| `hit.snippet` capped at 1500 chars | `snippet` |
| `--discovered-for` flag | `discovered_for` |
| `hit.rank` | `_outcrawl_rank` (preserved for debugging) |

Hits whose `url` is not an `http(s)` URL are dropped.

Phase 2 verification still goes through Semantic Scholar regardless of
whether the candidate came from Outcrawl, Serply, Tavily, Exa, or from the
host's native search. Outcrawl is ONLY a discovery backend; the
verification chain (`levenshtein_match.py`, `check_cutoff.py`,
`dedupe_by_id.py`, `bibtex_format.py`, `citation_coverage.py`) is
unchanged.

## Query patterns

Match the literature-review-agent's outline-driven query design. Run one
Outcrawl call per query, then merge all candidate lists:

| Query type | Source in `outline.json` | Example query | `--discovered-for` |
|---|---|---|---|
| Macro context | `introduction_strategy.search_directions[i]` | `"Survey of long-context attention mechanisms 2020-2024"` | `"intro"` |
| Foundational | same | `"Foundational papers transformer self-attention scaling laws"` | `"intro"` |
| SOTA scan | `related_work_strategy.subsections[i].sota_investigation_mission` | `"Recent SOTA sparse attention transformers 2024"` | `"related_work[2.1]"` |
| Limitation hunt | `related_work_strategy.subsections[i].limitation_search_queries[j]` | `"Block-sparse attention failure modes long sequences"` | `"related_work[2.1]"` |

For the related-work cluster queries, the `--discovered-for` tag matters:
the downstream `citation_coverage.py` gate uses it to attribute each
citation to the right cluster when reporting which papers were not yet
integrated.

**Tip:** Use `--academic` for the SOTA scan and limitation hunt queries
to keep results focused on research papers. For broad intro queries,
omitting `--academic` may yield useful surveys and blog posts that
reference foundational work.

## Cost and rate limits

Outcrawl has a free tier of 1,000 credits a month, and each response's
`usage.credits` field reports what that call used. See
<https://outcrawl.ai/pricing> for current plans. Each query is one
call, so a typical paper with ~15-20 search queries (3-5 intro queries +
10-15 related-work queries) is ~15-20 calls per full Lit Review Agent run.

The pipeline's wall-time floor is still set by Semantic Scholar's 1 QPS
verification limit, not by Outcrawl.

## Security

- **NEVER commit `OUTCRAWL_API_KEY` to git.** The repo's `.gitignore`
  blocks `.env`, `*.env`, and `secrets.json` patterns. Keep your key in
  your shell environment or your secrets manager (1Password CLI, op,
  doppler, etc.).
- The helper reads the key from the environment only. It does NOT accept
  the key as a command-line argument (which would expose it in shell
  history). It is sent in the `Authorization` header, never in the URL.
- Outcrawl sees the queries you send. Don't include sensitive draft text
  in queries.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ERROR: OUTCRAWL_API_KEY environment variable not set` | env var missing | `export OUTCRAWL_API_KEY="..."` |
| `ERROR: Outcrawl HTTP 401` | invalid or missing key | check your key at https://outcrawl.ai |
| `ERROR: Outcrawl HTTP 402` | out of credits | check your usage at https://outcrawl.ai |
| `ERROR: Outcrawl HTTP 429` | rate-limited | back off, lower concurrency |
| `WARN: Outcrawl returned 0 results` | query too narrow | broaden the query or remove `--academic` |
| `Outcrawl network error` | no internet, DNS issue | check your connection; the helper uses urllib stdlib only, no proxy support |

## When to prefer Outcrawl vs the host's native search

| Use case | Recommended backend |
|---|---|
| Claude Code, Cursor, Antigravity (have native web search) | host's native search (free, integrated) |
| Aider, OpenCode, generic CLI agents | Outcrawl, Serply, Tavily or Exa (gives them search) |
| Batch reproducible runs | Outcrawl, Serply, Tavily or Exa (deterministic backend) |
| Research-paper-heavy queries | Outcrawl (`--academic`), Exa (`category: "research paper"`), Tavily (`--academic`) or Serply (`--academic`) |
| One-off interactive runs | host's native search (less friction) |
