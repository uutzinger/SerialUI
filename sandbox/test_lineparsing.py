import logging, time
import re
import numpy as np

MAX_COLS = 16           # maximum number of columns (after this it begins to overflow off bottom of chart)
MAX_ROWS = 256          # maximum number of rows in the buffer
MAX_ROWS_LINEDATA = 64  # maximum number of rows for temporary array when parsing line data

# "Power: 1 2 3 4" > "Power" , "1 2 3 4"
# "Power: 1 2 3 4; 4 5 6 7" > "Power" , "1 2 3 4; 4 5 6 7"
# "Power: 1 2 3 4, 4 5 6 7" > "Power" , "1 2 3 4, 4 5 6 7"
# "Speed: 1 2 3 4, Power: 1 2 3 4" > "Speed", "1 2 3 4, ", "Power" , "1 2 3 4"
# "Speed: 1 2 3 4, 5 6 7 8, Power: 1 2 3 4" > "Speed", "1 2 3 4, 5 6 7 8,", "Power" , "1 2 3 4"
NAMED_SEGMENT_REGEX = re.compile(r'(\w+):([\d\s;,]+)')
#NAMED_SEGMENT_REGEX = re.compile(r'\s*,?(\w+):\s*([\d\s;,]+)')
#NAMED_SEGMENT_REGEX = re.compile(r'(\w+):([\d\s;,]+?)(?=\s*\w+:|$)')

# "1 2 3 4, 4 5 6 7" > ["1 2 3 4", "4 5 6 7"] 
# "1 2 3 4; 4 5 6 7" > ["1 2 3 4", "4 5 6 7"]
SEGMENT_SPLIT_REGEX = re.compile(r'[,;]+')

class CircularBuffer:
    '''
    Circular buffer for storing numpy data.

    - Dynamically adjusts columns based on incoming data.
    - Uses a rolling approach to keep the most recent data.
    - Ensures retrieval provides only valid rows and columns.
    - Tracks sample numbers for continuous measurements.
    '''

    def __init__(self, initial_rows, initial_columns, dtype=float):
        ''' Initialize the circular buffer '''
        self._nrows = initial_rows
        self._ncols = initial_columns
        self._dtype = dtype
        # _data shape is [nrows x ncols]
        self._data = np.full((initial_rows, initial_columns), np.nan, dtype=self._dtype)

        self._head = 0         # Next insert position
        self._num_entries = 0  # Number of valid (populated) row entries
        self._num_columns = 0  # Tracks how many columns have been populated
        self._oldest = 0       # Tracks the oldest "measurement number"
        self._latest = 0       # Tracks the newest "measurement number"

    def push(self, data_array: np.ndarray):
        ''' Add new data to the circular buffer '''

        # 1 Determine size of new data
        num_new_rows, num_new_cols = data_array.shape

        # 2 Expand columns if necessary
        if num_new_cols > self._ncols:
            columns_to_add = max(self._ncols // 2, num_new_cols - self._ncols)
            new_cols = self._ncols + columns_to_add
            new_data = np.full((self._nrows, new_cols), np.nan, dtype=self._dtype)

            # Preserve old data
            # We only copy up to self._ncols since that's what existed
            new_data[:, :self._ncols] = self._data
            self._data = new_data
            self._ncols = new_cols

        # 3 Expand rows by if necessary
        if num_new_rows > self._nrows:
            rows_to_add = max(self._nrows // 2, num_new_rows - self._nrows)
            new_rows = self._nrows + rows_to_add
            new_data = np.full((new_rows, self._ncols), np.nan, dtype=self._dtype)

            # Preserve old data
            new_data[:self._nrows, :] = self._data
            self._data = new_data
            self._nrows = new_rows  

        # 4 If new data exactly fills the buffer we overwrite all at once
        if num_new_rows == self._nrows:
            self._data[:self._nrows, :num_new_cols] = data_array[-self._nrows:, :num_new_cols]
            self._head = 0 
            self._num_entries = self._nrows
            self._num_columns = max(num_new_cols, self._num_columns)
            self._latest += num_new_rows
            self._oldest = self._latest - self._num_entries + 1
            return

        # 5 Write new data at _head
        end_pos = (self._head + num_new_rows) % self._nrows

        if end_pos < self._head:
            # Wraparound insertion: Split into two parts
            first_part = self._nrows - self._head
            self._data[self._head:self._nrows, :num_new_cols] = data_array[:first_part, :num_new_cols]
            self._data[0:end_pos, :num_new_cols] = data_array[first_part:, :num_new_cols]
        else:
            # Direct insertion (no wrap around)
            self._data[self._head:end_pos, :num_new_cols] = data_array[:, :num_new_cols]

        # 6 Update index and counters
        self._head = end_pos
        self._num_entries = min(self._num_entries + num_new_rows, self._nrows)
        self._num_columns = max(self._num_columns, num_new_cols)
        self._latest += num_new_rows
        self._oldest = self._latest - self._num_entries + 1

    def clear(self):
        ''' Clear the buffer (set all values to NaN) '''
        self._data.fill(np.nan)
        self._head = 0
        self._num_entries = 0
        self._num_columns = 0
        self._oldest = 0
        self._latest = 0

    @property
    def data(self):
        ''' Retrieve valid data ordered from oldest to newest '''
        if self._num_entries == 0:
            return np.empty((0, self._num_columns), dtype=self.dtype)

        start = (self._head - self._num_entries) % self._nrows
        end = (start + self._num_entries) % self._nrows

        if start <= end:
            # No wrap needed
            return self._data[start:end, :self._num_columns]
        else:
            # Wrap around
            return np.vstack([
                self._data[start:self._nrows, :self._num_columns],
                self._data[:end, :self._num_columns]
            ])
        
    @property
    def shape(self):
        ''' Return the shape (populated rows, populated columns) of the buffer '''
        return (self._num_entries, self._num_columns) 

    @property
    def capacity(self):
        ''' Return the capacity (rows, columns) of the buffer '''
        return (self._nrows, self._ncols) 

    @property
    def ncols(self):
        ''' Return the number of columns of the buffer '''
        return self._ncols 

    @property
    def nrows(self):
        ''' Return the number of rows of the buffer '''
        return self._nrows 

    @property
    def counter(self):
        ''' Return the oldest and newest measurement number'''
        return (self._oldest, self._latest)

    @property
    def dtype(self):
        ''' Return the dataype '''
        return self._dtype 
        
def process_lines_simple(lines, buffer, data_array, variable_index):
    """Fast processing of data without headers, dynamically expanding the buffer."""

    row_idx = 0             # Tracks row position in data_array
    max_segment_length = 0  # Track longest segment
    num_columns = 0         # Track maximum column index
    new_samples = 0         # Track number of valid rows
    data_array_rows, data_array_cols = data_array.shape

    for line in lines:
        # Decode byte string if necessary
        decoded_line = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else line

        # Split into components efficiently
        segments = SEGMENT_SPLIT_REGEX.split(decoded_line.strip(" ,;"))

        # Convert segments to NumPy arrays
        for col_idx, segment in enumerate(segments):
            segment_data = np.array(segment.split(), dtype=float)

            len_segment = len(segment_data)
            row_end = row_idx + len_segment
            max_segment_length = max(max_segment_length, len_segment)

            # Expand rows dynamically (similar to CircularBuffer logic)
            if row_end >= data_array_rows:
                rows_to_add = max(data_array_rows // 2, row_end - data_array_rows)
                new_rows = data_array_rows + rows_to_add
                new_data_array = np.full((new_rows, data_array_cols), np.nan, dtype=data_array.dtype)
                new_data_array[:data_array_rows, :] = data_array
                data_array = new_data_array
                data_array_rows = new_rows  # Update row count

            # Expand columns dynamically (similar to CircularBuffer logic)
            if col_idx >= data_array_cols:
                cols_to_add = max(data_array_cols // 2, col_idx - data_array_cols + 1)
                new_cols = data_array_cols + cols_to_add
                new_data_array = np.full((data_array_rows, new_cols), np.nan, dtype=data_array.dtype)
                new_data_array[:, :data_array_cols] = data_array  # Copy old data
                data_array = new_data_array
                data_array_cols = new_cols  # Update column count

            # Store the values in `data_array`
            data_array[row_idx:row_end, col_idx] = segment_data

        new_samples += max_segment_length

        # Advance row_idx after processing a full line
        row_idx += max_segment_length  # Move to next free row
        max_segment_length = 0  # Reset segment tracking for the new row
        num_columns = max(col_idx + 1, num_columns)  # Update maximum column count

    # Update variable index dynamically
    variable_index = {str(i + 1): i for i in range(num_columns)}

    # Push only the valid portion of data_array to the buffer
    buffer.push(data_array[:new_samples, :num_columns])

    # Clear only the used portion of `data_array`
    data_array[:new_samples, :num_columns] = np.nan  

    return variable_index, data_array

def process_lines(lines, buffer, data_array, variable_index):

    # Initialize variables
    row_idx = 0
    processed_vars = set()  # Track variables already processed in this line
    max_segment_length = 0  # Track longest segment
    new_samples = 0         # Track new samples added
    data_array_rows, data_array_cols = data_array.shape

    for line in lines:
        # Decode the line if it's a byte object
        decoded_line = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else line

        # Match named segments (e.g., "Power: 1 2 3 4")
        named_segments = NAMED_SEGMENT_REGEX.findall(decoded_line)
        
        for name, data in named_segments:
            # Split data by semicolon or comma for multiple components
            segments = SEGMENT_SPLIT_REGEX.split(data.strip(" ,;"))

            for i, segment in enumerate(segments):
                # Convert segment to NumPy array
                segment_data = np.fromiter(segment.split(), dtype=float)

                # Assign correct variable name (with index for subsegments)
                name_ext = name if len(segments) == 1 else f"{name}_{i + 1}"

                # Efficient variable indexing
                col_idx = variable_index.setdefault(name_ext, len(variable_index))

                len_segment = len(segment_data)

                # If this variable has already been processed, increment `row_idx` *before* storing data
                if name_ext in processed_vars:
                    row_idx += max_segment_length  # Move to next free row
                    new_samples += max_segment_length
                    processed_vars.clear()  # Reset for new row tracking
                    max_segment_length = 0  # Reset segment tracking for the new row

                # Track that this variable has been processed
                processed_vars.add(name_ext)

                row_end = row_idx + len_segment # update row end

                # Keep track of the maximum segment length (to increment `row_idx` later)
                max_segment_length = max(max_segment_length, len_segment)

                # Expand data_array when needed (Memory-efficient)
                if row_end >= data_array_rows:
                    rows_to_add = max(data_array_rows // 2, row_end - data_array_rows)
                    new_rows = data_array_rows + rows_to_add
                    new_data_array = np.full((new_rows, data_array_cols), np.nan, dtype=data_array.dtype)
                    new_data_array[:data_array_rows, :] = data_array
                    data_array = new_data_array
                    data_array_rows = new_rows  # Update row count

                # Expand columns if needed
                if col_idx >= data_array_cols:
                    cols_to_add = max(data_array_cols // 2, col_idx - data_array_cols + 1)
                    new_cols = data_array_cols + cols_to_add
                    new_data_array = np.full((data_array_rows, new_cols), np.nan, dtype=data_array.dtype)
                    new_data_array[:, :data_array_cols] = data_array  # Copy old data
                    data_array = new_data_array
                    data_array_cols = new_cols  # Update column count

                # Store the values in `data_array`
                data_array[row_idx:row_end, col_idx] = segment_data

        # After processing a full line, move to the next row
        row_idx += max_segment_length  
        new_samples += max_segment_length  
        max_segment_length = 0 
        processed_vars.clear()

    # Update buffer and variable index
    num_columns = max(variable_index.values(), default=0) + 1

    # Push only the valid portion of `data_array`
    buffer.push(data_array[:new_samples, :num_columns])

    # Clear only the used portion of `data_array`
    data_array[:new_samples, :num_columns] = np.nan  

    return variable_index, data_array


def main():

    buffer = CircularBuffer(MAX_ROWS, MAX_COLS)
    data_array = np.full((MAX_ROWS_LINEDATA, MAX_COLS), np.nan)
    variable_index = {}

    # Test Buffer
    test_array = np.random.rand(MAX_ROWS_LINEDATA, MAX_COLS) 
    tic = time.perf_counter()
    for _ in range(100000):
        # Buffer
        buffer.push(test_array)
    toc = time.perf_counter()
    print(f"\n⏱️ Processing time: {100000*MAX_ROWS_LINEDATA/(toc - tic):0.1f} lines/sec")
    print(f"⏱️ Processing time: {100000*MAX_ROWS_LINEDATA*MAX_COLS/(toc - tic):0.1f} floats/sec")

    # 7 Million lines/sec
    # 115 Million floats/sec

    # Test input (lines as strings)
    text_lines = [
        "Power: 1 2 3 4, Speed: 5 6 7 8",
        "Power: 4 3 2 1, Speed: 8 7 6 5",
        "Sound: 1 2 3 4",
        "Sound: 5 6 7 Blood Pressure: 121",
        "Sound: 8 9 10 11 12",
        "Sound: 13 14 Sound: 15 16, Oxygenation: 99"
    ]
    for line in text_lines:
        byte_size = len(line.encode("utf-8"))

    # Convert lines to `bytearray`
    lines = [bytearray(line, encoding="utf-8") for line in text_lines]
    # Initialize circular buffer

    variable_index, data_array = process_lines(lines, buffer, data_array, variable_index)
    tic = time.perf_counter()
    for _ in range(100000):
        # Process lines
        variable_index, data_array = process_lines(lines, buffer, data_array, variable_index)
    toc = time.perf_counter()
    print(f"\n⏱️ Processing time: {100000*len(text_lines)/(toc - tic):0.1f} lines/sec")
    print(f"⏱️ Processing time: {100000*byte_size/(toc - tic):0.1f} bytes/sec")

    # 73 k lines/sec
    # 507 k bytes/sec

    # Display
    print("\n📌 **Variable Index**")
    print(variable_index)

    # print("\n📊 **Buffer Data**")
    # for i, row in enumerate(buffer.data):
    #     print(f"Row {i}: {row}")


    ################################################
    ################################################
    ################################################

    buffer.clear()
    data_array = np.full((MAX_ROWS_LINEDATA, MAX_COLS), np.nan)
    variable_index = {}
    sample_number = 0

    # Test input (lines as strings)
    text_lines = [
        "Sound: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32",
        "Sound: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 Blood Pressure: 120",
        "Sound: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32",
        "Sound: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 Oxygenation: 100"
        "Sound: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32",
        "Sound: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 Blood Pressure: 121",
        "Sound: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32",
        "Sound: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 Oxygenation: 99"
        "Sound: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32",
        "Sound: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 Blood Pressure: 122",
        "Sound: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32",
        "Sound: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 Oxygenation: 98"
    ]
    for line in text_lines:
        byte_size = len(line.encode("utf-8"))

    # Convert lines to `bytearray`
    lines = [bytearray(line, encoding="utf-8") for line in text_lines]
    # Initialize circular buffer

    first_part = text_lines[:5]
    second_part = text_lines[5:] 
    lines_first_part = [bytearray(line, encoding="utf-8") for line in first_part]
    lines_second_part = [bytearray(line, encoding="utf-8") for line in second_part]
    variable_index, data_array = process_lines(lines_first_part, buffer, data_array, variable_index)
    variable_index, data_array = process_lines(lines_second_part, buffer, data_array, variable_index)
    tic = time.perf_counter()
    for _ in range(100000):
        # Process lines
        variable_index, data_array = process_lines(lines_first_part, buffer, data_array, variable_index)
        variable_index, data_array = process_lines(lines_second_part, buffer, data_array, variable_index)
    toc = time.perf_counter()
    print(f"\n⏱️ Processing time: {100000*len(text_lines)/(toc - tic):0.1f} lines/sec")
    print(f"⏱️ Processing time: {100000*byte_size/(toc - tic):0.1f} bytes/sec")

    # 67 k lines/sec
    # 727 k bytes/sec

    #
    # Display
    print("\n📌 **Variable Index**")
    print(variable_index)

    # print("\n📊 **Buffer Data**")
    # for i, row in enumerate(buffer.data):
    #     print(f"Row {i}: {row}")

    ################################################
    ################################################
    ################################################

    buffer.clear()
    data_array = np.full((MAX_ROWS_LINEDATA, MAX_COLS), np.nan)
    variable_index = {}

    text_lines = [
        "1 2 3 4, 5 6 7 8",
        "4 3 2 1, 8 7 6 5",
        "1 2 3 4",
        "5 6 7, 121",
        "8 9 10 11 12",
        "13 14, 15 16, 99"
    ]
    for line in text_lines:
        byte_size = len(line.encode("utf-8"))

    # Convert lines to `bytearray`
    lines = [bytearray(line, encoding="utf-8") for line in text_lines]

    variable_index = {}

    # Process lines
    variable_index, data_array = process_lines_simple(lines, buffer, data_array, variable_index)
    tic = time.perf_counter()
    for _ in range(100000):
        # Process lines
        variable_index, data_array = process_lines_simple(lines, buffer, data_array, variable_index)
    toc = time.perf_counter()
    print(f"\n⏱️ Processing time: {100000*len(text_lines)/(toc - tic):0.1f} lines/sec")
    print(f"⏱️ Processing time: {100000*byte_size/(toc - tic):0.1f} bytes/sec")

    # 80k lines/sec
    # 213 k bytes/sec

    # Display
    print("\n📌 **Variable Index**")
    print(variable_index)

    # print("\n📊 **Buffer Data**")
    # for i, row in enumerate(buffer.data):
    #     print(f"Row {i}: {row}")



if __name__ == "__main__":
    main()