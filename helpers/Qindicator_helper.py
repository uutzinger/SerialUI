############################################################################################
# QT Indicator Helper
############################################################################################
# Summer 2024: created
# ------------------------------------------------------------------------------------------
# Urs Utzinger
# University of Arizona 2024
############################################################################################

# NOT FINISHED
#   new line to data parser
#   single value to indicator
#   tripple value to indicator
#   quadrupple value to indicator
#   tripple value to 3D plot

# CHECK FIX THIS

############################################################################################
# Helpful readings:
# ------------------------------------------------------------------------------------------
#
############################################################################################

import logging, time

from PyQt5.QtCore import QObject, QTimer, QThread, pyqtSlot, QStandardPaths, QSettings, pyqtSignal
from PyQt5.QtWidgets import QFileDialog, QLineEdit, QSlider, QTabWidget, QGraphicsView, QVBoxLayout, QWidget, QPushButton
from PyQt5.QtGui import QBrush, QColor, QIcon, QVector3D

# QT Graphing for 3D display
import pyqtgraph as pg
import pyqtgraph.opengl as gl

# Numerical Math
import numpy as np

# Constants
########################################################################################
UPDATE_INTERVAL =   100 # milliseconds, visualization does not improve with updates faster than 10 Hz
COLORS = ['green', 'red', 'blue', 'black', 'magenta'] # need to have MAX_COLUMNS colors
# https://i.sstatic.net/lFZum.png

# Support Functions and Classes
########################################################################################

def clip_value(value, min_value, max_value):
    return max(min_value, min(value, max_value))

############################################################################################
# QChart interaction with Graphical User Interface
############################################################################################
    
class QIndicatorUI(QObject):
    """
    - Single Value Indicator Interface for QT
    - 3D GL plotting Interface for QT
    
    Displays received values in a value indicator.
    Displays up 4 vectors in a 3D plot.
 
    The data is received from the serial port.

    Slots (functions available to respond to external signals)
        on_pushButton_Start
        on_pushButton_Stop
        on_pushButton_Clear
        on_pushButton_Save
        on_dataSeparatorChanged
        on_newLinesReceived(list)
        
    Functions
        updateDisplay()
    """


    # Signals
    ########################################################################################

    # No Signals, no worker, all in the main thread
               
    def __init__(self, parent=None, ui=None, serialUI=None, serialWorker=None):
        # super().__init__()
        super(QIndicatorUI, self).__init__(parent)

        if ui is None:
            self.logger.log(logging.ERROR, "[{}]: Need to have access to User Interface".format(int(QThread.currentThreadId())))
        self.ui = ui

        if serialUI is None:
            self.logger.log(logging.ERROR, "[{}]: Need to have access to Serial User Interface".format(int(QThread.currentThreadId())))
        self.serialUI = serialUI

        if serialWorker is None:
            self.logger.log(logging.ERROR, "[{}]: Need to have access to Serial Worker".format(int(QThread.currentThreadId())))
        self.serialWorker = serialWorker

        ThreeD_1_range = 10
        ThreeD_2_range = 10
        ThreeD_3_range = 10
        ThreeD_4_range = 10

        # Buttons -------------------------------------------
        
        # START/STOP Button
        # CLEAR Button
        # SAVE Button
        # DATA SEPARATOR Drop Down        

        # Data Stores --------------------------------------
        #   for 3D plot 
        self.data_1 = np.zeros([1,3])
        self.data_2 = np.zeros([1,3])
        self.data_3 = np.zeros([1,3])
        self.data_4 = np.zeros([1,3])

        if USE3DPLOT is True:

            g_1 = gl.GLGridItem(antialias=True, glOptions='opaque')
            g_1.setSize(x=ThreeD_1_range*2, y=ThreeD_1_range*2)  # Set the grid size (xSpacing, ySpacing)
            g_1.setSpacing(x=ThreeD_1_range/10, y=ThreeD_1_range/10)  # Set the grid size (xSpacing, ySpacing)
            g_1.setColor((0, 0, 0, 255)) 
            self.ui.ThreeD_1.addItem(g_1)

            self.sp_1 = gl.GLScatterPlotItem()
            self.sp_1.setGLOptions('translucent')
            self.ui.ThreeD_1.addItem(self.sp_1)

            self.lp_1 = gl.GLLinePlotItem()
            self.lp_1.setGLOptions('translucent')
            self.ui.ThreeD_2.addItem(self.lp_1)

            self.ui.ThreeD_1.opts['center'] = QVector3D(0, 0, 0) 
            self.ui.ThreeD_1.opts['bgcolor'] = (255, 255, 255, 255)  # Set background color to white
            self.ui.ThreeD_1.opts['distance'] = 1.*ThreeD_1_range
            self.ui.ThreeD_1.opts['translucent'] = True
            self.ui.ThreeD_1.show()
            self.ui.ThreeD_1.update()

            g_2 = gl.GLGridItem(antialias=True, glOptions='opaque')
            g_2.setSize(x=ThreeD_2_range*2, y=ThreeD_2_range*2)  # Set the grid size (xSpacing, ySpacing)
            g_2.setSpacing(x=ThreeD_2_range/10, y=ThreeD_2_range/10)  # Set the grid size (xSpacing, ySpacing)
            g_2.setColor((0, 0, 0, 255)) 
            self.ui.ThreeD_1.addItem(g_2)

            self.sp_2 = gl.GLScatterPlotItem()
            self.sp_2.setGLOptions('translucent')
            self.ui.ThreeD_2.addItem(self.sp_2)

            self.lp_2 = gl.GLLinePlotItem()
            self.lp_2.setGLOptions('translucent')
            self.ui.ThreeD_2.addItem(self.lp_2)

            self.ui.ThreeD_2.opts['center'] = QVector3D(0, 0, 0) 
            self.ui.ThreeD_2.opts['bgcolor'] = (255, 255, 255, 255)  # Set background color to white
            self.ui.ThreeD_2.opts['distance'] = 1.*ThreeD_1_range
            self.ui.ThreeD_2.opts['translucent'] = True
            self.ui.ThreeD_2.show()
            self.ui.ThreeD_2.update()

            g_3 = gl.GLGridItem(antialias=True, glOptions='opaque')
            g_3.setSize(x=ThreeD_3_range*2, y=ThreeD_3_range*2)
            g_3.setSpacing(x=ThreeD_3_range/10, y=ThreeD_3_range/10)
            g_3.setColor((0, 0, 0, 255))
            self.ui.ThreeD_3.addItem(g_3)

            self.sp_3 = gl.GLScatterPlotItem()
            self.sp_3.setGLOptions('translucent')
            self.ui.ThreeD_3.addItem(self.sp_3)

            self.lp_3 = gl.GLLinePlotItem()
            self.lp_3.setGLOptions('translucent')
            self.ui.ThreeD_3.addItem(self.lp_3)

            self.ui.ThreeD_3.opts['center'] = QVector3D(0, 0, 0)
            self.ui.ThreeD_3.opts['bgcolor'] = (255, 255, 255, 255)
            self.ui.ThreeD_3.opts['distance'] = 1.*ThreeD_3_range
            self.ui.ThreeD_3.opts['translucent'] = True
            self.ui.ThreeD_3.show()
            self.ui.ThreeD_3.update()

            g_4 = gl.GLGridItem(antialias=True, glOptions='opaque')
            g_4.setSize(x=ThreeD_4_range*2, y=ThreeD_4_range*2)
            g_4.setSpacing(x=ThreeD_4_range/10, y=ThreeD_4_range/10)
            g_4.setColor((0, 0, 0, 255))
            self.ui.ThreeD_4.addItem(g_4)

            self.sp_4 = gl.GLScatterPlotItem()
            self.sp_4.setGLOptions('translucent')
            self.ui.ThreeD_4.addItem(self.sp_4)

            self.lp_4 = gl.GLLinePlotItem()
            self.lp_4.setGLOptions('translucent')
            self.ui.ThreeD_4.addItem(self.lp_4)

            self.ui.ThreeD_4.opts['center'] = QVector3D(0, 0, 0)
            self.ui.ThreeD_4.opts['bgcolor'] = (255, 255, 255, 255)
            self.ui.ThreeD_4.opts['distance'] = 1.*ThreeD_4_range
            self.ui.ThreeD_4.opts['translucent'] = True
            self.ui.ThreeD_4.show()
            self.ui.ThreeD_4.update()
        
        self.logger = logging.getLogger("QIndicatorUI_")

        self.textDataSeparator = b'\t'                                       # default data separator
        index = self.ui.comboBoxDropDown_DataSeparator.findText("tab (\\t)") # find default data separator in drop down
        self.ui.comboBoxDropDown_DataSeparator.setCurrentIndex(index)        # update data separator combobox
        self.logger.log(logging.DEBUG, "[{}]: data separator {}.".format(int(QThread.currentThreadId()), repr(self.textDataSeparator)))

        self.ui.pushButton_IndicatorStartStop.setText("Start")

        # Plot update frequency
        self.IndicatorTimer = QTimer()
        self.IndicatorTimer.setInterval(100)  # milliseconds, we can not see more than 50 Hz, 10Hz still looks smooth
        self.IndicatorTimer.timeout.connect(self.updatePlot)
                
        self.logger.log(logging.INFO, "[{}]: Initialized.".format(int(QThread.currentThreadId())))

    # Response Functions to User Interface Signals
    ########################################################################################

    def update_Indicators(self):
        """
        Update the indicator display with the latest data
        """
        pass

    def clear_Indicators(self):
        """
        Clear the indicator display
        """
        pass

    def update_3Ddata(self, readings: list):

        # expecting 4 sets of 3 values
            
        if USE3DPLOT == True:

            color = (1., 0., 0., 0.5)
            size = 10.

            if len(readings) >= 3:
                self.data3D_1 = np.concatenate((self.data3D_1, np.array([[readings[0],readings[1],readings[2]]])), axis=0)
                if len(self.data3D_1) > 2:
                    data3D_1_min = np.min(self.data3D_1[1:-1,:], axis=0)
                    data3D_1_max = np.max(self.data3D_1[1:-1,:], axis=0)

            if len(readings) >= 6:
                self.data3D_2 = np.concatenate((self.data3D_2, np.array([[readings[0],readings[1],readings[2]]])), axis=0)
                if len(self.data3D_2) > 2:
                    data3D_2_min = np.min(self.data3D_2[1:-1,:], axis=0)
                    data3D_2_max = np.max(self.data3D_2[1:-1,:], axis=0)

            if len(readings) >= 9:
                self.data3D_3 = np.concatenate((self.data3D_3, np.array([[readings[0],readings[1],readings[2]]])), axis=0)
                if len(self.data3D_3) > 2:
                    data3D_3_min = np.min(self.data3D_3[1:-1,:], axis=0)
                    data3D_3_max = np.max(self.data3D_3[1:-1,:], axis=0)

            if len(readings) >= 12:
                self.data3D_4 = np.concatenate((self.data3D_4, np.array([[readings[0],readings[1],readings[2]]])), axis=0)
                if len(self.data3D_4) > 2:
                    data3D_4_min = np.min(self.data3D_4[1:-1,:], axis=0)
                    data3D_4_max = np.max(self.data3D_4[1:-1,:], axis=0)

            n = self.data3D_1.shape[0]
            self.sp_1.setData(pos=self.data3D_1[1:n,:], color = color, size=size)
            self.lp_1.setData(pos=self.data3D_1[1:n,:], width=3.0, color=(0.5, 0.5, 0.5, 0.5))
            # Calculate the data range
            if len(self.data3D_1) > 2:
                data3D_1_range = np.linalg.norm(data3D_1_max - data3D_1_min)
                data3D_1_camera_distance = data3D_1_range
                self.ui.ThreeD_1.opts['distance'] = data3D_1_camera_distance
                data3D_1_center = data3D_1_min + (data3D_1_max - data3D_1_min)/2 
                self.ui.ThreeD_1.opts['center'] = QVector3D(data3D_1_center[0], data3D_1_center[1], data3D_1_center[2])
            self.ui.ThreeD_1.update()

            n = self.data3D_2.shape[0]
            self.sp_2.setData(pos=self.data3D_2[1:n,:], color = color, size=size)
            self.lp_2.setData(pos=self.data3D_2[1:n,:], width=3.0, color=(0.5, 0.5, 0.5, 0.5))
            # Calculate the data range
            if len(self.data3D_2) > 2:
                data3D_2_range = np.linalg.norm(data3D_2_max - data3D_2_min)
                data3D_2_camera_distance = data3D_2_range
                self.ui.ThreeD_2.opts['distance'] = data3D_2_camera_distance
                data3D_2_center = data3D_2_min + (data3D_2_max - data3D_2_min)/2 
                self.ui.ThreeD_2.opts['center'] = QVector3D(data3D_2_center[0], data3D_2_center[1], data3D_2_center[2])
            self.ui.ThreeD_2.update()

            n = self.data3D_3.shape[0]
            self.sp_3.setData(pos=self.data3D_3[1:n,:], color = color, size=size)
            self.lp_3.setData(pos=self.data3D_3[1:n,:], width=3.0, color=(0.5, 0.5, 0.5, 0.5))
            # Calculate the data range
            if len(self.data3D_3) > 2:
                data3D_3_range = np.linalg.norm(data3D_3_max - data3D_3_min)
                data3D_3_camera_distance = data3D_3_range
                self.ui.ThreeD_3.opts['distance'] = data3D_3_camera_distance
                data3D_3_center = data3D_3_min + (data3D_3_max - data3D_3_min)/2 
                self.ui.ThreeD_3.opts['center'] = QVector3D(data3D_3_center[0], data3D_3_center[1], data3D_3_center[2])
            self.ui.ThreeD_3.update()

            n = self.data3D_4.shape[0]
            self.sp_4.setData(pos=self.data3D_4[1:n,:], color = color, size=size)
            self.lp_4.setData(pos=self.data3D_4[1:n,:], width=3.0, color=(0.5, 0.5, 0.5, 0.5))
            # Calculate the data range
            if len(self.data3D_4) > 2:
                data3D_4_range = np.linalg.norm(data3D_4_max - data3D_4_min)
                data3D_4_camera_distance = data3D_4_range
                self.ui.ThreeD_4.opts['distance'] = data3D_4_camera_distance
                data3D_4_center = data3D_4_min + (data3D_4_max - data3D_4_min)/2 
                self.ui.ThreeD_4.opts['center'] = QVector3D(data3D_4_center[0], data3D_4_center[1], data3D_4_center[2])
            self.ui.ThreeD_4.update()

    def clear_3Ddata(self):
        if USE3DPLOT == True:
            self.data3D_1 = np.zeros([1,3])
            self.data3D_2 = np.zeros([1,3])
            self.data3D_3 = np.zeros([1,3])
            self.data3D_4 = np.zeros([1,3])
            self.sp_1.setData(pos=self.data3D_1, color = (1, 0, 0, 0.5), size=10)
            self.lp_1.setData(pos=self.data3D_1, color = (0.5, 0.5, 0.5, 0.5), width=3.0)
            self.sp_2.setData(pos=self.data3D_2, color = (1, 0, 0, 0.5), size=10)
            self.lp_2.setData(pos=self.data3D_2, color = (0.5, 0.5, 0.5, 0.5), width=3.0)
            self.sp_3.setData(pos=self.data3D_3, color = (1, 0, 0, 0.5), size=10)
            self.lp_3.setData(pos=self.data3D_3, color = (0.5, 0.5, 0.5, 0.5), width=3.0)
            self.sp_4.setData(pos=self.data3D_4, color = (1, 0, 0, 0.5), size=10)
            self.lp_4.setData(pos=self.data3D_4, color = (0.5, 0.5, 0.5, 0.5), width=3.0)
            self.ui.ThreeD_1.update()
            self.ui.ThreeD_2.update()
            self.ui.ThreeD_3.update()
            self.ui.ThreeD_4.update()

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
        elif _tmp == "tab (\\t)":
            self.textDataSeparator = b'\t'
        else:
            self.textDataSeparator = b','            
        self.logger.log(logging.INFO, "[{}]: Data separator {}".format(int(QThread.currentThreadId()), repr(self.textDataSeparator)))
        self.ui.statusBar().showMessage('Data Separator changed.', 2000)            

    @pyqtSlot(list)
    def on_newLinesReceived(self, lines: list):
        """
        Decode a received list of bytes lines and fromat for indicator display
    
        Single Values are epxected to have following format:  
          Legend:12.34
        Tripple Values are expected to have following format: 
          Legend:12.34 textDataSeparator 56.78 textDataSeparator 90.12
        Quadrupple Values are expected to have following format:
          Legend:12.34 textDataSeparator 56.78 textDataSeparator 90.12 textDataSeparator 34.56
        """
        tic = time.perf_counter()
        # parse text into numbers, textDataSeparator is a byte string, filter removes empty strings and \n and \r
        # the filter is necessary if data is lost during serial tranmission and a partial end of line is received
        # data = [list(map(float, filter(None, line.split(self.textDataSeparator)))) for line in lines if not (b'\n' in line or b'\r' in line)]
        parsed_data = []
        legends = []
        for line in lines:
            if not (b'\n' in line or b'\r' in line):
                items = line.split(self.textDataSeparator)
                data_row, legend_row = [], []
                for item in items:
                    parts = item.split(b':')
                    if len(parts) == 1:
                        try:
                            data_row.append(float(parts[0].strip()))
                        except:
                            self.logger.log(logging.DEBUG, "[{}]: Could not convert to float: {}".format(int(QThread.currentThreadId()), parts[0]))
                    elif len(parts) == 2:
                        legend, value = parts
                        legend_row.append(legend.strip().decode(self.serialUI.encoding))
                        try:
                            data_row.append(float(value.strip()))
                        except:
                            self.logger.log(logging.DEBUG, "[{}]: Could not convert to float: {}".format(int(QThread.currentThreadId()), value))
                    else:
                        # wrong separator
                        self.logger.log(logging.DEBUG, "[{}]: Wrong separator in line: {}".format(int(QThread.currentThreadId()), line))
                        self.ui.statusBar().showMessage('Change Data Separator!', 2000)
                if data_row:   parsed_data.append(data_row)
                if legend_row: legends.append(legend_row)
        toc = time.perf_counter()
        self.logger.log(logging.DEBUG, "[{}]: Lines to Data: took {} ms".format(int(QThread.currentThreadId()), 1000*(toc-tic))) # 200 microseconds

        try:
            data_array = np.array(parsed_data, dtype=float)
        except ValueError:
            max_length = max(len(row) for row in parsed_data)
            padded_data = [row + [np.nan] * (max_length - len(row)) for row in parsed_data]
            data_array = np.array(padded_data, dtype=float)

        num_rows, num_cols = data_array.shape
        sample_numbers = np.arange(self.sample_number, self.sample_number + num_rows).reshape(-1, 1)
        self.sample_number += num_rows
        right_pad = MAX_COLUMNS - num_cols
        if right_pad > 0:
            new_array = np.hstack([sample_numbers, data_array, np.full((num_rows, right_pad), np.nan)])
        else:
            new_array = np.hstack([sample_numbers, data_array[:, :MAX_COLUMNS]])

        self.buffer.push(new_array)
        self.legends = legends[-1]
        
        toc = time.perf_counter()
        self.logger.log(logging.DEBUG, "[{}]: {} Data points received: took {} ms".format(int(QThread.currentThreadId()), num_rows, 1000*(toc-tic)))
        
    @pyqtSlot()
    def on_pushButton_StartStop(self):
        """
        Start/Stop plotting
        
        Connect serial receiver new data received
        Start timer
        """
        if self.ui.pushButton_IndicatorStartStop.text() == "Start":
            # We want to start plotting
            if self.serialUI.textLineTerminator == '':
                self.logger.log(logging.ERROR, "[{}]: Indicating of of raw data not yet supported".format(int(QThread.currentThreadId())))
                return
            self.serialWorker.linesReceived.connect(self.on_newLinesReceived) # enable plot data feed
            self.IndicatorTimer.start()
            if self.serialUI.receiverIsRunning == False:
                self.serialUI.startReceiverRequest.emit()
                self.serialUI.startThroughputRequest.emit()
            self.ui.pushButton_IndicatorStartStop.setText("Stop")
            self.logger.log(logging.INFO, "[{}]: Start indicating".format(int(QThread.currentThreadId())))
            self.ui.statusBar().showMessage('Indicator update started.', 2000)            
        else:
            # We want to stop plotting
            self.IndicatorTimer.stop()
            self.ui.pushButton_IndicatorStartStop.setText("Start")
            try:
                self.serialWorker.linesReceived.disconnect(self.on_newLinesReceived)
            except:
                self.logger.log(logging.WARNING, "[{}]: lines-received signal was not connected the indicator".format(int(QThread.currentThreadId())))
            self.logger.log(logging.INFO, "[{}]: Stopped indicating".format(int(QThread.currentThreadId())))
            self.ui.statusBar().showMessage('Indicator update stopped.', 2000)            

    @pyqtSlot()
    def on_pushButton_Clear(self):
        """
        Clear Plot
        
        Clear data buffer then update plot
        """
        # clear plot
        # FIX THIS
        # self.buffer.clear()
        # self.updatePlot()
        self.logger.log(logging.INFO, "[{}]: Cleared plotted data.".format(int(QThread.currentThreadId())))
        self.ui.statusBar().showMessage('Chart cleared.', 2000)            

    @pyqtSlot()
    def on_pushButton_Save(self):
        """ 
        Save data into Text File 
        """
        stdFileName = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) + "/data.txt"
        fname, _ = QFileDialog.getSaveFileName(self.ui, 'Save as', stdFileName, "Text files (*.txt)")
        # FIX THIS
        # np.savetxt(fname, self.buffer.data, delimiter=',')
        self.logger.log(logging.INFO, "[{}]: Saved plotted data.".format(int(QThread.currentThreadId())))
        self.ui.statusBar().showMessage('Chart data saved.', 2000)            

#####################################################################################
# Testing
#####################################################################################

if __name__ == '__main__':
    # not implemented
    pass