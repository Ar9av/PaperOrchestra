# Host Integration Guide

How to run the paper-orchestra skill pack under different coding agents.
**No API keys are required for any of these.** Each host uses its own native
tools (LLM, web search, fetch, bash, file I/O) to execute the skills.

## What the host needs to provide

Every host agent must have, at minimum:

| Capability | Used by |
|---|---|
| LLM reasoning (its own model) | All 5 agent skills |
| File read/write | All skills |
| Bash / shell execution | Deterministic scripts, LaTeX compile |
| Web search tool | Literature Review Agent (Step 3 candidate discovery) |
| URL fetch tool | Literature Review Agent (Semantic Scholar verification) |
| Vision input (optional) | Plotting Agent VLM critique loop, Section Writing multimodal call |

If the host lacks vision input, the Plotting Agent skips the critique loop and
the Section Writing Agent works text-only (with reduced figure-grounded
reasoning quality — see `paper-fidelity.md`).

If the host lacks web search, the Literature Review Agent runs in degraded
mode: it uses only any user-provided BibTeX in `workspace/inputs/` and emits
a TODO marker if Intro/Related Work cannot be cited.

---

## Claude Code

1. Symlink the skills:
   ```bash
   mkdir -p ~/.claude/skills
   for s in paper-orchestra outline-agent plotting-agent literature-review-agent \
            section-writing-agent content-refinement-agent paper-writing-bench \
            paper-autoraters claim-evidence-audit; do
     ln -sf ~/paper-orchestra/skills/$s ~/.claude/skills/$s
   done
   ```
2. Start a session in your project root.
3. Scaffold a workspace and drop your inputs:
   ```
   ! python ~/paper-orchestra/skills/paper-orchestra/scripts/init_workspace.py --out workspace/
   ```
4. Ask Claude:
   > Run the paper-orchestra pipeline on `./workspace`.

   Claude will detect the trigger phrase, load `paper-orchestra/SKILL.md`,
   and follow it step by step. Steps 2 and 3 are run in parallel via Claude
   Code's `Agent` tool — Claude spawns two concurrent sub-agents (one with
   `subagent_type=general-purpose` reading `plotting-agent/SKILL.md`, one
   reading `literature-review-agent/SKILL.md`).

5. Web search uses Claude Code's `WebSearch` tool. Semantic Scholar fetches
   use `WebFetch` against `https://api.semanticscholar.org/graph/v1/paper/...`
   (public, no key required).

6. LaTeX compilation uses Claude Code's `Bash` tool: `latexmk -pdf`.

---

## Cursor

1. Drop the skill markdown files into `.cursor/rules/`:
   ```bash
   mkdir -p .cursor/rules
   cp -r ~/paper-orchestra/skills/*/SKILL.md .cursor/rules/
   ```
2. Use `@SKILL.md` references in your prompts, or just paste the trigger
   phrase: "Run paper-orchestra on this workspace."
3. Cursor's web search (`@web`) handles Step 3 candidate discovery. Its
   browser tool fetches `api.semanticscholar.org` URLs.
4. Cursor's parallel agents (Agent panel) run Steps 2 and 3 concurrently when
   you split them into two tasks.

---

## Google Antigravity

1. Antigravity has a worker pool. Configure two workers to run the plotting
   and literature review steps in parallel.
2. Each worker reads the corresponding `SKILL.md` from
   `~/paper-orchestra/skills/`.
3. Antigravity's built-in search and fetch tools handle Step 3 networking;
   no API key configuration needed.
4. Final compile via Antigravity's shell runner.

---

## Cline (VS Code extension)

1. Add the skills to Cline's custom instructions or as project-level docs.
2. Cline reads `SKILL.md` files via the file tool.
3. Web search and fetch are provided by Cline's built-in browser/search tools.
4. Steps 2 and 3 run sequentially (Cline does not yet support parallel
   sub-agents) — start with Step 3 since it's slower.

---

## Aider

1. Aider is text-only and lacks built-in web search or vision. Use the
   degraded mode: provide a pre-built BibTeX in `workspace/inputs/refs.bib`
   and run only the Outline → Section Writing → Content Refinement steps.
2. Aider's `/run` command executes the deterministic scripts.
3. The Plotting Agent's VLM critique loop is skipped; figures are rendered
   once with no refinement.

---

## OpenCode / generic CLI agent

1. Any agent that can read files, run shell commands, and call an LLM can
   execute this pipeline. The skills are just markdown.
2. The minimum integration is: `cat skills/paper-orchestra/SKILL.md` into the
   system prompt, then let the agent take over.

---

## Known issues and workarounds

### LaTeX compilation: figures appearing between references

The most common final-layout defect is figures floating into or after the
References section. This happens when the Experiments section has many floats
and LaTeX cannot place them all before `\bibliography{}`.

**Fix (already encoded in `section-writing-agent/SKILL.md`)**: the Section
Writing Agent must emit `\clearpage` immediately before `\bibliographystyle{...}`.
If you encounter this in a compiled PDF, edit `workspace/final/paper.tex`
and add `\clearpage` before the bibliography line, then recompile.

### LaTeX compilation: missing style files on basic TeX installations

The NeurIPS 2024 template requires packages (`nicefrac`, `microtype`,
`cleveref`, and the T1/Courier fonts via `\usepackage[T1]{fontenc}`) that are
not included in minimal TeX Live distributions (e.g., `texlive-2025-basic`
on macOS). If compilation fails with `File '*.sty' not found`:

1. Install the full TeX Live scheme: `tlmgr install scheme-full` (requires
   admin), or install individual packages: `tlmgr install cleveref nicefrac
   microtype`.
2. Alternatively, comment out the missing packages and replace:
   - `\cref{fig:X}` → `Figure~\ref{fig:X}`
   - `\cref{tab:Y}` → `Table~\ref{tab:Y}`
   - `\texttt{...}` uses courier; if courier is missing, use `\textit{...}`
   - Remove `\usepackage[T1]{fontenc}` and `\usepackage{url}` if Courier
     TFM files are absent (symptom: `pcrr7t not loadable`).

### citation_pool.json key format mismatch

The Literature Review Agent may generate citation keys in its own format (e.g.,
`lewis2020rag`) while `bibtex_format.py` generates canonical keys from author +
year + first title word (e.g., `lewis2020retrievalaugmented`). Running
`bibtex_format.py` after the Lit Review Agent will update the keys in the pool,
but the already-written `intro_relwork.tex` and `refs.bib` will still use the
old keys, causing citation coverage gate failures.

**Fix**: after running `bibtex_format.py --pool ... --out ...`, run a key
substitution pass over `intro_relwork.tex`:

```python
import json
with open('workspace/citation_pool.json') as f:
    pool = json.load(f)
key_map = {p['key']: p['bibtex_key'] for p in pool['papers']}
with open('workspace/drafts/intro_relwork.tex') as f:
    content = f.read()
for old, new in key_map.items():
    content = content.replace('{' + old + '}', '{' + new + '}')
with open('workspace/drafts/intro_relwork.tex', 'w') as f:
    f.write(content)
```

Then rebuild `refs.bib` from the pool's `bibtex_key` fields before running
the Section Writing Agent.

### authors format in citation_pool.json

If the Literature Review Agent writes authors as plain strings
(`"authors": ["Alice Smith", "Bob Jones"]`), but `bibtex_format.py` expects
dicts (`{"name": "Alice Smith"}`), bibtex_format.py will raise `AttributeError`.
Fix by running a normalisation pass before `bibtex_format.py`:

```python
for p in pool['papers']:
    if p.get('authors') and isinstance(p['authors'][0], str):
        p['authors'] = [{'name': a} for a in p['authors']]
```

---

## Verifying your host integration

Run the smoke test on the bundled example:

```bash
cd ~/paper-orchestra
python skills/paper-orchestra/scripts/init_workspace.py --out /tmp/po-test/
cp examples/minimal/inputs/* /tmp/po-test/inputs/
python skills/paper-orchestra/scripts/validate_inputs.py --workspace /tmp/po-test/
```

Then ask your host agent to run the pipeline on `/tmp/po-test/`. A
successful run should produce `/tmp/po-test/final/paper.pdf` after ~15-40
minutes (host-dependent).
