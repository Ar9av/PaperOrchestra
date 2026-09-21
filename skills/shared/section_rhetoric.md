# Section Rhetoric — Structural Templates per Section

The PaperOrchestra prompts (App. F.1) tell the Section Writing Agent *what
content* each section must contain. They say very little about *how the prose
should be shaped* — which sentence carries the message, what order the moves
come in, how a module description differs from a module motivation.

That gap is where AI-written papers read as competent but flat: every
paragraph is a correct summary of something, and no paragraph makes a move.

This reference supplies the missing rhetorical layer. It is a set of
**structural templates**, not style advice. Each template is a fixed sequence
of paragraph roles; the writing agent picks one template per section and
fills the roles.

**Load selectively.** Do not paste this whole file into a prompt. Step 4 pulls
the templates for the sections it is drafting; Step 5 pulls the checklists.

---

## Global rules (apply to every section)

1. **One paragraph, one message.** If a paragraph carries two messages, split it.
2. **The first sentence states the message.** A paragraph that opens with
   background and lands its point in sentence five is a paragraph a reviewer
   skims past.
3. **Nouns are self-contained.** Define a term before reusing it; never let a
   noun phrase depend on context the reader has not been given yet.
4. **Every sentence has a stated relation to the previous one** — cause,
   contrast, consequence, refinement, or example. If no relation exists, the
   sentence belongs in a different paragraph.
5. **Terminology is frozen.** One name per concept, chosen once, used from
   Abstract to Conclusion. Synonym variation reads as a second system.
6. **Unsupported claims get weakened or cut**, never hedged into vagueness.
   See `skills/content-refinement-agent/references/claim-evidence-map.md`.

---

## Abstract

Pick one of three templates based on how many contributions the outline
declares (`outline.json` → `section_plan` → contributions).

### Template A — Challenge → Contribution (one contribution)

| # | Role | Length |
|---|---|---|
| 1 | Task | 1 sentence |
| 2 | Technical challenge that previous methods hit | 1–2 sentences |
| 3 | The contribution that resolves it — **name the technique, do not explain its steps** | 1–2 sentences |
| 4 | Benefit of that contribution | 1 sentence |
| 5 | Experiment summary with the headline number | 1 sentence |

### Template B — Challenge → Insight → Contribution

Same as A, with one extra role between 2 and 3: **the insight** — the single
sentence explaining *why* the challenge is solvable at all. Use this when the
paper's novelty is a way of seeing the problem, not a mechanism.

### Template C — Multiple contributions

| # | Role |
|---|---|
| 1 | Task |
| 2 | Optional one-sentence contrast with prior methods |
| 3 | Contribution 1 **+ its technical advantage, in the same sentence** |
| 4 | Contribution 2 + advantage |
| 5 | Contribution 3 + advantage |
| 6 | Experiment summary |

The pairing in roles 3–5 is the whole skill: a contribution named without its
advantage reads as a feature list.

### Abstract checklist

1. Can a reader name the task, the challenge, the contribution, and the result
   after one pass?
2. Is every number in the abstract present in the Experiments section?
3. Is each technical name readable without the Method section?
4. Does any sentence carry more than one message?

---

## Introduction

### The logic chain (answer backward, write forward)

Answer these before drafting:

1. What technical problem do we solve, and why is there no established solution?
2. What does our pipeline contribute — new task, new metric, new problem, or
   new technique?
3. Why do those contributions resolve the challenge, and what insight do they
   carry?
4. Which prior methods lead the reader most directly to that challenge?

Then write in this order:

```
% Part 1  Task + applications + the metrics that matter
% Part 2  Prior methods → the technical challenge (limitation AND its cause)
% Part 3  Our pipeline → why it works
% Part 4  Additional contributions and impact
% Part 5  Experiment summary
% Part 6  Contribution bullets
```

### Part 1 — three openings

- **Opening 1 (niche task):** define the task in one sentence — *what output*
  from *what input* — then 2–3 application scenarios.
- **Opening 2 (familiar task):** skip the definition, open on application
  importance, append the target requirement (accuracy / latency / robustness).
- **Opening 3 (new setting):** applications of the general task first, then
  narrow to the specific setting. Best when the setting itself is the novelty.

### Part 2 — the technical challenge

A technical challenge is **a limitation plus its cause**. "Prior methods are
slow" is not a challenge; "prior methods re-encode the full context at every
step, so latency grows linearly in dialogue length" is. Papers whose Part 2
lists limitations without causes cannot write a convincing Part 3, because
there is nothing for the method to attack.

Discuss prior work strictly around the challenge this paper actually solves.
Prior work that is unrelated to the challenge belongs in Related Work.

### Part 3 — the pipeline

State the solution, then why it works. "Why it works" is the sentence readers
quote when they recommend the paper; it is the single highest-value sentence
in the Introduction.

### Introduction checklist

1. Does Part 2 give a cause, not just a symptom?
2. Does Part 3 explain why the design resolves *that specific* cause?
3. Would the contribution bullets survive a reviewer asking "which experiment
   shows this?"
4. Does the Introduction avoid describing the method as a patch on a baseline?

---

## Related Work

Step 3 (literature-review-agent) drafts this section; this template governs
its paragraph shape.

**2–4 topics**, grouped by technical theme, never by publication year:

1. Mainstream methods for the task.
2. Methods closest to our core idea.
3. Auxiliary techniques we build on.

Each topic paragraph runs:

| # | Role |
|---|---|
| 1 | Topic sentence defining the scope of this group |
| 2 | Representative methods, compactly summarized |
| 3 | The limitation of this group **tied to our target challenge** |
| 4 | Transition to our method |

Do compare mechanisms, assumptions, and failure modes. Do not produce a
citation dump, and do not bury the strongest competitor — reviewers read
Related Work to find out whether you know who you are competing with.

---

## Method

### Before drafting

List every module in the pipeline. For each, answer three questions:

- How does it run?
- Why is it needed?
- Why does it work?

A module that cannot answer all three is either underspecified or not a module.

### The module triad

Every Method subsection carries three elements, written in this order:

1. **Design** — representation, network, data structure, and the forward
   process as `input → step → step → output`. Write this first; it is the
   concrete backbone.
2. **Motivation** — problem-driven: *because X fails, we design Y*. Added
   after the design exists, so it can reference specifics.
3. **Technical advantage** — why this beats the alternative, tied to
   measurable behavior wherever the experimental log supports it.

Writing design-only subsections produces a system description. Writing
motivation-only subsections produces a pitch. The triad produces a method.

### Method checklist

1. Does each subsection map to a block in the pipeline figure?
2. Is the forward process reconstructible from the text alone?
3. Is every design choice either motivated or ablated (ideally both)?
4. Does the section avoid reading as incremental patching of a naive baseline?

---

## Experiments

### The three questions the section must answer

1. **Is it better than strong baselines?** Main benchmark, standard metrics,
   recent and strongest public methods, identical protocol.
2. **Which design choices produce the gain?** Ablations that remove, replace,
   or disable each key module, reported as a delta to the full model.
3. **How far does it generalize?** Harder settings, out-of-distribution cases,
   stress tests — reporting failure modes as well as gains.

A paper answering only question 1 is a benchmark entry, not a method paper.

### Structure

```
Experimental Setup → Main comparison → Secondary validation → Ablations → Limits/failure cases
```

Map every claimed contribution to at least one experiment. Contributions with
no supporting experiment must be removed from the Introduction, not defended
in the Experiments section.

### Table rules

See `skills/section-writing-agent/references/latex-table-patterns.md` for the
booktabs conventions. Two rules that belong here rather than there:

- **Label metric direction in the header** — `PSNR ↑`, `LPIPS ↓`, `Latency (ms) ↓`.
  A reviewer should never have to infer which way is better.
- **One table, one message.** Unrelated results in one table means neither
  result lands.

---

## Conclusion

| # | Role |
|---|---|
| 1 | Restate the problem solved and the core technical idea |
| 2 | Strongest evidence, one sentence |
| 3 | Practical impact or the insight that generalizes |
| 4 | Limitation |
| 5 | Concrete next step |

### Limitations: scope, not defects

Prefer limitations that bound the *setting*: data regime, assumption, or
deployment scope. These describe where the method applies and cost nothing.

Avoid confessing fixable implementation flaws unless they genuinely define the
method's scope — a reviewer reads "we did not tune the learning rate" as a
reason to reject, and "we evaluate only on short sequences" as a boundary.

Distinguish the two explicitly:

- **Technical defect** — loses to strong baselines on a key metric, or forces
  an unacceptable tradeoff.
- **Scope limitation** — bounded by the current task setting while remaining
  competitive with SOTA.

Only the second belongs in a Conclusion.

---

## Attribution

The abstract/introduction/method templates here are adapted from
[Master-cai/Research-Paper-Writing-Skills](https://github.com/Master-cai/Research-Paper-Writing-Skills)
(MIT License), which distills Prof. Peng Sida's open paper-writing notes into
agent-readable form. This file restates those structures in the vocabulary of
the PaperOrchestra pipeline (outline.json roles, Step 4 / Step 5 handoffs) and
adds the checklists used by the refinement loop. The original repository is
the better reference for worked examples from published CV papers.
