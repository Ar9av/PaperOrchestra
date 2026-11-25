#!/usr/bin/env python3
"""
validate_schema.py — schema validation for claims.json, claim_evidence_map.json
and citation_audit.json (stdlib only; no jsonschema dependency).

Usage:
    python validate_schema.py [--claims claims.json] [--map claim_evidence_map.json]
                              [--audit citation_audit.json]

When --claims and --map are both given, claim ids must agree between them.
Exit codes: 0 valid, 1 schema violations, 2 file missing / not JSON.
"""
import argparse
import json
import re
import sys

CLAIM_TYPES = {"numeric_result", "comparison", "show_claim", "cited_fact"}
STATUSES = {"supported", "partial", "unmapped"}
EVIDENCE_KINDS = {"log_number", "log_table_row", "figure", "table", "citation"}
VERDICTS = {"supported", "partially_supported", "not_supported", "cannot_verify"}
LOCATOR_TYPES = {"section", "page", "quote"}
ID_RE = re.compile(r"^C\d{3,}$")


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate_claims(doc) -> list:
    errs = []
    if not isinstance(doc, dict):
        return ["claims: top level must be an object"]
    if doc.get("version") != 1:
        errs.append("claims: 'version' must be 1")
    if not isinstance(doc.get("claims"), list):
        return errs + ["claims: 'claims' must be a list"]
    seen = set()
    for i, c in enumerate(doc["claims"]):
        w = f"claims[{i}]"
        if not isinstance(c, dict):
            errs.append(f"{w}: must be an object")
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not ID_RE.match(cid):
            errs.append(f"{w}: 'id' must match C### (got {cid!r})")
        elif cid in seen:
            errs.append(f"{w}: duplicate id {cid}")
        seen.add(cid)
        if not isinstance(c.get("text"), str) or not c["text"].strip():
            errs.append(f"{w}: 'text' must be a non-empty string")
        if not isinstance(c.get("section"), str) or not c["section"].strip():
            errs.append(f"{w}: 'section' must be a non-empty string")
        if not _is_int(c.get("line")) or c["line"] < 1:
            errs.append(f"{w}: 'line' must be an integer >= 1")
        t = c.get("types")
        if not isinstance(t, list) or not t or not set(t) <= CLAIM_TYPES:
            errs.append(f"{w}: 'types' must be a non-empty list drawn from {sorted(CLAIM_TYPES)}")
        for key in ("cite_keys", "refs"):
            v = c.get(key, [])
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                errs.append(f"{w}: '{key}' must be a list of strings")
        if isinstance(t, list) and "cited_fact" in t and not c.get("cite_keys"):
            errs.append(f"{w}: type cited_fact requires non-empty 'cite_keys'")
        nums = c.get("numbers", [])
        if not isinstance(nums, list):
            errs.append(f"{w}: 'numbers' must be a list")
        else:
            for j, n in enumerate(nums):
                if not (isinstance(n, dict) and isinstance(n.get("raw"), str)
                        and _is_num(n.get("value")) and isinstance(n.get("percent"), bool)
                        and _is_int(n.get("decimals")) and isinstance(n.get("trivial"), bool)):
                    errs.append(f"{w}.numbers[{j}]: needs raw:str value:number percent:bool "
                                f"decimals:int trivial:bool")
    return errs


def validate_map(doc) -> list:
    errs = []
    if not isinstance(doc, dict):
        return ["map: top level must be an object"]
    if doc.get("version") != 1:
        errs.append("map: 'version' must be 1")
    if not isinstance(doc.get("claims"), list):
        return errs + ["map: 'claims' must be a list"]
    seen = set()
    for i, e in enumerate(doc["claims"]):
        w = f"map.claims[{i}]"
        if not isinstance(e, dict):
            errs.append(f"{w}: must be an object")
            continue
        cid = e.get("claim_id")
        if not isinstance(cid, str) or not ID_RE.match(cid):
            errs.append(f"{w}: 'claim_id' must match C###")
        elif cid in seen:
            errs.append(f"{w}: duplicate claim_id {cid}")
        seen.add(cid)
        if e.get("status") not in STATUSES:
            errs.append(f"{w}: 'status' must be one of {sorted(STATUSES)}")
        if not isinstance(e.get("text"), str) or not e["text"].strip():
            errs.append(f"{w}: 'text' must be a non-empty string")
        if not isinstance(e.get("section"), str):
            errs.append(f"{w}: 'section' must be a string")
        if not _is_int(e.get("line")) or e["line"] < 1:
            errs.append(f"{w}: 'line' must be an integer >= 1")
        ev = e.get("evidence")
        if not isinstance(ev, list):
            errs.append(f"{w}: 'evidence' must be a list")
            ev = []
        usable = 0
        for j, x in enumerate(ev):
            ww = f"{w}.evidence[{j}]"
            if not isinstance(x, dict) or x.get("kind") not in EVIDENCE_KINDS:
                errs.append(f"{ww}: 'kind' must be one of {sorted(EVIDENCE_KINDS)}")
                continue
            if not isinstance(x.get("detail"), str) or not isinstance(x.get("locator"), str):
                errs.append(f"{ww}: 'detail' and 'locator' must be strings")
            if "audit_verdict" in x and x["audit_verdict"] not in VERDICTS:
                errs.append(f"{ww}: bad audit_verdict {x['audit_verdict']!r}")
            if not x.get("rejected"):
                usable += 1
        if e.get("status") in ("supported", "partial") and usable == 0:
            errs.append(f"{w}: status {e.get('status')} requires at least one non-rejected evidence entry")
        if e.get("status") == "unmapped" and usable:
            errs.append(f"{w}: status unmapped but usable evidence present")
        for key in ("unmatched_numbers", "missing_bib_keys"):
            if not isinstance(e.get(key), list):
                errs.append(f"{w}: '{key}' must be a list")
        if not isinstance(e.get("needs_citation_audit"), bool):
            errs.append(f"{w}: 'needs_citation_audit' must be a boolean")
    s = doc.get("summary")
    if not isinstance(s, dict):
        errs.append("map: 'summary' must be an object")
    else:
        entries = [e for e in doc["claims"] if isinstance(e, dict)]
        if s.get("total") != len(entries):
            errs.append(f"map.summary.total={s.get('total')} but {len(entries)} claims present")
        for st in STATUSES:
            n = sum(1 for e in entries if e.get("status") == st)
            if s.get(st) != n:
                errs.append(f"map.summary.{st}={s.get(st)} but counted {n}")
        if not _is_num(s.get("coverage_pct")):
            errs.append("map.summary.coverage_pct must be a number")
    return errs


def validate_audit(doc) -> list:
    errs = []
    if not isinstance(doc, dict) or not isinstance(doc.get("audits"), list):
        return ["audit: top level must be an object with an 'audits' list"]
    seen = set()
    for i, a in enumerate(doc["audits"]):
        w = f"audits[{i}]"
        if not isinstance(a, dict):
            errs.append(f"{w}: must be an object")
            continue
        if not isinstance(a.get("claim_id"), str) or not ID_RE.match(a["claim_id"]):
            errs.append(f"{w}: 'claim_id' must match C###")
        if not isinstance(a.get("cite_key"), str) or not a["cite_key"]:
            errs.append(f"{w}: 'cite_key' must be a non-empty string")
        key = (a.get("claim_id"), a.get("cite_key"))
        if key in seen:
            errs.append(f"{w}: duplicate (claim_id, cite_key) {key}")
        seen.add(key)
        v = a.get("verdict")
        if v not in VERDICTS:
            errs.append(f"{w}: 'verdict' must be one of {sorted(VERDICTS)}")
        loc = a.get("locator")
        if v in ("supported", "partially_supported", "not_supported"):
            if not (isinstance(loc, dict) and loc.get("type") in LOCATOR_TYPES
                    and isinstance(loc.get("value"), str) and loc["value"].strip()):
                errs.append(f"{w}: verdict {v} requires locator {{type: section|page|quote, value: str}}")
        elif loc is not None and not (isinstance(loc, dict) and loc.get("type") in LOCATOR_TYPES):
            errs.append(f"{w}: locator, if present, needs type in {sorted(LOCATOR_TYPES)}")
        if v in ("partially_supported", "not_supported", "cannot_verify") \
                and not (isinstance(a.get("notes"), str) and a["notes"].strip()):
            errs.append(f"{w}: verdict {v} requires non-empty 'notes'")
    return errs


def cross_check(claims_doc, map_doc) -> list:
    ids = {c.get("id") for c in claims_doc.get("claims", []) if isinstance(c, dict)}
    mids = {e.get("claim_id") for e in map_doc.get("claims", []) if isinstance(e, dict)}
    errs = [f"cross: claim {i} has no map entry" for i in sorted(ids - mids, key=str)]
    errs += [f"cross: map entry {i} has no claim in claims.json" for i in sorted(mids - ids, key=str)]
    return errs


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--claims")
    ap.add_argument("--map")
    ap.add_argument("--audit")
    args = ap.parse_args()
    if not (args.claims or args.map or args.audit):
        ap.error("give at least one of --claims / --map / --audit")
    docs, errs = {}, []
    for name, path, fn in (("claims", args.claims, validate_claims),
                           ("map", args.map, validate_map),
                           ("audit", args.audit, validate_audit)):
        if not path:
            continue
        try:
            docs[name] = _load(path)
        except (OSError, ValueError) as e:
            print(f"ERROR: cannot load {path}: {e}", file=sys.stderr)
            return 2
        e = fn(docs[name])
        print(f"{name}: {'OK' if not e else str(len(e)) + ' error(s)'} ({path})")
        errs += e
    if "claims" in docs and "map" in docs and isinstance(docs["claims"], dict) \
            and isinstance(docs["map"], dict):
        errs += cross_check(docs["claims"], docs["map"])
    for e in errs:
        print("  - " + e)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
