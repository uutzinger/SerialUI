#!/usr/bin/env python3
############################################################################################################################################
# Serial Communication App
# ************************
#
# - Provides serial interface to send and receive data to/from 
#     - serial port (USB, RS232)
#     - serial BLE (Nordic UART Service)
# - Displays received data in a scrollable text window with option to record to file.
#     - can handle data at high rates comparable with other terminal programs
# - Plots data in chart with zoom, save and clear.
#     - extracts numbers from data in simple or structured manner efficiently
#     - can use pyqtgraph or fastplotlib for plotting
# - Handles connection upon insertion and removal of USB devices.
# - Attempts handling of BLE devices in comprehensive manner.
#
# Configurations can be changed in config.py
#
# This code is maintained by Urs Utzinger
############################################################################################################################################
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
# ==============================================================================
# Config
# ==============================================================================
# This will steer imports
from config import (
    USE_BLE, USE_3DPLOT, USE_FASTPLOTLIB, USE_BLUETOOTHCTL,
    VERSION, AUTHOR, DATE,
    DEFAULT_TEXT_LINES, MAX_TEXT_LINES, MAX_ROWS,
    DEBUGKEYINPUT, DEBUG_LEVEL, DEBUGRECEIVER, DEBUGCHART,
    ENCODING, BACKGROUNDCOLOR, BACKGROUNDCOLOR_LOG, BACKGROUNDCOLOR_TABS,
    EOL_DICT, EOL_DICT_INV, EOL_DEFAULT_LABEL, EOL_DEFAULT_BYTES, DEFAULT_LINETERMINATOR,
    PARSE_OPTIONS, PARSE_OPTIONS_INV, PARSE_DEFAULT_LABEL, PARSE_DEFAULT_NAME,
    LOG_OPTIONS, LOG_OPTIONS_INV, LOG_DEFAULT_LABEL, LOG_DEFAULT_NAME,
    DISCRETE_GPU
)
# ==============================================================================
# Graphics Environment Setup
# ==============================================================================
# This needs to run before importing any QT, wgpu, pygfx, fastplotlib, pyqtgraph modules
from helpers.General_helper import setup_graphics_env
if DEBUGCHART:
    setup_graphics_env(
        prefer_discrete_gpu=DISCRETE_GPU,                                      # use False to bias to iGPU
        force_backend=None,                                                    # None->auto per OS; or "vulkan"/"dx12"/"metal"/"gl"
        wayland_ok=True,                                                       # set False to force X11 on Linux even if Wayland session
        verbose_logs=True,                                                     # True to enable RUST_LOG for wgpu
    )
else:
    setup_graphics_env(
        prefer_discrete_gpu=DISCRETE_GPU,                                      # use False to bias to iGPU
        force_backend=None,                                                    # None->auto per OS; or "vulkan"/"dx12"/"metal"/"gl"
        wayland_ok=True,                                                       # set False to force X11 on Linux even if Wayland session
        verbose_logs=False,                                                    # True to enable RUST_LOG for wgpu
    )
# ==============================================================================
# Imports
# ==============================================================================
#
# Basic libraries 
# ----------------------------------------
import sys
import os
import time
import textwrap
from markdown import markdown
from datetime import datetime
from pathlib import Path
import logging
#
# QT imports, QT5 or QT6 
# ----------------------------------------
try:
    from PyQt6 import uic
    from PyQt6.QtCore import (
        QTimer, Qt, pyqtSlot, pyqtSignal, QStandardPaths, QCoreApplication
    )
    from PyQt6.QtWidgets import (
        QMainWindow, QLineEdit, QSlider, 
        QMessageBox, QDialog, QVBoxLayout, 
        QTextEdit, QTabWidget, QWidget, 
        QPlainTextEdit, QApplication,
    )
    from PyQt6.QtGui import QIcon, QShortcut, QTextCursor, QTextOption,  QKeySequence, QGuiApplication, QPixmap
    WindowType    = Qt.WindowType
    ConnectionType= Qt.ConnectionType
    NO_WRAP       = QPlainTextEdit.LineWrapMode.NoWrap
    NO_WORDWRAP   = QTextOption.WrapMode.NoWrap
    MOVE_END      = QTextCursor.MoveOperation.End
    KEY_UP        = QKeySequence(Qt.Key.Key_Up)
    KEY_DOWN      = QKeySequence(Qt.Key.Key_Down)
    DOCUMENTS     = QStandardPaths.StandardLocation.DocumentsLocation
    hasQt6        = True
except Exception:
    from PyQt5 import uic
    from PyQt5.QtCore import (
        QTimer, Qt, pyqtSlot, pyqtSignal, QStandardPaths, QCoreApplication
    )
    from PyQt5.QtWidgets import (
        QMainWindow, QLineEdit, QSlider, 
        QMessageBox, QDialog, QVBoxLayout, 
        QTextEdit, QTabWidget, QWidget, QShortcut, 
        QPlainTextEdit, QApplication,
    )
    from PyQt5.QtGui import (
        QIcon, QTextCursor, QTextOption, QKeySequence, QGuiApplication, QPixmap
    )
    WindowType    = Qt
    ConnectionType= Qt
    NO_WRAP       = QPlainTextEdit.NoWrap
    NO_WORDWRAP   = QTextOption.NoWrap
    MOVE_END      = QTextCursor.End
    KEY_UP        = QKeySequence(Qt.Key_Up)
    KEY_DOWN      = QKeySequence(Qt.Key_Down)
    DOCUMENTS     = QStandardPaths.DocumentsLocation
    hasQt6        = False
#
# # Set HiDPI rounding policy early (before creating QApplication). Safe for Qt5/Qt6.
# NOT enabled as environment variables should take care of this
# try:
#     if hasattr(QGuiApplication, "setHighDpiScaleFactorRoundingPolicy"):
#         # Only set if no instance exists yet
#         if QGuiApplication.instance() is None:
#             # Prefer PassThrough; fall back to RoundPreferFloor if not available
#             policy = getattr(Qt.HighDpiScaleFactorRoundingPolicy, "PassThrough",
#                              getattr(Qt.HighDpiScaleFactorRoundingPolicy, "RoundPreferFloor"))
#             QGuiApplication.setHighDpiScaleFactorRoundingPolicy(policy)
# except Exception:
#     pass
#
# Enable High DPI scaling and use high DPI pixmaps (should be before creating QApplication)
try:
    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True
        )
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True
        )
except Exception:
    pass
#
# Program's local class imports 
# ----------------------------------------
#
from helpers.Qgraph_helper          import QChart
from helpers.Qserial_helper         import QSerial
from helpers.USB_SerialPortMonitor  import QUSBMonitor
from helpers.General_helper         import (clip_value, connect, disconnect, select_file, 
                                            confirm_overwrite_append)
if USE_BLE:
    from helpers.QBLE_helper        import QBLESerial 
#
# Profiling
# ----------------------------------------
# To profile this application run the program with:
#    kernprof -l -v SerialUI.py
# Then create a readable report with:
#    python -m line_profiler SerialUI.py.lprof > SerialUI_profile.txt
# This will shows which statements in tagged functions take the most time.
try:
    profile                                                                    # provided by kernprof at runtime
except NameError:
    def profile(func):                                                         # no-op when not profiling
        return func

############################################################################################################################################
#
# Main Window
#
#    This is the Viewer of the Model - View - Controller (MVC) architecture.
#
############################################################################################################################################

class mainWindow(QMainWindow):
    """
    Main program that ties the classes, threads and widgets together.

    Serial:
    Create serial interface. The initialization sets a custom serial worker in a separate qt thread.

    BLE:
    Create BLE interface. The initialization sets a custom worker using a custom task scheduler.

    Text and Log Display:
    Create text and log display windows with scrollbar, history, save and record.

    Plotter:
    Create chart interface using pyqtgraph or fastplotlib.
    The chart can be zoomed in time and saved/exported.
    Fastplotlib utilizes GPU if present. pyqtgraph uses multiple cores for rendering.

    Indicator:
    Display values and vectors (not yet implemented).

    USB Monitor:
    Detect insertion and removal of USB devices. It triggers reconnection attempt.
    """

    # Signals of the main window
    # ==========================================================================
    mtocRequest            = pyqtSignal()                                      # request to receive function profiling information
    sendFileRequest        = pyqtSignal(Path)                                  # request to open file and send over serial port
    sendTextRequest        = pyqtSignal(bytes)                                 # request to transmit text to TX
    sendLineRequest        = pyqtSignal(bytes)                                 # request to transmit one line of text to TX
    sendLinesRequest       = pyqtSignal(list)                                  # request to transmit lines of text to TX
    runMonitoringRequest   = pyqtSignal(bool)                                  # request monitor on/off
    rxStartRequest         = pyqtSignal()                                      # start transceivers (whoever is wired)
    rxStopRequest          = pyqtSignal()                                      # stop transceivers (whoever is wired)
    throughputStartRequest = pyqtSignal()                                      # start throughput (whoever is wired)
    throughputStopRequest  = pyqtSignal()                                      # stop throughput (whoever is wired)
    
    # ==========================================================================
    # Initialize
    # ==========================================================================
    def __init__(self, parent=None, logger=None):
        """
        Initialize the components of the main window.
        This will create the connections between slots and signals in both directions.
        Serial, BLE, Chart and USB monitoring is setup in their initialization threads.
        Display and logging is handled here in the main thread.
        """

        super().__init__(parent)                                               # parent constructor

        if logger is None:
            self.logger = logging.getLogger("SerialUI")
            self.logger.setLevel(DEBUG_LEVEL)
            sh = logging.StreamHandler()
            fmt = "[%(levelname)-8s] [%(name)-10s] %(message)s"
            sh.setFormatter(logging.Formatter(fmt))
            self.logger.addHandler(sh)
            self.logger.propagate = False
        else:
            self.logger = logger

        self.encoding = ENCODING
        self.maxlines = DEFAULT_TEXT_LINES

        self.main_dir = os.path.dirname(os.path.abspath(__file__))
        self.instance_name = self.objectName() if self.objectName() else self.__class__.__name__

        self.isMonitoring = False
        self.isPlotting   = False                                              # chart receiver status request
        self.lineSendHistory     = []                                          # previously sent text (e.g. commands)
        self.lineSendHistoryIndx = -1               
        self.textLineTerminator = DEFAULT_LINETERMINATOR

        # User Interface
        # ----------------------------------------
        self.ui = uic.loadUi("assets/serialUI.ui", self)
        self.setWindowTitle("Serial GUI")

        # Log Display
        # ----------------------------------------
        # Needs to be setup first, otherwise logging is not available

        self.log_widget = self.ui.plainTextEdit_Log
        self.log_widget.setStyleSheet(f"background-color: {BACKGROUNDCOLOR_LOG};")

        # Modify LOG display window on serial text display
        self.log_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.log_widget.setLineWrapMode(NO_WRAP)                               # no wrapping for better performance
        self.log_widget.setReadOnly(True)                                      # prevent user edits
        self.log_widget.setWordWrapMode(NO_WORDWRAP)                           # no wrapping for better performance
        self.log_widget.setUndoRedoEnabled(False)
        self.log_widget.setMaximumBlockCount(int(self.maxlines/5))
        self.log_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        self.log_scroll_bar = self.log_widget.verticalScrollBar()
        self.log_scroll_bar.setSingleStep(1)                                   # highest resolution for scrolling
        self.log_scroll_bar.setPageStep(10)                                    # defines how much a full page scroll moves
        self.log_scroll_bar.setValue(self.log_scroll_bar.maximum())            # scroll to bottom
        # Set cursor to end of LOG display for auto scrolling
        # one should obtain a copy of the text cursor each time one modifies it
        textCursor = self.log_widget.textCursor()
        textCursor.movePosition(MOVE_END)
        self.log_widget.setTextCursor(textCursor)
        self.log_widget.ensureCursorVisible()

        # Icons
        # ----------------------------------------
        icon_path     = os.path.join(self.main_dir, "assets", "icon_48.png")
        window_icon   = QIcon(icon_path)
        self.setWindowIcon(window_icon)
        QApplication.setWindowIcon(window_icon)
        ble_icon_path = os.path.join(self.main_dir, "assets", "BLE_48.png")
        ble_icon      = QIcon(ble_icon_path)
        usb_icon_path = os.path.join(self.main_dir, "assets", "USB_48.png")
        usb_icon      = QIcon(usb_icon_path)

        # pix = QPixmap(icon_path)
        # self.logger.log(logging.INFO, f"Icon Pixmap isNull: {pix.isNull()}, Size: {pix.size()}")
        # pix = QPixmap(usb_icon_path)
        # self.logger.log(logging.INFO, f"USB Icon Pixmap isNull: {pix.isNull()}, Size: {pix.size()}")
        # pix = QPixmap(ble_icon_path)
        # self.logger.log(logging.INFO, f"BLE Icon Pixmap isNull: {pix.isNull()}, Size: {pix.size()}")

        # Find the tabs and connect to tab change
        # ----------------------------------------
        self.tabs: QTabWidget = self.findChild(QTabWidget, "tabWidget_MainWindow")
        self.tabs.currentChanged.connect(self.on_tab_change)
        self.tabs.setStyleSheet(f"QWidget {{ background-color: {BACKGROUNDCOLOR_TABS}; }}")

        # Configure Drop Down Menus
        # ----------------------------------------

        # Line Termination Serial
        cb = self.ui.comboBoxDropDown_LineTermination
        cb.blockSignals(True)
        cb.clear()
        cb.addItems(list(EOL_DICT.keys()))
        # Set current index based on the current bytes value (if you already have one)
        current_bytes = getattr(self, "textLineTerminator", EOL_DEFAULT_BYTES)
        label = EOL_DICT_INV.get(current_bytes, EOL_DEFAULT_LABEL)
        idx = cb.findText(label)
        if idx >= 0:
            cb.setCurrentIndex(idx)
        else:
            cb.setCurrentIndex(cb.findText(EOL_DEFAULT_LABEL))
        cb.blockSignals(False)

        # Line Termination BLE
        cb = self.ui.comboBoxDropDown_LineTermination_BLE
        cb.blockSignals(True)
        cb.clear()
        cb.addItems(list(EOL_DICT.keys()))
        # Set current index based on the current bytes value (if you already have one)
        # current_bytes = getattr(self, "textLineTerminator", EOL_DEFAULT_BYTES)
        # label = EOL_DICT_INV.get(current_bytes, EOL_DEFAULT_LABEL)
        idx = cb.findText(label)
        if idx >= 0:
            cb.setCurrentIndex(idx)
        else:
            cb.setCurrentIndex(cb.findText(EOL_DEFAULT_LABEL))
        cb.blockSignals(False)

        # Plotting Data Separator
        cb = self.ui.comboBoxDropDown_DataSeparator
        cb.blockSignals(True)
        cb.clear()
        cb.addItems(list(PARSE_OPTIONS.keys()))
        current_name = getattr(self, "textDataSeparator", PARSE_DEFAULT_NAME)
        label = PARSE_OPTIONS_INV.get(current_name, PARSE_DEFAULT_LABEL)
        idx = cb.findText(label)
        if idx >= 0:
            cb.setCurrentIndex(idx)
        else:
            cb.setCurrentIndex(cb.findText(PARSE_DEFAULT_LABEL))
        cb.blockSignals(False)

        # LOG level
        cb = self.ui.comboBoxDropDown_LogLevel
        cb.blockSignals(True)
        cb.clear()
        cb.addItems(list(LOG_OPTIONS.keys()))
        current_name = getattr(self, "textLogLevel", LOG_DEFAULT_NAME)
        label = LOG_OPTIONS_INV.get(current_name, LOG_DEFAULT_LABEL)
        idx = cb.findText(label)
        if idx >= 0:
            cb.setCurrentIndex(idx)
        else:
            cb.setCurrentIndex(cb.findText(LOG_DEFAULT_LABEL))
        cb.blockSignals(False)

        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: User Interface drop downs initialized."
        )

        # Configure the Buttons (enabled/disabled)
        # ----------------------------------------

        # Text display buttons
        self.ui.pushButton_ReceiverStartStop.setText("Start")
        self.ui.pushButton_ReceiverStartStop.setEnabled(True)
        self.ui.pushButton_SendFile.setEnabled(False)
        self.ui.pushButton_ReceiverClearOutput.setEnabled(True)
        self.ui.pushButton_ReceiverSave.setEnabled(True)

        # Serial Buttons
        self.ui.pushButton_SerialOpenClose.setText("Open")
        self.ui.pushButton_SerialScan.setEnabled(True)
        self.ui.pushButton_SerialOpenClose.setEnabled(False)
        self.ui.pushButton_ToggleDTR.setEnabled(False)
        self.ui.pushButton_ResetESP.setEnabled(False)
        if USE_BLE:
            self.ui.pushButton_toBLE.setEnabled(True)
        else:
            self.ui.pushButton_toBLE.setEnabled(False)

        # BLE Buttons
        if USE_BLE:
            self.ui.pushButton_BLEScan.setEnabled(True)
            self.ui.pushButton_BLEConnect.setEnabled(False)
            self.ui.pushButton_toSerial.setEnabled(True)
        else:
            self.ui.pushButton_BLEScan.setEnabled(False)
            self.ui.pushButton_BLEConnect.setEnabled(False)
            self.ui.pushButton_toSerial.setEnabled(True)
        
        if USE_BLUETOOTHCTL:
            self.ui.pushButton_BLEPair.setEnabled(True)
            self.ui.pushButton_BLETrust.setEnabled(True)
            self.ui.pushButton_BLEStatus.setEnabled(True)
        else:
            self.ui.pushButton_BLEPair.setEnabled(False)
            self.ui.pushButton_BLETrust.setEnabled(False)
            self.ui.pushButton_BLEStatus.setEnabled(False)

        # Chart Buttons
        self.ui.pushButton_ChartStartStop.setText("Start")
        self.ui.pushButton_ChartStartStop.setEnabled(True)
        self.ui.pushButton_ChartClear.setEnabled(True)
        self.ui.pushButton_ChartSave.setEnabled(True)
        self.ui.pushButton_ChartSaveFigure.setEnabled(True)

        # Indicator Buttons
        self.ui.pushButton_IndicatorStartStop.setEnabled(True)

        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: User Interface buttons initialized."
        )

        # Plotter
        # ----------------------------------------
        # Create user interface hook for chart plotting
        self.chart = QChart(parent=self, ui=self.ui)                           # create chart user interface object

        # Signals from Main to Chart-UI
        self.mtocRequest.connect(                           self.chart.on_mtocRequest) # connect mtoc request to worker
        self.ui.pushButton_ChartStartStop.clicked.connect(  self.chart.on_pushButton_ChartStartStop)
        self.ui.pushButton_ChartPause.clicked.connect(      self.chart.on_pushButton_ChartPause)
        self.ui.pushButton_ChartClear.clicked.connect(      self.chart.on_pushButton_ChartClear)
        self.ui.pushButton_ChartSave.clicked.connect(       self.chart.on_pushButton_ChartSave)
        self.ui.pushButton_ChartSaveFigure.clicked.connect( self.chart.on_pushButton_ChartSaveFigure)

        self.ui.comboBoxDropDown_DataSeparator.currentIndexChanged.connect(self.chart.on_comboBox_DataSeparator)

        # Signals from Chart-UI to Main
        self.chart.plottingRunning.connect(                 self.handle_ReceiverRunning)
        self.chart.logSignal.connect(                       self.handle_log)   # connect log messages to Serial UI


        # Done with Plotter
        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Plotter initialized."
        )

        # Serial
        # ----------------------------------------

        # Create user interface hook for Serial
        self.serial = QSerial(parent=self, ui=self.ui)                         # create serial user interface object
 
        # Signals from mainWindow to Serial (UI
        self.mtocRequest.connect(                           self.serial.on_mtocRequest) # connect mtoc request to worker
        # Signals handled elsewhere:
        #   sendFileRequest
        #   sendTextRequest
        #   sendLineRequest
        #   sendLinesRequest
        #   runMonitoringRequest

        # Signals from Serial-UI to Main
        self.serial.logSignal.connect(                      self.handle_log)   # connect log messages to Serial UI

        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Serial initialized."
        )

        # BLE
        # ----------------------------------------

        if USE_BLE:
            # Create user interface hook for BLE
            self.ble = QBLESerial(parent=self, ui=self.ui)                     # create BLE UI object

            # Signals from mainWindow to QBLE (UI)
            self.mtocRequest.connect(                       self.ble.on_mtocRequest) # connect mtoc request
            # Signals handled elsewhere:
            #   sendFileRequest
            #   sendTextRequest
            #   sendLineRequest
            #   sendLinesRequest
            #   runMonitoringRequest

            # Signals from QBLE (UI) to Main
            self.ble.logSignal.connect(                     self.handle_log)   # connect log messages to Serial UI

            self.handle_log(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: BLE initialized."
            )

        # Chart Zoom
        # ----------------------------------------

        self.horizontalSlider_Zoom = self.ui.findChild(QSlider, "horizontalSlider_Zoom")
        self.horizontalSlider_Zoom.setMinimum(8)
        self.horizontalSlider_Zoom.setMaximum(MAX_ROWS)
        self.lineEdit_Zoom = self.ui.findChild(QLineEdit, "lineEdit_Horizontal_Zoom")

        # Monitoring
        # ----------------------------------------

        self.ui.pushButton_ReceiverStartStop.clicked.connect(  self.on_pushButton_ReceiverStartStop) # start/stop serial receive
        self.ui.pushButton_ReceiverSave.clicked.connect(       self.on_pushButton_ReceiverSave) # save text from serial receive window
        self.ui.pushButton_ReceiverClearOutput.clicked.connect(self.on_pushButton_ReceiverClearOutput) # clear serial receive window
        self.ui.pushButton_SendFile.clicked.connect(           self.on_pushButton_SendFile) # send text from a file to serial port

        # Text Input
        # ----------------------------------------

        self.ui.lineEdit_Text.setEnabled(False)
        self.ui.pushButton_SendFile.setEnabled(False)

        # Text Display
        # ----------------------------------------

        self.horizontalSlider = self.ui.findChild(QSlider, "horizontalSlider_History")
        self.horizontalSlider.setMinimum(50)
        self.horizontalSlider.setMaximum(MAX_TEXT_LINES)
        self.horizontalSlider.setValue(int(self.maxlines))

        # Debounce apply of history limit
        self.historySliderTimer = QTimer(self)
        self.historySliderTimer.setSingleShot(True)
        self.historySliderTimer.setInterval(250)                               # ms
        self.historySliderTimer.timeout.connect(self.applyHistoryLimit)

        self.lineEdit_History = self.ui.findChild(QLineEdit, "lineEdit_Vertical_History")
        self.lineEdit_History.setText(str(self.maxlines))

        self.text_widget = self.ui.plainTextEdit_Text

        self.text_widget.setStyleSheet(f"background-color: {BACKGROUNDCOLOR};")

        # Modify text display window on serial text display
        self.text_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.text_widget.setLineWrapMode(NO_WRAP)                              # no wrapping for better performance
        self.text_widget.setReadOnly(True)                                     # prevent user edits
        self.text_widget.setWordWrapMode(NO_WORDWRAP)                          # no wrapping for better performance
        self.text_widget.setUndoRedoEnabled(False)
        self.text_widget.setMaximumBlockCount(self.maxlines)

        # Modify TEXT display scrollbar behavior
        self.text_widget.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.text_scroll_bar = self.text_widget.verticalScrollBar()
        self.text_scroll_bar.setSingleStep(1)                                  # highest resolution for scrolling
        self.text_scroll_bar.setPageStep(20)                                   # defines how much a full page scroll moves
        self.text_scroll_bar.setValue(self.text_scroll_bar.maximum())          # scroll to bottom

        # Set cursor to end of text display for auto scrolling
        textCursor = self.text_widget.textCursor()
        textCursor.movePosition(MOVE_END)
        self.text_widget.setTextCursor(textCursor)
        self.text_widget.ensureCursorVisible()

        self.recordingFileName = ""
        self.recordingFile = None

        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Text display initialized."
        )

        # end/RX wiring follows transport readiness
        # ----------------------------------------

        self.txrxReady_wired_to_ble = False
        self.txrxReady_wired_to_serial = False

        # combined throughput stats
        self.rx_serial = 0.0
        self.tx_serial = 0.0
        self.rx_ble    = 0.0
        self.tx_ble    = 0.0
        self.pps       = 0.01

        # React to connection state changes
        self.serial.txrxReadyChanged.connect(self.update_sendreceive_targets_serial)
        if USE_BLE:
            self.ble.txrxReadyChanged.connect(self.update_sendreceive_targets_ble)

        # Receive per-transport throughput and aggregate in main
        try:
            self.serial.throughputUpdate.connect(self.on_throughputUpdate)
        except Exception:
            pass
        if USE_BLE:
            try:
                self.ble.throughputUpdate.connect(self.on_throughputUpdate)
            except Exception:
                pass
        try:
            self.chart.throughputUpdate.connect(self.on_throughputUpdate)
        except Exception:
            pass


        self.ui.stackedWidget_BLE_Serial.setCurrentIndex(0)                    # start with serial tab visible

        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Receiver connected."
        )

        # USB device connect/disconnect
        # ----------------------------------------
        self.usbmonitor = QUSBMonitor(parent=self, ui=self.ui)                 # create USB monitor user interface object

        self.usbmonitor.usb_event_detected.connect(         self.serial.on_usb_event_detected)
        self.usbmonitor.logSignal.connect(                  self.handle_log)

        self.mtocRequest.connect(                           self.usbmonitor.on_mtocRequest)

        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: USB monitor initialized."
        )

        # Indicator
        # ----------------------------------------

        # for now disable the indicator page
        indicator_page: QWidget = self.tabs.findChild(QWidget, 'Indicator')
        if indicator_page is not None:
            idx = self.tabs.indexOf(indicator_page)
            if idx != -1:
                self.tabs.setTabVisible(idx, False)

        if USE_3DPLOT:
            self.ui.ThreeD.setEnabled(True)
        else:
            self.ui.ThreeD.setEnabled(False)

        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Indicator initialized."
        )

        # Main Program
        # ----------------------------------------

        # Signals from mainWindow to itself
        # ----------------------------------------
        self.runMonitoringRequest.connect(                  self.handle_ReceiverRunning)

        # Interface Elements Connections
        # ----------------------------------------

        # Serial Buttons
        self.ui.pushButton_SerialScan.clicked.connect(      self.serial.on_pushButton_SerialScan) # scan for ports
        self.ui.pushButton_SerialOpenClose.clicked.connect( self.serial.on_pushButton_SerialOpenClose) # open/close serial port
        self.ui.pushButton_ToggleDTR.clicked.connect(       lambda:self.serial.toggleDTRRequest.emit()) # toggle DTR
        self.ui.pushButton_ResetESP.clicked.connect(        lambda:self.serial.espResetRequest.emit()) # reset ESP32

        # BLE Buttons
        if USE_BLE:
            # Switch from Serial to BLE
            self.ui.pushButton_toBLE.clicked.connect(       self.on_pushButton_toBLE) # switch to BLE tab
            self.ui.pushButton_toBLE.setIcon(ble_icon)
            # BLE action buttons
            self.ui.pushButton_BLEScan.clicked.connect(     self.ble.on_pushButton_BLEScan)
            self.ui.pushButton_BLEConnect.clicked.connect(  self.ble.on_pushButton_BLEConnect)
        # BLUETOOTHCTL buttons
            if USE_BLUETOOTHCTL:
                self.ui.pushButton_BLEPair.clicked.connect( self.ble.on_pushButton_BLEPair)
                self.ui.pushButton_BLETrust.clicked.connect(self.ble.on_pushButton_BLETrust)
                self.ui.pushButton_BLEStatus.clicked.connect(self.ble.on_pushButton_BLEStatus)

        # Switch from BLE to Serial
        self.ui.pushButton_toSerial.clicked.connect(        self.on_pushButton_toSerial) # switch to Serial tab
        self.ui.pushButton_toSerial.setIcon(usb_icon)

        # Radio Button Record
        self.ui.checkBox_ReceiverRecord.toggled.connect(    self.on_receiverRecord) # record incoming data to file
        self.ui.checkBox_DisplayBLE.toggled.connect(        self.on_displayBLE) # record incoming data to file
        self.ui.checkBox_DisplaySerial.toggled.connect(     self.on_displaySerial) # record incoming data to file

        # Serial ComboBoxes
        self.ui.comboBoxDropDown_SerialPorts.currentIndexChanged.connect(    self.serial.on_comboBoxDropDown_SerialPorts) # user changed serial port
        self.ui.comboBoxDropDown_BaudRates.currentIndexChanged.connect(      self.serial.on_comboBoxDropDown_BaudRates) # user changed baud rate
        self.ui.comboBoxDropDown_LineTermination.currentIndexChanged.connect(self.serial.on_comboBoxDropDown_LineTermination) # User changed line termination

        # BLE ComboBoxes
        if USE_BLE:
            self.ui.comboBoxDropDown_Device.currentIndexChanged.connect(     self.ble.on_comboBoxDropDown_BLEDevices)
            self.ui.comboBoxDropDown_LineTermination_BLE.currentIndexChanged.connect(self.ble.on_comboBoxDropDown_LineTermination)

        # Log ComboBoxes
        self.ui.comboBoxDropDown_LogLevel.currentIndexChanged.connect(self.on_changeLoglevel)

        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Serial and BLE signals connected."
        )

        # Text History Length
        self.horizontalSlider.valueChanged.connect(         self.on_HistorySliderValueChanged)
        self.horizontalSlider.sliderReleased.connect(       self.on_HistorySliderReleased) # add
        self.lineEdit_History.returnPressed.connect(        self.on_HistoryLineEditChanged)

        # Chart Zoom Slider
        self.horizontalSlider_Zoom.valueChanged.connect(    self.chart.on_ZoomSliderChanged)
        self.horizontalSlider_Zoom.sliderReleased.connect(  self.chart.on_ZoomSliderReleased)
        self.lineEdit_Zoom.returnPressed.connect(           self.chart.on_ZoomLineEditChanged)

        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Slider signals connected."
        )

        # Text Input
        # ----------------------------------------
        #   User hits up/down arrow in send lineEdit
        self.shortcutUpArrow   = QShortcut(KEY_UP, self.ui.lineEdit_Text,    self.on_upArrowPressed)
        self.shortcutDownArrow = QShortcut(KEY_DOWN, self.ui.lineEdit_Text,  self.on_downArrowPressed)

        # Return key pressed in send lineEdit
        self.ui.lineEdit_Text.returnPressed.connect(        self.on_carriageReturnPressed) # send text as soon as enter key is pressed

        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Text entry signals connected."
        )

        # Menu Bar
        # ----------------------------------------
        # Connect the action_about action to the show_about_dialog slot
        self.ui.action_About.triggered.connect(             self.show_about_dialog)
        self.ui.action_Help.triggered.connect(              self.show_help_dialog)
        self.ui.action_Profile.triggered.connect(           self.on_mtocRequest)
        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Menu initialized."
        )
        
        # Status Bar
        # ----------------------------------------
        self.statusTimer = QTimer(self)
        self.statusTimer.timeout.connect(                   self.on_resetStatusBar)
        self.statusTimer.start(10000)                                          # trigger every 10 seconds
        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Status Bar initialized."
        )
        
        # Display UI
        # ----------------------------------------
        self.show()
        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Displaying User Interface."
        )

    # ==========================================================================
    # User Interface Functions General
    # ==========================================================================

    @pyqtSlot()
    def on_mtocRequest(self):
        """
        Produce profiling log message.

        For selected functions, during runtime we measure their execution time.
        If PROFILEME is False, this will report 0.
        """

        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Obtaining profiling info."
        )
                
        if USE_BLE:
            ble_status = "running" if self.ble.receiverIsRunning else "off"
        else:
            ble_status = "off"

        log_message = textwrap.dedent(f"""
            main Window
            =============================================================
            monitoring is                    {"on" if self.isMonitoring else "off"}.
            plotting is                      {"on" if self.isPlotting else "off"}.
            serial worker is                 {"running" if self.serial.receiverIsRunning else "off"}.
            ble worker is                    {ble_status}.
        """)
        self.handle_log(-1, log_message)

        # Emit the mtocRequest signal for other components to respond
        self.mtocRequest.emit()

    @pyqtSlot()
    def on_logSignal(self, level: int, message: str) -> None:
        """Handle log messages from the logger."""
        self.handle_log(level, message)

    @profile
    def handle_log(self, level: int, message: str) -> None:
        """
        Handle log messages from the logger.
        We log to console and to the dedicated log window.
        level: -2 = forced display, disregarding log level
               -1 = mtoc request
               0..50 = logging levels
        message: the log message to display
        """
        # Console
        # ----------------------------------------

        if level > -1:
            self.logger.log(level, message)

        # Logwindow
        # ----------------------------------------

        if level == -1:
            # mtoc request
            #
            self.log_widget.setUpdatesEnabled(False)                           # disable repaint
            prev_pos  = self.log_scroll_bar.value()                            # remember position
            at_bottom = prev_pos >= (self.log_scroll_bar.maximum() - self.log_scroll_bar.pageStep()) # are we watching the latest log
            text_cursor = QTextCursor(self.log_widget.document())              # create text cursor
            text_cursor.movePosition(MOVE_END)                                 # move to end
            text_cursor.insertText(message)                                    # insert text at end
            # Now restore the scrollbar (auto-scroll only if view was at bottom)
            if at_bottom:
                self.log_scroll_bar.setValue(self.log_scroll_bar.maximum())
            else:
                self.log_scroll_bar.setValue(prev_pos)
            self.log_widget.setUpdatesEnabled(True)

        elif level >= self.logger.getEffectiveLevel() or level ==-2:
            # regular log message > -1, 
            # forced display, disregarding log level== -2
            #
            # Format the message
            if level>-1:
                try:
                    level_name = logging.getLevelNamesMapping()[level]         # Python 3.11+
                except AttributeError:
                    level_name = logging.getLevelName(level)                   # Python < 3.11 fallback
            else:
                level_name = "FORCED"

            formatted  = f"[{level_name:<8.8}] {message}\n"

            self.log_widget.setUpdatesEnabled(False)                           # disable repaint
            prev_pos  = self.log_scroll_bar.value()
            at_bottom = prev_pos >= (self.log_scroll_bar.maximum() - self.log_scroll_bar.pageStep())
            text_cursor = QTextCursor(self.log_widget.document())              # create new cursor
            text_cursor.movePosition(MOVE_END)
            text_cursor.insertText(formatted)
            if at_bottom:
                self.log_scroll_bar.setValue(self.log_scroll_bar.maximum())
            else:
                self.log_scroll_bar.setValue(prev_pos)
            self.log_widget.setUpdatesEnabled(True)

    @pyqtSlot()
    def on_resetStatusBar(self):
        """Reset the status bar message to default with current date and time."""
        now = datetime.now()
        formatted_date_time = now.strftime("%Y-%m-%d %H:%M")
        self.statusBar().showMessage("Serial User Interface. " + formatted_date_time)

    @pyqtSlot()
    def show_about_dialog(self):
        """Show an 'About' dialog with program information."""
        # Information to be displayed
        info_text = "Serial Terminal & Plotter\nVersion: {}\nAuthor: {}\n{}".format(VERSION, AUTHOR, DATE)
        # Create and display the MessageBox
        QMessageBox.about(self, "About Program", info_text)                    # create and display the MessageBox
        self.show()

    @pyqtSlot()
    def show_help_dialog(self):
        """Show a 'Help' dialog with readme content."""
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
        text_edit.setReadOnly(True)                                            # make the text edit read-only
        layout.addWidget(text_edit)

        dialog_width = 1280                                                    # example width
        dialog_height = 800                                                    # example height
        dialog.resize(dialog_width, dialog_height)

        # Show the dialog
        try:
            dialog.exec()
        except AttributeError:
            dialog.exec_()

    @pyqtSlot(int)
    def on_tab_change(self, index: int) -> None:
        """
        Respond to tab change event
        """
        tab_name = self.tabs.tabText(index)

        if tab_name == "Monitor":
            self.text_scroll_bar.setValue(self.text_scroll_bar.maximum())
            self.log_scroll_bar.setValue(self.log_scroll_bar.maximum())

        elif tab_name == "Plotter":
            pass

        elif tab_name == "Indicator":
            pass

        else:
            self.handle_log(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Unknown tab name: {tab_name}"
            )

    @pyqtSlot()
    def on_pushButton_toSerial(self) -> None:
        """
        Switch to Serial
        """
        self.ui.stackedWidget_BLE_Serial.setCurrentIndex(0)
        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Serial."
        )
        self.ui.statusBar().showMessage('Serial.', 2000)

    @pyqtSlot()
    def on_pushButton_toBLE(self) -> None:
        """ 
        Switch to BLE
        """
        if not USE_BLE:
            self.handle_log(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: BLE is not enabled in config."
            )
            self.ui.statusBar().showMessage('BLE is not enabled in config.', 2000)
            return

        self.ui.stackedWidget_BLE_Serial.setCurrentIndex(1)
        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: BLE."
        )
        self.ui.statusBar().showMessage('BLE.', 2000)

    @pyqtSlot()
    def showEvent(self, event):
        """Qt calls this when the User Interface window is shown."""
        super().showEvent(event)
        if USE_FASTPLOTLIB:
            QTimer.singleShot(200, self.chart.fpl_figure_init)
        else:
            QTimer.singleShot(200, self.chart.pg_figure_init)   

    @pyqtSlot()
    def closeEvent(self, event):
        """
        Respond to window close event.
        Close the serial port, stop the serial thread and the chart update timer.
        """
        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Finishing workers..."
        )

        disconnect(self.mtocRequest,             self.serial.on_mtocRequest)
        disconnect(self.mtocRequest,             self.chart.on_mtocRequest)
        disconnect(self.mtocRequest,             self.usbmonitor.on_mtocRequest)
        
        disconnect(self.sendFileRequest,         self.serial.sendFileRequest)
        disconnect(self.sendTextRequest,         self.serial.sendTextRequest)
        disconnect(self.sendLineRequest,         self.serial.sendLineRequest)
        disconnect(self.sendLinesRequest,        self.serial.sendLinesRequest)

        if USE_BLE:
            disconnect(self.mtocRequest,            self.ble.on_mtocRequest)

            disconnect(self.sendFileRequest,        self.ble.sendFileRequest)
            disconnect(self.sendTextRequest,        self.ble.sendTextRequest)
            disconnect(self.sendLineRequest,        self.ble.sendLineRequest)
            disconnect(self.sendLinesRequest,       self.ble.sendLinesRequest)

        self.throughputStopRequest.emit()
        self.rxStopRequest.emit()
        QCoreApplication.processEvents()

        self.usbmonitor.cleanup()                                              # stop the USB monitor thread
        self.serial.cleanup()                                                  # close serial port and stop thread
        if USE_BLE: 
            self.ble.cleanup()                                                 # close BLE connection and stop thread
        self.chart.cleanup()                                                   # stop the chart timer

        event.accept()                                                         # accept the close event to proceed closing the application

    @pyqtSlot(float, float, str)
    def on_throughputUpdate(self, rx: float, tx: float, source: str) -> None:
        """Report total throughput from Serial and BLE"""
        if source == "serial":
            self.rx_serial, self.tx_serial = rx, tx
        elif source == "ble":
            self.rx_ble, self.tx_ble = rx, tx
        elif source == "chart":
            self.pps = tx                                                      # points per second

        self.total_rx = self.rx_serial + self.rx_ble
        self.total_tx = self.tx_serial + self.tx_ble

        # # poor man's low pass
        # self.total_rx = 0.5 * self.total_rx + 0.5 * total_rx
        # self.total_tx = 0.5 * self.total_tx + 0.5 * total_tx

        # Format like before, but combined
        if self.total_rx > 1_000_000 or self.total_tx > 1_000_000:
            text = f"Rx:{self.total_rx/1048576.:4,.2f}  Tx:{self.total_tx/1048576.:4,.2f} MB/s "
        elif self.total_rx > 1_000 or self.total_tx > 1_000:
            text = f"Rx:{self.total_rx/1024.:4,.1f}  Tx:{self.total_tx/1024.:4,.1f} kB/s "
        else:
            text = f"Rx:{self.total_rx:4,.0f}  Tx:{self.total_tx:4,.0f} B/s "

        if self.pps > 1_000_000:
            text += f"{self.pps/1048576.:5,.2f} MP/s"
        elif self.pps > 1_000:
            text += f"{self.pps/1024.:5,.1f} kP/s"
        else:
            text += f"{self.pps:5,.0f} P/s"
        self.ui.label_throughput.setText(text.replace(",", "_"))

    # ==========================================================================
    # User Interface Functions: Monitor related
    # ==========================================================================

    """
        on_carriageReturnPressed             transmit text from UI to serial TX line
        on_upArrowPressed                    recall previous line of text from serial TX line buffer
        on_downArrowPressed                  recall next line of text from serial TX line buffer
        on_pushButton_SendFile               send file to serial port
        on_pushButton_ReceiverClearOutput    clear the text display window
        on_pushButton_ReceiverStartStop      start/stop serial text display and throughput timer
        on_pushButton_ReceiverSave           save text from display window into text file
        on_record                            start/stop recording of data
        on_HistoryLineEditChanged            change the number of lines in the text display window (by entering number)
        on_HistorySliderValueChanged         change the number of lines in the text display window (with slider)
    """

    @pyqtSlot()
    def on_upArrowPressed(self) -> None:
        """
        Handle special keys on lineEdit: UpArrow
        """
        if not self.lineSendHistory:                                           # check if history is empty
            self.ui.lineEdit_Text.setText("")
            self.ui.statusBar().showMessage("No commands in history.", 2000)
            return

        if self.lineSendHistoryIndx > 0:
            self.lineSendHistoryIndx -= 1
        else:
            self.lineSendHistoryIndx = 0                                       # stop at oldest command

        self.ui.lineEdit_Text.setText(self.lineSendHistory[self.lineSendHistoryIndx])
        self.ui.statusBar().showMessage("Command retrieved from history.", 2000)
        
    @pyqtSlot()
    def on_downArrowPressed(self) -> None:
        """
        Handle special keys on lineEdit: DownArrow
        """
        if not self.lineSendHistory:
            self.ui.lineEdit_Text.setText("")
            self.ui.statusBar().showMessage("No commands in history.", 2000)
            return
    
        if self.lineSendHistoryIndx < len(self.lineSendHistory) - 1:
            self.lineSendHistoryIndx += 1
            self.ui.lineEdit_Text.setText(self.lineSendHistory[self.lineSendHistoryIndx])
        else:
            self.lineSendHistoryIndx = len(self.lineSendHistory)               # move past last entry
            self.ui.lineEdit_Text.clear()
            self.ui.statusBar().showMessage("Ready for new command.", 2000)

    @pyqtSlot()
    def on_carriageReturnPressed(self) -> None:
        """
        Transmitting text from UI to serial TX line
        """

        if DEBUGKEYINPUT:
            tic = time.perf_counter()
            self.handle_log(logging.DEBUG, 
                f"[{self.instance_name[:15]:<15}]: Text entering detected at {tic}"
            )

        text = self.ui.lineEdit_Text.text()                                    # obtain text from send input window

        # Line Terminator "\n"  or "\r\n"
        #  - "\n" when user selected "\n" in drop down 
        #  - "\r\n" when ("\r\n" or "" or "\r")
        eol = self.textLineTerminator if self.textLineTerminator not in {b"", b"\r"} else b"\r\n"

        self.runMonitoringRequest.emit(True)            

        if not text:
            # No text provided, empty line

            text_bytearray = eol
            self.handle_log(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Sending empty line"
            )

        else:
            # Send text provided by user and keep history

            self.lineSendHistory.append(text)                                  # keep history of previously sent commands
            self.lineSendHistoryIndx = len(self.lineSendHistory)               # reset history pointer
        
            try:
                text_bytearray = text.encode(self.encoding, errors="replace") + eol # add line termination
            except Exception as e:
                self.handle_log(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Encoding error: {e}"
                )
                return

        if DEBUGKEYINPUT:
            self.handle_log(logging.DEBUG, 
                f"[{self.instance_name[:15]:<15}]: Text ready to emit {time.perf_counter()}"
            )

        self.sendTextRequest.emit(text_bytearray)                              # send text to serial or BLE TX line

        self.ui.lineEdit_Text.clear()
        self.ui.statusBar().showMessage("Text sent.", 2000)

        if DEBUGKEYINPUT:
            toc = time.perf_counter()
            self.handle_log(logging.DEBUG, 
                f"[{self.instance_name[:15]:<15}]: Text emission completed in {1000*(toc - tic):.2f} ms."
            )

    @pyqtSlot()
    def on_pushButton_SendFile(self) -> None:
        """
        Transmitting file to serial TX line
        """
        stdFileName = (
            QStandardPaths.writableLocation(DOCUMENTS)
            + "/Serial.txt"
        )

        file_path = select_file(
            stdFileName=stdFileName,
            filter="Text files (*.txt *.csv);;Binary files (*.bin *.dat);;All files (*)",
            suffix="",
            do_text="Load",
            cancel_text="Cancel",
            parent=self.ui
        )

        if file_path:
            self.runMonitoringRequest.emit(True)
            self.sendFileRequest.emit(file_path)

        self.ui.statusBar().showMessage('File sent.', 2000)


    @pyqtSlot()
    def on_pushButton_ReceiverClearOutput(self) -> None:
        """
        Clearing text display window
        """

        linesBufferTimerSerial_was_active     = False
        byteArrayBufferTimerSerial_was_active = False
        htmlBufferTimerSerial_was_active      = False
        linesBufferTimerBLE_was_active        = False
        byteArrayBufferTimerBLE_was_active    = False
        htmlBufferTimerBLE_was_active         = False

        if self.serial.linesBufferTimer.isActive():
            self.serial.linesBufferTimer.stop()
            linesBufferTimerSerial_was_active = True
        if self.serial.byteArrayBufferTimer.isActive():
            self.serial.byteArrayBufferTimer.stop()
            byteArrayBufferTimerSerial_was_active = True
        if self.serial.htmlBufferTimer.isActive():
            self.serial.htmlBufferTimer.stop()
            htmlBufferTimerSerial_was_active = True

        self.serial.linesBuffer.clear()
        self.serial.byteArrayBuffer.clear()
        self.serial.htmlBuffer = ""

        if USE_BLE:
            if self.ble.linesBufferTimer.isActive():
                self.ble.linesBufferTimer.stop()
                linesBufferTimerBLE_was_active = True
            if self.ble.byteArrayBufferTimer.isActive():
                self.ble.byteArrayBufferTimer.stop()
                byteArrayBufferTimerBLE_was_active = True
            if self.ble.htmlBufferTimer.isActive():
                self.ble.htmlBufferTimer.stop()
                htmlBufferTimerBLE_was_active = True

            self.ble.linesBuffer.clear()
            self.ble.byteArrayBuffer.clear()
            self.ble.htmlBuffer = ""

        self.text_widget.clear()

        if linesBufferTimerSerial_was_active:
            self.serial.linesBufferTimer.start()
        if byteArrayBufferTimerSerial_was_active:
            self.serial.byteArrayBufferTimer.start()
        if htmlBufferTimerSerial_was_active:
            self.serial.htmlBufferTimer.start()

        if linesBufferTimerBLE_was_active:
            self.ble.linesBufferTimer.start()
        if byteArrayBufferTimerBLE_was_active:
            self.ble.byteArrayBufferTimer.start()
        if htmlBufferTimerBLE_was_active:
            self.ble.htmlBufferTimer.start()

        self.handle_log(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Text and Log display cleared."
        )
        self.ui.statusBar().showMessage("Text Display Cleared.", 2000)

    @pyqtSlot()
    def on_pushButton_ReceiverStartStop(self) -> None:
        """
        Start/Stop Receiver(s) (Serial and/or BLE)
        """
        if self.ui.pushButton_ReceiverStartStop.text() == "Start":
            # START text display
            self.runMonitoringRequest.emit(True)
            self.handle_log(logging.DEBUG,
                f"[{self.instance_name[:15]:<15}]: Turning text display on."
            )
            self.ui.statusBar().showMessage("Text Display Starting", 2000)
            
        else:
            # STOP text display
            self.runMonitoringRequest.emit(False)
            self.handle_log(logging.DEBUG, 
                f"[{self.instance_name[:15]:<15}]: Turning text display off."
            )
            self.ui.statusBar().showMessage('Text Display Stopping.', 2000)            

    @pyqtSlot()
    def on_pushButton_ReceiverSave(self) -> None:
        """
        Saving text from display window into text file
        This is not the same as enable recording to file
        """
        stdFileName = (
            QStandardPaths.writableLocation(DOCUMENTS)
            + "/Serial.txt"
        )

        file_path = select_file(
            stdFileName=stdFileName,
            filter="Text files (*.txt);;Binary files (*.bin *.dat)",
            suffix="txt",
            do_text="Save",
            cancel_text="Cancel",
            parent=self.ui
        )

        if file_path is None:
            return

        if file_path.exists():                                                 # check if file already exists
            mode = confirm_overwrite_append(offer_append=True)
            if mode == "c":                                                    # cancel
                self.handle_log(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Save cancelled."
                )
                return
        else:
            mode = "w"                                                         # default to write mode if file doesn't exist

        try:
            # check if fname is valid, user can select cancel
            with open(file_path, mode, encoding=self.encoding) as f:
                f.write(self.text_widget.toPlainText())
            self.handle_log(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Serial Monitor text saved to {file_path.name}."
            )
            self.ui.statusBar().showMessage("Serial Monitor text saved.", 2000)
        except Exception as e:
            self.handle_log(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Error saving Serial Monitor text to {file_path.name}: {e}"
            )
            self.ui.statusBar().showMessage(f"Error saving Serial Monitor text: {e}", 5000)

    @pyqtSlot()
    def on_receiverRecord(self) -> None:
        self.record = self.ui.checkBox_ReceiverRecord.isChecked()
        if self.record:
            if self.recordingFileName == "":
                stdFileName = (
                    QStandardPaths.writableLocation(DOCUMENTS)
                    + "/Serial.txt"
                ) 
            else:
                stdFileName = self.recordingFileName

            file_path = select_file(
                stdFileName=stdFileName,
                filter="Text files (*.txt)",
                suffix="txt",
                do_text="Record",
                cancel_text="Cancel",
                parent=self.ui
            )

            if not file_path:
                self.record = False
                self.ui.checkBox_ReceiverRecord.setChecked(self.record)
                # keep QSerial in sync
                self.serial.record = False
                self.serial.recordingFile = None
                self.serial.recordingFileName = ""
                if USE_BLE:
                    self.ble.record = False
                    self.ble.recordingFile = None
                    self.ble.recordingFileName = ""
                return
            
            if file_path.exists():                                             # Check if file already exists
                mode = confirm_overwrite_append(offer_append=True)
                if mode == "c":                                                # Cancel
                    self.record = False
                    self.ui.checkBox_ReceiverRecord.setChecked(self.record)
                    self.serial.record = False
                    self.serial.recordingFile = None
                    self.serial.recordingFileName = ""
                    if USE_BLE:
                        self.ble.record = False
                        self.ble.recordingFile = None
                        self.ble.recordingFileName = ""
                    return
                else:
                    mode = mode + "b"                                          # append or overwrite in binary mode
            else:
                mode = "wb"                                                    # default to write mode if file doesn't exist

            try:    
                self.recordingFile = open(file_path, mode)
                mode_text = "write" if mode == "wb" else "append"
                self.handle_log(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Recording to file {file_path.name} in mode {mode_text}."
                )
                self.serial.record = True
                self.serial.recordingFile = self.recordingFile
                self.serial.recordingFileName = str(file_path)
                if USE_BLE:
                    self.ble.record = True
                    self.ble.recordingFile = self.recordingFile
                    self.ble.recordingFileName = str(file_path)
            except Exception as e:
                self.handle_log(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Could not open file {file_path.name} in mode {mode}: {e}."
                )
                self.record = False
                self.ui.checkBox_ReceiverRecord.setChecked(self.record)
                self.serial.record = False
                self.serial.recordingFile = None
                self.serial.recordingFileName = ""
                if USE_BLE:
                    self.ble.record = False
                    self.ble.recordingFile = None
                    self.ble.recordingFileName = ""
        else:
            if self.recordingFile:
                try:
                    self.recordingFile.flush()
                    self.recordingFile.close()
                    self.handle_log(logging.INFO, 
                        f"[{self.instance_name[:15]:<15}]: Recording to file {self.recordingFile.name} stopped."
                    )
                except Exception as e:
                    self.handle_log(logging.ERROR, 
                        f"[{self.instance_name[:15]:<15}]: Could not close file {self.recordingFile.name}: {e}."
                    )
                self.recordingFile = None
                self.serial.record = False
                self.serial.recordingFile = None
                self.serial.recordingFileName = ""
                if USE_BLE:
                    self.ble.record = False
                    self.ble.recordingFile = None
                    self.ble.recordingFileName = ""

    @pyqtSlot()
    def on_displayBLE(self) -> None:
        """Toggle wether to display incoming BLE data in the text window"""
        self.ble.display = self.ui.checkBox_DisplayBLE.isChecked()

    @pyqtSlot()
    def on_displaySerial(self) -> None:
        """Toggle wether to display incoming Serial data in the text window"""
        self.serial.display = self.ui.checkBox_DisplaySerial.isChecked()

    @pyqtSlot(int)
    def on_HistorySliderValueChanged(self, value: int):
        """
        Serial Terminal History Slider Handling
        This starts debounce timer
        """
        value = int(clip_value(value, 50, MAX_TEXT_LINES))
        self.lineEdit_History.setText(str(value))
        self.historySliderTimer.start()

    @pyqtSlot()
    def on_HistorySliderReleased(self):
        """Commit history slider value on release"""
        # Commit immediately on release; cancel pending debounce
        if self.historySliderTimer.isActive():
            self.historySliderTimer.stop()
        self.applyHistoryLimit()
        
    @pyqtSlot()
    def applyHistoryLimit(self):
        """
        Serial Terminal History Slider Handling
        This sets the maximum number of text line retained in the terminal display window

        Update the corresponding line edit box when the slider is moved
        """
        value = int(clip_value(self.horizontalSlider.value(), 50, MAX_TEXT_LINES))
        self.maxlines = value
        self.horizontalSlider.blockSignals(True)
        self.horizontalSlider.setValue(value)
        self.horizontalSlider.blockSignals(False)
        self.lineEdit_History.setText(str(self.maxlines))

        self.text_widget.setMaximumBlockCount(self.maxlines)                   # set maximum lines in text display

        # Propagate to sources so their flushers trim consistently
        try:
            self.serial.maxlines = int(self.maxlines)
        except Exception:
            pass
        if USE_BLE:
            try:
                self.ble.maxlines = int(self.maxlines)
            except Exception:
                pass

        self.handle_log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Terminal history set to {value}."
        )

    @pyqtSlot()
    def on_HistoryLineEditChanged(self):
        """
        Serial Terminal History Text Edit Handling
        Updates the slider and the history range when text is entered manually.
        """
        try: 
            value = int(self.lineEdit_History.text().strip())
            value = clip_value(value, 50, MAX_TEXT_LINES)
            self.maxlines = value
            self.horizontalSlider.blockSignals(True)
            self.horizontalSlider.setValue(self.maxlines)
            self.horizontalSlider.blockSignals(False)

            self.text_widget.setMaximumBlockCount(self.maxlines)               # set maximum lines in text display

            self.handle_log(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Terminal history set to {self.maxlines}."
            )

        except ValueError:
            self.lineEdit_History.setText(str(self.maxlines))
            
            self.handle_log(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Invalid value for history: {self.lineEdit_History.text()}"
            )

    @pyqtSlot(bool)
    def update_sendreceive_targets_serial(self, ready: bool) -> None:
        """Update wiring of send/receive signals to serial worker"""
        if ready:
            if self.txrxReady_wired_to_serial:
                if (self.isMonitoring or self.isPlotting):
                    self.rxStartRequest.emit()
                    self.throughputStartRequest.emit()
                return
            self.textLineTerminator = self.serial.textLineTerminator
            ok = True
            ok &= connect(self.sendFileRequest,  self.serial.sendFileRequest)
            ok &= connect(self.sendTextRequest,  self.serial.sendTextRequest)
            ok &= connect(self.sendLineRequest,  self.serial.sendLineRequest)
            ok &= connect(self.sendLinesRequest, self.serial.sendLinesRequest)
            # also wire RX and Throughput control
            ok &= connect(self.rxStartRequest,    self.serial.startTransceiverRequest)
            ok &= connect(self.rxStopRequest,     self.serial.stopTransceiverRequest)
            ok &= connect(self.throughputStartRequest,    self.serial.startThroughputRequest)
            ok &= connect(self.throughputStopRequest,     self.serial.stopThroughputRequest)
            self.txrxReady_wired_to_serial = ok
            if ok:
                self.handle_log(logging.DEBUG, 
                    f"[{self.instance_name[:15]:<15}]: TX/RX wired to Serial."
                )
                # If monitor/plotter is running, start now
                if (self.isMonitoring or self.isPlotting):
                    self.rxStartRequest.emit()
                    self.throughputStartRequest.emit()
            else:
                self.handle_log(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Could not wire TX/RX to Serial."
                )
        else:
            # Best-effort disconnect
            if not self.txrxReady_wired_to_serial:
                return
            ok = True
            ok &= disconnect(self.sendFileRequest,  self.serial.sendFileRequest)
            ok &= disconnect(self.sendTextRequest,  self.serial.sendTextRequest)
            ok &= disconnect(self.sendLineRequest,  self.serial.sendLineRequest)
            ok &= disconnect(self.sendLinesRequest, self.serial.sendLinesRequest)
            ok &= disconnect(self.rxStartRequest,   self.serial.startTransceiverRequest)
            ok &= disconnect(self.rxStopRequest,    self.serial.stopTransceiverRequest)
            ok &= disconnect(self.throughputStartRequest,   self.serial.startThroughputRequest)
            ok &= disconnect(self.throughputStopRequest,    self.serial.stopThroughputRequest)
            self.txrxReady_wired_to_serial = not ok
            if ok:
                self.handle_log(logging.DEBUG, 
                    f"[{self.instance_name[:15]:<15}]: TX disconnected from Serial."
                )
            else:
                self.handle_log(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Could not disconnect TX from Serial."
                )

    @pyqtSlot(bool)
    def update_sendreceive_targets_ble(self, ready: bool) -> None:
        """Update wiring of send/receive signals to BLE worker"""
        if ready:
            if self.txrxReady_wired_to_ble:
                if (self.isMonitoring or self.isPlotting):
                    self.rxStartRequest.emit()
                    self.throughputStartRequest.emit()
                return
            self.textLineTerminator = self.ble.textLineTerminator
            ok = True
            ok &= connect(self.sendFileRequest,  self.ble.sendFileRequest)
            ok &= connect(self.sendTextRequest,  self.ble.sendTextRequest)
            ok &= connect(self.sendLineRequest,  self.ble.sendLineRequest)
            ok &= connect(self.sendLinesRequest, self.ble.sendLinesRequest)
            # also wire RX and Throughput control
            ok &= connect(self.rxStartRequest,    self.ble.startTransceiverRequest)
            ok &= connect(self.rxStopRequest,     self.ble.stopTransceiverRequest)
            ok &= connect(self.throughputStartRequest,    self.ble.startThroughputRequest)
            ok &= connect(self.throughputStopRequest,     self.ble.stopThroughputRequest)
            self.txrxReady_wired_to_ble = ok
            if ok:
                self.handle_log(logging.DEBUG, 
                    f"[{self.instance_name[:15]:<15}]: TX/RX wired to BLE."
                )
                if (self.isMonitoring or self.isPlotting):
                    self.rxStartRequest.emit()
                    self.throughputStartRequest.emit()
            else:
                self.handle_log(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Could not wire TX/RX to BLE."
                )
        else:
            if not self.txrxReady_wired_to_ble:
                return
            ok = True
            ok &= disconnect(self.sendFileRequest,  self.ble.sendFileRequest)
            ok &= disconnect(self.sendTextRequest,  self.ble.sendTextRequest)
            ok &= disconnect(self.sendLineRequest,  self.ble.sendLineRequest)
            ok &= disconnect(self.sendLinesRequest, self.ble.sendLinesRequest)
            ok &= disconnect(self.rxStartRequest,   self.ble.startTransceiverRequest)
            ok &= disconnect(self.rxStopRequest,    self.ble.stopTransceiverRequest)
            ok &= disconnect(self.throughputStartRequest,   self.ble.startThroughputRequest)
            ok &= disconnect(self.throughputStopRequest,    self.ble.stopThroughputRequest)
            self.txrxReady_wired_to_ble = not ok
            if ok:
                self.handle_log(logging.DEBUG, 
                    f"[{self.instance_name[:15]:<15}]: TX disconnected from BLE."
                )
            else:
                self.handle_log(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Could not disconnect TX from BLE."
                )

    @pyqtSlot(int)
    def on_changeLoglevel(self, _index:int) -> None:
        """
        Change the log level based on the dropdown selection.
        """

        label = self.ui.comboBoxDropDown_LogLevel.currentText()
        level  = LOG_OPTIONS.get(label, LOG_DEFAULT_NAME)

        name = LOG_OPTIONS_INV.get(level, repr(level))
        self.handle_log(-2,
            f"[{self.instance_name[:15]:<15}]: Log level changed to {name}."
        )

        self.logger.setLevel(level)

        self.ui.statusBar().showMessage("Log level changed.", 2000)            

    # ==========================================================================
    # Receiver Functions: Handles Serial and BLE Receiver
    # ==========================================================================

    @pyqtSlot(bool)
    def handle_ReceiverRunning(self, runIt: bool) -> None:
        """
        When the users starts text display or chart display we need to
        make sure that the serial or BLE receivers is running.

        When text display is requested we connect the signals from the serial or ble worker to the display function
        When charting is requested, we connect the signals from the serial or ble worker to the charting function
        
        When either monitoring or charting is requested we start the serial/ble text receiver and the throughput calculator

        If neither of them is requested we stop the serial/ble text receiver and the throughput calculator
        """

        # Get the sender object, it can be Serial, BLE or Plotting
        sender = self.sender()

        if DEBUGRECEIVER:
            self.handle_log(logging.DEBUG,
                f"[{self.instance_name[:15]:<15}]: Handle_ReceiverRunning called by {sender} at {time.perf_counter()}."
            )

        # Plotting 
        # ----------------------------------------
        if sender == self.chart:
            if runIt and not self.isPlotting:
                # Start plotting data
                #if self.serialUseSerial:
                try:
                    self.serial.connect_receivedLines(  self.chart.on_receivedLines) # connect chart display to serial receiver signal
                    self.serial.connect_receivedData(   self.chart.on_receivedData) # connect chart display to serial receiver signal
                    self.ui.pushButton_ChartStartStop.setText("Stop")
                    self.isPlotting = runIt
                    if DEBUGRECEIVER:
                        self.handle_log(logging.DEBUG,
                            f"[{self.instance_name[:15]:<15}]: Connected signals from serial for charting at {time.perf_counter()}."
                        )
                except Exception as e:
                    self.handle_log(logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: Connect to signals for charting failed: {e}"
                    )
                if USE_BLE:
                    # if self.serialUseBLE:
                    try:
                        self.ble.connect_receivedLines( self.chart.on_receivedLines) # connect chart display to ble receiver signal
                        self.ble.connect_receivedData(  self.chart.on_receivedData) # connect chart display to ble receiver signal                            
                        self.ui.pushButton_ChartStartStop.setText("Stop")
                        self.isPlotting = runIt
                        if DEBUGRECEIVER:
                            self.handle_log(logging.DEBUG,
                                f"[{self.instance_name[:15]:<15}]: Connected signals from BLE for charting at {time.perf_counter()}."
                            )
                    except Exception as e:
                        self.handle_log(logging.ERROR,
                            f"[{self.instance_name[:15]:<15}]: Connect to signals for charting failed: {e}"
                        )
            elif not runIt and self.isPlotting:
                # Stop plotting data
                # if self.serialUseSerial:
                try:
                    self.serial.disconnect_receivedLines(self.chart.on_receivedLines) # disconnect chart display to serial receiver signal
                    self.serial.disconnect_receivedData(self.chart.on_receivedData) # disconnect chart display to serial receiver signal
                    self.ui.pushButton_ChartStartStop.setText("Start")
                    self.isPlotting = runIt
                    if DEBUGRECEIVER:
                        self.handle_log(logging.DEBUG,
                            f"[{self.instance_name[:15]:<15}]: Disconnected signals for charting from serial."
                        )
                except Exception as e:
                    self.handle_log(logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: Disconnect to signals for charting failed: {e}"
                    )
                if USE_BLE: 
                    # if self.serialUseBLE:
                    try:
                        self.ble.disconnect_receivedLines(self.chart.on_receivedLines) # disconnect chart display to ble receiver signal
                        self.ble.disconnect_receivedData(self.chart.on_receivedData) # disconnect chart display to ble receiver signal
                        self.ui.pushButton_ChartStartStop.setText("Start")
                        self.isPlotting = runIt
                        if DEBUGRECEIVER:
                            self.handle_log(logging.DEBUG,
                                f"[{self.instance_name[:15]:<15}]: Disconnected signals for charting from BLE."
                            )
                    except Exception as e:
                        self.handle_log(logging.ERROR,
                            f"[{self.instance_name[:15]:<15}]: Disconnect to signals for charting failed: {e}"
                        )
            else:
                self.handle_log( logging.WARNING,
                    f"[{self.instance_name[:15]:<15}]: Should not end up here when starting/stopping charting."
                )
 
        # Monitoring 
        # ----------------------------------------
        elif sender == self:

            if runIt and not self.isMonitoring:
                # Start displaying data in serial terminal
                #if self.serialUseSerial:
                try:
                    self.serial.connect_receivedLines(  self.serial.on_receivedLines) # connect text display to serial receiver signal
                    self.serial.connect_receivedData(   self.serial.on_receivedData) # connect text display to serial receiver signal
                    self.ui.pushButton_ReceiverStartStop.setText("Stop")
                    self.isMonitoring = runIt
                    if DEBUGRECEIVER:
                        self.handle_log(logging.DEBUG,
                            f"[{self.instance_name[:15]:<15}]: Connected Serial signals for text displaying."
                        )
                except Exception as e:
                    self.handle_log(logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: Connecting to Serial signals for text displaying failed: {e}"
                    )

                if USE_BLE:
                    # if self.serialUseBLE:
                    try:
                        self.ble.connect_receivedLines( self.ble.on_receivedLines) # connect text display to serial receiver signal
                        self.ble.connect_receivedData(  self.ble.on_receivedData) # connect text display to serial receiver signal
                        self.ui.pushButton_ReceiverStartStop.setText("Stop")
                        self.isMonitoring = runIt
                        if DEBUGRECEIVER:
                            self.handle_log(logging.DEBUG,
                                f"[{self.instance_name[:15]:<15}]: Connected BLE signals for text displaying."
                            )
                    except Exception as e:
                        self.handle_log(logging.ERROR,
                            f"[{self.instance_name[:15]:<15}]: Connecting to BLE signals for text displaying failed: {e}"
                        )

            elif not runIt and self.isMonitoring:
                # Stop displaying data in monitor
                # if self.serialUseSerial:
                try:
                    self.serial.disconnect_receivedLines(self.serial.on_receivedLines) # disconnect text display to serial receiver signal
                    self.serial.disconnect_receivedData(self.serial.on_receivedData) # disconnect text display to serial receiver signal
                    self.ui.pushButton_ReceiverStartStop.setText("Start")
                    self.isMonitoring = runIt
                    if DEBUGRECEIVER:
                        self.handle_log(logging.DEBUG,
                            f"[{self.instance_name[:15]:<15}]: Disconnected Serial signals for text displaying."
                        )
                except Exception as e:
                    self.handle_log(logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: Disconnecting from Serial signals for text displaying failed: {e}"
                    )
                if USE_BLE:
                    # if self.serialUseBLE:
                    try:
                        self.ble.disconnect_receivedLines(self.ble.on_receivedLines) # disconnect text display to serial receiver signal
                        self.ble.disconnect_receivedData(self.ble.on_receivedData) # disconnect text display to serial receiver signal
                        self.ui.pushButton_ReceiverStartStop.setText("Start")
                        self.isMonitoring = runIt
                        if DEBUGRECEIVER:
                            self.handle_log(logging.DEBUG,
                                f"[{self.instance_name[:15]:<15}]: Disconnected BLE signals for text displaying."
                            )
                    except Exception as e:
                        self.handle_log(logging.ERROR,
                            f"[{self.instance_name[:15]:<15}]: Disconnecting from BLE signals for text displaying failed: {e}"
                        )
        else:
            # Signal should not come from any widget other than serial or chart
            self.handle_log(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Should not end up here, neither monitor nor chart emitted the signal."
            )

        # Start or Stop the serial or ble receiver
        # ----------------------------------------

        if not (self.isPlotting or self.isMonitoring):
            # We are neither plotting nor displaying data, therefore we want to stop the serial worker
            self.throughputStopRequest.emit()
            self.rxStopRequest.emit()
            self.ui.lineEdit_Text.setEnabled(False)
            self.ui.pushButton_SendFile.setEnabled(False)
            
        else:
            # We are plotting or monitoring data
            self.throughputStartRequest.emit()
            self.rxStartRequest.emit()
            self.ui.lineEdit_Text.setEnabled(True)
            self.ui.pushButton_SendFile.setEnabled(True)

############################################################################################################################################
# Main 
############################################################################################################################################

if __name__ == "__main__":

    # Logging
    root_logger = logging.getLogger("SerialUI")
    root_logger.setLevel(DEBUG_LEVEL)
    sh = logging.StreamHandler()
    fmt = "[%(levelname)-8s] [%(name)-10s] %(message)s"
    sh.setFormatter(logging.Formatter(fmt))
    root_logger.addHandler(sh)
    root_logger.propagate = False
    
    app = QApplication(sys.argv)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    app.setWindowIcon(QIcon(os.path.join(base_dir, "assets", "icon_48.png")))

    win = mainWindow(logger=root_logger)

    # Adjust screen scaling
    screen = app.primaryScreen()
    scalingX = screen.logicalDotsPerInchX() / 96.0
    scalingY = screen.logicalDotsPerInchY() / 96.0
    win.resize(int(1280 * scalingX), int(800 * scalingY))

    # Adjust Window Appearance
    # sanitize_main_window_flags(win)

    win.show()
    try:
        exit_code = app.exec()                                                 # PyQt6
    except AttributeError:
        exit_code = app.exec_()                                                # PyQt5

    sys.exit(exit_code)
