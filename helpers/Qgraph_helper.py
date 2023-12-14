############################################################################################
# QT Chart Helper
############################################################################################
# Fall 2022: initial work
# ------------------------------------------------------------------------------------------
# Urs Utzinger
# University of Arizona 2023
############################################################################################

""" 
https://www.pythonguis.com/tutorials/embed-pyqtgraph-custom-widgets-qt-app/
https://www.pyqtgraph.org/
https://www.youtube.com/watch?v=oWERFvUVDTg&ab_channel=UpskillwithGeeksforGeeks
https://www.pythonguis.com/tutorials/plotting-pyqtgraph/
https://stackoverflow.com/questions/65332619/pyqtgraph-scrolling-plots-plot-in-chunks-show-only-latest-10s-samples-in-curre
https://github.com/pbmanis/EKGMonitor
""" 

import logging, time

from PyQt5.QtCore import QObject, QTimer, QThread, pyqtSlot, QStandardPaths
from PyQt5.QtWidgets import QFileDialog, QLineEdit, QSlider, QTabWidget, QGraphicsView, QVBoxLayout

# QT Graphing for chart plotting
import pyqtgraph as pg

# Numerical Math
import numpy as np

# Constants
########################################################################################
MAX_ROWS = 44100 # data history length
MAX_COLUMNS = 4 # max number of signal traces
UPDATE_INTERVAL = 100 # milliseconds, visualization does not improve with updates faster than 10 Hz
COLORS = ['green', 'red', 'blue', 'black'] # need to have MAX_COLUMNS colors

# Support Functions and Classes
########################################################################################

def clip_value(value, min_value, max_value):
    return max(min_value, min(value, max_value))

class CircularBuffer():
    '''
    This is a circular buffer to store numpy data.
    
    It is initialized based on MAX_ROWS and MAX_COLUMNS.
    You add data by pushing a numpy array to it. The width of the numpy array needs to match MAX_COLUMNS.
    You access the data by the data property. 
    It automatically rearranges adding and extracting data with wrapping around.
    '''    
    def __init__(self):
        ''' initialize the circular buffer '''
        self._data = np.full((MAX_ROWS, MAX_COLUMNS+1), np.nan)
        self._index = 0
        
    def push(self, data_array):
        ''' add new data to the circular buffer '''
        num_new_rows, num_new_cols = data_array.shape
        if num_new_cols != MAX_COLUMNS+1:
            raise ValueError("Data array must have {} columns".format(MAX_COLUMNS+1))
        end_index = (self._index + num_new_rows) % MAX_ROWS # where new data will be inserted
        if end_index < self._index:
            # wrapping is necessary when inserting new data
            self._data[self._index:MAX_ROWS] = data_array[:MAX_ROWS - self._index]
            self._data[:end_index] = data_array[MAX_ROWS - self._index:]
        else:
            # no wrapping necessary, new data fits into the buffer
            self._data[self._index:end_index] = data_array
                    
        self._index = end_index

    def clear(self):
        ''' set all buffer values to -inf '''
        self._data = np.full((MAX_ROWS, MAX_COLUMNS+1), np.nan)
    
    @property
    def data(self):
        ''' obtain the data from the buffer'''
        if self._index == 0:
            return self._data
        else:
            # rearrange the data so that the newest data is at the end
            # return np.vstack((self._data[self._index:], self._data[:self._index]))
            return np.roll(self._data, -self._index, axis=0)

############################################################################################
# QChart interaction with Graphical User Interface
############################################################################################
    
class QChartUI(QObject):
    """
    Chart Interface for QT
    
    The chart displays up MAX_COLUMNS (4) signals in a plot.
    The data is received from the serial port and organized into columns of a numpy array.
    The plot can be zoomed in by selecting how far back in time to display it.
    The horizontal axis is the sample number.
    The vertical axis is auto scaled to the max and minimum values of the data.

    Slots (functions available to respond to external signals)
        on_pushButton_Start
        on_pushButton_Stop
        on_pushButton_Clear
        on_pushButton_Save
        on_HorizontalSliderChanged(int)
        on_HorizontalLineEditChanged
        on_newLineReceived(bytes)
        on_newLinesReceived(list)
        
    Functions
        updatePlot()
    """
    
    # Signals
    ########################################################################################

    # No Signals, no worker all in the main thread
               
    def __init__(self, parent=None, ui=None, serialUI=None, serialWorker=None):
        # super().__init__()
        super(QChartUI, self).__init__(parent)

        if ui is None:
            self.logger.log(logging.ERROR, "[{}]: Need to have access to User Interface".format(int(QThread.currentThreadId())))
        self.ui = ui

        if serialUI is None:
            self.logger.log(logging.ERROR, "[{}]: Need to have access to Serial User Interface".format(int(QThread.currentThreadId())))
        self.serialUI = serialUI

        if serialWorker is None:
            self.logger.log(logging.ERROR, "[{}]: Need to have access to Serial Worker".format(int(QThread.currentThreadId())))
        self.serialWorker = serialWorker

        # Create the chart
        self.chartWidget = pg.PlotWidget()

        # Replace the GraphicsView widget in the User Interface (ui) with the pyqtgraph plot
        self.tabWidget = self.ui.findChild(QTabWidget, 'tabWidget_MainWindow')
        self.graphicsView = self.ui.findChild(QGraphicsView, 'chartView')
        self.tabLayout = QVBoxLayout(self.graphicsView)
        self.tabLayout.addWidget(self.chartWidget)
        
        # Setting the plotWidget features
        self.chartWidget.setBackground('w')
        self.chartWidget.showGrid(x=True, y=True)
        self.chartWidget.setLabel('left', 'Signal', units='V') # ESP ADC calibrates the reading in mV
        self.chartWidget.setLabel('bottom', 'Sample', units='')
        self.chartWidget.setTitle("Chart")
        self.chartWidget.setMouseEnabled(x=True, y=True) # allow to move and zoom in the plot window
                
        self.sample_number = 0  # A counter indicating current sample number which is also the x position in the plot
        self.pen = [pg.mkPen(color, width=2) for color in COLORS] # colors for the signal traces
        self.data_line = [self.chartWidget.plot([], [], pen=self.pen[i % len(self.pen)], name=str(i)) for i in range(MAX_COLUMNS)]
        
        self.maxPoints = 1024 # maximum number of points to show in a plot from now to the past
        
        self.buffer = CircularBuffer()
        
        self.textDataSeparator = b',' # comma
        
        # Initialize the plot axis ranges
        self.chartWidget.setXRange(0, self.maxPoints)
        self.chartWidget.setYRange(-1., 1.)

        # Initialize the horizontal slider
        self.horizontalSlider = self.ui.findChild(QSlider, "horizontalSlider_Zoom")
        self.horizontalSlider.setMinimum(16)
        self.horizontalSlider.setMaximum(MAX_ROWS)
        self.horizontalSlider.setValue(int(self.maxPoints))  
        self.lineEdit = self.ui.findChild(QLineEdit, "lineEdit_Horizontal")
        self.lineEdit.setText(str(self.maxPoints))
        
        self.logger = logging.getLogger("QChartUI_")           

        # Plot update frequency
        self.ChartTimer = QTimer()
        self.ChartTimer.setInterval(100)  # milliseconds, we can not see more than 50 Hz
        self.ChartTimer.timeout.connect(self.updatePlot)
                
        self.logger.log(logging.INFO, "[{}]: Initialized.".format(int(QThread.currentThreadId())))

    # Response Functions to User Interface Signals
    ########################################################################################

    def updatePlot(self):
        """
        Update the chart plot
        
        Do not plot data that is np.nan.
        Populate the data_line traces with the data.
        Set the horizontal range to show between newest data and maxPoints back in time.
        Set vertical range to min and max of data.
        """
        
        tic = time.perf_counter()
        data = self.buffer.data

        # where do we have valid data?
        have_data = ~np.isnan(data)
        max_y = -np.inf
        min_y =  np.inf
        max_x = -np.inf
        min_x =  np.inf
        for i in range(MAX_COLUMNS): # for each column
            have_column_data = have_data[:,i+1] 
            x = data[have_column_data,0] # extract the sample numbers
            y = data[have_column_data,i+1]/1000. # ESP ADC calibrates the reading to mV
            # max and min of data
            if x.size > 0: # avoid empty numpy array
                max_x = max([np.max(x), max_x]) # update max and min
                min_x = min([np.min(x), min_x])
            if y.size > 0: # avoid empty numpy array
                max_y = max([np.max(y), max_y]) # update max and min
                min_y = min([np.min(y), min_y])
            self.data_line[i].setData(x, y) # update the plot

        if min_x <= max_x: # we found valid data
            self.chartWidget.setXRange(max_x - self.maxPoints, max_x) # set the horizontal range
        if min_y <= max_y: 
            self.chartWidget.setYRange(min_y, max_y) # set the vertical range
        self.chartWidget.addLegend() # add a legend

        toc = time.perf_counter()            
        self.logger.log(logging.DEBUG, "[{}]: Plot updated in {} ms".format(int(QThread.currentThreadId()), 1000*(toc-tic)))

    @pyqtSlot()
    def on_changeDataSeparator(self):
        ''' user wants to change the data separator '''
        _tmp = self.ui.comboBoxDropDown_DataSeparator.currentText()
        if _tmp == "comma (,)":
            self.textDataSeparator = b','
        elif _tmp == "semicolon (;)":
            self.textDataSeparator = b';'
        elif _tmp == "point (.)":
            self.textDataSeparator = b'.'
        elif _tmp == "space (\\s)":
            self.textDataSeparator = b' '
        else:
            self.textDataSeparator = b','            
        self.logger.log(logging.INFO, "[{}]: Data separator {}".format(int(QThread.currentThreadId()), repr(self.textDataSeparator)))
        self.ui.statusBar().showMessage('Data Separator changed.', 2000)            

    @pyqtSlot(list)
    def on_newLinesReceived(self, lines: list):
        """
        Decode a received list of bytes lines and add data to the circular buffer
        """
        tic = time.perf_counter()
        # parse text into numbers, textDataSeparator is a byte string, filter removes empty strings and \n and \r
        # the filter is necessary if data is lost during serial tranmission and a partial end of line is received
        data = [list(map(float, filter(None, line.split(self.textDataSeparator)))) for line in lines if not (b'\n' in line or b'\r' in line)]
        #toc = time.perf_counter()
        #self.logger.log(logging.DEBUG, "[{}]: Lines to Data: took {} ms".format(int(QThread.currentThreadId()), 1000*(toc-tic))) # 200 microseconds

        try:
            # conversion to numpy if all lines have the same length
            data_array = np.array(data, dtype=float)
        except:
            # likely we have a list of lines with different lengths
            row_len = [len(data_rows) for data_rows in data]
            max_length = max(row_len)
            # Pad shorter lines with np.nan
            padded_data = [data_row + [np.nan]*(max_length - len(data_row)) for data_row in data]
            data_array = np.array(padded_data, dtype=float)

        num_rows, num_cols = data_array.shape
        sample_numbers = np.arange(self.sample_number, self.sample_number + num_rows)
        sample_numbers = sample_numbers.reshape(-1, 1)
        self.sample_number += num_rows
        right_pad = MAX_COLUMNS - num_cols
        if right_pad > 0:
            new_array = np.hstack([sample_numbers, data_array, np.full((num_rows, right_pad), np.nan)])
        else:
            new_array = np.hstack([sample_numbers, data_array[:, :MAX_COLUMNS]])

        self.buffer.push(new_array)
        
        toc = time.perf_counter()
        self.logger.log(logging.DEBUG, "[{}]: {} Data points received: took {} ms".format(int(QThread.currentThreadId()), num_rows, 1000*(toc-tic)))
        # 300 microseconds
        
    @pyqtSlot()
    def on_pushButton_StartStop(self):
        """
        Start/Stop plotting
        
        Connect serial receiver new data received
        Start timer
        """
        if self.ui.pushButton_ChartStartStop.text() == "Start":
            if self.serialUI.textLineTerminator == '':
                self.logger.log(logging.ERROR, "[{}]: Plotting of of raw data not yet supported".format(int(QThread.currentThreadId())))
                return
            # start plotting
            try:
                self.serialWorker.linesReceived.disconnect(self.serialUI.on_SerialReceivedLines) # turn off text display
                self.logger.log(logging.WARNING, "[{}]: Disconnected lines-received signal from serial text display.".format(int(QThread.currentThreadId())))
            except:
                pass
            self.serialWorker.linesReceived.connect(self.on_newLinesReceived) # enable plot data feed
            self.ChartTimer.start()
            if self.serialUI.receiverIsRunning == False:
                self.serialUI.startReceiverRequest.emit()
                self.serialUI.startThroughputRequest.emit()
            self.ui.pushButton_ChartStartStop.setText("Stop")
            self.logger.log(logging.INFO, "[{}]: Start plotting".format(int(QThread.currentThreadId())))
            self.ui.statusBar().showMessage('Chart update started.', 2000)            
        else:
            self.ChartTimer.stop()
            if self.serialUI.receiverIsRunning == True:
                self.serialUI.stopReceiverRequest.emit()
                self.serialUI.stopThroughputRequest.emit()
                self.ui.pushButton_ChartStartStop.setText("Start")
            try:
                self.serialWorker.linesReceived.disconnect(self.on_newLinesReceived)
            except:
                self.logger.log(logging.WARNING, "[{}]: lines-received signal was not connected the chart".format(int(QThread.currentThreadId())))
            self.logger.log(logging.INFO, "[{}]: Stopped plotting".format(int(QThread.currentThreadId())))
            self.ui.statusBar().showMessage('Chart update stopped.', 2000)            

    @pyqtSlot()
    def on_pushButton_Clear(self):
        """
        Clear Plot
        
        Clear data buffer then update plot
        """
        # clear plot
        self.buffer.clear()
        self.updatePlot()
        self.logger.log(logging.INFO, "[{}]: Cleared plotted data.".format(int(QThread.currentThreadId())))
        self.ui.statusBar().showMessage('Chart cleared.', 2000)            

    @pyqtSlot()
    def on_pushButton_Save(self):
        """ 
        Save data into Text File 
        """
        stdFileName = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) + "/data.txt"
        fname, _ = QFileDialog.getSaveFileName(self.ui, 'Save as', stdFileName, "Text files (*.txt)")
        np.savetxt(fname, self.buffer.data, delimiter=',')
        self.logger.log(logging.INFO, "[{}]: Saved plotted data.".format(int(QThread.currentThreadId())))
        self.ui.statusBar().showMessage('Chart data saved.', 2000)            

    @pyqtSlot(int)
    def on_HorizontalSliderChanged(self,value):
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
        self.logger.log(logging.DEBUG, "[{}]: Horizontal zoom set to {}.".format(int(QThread.currentThreadId()), int(value)))
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
        self.logger.log(logging.DEBUG, "[{}]: Horizontal zoom line edit set to {}.".format(int(QThread.currentThreadId()), value))
        self.updatePlot()  

#####################################################################################
# Testing
#####################################################################################

if __name__ == '__main__':
    # not implemented
    pass