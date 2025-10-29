#!/usr/bin/env python3
import time
import random
import math
import argparse
import re
import statistics
import numpy as np
from numba import njit

# C++ parser
from line_parsers.simple_parser import parse_lines as c_parse_lines

# Regexes (if you still need named segments later)
NAMED_SEGMENT_REGEX  = re.compile(r'([A-Za-z ]+):([\d\s;,]+)')
SEGMENT_SPLIT_REGEX  = re.compile(r'[,;]+')
SEG_SPLIT           = SEGMENT_SPLIT_REGEX.split

# Initial capacities for the NumPy-based parser
INIT_ROWS = 512
INIT_COLS = 16

@njit(cache=True)
def _ensure_capacity(arr, rows, cols, rows_needed, cols_needed):
    """
    Nopython‐compatible growth logic for a 2D float64 array.
    Returns (new_arr, new_rows, new_cols).
    """
    # how many extra rows/cols do we need?
    rows_to_add = 0
    if rows_needed > rows:
        rows_to_add = rows_needed - rows + 1
        half = rows // 2
        if half > rows_to_add:
            rows_to_add = half

    cols_to_add = 0
    if cols_needed + 1 > cols:
        cols_to_add = cols_needed - cols + 1
        half = cols // 2
        if half > cols_to_add:
            cols_to_add = half

    # only grow if needed
    if rows_to_add or cols_to_add:
        new_rows = rows + rows_to_add
        new_cols = cols + cols_to_add
        # create a fresh array, filled with NaN
        new_arr = np.full((new_rows, new_cols), np.nan, dtype=arr.dtype)
        # copy old data into the top-left
        for i in range(rows):
            for j in range(cols):
                new_arr[i, j] = arr[i, j]
        return new_arr, new_rows, new_cols
    else:
        return arr, rows, cols
def py_parse_lines_np(lines):
    """
    Pure‐Python+NumPy parser that grows its own array as needed.
    Returns a 2D NumPy float64 array.
    """
    # allocate local array (all NaNs)
    rows, cols = INIT_ROWS, INIT_COLS
    data = np.full((rows, cols), np.nan, dtype=np.float64)

    row = 0
    num_columns = 0

    for line in lines:
        # decode bytes if needed
        if isinstance(line, (bytes, bytearray)):
            line = line.decode("utf-8")

        # split into segments, dropping empty tokens
        segments = [seg.strip() for seg in SEG_SPLIT(line) if seg.strip()]

        # parse each segment into floats
        max_len_segment = 0
        for col, segment in enumerate(segments):
            # parse whitespace‐separated floats
            try:
                vals = np.fromstring(segment, dtype=np.float64, sep=' ')
            except Exception:
                vals = np.array([], dtype=np.float64)

            ln = vals.size
            max_len_segment = max(max_len_segment, ln)
            num_columns = max(num_columns, col + 1)

            # ensure capacity for rows (row + ln) and column col
            data, rows, cols = _ensure_capacity(data, rows, cols,
                                                row + ln, col)

            # store
            if ln > 0:
                data[row:row+ln, col] = vals

        # if no segment yielded any number, still produce one NaN row
        if max_len_segment == 0:
            max_len_segment = 1

        row += max_len_segment

    # trim to actual used size
    return data[:row, :num_columns]

def py_parse_lines(lines):
    """
    Pure‐Python fallback that returns a list-of-lists.
    """
    result = []
    for line in lines:
        if isinstance(line, (bytes, bytearray)):
            line = line.decode("utf-8")

        # 1) split channels
        channels = []
        start = 0
        for i, ch in enumerate(line):
            if ch in ",;":
                channels.append(line[start:i])
                start = i + 1
        channels.append(line[start:])

        # 2) parse floats or NaN
        parsed = []
        any_valid = False
        for ch in channels:
            tokens = ch.split()
            col_nums = []
            for tok in tokens:
                try:
                    v = float(tok)
                    col_nums.append(v)
                    any_valid = True
                except ValueError:
                    col_nums.append(math.nan)
            parsed.append(col_nums)

        # 3) how many rows this line makes?
        max_len = max((len(col) for col in parsed), default=0)
        if not any_valid:
            max_len = 1
            parsed = [[] for _ in parsed]

        # 4) emit rows
        for r in range(max_len):
            row = []
            for col in parsed:
                row.append(col[r] if r < len(col) else math.nan)
            result.append(row)

    return result

def generate_lines(n, max_channels=5, max_nums=20):
    """
    Generate random test lines for benchmarking.
    n = 10_000       # (10k lines)
    max_channels = 5 # max channels per line
    max_nums = 20    # max numbers per channel
    """
    lines = []
    for _ in range(n):
        nch = random.randint(1, max_channels)
        chans = []
        for _ in range(nch):
            cnt = random.randint(1, max_nums)
            nums = [f"{random.uniform(0,100):.3f}" for _ in range(cnt)]
            chans.append(" ".join(nums))
        lines.append(",".join(chans))
    return lines

def compute_line_channel_stats(lines):
    # 1) Channels‐per‐line metrics
    #    split on comma → one channel per element
    channels_per_line = [line.count(',') + 1 for line in lines]
    
    avg_ch      = statistics.mean(channels_per_line)
    min_ch      = min(channels_per_line)
    max_ch      = max(channels_per_line)

    # 2) Datapoints‐per‐channel metrics
    #    for each line, split into channels; for each channel, split on whitespace
    dp_counts = []
    for line in lines:
        for channel in line.split(','):
            # filter out any empty strings so "  " → [] rather than ['','']
            nums = [tok for tok in channel.split() if tok]
            dp_counts.append(len(nums))

    avg_dp     = statistics.mean(dp_counts)
    min_dp     = min(dp_counts)
    max_dp     = max(dp_counts)

    return {
        'channels_per_line': {
            'avg': avg_ch, 'min': min_ch, 'max': max_ch
        },
        'datapoints_per_channel': {
            'avg': avg_dp, 'min': min_dp, 'max': max_dp
        }
    }

def main():
    p = argparse.ArgumentParser(
        description="Benchmark simple-parsing implementations"
    )
    p.add_argument("--lines",    type=int, default=10_000,
                   help="Number of lines")
    p.add_argument("--channels", type=int, default=5,
                   help="Max channels per line")
    p.add_argument("--nums",     type=int, default=20,
                   help="Max numbers per channel")
    args = p.parse_args()

    print(f"Generating {args.lines} lines…")
    lines = generate_lines(args.lines, args.channels, args.nums)

    stats = compute_line_channel_stats(lines)
    print("Channels per line:    avg={avg:.2f}, min={min}, max={max}"
          .format(**stats['channels_per_line']))
    print("Datapoints/channel:   avg={avg:.2f}, min={min}, max={max}"
          .format(**stats['datapoints_per_channel']))

    # warmup
    print("\nWarmup:")
    _ = py_parse_lines(lines)
    _ = py_parse_lines_np(lines)
    _ = c_parse_lines(lines)

    # Pure Python
    print("\nPurepython parsing:")
    t0 = time.perf_counter()
    _ = py_parse_lines(lines)
    t_py = time.perf_counter() - t0

    # Python + NumPy
    print("\nPython Numpy parsing:")
    t0 = time.perf_counter()
    arr_np = py_parse_lines_np(lines)
    t_py_np = time.perf_counter() - t0

    # PyBind11 C++
    print("\nC parsing:")
    t0 = time.perf_counter()
    arr_c, _, _= c_parse_lines(lines, channel_names = ["1", "2", "3", "4", "5"], strict=False)
    t_c = time.perf_counter() - t0

    print("\nResults:")
    print(f"  Pure-Python          : {t_py:.3f}s → {args.lines / t_py:,.0f} lines/sec")
    print(f"  Pure-Python + NumPy  : {t_py_np:.3f}s → {args.lines / t_py_np:,.0f} lines/sec")
    print(f"  PyBind11 C++         : {t_c:.3f}s → {args.lines / t_c:,.0f} lines/sec")

    # verify shapes are roughly comparable
    print("\nOutput shapes:")
    print("  Python-list         →", len(py_parse_lines(lines)), "rows")
    print("  Python+NumPy        →", arr_np.shape)
    print("  PyBind11 C++ NumPy  →", arr_c.shape)

if __name__ == "__main__":
    main()


"""
Single pass with debug options enabled (slow):
Results:
  Pure-Python          : 0.750s → 13,335 lines/sec
  Pure-Python + NumPy  : 0.364s → 27,487 lines/sec
  PyBind11 C++         : 0.071s → 141,139 lines/sec

Single pass parser compiler and linker optimized (fast):
Results:
  Pure-Python          : 0.759s → 13,175 lines/sec
  Pure-Python + NumPy  : 0.215s → 46,420 lines/sec
  PyBind11 C++         : 0.025s → 401..414_000  lines/sec

# Two pass parser compiler and linker optimized (fast):
  Results:
  Pure-Python          : 0.732s → 13,666 lines/sec
  Pure-Python + NumPy  : 0.211s → 47,322 lines/sec
  PyBind11 C++         : 0.025s → >=420_000 lines/sec

# Two pass parser compiler and linker optimized with GIL release(fast):
  
"""