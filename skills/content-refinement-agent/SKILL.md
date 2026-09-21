---
name: content-refinement-agent
description: Step 5 of the PaperOrchestra pipeline (arXiv:2604.05018). Iteratively refine drafts/paper.tex by simulating peer review and applying targeted revisions, with strict accept/revert halt rules, deterministic 0-100 decision bands (Accept/Minor/Major/Reject) that drive a target-met early stop, and a Devil's Advocate concession-threshold guard that blocks acceptance on unresolved critical findings. Maintains a worklog and snapshots each iteration so revert is real, not symbolic. TRIGGER when the orchestrator delegates Step 5 or when the user asks to "refine the draft", "iterate on the paper", or "run peer review on this paper".
data_access_level: verified_only
---

# Content Refinement Agent (Step 5)

Faithful implementation of the Content Refinement Agent from PaperOrchestra
(Song et al., 2026, arXiv:2604.05018, §4 Step 5, App. F.1 pp. 49–51).

**Cost: ~5–7 LLM calls** (App. B), typically ~3 refinement iterations, each
consisting of one reviewer call and one revision call.

The paper highlights this step as one of the largest contributors to overall
quality: refinement alone accounts for +19% (CVPR) and +22% (ICLR) absolute
acceptance-rate improvement (Fig. 4). Get this step right.

## Inputs

- `workspace/drafts/paper.tex` — output of Step 4
- `workspace/inputs/conference_guidelines.md`
- `workspace/inputs/experimental_log.md` — used as ground truth for the
  hallucination check
- `workspace/citation_pool.json` / `workspace/refs.bib` — the allowed
  bibliography

## Outputs

- `workspace/refinement/iter1/`, `iter2/`, `iter3/` — per-iteration snapshots
  containing `paper.tex`, `paper.pdf`, `review.json`, `score.json`
- `workspace/refinement/worklog.json` — append-only history of decisions
- `workspace/final/paper.tex` and `workspace/final/paper.pdf` — copy of the
  best accepted snapshot

## The refinement loop

```
prev_score = score(paper.tex)                  # baseline from initial draft
snapshot iter0/

for iter in 1..ITER_CAP (default 3):
    1. simulate_review(paper.tex) → review.json
       (uses `references/reviewer-rubric.md` rubric)

    2. apply_revision(paper.tex, review.json) → new_paper.tex
       (uses verbatim Refinement Agent prompt at `references/prompt.md`)

    3. snapshot iter<N>/ with new_paper.tex, review.json
       latexmk -pdf new_paper.tex → iter<N>/paper.pdf

    4. score(new_paper.tex) → curr_score

    5. decide via score_delta.py:
       - if curr.overall > prev.overall:                       ACCEPT
       - elif curr.overall == prev.overall and net_subaxis ≥0: ACCEPT
       - else:                                                 REVERT

    6. apply_worklog.py to append the decision

    7. if REVERT or no actionable weaknesses or iter == ITER_CAP: HALT

    paper.tex ← new_paper.tex   (only on ACCEPT)
    prev_score ← curr_score

cp <best iter>/paper.tex → workspace/final/paper.tex
```

The "best" snapshot at HALT is the one with the highest accepted overall
score. On a REVERT halt, the best is the iteration immediately before the
revert.

## Step-by-step

### 0. Pre-refinement integrity gate

Before snapshotting or scoring the initial draft, run two gates in order:

**Gate A — AI failure modes** (load `references/ai-failure-modes.md`, runs once):

Load `references/ai-failure-modes.md` (which points to `skills/shared/ai_failure_modes.md`).
Run all 7 checks against the draft and the inputs. This gate runs **once only**,
at the start of iteration 1.

- CONFIRMED failure → write HALT entry to worklog.json, report to user, stop.
- SUSPECTED failure → add WARNING comment to paper.tex, log in worklog.json, continue.
- No failures → proceed.

**Gate B — Claim-evidence provenance** (runs once, WARN gate):

```bash
python skills/paper-orchestra/scripts/claim_evidence_gate.py \
    --paper workspace/drafts/paper.tex \
    --log   workspace/inputs/experimental_log.md \
    --out   workspace/claim_evidence_report.json
```

Exit 0 → PASS, proceed normally.
Exit 1 → WARN: unsupported numeric claims found. Log in worklog.json as:
`{gate: "claim_evidence", status: "WARN", unsupported_count: N, report: "workspace/claim_evidence_report.json"}`
Pass the `unsupported` list from the report to the revision agent in Step 3 as
an additional instruction: "The following numeric values appear in the paper but
cannot be corroborated in experimental_log.md — verify or remove them: ..."
Do NOT halt on Gate B warnings; the revision agent will address them.

**Gate C — Reverse outline** (runs once, advisory):

```bash
python skills/content-refinement-agent/scripts/reverse_outline.py \
    --paper workspace/drafts/paper.tex \
    --out   workspace/reverse_outline.md \
    --json  workspace/reverse_outline.json
```

Strips the draft to one line per paragraph — its topic sentence — and flags
paragraphs with no topic sentence, two messages, or a citation dump. Read
`workspace/reverse_outline.md` before the first reviewer call and pass it into
the reviewer call as the input for the **Logical Flow** axis. Structural
findings enter the revision agenda as *reorder / merge / split / cut*
instructions; sentence-level rewriting cannot fix a sequencing problem, and
iterations spent polishing a misordered section still count against the budget.
See `references/reverse-outline.md`.

**Gate D — Read research brief** (every run, no exit code):

If `workspace/research_brief.md` exists, read it before all reviewer calls.
Pass the "Sections where evidence was thin" list from §4 as additional
context to the Devil's Advocate reviewer. This surfaces the highest-risk
sections for CRITICAL scrutiny.

### 0b. Snapshot the initial draft

```bash
python skills/content-refinement-agent/scripts/snapshot.py \
    --src workspace/drafts/paper.tex \
    --dst workspace/refinement/iter0/
```

This creates `iter0/paper.tex`. Then compile to `iter0/paper.pdf`:


```bash
cd workspace/refinement/iter0/ && latexmk -pdf -interaction=nonstopmode paper.tex
```

Score it (see Step 1 below) → `iter0/score.json`.

### 1. Simulate peer review

For each iteration N starting from 1:

**Writing quality pre-check (start of every iteration):** Load
`references/writing-quality-check.md` and run the 5-category checklist
(Categories A–E) against the current draft. Note violations and add them to
the revision agenda.

**Update critique memory before the reviewer call** (iter N ≥ 2 only — skip for iter 1):

```bash
python skills/content-refinement-agent/scripts/update_critique_memory.py \
    --worklog workspace/refinement/worklog.json \
    --review  workspace/refinement/iter<N-1>/review.json \
    --iter    <N> \
    --out     workspace/refinement/critique_memory.json
```

This produces `critique_memory.json` with `focus_on` (persistent unresolved
issues) and `do_not_reflag` (already-resolved issues). Inject both lists into
the reviewer system prompt verbatim:

```
CRITIQUE MEMORY — you must honour this before reviewing:

FOCUS ON (flagged in prior iterations, not yet resolved — prioritise these):
<critique_memory.focus_on items, one per line>

DO NOT RE-FLAG (already addressed in prior iterations):
<critique_memory.do_not_reflag items, one per line>
```

This prevents the reviewer from re-discovering already-fixed issues and
from missing genuinely stuck problems.

Regenerate the reverse outline for the current draft (`reverse_outline.py`,
Gate C) and include `workspace/reverse_outline.md` in the reviewer's user
message. The reviewer scores Logical Flow against the topic-sentence sequence
rather than against its impression of the prose, which is what makes that axis
move for structural reasons instead of stylistic ones.

Load `references/reviewer-rubric.md` as the system prompt for the simulated
reviewer call. The reviewer reads `iter<N-1>/paper.pdf` (or `paper.tex` if
your host LLM lacks PDF input) and produces a JSON of strengths,
weaknesses, questions, and per-axis scores.

The rubric is structured to mimic AgentReview (Jin et al., 2024) — the
paper's chosen evaluator. We ship a faithful rubric in the references
directory; the host agent's LLM does the actual reviewing.

**Devil's Advocate reviewer:** One simulated reviewer must be designated the DA
following `references/da-reviewer.md`. The DA challenges core claims from first
principles (causal overclaiming, ablation coverage, baseline fairness,
generalization claims, novelty inflation) rather than surface polish. If the DA
issues a CRITICAL finding that remains unaddressed after all reviewers weigh in,
that finding blocks the "refinement accepted" decision regardless of rubric scores.
Log DA CRITICAL findings in worklog.json: `{da_critical: true, finding: "..."}`.

Record the DA's per-round findings and concession decisions in
`workspace/refinement/da_concessions.json` (schema in `references/da-reviewer.md`)
and enforce the concession-threshold protocol deterministically — this stops the
simulated DA from sycophantically caving:

```bash
python skills/content-refinement-agent/scripts/concession_guard.py \
    --log workspace/refinement/da_concessions.json \
    --out workspace/refinement/iter<N>/da_guard.json
# exit 0 = clear; exit 1 = standing CRITICAL → force REVERT this iteration;
# exit 2 = a concession was rejected (caving/consecutive) → DA must restate;
# exit 3 = schema error.
```

The guard rejects any concession made at `rebuttal_score < 4` or in a round
immediately following another concession, and restores the affected finding to
"standing". A standing CRITICAL (exit 1) overrides an ACCEPT into a REVERT.

Save to `workspace/refinement/iter<N>/review.json`.

### 2. Score the draft

The reviewer call produces both qualitative feedback and a per-axis score:

```json
{
  "axis_scores": {
    "scientific_depth":     {"score": 65, "justification": "..."},
    "technical_execution":  {"score": 70, "justification": "..."},
    "logical_flow":         {"score": 60, "justification": "..."},
    "writing_clarity":      {"score": 55, "justification": "..."},
    "evidence_presentation":{"score": 72, "justification": "..."},
    "academic_style":       {"score": 68, "justification": "..."}
  },
  "overall_score": 64.5,
  "decision_band": "Major Revision",
  "strengths": [...],
  "weaknesses": [...],
  "questions": [...]
}
```

Save to `iter<N>/score.json`. (Combined with `review.json` if your host
emits one document; the schemas overlap.)

`decision_band` is derived deterministically from `overall_score` — Accept
(≥80) / Minor Revision (65–79) / Major Revision (50–64) / Reject (<50). Fill it
in with `python skills/content-refinement-agent/scripts/decision_band.py
--score-json iter<N>/score.json` rather than by hand, so it can never disagree
with the number. The bands drive the target-met halt in Step 5.

### 3. Apply revision

Load the **verbatim Content Refinement Agent prompt** at `references/prompt.md`.
Prepend the Anti-Leakage Prompt. Inputs:

- `paper.tex` — current draft
- `paper.pdf` — compiled PDF (multimodal context if available)
- `conference_guidelines.md`
- `experimental_log.md` — ground truth for numeric claims
- `worklog.json` — history of previous changes
- `citation_pool.json` — the allowed bibliography
- `reviewer_feedback` — the JSON from Step 1

The prompt instructs the model to address weaknesses, integrate question
answers, and emit two output blocks:

1. A worklog JSON `{addressed_weaknesses[], integrated_answers[], actions_taken[]}`
2. The full revised LaTeX code

Save the revised LaTeX as `iter<N>/paper.tex`. Append the worklog JSON to
`workspace/refinement/worklog.json` via `apply_worklog.py`.

### 4. Compile and re-score

```bash
cd workspace/refinement/iter<N>/ && latexmk -pdf -interaction=nonstopmode paper.tex
```

Then re-run the simulated review on the new draft → updated `score.json`
for the new iteration. (This is the "re-score after revision" call.)

### 5. Apply the accept/revert decision

The calling loop must track `CONSECUTIVE_SMALL` (starts at 0) and pass it
on each call so `score_delta.py` can detect the plateau:

```bash
python skills/content-refinement-agent/scripts/score_delta.py \
    --prev workspace/refinement/iter<N-1>/score.json \
    --curr workspace/refinement/iter<N>/score.json \
    --plateau-threshold 1.0 \
    --plateau-streak 3 \
    --accept-threshold 80 \
    --consecutive-small $CONSECUTIVE_SMALL \
    > workspace/refinement/iter<N>/delta.json

EXIT=$?
# Update streak for next iteration:
CONSECUTIVE_SMALL=$(python3 -c "
import json
d = json.load(open('workspace/refinement/iter<N>/delta.json'))
print(d['consecutive_small'])
")
```

Exit codes:
- `0` — ACCEPT (overall improved or tied with non-negative net sub-axis, below the Accept band, no plateau)
- `1` — REVERT (overall decreased)
- `2` — REVERT (tied overall, but net sub-axis change negative)
- `4` — HALT_PLATEAU (accepted but N consecutive iterations below threshold — stop early)
- `5` — HALT_TARGET_MET (accepted AND reached the Accept band, overall ≥ 80 — stop)

Behavior:

- **ACCEPT (exit 0)**: keep `iter<N>/paper.tex` as the new best. Continue to iter N+1.
- **REVERT (exit 1 or 2)**: copy `iter<N-1>/paper.tex` back as canonical, halt.
- **HALT_PLATEAU (exit 4)**: keep current (it was accepted), but stop — further
  iterations are unlikely to yield meaningful gains. In practice ~85% of
  refinement gain comes in iteration 1; the plateau fires when subsequent
  iterations improve by less than 1 point for 3 consecutive rounds.
- **HALT_TARGET_MET (exit 5)**: keep current (it was accepted), but stop — the
  paper has reached the Accept band (overall ≥ 80), so there is no reason to
  keep iterating and risk a regression. The `delta.json` carries
  `decision_band_prev` / `decision_band_curr` for the run report.

**Override — DA CRITICAL.** If `concession_guard.py` (Step 1) returned exit 1
for this iteration, treat the outcome as **REVERT** even when `score_delta.py`
says ACCEPT: roll back to `iter<N-1>/paper.tex` and require the next revision to
address the standing CRITICAL finding.

Always log the decision via `apply_worklog.py --decision ...`.

### 6. Halt rules

Halt the loop when ANY of these is true:

1. Iteration count reaches `ITER_CAP` (default 3).
2. `score_delta.py` returned exit code 1 or 2 (REVERT), OR `concession_guard.py`
   returned exit 1 (standing DA CRITICAL → forced REVERT).
3. The simulated reviewer's `weaknesses` list is empty (no actionable
   feedback to apply).
4. `score_delta.py` returned exit code 4 (HALT_PLATEAU — plateau early-stop).
5. `score_delta.py` returned exit code 5 (HALT_TARGET_MET — reached the Accept
   band, overall ≥ 80; promote the current draft).

### 7. Promote the best snapshot

Identify the iteration with the highest accepted `overall_score` (this may
be the latest accepted iteration, OR an earlier one if a later iteration
was reverted). Copy:

```bash
cp workspace/refinement/iter<best>/paper.tex workspace/final/paper.tex
cp workspace/refinement/iter<best>/paper.pdf workspace/final/paper.pdf
```

Then in the final report, tell the user:
- How many iterations were run
- The final overall score and its decision band (Accept / Minor / Major / Reject)
- The score trajectory with bands (e.g., "iter0 58.0 Major → iter1 67.3 Minor (accept) → iter2 81.0 Accept (halt: target met)")
- Which iteration was promoted, and the halt reason (revert / plateau / target met / iter cap / DA critical)

## Critical safety constraints (App. F.1 page 50–51)

The paper explicitly notes that early versions of the Refinement Agent
"exploited the automated reviewer's scoring function by superficially
listing missing baselines as limitations to artificially inflate
acceptance scores." The verbatim prompt forbids this. **You must honor it:**

- **[IRON RULE] Halt on score regression.** If `score_delta.py` returns exit
  code 1 or 2 (REVERT), immediately revert to the previous snapshot and halt.
  No further revision attempts are permitted after a regression.
- **[IRON RULE] No new experiments in revision.** Ignore reviewer requests for
  new experiments, ablations, or baselines. The Refinement Agent's job is
  presentation, not new science. If the reviewer asks for missing data, simply
  skip those points — do NOT add fabricated experiments, do NOT add a "future
  work" item promising them.
- **[IRON RULE] All numeric claims must match experimental_log.md.** The agent
  cannot introduce new numbers, only re-present existing ones. Any number in
  the revised paper that does not appear in experimental_log.md is a
  hallucination.
- **Never explicitly state a limitation.** The phrase "we acknowledge as a
  limitation that..." is forbidden. The model can address weaknesses
  through clearer explanation, but must not game the evaluator by listing
  them defensively.

These rules prevent reward hacking and keep the refinement loop honest.

## Resources

- `references/prompt.md` — verbatim Content Refinement Agent prompt from App. F.1
- `references/reviewer-rubric.md` — AgentReview-style scoring rubric (6 axes)
- `references/halt-rules.md` — accept/revert/halt logic in formal pseudocode
- `references/safe-revision-rules.md` — anti-reward-hack constraints
- `references/writing-quality-check.md` — 5-category anti-AI-prose checklist (pointer to shared)
- `references/ai-failure-modes.md` — 7-mode integrity gate run before first iteration (pointer to shared)
- `references/da-reviewer.md` — Devil's Advocate reviewer protocol and concession rules
- `references/reverse-outline.md` — **NEW** what the paragraph flags mean and how to read a reverse outline
- `scripts/score_delta.py` — accept/revert/halt decision from two score JSONs; emits decision bands + target-met halt (exit 5)
- `scripts/decision_band.py` — map an overall score to a canonical decision band (Accept/Minor/Major/Reject)
- `scripts/concession_guard.py` — enforce the DA concession-threshold protocol; blocks accept on a standing CRITICAL
- `scripts/score_trajectory.py` — per-dimension score history, regression and plateau detection
- `scripts/reverse_outline.py` — **NEW** topic-sentence outline + structural paragraph flags
- `scripts/apply_worklog.py` — append iteration entries to worklog.json
- `scripts/snapshot.py` — copy paper.tex/paper.pdf into iter<N>/ for rollback
- `scripts/update_critique_memory.py` — **NEW** build/update critique_memory.json from worklog + review (AutoSci-inspired reviewer memory)
- `skills/shared/writing_quality_check.md` — full anti-AI-prose checklist (5 categories)
- `skills/shared/ai_failure_modes.md` — full AI research failure modes gate (7 modes)
- `skills/shared/handoff_schemas.md` — formal data contracts between all pipeline steps
- `skills/shared/research_brief_template.md` — **NEW** research brief schema (read §1–§4 before first reviewer call)
