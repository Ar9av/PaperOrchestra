#!/usr/bin/env python3
"""
test_reverse_outline.py — regression tests for the reverse-outline builder.

Stdlib only:

    python3 skills/content-refinement-agent/scripts/test_reverse_outline.py
"""
import unittest

from reverse_outline import analyze_paragraph, build_outline, preprocess, sentences

MAXS, MAXW = 8, 220


def flags(text: str) -> list[str]:
    result = analyze_paragraph(text, MAXS, MAXW)
    return result["flags"] if result else []


class TestPreprocess(unittest.TestCase):
    def test_preamble_is_dropped(self):
        tex = (r"\documentclass{article}\definecolor{brand}{RGB}{1,2,3}"
               r"\begin{document}\section{Intro} Body text here.\end{document}")
        out = preprocess(tex)
        self.assertNotIn("definecolor", out)
        self.assertIn("Body text here.", out)

    def test_float_environments_are_dropped(self):
        tex = (r"\begin{document}\section{X} Real prose sentence goes here."
               r"\begin{figure}\includegraphics{a.png}\caption{A caption.}\end{figure}"
               r"\end{document}")
        self.assertNotIn("caption", preprocess(tex))

    def test_abstract_becomes_a_section(self):
        tex = r"\begin{document}\begin{abstract}Some abstract prose.\end{abstract}\end{document}"
        self.assertIn(r"\section{Abstract}", preprocess(tex))

    def test_bibliography_is_dropped(self):
        tex = r"\begin{document}\section{X} Prose. \bibliography{refs}\end{document}"
        self.assertNotIn("refs", preprocess(tex))


class TestSentences(unittest.TestCase):
    def test_run_in_heading_merges_forward(self):
        # "Policy engine." is a bold lead-in, not a sentence of its own.
        s = sentences("Policy engine. The engine evaluates every tool call against "
                      "a YAML ruleset before the call reaches the operating system.")
        self.assertEqual(len(s), 1)
        self.assertTrue(s[0].startswith("Policy engine."))

    def test_ordinary_sentences_are_not_merged(self):
        s = sentences("The first sentence carries the message of this paragraph. "
                      "The second sentence supports it with a concrete example.")
        self.assertEqual(len(s), 2)


class TestFlags(unittest.TestCase):
    def test_clean_paragraph_has_no_flags(self):
        text = ("Our policy engine evaluates tool calls before execution. "
                "It matches each call against a ruleset of twenty-five detectors. "
                "Calls that match a critical rule are blocked outright.")
        self.assertEqual(flags(text), [])

    def test_run_in_heading_is_not_a_missing_topic_sentence(self):
        text = ("Policy engine. The engine evaluates every tool call against a YAML "
                "ruleset before the call reaches the operating system, and blocks "
                "the ones that match a critical rule.")
        self.assertNotIn("no-topic-sentence", flags(text))

    def test_connective_opener_is_flagged(self):
        text = ("However, the same mechanism fails when the agent writes to a path "
                "outside the workspace root. We therefore extend the matcher to "
                "canonicalize paths before evaluation.")
        self.assertIn("no-topic-sentence", flags(text))

    def test_overlong_paragraph_is_flagged(self):
        text = " ".join(f"This is supporting sentence number {i} in a long paragraph." 
                        for i in range(12))
        self.assertIn("overlong", flags(text))

    def test_two_pivots_are_flagged(self):
        text = ("The baseline achieves reasonable precision on static inputs. "
                "However, it collapses under adaptive prompts in our setting. "
                "In contrast, the policy engine holds its precision throughout.")
        self.assertIn("multi-pivot", flags(text))

    def test_citation_dump_is_flagged(self):
        text = ("Several systems address this problem [CITE] [CITE] [CITE]. "
                "Others take a complementary approach [CITE] [CITE].")
        self.assertIn("citation-dump", flags(text))

    def test_short_single_sentence_is_an_orphan(self):
        text = ("This observation about adaptive adversaries motivates the enforcement "
                "design described in the following subsection of the paper.")
        self.assertIn("orphan", flags(text))

    def test_long_single_sentence_is_not_an_orphan(self):
        text = ("The vendor landscape divides into four broad categories according to whether "
                "a given product intercepts agent tool calls at runtime, scans repositories "
                "after the fact for credentials that have already leaked into history, gates "
                "model access at the network boundary through a proxy layer, or merely "
                "reports its findings to a dashboard without offering any enforcement path "
                "that could stop the action before it reaches the operating system at all.")
        self.assertNotIn("orphan", flags(text))

    def test_fragments_are_not_paragraphs(self):
        self.assertIsNone(analyze_paragraph("Table 1.", MAXS, MAXW))


class TestBuildOutline(unittest.TestCase):
    def test_sections_and_subsection_depth(self):
        tex = (r"\begin{document}"
               r"\section{Method} The method proceeds in three stages, each of which is "
               r"described in the subsections that follow this overview paragraph."
               "\n\n"
               r"\subsection{Policy Engine} The engine evaluates every incoming tool call "
               r"against a ruleset of detectors before that call reaches the system."
               r"\end{document}")
        outline = build_outline(tex, MAXS, MAXW)
        titles = [s["section"] for s in outline]
        self.assertEqual(titles, ["Method", "— Policy Engine"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
