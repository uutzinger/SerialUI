#!/usr/bin/env python3
"""
Parser parity tests: Python parser paths in Qgraph_helper vs C extensions.

Run:
    python3 testing/test_parser_parity.py
"""

from pathlib import Path
import sys
import numpy as np


# Ensure imports work when run from repository root or testing directory.
ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "helpers"
if str(HELPERS) not in sys.path:
    sys.path.insert(0, str(HELPERS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from helpers.Qgraph_helper import QChart
from line_parsers import simple_parser, header_parser


class DummySignal:
    def __init__(self):
        self.messages = []

    def emit(self, level, msg):
        self.messages.append((level, msg))


class DummyBuffer:
    def __init__(self):
        self.arr = None

    def push(self, arr):
        self.arr = np.array(arr, copy=True)


class DummyChart:
    pass


def _arrays_equal(a: np.ndarray, b: np.ndarray) -> bool:
    return a.shape == b.shape and np.allclose(a, b, equal_nan=True)


def run_python_simple(lines, channel_names=None):
    d = DummyChart()
    d.data_array = np.empty((64, 64), dtype=np.float64)
    d.data_array[:] = np.nan
    d.buffer = DummyBuffer()
    d.SEG_SPLIT = QChart.SEG_SPLIT
    d.ensure_capacity = QChart.ensure_capacity
    d.parse_segment_numbers = QChart.parse_segment_numbers
    d.channel_names_dict = {} if channel_names is None else dict(channel_names)
    d.logSignal = DummySignal()
    d.mtoc_process_lines_simple = 0.0
    QChart.process_lines_simple(d, lines)
    return d.buffer.arr, d.channel_names_dict


def run_python_header(lines, channel_names=None):
    d = DummyChart()
    d.data_array = np.empty((64, 64), dtype=np.float64)
    d.data_array[:] = np.nan
    d.buffer = DummyBuffer()
    d.SEG_SPLIT = QChart.SEG_SPLIT
    d.ensure_capacity = QChart.ensure_capacity
    d.parse_segment_numbers = QChart.parse_segment_numbers
    d.split_headers_line = QChart.split_headers_line
    d.channel_names_dict = {} if channel_names is None else dict(channel_names)
    d.logSignal = DummySignal()
    d.mtoc_process_lines_header = 0.0
    QChart.process_lines_header(d, lines)
    return d.buffer.arr, d.channel_names_dict


def assert_case(tag, py_func, c_func, lines, channel_names=None):
    py_arr, py_names = py_func(lines, channel_names)
    c_arr, _shape, c_names = c_func(
        lines,
        channel_names={} if channel_names is None else dict(channel_names),
        strict=False,
        gil_release=False,
    )

    assert _arrays_equal(py_arr, c_arr), (
        f"{tag}: data mismatch\n"
        f"lines={lines}\n"
        f"py shape={py_arr.shape}, c shape={c_arr.shape}\n"
        f"py=\n{py_arr}\n\nc=\n{c_arr}\n"
    )
    assert py_names == c_names, (
        f"{tag}: channel name mismatch\n"
        f"lines={lines}\n"
        f"py names={py_names}\n"
        f"c names={c_names}\n"
    )


def main():
    simple_cases = [
        ("simple/basic", ["1 2 3,4 5", "6,7 8 9"], None),
        ("simple/invalid-mid-token", ["1 2 bad 3,4 5"], None),
        ("simple/prefix-junk", ["1abc 2,3"], None),
        ("simple/empty-lines", ["", "   ", ",,"], None),
        ("simple/existing-names", ["1,2,3"], {"A": 0, "B": 1}),
        ("simple/invalid-only", ["abc def"], None),
    ]

    header_cases = [
        ("header/basic", ["A:1 2 3, B:4 5"], None),
        ("header/headerless-prefix", ["1 2, A:3 4"], None),
        ("header/repeated-header", ["A:1 2 A:3 4"], None),
        ("header/spaces-in-name", ["Blood Pressure:121 122"], None),
        ("header/invalid-token-mid", ["A:1 bad 2"], None),
        ("header/unnamed", ["1 2,3", "A:4"], None),
        ("header/single-to-multi", ["A:1 2", "A:3,4"], None),
        ("header/multi-repeat", ["A:1,2 A:3,4"], None),
    ]

    for tag, lines, names in simple_cases:
        assert_case(tag, run_python_simple, simple_parser.parse_lines, lines, names)

    for tag, lines, names in header_cases:
        assert_case(tag, run_python_header, header_parser.parse_lines, lines, names)

    print(f"Parity checks passed: {len(simple_cases) + len(header_cases)} cases")


if __name__ == "__main__":
    main()
