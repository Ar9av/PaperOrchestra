---
name: plotting-agent
description: Step 2 of the PaperOrchestra pipeline (arXiv:2604.05018). Execute the visualization plan from outline.json — render plots and conceptual diagrams from experimental_log.md and idea.md, optionally refine via VLM critique loop, and produce context-aware captions. Runs in parallel with the literature-review-agent. TRIGGER when the orchestrator delegates Step 2 or when the user asks to "generate the figures for my paper" or "render the plots from this experiment log".
---

# Plotting Agent (Step 2)

Faithful implementation of the Plotting Agent from PaperOrchestra
(Song et al., 2026, arXiv:2604.05018, §4 Step 2 and App. F.1 p.45).

**Cost: ~20–30 LLM calls.** The paper uses PaperBanana (Zhu et al., 2026) as
the default backbone with a closed-loop VLM-critique refinement. This skill
expresses that loop in host-agent terms: you (the host agent) generate
matplotlib code with your own LLM, render via your Bash/Python tool,
optionally critique the rendered PNG with your vision model, redraw, and
finally caption.

## Inputs

- `workspace/outline.json` — specifically the `plotting_plan` array
- `workspace/inputs/idea.md` and `workspace/inputs/experimental_log.md` —
  the source data
- `workspace/inputs/figures/` — optional pre-existing figures (`PlotOn` mode)

## Outputs

- `workspace/figures/<figure_id>.png` — one PNG per `plotting_plan` entry
  (300 DPI, sized to the requested aspect ratio)
- `workspace/figures/captions.json` — `{figure_id: caption_text}` map

## Workflow

### Per figure (executed independently per `figure_id`)

1. **Read the figure spec** from `outline.json`:
   ```json
   {
     "figure_id": "fig_main_results",
     "title": "Main Results on Dataset X",
     "plot_type": "plot",
     "data_source": "experimental_log.md",
     "objective": "Visual summary (Grouped Bar Chart) demonstrating ...",
     "aspect_ratio": "5:4"
   }
   ```

2. **Few-shot retrieval (visual planning)**: pick the matching pattern from
   `references/chart-patterns.md` (for `plot_type=="plot"`) or
   `references/diagram-patterns.md` (for `plot_type=="diagram"`).

3. **Extract data**: parse `idea.md` and/or `experimental_log.md`
   (`data_source` field tells you which) to obtain the numeric values or
   conceptual entities the figure needs. For `experimental_log.md`, the
   `## 2. Raw Numeric Data` section contains markdown tables.

4. **Render**:

   **If `PAPERBANANA_PATH` is set** — use the PaperBanana backbone
   (Zhu et al., 2026). It runs a Retriever → Planner → Stylist → Visualizer
   → Critic loop and is especially good for `plot_type == "diagram"`.
   See `references/paperbanana-cookbook.md` for setup (needs a Gemini API key).

   ```bash
   python skills/plotting-agent/scripts/paperbanana_render.py \
       --figure-id <figure_id> \
       --caption   "<objective from figure spec>" \
       --content-file workspace/inputs/idea.md \
       --task      <diagram|plot> \
       --aspect-ratio <aspect_ratio> \
       --out       workspace/figures/<figure_id>.png
   ```

   **Otherwise** — write a matplotlib script and run it via your Bash tool,
   or use the bundled helper:
   ```bash
   python skills/plotting-agent/scripts/render_matplotlib.py \
       --spec spec.json \
       --out workspace/figures/<figure_id>.png
   ```
   The script must apply the academic style from `chart-patterns.md`, use the
   correct pixel size from `aspect-ratios.md`, save at 300 DPI, and call
   `plt.close()` after `savefig`.

5. **VLM critique loop (optional, only if your host has vision)**:
   - Reload the rendered PNG as a multimodal input to your LLM.
   - Critique it against the figure's `objective` from the outline. Look for:
     visual artifacts, mislabeled axes, illegible text, color clashes,
     misleading scaling, missing legend, overlapping labels.
   - If problems are found, regenerate the matplotlib script with corrections
     and re-render. Cap at 3 critique iterations per figure.
   - This is the closed-loop refinement step the paper inherits from
     PaperBanana. See `references/plotting-pipeline.md` for the full loop
     description.
   - **If your host has no vision input, skip this step entirely.** The
     figure will still render correctly, just without iterative refinement.

6. **Generate the caption** using the verbatim Caption Generation prompt at
   `references/caption-prompt.md`. Inputs to the caption prompt:
   - `task_name` — the section the figure belongs to (e.g., "Methodology",
     "Experiments")
   - `raw_content` — the surrounding section text (or content_bullets from
     the section_plan if the section isn't drafted yet)
   - `description` — the `objective` field from the figure spec
   - `figure_desc` — a 1-sentence description of what the rendered figure
     actually shows (from your VLM critique pass, or from the script's plan
     if no vision)

   Write the caption to `workspace/figures/captions.json` keyed by
   `figure_id`. **Captions must NOT contain `Figure N:` or `Caption N:`
   prefixes** — the LaTeX template handles numbering. Plain text only, no
   markdown.

## Conceptual diagrams

For `plot_type == "diagram"`, prefer PaperBanana when available — its
Retriever grounds the Planner in real published paper diagrams.  If
`PAPERBANANA_PATH` is unset, follow `references/diagram-patterns.md`.
Patterns include block diagrams, system overviews, flowcharts, and
algorithm-as-graph. The bundled helper:

```bash
python skills/plotting-agent/scripts/render_diagram.py \
    --spec diagram_spec.json \
    --out workspace/figures/<figure_id>.png
```

handles the simple cases (boxes-and-arrows). For complex Fig-1-style
overview diagrams, write matplotlib patches code yourself.

## Hard rules

- **300 DPI** for every figure. Lower DPI gets rejected at the LaTeX compile
  step on conference templates.
- **Aspect ratio is exact**. The figure spec's `aspect_ratio` is one of 12
  enumerated strings. Use the pixel targets in `references/aspect-ratios.md`.
- **Hide top and right spines** for plots. (Diagrams: no spines at all.)
- **Muted academic colors** only. The palette is in `chart-patterns.md`.
  Never use matplotlib defaults (too saturated for print).
- **No 3D, no pie charts, no decorative visuals.** The paper's evaluators
  penalize these.
- **Every figure MUST have a caption** in `captions.json`. The Section
  Writing Agent will fail-stop if a caption is missing for any figure
  referenced from the outline.
- **No `Figure N:` prefix** in captions — LaTeX adds it.
- **Never describe data you didn't plot.** The Plotting Agent must not
  hallucinate axes, baselines, or trends. Source-of-truth is
  `experimental_log.md` or `idea.md`.

## Verification gate (run before handing off to Step 3/4)

The hard rules above are stated everywhere and enforced nowhere. This gate
makes the mechanical half checkable:

```bash
python skills/plotting-agent/scripts/figure_lint.py \
    --figures workspace/figures \
    --captions workspace/figures/captions.json
```

ERRORs: a rendered figure with no caption, a caption with no file, an empty
caption, a raster too small to print. WARNs: resolution under ~300 DPI at
single-column width, aspect ratios past 4:1, captions that number themselves
(`Figure 3: ...`), captions under eight words, and a figure set with no
architecture/pipeline/overview figure in it.

PNG geometry is read from the IHDR and pHYs chunks directly — no imaging
library, consistent with the repo's deterministic-helpers-only rule.

After Step 4 has produced `paper.tex`, re-run with `--paper` to confirm the
draft uses every figure Step 2 rendered and references no file that does not
exist:

```bash
python skills/plotting-agent/scripts/figure_lint.py \
    --figures workspace/figures \
    --paper   workspace/drafts/paper.tex
```

Fix ERRORs before continuing. A missing caption is the one failure that
propagates silently: Step 4 splices the figure with whatever caption it
invents, and Step 5 has no way to know the caption was never grounded.

## Pre-existing figures (PlotOn mode)

If `workspace/inputs/figures/` is non-empty, check whether any pre-existing
file matches a `figure_id` in the outline (by filename prefix). If so,
**copy** it into `workspace/figures/` as-is and **still generate a caption**
using the caption prompt. Only generate from scratch the figure_ids that
have no pre-existing counterpart.

## Resources

- `references/caption-prompt.md` — verbatim Caption Generation prompt from App. F.1
- `references/plotting-pipeline.md` — the full few-shot → render → critique → caption loop
- `references/chart-patterns.md` — matplotlib style + chart type recipes
- `references/diagram-patterns.md` — conceptual diagram recipes
- `references/aspect-ratios.md` — pixel targets for each of the 12 allowed ratios at 300 DPI
- `references/paperbanana-cookbook.md` — **NEW** PaperBanana setup, usage, cost notes, attribution
- `scripts/render_matplotlib.py` — render a JSON plot spec → PNG (matplotlib fallback)
- `scripts/render_diagram.py` — render a JSON diagram spec → PNG (matplotlib fallback)
- `scripts/paperbanana_render.py` — **NEW** PaperBanana backbone wrapper (reads `PAPERBANANA_PATH` from env)
- `scripts/figure_lint.py` — **NEW** resolution / aspect / caption-coverage gate; `--paper` cross-checks `\includegraphics`
