##########################################################################################################################################        
# QT Serial Helper
##########################################################################################################################################        
#
# QSerialUI:        Controller  - Interface to GUI, runs in main thread.
# QSerial:          Model       - Functions running in separate thread, communication through signals and slots.
#
# USBMonitorWorker:         Monitor USB device insertion/removal on both Windows and Linux
# IncompleteHTMLTracker:    Streaming HTML parser that detects incomplete HTML
#
# This code is maintained by Urs Utzinger
##########################################################################################################################################        

########################################################################################
# Debug
DEBUGSERIAL  = False  # enable/disable low level serial debugging
PROFILEME    = True   # calculate profiling information
DEBUGTHREADS = False  # enable/disable thread debugging
FORCE_USB_POLLING = True  # force USB polling on Linux and Darwin, currently event based method does not work for me

#
# Constants
########################################################################################
DEFAULT_BAUDRATE       = 2000000     # default baud rate for serial port
DEFAULT_LINETERMINATOR = b""         # default line termination
MAX_TEXTBROWSER_LENGTH = 5000        # max number of lines in display window 
RECEIVER_FINISHCOUNT   = 10          # [times] If we encountered a timeout 10 times we slow down serial polling
SERIAL_BUFFER_SIZE     = 4096        # [bytes] size of the serial buffer, CAN NOT CHANGE on Linux and Darwin
FLUSH_INTERVAL_MS      = 100         # [ms] 10 Hz update of the text display (received data is buffered)
USB_POLLING_INTERVAL   = 300         # [ms] interval to check for USB device insertion/removal
########################################################################################

import time
import logging
import re
import platform
import textwrap

from pathlib import Path
from html.parser import HTMLParser
from difflib import SequenceMatcher

try: 
    from PyQt6.QtCore import (
        QObject, QTimer, QThread, pyqtSignal, pyqtSlot, QStandardPaths, 
        QMetaObject, QByteArray, QIODevice, pyqtBoundSignal, QCoreApplication, 
        QEventLoop
    )
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QTextCursor, QTextOption
    from PyQt6.QtWidgets import QFileDialog, QMessageBox, QSlider, QLineEdit
    from PyQt6.QtSerialPort import QSerialPort, QSerialPortInfo
    hasQt6 = True
except:
    from PyQt5.QtCore import (
        QObject, QTimer, QThread, pyqtSignal, pyqtSlot, QStandardPaths, 
        QMetaObject, QByteArray, QIODevice, pyqtBoundSignal, QCoreApplication, 
        QEventLoop
    )
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QTextCursor, QTextOption
    from PyQt5.QtWidgets import QFileDialog, QMessageBox, QSlider, QLineEdit
    from PyQt5.QtSerialPort import QSerialPort, QSerialPortInfo
    hasQt6 = False

##########################################################################################################################################        
# Support Functions and Classes
##########################################################################################################################################        

def clip_value(value, min_value, max_value):
    return max(min_value, min(value, max_value))

class IncompleteHTMLTracker(HTMLParser):
    """
    A streaming HTML parser that detects incomplete HTML.
    Returns:
      - `valid_html`: Fully completed HTML that can be safely displayed.
      - `incomplete_html`: Remaining unprocessed HTML that needs more data.
    """

    def __init__(self):
        super().__init__()
        self.tag_stack = {}  # Dictionary to track open tags {tag_name: count}
        self.incomplete_html_buffer = ""  # Store leftover HTML for next chunk
        self.valid_html_buffer = ""  # Buffer for confirmed valid HTML

        # Precompile regex patterns for efficiency
        self.tag_start_pattern = re.compile(r"<([a-zA-Z0-9]+)(\s[^<>]*)?>")  # Matches opening tags with optional attributes
        self.tag_end_pattern = re.compile(r"</([a-zA-Z0-9]+)>")  # Matches closing tags

        self.self_closing_tags = {"br", "img", "hr", "input", "meta", "link"}  # Tags that don't require closing

    def handle_starttag(self, tag, attrs) -> None:
        """Track opening tags, unless they are self-closing."""
        if tag not in self.self_closing_tags:
            self.tag_stack[tag] = self.tag_stack.get(tag, 0) + 1  # Increment count
            # logging.debug(f"Opening tag detected: <{tag}> (Total open: {self.tag_stack[tag]})")

    def handle_endtag(self, tag) -> None:
        """Track closing tags and remove from stack when matched."""
        if tag in self.tag_stack:
            self.tag_stack[tag] -= 1  # Decrement count
            # logging.debug(f"Closing tag detected: </{tag}> (Remaining open: {self.tag_stack[tag]})")
            if self.tag_stack[tag] == 0:
                del self.tag_stack[tag]  # Remove fully closed tag

    def detect_incomplete_html(self, html: str) -> None:
        """
        Processes incoming HTML and separates:
        - `valid_html`: Fully closed and valid HTML content.
        - `incomplete_html`: Content waiting for more data to be completed.
        """
        # logging.debug(f"Received HTML chunk:\n{html}")

        # Append new HTML data to any previously incomplete content
        self.incomplete_html_buffer += html  
        self.valid_html_buffer = ""  # Reset valid buffer

        # Try parsing the entire buffer
        try:
            self.feed(self.incomplete_html_buffer)

            if not self.tag_stack:
                # If all tags are closed, the buffer is fully valid
                self.valid_html_buffer = self.incomplete_html_buffer
                self.incomplete_html_buffer = ""  # Reset after processing
                # logging.debug(f"All tags closed. Valid HTML:\n{self.valid_html_buffer}")
                return self.valid_html_buffer, ""
        except Exception as e:
            # logging.error(f"HTML Parsing Error: {e}")  # Log parsing errors
            pass

        # Detect where last fully valid HTML ends
        last_valid_position = self._find_last_complete_tag(self.incomplete_html_buffer)

        # Separate valid vs. incomplete parts
        self.valid_html_buffer = self.incomplete_html_buffer[:last_valid_position]
        self.incomplete_html_buffer = self.incomplete_html_buffer[last_valid_position:]

        # logging.debug(f"Valid HTML Extracted:\n{self.valid_html_buffer}")
        # logging.debug(f"Incomplete HTML Stored:\n{self.incomplete_html_buffer}")

        return self.valid_html_buffer, self.incomplete_html_buffer

    def _find_last_complete_tag(self, html: str) -> None:
        """
        Finds the last fully completed tag position in the string.
        Ensures that incomplete start tags (like <p class="...) are not included in valid HTML.
        """
        logging.debug("Scanning for last fully closed tag...")
        last_valid_pos = 0
        open_tags = {}

        # Scan the HTML chunk for opening tags
        for match in self.tag_start_pattern.finditer(html):
            tag_name = match.group(1)
            tag_pos = match.start()

            if tag_name in self.self_closing_tags:
                continue  # Ignore self-closing tags

            open_tags[tag_name] = open_tags.get(tag_name, 0) + 1  # Increment count
            # logging.debug(f"Unmatched opening tag: <{tag_name}> at position {tag_pos}")

        # Scan the HTML chunk for closing tags
        for match in self.tag_end_pattern.finditer(html):
            tag_name = match.group(1)
            tag_pos = match.end()

            if tag_name in open_tags:
                open_tags[tag_name] -= 1
                # logging.debug(f"Matched closing tag: </{tag_name}> at position {tag_pos}")
                if open_tags[tag_name] == 0:
                    del open_tags[tag_name]

            # If no unmatched open tags, update last valid position
            if not open_tags:
                last_valid_pos = tag_pos

        # logging.debug(f"Last valid tag found at position {last_valid_pos}")
        return last_valid_pos

##########################################################################################################################################        
##########################################################################################################################################        
#
# Serial Port Monitor
# 
# Monitors USB device insertion and removal on both Windows and Linux
# Emits signal when insertion/removal event occurs
# 
##########################################################################################################################################        
##########################################################################################################################################        

class USBMonitorWorker(QObject):
    usb_event_detected = pyqtSignal(str)  # Signal to communicate with the main thread
    finished           = pyqtSignal() 
    logSignal          = pyqtSignal(int, str) 

    def __init__(self):
        super().__init__()

        self.running = False
        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"
        self.mtoc_monitor_usb = 0

    @pyqtSlot()
    def run(self):

        if DEBUGTHREADS:
            import debugpy
            debugpy.debug_this_thread()

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"

        self.running = True

        os_type = platform.system()
        if os_type == "Linux" or os_type == "Darwin":
            self.monitor_usb_linux()
        elif os_type == "Windows":
            self.monitor_usb_windows()
        else:
            self.handle_log(logging.ERROR, f"unsupported operating system: {os_type}")

    def handle_log(self, level: int, message: str) -> None:
        """Emit the log signal with a level and message."""
        self.logSignal.emit(level, message)

    def monitor_usb_linux(self) -> None:
        """
        USB device insertion/removal monitoring on Linux
        """

        import pyudev

        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by(subsystem='tty')

        if FORCE_USB_POLLING:

            self.monitor_usb_linux_polling(monitor)

        else:

            def device_event(action, device):

                if self.running is False:
                    return

                try:
                    if PROFILEME:
                        tic = time.perf_counter()

                    device_node = device.device_node
                    if action == 'add':
                        self.usb_event_detected.emit(f"USB device added: {device_node}")
                    elif action == 'remove':
                        self.usb_event_detected.emit(f"USB device removed: {device_node}")

                    if PROFILEME:
                        toc = time.perf_counter()
                        self.mtoc_monitor_usb = max((toc - tic), self.mtoc_monitor_usb)

                except Exception as e:
                    self.handle_log(logging.ERROR, f"[{self.thread_id}]: device event error: {e}")

            # Start observer in the same thread
            try:
                self.observer = pyudev.MonitorObserver(monitor, callback=device_event, name='usb-monitor')
                self.observer.daemon = True
                self.observer.start()

                self.handle_log(logging.INFO, f"[{self.thread_id}]: USB MonitorObserver started.")
                while self.running:
                    QThread.msleep(USB_POLLING_INTERVAL)  # Keep the thread alive

            except Exception as e:
                self.handle_log(
                    logging.ERROR, 
                    f"[{self.thread_id}]: failed to start USB MonitorObserver: {e}"
                    )

        self.finished.emit()

    def monitor_usb_linux_polling(self, monitor) -> None:
        """
        Fallback polling method for USB events on Linux
        """
        for device in iter(lambda: monitor.poll(timeout=USB_POLLING_INTERVAL), None):
            if not self.running:
                break

            if PROFILEME:
                tic = time.perf_counter()

            try:
                action = device.action
                device_node = device.device_node

                if action == 'add':
                    self.usb_event_detected.emit(f"USB device added: {device_node}")
                elif action == 'remove':
                    self.usb_event_detected.emit(f"USB device removed: {device_node}")

                if PROFILEME:
                    toc = time.perf_counter()
                    self.mtoc_monitor_usb = max((toc - tic), self.mtoc_monitor_usb)

            except Exception as e:
                self.handle_log(logging.ERROR, f"[{self.thread_id}]: fallback poll error: {e}")
                QThread.msleep(USB_POLLING_INTERVAL)

        self.finished.emit()
        
    def monitor_usb_windows(self) -> None:
        import wmi
        c = wmi.WMI()

        try:
            watchers = {
                "add": c.Win32_PnPEntity.watch_for(notification_type="Creation", delay_secs=1),
                "remove": c.Win32_PnPEntity.watch_for(notification_type="Deletion", delay_secs=1)
            }
        except Exception as e:
            self.handle_log(logging.ERROR, f"[{self.thread_id}]: error setting up USB monitor: {e}")
            return

        while self.running:
            if PROFILEME:
                tic = time.perf_counter()

            try:
                for action, watcher in watchers.items():
                    if not self.running:  # Early exit check
                        break

                    event = watcher(timeout_ms=500)  # Wait for an event
                    if event and ('USB' in event.Description or 'COM' in event.Name):
                        message = f"USB device {'added' if action == 'add' else 'removed'}: {event.Description} ({event.Name})"
                        self.usb_event_detected.emit(message)

            except wmi.x_wmi_timed_out:
                continue  # No event, continue waiting

            except Exception as e:
                self.handle_log(logging.ERROR, f"[{self.thread_id}]: error: {e}")

            if PROFILEME:
                toc = time.perf_counter()
                self.mtoc_monitor_usb = max((toc - tic), self.mtoc_monitor_usb)  # End performance tracking

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

        if hasattr(self, "observer"):
            try:
                self.observer.stop()
            except Exception:
                pass

    @pyqtSlot()
    def handle_mtoc(self) -> None:
        """Emit the mtoc signal with a function name and time in a single log call."""
        log_message = textwrap.dedent(f"""
            USB Monitor
            =============================================================
            monitor_usb             took {self.mtoc_monitor_usb*1000:.2f} ms.
        """)
        self.handle_log(logging.INFO, log_message)

##########################################################################################################################################        
##########################################################################################################################################        
#
# QSerial interaction with Graphical User Interface
#
# This section contains routines that can not be moved to a separate thread because it interacts with the QT User Interface.
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
        closePortRequest                 request that QSerial closes current port
        sendTextRequest                  request that provided text is transmitted over serial TX
        sendLineRequest                  request that provided line of text is transmitted over serial TX
        sendLinesRequest                 request that provided lines of text are transmitted over serial TX
        sendFileRequest                  request that provided file is transmitted over serial TX
        setupReceiverRequest             request that QTimer for receiver and QTimer for throughput is created
        startReceiverRequest             request that QTimer for receiver is started
        stopReceiverRequest              request that QTimer for receiver is stopped
        startThroughputRequest           request that QTimer for throughput is started
        stopThroughputRequest            request that QTimer for throughput is stopped
        serialStatusRequest              request that QSerial reports current port, baudrate, line termination, encoding, timeout
        finishWorkerRequest              request that QSerial worker is finished
        closePortRequest                 request that QSerial closes current port
        displayingRunning                request that QSerial is running and want to display text in terminal

    Slots (functions available to respond to external signals)
        on_logSignal(int, str)               pickup log signal from QSerial
        on_carriageReturnPressed             transmit text from UI to serial TX line
        on_upArrowPressed                    recall previous line of text from serial TX line buffer
        on_downArrowPressed                  recall next line of text from serial TX line buffer
        on_pushButton_SendFile               send file to serial port
        on_pushButton_SerialClearOutput      clear the text display window
        on_pushButton_SerialStartStop        start/stop serial text display and throughput timer
        on_pushButton_SerialSave             save text from display window into text file
        on_pushButton_SerialScan             update serial port list
        on_pushButton_SerialOpenClose        open/close serial port
        on_SerialRecord                      start/stop recording of serial data
        on_comboBoxDropDown_SerialPorts      user selected a new port on the drop down list
        on_comboBoxDropDown_BaudRates        user selected a different baudrate on drop down list
        on_comboBoxDropDown_LineTermination  user selected a different line termination from drop down menu
        
        on_HistoryLineEditChanged
        on_HistoryHorizontalSliderChanged
        ---- 
        on_serialStatusReady                 pickup QSerial status on port, baudrate, line termination, timeout, connected
        on_newPortListReady                  pickup new list of serial ports (ports,portNames, portHWID)
        on_newBaudListReady(list)            pickup new list of baudrates
        on_receivedData(bytes)               pickup text from serial port
        on_flushByteArrayBuffer()            push byte array buffer to text display
        on_receivedLines(list)               pickup lines of text from serial port
        on_flushLinesBuffer()                push lines buffer to text display
        on_serialWorkerStateChanged(bool)    pickup running state of serial worker
        on_throughputReady(int, int)         pickup throughput data from QSerial
        on_usb_event_detected(str)           pickup USB device insertion or removal


    Functions
        handle_log(int, str)                 emit log signal with level and message
        handle_mtoc()                        emit mtoc signal with function name and time in a single log call
        handle_usb_event_detected(str)       emit usb event signal with message
        cleanup                              cleanup the QSerialUI

    """

    # Signals
    ########################################################################################

    scanPortsRequest             = pyqtSignal()                                            # port scan
    scanBaudRatesRequest         = pyqtSignal()                                            # baudrates scan
    changePortRequest            = pyqtSignal(str, int)                                    # port and baudrate to change
    changeBaudRequest            = pyqtSignal(int)                                         # request serial baud rate to change
    changeLineTerminationRequest = pyqtSignal(bytes)                                       # request line termination to change
    sendTextRequest              = pyqtSignal(bytes)                                       # request to transmit text to TX
    sendLineRequest              = pyqtSignal(bytes)                                       # request to transmit one line of text to TX
    sendLinesRequest             = pyqtSignal(list)                                        # request to transmit lines of text to TX
    setupReceiverRequest         = pyqtSignal()                                            # request to setup receiver and throughput timer
    startReceiverRequest         = pyqtSignal()                                            # start serial receiver, expecting text
    stopReceiverRequest          = pyqtSignal()                                            # stop serial receiver
    startThroughputRequest       = pyqtSignal()                                            # start timer to report throughput
    stopThroughputRequest        = pyqtSignal()                                            # stop timer to report throughput
    serialStatusRequest          = pyqtSignal()                                            # request serial port and baudrate status
    finishWorkerRequest          = pyqtSignal()                                            # request worker to finish
    closePortRequest             = pyqtSignal()                                            # close the current serial Port
    sendFileRequest              = pyqtSignal(str)                                         # request to open file and send over serial port
    displayingRunning            = pyqtSignal(bool)                                        # signal to indicate that serial monitor is running
    toggleDTRRequest             = pyqtSignal()                                            # request to toggle DTR
    espResetRequest              = pyqtSignal()                                            # request to reset ESP
             
    # Init
    ########################################################################################

    def __init__(self, parent=None, ui=None, worker=None, logger=None):

        super().__init__(parent)

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"

        # state variables, populated by service routines
        self.defaultBaudRate       = DEFAULT_BAUDRATE
        self.BaudRates             = []                                                    # e.g. (1200, 2400, 9600, 115200)
        self.serialPortHWIDs       = []                                                    # device specific identifier
        self.serialPortNames       = []                                                    # human readable
        self.serialPorts           = []                                                    # e.g. COM6
        self.serialPort            = ""                                                    # e.g. COM6
        self.serialPortHWID        = ""                                                    # e.g. USB VID:PID=1A86:7523 
        self.serialBaudRate        = DEFAULT_BAUDRATE                                      # e.g. 115200
        self.serialSendHistory     = []                                                    # previously sent text (e.g. commands)
        self.serialSendHistoryIndx = -1                                                    # init history
        self.lastNumReceived       = 0                                                     # init throughput            
        self.lastNumSent           = 0                                                     # init throughput
        self.rx                    = 0                                                     # init throughput
        self.tx                    = 0                                                     # init throughput 
        self.lastNumComputed       = time.perf_counter()                                   # init throughput time calculation
        self.receiverIsRunning     = False                                                 # keep track of worker state
        self.textLineTerminator    = DEFAULT_LINETERMINATOR                                # default line termination: none
        self.encoding              = "utf-8"                                               # default encoding
        self.serialTimeout         = 0                                                     # default timeout    
        self.isScrolling           = False                                                 # keep track of text display scrolling
        self.connected             = False                                                 # keep track of connection state

        # Backup for reconnection/device removal
        self.serialPort_backup     = ""
        self.serialPortHWID_backup = ""
        self.serialBaudRate_backup = DEFAULT_BAUDRATE
        self.awaitingReconnection  = False

        self.record                = False                                                 # record serial data
        self.recordingFileName     = ""
        self.recordingFile         = None

        # self.textBrowserLength     = MAX_TEXTBROWSER_LENGTH + 1

        self.byteArrayBuffer = bytearray()
        self.byteArrayBufferTimer = QTimer()
        self.byteArrayBufferTimer.setInterval(FLUSH_INTERVAL_MS)
        self.byteArrayBufferTimer.timeout.connect(self.flushByteArrayBuffer)

        self.linesBuffer = list()
        self.linesBufferTimer = QTimer()
        self.linesBufferTimer.setInterval(FLUSH_INTERVAL_MS)
        self.linesBufferTimer.timeout.connect(self.flushLinesBuffer)
        
        self.htmlBuffer = ""
        self.htmlBufferTimer = QTimer()
        self.htmlBufferTimer.setInterval(FLUSH_INTERVAL_MS)
        self.htmlBufferTimer.timeout.connect(self.flushHTMLBuffer)
        
        self.mtoc_on_newBaudListReady = 0
        self.mtoc_on_newPortListReady = 0
        self.mtoc_on_receivedData = 0
        self.mtoc_on_receivedLines = 0
        self.mtoc_on_throughputReady = 0
        self.mtoc_on_usb_event_detected = 0
        self.mtoc_on_serialStatusReady = 0

        self.mtoc_appendTextLines = 0 
        self.mtoc_appendText = 0
        self.mtoc_appendHtml = 0
        self.mtoc_clear = 0
        
        self.eol_dict = {
            "newline (\\n)"          : b"\n",
            "return (\\r)"           : b"\r",
            "newline return (\\n\\r)": b"\n\r",
            "return newline (\\r\\n)": b"\r\n",
            "none"                   : b""
        }
        self.eol_dict_inv = {v: k for k, v in self.eol_dict.items()}

        # setup logging delegation
        if logger is None:
            self.logger = logging.getLogger("QSerUI")
        else:
            self.logger = logger

        if parent is not None:
            # user parents logger if available
            if hasattr(parent, "handle_log"):
                self.handle_log = parent.handle_log

        if ui is None:
            self.handle_log(
                logging.ERROR,
                f"[{self.thread_id}]: need to have access to User Interface"
            )
        self.ui = ui

        if worker is None:
            self.handle_log(
                logging.ERROR,
                f"[{self.thread_id}]: need to have access to serial worker signals"
            )
        self.serialWorker = worker


        self.maxlines = 500
        self.horizontalSlider = self.ui.findChild(QSlider, "horizontalSlider_History")
        self.horizontalSlider.setMinimum(50)
        self.horizontalSlider.setMaximum(MAX_TEXTBROWSER_LENGTH)
        self.horizontalSlider.setValue(int(self.maxlines))
        self.lineEdit_History = self.ui.findChild(QLineEdit, "lineEdit_Vertical_History")
        self.lineEdit_History.setText(str(self.maxlines))

        # Modify text display window on serial text display
        self.ui.plainTextEdit_Text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)  # Always show scrollbar
        self.ui.plainTextEdit_Text.setReadOnly(True)  # Prevent user edits
        self.ui.plainTextEdit_Text.setWordWrapMode(QTextOption.NoWrap)  # No wrapping for better performance
        self.ui.plainTextEdit_Text.setUndoRedoEnabled(False)
        self.ui.plainTextEdit_Text.setMaximumBlockCount(self.maxlines) # no limit, will trim with timer

        # Modify scrollbar behavior
        scrollbar = self.ui.plainTextEdit_Text.verticalScrollBar()
        scrollbar.setSingleStep(1)  # Highest resolution for scrolling
        scrollbar.setPageStep(20)  # Defines how much a full page scroll moves
        scrollbar.setValue(scrollbar.maximum())  # Scroll to bottom 

        # Set cursor to end of text for auto scrolling
        textCursor = self.ui.plainTextEdit_Text.textCursor()
        self.move_op = QTextCursor.MoveOperation.End if hasQt6 else QTextCursor.End
        textCursor.movePosition(self.move_op)
        self.ui.plainTextEdit_Text.setTextCursor(textCursor)
        self.ui.plainTextEdit_Text.ensureCursorVisible()

        # Update UI elements

        # Disable closing serial port button
        self.ui.pushButton_SerialOpenClose.setText("Open")
        self.ui.pushButton_SerialOpenClose.setEnabled(False)
        # Disable start button in serial monitor and chart
        self.ui.pushButton_ChartStartStop.setEnabled(True)
        self.ui.pushButton_SerialStartStop.setEnabled(True)
        self.ui.pushButton_IndicatorStartStop.setEnabled(True)
        self.ui.lineEdit_Text.setEnabled(False)
        self.ui.pushButton_SendFile.setEnabled(False)

        self.handle_log(
            logging.INFO, 
            f"[{self.thread_id}]: QSerialUI initialized."
        )

    ########################################################################################
    # Helper functions
    ########################################################################################

    def handle_log(self, level: int, message: str) -> None:
        self.logger.log(level, message)

    ########################################################################################
    # Slots on UI events
    ########################################################################################

    @pyqtSlot()
    def handle_mtoc(self) -> None:
        """Emit the mtoc signal with a function name and time in a single log call."""
        log_message = textwrap.dedent(f"""
            QSerialUI Profiling
            =============================================================
            on_newBaudListReady     took {self.mtoc_on_newBaudListReady*1000:.2f} ms.
            on_newPortListReady     took {self.mtoc_on_newPortListReady*1000:.2f} ms.
            on_receivedData         took {self.mtoc_on_receivedData*1000:.2f} ms.
            on_receivedLines        took {self.mtoc_on_receivedLines*1000:.2f} ms.
            on_throughputRead       took {self.mtoc_on_throughputReady*1000:.2f} ms.
            on_usb_event_detect     took {self.mtoc_on_usb_event_detected*1000:.2f} ms.
            on_serialStatusReady    took {self.mtoc_on_serialStatusReady*1000:.2f} ms.

            appendTextLines         took {self.mtoc_appendTextLines*1000:.2f} ms.
            appendText              took {self.mtoc_appendText*1000:.2f} ms.
            appendHtml              took {self.mtoc_appendHtml*1000:.2f} ms.
            clear                   took {self.mtoc_clear*1000:.2f} ms.
        """)
        self.handle_log(logging.INFO, log_message)

    @pyqtSlot(int,str)
    def on_logSignal(self, level: int, message: str) -> None:
        """pickup log messages"""
        self.handle_log(level, message)

    @pyqtSlot()
    def on_carriageReturnPressed(self) -> None:
        """
        Transmitting text from UI to serial TX line
        """

        if DEBUGSERIAL:
            tic = time.perf_counter()
            self.handle_log(logging.DEBUG, f"[{self.thread_id}]: text entering detected at {tic}")

        text = self.ui.lineEdit_Text.text()                                # obtain text from send input window

        # Make sure we have valid line terminator
        eol = self.textLineTerminator if self.textLineTerminator not in {b"", b"\r"} else b"\r\n"

        if not text:
            text_bytearray = eol
            self.handle_log(logging.INFO, f"[{self.thread_id}]: sending empty line")

        else:        
            self.displayingRunning.emit(True)            
            self.serialSendHistory.append(text)                                # keep history of previously sent commands
            self.serialSendHistoryIndx = len(self.serialSendHistory)           # reset history pointer
        
            try:
                text_bytearray = text.encode(self.encoding) + eol # add line termination
            except UnicodeEncodeError:
                text_bytearray = text.encode("utf-8", errors="replace") + eol
                self.handle_log(logging.WARNING, f"[{self.thread_id}]: encoding error, using UTF-8 fallback.")
            except Exception as e:
                self.handle_log(logging.ERROR, f"[{self.thread_id}]: encoding error: {e}")
                return

        if DEBUGSERIAL:
            self.handle_log(logging.DEBUG, f"[{self.thread_id}]: text ready to emit {time.perf_counter()}")

        self.sendTextRequest.emit(text_bytearray)                                # send text to serial TX line
        self.ui.lineEdit_Text.clear()
        self.ui.statusBar().showMessage("Text sent.", 2000)

        if DEBUGSERIAL:
            toc = time.perf_counter()
            self.handle_log(logging.DEBUG, f"[{self.thread_id}]: text emission completed in {1000*(toc - tic):.2f} ms.")

    @pyqtSlot(str)
    def on_usb_event_detected(self, message: str) -> None:
        """
        This responds to an USB device insertion on removal
        """

        # Check for ports directly
        ports, port_names, port_hwids = [], [], []
        for info in QSerialPortInfo.availablePorts():
            ports.append(info.portName())
            port_names.append(info.description())
            port_hwids.append(f"{info.vendorIdentifier():04X}:{info.productIdentifier():04X}")

        if "USB device removed" in message:
            # Check if the device is still there
            if self.serialPort not in ports and self.serialPort != "":
                # Device is no longer there, close the port
                if self.serialPort != "":
                    self.serialPortHWID_backup  = self.serialPortHWID
                    self.serialBaudRate_backup  = self.serialBaudRate
                    self.serialPort_previous    = self.serialPort
                    self.awaitingReconnection   = True
                QTimer.singleShot(  0, lambda: self.stopThroughputRequest.emit()) # request to stop throughput
                QTimer.singleShot( 50, lambda: self.closePortRequest.emit())      # request to close serial port
                QTimer.singleShot(250, lambda: self.serialStatusRequest.emit())   # request to report serial port status
                QTimer.singleShot(300, lambda: self.scanPortsRequest.emit())      # initiate update of port list

                self.handle_log(
                    logging.INFO, 
                    f"[{self.thread_id}]: requesting Closing serial port."
                )
                self.ui.statusBar().showMessage('USB device removed, Serial Close requested.', 5000)            
            else:
                pass

        elif "USB device added" in message:
            if self.awaitingReconnection: 
                best_match = None
                best_score = 0.0
                for hwid in port_hwids:
                    score = SequenceMatcher(None, self.serialPortHWID_backup, hwid).ratio()
                    if score > best_score:  # Keep track of the best match
                        best_score = score
                        best_match = hwid
                if score > 0.8:
                    # find the port that matches the previous hwid
                    indx = port_hwids.index(best_match)
                    self.serialPort_backup = ports[indx]
                    self.serialPort_previous = ports[indx]
                    QTimer.singleShot(  0, lambda: self.scanPortsRequest.emit())                # request new port list
                    QTimer.singleShot( 50, lambda: self.scanBaudRatesRequest.emit())            # update baudrates
                    QTimer.singleShot(100, lambda: self.changePortRequest.emit(self.serialPort_backup, self.serialBaudRate_backup) ) # takes 11ms to open port
                    QTimer.singleShot(200, lambda: self.serialStatusRequest.emit())             # request to report serial port status            
                    QTimer.singleShot(250, lambda: self.startThroughputRequest.emit())          # request to start serial receiver
                    self.awaitingReconnection = False
                    self.handle_log(
                        logging.INFO, 
                        f"[{self.thread_id}]: device {port_names[indx]} on port {self.serialPort_backup} reopened with baud {self.serialBaudRate_backup} "
                        f"eol {repr(self.textLineTerminator)} timeout {self.serialTimeout}."
                    )
                    self.ui.statusBar().showMessage('USB device reconnection.', 5000)
                else:
                    self.handle_log(
                        logging.INFO, 
                        f"[{self.thread_id}]: new device {best_match} does not match hardware id {self.serialPortHWID_backup} ."
                    )

            else:
                # We have new device insertion, connect to it
                if self.serialPort == "":
                    # new_ports     = [port for port in ports if port not in self.serialPorts] # prevents device to be opened that was previously found but not opened
                    new_ports = [port for port in ports]
                    new_portnames = [port_names[ports.index(port)] for port in new_ports if port in ports]  # Get corresponding names

                    # Figure out if useable port
                    if new_ports:
                        new_port      = new_ports[0] # Consider first found new port
                        new_portname  = new_portnames[0] if new_portnames else "Unknown Device"
                        new_baudrate  = self.serialBaudRate if self.serialBaudRate > 0 else DEFAULT_BAUDRATE

                        # Show user confirmation dialog
                        reply = QMessageBox.question(self.ui, "New USB Device Detected",
                            f"Do you want to connect to {new_port} ({new_portname})?",
                            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                        if reply == QMessageBox.Yes:
                            # Start the receiver
                            self.serialPort_previous = new_port
                            QTimer.singleShot(  0, lambda: self.scanPortsRequest.emit())                # request new port list
                            QTimer.singleShot( 50, lambda: self.scanBaudRatesRequest.emit())            # request new baud rate list
                            QTimer.singleShot(100, lambda: self.changePortRequest.emit(new_port, new_baudrate)) # takes 11ms to open
                            QTimer.singleShot(200, lambda: self.serialStatusRequest.emit())             # request to report serial port status            
                            QTimer.singleShot(250, lambda: self.startThroughputRequest.emit())          # request to start serial receiver
                            self.handle_log(
                                logging.INFO, 
                                f"[{self.thread_id}]: requested opening Serial port {new_port} with {new_baudrate} baud."
                            )
                            self.ui.statusBar().showMessage('Serial Open requested.', 2000)

    @pyqtSlot()
    def on_upArrowPressed(self) -> None:
        """
        Handle special keys on lineEdit: UpArrow
        """
        if not self.serialSendHistory:  # Check if history is empty
            self.ui.lineEdit_Text.setText("")
            self.ui.statusBar().showMessage("No commands in history.", 2000)
            return

        if self.serialSendHistoryIndx > 0:
            self.serialSendHistoryIndx -= 1
        else:
            self.serialSendHistoryIndx = 0  # Stop at oldest command

        self.ui.lineEdit_Text.setText(self.serialSendHistory[self.serialSendHistoryIndx])
        self.ui.statusBar().showMessage("Command retrieved from history.", 2000)
        
    @pyqtSlot()
    def on_downArrowPressed(self) -> None:
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
    def on_pushButton_SendFile(self) -> None:
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
            QTimer.singleShot(50, lambda: self.sendFileRequest.emit(fname))
            
        self.ui.statusBar().showMessage('Text file sent.', 2000)            

    @pyqtSlot()
    def on_pushButton_SerialClearOutput(self) -> None:
        """
        Clearing text display window
        """
        if self.linesBufferTimer.isActive():
            self.linesBufferTimer.stop()
        if self.byteArrayBufferTimer.isActive():
            self.byteArrayBufferTimer.stop()
        if self.htmlBufferTimer.isActive():
            self.htmlBufferTimer.stop()
        self.linesBuffer.clear()
        self.byteArrayBuffer.clear()
        self.htmlBuffer = ""

        self.ui.plainTextEdit_Text.clear()
        self.handle_log(logging.INFO, f"[{self.thread_id}]: text and Log display cleared.")
        self.ui.statusBar().showMessage("Text Display Cleared.", 2000)

    @pyqtSlot()
    def on_pushButton_SerialStartStop(self) -> None:
        """
        Start serial receiver
        """
        if self.ui.pushButton_SerialStartStop.text() == "Start":
            # START text display
            self.displayingRunning.emit(True)
            self.handle_log(
                logging.DEBUG,
                f"[{self.thread_id}]: turning text display on."
            )
            self.ui.statusBar().showMessage("Text Display Starting", 2000)
            
        else:
            # STOP text display
            self.displayingRunning.emit(False)
            self.handle_log(
                logging.DEBUG, 
                f"[{self.thread_id}]: turning text display off."
            )
            self.ui.statusBar().showMessage('Text Display Stopping.', 2000)            

    @pyqtSlot()
    def on_pushButton_SerialSave(self) -> None:
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
                f.write(self.ui.plainTextEdit_Text.toPlainText())

        self.ui.statusBar().showMessage("Serial Monitor text saved.", 2000)

    @pyqtSlot()
    def on_pushButton_SerialScan(self) -> None:
        """
        Updating serial port list

        Sends signal to serial worker to scan for ports
        Serial worker will create newPortList signal when completed which
        is handled by the function on_newPortList below
        """
        self.scanPortsRequest.emit()
        self.handle_log(
            logging.DEBUG, 
            f"[{self.thread_id}]: scanning for serial ports."
        )
        self.ui.statusBar().showMessage('Serial Port Scan requested.', 2000)            

    @pyqtSlot()
    def on_SerialRecord(self) -> None:
        self.record = self.ui.radioButton_SerialRecord.isChecked()
        if self.record:
    
            if self.recordingFileName == "":
                stdFileName = (
                    QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
                    + "/QSerial.txt"
                ) 
            else:
                stdFileName = self.recordingFileName
    
            self.recordingFileName, _ = QFileDialog.getSaveFileName(
                self.ui, "Save As", stdFileName, "Text files (*.txt)"
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
                        self.handle_log(logging.INFO, f"[{self.thread_id}]: overwrite choice aborted.")  
                        self.record = False
                        self.ui.radioButton_SerialRecord.setChecked(self.record)
                        return
                else:
                    mode = "wb"  # Default to write mode if file doesn't exist

                try:
                    self.recordingFile = open(file_path, mode)
                    self.handle_log(logging.INFO, f"[{self.thread_id}]: recording to file {file_path.name} in mode {mode}.")
                except Exception as e:
                    self.handle_log(logging.ERROR, f"[{self.thread_id}]: could not open file {file_path.name} in mode {mode}.")
                    self.record = False
                    self.ui.radioButton_SerialRecord.setChecked(self.record)
        else:
            if self.recordingFile:
                try:
                    self.recordingFile.flush()
                    self.recordingFile.close()
                    self.handle_log(logging.INFO, f"[{self.thread_id}]: recording to file {self.recordingFile.name} stopped.")
                except Exception as e:
                    self.handle_log(logging.ERROR, f"[{self.thread_id}]: could not close file {self.recordingFile.name}.")
                self.recordingFile = None

    @pyqtSlot()
    def on_pushButton_SerialOpenClose(self) -> None:
        if self.ui.pushButton_SerialOpenClose.text() == "Close":
            # Close the serial port
            #   stop the receiver
            self.serialPort_previous = self.serialPort
            QTimer.singleShot(  0, lambda: self.stopThroughputRequest.emit()) # request to stop throughput
            QTimer.singleShot( 50, lambda: self.closePortRequest.emit())      # request to close serial port
            QTimer.singleShot(250, lambda: self.serialStatusRequest.emit())   # request to report serial port status
            #   shade sending text
            self.ui.lineEdit_Text.setEnabled(False)
            self.ui.pushButton_SendFile.setEnabled(False)
            # do not want to automatically reconnect when device is reinserted
            self.awaitingReconnection = False

            self.handle_log(
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
                self.handle_log(
                    logging.INFO, 
                    f"[{self.thread_id}]: serial port not valid. Error {str(e)}"
                )
                self.ui.statusBar().showMessage('Can not open serial port.', 2000)
                return

            else:
                baudrate = self.serialBaudRate if self.serialBaudRate > 0 else DEFAULT_BAUDRATE

                _tmp = self.ui.comboBoxDropDown_LineTermination.currentText()        
                textLineTerminator = self.eol_dict.get(_tmp, b"\r\n")

                # Start the receiver
                QTimer.singleShot(  0, lambda: self.changeLineTerminationRequest.emit(textLineTerminator))
                QTimer.singleShot( 20, lambda: self.changePortRequest.emit(port, baudrate)) # takes 11ms to open
                QTimer.singleShot(200, lambda: self.serialStatusRequest.emit())    # request to report serial port status            
                self.handle_log(
                    logging.INFO, 
                    f"[{self.thread_id}]: requesting opening serial port {port} with {self.serialBaudRate} baud."
                )
                self.ui.statusBar().showMessage('Serial Open requested.', 2000)

        # clear USB unplug reconnection flag
        self.awaitingReconnection = False

    @pyqtSlot()
    def on_comboBoxDropDown_SerialPorts(self) -> None:
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
                        self.handle_log(logging.INFO, f"[{self.thread_id}]: changing baudrate to {baudrate}")
                    else:
                        baudrate = self.defaultBaudRate  # use default baud rate
                        self.handle_log(logging.INFO, f"[{self.thread_id}]: using default baudrate {baudrate}")
                else:
                    baudrate = self.defaultBaudRate # use default baud rate, user can change later

            # change port if port changed
            if port != self.serialPort or baudrate != self.serialBaudRate:
                QTimer.singleShot(   0, lambda: self.changePortRequest.emit(port, baudrate))  # takes 11ms to open
                QTimer.singleShot( 200, lambda: self.serialStatusRequest.emit())   # request to report serial port status
                self.handle_log(
                    logging.INFO,
                    f"[{self.thread_id}]: port {port} baud {baudrate}"
                )
            else:
                # port already open
                self.handle_log(
                    logging.INFO,
                    f"[{self.thread_id}]: keeping current port {port} baud {baudrate}"
                )

        else:
            # No port is open, do not change anything
            self.handle_log(
                logging.INFO,
                f"[{self.thread_id}]: port not changed, no port is open."
            )

        self.ui.statusBar().showMessage("Serial port change requested.", 2000)

    @pyqtSlot()
    def on_comboBoxDropDown_BaudRates(self) -> None:
        """
        User selected a different baudrate on drop down list
        """
        if self.serialPort != "":
            lenBaudRates = len(self.BaudRates)

            if lenBaudRates > 0:  # if we have recognized serial baud rates
                index = self.ui.comboBoxDropDown_BaudRates.currentIndex()

                if index < lenBaudRates:  # last entry is -1
                    baudrate = self.BaudRates[index]
                    self.handle_log(logging.INFO, f"[{self.thread_id}]: changing baudrate to {baudrate}")
                else:
                    baudrate = self.defaultBaudRate  # use default baud rate
                    self.handle_log(logging.INFO, f"[{self.thread_id}]: using default baudrate {baudrate}")

                if baudrate != self.serialBaudRate:  # change baudrate if different from current
                    self.changeBaudRequest.emit(baudrate)
                    QTimer.singleShot(200, lambda: self.serialStatusRequest.emit())             # request to report serial port status
                    self.handle_log(
                        logging.INFO,
                        f"[{self.thread_id}]: changing baudrate to {baudrate}."
                    )
                else:
                    self.handle_log(
                        logging.INFO,
                        f"[{self.thread_id}]: baudrate remains the same."
                    )

            else:
                self.handle_log(
                    logging.ERROR,
                    f"[{self.thread_id}]: no baudrates available"
                )

        else:
            # do not change anything as we first need to open a port
            self.handle_log(
                logging.WARNING,
                f"[{self.thread_id}]: no port open, can not change baudrate"
            )

        self.ui.statusBar().showMessage('Baudrate change requested.', 2000)

    @pyqtSlot()
    def on_comboBoxDropDown_LineTermination(self) -> None:
        """
        User selected a different line termination from drop down menu
        """

        _tmp = self.ui.comboBoxDropDown_LineTermination.currentText()        
        self.textLineTerminator = self.eol_dict.get(_tmp, b"\r\n")

        # ask line termination to be changed if port is open
        # if self.serialPort != "":
        QTimer.singleShot( 0, lambda: self.changeLineTerminationRequest.emit(self.textLineTerminator))
        QTimer.singleShot(50, lambda: self.serialStatusRequest.emit()) # request to report serial port status

        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: line termination {repr(self.textLineTerminator)}"
        )
        self.ui.statusBar().showMessage("Line Termination updated", 2000)

    @pyqtSlot()
    def on_HistorySliderChanged(self):
        """
        Serial Terminal History Slider Handling
        This sets the maximum number of text line retained in the terminal display window

        Update the corresponding line edit box when the slider is moved
        """
        value = self.horizontalSlider.value()
        value = int(clip_value(value, 50, MAX_TEXTBROWSER_LENGTH))
        self.maxlines = value
        self.horizontalSlider.blockSignals(True)
        self.horizontalSlider.setValue(value)
        self.horizontalSlider.blockSignals(False)
        if DEBUGSERIAL:
            self.handle_log(
                logging.DEBUG,
                f"[{self.thread_id}]: Horizontal zoom set to {value}."
            )
        self.lineEdit_History.setText(str(self.maxlines))
        self.ui.plainTextEdit_Text.setMaximumBlockCount(self.maxlines)

    @pyqtSlot()
    def on_HistoryLineEditChanged(self):
        """
        Serial Terminal History Text Edit Handling
        Updates the slider and the history range when text is entered manually.
        """
        try: 
            value = int(self.lineEdit_History.text().strip())
            value = clip_value(value, 50, MAX_TEXTBROWSER_LENGTH)
            
            self.maxlines = value
            
            self.horizontalSlider.blockSignals(True)
            self.horizontalSlider.setValue(self.maxlines)
            self.horizontalSlider.blockSignals(False)

            self.ui.plainTextEdit_Text.setMaximumBlockCount(self.maxlines)

            self.handle_log(
                logging.DEBUG,
                f"[{self.thread_id}]: Vertical terminal history set to {self.maxlines}."
            )

        except ValueError:
            self.lineEdit_History.setText(str(self.maxlines))
            
            self.handle_log(
                logging.ERROR,
                f"[{self.thread_id}]: Invalid value for history: {self.lineEdit_History.text()}"
            )

    ########################################################################################
    # Slots for Worker Signals
    ########################################################################################

    @pyqtSlot(str, int, bytes, bool)
    def on_serialStatusReady(self, 
                             port: str, 
                             baud: int, 
                             eol: bytes, 
                             connected: bool) -> None:
        """
        Serial status report available
        """

        if PROFILEME: 
            tic = time.perf_counter()

        # Port
        self.serialPort     = port
        self.connected      = connected

        # Line termination
        self.textLineTerminator = eol

        _tmp = self.eol_dict_inv.get(eol, "return newline (\\r\\n)")

        if eol not in self.eol_dict_inv:
            self.handle_log(logging.WARNING, f"[{self.thread_id}]: unknown line termination {eol}.")
            self.handle_log(logging.WARNING, f"[{self.thread_id}]: set line termination to {_tmp}.")

        try:
            index = self.ui.comboBoxDropDown_LineTermination.findText(_tmp)
            if index > -1:
                self.ui.comboBoxDropDown_LineTermination.blockSignals(True)
                self.ui.comboBoxDropDown_LineTermination.setCurrentIndex(index)
                self.handle_log(logging.DEBUG, f"[{self.thread_id}]: selected line termination {_tmp}.")
        except Exception as e:
            self.handle_log(logging.ERROR, f"[{self.thread_id}]: line termination error: {e}.")
        finally:
            self.ui.comboBoxDropDown_LineTermination.blockSignals(False)

        # Update UI Based on Connection State
        self.ui.pushButton_SerialOpenClose.setText("Close" if connected else "Open")
        self.ui.pushButton_SerialOpenClose.setEnabled(connected or self.serialPort != "")
        self.ui.lineEdit_Text.setEnabled(connected)
        self.ui.pushButton_SendFile.setEnabled(connected)
    
        if not connected:

            # Not Connected

            self.ui.comboBoxDropDown_SerialPorts.blockSignals(True)
            if self.serialPort != "":
                index = self.ui.comboBoxDropDown_SerialPorts.findText(self.serialPort)
            elif self.serialPort_previous != "":
                index = self.ui.comboBoxDropDown_SerialPorts.findText(self.serialPort_previous)
            else:
                index = -1
            if index > -1: # if we found item
                self.ui.comboBoxDropDown_SerialPorts.setCurrentIndex(index)
                self.ui.pushButton_SerialOpenClose.setEnabled(True)

            else:  # if we did not find item, set box to last item (None)
                self.ui.comboBoxDropDown_SerialPorts.setCurrentIndex(len(self.serialPortNames))
                self.ui.pushButton_SerialOpenClose.setEnabled(False)
            self.ui.comboBoxDropDown_SerialPorts.blockSignals(False)

            self.ui.pushButton_ToggleDTR.setEnabled(False)
            self.ui.pushButton_ResetESP.setEnabled(False)

        else:

            # Connected

            # Handle Connection UI Updates**
            self.ui.pushButton_ChartStartStop.setEnabled(True)
            self.ui.pushButton_SerialStartStop.setEnabled(True)
            self.ui.pushButton_ToggleDTR.setEnabled(True)
            self.ui.pushButton_ResetESP.setEnabled(True)


            # Update Baud Rate
            self.serialBaudRate = baud if baud > 0 else self.defaultBaudRate
            self.defaultBaudRate = self.serialBaudRate

            self.ui.lineEdit_Text.setEnabled(True)
            self.ui.pushButton_SendFile.setEnabled(True)

            # Set Serial Port Combobox**
            try:
                index = self.ui.comboBoxDropDown_SerialPorts.findText(self.serialPort)
                self.ui.comboBoxDropDown_SerialPorts.blockSignals(True)
                self.ui.comboBoxDropDown_SerialPorts.setCurrentIndex(index)
                self.handle_log(logging.DEBUG, f"[{self.thread_id}]: selected port \"{self.serialPort}\".")
            except Exception as e:
                self.handle_log(logging.ERROR, f"[{self.thread_id}]: port error: {e}.")
            finally:
                self.ui.comboBoxDropDown_SerialPorts.blockSignals(False)

            # Set Baud Rate Combobox**
            try:
                index = self.ui.comboBoxDropDown_BaudRates.findText(str(self.serialBaudRate))
                if index > -1:
                    self.ui.comboBoxDropDown_BaudRates.blockSignals(True)
                    self.ui.comboBoxDropDown_BaudRates.setCurrentIndex(index)
                    self.handle_log(logging.DEBUG, f"[{self.thread_id}]: selected baudrate {self.serialBaudRate}.")
            except Exception as e:
                self.handle_log(logging.ERROR, f"[{self.thread_id}]: baudrate error: {e}.")
            finally:
                self.ui.comboBoxDropDown_BaudRates.blockSignals(False)

            self.handle_log(logging.DEBUG, f"[{self.thread_id}]: receiver is {'running' if self.receiverIsRunning else 'not running'}.")

        self.ui.statusBar().showMessage("Serial status updated", 2000)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_serialStatusReady = max((toc - tic), self.mtoc_on_serialStatusReady)

    @pyqtSlot(list, list, list)
    def on_newPortListReady(self, ports: list, portNames: list, portHWIDs: list) -> None:
        """
        New serial port list available
        """
        if PROFILEME: 
            tic = time.perf_counter()

        self.handle_log(
            logging.DEBUG,
            f"[{self.thread_id}]: port list received."
        )
        self.serialPorts     = ports
        self.serialPortNames = portNames
        self.serialPortHWIDs = portHWIDs
        
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
            self.serialPort_previous = ""
        # enable signals again
        self.ui.comboBoxDropDown_SerialPorts.blockSignals(False)
        self.ui.statusBar().showMessage("Port list updated", 2000)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_newPortListReady = max((toc - tic), self.mtoc_on_newPortListReady )  # End performance tracking

    @pyqtSlot(list)
    def on_newBaudListReady(self, baudrates: list) -> None:
        """
        New baud rate list available
        For logic and sequence of commands refer to newPortList
        """

        if PROFILEME: 
            tic = time.perf_counter()

        self.handle_log(
            logging.DEBUG,
            f"[{self.thread_id}]: baud list received."
        )
        self.BaudRates = baudrates
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

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_newBaudListReady = max((toc - tic), self.mtoc_on_newBaudListReady)  # End performance tracking

    ########################################################################################
    # Slots for Data Received
    ########################################################################################

    @pyqtSlot(bytes)
    def on_receivedData(self, byte_array: bytes) -> None:
        """
        Receives a raw byte array from the serial port, decodes it, stores it in a buffer
        """

        if PROFILEME or DEBUGSERIAL: 
            tic = time.perf_counter()

            if DEBUGSERIAL:
                self.handle_log(logging.DEBUG, f"[{self.thread_id}]: text received on {tic}.")

        if byte_array:
            self.byteArrayBuffer.extend(byte_array)
            if not self.byteArrayBufferTimer.isActive():
                self.byteArrayBufferTimer.start()

            if self.record and self.recordingFile:
                try:
                    self.recordingFile.write(byte_array)
                except Exception as e:
                    self.handle_log(logging.ERROR, f"[{self.thread_id}]: could not write to file {self.recordingFileName}. Error: {e}")
                    self.record = False
                    self.ui.radioButton_SerialRecord.setChecked(self.record)

        if PROFILEME or DEBUGSERIAL:
            toc = time.perf_counter()
            if DEBUGSERIAL:
               self.handle_log(logging.DEBUG, f"[{self.thread_id}]: text inserted in: {1000*(toc-tic):.2f} ms")

            if PROFILEME: 
                self.mtoc_on_receivedData = max((toc - tic), self.mtoc_on_receivedData)  # End performance tracking

    @pyqtSlot()
    def flushByteArrayBuffer(self) -> None:
        """
        Takes content of the text buffer and displays it efficiently
        It also stores the content in a file if requested
        If user has scrolled away from bottom of display, update will stop
        """

        if self.byteArrayBuffer:

            if PROFILEME:
                tic = time.perf_counter()

            scroll_bar = self.ui.plainTextEdit_Text.verticalScrollBar()
            at_bottom = scroll_bar.value() >= (scroll_bar.maximum() - scroll_bar.pageStep())

            if not at_bottom:
                return

            # Decode byte array
            text = self.byteArrayBuffer.decode(self.encoding, errors="replace")
            self.byteArrayBuffer.clear()

            if text:
                lines = text.splitlines(keepends=True)
                if not lines:
                    return
                
                self.ui.plainTextEdit_Text.setUpdatesEnabled(False)

                # if more lines available then there are lines in terminal history, 
                # do a full redraw with the latest lines that fit in the terminal,
                # otherwise append text to terminal history and let widget auto trim
                if len(lines) > self.maxlines:
                    # full redraw
                    display_text = ''.join(lines[-self.maxlines:])
                    self.ui.plainTextEdit_Text.setPlainText(display_text)
                else:
                    # fast append
                    self.ui.plainTextEdit_Text.moveCursor(QTextCursor.End)
                    self.ui.plainTextEdit_Text.insertPlainText(text)

                scroll_bar.setValue(scroll_bar.maximum())  # Scroll to bottom for autoscroll
                self.ui.plainTextEdit_Text.setUpdatesEnabled(True)                

            if PROFILEME:
                toc = time.perf_counter()
                self.mtoc_appendText = max(toc - tic, self.mtoc_appendText)

        else:
            self.byteArrayBufferTimer.stop()

    @pyqtSlot(list)
    def on_receivedLines(self, lines: list) -> None:
        """
        Receives lines of text from the serial input handler, stores them in a buffer
        """

        if PROFILEME or DEBUGSERIAL: 
            tic = time.perf_counter()

            if DEBUGSERIAL:
                self.handle_log(logging.DEBUG, f"[{self.thread_id}]: text lines received on {tic}.")

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
                    self.handle_log(logging.ERROR, f"[{self.thread_id}]: could not write to file {self.recordingFileName}. Error: {e}")
                    self.record = False
                    self.ui.radioButton_SerialRecord.setChecked(self.record)

        if PROFILEME or DEBUGSERIAL:
            toc = time.perf_counter()
            if DEBUGSERIAL:
                self.handle_log(logging.DEBUG, f"[{self.thread_id}]: text inserted in: {(toc - tic)*1000:.2f} ms")

            if PROFILEME: 
                self.mtoc_on_receivedLines = max((toc - tic), self.mtoc_on_receivedLines)  # End performance tracking

    @pyqtSlot()
    def flushLinesBuffer(self) -> None:
        """
        Takes the content of the line buffer and displays it efficiently in the terminal
        """
          
        if self.linesBuffer:

            if PROFILEME: 
                tic = time.perf_counter()  # Start performance tracking

            scroll_bar = self.ui.plainTextEdit_Text.verticalScrollBar()
            at_bottom = scroll_bar.value() >= (scroll_bar.maximum() - scroll_bar.pageStep())

            if not at_bottom:
                return
            
            # Decode all lines efficiently
            decoded_lines = [line.decode(self.encoding, errors="replace") for line in self.linesBuffer]
            self.linesBuffer.clear()

            # Append new lines to the display
            if decoded_lines:

                self.ui.plainTextEdit_Text.setUpdatesEnabled(False)

                # if more lines available then there are lines in terminal history, 
                # do a full redraw with the latest lines that fit in the terminal,
                # otherwise append text to terminal history and let widget auto trim
                if len(decoded_lines) > self.maxlines:
                    # full redraw
                    display_text = '\n'.join(decoded_lines[-self.maxlines:])
                    self.ui.plainTextEdit_Text.setPlainText(display_text)
                else:
                    # fast append
                    display_text = '\n'.join(decoded_lines)
                    self.ui.plainTextEdit_Text.moveCursor(QTextCursor.End)
                    self.ui.plainTextEdit_Text.insertPlainText(display_text)

                scroll_bar.setValue(scroll_bar.maximum())  # Scroll to bottom for autoscroll
                self.ui.plainTextEdit_Text.setUpdatesEnabled(True)

            if PROFILEME: 
                toc = time.perf_counter()  # End performance tracking
                self.mtoc_appendTextLines = max((toc - tic),self.mtoc_appendTextLines )  # End performance tracking

        else:
            self.linesBufferTimer.stop()            

    @pyqtSlot(str)
    def on_receivedHTML(self, html: str) -> None:
        """
        Received html text from the serial input handler, stores them in a buffer
        """

        if PROFILEME or DEBUGSERIAL: 
            tic = time.perf_counter()

            if DEBUGSERIAL:
                self.handle_log(logging.DEBUG, f"[{self.thread_id}]: html received on {tic}.")

        if html:
            self.htmlBuffer += html
            if not self.htmlBufferTimer.isActive():
                self.htmlBufferTimer.start()

            if self.record and self.recordingFile:
                try:
                    self.recordingFile.write(html)
                except Exception as e:
                    self.handle_log(logging.ERROR, f"[{self.thread_id}]: could not write to file {self.recordingFileName}. Error: {e}")
                    self.record = False
                    self.ui.radioButton_SerialRecord.setChecked(self.record)

        if PROFILEME or DEBUGSERIAL:
            toc = time.perf_counter()
            if DEBUGSERIAL:
               self.handle_log(logging.DEBUG, f"[{self.thread_id}]: html inserted in: {1000*(toc-tic):.2f} ms")

            if PROFILEME: 
                self.mtoc_on_receivedHTML = max((toc - tic), self.mtoc_on_receivedHTML)  # End performance tracking
        
    @pyqtSlot()
    def flushHTMLBuffer(self) -> None:
        """
        Takes the content of the line buffer and displays it efficiently in the terminal
        """
          
        if self.htmlBuffer:

            if PROFILEME: 
                tic = time.perf_counter()  # Start performance tracking

            scroll_bar = self.ui.plainTextEdit_Text.verticalScrollBar()
            at_bottom = scroll_bar.value() >= (scroll_bar.maximum() - scroll_bar.pageStep())

            if not at_bottom:
                return
            
            # Process HTML & detect incomplete tags
            valid_html_part, self.htmlBuffer = self.html_tracker.detect_incomplete_html(self.htmlBuffer)

            if valid_html_part:
                
                self.ui.plainTextEdit_Text.setUpdatesEnabled(False)
                text_cursor = self.ui.plainTextEdit_Text.textCursor()
                text_cursor.movePosition(QTextCursor.End)
                text_cursor.insertHtml(valid_html_part)
                scroll_bar.setValue(scroll_bar.maximum())
                self.ui.plainTextEdit_Text.setUpdatesEnabled(True)

            if PROFILEME: 
                toc = time.perf_counter()  # End performance tracking
                self.mtoc_appendHTML = max((toc - tic),self.mtoc_appendHTML )  # End performance tracking

        else:
            self.htmlBufferTimer.stop()            

    @pyqtSlot(bool)
    def on_serialWorkerStateChanged(self, running: bool) -> None:
        """
        Serial worker was started or stopped
        """
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: serial worker is {'on' if running else 'off'}."
        )
        self.receiverIsRunning = running
        if running:
            self.ui.statusBar().showMessage("Serial Worker started", 2000)
        else:
            self.ui.statusBar().showMessage("Serial Worker stopped", 2000)

    @pyqtSlot(int, int)
    def on_throughputReady(self, numReceived: int, numSent: int) -> None:
        """
        Report throughput
        """

        tic = time.perf_counter()
        deltaTime = tic - self.lastNumComputed
        self.lastNumComputed = tic

        # delta num chars received and sent
        rx = numReceived - self.lastNumReceived
        tx = numSent - self.lastNumSent

        self.lastNumReceived = numReceived
        self.lastNumSent = numSent

        # calculate throughput
        # deltaTime is in milli seconds -> *1000
        # numReceived and numSent are in kilo bytes -> /1024
        if rx >=0: 
            self.rx = rx / deltaTime
        if tx >=0: 
            self.tx = tx / deltaTime

        # # poor man's low pass
        # self.rx = 0.5 * self.rx + 0.5 * rx
        # self.tx = 0.5 * self.tx + 0.5 * tx

        if self.rx>1_000_000 or self.tx>1_000_000:
            self.ui.label_throughput.setText(
                f"Rx:{self.rx/1048576.:7,.2f}  Tx:{self.tx/1048576.:7,.2f} MB/s".replace(",","_")
            )
        elif self.rx>1_000 or self.tx>1_000:
            self.ui.label_throughput.setText(
                f"Rx:{self.rx/1024.:7,.1f}  Tx:{self.tx/1024.:7,.1f} kB/s".replace(",","_")
            )
        else:
            self.ui.label_throughput.setText(
                f"Rx:{self.rx:7,.1f}  Tx:{self.tx:7,.1f} B/s".replace(",","_")
            )

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_throughputReady = max((toc - tic), self.mtoc_on_throughputReady)  # End performance tracking
    
    def cleanup(self) -> None:
        """
        Perform cleanup tasks for QSerialUI, such as stopping timers, disconnecting signals,
        and ensuring proper worker shutdown.
        """

        if hasattr(self.recordingFile, "close"):
            try:
                self.recordingFile.flush()
                self.recordingFile.close()
            except:
                self.handle_log(
                    logging.ERROR, 
                    f"[{self.thread_id}]: could not close file {self.recordingFileName}."
                )
        
        # Stop timers if they are still active
        if self.byteArrayBufferTimer.isActive():
            self.byteArrayBufferTimer.stop()
        if self.linesBufferTimer.isActive():
            self.linesBufferTimer.stop()
        if self.htmlBufferTimer.isActive():
            self.htmlBufferTimer.stop()

        self.handle_log(
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
#    This is the Model of the Model - View - Controller (MVC) architecture.
#
# start and stop worker
# sent text, lines,
# scan for serial ports and baudrate
# change or open port
# change line termination, baudrate 
# calculate serial throughput 
#
##########################################################################################################################################        
##########################################################################################################################################        

class QSerial(QObject):
    """
    Serial Interface for QT

    Worker Signals
        receivedData bytes               received text on serial RX
        receivedLines list               received multiple lines on serial RX
        newPortListReady                 completed a port scan
        newBaudListReady                 completed a baud scan
        throughputReady                  throughput data is available
        serialStatusReady                report on port and baudrate available
        serialWorkerStateChanged         worker started or stopped
        logSignal                        logging message
        finished                         worker finished

    Worker Slots
        on_setupReceiverRequest()        create receiver elements (in different thread)
        on_dataReady()                   QSerial triggered data pickup from serial port

        on_changePortRequest(str, int)   worker received request to change port
        on_changeLineTerminationRequest(bytes)
        on_throughputTimer()             emit throughput data every second
        on_closePortRequest()            worker received request to close current port
        on_changeBaudRequest(int)        worker received request to change baud rate
        on_scanPortsRequest()            worker received request to scan for serial ports
        on_serialStatusRequest()         worker received request to report current port and baudrate
        on_sendTextRequest(bytes)        worker received request to transmit text
        on_sendLinesRequest(list of bytes) worker received request to transmit multiple lines of text
        on_sendFileRequest(str)          worker received request to transmit a file
        
        on_startReceiverRequest()        connect to serial Input
        on_stopReceiverRequest()         stop serial input
        on_startThroughputRequest()      start timer to report throughput
        on_stopThroughputRequest()       stop timer to report throughput
        on_stopWorkerRequest()           stop  timer and close serial port

    Functions
        handle_log(int, str)             emit log message   
        handle_mtoc()                    emit mtoc message
        wait_for_signal(signal)          wait for signal to be emitted
        scanPorts()                      scan for serial ports
        openPort(str, int, bool)         open serial port
        closePort()                      close serial port
        clearPort()                      clear serial port buffers
        writeData(bytes)                 write data to serial port

    Hidden Utility Functions
        espBootloader()                  perform classic ESP reset to boot loader
        espHardReset()                   perform ESP hard reset
    """

    # Signals
    ########################################################################################
    receivedData             = pyqtSignal(bytes)                                           # text received on serial port
    receivedLines            = pyqtSignal(list)                                            # lines of text received on serial port
    newPortListReady         = pyqtSignal(list, list, list)                                # updated list of serial ports is available
    newBaudListReady         = pyqtSignal(list)                                            # updated list of baudrates is available
    serialStatusReady        = pyqtSignal(str, int, bytes, bool)                           # serial status is available
    throughputReady          = pyqtSignal(int,int)                                         # number of characters received/sent on serial port
    serialWorkerStateChanged = pyqtSignal(bool)                                            # worker started or stopped
    logSignal                = pyqtSignal(int, str)                                        # Logging
    finished                 = pyqtSignal() 
        
    # Init
    ########################################################################################
    def __init__(self, parent=None):

        super().__init__(parent)

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"
        
        # Profiling
        self.mtoc_on_sendTextRequest = 0.
        self.mtoc_on_sendLineRequest = 0.
        self.mtoc_on_sendLinesRequest = 0.
        self.mtoc_on_sendFileRequest = 0.
        self.mtoc_read = 0.
        self.mtoc_write = 0.
        self.mtoc_readlines = 0.

        # Receiver
        self.receiverIsRunning  = False
        self.QSer = None
        self.eol = DEFAULT_LINETERMINATOR  # default line termination
        self.baud = DEFAULT_BAUDRATE
        self.port_name = ""

        self.bufferIn  = bytearray()
        self.totalCharsReceived = 0
        self.totalCharsSent     = 0

        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: QSerial initialized."
        )

    @pyqtSlot()
    def on_setupReceiverRequest(self) -> None:
        """
        Set up QTimer for throughput measurements
        This needs to be run after the worker was move to different tread
        """

        if DEBUGTHREADS:
            import debugpy
            debugpy.debug_this_thread()

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"


        self.QSer = QSerialPort()  # serial port object

        self.QSer.errorOccurred.connect(
            lambda err: (
                err != QSerialPort.NoError and
                self.handle_log(
                    logging.ERROR,
                    f"[{self.thread_id}]: QSerial Error {err}: {self.QSer.errorString()}"
                )
            )
        )

        # setup the throughput measurement timer
        self.throughputTimer = QTimer()
        self.throughputTimer.setInterval(1000)
        self.throughputTimer.timeout.connect(self.on_throughputTimer)
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: setup throughput timer."
        )

    ########################################################################################
    # Utility Functions
    ########################################################################################

    def handle_log(self, level: int, message:str) -> None:
        """Emit the log signal with a level and message."""
        self.logSignal.emit(level, message)

    def wait_for_signal(self, signal: pyqtBoundSignal) -> float:
        """Utility to wait until a signal is emitted."""
        tic = time.perf_counter()
        loop = QEventLoop()
        signal.connect(loop.quit)
        loop.exec()
        return time.perf_counter() - tic

    def scanPorts(self) -> None:
        """
        Scanning for all serial ports
        """
        self.serialPorts      = []
        self.serialPortNames  = []
        self.serialPortHWIDs  = []
        for info in QSerialPortInfo.availablePorts():
            # do not take ports that:
            # - have description 'N/A'
            # - have description ''
            # - have no vendor or product identifier
            # - can not be opened
            desc = info.description().strip().lower()
            if desc == 'n/a' or desc == '':
                continue
            if not (info.hasVendorIdentifier() and info.hasProductIdentifier()):
                continue
            port = QSerialPort(info)
            if not port.open(QIODevice.ReadWrite):
                continue
            port.close()

            self.serialPorts.append(info.portName())
            self.serialPortNames.append(info.description())
            self.serialPortHWIDs.append(f"{info.vendorIdentifier():04X}:{info.productIdentifier():04X}")

    def openPort(self, name: str, baud: int) -> bool:
        """
        Open the serial port
        """
        if self.QSer.isOpen():
            self.QSer.close()

        self.QSer.setPortName(name)
        self.QSer.setBaudRate(baud)
        self.QSer.setDataBits(QSerialPort.Data8)
        self.QSer.setParity(QSerialPort.NoParity)
        self.QSer.setStopBits(QSerialPort.OneStop)
        self.QSer.setFlowControl(QSerialPort.NoFlowControl)
        # alternative flow controls are:
        # QSerialPort::NoFlowControl, QSerialPort::HardwareControl, QSerialPort::SoftwareControl);
        # Software is XON/XOFF
        # Hardware uses RequestToSent and DataTerminalRead signal lines
        self.QSer.setReadBufferSize(SERIAL_BUFFER_SIZE)
        if not self.QSer.open(QIODevice.ReadWrite):
            return False

        # # If hardware flow control do this here:
        # self.QSer.setRequestToSend(True)
        # QThread.msleep(10)
        # self.QSer.setRequestToSend(False)

        self.port_name = name
        self.baud = baud
 
        return True

    def closePort(self) -> None:
        """
        Closes the serial port and resets attributes.
        """
        if self.QSer.isOpen():
            try:
                self.clearPort()
                if self.QSer.isOpen():
                    self.QSer.close()
                self.port_name = ""
                self.baud = DEFAULT_BAUDRATE

                self.handle_log(
                    logging.INFO, 
                    f"[{self.thread_id}]: serial port closed."
                )
            except Exception as e:
                self.handle_log(
                    logging.ERROR, 
                    f"[{self.thread_id}]: failed to close port - {e}"
                )

    def clearPort(self) -> None:
        """
        Clear serial buffers (input, output, and internal bufferIn),
        and reset counters.
        """
        if self.QSer.isOpen():
            self.QSer.clear(QSerialPort.AllDirections)
            QCoreApplication.processEvents()
            _ = bytes(self.QSer.readAll())
            self.QSer.flush()

        # Your internal bookkeeping
        self.bufferIn.clear()
        self.totalCharsReceived = 0
        self.totalCharsSent     = 0

    def writeData(self, data: bytes) -> None:

        if self.QSer.isOpen():

            if DEBUGSERIAL or PROFILEME:
                tic = time.perf_counter()

            ba = QByteArray(data)
            l_w = self.QSer.write(ba)
            l_ba = len(data)

            if l_w == -1:
                self.handle_log(
                    logging.ERROR,
                    f"[{self.thread_id}]: Tx failed."
                )
            else:
                self.totalCharsSent += l_w

                if DEBUGSERIAL or PROFILEME:
                    toc = time.perf_counter()

                    if DEBUGSERIAL:
                        self.handle_log(
                            logging.DEBUG,
                            f"[{self.thread_id}]: Tx wrote {l_w} of {l_ba} bytes in {1000 * (toc - tic):.2f} ms."
                        )

                    if PROFILEME: 
                        self.mtoc_write = max((toc - tic), self.mtoc_write)

        else:
            self.handle_log(
                logging.ERROR,
                f"[{self.thread_id}]: Tx port not opened."
            )

            self.mtoc_write = 0.

    def toggleDTR(self) -> None:
        """
        Toggle DTS to get microcontroller out og while(!Serial)
        """
        if self.QSer.isOpen():
            # RTS low (idle) to prevent ESP reset circuitry
            self.QSer.setRequestToSend(False)
            # SetDTR to get microcontroller board out of while(!Serial)
            self.QSer.setDataTerminalReady(True)
            QThread.msleep(50)
            self.QSer.setDataTerminalReady(False)

            self.handle_log(
                logging.INFO, 
                f"[{self.thread_id}]: DTR toggled."
            )

        else:
            self.handle_log(
                logging.ERROR, 
                f"[{self.thread_id}]: Toggle DTR failed, serial port not open!"
            )


    def espBootloader(self) -> None:
        """
        Classic ESP32 auto‑reset into the serial ROM bootloader.

        Sequence (active‑low signals):
        1. RTS low  = EN low   → hard reset  
        2. Delay ~100 ms  
        3. DTR low  = GPIO0 low → select bootloader  
        4. RTS high = EN high  → release reset (chip runs in bootloader)  
        5. Delay ~100 ms  
        6. DTR high = GPIO0 high → leave BOOT line idle
        """

        if self.QSer.isOpen():
            # 0) Ensure both lines idle (EN=HIGH, GPIO0=HIGH)
            self.QSer.setRequestToSend(False)        # RTS → high → EN=HIGH
            self.QSer.setDataTerminalReady(False)    # DTR → high → GPIO0=HIGH

            # 1) Hard reset: pull EN low
            self.QSer.setRequestToSend(True)         # RTS → low → EN=LOW
            QThread.msleep(100)

            # 2) Bootloader select: pull GPIO0 low
            self.QSer.setDataTerminalReady(True)     # DTR → low → GPIO0=LOW

            # 3) Release reset: EN high → bootloader starts
            self.QSer.setRequestToSend(False)        # RTS → high → EN=HIGH
            QThread.msleep(100)

            # 4) Back to idle: GPIO0 high → normal BOOT pin idle
            self.QSer.setDataTerminalReady(False)    # DTR → high → GPIO0=HIGH

            self.handle_log(
                logging.INFO, 
                f"[{self.thread_id}]: ESP bootloader reset completed."
            )
        else:   
            self.handle_log(
                logging.ERROR, 
                f"[{self.thread_id}]: ESP bootloader reset failed, serial port not open!"
            )
    
    def espHardReset(self) -> None:
        """
        Perform a “hard reset” of the ESP chip (no bootloader entry).
        
        Sequence:
        1. Ensure both lines idle: EN=HIGH, GPIO0=HIGH
        2. Pull EN low   → reset the chip
        3. Wait           ~100 ms for reset to register
        4. Release EN high → chip starts running your sketch
        If you happen to hold DTR low (GPIO0=LOW) *before* calling this, then
        this same RTS toggle will release the chip into its bootloader instead.
        """

        if self.QSer.isOpen():
            # 1) Idle: EN=HIGH (RTS de‑asserted), GPIO0=HIGH (DTR de‑asserted)
            self.QSer.setRequestToSend(False)       # RTS=False → EN=HIGH
            self.QSer.setDataTerminalReady(False)   # DTR=False → GPIO0=HIGH

            # 2) Reset: pull EN low
            self.QSer.setRequestToSend(True)        # RTS=True → EN=LOW

            # 3) Hold reset long enough
            QThread.msleep(100)

            # 4) Release reset: EN goes high, chip runs
            self.QSer.setRequestToSend(False)       # RTS=False → EN=HIGH

            
            self.handle_log(
                logging.INFO, 
                f"[{self.thread_id}]: ESP hard reset completed."
            )
        else:
            self.handle_log(
                logging.ERROR, 
                f"[{self.thread_id}]: ESP hard reset failed, serial port not open!"
            )

    ########################################################################################
    # UI request responses
    ########################################################################################

    @pyqtSlot()
    def handle_mtoc(self):
        """Emit the mtoc signal with a function name and time in a single log call."""
        log_message = textwrap.dedent(f"""
            QSerial Profiling
            =============================================================
            on_sendTextRequest      took {self.mtoc_on_sendTextRequest*1000:.2f} ms.
            on_sendLineRequest      took {self.mtoc_on_sendLineRequest*1000:.2f} ms.
            on_sendLinesRequest     took {self.mtoc_on_sendLinesRequest*1000:.2f} ms.
            on_sendFileRequest      took {self.mtoc_on_sendFileRequest*1000:.2f} ms.            
            Serial Read             took {self.mtoc_read*1000:.2f} ms.
            Serial Readlines        took {self.mtoc_readlines*1000:.2f} ms.
            Serial Write            took {self.mtoc_write*1000:.2f} ms.
            Bytes received               {self.totalCharsReceived}.
            Bytes sent                   {self.totalCharsSent}.
        """)
        self.handle_log(logging.INFO, log_message)

    @pyqtSlot()
    def on_dataReady(self) -> None:
        """
        Reading bytes from serial RX
        Then splitting them into list of lines or directly sending them to the UI
        """

        if DEBUGSERIAL or PROFILEME:
            tic = time.perf_counter()

        chunk = bytes(self.QSer.readAll())
        self.totalCharsReceived += len(chunk)

        if self.eol:  
            
            # EOL-based reading -> processing line by line 
            #------------------------------------------------------------------------

            self.bufferIn.extend(chunk)

            # Ensure `_eol` exists in buffer before splitting
            if self.eol not in self.bufferIn:
                # No complete lines received yet                    
                lines = []

            else: 
                # Delimiter found, split byte array into lines
                lines = self.bufferIn.split(self.eol)

                if lines:
                    if lines[-1] == b"":
                        # No partial line, clear the buffer
                        lines.pop()
                        self.bufferIn.clear()
                    else:
                        # Partial line detected, store it for the next read
                        self.bufferIn[:] = lines.pop() 

                    self.receivedLines.emit(lines)

            if DEBUGSERIAL or PROFILEME:
                toc = time.perf_counter()
                if DEBUGSERIAL:
                    self.handle_log(
                        logging.DEBUG,
                        f"[{self.thread_id}]: Rx {len(chunk)} bytes from {len(lines)} lines in {1000 * (toc - tic):.2f} ms."
                    )
                if PROFILEME: 
                    self.mtoc_readlines = max((toc - tic), self.mtoc_readlines)

        else:              

            # Raw byte reading
            # -----------------------------------------------------

            self.receivedData.emit(chunk)  # single chunk, emit ir right away

            if DEBUGSERIAL or PROFILEME:
                toc = time.perf_counter()
                if DEBUGSERIAL:
                    total_bytes = len(chunk)
                    self.handle_log(
                        logging.DEBUG,
                        f"[{self.thread_id}]: Rx {total_bytes} bytes in {1000 * (toc - tic):.2f} ms."
                    )
                if PROFILEME: 
                    self.mtoc_read = max((toc - tic), self.mtoc_read)

    @pyqtSlot(str, int)
    def on_changePortRequest(self, name: str, baud: int) -> None:
        """
        Request to change port received
        """
        if name != "":
            if self.openPort( name = name, baud = baud):
                self.handle_log(
                    logging.INFO,
                    f"[{self.thread_id}]: port {name} opened with baud {baud}."
                )
            else:
                self.handle_log(
                    logging.ERROR,
                    f"[{self.thread_id}]: failed to open port {name}."
                )
        else:
            self.handle_log(
                logging.ERROR,
                f"[{self.thread_id}]: port not provided."
            )

    @pyqtSlot(bytes)
    def on_changeLineTerminationRequest(self, lineTermination: bytes) -> None:
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
            self.eol = lineTermination
            self.handle_log(
                logging.INFO,
                f"[{self.thread_id}]: changed line termination to {repr(self.eol)}."
            )

    @pyqtSlot()
    def on_throughputTimer(self) -> None:
        """
        Report throughput numbers every second
        """
        if self.QSer.isOpen():
            self.throughputReady.emit(
                self.totalCharsReceived, self.totalCharsSent
            )
        else:
            self.throughputReady.emit(0, 0)
        
    @pyqtSlot()
    def on_closePortRequest(self) -> None:
        """
        Request to close port received
        """
        self.closePort()

    @pyqtSlot(int)
    def on_changeBaudRateRequest(self, baud: int) -> None:
        """
        New baudrate received
        """
        if (baud is None) or (baud <= 0):
            self.handle_log(
                logging.WARNING,
                f"[{self.thread_id}]: range error, baudrate not changed to {baud}."
            )
        else:
            if self.QSer.isOpen():
                if (self.serialBaudRates.index(baud) >= 0):
                    self.QSer.setBaudRate(baud)

                    if (self.QSer.baudRate == baud):  # check if new value matches desired value
                        self.handle_log(
                            logging.INFO,
                            f"[{self.thread_id}]: changed baudrate to {baud}."
                        )
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
            else:
                self.handle_log(
                    logging.ERROR,
                    f"[{self.thread_id}]: failed to set baudrate, serial port not open!"
                )

    @pyqtSlot()
    def on_scanPortsRequest(self) -> None:
        """ 
        Request to scan for serial ports received 
        """            
        self.scanPorts()
        self.newPortListReady.emit(self.serialPorts, self.serialPortNames, self.serialPortHWIDs)
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: port(s) {self.serialPortNames} available."
        )

    @pyqtSlot()
    def on_scanBaudRatesRequest(self) -> None:
        """
        Request to report serial baud rates received
        """
        self.serialBaudRates = QSerialPortInfo.standardBaudRates()

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
            self.serialBaudRates = [DEFAULT_BAUDRATE]

        self.newBaudListReady.emit(self.serialBaudRates)

    @pyqtSlot()
    def on_serialStatusRequest(self) -> None:
        """
        Request to report of serial status received
        """
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: providing serial status."
        )
        if self.QSer.isOpen():
            self.serialStatusReady.emit(
                self.QSer.portName(),
                self.QSer.baudRate(),
                self.eol,
                True,
            )
        else:
            self.serialStatusReady.emit(
                "",
                self.QSer.baudRate(),
                self.eol,
                False,
            )

    @pyqtSlot(bytes)
    def on_sendTextRequest(self, byte_array: bytes) -> None:
        """
        Request to transmit text to serial TX line
        """
        if PROFILEME: 
            tic = time.perf_counter()

        self.writeData(byte_array)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_sendTextRequest = max((toc - tic), self.mtoc_on_sendTextRequest)  # End performance tracking

    @pyqtSlot(bytes)
    def on_sendLineRequest(self, byte_array: bytes) -> None:
        """
        Request to transmit a line of text to serial TX line
        Terminate the text with eol characters.
        """

        if PROFILEME: 
            tic = time.perf_counter()

        self.writeData(byte_array + self.eol)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_sendLineRequest = max((toc - tic), self.mtoc_on_sendLineRequest)  # End performance tracking

    @pyqtSlot(list)
    def on_sendLinesRequest(self, lines: list) -> None:
        """
        Request to transmit multiple lines of text to serial TX line
        """

        if PROFILEME: 
            tic = time.perf_counter()

        joined = b"".join(line + self.eol for line in lines)
        self.writeData(joined)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_sendLinesRequest = max((toc - tic), self.mtoc_on_sendLinesRequest)  # End performance tracking

    @pyqtSlot(str)
    def on_sendFileRequest(self, fname: str) -> None:
        """
        Request to transmit file to serial TX line
        """

        if PROFILEME: 
            tic = time.perf_counter()

            if fname:
                try:
                    with open(fname, "rb") as f:  # open file in binary read mode
                        file_content = f.read()
                        self.writeData(file_content)
                except:
                    self.handle_log(
                        logging.ERROR,
                        f'[{self.thread_id}]: Error Tx "{fname}".'                        )
            else:
                self.handle_log(
                    logging.WARNING,
                    f"[{self.thread_id}]: No Tx file name provided."
                )

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_sendFileRequest = max((toc - tic), self.mtoc_on_sendFileRequest)  # End performance tracking

    @pyqtSlot()
    def on_toggleDTRRequest(self) -> None:
        self.toggleDTR()        

    @pyqtSlot()
    def on_resetESPRequest(self) -> None:
        self.espHardReset()

    @pyqtSlot()
    def on_startReceiverRequest(self) -> None:
        """
        Start the receiving serial data
        This will be called from main program if text display or charting is requested
        """
        if not self.receiverIsRunning:
            if self.QSer.isOpen():
                try:
                    self.clearPort()
                    # self.QSer.readyRead.connect(self.on_dataReady, Qt.QueuedConnection)
                    self.QSer.readyRead.connect(self.on_dataReady)
                    self.receiverIsRunning  = True
                    self.serialWorkerStateChanged.emit(True)  # serial worker is running
                    self.handle_log(
                        logging.INFO,
                        f"[{self.thread_id}]: receiver started."
                    )

                except Exception as e:
                    self.handle_log(
                        logging.ERROR,
                        f"[{self.thread_id}]: receiver start not successful, error: {e}."
                    )
            else:
                self.handle_log(
                    logging.ERROR,
                    f"[{self.thread_id}]: receiver not started, serial port not open."
                )
        else:
            self.handle_log(
                logging.ERROR,
                f"[{self.thread_id}]: receiver is already running."
            )

    @pyqtSlot()
    def on_stopReceiverRequest(self) -> None:
        """
        Stop receiving serial data
        This will be called from main program if text display or charting is no longer running
        """
        if self.receiverIsRunning:
            try:
                self.QSer.readyRead.disconnect(self.on_dataReady)
                self.receiverIsRunning  = False
                self.serialWorkerStateChanged.emit(False)  # serial worker not running
                self.handle_log(
                    logging.INFO,
                    f"[{self.thread_id}]: stopped receiver."
                )
            except Exception as e:
                self.handle_log(
                    logging.ERROR,
                    f"[{self.thread_id}]: receiver stop not successful, error: {e}."
                )

    @pyqtSlot()
    def on_startThroughputRequest(self) -> None:
        """
        Stop QTimer for reading throughput
        This will be called by main program when user presses start button for text display or charting
        """
        self.throughputTimer.start()
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: started throughput timer."
        )

    @pyqtSlot()
    def on_stopThroughputRequest(self) -> None:
        """
        Stop QTimer for reading throughput
        This will be called by main program when user presses the stop button to end text display or charting
        """
        self.throughputTimer.stop()
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: stopped throughput timer."
        )

    @pyqtSlot()
    def on_stopWorkerRequest(self) -> None:
        """
        Worker received request to stop
        We want to stop the worker and exit the program
        """

        self.on_stopThroughputRequest()
        self.on_stopReceiverRequest()
        self.clearPort()
        self.closePort()
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: stopped worker."
        )
        self.finished.emit()

#####################################################################################
# Testing
#####################################################################################

if __name__ == "__main__":
    # not implemented
    pass