############################################################################################################################################
# Circular Buffer
#
# functions:
#   - push(ndarray) add new data to the buffer, auto-expands buffer if necessary
#   - clear    reset counters and fill data with NaN
#   - last(n)  newest n rows of data
#   - first(n) oldest n rows of data
# properties:
#   - data     -> ndarray all valid data ordered from oldest to newest
#   - capacity -> (rows, columns) total allocated size
#   - shape    -> (nrows, ncols) number of valid rows and columns
#   - counter  -> (oldest, latest) measurement number (auto-incrementing)
#   - dtype    -> data type used by the buffer
#
# Urs Utzinger 2025
############################################################################################################################################
# Performance
#
# Push:
# Circular buffer can push about 
#        10_000_000 data points per second for [  50 x  1] numpy array
#     1_000_000_000 data points per second for [1024 x 16] numpy array
# Numba acceleration is only useful if number of rows added at a time is less than 512
#
# Last(n):
# Circular buffer can retrieve about
#     1_000_000_000 data points per second for a buffer with   1_024 rows
# 1_000_000_000_000 data points per second for a buffer with 500_000 rows
# Numba acceleration is slower than pure numpy
############################################################################################################################################
#
import numpy as np
try:
    from numba import float64, int64
    from numba.experimental import jitclass
    hasNUMBA = True
except Exception:
    float64 = int64 = None
    jitclass = None
    hasNUMBA = False
    
############################################################################################################################################
# CircularBuffer class
# ##########################################################################################################################################
class CircularBuffer:
    '''
    Circular buffer for storing numpy data of any data type.

    - Dynamically adjusts columns based on incoming data.
    - Uses a rolling approach to keep the most recent data.
    - Ensures retrieval provides only valid rows and columns.
    - Tracks sample numbers for continuous measurements.
    '''

    def __init__(self, initial_rows, initial_columns, dtype=np.float64):
        ''' Initialize the circular buffer '''
        if initial_rows <= 0 or initial_columns <= 0:
            raise ValueError("initial_rows and initial_columns must be > 0")
        if not np.issubdtype(np.dtype(dtype), np.floating):
            raise TypeError("dtype must be a floating type to support NaN padding")
        self._nrows = initial_rows
        self._ncols = initial_columns
        self._dtype = dtype
        # _data shape is [nrows x ncols]
        self._data = np.full((initial_rows, initial_columns), np.nan, dtype=self._dtype)

        self._head         = 0                                                 # Next insert position
        self._nRowEntries  = 0                                                 # Number of valid (populated) row entries
        self._nColEntries  = 0                                                 # Tracks how many columns have been populated
        self._oldest       = 0                                                 # Tracks the oldest "measurement number"
        self._latest       = 0                                                 # Tracks the newest "measurement number"

    def push(self, data_array: np.ndarray):
        ''' Add new data to the circular buffer '''

        if data_array is None:
            return 0

        if isinstance(data_array, np.ndarray) and data_array.dtype == self._dtype:
            pass
        else:
            data_array = np.asarray(data_array, dtype=self._dtype)

        if data_array.ndim == 1:
            data_array = data_array.reshape(1, -1)
        if data_array.size == 0:
            return 0

        ncols = self._ncols
        nrows = self._nrows
        head  = self._head
        nRowEntries = self._nRowEntries
        nColEntries = self._nColEntries

        # 1 Determine size of new data
        num_new_rows, num_new_cols = data_array.shape

        # 2 Expand columns if necessary
        if num_new_cols > ncols:
            columns_to_add = max(ncols // 2, num_new_cols - ncols)
            new_cols = ncols + columns_to_add
            new_data = np.empty((self._nrows, new_cols), dtype=self._dtype)
            # Preserve old data
            # We only copy up to ncols since that's what existed
            new_data[:, :ncols] = self._data                                   # this is moderately costly operation
            new_data[:, ncols:] = np.nan                                       # Fill with NaN values
            self._data = new_data
            self._ncols = new_cols
            ncols = new_cols

        # 3 Expand rows if necessary
        if num_new_rows > nrows:
            rows_to_add = max(nrows // 2, num_new_rows - nrows)
            new_rows = nrows + rows_to_add
            # Create new array with expanded size and NaN values
            new_data = np.empty((new_rows, ncols), dtype=self._dtype)
            # Preserve old data
            new_data[:nrows, :] = self._data
            new_data[nrows:, :] = np.nan
            self._data = new_data
            self._nrows = new_rows
            nrows = new_rows

        # 4 If new data exactly fills the buffer, we overwrite all at once
        if num_new_rows == nrows:
            self._data[:nrows, :num_new_cols] = data_array[-nrows:, :num_new_cols]
            if num_new_cols < nColEntries:
                self._data[:nrows, num_new_cols:nColEntries] = np.nan          # Fill with NaN values
            self._head = 0
            self._nRowEntries = nrows
            self._nColEntries =  max(nColEntries, num_new_cols)
            self._latest += num_new_rows
            self._oldest = self._latest - self._nRowEntries + 1
            return

        # 5 Write new data at _head
        end_pos = (head + num_new_rows) % nrows
        if end_pos < head:
            # Wraparound insertion: Split into two parts
            first_part = nrows - head
            self._data[head:nrows, :num_new_cols] = data_array[:first_part, :num_new_cols]
            self._data[0:end_pos,  :num_new_cols] = data_array[first_part:, :num_new_cols]
            # clear trailing unwritten columns for rows we touched
            if num_new_cols < nColEntries:
                self._data[head:nrows, num_new_cols:nColEntries] = np.nan
                if end_pos:
                    self._data[0:end_pos,  num_new_cols:nColEntries] = np.nan
        else:
            # Direct insertion (no wrap around)
            self._data[head:end_pos, :num_new_cols] = data_array[:, :num_new_cols]
            if num_new_cols < nColEntries:
                self._data[head:end_pos, num_new_cols:nColEntries] = np.nan

        # 6 Update index and counters
        self._head = end_pos
        self._nRowEntries = min(nRowEntries + num_new_rows, nrows)
        self._nColEntries = max(nColEntries, num_new_cols)
        self._latest += num_new_rows
        self._oldest = self._latest - self._nRowEntries + 1

    def clear(self):
        ''' Clear the buffer (set all values to NaN) '''
        self._data.fill(np.nan)
        self._head = 0
        self._nRowEntries = 0
        self._nColEntries = 0
        self._oldest = 0
        self._latest = 0

    def last(self, n:int=1) -> np.ndarray:
        ''' Retrieve the newest n valid data rows ordered from oldest to newest '''
        if n <= 0 or self._nRowEntries == 0 or self._nColEntries == 0:
            return np.empty((0, self._nColEntries), dtype=self._dtype)

        nrows = self._nrows
        head  = self._head
        nRowEntries  = self._nRowEntries
        nColEntries  = self._nColEntries

        n = min(n, nRowEntries)

        start = (head - n) % nrows
        end   = head

        if start < end:
            # No wrap needed
            return self._data[start:end, :nColEntries]
        else:
            # Wrapped: two slices
            first_len  = nrows - start                                         # rows from start to end of buffer
            second_len = end                                                   # rows from start of buffer to end

            out = np.empty((n, nColEntries), dtype=self._dtype)
            # 1) tail segment
            if first_len:
                out[0:first_len, :] = self._data[start:nrows, :nColEntries]
            # 2) head segment
            if second_len:
                out[first_len:first_len + second_len, :] = self._data[0:end, :nColEntries]
            return out

    def first(self, n:int=1) -> np.ndarray:
        ''' Retrieve the oldest n valid data rows ordered from oldest to newest '''
        if n <= 0 or self._nRowEntries == 0 or self._nColEntries == 0:
            return np.empty((0, self._nColEntries), dtype=self._dtype)

        nrows = self._nrows
        head  = self._head
        nRowEntries  = self._nRowEntries
        nColEntries  = self._nColEntries
    
        n = min(n, nRowEntries)

        start = (head  - nRowEntries) % nrows
        end   = (start + n) % nrows

        if start < end:
            # No wrap needed
            return self._data[start:end, :nColEntries]
        else:
            # Wrapped: two slices
            first_len  = nrows - start                                         # rows from start to end of buffer
            second_len = end                                                   # rows from start of buffer to end

            out = np.empty((n, nColEntries), dtype=self._dtype)
            # 1) tail segment
            if first_len:
                out[0:first_len, :] = self._data[start:nrows, :nColEntries]
            # 2) head segment
            if second_len:
                out[first_len:first_len + second_len, :] = self._data[0:end, :nColEntries]
            return out

    @property
    def data(self):
        ''' Retrieve valid data ordered from oldest to newest '''
        if self._nRowEntries == 0 or self._nColEntries == 0:
            return np.empty((0, self._nColEntries), dtype=self._dtype)

        nrows     = self._nrows
        head      = self._head
        nRowEntries = self._nRowEntries
        nColEntries = self._nColEntries

        start = (head  - nRowEntries) % nrows
        end   = (start + nRowEntries) % nrows

        if start < end:
            # No wrap needed
            return self._data[start:end, :nColEntries]
        else:
            # Wrapped: two slices
            first_len  = nrows - start                                         # rows from `start` to end of buffer
            second_len = end                                                   # rows from start of buffer to `end`
            #
            out = np.empty((nRowEntries, nColEntries), dtype=self._dtype)
            # 1) tail segment
            if first_len:
                out[0:first_len, :] = self._data[start:nrows, :nColEntries]
            # 2) head segment
            if second_len:
                out[first_len:first_len + second_len, :] = self._data[0:end, :nColEntries]
            return out

    @property
    def shape(self):
        ''' Return the shape (populated rows, populated columns) of the buffer '''
        return (self._nRowEntries, self._nColEntries)

    @property
    def capacity(self):
        ''' Return the capacity (rows, columns) of the buffer '''
        return (self._nrows, self._ncols) 

    @property
    def counter(self):
        ''' Return the oldest and newest measurement number'''
        return (self._oldest, self._latest)

    @property
    def dtype(self):
        ''' Return the data type '''
        return self._dtype 

############################################################################################################################################
# Numba accelerated CircularBuffer for float64 data
############################################################################################################################################

# Numba acceleration data types
if hasNUMBA:
    spec = [
        ('_data',       float64[:, :]),
        ('_nrows',        int64),
        ('_ncols',        int64),
        ('_head',         int64),
        ('_nRowEntries',  int64),
        ('_nColEntries',  int64),
        ('_oldest',       int64),
        ('_latest',       int64),
    ]

    @jitclass(spec)
    class CircularBuffer64:
        '''
        Circular buffer width 2D numpy data. A column is a data channel.

        - Dynamically adjusts columns based on incoming data.
        - Uses a rolling approach to keep the most recent data.
        - Ensures retrieval provides only valid rows and columns.
        - Tracks sample numbers of continuous measurements.
        '''

        def __init__(self, initial_rows, initial_columns, dummy=None):
            ''' Initialize the circular buffer '''
            self._nrows = initial_rows
            self._ncols = initial_columns

            # _data shape is [nrows x ncols]
            self._data = np.full((initial_rows, initial_columns), np.nan)

            self._head        = 0                                              # Next insert position
            self._nRowEntries = 0                                              # Number of valid (populated) row entries
            self._nColEntries = 0                                              # Number of valid (populated) columns
            self._oldest      = 0                                              # Tracks the oldest "measurement number" in the buffer, will adjust with each new data push
            self._latest      = 0                                              # Tracks the newest "measurement number" in the buffer, will increment with each new data push

        def push(self, data_array: np.ndarray):
            ''' Add new data to the circular buffer '''

            if data_array is None:
                return 0
            
            if data_array.ndim == 1:
                data_array = data_array.reshape(1, -1)
            if data_array.size == 0:
                return 0

            ncols = self._ncols
            nrows = self._nrows
            head  = self._head
            nRowEntries = self._nRowEntries
            nColEntries = self._nColEntries

            # 1 Determine size of new data
            num_new_rows, num_new_cols = data_array.shape

            # 2 Expand columns if necessary
            if num_new_cols > ncols:
                columns_to_add = max(ncols // 2, num_new_cols - ncols)
                new_cols = ncols + columns_to_add
                # Create new array with expanded size and NaN values, take 
                new_data = np.empty((nrows, new_cols))
                new_data[:, ncols:] = np.nan                                   # Fill with NaN values
                # Preserve old data
                # We only copy up to ncols since that's what existed
                new_data[:, :ncols] = self._data                               # this is moderately costly operation
                self._data = new_data
                self._ncols = new_cols
                ncols = new_cols

            # 3 Expand rows if necessary
            if num_new_rows > nrows:
                rows_to_add = max(nrows // 2, num_new_rows - nrows)
                new_rows = nrows + rows_to_add
                # Create new array with expanded size and NaN values
                new_data = np.empty((new_rows, ncols))
                new_data[nrows:, :] = np.nan
                # Preserve old data
                new_data[:nrows, :] = self._data
                self._data = new_data
                self._nrows = new_rows
                nrows = new_rows

            # 4 If the new data exactly fits the buffer we overwrite all at once
            if num_new_rows == nrows:
                self._data[:nrows, :num_new_cols] = data_array[-nrows:, :num_new_cols]
                if num_new_cols < nColEntries:
                    self._data[:nrows, num_new_cols:nColEntries] = np.nan      # Fill with NaN values
                self._head = 0
                self._nRowEntries = nrows
                self._nColEntries = max(num_new_cols, nColEntries)
                self._latest += num_new_rows
                self._oldest = self._latest - self._nRowEntries + 1
                return

            # 5 Write new data at _head
            end_pos = (head + num_new_rows) % nrows
            if end_pos < head:
                # Wrap around insertion: Split into two parts
                first_part = nrows - head
                self._data[head:nrows, :num_new_cols] = data_array[:first_part, :num_new_cols]
                self._data[0:end_pos, :num_new_cols] = data_array[first_part:, :num_new_cols]
                if num_new_cols < nColEntries:
                    self._data[head:nrows, num_new_cols:nColEntries] = np.nan
                    if end_pos > 0:
                        self._data[0:end_pos, num_new_cols:nColEntries] = np.nan
            else:
                # Direct insertion (no wrap around)
                self._data[head:end_pos, :num_new_cols] = data_array[:, :num_new_cols]
                if num_new_cols < nColEntries:
                    self._data[head:end_pos, num_new_cols:nColEntries] = np.nan

            # 6 Update index and counters
            self._head = end_pos
            self._nRowEntries = min(nRowEntries + num_new_rows, nrows)
            self._nColEntries = max(nColEntries, num_new_cols)
            self._latest += num_new_rows
            self._oldest = self._latest - self._nRowEntries + 1

        def clear(self):
            ''' Clear the buffer (set all values to NaN) '''
            self._data.fill(np.nan)
            self._head = 0
            self._nRowEntries = 0
            self._nColEntries = 0
            self._oldest = 0
            self._latest = 0

        def last(self, n:int=1) -> np.ndarray:
            ''' Retrieve the last n valid data rows ordered from oldest to newest '''
            if n <= 0 or self._nRowEntries == 0 or self._nColEntries == 0:
                return np.empty((0, self._nColEntries))

            nrows = self._nrows
            head  = self._head
            nRowEntries  = self._nRowEntries
            nColEntries  = self._nColEntries

            n = min(n, nRowEntries)

            start = (head - n) % nrows
            end   = head

            if start < end:
                # No wrap needed
                return self._data[start:end, :nColEntries]
            else:
                # Wrapped: two slices
                first_len  = nrows - start                                     # rows from start to end of buffer
                second_len = end                                               # rows from start of buffer to end

                out = np.empty((n, nColEntries))
                # 1) tail segment
                if first_len:
                    out[0:first_len, :] = self._data[start:nrows, :nColEntries]
                # 2) head segment
                if second_len:
                    out[first_len:first_len + second_len, :] = self._data[0:end, :nColEntries]
                return out

        def first(self, n:int=1) -> np.ndarray:
            ''' Retrieve the first n valid data rows ordered from oldest to newest '''
            if n <= 0 or self._nRowEntries == 0 or self._nColEntries == 0:
                return np.empty((0, self._nColEntries))

            nrows = self._nrows
            head  = self._head
            nRowEntries  = self._nRowEntries
            nColEntries  = self._nColEntries    

            n = min(n, nRowEntries)

            start = (head  - nRowEntries) % nrows
            end   = (start + n) % nrows

            if start < end:
                # No wrap needed
                return self._data[start:end, :nColEntries]
            else:
                # Wrapped: two slices
                first_len  = nrows - start                                     # rows from start to end of buffer
                second_len = end                                               # rows from start of buffer to end

                out = np.empty((n, nColEntries))
                # 1) tail segment
                if first_len:
                    out[0:first_len, :] = self._data[start:nrows, :nColEntries]
                # 2) head segment
                if second_len:
                    out[first_len:first_len + second_len, :] = self._data[0:end, :nColEntries]
                return out
        
        @property
        def data(self):
            """Retrieve valid data ordered from oldest to newest."""
            if self._nRowEntries == 0 or self._nColEntries == 0:
                return np.empty((0, self._nColEntries))

            nrows     = self._nrows
            head      = self._head
            nRowEntries = self._nRowEntries
            nColEntries = self._nColEntries

            start = (head  - nRowEntries) % nrows
            end   = (start + nRowEntries) % nrows

            if start < end:
                # No wrap: just one contiguous slice
                return self._data[start:end, :nColEntries]

            else:
                # Wrapped: two slices
                first_len  = nrows - start                                     # rows from `start` to end of buffer
                second_len = end                                               # rows from start of buffer to `end`
                #
                out = np.empty((nRowEntries, nColEntries))
                # 1) tail segment
                if first_len:
                    out[0:first_len, :] = self._data[start:nrows, :nColEntries]
                # 2) head segment
                if second_len:
                    out[first_len:first_len+second_len, :] = self._data[0:end, :nColEntries]
                return out

        @property
        def shape(self):
            ''' Return the shape of the buffer (populated rows, populated columns) '''
            return (self._nRowEntries, self._nColEntries)

        @property
        def capacity(self):
            ''' Return the capacity of the buffer (rows, columns)  '''
            return (self._nrows, self._ncols) 

        @property
        def counter(self):
            ''' Return the oldest and newest measurement number'''
            return (self._oldest, self._latest)

        @property
        def dtype(self):
            ''' Return the data type '''
            return np.float64 

else:
    # Fallback placeholder if numba is not available
    class CircularBuffer64:                                                    # type: ignore
        def __init__(self, *_, **__):
            raise RuntimeError("Numba is not available; CircularBuffer64 cannot be used.")


############################################################################################################################################
# Testing
############################################################################################################################################

if __name__ == "__main__":
    import time
    import math
    import matplotlib.pyplot as plt
    from matplotlib.ticker import ScalarFormatter

    def benchmark_push(buffer, data_list):
        """Push Benchmark"""
        # warm-up for JIT compile
        for arr in data_list[:2]:
            buffer.push(arr)

        start = time.perf_counter()
        for arr in data_list:
            buffer.push(arr)
        return time.perf_counter() - start

    def benchmark_last(buffer, fractions=(0.25, 0.5, 1.0)):
        """
        Measure last(n) performance for n as fractions of available rows.
        Auto-scales repeats so total copied rows are comparable.
        Returns dict: {fraction: (elapsed, repeats, n)}
        """

        avail = getattr(buffer, "shape", (0, 0))[0]
        if avail <= 0:
            return {}

        # JIT warm-up for numba variant
        buffer.last(1)
        buffer.last(min(2, avail))

        # Use the buffer's current valid columns
        def current_ncols(buf):
            return getattr(buf, "_nColEntries", getattr(buf, "shape", (0, 0))[1])

        results = {}
        for frac in fractions:
            n = max(1, min(avail, int(avail * float(frac))))
            # keep bounds to avoid super tiny/huge loops
            target_rows = max(10_000, int(avail * 0.25))
            repeats = max(10, min(10_000, target_rows // n))

            # Capture ncols once per fraction (stable after pushes)
            ncols = current_ncols(buffer)

            # time the calls
            t0 = time.perf_counter()
            out = None
            for _ in range(repeats):
                out = buffer.last(n)
            dt = time.perf_counter() - t0

            # touch ‘out’ a bit so it isn’t optimized away by Python ref (cheap)
            if out is not None:
                _ = out.shape

            results[frac] = (dt, repeats, n, ncols)
        return results

    def generate_test_data(n_batches, batch_rows, batch_cols):
        return [np.random.rand(batch_rows, batch_cols) for _ in range(n_batches)]

    def _ensure_2d(arr):
        """Helper: ensure arr is a 2D numpy array for imshow/contour (rows x cols)."""
        a = np.array(arr, dtype=float)
        if a.ndim == 1:
            a = a.reshape(-1, 1)
        return a

    def _plot_heatmap(ax, rows_grid, cols_grid, data, title, cmap="viridis", vmin=None, vmax=None):
        """
        Show a heatmap for given data (rows x cols). rows_grid, cols_grid are tick labels.
        vmin/vmax can be shared across subplots to align color scales.
        """
        data = _ensure_2d(data)
        im = ax.imshow(
            data,
            origin="lower",
            aspect="auto",
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
        )
        ax.set_title(title)
        ax.set_xlabel("batch_cols")
        ax.set_ylabel("batch_rows")
        ax.set_xticks(np.arange(len(cols_grid)))
        ax.set_xticklabels([str(c) for c in cols_grid])
        ax.set_yticks(np.arange(len(rows_grid)))
        ax.set_yticklabels([str(r) for r in rows_grid])
        cbar = plt.colorbar(im, ax=ax, pad=0.01)
        cbar.ax.set_ylabel("data points/s", rotation=90)
        cbar.formatter = ScalarFormatter(useMathText=True)
        cbar.formatter.set_powerlimits((-2, 2))
        cbar.update_ticks()

    def plot_results(buffer_size, rows_list, cols_list, push_py, push_nb, last_py_map, last_nb_map):
        """
        Make figures for one buffer_size:
        - Push: one window with 2 subplots (Python | Numba).
        - Last(n): one window with 3 rows (fractions) x 2 columns (Python | Numba).
        Data arrays are shape [len(rows_list), len(cols_list)].
        """
        # -------- Push figure (2 subplots side-by-side) --------
        fig_push, axes_push = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
        # Share color scale between Python and Numba push
        vmin_push = float(np.nanmin(push_py)) if np.isfinite(np.nanmin(push_py)) else None
        vmax_push = float(np.nanmax(push_py)) if np.isfinite(np.nanmax(push_py)) else None
        if hasNUMBA and push_nb is not None:
            vmin_nb = float(np.nanmin(push_nb)) if np.isfinite(np.nanmin(push_nb)) else None
            vmax_nb = float(np.nanmax(push_nb)) if np.isfinite(np.nanmax(push_nb)) else None
            vmin_push = min(vmin_push, vmin_nb) if vmin_push is not None and vmin_nb is not None else vmin_push or vmin_nb
            vmax_push = max(vmax_push, vmax_nb) if vmax_push is not None and vmax_nb is not None else vmax_push or vmax_nb
        _plot_heatmap(axes_push[0], rows_list, cols_list, push_py, f"Push Python (buffer_size={buffer_size})", vmin=vmin_push, vmax=vmax_push)
        if hasNUMBA and push_nb is not None:
            _plot_heatmap(axes_push[1], rows_list, cols_list, push_nb, f"Push Numba (buffer_size={buffer_size})", vmin=vmin_push, vmax=vmax_push)
        else:
            axes_push[1].set_visible(False)
        fig_push.suptitle("Push throughput: Python vs Numba", fontsize=11)

        # -------- last(n) figure (3 rows x 2 cols: fractions × [Python | Numba]) --------
        fracs = list(last_py_map.keys())
        nrows_sub = len(fracs)
        fig_last, axes_last = plt.subplots(nrows_sub, 2, figsize=(12, 4 * nrows_sub), constrained_layout=True)
        if nrows_sub == 1:
            axes_last = np.array([axes_last])                                  # ensure 2D indexing
        for i, frac in enumerate(fracs):
            data_py = last_py_map.get(frac)
            data_nb = last_nb_map.get(frac) if last_nb_map is not None else None
            # Share color scale per row between Python and Numba
            vmin_row = float(np.nanmin(data_py)) if np.isfinite(np.nanmin(data_py)) else None
            vmax_row = float(np.nanmax(data_py)) if np.isfinite(np.nanmax(data_py)) else None
            if hasNUMBA and data_nb is not None:
                vmin_nb = float(np.nanmin(data_nb)) if np.isfinite(np.nanmin(data_nb)) else None
                vmax_nb = float(np.nanmax(data_nb)) if np.isfinite(np.nanmax(data_nb)) else None
                vmin_row = min(vmin_row, vmin_nb) if vmin_row is not None and vmin_nb is not None else vmin_row or vmin_nb
                vmax_row = max(vmax_row, vmax_nb) if vmax_row is not None and vmax_nb is not None else vmax_row or vmax_nb
            _plot_heatmap(axes_last[i, 0], rows_list, cols_list, data_py, f"last(n) frac={frac} - Python", vmin=vmin_row, vmax=vmax_row)
            if hasNUMBA and data_nb is not None:
                _plot_heatmap(axes_last[i, 1], rows_list, cols_list, data_nb, f"last(n) frac={frac} - Numba", vmin=vmin_row, vmax=vmax_row)
            else:
                axes_last[i, 1].set_visible(False)
        fig_last.suptitle(f"last(n) throughput by fraction (buffer_size={buffer_size})", fontsize=11)

    def collect_and_plot():
        # Config
        N = 1000                                                               # number of batches to push
        buffer_sizes = [1024, 64*1024, 128*1024, 512*1024]
        rows_list    = [50, 64, 256, 512, 1024]
        cols_list    = [1, 4, 8, 16, 32]
        last_fracs   = (0.25, 0.5, 1.0)

        # Index maps
        r_index = {v: i for i, v in enumerate(rows_list)}
        c_index = {v: j for j, v in enumerate(cols_list)}

        for buffer_size in buffer_sizes:
            # Prepare result arrays
            push_py = np.full((len(rows_list), len(cols_list)), np.nan, dtype=float)
            push_nb = np.full((len(rows_list), len(cols_list)), np.nan, dtype=float) if hasNUMBA else None
            last_py = {f: np.full((len(rows_list), len(cols_list)), np.nan, dtype=float) for f in last_fracs}
            last_nb = {f: np.full((len(rows_list), len(cols_list)), np.nan, dtype=float) for f in last_fracs} if hasNUMBA else {}

            for batch_rows in rows_list:
                for batch_cols in cols_list:
                    print(f"[buffer_size={buffer_size}] rows={batch_rows}, cols={batch_cols}")
                    data = generate_test_data(N, batch_rows, batch_cols)

                    # Python buffer
                    buf_py = CircularBuffer(buffer_size, 16)
                    t_py = benchmark_push(buf_py, data)
                    py_dps = (N * batch_rows * batch_cols) / t_py if t_py > 0 else float('inf')
                    push_py[r_index[batch_rows], c_index[batch_cols]] = py_dps
                    last_py_res = benchmark_last(buf_py, last_fracs)
                    for frac, (dt, reps, n, ncols) in last_py_res.items():
                        rows = reps * n
                        rps = rows / dt if dt > 0 else float('inf')
                        dps = rps * ncols
                        last_py[frac][r_index[batch_rows], c_index[batch_cols]] = dps

                    # Numba buffer (if available)
                    if hasNUMBA:
                        buf_nb = CircularBuffer64(buffer_size, 16)
                        t_nb = benchmark_push(buf_nb, data)
                        nb_dps = (N * batch_rows * batch_cols) / t_nb if t_nb > 0 else float('inf')
                        push_nb[r_index[batch_rows], c_index[batch_cols]] = nb_dps
                        last_nb_res = benchmark_last(buf_nb, last_fracs)
                        for frac, (dt, reps, n, ncols) in last_nb_res.items():
                            rows = reps * n
                            rps = rows / dt if dt > 0 else float('inf')
                            dps = rps * ncols
                            last_nb[frac][r_index[batch_rows], c_index[batch_cols]] = dps

            # Plot for this buffer_size
            plot_results(buffer_size, rows_list, cols_list, push_py, push_nb, last_py, last_nb)

        plt.show()

    def collect_and_print():
        N = 1000                                                               # number of batches to push

        for buffer_size in [1024, 64*1024, 128*1024, 512*1024]:
            print(f"Testing with buffer_size={buffer_size} =====================================================")
            for batch_rows in [50, 64, 256, 512, 1024]:
                for batch_cols in [1, 4, 8, 16, 32]:
                    print(f"Testing with rows={batch_rows}, cols={batch_cols}")
                    data = generate_test_data(N, batch_rows, batch_cols)

                    # Pure Python
                    buf_py = CircularBuffer(buffer_size, 16)
                    t_py  = benchmark_push(buf_py, data)
                    print(f"Python push: {N*batch_rows*batch_cols/t_py:.0f} data points/sec")

                    # Numba jitclass
                    buf_jit = CircularBuffer64(buffer_size, 16)
                    t_jit  = benchmark_push(buf_jit, data)
                    print(f"Numba push : {N*batch_rows*batch_cols/t_jit:.0f} data points/sec")
                    print(f"Speedup from Numba: {t_py/t_jit:.2f}×")

                    last_py = benchmark_last(buf_py)
                    for frac, (dt, reps, n, ncols) in last_py.items():
                        rows = reps * n
                        cps = reps / dt if dt > 0 else float('inf')
                        rps = rows / dt if dt > 0 else float('inf')
                        dps = rps * ncols
                        print(f"Python last(n={n:>7}, frac={frac:>4}): data points/s={dps:,.0f}")

                    last_jit = benchmark_last(buf_jit)
                    for frac, (dt, reps, n, ncols) in last_jit.items():
                        rows = reps * n
                        cps = reps / dt if dt > 0 else float('inf')
                        rps = rows / dt if dt > 0 else float('inf')
                        dps = rps * ncols
                        print(f"Numba  last(n={n:>7}, frac={frac:>4}): data points/s={dps:,.0f}")

    # Run textual benchmarks
    collect_and_print()
    # Then collect and plot heatmaps/contours
    collect_and_plot()