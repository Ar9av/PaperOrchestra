#!/usr/bin/env python3
"""
test_table_lint.py — regression tests for the LaTeX table linter.

Stdlib only:

    python3 skills/section-writing-agent/scripts/test_table_lint.py
"""
import unittest

from table_lint import decimals, find_tables, is_numeric, lint_table, split_rows

GOOD = r"""
\begin{table}[t]
\centering
\caption{Accuracy and latency on the held-out split of Dataset X, averaged over five seeds.}
\label{tab:main}
\begin{tabular}{lrr}
\toprule
Method & Accuracy $\uparrow$ & Latency (ms) $\downarrow$ \\
\midrule
Baseline & 78.2 & 12.3 \\
Ours     & 85.4 & 8.1 \\
\bottomrule
\end{tabular}
\end{table}
"""


def codes(tex: str, after_conclusion: bool = False) -> set[str]:
    tables = find_tables(tex)
    out: set[str] = set()
    for t in tables:
        out |= {f["code"] for f in lint_table(t, after_conclusion)}
    return out


class TestGoodTable(unittest.TestCase):
    def test_clean_table_has_no_findings(self):
        self.assertEqual(codes(GOOD), set())

    def test_unicode_arrows_also_count(self):
        self.assertNotIn("no-metric-direction",
                         codes(GOOD.replace(r"$\uparrow$", "↑").replace(r"$\downarrow$", "↓")))


class TestErrors(unittest.TestCase):
    def test_vertical_rules(self):
        self.assertIn("vertical-rule", codes(GOOD.replace("{lrr}", "{l|r|r}")))

    def test_hline(self):
        self.assertIn("hline", codes(GOOD.replace(r"\midrule", r"\hline")))

    def test_missing_rules(self):
        self.assertIn("missing-rules", codes(GOOD.replace(r"\bottomrule", " ")))

    def test_caption_below_tabular(self):
        broken = r"""
\begin{table}[t]
\begin{tabular}{lr}
\toprule
Method & Accuracy $\uparrow$ \\
\midrule
Ours & 85.4 \\
\bottomrule
\end{tabular}
\caption{Accuracy on the held-out split of Dataset X across five random seeds.}
\label{tab:x}
\end{table}
"""
        self.assertIn("caption-below", codes(broken))

    def test_missing_caption(self):
        self.assertIn("no-caption", codes(
            GOOD.replace(r"\caption{Accuracy and latency on the held-out split of "
                         r"Dataset X, averaged over five seeds.}", " ")))

    def test_table_without_tabular(self):
        self.assertIn("no-tabular", codes(r"\begin{table}\caption{Nothing here at all.}\end{table}"))


class TestWarnings(unittest.TestCase):
    def test_missing_label(self):
        self.assertIn("no-label", codes(GOOD.replace(r"\label{tab:main}", " ")))

    def test_thin_caption(self):
        self.assertIn("thin-caption", codes(GOOD.replace(
            r"\caption{Accuracy and latency on the held-out split of Dataset X, "
            r"averaged over five seeds.}", r"\caption{Results.}")))

    def test_missing_metric_direction(self):
        found = codes(GOOD.replace(r"Accuracy $\uparrow$", "Accuracy")
                          .replace(r"Latency (ms) $\downarrow$", "Latency (ms)"))
        self.assertIn("no-metric-direction", found)

    def test_mixed_decimal_precision(self):
        self.assertIn("mixed-precision", codes(GOOD.replace("& 8.1 ", "& 8.14 ")))

    def test_table_after_conclusion(self):
        self.assertIn("late-table", codes(GOOD, after_conclusion=True))

    def test_text_column_is_not_checked_for_direction(self):
        # The Method column is text; it must not be asked for an arrow.
        found = codes(GOOD)
        self.assertNotIn("no-metric-direction", found)


class TestCellHelpers(unittest.TestCase):
    def test_bold_numbers_are_numeric(self):
        self.assertTrue(is_numeric(r"\textbf{85.4}"))

    def test_math_and_percent_are_numeric(self):
        self.assertTrue(is_numeric(r"$92.1$"))
        self.assertTrue(is_numeric(r"3.2\%"))

    def test_text_is_not_numeric(self):
        self.assertFalse(is_numeric("Critical"))
        self.assertFalse(is_numeric("Mar 2025"))

    def test_decimal_counting(self):
        self.assertEqual(decimals("85.4"), 1)
        self.assertEqual(decimals(r"\textbf{85.40}"), 2)
        self.assertEqual(decimals("12"), 0)

    def test_escaped_ampersand_is_not_a_column_break(self):
        rows = split_rows(r"R\&D & 12.0 \\")
        self.assertEqual(len(rows[0]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
