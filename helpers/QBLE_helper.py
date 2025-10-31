############################################################################################################################################
# QT BLE Serial UART Helper
#
# QBLESerial:         Controller  - BLE interface to GUI, runs in main thread.
# BLEAKWorker:        Model       - Functions running in separate async thread, communication through signals and slots with QBLESerial.
#                                   This offers scanning, connecting, disconnecting, sending and receiving data.
# AsyncThread:        Model       - Custom QThread to run asyncio event loop for BLEAKWorker.
# BluetoothctlWorker: Model       - Functions through signals and slots with QBLESerial and wrapping the Bluetoothctl interface (Linux only).
#                                   This offers pairing, trusting of devices
#
# This code is maintained by Urs Utzinger
############################################################################################################################################
#
# ==============================================================================
# Configuration
# ==============================================================================
from config import (FLUSH_INTERVAL_MS,
                    BLEPIN, 
                    SERVICE_UUID, RX_CHARACTERISTIC_UUID, TX_CHARACTERISTIC_UUID,
                    USE_BLUETOOTHCTL, BLEMTUMAX, BLEMTUNORMAL, ATT_HDR, BLEMTUDEFAULT,
                    PROFILEME, DEBUGSERIAL, DEBUG_LEVEL,
                    EOL_DICT, EOL_DICT_INV, EOL_DEFAULT_BYTES,
                    DEFAULT_TEXT_LINES,
                    MAX_DATAREADYCALLS, MAX_EOL_DETECTION_TIME, MAX_EOL_FALLBACK_TIMEOUT,
                    MAX_BACKLOG_BYTES
                   )

# ==============================================================================
# Imports
# ==============================================================================
# General Imports
# ----------------------------------------
import time
import logging
import textwrap
import platform
from pathlib import Path
from typing import Any
import inspect
#
# Array operations
import numpy as np
#
# Bleak IO event 
import asyncio
#
# Bluetooth library
from bleak import BleakClient, BleakScanner, BleakError
from bleak.backends.device import BLEDevice
#
# Custom Imports
# ----------------------------------------
from helpers.IncompleteHTMLTracker import IncompleteHTMLTracker
from helpers.Qbluetoothctl_helper import BluetoothctlWrapper
from helpers.General_helper import wait_for_signal, connect, disconnect, qobject_alive
try: 
    from PyQt6.QtCore import Qt, QObject, QThread, QTimer,  pyqtSignal, pyqtSlot
    from PyQt6.QtGui import QTextCursor
    ConnectionType = Qt.ConnectionType
    PreciseTimerType = Qt.TimerType.PreciseTimer
    CursorEnd = QTextCursor.MoveOperation.End
except Exception:
    from PyQt5.QtCore import Qt, QObject, QThread, QTimer, pyqtSignal, pyqtSlot
    from PyQt5.QtGui import QTextCursor
    ConnectionType = Qt
    PreciseTimerType = QTimer.PreciseTimer
    CursorEnd = QTextCursor.End
#
# Profiling
# ----------------------------------------
try:
    profile                                                                    # provided by kernprof at runtime
except NameError:
    def profile(func):                                                         # no-op when not profiling
        return func
    
############################################################################################################################################
#
# QBLESerial interaction with Graphical User Interface
#
# This section contains routines that can not be moved to a separate thread because they interact with the QT User Interface.
#
# This is the Controller (Presenter)  of the Model - View - Controller (MVC) architecture.
#
############################################################################################################################################

class QBLESerial(QObject):
    """
    Object providing functionality between User Interface and BLE Serial Worker.
    This interface must run in the main thread and interacts with user.

    Signals (to be emitted by UI and picked up by BLE Worker)
        scanDevicesRequest                  request that BLE Worker is scanning for devices
        connectDeviceRequest                request that BLE Worker is connecting to device
        disconnectDeviceRequest             request that BLE Worker is disconnecting from device
        pairDeviceRequest                   request that BLE Worker is paring bluetooth device
        removeDeviceRequest                 request that BLE Worker is removing bluetooth device
        changeLineTerminationRequest        request that BLE Worker is using difference line termination
        bleStatusRequest                    request that BLE Worker reports current status
        setupTransceiverRequest             request that bluetoothctl interface and throughput timer is created
        # setupBLEWorkerRequest               request that asyncio event loop is created and bluetoothctrl wrapper is started
        startTransceiverRequest             request to subscribe to BLE notifications and throughput timer are started
        stopTransceiverRequest              request to unsubscribe from BLE notifications 0and throughput timer are stopped
        startThroughputRequest              request that throughput timer is started
        stopThroughputRequest               request that throughput timer is stopped
        finishWorkerRequest                 request that BLE Worker worker is finished
        mtocRequest                         request that BLE worker measures time of code

    Slots (functions available to respond to external signals or events from buttons, input fields, etc.)
        on_pushButton_BLEScan               update BLE device list
        on_pushButton_BLEConnect            open/close BLE device
        on_pushButton_BLEPair               pair or remove BLE device
        on_pushButton_BLETrust              trust or distrust BLE device
        on_pushButton_BLEStatus             request BLE device status
        on_comboBoxDropDown_BLEDevices      user selected a new BLE device from the drop down list
        on_comboBoxDropDown_LineTermination user selected a different line termination from drop down menu

        on_statusReady                      pickup BLE device status
        on_deviceListReady                  pickup new list of devices
        on_receivedData                     pickup text from BLE transceiver
        on_receivedLines                    pickup lines of text from BLE transceiver
        on_throughputReady                  pickup throughput data from BLE transceiver
        on_pairingSuccess                   pickup wether device pairing was successful
        on_removalSuccess                   pickup wether device removal was successful

        on_mtocRequest                      emit mtoc signal with function name and time in a single log call

    Functions
        cleanup                             cleanup the Serial

    """

    # Signals
    # ==========================================================================

    # BLEAK
    scanDevicesRequest           = pyqtSignal()                                # scan for BLE devices
    connectDeviceRequest         = pyqtSignal(object, int, bool)               # connect to BLE device, mac, timeout, 
    disconnectDeviceRequest      = pyqtSignal()                                # disconnect from BLE device
    changeLineTerminationRequest = pyqtSignal(bytes)                           # request line termination to change
    startThroughputRequest       = pyqtSignal()                                # request that throughput timer is started
    stopThroughputRequest        = pyqtSignal()                                # request that throughput timer is stopped 
    startTransceiverRequest      = pyqtSignal()                                # start transceiver (display of incoming text, connection remains)
    stopTransceiverRequest       = pyqtSignal()                                # stop transceiver (display of incoming text, connection remains)
    setupTransceiverFinished     = pyqtSignal()                                # request to setup transceiver finished
    finishWorkerRequest          = pyqtSignal()                                # request worker to finish
    mtocRequest                  = pyqtSignal()                                # request that BLE worker measures time of code
    logSignal                    = pyqtSignal(int, str)                        # Logging
    throughputUpdate             = pyqtSignal(float, float, str)               # report rx/tx to main ("ble")

    sendFileRequest              = pyqtSignal(Path)                            # request to send file
    sendTextRequest              = pyqtSignal(bytes)                           # request to transmit text to TX
    sendLineRequest              = pyqtSignal(bytes)                           # request to transmit one line of text to TX
    sendLinesRequest             = pyqtSignal(list)                            # request to transmit lines of text to TX
    txrxReadyChanged             = pyqtSignal(bool)                            # ready to accept send file, text, line or lines

    # bluetooth ctl
    pairDeviceRequest            = pyqtSignal(str,str)                         # pair with BLE device mac and pin
    removeDeviceRequest          = pyqtSignal(str)                             # remove BLE device from systems paired list 
    trustDeviceRequest           = pyqtSignal(str)                             # trust a device
    distrustDeviceRequest        = pyqtSignal(str)                             # distrust a device
    bleStatusRequest             = pyqtSignal(str)                             # request BLE device status

    # Init
    # ==========================================================================

    def __init__(self, parent=None, ui=None):

        super().__init__(parent)

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else -1
        self.instance_name = self.objectName() if self.objectName() else self.__class__.__name__

        # For debugging initialization
        self.logger = logging.getLogger(self.instance_name[:10])
        self.logger.setLevel(DEBUG_LEVEL)
        if not self.logger.handlers:
            sh = logging.StreamHandler()
            fmt = "[%(levelname)-8s] [%(name)-10s] %(message)s"
            sh.setFormatter(logging.Formatter(fmt))
            self.logger.addHandler(sh)
        self.logger.propagate = False

        # state variables, populated by service routines
        self.device                = ""                                        # BLE device
        self.device_info           = {}                                        # BLE device status
        self.rx                    = 0                                         # init throughput
        self.tx                    = 0                                         # init throughput 
        self.textLineTerminator    = EOL_DEFAULT_BYTES                         # default line termination

        # self.isLogScrolling        = False                                   # keep track of log display scrolling
        # self.isTextScrolling       = False                                   # keep track of text display scrolling
        self.device_backup         = ""                                        # keep track of previously connected device

        self.lastNumComputed       = time.perf_counter()                       # init throughput time calculation
        self.receiverIsRunning     = False                                     # BLE transceiver is not running

        self.lastNumReceived       = 0
        self.lastNumSent           = 0
    
        self.awaitingReconnection  = False

        self.record                = False                                     # record serial data
        self.recordingFileName     = ""
        self.recordingFile         = None

        # terminal/history line budget used by flushers
        if parent and hasattr(parent, "maxlines"):
            self.maxlines = int(parent.maxlines)
        else:
            self.maxlines = int(DEFAULT_TEXT_LINES)

        # self.textBrowserLength     = MAX_TEXTBROWSER_LENGTH + 1

        self.byteArrayBuffer = bytearray()
        self.byteArrayBufferTimer = QTimer(self)
        self.byteArrayBufferTimer.setTimerType(PreciseTimerType)
        self.byteArrayBufferTimer.setInterval(FLUSH_INTERVAL_MS)
        self.byteArrayBufferTimer.timeout.connect(self.flushByteArrayBuffer)

        self.linesBuffer = list()
        self.linesBufferTimer = QTimer(self)
        self.linesBufferTimer.setTimerType(PreciseTimerType)
        self.linesBufferTimer.setInterval(FLUSH_INTERVAL_MS)
        self.linesBufferTimer.timeout.connect(self.flushLinesBuffer)
        
        # Not yet implemented
        self.htmlBuffer = ""
        self.htmlBufferTimer = QTimer(self)
        self.htmlBufferTimer.setTimerType(PreciseTimerType)
        self.htmlBufferTimer.setInterval(FLUSH_INTERVAL_MS)
        # self.htmlBufferTimer.timeout.connect(self.flushHTMLBuffer)
        
        self.mtoc_on_deviceListReady = 0.
        self.mtoc_on_throughputReady = 0.
        self.mtoc_on_statusReady     = 0.
        self.mtoc_on_receivedData    = 0. 
        self.mtoc_on_receivedLines   = 0. 
        self.mtoc_on_receivedHTML    = 0. 
        self.mtoc_appendTextLines    = 0.
        self.mtoc_appendText         = 0.
        self.mtoc_appendHtml         = 0.

        # Delegate encoding if parent has one
        if parent and hasattr(parent, "encoding"):
            self.encoding = parent.encoding
        else:
            self.encoding = "utf-8"

        # Check if we have a valid User Interface
        if ui is None:
            self.logger.log(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: need to have access to User Interface"
            )
            raise ValueError("User Interface (ui) is required but was not provided.")
        self.ui = ui

        self.display = True                                                    # display incoming data
        self.ui.checkBox_DisplayBLE.setUpdatesEnabled(False)
        self.ui.checkBox_DisplayBLE.setChecked(self.display)
        self.ui.checkBox_DisplayBLE.setUpdatesEnabled(True)

        self.text_widget = self.ui.plainTextEdit_Text                          # Text widget for displaying received data
        self.text_scroll_bar = self.text_widget.verticalScrollBar()            # Scroll bar for the text widget

        self.html_tracker = IncompleteHTMLTracker()                            # Initialize the HTML tracker  

        if USE_BLUETOOTHCTL:
            self.hasBluetoothctl = (platform.system() == "Linux" )
        else:
            self.hasBluetoothctl = False

        # ----------------------------------------
        # Bleak Serial Worker & Thread
        # ----------------------------------------

        # Bleak Thread using custom AsyncThread
        self.bleakThread = AsyncThread()                                       # create QThread object

        # Create the bleak worker
        self.bleakWorker = BleakWorker()                                       # create BLE worker object
        self.bleakWorker.moveToThread(self.bleakThread)
        # Make sure loop exits before scheduling coroutines
        self.bleakThread.ready.connect(                 lambda loop: (self.bleakWorker.set_loop(loop), self.scanDevicesRequest.emit()))
        self.bleakWorker.finished.connect(              lambda: self.bleakThread.stop())
        self.bleakWorker.finished.connect(              lambda: self.bleakThread.wait())
        self.mtocRequest.connect(                       lambda: self.bleakWorker.request_mtoc()) # connect mtoc request to worker

        # Signals from QBLE (UI) -> Bleak Worker
        self.changeLineTerminationRequest.connect(      lambda eol: self.bleakWorker.change_LineTermination(eol)) # connect changing line termination
        self.scanDevicesRequest.connect(                lambda: self.bleakWorker.start_scan())
        self.sendFileRequest.connect(                   lambda filePath: self.bleakWorker.send_file(filePath)) # request to send file
        self.sendTextRequest.connect(                   lambda text: self.bleakWorker.send_bytes(text)) # request to transmit text to TX
        self.sendLineRequest.connect(                   lambda line: self.bleakWorker.send_line(line)) # request to transmit one line of text to TX
        self.sendLinesRequest.connect(                  lambda lines: self.bleakWorker.send_lines(lines)) # request to transmit lines of text to TX
        # Signals to run bleak commands
        self.connectDeviceRequest.connect(              lambda device, timeout, reconnect: self.bleakWorker.connect_device(device, timeout, reconnect))
        self.disconnectDeviceRequest.connect(           lambda: self.bleakWorker.disconnect_device())
        self.startTransceiverRequest.connect(           lambda: self.bleakWorker.start_transceiver())
        self.stopTransceiverRequest.connect(            lambda: self.bleakWorker.stop_transceiver())
        self.startThroughputRequest.connect(            lambda: self.bleakWorker.start_throughput())
        self.stopThroughputRequest.connect(             lambda: self.bleakWorker.stop_throughput())
        self.finishWorkerRequest.connect(               lambda: self.bleakWorker.clean_up())

        # Signals from BLEAK Worker to UI
        self.bleakWorker.throughputReady.connect(       self.on_throughputReady, type=ConnectionType.QueuedConnection) # connect display throughput status
        self.bleakWorker.deviceListReady.connect(       self.on_deviceListReady, type=ConnectionType.QueuedConnection) # connect new port list to its ready signal
        self.bleakWorker.connectingSuccess.connect(     self.on_connectingSuccess, type=ConnectionType.QueuedConnection) # connect connecting status to BLE UI
        self.bleakWorker.disconnectingSuccess.connect(  self.on_disconnectingSuccess, type=ConnectionType.QueuedConnection) # connect disconnecting status to BLE UI
        self.bleakWorker.workerStateChanged.connect(    self.on_workerStateChanged, type=ConnectionType.QueuedConnection) # mirror serial worker state to serial UI
        self.bleakWorker.logSignal.connect(             self.on_logSignal)     # connect log messages to BLE UI
        self.bleakWorker.eolChanged.connect(            self.on_eolChanged, type=ConnectionType.QueuedConnection)
        # Connected elsewhere
        # self.bleakWorker.receivedLines
        # self.bleakWorker.receivedData

        # Connections made, now start
        self.bleakThread.start()

        # ----------------------------------------
        # Bluetoothctl Worker & Thread
        # ----------------------------------------

        # BLE Thread using custom AsyncThread
        self.bluetoothctlThread = QThread()                                    # create QThread object
    
        # Create the BLE worker
        self.bluetoothctlWorker = BluetoothctlWorker()                         # create BLE worker object
        self.bluetoothctlWorker.moveToThread(           self.bluetoothctlThread)
        # propagate capability flag
        self.bluetoothctlWorker.hasBluetoothctl = self.hasBluetoothctl

        # ----------------------------------------
        # Signals
        # ----------------------------------------

        # Connect Bluetoothctl worker / thread finished
        self.bluetoothctlWorker.finished.connect(       self.bluetoothctlThread.quit) # if worker emits finished quite worker thread
        self.bluetoothctlWorker.finished.connect(       self.bluetoothctlWorker.deleteLater) # delete worker at some time
        self.bluetoothctlWorker.destroyed.connect(      lambda: setattr(self, "bluetoothctlWorker", None))    
        self.bluetoothctlThread.finished.connect(       self.bluetoothctlThread.deleteLater) # delete thread at some time
        self.bluetoothctlThread.destroyed.connect(      lambda: setattr(self, "bluetoothctlThread", None)) 
        # There is no start method in the bluetoothctlWorker
        # self.bluetoothctlThread.started.connect(        self.bluetoothctlWorker.start, type = ConnectionType.QueuedConnection)

        # QBLE (UI) -> Bluetoothctl Worker
        self.pairDeviceRequest.connect(                 self.bluetoothctlWorker.on_pairDeviceRequest, type=ConnectionType.QueuedConnection)
        self.removeDeviceRequest.connect(               self.bluetoothctlWorker.on_removeDeviceRequest, type=ConnectionType.QueuedConnection)
        self.trustDeviceRequest.connect(                self.bluetoothctlWorker.on_trustDeviceRequest, type=ConnectionType.QueuedConnection)
        self.distrustDeviceRequest.connect(             self.bluetoothctlWorker.on_distrustDeviceRequest, type=ConnectionType.QueuedConnection)
        self.bleStatusRequest.connect(                  self.bluetoothctlWorker.on_bleStatusRequest, type=ConnectionType.QueuedConnection)
        # allow global shutdown to stop bluetoothctl too
        self.finishWorkerRequest.connect(               self.bluetoothctlWorker.on_finishWorkerRequest)

        # Bluetoothctl Worker -> QBLE (UI)
        self.bluetoothctlWorker.statusReady.connect(    self.on_statusReady, type=ConnectionType.QueuedConnection) # connect status to BLE UI
        self.bluetoothctlWorker.pairingSuccess.connect( self.on_pairingSuccess, type=ConnectionType.QueuedConnection) # connect pairing status to BLE UI
        self.bluetoothctlWorker.trustSuccess.connect(   self.on_trustSuccess, type=ConnectionType.QueuedConnection) # connect trust status to BLE UI
        self.bluetoothctlWorker.distrustSuccess.connect(self.on_distrustSuccess, type=ConnectionType.QueuedConnection) # connect distrust status to BLE UI
        self.bluetoothctlWorker.removalSuccess.connect( self.on_removalSuccess, type=ConnectionType.QueuedConnection) # connect removal status to BLE UI
        self.bluetoothctlWorker.logSignal.connect(      self.on_logSignal, type=ConnectionType.QueuedConnection)

        # Bluetoothctl Connections and Start
        # ----------------------------------------
        self.bluetoothctlThread.start()                                        # start thread
        self.logger.log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Bluetoothctl Worker started."
        )
        
        self.logger.log(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: QBLESerial initialized."
        )

    # ==========================================================================
    # Slots Received Requests
    # ==========================================================================

    @pyqtSlot()
    def on_mtocRequest(self) -> None:
        """Emit the mtoc signal with a function name and time in a single log call."""

        log_message = textwrap.dedent(f"""
            BLE Profiling
            =============================================================
            on_deviceListReady      took {self.mtoc_on_deviceListReady*1000:.2f} ms.
            on_throughputReady      took {self.mtoc_on_throughputReady*1000:.2f} ms.
            on_statusReady          took {self.mtoc_on_statusReady*1000:.2f} ms.

            on_receivedData         took {self.mtoc_on_receivedData*1000:.2f} ms.
            on_receivedLines        took {self.mtoc_on_receivedLines*1000:.2f} ms.
            on_receivedHTML         took {self.mtoc_on_receivedHTML*1000:.2f} ms.

            appendTextLines         took {self.mtoc_appendTextLines*1000:.2f} ms.
            appendText              took {self.mtoc_appendText*1000:.2f} ms.
            appendHtml              took {self.mtoc_appendHtml*1000:.2f} ms.
        """)
        self.logSignal.emit(-1, log_message)

        self.mtoc_on_deviceListReady = 0.
        self.mtoc_on_throughputReady = 0.
        self.mtoc_on_statusReady     = 0.
        self.mtoc_on_receivedData    = 0. 
        self.mtoc_on_receivedLines   = 0. 
        self.mtoc_on_receivedHTML    = 0. 
        self.mtoc_appendTextLines    = 0.
        self.mtoc_appendText         = 0.
        self.mtoc_appendHtml         = 0.

        # Emit the mtoc request to the ble worker
        self.mtocRequest.emit()

    # ==========================================================================
    # Slots
    # ==========================================================================

    # General

    @pyqtSlot(int,str)
    def on_logSignal(self, level:int, message:str):
        """pickup log messages, not used as no connection with separate thread"""
        self.logSignal.emit(level, message)

    # BLEAK

    @pyqtSlot()
    def on_pushButton_BLEScan(self):
        """
        Update BLE device list
        """
        self.scanDevicesRequest.emit()
        self.ui.pushButton_BLEScan.setEnabled(False)
        self.ui.pushButton_BLEConnect.setEnabled(False)
        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: BLE device scan requested."
        )
        self.ui.statusBar().showMessage('BLE device scan requested.', 2000)            

    @pyqtSlot()
    def on_pushButton_BLEConnect(self):
        """
        Handle connect/disconnect requests.
        """
        if self.ui.pushButton_BLEConnect.text() == "Connect":

            if self.device:
                self.connectDeviceRequest.emit(self.device, 10, False)
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Attempting to connect to device."
                )
                self.ui.statusBar().showMessage('BLE connection requested.', 2000)

            else:
                self.logSignal.emit(logging.WARNING, 
                    f"[{self.instance_name[:15]:<15}]: No device selected for connection."
                )

        elif self.ui.pushButton_BLEConnect.text() == "Disconnect":

            if self.device:
                self.disconnectDeviceRequest.emit()
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Attempting to disconnect from device."
                )
                self.ui.statusBar().showMessage('BLE disconnection requested.', 2000)
            else:
                self.logSignal.emit(logging.WARNING, 
                    f"[{self.instance_name[:15]:<15}]: No device selected for disconnection."
                )

        else:
            self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: User interface Connect button is labeled incorrectly."
            )

    @pyqtSlot()
    def on_comboBoxDropDown_BLEDevices(self): 
        "user selected a different BLE device from the drop down list"

        # disconnect current device
        self.disconnectDeviceRequest.emit()
        if self.device:
            self.logSignal.emit(logging.INFO, f"[{self.instance_name[:15]:<15}]: BLE devices disconnect requested {getattr(self.device, 'name', '')}")
        else:
            self.logSignal.emit(logging.INFO, f"[{self.instance_name[:15]:<15}]: BLE devices disconnect requested")
        self.ui.statusBar().showMessage('BLE device disconnect requested.', 2000)

        # prepare UI for new selection
        index=self.ui.comboBoxDropDown_Device.currentIndex()
        if index >= 0:
            self.device = self.ui.comboBoxDropDown_Device.itemData(index)      # BLE device from BLEAK scanner
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Selected device: {self.device.name}, Address: {self.device.address}"
            )
            self.ui.pushButton_BLEConnect.setEnabled(True)                     # will want to connect
            if self.hasBluetoothctl: 
                self.ui.pushButton_BLEPair.setEnabled(True)                    # uses bluetoothctl
                self.ui.pushButton_BLETrust.setEnabled(True)                   # uses bluetoothctl
                self.ui.pushButton_BLEStatus.setEnabled(True)                  # uses bluetoothctl
            self.ui.pushButton_SendFile.setEnabled(False)                      # its not yet connected
            self.ui.pushButton_BLEPair.setText("Pair")
            self.ui.pushButton_BLEConnect.setText("Connect")
            self.ui.pushButton_BLETrust.setText("Trust")
            self.ui.statusBar().showMessage(f'BLE device {self.device.name} selected.', 2000)
        else:
            self.logSignal.emit(logging.WARNING, 
                f"[{self.instance_name[:15]:<15}]: No devices found"
            )
            self.ui.pushButton_BLEConnect.setEnabled(False)
            if self.hasBluetoothctl: 
                self.ui.pushButton_BLEPair.setEnabled(False)
                self.ui.pushButton_BLETrust.setEnabled(False)
                self.ui.pushButton_BLEStatus.setEnabled(False)
            self.ui.pushButton_SendFile.setEnabled(False)
            self.ui.pushButton_BLEScan.setEnabled(True)

    @pyqtSlot()
    def on_comboBoxDropDown_LineTermination(self):
        """
        User selected a different line termination from drop down menu
        """
        label = self.ui.comboBoxDropDown_LineTermination_BLE.currentText()
        term  = EOL_DICT.get(label, EOL_DEFAULT_BYTES)
        self.textLineTerminator = term

        # Notify the rest of the app
        self.changeLineTerminationRequest.emit(term)

        # Log both the friendly label and the raw bytes for clarity
        hr = EOL_DICT_INV.get(term, repr(term))
        self.logSignal.emit(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: line termination -> {hr} ({repr(term)})"
        )

        self.ui.statusBar().showMessage("Line termination changed.", 2000)

    # BluetoothCtl

    @pyqtSlot()
    def on_pushButton_BLEPair(self):
        """User clicked Pair / Remove."""
        if not self.device:
            self.logSignal.emit(logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: No device set to pair/remove"
            )
            return

        mac = getattr(self.device, "address", None)
        if not mac:
            self.logSignal.emit(logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: Device has no address"
            )
            return

        paired = self.device_info.get("paired", False)
        # Disable until result arrives
        self.ui.pushButton_BLEPair.setEnabled(False)

        if not paired:
            # Request pairing
            self.pairDeviceRequest.emit(mac, BLEPIN)
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Pair request sent for {self.device.name}"
            )
            self.ui.statusBar().showMessage("BLE pairing requested.", 2000)
        else:
            # Request removal
            self.removeDeviceRequest.emit(mac)
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Remove (unpair) request sent for {self.device.name}"
            )
            self.ui.statusBar().showMessage("BLE removal requested.", 2000)

    @pyqtSlot()
    def on_pushButton_BLETrust(self):
        """User clicked Trust / Distrust."""
        if not self.device:
            self.logSignal.emit(logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: No device set to trust/distrust"
            )
            return

        mac = getattr(self.device, "address", None)
        if not mac:
            self.logSignal.emit(logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: Device has no address"
            )
            return

        trusted = self.device_info.get("trusted", False)
        self.ui.pushButton_BLETrust.setEnabled(False)

        if not trusted:
            self.trustDeviceRequest.emit(mac)
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Trust request sent for {self.device.name}"
            )
            self.ui.statusBar().showMessage("BLE trust requested.", 2000)
        else:
            self.distrustDeviceRequest.emit(mac)
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Distrust request sent for {self.device.name}"
            )
            self.ui.statusBar().showMessage("BLE distrust requested.", 2000)

    @pyqtSlot()
    def on_pushButton_BLEStatus(self):
        if self.device is not None:
            self.bleStatusRequest.emit(self.device.address)
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: BLE devices status requested {self.device.name}"
            )
            self.ui.statusBar().showMessage('BLE device status requested.', 2000)

    @pyqtSlot(dict)
    def on_statusReady(self, status):
        """
        pickup BLE device status
        
        the status is:
        device_info = {
            "mac":       None,
            "name":      None,
            "paired":    None,
            "trusted":   None,
            "connected": None,
            "rssi":      None
        }
        """

        if PROFILEME: 
            tic = time.perf_counter()

        self.device_info = status

        if (self.device_info["mac"] is not None) and (self.device_info["mac"] != "") and self.hasBluetoothctl: 
            self.ui.pushButton_BLEPair.setEnabled(True)
            self.ui.pushButton_BLETrust.setEnabled(True)
            self.ui.pushButton_BLEPair.setText("Remove" if self.device_info["paired"] else "Pair")
            self.ui.pushButton_BLETrust.setText("Distrust" if self.device_info["trusted"] else "Trust")
        else:
            self.ui.pushButton_BLEPair.setEnabled(False)
            self.ui.pushButton_BLETrust.setEnabled(False)

        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Device status: {status}"
        )

        self.ui.statusBar().showMessage("BLE status updated", 2000)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_statusReady = max((toc - tic), self.mtoc_on_statusReady)

    @pyqtSlot(list)
    def on_deviceListReady(self, devices:list):
        """pickup new list of devices"""

        if PROFILEME: 
            tic = time.perf_counter()

        self.logSignal.emit(
            logging.DEBUG,
            f"[{self.instance_name[:15]:<15}]: Device list received."
        )

        self.ui.pushButton_BLEScan.setEnabled(True)                            # re-enable device scan, was turned of during scanning

        # save current selected device 
        currentIndex   = self.ui.comboBoxDropDown_Device.currentIndex()
        selectedDevice = self.ui.comboBoxDropDown_Device.itemData(currentIndex)

        self.ui.comboBoxDropDown_Device.blockSignals(True)
        self.ui.comboBoxDropDown_Device.clear()
        for device in devices:
            self.ui.comboBoxDropDown_Device.addItem(f"{device.name} ({device.address})", device)
        
        # search for previous device and select it
        index_to_select = -1
        if selectedDevice is not None:
            for index in range(self.ui.comboBoxDropDown_Device.count()):
                if self.ui.comboBoxDropDown_Device.itemData(index) == selectedDevice:
                    index_to_select = index
                    break

        if index_to_select == -1 and self.ui.comboBoxDropDown_Device.count() > 0:
            index_to_select = 0

        if index_to_select != -1:
            self.ui.comboBoxDropDown_Device.setCurrentIndex(index_to_select)
            # ensure internal state reflects selection even if signals were blocked
            self.device = self.ui.comboBoxDropDown_Device.itemData(index_to_select)

        self.ui.comboBoxDropDown_Device.blockSignals(False)

        if len(devices) > 0:
            self.ui.pushButton_BLEConnect.setEnabled(True)

        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Device list updated."
        )

        self.ui.statusBar().showMessage("BLE device list updated", 2000)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_deviceListReady = max((toc - tic), self.mtoc_on_deviceListReady ) # End performance tracking


    @pyqtSlot(bytes)
    def on_eolChanged(self, eol: bytes) -> None:
        """Update EOL in UI and internal state."""
        self.textLineTerminator = eol
        label = EOL_DICT_INV.get(eol, repr(eol))
        try:
            idx = self.ui.comboBoxDropDown_LineTermination_BLE.findText(label)
            self.ui.comboBoxDropDown_LineTermination_BLE.blockSignals(True)
            if idx > -1:
                self.ui.comboBoxDropDown_LineTermination_BLE.setCurrentIndex(idx)
        except Exception as e:
            self.logSignal.emit(logging.ERROR, f"[{self.instance_name[:15]:<15}]: EOL UI update error: {e}")
        finally:
            self.ui.comboBoxDropDown_LineTermination_BLE.blockSignals(False)
        self.logSignal.emit(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Auto‑detected line termination -> {label} ({repr(eol)})."
        )
        self.ui.statusBar().showMessage("BLE line termination updated.", 2000)

    # ==========================================================================
    # Slots for Data Received
    # ==========================================================================

    @pyqtSlot(bytearray)
    @profile
    def on_receivedData(self, byte_array: bytearray):
        """
        Receives a raw byte array from the ble device, 
        stores it in the byte array buffer,
        saves it to file if recording is enabled,
        """

        if PROFILEME: 
            tic = time.perf_counter()

        if DEBUGSERIAL:
            self.logSignal.emit(logging.DEBUG, 
                f"[{self.instance_name[:15]:<15}]: Text received."
            )

        if byte_array:
            self.byteArrayBuffer.extend(byte_array)
            if not self.byteArrayBufferTimer.isActive():
                self.byteArrayBufferTimer.start()

            if self.record and self.recordingFile:
                try:
                    self.recordingFile.write(byte_array)
                except Exception as e:
                    self.logSignal.emit(logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: Could not write to file {self.recordingFileName}. Error: {e}"
                    )                    
                    self.record = False
                    self.ui.checkBox_ReceiverRecord.setChecked(self.record)
                    self.recordingFile = None
                    self.recordingFileName = ""

        if PROFILEME :
            toc = time.perf_counter()
            self.mtoc_on_receivedData = max((toc - tic), self.mtoc_on_receivedData) # End performance tracking

    @pyqtSlot()
    @profile
    def flushByteArrayBuffer(self) -> None:
        """
        Takes content of the byte array buffer and displays it efficiently
        If user has scrolled away from bottom of display, update will stop
        """

        if self.display:

            if PROFILEME:
                tic = time.perf_counter()

            buf = self.byteArrayBuffer
            if not buf:
                self.byteArrayBufferTimer.stop()
                return

            at_bottom = self.text_scroll_bar.value() >= (self.text_scroll_bar.maximum() - self.text_scroll_bar.pageStep())
            if not at_bottom:
                # Cap raw backlog to avoid unbounded growth while scrolled up
                if len(self.byteArrayBuffer) > MAX_BACKLOG_BYTES:
                    self.byteArrayBuffer[:] = self.byteArrayBuffer[-MAX_BACKLOG_BYTES:]
                return

            arr = np.frombuffer(buf, dtype=np.uint8)
            newline_positions = np.where(arr == 0x0A)[0]                       # 0x0A = '\n'

            ends_with_nl = (buf[-1] == 0x0A)
            if ends_with_nl:
                total_lines = int(newline_positions.size)
            else:
                total_lines = int(newline_positions.size) + 1

            if total_lines == 0:
                return

            self.text_widget.setUpdatesEnabled(False)

            try: 

                # if more lines available then there are lines in terminal history,
                # do a full redraw with the latest lines that fit in the terminal,
                # otherwise append text to terminal history and let widget auto trim

                if total_lines > self.maxlines:
                    # more lines than we can show, trim

                    # Find cut position *after* the newline that precedes the last L lines.
                    # If buffer ends with '\n': cut after newline_positions[-L-1]
                    # Else (unterminated last line): cut after newline_positions[-L]

                    # index of the newline just *before* the last L lines
                    if ends_with_nl:
                        idx = total_lines - self.maxlines - 1
                    else:
                        idx = total_lines - self.maxlines
                    start = int(newline_positions[idx]) + 1 if idx >= 0 else 0

                    # Decode only what we will display
                    text = buf[start:].decode(self.encoding, errors="replace")
                    # Full redraw
                    self.text_widget.setPlainText(text)

                else:
                    # fast append, no trimming needed

                    # Decode byte array
                    text = buf.decode(self.encoding, errors="replace")
                    # Append text
                    self.text_widget.moveCursor(CursorEnd)
                    self.text_widget.insertPlainText(text)

                # Autoscroll to bottom
                self.text_scroll_bar.setValue(self.text_scroll_bar.maximum())  # Scroll to bottom for autoscroll
            finally:
                try:
                    del arr
                except NameError:
                    pass
                self.text_widget.setUpdatesEnabled(True)

                if PROFILEME:
                    toc = time.perf_counter()
                    self.mtoc_appendText = max(toc - tic, self.mtoc_appendText)

        # No display but still need to clear buffer
        self.byteArrayBuffer.clear()

    @pyqtSlot(list)
    @profile
    def on_receivedLines(self, lines: list):
        """
        Receives lines of text from the ble port, 
        Stores them in the lines buffer,
        Saves them to file if recording is enabled,
        """

        if PROFILEME: 
            tic = time.perf_counter()

        if DEBUGSERIAL:
            self.logSignal.emit(logging.DEBUG, 
                f"[{self.instance_name[:15]:<15}]: Text lines received."
            )

        if lines:

            self.linesBuffer.extend(lines)
            if not self.linesBufferTimer.isActive():
                self.linesBufferTimer.start()

            if self.record and self.recordingFile:
                try:
                    # combine the lines to single bytearray with eol added
                    _tmp = self.textLineTerminator.join(lines) + self.textLineTerminator
                    self.recordingFile.write(_tmp)
                except Exception as e:
                    self.logSignal.emit(logging.ERROR, f"[{self.instance_name[:15]:<15}]: Could not write to file {self.recordingFileName}. Error: {e}")
                    self.record = False
                    self.ui.checkBox_ReceiverRecord.setChecked(self.record)
                    self.recordingFile = None
                    self.recordingFileName = ""

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_on_receivedLines = max((toc - tic), self.mtoc_on_receivedLines) # End performance tracking

    @pyqtSlot()
    @profile
    def flushLinesBuffer(self) -> None:
        """
        Takes the content of the line buffer and displays it efficiently in the terminal
        This does not preserve the cursor position.
        """
          
        if self.linesBuffer:

            if self.display:
                if PROFILEME: 
                    tic = time.perf_counter()                                  # Start performance tracking

                at_bottom = self.text_scroll_bar.value() >= (self.text_scroll_bar.maximum() - self.text_scroll_bar.pageStep())

                if not at_bottom:
                    if len(self.linesBuffer) > self.maxlines:
                        # too many lines to show, keep only the most recent lines (in-place)
                        self.linesBuffer[:] = self.linesBuffer[-self.maxlines:]
                    return

                # Build display text efficiently: join bytes, decode once, add trailing newline

                nLines_incoming = len(self.linesBuffer)
                if nLines_incoming > self.maxlines:
                    # more lines than we can show, only keep the last maxlines
                    lines_toShow = self.linesBuffer[-self.maxlines:]
                    useReplace = True
                else:
                    # all lines fit in terminal
                    lines_toShow = self.linesBuffer[:]
                    useReplace = False
                # clear buffer after snapshot
                self.linesBuffer.clear()

                if lines_toShow:

                    self.text_widget.setUpdatesEnabled(False)

                    # Join bytes → one decode; add trailing newline to avoid gluing batches
                    display_text = (b'\n'.join(lines_toShow) + b'\n').decode(self.encoding, errors="replace")

                    # If more lines than history capacity, redraw; else append
                    if useReplace:
                        # full redraw
                        self.text_widget.setPlainText(display_text)
                    else:
                        # fast append
                        self.text_widget.moveCursor(CursorEnd)
                        self.text_widget.insertPlainText(display_text)

                    self.text_scroll_bar.setValue(self.text_scroll_bar.maximum()) # Scroll to bottom for autoscroll
                    self.text_widget.setUpdatesEnabled(True)

                if PROFILEME: 
                    toc = time.perf_counter()                                  # End performance tracking
                    self.mtoc_appendTextLines = max((toc - tic),self.mtoc_appendTextLines ) # End performance tracking

            # No display but still need to clear buffer
            self.linesBuffer.clear()

        else:
            self.linesBufferTimer.stop()            

    @pyqtSlot(str)
    @profile
    def on_receivedHTML(self, html: str) -> None:
        """
        Received html text from the ble input handler
        Stores it in the html buffer
        Saves it to file if recording is enabled,
        """

        if PROFILEME or DEBUGSERIAL: 
            tic = time.perf_counter()

        if DEBUGSERIAL:
            self.logSignal.emit(logging.DEBUG, f"[{self.instance_name[:15]:<15}]: HTML received.")

        if html:
            self.htmlBuffer += html
            if not self.htmlBufferTimer.isActive():
                self.htmlBufferTimer.start()

            if self.record and self.recordingFile:
                try:
                    self.recordingFile.write(html)
                except Exception as e:
                    self.logSignal.emit(
                        logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: Could not write to file {self.recordingFileName}. Error: {e}"
                    )
                    self.record = False
                    self.ui.checkBox_ReceiverRecord.setChecked(self.record)
                    self.recordingFile = None
                    self.recordingFileName = ""

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_on_receivedHTML = max((toc - tic), self.mtoc_on_receivedHTML) # End performance tracking

    @pyqtSlot()
    @profile
    def flushHTMLBuffer(self) -> None:
        """
        Takes the content of the html buffer and displays it efficiently in the terminal

        HTML can only be appended to regular text widgets, not the plain text widget and that is slower.
        So I will need to create alternative rich text widget if HTML display is needed.
        """
          
        if self.htmlBuffer:


            self.logSignal.emit(logging.WARNING, 
                f"[{self.instance_name[:15]:<15}]: Appending HTML to rich text widget not implemented."
            )
            return

            if self.display:
                if PROFILEME: 
                    tic = time.perf_counter()                                  # Start performance tracking

                at_bottom = self.rich_text_scroll_bar.value() >= (self.rich_text_scroll_bar.maximum() - self.rich_text_scroll_bar.pageStep())

                if not at_bottom:
                    return
                
                # Process HTML & detect incomplete tags
                valid_html_part, self.htmlBuffer = self.html_tracker.detect_incomplete_html(self.htmlBuffer)

                if valid_html_part:
                    # Append new HTML to the display
                    self.rich_text_widget.setUpdatesEnabled(False)
                    self.rich_text_widget.moveCursor(QTextCursor.MoveOperation.End)
                    self.rich_text_widget.insertHtml(valid_html_part)          # works on QTextEdit
                    self.rich_text_scroll_bar.setValue(self.rich_text_scroll_bar.maximum()) # Scroll to bottom for autoscroll
                    self.rich_text_widget.setUpdatesEnabled(True)

                if PROFILEME: 
                    toc = time.perf_counter()                                  # End performance tracking
                    self.mtoc_appendHTML = max((toc - tic),self.mtoc_appendHTML ) # End performance tracking
            
            # Did not display but still need to clear buffer
            self.htmlBuffer = ""

        else:
            pass
            # Not yet implemented
            # self.htmlBufferTimer.stop()

    @pyqtSlot(bool)
    def on_workerStateChanged(self, running: bool) -> None:
        """
        BLE worker was started or stopped
        """
        self.logSignal.emit(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: BLEAK worker is {'on' if running else 'off'}."
        )
        self.receiverIsRunning = running
        if running:
            self.ui.statusBar().showMessage("BLE Worker started", 2000)
        else:
            self.ui.statusBar().showMessage("BLEAK Worker stopped", 2000)

    @pyqtSlot(float,float)
    @profile
    def on_throughputReady(self, numReceived:int, numSent:int):
        """
        Report throughput data from BLEAK transceiver
        """

        tic = time.perf_counter()
        deltaTime = tic - self.lastNumComputed
        self.lastNumComputed = tic

        rx = numReceived - self.lastNumReceived
        tx = numSent - self.lastNumSent

        self.lastNumReceived = numReceived
        self.lastNumSent     = numSent

        # calculate throughput
        # deltaTime is in milli seconds -> *1000
        # numReceived and numSent are in kilo bytes -> /1024
        if rx >=0: 
            self.rx = rx / deltaTime
        if tx >=0: 
            self.tx = tx / deltaTime

        self.throughputUpdate.emit(float(self.rx), float(self.tx), "ble")

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_throughputReady = max((toc - tic), self.mtoc_on_throughputReady) # End performance tracking

    # BLEAK SUCCESS
    # ----------------------------------------

    @pyqtSlot(bool)
    def on_connectingSuccess(self, success):
        """pickup wether device connection was successful"""
        self.device_info["connected"] = success

        # Inform main to (un)wire send targets for BLE
        self.txrxReadyChanged.emit(bool(success))

        if success:
            self.ui.pushButton_SendFile.setEnabled(True)
            self.ui.lineEdit_Text.setEnabled(True)
            self.ui.pushButton_BLEConnect.setEnabled(True)
            self.ui.pushButton_BLEConnect.setText("Disconnect")

            # Push current BLE EOL selection to worker so parsing starts correctly
            label = self.ui.comboBoxDropDown_LineTermination_BLE.currentText()
            term  = EOL_DICT.get(label, self.textLineTerminator)
            if term is None:
                term = self.textLineTerminator
            self.textLineTerminator = term
            self.changeLineTerminationRequest.emit(term)

        else:
            self.ui.pushButton_SendFile.setEnabled(False)
            self.ui.lineEdit_Text.setEnabled(False)
            self.ui.pushButton_BLEConnect.setEnabled(True)
            self.ui.pushButton_BLEConnect.setText("Connect")

        # self.receiverIsRunning  = success

        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Device {self.device.name} connection: {'successful' if success else 'failed'}"
        )

        self.ui.statusBar().showMessage(f'BLE device connection: {"successful" if success else "failed"}', 2000)

    @pyqtSlot(bool)
    def on_disconnectingSuccess(self, success):
        """pickup wether device disconnection was successful"""
        self.device_info["connected"] = not(success)

        # Inform main to (un)wire send targets for BLE
        self.txrxReadyChanged.emit(not success)

        self.ui.pushButton_SendFile.setEnabled(False)
        self.ui.lineEdit_Text.setEnabled(False)
        self.ui.pushButton_BLEConnect.setEnabled(True)
        self.ui.pushButton_BLEConnect.setText("Connect")

        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Device {self.device.name} disconnection: {'successful' if success else 'failed'}"
        )

        self.receiverIsRunning  = False

        self.ui.statusBar().showMessage('BLE device  disconnected.', 2000)

    # Bluetoothctl SUCCESS
    # ----------------------------------------

    @pyqtSlot(bool)
    def on_pairingSuccess(self, success):
        """pickup wether device pairing was successful"""
        self.device_info["paired"] = success
        self.ui.pushButton_BLEPair.setEnabled(True)
        self.ui.pushButton_BLEPair.setText("Remove" if success else "Pair")
        self.logSignal.emit(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Device {self.device.name} pairing: {'successful' if success else 'failed'}"
        )
        self.ui.statusBar().showMessage('BLE device paired.' if success else 'BLE pairing failed.', 2000)


    @pyqtSlot(bool)
    def on_removalSuccess(self, success):
        """pickup wether device removal was successful"""
        # success True => now unpaired
        self.device_info["paired"] = not success
        self.ui.pushButton_BLEPair.setEnabled(True)
        self.ui.pushButton_BLEPair.setText("Pair" if success else "Remove")
        self.logSignal.emit(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Device {self.device.name} removal: {'successful' if success else 'failed'}"
        )
        self.ui.statusBar().showMessage('BLE device removed.' if success else 'BLE removal failed.', 2000)

    @pyqtSlot(bool)
    def on_trustSuccess(self, success):
        """pickup wether device pairing was successful"""
        self.device_info["trusted"] = success
        self.ui.pushButton_BLETrust.setEnabled(True)
        self.ui.pushButton_BLETrust.setText("Distrust" if success else "Trust")
        self.logSignal.emit(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Device {self.device.name} trusting: {'successful' if success else 'failed'}"
        )
        self.ui.statusBar().showMessage('BLE device trusted.' if success else 'BLE trust failed.', 2000)

    @pyqtSlot(bool)
    def on_distrustSuccess(self, success):
        # success True => now untrusted
        self.device_info["trusted"] = not success
        self.ui.pushButton_BLETrust.setEnabled(True)
        self.ui.pushButton_BLETrust.setText("Trust" if success else "Distrust")
        self.logSignal.emit(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Device {self.device.name} distrusting: {'successful' if success else 'failed'}"
        )
        self.ui.statusBar().showMessage('BLE device distrusted.' if success else 'BLE distrust failed.', 2000)

    # ==========================================================================
    # UI wants to receive data or cleanup
    # ==========================================================================

    def connect_receivedLines(self, on_receivedLines: pyqtSlot) -> None:
        if not connect(self.bleakWorker.receivedLines, on_receivedLines):
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Received lines signal could not be connected."
            )

    def connect_receivedData(self, on_receivedData: pyqtSlot) -> None:
        if not connect(self.bleakWorker.receivedData, on_receivedData):
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Received data signal could not be connected."
            )

    def disconnect_receivedLines(self, on_receivedLines: pyqtSlot) -> None:
        if not disconnect(self.bleakWorker.receivedLines, on_receivedLines):
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Received lines signal could not be disconnected."
            )

    def disconnect_receivedData(self, on_receivedData: pyqtSlot) -> None:
        if not disconnect(self.bleakWorker.receivedData, on_receivedData):
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Received data signal could not be disconnected."
            )

    def cleanup(self):
        """
        Perform cleanup tasks for QBLESerial, such as 
          stopping timers, 
          disconnecting signals,
          and ensuring proper worker shutdown.
        """

        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Cleaning up BLEAK & bluetoothctl workers."
        )
        self.ui.statusBar().showMessage('Cleaning up BLEAK and bluetoothctl workers.', 2000)

        if hasattr(self.recordingFile, "close"):
            try:
                self.recordingFile.close()
            except Exception as e:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Could not close file {self.recordingFileName}: {e}"
                )

        # Stop timers if they are still active
        if self.byteArrayBufferTimer.isActive():
            self.byteArrayBufferTimer.stop()
        if self.linesBufferTimer.isActive():
            self.linesBufferTimer.stop()
        # Not implemented yet
        # if self.htmlBufferTimer.isActive():
        #     self.htmlBufferTimer.stop()

        # Gather workers/threads
        bleakWorker = getattr(self, "bleakWorker", None)
        bleakThread = getattr(self, "bleakThread", None)
        btWorker    = getattr(self, "bluetoothctlWorker", None)
        btThread    = getattr(self, "bluetoothctlThread", None)

        # Request both workers to finish (single signal wired to both)
        self.finishWorkerRequest.emit()

        if bleakWorker:
            ok, args, reason = wait_for_signal(
                bleakWorker.finished,
                timeout_ms=1000,
                sender=bleakWorker
            )
            if not ok and reason != "destroyed":
                self.logSignal.emit(logging.ERROR,
                    f"[{self.instance_name[:15]:<15}]: BLEAK Worker finish timed out because of {reason}.")
            else:
                self.logSignal.emit(logging.DEBUG,
                    f"[{self.instance_name[:15]:<15}]: BLEAK Worker finished: {args}."
                )
        else:
            self.logSignal.emit(logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: BLEAK worker not initialized."
            )

        if bleakThread:
            # AsyncThread: prefer stop() before forcing
            try:
                bleakThread.stop()
            except Exception:
                pass
            if not bleakThread.wait(1000):
                self.logSignal.emit(logging.WARNING,
                    f"[{self.instance_name[:15]:<15}]: BLEAK Thread graceful stop timed out after 3000 ms; forcing quit.")
                bleakThread.quit() 
                if not bleakThread.wait(1000):
                    self.logSignal.emit(logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: BLEAK Thread won’t quit; terminating as last resort.")
                    try:
                        bleakThread.terminate()
                        bleakThread.wait(500)
                    except Exception:
                        pass

        # Wait for bluetoothctl worker (if present and thread running)
        if btThread and qobject_alive(btThread) and btThread.isRunning():
            if btWorker and qobject_alive(btWorker):
                ok, args, reason = wait_for_signal(
                    btWorker.finished,
                    timeout_ms=2000,
                    sender=btWorker,
                )
                if not ok and reason != "destroyed":
                    self.logSignal.emit(logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: Bluetoothctl Worker finish timed out because of {reason}.")
                else:
                    self.logSignal.emit(logging.DEBUG,
                        f"[{self.instance_name[:15]:<15}]: Bluetoothctl Worker finished: {args}."
                    )
        else:
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl worker already stopped or not initialized."
            )

        # Bring bluetoothctl thread down
        if btThread and qobject_alive(btThread):
            if not btThread.wait(1000):
                self.logSignal.emit(logging.WARNING,
                    f"[{self.instance_name[:15]:<15}]: Bluetoothctl Thread graceful stop timed out; forcing quit.")
                btThread.quit()
                if not btThread.wait(1000):
                    self.logSignal.emit(logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: Bluetoothctl Thread won’t quit; terminating as last resort.")
                    try:
                        btThread.terminate()
                        btThread.wait(500)
                    except Exception:
                        pass

        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Cleaned up."
        )

############################################################################################################################################
#
# Bleak Worker
#
# start and stop worker
# send text, line, lines, file
# scan for devices
# change device
# connect and disconnect device
# change line termination
# calculate throughput 
#
# The worker uses a separate async thread handling BLE serial input and output
# These routines have no access to the user interface,
# Communication occurs through signals
#
# This is the Model of the Model - View - Controller (MVC) architecture.
#
############################################################################################################################################

class AsyncThread(QThread):
    """
    Async Thread for BLEAK Operations
    This replaces QThread:
    We can not run BLEAK inside a QT Thread as async only works in main thread
    """

    ready = pyqtSignal(object)                                                 # emits the loop once setup
    
    def __init__(self):
        super().__init__()
        self._loop = None                                                      # ensure attribute exists before run()

    def run(self):
        # Create and install an asyncio loop in *this* thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self.ready.emit(loop)
        # Run forever
        try:
            loop.run_forever()
        finally:
            loop.close()

    def stop(self):
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)

    @property
    def loop(self):
        return getattr(self, "_loop", None)


class BleakWorker(QObject):
    """
    Bleak Worker
        start_transceiver()                    connect to BLE notifications
        stop_transceiver()                      disconnect from BLE notifications
        request_mtoc()
        start_throughput()
        stop_throughput()
        change_LineTermination()                EOL character
        clean_up()                              stop transceiver, throughput, disconnect device
        start_scan()
        select_device()                         select device by MAC and update self.device
        connect_device()                        connect to selected BLEDevice
        disconnect_device()                     disconnect from BLEDevice
        send_bytes()
        send_line()
        send_lines()
        send_file(Path)

    Callbacks:
        _handle_data(sender, data)                      handle incoming data from BLE device
        _setup_throughput()
        _throughput_loop()                      Emit every second throughput data
        _startTransceiver()
        _stopTransceiver()
        _scanDevices()
        _connectDevice()
            _handle_disconnect()
            _handle_reconnection()
        _disconnectDevice()
        _sendText
        _sendLine
        _sendLines
        _sendFile

    Utility Functions:
        set_loop(loop)                         set asyncio loop for this worker
        schedule(coro)                         schedule a coroutine to run in the worker's loop
    """

    logSignal            = pyqtSignal(int, str)  
    deviceListReady      = pyqtSignal(list)
    connectingSuccess    = pyqtSignal(bool)
    disconnectingSuccess = pyqtSignal(bool)
    receivedLines        = pyqtSignal(list)
    receivedData         = pyqtSignal(bytearray)
    throughputReady      = pyqtSignal(float, float)                            # RX, TX throughput in
    workerStateChanged   = pyqtSignal(bool)
    eolChanged           = pyqtSignal(bytes)                                   # notify UI when eol changed
    finished             = pyqtSignal()

    def __init__(self, parent=None):
        super(BleakWorker, self).__init__(parent)

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else -1
        self.instance_name = self.objectName() if self.objectName() else self.__class__.__name__

        self.loop = None
        self._throughput_task = None

        self.eol =  EOL_DEFAULT_BYTES
        self.client = None
        self.device = None
        self.device_backup = None
        self.services = None
        self.bytes_received = 0
        self.bytes_sent = 0
        self.bufferIn = bytearray()

        self.timeout = 0
        self.reconnect = False
        self.awaitingReconnection  = False

        self.NSUdevices = []
        self.mtu = 23
        self.BLEpayloadSize = 20

        self.receiverIsRunning = False

        self.mtoc_on_sendText = 0.
        self.mtoc_on_sendLine = 0.
        self.mtoc_on_sendLines = 0.
        self.mtoc_on_sendFile = 0.
        self.mtoc_readlines = 0.
        self.mtoc_read = 0.
        self.mtoc_on_scanDevices = 0.
        self.mtoc_on_connectDevice = 0.
        self.mtoc_on_disconnectDevice = 0.

        # EOL autodetection (mirror Serial worker defaults)
        self.dataReady_calls = 0
        self.eolWindow_start = 0.0
        self.dataReady_calls_threshold   = MAX_DATAREADYCALLS
        self.eolDetection_timeThreshold  = MAX_EOL_DETECTION_TIME
        self.eolFallback_timeout         = MAX_EOL_FALLBACK_TIMEOUT
        self.bufferIn_max = 65536                                              # cap buffer growth

    # ==========================================================================
    # Functions, Async Functions, Callbacks
    # ==========================================================================

    def set_loop(self, loop):
        self.loop = loop
        try:
            self.thread_id = int(QThread.currentThreadId())
        except Exception:
            import threading
            self.thread_id = threading.get_ident()

    def schedule(self, coro) -> asyncio.Future:
        if not self.loop:
            raise RuntimeError("Can not schedule async task, bleak loop not set yet")

        # determine label for logging
        label = None
        if inspect.iscoroutine(coro):
            try:
                label = coro.cr_code.co_name
            except Exception:
                label = getattr(coro, "__name__", "coroutine")
        else:
            label = getattr(coro, "__name__", type(coro).__name__)
        if not label:
            label = "coroutine"
        
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        setattr(fut, "_task_label", label)

        def _log_ex(f):
            label = getattr(f, "_task_label", "coroutine")
            
            if f.cancelled():
                self.logSignal.emit(logging.WARNING,
                    f"[{self.instance_name[:15]:<15}]: {label} async task cancelled.")
                return
            
            try:
                f.result()
            except Exception as e:
                etype = type(e).__name__
                emsg  = str(e).strip()
                if not emsg:
                    # Some exceptions have empty __str__; use repr
                    emsg = repr(e)
                self.logSignal.emit(logging.ERROR,
                    f"[{self.instance_name[:15]:<15}]: {label} async task error: {etype}: {emsg}")
        
        fut.add_done_callback(_log_ex)
        return fut

    @profile
    def _handle_data(self, *args: Any) -> None:
        """
        Handle incoming data from BLE device.

        This is analog to "on_dataReady" from serial input handler.

        data is of type byte_array
        """

        if PROFILEME:
            tic = time.perf_counter()

        if len(args) >= 2:
            # sender = args[0]
            data = args[1]
        else:
            data= args[0]

        if not data:
            return

        self.bytes_received += len(data)

        self.logSignal.emit(logging.DEBUG,
            f"[{self.instance_name[:15]:<15}]: Data received callback with {self.bytes_received} bytes."
        )

        if self.eol:

            # EOL-based reading -> processing line by line 
            #------------------------------------------------------------------------

            self.bufferIn.extend(data)

            # Cap buffer size to prevent unbounded growth
            if len(self.bufferIn) > self.bufferIn_max:
                self.bufferIn[:] = self.bufferIn[-self.bufferIn_max:]

            now = time.perf_counter()
            lines = None

            if self.eol in self.bufferIn:
                # Seen current delimiter → reset detection window
                self.dataReady_calls = 0
                self.eolWindow_start = 0.0
                lines = self.bufferIn.split(self.eol)

            else:
                # EOL auto-detect if EOL not observed for a while

                self.dataReady_calls += 1
                if self.eolWindow_start == 0.0:
                    self.eolWindow_start = now
                elapsed = now - self.eolWindow_start

                if (self.dataReady_calls >= self.dataReady_calls_threshold
                    and elapsed >= self.eolDetection_timeThreshold):

                    # Do we have any eol in the buffer?
                    buf = self.bufferIn
                    if b"\r\n" in buf:
                        best_cand = b"\r\n"
                    else:
                        if b"\n" in buf:
                            if b"\n\r" in buf:
                                best_cand = b"\n\r"
                            else:
                                best_cand = b"\n"
                        elif b"\r" in buf:
                            best_cand = b"\r"
                        else:
                            best_cand = None

                    if best_cand and best_cand != self.eol:
                        # Switch to detected delimiter
                        self.eol = best_cand
                        self.dataReady_calls = 0
                        self.eolWindow_start = 0.0
                        self.logSignal.emit(logging.INFO,
                            f"[{self.instance_name[:15]:<15}]: Auto‑detected line termination -> {repr(self.eol)}."
                        )
                        # notify UI of change
                        self.eolChanged.emit(self.eol)
                        # parse immediately using new delimiter
                        lines = self.bufferIn.split(self.eol)

                    elif elapsed >= self.eolFallback_timeout:
                        # Switch to raw after prolonged absence of any delimiter
                        self.eol = b""
                        self.dataReady_calls = 0
                        self.eolWindow_start = 0.0
                        self.logSignal.emit(logging.INFO,
                            f"[{self.instance_name[:15]:<15}]: No delimiter {self.eolFallback_timeout:.1f}s → switching to raw."
                        )
                        # notify UI of the change
                        self.eolChanged.emit(self.eol)
                        # emit buffered bytes once and clear
                        if self.bufferIn:
                            self.receivedData.emit(self.bufferIn)
                            self.bufferIn.clear()
                        if PROFILEME:
                            toc = time.perf_counter()
                            self.mtoc_read = max((toc - tic), self.mtoc_read)
                        return

            if lines is not None:
                if lines:
                    tail = lines[-1]
                    lines.pop()
                    if tail:
                        self.bufferIn[:] = tail
                    else:
                        self.bufferIn.clear()

                    if lines:
                        self.receivedLines.emit(lines)

                if PROFILEME:
                    toc = time.perf_counter()
                    self.mtoc_readlines = max((toc - tic), self.mtoc_readlines)

                if DEBUGSERIAL:
                    self.logSignal.emit(logging.DEBUG,
                        f"[{self.instance_name[:15]:<15}]: Rx {len(data)} bytes from {len(lines)} lines."
                    )
            else:
                if PROFILEME:
                    toc = time.perf_counter()
                    self.mtoc_readlines = max((toc - tic), self.mtoc_readlines)

        else:

            # Raw byte reading
            # ----------------------------------------
            self.receivedData.emit(data)

            if PROFILEME:
                toc = time.perf_counter()
                self.mtoc_read = max((toc - tic), self.mtoc_read)

            if DEBUGSERIAL:
                total_bytes = len(data)
                self.logSignal.emit(
                    logging.DEBUG,
                    f"[{self.instance_name[:15]:<15}]: Rx {total_bytes} bytes."
                )

    def request_mtoc(self):
        """Emit the mtoc signal with a function name and time in a single log call."""
        log_message = textwrap.dedent(f"""
            BLE Worker Profiling
            =============================================================
            BLE Send Text   took {self.mtoc_on_sendText*1000:.2f} ms.
            BLE Send Line   took {self.mtoc_on_sendLine*1000:.2f} ms.
            BLE Send Lines  took {self.mtoc_on_sendLines*1000:.2f} ms.
            BLE Send File   took {self.mtoc_on_sendFile*1000:.2f} ms.
            BLE Readlines   took {self.mtoc_readlines*1000:.2f} ms.
            BLE Read        took {self.mtoc_read*1000:.2f} ms.

            Bytes received       {self.bytes_received}.
            Bytes sent           {self.bytes_sent}.

            BLE Scan        took {self.mtoc_on_scanDevices*1000:.2f} ms.
            BLE Connect     took {self.mtoc_on_connectDevice*1000:.2f} ms.
            BLE Disconnect  took {self.mtoc_on_disconnectDevice*1000:.2f} ms.
        """)
        self.logSignal.emit(-1, log_message)
        self.mtoc_on_sendText = 0.
        self.mtoc_on_sendLine = 0.
        self.mtoc_on_sendLines = 0.
        self.mtoc_on_sendFile = 0.
        self.mtoc_readlines = 0.
        self.mtoc_read = 0.
        self.mtoc_on_scanDevices = 0.
        self.mtoc_on_connectDevice = 0.
        self.mtoc_on_disconnectDevice = 0.

    def start_throughput(self):
        """Schedule Throughput"""
        self.schedule(self._setup_throughput())

    async def _setup_throughput(self):
        """Start periodic tasks using asyncio without Timer"""
        if self._throughput_task and not self._throughput_task.done():
            return
        self._throughput_task = self.loop.create_task(self._throughput_loop(), name="throughput")
        self._throughput_task.add_done_callback(lambda t: setattr(self, "_throughput_task", None))
        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Throughput timer is set up.")

    async def _throughput_loop(self):
        """Publish the throughput metrics."""
        try:
            while True:
                self.throughputReady.emit(self.bytes_received, self.bytes_sent)
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise

    def stop_throughput(self):
        task = self._throughput_task
        if not task:
            return

        self.loop.call_soon_threadsafe(task.cancel)

        def _wait_for_cancel(t):
            async def _await():
                try:
                    await t
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    self.logSignal.emit(logging.ERROR, 
                        f"[{self.instance_name[:15]:<15}]: Throughput task error: {e}"
                    )
            return _await()

        asyncio.run_coroutine_threadsafe(_wait_for_cancel(task), self.loop)

        self.throughputReady.emit(0, 0)
        self._throughput_task = None
        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Throughput timer stopped."
        )

    def start_transceiver(self):
        if self.receiverIsRunning:
            self.logSignal.emit(logging.DEBUG,
                f"[{self.instance_name[:15]:<15}]: Transceiver is already running."
            )
            return

        if not (self.client and self.client.is_connected):
            self.logSignal.emit(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: No BLE client or BLE client not connected."
            )
            return

        fut = self.schedule(self._startTransceiver())
        def _done(f):
            exc = f.exception()
            if exc:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Transceiver not started: {exc}"
                )
            else:
                self.receiverIsRunning = True
                self.workerStateChanged.emit(True)
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Transceiver started, subscribed to notifications."
                )
        fut.add_done_callback(_done)

    async def _startTransceiver(self):
        await self.client.start_notify(self.char_tx, self._handle_data)

    def stop_transceiver(self):
        if not self.receiverIsRunning:
            self.logSignal.emit(logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: Transceiver is already stopped."
            )
            return

        fut = self.schedule(self._stopTransceiver())
        def _done(f):
            exc = f.exception()
            if exc:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Transceiver stop failed: {exc}"
                )
            else:
                self.receiverIsRunning = False
                self.workerStateChanged.emit(False)
                self.logSignal.emit(logging.WARNING,
                    f"[{self.instance_name[:15]:<15}]: BLEAK client unsubscribed from notifications.")
        fut.add_done_callback(_done)
                
    async def _stopTransceiver(self):
        await self.client.stop_notify(self.char_tx)

    def clean_up(self):
        """Handle Cleanup of the worker."""

        self.stop_throughput()
        self.stop_transceiver()

        # Disconnect BLE client if connected
        if self.client and self.client.is_connected:
            already_disconnecting = bool(getattr(self, "disconnecting", False))
            fut = None
            if not already_disconnecting:
                fut = self.schedule(self._disconnectDevice())
            ok, _, reason = wait_for_signal(self.disconnectingSuccess, timeout_ms=3000, sender=self)
            if not ok and reason != "destroyed":
                self.logSignal.emit(logging.WARNING,
                    f"[{self.instance_name[:15]:<15}]: Disconnect timed out ({reason})."
                )
                # Best effort: cancel the task if we started one
                if fut is not None:
                    try:
                        fut.cancel()
                    except Exception:
                        pass
            # Drain the future to surface any exception and avoid pending-task warnings
            if fut is not None:
                try:
                    fut.result(timeout=0.1)
                    self.logSignal.emit(logging.INFO,
                        f"[{self.instance_name[:15]:<15}]: Disconnected BLE client.")
                except Exception as e:
                    self.logSignal.emit(logging.DEBUG,
                        f"[{self.instance_name[:15]:<15}]: Disconnect future result: {e}")

        # Reset worker state
        self.device = None
        self.bytes_received = 0
        self.bytes_sent = 0
        self.bufferIn.clear()

        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: BLEAK Serial Worker cleanup completed."
        )

        # Emit finished signal
        self.finished.emit()

    def change_LineTermination(self, lineTermination: bytes):
        """
        Set the new line termination sequence.
        """
        if lineTermination is None:
            self.logSignal.emit(logging.WARNING, 
                f"[{self.instance_name[:15]:<15}]: Line termination not changed, line termination string not provided."
            )
        else:
            self.eol = lineTermination
            self.dataReady_calls = 0
            self.eolWindow_start = 0.0
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Changed line termination to {repr(self.eol)}."
    )

    # BLEAK Device Scan
    # ----------------------------------------

    def start_scan(self):
        self.schedule(self._scanDevices())

    async def _scanDevices(self):
        """Scan for BLE devices offering the Nordic UART Service."""

        if PROFILEME: 
            tic = time.perf_counter()

        try:
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Scanning for BLE devices."
            )
            devices = await BleakScanner.discover(timeout=5, return_adv=True)
        except Exception as e:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Error scanning for devices: {e}"
            )
            return
        
        if not devices:
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: No devices found."
            )
        
        self.NSUdevices = []
        for device, adv in devices.values():
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Found device: {device.name} ({device.address}) RSSI: {adv.rssi} dBm"
            )
            suids = adv.service_uuids or ()
            for service_uuid in suids:
                # self.logSignal.emit(logging.INFO, 
                #     f"[{self.instance_name[:15]:<15}]: Found service UUID: {service_uuid}"
                # )
                if service_uuid.lower() == SERVICE_UUID.lower():
                    self.NSUdevices.append(device)

        if not self.NSUdevices:
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Scan complete. No matching devices found."
            )
        else:
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Scan complete."
            )
        self.deviceListReady.emit(self.NSUdevices)

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_on_scanDevices = max((toc - tic), self.mtoc_on_scanDevices) # End performance tracking

    # BLEAK Device Connect
    # ----------------------------------------

    # def select_device(self, mac: str):
    #     """Select a device from the scanned devices by MAC."""
    #     for dev in self.NSUdevices:
    #         if dev.address == mac:
    #             self.device = dev
    #             self.logSignal.emit(logging.INFO, 
    #                 f"[{self.instance_name[:15]:<15}]: Device selected: {dev.name} ({dev.address})"
    #             )
    #             return
    #     self.logSignal.emit(logging.WARNING, 
    #         f"[{self.instance_name[:15]:<15}]: No device found with MAC {mac}"
    #     )

    def connect_device(self, device: BLEDevice, timeout: int, reconnect: bool):
        self.schedule(self._connectDevice(device=device, timeout=float(timeout), reconnect=reconnect))

    async def _rescan_for_device(self, name: str, address: str, timeout: float = 3.0):
        """
        Rescan briefly to refresh BlueZ device object (handles RPA changes).
        This addresses issues when privacy settings are turned on for some devices.
        """
        try:
            results = await BleakScanner.discover(timeout=timeout, return_adv=True)
        except Exception:
            return None
        # Prefer address match
        if address:
            for dev, adv in results.values():
                if dev.address == address:
                    return dev
        # Fallback name match
        if name:
            for dev, adv in results.values():
                if dev.name == name:
                    return dev
        return None
    
    async def _connectDevice(self, device: BLEDevice, timeout: float, reconnect: bool):
        """
        handle the connection request to a BLE device.

        Parameters:
            device (BLEDevice): The device to connect to.
            timeout (int): Connection timeout in seconds.
            reconnect (bool): Whether to reconnect on disconnection.
        """

        if PROFILEME: 
            tic = time.perf_counter()

        self.device = device
        self.timeout = timeout
        self.reconnect = reconnect

        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Connecting to device: {device.name} ({device.address})"
        )

        if self.device is not None:
            self.client = BleakClient(
                self.device, 
                disconnected_callback=self._handle_disconnected, 
                timeout=self.timeout
            )
            try:
                await self.client.connect(timeout=self.timeout)
                # acquire services and MTU after connection
                self.services = getattr(self.client, "services", None)
                if self.client._backend.__class__.__name__ == "BleakClientBlueZDBus":
                    # try MTU negotiation if available
                    acquire = getattr(self.client._backend, "_acquire_mtu", None)
                    if callable(acquire):
                        try:
                            await acquire()
                        except Exception:
                            pass
                self.mtu = getattr(self.client, "mtu_size", None)
                if isinstance(self.mtu, int) and (self.mtu > ATT_HDR) and (self.mtu <= BLEMTUMAX):
                    self.BLEpayloadSize = self.mtu - ATT_HDR
                else:
                    self.mtu = BLEMTUDEFAULT 
                    self.BLEpayloadSize = BLEMTUDEFAULT  - ATT_HDR

                service = self.services.get_service(SERVICE_UUID) if self.services else None
                if not service:
                    raise BleakError("Target service not found after connect")
                self.char_tx = service.get_characteristic(TX_CHARACTERISTIC_UUID)
                self.char_rx = service.get_characteristic(RX_CHARACTERISTIC_UUID)

                self.connectingSuccess.emit(True) 
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Connected to {self.device.name} "
                    f"MTU={self.mtu}, payload={self.BLEpayloadSize}"
                )

            except BleakError as e1:
                msg = str(e1).lower()
                if "not found" in msg and "device" in msg:
                    # Retry once: Rescan to rebuild BlueZ device object
                    self.logSignal.emit(logging.WARNING,
                        f"[{self.instance_name[:15]:<15}]: Device path missing, rescanning for {device.name}..."
                    )
                    refreshed = await self._rescan_for_device(device.name, device.address, timeout=3.0)
                    if refreshed:
                        self.device = refreshed
                        try:
                            self.client = BleakClient(
                                refreshed,
                                disconnected_callback=self._handle_disconnected,
                                timeout=self.timeout
                            )
                            await self.client.connect(timeout=self.timeout)
                            self.services = getattr(self.client, "services", None)

                            if self.client._backend.__class__.__name__ == "BleakClientBlueZDBus":
                                acquire = getattr(self.client._backend, "_acquire_mtu", None)
                                if callable(acquire):
                                    try: 
                                        await acquire()
                                    except Exception: 
                                        pass
                            self.mtu = getattr(self.client, "mtu_size", None)
                            if isinstance(self.mtu, int) and (self.mtu > ATT_HDR) and (self.mtu <= BLEMTUMAX):
                                self.BLEpayloadSize = self.mtu - ATT_HDR
                            else:
                                self.mtu = BLEMTUDEFAULT
                                self.BLEpayloadSize = BLEMTUDEFAULT - ATT_HDR

                            service = self.services.get_service(SERVICE_UUID) if self.services else None
                            if not service:
                                raise BleakError("Target service not found after rescan connect")
                            self.char_tx = service.get_characteristic(TX_CHARACTERISTIC_UUID)
                            self.char_rx = service.get_characteristic(RX_CHARACTERISTIC_UUID)

                            self.connectingSuccess.emit(True)
                            self.logSignal.emit(logging.INFO,
                                f"[{self.instance_name[:15]:<15}]: Connected after rescan MTU={self.mtu}, payload={self.BLEpayloadSize}"
                            )
                            return
                        
                        except Exception as e2:
                            self.logSignal.emit(logging.ERROR,
                                f"[{self.instance_name[:15]:<15}]: Rescan connect failed: {e2}"
                            )
                    else:
                        self.logSignal.emit(logging.ERROR,
                            f"[{self.instance_name[:15]:<15}]: Rescan did not find device again."
                        )
                else:
                    if "authentication" in msg or "security" in msg:
                        self.logSignal.emit(logging.ERROR,
                            f"[{self.instance_name[:15]:<15}]: Connection needs pairing/auth ({e1})."
                        )
                    else:
                        self.logSignal.emit(logging.ERROR,
                            f"[{self.instance_name[:15]:<15}]: Connection error: {e1}"
                        )
                self.connectingSuccess.emit(False)
                self.char_tx = None
                self.char_rx = None
                self.client = None
                
        else:
            self.logSignal.emit(logging.WARNING, 
                f"[{self.instance_name[:15]:<15}]: No device selected. Please select a device from the scan results."
            )

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_on_connectDevice = max((toc - tic), self.mtoc_on_connectDevice)

    def _handle_disconnected(self, client):
        """
        Callback when the BLE device is unexpectedly disconnected.
        Starts a background task to handle reconnection.
        """
        self.logSignal.emit(logging.WARNING, 
            f"[{self.instance_name[:15]:<15}]: Device disconnected: {self.device.name} ({self.device.address})"
        )

        # Reflect disconnected state immediately so UI switches to "Connect"
        if self.receiverIsRunning:
            self.receiverIsRunning = False
            self.workerStateChanged.emit(False)
        self.disconnectingSuccess.emit(True)                                   # UI: show Connect, disable send, etc.

        if not self.reconnect:                                                 # Check if reconnection is allowed
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Reconnection disabled. No attempt will be made."
            )
            self.client = None
            self.char_rx = None
            self.char_tx = None
        else:
            # Start the reconnection in a background task
            self.schedule(self._handle_reconnection())

    async def _handle_reconnection(self):
        """
        Handles reconnection attempts in a non-blocking manner.
        """
        retry_attempts = 0
        max_retries    = 5
        backoff        = 1                                                     # Initial backoff in seconds

        while (
            retry_attempts < max_retries
            and self.reconnect
            and self.client is not None
            and (not getattr(self.client, "is_connected", False))
        ):

            try:
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Reconnection attempt {retry_attempts + 1} to {self.device.name}..."
                )
                await self.client.connect(timeout=10)

                # When BLE device is reconnected, one needs to reacquire the services and MTU
                self.services = self.client.services
                if self.client._backend.__class__.__name__ == "BleakClientBlueZDBus": 
                    await self.client._backend._acquire_mtu()
                self.mtu = getattr(self.client, "mtu_size", None)
                if isinstance(self.mtu, int) and (self.mtu > ATT_HDR) and (self.mtu <= BLEMTUMAX):
                    self.BLEpayloadSize = self.mtu - ATT_HDR
                else:
                    self.mtu = BLEMTUNORMAL
                    self.BLEpayloadSize = BLEMTUNORMAL - ATT_HDR

                service = self.services.get_service(SERVICE_UUID)
                self.char_tx = service.get_characteristic(TX_CHARACTERISTIC_UUID)
                self.char_rx = service.get_characteristic(RX_CHARACTERISTIC_UUID)

                # Reconnect notifications if receiver was running
                await self.client.start_notify(self.char_tx, self._handle_data)
                self.receiverIsRunning = True
                self.workerStateChanged.emit(True)

                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Reconnected to {self.device.name} with MTU={self.mtu} and notifications started."
                )
                retry_attempts = 0                                             # Reset retry attempts on success
                return                                                         # Exit the loop on successful reconnection

            except Exception as e:
                retry_attempts += 1
                self.logSignal.emit(logging.WARNING, 
                    f"[{self.instance_name[:15]:<15}]: Reconnection attempt {retry_attempts} failed: {e}"
                )
                await asyncio.sleep(backoff)
                backoff *= 2                                                   # Exponential backoff

                self.client = None
                self.char_rx = None
                self.char_tx = None

        # Exit conditions
        if retry_attempts >= max_retries:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to reconnect to {self.device.name} after {max_retries} attempts."
            )
        elif not self.reconnect:
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Reconnection attempts stopped by the user."
            )
        elif getattr(self.client, "is_connected", False):
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Already connected to {self.device.name}. Exiting reconnection loop."
            )

        # Ensure UI reflects disconnected state and can try Connect again
        if self.receiverIsRunning:
            self.receiverIsRunning = False
            self.workerStateChanged.emit(False)
        self.disconnectingSuccess.emit(True)                                   # switch UI to "Connect"

        # Make sure internal handles are cleared
        self.client = None
        self.char_rx = None
        self.char_tx = None

    # BLEAK Device Disconnect
    # ----------------------------------------

    def disconnect_device(self):
        self.schedule(self._disconnectDevice())

    async def _disconnectDevice(self):
        """
        Handles disconnection requests from the user.
        Ensures clean disconnection and updates the application state.
        """
        if PROFILEME:
            tic = time.perf_counter()

        self.reconnect = False                                                 # Stop reconnection attempts

        if not self.client or not self.client.is_connected:
            self.logSignal.emit(logging.WARNING, 
                f"[{self.instance_name[:15]:<15}]: No active connection to disconnect."
            )
            self.disconnectingSuccess.emit(False)
            return

        if getattr(self, "disconnecting", False):
            self.logSignal.emit(logging.WARNING, 
                f"[{self.instance_name[:15]:<15}]: Disconnection already in progress."
            )
            return

        self.disconnecting = True                                              # Set disconnection flag
        try:
            await self.client.disconnect()
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Disconnected from device: {self.device.name} ({self.device.address})"
            )
            # Reset client 
            self.client = None
            self.device = None
            self.services = None
            self.char_rx = None
            self.char_tx = None
            # Emit success signal
            self.disconnectingSuccess.emit(True)
        except Exception as e:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Error during disconnection: {e}"
            )
            self.disconnectingSuccess.emit(False)
        finally:
            self.disconnecting = False                                         # Reset disconnection flag

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_on_disconnectDevice = max((toc - tic), self.mtoc_on_disconnectDevice)

    # BLEAK send data
    # ----------------------------------------
    # text, line, lines, file

    def send_bytes(self, byte_array: bytes):
        self.schedule(self._sendBytes(byte_array=byte_array))

    @profile
    async def _sendBytes(self, byte_array: bytes):
        """Send provided bytes over BLE."""

        if PROFILEME: 
            tic = time.perf_counter()

        if byte_array and self.client and self.client.is_connected and self.char_rx:
            char_rx = self.char_rx
            payload_size = self.BLEpayloadSize
            for i in range(0, len(byte_array), payload_size):
                chunk = byte_array[i:i+payload_size]
                await self.client.write_gatt_char(char_rx, chunk, response=False) # response=False for speed, returns immediately
                self.bytes_sent += len(chunk)
            self.logSignal.emit(logging.DEBUG, 
                f"[{self.instance_name[:15]:<15}]: Sent: {byte_array}"
            )
        else:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Not connected or no data to send."
            )

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_sendText = max((toc - tic), self.mtoc_on_sendText)    # End performance tracking

    def send_line(self, line: bytes):
        self.schedule(self._sendLine(line))

    @profile
    async def _sendLine(self, line: bytes):
        """Send a single line of text (with EOL) over BLE."""
        if PROFILEME: 
            tic = time.perf_counter()

        if self.eol:
            await self._sendBytes(line + self.eol)
        else:
            await self._sendBytes(line)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_sendLine = max((toc - tic), self.mtoc_on_sendLine)    # End performance tracking

    @pyqtSlot(list)
    def send_lines(self, lines: list):
        self.schedule(self._sendLines(lines))

    @profile
    async def _sendLines(self, lines: list):
        """Send multiple lines of text over BLE."""
        if PROFILEME: 
            tic = time.perf_counter()

        for line in lines:
            await self._sendLine(line)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_sendLines = max((toc - tic), self.mtoc_on_sendLines)  # End performance tracking

    def send_file(self, filePath: Path):
        self.schedule(self._sendFile(filePath))

    @profile
    async def _sendFile(self, filePath: Path):
        """Transmit a file to the BLE device."""

        if PROFILEME: 
            tic = time.perf_counter()

        if self.client and self.client.is_connected and self.char_rx:
            if not filePath:
                self.logSignal.emit(logging.ERROR, 'No file path provided.')
                return
            try:
                data = await asyncio.to_thread(filePath.read_bytes)
            except FileNotFoundError:
                self.logSignal.emit(logging.ERROR, f'File "{filePath.name}" not found.')
                return
            except Exception as e:
                self.logSignal.emit(logging.ERROR, f'Unexpected error opening "{filePath.name}": {e}')
                return
                
            if not data:
                self.logSignal.emit(logging.WARNING, f'[{self.instance_name[:15]}]: File "{filePath.name}" is empty.')
                return

            file_size = len(data)
            self.logSignal.emit(logging.INFO, f'Starting transmission of "{filePath.name}" ({file_size} bytes).')

            char_rx = self.char_rx
            payload_size = self.BLEpayloadSize
            for i in range(0, len(data), payload_size):
                chunk = data[i:i+payload_size]
                try:
                    await self.client.write_gatt_char(char_rx, chunk, response=False)
                    self.bytes_sent += len(chunk)
                except Exception as e:
                    self.logSignal.emit(logging.ERROR, f'Error transmitting chunk at offset {i}: {e}.')
                    break

            self.logSignal.emit(logging.INFO, f'Finished transmission of "{filePath.name}".')

        else:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: BLE client not available or not connected."
            )

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_sendFile = max((toc - tic), self.mtoc_on_sendFile)    # End performance tracking

############################################################################################################################################
#
# Bluetothctl Worker
#
# status, pair, remove, trust, distrust a device
#
# these routines have no access to the user interface,
# communication occurs through signals
#
#    This is the Model of the Model - View - Controller (MVC) architecture.
#
# start and stop worker
# pair and remove device
# trust and distrust device
# status of device
#
############################################################################################################################################

class BluetoothctlWorker(QObject):
    """
    Bluetoothctl Worker

    Worker Signals
        statusReady(dict)                      report BLE status
        pairingSuccess(bool)                   was pairing successful
        removalSuccess(bool)                   was removal successful
        logSignal(int, str)                    log message available
        finished()                             worker finished

    Worker Slots
        on_finishWorkerRequest()               finish the worker
        on_bleStatusRequest(str)               request BLE status of a device by MAC
        on_pairDeviceRequest(str, str)         pair with a selected device by MAC and PIN
        on_removeDeviceRequest(str)            remove a paired device by MAC
        on_trustDeviceRequest(str)             trust a selected device by MAC
        on_distrustDeviceRequest(str)          distrust a selected device by MAC
        on_mtocRequest()                       emit mtoc message

    """

    # Signals
    # ==========================================================================

    statusReady              = pyqtSignal(dict)                                # BLE device status dictionary
    connectingSuccess        = pyqtSignal(bool)                                # Connecting result
    disconnectingSuccess     = pyqtSignal(bool)                                # Disconnecting result
    pairingSuccess           = pyqtSignal(bool)                                # Pairing result
    removalSuccess           = pyqtSignal(bool)                                # Removal result
    trustSuccess             = pyqtSignal(bool)                                # Trusting result
    distrustSuccess          = pyqtSignal(bool)                                # Distrusting result
    logSignal                = pyqtSignal(int, str)                            # Logging
    finished                 = pyqtSignal()                                    # Worker finished

    # Init
    # ==========================================================================
    def __init__(self, parent=None):

        super(BluetoothctlWorker, self).__init__(parent)

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else -1
        self.instance_name = self.objectName() if self.objectName() else self.__class__.__name__

        # Platform capability (can be overridden by controller)
        self.hasBluetoothctl = (platform.system() == "Linux")

        # Profiling
        self.mtoc_on_bleStatusRequest = 0.
        self.mtoc_on_pairDeviceRequest = 0.
        self.mtoc_on_removeDeviceRequest = 0.
        self.mtoc_on_trustDeviceRequest = 0.
        self.mtoc_on_distrustDeviceRequest = 0.

        self.bluetoothctlWrapper = None
 
        self.PIN = BLEPIN                                                      # Placeholder PIN if required by pairing

        self.device_info = {
            "mac":       None,
            "name":      None,
            "paired":    None,
            "trusted":   None,
            "connected": None,
            "rssi":      None
        }

    # ==========================================================================
    # UI Response Functions
    # ==========================================================================

    @pyqtSlot()
    def on_mtocRequest(self):
        """Emit the mtoc signal with a function name and time in a single log call."""
        log_message = textwrap.dedent(f"""
            Bluetoothctl Worker Profiling
            =============================================================
            BLE Status      took {self.mtoc_on_bleStatusRequest*1000:.2f} ms.
            BLE Pair        took {self.mtoc_on_pairDeviceRequest*1000:.2f} ms.
            BLE Remove      took {self.mtoc_on_removeDeviceRequest*1000:.2f} ms.
            BLE Trust       took {self.mtoc_on_trustDeviceRequest*1000:.2f} ms.
            BLE Distrust    took {self.mtoc_on_distrustDeviceRequest*1000:.2f} ms.
        """)
        self.logSignal.emit(-1, log_message)
        self.mtoc_on_bleStatusRequest = 0.
        self.mtoc_on_pairDeviceRequest = 0.
        self.mtoc_on_removeDeviceRequest = 0.
        self.mtoc_on_trustDeviceRequest = 0.
        self.mtoc_on_distrustDeviceRequest = 0.

    @pyqtSlot()
    def on_finishWorkerRequest(self):
        """Cleanly stop bluetoothctl wrapper and signal finished."""
        try:
            if self.bluetoothctlWrapper:
                self.bluetoothctlWrapper.stop()
        except Exception:
            pass
        finally:
            self.bluetoothctlWrapper = None
        self.finished.emit()

    # ==========================================================================
    # UI request responses
    # ==========================================================================

    # Bluetoothctl Device Status
    # ----------------------------------------

    @pyqtSlot(str)
    def on_bleStatusRequest(self, mac: str):
        """
        Request device status by MAC.
        """

        if not self.hasBluetoothctl:
            self.logSignal.emit(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl not available."
            )
            return
        
        if PROFILEME: 
            tic = time.perf_counter()

        if self.bluetoothctlWrapper is None:
            # Initialize BluetoothctlWrapper (assumes BluetoothctlWrapper is defined elsewhere)
            self.bluetoothctlWrapper = BluetoothctlWrapper("bluetoothctl")
            self.bluetoothctlWrapper.log_signal.connect(self.logSignal)
            self.bluetoothctlWrapper.start()
            ok, args, reason = wait_for_signal(
                self.bluetoothctlWrapper.startup_completed_signal,
                1000,
                sender=self.bluetoothctlWrapper,
            )            
            if not ok:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Bluetoothctl wrapper startup timed out because of {reason}."
                )
            else:
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Bluetoothctl wrapper started: {args}."
                )

        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.get_device_info(mac=mac, timeout=2000)
            self.bluetoothctlWrapper.device_info_ready_signal.connect(self._on_device_info_ready)
            self.bluetoothctlWrapper.device_info_failed_signal.connect(self._on_device_info_failed)
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl wrapper status requested."
            )
        else:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl wrapper not available for status request."
            )

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_on_bleStatusRequest = max((toc - tic), self.mtoc_on_bleStatusRequest)

    @pyqtSlot(dict)
    def _on_device_info_ready(self, info: dict):
        self.logSignal.emit(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Device info retrieved: {info}"
        )
        self.device_info.update(info)
        self.statusReady.emit(self.device_info)
        # Disconnect signals
        if not disconnect(self.bluetoothctlWrapper.device_info_ready_signal, self._on_device_info_ready):
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Device info ready signal could not be disconnected."
            )

        if not disconnect(self.bluetoothctlWrapper.device_info_failed_signal, self._on_device_info_failed):
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Device info failed signal could not be disconnected."
            )

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl stopped."
            )

    @pyqtSlot(str)
    def _on_device_info_failed(self, mac: str):
        self.logSignal.emit(logging.ERROR, 
            f"[{self.instance_name[:15]:<15}]: Failed to retrieve device info for MAC: {mac}"
        )
        if not disconnect(self.bluetoothctlWrapper.device_info_ready_signal, self._on_device_info_ready):
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Device info ready signal could not be disconnected."
            )
        if not disconnect(self.bluetoothctlWrapper.device_info_failed_signal, self._on_device_info_failed):
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Device info failed signal could not be disconnected."
            )

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl stopped."
            )

    # Bluetoothctl Pair Device
    # ----------------------------------------

    @pyqtSlot(str,str)
    def on_pairDeviceRequest(self, mac: str, pin: str):
        """Pair with the currently selected device."""

        if not self.hasBluetoothctl:
            self.logSignal.emit(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl not available."
            )
            return

        if PROFILEME:
            tic = time.perf_counter()

        if self.bluetoothctlWrapper is None:
            # Initialize BluetoothctlWrapper
            self.bluetoothctlWrapper = BluetoothctlWrapper("bluetoothctl")
            self.bluetoothctlWrapper.log_signal.connect(self.logSignal)
            self.bluetoothctlWrapper.start()
            ok, args, reason = wait_for_signal(
                self.bluetoothctlWrapper.startup_completed_signal, 
                timeout_ms=1000,
                sender=self.bluetoothctlWrapper
            )
            if not ok:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Bluetoothctl wrapper startup timed out because of {reason}."
                )
            else:
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Bluetoothctl wrapper started: {args}."
                )

        if mac is not None and self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.device_pair_succeeded_signal.connect(self._on_pairing_successful)
            self.bluetoothctlWrapper.device_pair_failed_signal.connect(self._on_pairing_failed)
            self.bluetoothctlWrapper.pair(mac=mac, pin=pin, timeout=5000, scantime=1000)
        else:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: No device selected or BluetoothctlWrapper not available."
            )

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_on_pairDeviceRequest = max((toc - tic), self.mtoc_on_pairDeviceRequest)

    def _on_pairing_successful(self, mac: str):
        self.pairingSuccess.emit(True)
        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Paired with {mac}"
        )
        if not disconnect(self.bluetoothctlWrapper.device_pair_succeeded_signal, self._on_pairing_successful):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to disconnect device_pair_succeeded_signal"
            )
        if not disconnect(self.bluetoothctlWrapper.device_pair_failed_signal, self._on_pairing_failed):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to disconnect device_pair_failed_signal"
            )

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl stopped."
            )

    def _on_pairing_failed(self, mac: str):
        self.pairingSuccess.emit(False)
        self.logSignal.emit(logging.ERROR, 
            f"[{self.instance_name[:15]:<15}]: Pairing with {mac} unsuccessful"
        )
        if not disconnect(self.bluetoothctlWrapper.device_pair_succeeded_signal, self._on_pairing_successful):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to disconnect device_pair_succeeded_signal"
            )

        if not disconnect(self.bluetoothctlWrapper.device_pair_failed_signal, self._on_pairing_failed):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to disconnect device_pair_failed_signal"
            )

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl stopped."
            )

    # Bluetoothctl Remove Device
    # ----------------------------------------

    @pyqtSlot(str)
    def on_removeDeviceRequest(self, mac: str):
        """Remove the currently selected device from known devices."""

        if not self.hasBluetoothctl:
            self.logSignal.emit(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl not available."
            )
            return

        if PROFILEME:
            tic = time.perf_counter()

        if self.bluetoothctlWrapper is None:
            # Initialize BluetoothctlWrapper (assumes BluetoothctlWrapper is defined elsewhere)
            self.bluetoothctlWrapper = BluetoothctlWrapper("bluetoothctl")
            self.bluetoothctlWrapper.log_signal.connect(self.logSignal)
            self.bluetoothctlWrapper.start()
            ok, args, reason = wait_for_signal(
                self.bluetoothctlWrapper.startup_completed_signal, 
                timeout_ms=1000,
                sender=self.bluetoothctlWrapper
            )
            if not ok:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Bluetoothctl wrapper startup timed out because of {reason}."
                )
            else:
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Bluetoothctl wrapper started: {args}."
                )

        if mac is not None:
            if self.bluetoothctlWrapper:
                if not connect(self.bluetoothctlWrapper.device_remove_succeeded_signal, self._on_removing_successful):
                    self.logSignal.emit(logging.ERROR, 
                        f"[{self.instance_name[:15]:<15}]: Failed to connect device_remove_succeeded_signal"
                    )
                if not connect(self.bluetoothctlWrapper.device_remove_failed_signal, self._on_removing_failed):
                    self.logSignal.emit(logging.ERROR, 
                        f"[{self.instance_name[:15]:<15}]: Failed to connect device_remove_failed_signal"
                    )
                self.bluetoothctlWrapper.remove(mac=mac, timeout=5000)
                self.logSignal.emit(logging.WARNING, 
                    f"[{self.instance_name[:15]:<15}]: BluetoothctlWrapper initiated device {mac} removal."
                )
            else:
                self.logSignal.emit(logging.WARNING, 
                    f"[{self.instance_name[:15]:<15}]: BluetoothctlWrapper not available."
                )
        else:
            self.logSignal.emit(logging.WARNING, 
                f"[{self.instance_name[:15]:<15}]: No device selected or BluetoothctlWrapper not available."
            )

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_on_removeDeviceRequest = max((toc - tic), self.mtoc_on_removeDeviceRequest)

    def _on_removing_successful(self, mac: str):
        self.removalSuccess.emit(True)
        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Device {mac} removed"
        )
        if not disconnect(self.bluetoothctlWrapper.device_remove_succeeded_signal, self._on_removing_successful):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to disconnect device_remove_succeeded_signal"
            )
        if not disconnect(self.bluetoothctlWrapper.device_remove_failed_signal, self._on_removing_failed):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to disconnect device_remove_failed_signal"
            )
        self.device = None

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl stopped."
            )

    def _on_removing_failed(self, mac: str):
        self.removalSuccess.emit(False)
        self.logSignal.emit(logging.ERROR, 
            f"[{self.instance_name[:15]:<15}]: Device {mac} removal unsuccessful"
        )
        if not disconnect(self.bluetoothctlWrapper.device_remove_succeeded_signal, self._on_removing_successful):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to disconnect device_remove_succeeded_signal"
            )
        if not disconnect(self.bluetoothctlWrapper.device_remove_failed_signal, self._on_removing_failed):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to disconnect device_remove_failed_signal"
            )
        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl stopped."
            )

    # Bluetoothctl Trust Device
    # ----------------------------------------

    @pyqtSlot(str)
    def on_trustDeviceRequest(self, mac: str):
        """Trust the currently selected device."""

        if not self.hasBluetoothctl:
            self.logSignal.emit(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl not available."
            )
            return

        if PROFILEME:
            tic = time.perf_counter()

        if self.bluetoothctlWrapper is None:
            # Initialize BluetoothctlWrapper (assumes BluetoothctlWrapper is defined elsewhere)
            self.bluetoothctlWrapper = BluetoothctlWrapper("bluetoothctl")
            self.bluetoothctlWrapper.log_signal.connect(self.logSignal)
            self.bluetoothctlWrapper.start()
            ok, args, reason = wait_for_signal(
                self.bluetoothctlWrapper.startup_completed_signal,
                timeout_ms=1000,
                sender=self.bluetoothctlWrapper
            )
            if not ok:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Bluetoothctl wrapper startup timed out because of {reason}."
                )
            else:
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Bluetoothctl wrapper started: {args}."
                )

        if mac is not None and self.bluetoothctlWrapper:
            if not connect(self.bluetoothctlWrapper.device_trust_succeeded_signal, self._on_trust_successful):
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Failed to connect device_trust_succeeded_signal"
                )
            if not connect(self.bluetoothctlWrapper.device_trust_failed_signal, self._on_trust_failed):
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Failed to connect device_trust_failed_signal"
                )
            self.bluetoothctlWrapper.trust(mac=mac, timeout=2000)
        else:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: No device selected or BluetoothctlWrapper not available."
            )

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_on_trustDeviceRequest = max((toc - tic), self.mtoc_on_trustDeviceRequest)

    def _on_trust_successful(self, mac: str):
        self.trustSuccess.emit(True)
        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Trusted {mac}"
        )
        if not disconnect(self.bluetoothctlWrapper.device_trust_succeeded_signal, self._on_trust_successful):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to disconnect device_trust_succeeded_signal"
            )
        if not disconnect(self.bluetoothctlWrapper.device_trust_failed_signal, self._on_trust_failed):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to disconnect device_trust_failed_signal"
            )

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl stopped."
            )

    def _on_trust_failed(self, mac: str):
        self.trustSuccess.emit(False)
        self.logSignal.emit(logging.ERROR, 
            f"[{self.instance_name[:15]:<15}]: Pairing with {mac} unsuccessful"
        )
        if not disconnect(self.bluetoothctlWrapper.device_trust_succeeded_signal, self._on_trust_successful):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to disconnect device_trust_succeeded_signal"
            )
        if not disconnect(self.bluetoothctlWrapper.device_trust_failed_signal, self._on_trust_failed):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to disconnect device_trust_failed_signal"
            )

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl stopped."
            )

    # Bluetoothctl Distrust Device
    # ----------------------------------------

    @pyqtSlot(str)
    def on_distrustDeviceRequest(self, mac: str):
        """Remove the currently selected device from known devices."""

        if not self.hasBluetoothctl:
            self.logSignal.emit(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl not available."
            )
            return

        if PROFILEME:
            tic = time.perf_counter()

        if self.bluetoothctlWrapper is None:
            # Initialize BluetoothctlWrapper (assumes BluetoothctlWrapper is defined elsewhere)
            self.bluetoothctlWrapper = BluetoothctlWrapper("bluetoothctl")
            self.bluetoothctlWrapper.log_signal.connect(self.logSignal)
            self.bluetoothctlWrapper.start()
            ok, args, reason = wait_for_signal(
                self.bluetoothctlWrapper.startup_completed_signal,
                timeout_ms=1000,
                sender=self.bluetoothctlWrapper,
            )
            if not ok:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Bluetoothctl wrapper startup timed out because of {reason}."
                )
            else:
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Bluetoothctl wrapper started: {args}."
                )

        if mac is not None:
            if self.bluetoothctlWrapper:
                if not connect(self.bluetoothctlWrapper.device_distrust_succeeded_signal, self._on_distrust_successful):
                    self.logSignal.emit(logging.ERROR, 
                        f"[{self.instance_name[:15]:<15}]: Failed to connect device_distrust_succeeded_signal"
                    )
                if not connect(self.bluetoothctlWrapper.device_distrust_failed_signal, self._on_distrust_failed):
                    self.logSignal.emit(logging.ERROR, 
                        f"[{self.instance_name[:15]:<15}]: Failed to connect device_distrust_failed_signal"
                    )
                self.bluetoothctlWrapper.distrust(mac=mac, timeout=2000)
                self.logSignal.emit(logging.WARNING, 
                    f"[{self.instance_name[:15]:<15}]: BluetoothctlWrapper initiated device {mac} distrust."
                )
            else:
                self.logSignal.emit(logging.WARNING, 
                    f"[{self.instance_name[:15]:<15}]: BluetoothctlWrapper not available."
                )
        else:
            self.logSignal.emit(logging.WARNING, 
                f"[{self.instance_name[:15]:<15}]: No device selected or BluetoothctlWrapper not available."
            )

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_on_distrustDeviceRequest = max((toc - tic), self.mtoc_on_distrustDeviceRequest)

    def _on_distrust_successful(self, mac: str):
        self.distrustSuccess.emit(True)

        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Device {mac} distrusted"
        )

        if not disconnect(self.bluetoothctlWrapper.device_distrust_succeeded_signal, self._on_distrust_successful):
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Device distrust success signal could not be disconnected."
            )

        if disconnect(self.bluetoothctlWrapper.device_distrust_failed_signal, self._on_distrust_failed):
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Device distrust failed signal could not be disconnected"
            )

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl stopped."
            )

    def _on_distrust_failed(self, mac: str):
        self.distrustSuccess.emit(False)
        self.logSignal.emit(logging.ERROR, 
            f"[{self.instance_name[:15]:<15}]: Device {mac} distrusted unsuccessful"
        )
        if not disconnect(self.bluetoothctlWrapper.device_distrust_succeeded_signal, self._on_distrust_successful):
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Device distrust success signal could not be disconnected."
            )

        if not disconnect(self.bluetoothctlWrapper.device_distrust_failed_signal, self._on_distrust_failed):
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Device distrust failed signal could not be disconnected."
            )

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Bluetoothctl stopped."
            )

############################################################################################################################################
# Testing
############################################################################################################################################

if __name__ == "__main__":
    # not implemented
    pass
