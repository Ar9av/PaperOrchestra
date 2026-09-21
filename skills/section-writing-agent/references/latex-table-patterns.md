# LaTeX Table Patterns

Conventions for building LaTeX tables from `experimental_log.md` raw numeric
data, per the Section Writing Agent prompt requirements (App. F.1 p.47, item
2 "Data & Tables").

## Required: booktabs

Always use the `booktabs` package. The preamble in a typical conference
template already includes it; if not, add:

```latex
\usepackage{booktabs}
```

## Three rules only

Booktabs uses **only** three horizontal rules: `\toprule`, `\midrule`,
`\bottomrule`. No `\hline`. No vertical bars.

```latex
\begin{table}[t]
\centering
\caption{Comparison of methods on Dataset X.}
\label{tab:main_results}
\begin{tabular}{lccc}
\toprule
Method      & Accuracy & F1 & Latency (ms) \\
\midrule
Baseline    & 78.2     & 0.79 & 12.3 \\
\textbf{Ours} & \textbf{85.4} & \textbf{0.87} & \textbf{8.1} \\
\bottomrule
\end{tabular}
\end{table}
```

## From experimental_log markdown table → LaTeX

`experimental_log.md` contains tables in plain markdown:

```markdown
## 2. Raw Numeric Data

### Table 1: Performance comparison on Dataset X

| Method   | Accuracy | F1   | Latency (ms) |
|----------|----------|------|--------------|
| Baseline | 78.2     | 0.79 | 12.3         |
| Ours-S   | 82.1     | 0.83 | 9.4          |
| Ours-L   | 85.4     | 0.87 | 8.1          |
```

The `extract_metrics.py` helper parses these into JSON:

```json
{
  "tables": [
    {
      "label": "Performance comparison on Dataset X",
      "headers": ["Method", "Accuracy", "F1", "Latency (ms)"],
      "rows": [
        ["Baseline", "78.2", "0.79", "12.3"],
        ["Ours-S", "82.1", "0.83", "9.4"],
        ["Ours-L", "85.4", "0.87", "8.1"]
      ]
    }
  ]
}
```

The Section Writing Agent then converts each entry to a `table` environment
verbatim. Important rules from the prompt:

- **Do not hallucinate numbers.** Copy the exact values from
  `extract_metrics.py`'s output.
- **Bold the best result** in each column (the convention for top-tier ML
  papers).
- **Use `\multicolumn{N}{c}{...}` for grouped headers** when the table has
  metric families (e.g., "Seen (J%)", "Seen F", "Unseen (J%)", "Unseen F").
- **Right-align numeric columns** with `r`, left-align text columns with `l`.
  Use `c` only for narrow centered identifiers.
- **Use `\textbf{...}` for bold**, never `**...**` (markdown).

## Readability rules

Booktabs gets the rules right; these get the table *read* right. A reviewer
spends seconds on a results table and forms an opinion from it.

- **Label metric direction in the header** — `Accuracy $\uparrow$`,
  `LPIPS $\downarrow$`, `Latency (ms) $\downarrow$`. Never make a reader infer
  which way is better. `table_lint.py` warns on any numeric column whose
  header carries no arrow.
- **Put units in the header**, not in the cells: `Latency (ms)`, not
  `12.3 ms` repeated down the column.
- **Keep decimal precision constant within a column.** `85.4` and `8.14` in
  one column reads as two different measurements. Pick the precision the
  weakest measurement justifies and hold it.
- **One table, one message.** Unrelated results in one table means neither
  lands. Split rather than widen.
- **Group multi-dataset results with `\multicolumn` + `\cmidrule`**, never
  with vertical separators:

```latex
\toprule
& \multicolumn{2}{c}{Seen} & \multicolumn{2}{c}{Unseen} \\
\cmidrule(lr){2-3} \cmidrule(lr){4-5}
Method & J $\uparrow$ & F $\uparrow$ & J $\uparrow$ & F $\uparrow$ \\
\midrule
```

- **Highlight sparingly.** Bold the best result; if a second emphasis is
  genuinely needed, underline the runner-up. Colored cells beyond one or two
  rows stop being emphasis.
- **Captions carry the setting, protocol, and notation** — not discussion. A
  six-word caption is a label, not a caption.

## Checking a draft

```bash
python skills/section-writing-agent/scripts/table_lint.py workspace/drafts/paper.tex
```

ERRORs are booktabs/LaTeX rule violations (vertical rules, `\hline`, caption
below the tabular, missing rules); WARNs are the readability conventions
above. Exit 1 on any ERROR, or on any WARN with `--strict`.

## Wide tables (2-column conference templates)

For tables that don't fit single-column width, use `table*` and `tabular*`
or `tabularx`:

```latex
\begin{table*}[t]
\centering
\caption{Ablation across all 6 components on 4 splits.}
\label{tab:ablation}
\begin{tabular}{lcccccc}
\toprule
Variant       & Seen J & Seen F & Unseen J & Unseen F & Mix J & Mix F \\
\midrule
Full          & 43.43  & 0.568  & 54.58    & 0.664    & 49.01 & 0.616 \\
- TB          & 33.05  & 0.507  & 50.48    & 0.657    & 41.77 & 0.582 \\
- TMFL        & 40.35  & 0.579  & 45.54    & 0.627    & 42.95 & 0.603 \\
\bottomrule
\end{tabular}
\end{table*}
```

The closing `\end{table*}` must match the opening `\begin{table*}`. The
`latex_sanity.py` script catches mismatches.

## Caption placement

```latex
\begin{table}[t]
\centering
\caption{Caption text here.}        % BEFORE the tabular for tables
\label{tab:my_label}
\begin{tabular}{...}
...
\end{tabular}
\end{table}
```

(For figures, `\caption` goes AFTER `\includegraphics`, not before. See
`figure-integration.md`.)

## Common pitfalls

| Issue | Fix |
|---|---|
| `\hline` everywhere | Replace with `\toprule` (top), `\midrule` (between header and body), `\bottomrule` (bottom). |
| Column too wide, runs off page | Switch to `table*` + `tabular*`. |
| Vertical bars | Remove. Booktabs forbids vertical rules. |
| Misaligned decimals | Use `S[table-format=2.2]` from `siunitx` if available, else right-align with `r`. |
| Table after Conclusion | Move it before. The prompt mandates this. |
| Hallucinated values | Cross-check against `extract_metrics.py` output. |

## Figures floating into or after the References section

**This is the most common final-layout bug.** When many figures appear in the
Experiments section and the bibliography is near the end, LaTeX cannot place all
floats in the text body and defers them past `\bibliography`.

**Fix**: always emit `\clearpage` immediately before `\bibliographystyle{...}`:

```latex
% Flush all pending floats before the bibliography
\clearpage

\bibliographystyle{plainnat}
\bibliography{refs}
```

The `\clearpage` forces LaTeX to output every deferred float on their own pages
before starting the reference list. Without it, figures that could not fit in the
Experiments section will appear between the References heading and the reference
entries, or after the last reference.

## Cross-referencing without cleveref

When the conference template uses `\usepackage[capitalize]{cleveref}`, the
Section Writing Agent should produce `\cref{fig:X}` and `\cref{tab:Y}`.
However, if `cleveref` is stripped (e.g., due to a minimal TeX installation),
bare `\ref{}` produces only the number with no "Figure" or "Table" prefix,
which reads as isolated numbers in the prose.

**Pattern to use when `cleveref` is absent**:

```latex
Figure~\ref{fig:overview}   % tilde prevents line break before number
Table~\ref{tab:main-results}
```

Never write just `\ref{fig:overview}` without a prefix; readers will see "...see 3."

The host agent must check whether `cleveref.sty` is available in the TeX
installation before choosing `\cref{}` vs `Figure~\ref{}`. A safe default is
to always use the `Figure~\ref{}` form; it degrades gracefully and works
everywhere.
