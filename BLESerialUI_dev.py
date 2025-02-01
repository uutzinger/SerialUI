#!/usr/bin/env python3
#############################################################################################
# BLE Serial Communication GUI
# ============================
#
# A simple BLE terminal application using Qt and Bleak library to communicate 
# with a BLE device through Nordic UART Service.
#
#
# This program will give you option to scan for BLE device, connect to a device, and pair
# with the device. It will allow you to send text to the BLE device and receive text.
#############################################################################################

# Need to rewrite code. I can not run bluetoothctl wrapper with Bleak simultaneously. 
# I need to start it up each time I use trust/distrust, pair/remove, status.

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Basic libraries
import sys
import os
import re
import logging
import time
import platform
from markdown import markdown

# Qt library
try:
    from PyQt6 import QtCore, QtWidgets, QtGui, uic
    from PyQt6.QtCore import (
        QObject, QProcess, pyqtSignal, pyqtSlot, 
        QTimer, QMutex, QMutexLocker, QThread,
        QEventLoop, Qt, QStandardPaths
    )
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QPushButton, QLabel,
        QTextEdit, QVBoxLayout, QWidget, QComboBox, QHBoxLayout, QSizePolicy, 
        QFileDialog, QShortcut, QLineEdit, QSlider, QMessageBox, QDialog, QTabWidget
    )
    from PyQt6.QtGui import QIcon, QKeySequence, QTextCursor, QPalette, QColor
    PYQT6 = True

except ImportError:
    from PyQt5 import QtCore, QtWidgets, QtGui, uic
    from PyQt5.QtCore import (
        QObject, QProcess, pyqtSignal, pyqtSlot, 
        QTimer, QMutex, QMutexLocker, QThread,
        QEventLoop, Qt, QStandardPaths
    )
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QPushButton, QLabel,
        QTextEdit, QVBoxLayout, QWidget, QComboBox, QHBoxLayout, QSizePolicy, 
        QFileDialog, QShortcut, QLineEdit, QSlider, QMessageBox, QDialog, QTabWidget
    )
    from PyQt5.QtGui import QIcon, QKeySequence, QTextCursor, QPalette, QColor
    PYQT6 = False
 
# IO event loop
import asyncio
import threading # for asyncio in a separate thread

# Bluetooth library
from bleak import BleakClient, BleakScanner, BleakError
from bleak.backends.device import BLEDevice

x
# Custom Helper Classes
# ---------------------
from helpers.QBLE_helper   import QBLESerialUI, QBLESerial
from helpers.Qgraph_helper import QChartUI, MAX_ROWS
from helpers.Codec_helper  import BinaryStreamProcessor
from helpers.Qbluetoothctl_helper import BluetoothctlWrapper

# Deal with high resolution displays
if not PYQT6:
    # Deal with high resolution displays
    if hasattr(QtCore.Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(QtCore.Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

# Future release will include option for displaying data in indicators
#  and 3D vector plots.
USE3DPLOT = False

#############################################################################################################################################
#############################################################################################################################################
#
# Main Window
#
#    This is the Viewer  of the Model - View - Controller (MVC) architecture.
#
#############################################################################################################################################
#############################################################################################################################################

class MainWindow(QMainWindow):
    """
    Sets up the user interface and creates the connections between the user interface objects and the worker.
    Worker slots are connected with the interface signals and the worker signals with the interface slots.

    This is the Viewer  of the Model - View - Controller (MVC) architecture.
    """

    # -------------------------------------------------------------------------------------
    # Initialize
    # -------------------------------------------------------------------------------------

    def __init__(self, logger=None):
        """
        Initialize the components of the main window.
        This will create the connections between slots and signals in both directions.

        BLESerial:
        Create serial BLE worker and move it to separate thread.

        Serial Plotter:
        Create chart user interface object.
        """
        super().__init__()

        if logger is None:
            self.logger = logging.getLogger("QMain")
        else:
            self.logger = logger

        if platform.system() == "Linux":
            self.hasBluetoothctl = True
        else:
            self.hasBluetoothctl = False

        main_dir = os.path.dirname(os.path.abspath(__file__))

        self.instance_name = self.objectName() if self.objectName() else self.__class__.__name__

        self.isDisplaying = False
        self.isPlotting   = False

        # Stream Processors
        self.binaryStream  = BinaryStreamProcessor(eop=b'\x00', logger = self.logger)

        # ----------------------------------------------------------------------------------------------------------------------
        # User Interface
        # ----------------------------------------------------------------------------------------------------------------------

        # Create an empty container object
        self.ui = uic.loadUi("assets/BLEserialUI.ui", self)
        icon_path = os.path.join(main_dir, "assets", "BLE_48.png")
        window_icon = QIcon(icon_path)
        self.setWindowIcon(QIcon(window_icon))
        self.setWindowTitle("BLE Serial GUI")

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

        self.ui.comboBoxDropDown_Device.addItem("none", None)    
        self.ui.comboBoxDropDown_Device.setItemData(
            self.ui.comboBoxDropDown_Device.findText("none"), None
        )
        self.ui.comboBoxDropDown_Device.setCurrentIndex(0)                                 # set default to none
        self.device = None                                                                    # default device: none                               

        # Find the index of "none"
        idx = self.ui.comboBoxDropDown_LineTermination.findText("none")
        if idx != -1:
            self.ui.comboBoxDropDown_LineTermination.setCurrentIndex(idx)
        self.textLineTerminator = b""

        # Find the index of "none"
        idx = self.ui.comboBoxDropDown_DataTermination.findText("No Labels (simple)")
        if idx != -1:
            self.ui.comboBoxDropDown_DataTermination.setCurrentIndex(idx)
        self.textLineTerminator = 0

        # Configure the Buttons
        # ----------------------------------------------------------------------------------------------------------------------
        self.ui.pushButton_Connect.setText("Connect")
        self.ui.pushButton_Pair.setText("Pair")
        self.ui.pushButton_StartStop.setText("Start")

        self.ui.pushButton_Connect.setEnabled(False)
        self.ui.pushButton_Pair.setEnabled(False)
        self.ui.pushButton_StartStop.setEnabled(False)
        self.ui.lineEdit_Text.setEnabled(False)
        self.ui.pushButton_SendFile.setEnabled(False)
        self.ui.pushButton_Scan.setEnabled(True)
        self.ui.pushButton_Status.setEnabled(False)
        self.ui.pushButton_Trust.setEnabled(False)
        self.ui.pushButton_Clear.setEnabled(True)
        self.ui.pushButton_Save.setEnabled(True)

        # Configure Scrolling
        # ----------------------------------------------------------------------------------------------------------------------

        # Text display window for BLE text display
        self.ui.textScrollbar = self.ui.plainTextEdit_Text.verticalScrollBar()
        self.ui.plainTextEdit_Text.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        
        # Text display window for log display
        self.ui.logScrollbar = self.ui.plainTextEdit_Log.verticalScrollBar()
        self.ui.plainTextEdit_Log.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )

        # ----------------------------------------------------------------------------------------------------------------------
        # BLE Serial Worker & Thread
        # ----------------------------------------------------------------------------------------------------------------------

        self.bleWorkerThread = QThread()                                                # create QThread object

        # Create the BLE worker
        self.bleWorker = QBLESerial()                                                   # create BLE worker object

        # Create user interface hook for BLE
        self.bleUI = QBLESerialUI(ui=self.ui, worker=self.bleWorker, logger=self.logger)# create BLE UI object

        # Connect worker / thread finished
        self.bleWorker.finished.connect(            self.bleWorkerThread.quit)          # if worker emits finished quite worker thread
        self.bleWorker.finished.connect(            self.bleWorker.deleteLater)         # delete worker at some time
        self.bleWorkerThread.finished.connect(      self.bleWorkerThread.deleteLater)   # delete thread at some time
        self.bleWorker.finished.connect(            self.bleUI.workerFinished)          # connect worker finished signal to BLE UI

        # Signals from BLE Worker to BLE-UI
        # ---------------------------------
        # self.bleWorker.receivedData.connect(            self.bleUI.on_receivedData)          # connect text display to BLE receiver signal
        # self.bleWorker.receivedLines.connect(           self.bleUI.on_receivedLines)         # connect text display to BLE receiver signal

        self.bleWorker.deviceListReady.connect(         self.bleUI.on_deviceListReady)       # connect new port list to its ready signal
        self.bleWorker.statusReady.connect(             self.bleUI.on_statusReady)           # connect 
        self.bleWorker.throughputReady.connect(         self.bleUI.on_throughputReady)       # connect display throughput status
        self.bleWorker.pairingSuccess.connect(          self.bleUI.on_pairingSuccess)        # connect pairing status to BLE UI
        self.bleWorker.trustSuccess.connect(            self.bleUI.on_trustSuccess)          # connect trust status to BLE UI
        self.bleWorker.distrustSuccess.connect(         self.bleUI.on_distrustSuccess)       # connect distrust status to BLE UI
        self.bleWorker.connectingSuccess.connect(       self.bleUI.on_connectingSuccess)     # connect connecting status to BLE UI
        self.bleWorker.disconnectingSuccess.connect(    self.bleUI.on_disconnectingSuccess)  # connect disconnecting status to BLE UI
        self.bleWorker.removalSuccess.connect(          self.bleUI.on_removalSuccess)        # connect removal status to BLE UI

        self.bleWorker.setupBLEWorkerFinished.connect(  self.bleUI.setupBLEWorkerFinished)   # connect setupBLEWorkerFinished signal to BLE UI
        self.bleWorker.setupTransceiverFinished.connect(self.bleUI.setupTransceiverFinished) # connect setupTransceiverFinished signal to BLE UI

        self.bleWorker.logSignal.connect(               self.bleUI.on_logSignal)             # connect log messages to BLE UI

        # Signals from BLE-UI to BLE Worker
        # ---------------------------------
        self.bleUI.connectDeviceRequest.connect(        self.bleWorker.on_connectDeviceRequest)
        self.bleUI.disconnectDeviceRequest.connect(     self.bleWorker.on_disconnectDeviceRequest)
        self.bleUI.changeLineTerminationRequest.connect(self.bleWorker.on_changeLineTerminationRequest)  # connect changing line termination
        self.bleUI.scanDevicesRequest.connect(          self.bleWorker.on_scanDevicesRequest)
        self.bleUI.pairDeviceRequest.connect(           self.bleWorker.on_pairDeviceRequest)
        self.bleUI.removeDeviceRequest.connect(         self.bleWorker.on_removeDeviceRequest)
        self.bleUI.trustDeviceRequest.connect(          self.bleWorker.on_trustDeviceRequest)
        self.bleUI.distrustDeviceRequest.connect(       self.bleWorker.on_distrustDeviceRequest)
        self.bleUI.bleStatusRequest.connect(            self.bleWorker.on_bleStatusRequest)

        self.bleUI.sendFileRequest.connect(             self.bleWorker.on_sendFileRequest)
        self.bleUI.sendTextRequest.connect(             self.bleWorker.on_sendTextRequest)
        self.bleUI.sendLineRequest.connect(             self.bleWorker.on_sendLineRequest)
        self.bleUI.sendLinesRequest.connect(            self.bleWorker.on_sendLinesRequest)

        self.bleUI.setupBLEWorkerRequest.connect(       self.bleWorker.on_setupBLEWorkerRequest)
        self.bleUI.setupTransceiverRequest.connect(     self.bleWorker.on_setupTransceiverRequest)
        self.bleUI.finishWorkerRequest.connect(         self.bleWorker.on_finishWorkerRequest)
        self.bleUI.stopTransceiverRequest.connect(      self.bleWorker.on_stopTransceiverRequest)

        # Signals from BLESerial-UI to Main
        # ---------------------------------
        self.bleUI.displayingRunning.connect(           self.handle_BLEReceiverRunning)

        # Signals from User Interface to BLESerial-UI
        # -------------------------------------------
        #
        # Connect Buttons
        self.ui.pushButton_Scan.clicked.connect(        self.bleUI.on_pushButton_Scan)
        self.ui.pushButton_Connect.clicked.connect(     self.bleUI.on_pushButton_Connect)
        self.ui.pushButton_StartStop.clicked.connect(   self.bleUI.on_pushButton_StartStop)
        self.ui.pushButton_Clear.clicked.connect(       self.bleUI.on_pushButton_Clear)
        self.ui.pushButton_Save.clicked.connect(        self.bleUI.on_pushButton_Save)
        self.ui.pushButton_SendFile.clicked.connect(    self.bleUI.on_pushButton_SendFile)
        self.ui.pushButton_Pair.clicked.connect(        self.bleUI.on_pushButton_Pair)
        self.ui.pushButton_Status.clicked.connect(      self.bleUI.on_pushButton_Status)
        self.ui.pushButton_Trust.clicked.connect(       self.bleUI.on_pushButton_Trust)
        #
        # Connect ComboBoxes
        self.ui.comboBoxDropDown_Device.currentIndexChanged.connect(             self.bleUI.on_comboBoxDropDown_BLEDevices)
        self.ui.comboBoxDropDown_LineTermination.currentIndexChanged.connect(    self.bleUI.on_comboBoxDropDown_LineTermination)
        self.ui.comboBoxDropDown_DataSeparator.currentIndexChanged.connect(      self.bleUI.on_comboBoxDropDown_DataSeparator)
        #
        # User hit up/down arrow in BLE lineEdit
        self.shortcutUpArrow   = QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Up), self.ui.lineEdit_Text, self.bleUI.on_upArrowPressed)
        self.shortcutDownArrow = QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Down),self.ui.lineEdit_Text, self.bleUI.on_downArrowPressed)
        
        # User hit carriage return in BLE lineEdit
        self.ui.lineEdit_Text.returnPressed.connect(                             self.bleUI.on_carriageReturnPressed) # Send text as soon as enter key is pressed

        # Radio buttons
        self.ui.radioButton_SerialRecord.clicked.connect(                        self.bleUI.on_SerialRecord) # Record incoming data to file

        # Done with Serial
        self.logger.log(
            logging.INFO,
            f"[{int(QThread.currentThreadId())}]: BLE initialized."
        )

        # ----------------------------------------------------------------------------------------------------------------------
        # Serial Plotter
        # ----------------------------------------------------------------------------------------------------------------------
        # Create user interface hook for chart plotting
        self.chartUI = QChartUI(ui=self.ui, serialUI=self.serialUI, serialWorker=self.serialWorker)  # create chart user interface object

        # Signals from Chart-UI to Main
        # ---------------------------------
        self.chartUI.plottingRunning.connect(                self.handle_BLEReceiverRunning)

        self.ui.pushButton_ChartStartStop.clicked.connect(  self.chartUI.on_pushButton_StartStop)
        self.ui.pushButton_ChartClear.clicked.connect(      self.chartUI.on_pushButton_Clear)
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
            f"[{int(QThread.currentThreadId())}]: Plotter initialized."
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
        self.bleWorker.moveToThread(self.bleWorkerThread)
        self.bleWorkerThread.start()  
        #
        # Create asyncio event loop and bluetoothctl wrapper
        self.bleUI.setupBLEWorkerRequest.emit()
        time_elapsed = self.wait_for_signal(self.bleUI.setupBLEWorkerFinished) * 1000
        self.logger.info(f"[{self.instance_name}] BLE worker setup in {time_elapsed:.2f} ms.")
        #
        # Start throughput timer
        self.bleUI.setupTransceiverRequest.emit()
        time_elapsed = self.wait_for_signal(self.bleUI.setupTransceiverFinished) * 1000
        self.logger.info(f"[{self.instance_name}] BLE transceiver setup in {time_elapsed:.2f} ms.")
        #
        # Populate the device list
        self.bleUI.scanDevicesRequest.emit()       # request to scan for BLE ports

        # ----------------------------------------------------------------------------------------------------------------------
        # Finish up
        # ----------------------------------------------------------------------------------------------------------------------

        self.show()


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
            self.ui.plainTextEdit_Text.verticalScrollBar().setValue(self.ui.plainTextEdit_Text.verticalScrollBar().maximum())
        elif tab_name == "Plotter":
            pass
        elif tab_name == "Indicator":
            pass
        else:
            try:
                self.logger.log(
                    logging.ERROR,
                    "[{}]: unknown tab name: {}".format(
                        int(QThread.currentThreadId()), tab_name
                    ),
                )
            except:
                pass

    def handle_BLEReceiverRunning(self, running):
        """
        Handle the serial receiver running state.
        
        When text display is requested we connect the signals from the serial worker to the display function
        When charting is requested, we connect the signals from the serial worker to the charting function
        
        When either displaying or charting is requested we start the serial text receiver and the throughput calculator
        If neither of them is requested we stop the serial text receiver
        """
        sender = self.sender()  # Get the sender object
        self.logger.log(logging.DEBUG, f"handle_BLEReceiverRunning called by {sender}")

        # Plotting --------------------------------------
        if sender == self.chartUI:
            if running and not self.isPlotting:
                self.bleWorker.receivedLines.connect(        self.chartUI.on_receivedLines) # connect chart display to serial receiver signal
              # self.bleWorker.receivedData.connect(         self.chartUI.on_receivedData)  # connect chart display to serial receiver signal
            elif not running and self.isPlotting:
                try:
                    self.bleWorker.receivedLines.disconnect( self.chartUI.on_receivedLines) # disconnect chart display to serial receiver signal
                  # self.bleWorker.receivedData.disconnect(  self.chartUI.on_receivedData)  # disconnect chart display to serial receiver signal
                except:
                    self.logger.log(logging.ERROR, "disconnect to chartUI.on_receivedLines failed")

            self.isPlotting = running

        # Displaying --------------------------------------
        elif sender == self.bleUI:
            if running and not self.isDisplaying:
                self.bleWorker.receivedLines.connect(        self.bleUI.on_receivedLines) # connect text display to serial receiver signal
                self.bleWorker.receivedData.connect(         self.bleUI.on_receivedData)  # connect text display to serial receiver signal
            elif not running and self.isDisplaying:
                try:
                    self.bleWorker.receivedLines.disconnect( self.bleUI.on_receivedLines) # disconnect text display to serial receiver signal
                    self.bleWorker.receivedData.disconnect(  self.bleUI.on_receivedData)  # disconnect text display to serial receiver signal
                except:
                    self.logger.log(logging.ERROR, "disconnect to bleUI.on_receivedLines failed")
            else:
                pass

            self.isDisplaying = running
            
        else:
            # Signal should not move from other than blelUI or ChartUI
            pass

        # Start or Stop the serial receiver ---------------
        if self.isPlotting or self.isDisplaying:
            QTimer.singleShot(50,lambda: self.bleUI.startThroughputRequest.emit())

    def on_resetStatusBar(self):
        now = datetime.now()
        formatted_date_time = now.strftime("%Y-%m-%d %H:%M")
        self.ui.statusbar.showMessage("BLE Serial User Interface. " + formatted_date_time)

    def show_about_dialog(self):
        # Information to be displayed
        info_text = "BLE Serial Terminal & Plotter\nVersion: 1.0\nAuthor: Urs Utzinger\n2024-2025"
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
        Close the device, stop the BLE worker thread.
        """
        self.bleUI.cleanup()  # close serial port and stop thread 
        self.chartUI.cleanup()  # stop the chart timer

        self.logger.info(f"[{self.instance_name}] Finishing worker ...")

        if self.bleWorker:
            if self.bleUI:
                self.bleUI.finishWorkerRequest.emit()
                time_elapsed = self.wait_for_signal(self.bleUI.workerFinished) * 1000    
                self.logger.info(f"[{self.instance_name}] Worker finished in {time_elapsed:.2f} ms.")
            else:
                self.logger.log(
                    logging.ERROR,
                    f"[{int(QThread.currentThreadId())}]: bleUI not initialized."
                )
        else:
            self.logger.log(
                logging.ERROR,
                f"[{int(QThread.currentThreadId())}]: bleWorker not initialized."
            )

        # self.logger.info([f"{self.instance_name}] Stopping worker thread..."])
        # self.bleWorkerThread.quit()
        # self.bleWorkerThread.wait()
        # self.logger.info(f"[{self.instance_name}] Worker thread stopped")

        event.accept()
#############################################################################################################################################        
#    Main
#############################################################################################################################################

if __name__ == "__main__":

    # set logging level
    # CRITICAL  50
    # ERROR     40
    # WARNING   30
    # INFO      20
    # DEBUG     10
    # NOTSET     0

    logging.basicConfig(level=logging.INFO)

    root_logger = logging.getLogger("BLESerial")
    current_level = root_logger.getEffectiveLevel()

    app = QtWidgets.QApplication(sys.argv)

    win = MainWindow(logger=root_logger)

    screen = app.primaryScreen()
    scalingX = screen.logicalDotsPerInchX() / 96.0
    scalingY = screen.logicalDotsPerInchY() / 96.0
    win.resize(int(1200 * scalingX), int(665 * scalingY))
    win.show()
    
    exit_code = app.exec()
    
    sys.exit(exit_code)

