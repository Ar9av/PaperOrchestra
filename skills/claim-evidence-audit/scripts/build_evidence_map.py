#!/usr/bin/env python3
"""
build_evidence_map.py — map each claim to evidence (deterministic).

Evidence kinds:
  log_number     claim number matches a number in experimental_log.md
  log_table_row  ... and the match sits in a markdown table row
  figure         claim \\ref's a label that sits in a figure environment
  table          claim \\ref's a label that sits in a table environment
  citation       claim \\cite's a key present in the verified .bib

Claim status:
  supported   every non-trivial number matched the log, or the claim has other
              evidence (figure/table/verified citation) and no unmatched numbers
              that lack a citation to attribute them to
  partial     some evidence, but at least one number is unmatched and nothing
              else accounts for it (or the only citation was judged
              partially_supported)
  unmapped    no usable evidence

An optional --audit file (host agent's cited-source verdicts, see
references/citation-audit.md) overrides citation evidence:
  not_supported        citation evidence rejected
  partially_supported  citation evidence downgraded
  supported / cannot_verify  kept (cannot_verify stays flagged)

Usage:
    python build_evidence_map.py --claims workspace/claim_audit/claims.json \\
        --log workspace/inputs/experimental_log.md --bib workspace/refs.bib \\
        --paper workspace/drafts/paper.tex \\
        --out-json workspace/claim_audit/claim_evidence_map.json \\
        --out-md   workspace/claim_audit/claim_evidence_map.md \\
        [--audit workspace/claim_audit/citation_audit.json]

Exit codes: 0 map written, 2 input missing/unreadable. Coverage is judged
separately by coverage_gate.py.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claimlib as cl  # noqa: E402

VERDICTS = ("supported", "partially_supported", "not_supported", "cannot_verify")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def match_numbers(claim_numbers, log_numbers, abs_tol, rel_tol):
    """Return (evidence list, unmatched numbers)."""
    evidence, unmatched = [], []
    for n in claim_numbers:
        if n.get("trivial"):
            continue
        hit = next((l for l in log_numbers if cl.numbers_match(n, l, abs_tol, rel_tol)), None)
        if hit is None:
            unmatched.append(n["raw"])
            continue
        kind = "log_table_row" if hit["in_table"] else "log_number"
        evidence.append({
            "kind": kind, "detail": f"{n['raw']} ~ {hit['raw']}",
            "locator": f"experimental_log.md:{hit['line']}",
            "excerpt": hit["row"][:160],
        })
    return evidence, unmatched


def build(claims_doc, log_text, bib_keys, labels, audit, abs_tol=0.0, rel_tol=0.0):
    log_numbers = cl.parse_log(log_text) if log_text else []
    audits = {}
    for a in (audit or {}).get("audits", []):
        audits.setdefault((a["claim_id"], a["cite_key"]), a)
    entries = []
    for c in claims_doc["claims"]:
        ev, unmatched = match_numbers(c.get("numbers", []), log_numbers, abs_tol, rel_tol)
        for ref in c.get("refs", []):
            info = labels.get(ref)
            if info and info["env"] in ("figure", "table"):
                ev.append({"kind": info["env"], "detail": ref,
                           "locator": f"paper.tex:{info['line']}",
                           "excerpt": ", ".join(info["files"])[:160]})
        missing_keys, needs_audit = [], False
        for key in c.get("cite_keys", []):
            if key not in bib_keys:
                missing_keys.append(key)
                continue
            e = {"kind": "citation", "detail": key, "locator": "refs.bib", "excerpt": ""}
            a = audits.get((c["id"], key))
            if a:
                e["audit_verdict"] = a["verdict"]
                e["audit_locator"] = a.get("locator")
                if a["verdict"] == "not_supported":
                    e["rejected"] = True
                elif a["verdict"] == "cannot_verify":
                    needs_audit = True
            else:
                needs_audit = True
            ev.append(e)
        usable = [e for e in ev if not e.get("rejected")]
        cite_ok = [e for e in usable if e["kind"] == "citation"]
        cite_full = [e for e in cite_ok if e.get("audit_verdict") != "partially_supported"]
        other = [e for e in usable if e["kind"] != "citation"]
        if not usable:
            status = "unmapped"
        elif unmatched and not cite_full:
            status = "partial"  # a number nothing accounts for
        elif cite_ok and not cite_full and not other:
            status = "partial"  # only a partially_supported citation
        else:
            status = "supported"
        entries.append({
            "claim_id": c["id"], "text": c["text"], "section": c["section"],
            "line": c["line"], "types": c["types"], "status": status,
            "evidence": ev, "unmatched_numbers": unmatched,
            "missing_bib_keys": missing_keys,
            "needs_citation_audit": bool(c.get("cite_keys")) and needs_audit,
        })
    return {"version": 1, "claims": entries, "summary": summarize(entries)}


def summarize(entries):
    total = len(entries)
    s = {"total": total}
    for st in ("supported", "partial", "unmapped"):
        s[st] = sum(1 for e in entries if e["status"] == st)
    s["coverage_pct"] = round(100.0 * s["supported"] / total, 1) if total else 100.0
    s["needs_citation_audit"] = sum(1 for e in entries if e["needs_citation_audit"])
    return s


def to_markdown(doc):
    order = {"unmapped": 0, "partial": 1, "supported": 2}
    rows = sorted(doc["claims"], key=lambda e: (order[e["status"]], e["line"]))
    s = doc["summary"]
    out = ["# Claim-Evidence Map", "",
           f"Claims: {s['total']} | supported: {s['supported']} | partial: {s['partial']} | "
           f"unmapped: {s['unmapped']} | coverage: {s['coverage_pct']}%", "",
           "| ID | Status | Section:Line | Claim | Evidence | Flags |", "|---|---|---|---|---|---|"]
    for e in rows:
        ev = "; ".join(f"{x['kind']}:{x['detail']}" + (" (rejected)" if x.get("rejected") else "")
                       for x in e["evidence"]) or "-"
        flags = []
        if e["unmatched_numbers"]:
            flags.append("unmatched: " + ", ".join(e["unmatched_numbers"]))
        if e["missing_bib_keys"]:
            flags.append("not in bib: " + ", ".join(e["missing_bib_keys"]))
        if e["needs_citation_audit"]:
            flags.append("citation audit pending")
        text = e["text"].replace("|", "\\|")
        if len(text) > 140:
            text = text[:137] + "..."
        out.append(f"| {e['claim_id']} | {e['status']} | {e['section']}:{e['line']} | {text} | "
                   f"{ev.replace('|', '/')} | {'; '.join(flags) or '-'} |")
    out += ["", "Unmapped and partial claims must be softened, removed, or backed by real "
            "evidence. Never invent evidence.", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--claims", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--bib", required=True)
    ap.add_argument("--paper", required=True, help="draft .tex, used to resolve \\label/\\ref")
    ap.add_argument("--audit", help="citation_audit.json from the host agent (optional)")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    ap.add_argument("--abs-tol", type=float, default=0.0, help="extra absolute tolerance (default 0)")
    ap.add_argument("--rel-tol", type=float, default=0.0, help="extra relative tolerance (default 0)")
    args = ap.parse_args()
    try:
        claims_doc = load_json(args.claims)
        log_text, bib_text, tex = read(args.log), read(args.bib), read(args.paper)
        audit = load_json(args.audit) if args.audit else None
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    labels = cl.scan_tex(tex)["labels"]
    doc = build(claims_doc, log_text, cl.parse_bib_keys(bib_text), labels, audit,
                args.abs_tol, args.rel_tol)
    for p in (args.out_json, args.out_md):
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write(to_markdown(doc))
    s = doc["summary"]
    print(f"Mapped {s['total']} claims: supported={s['supported']} partial={s['partial']} "
          f"unmapped={s['unmapped']} coverage={s['coverage_pct']}%")
    print(f"  -> {args.out_json}\n  -> {args.out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
