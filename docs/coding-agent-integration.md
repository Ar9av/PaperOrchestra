# Coding Agent Integration

Per-host setup for the paper-orchestra skill pack. **No API keys are
required for any host.** Each host uses its own native LLM, web search,
fetch, bash, and file tools.

For a higher-level overview see
`skills/paper-orchestra/references/host-integration.md`. This document is
the longer how-to.

## Capability matrix

| Capability | Required? | Used by |
|---|---|---|
| LLM reasoning | required | all 5 agent skills |
| File read/write | required | all skills |
| Bash / shell | required | deterministic scripts, latexmk |
| Web search | recommended | literature-review-agent (Step 3 discovery) |
| URL fetch | recommended | literature-review-agent (Semantic Scholar) |
| Vision input | recommended | plotting-agent VLM critique, section-writing-agent multimodal call |
| Parallel sub-agents | optional | plotting-agent ‖ literature-review-agent |

If web search is missing → degraded mode (use only pre-supplied refs.bib).
If vision is missing → text-only mode (no figure refinement, weaker
section writing).
If parallel sub-agents are missing → run sequentially (Step 3 first).

## Claude Code

### Install

```bash
git clone https://github.com/<you>/paper-orchestra ~/paper-orchestra
cd ~/paper-orchestra
pip install -r requirements.txt

# Symlink skills into Claude Code's skill dir
mkdir -p ~/.claude/skills
for s in paper-orchestra outline-agent plotting-agent literature-review-agent \
         section-writing-agent content-refinement-agent paper-writing-bench \
         paper-autoraters claim-evidence-audit; do
  ln -sf ~/paper-orchestra/skills/$s ~/.claude/skills/$s
done
```

### Run

```bash
# scaffold a workspace
python ~/paper-orchestra/skills/paper-orchestra/scripts/init_workspace.py \
    --out workspace/

# drop your inputs into workspace/inputs/
# (idea.md, experimental_log.md, template.tex, conference_guidelines.md)

# launch claude in your project root
claude
```

Then ask:

> Run the paper-orchestra pipeline on `./workspace`.

### Tool mapping

| Pipeline need | Claude Code tool |
|---|---|
| LLM | Claude itself |
| File I/O | `Read`, `Write`, `Edit` |
| Bash / latexmk | `Bash` |
| Web search (Step 3) | `WebSearch` |
| URL fetch (Semantic Scholar) | `WebFetch` |
| Vision (figures) | Claude's native image input via `Read` on PNG files |
| Parallel sub-agents | `Agent` tool with multiple concurrent calls |

### Tip

For Steps 2 ∥ 3, send a single message with two `Agent` tool calls in
parallel, one with `subagent_type=general-purpose` reading the
`plotting-agent/SKILL.md`, the other reading the
`literature-review-agent/SKILL.md`. This is the classic Claude Code
parallelism pattern.

## Cursor

### Install

```bash
git clone https://github.com/<you>/paper-orchestra ~/paper-orchestra
cd ~/paper-orchestra
pip install -r requirements.txt

# Cursor uses .cursor/rules/ in your project for skill files
mkdir -p .cursor/rules
for s in paper-orchestra outline-agent plotting-agent literature-review-agent \
         section-writing-agent content-refinement-agent paper-writing-bench \
         paper-autoraters claim-evidence-audit; do
  cp ~/paper-orchestra/skills/$s/SKILL.md .cursor/rules/$s.md
done
```

### Run

In Cursor's chat panel, with the `.cursor/rules/` files loaded, type:

> Run the paper-orchestra pipeline on `./workspace`. Use `@web` for web search.

Cursor's agent will load the rules, execute the pipeline, and use `@web`
for the literature-review search step.

### Notes

- For cross-skill `references/` files, you'll need to either copy the
  entire `skills/` tree into your project or symlink it. SKILL.md alone
  is not sufficient because it points to `references/prompt.md`.
- Cursor's parallel agents (Agent panel) handle Steps 2 ∥ 3 if you split
  them into two tasks.

## Google Antigravity

### Install

Antigravity stores skill packs in `~/.antigravity/skills/` (check the
current docs for the exact path; this is typical):

```bash
git clone https://github.com/<you>/paper-orchestra ~/paper-orchestra
mkdir -p ~/.antigravity/skills
for s in paper-orchestra outline-agent plotting-agent literature-review-agent \
         section-writing-agent content-refinement-agent paper-writing-bench \
         paper-autoraters claim-evidence-audit; do
  ln -sf ~/paper-orchestra/skills/$s ~/.antigravity/skills/$s
done
```

### Run

Antigravity has a worker pool — configure two workers for the parallel
Step 2 + Step 3 branch:

```
worker-A: read skills/plotting-agent/SKILL.md, execute on the workspace
worker-B: read skills/literature-review-agent/SKILL.md, execute on the workspace
```

Then trigger from the prompt:

> Spawn two parallel workers: one for plotting-agent, one for
> literature-review-agent. Both operate on `./workspace`. Wait for both
> to finish, then run section-writing-agent.

Antigravity's web search and URL fetch are built-in.

## Cline (VS Code)

Cline is text-only and lacks parallel sub-agents. Run sequentially.

```bash
git clone https://github.com/<you>/paper-orchestra ~/paper-orchestra
pip install -r requirements.txt
```

Add the skill MD files to Cline's "Custom Instructions" or paste the
relevant SKILL.md into the conversation.

In Cline's chat:

> Run paper-orchestra on `./workspace`. Run Step 3 before Step 2 since
> we don't have parallel sub-agents.

## Aider

Aider is text-only, no native web search. Use degraded mode.

```bash
git clone https://github.com/<you>/paper-orchestra ~/paper-orchestra
pip install -r requirements.txt

# pre-build refs.bib manually OR have Aider use a Bash tool to curl S2
```

In Aider:

> Read skills/paper-orchestra/SKILL.md and the Step 1 / Step 4 / Step 5
> sub-skills. Skip Steps 2 (no vision) and 3 (no web search). Use the
> bundled refs.bib in workspace/inputs/.

The Outline → Section Writing → Refinement minimal pipeline still works.

## OpenCode / Generic CLI agents

Any agent that can read files, run shell commands, and call an LLM can
execute this pipeline. The minimum integration:

```bash
# 1. Make the skills available to the agent's file tool
git clone https://github.com/<you>/paper-orchestra ~/paper-orchestra

# 2. Either pass `cat skills/paper-orchestra/SKILL.md` into the system
#    prompt, or have the agent read it via its file tool
```

Then prompt:

> Read `~/paper-orchestra/skills/paper-orchestra/SKILL.md` and execute
> the pipeline on `./workspace`. Use your native tools for LLM reasoning,
> web search (if available), and shell commands.

## Verifying integration

Run the bundled smoke test:

```bash
cd ~/paper-orchestra
python skills/paper-orchestra/scripts/init_workspace.py --out /tmp/po-test/
cp -r examples/minimal/inputs/* /tmp/po-test/inputs/
python skills/paper-orchestra/scripts/validate_inputs.py --workspace /tmp/po-test/
python skills/section-writing-agent/scripts/extract_metrics.py \
    --log /tmp/po-test/inputs/experimental_log.md \
    --out /tmp/po-test/metrics.json
```

Expected: validate_inputs exits 0, extract_metrics prints
"OK: extracted 4 table(s)".

Then ask your host agent to run the actual pipeline on `/tmp/po-test/`.
A successful end-to-end run produces `/tmp/po-test/final/paper.pdf`.
