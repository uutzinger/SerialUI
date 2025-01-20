##########################################################################################################################################        
# QT Serial Helper
##########################################################################################################################################        
# July 2022: initial work
# December 2023: implemented line reading
# Summer 2024: 
#   fixes and improvements
#   added pyqt6 support
# Fall 2024
#   reconnect when same device is removed and then reinserted into USB port
# Spring 2025
#   checked all routines for efficiency and errors. 
#   improved low level serial
#
# This code is maintained by Urs Utzinger
##########################################################################################################################################        

##########################################################################################################################################        
# This code has 3 sections
# QSerialUI: Controller - Interface to GUI, runs in main thread.
# QSerial:   Model - - Functions running in separate thread, communication through signals and slots.
# PSerial:   Sub Model - Low level interaction with serial ports, called from QSerial.
##########################################################################################################################################        

from serial import Serial as sp
from serial import SerialException, EIGHTBITS, PARITY_NONE, STOPBITS_ONE
from serial.tools import list_ports 

import time, logging
from math import ceil
from enum import Enum
import platform
from pathlib import Path
from collections import deque

try: 
    from PyQt6.QtCore import (
        QObject, QTimer, QThread, pyqtSignal, pyqtSlot, QStandardPaths
    )
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QTextCursor
    from PyQt6.QtWidgets import QFileDialog, QMessageBox
    hasQt6 = True
except:
    from PyQt5.QtCore import (
        QObject, QTimer, QThread, pyqtSignal, pyqtSlot, QStandardPaths
    )
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QTextCursor
    from PyQt5.QtWidgets import QFileDialog, QMessageBox
    hasQt6 = False

########################################################################################
# Debug
DEBUGSERIAL = False  # enable/disable low level serial debugging
# try:
#     import debugpy
#     DEBUGPY_ENABLED = True
# except ImportError:
#     DEBUGPY_ENABLED = False

# Constants
########################################################################################
DEFAULT_BAUDRATE       = 500000      # default baud rate for serial port
MAX_TEXTBROWSER_LENGTH = 4096        # display window is trimmed to these number of lines
                                     # lesser value results in better performance
MAX_LINE_LENGTH        = 1024        # number of characters after which an end of line characters is expected
RECEIVER_FINISHCOUNT   = 10          # [times] If we encountered a timeout 10 times we slow down serial polling
NUM_LINES_COLLATE      = 10          # [lines] estimated number of lines to collate before emitting signal
                                     #   this results in collating about NUM_LINES_COLLATE * 48 bytes in a list of lines
                                     #   plotting and processing large amounts of data is more efficient for display and plotting
MAX_RECEIVER_INTERVAL  = 100         # [ms]
MIN_RECEIVER_INTERVAL  = 5           # [ms]

class SerialReceiverState(Enum):
    """
    When data is expected on the serial input we use a QT timer to read line by line.
    When no data is expected we are in stopped state
    When data is expected but has not yet arrived we are in awaiting state
    When data has arrived and there might be more data arriving we are in receiving state
    """

    stopped         = 0
    awaitingData    = 1
    receivingData   = 2

##########################################################################################################################################        
##########################################################################################################################################        
#
# Serial Port Monitor
# 
##########################################################################################################################################        
##########################################################################################################################################        

class USBMonitorWorker(QObject):
    usb_event_detected = pyqtSignal(str)  # Signal to communicate with the main thread
    finished           = pyqtSignal() 
    logSignal          = pyqtSignal(int, str) 

    def __init__(self):
        super().__init__()
        self.running = True
        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"

    def run(self):
        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"

        os_type = platform.system()
        if os_type == "Linux" or os_type == "Darwin":
            self.monitor_usb_linux()
        elif os_type == "Windows":
            self.monitor_usb_windows()
        else:
            self.handle_log(logging.ERROR, f"Unsupported operating system: {os_type}")

    def handle_log(self, level, message):
        """Emit the log signal with a level and message."""
        self.logSignal.emit(level, message)

    def monitor_usb_linux(self):
        import pyudev
        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by(subsystem='tty')

        while self.running:
            try:
                device = monitor.poll(timeout=200)
                if device:
                    action = device.action
                    device_node = device.device_node
                    if action == 'add':
                        self.usb_event_detected.emit(f"USB device added: {device_node}")
                    elif action == 'remove':
                        self.usb_event_detected.emit(f"USB device removed: {device_node}")
            except Exception as e:
                self.handle_log(logging.ERROR, f"Error: {e}")
                time.sleep(1)
        
        self.finished.emit()

    def monitor_usb_windows(self):
        import wmi
        c = wmi.WMI()
        try:
            creation_watcher = c.Win32_PnPEntity.watch_for(notification_type="Creation", delay_secs=1)
            removal_watcher  = c.Win32_PnPEntity.watch_for(notification_type="Deletion", delay_secs=1)
        except Exception as e:
            self.handle_log(logging.ERROR, f"Error setting up USB monitor: {e}")
            return
        
        while self.running:
            try:
                if self.running:
                    event = creation_watcher(timeout_ms=500)  # Wait for an event for 500ms
                    if event and ('USB' in event.Description or 'COM' in event.Name):
                        self.usb_event_detected.emit(f"USB device added: {event.Description} ({event.Name})")

                if self.running:
                    removal_event = removal_watcher(timeout_ms=500)
                    if removal_event and ('USB' in removal_event.Description or 'COM' in removal_event.Name):
                        self.usb_event_detected.emit(f"USB device removed: {removal_event.Description} ({removal_event.Name})")

            except wmi.x_wmi_timed_out:
                pass  # No event within timeout, continue waiting

            except Exception as e:
                self.handle_log(logging.ERROR, f"Error: {e}")

        self.finished.emit()

    def stop(self):
        """Stop the worker safely."""
        self.running = False

        # Windows: Force an event to break `watch_for()`
        if platform.system() == "Windows":
            try:
                import wmi
                c = wmi.WMI()
                c.Win32_PnPEntity.watch_for(notification_type="Creation", delay_secs=0.1)  # Force an event
            except:
                pass  # Ignore errors, just forcing an update

        # Linux: Restart `pyudev` context (handled in `monitor_usb_linux`)

##########################################################################################################################################        
##########################################################################################################################################        
#
# QSerial interaction with Graphical User Interface
# This section contains routines that can not be moved to a separate thread
# because it interacts with the QT User Interface.
# The Serial Worker is in a separate thread and receives data through signals from this class
#
# Receiving from serial port is bytes or a list of bytes
# Sending to serial port is bytes or list of bytes
# We need to encode/decode received/sent text in QSerialUI
#
#    This is the Controller (Presenter)  of the Model - View - Controller (MVC) architecture.
#
##########################################################################################################################################        
##########################################################################################################################################        

class QSerialUI(QObject):
    """
    Serial Interface for QT

    Signals (to be emitted by UI)
        scanPortsRequest                 request that QSerial is scanning for ports
        scanBaudRatesRequest             request that QSerial is scanning for baudrates
        changePortRequest                request that QSerial is changing port
        changeBaudRequest                request that QSerial is changing baud rate
        changeLineTerminationRequest     request that QSerial line termination is changed
        sendTextRequest                  request that provided text is transmitted over serial TX
        sendLineRequest                  request that provided line of text is transmitted over serial TX
        sendLinesRequest                 request that provided lines of text are transmitted over serial TX
        setupReceiverRequest             request that QTimer for receiver and QTimer for throughput is created
        startReceiverRequest             request that QTimer for receiver is started
        stopReceiverRequest              request that QTimer for receiver is stopped
        startThroughputRequest           request that QTimer for throughput is started
        stopThroughputRequest            request that QTimer for throughput is stopped
        serialStatusRequest              request that QSerial reports current port, baudrate, line termination, encoding, timeout
        finishWorkerRequest              request that QSerial worker is finished
        closePortRequest                 request that QSerial closes current port

    Slots (functions available to respond to external signals)
        on_serialMonitorSend                 transmit text from UI to serial TX line
        on_serialMonitorSendUpArrowPressed   recall previous line of text from serial TX line buffer
        on_serialMonitorSendDownArrowPressed recall next line of text from serial TX line buffer
        on_pushButton_SerialClearOutput      clear the text display window
        on_pushButton_SerialStartStop        start/stop serial receiver and throughput timer
        on_pushButton_SerialSave             save text from display window into text file
        on_pushButton_SerialScan             update serial port list
        on_pushButton_SerialOpenClose        open/close serial port
        on_comboBoxDropDown_SerialPorts      user selected a new port on the drop down list
        on_comboBoxDropDown_BaudRates        user selected a different baudrate on drop down list
        on_comboBoxDropDown_LineTermination  user selected a different line termination from drop down menu
        on_serialStatusReady(str, int, bytes, float) pickup QSerial status on port, baudrate, line termination, timeout
        on_newPortListReady(list, list)      pickup new list of serial ports
        on_newBaudListReady(tuple)           pickup new list of baudrates
        on_SerialReceivedText(bytes)         pickup text from serial port
        on_SerialReceivedLines(list)         pickup lines of text from serial port
        on_throughputReceived(int, int)      pickup throughput data from QSerial
        on_usb_event_detected(str)           pickup USB device insertion or removal
    """

    # Signals
    ########################################################################################

    scanPortsRequest             = pyqtSignal()                                            # port scan
    scanBaudRatesRequest         = pyqtSignal()                                            # baudrates scan
    changePortRequest            = pyqtSignal(str, int, bool)                              # port and baudrate to change with ESP reset
    changeBaudRequest            = pyqtSignal(int)                                         # request serial baud rate to change
    changeLineTerminationRequest = pyqtSignal(bytes)                                       # request line termination to change
    sendTextRequest              = pyqtSignal(bytes)                                       # request to transmit text to TX
    sendLineRequest              = pyqtSignal(bytes)                                       # request to transmit one line of text to TX
    sendLinesRequest             = pyqtSignal(list)                                        # request to transmit lines of text to TX
    startReceiverRequest         = pyqtSignal()                                            # start serial receiver, expecting text
    stopReceiverRequest          = pyqtSignal()                                            # stop serial receiver
    setupReceiverRequest         = pyqtSignal()                                            # start serial receiver, expecting text
    startThroughputRequest       = pyqtSignal()                                            # start timer to report throughput
    stopThroughputRequest        = pyqtSignal()                                            # stop timer to report throughput
    resetESPonOpen               = pyqtSignal(bool)                                        # reset ESP32 on open    
    serialStatusRequest          = pyqtSignal()                                            # request serial port and baudrate status
    finishWorkerRequest          = pyqtSignal()                                            # request worker to finish
    closePortRequest             = pyqtSignal()                                            # close the current serial Port
    serialSendFileRequest        = pyqtSignal(str)                                         # request to open file and send over serial port
    displayingRunning            = pyqtSignal(bool)                                        # signal to indicate that serial monitor is running
           
    # Init
    ########################################################################################

    def __init__(self, parent=None, ui=None, worker=None, logger=None):

        super().__init__(parent)

        # state variables, populated by service routines
        self.defaultBaudRate       = DEFAULT_BAUDRATE
        self.BaudRates             = []                                                    # e.g. (1200, 2400, 9600, 115200)
        self.serialPortNames       = []                                                    # human readable
        self.serialPorts           = []                                                    # e.g. COM6
        self.serialPort            = ""                                                    # e.g. COM6
        self.serialBaudRate        = DEFAULT_BAUDRATE                                      # e.g. 115200
        self.serialSendHistory     = []                                                    # previously sent text (e.g. commands)
        self.serialSendHistoryIndx = -1                                                    # init history
        self.lastNumReceived       = 0                                                     # init throughput            
        self.lastNumSent           = 0                                                     # init throughput
        self.rx                    = 0                                                     # init throughput
        self.tx                    = 0                                                     # init throughput 
        self.receiverIsRunning     = False                                                 # keep track of worker state
        self.textLineTerminator    = b""                                                   # default line termination: none
        self.encoding              = "utf-8"                                               # default encoding
        self.serialTimeout         = 0                                                     # default timeout    
        self.isScrolling           = False                                                 # keep track of text display scrolling
        self.esp_reset             = False                                                 # reset ESP32 on open

        self.serialPort_backup     = ""
        self.serialBaudRate_backup = DEFAULT_BAUDRATE
        self.esp_reset_backup      = False
        self.awaitingReconnection  = False
        self.record                = False                                                 # record serial data
        self.recordingFileName     = ""
        self.recordingFile         = None
        self.textBrowserLength     = MAX_TEXTBROWSER_LENGTH + 1

        # self.textDisplayLineCount  = 1 # it will have at least the initial line

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"

        if logger is None:
            self.logger = logging.getLogger("QSerUI")
        else:
            self.logger = logger

        if ui is None:
            self.logger.log(
                logging.ERROR,
                f"[{self.thread_id}]: need to have access to User Interface"
            )
        self.ui = ui

        if worker is None:
            self.logger.log(
                logging.ERROR,
                f"[{self.thread_id}]: need to have access to serial worker signals"
            )
        self.serialWorker = worker

        # Text display window on serial text display
        self.ui.plainTextEdit_SerialTextDisplay.setReadOnly(True)   # Prevent user edits
        self.ui.plainTextEdit_SerialTextDisplay.setWordWrapMode(0)  # No wrapping for better performance

        self.textScrollbar = self.ui.plainTextEdit_SerialTextDisplay.verticalScrollBar()
        self.ui.plainTextEdit_SerialTextDisplay.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.textScrollbar.setSingleStep(1)                          # Highest resolution

        # Efficient text storage
        self.lineBuffer = deque(maxlen=MAX_TEXTBROWSER_LENGTH)       # Circular buffer


        # Disable closing serial port button
        self.ui.pushButton_SerialOpenClose.setText("Open")
        self.ui.pushButton_SerialOpenClose.setEnabled(False)
        # Disable start button in serial monitor and chart
        self.ui.pushButton_ChartStartStop.setEnabled(True)
        self.ui.pushButton_SerialStartStop.setEnabled(True)
        self.ui.pushButton_IndicatorStartStop.setEnabled(True)
        self.ui.lineEdit_SerialText.setEnabled(False)
        self.ui.pushButton_SerialSend.setEnabled(False)

        # Limit the amount of text retained in the serial text display window
        #   execute a text trim function every minute
        self.textTrimTimer = QTimer(self)
        self.textTrimTimer.timeout.connect(self.serialTextDisplay_trim)
        self.textTrimTimer.start(10000)  # Trigger every 10 seconds, this halts the display for a fraction of second, so dont do it often

        # Cursor for text display window
        self.textCursor = self.ui.plainTextEdit_SerialTextDisplay.textCursor()
        if hasQt6:
            self.textCursor.movePosition(QTextCursor.MoveOperation.End)
        else:
            self.textCursor.movePosition(QTextCursor.End)
        self.ui.plainTextEdit_SerialTextDisplay.setTextCursor(self.textCursor)
        self.ui.plainTextEdit_SerialTextDisplay.ensureCursorVisible()
        self.logger.log(
            logging.INFO, 
            f"[{self.thread_id}]: QSerialUI initialized."
        )

    # Response Functions to Timer Signals
    ########################################################################################

    def on_usb_event_detected(self, message):
        """
        This responds to an USB device insertion on removal
        """
        port_scan = [ [p.device, p.description, p.hwid] for p in list_ports.comports() ]
        ports = [sublist[0] for sublist in port_scan if sublist[1] != 'n/a']

        if "USB device removed" in message:
            # Check if the device is still there
            if self.serialPort not in ports and self.serialPort != "":
                # Device is no longer there, close the port
                if self.serialPort != "":
                    self.serialPort_backup     = self.serialPort
                    self.serialBaudRate_backup = self.serialBaudRate
                    self.esp_reset_backup      = self.esp_reset
                    self.awaitingReconnection  = True
                QTimer.singleShot(  0, lambda: self.stopThroughputRequest.emit()) # request to stop throughput
                QTimer.singleShot( 50, lambda: self.closePortRequest.emit())      # request to close serial port
                QTimer.singleShot(250, lambda: self.serialStatusRequest.emit())   # request to report serial port status
                # shade sending text
                self.ui.lineEdit_SerialText.setEnabled(False)
                self.ui.pushButton_SerialSend.setEnabled(False)                
                self.logger.log(
                    logging.INFO, 
                    f"[{self.thread_id}]: requesting Closing serial port."
                )
                self.ui.statusBar().showMessage('USB device removed, Serial Close requested.', 5000)            
            else:
                pass

        elif "USB device added" in message:
            if self.awaitingReconnection: 
                if self.serialPort in ports:
                    QTimer.singleShot(  0, lambda: self.changePortRequest.emit(self.serialPort_backup, self.serialBaudRate_backup, self.esp_reset_backup) ) # takes 11ms to open port
                    QTimer.singleShot(150, lambda: self.scanBaudRatesRequest.emit())            # update baudrates
                    QTimer.singleShot(200, lambda: self.serialStatusRequest.emit())             # request to report serial port status            
                    QTimer.singleShot(250, lambda: self.startThroughputRequest.emit())          # request to start serial receiver
                    self.awaitingReconnection = False
                    self.logger.log(
                        logging.INFO, 
                        f"[{self.thread_id}]: port {self.serialPort_backup} reopened with baud {self.serialBaudRate_backup} "
                        f"eol {repr(self.textLineTerminator)} timeout {self.serialTimeout} and esp_reset {self.esp_reset_backup}."
                    )
                    self.ui.statusBar().showMessage('USB device added back, Serial Open requested.', 5000)            
            else:
                # We have new device insertion, connect to it
                if self.serialPort == "":
                    # Figure out if useable port
                    if ports:
                        new_ports = [port for port in ports if port not in self.serialPorts]
                        if new_ports:
                            new_port = new_ports[0]
                            new_baudrate = self.serialBaudRate if self.serialBaudRate > 0 else DEFAULT_BAUDRATE
                            new_esp_reset = self.esp_reset
                            # Start the receiver
                            QTimer.singleShot(  0, lambda: self.changePortRequest.emit(new_port, new_baudrate, new_esp_reset)) # takes 11ms to open
                            QTimer.singleShot(100, lambda: self.scanPortsRequest.emit())                # request new port list
                            QTimer.singleShot(150, lambda: self.scanBaudRatesRequest.emit())            # request new baud rate list
                            QTimer.singleShot(200, lambda: self.serialStatusRequest.emit())             # request to report serial port status            
                            QTimer.singleShot(250, lambda: self.startThroughputRequest.emit())          # request to start serial receiver
                            # un-shade sending text
                            self.ui.lineEdit_SerialText.setEnabled(True)
                            self.ui.pushButton_SerialSend.setEnabled(True)                
                            self.logger.log(
                                logging.INFO, 
                                f"[{self.thread_id}]: requesting Opening Serial port {new_port} with {new_baudrate} baud and ESP reset {'on' if new_esp_reset else 'off'}."
                            )
                            self.ui.statusBar().showMessage('Serial Open requested.', 2000)

    # Response Functions to User Interface Signals
    ########################################################################################

    @pyqtSlot(int,str)
    def on_logSignal(self, int, str):
        """pickup log messages"""
        self.logger.log(int, str)

    @pyqtSlot()
    def on_serialMonitorSend(self):
        """
        Transmitting text from UI to serial TX line
        """
        text = self.ui.lineEdit_SerialText.text()                                # obtain text from send input window
        self.displayingRunning.emit(True)            
        self.ui.pushButton_SerialStartStop.setText("Stop")
        
        try:
            text_bytearray = text.encode(self.encoding) + self.textLineTerminator # add line termination
        except UnicodeEncodeError:
            text_bytearray = text.encode("utf-8", errors="replace") + self.textLineTerminator
            self.logger.log(logging.WARNING, f"[{self.thread_id}]: Encoding error, using UTF-8 fallback.")
        except Exception as e:
            self.logger.log(logging.ERROR, f"[{self.thread_id}]: Encoding error: {e}")
            return
        self.sendTextRequest.emit(text_bytearray)                                # send text to serial TX line
        self.ui.lineEdit_SerialText.clear()
        self.ui.statusBar().showMessage("Text sent.", 2000)

    @pyqtSlot()
    def on_serialSendFile(self):
        """
        Transmitting file to serial TX line
        """
        stdFileName = (
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.DocumentsLocation
            )
            + "/QSerial.txt"
        )
        fname, _ = QFileDialog.getOpenFileName(
            self.ui, "Open", stdFileName, "Text files (*.txt)"
        )
        if fname:
            QTimer.singleShot( 0, lambda: self.startThroughputRequest.emit())
            QTimer.singleShot(50, lambda: self.serialSendFileRequest.emit(fname))
            
        self.ui.statusBar().showMessage('Text file sent.', 2000)            

    @pyqtSlot()
    def on_serialMonitorSendUpArrowPressed(self):
        """
        Handle special keys on lineEdit: UpArrow
        """
        self.serialSendHistoryIndx += 1 # increment history pointer
        # if pointer at end of buffer restart at -1
        if self.serialSendHistoryIndx == len(self.serialSendHistory):
            self.serialSendHistoryIndx = -1
        # populate with previously sent command from history buffer
        if self.serialSendHistoryIndx == -1:
            # if index is -1, use empty string as previously sent command
            self.ui.lineEdit_SerialText.setText("")
        else:
            self.ui.lineEdit_SerialText.setText(
                self.serialSendHistory[self.serialSendHistoryIndx]
            )

        self.ui.statusBar().showMessage("Previously sent text retrieved.", 2000)

    @pyqtSlot()
    def on_serialMonitorSendDownArrowPressed(self):
        """
        Handle special keys on lineEdit: DownArrow
        """
        self.serialSendHistoryIndx -= 1 # decrement history pointer
        # if pointer is at start of buffer, reset index to end of buffer
        if self.serialSendHistoryIndx == -2:
            self.serialSendHistoryIndx = len(self.serialSendHistory) - 1

        # populate with previously sent command from history buffer
        if self.serialSendHistoryIndx == -1:
            # if index is -1, use empty string as previously sent command
            self.ui.lineEdit_SerialText.setText("")
        else:
            self.ui.lineEdit_SerialText.setText(
                self.serialSendHistory[self.serialSendHistoryIndx]
            )

        self.ui.statusBar().showMessage("Previously sent text retrieved.", 2000)

    @pyqtSlot()
    def on_pushButton_SerialClearOutput(self):
        """
        Clearing text display window
        """
        self.ui.plainTextEdit_SerialTextDisplay.clear()
        self.lineBuffer.clear()
        self.ui.statusBar().showMessage("Text Display Cleared.", 2000)

    @pyqtSlot()
    def on_pushButton_SerialStartStop(self):
        """
        Start serial receiver
        """
        if self.ui.pushButton_SerialStartStop.text() == "Start":
            # START text display
            self.ui.pushButton_SerialStartStop.setText("Stop")
            self.displayingRunning.emit(True)

            self.logger.log(
                logging.DEBUG,
                f"[{self.thread_id}]: turning text display on."
            )
            self.ui.statusBar().showMessage("Text Display Starting", 2000)
        else:
            # STOP text display
            self.ui.pushButton_SerialStartStop.setText("Start")
            self.displayingRunning.emit(False)
            
            self.logger.log(
                logging.DEBUG, 
                f"[{self.thread_id}]: turning text display off."
            )
            self.ui.statusBar().showMessage('Text Display Stopping.', 2000)            

    @pyqtSlot()
    def on_pushButton_SerialSave(self):
        """
        Saving text from display window into text file
        """
        stdFileName = (
            QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
            + "/QSerial.txt"
        )
        fname, _ = QFileDialog.getSaveFileName(
            self.ui, "Save as", stdFileName, "Text files (*.txt)"
        )

        if fname:
            # check if fname is valid, user can select cancel
            with open(fname, "w") as f:
                f.write(self.ui.plainTextEdit_SerialTextDisplay.toPlainText())

        self.ui.statusBar().showMessage("Serial Monitor text saved.", 2000)

    @pyqtSlot()
    def on_pushButton_SerialScan(self):
        """
        Updating serial port list

        Sends signal to serial worker to scan for ports
        Serial worker will create newPortList signal when completed which
        is handled by the function on_newPortList below
        """
        self.scanPortsRequest.emit()
        self.logger.log(
            logging.DEBUG, 
            f"[{self.thread_id}]: scanning for serial ports."
        )
        self.ui.statusBar().showMessage('Serial Port Scan requested.', 2000)            

    @pyqtSlot()
    def on_resetESPonOpen(self):
        self.esp_reset = self.ui.radioButton_ResetESPonOpen.isChecked()

    @pyqtSlot()
    def on_SerialRecord(self):
        self.record = self.ui.radioButton_SerialRecord.isChecked()
        if self.record:
    
            if self.recordingFileName == "":
                stdFileName = (
                    QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
                    + "/QSerial.txt"
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

    @pyqtSlot()
    def on_pushButton_SerialOpenClose(self):
        if self.ui.pushButton_SerialOpenClose.text() == "Close":
            # Close the serial port
            #   stop the receiver
            QTimer.singleShot(  0, lambda: self.stopThroughputRequest.emit()) # request to stop throughput
            QTimer.singleShot( 50, lambda: self.closePortRequest.emit())      # request to close serial port
            QTimer.singleShot(250, lambda: self.serialStatusRequest.emit())   # request to report serial port status
            #   shade sending text
            self.ui.lineEdit_SerialText.setEnabled(False)
            self.ui.pushButton_SerialSend.setEnabled(False)
            self.logger.log(
                logging.INFO, 
                f"[{self.thread_id}]: requesting closing serial port."
            )
            self.ui.statusBar().showMessage("Serial Close requested.", 2000)
        else:
            # Open the serial port
            index = self.ui.comboBoxDropDown_SerialPorts.currentIndex()
            try:
                port = self.serialPorts[index]                                # we have valid port

            except Exception as e:
                self.logger.log(
                    logging.INFO, 
                    f"[{self.thread_id}]: serial port not valid. Error {str(e)}"
                )
                self.ui.statusBar().showMessage('Can not open serial port.', 2000)
                return

            else:
                baudrate = self.serialBaudRate if self.serialBaudRate > 0 else DEFAULT_BAUDRATE
                textLineTerminator = self.update_LineTermination()

                # Start the receiver
                QTimer.singleShot(  0, lambda: self.changeLineTerminationRequest.emit(textLineTerminator))
                QTimer.singleShot( 20, lambda: self.changePortRequest.emit(port, baudrate, self.esp_reset)) # takes 11ms to open
                QTimer.singleShot(150, lambda: self.scanBaudRatesRequest.emit())   #
                QTimer.singleShot(200, lambda: self.serialStatusRequest.emit())    # request to report serial port status            
                QTimer.singleShot(250, lambda: self.startThroughputRequest.emit()) # request to start serial receiver
                #   un-shade sending text
                self.ui.lineEdit_SerialText.setEnabled(True)
                self.ui.pushButton_SerialSend.setEnabled(True)                
                self.logger.log(
                    logging.INFO, 
                    f"[{self.thread_id}]: requesting opening serial port {port} with {self.serialBaudRate} baud {'with esp reset.' if self.esp_reset else 'with reset.'}."
                )
                self.ui.statusBar().showMessage('Serial Open requested.', 2000)

        # clear USB unplug reconnection flag
        self.awaitingReconnection = False

    @pyqtSlot()
    def on_comboBoxDropDown_SerialPorts(self):
        """
        User selected a new port on the drop down list
        """
        lenSerialPorts = len(self.serialPorts)

        # keep track of selected port
        portIndex = self.ui.comboBoxDropDown_SerialPorts.currentIndex()

        port = None
        baudrate = None

        self.ui.pushButton_SerialOpenClose.setEnabled(False)
        if lenSerialPorts > 0:  # only continue if we have recognized serial ports
            if (portIndex > -1) and (portIndex < lenSerialPorts):
                port = self.serialPorts[portIndex]  # we have valid port
                self.ui.pushButton_SerialOpenClose.setEnabled(True)

        # Change the port if a port is open, otherwise we need to click on open button
        if self.serialPort != "":
            # A port is in use and we selected 
            if port is None:
                # "None" was selected so close the port
                QTimer.singleShot(  0, lambda: self.stopThroughputRequest.emit())   # request to stop throughput
                QTimer.singleShot( 50, lambda: self.closePortRequest.emit())        # request to close port
                QTimer.singleShot(250, lambda: self.serialStatusRequest.emit())     # request to report serial port status
                return                                                              # do not continue

            else:
                # We have valid new port
                
                # Make sure we have valid baud rate to open the new port
                lenBaudRates   = len(self.BaudRates)

                if lenBaudRates > 0:  # if we have recognized serial baud rates
                    baudIndex = self.ui.comboBoxDropDown_BaudRates.currentIndex()
                    if baudIndex < lenBaudRates:  # last entry is -1
                        baudrate = self.BaudRates[baudIndex]
                        self.logger.log(logging.INFO, f"[{self.thread_id}]: Changing baudrate to {baudrate}")
                    else:
                        baudrate = self.defaultBaudRate  # use default baud rate
                        self.logger.log(logging.INFO, f"[{self.thread_id}]: Using default baudrate {baudrate}")
                else:
                    baudrate = self.defaultBaudRate # use default baud rate, user can change later

            # change port if port changed
            if port != self.serialPort or baudrate != self.serialBaudRate:
                esp_reset = self.ui.radioButton_ResetESPonOpen.isChecked()
                QTimer.singleShot(   0, lambda: self.changePortRequest.emit(port, baudrate, esp_reset ))  # takes 11ms to open
                QTimer.singleShot( 200, lambda: self.scanBaudRatesRequest.emit())  # request to scan serial baud rates
                QTimer.singleShot( 250, lambda: self.serialStatusRequest.emit())   # request to report serial port status
                self.logger.log(
                    logging.INFO,
                    f"[{self.thread_id}]: port {port} baud {baudrate}"
                )
            else:
                # port already open
                self.logger.log(
                    logging.INFO,
                    f"[{self.thread_id}]: keeping current port {port} baud {baudrate}"
                )

        else:
            # No port is open, do not change anything
            self.logger.log(
                logging.INFO,
                f"[{self.thread_id}]: No port was perviously open."
            )

        self.ui.statusBar().showMessage("Serial port change requested.", 2000)

    @pyqtSlot()
    def on_comboBoxDropDown_BaudRates(self):
        """
        User selected a different baudrate on drop down list
        """
        if self.serialPort != "":
            lenBaudRates = len(self.BaudRates)

            if lenBaudRates > 0:  # if we have recognized serial baud rates
                index = self.ui.comboBoxDropDown_BaudRates.currentIndex()

                if index < lenBaudRates:  # last entry is -1
                    baudrate = self.BaudRates[index]
                    self.logger.log(logging.INFO, f"[{self.thread_id}]: Changing baudrate to {baudrate}")
                else:
                    baudrate = self.defaultBaudRate  # use default baud rate
                    self.logger.log(logging.INFO, f"[{self.thread_id}]: Using default baudrate {baudrate}")

                if baudrate != self.serialBaudRate:  # change baudrate if different from current
                    self.changeBaudRequest.emit(baudrate)
                    QTimer.singleShot(200, lambda: self.serialStatusRequest.emit())             # request to report serial port status
                    self.logger.log(
                        logging.INFO,
                        f"[{self.thread_id}]: Changing baudrate to {baudrate}."
                    )
                else:
                    self.logger.log(
                        logging.INFO,
                        f"[{self.thread_id}]: Baudrate remains the same."
                    )

            else:
                self.logger.log(
                    logging.ERROR,
                    f"[{self.thread_id}]: No baudrates available"
                )

        else:
            # do not change anything as we first need to open a port
            self.logger.log(
                logging.WARNING,
                f"[{self.thread_id}]: No port open, can not change baudrate"
            )

        self.ui.statusBar().showMessage('Baudrate change requested.', 2000)

    @pyqtSlot()
    def on_comboBoxDropDown_LineTermination(self):
        """
        User selected a different line termination from drop down menu
        """
        self.textLineTerminator = self.update_LineTermination()

        # ask line termination to be changed if port is open
        if self.serialPort != "":
            QTimer.singleShot( 0, lambda: self.changeLineTerminationRequest.emit(self.textLineTerminator))
            QTimer.singleShot(50, lambda: self.serialStatusRequest.emit()) # request to report serial port status

        self.logger.log(
            logging.INFO,
            f"[{self.thread_id}]: line termination {repr(self.textLineTerminator)}"
        )
        self.ui.statusBar().showMessage("Line Termination updated", 2000)

    def update_LineTermination(self):
        """ update line termination from UI"""
        _tmp = self.ui.comboBoxDropDown_LineTermination.currentText()
        if   _tmp == "newline (\\n)":           return(b"\n")
        elif _tmp == "return (\\r)":            return(b"\r")
        elif _tmp == "newline return (\\n\\r)": return(b"\n\r")
        elif _tmp == "none":                    return(b"")
        else:                                   return(b"\r\n")

    # Response to Serial Signals
    ########################################################################################

    @pyqtSlot(str, int, bytes, float)
    def on_serialStatusReady(self, port: str, baud: int, eol: bytes, timeout: float):
        """
        Serial status report available
        """
        self.serialPort = port

        if self.serialPort == "":
            self.ui.pushButton_SerialOpenClose.setText("Open")

        else: 
            # update only if we have valid port
            self.textLineTerminator = eol
            self.serialTimeout = timeout
            if baud > 0:
                self.serialBaudRate  = baud
                self.defaultBaudRate = baud
            else:
                self.serialBaudRate = self.defaultBaudRate

            self.ui.pushButton_SerialOpenClose.setText("Close")

            # adjust the combobox current item to match the current port
            try:
                index = self.ui.comboBoxDropDown_SerialPorts.findText(
                    self.serialPort
                )  # find current port in serial port list
                self.ui.comboBoxDropDown_SerialPorts.blockSignals(True)
                self.ui.comboBoxDropDown_SerialPorts.setCurrentIndex(index)  # update serial port combobox
                self.ui.comboBoxDropDown_SerialPorts.blockSignals(False)
                self.logger.log(
                    logging.DEBUG,
                    f'[{self.thread_id}]: selected port "{self.serialPort}".'
                )
            except Exception as e:
                self.logger.log(
                    logging.ERROR,
                    f"[{self.thread_id}]: port not available. Error {str(e)}."
                )
            # adjust the combobox current item to match the current baudrate
            try:
                index = self.ui.comboBoxDropDown_BaudRates.findText(str(self.serialBaudRate))
                if index > -1:
                    self.ui.comboBoxDropDown_BaudRates.blockSignals(True)
                    self.ui.comboBoxDropDown_BaudRates.setCurrentIndex(index)  #  baud combobox
                    self.logger.log(
                        logging.DEBUG,
                        f"[{self.thread_id}]: selected baudrate {self.serialBaudRate}."
                    )
                else:
                    self.logger.log(
                        logging.DEBUG,
                        f"[{self.thread_id}]: baudrate {self.serialBaudRate} not found."
                    )            
            except Exception as e:
                self.logger.log(
                    logging.ERROR,
                    f"[{self.thread_id}]: could not select baudrate. Error {str(e)}"
                )
            finally:
                self.ui.comboBoxDropDown_BaudRates.blockSignals(False)


            # adjust the combobox current item to match the current line termination
            if   eol == b"\n":   _tmp = "newline (\\n)"
            elif eol == b"\r":   _tmp = "return (\\r)"
            elif eol == b"\n\r": _tmp = "newline return (\\n\\r)"
            elif eol == b"\r\n": _tmp = "return newline (\\r\\n)"
            elif eol == b"":     _tmp = "none"
            else:               
                _tmp = "return newline (\\r\\n)"
                self.logger.log(
                    logging.WARNING,
                    f"[{self.thread_id}]: unknown line termination {eol}."
                )
                self.logger.log(
                    logging.WARNING,
                    f"[{self.thread_id}]: set line termination to {_tmp}."
                )

            try:
                index = self.ui.comboBoxDropDown_LineTermination.findText(_tmp)
                if index > -1:  # Check if the text was found
                    self.ui.comboBoxDropDown_LineTermination.blockSignals(True)
                    self.ui.comboBoxDropDown_LineTermination.setCurrentIndex(index)
                    self.logger.log(
                        logging.DEBUG,
                        f"[{self.thread_id}]: selected line termination {_tmp}."
                    )
                else:  # Handle case when the text is not found
                    self.logger.log(
                        logging.DEBUG,
                        f"[{self.thread_id}]: line termination {_tmp} not found."
                    )
            except Exception as e:  # Catch specific exceptions if possible
                self.logger.log(
                    logging.ERROR,
                    f"[{self.thread_id}]: line termination not available. Error: {str(e)}"
                )
            finally:
                self.ui.comboBoxDropDown_LineTermination.blockSignals(False)

            self.logger.log(
                logging.DEBUG,
                f"[{self.thread_id}]: receiver is {'running' if self.receiverIsRunning else 'not running'}."
            )

        # handle timeout and encoding
        #  not implemented as currently not selectable in the UI
        #  encoding is fixed to utf-8
        #  timeout can be computed from baud rate and longest expected line of text
        #  however it is set to zero resulting in non blocking reads and writes

        self.ui.statusBar().showMessage("Serial status updated", 2000)

    @pyqtSlot(list, list)
    def on_newPortListReady(self, ports: list, portNames: list):
        """
        New serial port list available
        """
        self.logger.log(
            logging.DEBUG,
            f"[{self.thread_id}]: port list received."
        )
        self.serialPorts = ports
        self.serialPortNames = portNames
        lenPortNames = len(self.serialPortNames)
        self.ui.comboBoxDropDown_SerialPorts.blockSignals(True) # block the box from emitting changed index signal when items are added
        # populate new items
        self.ui.comboBoxDropDown_SerialPorts.clear()
        self.ui.comboBoxDropDown_SerialPorts.addItems(self.serialPorts + ["None"])
        index = self.ui.comboBoxDropDown_SerialPorts.findText(self.serialPort)
        if index > -1: # if we found previously selected item
            self.ui.comboBoxDropDown_SerialPorts.setCurrentIndex(index)
        else:  # if we did not find previous item, set box to last item (None)
            self.ui.comboBoxDropDown_SerialPorts.setCurrentIndex(lenPortNames)
            QTimer.singleShot(  0, lambda: self.stopThroughputRequest.emit())          # request to stop throughput
            QTimer.singleShot( 50, lambda: self.closePortRequest.emit())               # request to close serial port
            QTimer.singleShot(250, lambda: self.serialStatusRequest.emit())            # request to report serial port status
        # enable signals again
        self.ui.comboBoxDropDown_SerialPorts.blockSignals(False)
        self.ui.statusBar().showMessage("Port list updated", 2000)

    @pyqtSlot(tuple)
    def on_newBaudListReady(self, baudrates):
        """
        New baud rate list available
        For logic and sequence of commands refer to newPortList
        """
        self.logger.log(
            logging.DEBUG,
            f"[{self.thread_id}]: baud list received."
        )
        self.BaudRates = list(baudrates)
        lenBaudRates = len(self.BaudRates)
        self.ui.comboBoxDropDown_BaudRates.blockSignals(True)
        self.ui.comboBoxDropDown_BaudRates.clear()
        self.ui.comboBoxDropDown_BaudRates.addItems(
            [str(x) for x in self.BaudRates]
        )
        index = self.ui.comboBoxDropDown_BaudRates.findText(str(self.serialBaudRate))
        if index > -1:
            self.ui.comboBoxDropDown_BaudRates.setCurrentIndex(index)
        else:
            self.ui.comboBoxDropDown_BaudRates.setCurrentIndex(lenBaudRates)
        self.ui.comboBoxDropDown_BaudRates.blockSignals(False)
        self.ui.statusBar().showMessage("Baudrates updated", 2000)


    # Helper function for decoding text safely
    def safe_decode(self, byte_data, encoding="utf-8"):
        """
        Safely decodes a byte array to a string, replacing invalid characters.
        """
        try:
            return byte_data.decode(encoding)
        except UnicodeDecodeError as e:
            return byte_data.decode(encoding, errors="replace").replace("\ufffd", "¿")
        except Exception as e:
            return ""  # Return empty string if decoding completely fails


    @pyqtSlot(bytes)
    def on_SerialReceivedText(self, byte_array: bytes):
        """
        Receives a raw byte array from the serial port, decodes it, stores it in a line-based buffer,
        and updates the text display efficiently.
        """
        self.logger.log(logging.DEBUG, f"[{self.thread_id}]: text received.")

        # 1. Decode byte array
        text = self.safe_decode(byte_array, self.encoding)
        
        if DEBUGSERIAL:
            self.logger.log(logging.DEBUG, f"[{self.thread_id}]: {text}")

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
            self.ui.plainTextEdit_SerialTextDisplay.appendPlainText(text)

            # 4. Store lines in the `deque`
            new_lines = text.split("\n")
            self.lineBuffer.extend(new_lines)  # Automatically trims excess lines

            # 5. Update the line count
            # self.textDisplayLineCount += len(new_lines)  # Update the line count

            # 6. Maintain scroll position if at the bottom
            if at_bottom:
                scrollbar = self.textScrollbar
                scrollbar.setValue(scrollbar.maximum())

    @pyqtSlot(list)
    def on_SerialReceivedLines(self, lines: list):
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
        decoded_lines = [self.safe_decode(line, self.encoding) for line in lines]

        if DEBUGSERIAL:
            for decoded_line in decoded_lines:
                self.logger.log(logging.DEBUG, f"[{self.thread_id}]: {decoded_line}")

        # 3. Append to `deque` (automatically trims when max length is exceeded)
        self.lineBuffer.extend(decoded_lines)

        # 4. Append text to display
        if decoded_lines:
            text = "\n".join(decoded_lines)

            # Check if user has scrolled to the bottom
            scrollbar = self.textScrollbar
            at_bottom = scrollbar.value() >= scrollbar.maximum() - 20

            self.ui.plainTextEdit_SerialTextDisplay.appendPlainText(text)

            # If the user was at the bottom, keep scrolling
            if at_bottom:
                scrollbar = self.textScrollbar
                scrollbar.setValue(scrollbar.maximum())

        # 5 Update total line count
        # self.textDisplayLineCount += len(decoded_lines)

    @pyqtSlot(bool)
    def on_serialWorkerStateChanged(self, running: bool):
        """
        Serial worker was started or stopped
        """
        self.logger.log(
            logging.INFO,
            f"[{self.thread_id}]: serial worker is {'on' if running else 'off'}."
        )
        self.receiverIsRunning = running
        if running:
            self.ui.statusBar().showMessage("Serial Worker started", 2000)
        else:
            self.ui.statusBar().showMessage("Serial Worker stopped", 2000)

    def on_throughputReceived(self, numReceived, numSent):
        """
        Report throughput
        """
        rx = numReceived - self.lastNumReceived
        tx = numSent - self.lastNumSent
        if rx < 0: rx = self.rx # self.lastNumReceived is not cleared when we clear the serial buffer, take care of it here
        if tx < 0: tx = self.tx
        # # poor man's low pass
        # self.rx = 0.5 * self.rx + 0.5 * rx
        # self.tx = 0.5 * self.tx + 0.5 * tx
        self.rx = rx
        self.tx = tx
        self.ui.throughput.setText(
            "{:<5.1f} {:<5.1f} kB/s".format(self.rx / 1000, self.tx / 1000)
        )
        self.lastNumReceived = numReceived
        self.lastNumSent = numSent

    def serialTextDisplay_trim(self):
        """
        Reduce the amount of text kept in the text display window
        Attempt to keep the scrollbar location
        """

        tic = time.perf_counter()

        # 0 Do we need to trim?
        textDisplayLineCount = self.ui.plainTextEdit_SerialTextDisplay.document().blockCount() # 70 micros
 
        if textDisplayLineCount > self.textBrowserLength:

            old_textDisplayLineCount = textDisplayLineCount
            scrollbar = self.textScrollbar  # Avoid redundant calls

            #  1 Where is the current scrollbar? (scrollbar value is pixel based)
            old_scrollbarMax = scrollbar.maximum()
            old_scrollbarValue = scrollbar.value()

            old_proportion = (old_scrollbarValue / old_scrollbarMax) if old_scrollbarMax > 0 else 1.0            
            old_linePosition = round(old_proportion * old_textDisplayLineCount)

            # 2 Replace text with the line buffer
            # lines_inTextBuffer  = len(self.lineBuffer)
            text = "\n".join(self.lineBuffer)
            self.ui.plainTextEdit_SerialTextDisplay.setPlainText(text)
            new_textDisplayLineCount = self.ui.plainTextEdit_SerialTextDisplay.document().blockCount()
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
            self.logger.log(
                logging.INFO,
                f"[{self.thread_id}]: trimmed text display in {(toc-tic)*1000:.2f} ms."
            )

        self.ui.statusBar().showMessage('Trimmed Text Display Window', 2000)
    
    def cleanup(self):
        if hasattr(self.recordingFile, "close"):
            try:
                self.recordingFile.close()
            except:
                self.logger.log(
                    logging.ERROR, 
                    f"[{self.thread_id}]: Could not close file {self.recordingFileName}."
                )
        self.logger.log(
            logging.INFO, 
            f"[{self.thread_id}]: cleaned up."
        )

##########################################################################################################################################        
##########################################################################################################################################        
#
# Q Serial
#
# separate thread handling serial input and output
# these routines have no access to the user interface,
# communication occurs through signals
#
# for serial write we send bytes
# for serial read we receive bytes
# conversion from text to bytes occurs in QSerialUI
#
#    This is the Model of the Model - View - Controller (MVC) architecture.
#
##########################################################################################################################################        
##########################################################################################################################################        

class QSerial(QObject):
    """
    Serial Interface for QT

    Worker Signals
        textReceived bytes               received text on serial RX
        linesReceived list               received multiple lines on serial RX
        newPortListReady                 completed a port scan
        newBaudListReady                 completed a baud scan
        throughputReady                  throughput data is available
        serialStatusReady                report on port and baudrate available
        serialWorkerStateChanged         worker started or stopped

    Worker Slots
        on_startReceiverRequest()        start timer that reads input port
        on_stopReceiverRequest()         stop  timer that reads input port
        on_stopWorkerRequest()           stop  timer and close serial port
        on_sendTextRequest(bytes)        worker received request to transmit text
        on_sendLinesRequest(list of bytes) worker received request to transmit multiple lines of text
        on_changePortRequest(str, int, bool) worker received request to change port
        on_changeLineTerminationRequest(bytes)
        on_changeSerialReset(bool)       worker received request to change serial reset
        on_change...                     worker received request to change line termination
        on_closePortRequest()            worker received request to close current port
        on_changeBaudRequest(int)        worker received request to change baud rate
        on_scanPortsRequest()            worker received request to scan for serial ports
        on_scanBaudRatesRequest()        worker received request to scan for serial baudrates
        on_serialStatusRequest()         worker received request to report current port and baudrate
        on_startThroughputRequest()      start timer to report throughput
        on_stopThroughputRequest()       stop timer to report throughput
        on_throughputTimer()             emit throughput data
    """

    # Signals
    ########################################################################################
    textReceived             = pyqtSignal(bytes)                                           # text received on serial port
    linesReceived            = pyqtSignal(list)                                            # lines of text received on serial port
    newPortListReady         = pyqtSignal(list, list)                                      # updated list of serial ports is available
    newBaudListReady         = pyqtSignal(tuple)                                           # updated list of baudrates is available
    serialStatusReady        = pyqtSignal(str, int, bytes, float)                          # serial status is available
    throughputReady          = pyqtSignal(int,int)                                         # number of characters received/sent on serial port
    serialWorkerStateChanged = pyqtSignal(bool)                                            # worker started or stopped
    logSignal                = pyqtSignal(int, str)                                         # Logging
    finished                 = pyqtSignal() 
        
    # Init
    ########################################################################################
    def __init__(self, parent=None):

        super().__init__(parent)

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"

        self.PSer = PSerial(parent=self)  # serial port object

        # Serial Ports
        self.PSer.scanports()
        self.serialPorts     = [sublist[0] for sublist in self.PSer.ports]                  # COM3 ...
        self.serialPortNames = [sublist[1] for sublist in self.PSer.ports]                  # USB ... (COM3)
        self.serialPortHWID  = [sublist[2] for sublist in self.PSer.ports]                  # USB VID:PID=1A86:7523 LOCATION=3-2

        # Baud Rates
        self.serialBaudRates = self.PSer.baudrates                                          # will have default baudrate as no port is open
        
        self.textLineTerminator = b"\r\n" # default line termination

        # Adjust response time
        # Fastest serial baud rate is 5,000,000 bits per second
        # Regular serial baud rate is   115,200 bits per second OR 5000000
        # Slow serial baud rate is        9,600 bits per second
        # Transmitting one byte with 8N1 (8 data bits, no stop bit, one stop bit) might take up to 10 bits
        # Transmitting two int16 like "-8192, -8191\r\n" takes 14 bytes (3 times more than the actual numbers)
        # This would result in receiving 1k lines/second with 115200 and 40k lines/second with 5,000,000
        # These numbers are now updated with a function based on baud rate, see further below
        self.receiverInterval        = MIN_RECEIVER_INTERVAL  # in milliseconds
        self.receiverIntervalStandby = 10 * MIN_RECEIVER_INTERVAL  # in milliseconds
        self.serialReadTimeOut       = 0  # in seconds
        self.serialReceiverCountDown = 0  # initialize

        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: QSerial initialized."
        )

    def handle_log(self, level, message):
        """Emit the log signal with a level and message."""
        self.logSignal.emit(level, message)

    # Slots
    ########################################################################################

    @pyqtSlot()
    def on_setupReceiverRequest(self):
        """
        Set up a QTimer for reading data from serial input line at predefined interval.
        This does not start the timer.
        We can not create the timer in the init function because when we move QSerial
         to a new thread and the timer would not move with it.

        Set up QTimer for throughput measurements
        """

        # if DEBUGPY_ENABLED: debugpy.debug_this_thread() # this should enable debugging of all methods QSerial methods

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"

        # setup the receiver timer
        self.serialReceiverState = SerialReceiverState.stopped  # initialize state machine
        self.receiverTimer = QTimer()
        self.receiverTimer.timeout.connect(self.updateReceiver)
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: setup receiver timer."
        )

        # setup the throughput measurement timer
        self.throughputTimer = QTimer()
        self.throughputTimer.setInterval(1000)
        self.throughputTimer.timeout.connect(self.on_throughputTimer)
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: setup throughput timer."
        )

    @pyqtSlot()
    def on_throughputTimer(self):
        """
        Report throughput
        """
        if self.PSer.connected:
            self.throughputReady.emit(
                self.PSer.totalCharsReceived, self.PSer.totalCharsSent
            )
        else:
            self.throughputReady.emit(0, 0)

    @pyqtSlot()
    def on_startReceiverRequest(self):
        """
        Start QTimer for reading data from serial input line (RX)
        Response will need to be analyzed in the main task.
        """
        # clear serial buffers
        self.PSer.clear()

        # start the receiver timer
        self.receiverTimer.setInterval(self.receiverInterval)
        self.receiverTimer.start()
        self.serialReceiverState = SerialReceiverState.awaitingData
        self.serialWorkerStateChanged.emit(True)  # serial worker is running
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: started receiver."
        )

    @pyqtSlot()
    def on_stopReceiverRequest(self):
        """
        Stop the receiver timer
        """
        self.receiverTimer.stop()
        self.serialReceiverState = SerialReceiverState.stopped
        self.serialWorkerStateChanged.emit(False)  # serial worker not running
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: stopped receiver."
        )

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
    def updateReceiver(self):
        """
        Reading lines of text from serial RX
        """
        if self.serialReceiverState == SerialReceiverState.stopped:
            self.handle_log(logging.ERROR, f"[{self.thread_id}]: receiver is stopped.")
            return
                
        start_time = time.perf_counter()

        if not self.PSer.connected:
            self.handle_log(logging.ERROR, f"[{self.thread_id}]: serial port not connected.")
            return

        # Check if end-of-line handling is needed
        if self.PSer.eol:  # non empty byte array
            # reading lines
            # -------------
            try:
                lines = self.PSer.readlines()  # Read lines until buffer is empty
            except Exception as e:
                self.handle_log(logging.ERROR, f"[{self.thread_id}]: Error reading lines - {e}")
                lines = []

            end_time = time.perf_counter()

            if lines:
                self.linesReceived.emit(lines)

                if DEBUGSERIAL:
                    self.handle_log(
                        logging.DEBUG,
                        f"[{self.thread_id}]: {len(lines)} lines {1000 * (end_time - start_time) / len(lines):.3f} ms per line."
                    )
                    self.handle_log(
                        logging.DEBUG,
                        "\n"
                        + "\n".join(
                            line.decode(errors="replace").replace("\ufffd", "¿")
                            for line in lines
                        ),
                    )

                if self.serialReceiverState == SerialReceiverState.awaitingData:
                    self.receiverTimer.setInterval(self.receiverInterval)
                    self.serialReceiverState = SerialReceiverState.receivingData
                    self.handle_log(
                        logging.INFO,
                        f"[{self.thread_id}]: receiving started, set faster update rate."
                    )

                self.serialReceiverCountDown = 0

            else:
                if self.serialReceiverState == SerialReceiverState.receivingData:
                    self.serialReceiverCountDown += 1
                    if self.serialReceiverCountDown >= RECEIVER_FINISHCOUNT:
                        self.serialReceiverState = SerialReceiverState.awaitingData
                        self.receiverTimer.setInterval(self.receiverIntervalStandby)
                        self.serialReceiverCountDown = 0
                        self.handle_log(
                            logging.INFO,
                            f"[{self.thread_id}]: receiving finished, set slower update rate."
                        )

        else:
            # reading raw bytes
            # -----------------
            byte_array = self.PSer.read()
            end_time = time.perf_counter()

            if byte_array:
                self.textReceived.emit(byte_array)

                duration = 1000 * (end_time - start_time) / len(byte_array)

                if DEBUGSERIAL:
                    self.handle_log(
                        logging.DEBUG,
                        f"[{self.thread_id}]: {len(byte_array)} bytes {duration:.3f} ms per line."
                    )

                if self.serialReceiverState == SerialReceiverState.awaitingData:
                    self.receiverTimer.setInterval(self.receiverInterval)
                    self.serialReceiverState = SerialReceiverState.receivingData
                    self.handle_log(
                        logging.INFO,
                        f"[{self.thread_id}]: receiving started, set faster update rate."
                    )

                self.serialReceiverCountDown = 0

            else:
                if self.serialReceiverState == SerialReceiverState.receivingData:
                    self.serialReceiverCountDown += 1
                    if self.serialReceiverCountDown >= RECEIVER_FINISHCOUNT:
                        self.serialReceiverState = SerialReceiverState.awaitingData
                        self.receiverTimer.setInterval(self.receiverIntervalStandby)
                        self.serialReceiverCountDown = 0
                        self.handle_log(
                            logging.INFO,
                            f"[{self.thread_id}]: receiving finished, set slower update rate."
                        )

    @pyqtSlot()
    def on_stopWorkerRequest(self):
        """
        Worker received request to stop
        We want to stop QTimer and close serial port and then let subscribers know that serial worker is no longer available
        """
        self.throughputTimer.stop()
        self.receiverTimer.stop()
        self.serialWorkerStateChanged.emit(False)  # serial worker is not running
        self.PSer.close()
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: stopped timer, closed port."
        )
        self.finished.emit()

    @pyqtSlot(bytes)
    def on_sendTextRequest(self, byte_array: bytes):
        """
        Request to transmit text to serial TX line
        """
        if self.PSer.connected:
            l = self.PSer.write(byte_array)
            l_ba = len(byte_array)
            if DEBUGSERIAL:
                self.handle_log(
                    logging.DEBUG,
                    f'[{self.thread_id}]: transmitted "{byte_array.decode("utf-8")}" [{l} of {l_ba}].'
                )
            else:
                self.handle_log(
                    logging.DEBUG,
                    f"[{self.thread_id}]: transmitted {l} of {l_ba} bytes."
                )
        else:
            self.handle_log(
                logging.ERROR,
                "[{}]: Tx, port not opened.".format(self.thread_id),
            )

    @pyqtSlot(bytes)
    def on_sendLineRequest(self, byte_array: bytes):
        """
        Request to transmit a line of text to serial TX line
        Terminate the text with eol characters.
        """
        if self.PSer.connected:
            l = self.PSer.writeline(byte_array)
            l_ba = len(byte_array)
            if DEBUGSERIAL:
                self.handle_log(
                    logging.DEBUG,
                    f'[{self.thread_id}]: transmitted "{byte_array.decode("utf-8")}" [{l} of {l_ba}].'
                )
            else:
                self.handle_log(
                    logging.DEBUG,
                    f"[{self.thread_id}]: Transmitted {l} of {l_ba} bytes."
                )
        else:
            self.handle_log(
                logging.ERROR,
                f"[{self.thread_id}]: Tx, port not opened."
            )

    @pyqtSlot(list)
    def on_sendLinesRequest(self, lines: list):
        """
        Request to transmit multiple lines of text to serial TX line
        """
        if self.PSer.connected:
            l = self.PSer.writelines(lines)
            self.handle_log(
                logging.DEBUG,
                f"[{self.thread_id}]: transmitted {l} bytes."
            )
        else:
            self.handle_log(
                logging.ERROR,
                f"[{self.thread_id}]: Tx, port not opened."
            )

    @pyqtSlot(str)
    def on_sendFileRequest(self, fname: str):
        """
        Request to transmit file to serial TX line
        """
        # if DEBUGPY_ENABLED: debugpy.debug_this_thread()

        if self.PSer.connected:
            if fname:
                with open(fname, "rb") as f:  # open file in binary read mode
                    try:
                        file_content = f.read()
                        l = self.PSer.write(file_content)
                        self.handle_log(
                            logging.DEBUG,
                            f'[{self.thread_id}]: transmitted "{fname}" [{l}].'
                        )
                    except:
                        self.handle_log(
                            logging.ERROR,
                            f'[{self.thread_id}]: error transmitting "{fname}".'                        )
            else:
                self.handle_log(
                    logging.WARNING,
                    f"[{self.thread_id}]: no file name provided."
                )
        else:
            self.handle_log(
                logging.ERROR,
                f"[{self.thread_id}]: Tx, port not opened."
            )

    @pyqtSlot(str, int, bool)
    def on_changePortRequest(self, port: str, baud: int, esp_reset: bool):
        """
        Request to change port received
        """
        if port != "":
            self.PSer.close()
            serialReadTimeOut, receiverInterval, receiverIntervalStandby = (
                self.compute_timeouts(baud)
            )
            if self.PSer.open(
                port = port,
                baud = baud,
                eol = self.textLineTerminator,
                timeout = serialReadTimeOut,
                esp_reset = esp_reset,
            ):
                self.serialReadTimeOut = serialReadTimeOut
                self.receiverInterval = receiverInterval
                self.receiverIntervalStandby = receiverIntervalStandby
                self.receiverTimer.setInterval(self.receiverInterval)
                self.handle_log(
                    logging.INFO,
                    f"[{self.thread_id}]: port {port} opened with baud {baud} eol {repr(self.textLineTerminator)} and timeout {self.PSer.timeout}."
                )
            else:
                self.handle_log(
                    logging.ERROR,
                    f"[{self.thread_id}]: failed to open port {port}."
                )
        else:
            self.handle_log(
                logging.ERROR,
                f"[{self.thread_id}]: port not provided."
            )

    @pyqtSlot()
    def on_closePortRequest(self):
        """
        Request to close port received
        """
        self.on_stopReceiverRequest()
        self.on_stopThroughputRequest()
        self.PSer.close()

    @pyqtSlot(int)
    def on_changeBaudRateRequest(self, baud: int):
        """
        New baudrate received
        """
        if (baud is None) or (baud <= 0):
            self.handle_log(
                logging.WARNING,
                f"[{self.thread_id}]: range error, baudrate not changed to {baud}."
            )
        else:
            serialReadTimeOut, receiverInterval, receiverIntervalStandby = (
                self.compute_timeouts(baud)
            )
            if self.PSer.connected:
                if (self.serialBaudRates.index(baud) >= 0):
                    # self.PSer.changeport(
                    #     port=self.PSer.port,
                    #     baud=baud,
                    #     eol=self.textLineTerminator,
                    #     timeout=serialReadTimeOut,
                    #     esp_reset = self.PSer.esp_reset
                    # )
                    self.PSer.baud = baud
                    if (self.PSer.baud == baud):  # check if new value matches desired value
                        self.serialReadTimeOut = serialReadTimeOut
                        # self.serialBaudRate = baud  # update local variable
                        self.receiverInterval = receiverInterval
                        self.receiverIntervalStandby = receiverIntervalStandby
                        self.receiverTimer.setInterval(self.receiverInterval)
                    else:
                        # self.serialBaudRate = self.PSer.baud
                        self.handle_log(
                            logging.ERROR,
                            f"[{self.thread_id}]: failed to set baudrate to {baud}."
                        )
                else:
                    self.handle_log(
                        logging.ERROR,
                        f"[{self.thread_id}]: baudrate {baud} not available."
                    )
                    # self.serialBaudRate = self.defaultBaudRate
            else:
                self.handle_log(
                    logging.ERROR,
                    f"[{self.thread_id}]: failed to set baudrate, serial port not open!"
                )

    @pyqtSlot(bytes)
    def on_changeLineTerminationRequest(self, lineTermination: bytes):
        """
        New LineTermination received
        """
        if lineTermination is None:
            self.handle_log(
                logging.WARNING,
                f"[{self.thread_id}]: line termination not changed, line termination string not provided."
            )
            return
        else:
            self.PSer.eol = lineTermination
            self.textLineTerminator = lineTermination
            self.handle_log(
                logging.INFO,
                f"[{self.thread_id}]: changed line termination to {repr(self.textLineTerminator)}."
            )

    @pyqtSlot()
    def on_scanPortsRequest(self):
        """ 
        Request to scan for serial ports received 
        """            
        if self.PSer.scanports() > 0 :
            self.serialPorts     = [sublist[0] for sublist in self.PSer.ports if sublist[1] != 'n/a']
            self.serialPortNames = [sublist[1] for sublist in self.PSer.ports if sublist[1] != 'n/a']
            self.serialPortHWID  = [sublist[2] for sublist in self.PSer.ports if sublist[1] != 'n/a']
        else :
            self.serialPorts = []
            self.serialPortNames = []
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: port(s) {self.serialPortNames} available."
        )
        self.newPortListReady.emit(self.serialPorts, self.serialPortNames)

    @pyqtSlot()
    def on_scanBaudRatesRequest(self):
        """
        Request to report serial baud rates received
        """
        if self.PSer.connected:
            self.serialBaudRates = self.PSer.baudrates
        else:
            self.serialBaudRates = ()
        if len(self.serialBaudRates) > 0:
            self.handle_log(
                logging.INFO,
                f"[{self.thread_id}]: baudrate(s) {self.serialBaudRates} available."
            )
        else:
            self.handle_log(
                logging.WARNING,
                f"[{self.thread_id}]: no baudrates available, port is closed."
            )
            self.serialBaudRates = (DEFAULT_BAUDRATE,)
        self.newBaudListReady.emit(self.serialBaudRates)

    @pyqtSlot()
    def on_serialStatusRequest(self):
        """
        Request to report of serial status received
        """
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: provided serial status."
        )
        if self.PSer.connected:
            self.serialStatusReady.emit(
                self.PSer.port, self.PSer.baud, self.PSer.eol, self.PSer.timeout
            )
        else:
            self.serialStatusReady.emit(
                "", self.PSer.baud, self.PSer.eol, self.PSer.timeout
            )

    # TODO
    # !!!!!!!!!!!!!!! Will want to update this based on actual data rate !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # 

    def compute_timeouts(self, baud: int, chars_per_line: int = 50):
        # Set timeout to the amount of time it takes to receive the shortest expected line of text
        # integer '123/n/r' 5 bytes, which is at least 45 serial bits
        # serialReadTimeOut = 40 / baud [s] is very small and we should just set it to zero (non blocking)
        serialReadTimeOut = 0  # make it non blocking

        # Set the QTimer interval so that each call we get a couple of lines
        # lets assume we receive 5 integers in one line, this is approx 50 bytes in a line,
        # lets use 10 serial bits per byte
        # lets request NUM_LINES_COLLATE lines per call
        receiverInterval = ceil(
            NUM_LINES_COLLATE * chars_per_line * 10 / baud * 1000
        )  # in milliseconds
        receiverIntervalStandby = 10 * receiverInterval  # make standby 10 times slower

        # check serial should occur no more than 200 times per second no less than 10 times per second
        if receiverInterval        < MIN_RECEIVER_INTERVAL:        receiverInterval = MIN_RECEIVER_INTERVAL
        if receiverIntervalStandby < MIN_RECEIVER_INTERVAL: receiverIntervalStandby = MIN_RECEIVER_INTERVAL
        if receiverInterval        > MAX_RECEIVER_INTERVAL:        receiverInterval = MAX_RECEIVER_INTERVAL
        if receiverIntervalStandby > MAX_RECEIVER_INTERVAL: receiverIntervalStandby = MAX_RECEIVER_INTERVAL

        return serialReadTimeOut, receiverInterval, receiverIntervalStandby

#############################################################################################################################################
#############################################################################################################################################
#
#
# Serial Low Level
#
#
#############################################################################################################################################
#############################################################################################################################################

import os
import struct

# Used for resetting ESP on Unix-like systems
if os.name != "nt":
    import fcntl
    import termios

    # Constants used for terminal status lines reading/setting.
    #   taken from pySerial's backend for IO:
    #   https://github.com/pyserial/pyserial/blob/master/serial/serialposix.py
    TIOCMSET  = getattr(termios, "TIOCMSET",  0x5418)
    TIOCMGET  = getattr(termios, "TIOCMGET",  0x5415)
    TIOCM_DTR = getattr(termios, "TIOCM_DTR",  0x002)
    TIOCM_RTS = getattr(termios, "TIOCM_RTS",  0x004)

class PSerial():
    """
    Serial Wrapper.

    read and returns bytes or list of bytes
    write bytes or list of bytes
    """

    def __init__(self, parent=None):

        # if DEBUGPY_ENABLED: debugpy.debug_this_thread() # this should enable debugging of all PSerial methods

        self.ser                = None
        self._port              = ""
        self._baud              = -1
        self._eol               = b""
        self._timeout           = -1
        self._ser_open          = False
        self._esp_reset         = False
        self.totalCharsReceived = 0
        self.totalCharsSent     = 0
        self.bufferIn           = bytearray()
        self.reset_delay        = 0.05 # for ESP reset
        self.parent             = parent

        # setup logging delegation
        if parent is not None:
            # user parents logger
            if hasattr(parent, "handle_log"):
                self.handle_log = self.parent.handle_log
            else:
                self.logger = logging.getLogger("PSer")
                self.handle_log = self.logger.log
        else:
            self.logger = logging.getLogger("PSer")
            self.handle_log = self.logger.log
            
        # check for serial ports
        _ = self.scanports()

    def scanports(self) -> int:
        """
        Scans for all available serial ports.
        """
        try:
            self._ports = [
                [p.device, p.description, p.hwid]
                for p in list_ports.comports()
            ]
            num_ports = len(self._ports)

            self.handle_log(logging.DEBUG, f"[SER            ]: Found {num_ports} available serial ports.")
            for port in self._ports:
                self.handle_log(
                    logging.DEBUG, 
                    f"[SER            ]: Port: {port[0]}, Desc: {port[1]}, HWID: {port[2]}"
            )

            return num_ports

        except Exception as e:
            self.handle_log(
                logging.ERROR, 
                f"[SER            ]: Error scanning ports - {e}"
            )
            self._ports = []  # Ensure `_ports` is empty on failure
            return 0
        
    def open(self, port: str, baud: int, eol: bytes, timeout: float, esp_reset: bool) -> bool:
        """ 
        Opens the specified serial port.
        """
        try:
            self.ser = sp(
                port = port,                    # The serial device
                baudrate = baud,                # Standard baud rate (115200 is common)
                bytesize = EIGHTBITS,           # Most common option
                parity = PARITY_NONE,           # No parity bit
                stopbits = STOPBITS_ONE,        # Standard stop bit
                timeout = timeout,              # Timeout for read operations
                write_timeout = timeout,        # Timeout for write operations
                inter_byte_timeout = None,      # Disable inter-character timeout
                rtscts = False,                 # No RTS/CTS handshaking
                dsrdtr = False,                 # No DSR/DTR signaling
                xonxoff = False                 # No software flow control
            )
        except SerialException as e:
            self.handle_log(
                logging.ERROR, 
                f"[SER            ]: SerialException: {e}; Failed to open {port} with baud {baud}."
            )
            self._ser_open = False
            self.ser = None
            self._port = ""
            return False
        except OSError as e:
            self.handle_log(
                logging.ERROR,
                f"[SER            ]: OSError: {e}; Failed to access port {port}."
            )
            self._ser_open = False
            self.ser = None
            self._port = ""
            return False

        try:
            self.ser.set_buffer_size(rx_size=16384, tx_size=16384)
        except Exception as e:
            self.handle_log(
                logging.ERROR, 
                f"[SER            ]: Error setting buffer size - {e}"
            )

        # If no exceptions occurred, the port was successfully opened
        self.handle_log(
            logging.INFO, 
            f"[SER            ]: Opened {port} at {baud} baud, timeout {timeout}."
        )

        # Mark serial as open
        self._ser_open  = True
        self._baud      = baud
        self._port      = port
        self._timeout   = timeout
        self._eol       = eol
        self._leneol    = len(eol)
        self._esp_reset = esp_reset

        # Perform ESP reset after the port is open
        if esp_reset:
            try:
                self.espHardReset()
                self.handle_log(logging.INFO, f"[SER            ]: {port} - ESP hard reset completed.")
            except Exception as e:
                self.handle_log(logging.ERROR, f"[SER            ]: {port} - ESP reset failed: {e}.")

        # Clear buffers
        try:
            self.ser.reset_input_buffer()
        except Exception as e:
            self.handle_log(logging.ERROR, f"[SER            ]: Failed to clear input buffer: {e}")

        try:
            self.ser.reset_output_buffer()
        except Exception as e:
            self.handle_log(logging.ERROR, f"[SER            ]: Failed to clear output buffer: {e}")

        # Reset statistics and internal buffers
        self.totalCharsReceived = 0
        self.totalCharsSent     = 0
        self.bufferIn.clear()

        return True


    def close(self):
        """
        Closes the serial port and resets attributes.
        """
        if self.ser and self._ser_open:
            try:
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
                self.ser.close()
                self.handle_log(logging.INFO, "[SER            ]: Serial port closed.")
            except Exception as e:
                self.handle_log(logging.ERROR, f"[SER            ]: Failed to close port - {e}")

        self._ser_open = False
        self._port = None

    def changeport(self, port: str, baud: int, eol: bytes, timeout: float, esp_reset: bool):
        """
        switch to different port
        """
        self.close()
        self.open(
            port = port, 
            baud = baud, 
            eol = eol, 
            timeout = timeout, 
            esp_reset = esp_reset
        )  # opening the port also clears its buffers
        self.handle_log(
            logging.INFO,
            f"[SER            ]: changed port to {port} with baud {baud} and eol {repr(eol)}"
        )

    def read(self) -> bytes:
        """
        Reads all bytes from the serial buffer.
        If the buffer is empty, returns an empty bytes object.
        """
        startTime = time.perf_counter()

        if not self._ser_open:
            self.handle_log(logging.ERROR, "[SER            ]: serial port not available.")
            return b""

        bytes_to_read = self.ser.in_waiting
        if bytes_to_read == 0:
            self.handle_log(logging.DEBUG, 
                f"[SER            ]: end of read, buffer empty in {1000 * (time.perf_counter() - startTime):.2f} ms."
            )
            return b""

        # Read available bytes
        self.bufferIn.extend(self.ser.read(bytes_to_read))
        byte_array = bytes(self.bufferIn)
        self.bufferIn.clear()
        self.totalCharsReceived += bytes_to_read

        # Log time taken to read
        self.handle_log(logging.DEBUG,
            f"[SER            ]: read: read {bytes_to_read} bytes in {1000 * (time.perf_counter() - startTime):.2f} ms."
        )

        return byte_array


    def readline(self) -> bytes:
        """
        Reads one line of text from the serial buffer.
        Handles partial lines when line termination is not found in buffer.
        """
        startTime = time.perf_counter()

        if not self._ser_open:
            self.handle_log(logging.ERROR, "[SER            ]: serial port not available.")
            return b""

        try:
            # Read until EOL
            _line = self.ser.read_until(self._eol)  
            # If times out _line includes whatever was read before timeout
            # If completed without timeout _line includes delimiter
            self.totalCharsReceived += len(_line)

            if not _line:  # No data received, return immediately
                return b""
        
            if _line.endswith(self._eol):
                # Merge previous bufferIn with the new full line
                self.bufferIn.extend(_line[:-self._leneol])
                line = bytes(self.bufferIn)
                self.bufferIn.clear()

            else:
                self.bufferIn.extend(_line)
                line = b""

        except Exception as e:
            self.handle_log(
                logging.ERROR, 
                f"[SER            ]: could not read from port - {e}"
            )
            return b""

        endTime = time.perf_counter()
        self.handle_log(
            logging.DEBUG,
            f"[SER            ]: read line: read {len(line)} bytes in {1000 * (endTime - startTime):.2f} ms."
        )

        return line


    def readlines(self) -> list:
        """
        Reads the serial buffer and converts it into lines of text.
        """

        startTime = time.perf_counter()

        lines = []

        if not self._ser_open:
            self.handle_log(logging.ERROR,"[SER            ]: serial port not available.")
            return []
        
        try:
            bytes_to_read = self.ser.in_waiting

            if bytes_to_read == 0:
                return []  # No data available
                    
            self.bufferIn.extend(self.ser.read(bytes_to_read))
            self.totalCharsReceived += bytes_to_read

            # Delimiter found, split byte array into lines
            lines = self.bufferIn.split(self._eol)

            if lines[-1] == b"":
                # No partial line, clear the buffer
                lines.pop()
                self.bufferIn.clear()
            else:
                # Partial line detected, store it for the next read
                self.bufferIn[:] = lines.pop() 

            endTime = time.perf_counter()
            self.handle_log(
                logging.DEBUG,
                f"[SER            ]: read lines: {bytes_to_read} bytes / {len(lines)} lines in {1000 * (endTime - startTime):.2f} ms."
            )

            return lines

        except Exception as e:
            self.handle_log(
                logging.ERROR, 
                f"[SER            ]: could not read from port - {e}"
            )
            return []

    def write(self, byte_array: bytes) -> int:
        """ 
        Sends an array of bytes over the serial port.
        Returns the number of bytes written, or 0 if an error occurs.
        """

        if not self._ser_open:
            self.handle_log(logging.ERROR, "[SER write]: serial port not available.")
            return 0
        
        l = 0 

        try:
            l = self.ser.write(byte_array)
            self.totalCharsSent += l

            if DEBUGSERIAL:
                l_ba = len(byte_array)
                decimal_values = " ".join(str(byte) for byte in byte_array)
                self.handle_log(
                    logging.DEBUG,
                    f"[SER write]: wrote {l} of {l_ba} bytes. {decimal_values}"
                )

        except Exception as e:
            self.handle_log(
                logging.ERROR,
                f"[SER write]: failed to write with timeout {self.timeout}. Error: {e}"
            )
            return 0

        return l

    def writeline(self, byte_array: bytes) -> int:
        """ 
        sends an array of bytes and adds eol 
        """
        if self._ser_open:
            try:
                l = self.ser.write(byte_array + self._eol)
                self.totalCharsSent += l
                if DEBUGSERIAL:
                    l_ba = len(byte_array)
                    l_eol = len(self._eol)
                    decimal_values = " ".join(str(byte) for byte in byte_array)
                    self.handle_log(
                        logging.DEBUG,
                        f"[SER writeline]: wrote {l} of {l_ba}+{l_eol} bytes. {decimal_values}"
                    )
                return l
            except:
                self.handle_log(
                    logging.ERROR,
                    f"[SER writeline]: failed to write with timeout {self.timeout}."
                )
                return l
        else:
            self.handle_log(
                logging.ERROR,
                f"[SER writeline]: serial port not available."
            )
            return 0

    def writeline(self, byte_array: bytes) -> int:
        """ 
        Sends an array of bytes and appends EOL before writing to the serial port.
        Returns the number of bytes written, or 0 if an error occurs.
        """
        if not self._ser_open:
            self.handle_log(logging.ERROR, "[SER writeline]: serial port not available.")
            return 0

        l = 0

        try:
            # Append EOL and send data
            full_message = byte_array + self._eol
            l = self.ser.write(full_message)
            self.totalCharsSent += l

            if DEBUGSERIAL:
                l_ba = len(byte_array)
                l_eol = len(self._eol)
                decimal_values = " ".join(str(byte) for byte in byte_array)
                self.handle_log(
                    logging.DEBUG,
                    f"[SER writeline]: wrote {l} of {l_ba}+{l_eol} bytes. {decimal_values}"
                )

        except Exception as e:
            self.handle_log(
                logging.ERROR, 
                f"[SER writeline]: failed to write - {e}"
            )
            return 0 

        return l

    def writelines(self, lines: list) -> int:
        """ 
        sends several lines of text and appends eol to each line
        """
        byte_array = self._eol.join(line for line in lines)
        if self._ser_open:
            try:
                l = self.ser.write(byte_array)
                self.totalCharsSent += l
                if DEBUGSERIAL:
                    self.handle_log(
                        logging.DEBUG,
                        f"[SER            ]: wrote {l} chars."
                    )
                return l
            except:
                self.handle_log(
                    logging.ERROR,
                    f"[SER            ]: failed to write with timeout {self.timeout}."
                )
                return l
        else:
            self.handle_log(
                logging.ERROR,
                f"[SER            ]: serial port not available."
            )
            return 0

    def writelines(self, lines: list) -> int:
        """ 
        Sends several lines of text and appends `self._eol` to each line before writing.
        Returns the total number of bytes written, or 0 if an error occurs.
        """
        if not self._ser_open:
            self.handle_log(logging.ERROR, "[SER writelines]: serial port not available.")
            return 0 

        l = 0

        try:
            # Join lines with EOL
            byte_array = b"".join([line + self._eol for line in lines])
            
            # Write data to serial port
            l = self.ser.write(byte_array)
            self.totalCharsSent += l

            if DEBUGSERIAL:
                decimal_values = " | ".join([line.decode(errors='ignore') for line in lines])
                self.handle_log(
                    logging.DEBUG,
                    f"[SER writelines]: wrote {l} chars. Data: {decimal_values}"
                )

        except Exception as e:
            self.handle_log(
                logging.ERROR, 
                f"[SER writelines]: failed to write - {e}"
            )
            return 0 

        return l

    def avail(self) -> int:
        """ 
        is there data in the serial receiving buffer? 
        """
        if self._ser_open:
            return self.ser.in_waiting
        else:
            return -1

    def clear(self):
        """
        clear serial buffers
        we want to clear not flush
        """
        if self._ser_open:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            self.bufferIn.clear()
            self.totalCharsReceived = 0
            self.totalCharsSent = 0
            
    def _setDTR(self, state: bool):
        """ 
        Sets the DTR (Data Terminal Ready) signal. 
        """
        if self.ser is None:
            self.handle_log(logging.WARNING, "[ESP Reset]: Serial port not initialized.")
            return

        try:
            self.ser.setDTR(state)
            self.handle_log(logging.DEBUG, f"[ESP Reset]: DTR set to {'HIGH' if state else 'LOW'}.")
        except SerialException as e:
            self.handle_log(logging.ERROR, f"[ESP Reset]: Failed to set DTR - {e}")


    def _setRTS(self, state: bool):
        """
        Sets the RTS (Request To Send) signal.
        Windows Workaround: Forces an update by toggling DTR.
        """
        if self.ser is None:
            self.handle_log(logging.WARNING, "[ESP Reset]: Serial port not initialized.")
            return

        try:
            self.ser.setRTS(state)
            self.ser.setDTR(self.ser.dtr)  # Windows workaround
            self.handle_log(logging.DEBUG, f"[ESP Reset]: RTS set to {'HIGH' if state else 'LOW'}.")
        except SerialException as e:
            self.handle_log(logging.ERROR, f"[ESP Reset]: Failed to set RTS - {e}")

    def _setDTRandRTS(self, dtr: bool = False, rts: bool = False):
        """
        Sets both DTR and RTS at the same time (UNIX only).
        """
        if self.ser is None:
            self.handle_log(logging.WARNING, "[ESP Reset]: Serial port not initialized.")
            return

        if platform.system() == ("Windows"):
            self.handle_log(logging.ERROR, "[ESP Reset]: _setDTRandRTS is not supported on Windows.")
            return

        try:
            status = struct.unpack("I", fcntl.ioctl(self.ser.fileno(), TIOCMGET, struct.pack("I", 0)))[0]
            status = (status | TIOCM_DTR) if dtr else (status & ~TIOCM_DTR)
            status = (status | TIOCM_RTS) if rts else (status & ~TIOCM_RTS)
            fcntl.ioctl(self.ser.fileno(), TIOCMSET, struct.pack("I", status))

            self.handle_log(logging.DEBUG, f"[ESP Reset]: DTR={'HIGH' if dtr else 'LOW'}, RTS={'HIGH' if rts else 'LOW'}.")
        except Exception as e:
            self.handle_log(logging.ERROR, f"[ESP Reset]: Failed to set DTR/RTS - {e}")

    # Sparkfun ESP32 Thing Plus Schematic Notes:
    #
    # - If DTR is LOW, toggling RTS from HIGH to LOW resets to run mode
    # - If RTS is HIGH, toggling DTR from LOW to HIGH resets to boot loader
    #
    # DTR and RTS are active low signals
    # DTR is connected to GPIO_0
    # RTS is connected to EN
    # GPIO0, when low during reset enters firmware upload mode
    # EN / CHIP_PU, when high normal operation, when driven low and released high resets the chip 

    def espClassicReset_Bootloader(self):
        """
        Classic ESP reset sequence to enter bootloader mode.
        """
        self.handle_log(logging.INFO, "[ESP Reset]: Starting Classic Reset (Bootloader Mode).")

        self._setDTR(False)  # IO0 = HIGH
        self._setRTS(True)   # EN = LOW (Reset active)
        time.sleep(0.1)
        self._setDTR(True)   # IO0 = LOW
        self._setRTS(False)  # EN = HIGH (Reset released)
        time.sleep(self.reset_delay)
        self._setDTR(False)  # IO0 = HIGH (Bootloader mode)

    def espUnixReset_Bootloader(self):
        """
        UNIX-only ESP reset sequence setting DTR and RTS lines together.
        """

        if platform.system() == "Windows":
            self.handle_log(logging.ERROR, "[ESP Reset]: espUnixReset_Bootloader is not supported on Windows.")
            return

        self.handle_log(logging.INFO, "[ESP Reset]: Starting UNIX Reset (Bootloader Mode).")

        self._setDTRandRTS(False, False)
        self._setDTRandRTS(True, True)
        self._setDTRandRTS(False, True)  # IO0 = HIGH, EN = LOW (Reset active)
        time.sleep(0.1)
        self._setDTRandRTS(True, False)  # IO0 = LOW, EN = HIGH (Reset released)
        time.sleep(self.reset_delay)
        self._setDTRandRTS(False, False) # IO0 = HIGH, Reset complete
        self._setDTR(False)  


    def espHardReset(self):
        """
        Reset sequence for hard resetting the chip.
        Can be used to reset out of the bootloader or to restart a running app.
        If DTR is LOW, toggling RTS from HIGH to LOW resets to run mode
        """

        self.handle_log(logging.INFO, "[ESP Reset]: Starting Hard Reset.")

        self._setDTR(False)  # IO0 = HIGH
        self._setRTS(False)  # EN = HIGH
        time.sleep(0.2)
        self._setRTS(True)   # EN = LOW (Reset active)
        time.sleep(0.2)
        self._setRTS(False)  # EN = HIGH (Reset released)
        time.sleep(0.2)

    # Setting and reading internal variables
    ########################################################################################

    @property
    def ports(self):
        """ returns list of ports """
        return self._ports

    @property
    def baudrates(self):
        """ 
        Returns a list of available baudrates. 
        Adds higher baudrates if the highest baudrate is <= 115200.
        """
        if not self._ser_open:
            return (DEFAULT_BAUDRATE,)

        if hasattr(self.ser, "BAUDRATES"):
            baud_list = list(self.ser.BAUDRATES)
            if max(baud_list) <= 115200:
                baud_list.extend([
                    230400, 250000, 460800, 500000, 921600, 1000000, 2000000
                ])
            return tuple(baud_list)
        
        return (DEFAULT_BAUDRATE,)

    @property
    def connected(self) -> bool:
        """ 
        Returns `True` if the serial port is open, otherwise `False`. 
        """
        return bool(self._ser_open)

    @property
    def port(self) -> str:
        """ 
        Returns the currently connected port as a string. 
        If the port is not open, returns an empty string. 
        """
        return self._port if self._ser_open else ""

    @port.setter
    def port(self, val: str):
        """ 
        Sets the serial port. 
        """
        if not val:
            self.handle_log(logging.WARNING, "[SER            ]: No port given.")
            return

        # Attempt to change the port
        if self.changeport(val, self.baud, self.eol, self.timeout, self.esp_reset):
            self._port = val 
            self.handle_log(logging.DEBUG, f"[SER            ]: Port changed to: {val}.")
        else:
            self.handle_log(logging.ERROR, f"[SER            ]: Failed to open port {val}.")

    @property
    def baud(self) -> int:
        """ 
        Returns the current serial baudrate. 
        If the port is closed, returns `None` instead of `-1`.
        """
        return self._baud if self._ser_open else None

    @baud.setter
    def baud(self, val: int):
        """ 
        Sets the serial baud rate. 
        """
        if not val or val <= 0:
            self.handle_log(
                logging.WARNING, 
                f"[SER            ]: baudrate not changed to {val}."
            )
            return

        if not self._ser_open:
            self.handle_log(logging.ERROR, "[SER            ]: failed to set baudrate, serial port not open!")
            return

        try:
            self.ser.baudrate = val
            self._baud = self.ser.baudrate  # Verify

            if self._baud == val:
                self.handle_log(logging.DEBUG, f"[SER            ]: baudrate: {val}.")
                # Clear buffers if baudrate update is successful
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
            else:
                self.handle_log(
                    logging.ERROR, 
                    f"[SER            ]: failed to set baudrate to {val}."
                )
        
        except Exception as e:
            self.handle_log(
                logging.ERROR, 
                f"[SER            ]: Error setting baudrate - {e}"
            )

    @property
    def eol(self):
        """ 
        Returns the current line termination character(s). 
        """
        return self._eol

    @eol.setter
    def eol(self, val):
        """ 
        Sets the end-of-line (EOL) termination sequence for serial communication. 
        """
        if not isinstance(val, (str, bytes, bytearray)):
            self.handle_log(logging.WARNING, "[SER            ]: EOL not changed, must provide a string or bytes.")
            return

        self._eol = val.encode() if isinstance(val, str) else val
        self._leneol = len(self._eol)  # Update length of EOL

        self.handle_log(
            logging.DEBUG, 
            f"[SER            ]: EOL set to: {repr(val)}"
        )

    @property
    def esp_reset(self):
        """ returns current line termination """
        return self._esp_reset
        
    @esp_reset.setter
    def esp_reset(self, val: bool):
        """ 
        Sets the ESP reset flag.
        """
        if not isinstance(val, bool): 
            self.handle_log(logging.WARNING, "[SER            ]: ESP reset not changed, must be True or False.")
            return

        self._esp_reset = val
        self.handle_log(
            logging.DEBUG, 
            f"[SER            ]: ESP reset set to: {val}"
        )
        
    @property
    def timeout(self):
        """ returns current serial timeout """
        return self._timeout

#####################################################################################
# Testing
#####################################################################################

if __name__ == "__main__":
    # not implemented
    pass