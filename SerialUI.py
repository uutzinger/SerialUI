#!/usr/bin/env python3
#############################################################################################################################################
# Serial Communication GUI
# ========================
#
# - Provides serial interface to send and receive text to/from serial port.
# - Plots of data on chart with zoom, save and clear.
# - Future release will include option for displaying data in indicators and 3D vector plots.
#
# This code is maintained by Urs Utzinger
#############################################################################################################################################

########################################################################################
# Debug and Profiling
DEBUGRECEIVER = False # enable/disable low level serial debugging
PROFILEME     = True # enable/disable profiling

# Constants
########################################################################################
USE3DPLOT     = False

import logging
DEBUG_LEVEL   = logging.INFO
# logging level and priority
# CRITICAL  50
# ERROR     40
# WARNING   30
# INFO      20
# DEBUG     10
# NOTSET     0

VERSION       = "1.1.1"
AUTHOR        = "Urs Utzinger"
DATE          = "2025, April"
#############################################################################################################################################

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Basic libraries
import sys
import os
import time
import textwrap
from markdown import markdown
from datetime import datetime

# QT imports, QT5 or QT6
try:
    from PyQt6 import QtCore, QtWidgets, QtGui, uic
    from PyQt6.QtCore import QThread, QTimer, QEventLoop, pyqtSlot
    from PyQt6.QtWidgets import (
        QMainWindow, QLineEdit, QSlider, 
        QMessageBox, QDialog, QVBoxLayout, 
        QTextEdit, QTabWidget, QWidget, QShortcut
    )
    from PyQt6.QtGui import QIcon
    hasQt6 = True
except:
    from PyQt5 import QtCore, QtWidgets, QtGui, uic
    from PyQt5.QtCore import QThread, QTimer, QEventLoop, pyqtSlot
    from PyQt5.QtWidgets import (
        QMainWindow, QLineEdit, QSlider, 
        QMessageBox, QDialog, QVBoxLayout, 
        QTextEdit, QTabWidget, QWidget, QShortcut
    )
    from PyQt5.QtGui import QIcon
    hasQt6 = False

# Custom program specific imports
from helpers.Qserial_helper   import QSerial, QSerialUI, USBMonitorWorker, MAX_TEXTBROWSER_LENGTH
from helpers.Qgraph_helper    import QChartUI, MAX_ROWS
from helpers.Codec_helper     import BinaryStreamProcessor

# Deal with high resolution displays
if not hasQt6:
    if hasattr(QtCore.Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(QtCore.Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

#############################################################################################################################################
#
# Main Window
#
#    This is the Viewer of the Model - View - Controller (MVC) architecture.
#
#############################################################################################################################################
#############################################################################################################################################

class mainWindow(QMainWindow):
    """
    Create the main window that stores all of the widgets necessary for the application.

    QSerial:
    Create serial worker and move it to separate thread.

    Serial Plotter:
    Create chart user interface object.
    """

    mtocRequest = QtCore.pyqtSignal()

    # ----------------------------------------------------------------------------------------------------------------------
    # Initialize
    # ----------------------------------------------------------------------------------------------------------------------

    def __init__(self, parent=None, logger=None):
        """
        Initialize the components of the main window.
        This will create the connections between slots and signals in both directions.

        Serial:
        Create serial worker and move it to separate thread.

        Serial Plotter:
        Create chart user interface object.
        """
        super(mainWindow, self).__init__(parent)  # parent constructor
        # super().__init__()

        if logger is None:
            self.logger = logging.getLogger("QMain")
        else:
            self.logger = logger
        
        main_dir = os.path.dirname(os.path.abspath(__file__))

        self.instance_name = self.objectName() if self.objectName() else self.__class__.__name__

        self.isDisplaying = False
        self.isPlotting   = False

       # Stream Processors
        self.binaryStream  = BinaryStreamProcessor(eop=b'\x00', logger = self.logger)

        # ----------------------------------------------------------------------------------------------------------------------
        # User Interface
        # ----------------------------------------------------------------------------------------------------------------------
        self.ui = uic.loadUi("assets/serialUI.ui", self)
        icon_path = os.path.join(main_dir, "assets", "serial_48.png")
        window_icon = QIcon(icon_path)
        self.setWindowIcon(QIcon(window_icon))
        self.setWindowTitle("Serial GUI")

        # Find the tabs and connect to tab change
        # ----------------------------------------------------------------------------------------------------------------------
        self.tabs: QTabWidget = self.findChild(QTabWidget, "tabWidget_MainWindow")
        self.tabs.currentChanged.connect(self.on_tab_change)

        # 3D plot windows and indicator tab
        # ----------------------------------------------------------------------------------------------------------------------
        # for now disable the indicator page
        indicator_page: QWidget = self.tabs.findChild(QWidget, 'Indicator')
        if indicator_page is not None:
            idx = self.tabs.indexOf(indicator_page)
            if idx != -1:
                self.tabs.setTabVisible(idx, False)

        if USE3DPLOT ==  True:
            self.ui.ThreeD_1.setEnabled(True)
            self.ui.ThreeD_2.setEnabled(True)
            self.ui.ThreeD_3.setEnabled(True)
            self.ui.ThreeD_4.setEnabled(True)
        else:
            self.ui.ThreeD_1.setEnabled(False)
            self.ui.ThreeD_2.setEnabled(False)
            self.ui.ThreeD_3.setEnabled(False)
            self.ui.ThreeD_4.setEnabled(False)

        # Configure Drop Down Menus
        # ----------------------------------------------------------------------------------------------------------------------

        # Find the index of "none"
        idx = self.ui.comboBoxDropDown_LineTermination.findText("none")
        if idx != -1:
            self.ui.comboBoxDropDown_LineTermination.setCurrentIndex(idx)
        self.textLineTerminator = b""

        # Find the index of "none"
        idx = self.ui.comboBoxDropDown_DataSeparator.findText("No Labels (simple)")
        if idx != -1:
            self.ui.comboBoxDropDown_DataSeparator.setCurrentIndex(idx)
        self.textDataSeparator = 'No Labels (simple)'  

        # Configure the Buttons
        # ----------------------------------------------------------------------------------------------------------------------
        self.ui.pushButton_SerialStartStop.setText("Start")
        self.ui.pushButton_SerialOpenClose.setText("Open")
        self.ui.pushButton_ChartStartStop.setText("Start")

        self.ui.pushButton_SerialScan.setEnabled(True)
        self.ui.pushButton_SerialOpenClose.setEnabled(False)
        self.ui.pushButton_SerialStartStop.setEnabled(False)
        self.ui.pushButton_SendFile.setEnabled(False)
        self.ui.pushButton_SerialClearOutput.setEnabled(True)
        self.ui.pushButton_SerialSave.setEnabled(True)
        self.ui.pushButton_SerialOpenClose.setEnabled(False)
        self.ui.pushButton_ChartStartStop.setEnabled(False)
        self.ui.pushButton_ChartClear.setEnabled(True)
        self.ui.pushButton_ChartSave.setEnabled(True)
        self.ui.pushButton_ChartSaveFigure.setEnabled(True)
        self.ui.pushButton_ToggleDTR.setEnabled(False)
        self.ui.pushButton_ResetESP.setEnabled(False)

        self.logger.log(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: User Interface buttons initialized."
        )

        #----------------------------------------------------------------------------------------------------------------------
        # Serial Worker & Thread
        # ----------------------------------------------------------------------------------------------------------------------

        # Serial Thread
        self.serialWorkerThread = QThread()                                                             # create QThread object
        
        # Create serial worker
        self.serialWorker = QSerial()                                                                   # create serial worker object

        # Create user interface hook for serial
        self.serialUI = QSerialUI(ui=self.ui, worker=self.serialWorker, logger=self.logger)             # create serial user interface object

        # Serial Worker
        # -----------------------------
        self.serialWorker.moveToThread(self.serialWorkerThread)  # move worker to thread

        # Connect worker / thread finished
        self.serialWorker.finished.connect(                 self.serialWorkerThread.quit)               # if worker emits finished quite worker thread
        self.serialWorker.finished.connect(                 self.serialWorker.deleteLater)              # delete worker at some time
        self.serialWorkerThread.finished.connect(           self.serialWorkerThread.deleteLater)        # delete thread at some time

        # Signals from mainWindow to Serial Worker
        # ---------------------------------------
        self.mtocRequest.connect(                           self.serialWorker.handle_mtoc)              # connect mtoc request to worker

        # Signals from Serial Worker to Serial-UI
        # ---------------------------------------
        self.serialWorker.newPortListReady.connect(         self.serialUI.on_newPortListReady)          # connect new port list to its ready signal
        self.serialWorker.newBaudListReady.connect(         self.serialUI.on_newBaudListReady)          # connect new baud list to its ready signal
        self.serialWorker.serialStatusReady.connect(        self.serialUI.on_serialStatusReady)         # connect display serial status to ready signal
        self.serialWorker.throughputReady.connect(          self.serialUI.on_throughputReady)           # connect display throughput status
        self.serialWorker.serialWorkerStateChanged.connect( self.serialUI.on_serialWorkerStateChanged)  # mirror serial worker state to serial UI
        self.serialWorker.logSignal.connect(                self.serialUI.on_logSignal)                 # connect log messages to BLE UI

        # Signals from Serial-UI to Serial Worker
        # ---------------------------------------
        self.serialUI.changePortRequest.connect(            self.serialWorker.on_changePortRequest)     # connect changing port
        self.serialUI.closePortRequest.connect(             self.serialWorker.on_closePortRequest)      # connect close port
        self.serialUI.changeBaudRequest.connect(            self.serialWorker.on_changeBaudRateRequest) # connect changing baud rate
        self.serialUI.changeLineTerminationRequest.connect( self.serialWorker.on_changeLineTerminationRequest)  # connect changing line termination
        self.serialUI.scanPortsRequest.connect(             self.serialWorker.on_scanPortsRequest)      # connect request to scan ports
        self.serialUI.scanBaudRatesRequest.connect(         self.serialWorker.on_scanBaudRatesRequest)  # connect request to scan baud rates
        self.serialUI.serialStatusRequest.connect(          self.serialWorker.on_serialStatusRequest)   # connect request for serial status

        self.serialUI.sendFileRequest.connect(              self.serialWorker.on_sendFileRequest)       # send file to serial port
        self.serialUI.sendTextRequest.connect(              self.serialWorker.on_sendTextRequest)       # connect sending text
        self.serialUI.sendLineRequest.connect(              self.serialWorker.on_sendLineRequest)       # connect sending line of text
        self.serialUI.sendLinesRequest.connect(             self.serialWorker.on_sendLinesRequest)      # connect sending lines of text

        self.serialUI.espResetRequest.connect(              self.serialWorker.on_resetESPRequest)       # connect reset ESP32
        self.serialUI.toggleDTRRequest.connect(             self.serialWorker.on_toggleDTRRequest)      # connect toggle DTR

        self.serialUI.setupReceiverRequest.connect(         self.serialWorker.on_setupReceiverRequest)  # connect start receiver
        self.serialUI.startReceiverRequest.connect(         self.serialWorker.on_startReceiverRequest)  # connect start receiver
        self.serialUI.stopReceiverRequest.connect(          self.serialWorker.on_stopReceiverRequest)   # connect start receiver
        self.serialUI.finishWorkerRequest.connect(          self.serialWorker.on_stopWorkerRequest)     # connect finish request
        self.serialUI.startThroughputRequest.connect(       self.serialWorker.on_startThroughputRequest)# start throughput
        self.serialUI.stopThroughputRequest.connect(        self.serialWorker.on_stopThroughputRequest) # stop throughput
        
        self.serialWorkerThread.start()                                                                 # start thread 
        QTimer.singleShot(  0, lambda: self.serialUI.setupReceiverRequest.emit())                       # establishes serial port and its timers in new thread
        QTimer.singleShot( 50, lambda: self.serialUI.scanBaudRatesRequest.emit())                       # request to scan for baudrates
        QTimer.singleShot(100, lambda: self.serialUI.scanPortsRequest.emit())                           # request to scan for serial ports
        self.logger.log(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Serial Worker started."
        )

        #----------------------------------------------------------------------------------------------------------------------
        # Main Program
        # ----------------------------------------------------------------------------------------------------------------------

        # Signals from mainWindow to itself
        # ---------------------------------------
        self.mtocRequest.connect(                           self.handle_mtoc)                           # connect mtoc request to worker

        # Signals from mainWindow to SerialUI
        # ---------------------------------------
        self.mtocRequest.connect(                           self.serialUI.handle_mtoc)                  # connect mtoc request to worker

        # Signals from Serial-UI to Main
        # ------------------------------
        self.serialUI.displayingRunning.connect(            self.handle_SerialReceiverRunning)

        # Signals from User Interface to Serial-UI
        # ----------------------------------------

        # General Buttons
        self.ui.pushButton_SerialScan.clicked.connect(      self.serialUI.on_pushButton_SerialScan)         # Scan for ports
        self.ui.pushButton_SerialStartStop.clicked.connect( self.serialUI.on_pushButton_SerialStartStop)    # Start/Stop serial receive
        self.ui.pushButton_SendFile.clicked.connect(        self.serialUI.on_pushButton_SendFile)           # Send text from a file to serial port
        self.ui.pushButton_SerialClearOutput.clicked.connect(self.serialUI.on_pushButton_SerialClearOutput) # Clear serial receive window
        self.ui.pushButton_SerialSave.clicked.connect(      self.serialUI.on_pushButton_SerialSave)         # Save text from serial receive window
        self.ui.pushButton_SerialOpenClose.clicked.connect( self.serialUI.on_pushButton_SerialOpenClose)    # Open/Close serial port
        self.ui.pushButton_ToggleDTR.clicked.connect(lambda:self.serialUI.toggleDTRRequest.emit())          # Toggle DTR
        self.ui.pushButton_ResetESP.clicked.connect(lambda: self.serialUI.espResetRequest.emit())           # Reset ESP32

        # Text History
        self.horizontalSlider_History = self.ui.findChild(QSlider, "horizontalSlider_History")
        self.horizontalSlider_History.setMinimum(100)
        self.horizontalSlider_History.setMaximum(MAX_TEXTBROWSER_LENGTH)
        self.horizontalSlider_History.sliderReleased.connect( self.serialUI.on_HistorySliderChanged)

        self.lineEdit_History = self.ui.findChild(QLineEdit, "lineEdit_Vertical_History")
        self.lineEdit_History.returnPressed.connect(        self.serialUI.on_HistoryLineEditChanged)


        # Connect ComboBoxes
        self.ui.comboBoxDropDown_SerialPorts.currentIndexChanged.connect(    self.serialUI.on_comboBoxDropDown_SerialPorts) # user changed serial port
        self.ui.comboBoxDropDown_BaudRates.currentIndexChanged.connect(      self.serialUI.on_comboBoxDropDown_BaudRates)   # user changed baud rate
        self.ui.comboBoxDropDown_LineTermination.currentIndexChanged.connect(self.serialUI.on_comboBoxDropDown_LineTermination) # User changed line termination
        
        # User hit up/down arrow in serial lineEdit
        self.shortcutUpArrow   = QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Up),  self.ui.lineEdit_Text, self.serialUI.on_upArrowPressed)
        self.shortcutDownArrow = QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Down),self.ui.lineEdit_Text, self.serialUI.on_downArrowPressed)

        self.ui.lineEdit_Text.returnPressed.connect(                              self.serialUI.on_carriageReturnPressed)   # Send text as soon as enter key is pressed

        # Radio buttons
        self.ui.radioButton_SerialRecord.clicked.connect(                         self.serialUI.on_SerialRecord) # Record incoming data to file

        # Done with Serial
        self.logger.log(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Serial Terminal initialized."
        )

        # ----------------------------------------------------------------------------------------------------------------------
        # Serial Plotter
        # ----------------------------------------------------------------------------------------------------------------------
        # Create user interface hook for chart plotting
        self.chartUI = QChartUI(ui=self.ui, serialUI=self.serialUI, serialWorker=self.serialWorker)     # create chart user interface object

        # Signals from mainWindow to Chart-UI
        # ---------------------------------
        self.mtocRequest.connect(                           self.chartUI.handle_mtoc)                   # connect mtoc request to worker

        # Signals from Chart-UI to Main
        # ---------------------------------
        self.chartUI.plottingRunning.connect(               self.handle_SerialReceiverRunning)

        self.ui.pushButton_ChartStartStop.clicked.connect(  self.chartUI.on_pushButton_ChartStartStop)
        self.ui.pushButton_ChartClear.clicked.connect(      self.chartUI.on_pushButton_ChartClear)
        self.ui.pushButton_ChartSave.clicked.connect(       self.chartUI.on_pushButton_ChartSave)
        self.ui.pushButton_ChartSaveFigure.clicked.connect( self.chartUI.on_pushButton_ChartSaveFigure)

        self.ui.comboBoxDropDown_DataSeparator.currentIndexChanged.connect(self.chartUI.on_changeDataSeparator)

        # Horizontal Zoom
        self.horizontalSlider_Zoom = self.ui.findChild(QSlider, "horizontalSlider_Zoom")
        self.horizontalSlider_Zoom.setMinimum(8)
        self.horizontalSlider_Zoom.setMaximum(MAX_ROWS)
        self.horizontalSlider_Zoom.valueChanged.connect(    self.chartUI.on_ZoomSliderChanged)

        self.lineEdit_Zoom = self.ui.findChild(QLineEdit, "lineEdit_Horizontal_Zoom")
        self.lineEdit_Zoom.returnPressed.connect(           self.chartUI.on_ZoomLineEditChanged)

        # Done with Plotter
        self.logger.log(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Plotter initialized."
        )

        # ----------------------------------------------------------------------------------------------------------------------
        # Menu Bar
        # ----------------------------------------------------------------------------------------------------------------------
        # Connect the action_about action to the show_about_dialog slot
        self.ui.action_About.triggered.connect(self.show_about_dialog)
        self.ui.action_Help.triggered.connect( self.show_help_dialog)
        self.ui.action_Profile.triggered.connect( self.on_handle_mtoc)
        self.logger.log(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: User Interface Menu initialized."
        )
        
        # ----------------------------------------------------------------------------------------------------------------------
        # Status Bar
        # ----------------------------------------------------------------------------------------------------------------------
        self.statusTimer = QTimer(self)
        self.statusTimer.timeout.connect(self.on_resetStatusBar)
        self.statusTimer.start(10000)  # Trigger every 10 seconds
        self.logger.log(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Status Bar initialized."
        )
        
        # ----------------------------------------------------------------------------------------------------------------------
        # Display UI
        # ----------------------------------------------------------------------------------------------------------------------
        self.show()
        self.logger.log(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Displaying User Interface."
        )

        #----------------------------------------------------------------------------------------------------------------------
        # Check for USB device connect/disconnect
        #----------------------------------------------------------------------------------------------------------------------

        self.usbThread = QThread()
        self.usbWorker = USBMonitorWorker()
        self.usbWorker.moveToThread(self.usbThread)
        
        # Connect signals and slots
        self.usbThread.started.connect(   self.usbWorker.run)
        self.usbWorker.finished.connect(  self.usbThread.quit)           # if worker emits finished quite worker thread
        self.usbWorker.finished.connect(  self.usbWorker.deleteLater)    # delete worker at some time
        self.usbThread.finished.connect(  self.usbThread.deleteLater)    # delete thread at some time
        self.usbWorker.usb_event_detected.connect(self.serialUI.on_usb_event_detected)
        self.usbWorker.logSignal.connect( self.serialUI.on_logSignal)
        self.mtocRequest.connect(         self.usbWorker.handle_mtoc)    # connect mtoc request to worker

        # Start the USB monitor thread
        self.usbThread.start()

        # Done USB monitor
        self.logger.log(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: USB monitor started."
        )

    @pyqtSlot()
    def handle_mtoc(self) -> None:
        """Emit the mtoc signal with a function name and time in a single log call."""
        log_message = textwrap.dedent(f"""
            main Window
            =============================================================
            displaying is                    {"on" if self.isDisplaying else "off"}.
            plotting is                      {"on" if self.isPlotting else "off"}.
            serial worker is                 {"running" if self.serialUI.receiverIsRunning else "off"}.
        """)
        self.logger.log(logging.INFO, log_message)

    @pyqtSlot(int)
    def on_tab_change(self, index):
        """
        Respond to tab change event
        """
        tab_name = self.tabs.tabText(index)

        if tab_name == "Monitor":
            scrollbar = self.ui.plainTextEdit_Text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

        elif tab_name == "Plotter":
            pass

        elif tab_name == "Indicator":
            pass

        else:
            self.logger.log(
                logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: unknown tab name: {tab_name}"
            )

    @pyqtSlot(bool)
    def handle_SerialReceiverRunning(self, runIt):
        """
        Handle wether we need the serial receiver to run.
        
        When text display is requested we connect the signals from the serial worker to the display function
        When charting is requested, we connect the signals from the serial worker to the charting function
        
        When either displaying or charting is requested we start the serial text receiver and the throughput calculator

        If neither of them is requested we stop the serial text receiver and the throughput calculator
        """

        sender = self.sender()  # Get the sender object
        if DEBUGRECEIVER:
            self.logger.log(
                logging.DEBUG,
                f"[{self.instance_name[:15]:<15}]: handle_SerialReceiverRunning called by {sender} at {time.perf_counter()}."
            )

        # Plotting --------------------------------------
        if sender == self.chartUI:
            if runIt and not self.isPlotting:
                # Start plotting data
                try:
                    self.serialWorker.receivedLines.connect(        self.chartUI.on_receivedLines) # connect chart display to serial receiver signal
                  # self.serialWorker.receivedData.connect(         self.chartUI.on_receivedData)  # connect chart display to serial receiver signal
                    self.ui.pushButton_ChartStartStop.setText("Stop")
                    self.isPlotting = runIt
                    if DEBUGRECEIVER:
                        self.logger.log(
                            logging.DEBUG,
                            f"[{self.instance_name[:15]:<15}]: connected signals for charting at {time.perf_counter()}."
                        )
                except:
                    self.logger.log(
                        logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: connect to signals for charting failed."
                    )
            elif not runIt and self.isPlotting:
                # Stop plotting data
                try:
                    self.serialWorker.receivedLines.disconnect( self.chartUI.on_receivedLines) # disconnect chart display to serial receiver signal
                  # This will be needed once we have a binary stream processor for data reception 
                  # self.serialWorker.receivedData.disconnect(  self.chartUI.on_receivedData)  # disconnect chart display to serial receiver signal
                    self.ui.pushButton_ChartStartStop.setText("Start")
                    self.isPlotting = runIt
                    if DEBUGRECEIVER:
                        self.logger.log(
                            logging.DEBUG,
                            f"[{self.instance_name[:15]:<15}]: disconnected signals for charting at {time.perf_counter()}."
                        )
                except:
                    self.logger.log(
                        logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: disconnect to signals for charting failed."
                    )
            else:
                self.loggler.log(
                    logging.WARNING,
                    f"[{self.instance_name[:15]:<15}]: should not end up here when starting/stopping charting."
                )
 
        # Displaying --------------------------------------
        elif sender == self.serialUI:
            if runIt and not self.isDisplaying:
                # Start displaying data in serial terminal
                try:
                    self.serialWorker.receivedLines.connect(    self.serialUI.on_receivedLines) # connect text display to serial receiver signal
                    self.serialWorker.receivedData.connect(     self.serialUI.on_receivedData)  # connect text display to serial receiver signal
                    self.ui.pushButton_SerialStartStop.setText("Stop")
                    self.isDisplaying = runIt
                    if DEBUGRECEIVER:
                        self.logger.log(
                            logging.DEBUG,
                            f"[{self.instance_name[:15]:<15}]: connected signals for text displaying at {time.perf_counter()}."
                        )
                except:
                    self.logger.log(
                        logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: connect to signals for text displaying failed."
                    )
            elif not runIt and self.isDisplaying:
                # Stop displaying data in serial terminal
                try:
                    self.serialWorker.receivedLines.disconnect( self.serialUI.on_receivedLines) # disconnect text display to serial receiver signal
                    self.serialWorker.receivedData.disconnect(  self.serialUI.on_receivedData)  # disconnect text display to serial receiver signal
                    self.ui.pushButton_SerialStartStop.setText("Start")
                    self.isDisplaying = runIt
                    if DEBUGRECEIVER:
                        self.logger.log(
                            logging.DEBUG,
                            f"[{self.instance_name[:15]:<15}]: disconnected signals for text displaying at {time.perf_counter()}."
                        )
                except:
                    self.logger.log(
                        logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: disconnect to signals for text displaying failed."
                    )
            else:
                self.logger.log(
                    logging.WARNING,
                    f"[{self.instance_name[:15]:<15}]: should not end up here when starting/stopping text displaying."
                )

        else:
            # Signal should not come from any widget other than SerialUI or ChartUI
            self.logger.log(
                logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: should not end up here, neither serialUI nor chartUI emitted the signal."
            )

        # Start or Stop the serial receiver ---------------
        #   If we neither plot nor display incoming data we dont need to run the serial worker
        if not (self.isPlotting or self.isDisplaying):
            # We are neither plotting nor displaying data, therefore we want to stop the serial worker        
            if self.serialUI.receiverIsRunning:
                QTimer.singleShot( 0,lambda: self.serialUI.stopReceiverRequest.emit())   # emit signal to finish worker
                QTimer.singleShot(50,lambda: self.serialUI.stopThroughputRequest.emit()) # finish throughput calc
                if DEBUGRECEIVER:
                    self.logger.log(
                        logging.DEBUG,
                        f"[{self.instance_name[:15]:<15}]: stopped receiver as it is not needed {time.perf_counter()}."
                    )
        else:
            # We are plotting or displaying data and we want to run the serial worker and throughput display
            if not self.serialUI.receiverIsRunning:
                QTimer.singleShot(0, lambda: self.serialUI.startReceiverRequest.emit())
                QTimer.singleShot(50,lambda: self.serialUI.startThroughputRequest.emit())
                if DEBUGRECEIVER:
                    self.logger.log(
                        logging.DEBUG,
                        f"[{self.instance_name[:15]:<15}]: started receiver at {time.perf_counter()}."
                    )

    @pyqtSlot()
    def on_resetStatusBar(self):
        now = datetime.now()
        formatted_date_time = now.strftime("%Y-%m-%d %H:%M")
        self.ui.statusbar.showMessage("Serial User Interface. " + formatted_date_time)

    @pyqtSlot()
    def show_about_dialog(self):
        # Information to be displayed
        info_text = "Serial Terminal & Plotter\nVersion: {}\nAuthor: {}\n{}".format(VERSION, AUTHOR, DATE)
        # Create and display the MessageBox
        QMessageBox.about(self, "About Program", info_text) # Create and display the MessageBox
        self.show()

    @pyqtSlot()
    def show_help_dialog(self):
        # Load Markdown content from readme file
        with open("README.md", "r") as file:
            markdown_content = file.read()
        html_content = markdown(markdown_content)

        html_with_style = f"""
        <style>
            body {{ font-size: 16px; }}
            h1 {{ font-size: 24px; }}
            h2 {{ font-size: 20px; }}
            h3 {{ font-size: 18px; font-style: italic; }}
            p  {{ font-size: 16px; }}
            li {{ font-size: 16px; }}
        </style>
        {html_content}
        """
        
        # Create a QDialog to display the readme content
        dialog = QDialog(self)
        dialog.setWindowTitle("Help")
        layout = QVBoxLayout(dialog)

        # Create a QTextEdit instance for displaying the HTML content
        text_edit = QTextEdit()
        text_edit.setHtml(html_with_style)
        text_edit.setReadOnly(True)  # Make the text edit read-only
        layout.addWidget(text_edit)

        dialog_width = 1024  # Example width
        dialog_height = 800  # Example height
        dialog.resize(dialog_width, dialog_height)

        # Show the dialog
        dialog.exec()

    @pyqtSlot()
    def on_handle_mtoc(self):
        self.mtocRequest.emit() 

    def closeEvent(self, event):
        """
        Respond to window close event.
        Close the serial port, stop the serial thread and the chart update timer.
        """
        self.serialUI.cleanup()  # close serial port and stop thread 
        self.chartUI.cleanup()  # stop the chart timer

        self.logger.log(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: finishing worker..."
        )

        if self.serialWorker:
            if self.serialUI:
                self.serialUI.finishWorkerRequest.emit()     # emit signal to finish worker

                if self.usbWorker:                           # stop the USB monitor thread
                    self.usbWorker.stop()
                    self.usbThread.quit()

                try:
                    loop = QEventLoop()                          # create event loop
                    self.serialWorker.finished.connect(loop.quit)                                            # connect the loop to finish signal
                    loop.exec()                              # wait until worker is finished
                except:
                    pass
            else:
                self.logger.log(
                    logging.ERROR,
                    f"[{self.instance_name[:15]:<15}]: serialUI not initialized."
                )

        else:
            self.logger.log(
                logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: serialWorker not initialized."
            )

        event.accept()  # accept the close event to proceed closing the application

    def wait_for_signal(self, signal) -> float:
        """Utility to wait until a signal is emitted."""
        tic = time.perf_counter()
        loop = QEventLoop()
        signal.connect(loop.quit)
        loop.exec()
        return time.perf_counter() - tic

#############################################################################################################################################
# Main 
#############################################################################################################################################

if __name__ == "__main__":
   
    logging.basicConfig(level=DEBUG_LEVEL)

    root_logger = logging.getLogger("SerialUI")
    current_level = root_logger.getEffectiveLevel()

    app = QtWidgets.QApplication(sys.argv)

    win = mainWindow(logger=root_logger)
    screen = app.primaryScreen()
    scalingX = screen.logicalDotsPerInchX() / 96.0
    scalingY = screen.logicalDotsPerInchY() / 96.0
    win.resize(int(1200 * scalingX), int(665 * scalingY))
    win.show()

    exit_code = app.exec()

    sys.exit(exit_code)
