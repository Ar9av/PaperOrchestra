#!/usr/bin/env python3
"""
test_figure_lint.py — regression tests for the figure/caption linter.

Stdlib only; PNG fixtures are synthesized in a temp directory rather than
committed as binaries:

    python3 skills/plotting-agent/scripts/test_figure_lint.py
"""
import os
import struct
import tempfile
import unittest
import zlib

from figure_lint import lint, png_geometry, referenced_figures

PIPELINE_CAPTION = ("System architecture of the proposed pipeline, showing the three "
                    "enforcement layers and the order in which they evaluate a call.")


def chunk(ctype: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + ctype + payload
            + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF))


def make_png(path: str, width: int, height: int, dpi: int | None = None) -> None:
    """Write a structurally valid PNG header; pixel data is not needed here."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
    if dpi:
        ppm = round(dpi / 0.0254)
        data += chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1))
    data += chunk(b"IDAT", zlib.compress(b"\x00")) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(data)


def codes(findings: list[dict]) -> set[str]:
    return {f["code"] for f in findings}


class TestPngGeometry(unittest.TestCase):
    def test_dimensions(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.png")
            make_png(p, 2370, 1770)
            geo = png_geometry(p)
            self.assertEqual((geo["width"], geo["height"]), (2370, 1770))

    def test_dpi_from_phys(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.png")
            make_png(p, 1200, 900, dpi=300)
            self.assertEqual(png_geometry(p)["dpi"], 300)

    def test_dpi_absent_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.png")
            make_png(p, 1200, 900)
            self.assertIsNone(png_geometry(p)["dpi"])

    def test_non_png_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.png")
            with open(p, "wb") as f:
                f.write(b"not a png at all")
            self.assertIsNone(png_geometry(p))


class TestReferencedFigures(unittest.TestCase):
    def test_paths_and_extensions_are_stripped(self):
        tex = (r"\includegraphics[width=0.8\textwidth]{../figures/fig_one.png}"
               r"\includegraphics{fig_two}")
        self.assertEqual(referenced_figures(tex), {"fig_one", "fig_two"})


class LintCase(unittest.TestCase):
    """Base class providing a temp figures directory."""

    def run_lint(self, figures: dict, captions: dict, tex=None) -> set[str]:
        with tempfile.TemporaryDirectory() as d:
            for stem, dims in figures.items():
                make_png(os.path.join(d, stem + ".png"), *dims)
            return codes(lint(d, captions, tex))


class TestResolution(LintCase):
    def test_print_quality_figure_passes(self):
        found = self.run_lint({"fig_arch": (2370, 1770)}, {"fig_arch": PIPELINE_CAPTION})
        self.assertEqual(found, set())

    def test_low_resolution_warns(self):
        found = self.run_lint({"fig_arch": (800, 600)}, {"fig_arch": PIPELINE_CAPTION})
        self.assertIn("low-resolution", found)
        self.assertNotIn("unusable-resolution", found)

    def test_tiny_figure_errors(self):
        found = self.run_lint({"fig_arch": (320, 240)}, {"fig_arch": PIPELINE_CAPTION})
        self.assertIn("unusable-resolution", found)

    def test_extreme_aspect_warns(self):
        found = self.run_lint({"fig_arch": (4800, 600)}, {"fig_arch": PIPELINE_CAPTION})
        self.assertIn("extreme-aspect", found)

    def test_wide_but_reasonable_aspect_passes(self):
        found = self.run_lint({"fig_arch": (4770, 1770)}, {"fig_arch": PIPELINE_CAPTION})
        self.assertNotIn("extreme-aspect", found)


class TestCaptions(LintCase):
    def test_figure_without_caption_errors(self):
        found = self.run_lint({"fig_arch": (2370, 1770), "fig_extra": (2370, 1770)},
                              {"fig_arch": PIPELINE_CAPTION})
        self.assertIn("missing-caption", found)

    def test_caption_without_figure_errors(self):
        found = self.run_lint({"fig_arch": (2370, 1770)},
                              {"fig_arch": PIPELINE_CAPTION, "fig_ghost": PIPELINE_CAPTION})
        self.assertIn("orphan-caption", found)

    def test_empty_caption_errors(self):
        found = self.run_lint({"fig_arch": (2370, 1770), "fig_b": (2370, 1770)},
                              {"fig_arch": PIPELINE_CAPTION, "fig_b": "   "})
        self.assertIn("empty-caption", found)

    def test_self_numbered_caption_warns(self):
        found = self.run_lint({"fig_arch": (2370, 1770)},
                              {"fig_arch": "Figure 3: " + PIPELINE_CAPTION})
        self.assertIn("self-numbered-caption", found)

    def test_thin_caption_warns(self):
        found = self.run_lint({"fig_arch": (2370, 1770), "fig_b": (2370, 1770)},
                              {"fig_arch": PIPELINE_CAPTION, "fig_b": "Accuracy results."})
        self.assertIn("thin-caption", found)

    def test_missing_pipeline_figure_warns(self):
        found = self.run_lint(
            {"fig_acc": (2370, 1770)},
            {"fig_acc": "Accuracy of each variant across the four evaluation splits "
                        "reported in the main comparison."})
        self.assertIn("no-pipeline-figure", found)


class TestPaperCrossCheck(LintCase):
    def test_unused_figure_errors(self):
        found = self.run_lint({"fig_arch": (2370, 1770)}, {"fig_arch": PIPELINE_CAPTION},
                              tex=r"\section{Method} No figures included here at all.")
        self.assertIn("unused-figure", found)

    def test_missing_file_errors(self):
        found = self.run_lint({"fig_arch": (2370, 1770)}, {"fig_arch": PIPELINE_CAPTION},
                              tex=r"\includegraphics{../figures/fig_arch.png}"
                                  r"\includegraphics{../figures/fig_absent.png}")
        self.assertIn("missing-file", found)

    def test_fully_consistent_workspace_passes(self):
        found = self.run_lint({"fig_arch": (2370, 1770)}, {"fig_arch": PIPELINE_CAPTION},
                              tex=r"\includegraphics[width=\linewidth]{../figures/fig_arch.png}")
        self.assertEqual(found, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
