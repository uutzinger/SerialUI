############################################################################################
# QT Chart Helper
############################################################################################
# December 2023: added chart plotting
# Summer 2024: 
#   added legend, fixed code issues
#   enabled flexible number of plot traces
#   added pyqt6 support
#
# This code is maintained by Urs Utzinger
############################################################################################

# General Imports
import logging, time
import re
from collections import defaultdict
from typing import List, Tuple

# QT Libraries
try:
    from PyQt6.QtCore import (
        QObject, QTimer, QThread, 
        pyqtSlot, QStandardPaths
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
        pyqtSlot, QStandardPaths
    )
    from PyQt5.QtWidgets import (
        QFileDialog, QLineEdit, QSlider,
        QTabWidget, QGraphicsView, QVBoxLayout,
    )
    from PyQt5.QtGui import QBrush, QColor
    hasQt6 = False

# QT Graphing for chart plotting
import pyqtgraph as pg

# Numerical Math
import numpy as np

try:
    from helpers.Qgraph_colors import color_names_sweet16 as COLORS
except:
    from Qgraph_colors import color_names_sweet16 as COLORS

# Constants
########################################################################################
MAX_ROWS = 44100         # data history length
MAX_COLS = len(COLORS)   # maximum number of columns [available colors]
#MAX_COLS = 16            # maximum number of columns (after this it begins to overflow off bottom of chart)
DEF_COLS = 2             # default number of columns
UPDATE_INTERVAL = 100    # milliseconds, visualization does not improve with updates faster than 10 Hz

########################################################################################
# Support Functions and Classes
########################################################################################

def clip_value(value, min_value, max_value):
    return max(min_value, min(value, max_value))

class CircularBuffer:
    '''
    This is a circular buffer to store numpy data.

    It adjusts the number of columns dynamically.
    It is initialized to the maximum number of rows and an initial number of columns.
    The buffer adjusts the columns based on incoming data, padding with NaNs as needed.
    '''    
    def __init__(self,max_rows, initial_columns):
        ''' Initialize the circular buffer '''
        self.max_rows = max_rows
        self.columns = initial_columns
        self._data = np.full((max_rows, initial_columns), np.nan)
        self._index = 0
        
    def push(self, data_array):
        ''' Add new data to the circular buffer '''
        num_new_rows, num_new_cols = data_array.shape

        # Adjust the number of columns of the buffer if necessary
        if num_new_cols > self.columns:
            new_data = np.full((self.max_rows, num_new_cols), np.nan)
            new_data[:, :self.columns] = self._data
            self._data = new_data
            self.columns = num_new_cols            
        elif num_new_cols < self.columns:
            if not np.isnan(self._data[:, num_new_cols:]).all():
                # Need to pad the incoming data to match existing columns
                padded_data_array = np.full((num_new_rows, self.columns), np.nan)
                padded_data_array[:, :num_new_cols] = data_array
                data_array = padded_data_array
            else:
                # Trim the buffer columns
                self._data = self._data[:, :num_new_cols]
                self.columns = num_new_cols

        # Insert data
        end_index = (self._index + num_new_rows) % self.max_rows # where new data will be inserted
        if end_index < self._index:
            # Wrapping is necessary when inserting new data
            self._data[self._index:self.max_rows] = data_array[:self.max_rows - self._index]
            self._data[:end_index] = data_array[self.max_rows - self._index:]
        else:
            # No wrapping necessary, new data fits into the buffer
            self._data[self._index:end_index] = data_array                    

        self._index = end_index

    def clear(self):
        ''' Set all buffer values to NaN '''
        self._data = np.full((self.max_rows, self.columns), np.nan)
    
    @property
    def data(self):
        ''' Obtain the data from the buffer '''
        if self._index == 0:
            return self._data
        else:
            # Rearrange the data so that the newest data is at the end
            return np.roll(self._data, -self._index, axis=0)


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
        on_pushButton_StartStop
        on_pushButton_Clear
        on_pushButton_Save
        on_HorizontalSliderChanged(int)
        on_HorizontalLineEditChanged
        on_newLinesReceived(list)
        on_changeDataSeparator

    Functions
        parse_lines()
        parse_lines_simple()
        updatePlot()
    """

    # Signals
    ########################################################################################
    # No Signals, no worker all in the main thread

    def __init__(self, parent=None, ui=None, serialUI=None, serialWorker=None):
        # super().__init__()
        super(QChartUI, self).__init__(parent)

        self.logger = logging.getLogger("QChartUI_")

        if ui is None:
            self.logger.log(
                logging.ERROR,
                "[{}]: Need to have access to User Interface".format(
                    int(QThread.currentThreadId())
                ),
            )
        self.ui = ui

        if serialUI is None:
            self.logger.log(
                logging.ERROR,
                "[{}]: Need to have access to Serial User Interface".format(
                    int(QThread.currentThreadId())
                ),
            )
        self.serialUI = serialUI

        if serialWorker is None:
            self.logger.log(
                logging.ERROR,
                "[{}]: Need to have access to Serial Worker".format(
                    int(QThread.currentThreadId())
                ),
            )
        self.serialWorker = serialWorker

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
        self.pen = [
            pg.mkPen(color, width=2) for color in COLORS
        ]  # colors for the signal traces
        self.data_line = [
            self.chartWidget.plot([], [], pen=self.pen[i % len(self.pen)], name=str(i))
            for i in range(DEF_COLS)
        ]

        # create a legend
        self.legend = self.chartWidget.addLegend()  # add a legend to the plot
        transparent_brush = QBrush(QColor(255, 255, 255, 0))  # set a transparent brush for the legend background
        self.legend.setBrush(transparent_brush)
        for line in self.data_line:
            self.legend.addItem(line, line.opts["name"])

        self.maxPoints = (1024) # maximum number of points to show in a plot from now to the past

        self.buffer = CircularBuffer(MAX_ROWS, MAX_COLS)
        self.legends = []

        # Initialize the plot axis ranges
        self.chartWidget.setXRange(0, self.maxPoints)
        self.chartWidget.setYRange(-1.0, 1.0)

        # Initialize the horizontal slider
        self.horizontalSlider = self.ui.findChild(QSlider, "horizontalSlider_Zoom")
        self.horizontalSlider.setMinimum(8)
        self.horizontalSlider.setMaximum(MAX_ROWS)
        self.horizontalSlider.setValue(int(self.maxPoints))
        self.lineEdit = self.ui.findChild(QLineEdit, "lineEdit_Horizontal")
        self.lineEdit.setText(str(self.maxPoints))
        
        self.logger = logging.getLogger("QChartUI_")

        self.textDataSeparator = 'No Labels (simple)'                                 # default data separator
        index = self.ui.comboBoxDropDown_DataSeparator.findText("No Labels (simple)") # find default data separator in drop down
        self.ui.comboBoxDropDown_DataSeparator.setCurrentIndex(index)                 # update data separator combobox
        self.logger.log(
            logging.DEBUG, 
            "[{}]: Data separator {}.".format(
                int(QThread.currentThreadId()), 
                repr(self.textDataSeparator)
            )
        )

        self.ui.pushButton_ChartStartStop.setText("Start")

        # Plot update frequency
        self.ChartTimer = QTimer()
        self.ChartTimer.setInterval(100)  # milliseconds, we can not see more than 50 Hz
        self.ChartTimer.timeout.connect(self.updatePlot)

        # Regular expression pattern to separate data values
        # This precompiles the text parsers
        self.labeled_data_re  = re.compile(r'\s+(?=\w+:)')   # separate labeled data into segments
        self.label_data_re    = re.compile(r'(\w+):\s*(.+)') # separate segments into label and data
        self.vector_scalar_re = re.compile(r'[;,]\s*')       # split on commas or semicolons

        # [[label:][{'\s' '\t' ''} value {',' ';', ''}]]
        # ----------------------------------------------
        # "label1: value1 label2: value2" to "label1: value1" and "label2: value2".
        # "label1: value1" to ("label1", "value1")
        # "value1, value2; value3" to ["value1", "value2", "value3"].

        self.logger.log(
            logging.INFO, 
            "[{}]: Initialized.".format(
                int(QThread.currentThreadId())
            )
        )

    # Utility functions
    ########################################################################################

    def parse_lines(self, lines: List[bytes]) -> List[dict]:
        """
        Takes a text line and parses it for labels, vectors, scalars, or unlabeled data.

        [[label:][{'\s' '\t' ''} value {',' ';', ''}]]
        The regular expressions are defined in the init function.

        A vector has a label and several values separated by commas or semicolons.
        """

        data_structure = []

        for line in lines:
            # First, extract potential labeled parts
            segments = self.labeled_data_re.split(line.decode(self.serialUI.encoding))
            scalar_count = 0
            vector_count = 0

            for segment in segments:
                if not segment:
                    continue
                match = self.label_data_re.match(segment)
                if match:
                    # labeled data
                    label, data = match.groups()
                    data_elements = self.vector_scalar_re.split(data)
                else:
                    # unlabeled data
                    data_elements = self.vector_scalar_re.split(segment)
                    label = None

                for data in data_elements:
                    try:
                        numbers = list(map(float, data.split()))
                    except ValueError:
                        continue  # Skip entries that cannot be converted to float
                    
                    if not numbers:
                        continue  # Skip empty data elements

                    if label:
                        header = f"{label}"
                    elif len(numbers) == 1:
                        scalar_count += 1
                        header = f"S{scalar_count}"
                    else:
                        vector_count += 1
                        header = f"V{vector_count}"

                    data_structure.append({'header': header, 'values': numbers, 'length': len(numbers)})

        return data_structure

    def parse_lines_simple(self, lines: List[bytes]) -> Tuple[List[np.ndarray], List[str]]:
        """
        Takes a text line and parses it.

        No headers are expected
        Each line is expected to have the same format.
        Scalars and vectors are separated by commas or semicolons.
        Vector elements are separated by whitespace.
        The regular expressions are defined in the init function.
        """

        component_lists = []    # List of lists, each sub-list will be converted to a numpy array
        header_list = []        # List of headers
        initialized = False     #

        for line in lines:
            # Decode the line from bytes to string
            decoded_line = line.decode(self.serialUI.encoding)

            # Split into major components (scalars or vector groups)
            components = self.vector_scalar_re.split(decoded_line)

            if not initialized:
                scalar_count=0
                vector_count=0
                # Initialize lists for each component
                for idx, component in enumerate(components):
                    component_lists.append([])
                    # Check if the component is a scalar or vector
                    values = component.strip().split()
                    if len(values) == 1:
                        scalar_count += 1
                        header_list.append(f"S{scalar_count}")
                    else:
                        vector_count
                        header_list.append(f"V{vector_count}")
                initialized = True

            for idx, component in enumerate(components):
                # Split potential vectors by whitespace and convert to float
                # values = [float(value) for value in component.strip().split() if value]
                values = []
                for value in component.strip().split():
                    try:
                        values.append(float(value))
                    except ValueError:
                        continue
                component_lists[idx].append(values)

        # Convert each component list to a numpy array
        data_array_list = [np.array(component) for component in component_lists]

        return data_array_list, header_list

    # Response Functions to User Interface Signals
    ########################################################################################

    def updatePlot(self):
        """
        Update the chart plot

        Plots data that is not np.nan.
        Populate the data_line traces with the data.
        Set the horizontal range to show newest data to go back in time maxPoints.
        Set vertical range to min and max of data.
        """

        tic = time.perf_counter()
        data = self.buffer.data
        num_rows, num_cols = data.shape

        self.legend.clear()                      # Clear the existing legend

        # Ensure there are enough data_line objects for each data column
        while len(self.data_line) < num_cols - 1:
            new_line_index = len(self.data_line)
            new_line = self.chartWidget.plot([], [], pen=self.pen[new_line_index % len(self.pen)], name=str(new_line_index))
            self.data_line.append(new_line)

        # Where do we have valid data?
        have_data = ~np.isnan(data)
        max_legends = len(self.legends)

        max_y = -np.inf
        min_y =  np.inf
        max_x = -np.inf
        min_x =  np.inf
        for i in range(num_cols-1):              # for each column
            have_column_data = have_data[:, i + 1]
            x = data[have_column_data, 0]        # extract the sample numbers
            y = data[have_column_data, i + 1]    # extract the data

            # max and min of data
            if x.size > 0:                       # avoid empty numpy array
                max_x = max([np.max(x), max_x])  # update max and min
                min_x = min([np.min(x), min_x])
            if y.size > 0:                       # avoid empty numpy array
                max_y = max([np.max(y), max_y])  # update max and min
                min_y = min([np.min(y), min_y])
            self.data_line[i].setData(x, y)      # update the plot

            # update the plot name
            if i < max_legends:
                self.data_line[i].opts["name"] = self.legends[i]
            else:
                self.data_line[i].opts["name"] = str(i)

            # update the legend
            self.legend.addItem(
                self.data_line[i], self.data_line[i].opts["name"]
            )  # Re-add the items with updated names to the legend

        # adjust range
        if min_x <= max_x:  # we found valid data
            self.chartWidget.setXRange(max_x - self.maxPoints, max_x)  # set the horizontal range
        if min_y <= max_y:
            self.chartWidget.setYRange(min_y, max_y)  # set the vertical range

        toc = time.perf_counter()
        self.logger.log(
            logging.DEBUG,
            "[{}]: Plot updated in {} ms".format(
                int(QThread.currentThreadId()), 1000 * (toc - tic)
            ),
        )

    @pyqtSlot()
    def on_changeDataSeparator(self):
        ''' user wants to change the data separator '''
        self.textDataSeparator = self.ui.comboBoxDropDown_DataSeparator.currentText()
        self.logger.log(logging.INFO, "[{}]: Data separator {}".format(int(QThread.currentThreadId()), self.textDataSeparator))
        self.ui.statusBar().showMessage('Data Separator changed.', 2000)            

    @pyqtSlot(list)
    def on_newLinesReceived(self, lines: list):
        """
        Decode a received list of bytes lines and add data to the circular buffer
        """
        tic = time.perf_counter()

        if self.textDataSeparator == 'No Labels (simple)':
            # Simple approach with no labels
            # ------------------------------

            # 1) Parse the data
            data_array_list, header_list = self.parse_lines_simple(lines)
    
            # 2) Stack the data and convert to numpy array, add sample numbers
            if data_array_list:
                # 2a) Stack horizontally
                data_array = np.hstack(data_array_list)

                # 2b) Add sample numbers as first column
                data_array_shape = data_array.shape
                if len(data_array_shape) == 2:
                    num_rows = data_array_shape[0]
                    sample_numbers = np.arange(self.sample_number, self.sample_number + num_rows).reshape(-1, 1)
                    self.sample_number += num_rows

                    data_array = np.hstack([sample_numbers, data_array])
                else:
                    data_array = None
            else:
                data_array = None

            # 3) Update headers
            if header_list and data_array_list:
                legends = []
                for idx, array in enumerate(data_array_list):
                    if array.ndim > 1:  # Ensure the array is multi-dimensional
                        num_cols = array.shape[1]
                    else:
                        num_cols = 1  # A 1D array is treated as having one column

                    if num_cols > 1:
                        header_labels = [f"{header_list[idx]}_{i+1}" for i in range(num_cols)]
                        legends.extend(header_labels)
                    else:
                        legends.append(header_list[idx])  
            else:
                legends = []
            
            # have numpy data_array and list of legends

        else: 
            # Complicated approach with labels
            # --------------------------------

            # 1) Parse the data
            parsed_data = self.parse_lines(lines)
            # takes about 0.35 ms for 10 lines of data

            # 2) Pad the data
            if self.textDataSeparator == 'No Labels (simple)':
            #    Determine the maximum number of data entries for each header
                header_analysis = defaultdict(lambda: {'count': 0, 'max_length': 0})
                for entry in parsed_data:
                    header = entry['header']
                    length = len(entry['values'])
                    header_analysis[header]['count'] += 1
                    header_analysis[header]['max_length'] = max(header_analysis[header]['max_length'], length)
                # no padding
                padded_parsed_results = parsed_data
            else:
            #    Determine the maximum number of data entries for each header
                header_analysis = defaultdict(lambda: {'count': 0, 'max_length': 0})
                for entry in parsed_data:
                    header = entry['header']
                    length = len(entry['values'])
                    header_analysis[header]['count'] += 1
                    header_analysis[header]['max_length'] = max(header_analysis[header]['max_length'], length)

                #    Find the maximum occurrence of any header
                max_header_occurrence = max(details['count'] for details in header_analysis.values())

                #    Pad the data to ensure all data the same length for each header
                padded_parsed_results = []

                for header, details in header_analysis.items():
                    # Existing entries for each header
                    existing_entries = [entry for entry in parsed_data if entry['header'] == header]
                    for entry in existing_entries:
                        max_length = details['max_length']
                        padded_values = entry['values'] + [float('nan')] * (max_length - len(entry['values']))
                        padded_parsed_results.append({'header': header, 'values': padded_values, 'length': max_length})

                    # Padding for headers to match max occurrence
                    padding_count = max_header_occurrence - details['count']
                    max_length = details['max_length']
                    padding_entry = {'header': header, 'values': [float('nan')] * max_length, 'length': max_length}
                    padded_parsed_results.extend([padding_entry] * padding_count)

            # takes about 0.175 ms for 10 lines of data

            # 3) Convert the parsed data to a numpy array

            data_array_list = []
            legends = []

            # Create numpy data array for each header
            for header, details in header_analysis.items():
                entries = [entry for entry in padded_parsed_results if entry['header'] == header]
                num_cols = details['max_length']

                # Prepare data for stacking
                data = np.array([entry['values'] for entry in entries], dtype=float)
                data_array_list.append(data)

                # Stack headers
                if num_cols > 1:
                    header_labels = [f"{header}_{i+1}" for i in range(num_cols)]
                    legends.extend(header_labels)
                else:
                    legends.append(header)  

            # Stack horizontally
            if data_array_list:
                # Stack arrays
                data_array = np.hstack(data_array_list)

                # Add sample numbers as first column
                data_array_shape = data_array.shape
                if len(data_array_shape) == 2:
                    num_rows, num_cols = data_array_shape
                    sample_numbers = np.arange(self.sample_number, self.sample_number + num_rows).reshape(-1, 1)
                    self.sample_number += num_rows

                    data_array = np.hstack([sample_numbers, data_array])

        self.buffer.push(data_array)
        self.legends = legends
        
        toc = time.perf_counter()
        self.logger.log(
            logging.DEBUG,
            "[{}]: {} Data points received: parsing took {} ms".format(
                int(QThread.currentThreadId()), num_rows, 1000 * (toc - tic)
            ),
        )

    @pyqtSlot()
    def on_pushButton_StartStop(self):
        """
        Start/Stop plotting

        Connect serial receiver new data received
        Start timer
        """
        if self.ui.pushButton_ChartStartStop.text() == "Start":
            # We want to start plotting
            if self.serialUI.textLineTerminator == "":
                self.logger.log(
                    logging.ERROR,
                    "[{}]: Plotting of of raw data not yet supported".format(
                        int(QThread.currentThreadId())
                    ),
                )
                return
            self.serialWorker.linesReceived.connect(
                self.on_newLinesReceived
            )  # enable plot data feed
            self.ChartTimer.start()
            if self.serialUI.receiverIsRunning == False:
                self.serialUI.startReceiverRequest.emit()
                self.serialUI.startThroughputRequest.emit()
            self.ui.pushButton_ChartStartStop.setText("Stop")
            self.logger.log(
                logging.INFO,
                "[{}]: Start plotting".format(int(QThread.currentThreadId())),
            )
            self.ui.statusBar().showMessage("Chart update started.", 2000)
        else:
            # We want to stop plotting
            self.ChartTimer.stop()
            self.ui.pushButton_ChartStartStop.setText("Start")
            try:
                self.serialWorker.linesReceived.disconnect(self.on_newLinesReceived)
            except:
                self.logger.log(
                    logging.WARNING,
                    "[{}]: lines-received signal was not connected the chart".format(
                        int(QThread.currentThreadId())
                    ),
                )
            self.logger.log(
                logging.INFO,
                "[{}]: Stopped plotting".format(
                    int(QThread.currentThreadId())
                ),
            )
            self.ui.statusBar().showMessage("Chart update stopped.", 2000)

    @pyqtSlot()
    def on_pushButton_Clear(self):
        """
        Clear Plot

        Clear data buffer then update plot
        """
        # clear plot
        self.buffer.clear()
        self.updatePlot()
        self.logger.log(
            logging.INFO,
            "[{}]: Cleared plotted data.".format(int(QThread.currentThreadId())),
        )
        self.ui.statusBar().showMessage("Chart cleared.", 2000)

    @pyqtSlot()
    def on_pushButton_Save(self):
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
        self.logger.log(
            logging.INFO,
            "[{}]: Saved plotted data.".format(int(QThread.currentThreadId())),
        )
        self.ui.statusBar().showMessage("Chart data saved.", 2000)

    @pyqtSlot(int)
    def on_HorizontalSliderChanged(self, value):
        """
        Serial Plotter Horizontal Slider Handling
        This sets the maximum number of points back in history shown on the plot

        Update the line edit box when the slider is moved
        This changes how far back in history we plot
        """
        value = clip_value(value, 16, MAX_ROWS)
        self.lineEdit.setText(str(int(value)))
        self.maxPoints = int(value)
        self.horizontalSlider.blockSignals(True)
        self.horizontalSlider.setValue(int(value))
        self.horizontalSlider.blockSignals(False)
        self.logger.log(
            logging.DEBUG,
            "[{}]: Horizontal zoom set to {}.".format(
                int(QThread.currentThreadId()), int(value)
            ),
        )
        self.updatePlot()

    @pyqtSlot()
    def on_HorizontalLineEditChanged(self):
        """
        Serial Plotter Horizontal Line Edit Handling
        Same as above but entering the number manually

        When text is entered manually into the horizontal edit field,
          update the slider and update the history range
        """
        sender = self.sender()
        value = int(sender.text())
        value = clip_value(value, 16, MAX_ROWS)
        self.horizontalSlider.blockSignals(True)
        self.horizontalSlider.setValue(int(value))
        self.horizontalSlider.blockSignals(False)
        self.maxPoints = int(value)
        self.logger.log(
            logging.DEBUG,
            "[{}]: Horizontal zoom line edit set to {}.".format(
                int(QThread.currentThreadId()), value
            ),
        )
        self.updatePlot()

#####################################################################################
# Testing
#####################################################################################

if __name__ == "__main__":
    # not implemented
    pass
