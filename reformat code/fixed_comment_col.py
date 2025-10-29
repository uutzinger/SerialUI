#!/usr/bin/env python3
"""
fixed_comment_col.py
Enforce inline comments to start at a chosen visual column (exact mode only).

Behavior:
- If code ends before --col: place '#' exactly at --col.
- If code extends past --col: place '#' one space after the last code character.

Usage:
  # Check only (prints violations with line numbers & lines)
  python fixed_comment_col.py --col 80 --mode check file.py

  # Fix -> prints modified source to stdout (no files written)
  python fixed_comment_col.py --col 80 --mode fix file.py

Options:
  --tabsize N   tab width for visual column calculation (default: 8)
"""
import argparse
import io
import sys
import tokenize
from pathlib import Path


def visual_col(line: str, scol: int, tabsize: int) -> int:
    """Return 1-based visual column for token start using tab expansion."""
    return len(line[:scol].expandtabs(tabsize)) + 1


def next_col_after_code(line: str, hash_scol: int, tabsize: int) -> int:
    """
    1-based visual column immediately after the last non-space char before the '#'.
    Tabs are expanded with tabsize.
    """
    prefix = line[:hash_scol]
    code_trim = prefix.rstrip(" \t")
    return len(code_trim.expandtabs(tabsize)) + 1


def process_file_to_text(
    src: str,
    target_col: int,
    count_only: bool,
    path: Path,
    tabsize: int,
) -> tuple[str, int]:
    """
    Exact-only rule:
      desired_col = target_col if code ends before target_col
                  = (one space after last code char) if code extends past target_col
    """
    out_lines = src.splitlines(keepends=False)
    violations = 0
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))

    # Map line number -> first COMMENT token (scol, ecol, tok_str)
    comments_by_line = {}
    for tok_type, tok_str, (srow, scol), (erow, ecol), _ in tokens:
        if tok_type == tokenize.COMMENT:
            comments_by_line.setdefault(srow, []).append((scol, ecol, tok_str))

    for i, line in enumerate(out_lines, start=1):
        if i not in comments_by_line:
            continue

        scol, _ecol, tok_str = comments_by_line[i][0]

        # Ignore full-line comments and shebangs
        stripped = line.lstrip()
        if stripped.startswith("#!") or stripped.startswith("#"):
            continue

        # Compute current and desired positions
        current_col = visual_col(line, scol, tabsize)
        code_next_col = next_col_after_code(line, scol, tabsize)

        if code_next_col > target_col:
            desired_col = code_next_col + 1  # one space after last code char
            note = " (code past target → 1 space after code)"
        else:
            desired_col = target_col
            note = ""

        is_violation = (current_col != desired_col)
        if not is_violation:
            continue

        violations += 1

        if count_only:
            print(f"{path}:{i}: comment at col {current_col}, expected {desired_col}{note}")
            print(f"    {line}")
        else:
            # Rewrite line: trim trailing spaces before '#', then add needed spaces
            prefix = line[:scol]
            code_trim = prefix.rstrip(" \t")
            code_next_col = len(code_trim.expandtabs(tabsize)) + 1
            needed_spaces = max(1, desired_col - code_next_col)
            new_line = code_trim + (" " * needed_spaces) + tok_str
            out_lines[i - 1] = new_line

    new_src = "\n".join(out_lines) + ("\n" if src.endswith("\n") else "")
    return (src if count_only else new_src), violations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--col", type=int, default=48, help="Target inline comment column (1-based).")
    ap.add_argument("--tabsize", type=int, default=8, help="Tab width for visual columns.")
    ap.add_argument("--mode", choices=["check", "fix"], default="check")
    ap.add_argument("file")
    args = ap.parse_args()

    in_path = Path(args.file)
    src = in_path.read_text(encoding="utf-8")

    count_only = (args.mode == "check")
    new_src, violations = process_file_to_text(
        src=src,
        target_col=args.col,
        count_only=count_only,
        path=in_path,
        tabsize=args.tabsize,
    )

    if args.mode == "fix":
        print(new_src, end="")

    if args.mode == "check" and violations > 0:
        print(f"\n{violations} violation(s) found.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()