############################################################################################
# QT BLE Serial UART Helper
############################################################################################
# November 2024: initial work
#
# This code is maintained by Urs Utzinger
############################################################################################

############################################################################################
# This code has 3 sections
# QBLESerialUI: Interface to GUI, runs in main thread.
# QBLESerial:   Functions running in separate thread, communication through signals and slots.
############################################################################################

import re
import time
import logging
import threading

from pathlib import Path

import asyncio
from qasync import QEventLoop  # Library to integrate asyncio with Qt
from bleak  import BleakClient, BleakScanner, BleakError 

try: 
    from PyQt6.QtCore import (
        QObject, QTimer, QThread, pyqtSignal, pyqtSlot, QStandardPaths,
    )
    from PyQt6.QtCore import Qt, QObject, QThread, QTimer, pyqtSignal, pyqtSlot, QStandardPaths
    from PyQt6.QtGui import QTextCursor
    from PyQt6.QtWidgets import QFileDialog, QMessageBox
    hasQt6 = True
except:
    from PyQt5.QtCore import (
        QObject, QTimer, QThread, pyqtSignal, pyqtSlot, QStandardPaths,
    )
    from PyQt5.QtCore import Qt, QObject, QThread, QTimer, pyqtSignal, pyqtSlot, QStandardPaths
    from PyQt5.QtGui import QTextCursor
    from PyQt5.QtWidgets import QFileDialog, QMessageBox
    hasQt6 = False

# Custom Helpers
from helpers.Codec_helper         import BinaryStreamProcessor
from helpers.Qbluetoothctl_helper import BluetoothctlWrapper

# Constants
########################################################################################
DEBUGSERIAL            = False       # enable debug output
MAX_TEXTBROWSER_LENGTH = 4096        # display window is trimmed to these number of lines
                                     # lesser value results in better performance
MAX_LINE_LENGTH        = 1024        # number of characters after which an end of line characters is expected
RECEIVER_FINISHCOUNT   = 10          # [times] If we encountered a timeout 10 times we slow down serial polling
NUM_LINES_COLLATE      = 10          # [lines] estimated number of lines to collate before emitting signal
                                     #   this results in collating about NUM_LINES_COLLATE * 48 bytes in a list of lines
                                     #   plotting and processing large amounts of data is more efficient for display and plotting
MAX_RECEIVER_INTERVAL  = 100         # [ms]
MIN_RECEIVER_INTERVAL  = 5           # [ms]


# UUIDs for the UART service and characteristics
SERVICE_UUID           = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
RX_CHARACTERISTIC_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
TX_CHARACTERISTIC_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

#BLE Constants
BLETIMEOUT             = 30  # Timeout for BLE operations
BLEMTUMAX              = 517
BLEMTUNORMAL           = 247

# Medibrick
TARGET_DEVICE_NAME     = "MediBrick_BLE"  # The name of the BLE device to search for
BLEPIN                 = 123456           # Known pairing pin for Medibrick_BLE

# Remove ANSI escape sequences
ANSI_ESCAPE            = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

##########################################################################################################################################        
##########################################################################################################################################        
#
# QBLESerial interaction with Graphical User Interface
#
# This section contains routines that can not be moved to a separate thread
# because it interacts with the QT User Interface.
# The BLE Worker is in a separate thread and receives data through signals from this class
#
# Receiving from BLE device is bytes or a list of bytes
# Sending to BLE device is bytes or list of bytes
# We need to encode/decode received/sent text in QBLESerialUI
#
#    This is the Controller (Presenter)  of the Model - View - Controller (MVC) architecture.
#
##########################################################################################################################################        
##########################################################################################################################################        

class QBLESerialUI(QObject):
    """
    Object providing functionality between User Interface and BLE Serial Worker.
    This interface must run in the main thread and interacts with user.

    Signals (to be emitted by UI abd picked up by BLE Worker)
        scanDevicesRequest                  request that QBLESerial is scanning for devices
        connectDeviceRequest                request that QBLESerial is connecting to device
        disconnectDeviceRequest             request that QBLESerial is disconnecting from device
        pairDeviceRequest                   request that QBLESerial is paring bluetooth device
        removeDeviceRequest                 request that QBLESerial is removing bluetooth device
        changeLineTerminationRequest        request that QBLESerial is using difference line termination
        sendFileRequest                     request that file is sent over BLE
        sendTextRequest                     request that provided text is transmitted over BLE
        sendLineRequest                     request that provided line of text is transmitted over BLE
        sendLinesRequest                    request that provided lines of text are transmitted over BLE
        bleStatusRequest                    request that QBLESerial reports current status
        setupTransceiverRequest             request that bluetoothctl interface and throughput timer is created
        setupBLEWorkerRequest               request that asyncio event loop is created and bluetoothctrl wrapper is started
        stopTransceiverRequest (not used)   request that bluetoothctl and throughput timer are stopped
        finishWorkerRequest                 request that QBLESerial worker is finished

    Slots (functions available to respond to external signals or events from buttons, input fields, etc.)
        on_pushButton_SendFile              send file over BLE
        on_pushButton_Clear                 clear the BLE text display window
        on_pushButton_StartStop             start/stop BLE transceiver
        on_pushButton_Save                  save text from display window into text file
        on_pushButton_Scan                  update BLE device list
        on_pushButton_Connect               open/close BLE device
        on_pushButton_Pair                  pair or remove BLE device
        on_pushButton_Trust                 trust or distrust BLE device
        on_pushButton_Status                request BLE device status
        on_comboBoxDropDown_BLEDevices      user selected a new BLE device from the drop down list
        on_comboBoxDropDown_LineTermination user selected a different line termination from drop down menu
        on_upArrowPressed                   recall previous line of text from BLE console line buffer
        on_downArrowPressed                 recall next line of text from BLE console line buffer
        on_carriageReturnPressed            transmit text from UI to BLE transceiver
        on_statusReady                      pickup BLE device status
        on_deviceListReady                  pickup new list of devices
        on_receivedData                     pickup text from BLE transceiver
        on_receivedLines                    pickup lines of text from BLE transceiver
        on_throughputReady                  pickup throughput data from BLE transceiver
        on_pairingSuccess                   pickup wether device pairing was successful
        on_removalSuccess                   pickup wether device removal was successful
        on_logSignal                        pickup log messages
    """

    # Signals
    ########################################################################################

    scanDevicesRequest           = pyqtSignal()                  # scan for BLE devices
    connectDeviceRequest         = pyqtSignal(BLEDevice, int, bool)  # connect to BLE device, mac, timeout, 
    disconnectDeviceRequest      = pyqtSignal()                  # disconnect from BLE device
    pairDeviceRequest            = pyqtSignal(str,str)           # pair with BLE device mac and pin
    removeDeviceRequest          = pyqtSignal(str)               # remove BLE device from systems paired list 
    trustDeviceRequest           = pyqtSignal(str)               # trust a device
    distrustDeviceRequest        = pyqtSignal(str)               # distrust a device
    changeLineTerminationRequest = pyqtSignal(bytes)             # request line termination to change
    sendTextRequest              = pyqtSignal(bytes)             # request to transmit text
    sendLineRequest              = pyqtSignal(bytes)             # request to transmit one line of text to TX
    sendLinesRequest             = pyqtSignal(list)              # request to transmit lines of text to TX
    sendFileRequest              = pyqtSignal(str)               # request to open file and send with transceiver
    bleStatusRequest             = pyqtSignal(str)               # request BLE device status
    setupTransceiverRequest      = pyqtSignal()                  # start transceiver
    setupBLEWorkerRequest        = pyqtSignal()                  # request that QBLESerial worker is setup
    stopTransceiverRequest       = pyqtSignal()                  # stop transceiver (display of incoming text, connection remains)
    finishWorkerRequest          = pyqtSignal()                  # request worker to finish
    setupBLEWorkerFinished       = pyqtSignal()                  # QBLESerial worker setup is finished
    setupTransceiverFinished     = pyqtSignal()                  # transceiver setup is finished
    workerFinished               = pyqtSignal()                  # worker is finished
           
    def __init__(self, parent=None, ui=None, worker=None, logger=None):
        """
        Need to provide the user interface and worker
        Start the timers for text display and log display trimming
        """

        super(QBLESerialUI, self).__init__(parent)

        # state variables, populated by service routines
        self.device                = ""       # BLE device
        self.device_info           = {}       # BLE device status
        self.bleSendHistory        = []       # previously sent text (e.g. commands)
        self.bleSendHistoryIndx    = -1       # init history
        self.rx                    = 0        # init throughput
        self.tx                    = 0        # init throughput 
        self.textLineTerminator    = b""      # default line termination: none
        self.encoding              = "utf-8"  # default encoding
        self.isLogScrolling        = False    # keep track of log display scrolling
        self.isTextScrolling       = False    # keep track of text display scrolling
        self.device_backup         = ""       # keep track of previously connected device
        self.transceiverIsRunning  = False    # BLE transceiver is not running

        self.lastNumReceived       = 0
        self.lastNumSent           = 0
    
        self.awaitingReconnection  = False
        self.record                = False                                                 # record serial data
        self.recordingFileName     = ""
        self.recordingFile         = None

        self.textBrowserLength     = MAX_TEXTBROWSER_LENGTH + 1

        self.instance_name = self.objectName() if self.objectName() else self.__class__.__name__

        if logger is None:
            self.logger = logging.getLogger("QBLE_UI")
        else:
            self.logger = logger

        if ui is None:
            self.handle_log(logging.ERROR, f"[{self.instance_name}] This applications needs to have access to User Interface")
            raise ValueError("User Interface (ui) is required but was not provided.")
        else:
            self.ui = ui

        if worker is None:
            self.handle_log(logging.ERROR, f"[{self.instance_name}] This applications needs to have access to BLE Worker")
            raise ValueError("BLE Worker (worker) is required but was not provided.")
        else:
            self.worker = worker
        
        # Text display window on serial text display
        self.ui.plainTextEdit_Text.setReadOnly(True)   # Prevent user edits
        self.ui.plainTextEdit_Text.setWordWrapMode(0)  # No wrapping for better performance

        self.textScrollbar = self.ui.plainTextEdit_Text.verticalScrollBar()
        self.ui.plainTextEdit_Text.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.textScrollbar.setSingleStep(1)                          # Highest resolution

        # Efficient text storage
        self.lineBuffer_text = deque(maxlen=MAX_TEXTBROWSER_LENGTH)       # Circular buffer


        # Log display window 
        self.ui.plainTextEdit_Log.setReadOnly(True)   # Prevent user edits
        self.ui.plainTextEdit_Log.setWordWrapMode(0)  # No wrapping for better performance

        self.logScrollbar = self.ui.plainTextEdit_Log.verticalScrollBar()
        self.ui.plainTextEdit_Log.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.logScrollbar.setSingleStep(1)                          # Highest resolution

        # Efficient text storage
        self.lineBuffer_log = deque(maxlen=MAX_TEXTBROWSER_LENGTH)       # Circular buffer


        # Limit the amount of text retained in the  text display window
        self.textTrimTimer = QTimer(self)
        self.textTrimTimer.timeout.connect(self.bleTextDisplay_trim)
        self.textTrimTimer.start(10000)  # Trigger every 10 seconds, this halts the display for a fraction of second, so dont do it often

        # Limit the amount of text retained in the log display window
        #   execute a text trim function every minute
        self.logTrimTimer = QTimer(self)
        self.logTrimTimer.timeout.connect(self.bleLogDisplay_trim)
        self.logTrimTimer.start(100000)  # Trigger every 10 seconds, this halts the display for a fraction of second, so dont do it often

        self.handle_log(logging.INFO,"QSerialUI initialized.")

    ########################################################################################
    # Helper functions
    ########################################################################################

    def handle_log(self, level, message):
        if level == logging.INFO:
            self.logger.info(message)
        elif level == logging.WARNING:
            self.logger.warning(message)
        elif level == logging.ERROR:
            self.logger.error(message)
        elif level == logging.DEBUG:
            self.logger.debug(message)
        elif level == logging.CRITICAL:
            self.logger.critical(message)
        else:
            self.logger.log(level, message)
        self.on_receivedLog(message, add_newline=True)

    def _safe_decode(self, byte_data, encoding="utf-8"):
        """
        Safely decodes a byte array to a string, replacing invalid characters.
        """
        try:
            return byte_data.decode(encoding)
        except UnicodeDecodeError as e:
            return byte_data.decode(encoding, errors="replace").replace("\ufffd", "¿")
        except Exception as e:
            return ""  # Return empty string if decoding completely fails

    ########################################################################################
    # Deal with Connections
    ########################################################################################

    def _safely_cleanconnect(signal, slot, previous_slot: None):
        try:
            if previous_slot is None:
                signal.disconnect()
            else:
                signal.disconnect(previous_slot)
        except TypeError:
            pass
        try:
            signal.connect(slot)
        except TypeError:
            pass

    def _safely_connect(signal, slot):
        try:
            signal.connect(slot)
        except TypeError:
            pass

    def _safely_disconnect(signal, slot):
        try:
            signal.disconnect(slot)
        except TypeError:
            pass

    ########################################################################################
    # Slots
    ########################################################################################

    @pyqtSlot(int,str)
    def on_logSignal(self, int, str):
        """pickup log messages, not used as no conenction with separate thread"""
        self.handle_log(int, str)

    @pyqtSlot()
    def on_carriageReturnPressed(self):
        """
        Transmitting text from UI to serial TX line
        """
        text = self.ui.lineEdit_Text.text()                                # obtain text from send input window
        if not text:
            self.ui.statusBar().showMessage("No text to send.", 2000)
            return
        
        self.displayingRunning.emit(True)            
        self.ui.pushButton_StartStop.setText("Stop")

        self.bleSendHistory.append(text)                             # keep history of previously sent commands
        self.bleSendHistoryIndx = len(self.bleSendHistory)           # reset history pointer
        
        try:
            text_bytearray = text.encode(self.encoding) + self.textLineTerminator # add line termination
        except UnicodeEncodeError:
            text_bytearray = text.encode("utf-8", errors="replace") + self.textLineTerminator
            self.handle_log(logging.WARNING, f"[{self.thread_id}]: Encoding error, using UTF-8 fallback.")
        except Exception as e:
            self.handle_log(logging.ERROR, f"[{self.thread_id}]: Encoding error: {e}")
            return
        
        self.sendTextRequest.emit(text_bytearray)                                # send text to serial TX line
        self.ui.lineEdit_Text.clear()
        self.ui.statusBar().showMessage("Text sent.", 2000)

    @pyqtSlot()
    def on_upArrowPressed(self):
        """
        Handle special keys on lineEdit: UpArrow
        """
        if not self.bleSendHistory:  # Check if history is empty
            self.ui.lineEdit_Text.setText("")
            self.ui.statusBar().showMessage("No commands in history.", 2000)
            return

        if self.bleSendHistoryIndx > 0:
            self.bleSendHistoryIndx -= 1
        else:
            self.bleSendHistoryIndx = 0  # Stop at oldest command

        self.ui.lineEdit_Text.setText(self.bleSendHistory[self.bleSendHistoryIndx])
        self.ui.statusBar().showMessage("Command retrieved from history.", 2000)
        
    @pyqtSlot()
    def on_downArrowPressed(self):
        """
        Handle special keys on lineEdit: DownArrow
        """
        if not self.serialSendHistory:
            self.ui.lineEdit_Text.setText("")
            self.ui.statusBar().showMessage("No commands in history.", 2000)
            return
    
        if self.serialSendHistoryIndx < len(self.serialSendHistory) - 1:
            self.serialSendHistoryIndx += 1
            self.ui.lineEdit_Text.setText(self.serialSendHistory[self.serialSendHistoryIndx])
        else:
            self.serialSendHistoryIndx = len(self.serialSendHistory)  # Move past last entry
            self.ui.lineEdit_Text.clear()
            self.ui.statusBar().showMessage("Ready for new command.", 2000)

    @pyqtSlot()
    def on_pushButton_SendFile(self):
        """Request to send a file over BLE."""
        stdFileName = ( QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation) + "/upload.txt" 
        )
        fname, _ = QFileDialog.getOpenFileName(
            self.ui, "Open", stdFileName, "Text files (*.txt)"
        )
        if fname:
            self.sendFileRequest.emit(fname)
        self.handle_log(logging.INFO, 'Text file send request completed.')            

    @pyqtSlot()
    def on_pushButton_Clear(self):
        """
        Clearing text display window
        """
        self.ui.plainTextEdit_Text.clear()
        self.ui.plainTextEdit_Log.clear()
        self.lineBuffer_text.clear()
        self.lineBuffer_log.clear()
        self.handle_log(logging.INFO, f"[{self.instance_name}] Text and Log display cleared.")
        self.ui.statusBar().showMessage("Text Display Cleared.", 2000)

    @pyqtSlot()
    def on_pushButton_StartStop(self):
        """
        Start BLE receiver
        This does not start or stop Transceiver, it just connects, disconnects signals
        """

        if self.ui.pushButton_StartStop.text() == "Start":
            # Start text display
            self.ui.pushButton_StartStop.setText("Stop")
            self.displayingRunning.emit(True)

            self.logger.log(
                logging.DEBUG,
                f"[{self.thread_id}]: turning text display on."
            )
            self.ui.statusBar().showMessage("Text Display Starting", 2000)

        else:
            # STOP text display
            self.ui.pushButton_StartStop.setText("Start")
            self.displayingRunning.emit(False)
            
            self.logger.log(
                logging.DEBUG, 
                f"[{self.thread_id}]: turning text display off."
            )
            self.ui.statusBar().showMessage('Text Display Stopping.', 2000)            

    @pyqtSlot()
    def on_pushButton_Save(self):
        """
        Saving text from display window into text file
        """
        stdFileName = (
            QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
            + "/QBLE.txt"
        )

        fname, _ = QFileDialog.getSaveFileName(
            self.ui, "Save as", stdFileName, "Text files (*.txt)"
        )

        if fname:
            if not fname.endswith(".txt"):
                fname += ".txt"

            with open(fname, "w") as f:
                f.write(self.ui.plainTextEdit_Text.toPlainText())

        self.handle_log(logging.INFO,"Text saved.")

    @pyqtSlot()
    def on_pushButton_Scan(self):
        """
        Update BLE device list
        """
        self.scanDevicesRequest.emit()
        self.ui.pushButton_Scan.setEnabled(False)
        self.ui.pushButton_Connect.setEnabled(False)
        self.handle_log(logging.INFO, f"[{self.instance_name}] BLE device list update requested.")

    @pyqtSlot()
    def on_pushButton_Connect(self):
        """
        Handle connect/disconnect requests.
        """
        if self.ui.pushButton_Connect.text() == "Connect":

            if self.device:
                self.connectDeviceRequest.emit(self.device, 10, False)
                self.handle_log(logging.INFO, f"[{self.instance_name}] Attempting to connect to device.")
            else:
                self.handle_log(logging.WARNING, f"[{self.instance_name}] No device selected for connection.")

        elif self.ui.pushButton_Connect.text() == "Disconnect":

            if self.device:
                self.disconnectDeviceRequest.emit()
                self.handle_log(logging.INFO, f"[{self.instance_name}] Attempting to disconnect from device.")
            else:
                self.handle_log(logging.WARNING, f"[{self.instance_name}] No device selected for disconnection.")

        else:
            self.handle_log(logging.ERROR, f"[{self.instance_name}] User interface Connect button is labeled incorrectly.")

    @pyqtSlot()
    def on_pushButton_Pair(self):
        """Trigger pairing with a device when the pair button is clicked."""
        
        if self.ui.pushButton_Pair.text() == "Pair":
        
            if self.device is not None:
                self.pairDeviceRequest.emit(self.device.address, self.BLEPIN)
                self.handle_log(logging.INFO, f"[{self.instance_name}] Paired with {self.TARGET_DEVICE_NAME}")
                self.ui.pushButton_Pair.setText("Remove")
                self._safely_disconnect(self.ui.pushButton_Pair.clicked, self.worker.on_pairDeviceRequest)
                self._safely_connect(self.ui.pushButton_Pair.clicked, self.worker.on_removeDeviceRequest)
            else:
                self.handle_log(logging.WARNING, f"[{self.instance_name}] No device set to pair")

        elif self.ui.pushButton_Pair.text() == "Remove":

            if self.device is not None:
                self.removeDeviceRequest.emit(self.device.address)
                self.handle_log(logging.INFO, f"[{self.instance_name}] {self.TARGET_DEVICE_NAME} removed")
                self.ui.pushButton_Pair.setText("Pair")
                self._safely_disconnect(self.ui.pushButton_Pair.clicked, self.worker.on_removeDeviceRequest)
                self._safely_connect(self.ui.pushButton_Pair.clicked, self.worker.on_pairDeviceRequest)
            else:
                self.handle_log(logging.WARNING, f"[{self.instance_name}] No device set to pair")

        else:
            self.handle_log(logging.ERROR, f"[{self.instance_name}] User interface Pair button is labeled incorrectly.")

    @pyqtSlot()
    def on_pushButton_Trust(self):
        """Trigger trusting with a device when the trust button is clicked."""
        
        if self.ui.pushButton_Trust.text() == "Trust":
        
            if self.device is not None:
                self.trustDeviceRequest.emit(self.device.address)
                self.handle_log(logging.INFO, f"[{self.instance_name}] Trusted {self.TARGET_DEVICE_NAME}")
                self.ui.pushButton_Trust.setText("Distrust")
                self._safely_disconnect(self.ui.pushButton_Trust.clicked, self.worker.on_trustDeviceRequest)
                self._safely_connect(self.ui.pushButton_Trust.clicked, self.worker.on_distrustDeviceRequest)
            else:
                self.handle_log(logging.WARNING, f"[{self.instance_name}] No device set to trust")

        elif self.ui.pushButton_Trust.text() == "Distrust":

            if self.device is not None:
                self.distrustDeviceRequest.emit(self.device.address)
                self.handle_log(logging.INFO, f"[{self.instance_name}] {self.TARGET_DEVICE_NAME} distrusted")
                self.ui.pushButton_Trust.setText("Trust")    
                self._safely_disconnect(self.ui.pushButton_Trust.clicked, self.worker.on_distrustDeviceRequest)
                self._safely_connect(self.ui.pushButton_Trust.clicked, self.worker.on_trustDeviceRequest)
            else:
                self.handle_log(logging.WARNING, f"[{self.instance_name}] No device set to trust")

        else:
            self.handle_log(logging.ERROR, f"[{self.instance_name}] User interface Trust button is labeled incorrectly.")

    @pyqtSlot()
    def on_pushButton_Status(self):
        if self.device is not None:
            self.bleStatusRequest.emit(self.device.address)

    @pyqtSlot()
    def on_comboBoxDropDown_BLEDevices(self): 
        "user selected a different BLE device from the drop down list"

        # disconnect current device
        self.disconnectDeviceRequest.emit()

        # prepare UI for new selection
        index=self.ui.comboBoxDropDown_Device.currentIndex()
        if index >= 0:
            self.device = self.ui.comboBoxDropDown_Device.itemData(index) # BLE device from BLEAK scanner
            self.handle_log(logging.INFO, f"[{self.instance_name}] Selected device: {self.device.name}, Address: {self.device.address}")
            self.ui.pushButton_Connect.setEnabled(True) # will want to connect
            if self.hasBluetoothctl: self.ui.pushButton_Pair.setEnabled(True) # uses bluetoothctl
            if self.hasBluetoothctl: self.ui.pushButton_Trust.setEnabled(True) # uses bluetoothctl
            if self.hasBluetoothctl: self.ui.pushButton_Status.setEnabled(True) # uses bluetoothctl
            self.ui.pushButton_SendFile.setEnabled(False) # its not yet connected
            self.ui.pushButton_Pair.setText("Pair")
            self.ui.pushButton_Connect.setText("Connect")
            self.ui.pushButton_Trust.setText("Trust")
        else:
            self.handle_log(logging.WARNING, f"[{self.instance_name}] No devices found")
            self.ui.pushButton_Connect.setEnabled(False)
            if self.hasBluetoothctl: self.ui.pushButton_Pair.setEnabled(False)
            if self.hasBluetoothctl: self.ui.pushButton_Trust.setEnabled(False)
            if self.hasBluetoothctl: self.ui.pushButton_Status.setEnabled(False)
            self.ui.pushButton_SendFile.setEnabled(False)
            self.ui.pushButton_Scan.setEnabled(True)

    @pyqtSlot()
    def on_comboBoxDropDown_LineTermination(self):
        """
        User selected a different line termination from drop down menu
        """
        _tmp = self.ui.comboBoxDropDown_LineTermination.currentText()
        if   _tmp == "newline (\\n)":           self.textLineTerminator = b"\n"
        elif _tmp == "return (\\r)":            self.textLineTerminator = b"\r"
        elif _tmp == "newline return (\\n\\r)": self.textLineTerminator = b"\n\r"
        elif _tmp == "none":                    self.textLineTerminator = b""
        else:                                   self.textLineTerminator = b"\r\n"

        # ask line termination to be changed
        self.changeLineTerminationRequest.emit(self.textLineTerminator)        
        self.handle_log(logging.INFO, f"[{self.instance_name}] line termination {repr(self.textLineTerminator)}")

    @pyqtSlot()
    def on_comboBoxDropDown_DataSeparator(self):
        """
        User selected a different data separator from drop down menu
        """
        _idx = self.ui.comboBoxDropDown_DataSeparator.currentIndex()
        if   _idx == 0: self.dataSeparator = 0
        elif _idx == 1: self.dataSeparator = 1
        elif _idx == 2: self.dataSeparator = 2
        elif _idx == 3: self.dataSeparator = 3
        else:           self.dataSeparator = 0

        self.handle_log(logging.INFO, f"[{self.instance_name}] data separator {repr(self.dataSeparator)}")

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
        self.device_info = status

        if (self.device_info["mac"] is not None) and (self.device_info["mac"] != ""): 
            if self.device_info["paired"]:
                self.ui.pushButton_Pair.setEnabled(True)
                self.ui.pushButton_Pair.setText("Remove")
            else:
                self.ui.pushButton_Pair.setEnabled(True)
                self.ui.pushButton_Pair.setText("Pair")

            if self.device_info["trusted"]:
                self.ui.pushButton_Trust.setEnabled(True)
                self.ui.pushButton_Trust.setText("Distrust")
            else:
                self.ui.pushButton_Trust.setEnabled(True)
                self.ui.pushButton_Trust.setText("Trust")

        self.handle_log(logging.INFO, f"[{self.instance_name}] Device status: {status}")

    @pyqtSlot(list)
    def on_deviceListReady(self, devices:list):
        """pickup new list of devices"""
        self.ui.pushButton_Scan.setEnabled(True) # re-enable device scan, was turned of during scanning

        # save current selected device 
        currentIndex   = self.ui.comboBoxDropDown_Device.currentIndex()
        selectedDevice = self.ui.comboBoxDropDown_Device.itemData(currentIndex)

        self.ui.comboBoxDropDown_Device.blockSignals(True)
        self.ui.comboBoxDropDown_Device.clear()
        for device in devices:
            self.ui.comboBoxDropDown_Device.addItem(f"{device.name} ({device.address})", device)
        
        # search for previous device and select it
        if selectedDevice is not None:
            for index in range(self.ui.comboBoxDropDown_Device.count()):
                if self.ui.comboBoxDropDown_Device.itemData(index) == selectedDevice:
                    self.ui.comboBoxDropDown_Device.setCurrentIndex(index)
                    break

        self.ui.comboBoxDropDown_Device.blockSignals(False)
        if len(devices) > 0:
            self.ui.pushButton_Connect.setEnabled(True)
        self.handle_log(logging.INFO, f"[{self.instance_name}] Device list updated.")   


    @pyqtSlot(bytes)
    def on_receivedData(self, byte_array: bytes):
        """
        Receives a raw byte array from the serial port, decodes it, stores it in a line-based buffer,
        and updates the text display efficiently.
        """
        self.handle_log(logging.DEBUG, f"[{self.thread_id}]: text received.")

        # 1. Decode byte array
        text = self._safe_decode(byte_array, self.encoding)
        
        if DEBUGSERIAL:
            self.handle_log(logging.DEBUG, f"[{self.thread_id}]: {text}")

        # 2. Record text to a file if recording is enabled
        if self.record:
            try:
                self.recordingFile.write(byte_array)
            except Exception as e:
                self.logger.log(logging.ERROR, f"[{self.thread_id}]: Could not write to file {self.recordingFileName}. Error: {e}")
                self.record = False
                self.ui.radioButton_SerialRecord.setChecked(self.record)

        # 3. Append new text to the display and buffer
        if text:
            scrollbar = self.textScrollbar
            at_bottom = scrollbar.value() >= scrollbar.maximum() - 20

            # Append text to display
            self.ui.plainTextEdit_Text.appendPlainText(text)

            # 4. Store lines in the `deque`
            new_lines = text.split("\n")
            self.lineBuffer_text.extend(new_lines)  # Automatically trims excess lines

            # 5. Maintain scroll position if at the bottom
            if at_bottom:
                scrollbar = self.textScrollbar
                scrollbar.setValue(scrollbar.maximum())

        # results.append({
        #     "datatype": data_type,
        #     "name": self.name.get(data_type, f"Unknown_{data_type}"),
        #     "data": numbers,
        #     "timestamp": time.time(),  # Add a timestamp
        # })
        #
        # numbers can be list of floats for ArduinoTextStreamProcessor
        # numbers can be byte, int8, unit8, int16, uint16, int32, uint32, float, double, list of strings, numpy arrays, for BinaryStreamProcessor

        # for result in results:
        #     data_type = result.get("datatype", "Unknown")
        #     name      = result.get("name", "Unknown Name")
        #     data      = result.get("data", "No Data")
        #     timestamp = result.get("timestamp", "No Timestamp")

        #     self.handle_log(
        #         logging.DEBUG,
        #         f"Result Processed - Type: {data_type}, Name: {name}, "
        #         f"Data: {data}, "
        #         f"Timestamp: {timestamp}"
        #     )

    @pyqtSlot()
    def on_SerialRecord(self):
        self.record = self.ui.radioButton_SerialRecord.isChecked()
        if self.record:
    
            if self.recordingFileName == "":
                stdFileName = (
                    QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
                    + "/Qble.txt"
                ) 
            else:
                stdFileName = self.recordingFileName
    
            self.recordingFileName, _ = QFileDialog.getOpenFileName(
                self.ui, "Open", stdFileName, "Text files (*.txt)"
            )

            if not self.recordingFileName:
                self.record = False
                self.ui.radioButton_SerialRecord.setChecked(self.record)
            else:
                file_path = Path(self.recordingFileName)

                if file_path.exists():  # Check if file already exists
                    msg_box = QMessageBox()
                    msg_box.setIcon(QMessageBox.Warning)
                    msg_box.setWindowTitle("File Exists")
                    msg_box.setText(f"The file '{file_path.name}' already exists. What would you like to do?")
                    msg_box.addButton("Overwrite", QMessageBox.YesRole)
                    msg_box.addButton("Append", QMessageBox.NoRole)

                    choice = msg_box.exec_()

                    if choice == 0:  # Overwrite
                        mode = "wb"
                    elif choice == 1:  # Append
                        mode = "ab"
                    else: 
                        self.logger.log(logging.INFO, f"[{self.thread_id}]: Overwrite choice aborted.")  
                        self.record = False
                        self.ui.radioButton_SerialRecord.setChecked(self.record)
                        return
                else:
                    mode = "wb"  # Default to write mode if file doesn't exist

                try:
                    self.recordingFile = open(file_path, mode)
                    self.logger.log(logging.INFO, f"[{self.thread_id}]: Recording to file {file_path.name} in mode {mode}.")
                except Exception as e:
                    self.logger.log(logging.ERROR, f"[{self.thread_id}]: Could not open file {file_path.name} in mode {mode}.")
                    self.record = False
                    self.ui.radioButton_SerialRecord.setChecked(self.record)
        else:
            if self.recordingFile:
                try:
                    self.recordingFile.close()
                    self.logger.log(logging.INFO, f"[{self.thread_id}]: Recording to file {self.recordingFile.name} stopped.")
                except Exception as e:
                    self.logger.log(logging.ERROR, f"[{self.thread_id}]: Could not close file {self.recordingFile.name}.")
                self.recordingFile = None

    @pyqtSlot(list)
    def on_receivedLines(self, lines: list):
        """
        Receives lines of text from the serial port, stores them in a circular buffer,
        and updates the text display efficiently.
        """
        self.logger.log(logging.DEBUG, f"[{self.thread_id}]: text lines received.")

        # 1. Record lines to file if recording is enabled
        if self.record:
            try:
                self.recordingFile.writelines(lines)
            except Exception as e:
                self.logger.log(logging.ERROR, f"[{self.thread_id}]: Could not write to file {self.recordingFileName}. Error: {e}")
                self.record = False
                self.ui.radioButton_SerialRecord.setChecked(self.record)

        # 2. Decode all lines efficiently
        decoded_lines = [self._safe_decode(line, self.encoding) for line in lines]

        if DEBUGSERIAL:
            for decoded_line in decoded_lines:
                self.logger.log(logging.DEBUG, f"[{self.thread_id}]: {decoded_line}")

        # 3. Append to `deque` (automatically trims when max length is exceeded)
        self.lineBuffer_text.extend(decoded_lines)

        # 4. Append text to display
        if decoded_lines:
            text = "\n".join(decoded_lines)

            # Check if user has scrolled to the bottom
            scrollbar = self.textScrollbar
            at_bottom = scrollbar.value() >= scrollbar.maximum() - 20

            self.ui.plainTextEdit_Text.appendPlainText(text)

            # If the user was at the bottom, keep scrolling
            if at_bottom:
                scrollbar = self.textScrollbar
                scrollbar.setValue(scrollbar.maximum())

    @pyqtSlot(float,float)
    def on_throughputReady(self, numReceived:int, numSent:int):
        """pickup throughput data from BLE transceiver"""

        rx = numReceived - self.lastNumReceived
        tx = numSent - self.lastNumSent
        if rx >=0: self.rx = rx
        if tx >=0: self.tx = tx
        # # poor man's low pass
        # self.rx = 0.5 * self.rx + 0.5 * rx
        # self.tx = 0.5 * self.tx + 0.5 * tx
        self.ui.label_throughput.setText(
            "RX:{:<5.1f} TX:{:<5.1f} kB/s".format(self.rx / 1024, self.tx / 1024)
        )
        self.lastNumReceived = numReceived
        self.lastNumSent     = numSent

    @pyqtSlot(bool)
    def on_connectingSuccess(self, success):
        """pickup wether device connection was successful"""
        self.device_info["connected"] = success

        if success:
            self.ui.pushButton_SendFile.setEnabled(True)
            self.ui.pushButton_Connect.setEnabled(True)
            self.ui.pushButton_Connect.setText("Disconnect")
            
        else:
            self.ui.pushButton_SendFile.setEnabled(False)
            self.ui.pushButton_Connect.setEnabled(True)
            self.ui.pushButton_Connect.setText("Connect")

        self.handle_log(logging.INFO, f"[{self.instance_name}] Device {self.device.name} connection: {'successful' if success else 'failed'}")


    @pyqtSlot()
    def on_disconnectingSuccess(self, success):
        """pickup wether device disconnection was successful"""
        self.device_info["connected"] = not(success)

        if success: # disconnecting
            self.ui.pushButton_SendFile.setEnabled(False)
            self.ui.pushButton_Connect.setEnabled(True)
            self.ui.pushButton_Connect.setText("Connect")
        else: # disconnecting failed
            self.ui.pushButton_Connect.setEnabled(True)
            self.ui.pushButton_Connect.setText("Disconnect")

        self.handle_log(logging.INFO, f"[{self.instance_name}] Device {self.device.name} disconnection: {'successful' if success else 'failed'}")

    @pyqtSlot(bool)
    def on_pairingSuccess(self, success):
        """pickup wether device pairing was successful"""
        self.device_info["paired"] = success
        if success:
            self.ui.pushButton_Pair.setEnabled(True)
            self.ui.pushButton_Pair.setText("Remove")
        else:
            self.ui.pushButton_Pair.setEnabled(True)
            self.ui.pushButton_Pair.setText("Pair")

        self.handle_log(logging.INFO, f"[{self.instance_name}] Device {self.device.name} pairing: {'successful' if success else 'failed'}")

    @pyqtSlot(bool)
    def on_removalSuccess(self, success):
        """pickup wether device removal was successful"""
        self.device_info["paired"] = not(success)

        if success: # removing
            self.ui.pushButton_Pair.setEnabled(True)
            self.ui.pushButton_Pair.setText("Pair")
        else: # removing failed
            self.ui.pushButton_Pair.setEnabled(True)
            self.ui.pushButton_Pair.setText("Remove")

        self.handle_log(logging.INFO, f"[{self.instance_name}] Device {self.device.name} removal: {'successful' if success else 'failed'}")

    @pyqtSlot(bool)
    def on_trustSuccess(self, success):
        """pickup wether device pairing was successful"""
        self.device_info["trusted"] = success
        if success:
            self.ui.pushButton_Trust.setEnabled(True)
            self.ui.pushButton_Trust.setText("Distrust")
        else:
            self.ui.pushButton_Trust.setEnabled(True)
            self.ui.pushButton_Trust.setText("Trust")

        self.handle_log(logging.INFO, f"[{self.instance_name}] Device {self.device.name} trusting: {'successful' if success else 'failed'}")

    @pyqtSlot(bool)
    def on_distrustSuccess(self, success):
        """pickup wether device removal was successful"""
        self.device_info["trusted"] = not(success)

        if success: # removing
            self.ui.pushButton_Trust.setEnabled(True)
            self.ui.pushButton_Trust.setText("Trust")
        else: # removing failed
            self.ui.pushButton_Trust.setEnabled(True)
            self.ui.pushButton_Trust.setText("Distrust")

        self.handle_log(logging.INFO, f"[{self.instance_name}] Device {self.device.name} distrusting: {'successful' if success else 'failed'}")


    @pyqtSlot()
    def bleTextDisplay_trim(self):
        """
        Reduce the amount of text kept in the text display window
        Attempt to keep the scrollbar location
        """

        tic = time.perf_counter()

        # 0 Do we need to trim?
        textDisplayLineCount = self.ui.plainTextEdit_Text.document().blockCount() # 70 micros
 
        if textDisplayLineCount > self.textBrowserLength:

            old_textDisplayLineCount = textDisplayLineCount
            scrollbar = self.textScrollbar  # Avoid redundant calls

            #  1 Where is the current scrollbar? (scrollbar value is pixel based)
            old_scrollbarMax = scrollbar.maximum()
            old_scrollbarValue = scrollbar.value()

            old_proportion = (old_scrollbarValue / old_scrollbarMax) if old_scrollbarMax > 0 else 1.0            
            old_linePosition = round(old_proportion * old_textDisplayLineCount)

            # 2 Replace text with the line buffer
            # lines_inTextBuffer  = len(self.lineBuffer_text)
            text = "\n".join(self.lineBuffer_text)
            self.ui.plainTextEdit_Text.setPlainText(text)
            new_textDisplayLineCount = self.ui.plainTextEdit_Text.document().blockCount()
            # new_textDisplayLineCount = lines_inTextBuffer + 1

            # 3 Update the scrollbar position
            new_scrollbarMax = self.textScrollbar.maximum()            
            if new_textDisplayLineCount > 0:
                new_linePosition = max(0, (old_linePosition - (old_textDisplayLineCount - new_textDisplayLineCount)))
                new_proportion = new_linePosition / new_textDisplayLineCount
                new_scrollbarValue = round(new_proportion * new_scrollbarMax)
            else:
                new_scrollbarValue = 0

            # 4 Ensure that text is scrolling when we set cursor towards the end

            if new_scrollbarValue >= new_scrollbarMax - 20:
                self.textScrollbar.setValue(new_scrollbarMax)  # Scroll to the bottom
            else:
                self.textScrollbar.setValue(new_scrollbarValue)

            toc = time.perf_counter()
            self.handle_log(
                logging.INFO,
                f"[{self.thread_id}]: trimmed text display in {(toc-tic)*1000:.2f} ms."
            )

        self.ui.statusBar().showMessage('Trimmed Text Display Window', 2000)


    @pyqtSlot()
    def bleLogDisplay_trim(self):
        """
        Reduce the amount of text kept in the log display window
        Attempt to keep the scrollbar location
        """

        tic = time.perf_counter()

        # 0 Do we need to trim?
        logDisplayLineCount = self.ui.plainTextEdit_Log.document().blockCount() # 70 micros
 
        if logDisplayLineCount > self.textBrowserLength:

            old_logDisplayLineCount = logDisplayLineCount
            scrollbar = self.logScrollbar  # Avoid redundant calls

            #  1 Where is the current scrollbar? (scrollbar value is pixel based)
            old_scrollbarMax = scrollbar.maximum()
            old_scrollbarValue = scrollbar.value()

            old_proportion = (old_scrollbarValue / old_scrollbarMax) if old_scrollbarMax > 0 else 1.0            
            old_linePosition = round(old_proportion * old_logDisplayLineCount)

            # 2 Replace text with the line buffer
            text = "\n".join(self.lineBuffer_log)
            self.ui.plainTextEdit_Log.setPlainText(text)
            new_logDisplayLineCount = self.ui.plainTextEdit_Log.document().blockCount()

            # 3 Update the scrollbar position
            new_scrollbarMax = self.textScrollbar.maximum()            
            if new_logDisplayLineCount > 0:
                new_linePosition = max(0, (old_linePosition - (old_logDisplayLineCount - new_textDisplayLineCount)))
                new_proportion = new_linePosition / new_logDisplayLineCount
                new_scrollbarValue = round(new_proportion * new_scrollbarMax)
            else:
                new_scrollbarValue = 0

            # 4 Ensure that text is scrolling when we set cursor towards the end
            if new_scrollbarValue >= new_scrollbarMax - 20:
                self.logScrollbar.setValue(new_scrollbarMax)  # Scroll to the bottom
            else:
                self.logScrollbar.setValue(new_scrollbarValue)

            toc = time.perf_counter()
            self.handle_log(
                logging.INFO,
                f"[{self.thread_id}]: trimmed log display in {(toc-tic)*1000:.2f} ms."
            )

        self.ui.statusBar().showMessage('Trimmed Log Display Window', 2000)

    def cleanup(self):
        """
        Perform cleanup tasks for QBLESerialUI, such as stopping timers, disconnecting signals,
        and ensuring proper worker shutdown.
        """
        self.logger.info("Performing QBLESerialUI cleanup...")

        if hasattr(self.recordingFile, "close"):
            try:
                self.recordingFile.close()
            except:
                self.handle_log(
                    logging.ERROR, 
                    f"[{self.thread_id}]: Could not close file {self.recordingFileName}."
                )

        # Stop timers
        if self.textTrimTimer.isActive():
            self.textTrimTimer.stop()
        if self.logTrimTimer.isActive():
            self.logTrimTimer.stop()

        self.textTrimTimer.timeout.disconnect()
        self.logTrimTimer.timeout.disconnect()

        self.handle_log(
            logging.INFO, 
            f"[{self.thread_id}]: cleaned up."
        )


##########################################################################################################################################        
##########################################################################################################################################        
#
# Q BLE Serial
#
# separate thread handling BLE serial input and output
# these routines have no access to the user interface,
# communication occurs through signals
#
# for BLE device write we send bytes
# for BLE device read we receive bytes
# conversion from text to bytes occurs in QBLESerialUI
#
#    This is the Model of the Model - View - Controller (MVC) architecture.
#
##########################################################################################################################################        
##########################################################################################################################################        

class QBLESerial(QObject):
    """
    BLE Serial Worker for QT

    Worker Signals
        receivedData(bytes)                    received text through BLE
        receivedLines(list)                    received multiple lines from BLE
        deviceListReady(list)                  completed a device scan
        throughputReady(float, float)          throughput data is available (RX, TX)
        statusReady(dict)                      report BLE status
        pairingSuccess(bool)                   was pairing successful
        removalSuccess(bool)                   was removal successful
        logSignal(int, str)                    log message available
        finished                               worker finished
    
    Worker Slots
        on_scanDevicesRequest()                request scanning for devices
        on_connectDeviceRequest(LEDevice,int,bool)) request connecting to device (device must be selected first)
        on_disconnectDeviceRequest()           request disconnecting from device
        on_pairDeviceRequest(str, str)         request pairing with bluetooth device mac and pin
        on_removeDeviceRequest(str)            request removing paired bluetooth device
        on_trustDeviceRequest(str)             request trusting a device
        on_distrustDeviceRequest(str)          request distrust a device
        on_sendTextRequest(bytes)              request sending raw bytes over BLE
        on_sendLineRequest(bytes)              request sending a line of text (with EOL) over BLE
        on_sendLinesRequest(list of bytes)     request sending multiple lines of text over BLE
        on_sendFileRequest(str)                request sending a file over BLE
        on_setupTransceiverRequest()           setup bluetoothctl and QTimer for throughput
        on_setupBLEWorkerRequest()             setup Worker asyncio loop and bluetoothctl
        on_stopTransceiverRequest()            stop bluetoothctl and QTimer
        on_changeLineTerminationRequest(bytes) change line termination sequence
        on_bleStatusRequest(str)               request BLE status of a device by MAC
        on_finishWorkerRequest()               finish the worker

    Additional helper method:
        on_selectDeviceRequest(str)            select a device from scanned devices by MAC
    """

    # Signals
    ########################################################################################

    receivedData             = pyqtSignal(bytes)         # text received 
    receivedLines            = pyqtSignal(list)          # lines of text received
    deviceListReady          = pyqtSignal(list)          # updated list of BLE devices  
    throughputReady          = pyqtSignal(float, float)  # RX, TX bytes per second
    statusReady              = pyqtSignal(dict)          # BLE device status dictionary
    connectingSuccess        = pyqtSignal(bool)          # Connecting result
    disconnectingSuccess     = pyqtSignal(bool)          # Disconnecting result
    pairingSuccess           = pyqtSignal(bool)          # Pairing result
    removalSuccess           = pyqtSignal(bool)          # Removal result
    trustSuccess             = pyqtSignal(bool)          # Trusting result
    distrustSuccess          = pyqtSignal(bool)          # Distrusting result
    logSignal                = pyqtSignal(int, str)      # Logging
    setupBLEWorkerFinished   = pyqtSignal()              # Setup worker completed
    setupTransceiverFinished = pyqtSignal()              # Transceiver setup completed
    finished                 = pyqtSignal()              # Worker finished
                                    # request to open file and send over serial port
           
    def __init__(self, parent=None):

        super(QBLESerialUI, self).__init__(parent)

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"

        # state variables, populated by service routines
        self.device_backup     = None
        self.awaitingReconnection  = False

        self.device = None
        self.client = None
        self.bluetoothctlWrapper = None
        self.eol = None
        self.partial_line = b""
        self.rx                    = 0                                                     # init throughput
        self.tx                    = 0                                                     # init throughput 

        self.PIN = "0000"  # Placeholder PIN if required by pairing
        self.reconnect = False

        self.NSUdevices = []
        self.device_info = {
            "mac":       None,
            "name":      None,
            "paired":    None,
            "trusted":   None,
            "connected": None,
            "rssi":      None
        }

        # might be obsolete
        self.isScrolling           = False    # keep track of text display scrolling

        self.asyncEventLoop = None
        self.asyncEventLoopThread = None

        self.instance_name = self.objectName() if self.objectName() else self.__class__.__name__

        self.logger = logging.getLogger("QSerUI_")

    ########################################################################################
    # Utility Functions
    ########################################################################################

    def wait_for_signal(self, signal) -> float:
        """Utility to wait until a signal is emitted."""
        tic = time.perf_counter()
        loop = QEventLoop()
        signal.connect(loop.quit)
        loop.exec()
        return time.perf_counter() - tic

    def handle_log(self, level:int, message:str):
        """Emit the log signal with a level and message."""
        self.logSignal.emit(level, message)

    def run_asyncEventLoop(self):
        """Start the asyncio event loop."""
        self.asyncEventLoop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.asyncEventLoop)
        try:
            self.asyncEventLoop.run_forever()
        except asyncio.CancelledError:
            self.handle_log(logging.INFO, f"[{self.instance_name}] Could not start Asyncio event loop.")
        finally:
            self.asyncEventLoop.close()

    def stop_asyncEventLoop(self):
        """Stop the asyncio event loop and its thread."""
        if self.asyncEventLoop and self.asyncEventLoop.is_running():
            self.asyncEventLoop.call_soon_threadsafe(self.asyncEventLoop.stop)
        if self.asyncEventLoopThread is not None:
            self.asyncEventLoopThread.join(timeout=2.0)
            self.asyncEventLoopThread = None

        self.handle_log(logging.INFO, f"[{self.instance_name}] Asyncio event loop and thread stopped.")            

    def schedule_async(self, coro):
        """Post a coroutine to the asyncio event loop."""
        if hasattr(self, "asyncEventLoop"):
            if self.asyncEventLoop is not None:
                if self.asyncEventLoop.is_running():
                    future = asyncio.run_coroutine_threadsafe(coro, self.asyncEventLoop)
                    return future
                else:
                    self.handle_log(logging.ERROR, "Asyncio event loop not running; cannot schedule async task.")
            else:
                self.handle_log(logging.ERROR, "Asyncio event loop is None; cannot schedule async task.")
        else:
            self.handle_log(logging.ERROR, "Asyncio event loop not available; cannot schedule async task.")

    ########################################################################################
    # Slots
    ########################################################################################


    # Setting up Worker in separate thread
    ########################################################################################

    @pyqtSlot()
    def on_setupBLEWorkerRequest(self):

        # Start the asyncio event loop for this worker
        # Need to use threading, cannot use QThread
        self.asyncEventLoopThread = threading.Thread(target=self.run_asyncEventLoop, daemon=True)
        self.asyncEventLoopThread.start()
        self.handle_log(logging.INFO, f"[{self.instance_name}] Asyncio event loop and thread started.")

        self.setupBLEWorkerFinished.emit()

    # Throughput
    # ----------
    @pyqtSlot()
    def on_setupTransceiverRequest(self):
        """
        Setup Timers and Program Wrapper
        """
        
        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"

        # Throughput tracking

        self.throughputTimer = QTimer(self)
        self.throughputTimer.setInterval(1000)
        self.throughputTimer.timeout.connect(self.on_throughputTimer)

        self.setupTransceiverFinished.emit()
        self.handle_log(logging.INFO, f"[{self.instance_name}] Throughput timer is set up.")


    @pyqtSlot()
    def on_startThroughputRequest(self):
        """
        Stop QTimer for reading through put from PSer)
        """
        self.throughputTimer.start()
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: started throughput timer."
        )


    @pyqtSlot()
    def on_stopThroughputRequest(self):
        """
        Stop QTimer for reading throughput from PSer)
        """
        self.throughputTimer.stop()
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: stopped throughput timer."
        )

    @pyqtSlot()
    def on_throughputTimer(self):
        """
        Report throughput.
        """
        self.throughputReady.emit(self.bytes_received, self.bytes_sent)
    
    @pyqtSlot()
    def on_stopTransceiverRequest(self):
        """Stop bluetoothctl and QTimer."""

        if hasattr(self, 'throughputTimer'):
            self.throughputTimer.stop()
            self.handle_log(logging.INFO, f"[{self.instance_name}] Throughput timer stopped.")

    @pyqtSlot()
    def on_finishWorkerRequest(self):
        """Handle Cleanup of the worker."""
        self.on_stopTransceiverRequest()

        # Disconnect BLE client if connected
        if self.client and self.client.is_connected:
            try:
                asyncio.run(self.client.disconnect())
                self.handle_log(logging.INFO, f"[{self.instance_name}] Disconnected BLE client.")
            except Exception as e:
                self.handle_log(logging.ERROR, f"[{self.instance_name}] Error disconnecting BLE client: {e}")
            finally:
                self.client = None

        # Reset worker state
        self.device = None
        self.bytes_received = 0
        self.bytes_sent = 0
        self.partial_line = b""

        # Stop the asyncio event loop
        self.stop_asyncEventLoop()

        self.handle_log(logging.INFO, f"[{self.instance_name}] BLE Serial Worker cleanup completed.")

        # Emit finished signal
        self.finished.emit()

    # Response Functions to User Interface Signals: Settings
    ########################################################################################

    # Misc
    # ----

    @pyqtSlot(bytes)
    def on_changeLineTerminationRequest(self, lineTermination: bytes):
        """
        Set the new line termination sequence.
        """
        if lineTermination is None:
            self.handle_log(logging.WARNING, f"[{self.instance_name}] Line termination not changed, no line termination string provided.")
        else:
            self.eol = lineTermination
            self.handle_log(logging.INFO, f"[{self.instance_name}] Changed line termination to {repr(self.eol)}.")

    # BLE Device Status
    # -----------------

    @pyqtSlot(str)
    def on_bleStatusRequest(self, mac: str):
        """Request device status by MAC."""

        if self.bluetoothctlWrapper is None:
            # Initialize BluetoothctlWrapper (assumes BluetoothctlWrapper is defined elsewhere)
            self.bluetoothctlWrapper = BluetoothctlWrapper("bluetoothctl")
            self.bluetoothctlWrapper.log_signal.connect(self.handle_log)
            self.bluetoothctlWrapper.start()
            time_elapsed = self.wait_for_signal(self.bluetoothctlWrapper.startup_completed_signal) * 1000
            self.handle_log(logging.INFO, f"[{self.instance_name}] bluetoothctl wrapper started in {time_elapsed:.2f} ms.")

        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.get_device_info(mac=mac, timeout=2000)
            self.bluetoothctlWrapper.device_info_ready_signal.connect(self._on_device_info_ready)
            self.bluetoothctlWrapper.device_info_failed_signal.connect(self._on_device_info_failed)
            self.handle_log(logging.INFO, f"[{self.instance_name}] Bluetoothctl wrapper status requested.")
        else:
            self.handle_log(logging.ERROR, f"[{self.instance_name}] Bluetoothctl wrapper not available for status request.")

    @pyqtSlot(dict)
    def _on_device_info_ready(self, info: dict):
        self.handle_log(logging.INFO, f"[{self.instance_name}] Device info retrieved: {info}")
        self.device_info.update(info)
        self.statusReady.emit(self.device_info)
        # Disconnect signals
        self.bluetoothctlWrapper.device_info_ready_signal.disconnect(self._on_device_info_ready)
        self.bluetoothctlWrapper.device_info_failed_signal.disconnect(self._on_device_info_failed)

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.handle_log(logging.INFO, f"[{self.instance_name}] Bluetoothctl stopped.")

    @pyqtSlot(str)
    def _on_device_info_failed(self, mac: str):
        self.handle_log(logging.ERROR, f"[{self.instance_name}] Failed to retrieve device info for MAC: {mac}")
        self.bluetoothctlWrapper.device_info_ready_signal.disconnect(self._on_device_info_ready)
        self.bluetoothctlWrapper.device_info_failed_signal.disconnect(self._on_device_info_failed)

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.handle_log(logging.INFO, f"[{self.instance_name}] Bluetoothctl stopped.")

    # BLE Device Scan
    # ---------------

    @pyqtSlot()
    def on_scanDevicesRequest(self):
        self.schedule_async(self._scanDevicesRequest())

    async def _scanDevicesRequest(self):
        """Scan for BLE devices offering the Nordic UART Service."""
        try:
            self.handle_log(logging.INFO, f"[{self.instance_name}] Scanning for BLE devices.")
            devices = await BleakScanner.discover(timeout=5, return_adv=True)
        except Exception as e:
            self.handle_log(logging.ERROR, f"[{self.instance_name}] Error scanning for devices: {e}")
            return
        
        if not devices:
            self.handle_log(logging.INFO, f"[{self.instance_name}] No devices found.")
        
        self.NSUdevices = []
        for device, adv in devices.values():
            for service_uuid in adv.service_uuids:
                if service_uuid.lower() == self.SERVICE_UUID.lower():
                    self.NSUdevices.append(device)
        
        if not self.NSUdevices:
            self.handle_log(logging.INFO, f"[{self.instance_name}] Scan complete. No matching devices found.")
        else:        
            self.handle_log(logging.INFO, f"[{self.instance_name}] Scan complete. Select a device from the dropdown.")
        self.deviceListReady.emit(self.NSUdevices)

    # BLE Device Connect
    # ------------------

    @pyqtSlot(str)
    def on_selectDeviceRequest(self, mac: str):
        """Select a device from the scanned devices by MAC."""
        for dev in self.NSUdevices:
            if dev.address == mac:
                self.device = dev
                self.handle_log(logging.INFO, f"[{self.instance_name}] Device selected: {dev.name} ({dev.address})")
                return
        self.handle_log(logging.WARNING, f"[{self.instance_name}] No device found with MAC {mac}")

    @pyqtSlot(BLEDevice, int, bool)
    def on_connectDeviceRequest(self, device: BLEDevice, timeout: int, reconnect: bool):
        self.schedule_async(self._connectDeviceRequest(device=device, timeout=timeout, reconnect=reconnect))

    async def _connectDeviceRequest(self, device: BLEDevice, timeout: int, reconnect: bool):
        """
        Slot to handle the connection request to a BLE device.

        Parameters:
            device (BLEDevice): The device to connect to.
            timeout (int): Connection timeout in seconds.
        """
        self.device = device
        self.timeout = timeout
        self.reconnect = reconnect

        self.handle_log(logging.INFO, f"[{self.instance_name}] Connecting to device: {device.name} ({device.address})")

        if self.device is not None:
            self.client = BleakClient(
                self.device, 
                disconnected_callback=self._on_DeviceDisconnected, 
                timeout=self.timeout
            )
            try:
                await self.client.connect(timeout=timeout)
                self.handle_log(logging.INFO, f"[{self.instance_name}] Connected to {self.device.name}")

                # Initialize the device
                await self.client.start_notify(self.TX_CHARACTERISTIC_UUID, self.handle_rx)
                # Prepare acquiring MTU if using BlueZ backend
                if self.client._backend.__class__.__name__ == "BleakClientBlueZDBus":
                    await self.client._backend._acquire_mtu()
                # Obtain MTU size
                self.mtu = self.client.mtu_size
                if self.mtu > 3 and self.mtu <= self.BLEMTUMAX:
                    self.BLEpayloadSize = self.mtu - 3  # Subtract ATT header size
                else:
                    self.BLEpayloadSize =  self.BLEMTUNORMAL - 3                
                self.connectingSuccess.emit(True) 
            except BleakError as e:
                if "not found" in str(e).lower():
                    self.handle_log(logging.ERROR, f"[{self.instance_name}] Connection error: {e}")
                    self.handle_log(logging.ERROR, f"[{self.instance_name}]Device is likely not paired. Please pair the device first.")
                else:
                    self.handle_log(logging.ERROR, f"[{self.instance_name}] Connection error: {e}")
                self.connectingSuccess.emit(False) 
            except Exception as e:
                self.handle_log(logging.ERROR, f"[{self.instance_name}] Unexpected error: {e}")
                self.connectingSuccess.emit(False) 
        else:
            self.handle_log(logging.WARNING, f"[{self.instance_name}] No device selected. Please select a device from the scan results.")


    async def _on_DeviceDisconnected(self, client):
        """
        Callback when the BLE device is unexpectedly disconnected.
        Starts a background task to handle reconnection.
        """
        self.handle_log(logging.WARNING, f"[{self.instance_name}] Device disconnected: {self.device.name} ({self.device.address})")

        if not self.reconnect:  # Check if reconnection is allowed
            self.handle_log(logging.INFO, f"[{self.instance_name}] Reconnection disabled. No attempt will be made.")
            self.client = None
        else:
            # Start the reconnection in a background task
            self.schedule_async(self._handle_reconnection())

    async def _handle_reconnection(self):
        """
        Handles reconnection attempts in a non-blocking manner.
        """
        retry_attempts = 0
        max_retries = 5
        backoff = 1  # Initial backoff in seconds

        while retry_attempts < max_retries and self.reconnect and not self.client.is_connected:
            try:
                self.handle_log(logging.INFO, f"[{self.instance_name}] Reconnection attempt {retry_attempts + 1} to {self.device.name}...")
                await self.client.connect(timeout=10)
                self.handle_log(logging.INFO, f"[{self.instance_name}] Reconnected to {self.device.name} ({self.device.address})")

                # Reinitialize the device (if necessary)
                await self.client.start_notify(self.TX_CHARACTERISTIC_UUID, self.handle_rx)

                retry_attempts = 0  # Reset retry attempts on success
                return  # Exit the loop on successful reconnection
            except Exception as e:
                retry_attempts += 1
                self.handle_log(logging.WARNING, f"[{self.instance_name}] Reconnection attempt {retry_attempts} failed: {e}")
                await asyncio.sleep(backoff)
                backoff *= 2  # Exponential backoff

        # Exit conditions
        if retry_attempts >= max_retries:
            self.handle_log(logging.ERROR, f"[{self.instance_name}] Failed to reconnect to {self.device.name} after {max_retries} attempts.")
        elif not self.reconnect:
            self.handle_log(logging.INFO, f"[{self.instance_name}] Reconnection attempts stopped by the user.")
        elif self.client.is_connected:
            self.handle_log(logging.INFO, f"[{self.instance_name}] Already connected to {self.device.name}. Exiting reconnection loop.")

    # BLE Device Disconnect
    # ---------------------

    @pyqtSlot()
    def on_disconnectDeviceRequest(self):
        self.schedule_async(self._disconnectDeviceRequest())

    async def _disconnectDeviceRequest(self):
        """
        Handles disconnection requests from the user.
        Ensures clean disconnection and updates the application state.
        """
        self.reconnect = False  # Stop reconnection attempts

        if not self.client or not self.client.is_connected:
            self.handle_log(logging.WARNING, f"[{self.instance_name}] No active connection to disconnect.")
            self.disconnectingSuccess.emit(False)
            return

        if getattr(self, "disconnecting", False):
            self.handle_log(logging.WARNING, f"[{self.instance_name}] Disconnection already in progress.")
            return

        self.disconnecting = True  # Set disconnection flag
        try:
            await self.client.disconnect()
            self.handle_log(logging.INFO, f"[{self.instance_name}] Disconnected from device: {self.device.name} ({self.device.address})")
            # Reset client 
            self.client = None
            self.device = None
            # Emit success signal
            self.disconnectingSuccess.emit(True)
        except Exception as e:
            self.handle_log(logging.ERROR, f"[{self.instance_name}] Error during disconnection: {e}")
            self.disconnectingSuccess.emit(False)
        finally:
            self.disconnecting = False  # Reset disconnection flag

    # BLE Device Pair
    # ---------------

    @pyqtSlot(str,str)
    def on_pairDeviceRequest(self, mac: str, pin: str):
        """Pair with the currently selected device."""

        if self.bluetoothctlWrapper is None:
            # Initialize BluetoothctlWrapper (assumes BluetoothctlWrapper is defined elsewhere)
            self.bluetoothctlWrapper = BluetoothctlWrapper("bluetoothctl")
            self.bluetoothctlWrapper.log_signal.connect(self.handle_log)
            self.bluetoothctlWrapper.start()
            time_elapsed = self.wait_for_signal(self.bluetoothctlWrapper.startup_completed_signal) * 1000
            self.handle_log(logging.INFO, f"[{self.instance_name}] bluetoothctl wrapper started in {time_elapsed:.2f} ms.")

        if mac is not None and self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.device_pair_succeeded_signal.connect(self._on_pairing_successful)
            self.bluetoothctlWrapper.device_pair_failed_signal.connect(self._on_pairing_failed)
            self.bluetoothctlWrapper.pair(mac=mac, pin=pin, timeout=5000, scantime=1000)
        else:
            self.handle_log(logging.ERROR, f"[{self.instance_name}] No device selected or BluetoothctlWrapper not available.")

    def _on_pairing_successful(self, mac: str):
        self.pairingSuccess.emit(True)
        try:
            self.bluetoothctlWrapper.device_pair_succeeded_signal.disconnect(self._on_pairing_successful)
            self.bluetoothctlWrapper.device_pair_failed_signal.disconnect(self._on_pairing_failed)
        except:
            pass
        self.handle_log(logging.INFO, f"[{self.instance_name}] Paired with {self.device.name if self.device else mac}")

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.handle_log(logging.INFO, f"[{self.instance_name}] Bluetoothctl stopped.")

    def _on_pairing_failed(self, mac: str):
        self.pairingSuccess.emit(False)
        try:
            self.bluetoothctlWrapper.device_pair_succeeded_signal.disconnect(self._on_pairing_successful)
            self.bluetoothctlWrapper.device_pair_failed_signal.disconnect(self._on_pairing_failed)
        except:
            pass
        self.handle_log(logging.ERROR, f"[{self.instance_name}] Pairing with {self.device.name if self.device else mac} unsuccessful")

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.handle_log(logging.INFO, f"[{self.instance_name}] Bluetoothctl stopped.")

    # BLE Device Remove
    # -----------------

    @pyqtSlot(str)
    def on_removeDeviceRequest(self, mac: str):
        """Remove the currently selected device from known devices."""

        if self.bluetoothctlWrapper is None:
            # Initialize BluetoothctlWrapper (assumes BluetoothctlWrapper is defined elsewhere)
            self.bluetoothctlWrapper = BluetoothctlWrapper("bluetoothctl")
            self.bluetoothctlWrapper.log_signal.connect(self.handle_log)
            self.bluetoothctlWrapper.start()
            time_elapsed = self.wait_for_signal(self.bluetoothctlWrapper.startup_completed_signal) * 1000
            self.handle_log(logging.INFO, f"[{self.instance_name}] bluetoothctl wrapper started in {time_elapsed:.2f} ms.")

        if mac is not None:
            if self.device:
                # disconnect from device before we remove it from the system
                if mac == self.device.address:
                    self.on_disconnectDeviceRequest()
            # remove device from the system
            if self.bluetoothctlWrapper:
                self.bluetoothctlWrapper.device_remove_succeeded_signal.connect(self._on_removing_successful)
                self.bluetoothctlWrapper.device_remove_failed_signal.connect(self._on_removing_failed)
                self.bluetoothctlWrapper.remove(mac=mac, timeout=5000)
                self.handle_log(logging.WARNING, f"[{self.instance_name}] BluetoothctlWrapper initiated device {mac} removal.")
            else:
                self.handle_log(logging.WARNING, f"[{self.instance_name}] BluetoothctlWrapper not available.")
        else:
            self.handle_log(logging.WARNING, f"[{self.instance_name}] No device selected or BluetoothctlWrapper not available.")

    def _on_removing_successful(self, mac: str):
        self.removalSuccess.emit(True)
        try:
            self.bluetoothctlWrapper.device_remove_succeeded_signal.disconnect(self._on_removing_successful)
            self.bluetoothctlWrapper.device_remove_failed_signal.disconnect(self._on_removing_failed)
        except:
            pass
        self.handle_log(logging.INFO, f"[{self.instance_name}] Device {self.device.name if self.device else mac} removed")
        self.device = None

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.handle_log(logging.INFO, f"[{self.instance_name}] Bluetoothctl stopped.")

    def _on_removing_failed(self, mac: str):
        self.removalSuccess.emit(False)
        try:
            self.bluetoothctlWrapper.device_remove_succeeded_signal.disconnect(self._on_removing_successful)
            self.bluetoothctlWrapper.device_remove_failed_signal.disconnect(self._on_removing_failed)
        except:
            pass
        self.handle_log(logging.ERROR, f"[{self.instance_name}] Device {self.device.name if self.device else mac} removal unsuccessful")

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.handle_log(logging.INFO, f"[{self.instance_name}] Bluetoothctl stopped.")

    # BLE Trust Device
    # ----------------

    @pyqtSlot(str)
    def on_trustDeviceRequest(self, mac: str):
        """Trust the currently selected device."""
        if self.bluetoothctlWrapper is None:
            # Initialize BluetoothctlWrapper (assumes BluetoothctlWrapper is defined elsewhere)
            self.bluetoothctlWrapper = BluetoothctlWrapper("bluetoothctl")
            self.bluetoothctlWrapper.log_signal.connect(self.handle_log)
            self.bluetoothctlWrapper.start()
            time_elapsed = self.wait_for_signal(self.bluetoothctlWrapper.startup_completed_signal) * 1000
            self.handle_log(logging.INFO, f"[{self.instance_name}] bluetoothctl wrapper started in {time_elapsed:.2f} ms.")

        if mac is not None and self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.device_trust_succeeded_signal.connect(self._on_trust_successful)
            self.bluetoothctlWrapper.device_trust_failed_signal.connect(self._on_trust_failed)
            self.bluetoothctlWrapper.trust(mac=mac, timeout=2000)
        else:
            self.handle_log(logging.ERROR, f"[{self.instance_name}] No device selected or BluetoothctlWrapper not available.")

    def _on_trust_successful(self, mac: str):
        self.trustSuccess.emit(True)
        try:
            self.bluetoothctlWrapper.device_trust_succeeded_signal.disconnect(self._on_trust_successful)
            self.bluetoothctlWrapper.device_trust_failed_signal.disconnect(self._on_trust_failed)
        except:
            pass
        self.handle_log(logging.INFO, f"[{self.instance_name}] Trusted {self.device.name if self.device else mac}")

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.handle_log(logging.INFO, f"[{self.instance_name}] Bluetoothctl stopped.")

    def _on_trust_failed(self, mac: str):
        self.trustSuccess.emit(False)
        try:
            self.bluetoothctlWrapper.device_trust_succeeded_signal.disconnect(self._on_trust_successful)
            self.bluetoothctlWrapper.device_trust_failed_signal.disconnect(self._on_trust_failed)
        except:
            pass
        self.handle_log(logging.ERROR, f"[{self.instance_name}] Pairing with {self.device.name if self.device else mac} unsuccessful")

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.handle_log(logging.INFO, f"[{self.instance_name}] Bluetoothctl stopped.")

    # BLE Distrust Device
    # -------------------

    @pyqtSlot(str)
    def on_distrustDeviceRequest(self, mac: str):
        """Remove the currently selected device from known devices."""
        if self.bluetoothctlWrapper is None:
            # Initialize BluetoothctlWrapper (assumes BluetoothctlWrapper is defined elsewhere)
            self.bluetoothctlWrapper = BluetoothctlWrapper("bluetoothctl")
            self.bluetoothctlWrapper.log_signal.connect(self.handle_log)
            self.bluetoothctlWrapper.start()
            time_elapsed = self.wait_for_signal(self.bluetoothctlWrapper.startup_completed_signal) * 1000
            self.handle_log(logging.INFO, f"[{self.instance_name}] bluetoothctl wrapper started in {time_elapsed:.2f} ms.")
            
        if mac is not None:
            if self.bluetoothctlWrapper:
                self.bluetoothctlWrapper.device_distrust_succeeded_signal.connect(self._on_distrust_successful)
                self.bluetoothctlWrapper.device_distrust_failed_signal.connect(self._on_distrust_failed)
                self.bluetoothctlWrapper.distrust(mac=mac, timeout=2000)
                self.handle_log(logging.WARNING, f"[{self.instance_name}] BluetoothctlWrapper initiated device {mac} distrust.")
            else:
                self.handle_log(logging.WARNING, f"[{self.instance_name}] BluetoothctlWrapper not available.")
        else:
            self.handle_log(logging.WARNING, f"[{self.instance_name}] No device selected or BluetoothctlWrapper not available.")

    def _on_distrust_successful(self, mac: str):
        self.distrustSuccess.emit(True)
        try:
            self.bluetoothctlWrapper.device_distrust_succeeded_signal.disconnect(self._on_distrust_successful)
            self.bluetoothctlWrapper.device_distrust_failed_signal.disconnect(self._on_distrust_failed)
        except:
            pass
        self.handle_log(logging.INFO, f"[{self.instance_name}] Device {self.device.name if self.device else mac} distrusted")

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.handle_log(logging.INFO, f"[{self.instance_name}] Bluetoothctl stopped.")

    def _on_distrust_failed(self, mac: str):
        self.distrustSuccess.emit(False)
        try:
            self.bluetoothctlWrapper.device_distrust_succeeded_signal.disconnect(self._on_distrust_successful)
            self.bluetoothctlWrapper.device_distrust_failed_signal.disconnect(self._on_distrust_failed)
        except:
            pass
        self.handle_log(logging.ERROR, f"[{self.instance_name}] Device {self.device.name if self.device else mac} distrusted unsuccessful")

        # Cleanup bluetoothctl
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.handle_log(logging.INFO, f"[{self.instance_name}] Bluetoothctl stopped.")

    # Response Functions for Sending & Receiving (Transceiver)
    ########################################################################################

    # Send Text
    # ---------

    @pyqtSlot(bytes)
    def on_sendTextRequest(self, text: bytes):
        self.schedule_async(self._sendTextRequest(text=text))

    async def _sendTextRequest(self, text: bytes):
        """Send provided text over BLE."""
        if text and self.client and self.client.is_connected:
            for i in range(0, len(text), self.BLEpayloadSize):
                chunk = text[i:i+self.BLEpayloadSize]
                await self.client.write_gatt_char(self.RX_CHARACTERISTIC_UUID, chunk, response=False)
                self.bytes_sent += len(chunk)
            self.handle_log(logging.INFO, f"[{self.instance_name}] Sent: {text}")
        else:
            self.handle_log(logging.ERROR, f"[{self.instance_name}] Not connected or no data to send.")

    # Send Line/s
    # -----------
    @pyqtSlot(bytes)
    def on_sendLineRequest(self, line: bytes):
        self.schedule_async( self._sendLineRequest(line))

    async def _sendLineRequest(self, line: bytes):
        """Send a single line of text (with EOL) over BLE."""
        if self.eol:
            await self._sendTextRequest(line + self.eol)
        else:
            await self._sendTextRequest(line)

    @pyqtSlot(list)
    def on_sendLinesRequest(self, lines: list):
        self.schedule_async(self._sendLinesRequest(lines))

    async def on_sendLinesRequest(self, lines: list):
        """Send multiple lines of text over BLE."""
        for line in lines:
            await self._sendLineRequest(line)

    # Send File
    # ---------
    @pyqtSlot(str)
    def on_sendFileRequest(self, fname: str):
        self.schedule_async(self._sendFileRequest(fname))

    async def _sendFileRequest(self, fname: str):
        """Transmit a file to the BLE device."""
        if self.client and self.client.is_connected:
            if fname:
                try:
                    with open(fname, "rb") as f:
                        data = f.read()
                        if not data:
                            self.handle_log(logging.WARNING, f'File "{fname}" is empty.')
                            return
                        file_size = len(data)
                        self.handle_log(logging.INFO, f'Starting transmission of "{fname}" ({file_size} bytes).')

                        for i in range(0, len(data), self.BLEpayloadSize):
                            chunk = data[i:i+self.BLEpayloadSize]
                            try:
                                await self.client.write_gatt_char(
                                    self.RX_CHARACTERISTIC_UUID, 
                                    chunk, 
                                    response=False
                                )
                                self.bytes_sent += len(chunk)
                            except Exception as e:
                                self.handle_log(logging.ERROR, f'Error transmitting chunk at offset {i}: {e}.')
                                break

                        self.handle_log(logging.INFO, f'Finished transmission of "{fname}".')

                except FileNotFoundError:
                    self.handle_log(logging.ERROR, f'File "{fname}" not found.')
                except Exception as e:
                    self.handle_log(logging.ERROR, f'Unexpected error transmitting "{fname}": {e}')
            else:
                self.handle_log(logging.WARNING, f"[{self.instance_name}] No file name provided.")
        else:
            self.handle_log(logging.ERROR, f"[{self.instance_name}] BLE client not available or not connected.")

    # Receive Text
    # ------------    
    def handle_rx(self, sender, data: bytes):
        """Handle incoming data from BLE device."""
        if not data:
            return

        self.bytes_received += len(data)

        if self.eol:
            # EOL-based parsing
            if self.partial_line:
                data = self.partial_line + data
                self.partial_line = b""

            lines = data.split(self.eol)
            if not data.endswith(self.eol):
                self.partial_line = lines.pop()

            if lines:
                self.receivedLines.emit(lines)
        else:
            self.receivedData.emit(data)


#####################################################################################
# Testing
#####################################################################################

if __name__ == "__main__":
    # not implemented
    pass
