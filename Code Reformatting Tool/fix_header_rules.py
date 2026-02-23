#!/usr/bin/env python3
"""
fix_header_rules.py

Normalize "rule" lines made of repeated '#', '=' or '-' in a single text file.

Modes:
- check: print normalized file to stdout, violations to stderr, exit non-zero on violations.
- fix:   print normalized file to stdout.

Target specification:
- Global targets (mutually exclusive):
    --len N    -> set repeat length N for all rule types
    --col N    -> set target end column N for all rule types (visual column)
- Per-type overrides:
    --len-hash N   or --col-hash N    for '#'
    --len-equal N  or --col-equal N   for '='
    --len-dash N   or --col-dash N    for '-'

If no target provided at all, lengths are inferred as the maximum seen per type (length semantics).

Comment safety (default):
- By default only lines that are comments are modified, and lines inside Python strings are skipped.
  Use --include-non-comments to also modify non-comment rule-like lines.

reST titles:
- --from-title makes underline/overline lengths match the title text length (length semantics).
"""
from __future__ import annotations
import argparse, re, sys, io, tokenize
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Literal

# Two forms:
#  1) Comment-prefixed:  ^indent '#'+spaces char{3,} spaces*$
#     e.g. "# =======", "# ----------", "# #######"
RULE_COMMENT_RE = re.compile(
    r'^(?P<indent>[ \t]*)#(?P<prefix_space>[ \t]+)'
    r'(?P<char>[#=\-])(?P<run>(?P=char){2,})[ \t]*$'
)
#  2) Pure run:         ^indent char{3,} spaces*$
#     e.g. "=====", "-----", "#####"
RULE_PURE_RE = re.compile(
    r'^(?P<indent>[ \t]*)(?P<char>[#=\-])(?P<run>(?P=char){2,})[ \t]*$'
)

SpecMode = Literal["length", "column"]
Spec = Dict[str, Optional[tuple[SpecMode, int]]]

def detect_rule(line: str) -> Optional[Tuple[str, str, str, int]]:
    """
    Return (indent, prefix, char, run_len) if line is a rule, else None.
      indent: leading whitespace
      prefix: "" or "# " (or "#   ") – comment marker and spaces BEFORE the run
      char:   '#', '=' or '-'
      run_len: number of repeated 'char'
    """
    m = RULE_COMMENT_RE.match(line)
    if m:
        indent = m.group("indent")
        prefix = "#" + m.group("prefix_space")
        ch = m.group("char")
        run_len = len(m.group("run")) + 1
        return indent, prefix, ch, run_len
    m = RULE_PURE_RE.match(line)
    if m:
        indent = m.group("indent")
        prefix = ""  # no comment prefix
        ch = m.group("char")
        run_len = len(m.group("run")) + 1
        return indent, prefix, ch, run_len
    return None

def infer_max_lengths(lines: List[str]) -> Dict[str, int]:
    maxlen = {'#': 0, '=': 0, '-': 0}
    for ln in lines:
        d = detect_rule(ln)
        if d:
            _, _, ch, n = d
            if n > maxlen[ch]:
                maxlen[ch] = n
    return maxlen

def visual_start_col(indent: str, prefix: str, tabsize: int) -> int:
    """
    1-based visual column where the FIRST run-character sits.
    Accounts for indent and optional comment prefix ('# ').
    """
    return len((indent + prefix).expandtabs(tabsize)) + 1

def is_probably_python(path: Path, text: str) -> bool:
    if path.suffix == ".py":
        return True
    first = text.splitlines(True)[:1]
    return bool(first and first[0].startswith("#!") and "python" in first[0].lower())

def classify_python_tokens(text: str) -> tuple[set[int], set[int]]:
    comment_lines: set[int] = set()
    in_string_lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            ttype = tok.type
            (srow, _), (erow, _) = tok.start, tok.end
            if ttype == tokenize.COMMENT:
                comment_lines.add(srow)
            elif ttype == tokenize.STRING:
                for ln in range(srow, erow + 1):
                    in_string_lines.add(ln)
    except Exception:
        pass
    return comment_lines, in_string_lines

def build_spec_from_args(args) -> Spec:
    conflicts = []
    if args.len_hash is not None and args.col_hash is not None:
        conflicts.append("'#': both --len-hash and --col-hash")
    if args.len_equal is not None and args.col_equal is not None:
        conflicts.append("'=': both --len-equal and --col-equal")
    if args.len_dash is not None and args.col_dash is not None:
        conflicts.append("'-': both --len-dash and --col-dash")
    if conflicts:
        print("Error: Conflicting per-type options:\n  " + "\n  ".join(conflicts), file=sys.stderr)
        sys.exit(2)

    spec: Spec = {'#': None, '=': None, '-': None}
    if args.len is not None:
        spec = {'#': ("length", args.len), '=': ("length", args.len), '-': ("length", args.len)}
    if args.col is not None:
        spec = {'#': ("column", args.col), '=': ("column", args.col), '-': ("column", args.col)}

    if args.len_hash is not None:  spec['#'] = ("length", args.len_hash)
    if args.len_equal is not None: spec['='] = ("length", args.len_equal)
    if args.len_dash is not None:  spec['-'] = ("length", args.len_dash)

    if args.col_hash is not None:  spec['#'] = ("column", args.col_hash)
    if args.col_equal is not None: spec['='] = ("column", args.col_equal)
    if args.col_dash is not None:  spec['-'] = ("column", args.col_dash)
    return spec

def normalize_rules(
    text: str,
    mode: str,
    spec: Spec,
    from_title: bool,
    tabsize: int,
    path: Path,
    only_comments: bool,
    is_python: bool,
    py_comment_lines: set[int],
    py_in_string_lines: set[int],
    debug: bool = False,
) -> Tuple[str, int, List[str]]:
    lines = text.splitlines(keepends=False)
    msgs: List[str] = []
    changes_or_viol = 0
    out: List[str] = lines[:]

    if all(v is None for v in spec.values()):
        maxlens = infer_max_lengths(lines)
        spec = {k: (("length", v) if v > 0 else None) for k, v in maxlens.items()}

    def prev_nonempty(i):
        j = i - 1
        while j >= 0 and lines[j].strip() == "":
            j -= 1
        return j

    def next_nonempty(i, n):
        j = i + 1
        while j < n and lines[j].strip() == "":
            j += 1
        return j

    def find_title_len(lines_: List[str], idx_: int) -> Optional[int]:
        n = len(lines_)
        j = prev_nonempty(idx_)
        if j is not None and j >= 0 and detect_rule(lines_[idx_]) and not detect_rule(lines_[j]):
            return len(lines_[j].rstrip("\n"))
        j = next_nonempty(idx_, n)
        k = next_nonempty(j, n) if j is not None and j < n else None
        if j is not None and k is not None:
            over = detect_rule(lines_[idx_])
            title = lines_[j].rstrip("\n")
            under = detect_rule(lines_[k])
            if over and under and over[2] == under[2]:
                return len(title)
        return None

    for idx, line in enumerate(lines):
        info = detect_rule(line)
        if not info:
            continue

        indent, prefix, ch, run_len = info

        # Skip string literals in Python
        if is_python and (idx + 1) in py_in_string_lines:
            continue

        # Only-comments filter:
        if only_comments:
            stripped = line.lstrip()
            if is_python:
                if not (stripped.startswith("#") and (idx + 1) in py_comment_lines):
                    continue
            else:
                if not stripped.startswith("#"):
                    continue

        # Target length precedence: explicit spec > from_title > keep
        mode_val = spec.get(ch)
        if mode_val is not None:
            mode_name, val = mode_val
            if mode_name == "length":
                target_len = max(1, int(val))
                msg_descr = f"{ch * target_len} (len {run_len} -> {target_len})"
                start_col = visual_start_col(indent, prefix, tabsize)
                end_col = start_col + target_len - 1
            else:
                start_col = visual_start_col(indent, prefix, tabsize)
                end_col = int(val)
                target_len = max(1, end_col - start_col + 1)
                msg_descr = f"{ch * target_len} (end col -> {end_col})"
        else:
            tlen = find_title_len(lines, idx) if from_title else None
            if tlen is not None and tlen > 0:
                target_len = tlen
                msg_descr = f"{ch * target_len} (len from title -> {target_len})"
                start_col = visual_start_col(indent, prefix, tabsize)
                end_col = start_col + target_len - 1
            else:
                target_len = run_len
                msg_descr = None
                start_col = visual_start_col(indent, prefix, tabsize)
                end_col = start_col + target_len - 1

        if debug and target_len != run_len:
            print(
                f"DBG {path}:{idx+1} ch={ch} prefix={'yes' if prefix else 'no'} "
                f"start_col={start_col} -> end_col={end_col} target_len={target_len}",
                file=sys.stderr,
            )

        if run_len != target_len:
            changes_or_viol += 1
            if mode == "check" and msg_descr:
                msgs.append(f"{path}:{idx+1}: {ch*run_len}  -> expected {msg_descr}")
            out[idx] = f"{indent}{prefix}{ch * target_len}"

    new_text = "\n".join(out) + ("\n" if text.endswith("\n") else "")
    return new_text, changes_or_viol, msgs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["check", "fix"], default="check")
    ap.add_argument("--debug", action="store_true", help="Print calculation details to stderr for modified lines.")

    # Global targets (mutually exclusive)
    meg = ap.add_mutually_exclusive_group()
    meg.add_argument("--len", type=int, help="Universal length for all rule types.")
    meg.add_argument("--col", type=int, help="Universal end column (visual) for all rule types.")

    # Per-type targets
    ap.add_argument("--len-hash",  type=int, help="Length for '#' rules.")
    ap.add_argument("--len-equal", type=int, help="Length for '=' rules.")
    ap.add_argument("--len-dash",  type=int, help="Length for '-' rules.")
    ap.add_argument("--col-hash",  type=int, help="End column for '#' rules (visual).")
    ap.add_argument("--col-equal", type=int, help="End column for '=' rules (visual).")
    ap.add_argument("--col-dash",  type=int, help="End column for '-' rules (visual).")

    ap.add_argument("--tabsize",   type=int, default=8, help="Tab width for visual column calculation.")
    ap.add_argument("--from-title", action="store_true", help="Match rule length to title text length (reST-style).")

    # Default: only modify comment lines
    ap.set_defaults(only_comments=True)
    oc = ap.add_mutually_exclusive_group()
    oc.add_argument("--only-comments", dest="only_comments", action="store_true",
                    help="Modify only comment rule lines (default).")
    oc.add_argument("--include-non-comments", dest="only_comments", action="store_false",
                    help="Also modify non-comment rule-like lines.")

    ap.add_argument("file", help="Single input file to process.")
    args = ap.parse_args()

    p = Path(args.file)
    src = p.read_text(encoding="utf-8")

    spec = build_spec_from_args(args)

    is_py = is_probably_python(p, src)
    if args.only_comments and is_py:
        py_comment_lines, py_in_string_lines = classify_python_tokens(src)
    else:
        py_comment_lines, py_in_string_lines = set(), set()

    new_text, count, msgs = normalize_rules(
        text=src,
        mode=args.mode,
        spec=spec,
        from_title=args.from_title,
        tabsize=args.tabsize,
        path=p,
        only_comments=args.only_comments,
        is_python=is_py,
        py_comment_lines=py_comment_lines,
        py_in_string_lines=py_in_string_lines,
        debug=args.debug,
    )

    # Always print normalized content to stdout
    print(new_text, end="")

    if args.mode == "check":
        for m in msgs:
            print(m, file=sys.stderr)
        if count > 0:
            print(f"\n{count} rule line(s) inconsistent.", file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    main()