# Tavily Search Cookbook (optional Phase 1 backend)

[Tavily](https://tavily.com) is a search API designed for LLMs, enabling
AI applications to access real-time web data with high relevance scoring.
The `literature-review-agent` can use Tavily as an **OPTIONAL** backend
for Phase 1 candidate discovery — useful when your host coding agent has
no native web search tool, or when you want an LLM-optimized search
backend.

> **Tavily is opt-in.** The literature-review-agent's default Phase 1
> path is "use your host agent's native web search tool" (`WebSearch` in
> Claude Code, `@web` in Cursor, the search tool in Antigravity, etc.).
> That requires zero configuration and no API key. Use Tavily only if
> you want to.

## Why use it

Tavily fills three gaps:

1. **Hosts with no built-in search.** Aider, OpenCode, and generic CLI
   agents often lack a native web search tool. Tavily gives them one.
2. **LLM-optimized relevance.** Tavily's `search_depth: "advanced"`
   mode returns higher relevance results for complex queries. The
   `--academic` flag restricts results to academic domains (arxiv.org,
   scholar.google.com, semanticscholar.org, aclanthology.org,
   openreview.net) for research-focused discovery.
3. **Batch / non-interactive runs.** When you want a deterministic,
   scriptable backend rather than going through the host agent's tool
   interface.

Tavily returns up to 20 results per call (the helper clamps to that
range), and each result includes a `title`, `url`, `content` (snippet),
and a relevance `score` which the helper preserves as `_tavily_score`
for debugging.

## Get a key

1. Sign up at <https://app.tavily.com>.
2. Copy your API key (format: `tvly-xxxxxxxxxxxxxxxxxxxxxxxx`).
3. Set it in your environment:

   ```bash
   export TAVILY_API_KEY="tvly-your-key-here"
   ```

   Or put it in a `.env` file (which is gitignored — the repo `.gitignore`
   blocks `*.env` and `.env*` patterns) and source it:

   ```bash
   set -a; source .env; set +a
   ```

**This repo never commits a key.** The helper reads `TAVILY_API_KEY` from
the environment at runtime. The key is your responsibility to provision
and secure.

## Run the helper

```bash
python skills/literature-review-agent/scripts/tavily_search.py \
    --query "Sparse attention long context transformers" \
    --num-results 15 \
    --academic \
    --discovered-for "related_work[2.1]"
```

Output (default — normalized to the literature-review-agent candidate
format):

```json
{
  "candidates": [
    {
      "title": "Longformer: The Long-Document Transformer",
      "snippet": "We present the Longformer, a self-attention mechanism that scales linearly with sequence length...",
      "source_url": "https://arxiv.org/abs/2004.05150",
      "discovered_for": ["related_work[2.1]"],
      "_tavily_score": 0.92
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
| `--num-results` | `10` | 1–20; the helper clamps to this range |
| `--topic` | `"general"` | `"general"` or `"news"`; use `"news"` for recent results |
| `--academic` | off | Restrict to academic domains (arxiv.org, scholar.google.com, etc.) |
| `--discovered-for` | `"intro"` | Tag attached to each candidate; use `"related_work[2.1]"` for cluster queries |
| `--raw` | off | Print the full Tavily response JSON instead of normalized candidates |

## Direct curl recipe

If you'd rather not use the Python helper (for one-off testing, or to
invoke from a host agent's `Bash` / `WebFetch` tool directly):

```bash
curl -X POST https://api.tavily.com/search \
  --header "Content-Type: application/json" \
  --header "Authorization: Bearer $TAVILY_API_KEY" \
  --data '{
    "query": "PaperOrchestra automated paper writing",
    "max_results": 10,
    "search_depth": "advanced",
    "topic": "general",
    "include_domains": ["arxiv.org", "scholar.google.com"]
  }'
```

The `$TAVILY_API_KEY` reference assumes the key is in your shell env.
**Do not** paste the literal key into the curl command in shell history
or chat — use the env var.

## Response shape

```json
{
  "query": "PaperOrchestra automated paper writing",
  "results": [
    {
      "title": "PaperOrchestra: A Multi-Agent Framework for ...",
      "url": "https://arxiv.org/abs/2604.05018",
      "content": "We present PaperOrchestra, a multi-agent framework...",
      "score": 0.95
    }
  ]
}
```

## Mapping Tavily → literature-review-agent candidate format

Phase 2 verification (Semantic Scholar fuzzy match → cutoff check → dedup)
expects candidates in this shape:

```json
{
  "title":          "...",
  "snippet":        "...",
  "source_url":     "...",
  "discovered_for": ["intro"]
}
```

`tavily_search.py` (the default mode) does this mapping:

| Tavily field | Candidate field |
|---|---|
| `result.title` | `title` |
| `result.url` | `source_url` |
| `result.content` capped at 1500 chars | `snippet` |
| `--discovered-for` flag | `discovered_for` |
| `result.score` | `_tavily_score` (preserved for debugging) |

Phase 2 verification still goes through Semantic Scholar regardless of
whether the candidate came from Tavily, Exa, or from the host's native
search. Tavily is ONLY a discovery backend; the verification chain
(`levenshtein_match.py` → `check_cutoff.py` → `dedupe_by_id.py` →
`bibtex_format.py` → `citation_coverage.py`) is unchanged.

## Query patterns

Match the literature-review-agent's outline-driven query design. Run one
Tavily call per query, then merge all candidate lists:

| Query type | Source in `outline.json` | Example query | `--discovered-for` |
|---|---|---|---|
| Macro context | `introduction_strategy.search_directions[i]` | `"Survey of long-context attention mechanisms 2020-2024"` | `"intro"` |
| Foundational | same | `"Foundational papers transformer self-attention scaling laws"` | `"intro"` |
| SOTA scan | `related_work_strategy.subsections[i].sota_investigation_mission` | `"Recent SOTA sparse attention transformers 2024"` | `"related_work[2.1]"` |
| Limitation hunt | `related_work_strategy.subsections[i].limitation_search_queries[j]` | `"Block-sparse attention failure modes long sequences"` | `"related_work[2.1]"` |

For the related-work cluster queries, the `--discovered-for` tag matters
— the downstream `citation_coverage.py` gate uses it to attribute each
citation to the right cluster when reporting which papers were not yet
integrated.

**Tip:** Use `--academic` for the SOTA scan and limitation hunt queries
to keep results focused on research papers. For broad intro queries,
omitting `--academic` may yield useful surveys and blog posts that
reference foundational work.

## Cost and rate limits

Tavily offers 1,000 free API credits per month (no credit card
required). The `search_depth: "advanced"` mode used by the helper costs
2 credits per query. For a typical paper with ~15-20 search queries
(3-5 intro queries + 10-15 related-work queries), one full Lit Review
Agent run costs ~30-40 credits — well within the free tier.

For higher volumes, see <https://tavily.com/pricing> for paid plans.
Tavily's rate limits are generous; the paper's 10-worker parallel
discovery pattern is well within them. The pipeline's wall-time floor is
still set by Semantic Scholar's 1 QPS verification limit, not by Tavily.

## SDK alternative

If `tavily-python` is installed (`pip install tavily-python`), you can
use the SDK directly instead of the bundled helper:

```python
from tavily import TavilyClient

client = TavilyClient()  # reads TAVILY_API_KEY from env
response = client.search(
    query="Sparse attention long context transformers",
    max_results=15,
    search_depth="advanced",
    include_domains=["arxiv.org", "scholar.google.com"],
)
```

The bundled `tavily_search.py` helper uses stdlib `urllib` only (like
`exa_search.py`) to avoid mandatory dependencies. The SDK is optional.

## Security

- **NEVER commit `TAVILY_API_KEY` to git.** The repo's `.gitignore`
  blocks `.env`, `*.env`, and `secrets.json` patterns. Keep your key in
  your shell environment or your secrets manager (1Password CLI, op,
  doppler, etc.).
- The helper reads the key from the environment only. It does NOT accept
  the key as a command-line argument (which would expose it in shell
  history).
- Tavily logs requests for billing and quality. Assume your queries are
  not private to Tavily themselves. Don't include sensitive draft text
  in queries.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ERROR: TAVILY_API_KEY environment variable not set` | env var missing | `export TAVILY_API_KEY="tvly-..."` |
| `ERROR: Tavily HTTP 401` | invalid or expired key | check your key at https://app.tavily.com |
| `ERROR: Tavily HTTP 429` | rate-limited | back off, lower concurrency |
| `WARN: Tavily returned 0 results` | query too narrow | broaden the query or remove `--academic` |
| `Tavily network error` | no internet, DNS issue | check your connection; the helper uses urllib stdlib only, no proxy support |

## When to prefer Tavily vs Exa vs the host's native search

| Use case | Recommended backend |
|---|---|
| Claude Code, Cursor, Antigravity (have native web search) | host's native search (free, integrated) |
| Aider, OpenCode, generic CLI agents | Tavily or Exa (gives them search) |
| Batch reproducible runs | Tavily or Exa (deterministic backend) |
| Research-paper-heavy queries | Exa (`category: "research paper"`) or Tavily (`--academic`) |
| Free tier / budget-conscious | Tavily (1,000 free credits/month) |
| LLM-optimized relevance scoring | Tavily (`search_depth: "advanced"`) |
| One-off interactive runs | host's native search (less friction) |

You can also mix: use the host's web search for the broad intro queries,
Exa for the narrow limitation-search queries where the research-paper
category filter helps the most, and Tavily for SOTA scan queries where
LLM-optimized relevance scoring shines.
