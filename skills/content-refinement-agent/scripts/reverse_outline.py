#!/usr/bin/env python3
"""
reverse_outline.py — Build a reverse outline of a LaTeX draft.

Reverse outlining is the check that catches structural problems prose-level
review misses: strip the paper down to one line per paragraph — its topic
sentence — and read only those lines. If the result does not read as an
argument, the paper does not have one, however well-written its sentences are.

This script does the mechanical half (extraction and smell detection) so the
reviewer call spends its attention on the judgment half (does this sequence of
topic sentences support the paper's thesis?).

Flags raised per paragraph:

  no-topic-sentence   First sentence is too short to carry a message, or opens
                      on a connective (However, Moreover, Furthermore...) —
                      a continuation word as an opener means the message lives
                      somewhere further down the paragraph.
  overlong            More than --max-sentences sentences or --max-words words.
                      Long paragraphs carry more than one message by default.
  multi-pivot         Two or more contrastive pivots (however, in contrast, on
                      the other hand). Each pivot is a change of direction; two
                      of them in one paragraph is two messages.
  orphan              A single-sentence paragraph. Either it belongs to a
                      neighbour or it is a heading in disguise.
  citation-dump       More citations than sentences. Characteristic of Related
                      Work paragraphs that list papers instead of positioning
                      against them.

Exit codes:
    0 — outline written; no flags, or advisory mode (default)
    1 — flags present and --strict was passed
    2 — input file missing or unreadable

Usage:
    python reverse_outline.py --paper workspace/drafts/paper.tex \\
        --out workspace/reverse_outline.md [--json workspace/reverse_outline.json] [--strict]
"""
import argparse
import json
import os
import re
import sys

# Environments whose contents are not prose and must not become paragraphs.
DROP_ENVIRONMENTS = [
    "figure", "figure*", "table", "table*", "tabular", "tabularx",
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "itemize", "enumerate", "description", "algorithm", "algorithmic",
    "lstlisting", "verbatim", "thebibliography",
]

CONNECTIVE_OPENERS = re.compile(
    r"^(?:however|moreover|furthermore|additionally|in addition|also|"
    r"therefore|thus|hence|consequently|as a result|that is|in other words|"
    r"for example|for instance|similarly|likewise|finally|then)\b",
    re.IGNORECASE,
)

PIVOTS = re.compile(
    r"\b(?:however|in contrast|by contrast|on the other hand|conversely|"
    r"nevertheless|nonetheless|whereas|although|yet)\b",
    re.IGNORECASE,
)

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\\$])")


def preprocess(tex: str) -> str:
    """
    Strip everything that is not body prose, while keeping sectioning intact.

    Runs before section splitting: the preamble defines colors and hyperref
    metadata that otherwise parse as paragraphs, and float/list environments
    contribute text belonging to no paragraph.
    """
    tex = re.sub(r"(?<!\\)%.*$", "", tex, flags=re.MULTILINE)
    parts = re.split(r"\\begin\{document\}", tex, maxsplit=1)
    tex = parts[1] if len(parts) > 1 else tex
    tex = re.split(r"\\end\{document\}", tex, maxsplit=1)[0]
    tex = re.split(r"\\bibliography\{|\\begin\{thebibliography\}", tex, maxsplit=1)[0]

    for env in DROP_ENVIRONMENTS:
        tex = re.sub(r"\\begin\{" + re.escape(env) + r"\}.*?\\end\{" + re.escape(env) + r"\}",
                     " ", tex, flags=re.DOTALL)

    # The abstract is a section for outlining purposes.
    tex = re.sub(r"\\begin\{abstract\}", r"\\section{Abstract}", tex)
    tex = re.sub(r"\\end\{abstract\}", " ", tex)
    return tex


def flatten(body: str) -> str:
    """Flatten LaTeX markup inside one section body into readable prose."""
    body = re.sub(r"\\cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{[^}]*\}", "[CITE]", body)
    body = re.sub(r"\\(?:label|ref|cref|Cref|autoref|includegraphics|usepackage|"
                  r"documentclass|bibliographystyle|bibliography|input|vspace|hspace|"
                  r"definecolor|hypersetup|newcommand|renewcommand|setlength)"
                  r"\*?(?:\[[^\]]*\])?\{[^}]*\}", " ", body)
    body = re.sub(r"\\(?:emph|textbf|textit|texttt|underline|textsc)\{([^{}]*)\}", r"\1", body)
    body = re.sub(r"\$[^$]*\$", " NUM ", body)
    body = body.replace("\\%", "%").replace("~", " ")
    body = re.sub(r"\\[a-zA-Z]+\*?", " ", body)
    body = re.sub(r"[{}]", " ", body)
    return body


def split_sections(tex: str) -> list[tuple[str, str]]:
    """Return [(heading, flattened body)] for every sectioning command."""
    marks = list(re.finditer(r"\\(sub)*section\*?\{([^}]*)\}", tex))
    if not marks:
        return [("(whole document)", flatten(tex))]
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(tex)
        depth = m.group(0).count("sub")
        title = ("— " * depth) + m.group(2).strip()
        out.append((title, flatten(tex[m.end():end])))
    return out


def sentences(paragraph: str) -> list[str]:
    """
    Split into sentences, merging run-in headings forward.

    "\\textbf{Policy engine.} The engine evaluates..." is one sentence with a
    bold lead-in, not a two-word sentence followed by a real one. Flattening
    drops the boldness, so short fragments ending in a period are re-attached
    to what follows — otherwise every run-in heading in the paper reports as a
    missing topic sentence.
    """
    raw = [s.strip() for s in SENTENCE_SPLIT.split(paragraph.strip()) if s.strip()]
    merged: list[str] = []
    carry = ""
    for s in raw:
        s = (carry + " " + s).strip() if carry else s
        carry = ""
        if len(s.split()) <= 5:
            carry = s
            continue
        merged.append(s)
    if carry:
        merged.append(carry)
    return merged


def analyze_paragraph(text: str, max_sentences: int, max_words: int) -> dict | None:
    sents = sentences(text)
    if not sents:
        return None
    words = len(text.split())
    if words < 15:                      # stray fragment, not a paragraph
        return None

    topic = sents[0]
    citations = text.count("[CITE]")
    flags = []

    if len(topic.split()) < 6 or CONNECTIVE_OPENERS.match(topic):
        flags.append("no-topic-sentence")
    if len(sents) > max_sentences or words > max_words:
        flags.append("overlong")
    if len(PIVOTS.findall(text)) >= 2:
        flags.append("multi-pivot")
    # A single-sentence paragraph usually belongs to a neighbour — but a long
    # single sentence is a paragraph doing its job in one breath.
    if len(sents) == 1 and words < 60:
        flags.append("orphan")
    if citations > len(sents):
        flags.append("citation-dump")

    return {
        "topic_sentence": re.sub(r"\s+", " ", topic)[:300],
        "sentences": len(sents),
        "words": words,
        "citations": citations,
        "flags": flags,
    }


def build_outline(tex: str, max_sentences: int, max_words: int) -> list[dict]:
    outline = []
    for title, body in split_sections(preprocess(tex)):
        paragraphs = []
        for chunk in re.split(r"\n\s*\n", body):
            p = analyze_paragraph(chunk, max_sentences, max_words)
            if p:
                paragraphs.append(p)
        if paragraphs:
            outline.append({"section": title, "paragraphs": paragraphs})
    return outline


def render_markdown(outline: list[dict]) -> str:
    total = sum(len(s["paragraphs"]) for s in outline)
    flagged = sum(1 for s in outline for p in s["paragraphs"] if p["flags"])
    lines = [
        "# Reverse Outline",
        "",
        f"{total} paragraphs across {len(outline)} sections; {flagged} carry a structural flag.",
        "",
        "Read the topic sentences alone, in order, ignoring everything else. If that",
        "sequence does not read as an argument, the fix is structural — reordering,",
        "merging, or cutting paragraphs — not sentence-level editing.",
        "",
    ]
    for sec in outline:
        lines.append(f"## {sec['section']}")
        lines.append("")
        for i, p in enumerate(sec["paragraphs"], 1):
            flag = f"  `{' '.join(p['flags'])}`" if p["flags"] else ""
            lines.append(f"{i}. {p['topic_sentence']}{flag}")
            lines.append(f"   _{p['sentences']} sentences, {p['words']} words"
                         + (f", {p['citations']} citations_" if p["citations"] else "_"))
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--paper", required=True, help="Path to the LaTeX draft")
    ap.add_argument("--out", required=True, help="Output path for the markdown reverse outline")
    ap.add_argument("--json", help="Optional output path for the machine-readable outline")
    ap.add_argument("--max-sentences", type=int, default=8)
    ap.add_argument("--max-words", type=int, default=220)
    ap.add_argument("--strict", action="store_true",
                    help="Exit 1 when any paragraph carries a flag")
    args = ap.parse_args()

    if not os.path.exists(args.paper):
        print(f"ERROR: file not found: {args.paper}", file=sys.stderr)
        return 2

    with open(args.paper) as f:
        tex = f.read()

    outline = build_outline(tex, args.max_sentences, args.max_words)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        f.write(render_markdown(outline))
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"sections": outline}, f, indent=2, ensure_ascii=False)

    total = sum(len(s["paragraphs"]) for s in outline)
    counts: dict[str, int] = {}
    for sec in outline:
        for p in sec["paragraphs"]:
            for fl in p["flags"]:
                counts[fl] = counts.get(fl, 0) + 1

    print(f"Reverse outline: {len(outline)} sections, {total} paragraphs → {args.out}")
    if counts:
        for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"  {name}: {n}")
    else:
        print("  no structural flags")

    return 1 if (counts and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
