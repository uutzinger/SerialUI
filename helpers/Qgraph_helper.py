############################################################################################
# QT Chart Helper
############################################################################################
#
# This code is maintained by Urs Utzinger
############################################################################################

# General Imports
import logging
import time
import re
import textwrap

# Numerical Math
import numpy as np

# QT Libraries
try:
    from PyQt6.QtCore import (
        QObject, QTimer, QThread, 
        pyqtSlot, QStandardPaths, pyqtSignal
    )
    from PyQt6.QtWidgets import (
        QFileDialog, QLineEdit, QSlider,QTabWidget,
        QGraphicsView,QVBoxLayout
    )
    from PyQt6.QtGui import QBrush, QColor
    hasQt6 = True
except:
    from PyQt5.QtCore import (
        QObject, QTimer, QThread, 
        pyqtSlot, QStandardPaths, pyqtSignal
    )
    from PyQt5.QtWidgets import (
        QFileDialog, QLineEdit, QSlider,
        QTabWidget, QGraphicsView, QVBoxLayout,
    )
    from PyQt5.QtGui import QBrush, QColor
    hasQt6 = False

# QT Graphing for chart plotting
import pyqtgraph as pg

# Colors
try:
    from helpers.Qgraph_colors import color_names_sweet16 as COLORS
except:
    from Qgraph_colors import color_names_sweet16 as COLORS

########################################################################################
# Debug
DEBUGCHART = False
PROFILEME   = True

# Constants
########################################################################################
MAX_ROWS = 131072        # data history length
MAX_COLS = len(COLORS)   # maximum number of data traces [available colors]
DEF_COLS          =   2  # default number of data traces
UPDATE_INTERVAL   =  50  # [ms] 20 Hz plot update, visualization does not improve with higher rate, it takes about 4ms to update plot
MAX_ROWS_LINEDATA = 512  # maximum number of rows for temporary array when parsing line data

########################################################################################
# Support Functions and Classes
########################################################################################

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

def clip_value(value, min_value, max_value):
    return max(min_value, min(value, max_value))

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

        if start < end:
            # No wrap needed
            return self._data[start:end, :self._num_columns]
        else:
            # Wrap around
            return np.vstack([
                self._data[start:self._nrows, :self._num_columns],
                self._data[0:end, :self._num_columns]
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
        ''' Return the data type '''
        return self._dtype 

############################################################################################
# QChart interaction with Graphical User Interface
############################################################################################

class QChartUI(QObject):
    """
    Chart Interface for QT

    The chart displays signals in a plot.
    The data is received from the serial port and organized into columns of a numpy array.
    The plot can be zoomed in by selecting how far back in time to display it.
    The horizontal axis is the sample number.
    The vertical axis is auto scaled to the max and minimum values of the data.

    Slots (functions available to respond to external signals)
        on_pushButton_ChartStartStop
        on_pushButton_ChartClear
        on_pushButton_ChartSave
        on_pushButton_ChartSaveFigure
        on_ZoomSliderChanged(int)
        on_ZoomLineEditChanged
        on_receivedLines(list)
        on_changeDataSeparator

    Functions
        parse_lines()
        parse_lines_simple()
        updatePlot()
    """

    # Signals
    ########################################################################################
    plottingRunning = pyqtSignal(bool)  # emit True if plotting, False if not plotting

    def __init__(self, parent=None, ui=None, serialUI=None, serialWorker=None, logger=None, encoding="utf-8"):

        super().__init__(parent)

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"

        self.mtoc_updatePlot = 0.
        self.mtoc_process_lines_simple = 0.
        self.mtoc_process_lines = 0.

        # Logging setup
        self.logger = logger if logger else logging.getLogger("QChartUI")
        if parent is not None and hasattr(parent, "handle_log"):
            self.handle_log = parent.handle_log

        if ui is None:
            self.handle_log(logging.ERROR, f"[{self.thread_id}]: Need to have access to User Interface")
        self.ui = ui

        if serialUI is None:
            self.handle_log(logging.ERROR, f"[{self.thread_id}]: Need to have access to Serial User Interface")
        self.serialUI = serialUI

        if serialWorker is None:
            self.handle_log(logging.ERROR, f"[{self.thread_id}]: Need to have access to Serial Worker")
        self.serialWorker = serialWorker

        self.encoding = encoding

        # Create the chart
        self.chartWidget = pg.PlotWidget()
    
        # Replace the GraphicsView widget in the User Interface (ui) with the pyqtgraph plot
        self.tabWidget = self.ui.findChild(QTabWidget, "tabWidget_MainWindow")
        self.graphicsView = self.ui.findChild(QGraphicsView, "chartView")
        self.tabLayout = QVBoxLayout(self.graphicsView)
        self.tabLayout.addWidget(self.chartWidget)

        # Setting the plotWidget features
        self.chartWidget.setBackground("w")
        self.chartWidget.showGrid(x=True, y=True)
        self.chartWidget.setLabel("left", "Signal", units="")
        self.chartWidget.setLabel("bottom", "Sample", units="")
        self.chartWidget.setTitle("Chart")
        self.chartWidget.setMouseEnabled(x=True, y=True)  # allow to move and zoom in the plot window

        self.sample_number = 0  # A counter indicating current sample number which is also the x position in the plot
        self.pen = [pg.mkPen(color, width=2) for color in COLORS]

        self.data_lines = []
        self.legend = None
        

        self.maxPoints = (1024) # maximum number of points to show in a plot from now to the past
        self.buffer = CircularBuffer(MAX_ROWS, MAX_COLS, dtype=float)
        self.data_array = np.full((MAX_ROWS_LINEDATA, MAX_COLS), np.nan)
        self.data_array_rows, self.data_array_cols = self.data_array.shape

        self.legends = []        # stores the variable names
        self.variable_index = {} # stores the variable names and their column index in the buffer

        self.sample_number = 0 
        self._prev_variable_index = {}
        self._sorted_variables = []
        self._variable_names = []

        # Initialize the plot axis ranges
        self.chartWidget.setXRange(0, self.maxPoints)
        self.chartWidget.setYRange(-1.0, 1.0)

        # Initialize the horizontal slider
        self.horizontalSlider = self.ui.findChild(QSlider, "horizontalSlider_Zoom")
        self.horizontalSlider.setMinimum(8)
        self.horizontalSlider.setMaximum(MAX_ROWS)
        self.horizontalSlider.setValue(int(self.maxPoints))
        self.lineEdit = self.ui.findChild(QLineEdit, "lineEdit_Horizontal_Zoom")
        self.lineEdit.setText(str(self.maxPoints))
        
        self.textDataSeparator = 'No Labels (simple)'                                 # default data separator
        index = self.ui.comboBoxDropDown_DataSeparator.findText("No Labels (simple)") # find default data separator in drop down
        self.ui.comboBoxDropDown_DataSeparator.setCurrentIndex(index)                 # update data separator combobox

        self.ui.pushButton_ChartStartStop.setText("Start")

        # Plot update frequency
        self.ChartTimer = QTimer()
        self.ChartTimer.setInterval(UPDATE_INTERVAL)
        self.ChartTimer.timeout.connect(self.updatePlot)

        self.handle_log(
            logging.INFO, 
            f"[{self.thread_id}]: Initialized."
        )

    # Utility functions
    ########################################################################################

    def handle_log(self, level, message):
        self.logger.log(level, message)
    
    @pyqtSlot()
    def handle_mtoc(self):
        """Emit the mtoc signal with a function name and time in a single log call."""
        log_message = textwrap.dedent(f"""
            Chart UI Profiling
            =============================================================
            mtoc_updatePlot         took {self.mtoc_updatePlot*1000:.2f} ms
            mtoc_process_lines      took {self.mtoc_process_lines*1000:.2f} ms
            mtoc_process_lines_smpl took {self.mtoc_process_lines_simple*1000:.2f} ms
        """)
        self.handle_log(logging.INFO, log_message)

    def cleanup(self):
        """
        Cleanup the chart UI.

        - Disconnects the updatePlot function from the timer.
        - Clears the plot data and legend.
        - Resets the plot axis ranges.
        """
        if hasattr(self.ChartTimer, "isActive") and self.ChartTimer.isActive():
            self.ChartTimer.stop()  
            self.ChartTimer.timeout.disconnect()
        if self.data_lines:
            # Remove each trace from the chart before clearing the list
            for line in self.data_lines:
                self.chartWidget.removeItem(line)
            self.data_lines.clear()
        if self.legend is not None:
            self.legend.clear()
        self.chartWidget.clear()
        self.handle_log(
            logging.INFO, 
            f"[{self.thread_id}]: cleaned up."
        )
        
    def updatePlot(self):
        """
        Update the chart plot.

        - Plots only valid (non-nan) data.
        - Dynamically updates the legend.
        - Ensures that number of traces matches number of columns.
        - Sets the horizontal range to show the newest data up to maxPoints.
        - Sets vertical range dynamically based on min/max values of the data.
        """

        if DEBUGCHART or PROFILEME:
            tic = time.perf_counter()
    
        data = self.buffer.data  # Retrieve circular buffer data
        num_rows, num_cols = self.buffer.shape
        oldest_sample, newest_sample = self.buffer.counter
        
        # Only consider the newest samples for p1lotting
        #   self.maxPoints is set by user on the GUI
        start_index = max(0, num_rows - self.maxPoints)
        data_slice = data[start_index:]  # shape (maxPoints, num_cols)
        x_start = oldest_sample + start_index
        x_end = oldest_sample + num_rows - 1
        x = np.arange(x_start, x_end + 1) if data_slice.shape[0] > 0 else np.array([])

        # Ensure `self.legend` is initialized properly
        if self.legend is None:
            self.legend = self.chartWidget.addLegend()
            transparent_brush = QBrush(QColor(255, 255, 255, 0))
            self.legend.setBrush(transparent_brush)

        # Ensure `self.data_lines` is initialized properly
        if not hasattr(self, "data_line"):
            self.data_lines = []

        # Re-sort if variable_index actually changed.
        if self.variable_index != self._prev_variable_index or  num_cols != len(self.data_lines):
            self._prev_variable_index = dict(self.variable_index)  # Store a copy

            # Sort variable_index by column order and extract variable names
            self._sorted_variables = sorted(self.variable_index.items(), key=lambda x: x[1])
            self._variable_names = [name for name, _ in self._sorted_variables]
                
            # 1 Ensure Correct Number of Data Lines

            # Add new lines if we have too few
            while len(self.data_lines) < num_cols:
                new_index = len(self.data_lines)
                new_line = self.chartWidget.plot([], [], pen=self.pen[new_index % len(self.pen)], name=f"Trace {new_index}")
                self.data_lines.append(new_line)

            # Clear traces that are no longer active if we have too many
            while len(self.data_lines) > num_cols:
                old_line = self.data_lines.pop()
                self.chartWidget.removeItem(old_line)

            # 2 Clear and Rebuild the legend

            self.legend.clear()
            for i, line in enumerate(self.data_lines):
                line.opts["name"] = self._variable_names[i] if i < len(self._variable_names) else f"Trace {i}"
                self.legend.addItem(line, line.opts["name"])  # This ensures a 1:1 mapping**


        # Plot data
        ########################################################
        
        max_y, min_y = -np.inf, np.inf
        max_x, min_x = -np.inf, np.inf

        # For each column, update the plot
        for i in range(num_cols):
            column_data = data_slice[:, i] if data_slice.shape[0] > 0 else np.array([])
            # Remove NaNs
            mask = ~np.isnan(column_data)
            valid_y = column_data[mask]
            valid_x = x[mask] if len(x) > 0 else np.array([])

            if valid_x.size > 0:
                max_x, min_x = max(max_x, np.nanmax(valid_x)), min(min_x, np.nanmin(valid_x))
            if valid_y.size > 0:
                max_y, min_y = max(max_y, np.nanmax(valid_y)), min(min_y, np.nanmin(valid_y))

            self.data_lines[i].setData(
                valid_x,
                valid_y,
                autoDownsample=True,
                clipToView=True
            )

        # Adjust axis ranges
        if max_x > -np.inf and min_x < np.inf:
            self.chartWidget.setXRange(min_x, max_x)

        if max_y > -np.inf and min_y < np.inf:
            self.chartWidget.setYRange(min_y, max_y)

        if DEBUGCHART:
            toc = time.perf_counter()
            self.handle_log(
                logging.DEBUG,
                f"[{self.thread_id}]: Plot updated in {1000 * (toc - tic):.2f} ms"
            )

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_updatePlot = max ((toc - tic), self.mtoc_updatePlot)

    ########################################################################################
    # Process Lines Function without Headers
    ########################################################################################

    def process_lines_simple(self, lines, encoding="utf-8"):
        """Fast processing of data without headers, dynamically expanding the buffer."""

        if PROFILEME:
            tic = time.perf_counter()

        row_idx = 0             # Tracks row position in data_array
        max_segment_length = 0  # Track longest segment
        num_columns = 0         # Track maximum column index
        new_samples = 0         # Track number of new samples
        self.data_array_rows, self.data_array_cols = self.data_array.shape 

        for line in lines:
            # Decode byte string if necessary
            decoded_line = line.decode(encoding)

            # Split into components efficiently
            segments = SEGMENT_SPLIT_REGEX.split(decoded_line.strip(" ,;"))

            # Convert segments to NumPy arrays
            for col_idx, segment in enumerate(segments):
                try:
                    segment_data = np.array(segment.split(), dtype=float)
                except:
                    self.handle_log(
                        logging.WARNING,
                        f"[{self.thread_id}]: Could not convert '{segment}' to float. Line '{line}'. "
                    )
                    continue

                len_segment = len(segment_data)
                row_end = row_idx + len_segment
                max_segment_length = max(max_segment_length, len_segment)

                # Expand rows if needed (memory-efficient)
                if row_end >= self.data_array_rows:
                    rows_to_add = max(self.data_array_rows // 2, row_end - self.data_array_rows)
                    new_rows = self.data_array_rows + rows_to_add
                    new_data_array = np.full((new_rows, self.data_array_cols), np.nan, dtype=self.data_array.dtype)
                    new_data_array[:self.data_array_rows, :] = self.data_array
                    self.data_array = new_data_array
                    self.data_array_rows = new_rows

                # Expand columns if needed
                if col_idx >= self.data_array_cols:
                    cols_to_add = max(self.data_array_cols // 2, col_idx - self.data_array_cols + 1)
                    new_cols = self.data_array_cols + cols_to_add
                    new_data_array = np.full((self.data_array_rows, new_cols), np.nan, dtype=self.data_array.dtype)
                    new_data_array[:, :self.data_array_cols] = self.data_array  # Copy old data
                    self.data_array = new_data_array
                    self.data_array_cols = new_cols

                # Store the values in `data_array`
                self.data_array[row_idx:row_end, col_idx] = segment_data

            new_samples += max_segment_length

            # Advance row_idx after processing a full line
            row_idx += max_segment_length  
            max_segment_length = 0  
            num_columns = max(col_idx + 1, num_columns)  

        # Update variable index dynamically
        self.variable_index = {str(i + 1): i for i in range(num_columns)}

        # Push only the valid portion of data_array to the buffer
        self.buffer.push(self.data_array[:new_samples, :num_columns])

        # Clear only the used portion of `data_array`
        self.data_array[:new_samples, :num_columns] = np.nan  

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_process_lines_simple = max((toc - tic), self.mtoc_process_lines_simple)

    ########################################################################################
    # Process Lines Function with Headers
    ########################################################################################

    # Line 1: "Power: 1 2 3 4, Speed: 5 6 7 8"
    # Line 2: "Power: 4 3 2 1, Speed: 8 7 6 5"
    # Result:
    #   Variable index: {"Power:0, "Speed":1}
    #   Data: [[1,5],
    #          [2,6],
    #          [3,7],
    #          [4,8],
    #          [4,8],
    #          [3,7],
    #          [2,6],
    #          [1,5]] 
    #
    # Line 1: "Power: 1, 2, 3, 4 Speed: 5, 6, 7, 8"
    # Line 2: "Power: 4, 3, 2, 1 Speed: 8, 7, 6, 5"
    # Result:
    #   Variable index: {"Power_1":0, "Power_2":1, "Power_3":2, "Power_4":3, "Speed_1":4, "Speed_2":5, "Speed_3":6, "Speed_4":7}
    #   Data: [[1,2,3,4,5,6,7,8],
    #          [4,3,2,1,8,7,6,5]] 
    #
    # Line 1: "Power: 1 2 3 4; 5 6 7 8 Speed:  9 10 11 12; 13 14 15 16" 
    # Line 2: "Power: 4 3 2 1; 8 7 6 5 Speed: 12 11 10  9; 16 15 14 13"
    # Result:
    #   Variable index {"Power_1":0, "Power_2":1, "Speed_1":2, "Speed_2":3
    #   Data: [[1,5, 9,13],
    #          [2,6,10,14],
    #          [3,7,11,15],
    #          [4,8,12,16],
    #          [4,8,12,16],
    #          [3,7,11,15],
    #          [2,6,10,14],
    #          [1,5, 9,13]]
    #

    # Line 1: "Sound: 1 2 3 4"
    # Line 2: "Sound: 5 6 7 Blood Pressure: 121"
    # Line 3: "Sound: 8 9 10 11 12"
    # Line 4: "Sound: 13 14 Sound: 15 16, Oxygenation: 99"

    # Result:
    #   Variable index: {"Sound}":0, "Blood Pressure":1, "Oxygenation":2}
    #   Data: 
    #   [[  1.  nan  nan]
    #   [   2.  nan  nan]
    #   [   3.  nan  nan]
    #   [   4.  nan  nan]
    #   [   5. 121.  nan]
    #   [   6.  nan  nan]
    #   [   7.  nan  nan]
    #   [   8.  nan  nan]
    #   [   9.  nan  nan]
    #   [  10.  nan  nan]
    #   [  11.  nan  nan]
    #   [  12.  nan  nan]
    #   [  13.  nan  nan]
    #   [  14.  nan  nan]
    #   [  15.  nan  99.]  # Moved to new row before inserting second "Sound"
    #   [  16.  nan  nan]]

    def process_lines(self, lines, encoding="utf-8"):

        if PROFILEME:
            tic = time.perf_counter()

        # Initialize variables
        row_idx = 0
        processed_vars = set()  # Track variables already processed in this line
        max_segment_length = 0  # Track longest segment
        new_samples = 0  # Track new samples added
        self.data_array_rows, self.data_array_cols = self.data_array.shape

        for line in lines:
            # Decode the line if it's a byte object
            decoded_line = line.decode(encoding)

            # Match named segments (e.g., "Power: 1 2 3 4")
            named_segments = NAMED_SEGMENT_REGEX.findall(decoded_line)
            
            for name, data in named_segments:
                # Split data by semicolon or comma for multiple components
                segments = SEGMENT_SPLIT_REGEX.split(data.strip(" ,;"))

                for i, segment in enumerate(segments):
                    # Convert segment to NumPy array
                    segment_data = np.array(segment.split(), dtype=float)

                    # Assign correct variable name (with index for subsegments)
                    name_ext = name if len(segments) == 1 else f"{name}_{i + 1}"

                    # Efficient variable indexing
                    col_idx = self.variable_index.setdefault(name_ext, len(self.variable_index))

                    len_segment = len(segment_data)

                    # Restart new columns after a line is completed
                    if name_ext in processed_vars:
                        row_idx += max_segment_length  
                        new_samples += max_segment_length
                        processed_vars.clear()  
                        max_segment_length = 0  

                    # Track that this variable has been processed
                    processed_vars.add(name_ext)

                    row_end = row_idx + len_segment  

                    # Keep track of the maximum segment length (to increment `row_idx` later)
                    max_segment_length = max(max_segment_length, len_segment)

                    # Expand rows dynamically as needed
                    if row_end >= self.data_array_rows:
                        rows_to_add = max(self.data_array_rows // 2, row_end - self.data_array_rows)
                        new_rows = self.data_array_rows + rows_to_add
                        new_data_array = np.full((new_rows, self.data_array_cols), np.nan, dtype=self.data_array.dtype)
                        new_data_array[:self.data_array_rows, :] = self.data_array
                        self.data_array = new_data_array
                        self.data_array_rows = new_rows  

                    # Expand columns dynamically as needed
                    if col_idx >= self.data_array_cols:
                        cols_to_add = max(self.data_array_cols // 2, col_idx - self.data_array_cols + 1)
                        new_cols = self.data_array_cols + cols_to_add
                        new_data_array = np.full((self.data_array_rows, new_cols), np.nan, dtype=self.data_array.dtype)
                        new_data_array[:, :self.data_array_cols] = self.data_array  
                        self.data_array = new_data_array
                        self.data_array_cols = new_cols  

                    # Store the values in `data_array`
                    self.data_array[row_idx:row_end, col_idx] = segment_data

            # After processing a full line, move to the next row
            row_idx += max_segment_length  
            new_samples += max_segment_length  
            max_segment_length = 0  
            processed_vars.clear()  

        # Update buffer and variable index
        num_columns = max(self.variable_index.values(), default=0) + 1

        # Push only the valid portion of `data_array`
        self.buffer.push(self.data_array[:new_samples, :num_columns])

        # Clear only the used portion of `data_array`
        self.data_array[:new_samples, :num_columns] = np.nan  

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_process_lines = max ((toc - tic), self.mtoc_process_lines)

    ########################################################################################
    ########################################################################################
    # Response Functions to User Interface Signals
    ########################################################################################
    ########################################################################################

    @pyqtSlot(list)
    def on_receivedLines(self, lines: list):
        """
        Decode/Parse a list of lines for data and add it to the circular buffer
        """

        if DEBUGCHART:
            tic = time.perf_counter()

        # Make a copy of the lines
        # lines_copy = [item[:] for item in lines]

        if self.textDataSeparator == 'No Labels (simple)':
            self.process_lines_simple(lines, encoding = self.encoding)

        elif self.textDataSeparator == 'With [Label:]':
            self.process_lines(lines, encoding = self.encoding)

        else:
            self.handle_log(
                logging.WARNING,
                f"[{self.thread_id}]: Data separator {repr(self.textDataSeparator)} not available."
            )


        if DEBUGCHART:
            toc = time.perf_counter()
            self.handle_log(
                logging.INFO,
                f"[{self.thread_id}]: Data points received: parsing took {1000 * (toc - tic)} ms"
            )        

    @pyqtSlot(list)
    def on_receivedData(self, byte_array: bytes):
        pass

    @pyqtSlot()
    def on_changeDataSeparator(self):
        ''' user wants to change the data separator '''
        self.textDataSeparator = self.ui.comboBoxDropDown_DataSeparator.currentText()
        self.handle_log(
            logging.INFO, 
            f"[{self.thread_id}]: Data separator {self.textDataSeparator}"
        )
        self.ui.statusBar().showMessage('Data Separator changed.', 2000)            

    @pyqtSlot()
    def on_pushButton_ChartStartStop(self):
        """
        Start/Stop plotting

        Connect serial receiver new data received
        Start timer
        """
        if self.ui.pushButton_ChartStartStop.text() == "Start":
            # We want to start plotting
            if self.serialUI.textLineTerminator == "":
                self.handle_log(
                    logging.ERROR,
                    f"[{self.thread_id}]: Plotting of of raw data not yet supported"
                )
                return
            
            if not self.ChartTimer.isActive():
                for line in self.data_lines:
                    self.chartWidget.removeItem(line) 
                self.data_lines.clear()
                if self.legend is not None:
                    self.legend.clear()
                self.chartWidget.clear()

            self.plottingRunning.emit(True)
            self.ChartTimer.start()
            self.handle_log(
                logging.INFO,
                f"[{self.thread_id}]: Start plotting"
            )
            self.ui.statusBar().showMessage("Chart update started.", 2000)

        else:
            # We want to stop plotting
            self.ChartTimer.stop()
            self.plottingRunning.emit(False)
            self.handle_log(
                logging.INFO,
                f"[{self.thread_id}]: Stopped plotting"
            )
            self.ui.statusBar().showMessage("Chart update stopped.", 2000)

    @pyqtSlot()
    def on_pushButton_ChartClear(self):
        """
        Clear Plot

        Clear data buffer then update plot
        """
        # clear buffer
        self.buffer.clear()

        for line in self.data_lines:
            self.chartWidget.removeItem(line)
        self.data_lines.clear()

        if self.legend is not None:
            self.legend.clear()

        self.chartWidget.clear()

        self.updatePlot()

        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: Cleared plotted data."
        )
        self.ui.statusBar().showMessage("Chart cleared.", 2000)

    @pyqtSlot()
    def on_pushButton_ChartSave(self):
        """
        Save data into Text File
        """
        stdFileName = (
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
            + "/data.txt"
        )
        fname, _ = QFileDialog.getSaveFileName(
            self.ui, "Save as", stdFileName, "Text files (*.txt)"
        )
        np.savetxt(fname, self.buffer.data, delimiter=",")
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: Saved plotted data."
        )
        self.ui.statusBar().showMessage("Chart data saved.", 2000)

    @pyqtSlot()
    def on_pushButton_ChartSaveFigure(self):
        """
        Save plot figure into SVG file
        """

        stdFileName = (
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
            + "/chart.svg"
        )
        fname, _ = QFileDialog.getSaveFileName(
            self.ui, "Save as", stdFileName, "PNG files (*.png)"
        )

        if not fname:  # User canceled the dialog
            return
        
        was_running = self.ChartTimer.isActive()

        try:
            if was_running:
                self.ChartTimer.stop() # Can not update plot while its saved

            exporter = pg.exporters.ImageExporter(self.chartWidget.getPlotItem())
            exporter.export(fname)

        except Exception as e:
            self.handle_log(
                logging.ERROR,
                f"[{self.thread_id}]: Error saving chart."
            )
            self.ui.statusBar().showMessage(f"Error saving chart: {str(e)}", 3000)
            if was_running:
                self.ChartTimer.start()  # Ensure the timer restarts if something goes wrong

        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: Chart saved as {fname}."
        )
        self.ui.statusBar().showMessage(f"Chart saved as {fname}.", 2000)

        # Restart timer if it was previously running
        if was_running:
            self.ChartTimer.start()

    @pyqtSlot(int)
    def on_ZoomSliderChanged(self, value):
        """
        Serial Plotter Horizontal Slider Handling
        This sets the maximum number of points back in history shown on the plot

        Update the line edit box when the slider is moved
        This changes how far back in history we plot
        """
        new_value = int(clip_value(value, 16, MAX_ROWS))
        self.lineEdit.setText(str(new_value))
        self.maxPoints = new_value
        self.horizontalSlider.blockSignals(True)
        self.horizontalSlider.setValue(new_value)
        self.horizontalSlider.blockSignals(False)
        if DEBUGCHART:
            self.handle_log(
                logging.DEBUG,
                f"[{self.thread_id}]: Horizontal zoom set to {value}."
            )
        self.updatePlot()

    @pyqtSlot()
    def on_ZoomLineEditChanged(self):
        """
        Serial Plotter Horizontal Line Edit Handling
        Updates the slider and the history range when text is entered manually.
        """
        sender = self.sender() # obtain the name of the sender of the signal so we can access its text
        if sender is None:
            self.handle_log(logging.WARNING, f"[{self.thread_id}]: No sender found for Horizontal Line Edit change.")
            return

        try:
            value = int(sender.text().strip())  # Strip spaces to prevent errors
        except ValueError:
            self.handle_log(logging.WARNING, f"[{self.thread_id}]: Invalid input in Horizontal Line Edit.")
            return  # Exit without applying changes if input is invalid

        # Ensure value is within the allowed range
        value = clip_value(value, 16, MAX_ROWS)

        # Prevent signal loops
        sender.blockSignals(True)
        sender.setText(str(value))  # Update text in case it was out of bounds
        sender.blockSignals(False)

        self.horizontalSlider.blockSignals(True)
        self.horizontalSlider.setValue(value)
        self.horizontalSlider.blockSignals(False)

        self.maxPoints = value  # Update max points

        self.handle_log(
            logging.DEBUG,
            f"[{self.thread_id}]: Horizontal zoom line edit set to {value}."
        )

        self.updatePlot()


#####################################################################################
# Testing
#####################################################################################

if __name__ == "__main__":
    # not implemented
    pass
