#!/usr/bin/env python3
"""
test_claim_evidence_gate.py — regression tests for the claim-evidence gate.

Stdlib only, no pytest, no fixtures on disk:

    python3 skills/paper-orchestra/scripts/test_claim_evidence_gate.py

Every case here corresponds to a claim the gate used to miss on real LaTeX.
"""
import unittest

from claim_evidence_gate import (
    PRIOR_WORK_CONTEXT,
    extract_claims,
    find_evidence,
    normalize_latex,
)


class TestNormalizeLatex(unittest.TestCase):
    def test_escaped_percent_is_not_a_comment(self):
        tex = r"Our method reaches 92.4\% accuracy on the held-out split."
        out = normalize_latex(tex)
        self.assertIn("accuracy on the held-out split", out)
        self.assertIn("92.4%", out)

    def test_real_comment_is_still_stripped(self):
        tex = "Visible text.  % TODO: rewrite this paragraph\nNext line."
        out = normalize_latex(tex)
        self.assertNotIn("TODO", out)
        self.assertIn("Visible text.", out)

    def test_math_multiplier_is_flattened(self):
        out = normalize_latex(r"a 2.13$\times$ multiplier")
        self.assertIn("×", out)
        self.assertNotIn("times", out)
        # and the flattened form is claim-extractable
        self.assertIn("2.13", [c.value for c in extract_claims(r"a 2.13$\times$ speedup")])

    def test_braced_relation_is_flattened(self):
        self.assertIn(">85%", normalize_latex(r"from ${>}85\%$ down"))

    def test_citation_leaves_a_marker(self):
        out = normalize_latex(r"Prior work reports 41.2\% \citep{smith2025}.")
        self.assertIn("[CITE]", out)
        self.assertTrue(PRIOR_WORK_CONTEXT.search(out))

    def test_other_refs_are_dropped_without_marker(self):
        out = normalize_latex(r"See \ref{fig:one} for the 12.5\% case.")
        self.assertNotIn("[CITE]", out)
        self.assertIn("12.5%", out)


class TestExtractClaims(unittest.TestCase):
    def test_percentage_claim_is_extracted(self):
        claims = extract_claims(r"The system improves accuracy by 3.2\% over the baseline.")
        self.assertIn("3.2", [c.value for c in claims])

    def test_prefix_hyphen_is_not_a_minus_sign(self):
        values = [c.value for c in extract_claims(r"We hold attacks to sub-5\% success.")]
        self.assertIn("5", values)
        self.assertNotIn("-5", values)

    def test_cited_number_is_attributed_not_claimed(self):
        claims = extract_claims(r"GitGuardian reports 28.6\% growth \citep{gg2026}.")
        self.assertTrue(claims)
        self.assertTrue(all(c.is_prior_work for c in claims))

    def test_our_number_is_not_attributed(self):
        claims = extract_claims(r"\section{Experiments} We reach 87.4\% accuracy.")
        ours = [c for c in claims if c.value == "87.4"]
        self.assertTrue(ours)
        self.assertFalse(ours[0].is_prior_work)
        self.assertEqual(ours[0].section, "Experiments")

    def test_baseline_comparison_is_our_claim(self):
        # "baseline" used to be an attribution cue, which turned the most
        # common shape of a real result into someone else's number.
        tex = r"\section{Experiments} Our model improves over the strongest baseline by 3.2\%."
        claims = [c for c in extract_claims(tex) if c.value == "3.2"]
        self.assertTrue(claims)
        self.assertFalse(claims[0].is_prior_work)

    def test_same_value_in_two_sentences_yields_two_claims(self):
        # The old global dedup let whichever sentence matched first decide the
        # classification of every later occurrence of that number.
        tex = (r"\section{Related Work} Prior work reports 41.2\% \citep{a2025}. "
               r"\section{Experiments} Our system reaches 41.2\% on the same split.")
        claims = [c for c in extract_claims(tex) if c.value == "41.2"]
        self.assertEqual(len(claims), 2)
        self.assertEqual({c.is_prior_work for c in claims}, {True, False})
        self.assertEqual({c.section for c in claims}, {"Related Work", "Experiments"})

    def test_abstract_is_a_named_section(self):
        tex = r"\begin{abstract} We reach 88.1\% accuracy. \end{abstract}"
        claims = [c for c in extract_claims(tex) if c.value == "88.1"]
        self.assertEqual(claims[0].section, "Abstract")

    def test_section_attribution(self):
        tex = r"\section{Method} No numbers. \section{Experiments} We reach 91.0\% recall."
        claims = [c for c in extract_claims(tex) if c.value == "91.0"]
        self.assertEqual(claims[0].section, "Experiments")

    def test_years_in_table_cells_are_not_claims(self):
        tex = r"\begin{tabular}{ll} 2025 & \textbf{2026} \\ \end{tabular}"
        self.assertEqual([c.value for c in extract_claims(tex)], [])


class TestFindEvidence(unittest.TestCase):
    def test_exact_number_match(self):
        log = "| Ours | 87.4 | 0.91 |"
        self.assertIsNotNone(find_evidence("87.4", log))

    def test_fabricated_number_is_unsupported(self):
        log = "| Ours | 87.4 | 0.91 |"
        self.assertIsNone(find_evidence("93.8", log))

    def test_no_partial_number_match(self):
        self.assertIsNone(find_evidence("87.4", "the value is 187.45 units"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
