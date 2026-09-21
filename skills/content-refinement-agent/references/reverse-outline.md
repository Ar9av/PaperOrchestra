# Reverse Outlining

A reverse outline is the paper's argument with all the prose removed: one line
per paragraph — its topic sentence — read in order. Sentence-level review
cannot find what this finds. A paper can be locally excellent everywhere and
still have no argument, and the only way to see that is to stop reading the
sentences.

The generated outline is the reviewer's input for the **Logical Flow** axis of
`references/reviewer-rubric.md`.

## Running it

```bash
python skills/content-refinement-agent/scripts/reverse_outline.py \
    --paper workspace/drafts/paper.tex \
    --out   workspace/reverse_outline.md \
    --json  workspace/reverse_outline.json
```

Exit 0 always, unless `--strict` is passed (then exit 1 when any paragraph
carries a flag). Default advisory mode is correct for the loop: the flags are
prompts for judgment, not defects.

## What the flags mean

| Flag | Heuristic | What it usually indicates |
|---|---|---|
| `no-topic-sentence` | Opening sentence is under six words, or opens on a connective (*However*, *Moreover*, *Therefore*) | The message lives further down the paragraph. Reviewers skimming topic sentences miss it entirely. |
| `overlong` | More than 8 sentences or 220 words | Two messages sharing a paragraph. Split at the pivot. |
| `multi-pivot` | Two or more contrastive turns (*however*, *in contrast*, *on the other hand*) | Each pivot changes direction; two changes of direction is two paragraphs. |
| `orphan` | Single sentence, under 60 words | Belongs to a neighbouring paragraph, or is a heading written as prose. |
| `citation-dump` | More citations than sentences | Related Work listing papers instead of positioning against them. |

Run-in bold headings (`\textbf{Policy engine.} The engine evaluates...`) are
merged into the sentence that follows, so the convention does not register as
a missing topic sentence.

## Reading the outline

Read only the numbered topic sentences of a section, in order, and ask:

1. Does the sequence make an argument, or is it a list of related facts?
2. Does each topic sentence follow from the previous one — cause, contrast,
   consequence, refinement, or example?
3. Can each topic sentence be mapped to the section's thesis? A paragraph that
   maps to nothing gets cut, not rewritten.
4. Is any paragraph's actual message different from its topic sentence? That
   is the paragraph to fix first.

Structural findings go into the revision agenda as *reorder / merge / split /
cut* instructions. Sentence-level rewriting cannot fix a sequencing problem,
and iterations spent polishing a misordered section are iterations the halt
rules count against the budget.

## Provenance

The reverse-outlining practice and the one-paragraph-one-message rule follow
[Master-cai/Research-Paper-Writing-Skills](https://github.com/Master-cai/Research-Paper-Writing-Skills)
(MIT). The flag heuristics and the script are PaperOrchestra's. See also
`skills/shared/section_rhetoric.md` for the per-section paragraph-role
templates the outline is checked against.
