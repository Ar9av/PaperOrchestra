#!/usr/bin/env python3
"""
claim_evidence_gate.py — Verify that quantitative claims in a paper draft
are grounded in the experimental log (AutoSci-inspired claim-evidence gate).

Analogous to orphan_cite_gate.py for citations: this gate extracts numeric
claims from the LaTeX draft and checks each against experimental_log.md.
Claims that cannot be corroborated are flagged as UNSUPPORTED.

This is a WARN gate (like validate_consistency.py), not a hard-stop gate:
  exit 0 — PASS: all extracted claims corroborated, or no claims extracted
  exit 1 — WARN: one or more claims could not be corroborated
  exit 2 — ERROR: input file missing or unreadable

Run during content-refinement Step 0 (pre-refinement integrity gate), after
ai_failure_modes checks.

Usage:
    python claim_evidence_gate.py \\
        --paper  workspace/drafts/paper.tex \\
        --log    workspace/inputs/experimental_log.md \\
        --out    workspace/claim_evidence_report.json

Optionally also writes a human-readable claim-evidence map (--out-md):
a `Claim | Value | Section | Evidence | Status` table the refinement agent
can paste into its revision agenda.

Output JSON:
    {
      "supported":   [ {claim, value, section, context, evidence_snippet} ],
      "unsupported": [ {claim, value, section, context} ],
      "uncertain":   [ {claim, value, section, context, reason} ],
      "summary": {
        "total": N,
        "supported": N, "unsupported": N, "uncertain": N
      }
    }
"""
import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict


# ── numeric claim patterns ────────────────────────────────────────────────────
# These patterns capture quantitative claims that typically appear in results:
#   - percentage improvements / accuracies          e.g. "improves by 3.2%"
#   - absolute metric values in result context      e.g. "achieves 87.4 mAP"
#   - ratio/fold improvements                       e.g. "2.5× faster"
#   - comparison operators with numbers             e.g. "outperforms X by 5.1"
# Patterns are intentionally broad; false positives are marked UNCERTAIN.

CLAIM_PATTERNS: list[re.Pattern] = [
    # percentage: "by 3.2%", "of 87.4%", "achieves 92.1%"
    re.compile(
        r"(?:by|of|to|at|achieves?|improves?\s+(?:by|to)|gains?|reduces?\s+(?:by|to)|"
        r"increases?\s+(?:by|to)|decreases?\s+(?:by|to)|accuracy|f1|recall|"
        r"precision|score|performance|rate|under|over|above|below)\s+"
        r"[<>~=]{0,2}\s*([+-]?\d+\.?\d*)\s*%",
        re.IGNORECASE,
    ),
    # bare percentage anywhere: "28.7%", "+34%" — broad on purpose, the
    # attribution pass below sorts cited numbers out of the claim set
    re.compile(r"([+-]?\d+\.?\d*)\s*%"),
    # ratio: "2.5× faster", "3x more"
    re.compile(r"(\d+\.?\d*)\s*[×x]\s*(?:faster|slower|more|less|better|worse)", re.IGNORECASE),
    # standalone multiplier: "2.13×", "×1.8"
    re.compile(r"(\d+\.?\d*)\s*×"),
    re.compile(r"×\s*(\d+\.?\d*)"),
    # absolute metric with label: "87.4 mAP", "0.923 AUC", "12.3 BLEU"
    re.compile(r"(\d+\.?\d*)\s+(?:mAP|AUC|BLEU|ROUGE|CIDEr|FID|IS|top-\d+|WER|CER|IoU)",
               re.IGNORECASE),
    # "outperforms / exceeds / surpasses ... by N"
    re.compile(
        r"(?:outperforms?|exceeds?|surpasses?|beats?|better\s+than|"
        r"superior\s+to|lags?\s+behind)\s+[^.]{0,60}?\s+by\s+([+-]?\d+\.?\d*)",
        re.IGNORECASE,
    ),
    # LaTeX table cells: numbers in tabular environments (heuristic)
    re.compile(r"\\textbf\{(\d+\.?\d*)\}"),
    re.compile(r"(\d{2,3}\.\d{1,2})\s*(?:\\\\|&|\})"),
]

# Pattern ids whose matches are structural rather than rhetorical. Small
# integers and bare years hit these constantly, so they are filtered harder.
GENERIC_PATTERN_IDS = {7, 8}

# Patterns that indicate the number belongs to someone else's paper rather
# than to us. `[CITE]` is the marker left behind by normalize_latex() where a
# \cite/\citep/\citet command stood: a number in a sentence that carries a
# citation is attributed, not claimed.
# The cues are deliberately narrow. "baseline" and "compared to" were cues in
# an earlier revision, which silently reclassified our own comparative results
# ("improves over the strongest baseline by 3.2%") as someone else's numbers —
# the single most common shape of a real claim in an Experiments section.
PRIOR_WORK_CONTEXT = re.compile(
    r"(?:\[CITE\]|prior\s+(?:work|methods?)|previous\s+(?:work|methods?|approaches)|"
    r"existing\s+(?:work|methods?|systems?|tools?)|et\s+al\.|"
    r"concurrent\s+work|related\s+work|report(?:s|ed)\s+by|according\s+to|"
    r"documents?\s|found\s+that)",
    re.IGNORECASE,
)

# Minimum number of characters around a match to extract as context snippet
CONTEXT_WINDOW = 120


# ── helpers ───────────────────────────────────────────────────────────────────

@dataclass
class Claim:
    value: str
    context: str
    pattern_id: int
    is_prior_work: bool = False
    section: str = "(unknown)"
    sentence: str = ""


def normalize_latex(text: str) -> str:
    r"""
    Flatten LaTeX markup into plain text that the claim patterns can match.

    Three things matter here, and each of them silently suppressed claims in
    the previous implementation:

    1. `\%` is an escaped percent sign, not a comment. Stripping from the
       first `%` on every line deleted the remainder of any line containing a
       percentage — i.e. most sentences that state a result.
    2. Percentages reach us as `3.2\%`, multipliers as `2.13$\times$`, and
       bounds as `${>}85\%$`. Un-normalized, none of these match a pattern
       written against plain `3.2%`.
    3. `\cite{...}` must leave a marker rather than vanish, otherwise
       attribution detection has nothing to key on and numbers belonging to
       cited work get reported as our own unsupported claims.
    """
    # Citations become a marker (attribution signal), other refs are dropped.
    text = re.sub(r"\\cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{[^}]*\}", " [CITE] ", text)
    text = re.sub(r"\\(?:label|ref|cref|Cref|autoref|footnote|url|href)\{[^}]*\}", " ", text)
    # Keep the abstract locatable: it precedes the first \section.
    text = re.sub(r"\\begin\{abstract\}", r"\\section{Abstract}", text)
    text = re.sub(r"\\(?:begin|end)\{[^}]*\}", " ", text)

    # Real comments only: a `%` not preceded by a backslash.
    text = re.sub(r"(?<!\\)%.*$", "", text, flags=re.MULTILINE)

    # Escapes and math markup → plain equivalents.
    text = text.replace(r"\%", "%")
    text = re.sub(r"\\times\b", "×", text)
    text = re.sub(r"\\(?:geq|ge)\b", ">=", text)
    text = re.sub(r"\\(?:leq|le)\b", "<=", text)
    text = re.sub(r"\\(?:sim|approx)\b", "~", text)
    text = re.sub(r"\\textbf\{(\d+\.?\d*)\}", r"\\textbf{\1}", text)  # keep for pattern 7
    text = re.sub(r"\{([<>~=]+)\}", r"\1", text)                       # ${>}85\% → >85%
    text = re.sub(r"\\[,;:!]", " ", text)                              # thin spaces
    # "sub-5%" / "under-3%": the hyphen is a prefix, not a minus sign. Left
    # alone, [+-]? swallows it and the claim is extracted as "-5".
    text = re.sub(r"(?<=[A-Za-z])-(?=\d+\.?\d*\s*%)", " ", text)
    text = text.replace("$", " ").replace("~", " ")
    return text


def section_index(text: str) -> list[tuple[int, str]]:
    """Offsets of \\section{...} headings, for locating a claim in the paper."""
    return [(m.start(), m.group(1).strip())
            for m in re.finditer(r"\\section\*?\{([^}]*)\}", text)]


def section_at(index: list[tuple[int, str]], offset: int) -> str:
    name = "(preamble)"
    for pos, title in index:
        if pos <= offset:
            name = title
        else:
            break
    return name


def _extract_sentence(text: str, match_start: int, match_end: int) -> str:
    """
    Return the sentence(s) most immediately containing the match.
    Uses sentence boundaries (. ! ?) rather than a fixed char window for the
    prior-work detection, so adjacent sections don't bleed in.
    """
    # Find the sentence start: last sentence-ending punctuation before the match
    before = text[:match_start]
    sent_start = max(
        before.rfind(". "),
        before.rfind(".\n"),
        before.rfind("! "),
        before.rfind("? "),
        before.rfind("\n\n"),
    )
    sent_start = sent_start + 1 if sent_start >= 0 else 0

    # Find the sentence end: next sentence-ending punctuation after the match
    after = text[match_end:]
    ends = [after.find(". "), after.find(".\n"), after.find("! "), after.find("? "),
            after.find("\n\n")]
    ends = [e for e in ends if e >= 0]
    sent_end = match_end + (min(ends) + 1 if ends else len(after))

    return text[sent_start:sent_end].replace("\n", " ").strip()


def extract_claims(tex: str) -> list[Claim]:
    """Extract all quantitative claims from LaTeX source."""
    clean = normalize_latex(tex)
    sections = section_index(clean)
    # Dedup on (value, sentence) rather than on value alone. Keying on the
    # value meant the first match anywhere in the paper fixed that number's
    # classification forever: a figure reported in Related Work suppressed the
    # identical number when we later claimed it in Experiments, and vice versa.
    seen: set[tuple[str, str]] = set()
    claims: list[Claim] = []

    for pid, pat in enumerate(CLAIM_PATTERNS):
        for m in pat.finditer(clean):
            val = m.group(1).strip()
            if not val:
                continue

            if pid in GENERIC_PATTERN_IDS:
                # Structural matches: drop small integers and bare years.
                try:
                    f = float(val)
                except ValueError:
                    continue
                if f < 0.5:
                    continue
                if val.isdigit() and 1900 <= int(val) <= 2099:
                    continue

            sentence = _extract_sentence(clean, m.start(), m.end())
            key = (val, sentence[:120])
            if key in seen:
                continue
            seen.add(key)

            is_prior = bool(PRIOR_WORK_CONTEXT.search(sentence))

            # Wider context for the human-readable context snippet
            start_ctx = max(0, m.start() - CONTEXT_WINDOW)
            end_ctx = min(len(clean), m.end() + CONTEXT_WINDOW)
            ctx = clean[start_ctx:end_ctx].replace("\n", " ").strip()

            claims.append(Claim(
                value=val,
                context=ctx,
                pattern_id=pid,
                is_prior_work=is_prior,
                section=section_at(sections, m.start()),
                sentence=sentence,
            ))

    return claims


def find_evidence(value: str, log_text: str) -> str | None:
    """
    Return a snippet from the log containing the given numeric value, or None.
    Matches whole decimal numbers (e.g. "87.4" matches "87.4" but not "87.41").
    """
    pat = re.compile(r"(?<!\d)" + re.escape(value) + r"(?!\d)")
    m = pat.search(log_text)
    if not m:
        return None
    start = max(0, m.start() - 80)
    end = min(len(log_text), m.end() + 80)
    return log_text[start:end].replace("\n", " ").strip()


def write_claim_map(report: dict, path: str) -> None:
    """
    Emit the claim-evidence map: one row per extracted claim, ordered
    unsupported → attributed → supported so the revision agenda reads
    top-down.
    """
    rows: list[tuple[str, ...]] = []
    for item in report["unsupported"]:
        rows.append((item["value"], item.get("section", ""), item["claim"],
                     "—", "**needs evidence**"))
    for item in report["uncertain"]:
        rows.append((item["value"], item.get("section", ""), item["claim"],
                     "cited source", "attributed"))
    for item in report["supported"]:
        rows.append((item["value"], item.get("section", ""), item["claim"],
                     item.get("evidence_snippet", ""), "supported"))

    def cell(s: str, width: int = 160) -> str:
        return s.replace("|", "\\|").replace("\n", " ").strip()[:width]

    lines = [
        "# Claim-Evidence Map",
        "",
        f"{report['summary']['total']} quantitative claims extracted from the draft. ",
        "Rows marked **needs evidence** carry a number that appears nowhere in ",
        "`experimental_log.md` and carries no citation — verify, attribute, or remove.",
        "",
        "| Value | Section | Claim | Evidence | Status |",
        "|---|---|---|---|---|",
    ]
    for value, section, claim, evidence, status in rows:
        lines.append(f"| `{value}` | {cell(section, 40)} | {cell(claim)} | {cell(evidence, 80)} | {status} |")
    lines.append("")

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines))


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--paper", required=True, help="Path to paper.tex (draft)")
    p.add_argument("--log",   required=True, help="Path to experimental_log.md")
    p.add_argument("--out",   required=True, help="Output path for claim_evidence_report.json")
    p.add_argument("--out-md", help="Optional path for the human-readable claim-evidence map (markdown)")
    args = p.parse_args()

    for path in (args.paper, args.log):
        if not os.path.exists(path):
            print(f"ERROR: file not found: {path}", file=sys.stderr)
            return 2

    with open(args.paper) as f:
        tex = f.read()
    with open(args.log) as f:
        log_text = f.read()

    claims = extract_claims(tex)

    supported: list[dict] = []
    unsupported: list[dict] = []
    uncertain: list[dict] = []

    for c in claims:
        evidence = find_evidence(c.value, log_text)

        if c.is_prior_work:
            uncertain.append({
                "claim": c.sentence[:300] or c.context[:200],
                "value": c.value,
                "section": c.section,
                "context": c.context,
                "reason": "sentence carries a citation or prior-work cue — attributed, not claimed",
            })
        elif evidence is not None:
            supported.append({
                "claim": c.sentence[:300] or c.context[:200],
                "value": c.value,
                "section": c.section,
                "context": c.context,
                "evidence_snippet": evidence,
            })
        else:
            unsupported.append({
                "claim": c.sentence[:300] or c.context[:200],
                "value": c.value,
                "section": c.section,
                "context": c.context,
            })

    report = {
        "supported":   supported,
        "unsupported": unsupported,
        "uncertain":   uncertain,
        "summary": {
            "total":       len(claims),
            "supported":   len(supported),
            "unsupported": len(unsupported),
            "uncertain":   len(uncertain),
        },
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    if args.out_md:
        write_claim_map(report, args.out_md)

    s = report["summary"]
    print(f"Claim-evidence gate: {s['total']} claims extracted")
    print(f"  supported:   {s['supported']}")
    print(f"  unsupported: {s['unsupported']}")
    print(f"  attributed:  {s['uncertain']}  (cited to another paper)")

    if unsupported:
        print("\nUNSUPPORTED claims (not found in experimental_log.md):")
        for item in unsupported:
            print(f"  [{item['value']}] {item['claim'][:120]}")
        print(f"\nWARN: {len(unsupported)} unsupported claim(s) — review before submission.")
        print(f"Full report: {args.out}")
        return 1

    print(f"PASS — all extracted claims are corroborated by experimental_log.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
