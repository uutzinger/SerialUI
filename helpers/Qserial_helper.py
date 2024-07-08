############################################################################################
# QT Serial Helper
############################################################################################
# July 2022: initial work
# December 2023: implemented line reading
# Summer 2024: fixes and improvements
# Summer 2024 b: upgrade to pyqt6
# ------------------------------------------------------------------------------------------
# Urs Utzinger
# University of Arizona 2022, 2023, 2024
# Cameron K Brooks
# Western University 2024
############################################################################################

############################################################################################
# This code has 3 sections
# QSerialUI: Interface to GUI, runs in main thread.
# QSerial: Serial functions running in separate thread, communication with signals and slots.
# PSerial: Low level interaction with serial ports, called from QSerial.
############################################################################################

from serial import Serial as sp
from serial import EIGHTBITS, PARITY_NONE, STOPBITS_ONE
from serial.tools import list_ports

import time, logging
from math import ceil
from enum import Enum

from PyQt6.QtCore import QObject, QTimer, QThread, pyqtSignal, pyqtSlot, QStandardPaths
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QFileDialog

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
DEFAULT_BAUDRATE = 500000  # default baud rate for serial port
MAX_TEXTBROWSER_LENGTH = (
    1024 * 1024
)  # display window character length is trimmed to this length
# lesser value results in better performance
MAX_LINE_LENGTH = (
    1024  # number of characters after which an end of line characters is expected
)
RECEIVER_FINISHCOUNT = (
    10  # [times] If we encountered a timeout 10 times we slow down serial polling
)
NUM_LINES_COLLATE = (
    10  # [lines] estimated number of lines to collate before emitting signal
)
#   this results in collating about NUM_LINES_COLLATE * 48 bytes in a list of lines
#   plotting and processing large amounts of data is more efficient for display and plotting
MAX_RECEIVER_INTERVAL = 100  # [ms]
MIN_RECEIVER_INTERVAL = 5  # [ms]


class SerialReceiverState(Enum):
    """
    When data is expected on the serial input we use a QT timer to read line by line.
    When no data is expected we are in stopped state
    When data is expected but has not yet arrived we are in awaiting state
    When data has arrived and there might be more data arriving we are in receiving state
    """

    stopped = 0
    awaitingData = 1
    receivingData = 2


############################################################################################
# QSerial interaction with Graphical User Interface
# This section contains routines that can not be moved to a separate thread
# because it interacts with the QT User Interface.
# The Serial Worker is in a separate thread and receives data through signals from this class
#
# Receiving from serial port is bytes or a list of bytes
# Sending to serial port is bytes or list of bytes
# We need to encode/decode received/sent text in QSerialUI
############################################################################################


class QSerialUI(QObject):
    """
    Serial Interface for QT

    Signals (to be emitted by UI)
        scanPortsRequest                 request that QSerial is scanning for ports
        scanBaudRatesRequest             request that QSerial is scanning for baudrates
        changePortRequest                request that QSerial is changing port
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
        on_comboBoxDropDown_SerialPorts      user selected a new port on the drop down list
        on_comboBoxDropDown_BaudRates        user selected a different baudrate on drop down list
        on_comboBoxDropDown_LineTermination  user selected a different line termination from drop down menu
        on_serialStatusReady(str, int, bytes, float) pickup QSerial status on port, baudrate, line termination, timeout
        on_newPortListReady(list, list)      pickup new list of serial ports
        on_newBaudListReady(tuple)           pickup new list of baudrates
        on_SerialReceivedText(bytes)         pickup text from serial port
        on_SerialReceivedLines(list)         pickup lines of text from serial port
        on_throughputReceived(int, int)      pickup throughput data from QSerial
    """

    # Signals
    ########################################################################################

    scanPortsRequest = pyqtSignal()  # port scan
    scanBaudRatesRequest = pyqtSignal()  # baudrates scan
    changePortRequest = pyqtSignal(str, int)  # port and baudrate to change
    changeBaudRequest = pyqtSignal(int)  # request serial baud rate to change
    changeLineTerminationRequest = pyqtSignal(
        bytes
    )  # request line termination to change
    sendTextRequest = pyqtSignal(bytes)  # request to transmit text to TX
    sendLineRequest = pyqtSignal(bytes)  # request to transmit one line of text to TX
    sendLinesRequest = pyqtSignal(list)  # request to transmit lines of text to TX
    startReceiverRequest = pyqtSignal()  # start serial receiver, expecting text
    stopReceiverRequest = pyqtSignal()  # stop serial receiver
    setupReceiverRequest = pyqtSignal()  # start serial receiver, expecting text
    startThroughputRequest = pyqtSignal()  # start timer to report throughput
    stopThroughputRequest = pyqtSignal()  # stop timer to report throughput
    serialStatusRequest = pyqtSignal()  # request serial port and baudrate status
    finishWorkerRequest = pyqtSignal()  # request worker to finish
    closePortRequest = pyqtSignal()  # close the current serial Port
    serialSendFileRequest = pyqtSignal(
        str
    )  # request to open file and send over serial port

    def __init__(self, parent=None, ui=None, worker=None):

        super(QSerialUI, self).__init__(parent)

        # state variables, populated by service routines
        self.defaultBaudRate = DEFAULT_BAUDRATE
        self.BaudRates = []  # e.g. (1200, 2400, 9600, 115200)
        self.serialPortNames = []  # human readable
        self.serialPorts = []  # e.g. COM6
        self.serialPort = ""  # e.g. COM6
        self.serialBaudRate = -1  # e.g. 115200
        self.serialSendHistory = []  # previously sent text (e.g. commands)
        self.serialSendHistoryIndx = -1  # init history
        self.lastNumReceived = 0  # init throughput
        self.lastNumSent = 0  # init throughput
        self.rx = 0  # init throughput
        self.tx = 0  # init throughput
        self.receiverIsRunning = False  # keep track of worker state
        self.textLineTerminator = b""  # default line termination: none
        self.encoding = "utf-8"  # default encoding
        self.serialTimeout = 0  # default timeout
        self.isScrolling = False  # keep track of text display scrolling

        self.logger = logging.getLogger("QSerUI_")

        if ui is None:
            self.logger.log(
                logging.ERROR,
                "[{}]: need to have access to User Interface".format(
                    int(QThread.currentThreadId())
                ),
            )
        self.ui = ui

        if worker is None:
            self.logger.log(
                logging.ERROR,
                "[{}]: need to have access to serial worker signals".format(
                    int(QThread.currentThreadId())
                ),
            )
        self.serialWorker = worker

        # Text display window on serial text display
        self.textScrollbar = self.ui.plainTextEdit_SerialTextDisplay.verticalScrollBar()
        self.ui.plainTextEdit_SerialTextDisplay.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )

        # Disable closing serial port button
        self.ui.pushButton_SerialOpenClose.setText("Open")
        self.ui.pushButton_SerialOpenClose.setEnabled(False)
        # Disable start button in serial monitor and chart
        self.ui.pushButton_ChartStartStop.setEnabled(False)
        self.ui.pushButton_SerialStartStop.setEnabled(False)
        self.ui.lineEdit_SerialText.setEnabled(False)
        self.ui.pushButton_SerialSend.setEnabled(False)

        # Limit the amount of text retained in the serial text display window
        # Execute a text trim function every minute
        self.textTrimTimer = QTimer(self)
        self.textTrimTimer.timeout.connect(self.serialTextDisplay_trim)
        self.textTrimTimer.start(
            10000
        )  # Trigger every 60 seconds, this halts the display for a fraction of second, so dont do it often

        # Cursor for text display window
        self.textCursor = self.ui.plainTextEdit_SerialTextDisplay.textCursor()
        self.textCursor.movePosition(QTextCursor.MoveOperation.End)
        self.ui.plainTextEdit_SerialTextDisplay.setTextCursor(self.textCursor)
        self.ui.plainTextEdit_SerialTextDisplay.ensureCursorVisible()
        self.logger.log(
            logging.INFO,
            "[{}]: QSerialUI initialized.".format(int(QThread.currentThreadId())),
        )

    # Response Functions to User Interface Signals
    ########################################################################################

    @pyqtSlot()
    def on_serialMonitorSend(self):
        """
        Transmitting text from UI to serial TX line
        """
        text = self.ui.lineEdit_SerialText.text()  # obtain text from send input window
        self.serialSendHistory.append(text)  # keep history of previously sent commands
        if self.receiverIsRunning == False:
            self.serialWorker.linesReceived.connect(
                self.on_SerialReceivedLines
            )  # connect text display to serial receiver signal
            self.serialWorker.textReceived.connect(
                self.on_SerialReceivedText
            )  # connect text display to serial receiver signal
            # self.startReceiverRequest.emit()
            # self.startThroughputRequest.emit()
            self.ui.pushButton_SerialStartStop.setText("Stop")
        text_bytearray = (
            text.encode(self.encoding) + self.textLineTerminator
        )  # add line termination
        self.sendTextRequest.emit(text_bytearray)  # send text to serial TX line
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
            self.serialSendFileRequest.emit(fname)

        self.ui.statusBar().showMessage("Text file sent.", 2000)

    @pyqtSlot()
    def on_serialMonitorSendUpArrowPressed(self):
        """
        Handle special keys on lineEdit: UpArrow
        """
        # increment history pointer
        self.serialSendHistoryIndx += 1
        # if pointer at end of buffer restart at -1
        if self.serialSendHistoryIndx == len(self.serialSendHistory):
            self.serialSendHistoryIndx = -1
        # populate with previous sent command from history buffer
        # if index is -1, use empty string as previously sent command
        if self.serialSendHistoryIndx == -1:
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
        # increment history pointer
        self.serialSendHistoryIndx -= 1
        # if pointer at start of buffer reset index to end of buffer
        if self.serialSendHistoryIndx == -2:
            self.serialSendHistoryIndx = len(self.serialSendHistory) - 1
        # populate with previous sent command from history buffer
        # if index is -1, use empty string as previously sent command
        if self.serialSendHistoryIndx == -1:
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
        self.ui.statusBar().showMessage("Text Display Cleared.", 2000)

    @pyqtSlot()
    def on_pushButton_SerialStartStop(self):
        """
        Start serial receiver
        """
        if self.ui.pushButton_SerialStartStop.text() == "Start":
            # Start text display
            self.ui.pushButton_SerialStartStop.setText("Stop")
            self.serialWorker.linesReceived.connect(
                self.on_SerialReceivedLines
            )  # connect text display to serial receiver signal
            self.serialWorker.textReceived.connect(
                self.on_SerialReceivedText
            )  # connect text display to serial receiver signal
            # self.startReceiverRequest.emit()
            # self.startThroughputRequest.emit()
            self.logger.log(
                logging.DEBUG,
                "[{}]: text display is on.".format(int(QThread.currentThreadId())),
            )
            self.ui.statusBar().showMessage("Text Display Started.", 2000)
        else:
            # End text display
            self.ui.pushButton_SerialStartStop.setText("Start")
            self.serialWorker.linesReceived.disconnect(
                self.on_SerialReceivedLines
            )  # connect text display to serial receiver signal
            self.serialWorker.textReceived.disconnect(
                self.on_SerialReceivedText
            )  # connect text display to serial receiver signal
            # self.stopReceiverRequest.emit()
            # self.stopThroughputRequest.emit()
            # if plotter is running, stop it
            # self.ui.pushButton_ChartStartStop.setText("Stop")
            # if self.ui.pushButton_ChartStartStop.text() == "Stop":
            #    self.ui.pushButton_ChartStartStop.click()
            self.logger.log(
                logging.DEBUG,
                "[{}]: text display is off.".format(int(QThread.currentThreadId())),
            )
            self.ui.statusBar().showMessage("Text Display Stopped.", 2000)

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
            "[{}]: scanning for serial ports.".format(int(QThread.currentThreadId())),
        )
        self.ui.statusBar().showMessage("Serial Port Scan requested.", 2000)

    @pyqtSlot()
    def on_pushButton_SerialOpenClose(self):
        if self.ui.pushButton_SerialOpenClose.text() == "Close":
            # Clost the serial port
            # Stop the receiver
            QTimer.singleShot(
                0, lambda: self.stopThroughputRequest.emit()
            )  # request to stop throughput
            QTimer.singleShot(
                50, lambda: self.stopReceiverRequest.emit()
            )  # request to stop serial receiver
            QTimer.singleShot(
                100, lambda: self.serialStatusRequest.emit()
            )  # request to report serial port status
            QTimer.singleShot(
                150, lambda: self.closePortRequest.emit()
            )  # request to close serial port
            # shade start button in serial monitor and chart
            self.ui.pushButton_SerialStartStop.setEnabled(False)
            self.ui.pushButton_ChartStartStop.setEnabled(False)
            # shade baud rate
            self.ui.comboBoxDropDown_BaudRates.setEnabled(False)
            # shade sending text
            self.ui.lineEdit_SerialText.setEnabled(False)
            self.ui.pushButton_SerialSend.setEnabled(False)
            self.ui.pushButton_SerialOpenClose.setText("Open")
            self.ui.statusBar().showMessage("Serial Close requested.", 2000)
        else:
            # Open the serial port
            # Start the receiver
            QTimer.singleShot(
                0,
                lambda: self.changePortRequest.emit(
                    self.serialPort, self.serialBaudRate
                ),
            )  # takes 11ms to open
            QTimer.singleShot(
                50, lambda: self.serialStatusRequest.emit()
            )  # request to report serial port status
            QTimer.singleShot(
                100, lambda: self.startReceiverRequest.emit()
            )  # request to start serial receiver
            QTimer.singleShot(
                150, lambda: self.startThroughputRequest.emit()
            )  # request to start serial receiver
            # un-shade start button in serial monitor and chart
            self.ui.pushButton_SerialStartStop.setEnabled(True)
            self.ui.pushButton_ChartStartStop.setEnabled(True)
            # un-shade baud rate
            self.ui.comboBoxDropDown_BaudRates.setEnabled(True)
            # un-shade sending text
            self.ui.lineEdit_SerialText.setEnabled(True)
            self.ui.pushButton_SerialSend.setEnabled(True)
            self.ui.pushButton_SerialOpenClose.setText("Close")
            self.ui.statusBar().showMessage("Serial Open requested.", 2000)

    @pyqtSlot()
    def on_comboBoxDropDown_SerialPorts(self):
        """
        User selected a new port on the drop down list
        """
        lenSerialPorts = len(self.serialPorts)
        lenBaudRates = len(self.BaudRates)
        if lenSerialPorts > 0:  # only continue if we have recognized serial ports
            index = self.ui.comboBoxDropDown_SerialPorts.currentIndex()
            if index == lenSerialPorts:  # "None" was selected so close the port
                self.closePortRequest.emit()
                self.serialPort = ""
                return  # do not continue
            else:
                port = self.serialPorts[index]  # we have valid port

            if lenBaudRates > 0:  # if we have recognized serial baudrates
                index = self.ui.comboBoxDropDown_BaudRates.currentIndex()
                if index < lenBaudRates:  # last entry is -1
                    baudrate = self.BaudRates[index]
                else:
                    baudrate = self.defaultBaudRate  # use default baud rate
            else:
                baudrate = (
                    self.defaultBaudRate
                )  # use default baud rate, user can change later

            # change port if port or baudrate changed
            if port != self.serialPort:
                self.serialBaudRate = baudrate
                self.serialPort = port
                QTimer.singleShot(
                    0, lambda: self.changePortRequest.emit(port, baudrate)
                )  # takes 11ms to open
                QTimer.singleShot(
                    50, lambda: self.scanBaudRatesRequest.emit()
                )  # request to scan serial baudrates
                QTimer.singleShot(
                    100, lambda: self.serialStatusRequest.emit()
                )  # request to report serial port status
                self.logger.log(
                    logging.INFO,
                    "[{}]: port {} baud {}".format(
                        int(QThread.currentThreadId()), port, baudrate
                    ),
                )
            elif port == self.serialPort:
                self.logger.log(
                    logging.INFO,
                    "[{}]: port {} baud {}".format(
                        int(QThread.currentThreadId()), port, baudrate
                    ),
                )
            elif baudrate != self.serialBaudRate:
                self.changeBaudRequest.emit(baudrate)
                self.logger.log(
                    logging.INFO,
                    "[{}]: baudrate {}".format(
                        int(QThread.currentThreadId()), baudrate
                    ),
                )
            else:
                self.logger.log(
                    logging.INFO,
                    "[{}]: port and baudrate remain the same".format(
                        int(QThread.currentThreadId()), port, baudrate
                    ),
                )

        else:
            self.logger.log(
                logging.ERROR,
                "[{}]: no ports available".format(int(QThread.currentThreadId())),
            )

        self.ui.statusBar().showMessage("Serial port change requested.", 2000)

    @pyqtSlot()
    def on_comboBoxDropDown_BaudRates(self):
        """
        User selected a different baudrate on drop down list
        """
        lenBaudRates = len(self.BaudRates)
        if lenBaudRates > 0:  # if we have recognized serial baudrates
            index = self.ui.comboBoxDropDown_BaudRates.currentIndex()
            if index < lenBaudRates:  # last entry is -1
                baudrate = self.BaudRates[index]
            else:
                baudrate = self.defaultBaudRate  # use default baud rate
            if (
                baudrate != self.serialBaudRate
            ):  # change baudrate if different from current
                self.changeBaudRequest.emit(baudrate)
                self.logger.log(
                    logging.INFO,
                    "[{}]: baudrate {}".format(
                        int(QThread.currentThreadId()), baudrate
                    ),
                )
            else:
                self.logger.log(
                    logging.INFO,
                    "[{}]: baudrate remains the same".format(
                        int(QThread.currentThreadId())
                    ),
                )
        else:
            self.logger.log(
                logging.ERROR,
                "[{}]: no baudrates available".format(int(QThread.currentThreadId())),
            )

        self.ui.statusBar().showMessage("Baudrate change requested.", 2000)

    @pyqtSlot()
    def on_comboBoxDropDown_LineTermination(self):
        """
        User selected a different line termination from drop down menu
        """
        _tmp = self.ui.comboBoxDropDown_LineTermination.currentText()
        if _tmp == "newline (\\n)":
            self.textLineTerminator = b"\n"
        elif _tmp == "return (\\r)":
            self.textLineTerminator = b"\r"
        elif _tmp == "newline return (\\n\\r)":
            self.textLineTerminator = b"\n\r"
        elif _tmp == "none":
            self.textLineTerminator = b""
        else:
            self.textLineTerminator = b"\r\n"
        self.changeLineTerminationRequest.emit(self.textLineTerminator)
        self.logger.log(
            logging.INFO,
            "[{}]: line termination {}".format(
                int(QThread.currentThreadId()), repr(self.textLineTerminator)
            ),
        )
        self.ui.statusBar().showMessage("Line Termination updated", 2000)

    # Response to Serial Signals
    ########################################################################################

    @pyqtSlot(str, int, bytes, float)
    def on_serialStatusReady(self, port: str, baud: int, eol: bytes, timeout: float):
        """
        Serial status report available
        """
        self.serialPort = port
        self.serialBaudRate = baud
        if baud <= 0:
            self.defaultBaudRate = DEFAULT_BAUDRATE
        else:
            self.defaultBaudRate = baud
        self.textLineTerminator = eol
        self.serialTimeout = timeout

        # adjust the combobox current item to match the current port
        try:
            if self.serialPort == "":
                index = self.ui.comboBoxDropDown_SerialPorts.findText(
                    "None"
                )  # find current port in serial port list
                self.ui.pushButton_ChartStartStop.setEnabled(False)
                self.ui.pushButton_SerialStartStop.setEnabled(False)
                self.ui.lineEdit_SerialText.setEnabled(False)
                self.ui.pushButton_SerialSend.setEnabled(False)
            else:
                index = self.ui.comboBoxDropDown_SerialPorts.findText(
                    self.serialPort
                )  # find current port in serial port list
                self.ui.pushButton_SerialOpenClose.setEnabled(
                    True
                )  # enable port closing button
                # self.ui.pushButton_ChartStartStop.setEnabled(True)                         # enable start/stop button for chart plotting
                # self.ui.pushButton_SerialStartStop.setEnabled(True)                        # enable start/stop button for serial monitor
                # self.ui.lineEdit_SerialText.setEnabled(True)                               # enable text input window
                # self.ui.pushButton_SerialSend.setEnabled(True)
            self.ui.comboBoxDropDown_SerialPorts.setCurrentIndex(
                index
            )  # update serial port combobox
            self.logger.log(
                logging.DEBUG,
                '[{}]: selected port "{}".'.format(
                    int(QThread.currentThreadId()), self.serialPort
                ),
            )
        except:
            self.logger.log(
                logging.ERROR,
                "[{}]: port not available.".format(int(QThread.currentThreadId())),
            )
        # adjust the combobox current item to match the current baudrate
        try:
            index = self.ui.comboBoxDropDown_BaudRates.findText(
                str(self.serialBaudRate)
            )
            self.ui.comboBoxDropDown_BaudRates.setCurrentIndex(index)  #  baud combobox
            self.logger.log(
                logging.DEBUG,
                "[{}]: selected baudrate {}.".format(
                    int(QThread.currentThreadId()), self.serialBaudRate
                ),
            )
        except:
            self.logger.log(
                logging.ERROR,
                "[{}]: no baudrate available.".format(int(QThread.currentThreadId())),
            )

        # adjust the combobox current item to match the current line termination
        if eol == b"\n":
            _tmp = "newline (\\n)"
        elif eol == b"\r":
            _tmp = "return (\\r)"
        elif eol == b"\n\r":
            _tmp = "newline return (\\n\\r)"
        elif eol == b"\r\n":
            _tmp = "return newline (\\r\\n)"
        elif eol == b"":
            _tmp = "none"
        else:
            _tmp = "return newline (\\r\\n)"
        try:
            index = self.ui.comboBoxDropDown_LineTermination.findText(_tmp)
            self.ui.comboBoxDropDown_LineTermination.setCurrentIndex(index)
            self.logger.log(
                logging.DEBUG,
                "[{}]: selected line termination {}.".format(
                    int(QThread.currentThreadId()), _tmp
                ),
            )
        except:
            self.logger.log(
                logging.ERROR,
                "[{}]: line termination not available.".format(
                    int(QThread.currentThreadId())
                ),
            )

        self.logger.log(
            logging.DEBUG,
            "[{}]: receiver is {}.".format(
                int(QThread.currentThreadId()),
                "running" if self.receiverIsRunning else "not running",
            ),
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
            "[{}]: port list received.".format(int(QThread.currentThreadId())),
        )
        self.serialPorts = ports
        self.serialPortNames = portNames
        lenPortNames = len(self.serialPortNames)
        # block the box from emitting changed index signal when items are added
        self.ui.comboBoxDropDown_SerialPorts.blockSignals(True)
        # what is currently selected in the box?
        selected = self.ui.comboBoxDropDown_SerialPorts.currentText()
        # populate new items
        self.ui.comboBoxDropDown_SerialPorts.clear()
        self.ui.comboBoxDropDown_SerialPorts.addItems(self.serialPorts + ["None"])
        # search for the previously selected item
        index = self.ui.comboBoxDropDown_SerialPorts.findText(selected)
        if index > -1:  # if we found previously selected item
            self.ui.comboBoxDropDown_SerialPorts.setCurrentIndex(index)
        else:  # if we did not find previous item set box to last item (None)
            self.ui.comboBoxDropDown_SerialPorts.setCurrentIndex(lenPortNames)
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
            "[{}]: baud list received.".format(int(QThread.currentThreadId())),
        )
        self.BaudRates = list(baudrates)
        lenBaudRates = len(self.BaudRates)
        self.ui.comboBoxDropDown_BaudRates.blockSignals(True)
        selected = self.ui.comboBoxDropDown_BaudRates.currentText()
        self.ui.comboBoxDropDown_BaudRates.clear()
        self.ui.comboBoxDropDown_BaudRates.addItems(
            [str(x) for x in self.BaudRates + [-1]]
        )
        if selected == "-1" or selected == "":
            index = self.ui.comboBoxDropDown_BaudRates.findText(
                str(self.serialBaudRate)
            )
        else:
            index = self.ui.comboBoxDropDown_BaudRates.findText(selected)
        if index > -1:
            self.ui.comboBoxDropDown_BaudRates.setCurrentIndex(index)
        else:
            self.ui.comboBoxDropDown_BaudRates.setCurrentIndex(lenBaudRates)
        self.ui.comboBoxDropDown_BaudRates.blockSignals(False)
        self.ui.statusBar().showMessage("Baudrates updated", 2000)

    @pyqtSlot(bytes)
    def on_SerialReceivedText(self, byte_array: bytes):
        """
        Received text () on serial port
        Display it in the text display window
        """
        self.logger.log(
            logging.DEBUG, "[{}]: text received.".format(int(QThread.currentThreadId()))
        )
        try:
            text = byte_array.decode(self.encoding)
            if DEBUGSERIAL:
                self.logger.log(
                    logging.DEBUG,
                    "[{}]: {}".format(int(QThread.currentThreadId()), text),
                )
            # Move cursor to the end of the document and insert text, if scrollbar is at the end, make sure text display scrolls up
            if self.textScrollbar.value() >= self.textScrollbar.maximum() - 20:
                self.isScrolling = True
            else:
                self.isScrolling = False
            self.textCursor.movePosition(QTextCursor.MoveOperation.End)
            self.textCursor.insertText(text + "\n")
            if self.isScrolling:
                self.ui.plainTextEdit_SerialTextDisplay.ensureCursorVisible()
        except:
            self.logger.log(
                logging.ERROR,
                "[{}]: could not decode text in {}.".format(
                    int(QThread.currentThreadId()), repr(byte_array)
                ),
            )

    @pyqtSlot(list)
    def on_SerialReceivedLines(self, lines: list):
        """
        Received lines of text on serial port
        Display the lines in the text display window
        """
        self.logger.log(
            logging.DEBUG,
            "[{}]: text lines received.".format(int(QThread.currentThreadId())),
        )
        # decode each line to string and join them with newline
        decoded_lines = []
        for line in lines:
            try:
                decoded_line = line.decode(self.encoding)
            except:
                decoded_line = line.decode(self.encoding, errors="replace").replace(
                    "\ufffd", "¿"
                )  # replace unknown characters with ¿
            decoded_lines.append(decoded_line)
        text = "\n".join(decoded_lines)
        # insert text at end of the document
        if self.textScrollbar.value() >= self.textScrollbar.maximum() - 20:
            self.isScrolling = True
        else:
            self.isScrolling = False
        self.textCursor.movePosition(QTextCursor.MoveOperation.End)
        self.textCursor.insertText(text + "\n")
        if self.isScrolling:
            self.ui.plainTextEdit_SerialTextDisplay.ensureCursorVisible()

    @pyqtSlot(bool)
    def on_serialWorkerStateChanged(self, running: bool):
        """
        Serial worker was started or stopped
        """
        self.logger.log(
            logging.DEBUG,
            "[{}]: serial worker is {}.".format(
                int(QThread.currentThreadId()), "on" if running else "off"
            ),
        )
        self.receiverIsRunning = running
        if running:
            # self.ui.pushButton_SerialStartStop.setText("Stop")
            # self.ui.pushButton_ChartStartStop.setText("Stop")
            self.ui.statusBar().showMessage("Serial Worker started", 2000)
        else:
            # self.ui.pushButton_SerialStartStop.setText("Start")
            # self.ui.pushButton_ChartStartStop.setText("Start")
            self.ui.statusBar().showMessage("Serial Worker stopped", 2000)

    def on_throughputReceived(self, numReceived, numSent):
        """
        Report throughput
        """
        rx = numReceived - self.lastNumReceived
        tx = numSent - self.lastNumSent
        if rx < 0:
            rx = (
                self.rx
            )  # self.lastNumReceived is not cleared when we clear the serial buffer, take care of it here
        if tx < 0:
            tx = self.tx
        # poor man's low pass
        self.rx = 0.5 * self.rx + 0.5 * rx
        self.tx = 0.5 * self.tx + 0.5 * tx
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
        # Where is the scrollbar?
        scrollbarMax = self.textScrollbar.maximum()
        if scrollbarMax != 0:
            proportion = self.textScrollbar.value() / scrollbarMax
        else:
            proportion = 1.0
        # How much do we need to trim?
        current_text = self.ui.plainTextEdit_SerialTextDisplay.toPlainText()
        len_current_text = len(current_text)
        numCharstoTrim = len_current_text - MAX_TEXTBROWSER_LENGTH
        if numCharstoTrim > 0:
            # Select the text to remove
            self.textCursor.setPosition(0)
            self.textCursor.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.KeepAnchor,
                numCharstoTrim,
            )
            # Remove the selected text
            self.textCursor.removeSelectedText()
            self.textCursor.movePosition(QTextCursor.MoveOperation.End)
            # update scrollbar position
            new_max = self.textScrollbar.maximum()
            new_value = round(proportion * new_max)
            self.textScrollbar.setValue(new_value)
            if new_value >= new_max - 20:
                self.ui.plainTextEdit_SerialTextDisplay.ensureCursorVisible()
        self.ui.statusBar().showMessage("Trimmed Text Display Window", 2000)


############################################################################################
# Q Serial
# ========
# separate thread handling serial input and output
# these routines have no access to the user interface,
# communication occurs through signals
#
# for serial write we send bytes
# for serial read we receive bytes
# conversion from text to bytes occurs in QSerialUI
############################################################################################


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
        on_changePortRequest(str, int)   worker received request to change port
        on_changeLineTerminationRequest(bytes)
                                         worker received request to change line termination
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
    textReceived = pyqtSignal(bytes)  # text received on serial port
    linesReceived = pyqtSignal(list)  # lines of text received on serial port
    newPortListReady = pyqtSignal(
        list, list
    )  # updated list of serial ports is available
    newBaudListReady = pyqtSignal(tuple)  # updated list of baudrates is available
    serialStatusReady = pyqtSignal(str, int, bytes, float)  # serial status is available
    throughputReady = pyqtSignal(
        int, int
    )  # number of characters received/sent on serial port
    serialWorkerStateChanged = pyqtSignal(bool)  # worker started or stopped
    finished = pyqtSignal()

    def __init__(self, parent=None):

        super(QSerial, self).__init__(parent)

        self.logger = logging.getLogger("QSerial")

        self.PSer = PSerial()
        self.PSer.scanports()
        self.serialPorts = [sublist[0] for sublist in self.PSer.ports]  # COM3 ...
        self.serialPortNames = [
            sublist[1] for sublist in self.PSer.ports
        ]  # USB ... (COM3)
        self.serialBaudRates = self.PSer.baudrates

        self.textLineTerminator = b"\r\n"  # default line termination

        # Adjust response time
        # Fastest serial baud rate is 5,000,000 bits per second
        # Regular serial baud rate is   115,200 bits per second OR 5000000
        # Slow serial baud rate is        9,600 bits per second
        # Transmitting one byte with 8N1 (8 data bits, no stop bit, one stop bit) might take up to 10 bits
        # Transmitting two int16 like "-8192, -8191\r\n" takes 14 bytes (3 times more than the actual numbers)
        # This would result in receiving 1k lines/second with 115200 and 40k lines/second with 5,000,000
        # These numbers are now updated with a function based on baud rate, see further below
        self.receiverInterval = MIN_RECEIVER_INTERVAL  # in milliseconds
        self.receiverIntervalStandby = 10 * MIN_RECEIVER_INTERVAL  # in milliseconds
        self.serialReadTimeOut = 0  # in seconds
        self.serialReceiverCountDown = 0  # initialize

        self.logger.log(
            logging.INFO,
            "[{}]: QSerial initialized.".format(int(QThread.currentThreadId())),
        )

    # Slots
    ########################################################################################

    @pyqtSlot()
    def on_setupReceiverRequest(self):
        """
        Set up a QTimer for reading data from serial input line at predefined interval.
        This does not start the timer.
        We can not create the timer in the init function because we will not move QSerial
         to a new thread and the timer would not move with it.

        Set up QTimer for throughput measurements
        """

        # if DEBUGPY_ENABLED: debugpy.debug_this_thread() # this should enable debugging of all methods QSerial methods

        # setup the receiver timer
        self.serialReceiverState = (
            SerialReceiverState.stopped
        )  # initialize state machine
        self.receiverTimer = QTimer()
        self.receiverTimer.timeout.connect(self.updateReceiver)
        self.logger.log(
            logging.INFO,
            "[{}]: Setup receiver timer.".format(int(QThread.currentThreadId())),
        )

        # setup the receiver timer
        self.throughputTimer = QTimer(self)
        self.throughputTimer.setInterval(1000)
        self.throughputTimer.timeout.connect(self.on_throughputTimer)
        self.logger.log(
            logging.INFO,
            "[{}]: Setup throughput timer.".format(int(QThread.currentThreadId())),
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
        self.logger.log(
            logging.INFO,
            "[{}]: Started receiver.".format(int(QThread.currentThreadId())),
        )

    @pyqtSlot()
    def on_stopReceiverRequest(self):
        """
        Stop the receiver timer
        """
        self.receiverTimer.stop()
        self.serialReceiverState = SerialReceiverState.stopped
        self.serialWorkerStateChanged.emit(False)  # serial worker not running
        self.logger.log(
            logging.INFO,
            "[{}]: Stopped receiver.".format(int(QThread.currentThreadId())),
        )

    @pyqtSlot()
    def on_startThroughputRequest(self):
        """
        Stop QTimer for reading through put from PSer)
        """
        self.throughputTimer.start()
        self.logger.log(
            logging.INFO,
            "[{}]: Started throughput timer.".format(int(QThread.currentThreadId())),
        )

    @pyqtSlot()
    def on_stopThroughputRequest(self):
        """
        Stop QTimer for reading through put from PSer)
        """
        self.throughputTimer.stop()
        self.logger.log(
            logging.INFO,
            "[{}]: Stopped throughput timer.".format(int(QThread.currentThreadId())),
        )

    @pyqtSlot()
    def updateReceiver(self):
        """
        Reading lines of text from serial RX
        """
        if self.serialReceiverState != SerialReceiverState.stopped:
            start_time = time.perf_counter()

            # Check if end-of-line handling is needed
            if self.PSer.eol:  # non empty byte array
                # reading lines
                # -------------
                lines = self.PSer.readlines()  # Read lines until buffer is empty
                end_time = time.perf_counter()

                if lines:
                    self.logger.log(
                        logging.DEBUG,
                        "[{}]: {} lines {:.3f} ms per line.".format(
                            int(QThread.currentThreadId()),
                            len(lines),
                            1000 * (end_time - start_time) / len(lines),
                        ),
                    )
                    if DEBUGSERIAL:
                        self.logger.log(
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
                        self.logger.log(
                            logging.INFO,
                            "[{}]: Receiving started, set faster update rate.".format(
                                int(QThread.currentThreadId())
                            ),
                        )

                    self.serialReceiverCountDown = 0
                    self.linesReceived.emit(lines)

                else:
                    if self.serialReceiverState == SerialReceiverState.receivingData:
                        self.serialReceiverCountDown += 1
                        if self.serialReceiverCountDown >= RECEIVER_FINISHCOUNT:
                            self.serialReceiverState = SerialReceiverState.awaitingData
                            self.receiverTimer.setInterval(self.receiverIntervalStandby)
                            self.serialReceiverCountDown = 0
                            self.logger.log(
                                logging.INFO,
                                "[{}]: Receiving finished, set slower update rate.".format(
                                    int(QThread.currentThreadId())
                                ),
                            )

            else:
                # reading raw bytes
                # -----------------
                byte_array = self.PSer.read()
                end_time = time.perf_counter()
                if byte_array:
                    duration = 1000 * (end_time - start_time) / len(byte_array)
                else:
                    duration = 0
                self.logger.log(
                    logging.DEBUG,
                    "[{}]: {} bytes {:.3f} ms per line.".format(
                        int(QThread.currentThreadId()), len(byte_array), duration
                    ),
                )

                self.textReceived.emit(byte_array)

        else:
            self.logger.log(
                logging.ERROR,
                "[{}]: Receiver is stopped or port is not open.".format(
                    int(QThread.currentThreadId())
                ),
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
        self.logger.log(
            logging.INFO,
            "[{}]: Stopped timer, closed port.".format(int(QThread.currentThreadId())),
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
                self.logger.log(
                    logging.DEBUG,
                    '[{}]: Transmitted "{}" [{} of {}].'.format(
                        int(QThread.currentThreadId()),
                        byte_array.decode("utf-8"),
                        l,
                        l_ba,
                    ),
                )
            else:
                self.logger.log(
                    logging.DEBUG,
                    "[{}]: Transmitted {} of {} bytes.".format(
                        int(QThread.currentThreadId()), l, l_ba
                    ),
                )
        else:
            self.logger.log(
                logging.ERROR,
                "[{}]: Tx, port not opened.".format(int(QThread.currentThreadId())),
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
                self.logger.log(
                    logging.DEBUG,
                    '[{}]: Transmitted "{}" [{} of {}].'.format(
                        int(QThread.currentThreadId()),
                        byte_array.decode("utf-8"),
                        l,
                        l_ba,
                    ),
                )
            else:
                self.logger.log(
                    logging.DEBUG,
                    "[{}]: Transmitted {} of {} bytes.".format(
                        int(QThread.currentThreadId()), l, l_ba
                    ),
                )
        else:
            self.logger.log(
                logging.ERROR,
                "[{}]: Tx, port not opened.".format(int(QThread.currentThreadId())),
            )

    @pyqtSlot(list)
    def on_sendLinesRequest(self, lines: list):
        """
        Request to transmit multiple lines of text to serial TX line
        """
        if self.PSer.connected:
            l = self.PSer.writelines(lines)
            self.logger.log(
                logging.DEBUG,
                "[{}]: Transmitted {} bytes.".format(int(QThread.currentThreadId()), l),
            )
        else:
            self.logger.log(
                logging.ERROR,
                "[{}]: Tx, port not opened.".format(int(QThread.currentThreadId())),
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
                        self.logger.log(
                            logging.DEBUG,
                            '[{}]: Transmitted "{}" [{}].'.format(
                                int(QThread.currentThreadId()), fname, l
                            ),
                        )
                    except:
                        self.logger.log(
                            logging.ERROR,
                            '[{}]: Error transmitting "{}".'.format(
                                int(QThread.currentThreadId()), fname
                            ),
                        )
            else:
                self.logger.log(
                    logging.WARNING,
                    "[{}]: No file name provided.".format(
                        int(QThread.currentThreadId())
                    ),
                )
        else:
            self.logger.log(
                logging.ERROR,
                "[{}]: Tx, port not opened.".format(int(QThread.currentThreadId())),
            )

    @pyqtSlot(str, int)
    def on_changePortRequest(self, port: str, baud: int):
        """
        Request to change port received
        """
        if port != "":
            self.PSer.close()
            serialReadTimeOut, receiverInterval, receiverIntervalStandby = (
                compute_timeouts(baud)
            )
            if self.PSer.open(
                port=port,
                baud=baud,
                eol=self.textLineTerminator,
                timeout=serialReadTimeOut,
            ):
                self.serialReadTimeOut = serialReadTimeOut
                self.receiverInterval = receiverInterval
                self.receiverIntervalStandby = receiverIntervalStandby
                self.receiverTimer.setInterval(self.receiverInterval)
                self.logger.log(
                    logging.INFO,
                    "[{}]: Port {} opened with baud {} eol {} and timeout {}.".format(
                        int(QThread.currentThreadId()),
                        port,
                        baud,
                        repr(self.textLineTerminator),
                        self.PSer.timeout,
                    ),
                )
            else:
                self.logger.log(
                    logging.ERROR,
                    "[{}]: Failed to open port {}.".format(
                        int(QThread.currentThreadId()), port
                    ),
                )
        else:
            self.logger.log(
                logging.ERROR,
                "[{}]: Port not provided.".format(int(QThread.currentThreadId())),
            )

    @pyqtSlot()
    def on_closePortRequest(self):
        """
        Request to close port received
        """
        self.PSer.close()

    @pyqtSlot(int)
    def on_changeBaudRateRequest(self, baud: int):
        """
        New baudrate received
        """
        if (baud is None) or (baud <= 0):
            self.logger.log(
                logging.WARNING,
                "[{}]: Range error, baudrate not changed to {},".format(
                    int(QThread.currentThreadId()), baud
                ),
            )
        else:
            serialReadTimeOut, receiverInterval, receiverIntervalStandby = (
                compute_timeouts(baud)
            )
            if self.PSer.connected:
                if (
                    self.serialBaudRates.index(baud) >= 0
                ):  # check if baud rate is available by searching for its index in the baud rate list
                    self.PSer.changeport(
                        self.PSer.port,
                        baud,
                        eol=self.textLineTerminator,
                        timeout=serialReadTimeOut,
                    )
                    if (
                        self.PSer.baud == baud
                    ):  # check if new value matches desired value
                        self.serialReadTimeOut = serialReadTimeOut
                        # self.serialBaudRate = baud  # update local variable
                        self.receiverInterval = receiverInterval
                        self.receiverIntervalStandby = receiverIntervalStandby
                        self.receiverTimer.setInterval(self.receiverInterval)
                    else:
                        # self.serialBaudRate = self.PSer.baud
                        self.logger.log(
                            logging.ERROR,
                            "[{}]: Failed to set baudrate to {}.".format(
                                int(QThread.currentThreadId()), baud
                            ),
                        )
                else:
                    self.logger.log(
                        logging.ERROR,
                        "[{}]: Baudrate {} not available.".format(
                            int(QThread.currentThreadId()), baud
                        ),
                    )
                    # self.serialBaudRate = -1
            else:
                self.logger.log(
                    logging.ERROR,
                    "[{}]: Failed to set baudrate, serial port not open!".format(
                        int(QThread.currentThreadId())
                    ),
                )

    @pyqtSlot(bytes)
    def on_changeLineTerminationRequest(self, lineTermination: bytes):
        """
        New LineTermination received
        """
        if lineTermination is None:
            self.logger.log(
                logging.WARNING,
                "[{}]: Line termination not changed, line termination string not provided.".format(
                    int(QThread.currentThreadId())
                ),
            )
            return
        else:
            self.PSer.eol = lineTermination
            self.textLineTerminator = lineTermination
            self.logger.log(
                logging.INFO,
                "[{}]: Changed line termination to {}.".format(
                    int(QThread.currentThreadId()), repr(self.textLineTerminator)
                ),
            )

    @pyqtSlot()
    def on_scanPortsRequest(self):
        """
        Request to scan for serial ports received
        """
        if self.PSer.scanports() > 0:
            self.serialPorts = [sublist[0] for sublist in self.PSer.ports]
            self.serialPortNames = [sublist[1] for sublist in self.PSer.ports]
        else:
            self.serialPorts = []
            self.serialPortNames = []
        self.logger.log(
            logging.INFO,
            "[{}]: Port(s) {} available.".format(
                int(QThread.currentThreadId()), self.serialPortNames
            ),
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
            self.logger.log(
                logging.INFO,
                "[{}]: Baudrate(s) {} available.".format(
                    int(QThread.currentThreadId()), self.serialBaudRates
                ),
            )
        else:
            self.logger.log(
                logging.WARNING,
                "[{}]: No baudrates available, port is closed.".format(
                    int(QThread.currentThreadId())
                ),
            )
        self.newBaudListReady.emit(self.serialBaudRates)

    @pyqtSlot()
    def on_serialStatusRequest(self):
        """
        Request to report of serial status received
        """
        self.logger.log(
            logging.INFO,
            "[{}]: Provided serial status".format(int(QThread.currentThreadId())),
        )
        if self.PSer.connected:
            self.serialStatusReady.emit(
                self.PSer.port, self.PSer.baud, self.PSer.eol, self.PSer.timeout
            )
        else:
            self.serialStatusReady.emit(
                "", self.PSer.baud, self.PSer.eol, self.PSer.timeout
            )


def compute_timeouts(baud: int, chars_per_line: int = 50):
    # Set timeout to the amount of time it takes to receive the shortest expected line of text
    # integer '123/n/r' 5 bytes, which is at least 45 serial bits
    # serialReadTimeOut = 40 / baud [s] is very small and we should just set it to zero (non blocking)
    serialReadTimeOut = 0  # make it non blocking

    # Set the QTimer interval so that each call we get a couple of lines
    # lets assume we receive 5 integers in one line each with a legenf, this is approx 50 bytes,
    # lets use 10 serial bits per byte
    # lets request NUM_LINES_COLLATE lines per call
    receiverInterval = ceil(
        NUM_LINES_COLLATE * chars_per_line * 10 / baud * 1000
    )  # in milliseconds
    receiverIntervalStandby = 10 * receiverInterval  # make standby 10 times slower

    # check serial should occur no more than 200 times per second no less than 10 times per second
    if receiverInterval < MIN_RECEIVER_INTERVAL:
        receiverInterval = MIN_RECEIVER_INTERVAL
    if receiverIntervalStandby < MIN_RECEIVER_INTERVAL:
        receiverIntervalStandby = MIN_RECEIVER_INTERVAL
    if receiverInterval > MAX_RECEIVER_INTERVAL:
        receiverInterval = MAX_RECEIVER_INTERVAL
    if receiverIntervalStandby > MAX_RECEIVER_INTERVAL:
        receiverIntervalStandby = MAX_RECEIVER_INTERVAL

    return serialReadTimeOut, receiverInterval, receiverIntervalStandby


################################################################################
# Serial Low Level
################################################################################


class PSerial:
    """
    Serial Wrapper.

    read returns bytes or list of bytes
    write expects bytes or list of bytes
    """

    def __init__(self):
        # if DEBUGPY_ENABLED: debugpy.debug_this_thread() # this should enable debugging of all PSerial methods

        self.logger = logging.getLogger("PSerial")
        self.ser = None
        self._port = ""
        self._baud = -1
        self._eol = b""
        self._timeout = -1
        self._ser_open = False
        self.totalCharsReceived = 0
        self.totalCharsSent = 0
        self.partialLine = b""
        self.havePartialLine = False
        # check for serial ports
        _ = self.scanports()

    def scanports(self) -> int:
        """
        scans for all available ports
        """
        self._ports = [[p.device, p.description] for p in list_ports.comports()]
        return len(self._ports)

    def open(self, port: str, baud: int, eol: bytes, timeout: float) -> bool:
        """open specified port"""
        try:
            self.ser = sp(
                port=port,  # the serial device
                baudrate=baud,  # often 115200 but Teensy sends/receives as fast as possible
                bytesize=EIGHTBITS,  # most common option
                parity=PARITY_NONE,  # most common option
                stopbits=STOPBITS_ONE,  # most common option
                timeout=timeout,  # wait until requested characters are received on read request or timeout occurs
                write_timeout=timeout,  # wait until requested characters are sent
                inter_byte_timeout=None,  # disable inter character timeout
                rtscts=False,  # do not use 'request to send' and 'clear to send' handshaking
                dsrdtr=False,  # dont want 'data set ready' signaling
                exclusive=None,  # do not share port in POSIX
                xonxoff=False,  # dont have 'xon/xoff' hand shaking in serial data stream
            )
        except:
            self._ser_open = False
            self.ser = None
            self._port = ""
            self.logger.log(
                logging.ERROR,
                "[SER {}]: Failed to open port {}.".format(
                    int(QThread.currentThreadId()), port
                ),
            )
            return False
        else:
            self.logger.log(
                logging.DEBUG,
                "[SER {}]: {} opened with baud {}.".format(
                    int(QThread.currentThreadId()), port, baud
                ),
            )
            self._ser_open = True
            self._baud = baud
            self._port = port
            self._timeout = timeout
            self._eol = eol
            self._leneol = len(eol)
            # clear buffers
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            self.totalCharsReceived = 0
            self.totalCharsSent = 0
            self.partialLine = b""
            self.havePartialLine = False
            return True

    def close(self):
        """
        closes serial port

        we have issue in closing textIOwrapped serial port, somehow it claims to be already closed
        """

        if (self.ser is not None) and self._ser_open:
            # close the port
            try:
                # clear buffers
                self.ser.reset_input_buffer()
            except:
                self.logger.log(
                    logging.ERROR,
                    "[SER {}]: failed to clear input buffer.".format(
                        int(QThread.currentThreadId())
                    ),
                )
            try:
                # clear buffers
                self.ser.reset_output_buffer()
            except:
                self.logger.log(
                    logging.ERROR,
                    "[SER {}]: failed to clear output buffer.".format(
                        int(QThread.currentThreadId())
                    ),
                )
            try:
                self.ser.close()
            except:
                self.logger.log(
                    logging.ERROR,
                    "[SER {}]: failed to complete closure.".format(
                        int(QThread.currentThreadId())
                    ),
                )
            self._port = ""
        self.logger.log(
            logging.INFO, "[SER {}]: Closed.".format(int(QThread.currentThreadId()))
        )
        self._ser_open = False

    def changeport(self, port: str, baud: int, eol: bytes, timeout: float):
        """switch to different port"""
        self.close()
        self.open(
            port=port, baud=baud, eol=eol, timeout=timeout
        )  # open also clears the buffers
        self.logger.log(
            logging.INFO,
            "[SER {}]: Changed port to {} with baud {} and eol {}".format(
                int(QThread.currentThreadId()), port, baud, repr(eol)
            ),
        )

    def read(self) -> bytes:
        """reads serial buffer until empty"""
        startTime = time.perf_counter()
        if self._ser_open:
            bytes_to_read = self.ser.in_waiting
            if bytes_to_read:
                byte_array = self.ser.read(bytes_to_read)
                self.totalCharsReceived += bytes_to_read
                endTime = time.perf_counter()
                self.logger.log(
                    logging.DEBUG,
                    "[SER {}]: Read {} bytes in {} ms.".format(
                        int(QThread.currentThreadId()),
                        bytes_to_read,
                        1000 * (endTime - startTime),
                    ),
                )
                return byte_array
            else:
                endTime = time.perf_counter()
                # self.logger.log(logging.DEBUG, "[SER {}]: End of read, buffer empty. tic toc {}.".format(int(QThread.currentThreadId()),endTime-startTime))
                return b""
        else:
            self.logger.log(
                logging.ERROR,
                "[SER {}]: Serial Port not available.".format(
                    int(QThread.currentThreadId())
                ),
            )
            return b""

    def readline(self) -> bytes:
        """
        reads one line of text
        this will not work if the read completed before reading the line termination characters
        then the merged line will include the line termination characters
        to avoid this the read timeout can not be set to zero or this function should not be used.
        """
        startTime = time.perf_counter()
        if self._ser_open:
            _line = self.ser.read_until(self._eol)  # _line includes the delimiter
            self.totalCharsReceived += len(_line)
            if _line:
                # received text
                if _line.endswith(self._eol):
                    # have complete line
                    if self.havePartialLine:
                        # merge previous partial line with current line
                        line = self.partialLine + _line[: -self._leneol]
                        self.havePartialLine = False
                        self.partialLine = b""
                    else:
                        line = _line[: -self._leneol]
                else:
                    # have partial line
                    self.partialLine = _line  # save partial line
                    self.havePartialLine = True
                    line = b""
            endTime = time.perf_counter()
            self.logger.log(
                logging.DEBUG,
                "[SER {}]: read line in {} ms.".format(
                    int(QThread.currentThreadId()), 1000 * (endTime - startTime)
                ),
            )
            return line.rstrip(self._eol)
        else:
            self.logger.log(
                logging.ERROR,
                "[SER {}]: Serial Port not available.".format(
                    int(QThread.currentThreadId())
                ),
            )
            return b""

    def readlines(self) -> list:
        """
        Reads the serial buffer and converts it into lines of text.

        1. Read all bytes from the serial buffer.
        2. Find the rightmost position of the line termination characters.
        3. If line termination is found:
          3.1 Split the byte array into lines.
          3.2 Merge any existing partial line with the first line.
          3.3 Handle partial delimiters by splitting the merged line.
          3.4 Store any remainder as the new partial line.
        4. If no line termination is found, add the byte array to the partial line array.
        """

        lines = []
        startTime = time.perf_counter()

        if self._ser_open:
            bytes_to_read = self.ser.in_waiting
            if bytes_to_read > 0:
                byte_array = self.ser.read(bytes_to_read)
                self.totalCharsReceived += bytes_to_read
            else:
                return []  # Return empty list if buffer is empty

            idx = byte_array.rfind(self._eol)
            if idx == -1:
                # No delimiter found, add to partial line
                self.partialLine += byte_array
                self.havePartialLine = True
            else:
                # Delimiter found, split byte array into lines
                lines = byte_array.split(self._eol)

                if self.havePartialLine:
                    # Merge previous partial line with the first line
                    merged_line = self.partialLine + lines[0]
                    lines = merged_line.split(self._eol) + lines[1:]
                    self.havePartialLine = False
                    self.partialLine = b""

                # Check for remaining bytes after the last delimiter
                e = idx + self._leneol
                if e < len(byte_array):
                    # Remainder exists, set as new partial line
                    self.partialLine = byte_array[e:]
                    self.havePartialLine = True
                    lines = lines[:-1]  # Remove the partial line from the list

                # Remove empty lines at the start or end
                if lines:
                    if lines[-1] == b"":
                        lines = lines[:-1]
                    if lines[0] == b"":
                        lines = lines[1:]

            endTime = time.perf_counter()
            self.logger.log(
                logging.DEBUG,
                "[SER {}]: Read {} bytes in {} ms.".format(
                    int(QThread.currentThreadId()),
                    bytes_to_read,
                    1000 * (endTime - startTime),
                ),
            )

            return lines
        else:
            self.logger.log(
                logging.ERROR,
                "[SER {}]: Serial Port not available.".format(
                    int(QThread.currentThreadId())
                ),
            )
            return []

    def write(self, byte_array: bytes) -> int:
        """sends an array of bytes"""
        if self._ser_open:
            try:
                l = self.ser.write(byte_array)
                self.totalCharsSent += l
                if DEBUGSERIAL:
                    l_ba = len(byte_array)
                    decimal_values = " ".join(str(byte) for byte in byte_array)
                    self.logger.log(
                        logging.DEBUG,
                        "[SER write {}]: Wrote {} of {} bytes. {}".format(
                            int(QThread.currentThreadId()), l, l_ba, decimal_values
                        ),
                    )
                return l
            except:
                self.logger.log(
                    logging.ERROR,
                    "[SER write {}]: Failed to write with timeout {}.".format(
                        int(QThread.currentThreadId()), self.timeout
                    ),
                )
                return l
        else:
            self.logger.log(
                logging.ERROR,
                "[SER write {}]: Serial Port not available.".format(
                    int(QThread.currentThreadId())
                ),
            )
            return 0

    def writeline(self, byte_array: bytes) -> int:
        """sends an array of bytes + eol"""
        if self._ser_open:
            try:
                l = self.ser.write(byte_array + self._eol)
                self.totalCharsSent += l
                if DEBUGSERIAL:
                    l_ba = len(byte_array)
                    l_eol = len(self._eol)
                    decimal_values = " ".join(str(byte) for byte in byte_array)
                    self.logger.log(
                        logging.DEBUG,
                        "[SER writeline {}]: Wrote {} of {}+{} bytes. {}".format(
                            int(QThread.currentThreadId()),
                            l,
                            l_ba,
                            l_eol,
                            decimal_values,
                        ),
                    )
                return l
            except:
                self.logger.log(
                    logging.ERROR,
                    "[SER writeline {}]: Failed to write with timeout {}.".format(
                        int(QThread.currentThreadId()), self.timeout
                    ),
                )
                return l
        else:
            self.logger.log(
                logging.ERROR,
                "[SER writeline {}]: Serial Port not available.".format(
                    int(QThread.currentThreadId())
                ),
            )
            return 0

    def writelines(self, lines: list) -> int:
        """sends several lines of text, append eol to each line"""
        byte_array = self._eol.join(line for line in lines)
        if self._ser_open:
            try:
                l = self.ser.write(byte_array)
                self.totalCharsSent += l
                if DEBUGSERIAL:
                    self.logger.log(
                        logging.DEBUG,
                        "[SER {}]: Wrote {} chars.".format(
                            int(QThread.currentThreadId()), l
                        ),
                    )
                return l
            except:
                self.logger.log(
                    logging.ERROR,
                    "[SER {}]: Failed to write with timeout {}.".format(
                        int(QThread.currentThreadId()), self.timeout
                    ),
                )
                return l
        else:
            self.logger.log(
                logging.ERROR,
                "[SER {}]: Serial Port not available.".format(
                    int(QThread.currentThreadId())
                ),
            )
            return 0

    def avail(self) -> int:
        """is there data in the serial receiving buffer?"""
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
            self.totalCharsReceived = 0
            self.totalCharsSent = 0

    # Setting and reading internal variables
    ########################################################################################

    @property
    def ports(self):
        """returns list of ports"""
        return self._ports

    @property
    def baudrates(self):
        """returns list of baudrates"""
        if self._ser_open:
            if max(self.ser.BAUDRATES) <= 115200:
                # add higher baudrates to the list
                return self.ser.BAUDRATES + (
                    230400,
                    250000,
                    460800,
                    500000,
                    921600,
                    1000000,
                    2000000,
                )
            return self.ser.BAUDRATES
        else:
            return ()

    @property
    def connected(self):
        """return true if connected"""
        return self._ser_open

    @property
    def port(self):
        """returns current port"""
        if self._ser_open:
            return self._port
        else:
            return ""

    @port.setter
    def port(self, val):
        """sets serial port"""
        if (val is None) or (val == ""):
            self.logger.log(
                logging.WARNING,
                "[SER {}]: No port given {}.".format(
                    int(QThread.currentThreadId()), val
                ),
            )
            return
        else:
            # change the port, clears the buffers
            if self.changeport(self, val, self.baud):
                self.logger.log(
                    logging.DEBUG,
                    "[SER {}]: Port:{}.".format(int(QThread.currentThreadId()), val),
                )
                self._port = val
            else:
                self.logger.log(
                    logging.ERROR,
                    "[SER {}]: Failed to open port {}.".format(
                        int(QThread.currentThreadId()), val
                    ),
                )

    @property
    def baud(self):
        """returns current serial baudrate"""
        if self._ser_open:
            return self._baud
        else:
            return -1

    @baud.setter
    def baud(self, val):
        """sets serial baud rate"""
        if (val is None) or (val <= 0):
            self.logger.log(
                logging.WARNING,
                "[SER {}]: Baudrate not changed to {}.".format(
                    int(QThread.currentThreadId()), val
                ),
            )
            return
        if self._ser_open:
            self.ser.baudrate = val  # set new baudrate
            self._baud = self.ser.baudrate  # request baudrate
            if self._baud == val:
                self.logger.log(
                    logging.DEBUG,
                    "[SER {}]: Baudrate:{}.".format(
                        int(QThread.currentThreadId()), val
                    ),
                )
            else:
                self.logger.log(
                    logging.ERROR,
                    "[SER {}]: Failed to set baudrate to {}.".format(
                        int(QThread.currentThreadId()), val
                    ),
                )
            # clear buffers
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        else:
            self.logger.log(
                logging.ERROR,
                "[SER {}]: Failed to set baudrate, serial port not open!".format(
                    int(QThread.currentThreadId())
                ),
            )

    @property
    def eol(self):
        """returns current line termination"""
        return self._eol

    @eol.setter
    def eol(self, val):
        """sets serial ioWrapper line termination"""
        if val is None:
            self.logger.log(
                logging.WARNING,
                "[SER {}]: EOL not changed, need to provide string.".format(
                    int(QThread.currentThreadId())
                ),
            )
            return
        else:
            self._eol = val
            # self._eol = ""
            self.logger.log(
                logging.ERROR,
                "[SER {}]: EOL: {}".format(int(QThread.currentThreadId()), repr(val)),
            )

    @property
    def timeout(self):
        """returns current serial timeout"""
        return self._timeout


#####################################################################################
# Testing
#####################################################################################

if __name__ == "__main__":
    # not implemented
    pass