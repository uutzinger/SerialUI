from Circular_Buffer import CircularBuffer
import numpy as np
import time

# kernprof -l -v profile_circular_buffer.py

# Function to benchmark buffer
def benchmark(iterations, rows, cols):
    buffer = CircularBuffer(131_072, 16, np.float64)  # Initial buffer size
    for _ in range(iterations):
        data = np.random.randn(rows, cols).astype(np.float64)
        buffer.push(data)
        _ = buffer.data

def main():
    iterations = 10000
    rows = 512
    cols = 32

    print(f"Testing with rows={rows}, cols={cols}")

    start = time.perf_counter()
    benchmark(iterations, rows, cols)
    end = time.perf_counter()
    print(f"Base buffer time:  {end - start:.4f} seconds")


if __name__ == "__main__":
    main()
