#!/usr/bin/env python3
"""
benchmark_buffer.py

Compare push() performance of a pure-Python CircularBuffer vs.
a Numba-accelerated jitclass version.
"""

import time
import numpy as np
from numba.experimental import jitclass
from numba import types

# -----------------------------------------------------------------------------
# 1) Define the Numba-accelerated jitclass
# -----------------------------------------------------------------------------
spec = [
    ('_data',        types.float64[:, :]),
    ('_nrows',       types.int64),
    ('_ncols',       types.int64),
    ('_head',        types.int64),
    ('_num_entries', types.int64),
    ('_num_columns', types.int64),
    ('_oldest',      types.int64),
    ('_latest',      types.int64),
]

@jitclass(spec)
class CircularBufferJIT:
    def __init__(self, initial_rows, initial_columns):
        self._nrows       = initial_rows
        self._ncols       = initial_columns
        self._data        = np.full((initial_rows, initial_columns), np.nan)
        self._head        = 0
        self._num_entries = 0
        self._num_columns = 0
        self._oldest      = 0
        self._latest      = 0

    def push(self, data_array):
        num_new_rows, num_new_cols = data_array.shape

        # Expand columns if needed
        if num_new_cols > self._ncols:
            add = max(self._ncols // 2, num_new_cols - self._ncols)
            new_c = self._ncols + add
            new_data = np.empty((self._nrows, new_c))
            new_data[:, self._ncols:] = np.nan  # Fill with NaN values
            new_data[:, :self._ncols] = self._data # this is moderately costly operation
            self._data = new_data
            self._ncols = new_c

        # Expand rows if needed
        if num_new_rows > self._nrows:
            add = max(self._nrows // 2, num_new_rows - self._nrows)
            new_r = self._nrows + add
            new_data = np.empty((new_r, self._ncols))
            new_data[self._nrows:, :] = np.nan
            new_data[:self._nrows, :] = self._data
            self._data = new_data
            self._nrows = new_r

        # Overwrite all if fits exactly
        if num_new_rows == self._nrows:
            self._data[:self._nrows, :num_new_cols] = data_array[-self._nrows:, :num_new_cols]
            self._head = 0
            self._num_entries = self._nrows
            self._num_columns = max(num_new_cols, self._num_columns)
            self._latest += num_new_rows
            self._oldest = self._latest - self._num_entries + 1
            return

        # Wrap-around insert
        end_pos = (self._head + num_new_rows) % self._nrows
        if end_pos < self._head:
            first = self._nrows - self._head
            self._data[self._head:, :num_new_cols] = data_array[:first, :num_new_cols]
            self._data[:end_pos,    :num_new_cols] = data_array[first:, :num_new_cols]
        else:
            self._data[self._head:end_pos, :num_new_cols] = data_array

        # Update pointers
        self._head        = end_pos
        self._num_entries = min(self._num_entries + num_new_rows, self._nrows)
        self._num_columns = max(self._num_columns, num_new_cols)
        self._latest     += num_new_rows
        self._oldest      = self._latest - self._num_entries + 1

    @property
    def data(self):
        """Retrieve valid data ordered from oldest to newest."""
        if self._num_entries == 0:
            return np.empty((0, self._num_columns))
        start = (self._head - self._num_entries) % self._nrows
        end   = (start + self._num_entries) % self._nrows
        if start < end:
            return self._data[start:end, :self._num_columns]
        else:
            first_len  = self._nrows - start   # rows from `start` to end of buffer
            second_len = end                   # rows from start of buffer to `end`
            out = np.empty((self._num_entries, self._num_columns))
            out[0:first_len, :] = self._data[start:self._nrows, :self._num_columns]
            out[first_len:first_len+second_len, :] = self._data[0:end, :self._num_columns]
            return out        

# -----------------------------------------------------------------------------
# 2) Define the pure-Python fallback class
# -----------------------------------------------------------------------------
class CircularBufferPy:
    def __init__(self, initial_rows, initial_columns):
        self._nrows       = initial_rows
        self._ncols       = initial_columns
        self._data        = np.full((initial_rows, initial_columns), np.nan)
        self._head        = 0
        self._num_entries = 0
        self._num_columns = 0
        self._oldest      = 0
        self._latest      = 0

    def push(self, data_array):
        num_new_rows, num_new_cols = data_array.shape

        if num_new_cols > self._ncols:
            add = max(self._ncols // 2, num_new_cols - self._ncols)
            new_c = self._ncols + add
            new_data = np.empty((self._nrows, new_c))
            new_data[:, self._ncols:] = np.nan  # Fill with NaN values
            new_data[:, :self._ncols] = self._data # this is moderately costly operation
            self._data = new_data
            self._ncols = new_c

        if num_new_rows > self._nrows:
            add = max(self._nrows // 2, num_new_rows - self._nrows)
            new_r = self._nrows + add
            new_data = np.empty((new_r, self._ncols))
            new_data[self._nrows:, :] = np.nan
            new_data[:self._nrows, :] = self._data
            self._data = new_data
            self._nrows = new_r

        if num_new_rows == self._nrows:
            self._data[:self._nrows, :num_new_cols] = data_array[-self._nrows:, :num_new_cols]
            self._head = 0
            self._num_entries = self._nrows
            self._num_columns = max(num_new_cols, self._num_columns)
            self._latest += num_new_rows
            self._oldest = self._latest - self._num_entries + 1
            return

        end = (self._head + num_new_rows) % self._nrows
        if end < self._head:
            first = self._nrows - self._head
            self._data[self._head:, :num_new_cols] = data_array[:first, :num_new_cols]
            self._data[:end,    :num_new_cols] = data_array[first:, :num_new_cols]
        else:
            self._data[self._head:end, :num_new_cols] = data_array

        self._head        = end
        self._num_entries = min(self._num_entries + num_new_rows, self._nrows)
        self._num_columns = max(self._num_columns, num_new_cols)
        self._latest     += num_new_rows
        self._oldest      = self._latest - self._num_entries + 1

    @property
    def data(self):
        """Retrieve valid data ordered from oldest to newest."""
        if self._num_entries == 0:
            return np.empty((0, self._num_columns))
        start = (self._head - self._num_entries) % self._nrows
        end   = (start + self._num_entries) % self._nrows
        if start < end:
            return self._data[start:end, :self._num_columns]
        else:
            first_len  = self._nrows - start   # rows from `start` to end of buffer
            second_len = end                   # rows from start of buffer to `end`
            out = np.empty((self._num_entries, self._num_columns))
            out[0:first_len, :] = self._data[start:self._nrows, :self._num_columns]
            out[first_len:first_len+second_len, :] = self._data[0:end, :self._num_columns]
            return out        

# -----------------------------------------------------------------------------
# 3) Benchmark harness
# -----------------------------------------------------------------------------
def benchmark(buffer, data_list):
    # warm-up for JIT compile
    for arr in data_list[:2]:
        buffer.push(arr)

    start = time.perf_counter()
    for arr in data_list:
        buffer.push(arr)
    return time.perf_counter() - start

def generate_test_data(n_batches, batch_rows, batch_cols):
    return [np.random.rand(batch_rows, batch_cols) for _ in range(n_batches)]

def main():
    N = 1000

    #batch_rows, batch_cols = 50, 32

    for buffer_size in [1024, 64*1024, 128*1024, 512*1024]:
        print(f"Testing with buffer_size={buffer_size} =====================================================")
        for batch_rows in [50, 64, 256, 512, 1024]:
            for batch_cols in [1, 4, 8, 16, 32]:
                print(f"Testing with rows={batch_rows}, cols={batch_cols}")
                data = generate_test_data(N, batch_rows, batch_cols)

                # Pure Python
                buf_py = CircularBufferPy(buffer_size, 16)
                t_py  = benchmark(buf_py, data)
                print(f"Python push: {t_py:.4f}s ({N/t_py:.0f} batches/sec)")

                # Numba jitclass
                buf_jit = CircularBufferJIT(buffer_size, 16)
                t_jit  = benchmark(buf_jit, data)
                print(f"Numba push : {t_jit:.4f}s ({N/t_jit:.0f} batches/sec)")
                print(f"Speedup from Numba: {t_py/t_jit:.2f}×")

if __name__ == "__main__":
    main()
