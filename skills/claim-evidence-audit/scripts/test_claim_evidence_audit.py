#!/usr/bin/env python3
"""
test_claim_evidence_audit.py — regression tests for the claim-evidence-audit
scripts. Stdlib only; fixtures live in ../fixtures:

    python3 skills/claim-evidence-audit/scripts/test_claim_evidence_audit.py
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "..", "fixtures")

import claimlib as cl
from audit_report import render
from build_evidence_map import build, to_markdown
from coverage_gate import coverage
from extract_claims import extract
from numeric_consistency import check
from validate_schema import cross_check, validate_audit, validate_claims, validate_map


def read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


TEX, LOG, BIB = read("paper.tex"), read("experimental_log.md"), read("refs.bib")


def claims_doc():
    return {"version": 1, "source": "paper.tex", "reviewed": False, "claims": extract(TEX)}


def build_map(audit=None):
    return build(claims_doc(), LOG, cl.parse_bib_keys(BIB), cl.scan_tex(TEX)["labels"], audit)


def by_text(doc, needle):
    return next(e for e in doc["claims"] if needle in e["text"])


def num(s):
    return cl.parse_numbers(s)[0]


class TestNumbers(unittest.TestCase):
    def test_percent_decimal_thousands(self):
        n = cl.parse_numbers(r"EM rose 3.2\% on 7,830 examples and 1{,}200 dev, 87.4 %")
        self.assertEqual([x["value"] for x in n], [3.2, 7830, 1200, 87.4])
        self.assertEqual([x["percent"] for x in n], [True, False, False, True])

    def test_skips_years_refs_and_model_names(self):
        n = cl.parse_numbers(r"In 2023 (Table 3, Section 4) GPT-4 and BLEU-4 \cite{x2020} \ref{tab:1}")
        self.assertEqual(n, [])

    def test_trivial_flag(self):
        n = cl.parse_numbers("3 runs, 12 layers, 0.5 dropout")
        self.assertEqual([x["trivial"] for x in n], [True, False, False])


class TestMatching(unittest.TestCase):
    def test_rounding_down_ok(self):
        self.assertTrue(cl.numbers_match(num("87.4"), num("87.43")))
        self.assertTrue(cl.numbers_match(num("87"), num("87.43")))

    def test_paper_more_precise_than_log_rejected(self):
        self.assertFalse(cl.numbers_match(num("87.43"), num("87.4")))

    def test_percent_fraction_reconcile(self):
        self.assertTrue(cl.numbers_match(num(r"87.4\%"), num("0.8743")))
        self.assertTrue(cl.numbers_match(num("0.874"), num("87.4%")))
        self.assertTrue(cl.numbers_match(num("91.0"), num("0.9101")))

    def test_off_by_more_than_rounding_rejected(self):
        self.assertFalse(cl.numbers_match(num("87.4"), num("87.9")))

    def test_tolerance_flags(self):
        self.assertTrue(cl.numbers_match(num("87.4"), num("87.9"), abs_tol=0.5))
        self.assertTrue(cl.numbers_match(num("100.0"), num("101.0"), rel_tol=0.01))


class TestScanAndExtract(unittest.TestCase):
    def test_sections_and_line_numbers(self):
        c = {x["id"]: x for x in claims_doc()["claims"]}
        first = next(v for v in c.values() if "improves F1" in v["text"])
        self.assertEqual((first["section"], first["line"]), ("Abstract", 5))
        concl = next(v for v in c.values() if "demonstrate" in v["text"])
        self.assertEqual(concl["section"], "Conclusion")
        self.assertEqual(TEX.splitlines()[concl["line"] - 1].strip()[:10], "We demonst")

    def test_comments_and_tables_not_claims(self):
        texts = " ".join(c["text"] for c in claims_doc()["claims"])
        self.assertNotIn("99.9", texts)
        self.assertNotIn("SparseLong & 87.4", texts)

    def test_types(self):
        d = claims_doc()
        t = {tuple(c["types"]) for c in d["claims"] if "Long-document models" in c["text"]}
        self.assertEqual(t, {("cited_fact",)})
        c4 = next(c for c in d["claims"] if "outperforming BigBird" in c["text"])
        self.assertIn("numeric_result", c4["types"])
        self.assertIn("comparison", c4["types"])

    def test_et_al_does_not_split_sentence(self):
        c = [x for x in claims_doc()["claims"] if "Vaswani et al." in x["text"]]
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["cite_keys"], ["vaswani2017attention", "ghost2099"])

    def test_ids_unique_and_schema_valid(self):
        d = claims_doc()
        self.assertEqual(validate_claims(d), [])
        self.assertEqual(len({c["id"] for c in d["claims"]}), len(d["claims"]))

    def test_no_preamble_claims(self):
        tex = "\\documentclass{article}\n% 55.5 here\n\\begin{document}\n\\section{A}\nWe achieve 12.5 BLEU.\n\\end{document}\n"
        d = extract(tex)
        self.assertEqual(len(d), 1)
        self.assertEqual((d[0]["section"], d[0]["line"]), ("A", 5))


class TestEvidenceMap(unittest.TestCase):
    def test_log_table_row_match_via_fraction(self):
        e = by_text(build_map(), "87.4")
        self.assertEqual(e["status"], "supported")
        self.assertTrue(all(x["kind"] == "log_table_row" for x in e["evidence"]))

    def test_unlogged_number_unmapped(self):
        e = by_text(build_map(), "99.2")
        self.assertEqual(e["status"], "unmapped")
        self.assertEqual(e["unmatched_numbers"], ["99.2%"])

    def test_figure_evidence(self):
        e = by_text(build_map(), "41.7")
        kinds = {x["kind"] for x in e["evidence"]}
        self.assertEqual(kinds, {"log_number", "figure"})

    def test_citation_only_if_in_bib(self):
        e = by_text(build_map(), "Vaswani et al.")
        self.assertEqual(e["missing_bib_keys"], ["ghost2099"])
        self.assertEqual([x["detail"] for x in e["evidence"]], ["vaswani2017attention"])

    def test_claim_with_only_missing_key_is_unmapped(self):
        d = {"version": 1, "claims": [{"id": "C001", "text": "X holds \\cite{nope}.", "section": "S",
             "line": 1, "types": ["cited_fact"], "numbers": [], "cite_keys": ["nope"], "refs": []}]}
        m = build(d, LOG, cl.parse_bib_keys(BIB), {}, None)
        self.assertEqual(m["claims"][0]["status"], "unmapped")

    def test_bare_claim_unmapped(self):
        self.assertEqual(by_text(build_map(), "demonstrate")["status"], "unmapped")

    def test_partial_when_some_numbers_unmatched(self):
        d = {"version": 1, "claims": [{"id": "C001", "text": "87.4 and 55.5", "section": "S", "line": 1,
             "types": ["numeric_result"], "cite_keys": [], "refs": [],
             "numbers": [num("87.4"), num("55.5")]}]}
        m = build(d, LOG, set(), {}, None)
        self.assertEqual(m["claims"][0]["status"], "partial")

    def test_audit_not_supported_rejects_citation(self):
        a = {"audits": [{"claim_id": "C002", "cite_key": "vaswani2017attention",
                         "verdict": "not_supported", "locator": {"type": "page", "value": "3"},
                         "notes": "source says the opposite"}]}
        m = build_map(a)
        e = next(x for x in m["claims"] if x["claim_id"] == "C002")
        self.assertEqual(e["status"], "unmapped")
        self.assertTrue(e["evidence"][0]["rejected"])
        self.assertEqual(validate_map(m), [])

    def test_audit_partially_supported_downgrades(self):
        a = {"audits": [{"claim_id": "C002", "cite_key": "vaswani2017attention",
                         "verdict": "partially_supported", "locator": {"type": "quote", "value": "costly"},
                         "notes": "only for long inputs"}]}
        e = next(x for x in build_map(a)["claims"] if x["claim_id"] == "C002")
        self.assertEqual(e["status"], "partial")
        self.assertFalse(e["needs_citation_audit"])

    def test_audit_supported_clears_pending(self):
        a = {"audits": [{"claim_id": "C002", "cite_key": "vaswani2017attention", "verdict": "supported",
                         "locator": {"type": "section", "value": "1"}, "notes": ""}]}
        e = next(x for x in build_map(a)["claims"] if x["claim_id"] == "C002")
        self.assertEqual((e["status"], e["needs_citation_audit"]), ("supported", False))

    def test_map_valid_and_markdown_orders_unmapped_first(self):
        m = build_map()
        self.assertEqual(validate_map(m), [])
        rows = [l for l in to_markdown(m).splitlines() if l.startswith("| C")]
        self.assertIn("unmapped", rows[0])


class TestNumericConsistency(unittest.TestCase):
    def test_reports_numbers_missing_from_log(self):
        rep = check(TEX, LOG)
        missing = {u["number"] for u in rep["unmatched"]}
        self.assertEqual(missing, {"99.2%"})

    def test_table_cells_are_checked(self):
        rep = check(TEX.replace("& 88.2", "& 77.7"), LOG)
        self.assertIn("77.7", {u["number"] for u in rep["unmatched"]})

    def test_small_ints_and_comment_numbers_ignored(self):
        rep = check("\\begin{document}\nWe ran 5 seeds. % 99.9\n\\end{document}", LOG)
        self.assertEqual(rep["summary"]["checked"], 0)

    def test_math_env_skipped(self):
        rep = check("\\begin{document}\n\\begin{equation}\nx = 123.456\n\\end{equation}\n\\end{document}", LOG)
        self.assertEqual(rep["summary"]["checked"], 0)


class TestCoverageAndReport(unittest.TestCase):
    def test_coverage_values(self):
        self.assertAlmostEqual(coverage(build_map()), 75.0)
        self.assertGreater(coverage(build_map(), count_partial=True), 0)
        self.assertEqual(coverage({"claims": []}), 100.0)

    def test_report_mentions_actions_and_safety(self):
        md = render(build_map(), check(TEX, LOG), None)
        self.assertIn("99.2", md)
        self.assertIn("never fabricated", md)
        self.assertIn("Citation audit not run", md)


class TestSchemaValidation(unittest.TestCase):
    def test_claims_violations(self):
        d = claims_doc()
        d["claims"][0]["line"] = 0
        d["claims"][1]["id"] = d["claims"][0]["id"]
        d["claims"][2]["types"] = ["bogus"]
        errs = validate_claims(d)
        self.assertTrue(any("line" in e for e in errs))
        self.assertTrue(any("duplicate" in e for e in errs))
        self.assertTrue(any("types" in e for e in errs))

    def test_cited_fact_requires_keys(self):
        d = claims_doc()
        c = next(c for c in d["claims"] if "cited_fact" in c["types"])
        c["cite_keys"] = []
        self.assertTrue(any("cite_keys" in e for e in validate_claims(d)))

    def test_map_violations(self):
        m = build_map()
        bad = copy.deepcopy(m)
        bad["claims"][0]["status"] = "great"
        bad["summary"]["total"] += 1
        errs = validate_map(bad)
        self.assertTrue(any("status" in e for e in errs))
        self.assertTrue(any("summary.total" in e for e in errs))

    def test_supported_without_evidence_rejected(self):
        m = build_map()
        e = next(x for x in m["claims"] if x["status"] == "supported")
        e["evidence"] = []
        self.assertTrue(any("requires at least one" in x for x in validate_map(m)))

    def test_audit_schema(self):
        self.assertEqual(validate_audit(json.loads(read("citation_audit.json"))), [])
        bad = {"audits": [{"claim_id": "C001", "cite_key": "k", "verdict": "supported"},
                          {"claim_id": "C002", "cite_key": "k", "verdict": "not_supported",
                           "locator": {"type": "page", "value": "2"}}]}
        errs = validate_audit(bad)
        self.assertTrue(any("locator" in e for e in errs))
        self.assertTrue(any("notes" in e for e in errs))

    def test_cross_check(self):
        d, m = claims_doc(), build_map()
        m["claims"].pop()
        self.assertTrue(any("no map entry" in e for e in cross_check(d, m)))


class TestCli(unittest.TestCase):
    def run_script(self, name, *args):
        return subprocess.run([sys.executable, os.path.join(HERE, name), *args],
                              capture_output=True, text=True)

    def test_end_to_end_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            p = lambda n: os.path.join(d, n)  # noqa: E731
            r = self.run_script("extract_claims.py", "--paper", os.path.join(FIX, "paper.tex"),
                                "--out", p("claims.json"))
            self.assertEqual(r.returncode, 0, r.stderr)
            r = self.run_script("build_evidence_map.py", "--claims", p("claims.json"),
                                "--log", os.path.join(FIX, "experimental_log.md"),
                                "--bib", os.path.join(FIX, "refs.bib"),
                                "--paper", os.path.join(FIX, "paper.tex"),
                                "--audit", os.path.join(FIX, "citation_audit.json"),
                                "--out-json", p("map.json"), "--out-md", p("map.md"))
            self.assertEqual(r.returncode, 0, r.stderr)
            r = self.run_script("validate_schema.py", "--claims", p("claims.json"), "--map", p("map.json"))
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertEqual(self.run_script("coverage_gate.py", "--map", p("map.json")).returncode, 1)
            self.assertEqual(self.run_script("coverage_gate.py", "--map", p("map.json"),
                                             "--threshold", "70").returncode, 0)
            r = self.run_script("numeric_consistency.py", "--paper", os.path.join(FIX, "paper.tex"),
                                "--log", os.path.join(FIX, "experimental_log.md"), "--out", p("num.json"))
            self.assertEqual(r.returncode, 1)
            r = self.run_script("audit_report.py", "--map", p("map.json"), "--numeric", p("num.json"),
                                "--out", p("report.md"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.getsize(p("report.md")) > 0)

    def test_missing_inputs_exit_2(self):
        self.assertEqual(self.run_script("extract_claims.py", "--paper", "/nope.tex",
                                         "--out", "/tmp/x.json").returncode, 2)
        self.assertEqual(self.run_script("coverage_gate.py", "--map", "/nope.json").returncode, 2)
        self.assertEqual(self.run_script("validate_schema.py", "--claims", "/nope.json").returncode, 2)
        self.assertEqual(self.run_script("numeric_consistency.py", "--paper", "/nope",
                                         "--log", "/nope").returncode, 2)

    def test_invalid_json_schema_exit_1(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "c.json")
            with open(f, "w") as fh:
                json.dump({"version": 2, "claims": []}, fh)
            self.assertEqual(self.run_script("validate_schema.py", "--claims", f).returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
