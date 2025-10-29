#!/usr/bin/env python3
import time
import random
import argparse
import statistics
import threading

# C++ parser
from line_parsers.simple_parser import parse_lines as c_parse_lines

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

def spin(counter, stop_event):
    while not stop_event.is_set():
        counter[0] += 1

def benchmark(args, lines, use_gil_release):

    # warmup
    print("Warm up…")
    channel_names = ["1", "2", "3", "4", "5"]
    _,_,channel_names = c_parse_lines(lines, channel_names = channel_names, strict=False, gil_release=use_gil_release)

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
        description="Benchmark simple-parsing implementations"
    )
    p.add_argument("--lines",    type=int, default=100_000,
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

    # first run without
    benchmark(args, lines, False)
    # then with
    benchmark(args, lines, True)

if __name__ == "__main__":
    main()

"""
Bench…
  Time per loop: 0.0245s → 4,077,752 lines/sec +/-92,072 lines
  Final shape: (1469533, 5)
  Final channel_names: ['1', '2', '3', '4', '5']
  Spin‐count (GIL churn): 60595
  gil was held
Bench…
  Time per loop: 0.0256s → 3,908,687 lines/sec +/-104,878 lines
  Final shape: (1469533, 5)
  Final channel_names: ['1', '2', '3', '4', '5']
  Spin‐count (GIL churn): 111089
  gil was released
"""