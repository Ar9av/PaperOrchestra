#!/usr/bin/env python3
"""
init_workspace.py — Scaffold a paper-orchestra workspace.

Creates the directory tree expected by the orchestrator and writes a stub
README inside `inputs/` listing the four required input files.

Usage:
    python init_workspace.py --out /path/to/workspace/
"""
import argparse
import os
import sys
import textwrap

# Minimal fallback template.tex written when the user hasn't provided one.
# Covers the sections required by most conference guidelines and is
# compatible with both single- and double-column document classes.
FALLBACK_TEMPLATE = textwrap.dedent(r"""
    \documentclass{article}

    % Minimal template scaffolded by init_workspace.py.
    % Replace \documentclass{article} with your target conference class
    % (e.g. \documentclass[10pt,twocolumn]{article} for double-column venues).
    % The Section Writing Agent will fill the TODO placeholders.
    % The Literature Review Agent fills Introduction and Related Work.

    \usepackage[utf8]{inputenc}
    \usepackage[T1]{fontenc}
    \usepackage{amsmath}
    \usepackage{amssymb}
    \usepackage{booktabs}
    \usepackage{graphicx}
    \usepackage{hyperref}
    \usepackage{geometry}
    \geometry{margin=1in}

    \title{TODO: Title}
    \author{Anonymous Authors}
    \date{}

    \begin{document}
    \maketitle

    \begin{abstract}
    TODO: Abstract.
    \end{abstract}

    \section{Introduction}
    TODO: Introduction. (To be filled by literature-review-agent.)

    \section{Related Work}
    TODO: Related Work. (To be filled by literature-review-agent.)

    \section{Method}
    TODO: Method. (To be filled by section-writing-agent.)

    \section{Experiments}
    TODO: Experiments. (To be filled by section-writing-agent.)

    \section{Conclusion}
    TODO: Conclusion. (To be filled by section-writing-agent.)

    \bibliographystyle{plain}
    \bibliography{refs}

    \end{document}
""").lstrip()

WORKSPACE_DIRS = [
    "inputs",
    "inputs/figures",
    "figures",
    "drafts",
    "refinement",
    "final",
    "cache",          # S2 verification cache (s2_cache.json written here)
]

INPUTS_README = textwrap.dedent("""\
    # Inputs

    The paper-orchestra pipeline expects the four files below in this
    directory before you start. Optional figures go in `figures/`.

    ## Required

    - `idea.md`                  — Idea Summary (Sparse or Dense; see io-contract.md)
    - `experimental_log.md`      — Setup, raw numeric data, qualitative observations
    - `template.tex`             — LaTeX template for the target conference
    - `conference_guidelines.md` — Page limit, mandatory sections, formatting rules

    ## Optional

    - `figures/`                 — Pre-existing figures (PNG/PDF). If empty, the
                                   plotting agent generates everything from scratch.

    See `skills/paper-orchestra/references/io-contract.md` in the repo for the
    exact schemas of each file.
    """)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True, help="Path to the workspace directory to create")
    p.add_argument("--force", action="store_true",
                   help="Allow scaffolding into a non-empty directory")
    args = p.parse_args()

    out = os.path.abspath(args.out)

    if os.path.exists(out) and os.listdir(out) and not args.force:
        print(f"ERROR: {out} exists and is non-empty. Use --force to overlay.", file=sys.stderr)
        return 1

    for sub in WORKSPACE_DIRS:
        os.makedirs(os.path.join(out, sub), exist_ok=True)

    inputs_readme = os.path.join(out, "inputs", "README.md")
    if not os.path.exists(inputs_readme):
        with open(inputs_readme, "w") as f:
            f.write(INPUTS_README)

    # Write a fallback template.tex if none exists yet.
    # Users can overwrite it with their conference-specific class at any time.
    template_path = os.path.join(out, "inputs", "template.tex")
    if not os.path.exists(template_path):
        with open(template_path, "w") as f:
            f.write(FALLBACK_TEMPLATE)
        print("INFO: wrote a minimal fallback template.tex to inputs/. "
              "Replace \\documentclass{article} with your target conference class if needed.")

    print(f"Workspace scaffolded at: {out}")
    print("Next: drop your idea.md, experimental_log.md, and")
    print("conference_guidelines.md into the inputs/ subdirectory, then run:")
    print(f"  python {os.path.dirname(__file__)}/validate_inputs.py --workspace {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
