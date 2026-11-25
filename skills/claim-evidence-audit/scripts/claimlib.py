#!/usr/bin/env python3
"""
claimlib.py — shared deterministic helpers for the claim-evidence-audit skill.

Stdlib only. No network, no LLM. Provides:
  - scan_tex():       line-aware LaTeX scan (section, environment, labels)
  - split_sentences(): sentence splitter that keeps the starting line number
  - parse_numbers():  number extraction with %, thousands separators, decimals
  - numbers_match():  rounding-aware comparison of a paper number to a log number
  - parse_log():      numbers (with line + table-row context) from experimental_log.md
  - parse_bib_keys(): keys present in a .bib file
"""
import bisect
import re

# Environments whose contents are not prose.
MATH_ENVS = {"equation", "equation*", "align", "align*", "eqnarray", "eqnarray*",
             "gather", "gather*", "multline", "multline*", "displaymath", "math"}
TABULAR_ENVS = {"tabular", "tabular*", "tabularx", "longtable", "array"}
OTHER_SKIP_ENVS = {"verbatim", "lstlisting", "minted", "thebibliography",
                   "algorithmic", "algorithm", "tikzpicture"}
FLOAT_ENVS = {"figure", "figure*", "table", "table*"}

TRIVIAL_INT_MAX = 10  # plain integers <= this are "trivial" (counts, indices)

SECTION_RE = re.compile(r"\\(section|subsection|subsubsection)\*?\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
ENV_RE = re.compile(r"\\(begin|end)\{([^}]+)\}")
LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
CITE_RE = re.compile(
    r"\\(?:cite|citep|citet|citealp|citealt|citeauthor|citeyear|autocite|parencite|textcite)\*?"
    r"(?:\[[^\]]*\]){0,2}\{([^}]+)\}")
REF_RE = re.compile(r"\\(?:ref|Cref|cref|autoref|eqref|pageref)\*?\{([^}]+)\}")
COMMENT_RE = re.compile(r"(?<!\\)%.*$")
BIB_KEY_RE = re.compile(r"^\s*@(?!comment|string|preamble)\w+\s*\{\s*([^,\s]+)\s*,", re.M | re.I)

ABBREV_RE = re.compile(r"\b(et al|e\.g|i\.e|Fig|Figs|Tab|vs|Eq|Eqs|Sec|cf|approx|etc|Dr|No|Ref|Refs)\.")
CONTEXT_WORD_RE = re.compile(
    r"(?:Table|Tab\.|Figure|Fig\.|Figs\.|Section|Sec\.|Eq\.|Equation|Appendix|Algorithm|"
    r"Theorem|Lemma|Step|Phase|Stage|Part|Chapter|Line|Page|pp\.|p\.)\s*[~\s]*\(?$", re.I)

NUM_RE = re.compile(
    r"(?<![A-Za-z]-)(?<![A-Za-z_\d.,])"
    r"(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<frac>\.\d+)?"
    r"(?P<pct>\s*(?:%|percent\b))?")


def strip_comment(line: str) -> str:
    return COMMENT_RE.sub("", line)


def split_keys(blob: str) -> list:
    return [k.strip() for k in blob.split(",") if k.strip()]


# ── LaTeX scan ────────────────────────────────────────────────────────────────

def scan_tex(tex: str) -> dict:
    """Line-aware scan.

    Returns {"lines": [ {line, section, text, envs, prose} ... ],
             "labels": {label: {env, line, files}}}.
    `text` is the comment-stripped line. `envs` is the set of environment names
    open on that line. Lines in the preamble are omitted. `section` is the
    current \\section title ("Abstract" inside the abstract environment,
    "(preamble)" never appears because the preamble is skipped).
    """
    raw_lines = tex.splitlines()
    has_doc = any("\\begin{document}" in l for l in raw_lines)
    in_doc = not has_doc
    section = "(front matter)"
    stack = []  # list of dicts {name, files}
    labels = {}
    out = []
    for i, raw in enumerate(raw_lines, 1):
        text = strip_comment(raw)
        if not in_doc:
            if "\\begin{document}" in text:
                in_doc = True
            continue
        opened_here = set()
        pos_events = []
        for m in ENV_RE.finditer(text):
            pos_events.append((m.start(), "env", m))
        for m in SECTION_RE.finditer(text):
            pos_events.append((m.start(), "sec", m))
        for m in LABEL_RE.finditer(text):
            pos_events.append((m.start(), "label", m))
        for m in GRAPHICS_RE.finditer(text):
            pos_events.append((m.start(), "gfx", m))
        pos_events.sort(key=lambda e: e[0])
        envs_at_start = {e["name"] for e in stack}
        for _, kind, m in pos_events:
            if kind == "env":
                name = m.group(2)
                if m.group(1) == "begin":
                    stack.append({"name": name, "files": []})
                    opened_here.add(name)
                    if name == "abstract":
                        section = "Abstract"
                else:
                    for j in range(len(stack) - 1, -1, -1):
                        if stack[j]["name"] == name:
                            del stack[j:]
                            break
                    if name == "abstract":
                        section = "(front matter)"
            elif kind == "sec":
                section = m.group(2).strip()
            elif kind == "gfx":
                for e in reversed(stack):
                    if e["name"] in FLOAT_ENVS:
                        e["files"].append(m.group(1))
                        break
            elif kind == "label":
                float_env = next((e for e in reversed(stack) if e["name"] in FLOAT_ENVS), None)
                labels[m.group(1)] = {
                    "env": (float_env["name"].rstrip("*") if float_env else
                            (stack[-1]["name"] if stack else "text")),
                    "line": i,
                    "files": float_env["files"] if float_env else [],
                }
        envs = envs_at_start | opened_here
        skip = MATH_ENVS | TABULAR_ENVS | OTHER_SKIP_ENVS
        out.append({"line": i, "section": section, "text": text,
                    "envs": envs, "prose": not (envs & skip)})
        if "\\end{document}" in text:
            break
    return {"lines": out, "labels": labels}


# ── sentences ─────────────────────────────────────────────────────────────────

def _paragraphs(lines):
    """Group consecutive prose lines of the same section into paragraphs."""
    para, last = [], None
    for ln in lines:
        stripped = ln["text"].strip()
        boundary = (not ln["prose"]) or not stripped or (last is not None and ln["section"] != last)
        if boundary and para:
            yield para
            para = []
        if ln["prose"] and stripped:
            para.append(ln)
            last = ln["section"]
        elif not stripped:
            last = None
    if para:
        yield para


def split_sentences(lines: list) -> list:
    """Return [(sentence_text, start_line, section)] for prose lines."""
    results = []
    for para in _paragraphs(lines):
        parts, starts, pos = [], [], 0
        for ln in para:
            t = SECTION_RE.sub("", ln["text"]).strip()
            t = re.sub(r"^\\(?:begin|end)\{[^}]*\}", "", t).strip()
            if not t:
                continue
            starts.append((pos, ln["line"]))
            parts.append(t)
            pos += len(t) + 1
        joined = " ".join(parts)
        if not joined.strip():
            continue
        protected = ABBREV_RE.sub(lambda m: m.group(0).replace(".", "\x00"), joined)
        offsets = [s for s, _ in starts]
        lnums = [l for _, l in starts]
        begin = 0
        for m in re.finditer(r"[.!?](?=\s+(?:[A-Z\\$(\[]|$))|[.!?]$", protected):
            end = m.end()
            _emit(results, joined, begin, end, offsets, lnums, para[0]["section"])
            begin = end
        if begin < len(joined):
            _emit(results, joined, begin, len(joined), offsets, lnums, para[0]["section"])
    return results


def _emit(results, joined, begin, end, offsets, lnums, section):
    chunk = joined[begin:end]
    lead = len(chunk) - len(chunk.lstrip())
    sent = re.sub(r"\s+", " ", chunk).strip()
    if len(sent) < 3:
        return
    idx = bisect.bisect_right(offsets, begin + lead) - 1
    results.append((sent, lnums[max(idx, 0)], section))


# ── numbers ───────────────────────────────────────────────────────────────────

def normalize_for_numbers(text: str) -> str:
    t = CITE_RE.sub(" ", text)
    t = REF_RE.sub(" ", t)
    t = re.sub(r"\\(?:label|url|href|includegraphics|input|bibliography|bibliographystyle)"
               r"(?:\[[^\]]*\])?\{[^}]*\}", " ", t)
    t = t.replace("{,}", ",").replace("\\%", "%")
    t = re.sub(r"\\[,;:! ]|~", " ", t)
    t = t.replace("$", "")
    return t


def parse_numbers(text: str) -> list:
    """Extract numeric mentions from LaTeX text.

    Each: {raw, value, percent, decimals, trivial}. Years, and numbers that
    follow 'Table', 'Figure', 'Section', ... are skipped.
    """
    t = normalize_for_numbers(text)
    found = []
    for m in NUM_RE.finditer(t):
        if CONTEXT_WORD_RE.search(t[:m.start()]):
            continue
        ipart = m.group("int").replace(",", "")
        frac = m.group("frac") or ""
        pct = bool(m.group("pct"))
        if not frac and not pct and "," not in m.group("int") and len(ipart) == 4 \
                and 1900 <= int(ipart) <= 2100:
            continue  # year
        value = float(ipart + frac)
        decimals = len(frac) - 1 if frac else 0
        trivial = (not frac and not pct and value <= TRIVIAL_INT_MAX)
        found.append({"raw": (m.group(0)).strip(), "value": value, "percent": pct,
                      "decimals": decimals, "trivial": trivial})
    return found


def numbers_match(p: dict, l: dict, abs_tol: float = 0.0, rel_tol: float = 0.0) -> bool:
    """Does paper number `p` agree with log number `l`?

    The paper is allowed to round the log value to the paper's own precision
    (|p - l| <= 0.5 * 10^-decimals(p)). Percent/fraction forms are reconciled:
    paper 87.4% (or a bare 87.4 in a table) matches log 0.874; paper 0.874 matches log 87.4%. The paper may
    NOT claim more precision than the log (paper 87.43 does not match log 87.4).
    """
    half = 0.5 * 10 ** (-p["decimals"])
    cands = [l["value"]]
    if not l["percent"] and l["value"] <= 1.0 and (p["percent"] or p["value"] > 1.0):
        cands.append(l["value"] * 100)  # log stores a fraction, paper a percentage
    if not p["percent"] and l["percent"]:
        cands.append(l["value"] / 100)
    for v in cands:
        if abs(p["value"] - v) <= half + 1e-9 + abs_tol + rel_tol * abs(v):
            return True
    return False


# ── experimental log ──────────────────────────────────────────────────────────

def parse_log(text: str) -> list:
    """Numbers in the experimental log: [{line, value, percent, decimals, raw,
    in_table, row}]. Markdown table separator rows are skipped."""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", s):
            continue
        in_table = s.startswith("|") and s.count("|") >= 2
        for n in parse_numbers(line.replace("*", "")):
            n = dict(n)
            n.update({"line": i, "in_table": in_table, "row": s if in_table else s[:200]})
            out.append(n)
    return out


def parse_bib_keys(bib: str) -> set:
    return set(BIB_KEY_RE.findall(bib))
