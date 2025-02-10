##########################################################################################################################################        
# QT Serial Helper
##########################################################################################################################################        
#
# This code has 3 sections
# QSerialUI: Controller - Interface to GUI, runs in main thread.
# QSerial:   Model - - Functions running in separate thread, communication through signals and slots.
# PSerial:   Sub Model - Low level interaction with serial ports, called from QSerial.
#
# This code is maintained by Urs Utzinger
##########################################################################################################################################        

from serial import Serial
from serial import SerialException, EIGHTBITS, PARITY_NONE, STOPBITS_ONE
from serial.tools import list_ports 

import time
import logging
import re
import platform

from math import ceil
from enum import Enum
from pathlib import Path
from collections import deque
from html.parser import HTMLParser
from difflib import SequenceMatcher


try: 
    from PyQt6.QtCore import (
        QObject, QTimer, QThread, pyqtSignal, pyqtSlot, QStandardPaths, QMetaObject
    )
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QTextCursor, QTextOption
    from PyQt6.QtWidgets import QFileDialog, QMessageBox, QPlainTextEdit, QScrollBar
    hasQt6 = True
except:
    from PyQt5.QtCore import (
        QObject, QTimer, QThread, pyqtSignal, pyqtSlot, QStandardPaths, QMetaObject
    )
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QTextCursor, QTextOption
    from PyQt5.QtWidgets import QFileDialog, QMessageBox, QPlainTextEdit, QScrollBar
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
DEFAULT_LINETERMINATOR = b""         # default line termination
MAX_TEXTBROWSER_LENGTH = 4096        # display window is trimmed to these number of lines
                                     # lesser value results in better performance
MAX_LINE_LENGTH        = 1024        # number of characters after which an end of line characters is expected
RECEIVER_FINISHCOUNT   = 10          # [times] If we encountered a timeout 10 times we slow down serial polling
NUM_LINES_COLLATE      = 10          # [lines] estimated number of lines to collate before emitting signal
                                     #   this results in collating about NUM_LINES_COLLATE * 48 bytes in a list of lines
                                     #   plotting and processing large amounts of data is more efficient for display and plotting
MAX_RECEIVER_INTERVAL  = 100         # [ms]
MIN_RECEIVER_INTERVAL  = 5           # [ms]
TRIM_INTERVAL          = 30000       # [ms] interval to trim text display window

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
# QPlainTextEdit Extension
# 
# Appends Text with no new line
# Appends List of lines
# Appends HTML with no new line, attempts to add only complete html blocks
# Trims display with text buffer
# Provides clear and insert new line functions
#
##########################################################################################################################################        
##########################################################################################################################################        

class QPlainTextEditExtended(QObject):

    logSignal = pyqtSignal(int, str)  
    
    def __init__(self, widget, lines_in_buffer: int = MAX_TEXTBROWSER_LENGTH):
        super().__init__(widget)  

        self.widget = widget

        self.textBuffer = deque(maxlen=lines_in_buffer)
        self.textBrowserLength = lines_in_buffer

        self.incomplete_line = ""

        self.incomplete_html = ""
        # self.incomplete_html_detector = re.compile(r"<([a-zA-Z]+)(\s+[^>]*)?$") 
        self.html_tracker = IncompleteHTMLTracker() 

        self.usePlain = True
        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"

    def handle_log(self, level, message):
        """Emit the log signal with a level and message."""
        self.logSignal.emit(level, message)

    def appendTextNoNL(self, text: str, check_nl: bool = False):
        """
        Append plain text without adding a new line.
        
        :param text: Plain text to append.
        :param check_nl: If True, splits text by `\n` and inserts separate text blocks.
                         If False, appends as-is without inserting new blocks.
        """
        if not text:
            return

        self.usePlain = True

        scroll_bar = self.widget.verticalScrollBar()
        at_bottom = scroll_bar.value() >= (scroll_bar.maximum() - 20)

        text_cursor = self.widget.textCursor()
        # saved_position = text_cursor.position()

        # Updated Circular Line Buffer
        text_lines = self.incomplete_line + text
        lines = text_lines.split("\n")
        if text[-1] != "\n":  # If last character is NOT a newline, it's incomplete
            self.incomplete_line = lines.pop()  # Store incomplete part for next call
        else:
            self.incomplete_line = ""  
        self.textBuffer.extend(lines) # store in buffer

        # Insert text
        text_cursor.movePosition(QTextCursor.End)
        if not check_nl:
            text_cursor.insertText(text)
        else:
            text_cursor.beginEditBlock()
            for i, line in enumerate(lines):
                text_cursor.insertText(line)
                if i < len(lines) - 1:
                    text_cursor.insertBlock()
            text_cursor.endEditBlock()

        # Restore Cursor Position
        # text_cursor.setPosition(saved_position)
        # self.widget.setTextCursor(text_cursor)        

        # Restore scrolling position if needed
        if at_bottom:
            scroll_bar.setValue(scroll_bar.maximum())

    def appendTextLines(self, lines: list):
        """
        Append list of lines.
        
        :param lines: list of lines to append.
        """
        if not lines:
            return

        self.usePlain = True

        # Record current scrollbar and cursor position
        scroll_bar = self.widget.verticalScrollBar()
        at_bottom = scroll_bar.value() >= (scroll_bar.maximum() - 20)

        # text_cursor = self.widget.textCursor()
        # saved_position = text_cursor.position()

        # Updated Circular Line Buffer
        self.textBuffer.extend(lines) # store in buffer

        # Add them all together
        text = "\n".join(lines) # adds new line between lines, but not at front or end of list

        self.widget.appendPlainText(text) # adds new line after last line

        # Restore Cursor Position
        # text_cursor.setPosition(saved_position)
        # self.widget.setTextCursor(text_cursor)        

        # Restore scrolling position if needed
        if at_bottom:
            scroll_bar.setValue(scroll_bar.maximum())

    def appendHtmlNoNL(self, html: str):
        """
        Append HTML text without adding a new line.
        
        :param html: HTML content to append.
        """

        # Nothing to do
        if not html.strip():
            return
        
        self.usePlain = False
        
        # Check location of scroll bar
        scroll_bar = self.widget.verticalScrollBar()
        at_bottom = scroll_bar.value() >= (scroll_bar.maximum() - 20)  # Fixed scrolling check

        # Check position of text cursor
        text_cursor = self.widget.textCursor()
        # saved_position = text_cursor.position()

        # Merge previous incomplete html and new html
        html = self.incomplete_html + html
        self.incomplete_html = ""

        # Process HTML & detect incomplete tags
        valid_html_part, self.incomplete_html = self.html_tracker.detect_incomplete_html(html)

        if valid_html_part:
            text_cursor.movePosition(QTextCursor.End)
            text_cursor.insertHtml(valid_html_part)

        # Restore Cursor Position
        # new_cursor_position = max(self.widget.document().characterCount() - saved_position, 0)
        # new_cursor =  self.widget.textCursor()
        # new_cursor.setPosition(new_cursor_position)
        # self.widget.setTextCursor(new_cursor)        

        # Restore scrolling position if needed        
        if at_bottom:
            scroll_bar.setValue(scroll_bar.maximum())

    def insertNL(self):
        """
        Insert a new text block (acts like adding a new paragraph).
        """
        scroll_bar = self.widget.verticalScrollBar()
        at_bottom = scroll_bar.value() >= (scroll_bar.maximum() - 20)

        text_cursor = self.widget.textCursor()
        text_cursor.movePosition(QTextCursor.End)
        text_cursor.insertBlock()

        if at_bottom:
            scroll_bar.setValue(scroll_bar.maximum())

    def clear(self):
        """
        Clear text in widget and buffer.
        """
        self.widget.clear()
        if self.usePlain:
            self.textBuffer.clear()

    @pyqtSlot()
    def trim(self):
        """
        Trim plain text or HTML.
        """
        tic = time.perf_counter()  # Start performance tracking

        if self.usePlain:
            self._trimText()  # Otherwise, trim plain text
            toc = time.perf_counter()  # End performance tracking
            self.handle_log(
                logging.INFO,
                f"[{self.thread_id}]: trimmed text display in {(toc - tic) * 1000:.2f} ms."
            )

        else:
            self._trimHtml()  # If HTML is active, trim HTML
            toc = time.perf_counter()  # End performance tracking
            self.handle_log(
                logging.INFO,
                f"[{self.thread_id}]: trimmed html display in {(toc - tic) * 1000:.2f} ms."
            )


    def _trimText(self):
        """
        Trim the displayed plain text.
        For efficiency, the current content is replaced with a line buffer
        that is populated when adding text or lines of text with functions above.
        """
        text_display_line_count = self.widget.document().blockCount()
        # text_display_character_count = self.widget.document().characterCount()

        if text_display_line_count > self.textBrowserLength:

            scrollbar = self.widget.verticalScrollBar()  # Get the scrollbar reference

            # Store current scroll position and cursor position
            old_scrollbar_max = scrollbar.maximum()
            old_scrollbar_value = scrollbar.value()
            old_proportion = (old_scrollbar_value / old_scrollbar_max) if old_scrollbar_max > 0 else 1.0

            # text_cursor = self.widget.textCursor()
            # old_cursor_position = text_display_character_count - text_cursor.position() # from end of document

            # Replace text using the circular buffer (fastest approach)
            text = "\n".join(self.textBuffer)  # Efficiently rebuild the display content
            self.widget.setPlainText(text)  # Full replacement (fast)

            # Recalculate new scrollbar position
            new_scrollbar_max = scrollbar.maximum()
            new_scrollbar_value = round(old_proportion * new_scrollbar_max) if new_scrollbar_max > 0 else 0

            # Restore scroll position
            if old_scrollbar_value >= old_scrollbar_max - 20:
                scrollbar.setValue(new_scrollbar_max)  # Auto-scroll to bottom
            else:
                scrollbar.setValue(new_scrollbar_value)  # Maintain user position

            # Restore cursor position
            # new_cursor = self.widget.textCursor()
            # new_cursor_position = len(text) - old_cursor_position
            # new_cursor.setPosition(max(new_cursor_position, 0))  # Ensure the position is valid
            # self.widget.setTextCursor(new_cursor)

    def _trimHtml(self):
        """
        Trim the displayed HTML.
        This will be slow as line by line is removed.
        """
        doc = self.widget.document()
        text_display_line_count = doc.blockCount()

        if text_display_line_count > self.textBrowserLength:

            scrollbar = self.widget.verticalScrollBar()

            old_scrollbar_max = scrollbar.maximum()
            old_scrollbar_value = scrollbar.value()
            old_proportion = (old_scrollbar_value / old_scrollbar_max) if old_scrollbar_max > 0 else 1.0

            # text_cursor = self.widget.textCursor()
            # old_cursor_position = doc.characterCount() - text_cursor.position()  # Relative to end of document

            # How much to trim?
            trim_count = text_display_line_count - self.textBrowserLength  # Lines to remove
            cursor = self.widget.textCursor()
            cursor.movePosition(QTextCursor.Start)  # Start from the top

            # Start trimming
            for _ in range(trim_count):
                if cursor.atEnd():  # Stop if there's nothing left to remove
                    break
                cursor.select(QTextCursor.BlockUnderCursor)  # Select the whole block
                cursor.removeSelectedText()  # Remove text within the block
                cursor.deleteChar()  # Delete the actual block (ensures new lines are removed)
                cursor.movePosition(QTextCursor.NextBlock)  # Move to the next block

            # Restore cursor position
            # new_cursor_position = max(doc.characterCount() - old_cursor_position, 0)
            # text_cursor.setPosition(new_cursor_position)
            # self.widget.setTextCursor(text_cursor)

            # Restore scrollbar position
            new_scrollbar_max = scrollbar.maximum()
            new_scrollbar_value = round(old_proportion * new_scrollbar_max) if new_scrollbar_max > 0 else 0

            if old_scrollbar_value >= old_scrollbar_max - 20:
                scrollbar.setValue(new_scrollbar_max)
            else:
                scrollbar.setValue(new_scrollbar_value)

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

    def handle_starttag(self, tag, attrs):
        """Track opening tags, unless they are self-closing."""
        if tag not in self.self_closing_tags:
            self.tag_stack[tag] = self.tag_stack.get(tag, 0) + 1  # Increment count
            # logging.debug(f"Opening tag detected: <{tag}> (Total open: {self.tag_stack[tag]})")

    def handle_endtag(self, tag):
        """Track closing tags and remove from stack when matched."""
        if tag in self.tag_stack:
            self.tag_stack[tag] -= 1  # Decrement count
            # logging.debug(f"Closing tag detected: </{tag}> (Remaining open: {self.tag_stack[tag]})")
            if self.tag_stack[tag] == 0:
                del self.tag_stack[tag]  # Remove fully closed tag

    def detect_incomplete_html(self, html: str):
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

    def _find_last_complete_tag(self, html: str):
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
            self.handle_log(logging.ERROR, f"unsupported operating system: {os_type}")

    def handle_log(self, level, message):
        """Emit the log signal with a level and message."""
        self.logSignal.emit(level, message)

    def monitor_usb_linux(self):
        import pyudev
        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by(subsystem='tty')

        for device in iter(lambda: monitor.poll(timeout=200), None):
            if not self.running:
                break  # Exit cleanly if stopped

            try:
                action = device.action
                device_node = device.device_node

                if action == 'add':
                    self.usb_event_detected.emit(f"USB device added: {device_node}")
                elif action == 'remove':
                    self.usb_event_detected.emit(f"USB device removed: {device_node}")
            except Exception as e:
                self.handle_log(logging.ERROR, f"[{self.thread_id}]: error: {e}")
                time.sleep(0.2)  # Shorter delay to avoid slow recovery

        self.finished.emit()

    def monitor_usb_windows(self):
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
        on_carriageReturnPressed             transmit text from UI to serial TX line
        on_upArrowPressed                    recall previous line of text from serial TX line buffer
        on_downArrowPressed                  recall next line of text from serial TX line buffer
        on_pushButton_SerialClearOutput      clear the text display window
        on_pushButton_SerialStartStop        start/stop serial receiver and throughput timer
        on_pushButton_SerialSave             save text from display window into text file
        on_pushButton_SerialScan             update serial port list
        on_pushButton_SerialOpenClose        open/close serial port
        on_comboBoxDropDown_SerialPorts      user selected a new port on the drop down list
        on_comboBoxDropDown_BaudRates        user selected a different baudrate on drop down list
        on_comboBoxDropDown_LineTermination  user selected a different line termination from drop down menu
        on_serialStatusReady                 pickup QSerial status on port, baudrate, line termination, timeout, esp_reset, connected
        on_newPortListReady                  pickup new list of serial ports (ports,portNames, portHWID)
        on_newBaudListReady(tuple)           pickup new list of baudrates
        on_receivedData(bytes)               pickup text from serial port
        on_receivedLines(list)               pickup lines of text from serial port
        on_throughputReady(int, int)         pickup throughput data from QSerial
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
    sendFileRequest              = pyqtSignal(str)                                         # request to open file and send over serial port
    displayingRunning            = pyqtSignal(bool)                                        # signal to indicate that serial monitor is running
    workerFinished               = pyqtSignal()                                            # worker is finished
             
    # Init
    ########################################################################################

    def __init__(self, parent=None, ui=None, worker=None, logger=None):

        super().__init__(parent)

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
        self.receiverIsRunning     = False                                                 # keep track of worker state
        self.textLineTerminator    = DEFAULT_LINETERMINATOR                                 # default line termination: none
        self.encoding              = "utf-8"                                               # default encoding
        self.serialTimeout         = 0                                                     # default timeout    
        self.isScrolling           = False                                                 # keep track of text display scrolling
        self.esp_reset             = False                                                 # reset ESP32 on open
        self.connected             = False                                                 # keep track of connection state

        # Backup for reconnection/device removal
        self.serialPort_backup     = ""
        self.serialPortHWID_backup = ""
        self.serialBaudRate_backup = DEFAULT_BAUDRATE
        self.esp_reset_backup      = False
        self.awaitingReconnection  = False

        self.record                = False                                                 # record serial data
        self.recordingFileName     = ""
        self.recordingFile         = None

        self.textBrowserLength     = MAX_TEXTBROWSER_LENGTH + 1

        # self.textDisplayLineCount  = 1 # it will have at least the initial line

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else "N/A"

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

        # Configure text display window on serial text display
        self.ui.plainTextEdit_Text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)  # Always show scrollbar
        self.ui.plainTextEdit_Text.setReadOnly(True)  # Prevent user edits
        self.ui.plainTextEdit_Text.setWordWrapMode(QTextOption.NoWrap)  # No wrapping for better performance

        # Configure scrollbar behavior
        scrollbar = self.ui.plainTextEdit_Text.verticalScrollBar()
        scrollbar.setSingleStep(1)  # Highest resolution for scrolling
        scrollbar.setPageStep(20)  # Defines how much a full page scroll moves
        scrollbar.setValue(scrollbar.maximum())  # Scroll to bottom 

        # Set cursor to end of text for autoscrolling
        textCursor = self.ui.plainTextEdit_Text.textCursor()
        self.move_op = QTextCursor.MoveOperation.End if hasQt6 else QTextCursor.End
        textCursor.movePosition(self.move_op)
        self.ui.plainTextEdit_Text.setTextCursor(textCursor)
        self.ui.plainTextEdit_Text.ensureCursorVisible()

        # Attach Extended Functionality (QPlainTextEditExtended)
        self.ui.plainTextEdit_Text_Ext = QPlainTextEditExtended(self.ui.plainTextEdit_Text)
        self.ui.plainTextEdit_Text_Ext.logSignal.connect(self.handle_log)

        # Setup Automatic Text Trimming to Prevent Memory Overload
        self.textTrimTimer = QTimer(self)
        self.textTrimTimer.timeout.connect(self._requestTrim)
        self.textTrimTimer.start(TRIM_INTERVAL)  # Adjust timing based on performance needs

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

    def handle_log(self, level, message):
        self.logger.log(level, message)

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

    def _requestTrim(self):
        """
        Safely requests trimming operation in the main thread.
        Executes when main thread is free.
        """
        QMetaObject.invokeMethod(
            self.ui.plainTextEdit_Text_Ext, "trim",
            Qt.QueuedConnection
        )

    ########################################################################################
    # Response Functions to Events
    ########################################################################################

    def on_usb_event_detected(self, message):
        """
        This responds to an USB device insertion on removal
        """

        # Scan the ports (not using serial worker)
        port_scan  = [ [p.device, p.description, p.hwid] for p in list_ports.comports() ]
        ports      = [sublist[0] for sublist in port_scan if sublist[1] != 'n/a']
        port_names = [sublist[1] for sublist in port_scan if sublist[1] != 'n/a']
        port_hwids = [sublist[2] for sublist in port_scan if sublist[1] != 'n/a']

        if "USB device removed" in message:
            # Check if the device is still there
            if self.serialPort not in ports and self.serialPort != "":
                # Device is no longer there, close the port
                if self.serialPort != "":
                    self.serialPortHWID_backup  = self.serialPortHWID
                    self.serialBaudRate_backup  = self.serialBaudRate
                    self.esp_reset_backup       = self.esp_reset
                    self.serialPort_previous    = self.serialPort
                    self.awaitingReconnection   = True
                QTimer.singleShot(  0, lambda: self.stopThroughputRequest.emit()) # request to stop throughput
                QTimer.singleShot( 50, lambda: self.closePortRequest.emit())      # request to close serial port
                QTimer.singleShot(250, lambda: self.serialStatusRequest.emit())   # request to report serial port status
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
                    QTimer.singleShot( 50, lambda: self.changePortRequest.emit(self.serialPort_backup, self.serialBaudRate_backup, self.esp_reset_backup) ) # takes 11ms to open port
                    QTimer.singleShot(150, lambda: self.scanBaudRatesRequest.emit())            # update baudrates
                    QTimer.singleShot(200, lambda: self.serialStatusRequest.emit())             # request to report serial port status            
                    QTimer.singleShot(250, lambda: self.startThroughputRequest.emit())          # request to start serial receiver
                    self.awaitingReconnection = False
                    self.handle_log(
                        logging.INFO, 
                        f"[{self.thread_id}]: device {port_names[indx]} on port {self.serialPort_backup} reopened with baud {self.serialBaudRate_backup} "
                        f"eol {repr(self.textLineTerminator)} timeout {self.serialTimeout} and esp_reset {self.esp_reset_backup}."
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
                        new_esp_reset = self.esp_reset

                        # Show user confirmation dialog
                        reply = QMessageBox.question(self.ui, "New USB Device Detected",
                            f"Do you want to connect to {new_port} ({new_portname})?",
                            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                        if reply == QMessageBox.Yes:
                            # Start the receiver
                            self.serialPort_previous = new_port
                            QTimer.singleShot(  0, lambda: self.scanPortsRequest.emit())                # request new port list
                            QTimer.singleShot( 50, lambda: self.changePortRequest.emit(new_port, new_baudrate, new_esp_reset)) # takes 11ms to open
                            QTimer.singleShot(150, lambda: self.scanBaudRatesRequest.emit())            # request new baud rate list
                            QTimer.singleShot(200, lambda: self.serialStatusRequest.emit())             # request to report serial port status            
                            QTimer.singleShot(250, lambda: self.startThroughputRequest.emit())          # request to start serial receiver
                            self.handle_log(
                                logging.INFO, 
                                f"[{self.thread_id}]: requested opening Serial port {new_port} with {new_baudrate} baud and ESP reset {'on' if new_esp_reset else 'off'}."
                            )
                            self.ui.statusBar().showMessage('Serial Open requested.', 2000)

    ########################################################################################
    # Slots on UI events
    ########################################################################################

    @pyqtSlot(int,str)
    def on_logSignal(self, int, str):
        """pickup log messages"""
        self.handle_log(int, str)

    @pyqtSlot()
    def on_carriageReturnPressed(self):
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

    @pyqtSlot()
    def on_upArrowPressed(self):
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
    def on_pushButton_SerialClearOutput(self):
        """
        Clearing text display window
        """
        self.ui.plainTextEdit_Text_Ext.clear()
        self.handle_log(logging.INFO, f"[{self.thread_id}]: text and Log display cleared.")
        self.ui.statusBar().showMessage("Text Display Cleared.", 2000)

    @pyqtSlot()
    def on_pushButton_SerialStartStop(self):
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
                f.write(self.ui.plainTextEdit_Text.toPlainText())

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
        self.handle_log(
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
                    self.recordingFile.close()
                    self.handle_log(logging.INFO, f"[{self.thread_id}]: recording to file {self.recordingFile.name} stopped.")
                except Exception as e:
                    self.handle_log(logging.ERROR, f"[{self.thread_id}]: could not close file {self.recordingFile.name}.")
                self.recordingFile = None

    @pyqtSlot()
    def on_pushButton_SerialOpenClose(self):
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
                textLineTerminator = self.update_LineTermination()

                # Start the receiver
                QTimer.singleShot(  0, lambda: self.changeLineTerminationRequest.emit(textLineTerminator))
                QTimer.singleShot( 20, lambda: self.changePortRequest.emit(port, baudrate, self.esp_reset)) # takes 11ms to open
                QTimer.singleShot(150, lambda: self.scanBaudRatesRequest.emit())   #
                QTimer.singleShot(200, lambda: self.serialStatusRequest.emit())    # request to report serial port status            
                QTimer.singleShot(250, lambda: self.startThroughputRequest.emit()) # request to start serial receiver
                self.handle_log(
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
                        self.handle_log(logging.INFO, f"[{self.thread_id}]: changing baudrate to {baudrate}")
                    else:
                        baudrate = self.defaultBaudRate  # use default baud rate
                        self.handle_log(logging.INFO, f"[{self.thread_id}]: using default baudrate {baudrate}")
                else:
                    baudrate = self.defaultBaudRate # use default baud rate, user can change later

            # change port if port changed
            if port != self.serialPort or baudrate != self.serialBaudRate:
                esp_reset = self.ui.radioButton_ResetESPonOpen.isChecked()
                QTimer.singleShot(   0, lambda: self.changePortRequest.emit(port, baudrate, esp_reset ))  # takes 11ms to open
                QTimer.singleShot( 200, lambda: self.scanBaudRatesRequest.emit())  # request to scan serial baud rates
                QTimer.singleShot( 250, lambda: self.serialStatusRequest.emit())   # request to report serial port status
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
                f"[{self.thread_id}]: no port was perviously open."
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
    def on_comboBoxDropDown_LineTermination(self):
        """
        User selected a different line termination from drop down menu
        """
        self.textLineTerminator = self.update_LineTermination()

        # ask line termination to be changed if port is open
        # if self.serialPort != "":
        QTimer.singleShot( 0, lambda: self.changeLineTerminationRequest.emit(self.textLineTerminator))
        QTimer.singleShot(50, lambda: self.serialStatusRequest.emit()) # request to report serial port status

        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: line termination {repr(self.textLineTerminator)}"
        )
        self.ui.statusBar().showMessage("Line Termination updated", 2000)

    def update_LineTermination(self):
        """ update line termination from UI"""
        _tmp = self.ui.comboBoxDropDown_LineTermination.currentText()

        eol_dict = {
            "newline (\\n)"          : b"\n",
            "return (\\r)"           : b"\r",
            "newline return (\\n\\r)": b"\n\r",
            "return newline (\\r\\n)": b"\r\n",
            "none"                   : b""
        }
        
        eol = eol_dict.get(_tmp, b"\r\n")
        return eol

    ########################################################################################
    # Slots for Worker Signals
    ########################################################################################

    @pyqtSlot(str, int, bytes, float, bool, bool, str)
    def on_serialStatusReady(self, port: str, baud: int, eol: bytes, timeout: float, esp_reset: bool, connected: bool, serialPortHWID: str):
        """
        Serial status report available
        """

        # Port
        self.serialPort     = port
        self.serialPortHWID = serialPortHWID
        self.connected      = connected

        # ESP reset
        self.esp_reset = esp_reset
        self.ui.radioButton_ResetESPonOpen.setChecked(self.esp_reset)

        # Timeout
        self.serialTimeout = timeout

        # Line termination
        self.textLineTerminator = eol

        eol_dict = {
            b"\n": "newline (\\n)",
            b"\r": "return (\\r)",
            b"\n\r": "newline return (\\n\\r)",
            b"\r\n": "return newline (\\r\\n)",
            b"": "none"
        }
        
        _tmp = eol_dict.get(eol, "return newline (\\r\\n)")

        if eol not in eol_dict:
            self.handle_log(logging.WARNING, f"[{self.thread_id}]: unknown line termination {eol}.")
            self.handle_log(logging.WARNING, f"[{self.thread_id}]: set line termination to {_tmp}.")

        # Update UI Combobox for Line Termination
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

        else:

            # Handle Connection UI Updates**
            self.ui.pushButton_ChartStartStop.setEnabled(True)
            self.ui.pushButton_SerialStartStop.setEnabled(True)

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

    @pyqtSlot(list, list, list)
    def on_newPortListReady(self, ports: list, portNames: list, portHWIDs: list):
        """
        New serial port list available
        """
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
            # QTimer.singleShot(  0, lambda: self.stopThroughputRequest.emit())          # request to stop throughput
            # QTimer.singleShot( 50, lambda: self.closePortRequest.emit())               # request to close serial port
            # QTimer.singleShot(250, lambda: self.serialStatusRequest.emit())            # request to report serial port status
        # enable signals again
        self.ui.comboBoxDropDown_SerialPorts.blockSignals(False)
        self.ui.statusBar().showMessage("Port list updated", 2000)

    @pyqtSlot(tuple)
    def on_newBaudListReady(self, baudrates):
        """
        New baud rate list available
        For logic and sequence of commands refer to newPortList
        """
        self.handle_log(
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

    ########################################################################################
    # Slots for Data Received
    ########################################################################################

    @pyqtSlot(bytes)
    def on_receivedData(self, byte_array: bytes):
        """
        Receives a raw byte array from the serial port, decodes it, stores it in a line-based buffer,
        and updates the text display efficiently.
        """

        if DEBUGSERIAL:
            tic = time.perf_counter()
            self.handle_log(logging.DEBUG, f"[{self.thread_id}]: text received on {tic}.")

        # Record text to a file if recording is enabled
        if self.record:
            try:
                self.recordingFile.write(byte_array)
            except Exception as e:
                self.handle_log(logging.ERROR, f"[{self.thread_id}]: could not write to file {self.recordingFileName}. Error: {e}")
                self.record = False
                self.ui.radioButton_SerialRecord.setChecked(self.record)

        # Decode byte array
        text = self._safe_decode(byte_array, self.encoding)

        # if DEBUGSERIAL:
        #     self.handle_log(logging.DEBUG, f"[{self.thread_id}]: {text}")

        # Append new text to the display without adding newline at end of text block
        if text:
            self.ui.plainTextEdit_Text_Ext.appendTextNoNL(text)

        toc = time.perf_counter()
        if DEBUGSERIAL:
            self.handle_log(logging.DEBUG, f"[{self.thread_id}]: text inserted in: {1000*(toc-tic):.2f} ms")

    @pyqtSlot(list)
    def on_receivedLines(self, lines: list):
        """
        Receives lines of text from the serial port, stores them in a circular buffer,
        and updates the text display efficiently.
        """
        if DEBUGSERIAL:
            tic = time.perf_counter()
            self.handle_log(logging.DEBUG, f"[{self.thread_id}]: text lines received on {tic}.")

        # Record lines to file if recording is enabled
        if self.record:
            try:
                self.recordingFile.writelines(lines)
            except Exception as e:
                self.handle_log(logging.ERROR, f"[{self.thread_id}]: could not write to file {self.recordingFileName}. Error: {e}")
                self.record = False
                self.ui.radioButton_SerialRecord.setChecked(self.record)

        # Decode all lines efficiently
        decoded_lines = [self._safe_decode(line, self.encoding) for line in lines]

        # if DEBUGSERIAL:
        #     for decoded_line in decoded_lines:
        #         self.handle_log(logging.DEBUG, f"[{self.thread_id}]: {decoded_line}")

        # Append new lines to the display
        if decoded_lines:
            self.ui.plainTextEdit_Text_Ext.appendTextLines(decoded_lines)

        if DEBUGSERIAL:
            toc = time.perf_counter()
            self.handle_log(logging.DEBUG, f"[{self.thread_id}]: text inserted in: {(toc - tic)*1000:.2f} ms")

    @pyqtSlot(bool)
    def on_serialWorkerStateChanged(self, running: bool):
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

    def on_throughputReady(self, numReceived, numSent):
        """
        Report throughput
        """
        rx = numReceived - self.lastNumReceived
        tx = numSent - self.lastNumSent
        if rx >=0: self.rx = rx
        if tx >=0: self.tx = tx
        # # poor man's low pass
        # self.rx = 0.5 * self.rx + 0.5 * rx
        # self.tx = 0.5 * self.tx + 0.5 * tx
        self.ui.label_throughput.setText(
            "Rx:{:<5.1f} Tx:{:<5.1f} kB/s".format(self.rx / 1024, self.tx / 1024)
        )
        self.lastNumReceived = numReceived
        self.lastNumSent = numSent

    # @pyqtSlot()
    # def serialTextDisplay_trim(self):
    #     """
    #     Reduce the amount of text kept in the text display window
    #     Attempt to keep the scrollbar location
    #     """

    #     tic = time.perf_counter()

    #     # 0. Do we need to trim?
    #     textDisplayLineCount = self.ui.plainTextEdit_Text.document().blockCount() # 70 micros
 
    #     if textDisplayLineCount > self.textBrowserLength:

    #         # old_textDisplayLineCount = textDisplayLineCount
    #         # scrollbar = self.textScrollbar  # Avoid redundant calls

    #         # #  1 Where is the current scrollbar? (scrollbar value is pixel based)
    #         # old_scrollbarMax = scrollbar.maximum()
    #         # old_scrollbarValue = scrollbar.value()

    #         # old_proportion = (old_scrollbarValue / old_scrollbarMax) if old_scrollbarMax > 0 else 1.0            
    #         # old_linePosition = round(old_proportion * old_textDisplayLineCount)

    #         # # 2 Replace text with the line buffer
    #         # # lines_inTextBuffer  = len(self.lineBuffer_text)
    #         # text = "\n".join(self.lineBuffer_text)
    #         # self.ui.plainTextEdit_Text.setPlainText(text)
    #         # new_textDisplayLineCount = self.ui.plainTextEdit_Text.document().blockCount()
    #         # # new_textDisplayLineCount = lines_inTextBuffer + 1

    #         # # 3 Update the scrollbar position
    #         # new_scrollbarMax = self.textScrollbar.maximum()            
    #         # if new_textDisplayLineCount > 0:
    #         #     new_linePosition = max(0, (old_linePosition - (old_textDisplayLineCount - new_textDisplayLineCount)))
    #         #     new_proportion = new_linePosition / new_textDisplayLineCount
    #         #     new_scrollbarValue = round(new_proportion * new_scrollbarMax)
    #         # else:
    #         #     new_scrollbarValue = 0

    #         # # 4 Ensure that text is scrolling when we set cursor towards the end

    #         # if new_scrollbarValue >= new_scrollbarMax - 20:
    #         #     self.textScrollbar.setValue(new_scrollbarMax)  # Scroll to the bottom
    #         # else:
    #         #     self.textScrollbar.setValue(new_scrollbarValue)

    #         scrollbar = self.ui.plainTextEdit_Text.verticalScrollBar()

    #         # 1. Where is the current scrollbar? (scrollbar value is pixel based)
    #         old_scrollbarMax = scrollbar.maximum()
    #         old_scrollbarValue = scrollbar.value()
    #         old_proportion = (old_scrollbarValue / old_scrollbarMax) if old_scrollbarMax > 0 else 1.0

    #         # 2. Replace text using the circular buffer (fastest approach)
    #         text = "\n".join(self.lineBuffer_text)  # Efficiently rebuild the display content
    #         self.ui.plainTextEdit_Text.setPlainText(text)  # Full replacement (fast)

    #         # 3. Recalculate scrollbar position
    #         new_scrollbarMax = scrollbar.maximum()
    #         if new_scrollbarMax > 0:
    #             new_scrollbarValue = round(old_proportion * new_scrollbarMax)
    #         else:
    #             new_scrollbarValue = 0

    #         # 4. Restore scroll position (if user is not at bottom, maintain relative position)
    #         if old_scrollbarValue >= old_scrollbarMax - 20:
    #             scrollbar.setValue(new_scrollbarMax)  # Auto-scroll to bottom
    #         else:
    #             scrollbar.setValue(new_scrollbarValue)  # Maintain user position

    #         toc = time.perf_counter()
    #         self.handle_log(
    #             logging.INFO,
    #             f"[{self.thread_id}]: trimmed text display in {(toc-tic)*1000:.2f} ms."
    #         )

    #     self.ui.statusBar().showMessage('Trimmed Text Display Window', 2000)
    
    def cleanup(self):
        """
        Perform cleanup tasks for QSerialUI, such as stopping timers, disconnecting signals,
        and ensuring proper worker shutdown.
        """

        if hasattr(self.recordingFile, "close"):
            try:
                self.recordingFile.close()
            except:
                self.handle_log(
                    logging.ERROR, 
                    f"[{self.thread_id}]: could not close file {self.recordingFileName}."
                )
        
        # Stop timers
        if self.textTrimTimer.isActive():
            self.textTrimTimer.stop()

        self.textTrimTimer.timeout.disconnect()


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
# change esp serial reset
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
    receivedData             = pyqtSignal(bytes)                                           # text received on serial port
    receivedLines            = pyqtSignal(list)                                            # lines of text received on serial port
    newPortListReady         = pyqtSignal(list, list, list)                                # updated list of serial ports is available
    newBaudListReady         = pyqtSignal(tuple)                                           # updated list of baudrates is available
    serialStatusReady        = pyqtSignal(str, int, bytes, float, bool, bool, str)         # serial status is available
    throughputReady          = pyqtSignal(int,int)                                         # number of characters received/sent on serial port
    serialWorkerStateChanged = pyqtSignal(bool)                                            # worker started or stopped
    logSignal                = pyqtSignal(int, str)                                        # Logging
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
        self.serialPortHWIDs = [sublist[2] for sublist in self.PSer.ports]                  # USB VID:PID=1A86:7523 LOCATION=3-2

        # Baud Rates
        self.serialBaudRates = self.PSer.baudrates                                          # will have default baudrate as no port is open
        
        self.textLineTerminator = DEFAULT_LINETERMINATOR  # default line termination

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

        # Throughput calculations for serial polling
        self.in_rate = 0
        self.last_CharsReceived = 0

        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: QSerial initialized."
        )

    ########################################################################################
    # Utility Functions
    ########################################################################################

    def handle_log(self, level, message):
        """Emit the log signal with a level and message."""
        self.logSignal.emit(level, message)

    def wait_for_signal(self, signal) -> float:
        """Utility to wait until a signal is emitted."""
        tic = time.perf_counter()
        loop = QEventLoop()
        signal.connect(loop.quit)
        loop.exec()
        return time.perf_counter() - tic

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
        
        self.in_rate = self.PSer.totalCharsReceived - self.last_CharsReceived
        self.last_CharsReceived = self.PSer.totalCharsReceived

    @pyqtSlot()
    def on_startReceiverRequest(self):
        """
        Start QTimer for reading data from serial input line (RX)
        Response will need to be analyzed in the main task.
        """
        # clear serial buffers
        self.PSer.clear()

        # start the receiver timer
        serialReadTimeOut, receiverInterval, receiverIntervalStandby = (
            self.compute_timeouts(self.PSer.baud)
        ) 

        self.receiverIntervalStandby = receiverIntervalStandby
        self.receiverInterval = receiverInterval
        self.serialReadTimeOut = serialReadTimeOut
        self.receiverTimer.setInterval(self.receiverIntervalStandby)
        self.receiverTimer.start()
        self.serialReceiverState = SerialReceiverState.awaitingData
        self.serialWorkerStateChanged.emit(True)  # serial worker is running
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: started receiver with interval {self.receiverIntervalStandby} ms."
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

        if DEBUGSERIAL:
            tic = time.perf_counter()

        if self.serialReceiverState == SerialReceiverState.stopped:
            self.handle_log(logging.ERROR, f"[{self.thread_id}]: receiver is stopped.")
            return
                
        if not self.PSer.connected:
            self.handle_log(logging.ERROR, f"[{self.thread_id}]: serial port not connected.")
            return

        data_or_lines = []

        try:
            if self.PSer.eol:  # EOL-based reading -> lines
                data_or_lines = self.PSer.readlines()
            else:              # Raw byte reading
                chunk = self.PSer.read()
                if chunk:
                    data_or_lines = [chunk]  # store as single-element list for uniform handling

        except Exception as e:
            self.handle_log(
                logging.ERROR, 
                f"[{self.thread_id}]: error reading - {e}"
            )

        if not data_or_lines:  # nothing received
            # No data, check if we want to reduce the update rate
            if self.serialReceiverState == SerialReceiverState.receivingData:
                self.serialReceiverCountDown += 1
                if self.serialReceiverCountDown >= RECEIVER_FINISHCOUNT:
                    self.serialReceiverState = SerialReceiverState.awaitingData
                    self.receiverTimer.setInterval(self.receiverIntervalStandby)
                    self.serialReceiverCountDown = 0
                    if DEBUGSERIAL:
                        self.handle_log(
                            logging.DEBUG,
                            f"[{self.thread_id}]: set slower update rate ({self.receiverIntervalStandby} ms) for receiver."
                        )

            if DEBUGSERIAL:
                toc = time.perf_counter()
                self.handle_log(
                    logging.DEBUG,
                    f"[{self.thread_id}]: no data received at {toc}."
                )
            return

        # We have data or lines
        if self.PSer.eol:
            self.receivedLines.emit(data_or_lines)
        else:
            self.receivedData.emit(data_or_lines[0])  # single chunk

        if self.serialReceiverState == SerialReceiverState.receivingData:
            self.serialReceiverCountDown = 0

        if self.serialReceiverState == SerialReceiverState.awaitingData:
            self.receiverTimer.setInterval(self.receiverInterval)
            self.serialReceiverState = SerialReceiverState.receivingData
            self.serialReceiverCountDown = 0
            if DEBUGSERIAL:
                self.handle_log(
                    logging.DEBUG,
                    f"[{self.thread_id}]: set faster update rate ({self.receiverInterval} ms) for receiver."
                )

        if DEBUGSERIAL:
            toc = time.perf_counter()
            total_bytes = sum(len(x) for x in data_or_lines)
            self.handle_log(
                logging.DEBUG,
                f"[{self.thread_id}]: read {total_bytes} bytes in {1000.0 * (toc - tic):.2f} ms at {toc}"
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
                    f"[{self.thread_id}]: transmitted {l} of {l_ba} bytes at {time.perf_counter()}."
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
                    f"[{self.thread_id}]: Transmitted {l} of {l_ba} bytes at {time.perf_counter()}."
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
            if DEBUGSERIAL:
                self.handle_log(
                    logging.DEBUG,
                    f"[{self.thread_id}]: transmitted {l} bytes at {time.perf_counter()}."
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
                        if DEBUGSERIAL:
                            self.handle_log(
                                logging.DEBUG,
                                f'[{self.thread_id}]: transmitted "{fname}" [{l}] at {time.perf_counter()}.'
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
            # self.PSer.close()
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
                self.receiverTimer.setInterval(self.receiverIntervalStandby)
                self.handle_log(
                    logging.INFO,
                    f"[{self.thread_id}]: port {port} opened with baud {baud} eol {repr(self.textLineTerminator)} timeout {self.PSer.timeout} and receiver interval {self.receiverInterval} ms."
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
                        serialReadTimeOut, receiverInterval, receiverIntervalStandby = (
                            self.compute_timeouts(baud)
                        )
                        self.serialReadTimeOut = serialReadTimeOut
                        # self.serialBaudRate = baud  # update local variable
                        self.receiverInterval = receiverInterval
                        self.receiverIntervalStandby = receiverIntervalStandby
                        self.receiverTimer.setInterval(self.receiverInterval)
                        self.handle_log(
                            logging.INFO,
                            f"[{self.thread_id}]: changed baudrate to {baud} with interval {self.receiverInterval} ms and standby {self.receiverIntervalStandby} ms."
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
            self.serialPortHWIDs = [sublist[2] for sublist in self.PSer.ports if sublist[1] != 'n/a']
        else :
            self.serialPorts     = []
            self.serialPortNames = []
            self.serialPortHWIDs = []
        self.handle_log(
            logging.INFO,
            f"[{self.thread_id}]: port(s) {self.serialPortNames} available."
        )
        self.newPortListReady.emit(self.serialPorts, self.serialPortNames, self.serialPortHWIDs)

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
                self.PSer.port, self.PSer.baud, self.PSer.eol, self.PSer.timeout, self.PSer.esp_reset, self.PSer.connected, self.PSer.hwid
            )
        else:
            self.serialStatusReady.emit(
                "", self.PSer.baud, self.PSer.eol, self.PSer.timeout, self.PSer.esp_reset, self.PSer.connected, ""
            )

    def compute_timeouts(self, baud: int, chars_per_line: int = 50):

        if baud == None or baud <= 0:
            baud = DEFAULT_BAUDRATE

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
            # total bits / baudrate [bps] * 1000 [ms]
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
# Provides 
#   open, close
#   read, readline, readlines 
#   write, writeline, writelines
#   serial status
#   ESP reset logic (DTR/RTS toggling)
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
    - Provides open, close
    - Provides read, readline, readlines 
    - Provides write, writeline, writelines
    - Optional ESP reset logic (DTR/RTS toggling)

    """

    def __init__(self, parent=None):

        # if DEBUGPY_ENABLED: debugpy.debug_this_thread() # this should enable debugging of all PSerial methods

        self.ser                = None
        self._port              = ""
        self._hwid              = ""
        self._portname          = ""
        self._baud              = -1
        self._eol               = b""
        self._timeout           = -1
        self._ser_open          = False
        self._esp_reset         = False
        self._leneol            = 0

        self.totalCharsReceived = 0
        self.totalCharsSent     = 0
        self.bufferIn           = bytearray()

        self.reset_delay        = 0.05 # for ESP reset
        self.parent             = parent

        # Setup logging delegation
        if parent is not None and hasattr(parent, "handle_log"):
            self.handle_log = self.parent.handle_log
        else:
            self.logger = logging.getLogger("PSer")
            self.handle_log = self.logger.log
            
        # check for serial ports
        self.scanports()
    
    def __enter__(self):
        """Support `with` statement usage."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Ensure the port is closed on exit."""
        self.close()

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

            if DEBUGSERIAL:
                self.handle_log(logging.DEBUG, f"[SER            ]: found {num_ports} available serial ports.")
                for port in self._ports:
                    self.handle_log(
                        logging.DEBUG, 
                        f"[SER            ]: port: {port[0]}, Desc: {port[1]}, HWID: {port[2]}"
                )

            return num_ports

        except Exception as e:
            self.handle_log(
                logging.ERROR, 
                f"[SER            ]: error scanning ports - {e}"
            )
            self._ports = []  # Ensure `_ports` is empty on failure
            return 0

    def open(self, port: str, baud: int, eol: bytes, timeout: float, esp_reset: bool) -> bool:
        """ 
        Opens the specified serial port.
        """
        # Check if port is already open with the same params, avoid re-init
        if self._ser_open and self._port == port and self._baud == baud and self._timeout == timeout and self._eol == eol:
            return True

        # Find port and hwid in list of available ports
        port_found = False
        for _port in self._ports:
            if _port[0] == port:
                port_found = True
                self._portname_temp = _port[1]
                self._hwid_temp = _port[2]
                break

        # If port not in system, exit
        if not port_found:
            self.handle_log(
                logging.ERROR, 
                f"[SER            ]: port {port} not found in list of available ports."
            )
            return False

        # Always close first in case it was already open or partially open
        self.close()

        try:
            self.ser = Serial()
            self.ser.port = port                    # The serial device
            self.ser.baudrate = baud                # Standard baud rate (115200 is common)
            self.ser.bytesize = EIGHTBITS           # Most common option
            self.ser.parity = PARITY_NONE           # No parity bit
            self.ser.stopbits = STOPBITS_ONE        # Standard stop bit
            self.ser.timeout = timeout              # Timeout for read operations
            self.ser.write_timeout = timeout        # Timeout for write operations
            self.ser.inter_byte_timeout = None      # Disable inter-character timeout
            self.ser.rtscts = False                 # No RTS/CTS handshaking
            self.ser.dsrdtr = False                 # No DSR/DTR signaling
            self.ser.xonxoff = False                # No software flow control

            # Set RTS and DTR before opening to avoid unintended resets
            self.ser.rts = False  # Ensure EN (Reset) stays HIGH
            self.ser.dtr = False  # Ensure GPIO0 stays HIGH

            # Now open the serial port
            self.ser.open()

        except SerialException as e:
            self.handle_log(
                logging.ERROR, 
                f"[SER            ]: SerialException: {e}; failed to create {port} with baud {baud}."
            )
            self._ser_open = False
            self.ser = None
            self._port = ""
            return False
        except OSError as e:
            self.handle_log(
                logging.ERROR,
                f"[SER            ]: OSError: {e}; failed to access port {port}."
            )
            self._ser_open = False
            self.ser = None
            self._port = ""
            return False

        # Attempt to set buffer size
        self.set_serial_buffer(self.ser, rx_size=16384, tx_size=16384)

        # Mark serial as open
        self._ser_open  = True
        self._baud      = baud
        self._port      = port
        self._timeout   = timeout
        self._eol       = eol
        self._leneol    = len(eol)
        self._esp_reset = esp_reset
        self._hwid      = self._hwid_temp
        self._portname  = self._portname_temp

        # If no exceptions occurred, the port was successfully opened
        self.handle_log(
            logging.INFO, 
            f"[SER            ]: opened {self._portname} at {port} with {baud} baud, timeout {timeout}"
            f"{', with esp reset' if esp_reset else ''} and hwid {self._hwid}."
        )


        # Perform ESP reset after the port is open
        if esp_reset:
            try:
                self.espHardReset()
                self.handle_log(logging.INFO, f"[SER            ]: {port} - ESP hard reset completed.")
            except Exception as e:
                self.handle_log(logging.ERROR, f"[SER            ]: {port} - ESP reset failed: {e}.")

        # Clear buffers
        self.clear()
        
        return True

    def set_serial_buffer(self, ser, rx_size=16384, tx_size=16384):
        """
        Manually set the serial buffer size on Linux/macOS using ioctl.
        """
        try:
            if platform.system() == "Windows":
                ser.set_buffer_size(rx_size=rx_size, tx_size=tx_size)
            elif platform.system() == "Linux":
                # Set read buffer size
                bufsize = struct.pack("I", rx_size)
                fcntl.ioctl(ser.fileno(), termios.TIOCSWINSZ, bufsize)

                # Set write buffer size
                bufsize = struct.pack("I", tx_size)
                fcntl.ioctl(ser.fileno(), termios.TIOCSWINSZ, bufsize)

            elif platform.system() == "Darwin":  # macOS
                # macOS does not have TIOCSWINSZ for serial devices.
                # Instead, we can try adjusting TIOCOUTQ to affect buffer sizes.
                fcntl.ioctl(ser.fileno(), termios.TIOCOUTQ, struct.pack("I", tx_size))
                fcntl.ioctl(ser.fileno(), termios.TIOCOUTQ, struct.pack("I", rx_size))

            else:
                self.handle_log(logging.INFO, f"[SER            ]: Can not buffer size on {platform.system()}")
                return

            self.handle_log(logging.INFO, f"[SER            ]: Buffer size set to {rx_size}/{tx_size} on {platform.system()}")

        except Exception as e:
            self.handle_log(logging.WARNING, f"[SER            ]: Could not set buffer size on {platform.system()} - {e}")


    def clear(self) -> None:
        """
        Clear serial buffers (input, output, and internal bufferIn),
        and reset counters.
        """
        if self._ser_open:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        self.bufferIn.clear()
        self.totalCharsReceived = 0
        self.totalCharsSent = 0
          
    def close(self):
        """
        Closes the serial port and resets attributes.
        """
        if self.ser and self._ser_open:
            try:
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
                self.ser.close()
                self.handle_log(logging.INFO, "[SER            ]: serial port closed.")
            except Exception as e:
                self.handle_log(logging.ERROR, f"[SER            ]: failed to close port - {e}")

        self._ser_open = False
        self._port = None

    def changeport(self, port: str, baud: int, eol: bytes, timeout: float, esp_reset: bool):
        """
        switch to different port
        """       
        success = self.open(
            port = port, 
            baud = baud, 
            eol = eol, 
            timeout = timeout, 
            esp_reset = esp_reset
        )
        if success:
            self.handle_log(
                logging.INFO, 
                f"[SER            ]: changed port to {port} @ {baud},  eol={repr(eol)}"
            )
        else:
            self.handle_log(
                logging.ERROR, 
                f"[SER            ]: failed to change port to {port} @ {baud},  eol={repr(eol)}"
            )

    def read(self) -> bytes:
        """
        Reads all bytes from the serial buffer.
        If the buffer is empty, returns an empty bytes object.
        """

        if DEBUGSERIAL:
            tic = time.perf_counter()

        if not self._ser_open:
            self.handle_log(logging.ERROR, "[SER            ]: serial port not available.")
            return b""

        bytes_to_read = self.ser.in_waiting
        if bytes_to_read == 0:
            return b""

        # Read available bytes
        byte_array = self.ser.read(bytes_to_read)
        self.totalCharsReceived += bytes_to_read

        # Log time taken to read
        if DEBUGSERIAL:
            toc = time.perf_counter()
            self.handle_log(
                logging.DEBUG,
                f"[SER            ]: read {bytes_to_read} bytes in {1000 * (toc - tic):.2f} ms from serial port at {toc}."
            )

        return byte_array


    def readline(self) -> bytes:
        """
        Reads one line of text from the serial buffer.
        Handles partial lines when line termination is not found in buffer.
        """

        if DEBUGSERIAL:
            tic = time.perf_counter()

        if not self._ser_open:
            self.handle_log(
                logging.ERROR, 
                "[SER            ]: serial port not available."
            )
            return b""

        try:
            # Read until EOL
            line_data = self.ser.read_until(self._eol)  
            # If times out _line includes whatever was read before timeout
            # If completed without timeout _line includes delimiter
            self.totalCharsReceived += len(line_data)

            if not line_data:  # No data received, return immediately
                return b""
        
            if line_data.endswith(self._eol):
                # Merge previous bufferIn with the new full line
                self.bufferIn.extend(line_data[:-self._leneol])
                line = bytes(self.bufferIn)
                self.bufferIn.clear()

            else:
                self.bufferIn.extend(line_data)
                line = b""

        except Exception as e:
            self.handle_log(
                logging.ERROR, 
                f"[SER            ]: could not read from port - {e}"
            )
            return b""

        if DEBUGSERIAL:
            toc = time.perf_counter()
            self.handle_log(
                logging.DEBUG,
                f"[SER            ]: read {len(line)} bytes from line in {1000 * (toc - tic):.2f} ms from serial port at {toc}."
            )

        return line


    def readlines(self) -> list:
        """
        Reads the serial buffer and converts it into lines of text.
        """

        if DEBUGSERIAL:
            tic = time.perf_counter()

        lines = []

        if not self._ser_open:
            self.handle_log(logging.ERROR,"[SER            ]: serial port not available.")
            return []
        
        try:
            bytes_to_read = self.ser.in_waiting

            if bytes_to_read == 0:
                return []  # No data available
            
            chunk = self.ser.read(bytes_to_read)
            self.totalCharsReceived += len(chunk)

        except Exception as e:
            self.handle_log(
                logging.ERROR, 
                f"[SER            ]: could not read from port - {e}"
            )
            return []


        self.bufferIn.extend(chunk)

        # Ensure `_eol` exists in buffer before splitting
        if self._eol not in self.bufferIn:
            return []  # No complete lines yet
    
        # Delimiter found, split byte array into lines
        lines = self.bufferIn.split(self._eol)

        if lines:
            if lines[-1] == b"":
                # No partial line, clear the buffer
                lines.pop()
                self.bufferIn.clear()
            else:
                # Partial line detected, store it for the next read
                self.bufferIn[:] = lines.pop() 

        if DEBUGSERIAL:
            toc = time.perf_counter()
            self.handle_log(
                logging.DEBUG,
                f"[SER            ]: read {bytes_to_read} bytes from {len(lines)} lines in {1000 * (toc - tic):.2f} ms from serial port at {toc}."
            )

        return lines


    def write(self, byte_array: bytes) -> int:
        """ 
        Sends an array of bytes over the serial port.
        Returns the number of bytes written, or 0 if an error occurs.
        """

        if DEBUGSERIAL:
            tic = time.perf_counter()

        if not self._ser_open:
            self.handle_log(logging.ERROR, "[SER write      ]: serial port not available.")
            return 0
        
        l = 0 

        try:
            l = self.ser.write(byte_array)
            # self.ser.flush()
            self.totalCharsSent += l

            if DEBUGSERIAL:
                l_ba = len(byte_array)
                # decimal_values = " ".join(str(byte) for byte in byte_array)
                toc = time.perf_counter()
                self.handle_log(
                    logging.DEBUG,
                    f"[SER write      ]: wrote {l} of {l_ba} bytes in {1000*(toc-tic):.2f} to serial port at {toc}."
                )

        except Exception as e:
            self.handle_log(
                logging.ERROR,
                f"[SER write      ]: failed to write with timeout {self.timeout}. Error: {e}"
            )
            return 0

        return l

    def writeline(self, byte_array: bytes) -> int:
        """ 
        Sends an array of bytes and appends EOL before writing to the serial port.
        Returns the number of bytes written, or 0 if an error occurs.
        """

        return self.write(byte_array + self._eol)


    def writelines(self, lines: list) -> int:
        """ 
        Sends several lines of text and appends `self._eol` to each line before writing.
        Returns the total number of bytes written, or 0 if an error occurs.
        """

        joined = b"".join(line + self._eol for line in lines)
        return self.write(joined)

    def avail(self) -> int:
        """ 
        is there data in the serial receiving buffer? 
        """
        if self._ser_open:
            return self.ser.in_waiting
        else:
            return -1

    # --------------------------
    #  ESP reset-related methods
    # --------------------------

    def _setDTR(self, state: bool):
        """ 
        Sets the DTR (Data Terminal Ready) signal.
        """
        if self.ser is None:
            self.handle_log(logging.WARNING, "[ESP Reset      ]: Serial port not initialized.")
            return

        try:
            self.ser.dtr = state
            self.handle_log(logging.DEBUG, f"[ESP Reset      ]: DTR set to {'ACTIVE' if not state else 'INACTIVE'}.")
        except SerialException as e:
            self.handle_log(logging.ERROR, f"[ESP Reset      ]: Failed to set DTR - {e}")


    def _setRTS(self, state: bool):
        """
        Sets the RTS (Request To Send) signal.
        Windows Workaround: Some drivers require RTS toggling for changes to take effect.
        """
        if self.ser is None:
            self.handle_log(logging.WARNING, "[ESP Reset      ]: Serial port not initialized.")
            return

        try:
            self.ser.rts = state

            # Windows workaround: Toggle RTS if the system requires it
            if platform.system() == "Windows":
                time.sleep(0.01)  # Small delay before toggling
                self.ser.rts = not state
                time.sleep(0.01)
                self.ser.rts = state  # Restore intended state

            self.handle_log(logging.DEBUG, f"[ESP Reset      ]: RTS set to {'ACTIVE' if not state else 'INACTIVE'}.")
        except SerialException as e:
            self.handle_log(logging.ERROR, f"[ESP Reset      ]: Failed to set RTS - {e}")


    def _setDTRandRTS(self, dtr: bool = False, rts: bool = False):
        """
        Sets both DTR and RTS at the same time (UNIX only).
        """
        if self.ser is None:
            self.handle_log(logging.WARNING, "[ESP Reset      ]: Serial port not initialized.")
            return

        if platform.system() == ("Windows"):
            self.handle_log(logging.ERROR, "[ESP Reset      ]: _setDTRandRTS is not supported on Windows.")
            return

        try:
            status = struct.unpack("I", fcntl.ioctl(self.ser.fileno(), TIOCMGET, struct.pack("I", 0)))[0]
            status = (status | TIOCM_DTR) if dtr else (status & ~TIOCM_DTR)
            status = (status | TIOCM_RTS) if rts else (status & ~TIOCM_RTS)
            fcntl.ioctl(self.ser.fileno(), TIOCMSET, struct.pack("I", status))

            self.handle_log(logging.DEBUG, f"[ESP Reset      ]: DTR={'ACTIVE' if dtr else 'INACTIVE'}, RTS={'ACTIVE' if rts else 'INACTIVE'}.")
        except Exception as e:
            self.handle_log(logging.ERROR, f"[ESP Reset      ]: Failed to set DTR/RTS - {e}")

    # DTR is connected to GPIO0
    # RTS is connected to EN
    #
    # DTR = True, GPIO0 low
    # RTS = True, EN low    
    #
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
        self.handle_log(logging.INFO, "[ESP Reset      ]: Starting Classic Reset (Bootloader Mode).")

        # self._setDTR(False)  # IO0 = HIGH
        # self._setRTS(True)   # EN = LOW (Reset active)
        # time.sleep(0.1)
        # self._setDTR(True)   # IO0 = LOW
        # self._setRTS(False)  # EN = HIGH (Reset released)
        # time.sleep(self.reset_delay)
        # self._setDTR(False)  # IO0 = HIGH (Bootloader mode)

        self._setDTR(False)  # GPIO0 = high
        self._setRTS(True)   # EN = low (reset active)
        time.sleep(0.1)      # Wait for reset
        self._setDTR(True)   # GPIO0 = low
        time.sleep(self.reset_delay)
        self._setRTS(False)  # EN = HIGH (reset inactive)
    
    def espUnixReset_Bootloader(self):
        """
        UNIX-only ESP reset sequence setting DTR and RTS lines together.
        """

        if platform.system() == "Windows":
            self.handle_log(logging.ERROR, "[ESP Reset      ]: espUnixReset_Bootloader is not supported on Windows.")
            return

        self.handle_log(logging.INFO, "[ESP Reset      ]: Starting UNIX Reset (Bootloader Mode).")

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

        self.handle_log(logging.INFO, "[ESP Reset      ]: Starting Hard Reset.")

        # self._setDTR(False)  # IO0 = HIGH
        # self._setRTS(False)  # EN = HIGH
        # time.sleep(0.2)
        # self._setRTS(True)   # EN = LOW (Reset active)
        # time.sleep(0.2)
        # self._setRTS(False)  # EN = HIGH (Reset released)
        # time.sleep(0.2)

        self._setDTR(False)   # IO0 = high
        time.sleep(0.05)      # Allow GPIO0 state to settle
        self._setRTS(True)    # EN = low (reset active)
        time.sleep(0.1)
        self._setRTS(False)   # EN = high (reset in active)
        time.sleep(0.2)
        
        self.handle_log(logging.INFO, "[ESP Reset      ]: Hard Reset Completed.")

    ########################################################################################
    # Reading and Setting Properties of Class
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
            return tuple(sorted(set(baud_list)))
        
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
        if self.changeport(val, self.baud or DEFAULT_BAUDRATE, self.eol, self.timeout, self.esp_reset):
            if DEBUGSERIAL:
                self.handle_log(logging.DEBUG, f"[SER            ]: Port changed to: {val}.")
        else:
            self.handle_log(logging.ERROR, f"[SER            ]: Failed to change port {val}.")

    @property
    def portname(self) -> str:
        """ 
        Returns the name of the currently connected port. 
        If the port is not open, returns an empty string. 
        """
        return self._portname if self._ser_open else ""
    
    @property
    def hwid(self) -> str:
        """ 
        Returns the hardware ID of the currently connected port. 
        If the port is not open, returns an empty string. 
        """
        return self._hwid if self._ser_open else ""
    
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
            self._baud = self.ser.baudrate 

            if self._baud == val:
                self.handle_log(logging.DEBUG, f"[SER            ]: baudrate: {val}.")
                self.clear()
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
        if isinstance(val, str):
            val = val.encode()

        elif not isinstance(val, (str, bytes, bytearray)):
            self.handle_log(logging.WARNING, "[SER            ]: EOL not changed, must provide a string or bytes.")
            return

        self._eol = val
        self._leneol = len(self._eol)  # Update length of EOL

        if DEBUGSERIAL:
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
        if DEBUGSERIAL:
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