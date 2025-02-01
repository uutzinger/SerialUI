#!/usr/bin/env python3
#############################################################################################################################################
# Serial Communication GUI
# ========================
#
# - Provides serial interface to send and receive text to/from serial port.
# - Plots of data on chart with zoom, save and clear.
#
# This code is maintained by Urs Utzinger
#############################################################################################################################################

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Basic libraries
import sys
import os
import logging
import time
from markdown import markdown
from datetime import datetime

# QT imports, QT5 or QT6
try:
    from PyQt6 import QtCore, QtWidgets, QtGui, uic
    from PyQt6.QtCore import QThread, QTimer, QEventLoop
    from PyQt6.QtWidgets import (
        QMainWindow, QLineEdit, QSlider, 
        QMessageBox, QDialog, QVBoxLayout, 
        QTextEdit, QTabWidget, QShortcut
    )
    from PyQt6.QtGui import QIcon, QKeySequence
    hasQt6 = True
except:
    from PyQt5 import QtCore, QtWidgets, QtGui, uic
    from PyQt5.QtCore import QThread, QTimer, QEventLoop, Qt
    from PyQt5.QtWidgets import (
        QMainWindow, QLineEdit, QSlider, 
        QMessageBox, QDialog, QVBoxLayout, 
        QTextEdit, QTabWidget, QShortcut
    )
    from PyQt5.QtGui import QIcon, QTextCursor, QPalette, QColor
    hasQt6 = False

# Custom program specific imports
from helpers.Qserial_helper     import QSerial, QSerialUI, USBMonitorWorker, QPlainTextEditExtended
from helpers.Qgraph_helper      import QChartUI, MAX_ROWS
from helpers.Codec_helper       import BinaryStreamProcessor


# Deal with high resolution displays
if not hasQt6:
    if hasattr(QtCore.Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(QtCore.Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

# Future release will include option for displaying data in indicators
#  and 3D vector plots.

########################################################################################
# Debug
DEBUGRECEIVER = False # enable/disable low level serial debugging
# try:
#     import debugpy
#     DEBUGPY_ENABLED = True
# except ImportError:
#     DEBUGPY_ENABLED = False

# Constants
########################################################################################
USE3DPLOT = False
DEBUG_LEVEL = logging.INFO
# logging level and priority
# CRITICAL  50
# ERROR     40
# WARNING   30
# INFO      20
# DEBUG     10
# NOTSET     0

#############################################################################################################################################
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
        self.tabs = self.findChild(QTabWidget, "tabWidget_MainWindow")
        self.tabs.currentChanged.connect(self.on_tab_change)

        # 3D plot windows
        # ----------------------------------------------------------------------------------------------------------------------

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

        #----------------------------------------------------------------------------------------------------------------------
        # Serial Worker & Thread
        # ----------------------------------------------------------------------------------------------------------------------

        # Serial Thread
        self.serialWorkerThread = QThread()                                                             # create QThread object
        self.serialWorkerThread.start()                                                                 # start thread which will start worker
        
        # Create serial worker
        self.serialWorker = QSerial()                                                                   # create serial worker object

        # Create user interface hook for serial
        self.serialUI = QSerialUI(ui=self.ui, worker=self.serialWorker, logger=self.logger)             # create serial user interface object

        # Connect worker / thread finished
        self.serialWorker.finished.connect(                 self.serialWorkerThread.quit)               # if worker emits finished quite worker thread
        self.serialWorker.finished.connect(                 self.serialWorker.deleteLater)              # delete worker at some time
        self.serialWorkerThread.finished.connect(           self.serialWorkerThread.deleteLater)        # delete thread at some time
        self.serialWorker.finished.connect(                 self.serialUI.workerFinished)               # connect worker finished signal to BLE UI

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

        self.serialUI.setupReceiverRequest.connect(         self.serialWorker.on_setupReceiverRequest)  # connect start receiver
        self.serialUI.startReceiverRequest.connect(         self.serialWorker.on_startReceiverRequest)  # connect start receiver
        self.serialUI.stopReceiverRequest.connect(          self.serialWorker.on_stopReceiverRequest)   # connect start receiver
        self.serialUI.finishWorkerRequest.connect(          self.serialWorker.on_stopWorkerRequest)     # connect finish request
        self.serialUI.startThroughputRequest.connect(       self.serialWorker.on_startThroughputRequest)# start throughput
        self.serialUI.stopThroughputRequest.connect(        self.serialWorker.on_stopThroughputRequest) # stop throughput

        # Signals from Serial-UI to Main
        # ------------------------------
        self.serialUI.displayingRunning.connect(            self.handle_SerialReceiverRunning)

        # Signals from User Interface to Serial-UI
        # ----------------------------------------
        #
        # General Buttons
        self.ui.pushButton_SerialScan.clicked.connect(      self.serialUI.on_pushButton_SerialScan)         # Scan for ports
        self.ui.pushButton_SerialStartStop.clicked.connect( self.serialUI.on_pushButton_SerialStartStop)    # Start/Stop serial receive
        self.ui.pushButton_SendFile.clicked.connect(        self.serialUI.on_pushButton_SendFile)           # Send text from a file to serial port
        self.ui.pushButton_SerialClearOutput.clicked.connect(self.serialUI.on_pushButton_SerialClearOutput) # Clear serial receive window
        self.ui.pushButton_SerialSave.clicked.connect(      self.serialUI.on_pushButton_SerialSave)         # Save text from serial receive window
        self.ui.pushButton_SerialOpenClose.clicked.connect( self.serialUI.on_pushButton_SerialOpenClose)    # Open/Close serial port
        #
        # Connect ComboBoxes
        self.ui.comboBoxDropDown_SerialPorts.currentIndexChanged.connect(    self.serialUI.on_comboBoxDropDown_SerialPorts) # user changed serial port
        self.ui.comboBoxDropDown_BaudRates.currentIndexChanged.connect(      self.serialUI.on_comboBoxDropDown_BaudRates)   # user changed baud rate
        self.ui.comboBoxDropDown_LineTermination.currentIndexChanged.connect(self.serialUI.on_comboBoxDropDown_LineTermination) # User changed line termination
        #
        # User hit up/down arrow in serial lineEdit
        self.shortcutUpArrow   = QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Up),  self.ui.lineEdit_Text, self.serialUI.on_upArrowPressed)
        self.shortcutDownArrow = QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Down),self.ui.lineEdit_Text, self.serialUI.on_downArrowPressed)

        self.ui.lineEdit_Text.returnPressed.connect(                              self.serialUI.on_carriageReturnPressed)   # Send text as soon as enter key is pressed

        # Radio buttons
        self.ui.radioButton_ResetESPonOpen.clicked.connect(                      self.serialUI.on_resetESPonOpen) # Reset ESP32 on open
        self.ui.radioButton_SerialRecord.clicked.connect(                        self.serialUI.on_SerialRecord) # Record incoming data to file

        # Done with Serial
        self.logger.log(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Serial initialized."
        )

        # ----------------------------------------------------------------------------------------------------------------------
        # Serial Plotter
        # ----------------------------------------------------------------------------------------------------------------------
        # Create user interface hook for chart plotting
        self.chartUI = QChartUI(ui=self.ui, serialUI=self.serialUI, serialWorker=self.serialWorker)  # create chart user interface object

        # Signals from Chart-UI to Main
        # ---------------------------------
        self.chartUI.plottingRunning.connect(                self.handle_SerialReceiverRunning)

        self.ui.pushButton_ChartStartStop.clicked.connect(  self.chartUI.on_pushButton_ChartStartStop)
        self.ui.pushButton_ChartClear.clicked.connect(      self.chartUI.on_pushButton_ChartClear)
        self.ui.pushButton_ChartSave.clicked.connect(       self.chartUI.on_pushButton_ChartSave)
        self.ui.pushButton_ChartSaveFigure.clicked.connect( self.chartUI.on_pushButton_ChartSaveFigure)

        self.ui.comboBoxDropDown_DataSeparator.currentIndexChanged.connect(self.chartUI.on_changeDataSeparator)

        # Horizontal Zoom
        self.horizontalSlider_Zoom = self.ui.findChild(QSlider, "horizontalSlider_Zoom")
        self.horizontalSlider_Zoom.setMinimum(8)
        self.horizontalSlider_Zoom.setMaximum(MAX_ROWS)
        self.horizontalSlider_Zoom.valueChanged.connect(    self.chartUI.on_HorizontalSliderChanged)

        self.lineEdit_Zoom = self.ui.findChild(QLineEdit, "lineEdit_Horizontal")
        self.lineEdit_Zoom.returnPressed.connect(           self.chartUI.on_HorizontalLineEditChanged)

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

        # ----------------------------------------------------------------------------------------------------------------------
        # Status Bar
        # ----------------------------------------------------------------------------------------------------------------------
        self.statusTimer = QTimer(self)
        self.statusTimer.timeout.connect(self.on_resetStatusBar)
        self.statusTimer.start(10000)  # Trigger every 10 seconds


        # Getting UI and Worker Running
        # -----------------------------
        self.serialWorker.moveToThread(self.serialWorkerThread)  # move worker to thread

        self.serialUI.scanPortsRequest.emit()              # request to scan for serial ports
        self.serialUI.scanBaudRatesRequest.emit()          # request to scan for serial ports
        self.serialUI.setupReceiverRequest.emit()          # establishes QTimer in the QThread above

        # ----------------------------------------------------------------------------------------------------------------------
        # Finish up
        # ----------------------------------------------------------------------------------------------------------------------
        self.show()

        #----------------------------------------------------------------------------------------------------------------------
        # Check for USB device connect/disconnect
        #----------------------------------------------------------------------------------------------------------------------

        self.usbThread = QThread()
        self.usbWorker = USBMonitorWorker()
        self.usbWorker.moveToThread(self.usbThread)
        
        # Connect signals and slots
        self.usbThread.started.connect(   self.usbWorker.run)
        self.usbWorker.finished.connect(  self.usbThread.quit)          # if worker emits finished quite worker thread
        self.usbWorker.finished.connect(  self.usbWorker.deleteLater)   # delete worker at some time
        self.usbThread.finished.connect(  self.usbThread.deleteLater)   # delete thread at some time
        self.usbWorker.usb_event_detected.connect(self.serialUI.on_usb_event_detected)
        self.usbWorker.logSignal.connect( self.serialUI.on_logSignal)
        self.usbThread.started.connect(   self.usbWorker.run)

        # Start the USB monitor thread
        self.usbThread.start()

        # Done USB monitor
        self.logger.log(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: USB monitor initialized."
        )

    def wait_for_signal(self, signal) -> float:
        """Utility to wait until a signal is emitted."""
        tic = time.perf_counter()
        loop = QEventLoop()
        signal.connect(loop.quit)
        loop.exec()
        return time.perf_counter() - tic
    
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


    def handle_usbThread_finished(self):
        self.logger.log(
            logging.DEBUG,
            f"[{self.instance_name[:15]:<15}]:USB monitor thread finished."
        )

    def handle_SerialReceiverRunning(self, runIt):
        """
        Handle the serial receiver running state.
        
        When text display is requested we connect the signals from the serial worker to the display function
        When charting is requested, we connect the signals from the serial worker to the charting function
        
        When either displaying or charting is requested we start the serial text receiver and the throughput calculator
        If neither of them is requested we stop the serial text receiver
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
                self.serialWorker.receivedLines.connect(        self.chartUI.on_receivedLines) # connect chart display to serial receiver signal
              # self.serialWorker.receivedData.connect(         self.chartUI.on_receivedData)  # connect chart display to serial receiver signal
                self.ui.pushButton_ChartStartStop.setText("Stop")
                if DEBUGRECEIVER:
                    self.logger.log(
                        logging.DEBUG,
                        f"[{self.instance_name[:15]:<15}]: connected signals for charting at {time.perf_counter()}."
                    )
            elif not runIt and self.isPlotting:
                try:
                    self.serialWorker.receivedLines.disconnect( self.chartUI.on_receivedLines) # disconnect chart display to serial receiver signal
                  # self.serialWorker.receivedData.disconnect(  self.chartUI.on_receivedData)  # disconnect chart display to serial receiver signal
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
                finally:
                    self.ui.pushButton_ChartStartStop.setText("Start")
        
            self.isPlotting = runIt

        # Displaying --------------------------------------
        elif sender == self.serialUI:
            if runIt and not self.isDisplaying:
                self.serialWorker.receivedLines.connect(        self.serialUI.on_receivedLines) # connect text display to serial receiver signal
                self.serialWorker.receivedData.connect(         self.serialUI.on_receivedData)  # connect text display to serial receiver signal
                self.ui.pushButton_SerialStartStop.setText("Stop")
                if DEBUGRECEIVER:
                    self.logger.log(
                        logging.DEBUG,
                        f"[{self.instance_name[:15]:<15}]: connected signals for text displaying at {time.perf_counter()}."
                    )
            elif not runIt and self.isDisplaying:
                try:
                    self.serialWorker.receivedLines.disconnect( self.serialUI.on_receivedLines) # disconnect text display to serial receiver signal
                    self.serialWorker.receivedData.disconnect(  self.serialUI.on_receivedData)  # disconnect text display to serial receiver signal
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
                finally:
                    self.ui.pushButton_SerialStartStop.setText("Start")
            else:
                pass

            self.isDisplaying = runIt
            
        else:
            # Signal should not move from other than SerialUI or ChartUI
            self.logger.log(
                logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: should not end up here, neither serialUI nor chartUI emitted the signal."
            )

        # Start or Stop the serial receiver ---------------
        #   If we neither plot nor display incoming data we dont need to run the serial worker
        if not (self.isPlotting or self.isDisplaying):
            # If we are neither plotting nor displaying data we need to stop the serial worker        
            if self.serialUI.receiverIsRunning:
                self.serialUI.stopReceiverRequest.emit()     # emit signal to finish worker
                QTimer.singleShot(50,lambda: self.serialUI.stopThroughputRequest.emit()) # finish throughput calc
                if DEBUGRECEIVER:
                    self.logger.log(
                        logging.DEBUG,
                        f"[{self.instance_name[:15]:<15}]: stopped receiver as it is not needed {time.perf_counter()}."
                    )
        else:
            # If we are plotting or displaying data we need to run the serial worker and throughput calc
            if not self.serialUI.receiverIsRunning:
                self.serialUI.startReceiverRequest.emit()
                QTimer.singleShot(50,lambda: self.serialUI.startThroughputRequest.emit())
                if DEBUGRECEIVER:
                    self.logger.log(
                        logging.DEBUG,
                        f"[{self.instance_name[:15]:<15}]: started receiver at {time.perf_counter()}."
                    )

    def on_resetStatusBar(self):
        now = datetime.now()
        formatted_date_time = now.strftime("%Y-%m-%d %H:%M")
        self.ui.statusbar.showMessage("Serial User Interface. " + formatted_date_time)

    def show_about_dialog(self):
        # Information to be displayed
        info_text = "Serial Terminal & Plotter\nVersion: 1.0\nAuthor: Urs Utzinger\n2022-2025"
        QMessageBox.about(self, "About Program", info_text) # Create and display the MessageBox
        self.show()

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
