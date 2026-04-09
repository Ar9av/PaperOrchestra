# Exa Search Cookbook (optional Phase 1 backend)

[Exa](https://exa.ai) is a search engine optimized for finding academic
papers and other high-quality content. The `literature-review-agent` can
use Exa as an **OPTIONAL** backend for Phase 1 candidate discovery — useful
when your host coding agent has no native web search tool, or when you
want a research-paper-focused search backend with better signal-to-noise
than general web search.

> **Exa is opt-in.** The literature-review-agent's default Phase 1 path is
> "use your host agent's native web search tool" (`WebSearch` in Claude
> Code, `@web` in Cursor, the search tool in Antigravity, etc.). That
> requires zero configuration and no API key. Use Exa only if you want
> to.

## Why use it

Exa fills three gaps:

1. **Hosts with no built-in search.** Aider, OpenCode, and generic CLI
   agents often lack a native web search tool. Exa gives them one.
2. **Research-paper-focused results.** Exa's `category: "research paper"`
   filter returns higher signal-to-noise than general web search for
   academic queries. The example response (e.g., for the query
   "PaperOrchestra") returns arXiv pages, conference proceedings, and
   academic tools rather than general SEO content.
3. **Batch / non-interactive runs.** When you want a deterministic,
   scriptable backend rather than going through the host agent's tool
   interface.

Exa returns 10–20 results per call (the helper clamps to that range), and
each result includes a `title`, `url`, optional `publishedDate`, and a
list of `highlights` (snippets) which the helper joins into a `snippet`
field consumable by the rest of the Phase 1 pipeline.

## Get a key

1. Sign up at <https://dashboard.exa.ai/>.
2. Copy your API key (format: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`).
3. Set it in your environment:

   ```bash
   export EXA_API_KEY="paste-key-here"
   ```

   Or put it in a `.env` file (which is gitignored — the repo `.gitignore`
   blocks `*.env` and `.env*` patterns) and source it:

   ```bash
   set -a; source .env; set +a
   ```

**This repo never commits a key.** The helper reads `EXA_API_KEY` from the
environment at runtime. The key is your responsibility to provision and
secure.

## Run the helper

```bash
python skills/literature-review-agent/scripts/exa_search.py \
    --query "Sparse attention long context transformers" \
    --num-results 15 \
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
      "_exa_id": "https://arxiv.org/abs/2004.05150",
      "_exa_published_date": "2020-04-10T00:00:00.000Z"
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
| `--category` | `"research paper"` | Pass `""` to disable category filtering for broader results |
| `--highlight-chars` | `4000` | Max characters per highlight (Exa parameter) |
| `--discovered-for` | `"intro"` | Tag attached to each candidate; use `"related_work[2.1]"` for cluster queries |
| `--raw` | off | Print the full Exa response JSON instead of normalized candidates |

## Direct curl recipe

If you'd rather not use the Python helper (for one-off testing, or to
invoke from a host agent's `Bash` / `WebFetch` tool directly):

```bash
curl -X POST https://api.exa.ai/search \
  --header "content-type: application/json" \
  --header "x-api-key: $EXA_API_KEY" \
  --data '{
    "query": "PaperOrchestra automated paper writing",
    "category": "research paper",
    "numResults": 10,
    "type": "auto",
    "contents": {
      "highlights": {
        "maxCharacters": 4000
      }
    }
  }'
```

The `$EXA_API_KEY` reference assumes the key is in your shell env. **Do
not** paste the literal key into the curl command in shell history or
chat — use the env var.

## Response shape

```json
{
  "requestId": "52fcb70256224863b33f356fdae37c7f",
  "resolvedSearchType": "neural",
  "results": [
    {
      "id": "https://arxiv.org/abs/2604.05018",
      "title": "PaperOrchestra: A Multi-Agent Framework for ...",
      "url": "https://arxiv.org/abs/2604.05018",
      "publishedDate": "2026-04-06T00:00:00.000Z",
      "highlights": ["...", "..."],
      "highlightScores": [0.4, 0.3],
      "image": "https://...",
      "favicon": "https://..."
    }
  ],
  "searchTime": 975.2,
  "costDollars": {
    "total":  0.007,
    "search": {"neural": 0.007}
  }
}
```

## Mapping Exa → literature-review-agent candidate format

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

`exa_search.py --normalize` (the default mode) does this mapping:

| Exa field | Candidate field |
|---|---|
| `result.title` | `title` |
| `result.url` (fallback `result.id`) | `source_url` |
| `result.highlights` joined and capped at 1500 chars | `snippet` |
| `--discovered-for` flag | `discovered_for` |
| `result.id` | `_exa_id` (preserved for debugging) |
| `result.publishedDate` | `_exa_published_date` (preserved for tie-breaking) |

Phase 2 verification still goes through Semantic Scholar regardless of
whether the candidate came from Exa or from the host's native search.
Exa is ONLY a discovery backend; the verification chain
(`levenshtein_match.py` → `check_cutoff.py` → `dedupe_by_id.py` →
`bibtex_format.py` → `citation_coverage.py`) is unchanged.

## Query patterns

Match the literature-review-agent's outline-driven query design. Run one
Exa call per query, then merge all candidate lists:

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

## Cost and rate limits

Exa pricing is per-query (~$0.007 per neural search at the time of
writing). For a typical paper with ~15-20 search queries (3-5 intro
queries + 10-15 related-work queries), one full Lit Review Agent run
costs ~$0.10-$0.15. Check <https://exa.ai/pricing> for current rates.

Exa's rate limits are generous; the paper's 10-worker parallel discovery
pattern is well within them. The pipeline's wall-time floor is still set
by Semantic Scholar's 1 QPS verification limit, not by Exa.

## Security

- **NEVER commit `EXA_API_KEY` to git.** The repo's `.gitignore` blocks
  `.env`, `*.env`, and `secrets.json` patterns. Keep your key in your
  shell environment or your secrets manager (1Password CLI, op, doppler,
  etc.).
- The helper reads the key from the environment only. It does NOT accept
  the key as a command-line argument (which would expose it in shell
  history).
- Exa logs requests for billing and quality. Assume your queries are not
  private to Exa themselves. Don't include sensitive draft text in
  queries.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ERROR: EXA_API_KEY environment variable not set` | env var missing | `export EXA_API_KEY="..."` |
| `ERROR: Exa HTTP 401` | invalid or expired key | check the dashboard for the current key |
| `ERROR: Exa HTTP 429` | rate-limited | back off, lower concurrency |
| `WARN: Exa returned 0 results` | query too narrow or odd category | broaden the query or try `--category ""` |
| `Exa network error` | no internet, DNS issue | check your connection; the helper uses urllib stdlib only, no proxy support |

## When to prefer Exa vs the host's native search

| Use case | Recommended backend |
|---|---|
| Claude Code, Cursor, Antigravity (have native web search) | host's native search (free, integrated) |
| Aider, OpenCode, generic CLI agents | Exa (gives them search) |
| Batch reproducible runs | Exa (deterministic backend) |
| Research-paper-heavy queries | Exa (better academic signal) |
| One-off interactive runs | host's native search (less friction) |

You can also mix: use the host's web search for the broad intro queries
and Exa for the narrow limitation-search queries where the
research-paper-category filter helps the most.
