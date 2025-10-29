#!/usr/bin/env python3
"""
Benchmark: Python open() vs Qt QFile/QTextStream (Qt5/Qt6)
- Text write/read (UTF-8)
- Binary write/read
Reports avg of N runs and the best (min) time.
"""

import os, tempfile, time, statistics, sys
from typing import Tuple

# ---- Qt import (Qt6 -> Qt5 fallback) ----------------------------------------
try:
    from PyQt6.QtCore import QFile, QIODevice
    from PyQt6.QtCore import QByteArray
    from PyQt6.QtCore import QStringConverter
    from PyQt6.QtCore import QTextStream  # Qt6 uses setEncoding() instead of setCodec()
    QT_MAJOR = 6
except Exception:
    from PyQt5.QtCore import QFile, QIODevice, QByteArray
    from PyQt5.QtCore import QTextStream  # Qt5 uses setCodec("UTF-8")
    QT_MAJOR = 5

# ---- Config -----------------------------------------------------------------
TOTAL_BYTES = 100 * 1024 * 1024   # 100 MB per test
CHUNK_SIZE  = 256 * 1024          # 256 KB chunk
RUNS = 3                          # do a few runs to average
TEXT_LINE = ("x" * (CHUNK_SIZE - 1)) + "\n"   # ~chunk-sized text with newline
BIN_CHUNK = b"x" * CHUNK_SIZE

# --- toggle these at the top ---
PY_BUFFERING_OPTIONS = {
    "default": -1,      # Python default
    "1MB": 1024*1024,   # large buffer
    "4MB": 4*1024*1024, # even larger
    "unbuffered": 0,    # binary-only; allowed in 'rb'/'wb'
}

def _timeit(fn, *args, runs=RUNS) -> Tuple[float, float, float]:
    """Return (avg, stdev, best) time over `runs`."""
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn(*args)
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return (statistics.mean(times), statistics.pstdev(times), min(times))

# ---- Python open() implementations ------------------------------------------
def py_write_text(path: str, total_bytes: int):
    written = 0
    # newline='\n' to avoid platform conversion surprises (fair vs QTextStream)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        while written < total_bytes:
            f.write(TEXT_LINE)
            written += len(TEXT_LINE)

def py_read_text(path: str):
    # read all lines to simulate real text processing
    with open(path, "r", encoding="utf-8", newline="\n") as f:
        for _ in f:
            pass

def py_write_binary(path: str, total_bytes: int, buffering: int = -1):
    written = 0
    # NOTE: buffering=0 is allowed for binary mode and can change perf characteristics
    with open(path, "wb", buffering=buffering) as f:
        while written < total_bytes:
            f.write(BIN_CHUNK)
            written += len(BIN_CHUNK)

def py_read_binary(path: str, buffering: int = -1):
    # Variant A: regular read()
    with open(path, "rb", buffering=buffering) as f:
        while f.read(CHUNK_SIZE):
            pass

def py_read_binary_into(path: str, buffering: int = -1):
    # Variant B: reuse a buffer to reduce allocations/copies
    buf = bytearray(CHUNK_SIZE)
    mv = memoryview(buf)
    with open(path, "rb", buffering=buffering) as f:
        while True:
            n = f.readinto(buf)
            if not n:
                break

# ---- Qt QFile/QTextStream implementations -----------------------------------
def qt_write_text(path: str, total_bytes: int):
    f = QFile(path)
    if not f.open(QIODevice.OpenModeFlag.WriteOnly | QIODevice.OpenModeFlag.Text):
        raise RuntimeError("QFile open for text write failed")
    ts = QTextStream(f)
    if QT_MAJOR >= 6:
        ts.setEncoding(QStringConverter.Encoding.Utf8)
    else:
        ts.setCodec("UTF-8")
    written = 0
    while written < total_bytes:
        ts << TEXT_LINE
        written += len(TEXT_LINE.encode("utf-8"))
    ts.flush()
    f.close()

def qt_read_text(path: str):
    f = QFile(path)
    if not f.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
        raise RuntimeError("QFile open for text read failed")
    ts = QTextStream(f)
    if QT_MAJOR >= 6:
        ts.setEncoding(QStringConverter.Encoding.Utf8)
    else:
        ts.setCodec("UTF-8")
    while not ts.atEnd():
        _ = ts.readLine()
    f.close()

def qt_write_binary(path: str, total_bytes: int):
    f = QFile(path)
    if not f.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError("QFile open for binary write failed")
    written = 0
    ba = QByteArray(BIN_CHUNK)  # reuse
    while written < total_bytes:
        # write(QByteArray) returns bytes written
        if f.write(ba) < 0:
            raise RuntimeError("QFile write failed")
        written += len(BIN_CHUNK)
    f.flush()
    f.close()

def qt_read_binary(path: str):
    f = QFile(path)
    if not f.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError("QFile open for binary read failed")
    while True:
        chunk = f.read(CHUNK_SIZE)
        if not chunk:
            break
    f.close()

def run_py_binary_matrix():
    for name, bufsize in PY_BUFFERING_OPTIONS.items():
        print(f"\n== Python BINARY ({name}) ==")
        fd, path = tempfile.mkstemp(prefix="bench_", suffix=".dat")
        os.close(fd)
        try:
            avg, std, best = _timeit(py_write_binary, path, TOTAL_BYTES, bufsize)
            size_mb = TOTAL_BYTES / (1024 * 1024)
            print(f"Write: avg {avg:.3f}s  std {std:.3f}s  best {best:.3f}s  "
                  f"→ {size_mb / best:.1f} MB/s (best)")

            # Regular read
            avg, std, best = _timeit(py_read_binary, path, bufsize)
            print(f"Read : avg {avg:.3f}s  std {std:.3f}s  best {best:.3f}s  "
                  f"→ {size_mb / best:.1f} MB/s (best)")

            # readinto() variant
            avg, std, best = _timeit(py_read_binary_into, path, bufsize)
            print(f"Read (into): avg {avg:.3f}s  std {std:.3f}s  best {best:.3f}s  "
                  f"→ {size_mb / best:.1f} MB/s (best)")
        finally:
            try: os.remove(path)
            except: pass

# ---- Orchestrator -----------------------------------------------------------
def run_one_case(writer, reader, label: str):
    print(f"\n== {label} ==")
    fd, path = tempfile.mkstemp(prefix="bench_", suffix=".dat")
    os.close(fd)  # we'll use our own openers
    try:
        avg, std, best = _timeit(writer, path, TOTAL_BYTES)
        size_mb = TOTAL_BYTES / (1024 * 1024)
        print(f"Write: avg {avg:.3f}s  std {std:.3f}s  best {best:.3f}s  "
              f"→ {size_mb / best:.1f} MB/s (best)")
        avg, std, best = _timeit(reader, path)
        print(f"Read : avg {avg:.3f}s  std {std:.3f}s  best {best:.3f}s  "
              f"→ {size_mb / best:.1f} MB/s (best)")
    finally:
        try:
            os.remove(path)
        except Exception:
            pass

def main():
    print(f"Qt major: {QT_MAJOR}")
    print(f"Total bytes per test: {TOTAL_BYTES/(1024*1024)} MB, chunk {CHUNK_SIZE/(1024)} KB, runs {RUNS}")

    # Warm-up pass to populate disk caches fairly
    run_one_case(py_write_binary, py_read_binary, "Warm-up (Python binary)")

    # Benchmarks
    run_one_case(qt_write_text,   qt_read_text,   "Qt TEXT (QTextStream UTF-8)")
    run_one_case(qt_write_binary, qt_read_binary, "Qt BINARY (QFile)")
    # run_one_case(py_write_binary, py_read_binary, "Python BINARY")
    run_one_case(py_write_text,   py_read_text,   "Python TEXT (UTF-8)")
    run_py_binary_matrix()

if __name__ == "__main__":
    main()
