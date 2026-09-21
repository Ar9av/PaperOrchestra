#!/usr/bin/env python3
"""
figure_lint.py — Check rendered figures and their captions before Step 4
splices them into the paper.

Figure defects are expensive in exactly the wrong way: they survive every
prose refinement iteration untouched, and they are the first thing a reviewer
sees. All of the checks here are mechanical — pixel dimensions, caption
coverage, whether the draft actually uses what Step 2 rendered.

PNG geometry is read from the IHDR chunk and DPI from pHYs directly, so this
script needs no imaging library (the repo ships deterministic helpers only).

Severity:
  ERROR — the paper will be wrong or incomplete (missing caption, unused
          figure, \\includegraphics pointing at a file that is not there,
          unusably small raster)
  WARN  — a reviewer will notice (low resolution, extreme aspect ratio,
          caption that numbers itself, caption too thin to carry a setting)

Exit codes:
    0 — no ERRORs (and no WARNs, if --strict)
    1 — at least one ERROR, or any WARN under --strict
    2 — figures directory or captions file missing

Usage:
    python figure_lint.py --figures workspace/figures \\
        --captions workspace/figures/captions.json \\
        [--paper workspace/drafts/paper.tex] [--json report.json] [--strict]
"""
import argparse
import json
import os
import re
import struct
import sys

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# A single-column figure in a two-column template is ~3.3in wide; 300 dpi is
# the usual camera-ready floor, so ~1000px is the practical minimum width.
MIN_WIDTH_WARN = 1000
MIN_WIDTH_ERROR = 600
MAX_ASPECT = 4.0

CAPTION_NUMBERING = re.compile(r"^\s*(?:figure|fig\.?)\s*\d*\s*[:.]?\s", re.IGNORECASE)
PIPELINE_WORDS = re.compile(
    r"\b(?:architecture|pipeline|overview|framework|system|workflow|schematic)\b",
    re.IGNORECASE,
)


def png_geometry(path: str) -> dict | None:
    """Return {width, height, dpi} for a PNG, or None if it is not one."""
    with open(path, "rb") as f:
        head = f.read(33)
        if not head.startswith(PNG_SIGNATURE) or head[12:16] != b"IHDR":
            return None
        width, height = struct.unpack(">II", head[16:24])

        dpi = None
        f.seek(8)
        while True:
            header = f.read(8)
            if len(header) < 8:
                break
            length, ctype = struct.unpack(">I", header[:4])[0], header[4:8]
            if ctype == b"pHYs":
                ppu_x, _, unit = struct.unpack(">IIB", f.read(9))
                if unit == 1:                       # 1 = metre
                    dpi = round(ppu_x * 0.0254)
                break
            if ctype == b"IDAT":                    # pHYs always precedes IDAT
                break
            f.seek(length + 4, os.SEEK_CUR)         # payload + CRC
    return {"width": width, "height": height, "dpi": dpi}


def referenced_figures(tex: str) -> set[str]:
    """Basenames (without extension) of every \\includegraphics target."""
    out = set()
    for m in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}", tex):
        out.add(os.path.splitext(os.path.basename(m.group(1).strip()))[0])
    return out


def lint(figures_dir: str, captions: dict, tex: str | None) -> list[dict]:
    findings: list[dict] = []

    def add(sev: str, code: str, subject: str, msg: str) -> None:
        findings.append({"severity": sev, "code": code, "figure": subject, "message": msg})

    files = sorted(f for f in os.listdir(figures_dir)
                   if f.lower().endswith((".png", ".pdf", ".jpg", ".jpeg")))
    stems = {os.path.splitext(f)[0] for f in files}

    for name in files:
        stem = os.path.splitext(name)[0]
        path = os.path.join(figures_dir, name)

        geo = png_geometry(path) if name.lower().endswith(".png") else None
        if geo:
            w, h = geo["width"], geo["height"]
            if w < MIN_WIDTH_ERROR:
                add("ERROR", "unusable-resolution", stem,
                    f"{w}x{h}px is too small to print; re-render at dpi>=300")
            elif w < MIN_WIDTH_WARN:
                add("WARN", "low-resolution", stem,
                    f"{w}x{h}px (~{w // 3}dpi at single-column width); "
                    "re-render at dpi>=300")
            ratio = max(w / h, h / w)
            if ratio > MAX_ASPECT:
                add("WARN", "extreme-aspect", stem,
                    f"aspect ratio {w}:{h} ({ratio:.1f}:1) will be illegible when "
                    "scaled to column width")

        if stem not in captions:
            add("ERROR", "missing-caption", stem, "rendered figure has no entry in captions.json")

        if tex is not None and stem not in referenced_figures(tex):
            add("ERROR", "unused-figure", stem,
                "not referenced by any \\includegraphics; the prompt requires every "
                "rendered figure to appear in the paper")

    for stem, caption in captions.items():
        if stem not in stems:
            add("ERROR", "orphan-caption", stem,
                "captions.json entry has no corresponding file in the figures directory")
        text = (caption or "").strip()
        if not text:
            add("ERROR", "empty-caption", stem, "caption is empty")
            continue
        if CAPTION_NUMBERING.match(text):
            add("WARN", "self-numbered-caption", stem,
                "caption starts with 'Figure N'; LaTeX numbers figures itself")
        if len(text.split()) < 8:
            add("WARN", "thin-caption", stem,
                f"caption is {len(text.split())} words; state what is plotted, on what "
                "axes, and what the reader should conclude")

    if captions and not any(PIPELINE_WORDS.search(c or "") for c in captions.values()):
        add("WARN", "no-pipeline-figure", "(set)",
            "no caption describes an architecture/pipeline/overview figure; papers "
            "without one make the reader reconstruct the method from prose")

    if tex is not None:
        for ref in referenced_figures(tex):
            if ref not in stems:
                add("ERROR", "missing-file", ref,
                    "\\includegraphics references a file that is not in the figures directory")

    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--figures", required=True, help="Path to workspace/figures")
    ap.add_argument("--captions", help="Path to captions.json (default: <figures>/captions.json)")
    ap.add_argument("--paper", help="Optional draft to cross-check \\includegraphics against")
    ap.add_argument("--json", help="Optional path for the machine-readable report")
    ap.add_argument("--strict", action="store_true", help="Exit 1 on WARNs too")
    args = ap.parse_args()

    captions_path = args.captions or os.path.join(args.figures, "captions.json")
    if not os.path.isdir(args.figures):
        print(f"ERROR: figures directory not found: {args.figures}", file=sys.stderr)
        return 2
    if not os.path.exists(captions_path):
        print(f"ERROR: captions file not found: {captions_path}", file=sys.stderr)
        return 2

    with open(captions_path) as f:
        captions = json.load(f)

    tex = None
    if args.paper:
        if not os.path.exists(args.paper):
            print(f"ERROR: paper not found: {args.paper}", file=sys.stderr)
            return 2
        with open(args.paper) as f:
            tex = f.read()

    findings = lint(args.figures, captions, tex)
    errors = [f for f in findings if f["severity"] == "ERROR"]
    warns = [f for f in findings if f["severity"] == "WARN"]

    print(f"figure_lint: {len(captions)} caption(s), {len(errors)} error(s), "
          f"{len(warns)} warning(s)")
    for f in findings:
        print(f"  {f['severity']:5s} [{f['code']}] {f['figure']}: {f['message']}")

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)) or ".", exist_ok=True)
        with open(args.json, "w") as fh:
            json.dump({"findings": findings}, fh, indent=2, ensure_ascii=False)

    if errors or (warns and args.strict):
        return 1
    if not findings:
        print("OK: figures and captions are consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
