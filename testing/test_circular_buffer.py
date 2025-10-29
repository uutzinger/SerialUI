from Circular_Buffer import CircularBuffer, CircularBuffer64
import time
import numpy as np

def benchmark(buffer_class, iterations=1000, rows=64, cols=8):
    buffer = buffer_class(131_072, 16, np.float64)  # Initial size of 131072 rows, 16 columns, dtype float64
    data = np.random.rand(rows, cols).astype(np.float64)

    # Warm-up for JIT (especially for Numba)
    if hasattr(buffer, "push"):
        buffer.push(data)

    start = time.perf_counter()
    for _ in range(iterations):
        buffer.push(data) # push
    _ = buffer.data # retrieve
    end = time.perf_counter()

    elapsed_ms = 1000 * (end - start)
    return elapsed_ms

def main():
    iterations = 1000

    for rows in [64, 256, 512, 1024]:
        for cols in [1, 4, 8, 16, 32]:
            print(f"Testing with rows={rows}, cols={cols}")
            time_regular = benchmark(CircularBuffer, iterations, rows, cols)
            time_numba   = benchmark(CircularBuffer64, iterations, rows, cols)
            speedup = time_regular / time_numba if time_numba > 0 else float('inf')
            print(f"Speedup from Numba: {speedup:.2f}×")

if __name__ == "__main__":
    main()

