#!/usr/bin/env python3
import time
import random
import argparse
import statistics
import threading

# C++ parser
from line_parsers.header_parser import parse_lines as c_parse_lines

def generate_lines(n, max_headers=5, max_nums=20, header_pool=None):
    """
    Generate n random “header:data” lines for benchmarking.

    Each line has between 1 and max_headers header‐fields. Each header is chosen
    at random from header_pool (a list of header‐names).  If header_pool is None,
    we default to ['A','B','C','D','E','F','G'].

    Within each header, we generate between 1 and max_nums floating‐point numbers
    (formatted to 3 decimals) separated by spaces.  Then we join headers on commas.

    Example single line: "A:12.345 67.890, C:3.141 2.718 1.618, G:0.577"
    """
    if header_pool is None:
        header_pool = ['A','B','C','D','E','F','G']

    lines = []
    nhdrs = len(header_pool)
    for _ in range(n):
        # pick between 1 and max_headers distinct headers for this line
        nch = random.randint(1, max_headers)
        chosen = random.sample(header_pool, nch)

        parts = []
        for hdr in chosen:
            cnt = random.randint(1, max_nums)
            nums = [f"{random.uniform(0,100):.3f}" for _ in range(cnt)]
            parts.append(f"{hdr}:" + " ".join(nums))
        lines.append(",".join(parts))

    return lines

def compute_line_channel_stats(lines):
    """
    Rough‐and‐ready stats on “channels per line” and “datapoints per channel”:
      - channels_per_line = line.count(',')+1
      - datapoints_per_channel = (for each channel: len(channel.split()))
    """
    channels_per_line = [line.count(',') + 1 for line in lines]
    avg_ch = statistics.mean(channels_per_line)
    min_ch = min(channels_per_line)
    max_ch = max(channels_per_line)

    dp_counts = []
    for line in lines:
        for chunk in line.split(','):
            # chunk looks like "A:1.234 5.678"; strip header before colon
            parts = chunk.split(':', 1)
            data_str = parts[1] if len(parts) == 2 else ""
            nums = [tok for tok in data_str.split() if tok]
            dp_counts.append(len(nums))
    avg_dp = statistics.mean(dp_counts)
    min_dp = min(dp_counts)
    max_dp = max(dp_counts)

    return {
        'channels_per_line':    {'avg': avg_ch, 'min': min_ch, 'max': max_ch},
        'datapoints_per_channel': {'avg': avg_dp, 'min': min_dp, 'max': max_dp}
    }


def spin(counter, stop_event):
    """A tight loop to consume the GIL (counter increments)."""
    while not stop_event.is_set():
        counter[0] += 1

def benchmark(args, lines, use_gil_release):
    """
    Warm up the parser, then spawn a background “spinner” thread to hold the GIL
    (if use_gil_release=False), or let the parser drop the GIL (if use_gil_release=True).
    Measure the time to run parse_lines 10× on the same data, and report throughput.
    """

    # “Warm up” so any templates get instantiated
    # We pass a small fake channel_names list so that parse_lines can reuse it.
    fake_initial = ['A', 'B', 'C', 'D', 'E']
    _, shape, channel_names = c_parse_lines(lines,
                                            channel_names=fake_initial,
                                            strict=False,
                                            gil_release=use_gil_release)
    
    # Print the warm‐up results once:
    print(" Warmup → returned shape:", shape, "channel_names:", channel_names)

    # add thread to keep the GIL busy
    print("Start spin thread…")
    stop = threading.Event()
    counter = [0]
    t = threading.Thread(target=spin, args=(counter, stop))
    t.start()

    print("Bench…")
    # reset the counter
    counter[0] = 0
    time.sleep(0)  # give the thread a chance to start

    # benchmark
    t0 = time.perf_counter()
    t_elapsed = [0.0] * 10;
    for i in range(10):
        t0 = time.perf_counter()
        arr, shape, channel_names = c_parse_lines(lines,
                                                  channel_names=channel_names,
                                                  strict=False,
                                                  gil_release=use_gil_release)
        t_elapsed[i] = (time.perf_counter() - t0) / 10.0

    stop.set()
    t.join()

    t_elapsed_mean = statistics.mean(t_elapsed)
    t_elapsed_std = statistics.stdev(t_elapsed)
    inliers = [t for t in t_elapsed if t < t_elapsed_mean + 2 * t_elapsed_std]
    t_elapsed_mean = statistics.mean(inliers)
    t_elapsed_std = statistics.stdev(inliers)
    lines_per_sec = args.lines / t_elapsed_mean
    lines_per_sec_std = args.lines / (t_elapsed_mean) - args.lines / (t_elapsed_mean + t_elapsed_std)
    print(f"  Time per loop: {t_elapsed_mean:.4f}s → {lines_per_sec:,.0f} lines/sec +/-{lines_per_sec_std:,.0f} lines")
    print(f"  Final shape: {shape}")
    print(f"  Final channel_names: {channel_names}")
    print(f"  Spin‐count (GIL churn): {counter[0]}")
    print(f"  gil was {'released' if use_gil_release else 'held'}")

def main():
    p = argparse.ArgumentParser(
        description="Benchmark header_parser.parse_lines"
    )
    p.add_argument("--lines",    type=int, default=100_000,
                   help="Number of lines to generate")
    p.add_argument("--headers",  type=int, default=5,
                   help="Max distinct headers per line")
    p.add_argument("--nums",     type=int, default=20,
                   help="Max numeric tokens per header")
    args = p.parse_args()

    print(f"Generating {args.lines} random lines with up to {args.headers} headers…")
    lines = generate_lines(args.lines, max_headers=args.headers, max_nums=args.nums)

    stats = compute_line_channel_stats(lines)
    stats_ch = stats['channels_per_line']
    stats_dp = stats['datapoints_per_channel']
    print(f"Channels/line   → avg={stats_ch['avg']:.2f}, min={stats_ch['min']}, max={stats_ch['max']}")
    print(f"Datapoints/ch   → avg={stats_dp['avg']:.2f}, min={stats_dp['min']}, max={stats_dp['max']}")

    # first run without
    benchmark(args, lines, False)
    # then with
    benchmark(args, lines, True)

if __name__ == "__main__":
    main()

"""
  Time per loop: 0.0564s → 1,774,062 lines/sec +/-34,981 lines
   gil was held
  Time per loop: 0.0571s → 1,750,945 lines/sec +/-40,896 lines
   gil was released

  Time per loop: 0.0538s → 1,860,445 lines/sec +/-14,479 lines
   gil was held
  Time per loop: 0.0538s → 1,857,802 lines/sec +/-26,376 lines
   gil was released

With ankerl-unordered-hash

Bench…
  Time per loop: 0.0527s → 1,898,397 lines/sec +/-27,091 lines
  Final shape: (1467120, 14)
  Final channel_names: ['A_1', 'B_1', 'C_1', 'D_1', 'E_1', 'A_2', 'F_1', 'E_2', 'G_1', 'G_2', 'F_2', 'D_2', 'B_2', 'C_2']
  Spin‐count (GIL churn): 72862
  gil was held
Bench…
  Time per loop: 0.0538s → 1,860,367 lines/sec +/-28,110 lines
  Final shape: (1467120, 14)
  Final channel_names: ['A_1', 'B_1', 'C_1', 'D_1', 'E_1', 'A_2', 'F_1', 'E_2', 'G_1', 'G_2', 'F_2', 'D_2', 'B_2', 'C_2']
  Spin‐count (GIL churn): 129846
  gil was released
"""
