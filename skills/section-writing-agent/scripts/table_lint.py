#!/usr/bin/env python3
"""
table_lint.py — Check LaTeX tables against the conventions in
references/latex-table-patterns.md.

Tables are the first thing a reviewer looks at and the last thing a generated
draft gets right. The failures are mechanical and therefore checkable: vertical
rules, \\hline stacks, captions below the tabular, metric columns with no
direction marker, mixed decimal precision down a column.

Severity:
  ERROR — violates a booktabs/LaTeX rule the prompt states outright
  WARN  — violates a readability convention a reviewer will notice

Exit codes:
    0 — no ERRORs (and no WARNs, if --strict)
    1 — at least one ERROR, or any WARN under --strict
    2 — input file missing or unreadable

Usage:
    python table_lint.py workspace/drafts/paper.tex [--json report.json] [--strict]
"""
import argparse
import json
import os
import re
import sys

METRIC_ARROWS = ("↑", "↓", r"\uparrow", r"\downarrow", r"\textuparrow", r"\textdownarrow")

RULE_MACROS = ("\\toprule", "\\midrule", "\\bottomrule", "\\cmidrule", "\\hline", "\\cline")


def find_tables(tex: str) -> list[dict]:
    """Return one record per table/table* environment."""
    out = []
    for m in re.finditer(r"\\begin\{(table\*?)\}(.*?)\\end\{\1\}", tex, re.DOTALL):
        out.append({
            "env": m.group(1),
            "body": m.group(2),
            "start": m.start(),
            "line": tex[:m.start()].count("\n") + 1,
        })
    return out


def strip_cell(cell: str) -> str:
    cell = re.sub(r"\\(?:textbf|textit|emph|texttt|underline|mathbf)\{([^{}]*)\}", r"\1", cell)
    cell = re.sub(r"\\cellcolor\{[^}]*\}|\\rowcolor\{[^}]*\}", " ", cell)
    cell = re.sub(r"\\multicolumn\{\d+\}\{[^}]*\}\{([^{}]*)\}", r"\1", cell)
    cell = cell.replace("$", "").replace("~", " ").replace("\\%", "%").replace("\\&", "&")
    cell = re.sub(r"\\[a-zA-Z]+\*?", " ", cell)
    return cell.strip(" {}")


NUMERIC = re.compile(r"^[+-]?\d+(?:\.\d+)?%?$")


def is_numeric(cell: str) -> bool:
    return bool(NUMERIC.match(strip_cell(cell).replace(",", "")))


def decimals(cell: str) -> int:
    body = strip_cell(cell).replace(",", "").rstrip("%")
    return len(body.split(".")[1]) if "." in body else 0


def split_rows(tabular_body: str) -> list[list[str]]:
    rows = []
    for raw in re.split(r"\\\\", tabular_body):
        line = raw
        for macro in RULE_MACROS:
            line = re.sub(re.escape(macro) + r"(?:\([^)]*\))?(?:\{[^}]*\})?", " ", line)
        if not line.strip():
            continue
        rows.append([c for c in re.split(r"(?<!\\)&", line)])
    return rows


def lint_table(t: dict, after_conclusion: bool) -> list[dict]:
    findings: list[dict] = []
    body = t["body"]

    def add(sev: str, code: str, msg: str) -> None:
        findings.append({"severity": sev, "code": code, "line": t["line"],
                         "env": t["env"], "message": msg})

    tab = re.search(r"\\begin\{(tabular\*?|tabularx|tabulary)\}(?:\{[^}]*\})?\{([^}]*)\}(.*?)"
                    r"\\end\{\1\}", body, re.DOTALL)
    if not tab:
        add("ERROR", "no-tabular", "table environment contains no tabular")
        return findings

    colspec, rows_src = tab.group(2), tab.group(3)

    if "|" in colspec:
        add("ERROR", "vertical-rule",
            f"column spec {{{colspec}}} uses vertical rules; booktabs forbids them")
    if "\\hline" in body or "\\cline" in body:
        add("ERROR", "hline", "uses \\hline/\\cline; use \\toprule/\\midrule/\\bottomrule")
    if "\\toprule" not in body or "\\bottomrule" not in body:
        add("ERROR", "missing-rules", "missing \\toprule and/or \\bottomrule")

    cap = body.find("\\caption")
    tab_start = body.find("\\begin{" + tab.group(1))
    if cap == -1:
        add("ERROR", "no-caption", "table has no \\caption")
    elif cap > tab_start:
        add("ERROR", "caption-below",
            "\\caption appears after the tabular; table captions go above")
    else:
        caption_text = strip_cell(body[cap:body.find("\n\\label") if "\\label" in body else cap + 400])
        words = len(re.sub(r"^caption", "", caption_text, flags=re.I).split())
        if words < 6:
            add("WARN", "thin-caption",
                f"caption is {words} words; state the setting, protocol, and notation")

    if "\\label" not in body:
        add("WARN", "no-label", "table has no \\label, so it cannot be cross-referenced")

    if after_conclusion:
        add("WARN", "late-table",
            "table appears after the Conclusion; the prompt requires tables before it")

    # ── column-level checks ────────────────────────────────────────────────
    rows = split_rows(rows_src)
    if len(rows) < 2:
        return findings
    header, data = rows[0], rows[1:]
    width = len(header)

    for col in range(width):
        cells = [r[col] for r in data if len(r) == width]
        numeric = [c for c in cells if is_numeric(c)]
        if not cells or len(numeric) < max(2, int(0.8 * len(cells))):
            continue  # not a numeric metric column

        head = header[col] if col < len(header) else ""
        if not any(a in head for a in METRIC_ARROWS):
            add("WARN", "no-metric-direction",
                f"numeric column {col + 1} ({strip_cell(head)!r}) has no ↑/↓ marker; "
                "a reviewer should not have to infer which direction is better")

        precisions = {decimals(c) for c in numeric}
        if len(precisions) > 1:
            add("WARN", "mixed-precision",
                f"numeric column {col + 1} ({strip_cell(head)!r}) mixes decimal precision "
                f"{sorted(precisions)}; keep it constant within a metric column")

    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paper", help="Path to the LaTeX draft")
    ap.add_argument("--json", help="Optional path for the machine-readable report")
    ap.add_argument("--strict", action="store_true", help="Exit 1 on WARNs too")
    args = ap.parse_args()

    if not os.path.exists(args.paper):
        print(f"ERROR: file not found: {args.paper}", file=sys.stderr)
        return 2
    with open(args.paper) as f:
        tex = f.read()

    concl = re.search(r"\\section\*?\{\s*Conclusion", tex, re.IGNORECASE)
    concl_at = concl.start() if concl else len(tex)

    tables = find_tables(tex)
    findings: list[dict] = []
    for t in tables:
        findings.extend(lint_table(t, after_conclusion=t["start"] > concl_at))

    errors = [f for f in findings if f["severity"] == "ERROR"]
    warns = [f for f in findings if f["severity"] == "WARN"]

    print(f"table_lint: {len(tables)} table(s), {len(errors)} error(s), {len(warns)} warning(s)")
    for f in findings:
        print(f"  {f['severity']:5s} line {f['line']:>5} [{f['code']}] {f['message']}")

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)) or ".", exist_ok=True)
        with open(args.json, "w") as fh:
            json.dump({"tables": len(tables), "findings": findings}, fh, indent=2,
                      ensure_ascii=False)

    if errors or (warns and args.strict):
        return 1
    if not findings:
        print("OK: all tables follow the booktabs conventions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
