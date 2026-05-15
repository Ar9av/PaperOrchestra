#!/usr/bin/env python3
"""
check_idea_density.py — Pre-flight quality assessment for PaperOrchestra inputs.

Exit codes:
  0 — PASS: all checks passed
  1 — FAIL: one or more checks failed
  2 — File not found
"""

import argparse
import re
import sys


def tokenize(text: str) -> set:
    """Return a set of lowercase word tokens from text."""
    return set(re.findall(r"[a-z]+", text.lower()))


def jaccard(set_a: set, set_b: set) -> float:
    """Compute Jaccard similarity between two token sets."""
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def count_words(text: str) -> int:
    """Count whitespace-delimited words."""
    return len(text.split())


def count_markdown_tables(text: str) -> int:
    """Count markdown table separator lines (|---|)."""
    return len(re.findall(r"^\|[-| :]+\|", text, re.MULTILINE))


def count_numeric_values(text: str) -> int:
    r"""Count numeric values matching -?\d+\.?\d*."""
    return len(re.findall(r"-?\d+\.?\d*", text))


def has_hypothesis_signal(text: str) -> tuple:
    """Return (found: bool, matched_word: str)."""
    signals = ["hypothesis", "propose", "method", "approach", "contribution"]
    lower = text.lower()
    for signal in signals:
        if signal in lower:
            return True, signal
    return False, ""


def main():
    parser = argparse.ArgumentParser(
        description="Pre-flight density check for idea.md and experimental_log.md"
    )
    parser.add_argument("--idea", required=True, help="Path to idea.md")
    parser.add_argument("--log", required=True, help="Path to experimental_log.md")
    parser.add_argument(
        "--min-idea-words",
        type=int,
        default=50,
        help="Minimum word count for idea.md (default: 50)",
    )
    parser.add_argument(
        "--min-tables",
        type=int,
        default=1,
        help="Minimum number of markdown tables in experimental_log.md (default: 1)",
    )
    parser.add_argument(
        "--min-numeric-values",
        type=int,
        default=5,
        help="Minimum numeric values in experimental_log.md (default: 5)",
    )
    args = parser.parse_args()

    # Load files
    try:
        with open(args.idea, "r", encoding="utf-8") as f:
            idea_text = f.read()
    except FileNotFoundError:
        print(f"[ERROR] File not found: {args.idea}", file=sys.stderr)
        sys.exit(2)

    try:
        with open(args.log, "r", encoding="utf-8") as f:
            log_text = f.read()
    except FileNotFoundError:
        print(f"[ERROR] File not found: {args.log}", file=sys.stderr)
        sys.exit(2)

    failures = []

    # Check 1: idea.md word count
    idea_words = count_words(idea_text)
    if idea_words >= args.min_idea_words:
        print(f"[PASS] idea.md: {idea_words} words (min: {args.min_idea_words})")
    else:
        print(
            f"[FAIL] idea.md: {idea_words} words (min: {args.min_idea_words})"
        )
        failures.append(f"idea.md word count {idea_words} < {args.min_idea_words}")

    # Check 2: idea.md hypothesis signal
    found, matched = has_hypothesis_signal(idea_text)
    if found:
        print(f'[PASS] idea.md: contains hypothesis signal ("{matched}")')
    else:
        print(
            "[FAIL] idea.md: no hypothesis signal found "
            "(need one of: hypothesis, propose, method, approach, contribution)"
        )
        failures.append("idea.md missing hypothesis signal")

    # Check 3: experimental_log.md table count
    # Prose-style logs are valid as long as they contain enough numeric values
    # (checked next). A missing table is therefore a warning, not a hard fail.
    table_count = count_markdown_tables(log_text)
    if table_count >= args.min_tables:
        print(
            f"[PASS] experimental_log.md: {table_count} tables found "
            f"(min: {args.min_tables})"
        )
    else:
        print(
            f"[WARN] experimental_log.md: {table_count} markdown tables found "
            f"(min: {args.min_tables}). Prose-format logs are accepted when "
            f"numeric values meet the threshold — see Check 4."
        )

    # Check 4: experimental_log.md numeric values
    numeric_count = count_numeric_values(log_text)
    if numeric_count >= args.min_numeric_values:
        print(
            f"[PASS] experimental_log.md: {numeric_count} numeric values "
            f"(min: {args.min_numeric_values})"
        )
    else:
        print(
            f"[FAIL] experimental_log.md: {numeric_count} numeric values "
            f"(min: {args.min_numeric_values})"
        )
        failures.append(
            f"experimental_log.md numeric values {numeric_count} < {args.min_numeric_values}"
        )

    # Check 5: Jaccard similarity (not duplicates)
    idea_tokens = tokenize(idea_text)
    log_tokens = tokenize(log_text)
    similarity = jaccard(idea_tokens, log_tokens)
    if similarity < 0.5:
        print(
            f"[PASS] idea.md / experimental_log.md not duplicates "
            f"(Jaccard: {similarity:.2f})"
        )
    else:
        print(
            f"[FAIL] idea.md / experimental_log.md appear to be duplicates "
            f"(Jaccard: {similarity:.2f} >= 0.50)"
        )
        failures.append(
            f"idea.md and experimental_log.md too similar (Jaccard {similarity:.2f})"
        )

    # Summary
    print()
    if not failures:
        print("Pre-flight density check: PASS")
        sys.exit(0)
    else:
        print(f"Pre-flight density check: FAIL ({len(failures)} check(s) failed)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
