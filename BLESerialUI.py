#############################################################################################
# BLE_Serial.py
#
# Description: A simple BLE terminal application using Qt and Bleak library to communicate 
# with a BLE device through Nordic UART Service.
#
# Requisites:
# pip install asyncio bleak gasync PyQt5
#
# This program will give you option to scan for BLE device, connect to a device, and pair
# with the device. It will allow you to send text to the BLE device and receive text.
#############################################################################################

import sys
import re
import logging
import time

# Bluetooth library
from bleak import BleakClient, BleakScanner, BleakError
from bleak.backends.device import BLEDevice

# IO event loop
import asyncio
from qasync import QEventLoop, asyncSlot   # Library to integrate asyncio with Qt

# Qt library
try:
    from PyQt6.QtCore import (
        QObject, pyqtSignal, pyqtSlot, 
        QTimer, QThread,
        QEventLoop, QTimer, Qt
    )
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QPushButton, QLabel,
        QTextEdit, QVBoxLayout, QWidget, QComboBox, QHBoxLayout, QSizePolicy
    )
    from PyQt6.QtGui import QShortcut, QKeySequence, QTextCursor,
    PYQT6 = True
except:
    from PyQt5.QtCore import (
        QObject, pyqtSignal, pyqtSlot, QTimer, QThread,
        QEventLoop, QTimer, Qt
    )
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QPushButton, QLabel,
        QTextEdit, QVBoxLayout, QWidget, QComboBox, QHBoxLayout, QSizePolicy, 
        QFileDialog, QStandardPaths
    )
    from PyQt5.QtGui import QShortcut, QKeySequence, QTextCursor, QTextCursor,
    PYQT6 = False

# bluetoothctl program wrapper
from helpers.Qbluetoothctl_helper import BluetoothctlWrapper

# Bluetooth Helper
# Once this program works I will put the QBLESerialUI and the QBLESerial class into a helper file:
# from helpers.QBLE_helper import QBLESerialUI, QBLESerial, 

from helpers.Codec_helper import BinaryStreamProcessor, ArduinoTextStreamProcessor
# 
# BinaryStreamProcessor(eop=b'\x00', logger = None)
#   process(new_data: bytes) -> List[Dict]
#
# ArduinoTextStreamProcessor(eol=b'\n', encoding='utf-8', logger=None)
#   process(new_data: bytes, labels: bool = True) -> List[Dict]:
#
# results.append({
#     "datatype": data_type,
#     "name": self.name.get(data_type, f"Unknown_{data_type}"),
#     "data": numbers,
#     "timestamp": time.time(),  # Add a timestamp
# })
#
# numbers can be list of floats for ArduinoTextStreamProcessor
# numbers can be byte, int8, unit8, int16, uint16, int32, uint32, float, double, list of strings, numpy arrays, for BinaryStreamProcessor


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
        setupTransceiverRequest             request that bluetoothctl interface and throughput timer is created
        stopTransceiverRequest (not used)   request that bluetoothctl and throughput timer are stopped
        statusRequest                       request that QBLESerial reports current status
        finishWorkerRequest                 request that QBLESerial worker is finished

    Slots (functions available to respond to external signals or events from buttons, input fields, etc.)
        on_upArrowPressed                   recall previous line of text from BLE console line buffer
        on_downArrowPressed                 recall next line of text from BLE console line buffer
        on_carriageReturnPressed            transmit text from UI to BLE transceiver
        on_pushButton_Send                  send file over BLE
        on_pushButton_Clear                 clear the BLE text display window
        on_pushButton_Start                 start/stop BLE transceiver
        on_pushButton_Save                  save text from display window into text file
        on_pushButton_Scan                  update BLE device list
        on_pushButton_Connect               open/close BLE device
        on_pushButton_Pair                  pair or remove BLE device
        on_pushButton_Trust                 trust or distrust BLE device
        on_pushButton_Status                request BLE device status
        on_comboBoxDropDown_BLEDevices      user selected a new BLE device from the drop down list
        on_comboBoxDropDown_LineTermination user selected a different line termination from drop down menu
        on_statusReady(dict)                pickup BLE device status
        on_deviceListReady(list)            pickup new list of devices
        on_receivedData(bytes)              pickup text from BLE transceiver
        on_receivedLines(list)              pickup lines of text from BLE transceiver
        on_throughputReady(float, float)    pickup throughput data from BLE transceiver
        on_pairingSuccess(bool)             pickup wether device pairing was successful
        on_removalSuccess(bool)             pickup wether device removal was successful
        on_logSignal(int, str)              pickup log messages
    """

    # Constants
    ########################################################################################
    MAX_TEXTBROWSER_LENGTH = 1024 * 1024      # display window character length is trimmed to this length
                                              # lesser value results in better performance
    MAX_LINE_LENGTH        = 1024             # number of characters after which an end of line characters is expected
    NUM_LINES_COLLATE      = 10               # [lines] estimated number of lines to collate before emitting signal
                                              #   this results in collating about NUM_LINES_COLLATE * 48 bytes in a list of lines
                                              #   plotting and processing large amounts of data is more efficient for display and plotting
    TARGET_DEVICE_NAME     = "MediBrick_BLE"  # The name of the BLE device to search for
    BLEPIN                 = 123456           # Known pairing pin for Medibrick_BLE

    # Remove ANSI escape sequences
    ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

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
    stopTransceiverRequest       = pyqtSignal()                  # stop transceiver (display of incoming text, connection remains)
    setupTransceiverRequest      = pyqtSignal()                  # start transceiver
    statusRequest                = pyqtSignal(str)               # request BLE device status
    finishWorkerRequest          = pyqtSignal()                  # request worker to finish
           
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

        if logger is None:
            self.logger = logging.getLogger("QBLE_UI_")
        else:
            self.logger = logger

        if ui is None:
            self.logger.log(
                logging.ERROR,
                "[{}]: need to have access to User Interface".format(
                    int(QThread.currentThreadId())
                ),
            )
            raise ValueError("User Interface (ui) is required but was not provided.")
        else:
            self.ui = ui

        if worker is None:
            self.logger.log(
                logging.ERROR,
                "[{}]: need to have access to BLE Worker".format(
                    int(QThread.currentThreadId())
                ),
            )
            raise ValueError("BLE Worker (worker) is required but was not provided.")
        else:
            self.worker = worker
        
        # Limit the amount of text retained in the  text display window
        #   execute a text trim function every minute
        self.textTrimTimer = QTimer(self)
        self.textTrimTimer.timeout.connect(self.on_bleTextDisplay_trim)
        self.textTrimTimer.start(10000)  # Trigger every 10 seconds, this halts the display for a fraction of second, so dont do it often

        # Limit the amount of text retained in the log display window
        #   execute a text trim function every minute
        self.logTrimTimer = QTimer(self)
        self.logTrimTimer.timeout.connect(self.on_bleLogDisplay_trim)
        self.logTrimTimer.start(100000)  # Trigger every 10 seconds, this halts the display for a fraction of second, so dont do it often

        self.handle_log(
            logging.INFO, 
            "[{}]: QSerialUI initialized.".format(int(QThread.currentThreadId()))
        )

    ########################################################################################
    # Helper functions
    ########################################################################################

    def handle_log(self, level, message):
        if level == logging.INFO:
            self.logger.info(message)
            self.append_log(message)
        elif level == logging.WARNING:
            self.logger.warning(message)
            self.append_log(message)
        elif level == logging.ERROR:
            self.logger.error(message)
            self.append_log(message)
        else:
            self.logger.log(level, message)
            self.append_log(message)

    def append_log(self, text, add_newline=False):
        """Appends log text to the output area."""
        text = self.ANSI_ESCAPE.sub('', text)
        self.logger.log(
            logging.DEBUG, 
            "[{}]: text received: {}".format(int(QThread.currentThreadId()),text)
        )
        try:
            if self.ui.logScrollbar.value() >= self.ui.logScrollbar.maximum() - 20:
                self.isLogScrolling = True
            else:
                self.isLogScrolling = False
            if PYQT6:
                self.ui.logCursor.movePosition(QTextCursor.MoveOperation.End)
            else:
                self.ui.logCursor.movePosition(QTextCursor.End)
            if add_newline:
                self.ui.logCursor.insertPlainText(text + "\n")
            else:
                self.ui.logCursor.insertPlainText(text)
            if self.isLogScrolling:
                self.ui.plainTextEdit_Log.ensureCursorVisible()

        except Exception as e:
            self.logger.log(
                logging.ERROR,
                "[{}]: could not display text in {}. Error {}".format(
                    int(QThread.currentThreadId()), repr(text), str(e)
                ),
            )

    def append_text(self, text, add_newline=False):
        """Appends text to the BLE output area."""
        self.logger.log(
            logging.DEBUG, 
            "[{}]: text received: {}".format(int(QThread.currentThreadId()),text)
        )
        try:
            if self.ui.textScrollbar.value() >= self.ui.textScrollbar.maximum() - 20:
                self.isTextScrolling = True
            else:
                self.isTextScrolling = False
            if PYQT6:
                self.ui.textCursor.movePosition(QTextCursor.MoveOperation.End)
            else:
                self.ui.textCursor.movePosition(QTextCursor.End)
            if add_newline:
                self.ui.textCursor.insertPlainText(text+"\n")
            else:
                self.ui.textCursor.insertPlainText(text)
            if self.isTextScrolling:
                self.ui.plainTextEdit_Text.ensureCursorVisible()

        except Exception as e:
            self.logger.log(
                logging.ERROR,
                "[{}]: could not display text in {}. Error {}".format(
                    int(QThread.currentThreadId()), repr(text), str(e)
                ),
            )

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

    @pyqtSlot()
    def on_bleTextDisplay_trim(self):
        """
        Reduce the amount of text kept in the text display window
        Attempt to keep the scrollbar location
        """

        # Where is the scrollbar?
        scrollbarMax = self.ui.textScrollbar.maximum()
        if scrollbarMax != 0:
            proportion = self.ui.textScrollbar.value() / scrollbarMax
        else:
            proportion = 1.0
        # How much do we need to trim?
        len_current_text = self.ui.plainTextEdit_Text.document().characterCount()
        numCharstoTrim = len_current_text - self.MAX_TEXTBROWSER_LENGTH

        if numCharstoTrim > 0:
            # Select the text to remove
            self.ui.textCursor.setPosition(0)
            if PYQT6:
                self.ui.textCursor.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor,
                    numCharstoTrim,
                )
            else:
                self.ui.textCursor.movePosition(
                    QTextCursor.Right,
                    QTextCursor.KeepAnchor,
                    numCharstoTrim,
                )
            # Remove the selected text
            self.ui.textCursor.removeSelectedText()
            if PYQT6:
                self.ui.textCursor.movePosition(QTextCursor.MoveOperation.End)
            else:
                self.ui.textCursor.movePosition(QTextCursor.End)
            # update scrollbar position
            new_max = self.ui.textScrollbar.maximum()
            new_value = round(proportion * new_max)
            self.ui.textScrollbar.setValue(new_value)
            # ensure that text is scrolling when we set cursor towards the end
            if new_value >= new_max - 20:
                self.ui.plainTextEdit_Text.ensureCursorVisible()
            
            self.handle_log(logging.INFO, "Text Display Trimmed.")

    @pyqtSlot()
    def on_bleLogDisplay_trim(self):
        """
        Reduce the amount of text kept in the log display window
        Attempt to keep the scrollbar location
        """

        # Where is the scrollbar?
        scrollbarMax = self.ui.logScrollbar.maximum()
        if scrollbarMax != 0:
            proportion = self.ui.logScrollbar.value() / scrollbarMax
        else:
            proportion = 1.0
        # How much do we need to trim?
        len_current_text = self.ui.plainTextEdit_Log.document().characterCount()
        numCharstoTrim = len_current_text - self.MAX_TEXTBROWSER_LENGTH

        if numCharstoTrim > 0:
            # Select the text to remove
            self.ui.textCursor.setPosition(0)
            if PYQT6:
                self.ui.logCursor.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor,
                    numCharstoTrim,
                )
            else:
                self.ui.logCursor.movePosition(
                    QTextCursor.Right,
                    QTextCursor.KeepAnchor,
                    numCharstoTrim,
                )
            # Remove the selected text
            self.ui.logCursor.removeSelectedText()
            if PYQT6:
                self.ui.logCursor.movePosition(QTextCursor.MoveOperation.End)
            else:
                self.ui.logCursor.movePosition(QTextCursor.End)
            # update scrollbar position
            new_max = self.ui.logScrollbar.maximum()
            new_value = round(proportion * new_max)
            self.ui.logScrollbar.setValue(new_value)
            # ensure that text is scrolling when we set cursor towards the end
            if new_value >= new_max - 20:
                self.ui.plainTextEdit_Log.ensureCursorVisible()
            
            self.handle_log(logging.INFO, "Log Display Trimmed.")

    @pyqtSlot()
    def on_carriageReturnPressed(self):
        """
        Transmitting text from UI to BLE transceiver
        """
        text = self.ui.lineEdit_Text.text()                             # obtain text from send input window
        self.bleSendHistory.append(text)                                # keep history of previously sent commands
        self.bleSendHistoryIndx = -1                                    # reset history pointer

        if not self.transceiverIsRunning:

            # Remove connections and cleanly connect signals
            self._safely_cleanconnect(self.worker.receivedLines, self.on_ReceivedLines)
            self._safely_cleanconnect(self.worker.receivedData, self.on_ReceivedText)

            # Update state and UI
            self.transceiverIsRunning = True
            self.ui.pushButton_Start.setText("Stop")

        text_bytearray = text.encode(self.encoding) + self.textLineTerminator # add line termination
        self.sendTextRequest.emit(text_bytearray)                        # send text to BLE TX line
        self.ui.lineEdit_Text.clear()                                    # clear send input window  
        self.handle_log(logging.INFO,"Text sent.")

    @pyqtSlot()
    def on_pushButton_Send(self):
        """Request to send a file over BLE."""
        stdFileName = ( QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation) 
            + "/upload.txt" 
        )
        fname, _ = QFileDialog.getOpenFileName(
            self.ui, "Open", stdFileName, "Text files (*.txt)"
        )
        if fname:
            self.sendFileRequest.emit(fname)
        self.handle_log(logging.INFO, 'Text file send request completed.')            

    @pyqtSlot()
    def on_upArrowPressed(self):
        """
        Handle special keys on lineEdit: UpArrow
        """
        self.bleSendHistoryIndx += 1 # increment history pointer
        # if pointer at end of buffer restart at -1
        if self.bleSendHistoryIndx == len(self.bleSendHistory):
            self.bleSendHistoryIndx = -1
        # populate with previously sent command from history buffer
        if self.bleSendHistoryIndx == -1:
            # if index is -1, use empty string as previously sent command
            self.ui.lineEdit_Text.setText("")
        else:
            self.ui.lineEdit_Text.setText(
                self.bleSendHistory[self.bleSendHistoryIndx]
            )

        self.handle_log(logging.INFO,"Previously sent text retrieved.")

    @pyqtSlot()
    def on_downArrowPressed(self):
        """
        Handle special keys on lineEdit: DownArrow
        """
        self.bleSendHistoryIndx -= 1 # decrement history pointer
        # if pointer is at start of buffer, reset index to end of buffer
        if self.bleSendHistoryIndx == -2:
            self.bleSendHistoryIndx = len(self.bleSendHistory) - 1

        # populate with previously sent command from history buffer
        if self.bleSendHistoryIndx == -1:
            # if index is -1, use empty string as previously sent command
            self.ui.lineEdit_Text.setText("")
        else:
            self.ui.lineEdit_Text.setText(
                self.bleSendHistory[self.bleSendHistoryIndx]
            )

        self.handle_log(logging.INFO, "Previously sent text retrieved.")

    def on_ReceivedLines(self, lines):
        """Received lines"""
        for line in lines:
            self.append_text(line, add_newline=True)

    def on_ReceivedText(self, text):
        """Received text"""
        self.append_text(text, add_newline=False)

    @pyqtSlot()
    def on_pushButton_Clear(self):
        """
        Clearing text display window
        """
        self.ui.plainTextEdit_Text.clear()
        self.ui.plainTextEdit_Log.clear()
        self.handle_log(logging.INFO, "Text and Log display cleared.")

    @pyqtSlot()
    def on_pushButton_Start(self):
        """
        Start BLE receiver
        This does not start or stop Transceiver, it just connects, disconnects signals
        """

        if self.ui.pushButton_Start.text() == "Start":
            # Start text display
            self.ui.pushButton_Start.setText("Stop")
            self._safely_connect(self.worker.receivedLines, self.on_ReceivedLines)
            self._safely_connect(self.worker.receivedData, self.on_ReceivedText)
            self.transceiverIsRunning = True
            self.handle_log(
                logging.DEBUG,
                "[{}]: text display is on.".format(int(QThread.currentThreadId())),
            )

        else:
            # End text display
            self.ui.pushButton_Start.setText("Start")
            self._safely_disconnect(self.worker.receivedLines, self.on_ReceivedLines)
            self._safely_disconnect(self.worker.receivedData, self.on_ReceivedText)
            self.transceiverIsRunning = False
            self.handle_log(
                logging.DEBUG, 
                "[{}]: text display is off.".format(int(QThread.currentThreadId()))
            )

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
        self.handle_log(logging.INFO, "BLE device list update requested.")

    @pyqtSlot()
    def on_pushButton_Connect(self):
        """
        Handle connect/disconnect requests.
        """
        if self.ui.pushButton_Connect.text() == "Connect":

            if self.device:
                self.connectDeviceRequest.emit(self.device, 10, False)
                self.handle_log(logging.INFO, "Attempting to connect to device.")
            else:
                self.handle_log(logging.WARNING, "No device selected for connection.")

        elif self.ui.pushButton_Connect.text() == "Disconnect":

            if self.device:
                self.disconnectDeviceRequest.emit()
                self.handle_log(logging.INFO, "Attempting to disconnect from device.")
            else:
                self.handle_log(logging.WARNING, "No device selected for disconnection.")

        else:
            self.handle_log(logging.ERROR, "User interface Connect button is labeled incorrectly.")

    @pyqtSlot()
    def on_pushButton_Pair(self):
        """Trigger pairing with a device when the pair button is clicked."""
        
        if self.ui.pushButton_Pair.text() == "Pair":
        
            if self.device is not None:
                self.pairDeviceRequest.emit(self.device.address, self.BLEPIN)
                self.handle_log(logging.INFO, f"Paired with {self.TARGET_DEVICE_NAME}")
                self.ui.pushButton_Pair.setText("Remove")
                self._safely_disconnect(self.ui.pushButton_Pair.clicked, self.worker.on_pairDeviceRequest)
                self._safely_connect(self.ui.pushButton_Pair.clicked, self.worker.on_removeDeviceRequest)
            else:
                self.handle_log(logging.WARNING, "No device set to pair")

        elif self.ui.pushButton_Pair.text() == "Remove":

            if self.device is not None:
                self.removeDeviceRequest.emit(self.device.address)
                self.handle_log(logging.INFO, f"{self.TARGET_DEVICE_NAME} removed")
                self.ui.pushButton_Pair.setText("Pair")
                self._safely_disconnect(self.ui.pushButton_Pair.clicked, self.worker.on_removeDeviceRequest)
                self._safely_connect(self.ui.pushButton_Pair.clicked, self.worker.on_pairDeviceRequest)
            else:
                self.handle_log(logging.WARNING, "No device set to pair")

        else:
            self.handle_log(logging.ERROR, "User interface Pair button is labeled incorrectly.")

    @pyqtSlot()
    def on_pushButton_Trust(self):
        """Trigger trusting with a device when the trust button is clicked."""
        
        if self.ui.pushButton_Trust.text() == "Trust":
        
            if self.device is not None:
                self.trustDeviceRequest.emit(self.device.address)
                self.handle_log(logging.INFO, f"Trusted {self.TARGET_DEVICE_NAME}")
                self.ui.pushButton_Trust.setText("Distrust")
                self._safely_disconnect(self.ui.pushButton_Trust.clicked, self.worker.on_trustDeviceRequest)
                self._safely_connect(self.ui.pushButton_Trust.clicked, self.worker.on_distrustDeviceRequest)
            else:
                self.handle_log(logging.WARNING, "No device set to trust")

        elif self.ui.pushButton_Trust.text() == "Distrust":

            if self.device is not None:
                self.distrustDeviceRequest.emit(self.device.address)
                self.handle_log(logging.INFO, f"{self.TARGET_DEVICE_NAME} distrusted")
                self.ui.pushButton_Trust.setText("Trust")    
                self._safely_disconnect(self.ui.pushButton_Trust.clicked, self.worker.on_distrustDeviceRequest)
                self._safely_connect(self.ui.pushButton_Trust.clicked, self.worker.on_trustDeviceRequest)
            else:
                self.handle_log(logging.WARNING, "No device set to trust")

        else:
            self.handle_log(logging.ERROR, "User interface Trust button is labeled incorrectly.")

    @pyqtSlot()
    def on_pushButton_Status(self):
        if self.device is not None:
            self.statusRequest.emit(self.device.address)

    @pyqtSlot()
    def on_comboBoxDropDown_BLEDevices(self): 
        "user selected a different BLE device from the drop down list"

        # disconnect current device
        self.disconnectDeviceRequest.emit()

        # prepare UI for new selection
        index=self.ui.comboBoxDropDown_Device.currentIndex()
        if index >= 0:
            self.device = self.ui.comboBoxDropDown_Device.itemData(index) # BLE device from BLEAK scanner
            self.handle_log(logging.INFO, f"Selected device: {self.device.name}, Address: {self.device.address}")
            self.ui.pushButton_Connect.setEnabled(True) # will want to connect
            self.ui.pushButton_Pair.setEnabled(True) # uses bluetoothctl
            self.ui.pushButton_Trust.setEnabled(True) # uses bluetoothctl
            self.ui.pushButton_Status.setEnabled(True) # uses bluetoothctl
            self.ui.pushButton_Send.setEnabled(False) # its not yet connected
            self.ui.pushButton_Pair.setText("Pair")
            self.ui.pushButton_Connect.setText("Connect")
            self.ui.pushButton_Trust.setText("Trust")
        else:
            self.handle_log(logging.WARNING, "No devices found")
            self.ui.pushButton_Connect.setEnabled(False)
            self.ui.pushButton_Pair.setEnabled(False)
            self.ui.pushButton_Trust.setEnabled(False)
            self.ui.pushButton_Status.setEnabled(False)
            self.ui.pushButton_Send.setEnabled(False)
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
        
        self.logger.log(
            logging.INFO,
            "[{}]: line termination {}".format(
                int(QThread.currentThreadId()), repr(self.textLineTerminator)
            ),
        )

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

        self.logger.log(
            logging.INFO,
            "[{}]: data separator {}".format(
                int(QThread.currentThreadId()), repr(self.dataSeparator)
            ),
        )

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

        self.handle_log(logging.INFO, f"Device status: {status}")

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
        self.handle_log(logging.INFO, "Device list updated.")   

    @pyqtSlot(bytes)
    def on_receivedData(self, data):
        """pickup text from BLE transceiver"""
        self.append_text(data.decode(self.encoding), new_line=False)

        # Handle data decoding

        # No EOL, just emit raw data
        # 0 None
        # 1 No Labels (simple)
        # 2 Labels [Label:]
        # 3 Binary

        if self.dataSeparator == 0:
            # There is no data decoding wanted
            results = []
        elif self.dataSeparator == 1:
            results = self.arduinoStream.process(data,labels=False)
        elif self.dataSeparator == 2:
            results = self.arduinoStream.process(data,labels=True)
        elif self.dataSeparator == 3:
            results = self.binaryStream.process(data)
        else:
            self.handle_log(logging.ERROR, f"Unknown data separator: {self.dataSeparator}")
            results = []

        # results.append({
        #     "datatype": data_type,
        #     "name": self.name.get(data_type, f"Unknown_{data_type}"),
        #     "data": numbers,
        #     "timestamp": time.time(),  # Add a timestamp
        # })
        #
        # numbers can be list of floats for ArduinoTextStreamProcessor
        # numbers can be byte, int8, unit8, int16, uint16, int32, uint32, float, double, list of strings, numpy arrays, for BinaryStreamProcessor

        for result in results:
            data_type = result.get("datatype", "Unknown")
            name      = result.get("name", "Unknown Name")
            data      = result.get("data", "No Data")
            timestamp = result.get("timestamp", "No Timestamp")

            self.handle_log(
                logging.DEBUG,
                f"Result Processed - Type: {data_type}, Name: {name}, "
                f"Data: {data}, "
                f"Timestamp: {timestamp}"
            )

    @pyqtSlot(list)
    def on_receivedLines(self, lines):
        """pickup lines of text from BLE transceiver"""
        for line in lines:
            self.append_text(line, add_newline=True)

    @pyqtSlot(float,float)
    def on_throughputReady(self, rx:float, tx:float):
        """pickup throughput data from BLE transceiver"""
        self.rx = rx
        self.tx = tx
        self.ui.label_throughput.setText(f"Throughput: RX:{rx} TX:{tx} Bps")

    @pyqtSlot(bool)
    def on_connectingSuccess(self, success):
        """pickup wether device connection was successful"""
        self.device_info["connected"] = success

        if success:
            self.ui.pushButton_Send.setEnabled(True)
            self.ui.pushButton_Connect.setEnabled(True)
            self.ui.pushButton_Connect.setText("Disconnect")
            
        else:
            self.ui.pushButton_Send.setEnabled(False)
            self.ui.pushButton_Connect.setEnabled(True)
            self.ui.pushButton_Connect.setText("Connect")

        self.handle_log(logging.INFO, f"Device {self.device.name} connection: {'successful' if success else 'failed'}")


    @pyqtSlot()
    def on_disconnectingSuccess(self, success):
        """pickup wether device disconnection was successful"""
        self.device_info["connected"] = not(success)

        if success: # disconnecting
            self.ui.pushButton_Send.setEnabled(False)
            self.ui.pushButton_Connect.setEnabled(True)
            self.ui.pushButton_Connect.setText("Connect")
        else: # disconnecting failed
            self.ui.pushButton_Connect.setEnabled(True)
            self.ui.pushButton_Connect.setText("Disconnect")

        self.handle_log(logging.INFO, f"Device {self.device.name} disconnection: {'successful' if success else 'failed'}")

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

        self.handle_log(logging.INFO, f"Device {self.device.name} pairing: {'successful' if success else 'failed'}")

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

        self.handle_log(logging.INFO, f"Device {self.device.name} removal: {'successful' if success else 'failed'}")

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

        self.handle_log(logging.INFO, f"Device {self.device.name} trusting: {'successful' if success else 'failed'}")

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

        self.handle_log(logging.INFO, f"Device {self.device.name} distrusting: {'successful' if success else 'failed'}")

    @pyqtSlot(int,str)
    def on_logSignal(self, int, str):
        """pickup log messages"""
        self.handle_log(int, str)

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
        on_stopTransceiverRequest()            stop bluetoothctl and QTimer
        on_changeLineTerminationRequest(bytes) change line termination sequence
        on_statusRequest(str)                  request BLE status of a device by MAC
        on_finishWorkerRequest()               finish the worker

    Additional helper method:
        on_selectDeviceRequest(str)            select a device from scanned devices by MAC
    """

    # Constants
    ########################################################################################
    # BLE Nordic Serial UART Service
    SERVICE_UUID           = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"  # Nordic UART Service 
    RX_CHARACTERISTIC_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # TX to BLE device
    TX_CHARACTERISTIC_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # RX from BLE device
    # BLE
    BLETIMEOUT = 30  # Timeout for BLE operations
    BLEMTUMAX    = 517
    BLEMTUNORMAL = 247

    # Signals
    ########################################################################################
    receivedData       = pyqtSignal(bytes)         # text received 
    receivedLines      = pyqtSignal(list)          # lines of text received
    deviceListReady    = pyqtSignal(list)          # updated list of BLE devices  
    throughputReady    = pyqtSignal(float, float)  # RX, TX bytes per second
    statusReady        = pyqtSignal(dict)          # BLE device status dictionary
    connectingSuccess  = pyqtSignal(bool)          # Connecting result
    disconnectingSuccess = pyqtSignal(bool)          # Disconnecting result
    pairingSuccess     = pyqtSignal(bool)          # Pairing result
    removalSuccess     = pyqtSignal(bool)          # Removal result
    trustSuccess       = pyqtSignal(bool)          # Trusting result
    distrustSuccess    = pyqtSignal(bool)          # Distrusting result
    logSignal          = pyqtSignal(int, str)      # Logging
    finished           = pyqtSignal()              # Worker finished

    def __init__(self, parent=None):

        super(QBLESerial, self).__init__(parent)

        self.device = None
        self.client = None
        self.bluetoothctlWrapper = None
        self.eol = None
        self.partial_line = b""
        self.bytes_received = 0
        self.bytes_sent = 0
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

    ########################################################################################
    # Slots
    ########################################################################################

    # Throughput
    # ----------
    @pyqtSlot()
    def on_setupTransceiverRequest(self):
        """
        Setup Timers and Program Wrapper
        """
        # Throughput tracking
        self.last_time = time.time()
        self.throughputTimer = QTimer(self)
        self.throughputTimer.setInterval(1000)
        self.throughputTimer.timeout.connect(self._calculate_throughput)
        self.throughputTimer.start(1000)
        self.handle_log(logging.INFO, "Setup throughput timer.")

        # Initialize BluetoothctlWrapper (assumes BluetoothctlWrapper is defined elsewhere)
        self.bluetoothctlWrapper = BluetoothctlWrapper("bluetoothctl")
        self.bluetoothctlWrapper.log_signal.connect(self.handle_log)
        self.bluetoothctlWrapper.start()
        self.handle_log(logging.INFO, "bluetoothctl wrapper started.")

    @pyqtSlot()
    def _calculate_throughput(self):
        """
        Calculate and update the throughput display.
        """
        current_time = time.time()
        elapsed_time = current_time - self.last_time
        self.last_time = current_time
        if elapsed_time > 0:
            bps_rx = self.bytes_received / elapsed_time
            bps_tx = self.bytes_sent / elapsed_time
            self.throughputReady.emit(bps_rx, bps_tx)
        self.bytes_received = 0
        self.bytes_sent = 0

    @pyqtSlot()
    def on_stopTransceiverRequest(self):
        """Stop bluetoothctl and QTimer."""

        if hasattr(self, 'throughputTimer'):
            self.throughputTimer.stop()
            self.handle_log(logging.INFO, "Throughput timer stopped.")

        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None
            self.handle_log(logging.INFO, "Bluetoothctl stopped.")

    @pyqtSlot()
    def on_finishWorkerRequest(self):
        """Handle Cleanup of the worker."""
        self.on_stopTransceiverRequest()

        # Disconnect BLE client if connected
        if self.client and self.client.is_connected:
            try:
                asyncio.run(self.client.disconnect())
                self.handle_log(logging.INFO, "Disconnected BLE client.")
            except Exception as e:
                self.handle_log(logging.ERROR, f"Error disconnecting BLE client: {e}")
            finally:
                self.client = None

        # Reset worker state
        self.device = None
        self.bytes_received = 0
        self.bytes_sent = 0
        self.partial_line = b""

        # Cleanup any additional resources
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.stop()
            self.bluetoothctlWrapper = None

        self.handle_log(logging.INFO, "BLE Serial Worker cleanup completed.")

        # Emit finished signal
        self.finished.emit()

    @pyqtSlot(int, str)
    def handle_log(self, level, message):
        """Emit the log signal with a level and message."""
        self.logSignal.emit(level, message)

    @pyqtSlot(bytes)
    def on_changeLineTerminationRequest(self, lineTermination: bytes):
        """
        Set the new line termination sequence.
        """
        if lineTermination is None:
            self.handle_log(
                logging.WARNING,
                "Line termination not changed, no line termination string provided."
            )
            return
        else:
            self.eol = lineTermination
            self.handle_log(
                logging.INFO,
                f"Changed line termination to {repr(self.eol)}."
            )

    # Status
    # ------
    @pyqtSlot(str)
    def on_statusRequest(self, mac: str):
        """Request device status by MAC."""
        if self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.get_device_info(mac=mac, timeout=2000)
            self.bluetoothctlWrapper.device_info_ready_signal.connect(self._on_device_info_ready)
            self.bluetoothctlWrapper.device_info_failed_signal.connect(self._on_device_info_failed)
            self.handle_log(logging.INFO, "Bluetoothctl wrapper status requested.")
        else:
            self.handle_log(logging.ERROR, "Bluetoothctl wrapper not available for status request.")

    @pyqtSlot(dict)
    def _on_device_info_ready(self, info: dict):
        self.handle_log(logging.INFO, f"Device info retrieved: {info}")
        self.device_info.update(info)
        self.statusReady.emit(self.device_info)
        # Disconnect signals
        self.bluetoothctlWrapper.device_info_ready_signal.disconnect(self._on_device_info_ready)
        self.bluetoothctlWrapper.device_info_failed_signal.disconnect(self._on_device_info_failed)

    @pyqtSlot(str)
    def _on_device_info_failed(self, mac: str):
        self.handle_log(logging.ERROR, f"Failed to retrieve device info for MAC: {mac}")
        self.bluetoothctlWrapper.device_info_ready_signal.disconnect(self._on_device_info_ready)
        self.bluetoothctlWrapper.device_info_failed_signal.disconnect(self._on_device_info_failed)

    # Scan
    # ----
    @asyncSlot()
    async def on_scanDevicesRequest(self):
        """Scan for BLE devices offering the Nordic UART Service."""
        self.handle_log(logging.INFO, "Scanning for BLE devices.")
        devices = await BleakScanner.discover(timeout=5, return_adv=True)
        if not devices:
            self.handle_log(logging.INFO, "No devices found.")
            return
        self.NSUdevices = []
        for device, adv in devices.values():
            for service_uuid in adv.service_uuids:
                if service_uuid.lower() == self.SERVICE_UUID.lower():
                    self.NSUdevices.append(device)
        
        if not self.NSUdevices:
            self.handle_log(logging.INFO, "No matching devices found.")
        else:
            self.handle_log(logging.INFO, "Scan complete. Select a device from the dropdown.")
            self.deviceListReady.emit(self.NSUdevices)

    # Connect
    # -------
    @pyqtSlot(str)
    def on_selectDeviceRequest(self, mac: str):
        """Select a device from the scanned devices by MAC."""
        for dev in self.NSUdevices:
            if dev.address == mac:
                self.device = dev
                self.handle_log(logging.INFO, f"Device selected: {dev.name} ({dev.address})")
                return
        self.handle_log(logging.WARNING, f"No device found with MAC {mac}")

    @asyncSlot(BLEDevice, int, bool)
    async def on_connectDeviceRequest(self, device: BLEDevice, timeout: int, reconnect: bool):
        """
        Slot to handle the connection request to a BLE device.

        Parameters:
            device (BLEDevice): The device to connect to.
            timeout (int): Connection timeout in seconds.
        """
        self.device = device
        self.timeout = timeout
        self.reconnect = reconnect

        self.handle_log(logging.INFO, f"Connecting to device: {device.name} ({device.address})")

        if self.device is not None:
            self.client = BleakClient(
                self.device, 
                disconnected_callback=self._on_DeviceDisconnected, 
                timeout=self.timeout
            )
            try:
                await self.client.connect(timeout=timeout)
                self.handle_log(logging.INFO, f"Connected to {self.device.name}")

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
                    self.handle_log(logging.ERROR, f"Connection error: {e}")
                    self.handle_log(logging.ERROR, "Device is likely not paired. Please pair the device first.")
                else:
                    self.handle_log(logging.ERROR, f"Connection error: {e}")
                self.connectingSuccess.emit(False) 
            except Exception as e:
                self.handle_log(logging.ERROR, f"Unexpected error: {e}")
                self.connectingSuccess.emit(False) 
        else:
            self.handle_log(logging.WARNING, "No device selected. Please select a device from the scan results.")


    async def _on_DeviceDisconnected(self, client):
        """
        Callback when the BLE device is unexpectedly disconnected.
        Starts a background task to handle reconnection.
        """
        self.handle_log(logging.WARNING, f"Device disconnected: {self.device.name} ({self.device.address})")

        if not self.reconnect:  # Check if reconnection is allowed
            self.handle_log(logging.INFO, "Reconnection disabled. No attempt will be made.")
            self.client = None
            return

        # Start the reconnection in a background task
        asyncio.create_task(self._handle_reconnection())

    @asyncSlot()
    async def _handle_reconnection(self):
        """
        Handles reconnection attempts in a non-blocking manner.
        """
        retry_attempts = 0
        max_retries = 5
        backoff = 1  # Initial backoff in seconds

        while retry_attempts < max_retries and self.reconnect and not self.client.is_connected:
            try:
                self.handle_log(logging.INFO, f"Reconnection attempt {retry_attempts + 1} to {self.device.name}...")
                await self.client.connect(timeout=10)
                self.handle_log(logging.INFO, f"Reconnected to {self.device.name} ({self.device.address})")

                # Reinitialize the device (if necessary)
                await self.client.start_notify(self.TX_CHARACTERISTIC_UUID, self.handle_rx)

                retry_attempts = 0  # Reset retry attempts on success
                return  # Exit the loop on successful reconnection
            except Exception as e:
                retry_attempts += 1
                self.handle_log(logging.WARNING, f"Reconnection attempt {retry_attempts} failed: {e}")
                await asyncio.sleep(backoff)
                backoff *= 2  # Exponential backoff

        # Exit conditions
        if retry_attempts >= max_retries:
            self.handle_log(logging.ERROR, f"Failed to reconnect to {self.device.name} after {max_retries} attempts.")
        elif not self.reconnect:
            self.handle_log(logging.INFO, "Reconnection attempts stopped by the user.")
        elif self.client.is_connected:
            self.handle_log(logging.INFO, f"Already connected to {self.device.name}. Exiting reconnection loop.")

    # Disconnect
    # ----------
    @pyqtSlot()
    async def on_disconnectDeviceRequest(self):
        """
        Handles disconnection requests from the user.
        Ensures clean disconnection and updates the application state.
        """
        self.reconnect = False  # Stop reconnection attempts

        if not self.client or not self.client.is_connected:
            self.handle_log(logging.WARNING, "No active connection to disconnect.")
            self.disconnectingSuccess.emit(False)
            return

        if getattr(self, "disconnecting", False):
            self.handle_log(logging.WARNING, "Disconnection already in progress.")
            return

        self.disconnecting = True  # Set disconnection flag
        try:
            await self.client.disconnect()
            self.handle_log(logging.INFO, f"Disconnected from device: {self.device.name} ({self.device.address})")
            # Reset client 
            self.client = None
            self.device = None
            # Emit success signal
            self.disconnectingSuccess.emit(True)
        except Exception as e:
            self.handle_log(logging.ERROR, f"Error during disconnection: {e}")
            self.disconnectingSuccess.emit(False)
        finally:
            self.disconnecting = False  # Reset disconnection flag

    # Pair
    # ----
    @pyqtSlot(str,str)
    def on_pairDeviceRequest(self, mac: str, pin: str):
        """Pair with the currently selected device."""
        if mac is not None and self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.device_pair_succeeded_signal.connect(self._on_pairing_successful)
            self.bluetoothctlWrapper.device_pair_failed_signal.connect(self._on_pairing_failed)
            self.bluetoothctlWrapper.pair(mac=mac, pin=pin, timeout=5000, scantime=1000)
        else:
            self.handle_log(logging.ERROR, "No device selected or BluetoothctlWrapper not available.")

    def _on_pairing_successful(self, mac: str):
        self.pairingSuccess.emit(True)
        try:
            self.bluetoothctlWrapper.device_pair_succeeded_signal.disconnect(self._on_pairing_successful)
            self.bluetoothctlWrapper.device_pair_failed_signal.disconnect(self._on_pairing_failed)
        except:
            pass
        self.handle_log(logging.INFO, f"Paired with {self.device.name if self.device else mac}")

    def _on_pairing_failed(self, mac: str):
        self.pairingSuccess.emit(False)
        try:
            self.bluetoothctlWrapper.device_pair_succeeded_signal.disconnect(self._on_pairing_successful)
            self.bluetoothctlWrapper.device_pair_failed_signal.disconnect(self._on_pairing_failed)
        except:
            pass
        self.handle_log(logging.ERROR, f"Pairing with {self.device.name if self.device else mac} unsuccessful")

    # Remove
    # ------
    @pyqtSlot(str)
    def on_removeDeviceRequest(self, mac: str):
        """Remove the currently selected device from known devices."""
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
                self.handle_log(logging.WARNING, f"BluetoothctlWrapper initiated device {mac} removal.")
            else:
                self.handle_log(logging.WARNING, "BluetoothctlWrapper not available.")
        else:
            self.handle_log(logging.WARNING, "No device selected or BluetoothctlWrapper not available.")

    def _on_removing_successful(self, mac: str):
        self.removalSuccess.emit(True)
        try:
            self.bluetoothctlWrapper.device_remove_succeeded_signal.disconnect(self._on_removing_successful)
            self.bluetoothctlWrapper.device_remove_failed_signal.disconnect(self._on_removing_failed)
        except:
            pass
        self.handle_log(logging.INFO, f"Device {self.device.name if self.device else mac} removed")
        self.device = None

    def _on_removing_failed(self, mac: str):
        self.removalSuccess.emit(False)
        try:
            self.bluetoothctlWrapper.device_remove_succeeded_signal.disconnect(self._on_removing_successful)
            self.bluetoothctlWrapper.device_remove_failed_signal.disconnect(self._on_removing_failed)
        except:
            pass
        self.handle_log(logging.ERROR, f"Device {self.device.name if self.device else mac} removal unsuccessful")

    # Trust
    # -----
    @pyqtSlot(str)
    def on_trustDeviceRequest(self, mac: str):
        """Trust the currently selected device."""
        if mac is not None and self.bluetoothctlWrapper:
            self.bluetoothctlWrapper.device_trust_succeeded_signal.connect(self._on_trust_successful)
            self.bluetoothctlWrapper.device_trust_failed_signal.connect(self._on_trust_failed)
            self.bluetoothctlWrapper.trust(mac=mac, timeout=2000)
        else:
            self.handle_log(logging.ERROR, "No device selected or BluetoothctlWrapper not available.")

    def _on_trust_successful(self, mac: str):
        self.trustSuccess.emit(True)
        try:
            self.bluetoothctlWrapper.device_trust_succeeded_signal.disconnect(self._on_trust_successful)
            self.bluetoothctlWrapper.device_trust_failed_signal.disconnect(self._on_trust_failed)
        except:
            pass
        self.handle_log(logging.INFO, f"Trusted {self.device.name if self.device else mac}")

    def _on_trust_failed(self, mac: str):
        self.trustSuccess.emit(False)
        try:
            self.bluetoothctlWrapper.device_trust_succeeded_signal.disconnect(self._on_trust_successful)
            self.bluetoothctlWrapper.device_trust_failed_signal.disconnect(self._on_trust_failed)
        except:
            pass
        self.handle_log(logging.ERROR, f"Pairing with {self.device.name if self.device else mac} unsuccessful")

    # Distrust
    # --------
    @pyqtSlot(str)
    def on_distrustDeviceRequest(self, mac: str):
        """Remove the currently selected device from known devices."""
        if mac is not None:
            if self.bluetoothctlWrapper:
                self.bluetoothctlWrapper.device_distrust_succeeded_signal.connect(self._on_distrust_successful)
                self.bluetoothctlWrapper.device_distrust_failed_signal.connect(self._on_distrust_failed)
                self.bluetoothctlWrapper.distrust(mac=mac, timeout=2000)
                self.handle_log(logging.WARNING, f"BluetoothctlWrapper initiated device {mac} distrust.")
            else:
                self.handle_log(logging.WARNING, "BluetoothctlWrapper not available.")
        else:
            self.handle_log(logging.WARNING, "No device selected or BluetoothctlWrapper not available.")

    def _on_distrust_successful(self, mac: str):
        self.distrustSuccess.emit(True)
        try:
            self.bluetoothctlWrapper.device_distrust_succeeded_signal.disconnect(self._on_distrust_successful)
            self.bluetoothctlWrapper.device_distrust_failed_signal.disconnect(self._on_distrust_failed)
        except:
            pass
        self.handle_log(logging.INFO, f"Device {self.device.name if self.device else mac} distrusted")

    def _on_distrust_failed(self, mac: str):
        self.distrustSuccess.emit(False)
        try:
            self.bluetoothctlWrapper.device_distrust_succeeded_signal.disconnect(self._on_distrust_successful)
            self.bluetoothctlWrapper.device_distrust_failed_signal.disconnect(self._on_distrust_failed)
        except:
            pass
        self.handle_log(logging.ERROR, f"Device {self.device.name if self.device else mac} distrusted unsuccessful")

    # Send Text
    # ---------
    @asyncSlot(bytes)
    async def on_sendTextRequest(self, text: bytes):
        """Send provided text over BLE."""
        if text and self.client and self.client.is_connected:
            for i in range(0, len(text), self.BLEpayloadSize):
                chunk = text[i:i+self.BLEpayloadSize]
                await self.client.write_gatt_char(self.RX_CHARACTERISTIC_UUID, chunk, response=False)
                self.bytes_sent += len(chunk)
            self.handle_log(logging.INFO, f"Sent: {text}")
        else:
            self.handle_log(logging.ERROR, "Not connected or no data to send.")

    # Send Line/s
    # -----------
    @asyncSlot(bytes)
    async def on_sendLineRequest(self, line: bytes):
        """Send a single line of text (with EOL) over BLE."""
        if self.eol:
            await self.on_sendTextRequest(line + self.eol)
        else:
            await self.on_sendTextRequest(line)

    @asyncSlot(list)
    async def on_sendLinesRequest(self, lines: list):
        """Send multiple lines of text over BLE."""
        for line in lines:
            await self.on_sendLineRequest(line)

    # Send File
    # ---------
    @asyncSlot(str)
    async def on_sendFileRequest(self, fname: str):
        """
        Transmit a file to the BLE device.
        """
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
                self.handle_log(logging.WARNING, "No file name provided.")
        else:
            self.handle_log(logging.ERROR, "BLE client not available or not connected.")

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

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qt BLE Terminal")
        self.resize(400, 300)

        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger("BLE_Serial")

        # ----------------------------------------------------------------------------------------------------------------------
        # User Interface
        # ----------------------------------------------------------------------------------------------------------------------

        # Text Areas
        self.ui.plainTextEdit_Log                = QTextEdit(self)    # BLE logs
        self.ui.plainTextEdit_Log.setReadOnly(True)
        self.ui.plainTextEdit_Text               = QTextEdit(self)    # BLE text display
        self.ui.plainTextEdit_Text.setReadOnly(True)        
        self.ui.lineEdit_Text                    = QTextEdit(self)    # input

        # Combo Boxes
        self.ui.comboBoxDropDown_Device          = QComboBox(self)
        self.ui.comboBoxDropDown_LineTermination = QComboBox(self)
        self.ui.comboBoxDropDown_DataSeparator   = QComboBox(self)

        # Buttons
        self.ui.pushButton_Send                  = QPushButton("Send File", self)
        self.ui.pushButton_Scan                  = QPushButton("Scan for Device", self)
        self.ui.pushButton_Connect               = QPushButton("Connect", self)
        self.ui.pushButton_Pair                  = QPushButton("Pair", self)
        self.ui.pushButton_Status                = QPushButton("Status", self)
        self.ui.pushButton_Trust                 = QPushButton("Trust", self)
        self.ui.pushButton_Clear                 = QPushButton("Clear", self)
        self.ui.pushButton_Start                 = QPushButton("Start / Stop", self)
        self.ui.pushButton_Save                  = QPushButton("Save", self)

        # Adjust Text Input_to be single-line
        self.ui.lineEdit_Text.setFixedHeight(30)  # Adjust height to make it single-line
        
        # BLE Text Output window 
        self.ui.plainTextEdit_Text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Adjust Log Text Output window
        self.ui.plainTextEdit_Log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.ui.plainTextEdit_Log.setFixedHeight(100)  # Set a smaller fixed height for BLE output

        # Throughput tracking
        self.label_throughput = QLabel("Throughput: 0 Bps", self)  # Label for throughput
        self.label_throughput.setFixedWidth(155)  # Adjust as needed

        # Layout Configuration

        # Vertical Layout
        self.ui.layout = QVBoxLayout()
        # Add text windows
        self.ui.layout.addWidget(self.ui.plainTextEdit_Text, stretch=3)  # Larger stretch Tex
        self.ui.layout.addWidget(self.ui.plainTextEdit_Log, stretch=1)  # Smaller stretch Log
        self.ui.layout.addWidget(self.ui.lineEdit_Text)
        # Horizontal Layout for the start/stop, clear, Save, Send button and throughput label
        self.ui.send_layout = QHBoxLayout()
        self.ui.send_layout.addWidget(self.ui.pushButton_Start)
        self.ui.send_layout.addWidget(self.ui.comboBoxDropDown_LineTermination)
        self.ui.send_layout.addWidget(self.ui.comboBoxDropDown_DataSeparator)
        self.ui.send_layout.addWidget(self.ui.pushButton_Clear)
        self.ui.send_layout.addWidget(self.ui.pushButton_Save)
        self.ui.send_layout.addWidget(self.ui.pushButton_Send)
        self.ui.send_layout.addWidget(self.ui.label_throughput)
        # Horizontal Layout for the other buttons
        self.ui.button_layout = QHBoxLayout()
        self.ui.button_layout.addWidget(self.ui.pushButton_Scan)
        self.ui.button_layout.addWidget(self.ui.pushButton_Connect)
        self.ui.button_layout.addWidget(self.ui.pushButton_Pair)
        self.ui.button_layout.addWidget(self.ui.pushButton_Trust)
        self.ui.button_layout.addWidget(self.ui.pushButton_Status)
        self.ui.button_layout.addWidget(self.ui.comboBoxDropDown_Device)
        # Add the Button Layouts
        self.ui.layout.addLayout(self.ui.send_layout)
        self.ui.layout.addLayout(self.ui.button_layout)

        # Container Widget
        self.ui.container = QWidget()
        self.ui.container.setLayout(self.ui.layout)
        self.setCentralWidget(self.ui.container)

        # Configure Drop Down Menus
        self.ui.comboBoxDropDown_Device
        self.ui.comboBoxDropDown_Device.addItem("none", None)                              # add none to drop down
        self.ui.comboBoxDropDown_Device.setCurrentIndex(0)                                 # set default to none
        self.device = None                                                                    # default device: none                               

        self.ui.comboBoxDropDown_LineTermination.addItem("none",                     b"")     # add none to drop down
        self.ui.comboBoxDropDown_LineTermination.addItem("newline (\\n)",            b"\n")   # add newline to drop down
        self.ui.comboBoxDropDown_LineTermination.addItem("return (\\r)",             b"\r")   # add return to drop down
        self.ui.comboBoxDropDown_LineTermination.addItem("newline return (\\n\\r)",  b"\n\r") # add newline return to drop down
        self.ui.comboBoxDropDown_LineTermination.addItem("return newline (\\r\\n)"), b"\r\n"  # add return newline to drop down
        self.ui.comboBoxDropDown_LineTermination.setCurrentIndex(0)                           # set default to none
        self.textLineTerminator = b""                                                            # default line termination: none

        self.ui.comboBoxDropDown_DataSeparator.addItem("none",               0)            # add none to drop down
        self.ui.comboBoxDropDown_DataSeparator.addItem("No Labels (simple)", 1)            # add newline to drop down
        self.ui.comboBoxDropDown_DataSeparator.addItem("Labels [Label:]",    2)            # add return to drop down
        self.ui.comboBoxDropDown_DataSeparator.addItem("Binary",             3)            # add return to drop down
        self.ui.comboBoxDropDown_DataSeparator.setCurrentIndex(0)                          # set default to none
        self.dataSeparator = 0                                                                # default data separator: none

        # Buttons
        self.ui.pushButton_Connect.setText("Connect")
        self.ui.pushButton_Pair.setText("Pair")
        self.ui.pushButton_Start.setText("Start")

        self.ui.pushButton_Connect.setEnabled(False)
        self.ui.pushButton_Pair.setEnabled(False)
        self.ui.pushButton_Start.setEnabled(False)
        self.ui.lineEdit_Text.setEnabled(False)
        self.ui.pushButton_Send.setEnabled(False)
        self.ui.pushButton_Scan.setEnabled(True)
        self.ui.pushButton_Status.setEnabled(False)
        self.ui.pushButton_Trust.setEnabled(False)
        self.ui.pushButton_Clear.setEnabled(True)
        self.ui.pushButton_Save.setEnabled(True)

        # Adjust Text Input_to be single-line
        self.ui.lineEdit_Text.setFixedHeight(30)  # Adjust height to make it single-line
        # BLE Text Output window 
        self.ui.plainTextEdit_Text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Adjust Text Output window (for log messages)
        self.ui.plainTextEdit_Log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.ui.plainTextEdit_Log.setFixedHeight(100)  # Set a smaller fixed height for BLE output

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

        # Set Cursor for text display window
        self.ui.textCursor = self.ui.plainTextEdit_Text.textCursor()
        if PYQT6:
            self.ui.textCursor.movePosition(QTextCursor.MoveOperation.End)
        else:
            self.ui.textCursor.movePosition(QTextCursor.End)
        self.ui.plainTextEdit_Text.setTextCursor(self.ui.textCursor)
        self.ui.plainTextEdit_Text.ensureCursorVisible()

        # Set Cursor for log display window
        self.ui.logCursor = self.ui.plainTextEdit_Log.textCursor()
        if PYQT6:
            self.logCursor.movePosition(QTextCursor.MoveOperation.End)
        else:
            self.ui.logCursor.movePosition(QTextCursor.End)
        self.ui.plainTextEdit_Log.setTextCursor(self.ui.logCursor)
        self.ui.plainTextEdit_Log.ensureCursorVisible()

        self.show()

        # ----------------------------------------------------------------------------------------------------------------------
        # Worker & Thread
        # ----------------------------------------------------------------------------------------------------------------------

        # Worker Thread
        self.bleWorkerThread = QThread()                             # create QThread object
        self.bleWorkerThread.start()                                 # start thread which will start worker

        # Create BLE worker
        self.bleWorker = QBLESerial()                                # create BLE worker object

        # Connect worker / thread
        self.bleWorker.finished.connect(            self.bleWorkerThread.quit)   # if worker emits finished quite worker thread
        self.bleWorker.finished.connect(            self.bleWorker.deleteLater)  # delete worker at some time
        self.bleWorkerThread.finished.connect(      self.bleWorkerThread.deleteLater)  # delete thread at some time
        
        # ----------------------------------------------------------------------------------------------------------------------
        # User Interface
        # ----------------------------------------------------------------------------------------------------------------------

        # Create user interface hook for BLE
        self.bleUI = QBLESerialUI(ui=self.ui, worker=self.bleWorker) 

        # Signals from BLE Worker to BLE-UI
        # ---------------------------------
        self.bleWorker.receivedData.connect(        self.bleUI.on_receivedData)         # connect text display to BLE receiver signal
        self.bleWorker.receivedLines.connect(       self.bleUI.on_receivedLines)        # connect text display to BLE receiver signal
        self.bleWorker.deviceListReady.connect(     self.bleUI.on_deviceListReady)      # connect new port list to its ready signal
        self.bleWorker.statusReady.connect(         self.bleUI.on_statusReady)          # connect 
        self.bleWorker.throughputReady.connect(     self.bleUI.on_throughputReady)      # connect display throughput status
        self.bleWorker.pairingSuccess.connect(      self.bleUI.on_pairingSuccess)       # connect pairing status to BLE UI
        self.bleWorker.trustSuccess.connect(        self.bleUI.on_trustSuccess)         # connect trust status to BLE UI
        self.bleWorker.distrustSuccess.connect(     self.bleUI.on_distrustSuccess)      # connect distrust status to BLE UI
        self.bleWorker.connectingSuccess.connect(   self.bleUI.on_connectingSuccess)    # connect connecting status to BLE UI
        self.bleWorker.disconnectingSuccess.connect(self.bleUI.on_disconnectingSuccess) # connect disconnecting status to BLE UI
        self.bleWorker.removalSuccess.connect(      self.bleUI.on_removalSuccess)       # connect removal status to BLE UI
        self.bleWorker.logSignal.connect(           self.bleUI.on_logSignal)            # connect log messages to BLE UI

        self.bleWorker.finished.connect(                self.bleWorkerThread.quit)
        self.bleWorker.finished.connect(                self.bleWorker.deleteLater)
        self.bleWorkerThread.finished.connect(self.bleWorkerThread.deleteLater)

        # Signals from BLE-UI to BLE Worker
        # ---------------------------------
        self.bleUI.changeLineTerminationRequest.connect(self.bleWorker.on_changeLineTerminationRequest)  # connect changing line termination
        self.bleUI.scanDevicesRequest.connect(      self.bleWorker.on_scanDevicesRequest)
        self.bleUI.connectDeviceRequest.connect(    self.bleWorker.on_connectDeviceRequest)
        self.bleUI.disconnectDeviceRequest.connect( self.bleWorker.on_disconnectDeviceRequest)
        self.bleUI.pairDeviceRequest.connect(       self.bleWorker.on_pairDeviceRequest)
        self.bleUI.trustDeviceRequest.connect(      self.bleWorker.on_trustDeviceRequest)
        self.bleUI.removeDeviceRequest.connect(     self.bleWorker.on_removeDeviceRequest)
        self.bleUI.sendFileRequest.connect(         self.bleWorker.on_sendFileRequest)
        self.bleUI.sendTextRequest.connect(         self.bleWorker.on_sendTextRequest)
        self.bleUI.sendLineRequest.connect(         self.bleWorker.on_sendLineRequest)
        self.bleUI.sendLinesRequest.connect(        self.bleWorker.on_sendLinesRequest)
        self.bleUI.setupTransceiverRequest.connect( self.bleWorker.on_setupTransceiverRequest)
        self.bleUI.stopTransceiverRequest.connect(  self.bleWorker.on_stopTransceiverRequest)
        self.bleUI.statusRequest.connect(           self.bleWorker.on_statusRequest)

        self.bleUI.finishWorkerRequest.connect(         self.bleWorker.on_finishWorkerRequest)

        # Prepare the BLE Worker and User Interface
        # --------------------------------------------
        self.bleWorker.moveToThread(self.bleWorkerThread)  # move worker to thread
        QTimer.singleShot( 0, lambda: self.bleUI.scanDevicesRequest.emit())      # request to scan for BLE ports
        QTimer.singleShot(50, lambda: self.bleUI.setupTransceiverRequest.emit())  # establishes QTimer in the QThread above

        # Signals from User Interface to BLESerial-UI
        # -------------------------------------------
        # Connect Buttons
        self.ui.pushButton_Scan.clicked.connect(         self.bleUI.on_pushButton_Scan)
        self.ui.pushButton_Connect.clicked.connect(      self.bleUI.on_pushButton_Connect)
        self.ui.pushButton_Start.clicked.connect(        self.bleUI.on_pushButton_Start)
        self.ui.pushButton_Clear.clicked.connect(        self.bleUI.on_pushButton_Clear)
        self.ui.pushButton_Save.clicked.connect(         self.bleUI.on_pushButton_Save)
        self.ui.pushButton_Send.clicked.connect(         self.bleUI.on_pushButton_Send)
        self.ui.pushButton_Pair.clicked.connect(         self.bleUI.on_pushButton_Pair)
        self.ui.pushButton_Status.clicked.connect(       self.bleUI.on_pushButton_Status)
        self.ui.pushButton_Trust.clicked.connect(        self.bleUI.on_pushButton_Trust)
        # Connect ComboBoxes
        self.ui.comboBoxDropDown_Device.currentIndexChanged.connect(             self.bleUI.on_comboBoxDropDown_BLEDevices)
        self.ui.comboBoxDropDown_LineTermination.currentIndexChanged.connect(    self.bleUI.on_comboBoxDropDown_LineTermination)
        self.ui.comboBoxDropDown_DataSeparator.currentIndexChanged.connect(      self.bleUI.on_comboBoxDropDown_DataSeparator)
        # User hit up/down arrow in BLE lineEdit
        self.ui.shortcutUpArrow   = QShortcut(QKeySequence.MoveToPreviousLine,   self.ui.lineEdit_Text, self.bleUI.on_upArrowPressed)
        self.ui.shortcutDownArrow = QShortcut(QKeySequence.MoveToNextLine,       self.ui.lineEdit_Text, self.bleUI.on_DownArrowPressed)    
        # User hit carriage return in BLE lineEdit
        self.ui.lineEdit_Text.returnPressed.connect(     self.bleUI.on_carriageReturnPressed) # Send text as soon as enter key is pressed
        

        # ----------------------------------------------------------------------------------------------------------------------
        # User Interface
        # ----------------------------------------------------------------------------------------------------------------------

        self.binaryStream  = BinaryStreamProcessor(eop=b'\x00', logger = self.logger)
        self.arduinoStream = ArduinoTextStreamProcessor(eol=b'\n', encoding='utf-8', logger=self.logger)

    def closeEvent(self, event):
        """
        Respond to window close event.
        Close the device, stop the BLE thread and the chart update timer.
        """
        if self.bleWorker:
            if self.bleUI:
                self.bleUI.finishWorkerRequest.emit()        # emit signal to finish worker

                loop = QEventLoop()                          # create event loop
                self.bleWorker.finished.connect(loop.quit)   # connect the loop to finish signal
                loop.exec()                                  # wait until worker is finished

                # Disconnect all signals from the worker
                self.bleWorker.receivedData.disconnect()
                self.bleWorker.receivedLines.disconnect()
                self.bleWorker.deviceListReady.disconnect()
                self.bleWorker.statusReady.disconnect()
                self.bleWorker.throughputReady.disconnect()
                self.bleWorker.pairingSuccess.disconnect()
                self.bleWorker.connectingSuccess.disconnect()
                self.bleWorker.disconnectingSuccess.disconnect()
                self.bleWorker.removalSuccess.disconnect()
                self.bleWorker.logSignal.disconnect()

                self.bleUI.changeLineTerminationRequest.disconnect()
                self.bleUI.scanDevicesRequest.disconnect()
                self.bleUI.connectDeviceRequest.disconnect()
                self.bleUI.disconnectDeviceRequest.disconnect()
                self.bleUI.pairDeviceRequest.disconnect()
                self.bleUI.removeDeviceRequest.disconnect()
                self.bleUI.sendFileRequest.disconnect()
                self.bleUI.sendTextRequest.disconnect()
                self.bleUI.sendLineRequest.disconnect()
                self.bleUI.sendLinesRequest.disconnect()
                self.bleUI.setupTransceiverRequest.disconnect()
                self.bleUI.stopTransceiverRequest.disconnect()
                self.bleUI.statusRequest.disconnect()

                self.ui.pushButton_Scan.clicked.disconnect()
                self.ui.pushButton_Connect.clicked.disconnect()
                self.ui.pushButton_Start.clicked.disconnect()
                self.ui.pushButton_Clear.clicked.disconnect()
                self.ui.pushButton_Save.clicked.disconnect()
                self.ui.pushButton_Send.clicked.disconnect()
                self.ui.pushButton_Pair.clicked.disconnect()
                self.ui.pushButton_Status.clicked.disconnect()
                self.ui.comboBoxDropDown_Device.currentIndexChanged.disconnect()
                self.ui.comboBoxDropDown_LineTermination.currentIndexChanged.disconnect()
                self.ui.comboBoxDropDown_DataSeparator.currentIndexChanged.disconnect()
                self.ui.lineEdit_Text.returnPressed.disconnect() # Send text as soon as enter key is pressed

                self.bleWorkerThread.quit()                  # quit the thread
                self.bleWorkerThread.wait()                  # wait until thread is closed
                self.logger.info("BLE Worker and thread cleaned up.")
            else:
                self.logger.log(
                    logging.ERROR,
                    "[{}]: bleUI not initialized.".format(
                        int(QThread.currentThreadId())
                    ),
                )
        else:
            self.logger.log(
                logging.ERROR,
                "[{}]: bleWorker not initialized.".format(
                    int(QThread.currentThreadId())
                ),
            )

        event.accept()  # accept the close event to proceed closing the application

###############################################################################################################################
#
#    Main
#
################################################################################################################################

async def run_app():
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = MainWindow()
    window.show()
    await asyncio.sleep(0)

# Main function to start the Qt application
if __name__ == "__main__":
    asyncio.run(run_app())
