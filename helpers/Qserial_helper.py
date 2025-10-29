############################################################################################################################################
# QT Serial Helper
#
# QSerial:        Controller  - Interface to GUI, runs in main thread.
# Serial:         Model       - Functions interfacing to serial port and running in a separate thread, 
#                               communication through signals and slots with QSerial.
#
# This code is maintained by Urs Utzinger
############################################################################################################################################

# ==============================================================================
# Configuration
# ==============================================================================
from config import (PROFILEME, DEBUGSERIAL, DEBUG_LEVEL,
                    FLUSH_INTERVAL_MS,
                    DEFAULT_BAUDRATE, SERIAL_BUFFER_SIZE,
                    EOL_DICT, EOL_DICT_INV, EOL_DEFAULT_BYTES, EOL_DEFAULT_LABEL,
                    DEFAULT_TEXT_LINES,
                    MAX_DATAREADYCALLS, MAX_EOL_DETECTION_TIME, MAX_EOL_FALLBACK_TIMEOUT,
                    MAX_BACKLOG_BYTES
                    )
# ==============================================================================
# Imports
# ==============================================================================
import time
import logging
import textwrap
from pathlib import Path
#
import numpy as np
#
from difflib import SequenceMatcher
#
# Custom Imports
# ----------------------------------------
from helpers.IncompleteHTMLTracker import IncompleteHTMLTracker
from helpers.General_helper import wait_for_signal, connect, disconnect, qobject_alive
#
# QT Libraries
# ----------------------------------------
try: 
    from PyQt6.QtCore import (
        Qt, QObject, QTimer, QThread, pyqtSignal, pyqtSlot,
        QByteArray, QIODevice, QCoreApplication, 
    )
    from PyQt6.QtGui        import QTextCursor
    from PyQt6.QtWidgets    import QMessageBox
    from PyQt6.QtSerialPort import QSerialPort, QSerialPortInfo
    ConnectionType= Qt.ConnectionType
    PreciseTimerType = Qt.TimerType.PreciseTimer
    OpenModeReadWrite = QIODevice.OpenModeFlag.ReadWrite
    ClearAllDirections = QSerialPort.Direction.AllDirections
    CursorEnd = QTextCursor.MoveOperation.End
    DataBits8 = QSerialPort.DataBits.Data8
    ParityNone = QSerialPort.Parity.NoParity
    StopBitsOne = QSerialPort.StopBits.OneStop
    FlowControlNone = QSerialPort.FlowControl.NoFlowControl
    Serial_NoError = QSerialPort.SerialPortError.NoError
    MessageBox_Yes, MessageBox_No = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
    MessageBox_Default = QMessageBox.StandardButton.Yes
except Exception:
    from PyQt5.QtCore import (
        Qt,QObject, QTimer, QThread, pyqtSignal, pyqtSlot,
        QByteArray, QIODevice, QCoreApplication, 
    )
    from PyQt5.QtGui        import QTextCursor
    from PyQt5.QtWidgets    import QMessageBox
    from PyQt5.QtSerialPort import QSerialPort, QSerialPortInfo
    ConnectionType = Qt
    PreciseTimerType = Qt.PreciseTimer
    OpenModeReadWrite = QIODevice.ReadWrite
    ClearAllDirections = QSerialPort.AllDirections
    CursorEnd = QTextCursor.End
    DataBits8 = QSerialPort.Data8
    ParityNone = QSerialPort.NoParity
    StopBitsOne = QSerialPort.OneStop
    FlowControlNone = QSerialPort.NoFlowControl
    Serial_NoError = QSerialPort.NoError
    MessageBox_Yes, MessageBox_No = QMessageBox.Yes, QMessageBox.No
    MessageBox_Default = QMessageBox.Yes
#
# Profiling
# ----------------------------------------
try:
    profile                                                                    # provided by kernprof at runtime
except NameError:
    def profile(func):                                                         # no-op when not profiling
        return func
    
############################################################################################################################################
############################################################################################################################################
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
############################################################################################################################################
############################################################################################################################################

class QSerial(QObject):
    """
    Serial Interface for QT

    Signals (to be emitted by UI)
        scanPortsRequest                 request that Serial Worker is scanning for ports
        scanBaudRatesRequest             request that Serial Worker is scanning for baudrates
        changePortRequest                request that Serial Worker is changing port
        changeBaudRequest                request that Serial Worker is changing baud rate
        changeLineTerminationRequest     request that Serial Worker line termination is changed
        closePortRequest                 request that Serial Worker closes current port
        setupTransceiverRequest          request that QTimer for receiver and QTimer for throughput is created
        startTransceiverRequest          request that QTimer for receiver is started
        stopTransceiverRequest           request that QTimer for receiver is stopped
        startThroughputRequest           request that QTimer for throughput is started
        stopThroughputRequest            request that QTimer for throughput is stopped
        serialStatusRequest              request that Serial Worker reports current port, baudrate, line termination, encoding, timeout
        finishWorkerRequest              request that Serial Worker worker is finished
        closePortRequest                 request that Serial Worker closes current port
        mtocRequest                      request that Serial Worker measures time of code

        sendFileRequest                  request to send file
        sendTextRequest                  request to transmit text to TX
        sendLineRequest                  request to transmit one line of text to TX
        sendLinesRequest                 request to transmit lines of text to TX

        receivedData(bytearray)          text received on serial port
        receivedLines(list)              lines of text received on serial port

    Slots (functions available to respond to external signals)
        on_logSignal(int, str)               pickup log signal from Serial Worker

        on_pushButton_SerialScan             update serial port list
        on_pushButton_SerialOpenClose        open/close serial port
        on_comboBoxDropDown_SerialPorts      user selected a new port on the drop down list
        on_comboBoxDropDown_BaudRates        user selected a different baudrate on drop down list
        on_comboBoxDropDown_LineTermination  user selected a different line termination from drop down menu
        
        on_statusReady                       pickup Serial Worker status on port, baudrate, line termination, timeout, connected
        on_newPortListReady                  pickup new list of serial ports (ports,portNames, portHWIDs)
        on_newBaudListReady(list)            pickup new list of baudrates
        on_receivedData(bytearray)           pickup text from serial port
        on_flushByteArrayBuffer()            push byte array buffer to text display
        on_receivedLines(list)               pickup lines of text from serial port
        on_flushLinesBuffer()                push lines buffer to text display
        on_workerStateChanged(bool)          pickup running state of serial worker
        on_throughputReady(int, int)         pickup throughput data from Serial Worker
        on_usb_event_detected(str)           pickup USB device insertion or removal

        on_mtocRequest()                    produce mtoc log message and start serialWorker mtoc request

        on_sendFileRequest                  request to send file
        on_sendTextRequest                  request to transmit text to TX
        on_sendLineRequest                  request to transmit one line of text to TX
        on_sendLinesRequest                 request to transmit lines of text to TX

    Functions
        handle_usb_event_detected(str)       emit usb event signal with message
        cleanup                              cleanup the Serial

    """

    # Signals
    # ==========================================================================

    scanPortsRequest             = pyqtSignal()                                # port scan
    scanBaudRatesRequest         = pyqtSignal()                                # baudrates scan
    changePortRequest            = pyqtSignal(str, int)                        # port and baudrate to change
    changeBaudRequest            = pyqtSignal(int)                             # request serial baud rate to change
    closePortRequest             = pyqtSignal()                                # close the current serial Port
    toggleDTRRequest             = pyqtSignal()                                # request to toggle DTR
    espResetRequest              = pyqtSignal()                                # request to reset ESP
    changeLineTerminationRequest = pyqtSignal(bytes)                           # request line termination to change
    serialStatusRequest          = pyqtSignal()                                # request serial port and baudrate status
    setupTransceiverRequest      = pyqtSignal()                                # request to setup receiver and throughput timer
    startTransceiverRequest      = pyqtSignal()                                # start serial receiver, expecting text
    setupTransceiverFinished     = pyqtSignal()                                # request to setup transceiver finished
    stopTransceiverRequest       = pyqtSignal()                                # stop serial receiver
    startThroughputRequest       = pyqtSignal()                                # start timer to report throughput
    stopThroughputRequest        = pyqtSignal()                                # stop timer to report throughput
    finishWorkerRequest          = pyqtSignal()                                # request worker to finish
    mtocRequest                  = pyqtSignal()                                # request to measure time of code
    logSignal                    = pyqtSignal(int, str)                        # Logging
    throughputUpdate             = pyqtSignal(float, float, str)               # report rx/tx to main ("serial")

    sendFileRequest              = pyqtSignal(Path)                            # request to send file
    sendTextRequest              = pyqtSignal(bytes)                           # request to transmit text to TX
    sendLineRequest              = pyqtSignal(bytes)                           # request to transmit one line of text to TX
    sendLinesRequest             = pyqtSignal(list)                            # request to transmit lines of text to TX
    txrxReadyChanged             = pyqtSignal(bool)                            # ready to accept send file, text, line or lines

    # Init
    # ==========================================================================

    def __init__(self, parent=None, ui=None):

        super().__init__(parent)

        self.instance_name = self.objectName() if self.objectName() else self.__class__.__name__
        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else -1

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
        self.defaultBaudRate       = DEFAULT_BAUDRATE
        self.BaudRates             = []                                        # e.g. (1200, 2400, 9600, 115200)
        self.serialPortHWIDs       = []                                        # device specific identifier
        self.serialPortNames       = []                                        # human readable
        self.serialPorts           = []                                        # e.g. COM6
        self.serialPort            = ""                                        # e.g. COM6
        self.serialPortHWID        = ""                                        # e.g. USB VID:PID=1A86:7523 
        self.serialBaudRate        = DEFAULT_BAUDRATE                          # e.g. 115200
        self.lastNumReceived       = 0                                         # init throughput            
        self.lastNumSent           = 0                                         # init throughput
        self.rx                    = 0                                         # init throughput
        self.tx                    = 0                                         # init throughput 
        self.lastNumComputed       = time.perf_counter()                       # init throughput time calculation
        self.receiverIsRunning     = False                                     # keep track of worker state
        self.textLineTerminator    = EOL_DEFAULT_BYTES                         # default line termination: none
        self.serialTimeout         = 0                                         # default timeout    
        self.serialConnected       = False                                     # keep track of connection state

        self.serialPort_previous   = ""                                        # previous port       
        # Backup for reconnection/device removal
        self.serialPort_backup     = ""
        self.serialPortHWID_backup = ""
        self.serialBaudRate_backup = DEFAULT_BAUDRATE
        self.awaitingReconnection  = False

        self.record                = False                                     # record serial data
        self.recordingFileName     = ""
        self.recordingFile         = None

        # terminal sizing used by flushers
        if parent and hasattr(parent, "maxlines"):                             # added
            self.maxlines = int(parent.maxlines)
        else:
            self.maxlines = int(DEFAULT_TEXT_LINES)

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
        self.htmlBufferTimer.setInterval(FLUSH_INTERVAL_MS)
        # self.htmlBufferTimer.timeout.connect(self.flushHTMLBuffer)
        
        self.mtoc_on_newPortListReady = 0.
        self.mtoc_on_newBaudListReady = 0.
        self.mtoc_on_receivedData = 0.
        self.mtoc_on_receivedLines = 0.
        self.mtoc_on_receivedHTML = 0.
        self.mtoc_on_throughputReady = 0.
        self.mtoc_on_usb_event_detected = 0.
        self.mtoc_on_statusReady = 0.
        self.mtoc_appendTextLines = 0.
        self.mtoc_appendText = 0.
        self.mtoc_appendHtml = 0.

        # Delegate encoding if parent has one
        if parent and hasattr(parent, "encoding"):
            self.encoding = parent.encoding
        else:
            self.encoding = "utf-8"

        # Check if we have a valid User Interface
        if ui is None:
            self.logger.log(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Need to have access to User Interface"
            )
            raise ValueError("User Interface (ui) is required but was not provided.")
        self.ui = ui

        self.display = True                                                    # display incoming data
        self.ui.checkBox_DisplaySerial.setUpdatesEnabled(False)
        self.ui.checkBox_DisplaySerial.setChecked(self.display)
        self.ui.checkBox_DisplaySerial.setUpdatesEnabled(True)

        # Abbreviations
        self.text_widget = self.ui.plainTextEdit_Text                          # Text widget in the UI
        self.text_scroll_bar = self.text_widget.verticalScrollBar()

        self.html_tracker = IncompleteHTMLTracker()                            # Initialize the HTML tracker  

        # Serial Worker & Thread
        # ----------------------------------------

        # Serial Thread
        self.serialThread = QThread()                                          # create QThread object
        
        # Serial Worker
        self.serialWorker = Serial()                                           # create serial worker object
        self.serialWorker.moveToThread(self.serialThread)                      # move worker to thread

        # Signals
        # ----------------------------------------

        # Connect Serial worker / thread finished
        self.serialWorker.finished.connect(          self.serialThread.quit)   # if worker emits finished quite worker thread
        self.serialWorker.finished.connect(          self.serialWorker.deleteLater) # delete worker at some time
        self.serialWorker.destroyed.connect(         lambda: setattr(self, "serialWorker", None))
        self.serialThread.finished.connect(          self.serialThread.deleteLater) # delete thread at some time
        self.serialThread.destroyed.connect(         lambda: setattr(self, "serialThread", None))
        self.serialThread.started.connect(           self.serialWorker.on_thread_debug_init, type=ConnectionType.QueuedConnection)

        # Signals from QSerial-UI to Serial Worker
        self.changePortRequest.connect(              self.serialWorker.on_changePortRequest, type=ConnectionType.QueuedConnection) # connect changing port
        self.closePortRequest.connect(               self.serialWorker.on_closePortRequest, type=ConnectionType.QueuedConnection) # connect close port
        self.changeBaudRequest.connect(              self.serialWorker.on_changeBaudRateRequest, type=ConnectionType.QueuedConnection) # connect changing baud rate
        self.changeLineTerminationRequest.connect(   self.serialWorker.on_changeLineTerminationRequest, type=ConnectionType.QueuedConnection) # connect changing line termination
        self.scanPortsRequest.connect(               self.serialWorker.on_scanPortsRequest, type=ConnectionType.QueuedConnection) # connect request to scan ports
        self.scanBaudRatesRequest.connect(           self.serialWorker.on_scanBaudRatesRequest, type=ConnectionType.QueuedConnection) # connect request to scan baud rates
        self.serialStatusRequest.connect(            self.serialWorker.on_serialStatusRequest, type=ConnectionType.QueuedConnection) # connect request for serial status

        self.espResetRequest.connect(                self.serialWorker.on_resetESPRequest, type=ConnectionType.QueuedConnection) # connect reset ESP32
        self.toggleDTRRequest.connect(               self.serialWorker.on_toggleDTRRequest, type=ConnectionType.QueuedConnection) # connect toggle DTR

        self.setupTransceiverRequest.connect(        self.serialWorker.on_setupTransceiverRequest, type=ConnectionType.QueuedConnection) # connect start receiver
        self.startTransceiverRequest.connect(        self.serialWorker.on_startTransceiverRequest, type=ConnectionType.QueuedConnection) # connect start receiver
        self.stopTransceiverRequest.connect(         self.serialWorker.on_stopTransceiverRequest, type=ConnectionType.QueuedConnection) # connect start receiver
        self.startThroughputRequest.connect(         self.serialWorker.on_startThroughputRequest, type=ConnectionType.QueuedConnection) # start throughput
        self.stopThroughputRequest.connect(          self.serialWorker.on_stopThroughputRequest, type=ConnectionType.QueuedConnection) # stop throughput
        self.finishWorkerRequest.connect(            self.serialWorker.on_finishWorkerRequest, type=ConnectionType.QueuedConnection) # connect finish request

        self.mtocRequest.connect(                    self.serialWorker.on_mtocRequest, type=ConnectionType.QueuedConnection) # connect mtoc request to worker

        self.sendFileRequest.connect(                self.serialWorker.on_sendFileRequest, type=ConnectionType.QueuedConnection) # request to send file
        self.sendTextRequest.connect(                self.serialWorker.on_sendTextRequest, type=ConnectionType.QueuedConnection) # request to transmit text to TX
        self.sendLineRequest.connect(                self.serialWorker.on_sendLineRequest, type=ConnectionType.QueuedConnection) # request to transmit one line of text to TX
        self.sendLinesRequest.connect(               self.serialWorker.on_sendLinesRequest, type=ConnectionType.QueuedConnection) # request to transmit lines of text to TX


        # Signals from Serial Worker to QSerial (UI)
        self.serialWorker.newPortListReady.connect(  self.on_newPortListReady, type=ConnectionType.QueuedConnection) # connect new port list to its ready signal
        self.serialWorker.newBaudListReady.connect(  self.on_newBaudListReady, type=ConnectionType.QueuedConnection) # connect new baud list to its ready signal
        self.serialWorker.statusReady.connect(       self.on_statusReady, type=ConnectionType.QueuedConnection) # connect display serial status to ready signal
        self.serialWorker.throughputReady.connect(   self.on_throughputReady, type=ConnectionType.QueuedConnection) # connect display throughput status
        self.serialWorker.workerStateChanged.connect(self.on_workerStateChanged, type=ConnectionType.QueuedConnection) # mirror serial worker state to serial UI
        self.serialWorker.setupTransceiverFinished.connect(self.setupTransceiverFinished, type=ConnectionType.QueuedConnection) # connect setup transceiver finished signal from worker to UI
        self.serialWorker.logSignal.connect(         self.on_logSignal, type=ConnectionType.QueuedConnection) # connect log messages to BLE UI

        # Getting Serial Worker Running
        # ----------------------------------------
        self.serialThread.start()                                              # start thread 
        self.logger.log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Serial Worker started."
        )

        self.setupTransceiverRequest.emit()                                    # establishes serial port and its timers in new thread
        ok, args, reason = wait_for_signal(
            self.setupTransceiverFinished,
            timeout_ms=1000,
            sender=self.serialWorker
        )
        if not ok:
            self.logger.log(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Serial transceiver setup timed out because of {reason}."
            )
            return
        else:
            self.logger.log(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Serial transceiver setup."
            )

        QTimer.singleShot( 0, lambda: self.scanBaudRatesRequest.emit())        # request to scan for baudrates
        QTimer.singleShot(50, lambda: self.scanPortsRequest.emit())            # request to scan for serial ports


        self.logger.log(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: QSerial initialized."
        )

    # ==========================================================================
    # Slots Received Requests
    # ==========================================================================

    @pyqtSlot()
    def on_mtocRequest(self) -> None:

        """Emit the mtoc signal with a function name and time in a single log call."""
        log_message = textwrap.dedent(f"""
            Serial Profiling
            =============================================================
            on_newPortListReady     took {self.mtoc_on_newPortListReady*1000:.2f} ms.
            on_newBaudListReady     took {self.mtoc_on_newBaudListReady*1000:.2f} ms.

            on_receivedData         took {self.mtoc_on_receivedData*1000:.2f} ms.
            on_receivedLines        took {self.mtoc_on_receivedLines*1000:.2f} ms.
            on_receivedHTML         took {self.mtoc_on_receivedHTML*1000:.2f} ms.

            on_throughputReady      took {self.mtoc_on_throughputReady*1000:.2f} ms.
            on_usb_event_detect     took {self.mtoc_on_usb_event_detected*1000:.2f} ms.
            on_statusReady          took {self.mtoc_on_statusReady*1000:.2f} ms.

            appendTextLines         took {self.mtoc_appendTextLines*1000:.2f} ms.
            appendText              took {self.mtoc_appendText*1000:.2f} ms.
            appendHtml              took {self.mtoc_appendHtml*1000:.2f} ms.
        """)
        self.logSignal.emit(-1, log_message)

        self.mtoc_on_newPortListReady = 0.
        self.mtoc_on_newBaudListReady = 0.
        self.mtoc_on_receivedData = 0.
        self.mtoc_on_receivedLines = 0.
        self.mtoc_on_receivedHTML = 0.
        self.mtoc_on_throughputReady = 0.
        self.mtoc_on_usb_event_detected = 0.
        self.mtoc_on_statusReady = 0.
        self.mtoc_appendTextLines = 0.
        self.mtoc_appendText = 0.
        self.mtoc_appendHtml = 0.

        # Emit the mtoc request to the serial worker
        self.mtocRequest.emit()

    # ==========================================================================
    # Slots
    # ==========================================================================

    @pyqtSlot(int,str)
    def on_logSignal(self, level: int, message: str) -> None:
        """pickup log messages"""
        self.logSignal.emit(level, message)

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
                QTimer.singleShot( 50, lambda: self.closePortRequest.emit())   # request to close serial port
                QTimer.singleShot(250, lambda: self.serialStatusRequest.emit()) # request to report serial port status
                QTimer.singleShot(300, lambda: self.scanPortsRequest.emit())   # initiate update of port list

                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Requesting Closing serial port."
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
                    if score > best_score:                                     # Keep track of the best match
                        best_score = score
                        best_match = hwid
                if best_score > 0.8:
                    # find the port that matches the previous hwid
                    indx = port_hwids.index(best_match)
                    self.serialPort_backup = ports[indx]
                    self.serialPort_previous = ports[indx]
                    QTimer.singleShot(  0, lambda: self.scanPortsRequest.emit()) # request new port list, takes 225ms to complete
                    QTimer.singleShot( 50, lambda: self.scanBaudRatesRequest.emit()) # update baudrates
                    QTimer.singleShot(100, lambda: self.changePortRequest.emit(self.serialPort_backup, self.serialBaudRate_backup) ) # takes 11ms to open port
                    QTimer.singleShot(200, lambda: self.serialStatusRequest.emit()) # request to report serial port status            
                    QTimer.singleShot(250, lambda: self.startThroughputRequest.emit()) # request to start serial receiver
                    self.awaitingReconnection = False
                    self.logSignal.emit(logging.INFO, 
                        f"[{self.instance_name[:15]:<15}]: Device {port_names[indx]} on port {self.serialPort_backup} reopened with baud {self.serialBaudRate_backup} "
                        f"eol {repr(self.textLineTerminator)} timeout {self.serialTimeout}."
                    )
                    self.ui.statusBar().showMessage('USB device reconnection.', 5000)
                else:
                    self.logSignal.emit(logging.INFO, 
                        f"[{self.instance_name[:15]:<15}]: New device {best_match} does not match hardware id {self.serialPortHWID_backup}."
                    )

            else:
                # We have new device insertion, connect to it
                if self.serialPort == "":
                    # new_ports     = [port for port in ports if port not in self.serialPorts]   # prevents device to be opened that was previously found but not opened
                    new_ports = [port for port in ports]
                    new_portnames = [port_names[ports.index(port)] for port in new_ports if port in ports] # Get corresponding names

                    # Figure out if useable port
                    if new_ports:
                        new_port      = new_ports[0]                           # Consider first found new port
                        new_portname  = new_portnames[0] if new_portnames else "Unknown Device"
                        new_baudrate  = self.serialBaudRate if self.serialBaudRate > 0 else DEFAULT_BAUDRATE

                        # Show user confirmation dialog
                        reply = QMessageBox.question(
                            self.ui,
                            "New USB Device Detected",
                            f"Do you want to connect to {new_port} ({new_portname})?",
                            MessageBox_Yes | MessageBox_No,
                            MessageBox_Default
                        )
                        if (reply == MessageBox_Yes):
                            # Start the receiver
                            QTimer.singleShot(  0, lambda: self.scanPortsRequest.emit()) # request new port list, takes up to 225ms
                            QTimer.singleShot(200, lambda: self.scanBaudRatesRequest.emit()) # request new baud rate list
                            QTimer.singleShot(210, lambda: self.changePortRequest.emit(new_port, new_baudrate)) # takes 11ms to open
                            QTimer.singleShot(240, lambda: self.serialStatusRequest.emit()) # request to report serial port status            
                            QTimer.singleShot(250, lambda: self.startThroughputRequest.emit()) # request to start serial receiver
                            self.logSignal.emit(logging.INFO, 
                                f"[{self.instance_name[:15]:<15}]: Requested opening Serial port {new_port} with {new_baudrate} baud."
                            )
                            self.ui.statusBar().showMessage('Serial Open requested.', 2000)

    @pyqtSlot()
    def on_pushButton_SerialScan(self) -> None:
        """
        Updating serial port list

        Sends signal to serial worker to scan for ports
        Serial worker will create newPortList signal when completed which
        is handled by the function on_newPortList below
        """
        self.scanPortsRequest.emit()
        self.logSignal.emit(logging.DEBUG, 
            f"[{self.instance_name[:15]:<15}]: Scanning for serial ports."
        )
        self.ui.statusBar().showMessage('Serial Port Scan requested.', 2000)            

    @pyqtSlot()
    def on_pushButton_SerialOpenClose(self) -> None:
        if self.ui.pushButton_SerialOpenClose.text() == "Close":
            # Close the serial port
            #   stop the receiver
            self.serialPort_previous = self.serialPort
            QTimer.singleShot(  0, lambda: self.stopThroughputRequest.emit())  # request to stop throughput
            QTimer.singleShot( 50, lambda: self.closePortRequest.emit())       # request to close serial port
            QTimer.singleShot(250, lambda: self.serialStatusRequest.emit())    # request to report serial port status
            # do not want to automatically reconnect when device is reinserted
            self.awaitingReconnection = False
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Requesting closing serial port."
            )
            self.ui.statusBar().showMessage("Serial Close requested.", 2000)
        else:
            # Open the serial port
            index = self.ui.comboBoxDropDown_SerialPorts.currentIndex()
            try:
                port = self.serialPorts[index]                                 # we have valid port

            except Exception as e:
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Serial port not valid. Error {str(e)}"
                )
                self.ui.statusBar().showMessage('Can not open serial port.', 2000)
                return

            else:
                baudrate = self.serialBaudRate if self.serialBaudRate > 0 else DEFAULT_BAUDRATE

                label = self.ui.comboBoxDropDown_LineTermination.currentText()        
                term = EOL_DICT.get(label, b"\r\n")

                # Start the receiver
                QTimer.singleShot(  0, lambda: self.changeLineTerminationRequest.emit(term))
                QTimer.singleShot( 20, lambda: self.changePortRequest.emit(port, baudrate)) # takes 11ms to open
                QTimer.singleShot(200, lambda: self.serialStatusRequest.emit()) # request to report serial port status            
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Requesting opening serial port {port} with {self.serialBaudRate} baud."
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
        if lenSerialPorts > 0:                                                 # only continue if we have recognized serial ports
            if (portIndex > -1) and (portIndex < lenSerialPorts):
                port = self.serialPorts[portIndex]                             # we have valid port
                self.ui.pushButton_SerialOpenClose.setEnabled(True)

        # Change the port if a port is open, otherwise we need to click on open button
        if self.serialPort != "":
            # A port is in use and we selected 
            if port is None:
                # "None" was selected so close the port
                QTimer.singleShot(  0, lambda: self.stopThroughputRequest.emit()) # request to stop throughput
                QTimer.singleShot( 50, lambda: self.closePortRequest.emit())   # request to close port
                QTimer.singleShot(250, lambda: self.serialStatusRequest.emit()) # request to report serial port status
                return                                                         # do not continue

            else:
                # We have valid new port
                
                # Make sure we have valid baud rate to open the new port
                lenBaudRates   = len(self.BaudRates)

                if lenBaudRates > 0:                                           # if we have recognized serial baud rates
                    baudIndex = self.ui.comboBoxDropDown_BaudRates.currentIndex()
                    if baudIndex < lenBaudRates:                               # last entry is -1
                        baudrate = self.BaudRates[baudIndex]
                        self.logSignal.emit(logging.INFO, 
                            f"[{self.instance_name[:15]:<15}]: Changing baudrate to {baudrate}"
                        )
                    else:
                        baudrate = self.defaultBaudRate                        # use default baud rate
                        self.logSignal.emit(logging.INFO, 
                            f"[{self.instance_name[:15]:<15}]: Using default baudrate {baudrate}"
                        )
                else:
                    baudrate = self.defaultBaudRate                            # use default baud rate, user can change later

            # change port if port changed
            if port != self.serialPort or baudrate != self.serialBaudRate:
                QTimer.singleShot(   0, lambda: self.changePortRequest.emit(port, baudrate)) # takes 11ms to open
                QTimer.singleShot( 200, lambda: self.serialStatusRequest.emit()) # request to report serial port status
                self.logSignal.emit(logging.INFO,
                    f"[{self.instance_name[:15]:<15}]: Port {port} baud {baudrate}"
                )
            else:
                # port already open
                self.logSignal.emit(logging.INFO,
                    f"[{self.instance_name[:15]:<15}]: Keeping current port {port} baud {baudrate}"
                )

        else:
            # No port is open, do not change anything
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Port not changed, no port is open."
            )

        self.ui.statusBar().showMessage("Serial port change requested.", 2000)

    @pyqtSlot()
    def on_comboBoxDropDown_BaudRates(self) -> None:
        """
        User selected a different baudrate on drop down list
        """
        if self.serialPort != "":
            lenBaudRates = len(self.BaudRates)

            if lenBaudRates > 0:                                               # if we have recognized serial baud rates
                index = self.ui.comboBoxDropDown_BaudRates.currentIndex()

                if index < lenBaudRates:                                       # last entry is -1
                    baudrate = self.BaudRates[index]
                    self.logSignal.emit(logging.INFO, 
                        f"[{self.instance_name[:15]:<15}]: Changing baudrate to {baudrate}"
                    )
                else:
                    baudrate = self.defaultBaudRate                            # use default baud rate
                    self.logSignal.emit(logging.INFO, 
                        f"[{self.instance_name[:15]:<15}]: Using default baudrate {baudrate}"
                    )

                if baudrate != self.serialBaudRate:                            # change baudrate if different from current
                    self.changeBaudRequest.emit(baudrate)
                    QTimer.singleShot(200, lambda: self.serialStatusRequest.emit()) # request to report serial port status
                    self.logSignal.emit(logging.INFO,
                        f"[{self.instance_name[:15]:<15}]: Changing baudrate to {baudrate}."
                    )
                else:
                    self.logSignal.emit(logging.INFO,
                        f"[{self.instance_name[:15]:<15}]: Baudrate remains the same."
                    )

            else:
                self.logSignal.emit(logging.ERROR,
                    f"[{self.instance_name[:15]:<15}]: No baudrates available"
                )

        else:
            # do not change anything as we first need to open a port
            self.logSignal.emit(logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: No port open, can not change baudrate"
            )

        self.ui.statusBar().showMessage('Baudrate change requested.', 2000)


    @pyqtSlot()
    def on_comboBoxDropDown_LineTermination(self):
        """
        User selected a different line termination from drop down menu
        """
        label = self.ui.comboBoxDropDown_LineTermination.currentText()
        term  = EOL_DICT.get(label, EOL_DEFAULT_BYTES)
        self.textLineTerminator = term

        # Notify the rest of the app
        # ask line termination to be changed if port is open
        if self.serialPort != "":
            QTimer.singleShot( 0, lambda: self.changeLineTerminationRequest.emit(term))
            QTimer.singleShot(50, lambda: self.serialStatusRequest.emit())     # request to report serial port status

        # Log both the friendly label and the raw bytes for clarity
        hr = EOL_DICT_INV.get(term, repr(term))
        self.logSignal.emit(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Line termination -> {hr} ({repr(term)})"
        )

        self.ui.statusBar().showMessage("Line termination updated.", 2000)

    # ==========================================================================
    # Slots for Worker Signals
    # ==========================================================================

    @pyqtSlot(str, str, int, bytes, bool)
    def on_statusReady(self, 
                             port: str, 
                             hwid: str,
                             baud: int, 
                             eol: bytes, 
                             connected: bool) -> None:
        """
        pickup Serial status

        the status is:
        - port: the serial port name (e.g. COM6)
        - baud: the serial baud rate (e.g. 115200)
        - eol: the line termination (e.g. b"\r\n")
        - connected: True if the port is open, False otherwise
        """

        if PROFILEME: 
            tic = time.perf_counter()

        # Port
        self.serialPort      = port
        self.serialConnected = connected
        self.serialPortHWID  = hwid

        # Line termination
        self.textLineTerminator = eol

        label = EOL_DICT_INV.get(eol, EOL_DEFAULT_LABEL)

        try:
            index = self.ui.comboBoxDropDown_LineTermination.findText(label)
            if index > -1:
                self.ui.comboBoxDropDown_LineTermination.blockSignals(True)
                self.ui.comboBoxDropDown_LineTermination.setCurrentIndex(index)
                self.logSignal.emit(logging.DEBUG, f"[{self.instance_name[:15]:<15}]: Selected line termination {label}.")
        except Exception as e:
            self.logSignal.emit(logging.ERROR, f"[{self.instance_name[:15]:<15}]: Line termination error: {e}.")
        finally:
            self.ui.comboBoxDropDown_LineTermination.blockSignals(False)

        # Update UI Based on Connection State
        self.ui.pushButton_SerialOpenClose.setText("Close" if connected else "Open")
        self.ui.pushButton_SerialOpenClose.setEnabled(connected or self.serialPort != "")
    
        if not connected:

            # Not Connected

            # Disable TX UI when disconnected
            self.ui.lineEdit_Text.setEnabled(False)
            self.ui.pushButton_SendFile.setEnabled(False)

            self.ui.comboBoxDropDown_SerialPorts.blockSignals(True)
            if self.serialPort != "":
                index = self.ui.comboBoxDropDown_SerialPorts.findText(self.serialPort)
            elif self.serialPort_previous != "":
                index = self.ui.comboBoxDropDown_SerialPorts.findText(self.serialPort_previous)
            else:
                index = -1
            if index > -1:                                                     # if we found item
                self.ui.comboBoxDropDown_SerialPorts.setCurrentIndex(index)
                self.ui.pushButton_SerialOpenClose.setEnabled(True)

            else:                                                              # if we did not find item, set box to last item (None)
                self.ui.comboBoxDropDown_SerialPorts.setCurrentIndex(len(self.serialPortNames))
                self.ui.pushButton_SerialOpenClose.setEnabled(False)
            self.ui.comboBoxDropDown_SerialPorts.blockSignals(False)

            self.ui.pushButton_ToggleDTR.setEnabled(False)
            self.ui.pushButton_ResetESP.setEnabled(False)

        else:

            # Connected

            # Handle Connection UI Updates**
            self.ui.pushButton_ChartStartStop.setEnabled(True)
            self.ui.pushButton_ReceiverStartStop.setEnabled(True)
            self.ui.pushButton_ToggleDTR.setEnabled(True)
            self.ui.pushButton_ResetESP.setEnabled(True)

            # Enable TX UI when connected
            self.ui.lineEdit_Text.setEnabled(True)
            self.ui.pushButton_SendFile.setEnabled(True)

            # Update Baud Rate
            self.serialBaudRate = baud if baud > 0 else self.defaultBaudRate
            self.defaultBaudRate = self.serialBaudRate

            # Set Serial Port Combobox
            try:
                index = self.ui.comboBoxDropDown_SerialPorts.findText(self.serialPort)
                self.ui.comboBoxDropDown_SerialPorts.blockSignals(True)
                self.ui.comboBoxDropDown_SerialPorts.setCurrentIndex(index)
                self.logSignal.emit(logging.DEBUG, 
                    f"[{self.instance_name[:15]:<15}]: Selected port \"{self.serialPort}\"."
                )
            except Exception as e:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Port error: {e}."
                )
            finally:
                self.ui.comboBoxDropDown_SerialPorts.blockSignals(False)

            # Set Baud Rate Combobox**
            try:
                index = self.ui.comboBoxDropDown_BaudRates.findText(str(self.serialBaudRate))
                if index > -1:
                    self.ui.comboBoxDropDown_BaudRates.blockSignals(True)
                    self.ui.comboBoxDropDown_BaudRates.setCurrentIndex(index)
                    self.logSignal.emit(logging.DEBUG, f"[{self.instance_name[:15]:<15}]: Selected baudrate {self.serialBaudRate}.")
            except Exception as e:
                self.logSignal.emit(logging.ERROR, f"[{self.instance_name[:15]:<15}]: Baudrate error: {e}.")
            finally:
                self.ui.comboBoxDropDown_BaudRates.blockSignals(False)

            self.logSignal.emit(logging.DEBUG, f"[{self.instance_name[:15]:<15}]: Receiver is {'running' if self.receiverIsRunning else 'not running'}.")

        # Notify main so it can (un)wire send targets
        self.txrxReadyChanged.emit(bool(connected))

        self.ui.statusBar().showMessage("Serial status updated", 2000)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_statusReady = max((toc - tic), self.mtoc_on_statusReady)

    @pyqtSlot(list, list, list)
    def on_newPortListReady(self, ports: list, portNames: list, portHWIDs: list) -> None:
        """
        New serial port list available
        """
        if PROFILEME: 
            tic = time.perf_counter()

        self.serialPorts     = ports
        self.serialPortNames = portNames
        self.serialPortHWIDs = portHWIDs
        
        lenPortNames = len(self.serialPortNames)
        self.ui.comboBoxDropDown_SerialPorts.blockSignals(True)                # block the box from emitting changed index signal when items are added
        # populate new items
        self.ui.comboBoxDropDown_SerialPorts.clear()
        self.ui.comboBoxDropDown_SerialPorts.addItems(self.serialPorts + ["None"])
        index = self.ui.comboBoxDropDown_SerialPorts.findText(self.serialPort)
        if index > -1:                                                         # if we found previously selected item
            self.ui.comboBoxDropDown_SerialPorts.setCurrentIndex(index)
        else:                                                                  # if we did not find previous item, set box to last item (None)
            self.ui.comboBoxDropDown_SerialPorts.setCurrentIndex(lenPortNames)
            self.serialPort_previous = ""
        # enable signals again
        self.ui.comboBoxDropDown_SerialPorts.blockSignals(False)

        self.logSignal.emit(logging.DEBUG,
            f"[{self.instance_name[:15]:<15}]: Port list received."
        )

        self.ui.statusBar().showMessage("Port list updated", 2000)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_newPortListReady = max((toc - tic), self.mtoc_on_newPortListReady ) # End performance tracking

    @pyqtSlot(list)
    def on_newBaudListReady(self, baudrates: list) -> None:
        """
        New baud rate list available
        For logic and sequence of commands refer to newPortList
        """

        if PROFILEME: 
            tic = time.perf_counter()

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

        self.logSignal.emit(logging.DEBUG,
            f"[{self.instance_name[:15]:<15}]: Baud list received."
        )

        self.ui.statusBar().showMessage("Baudrates updated", 2000)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_newBaudListReady = max((toc - tic), self.mtoc_on_newBaudListReady) # End performance tracking

    # ==========================================================================
    # Slots for Data Received
    # ==========================================================================

    @pyqtSlot(bytes)
    @profile
    def on_receivedData(self, byte_array: bytearray) -> None:
        """
        Receives a raw byte array from the serial port, 
        stores it in a buffer
        saves it to a file if recording is enabled
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

        if PROFILEME:
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

        # No display, but still need to clear buffer    
        self.byteArrayBuffer.clear()


    @pyqtSlot(list)
    @profile
    def on_receivedLines(self, lines: list) -> None:
        """
        Receives lines of text from the serial port,
        Stores them in the lines buffer
        Saves them to a file if recording is enabled
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

            # clear buffer after snapshot, regardless of display state
            self.linesBuffer.clear()

        else:
            self.linesBufferTimer.stop()            

    @pyqtSlot(str)
    @profile
    def on_receivedHTML(self, html: str) -> None:
        """
        Received html text from the serial input handler
        Stores it in the html buffer
        Saves it to a file if recording is enabled
        """

        if PROFILEME: 
            tic = time.perf_counter()

        if DEBUGSERIAL:
            self.logSignal.emit(logging.DEBUG, f"[{self.instance_name[:15]:<15}]: HTML received.")

        if html:
            self.htmlBuffer += html
            # Not yet implemented
            # if not self.htmlBufferTimer.isActive():
            #    self.htmlBufferTimer.start()

            if self.record and self.recordingFile:
                try:
                    self.recordingFile.write(html)
                except Exception as e:
                    self.logSignal.emit(logging.ERROR, 
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

                    self.rich_text_widget.setUpdatesEnabled(False)
                    self.rich_text_widget.moveCursor(QTextCursor.MoveOperation.End)
                    self.rich_text_widget.insertHtml(valid_html_part)          # works on QTextEdit
                    self.rich_text_scroll_bar.setValue(self.rich_text_scroll_bar.maximum()) # Scroll to bottom for autoscroll
                    self.rich_text_widget.setUpdatesEnabled(True)

                if PROFILEME: 
                    toc = time.perf_counter()                                  # End performance tracking
                    self.mtoc_appendHTML = max((toc - tic),self.mtoc_appendHTML ) # End performance tracking
            else:
                # No display, but still need to clear buffer
                self.htmlBuffer = ""

        else:
            pass
            # Not yet implemented
            # self.htmlBufferTimer.stop()            

    @pyqtSlot(bool)
    def on_workerStateChanged(self, running: bool) -> None:
        """
        Serial worker was started or stopped
        """
        self.logSignal.emit(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Serial worker is {'on' if running else 'off'}."
        )
        self.receiverIsRunning = running
        if running:
            self.ui.statusBar().showMessage("Serial Worker started", 2000)
        else:
            self.ui.statusBar().showMessage("Serial Worker stopped", 2000)

    @pyqtSlot(int, int)
    @profile
    def on_throughputReady(self, numReceived: int, numSent: int) -> None:
        """
        Report throughput from serial transceiver
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

        self.throughputUpdate.emit(float(self.rx), float(self.tx), "serial")

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_throughputReady = max((toc - tic), self.mtoc_on_throughputReady) # End performance tracking

    # UI wants to receive data

    def connect_receivedLines(self, on_receivedLines: pyqtSlot) -> None:
        if not connect(self.serialWorker.receivedLines, on_receivedLines):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Could not connect receivedLines signal."
            )

    def connect_receivedData(self, on_receivedData: pyqtSlot) -> None:
        if not connect(self.serialWorker.receivedData, on_receivedData):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Could not connect receivedData signal."
            )

    def disconnect_receivedLines(self, on_receivedLines: pyqtSlot) -> None:
        if not disconnect(self.serialWorker.receivedLines, on_receivedLines):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Could not disconnect receivedLines signal."
            )

    def disconnect_receivedData(self, on_receivedData: pyqtSlot) -> None:
        if not disconnect(self.serialWorker.receivedData, on_receivedData):
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Could not disconnect receivedData signal."
            )

    def cleanup(self) -> None:
        """
        Perform cleanup tasks for QSerial, such as 
          stopping timers, 
          disconnecting signals,
          and ensuring proper worker shutdown.
        """

        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Cleaning up Serial worker."
        )
        self.ui.statusBar().showMessage('Cleaning up Serial worker.', 2000)

        if hasattr(self.recordingFile, "close"):
            try:
                self.recordingFile.flush()
                self.recordingFile.close()
            except Exception as e:
                self.logSignal.emit( logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Could not close file {self.recordingFileName}: {e}."
                )
        
        # Stop timers if they are still active
        if self.byteArrayBufferTimer.isActive():
            self.byteArrayBufferTimer.stop()
        if self.linesBufferTimer.isActive():
            self.linesBufferTimer.stop()
        # Not yet implemented
        # if self.htmlBufferTimer.isActive():
        #    self.htmlBufferTimer.stop()

        serialWorker = getattr(self, "serialWorker", None)
        serialThread = getattr(self, "serialThread", None)

        self.finishWorkerRequest.emit()                                        # emit signal to finish worker

        # If thread already not running or worker already gone, skip finish request
        if serialThread and qobject_alive(serialThread) and serialThread.isRunning():
            if serialWorker and qobject_alive(serialWorker):
                ok, args, reason = wait_for_signal(
                    serialWorker.finished,
                    timeout_ms=1000,
                    sender=serialWorker
                )
                if not ok and reason != "destroyed":
                    self.logSignal.emit(logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: Serial Worker finish timed out because of {reason}.")
                else:
                    self.logSignal.emit(logging.DEBUG,
                        f"[{self.instance_name[:15]:<15}]: Serial Worker finished: {args}."
                    )
        else:
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Serial worker already stopped or not initialized."
            )

        if serialThread and qobject_alive(serialThread):
            if not serialThread.wait(1000):
                self.logSignal.emit(logging.WARNING,
                    f"[{self.instance_name[:15]:<15}]: Graceful stop timed out after 3000 ms; forcing quit."
                )
                serialThread.quit()                                            # quit the serial worker thread
                if not serialThread.wait(1000):
                    self.logSignal.emit(logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: Thread won’t quit; terminating as last resort."
                    )
                    try:
                        serialThread.terminate()
                        serialThread.wait(500)
                    except Exception:
                        pass

        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Cleaned up."
        )

############################################################################################################################################
#
# Serial Worker
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
# send file
# calculate serial throughput 
#
############################################################################################################################################

class Serial(QObject):
    """
    Serial Interface for QT

    Worker Signals
        receivedData bytearray           received text on serial RX
        receivedLines list               received multiple lines on serial RX
        newPortListReady                 completed a port scan
        newBaudListReady                 completed a baud scan
        throughputReady                  throughput data is available
        statusReady                      report on port and baudrate available
        workerStateChanged               worker started or stopped
        logSignal                        logging message
        finished                         worker finished

    Worker Slots
        on_setupTransceiverRequest()     create receiver elements (in different thread)
        on_dataReady()                   Serial triggered data pickup from serial port

        on_changePortRequest(str, int)   worker received request to change port
        on_changeLineTerminationRequest(bytes)
        on_throughputTimer()             emit throughput data every second
        on_closePortRequest()            worker received request to close current port
        on_changeBaudRequest(int)        worker received request to change baud rate
        on_scanPortsRequest()            worker received request to scan for serial ports
        on_serialStatusRequest()         worker received request to report current port and baudrate
        on_sendTextRequest(bytes)        worker received request to transmit text
        on_sendLinesRequest(list of bytes) worker received request to transmit multiple lines of text
        on_sendFileRequest(Path)          worker received request to transmit a file
        
        on_startTransceiverRequest()     connect to serial Input
        on_stopTransceiverRequest()      stop serial input
        on_startThroughputRequest()      start timer to report throughput
        on_stopThroughputRequest()       stop timer to report throughput
        on_finishWorkerRequest()         stop  timer and close serial port
        on_mtocRequest()                 emit mtoc message

    Functions
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
    # ==========================================================================
    receivedData             = pyqtSignal(bytearray)                           # text received on serial port
    receivedLines            = pyqtSignal(list)                                # lines of text received on serial port
    newPortListReady         = pyqtSignal(list, list, list)                    # updated list of serial ports is available
    newBaudListReady         = pyqtSignal(list)                                # updated list of baudrates is available
    statusReady              = pyqtSignal(str, str, int, bytes, bool)          # serial status is available
    throughputReady          = pyqtSignal(int,int)                             # number of characters received/sent on serial port
    workerStateChanged       = pyqtSignal(bool)                                # worker started or stopped
    logSignal                = pyqtSignal(int, str)                            # Logging
    setupTransceiverFinished = pyqtSignal()                                    # setup transceiver finished
    finished                 = pyqtSignal()                                    # worker has been closed
        
    # Init
    # ==========================================================================
    def __init__(self, parent=None):

        super(Serial, self).__init__(parent)

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else -1
        self.instance_name = self.objectName() if self.objectName() else self.__class__.__name__
        
        # Profiling
        self.mtoc_on_sendTextRequest = 0.
        self.mtoc_on_sendLineRequest = 0.
        self.mtoc_on_sendLinesRequest = 0.
        self.mtoc_on_sendFileRequest = 0.
        self.mtoc_read = 0.
        self.mtoc_readlines = 0.
        self.mtoc_write = 0.
        self.mtoc_on_scanPortsRequest = 0.
        self.mtoc_on_changePortRequest = 0.
        self.mtoc_on_changeBaudRateRequest = 0.
        self.mtoc_on_serialStatusRequest = 0.

        # Receiver
        self.receiverIsRunning  = False
        self.QSer = None
        self.eol = EOL_DEFAULT_BYTES                                           # default line termination
        self.baud = DEFAULT_BAUDRATE
        self.portName = ""
        self.portHWID = ""

        self.bufferIn  = bytearray()
        self.bytes_received = 0
        self.bytes_sent     = 0

        # EOL autodetection
        self.dataReady_calls = 0
        self.eolWindow_start = 0.0
        self.dataReady_calls_threshold = MAX_DATAREADYCALLS
        self.eolDetection_timeThreshold = MAX_EOL_DETECTION_TIME
        self.eolFallback_timeout = MAX_EOL_FALLBACK_TIMEOUT
        self.bufferIn_max = 65536                                              # keep last 64 KiB

        # Debugger
        self.debug_initialized = False

    # ==========================================================================
    # Utility Functions
    # ==========================================================================

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
            if not port.open(OpenModeReadWrite):
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
        self.QSer.setDataBits(DataBits8)
        self.QSer.setParity(ParityNone)
        self.QSer.setStopBits(StopBitsOne)
        self.QSer.setFlowControl(FlowControlNone)
        # alternative flow controls are:
        # QSerialPort::NoFlowControl, QSerialPort::HardwareControl, QSerialPort::SoftwareControl);
        # Software is XON/XOFF
        # Hardware uses RequestToSent and DataTerminalRead signal lines
        self.QSer.setReadBufferSize(SERIAL_BUFFER_SIZE)
        if not self.QSer.open(OpenModeReadWrite):
            return False

        # # If hardware flow control do this here:
        # self.QSer.setRequestToSend(True)
        # QThread.msleep(10)
        # self.QSer.setRequestToSend(False)

        self.portName = name
        self.baud = baud
        self.portHWID = self.getHWID()
 
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
                self.portName = ""
                self.baud = DEFAULT_BAUDRATE
                self.portHWID = ""

                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Serial port closed."
                )
            except Exception as e:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Failed to close port - {e}"
                )

    def clearPort(self) -> None:
        """
        Clear serial buffers (input, output, and internal bufferIn),
        and reset counters.
        """
        if self.QSer.isOpen():
            self.QSer.clear(ClearAllDirections)
            QCoreApplication.processEvents()
            _ = bytes(self.QSer.readAll())
            self.QSer.flush()

        # Your internal bookkeeping
        self.bufferIn.clear()
        self.bytes_received = 0
        self.bytes_sent     = 0

    @profile
    def writeData(self, data: bytes) -> None:

        if self.QSer.isOpen():

            if DEBUGSERIAL or PROFILEME:
                tic = time.perf_counter()

            ba = QByteArray(data)
            l_w = self.QSer.write(ba)
            l_ba = len(data)

            if l_w == -1:
                self.logSignal.emit(logging.ERROR,
                    f"[{self.instance_name[:15]:<15}]: Tx failed."
                )
            else:
                self.bytes_sent += l_w

                if DEBUGSERIAL or PROFILEME:
                    toc = time.perf_counter()

                    if DEBUGSERIAL:
                        self.logSignal.emit(logging.DEBUG,
                            f"[{self.instance_name[:15]:<15}]: Tx wrote {l_w} of {l_ba} bytes in {1000 * (toc - tic):.2f} ms."
                        )

                    if PROFILEME: 
                        self.mtoc_write = max((toc - tic), self.mtoc_write)

        else:
            self.logSignal.emit(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Tx port not opened."
            )

            self.mtoc_write = 0.

    def getHWID(self) -> str:
        """
        Return 'VID:PID' for the currently open port, or best effort by name.
        """
        try:
            if self.QSer and self.QSer.isOpen():
                info = QSerialPortInfo(self.QSer)
                if info.hasVendorIdentifier() and info.hasProductIdentifier():
                    return f"{info.vendorIdentifier():04X}:{info.productIdentifier():04X}"
        except Exception:
            pass
        # Fallback by port name if we have one
        try:
            name = self.QSer.portName() if self.QSer else self.portName
            if name:
                for info in QSerialPortInfo.availablePorts():
                    if info.portName() == name and info.hasVendorIdentifier() and info.hasProductIdentifier():
                        return f"{info.vendorIdentifier():04X}:{info.productIdentifier():04X}"
        except Exception:
            pass
        return ""

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

            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: DTR toggled."
            )

        else:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Toggle DTR failed, serial port not open!"
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
            self.QSer.setRequestToSend(False)                                  # RTS → high → EN=HIGH
            self.QSer.setDataTerminalReady(False)                              # DTR → high → GPIO0=HIGH

            # 1) Hard reset: pull EN low
            self.QSer.setRequestToSend(True)                                   # RTS → low → EN=LOW
            QThread.msleep(100)

            # 2) Bootloader select: pull GPIO0 low
            self.QSer.setDataTerminalReady(True)                               # DTR → low → GPIO0=LOW

            # 3) Release reset: EN high → bootloader starts
            self.QSer.setRequestToSend(False)                                  # RTS → high → EN=HIGH
            QThread.msleep(100)

            # 4) Back to idle: GPIO0 high → normal BOOT pin idle
            self.QSer.setDataTerminalReady(False)                              # DTR → high → GPIO0=HIGH

            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: ESP bootloader reset completed."
            )
        else:   
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: ESP bootloader reset failed, serial port not open!"
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
            self.QSer.setRequestToSend(False)                                  # RTS=False → EN=HIGH
            self.QSer.setDataTerminalReady(False)                              # DTR=False → GPIO0=HIGH

            # 2) Reset: pull EN low
            self.QSer.setRequestToSend(True)                                   # RTS=True → EN=LOW

            # 3) Hold reset long enough
            QThread.msleep(100)

            # 4) Release reset: EN goes high, chip runs
            self.QSer.setRequestToSend(False)                                  # RTS=False → EN=HIGH

            
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: ESP hard reset completed."
            )
        else:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: ESP hard reset failed, serial port not open!"
            )

    # ==========================================================================
    # UI Response Functions
    # ==========================================================================

    @pyqtSlot()
    def on_thread_debug_init(self) -> None:
        self.ensure_debugger_attached()

    def ensure_debugger_attached(self) -> None:
        """Enable debugpy tracing for this QThread (idempotent)."""
        if self.debug_initialized:
            return
        try:
            import debugpy
            debugpy.debug_this_thread()
            self.debug_initialized = True
            try:
                self.logSignal.emit(logging.DEBUG, 
                    f"[{self.instance_name[:15]:<15}]: debugpy enabled for serial worker thread."
                )
            except Exception:
                pass
        except Exception as e:
            try:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: debugpy init failed: {e}"
                )
            except Exception:
                pass

    @pyqtSlot()
    def on_mtocRequest(self):
        """Emit the mtoc signal with a function name and time in a single log call."""
        log_message = textwrap.dedent(f"""
            Serial Worker Profiling
            =============================================================
            Serial Send Text   took {self.mtoc_on_sendTextRequest*1000:.2f} ms.
            Serial Send Line   took {self.mtoc_on_sendLineRequest*1000:.2f} ms.
            Serial Send Lines  took {self.mtoc_on_sendLinesRequest*1000:.2f} ms.
            Serial Send File   took {self.mtoc_on_sendFileRequest*1000:.2f} ms.
            Serial Readlines   took {self.mtoc_readlines*1000:.2f} ms.
            Serial Read        took {self.mtoc_read*1000:.2f} ms.
            Serial Write       took {self.mtoc_write*1000:.2f} ms.

            Bytes received     {self.bytes_received}.
            Bytes sent         {self.bytes_sent}.

            Serial Scan Ports  took {self.mtoc_on_scanPortsRequest*1000:.2f} ms.
            Serial Change Port took {self.mtoc_on_changePortRequest*1000:.2f} ms.
            Serial Change Baud took {self.mtoc_on_changeBaudRateRequest*1000:.2f} ms.
            Serial Status      took {self.mtoc_on_serialStatusRequest*1000:.2f} ms.
        """)
        self.logSignal.emit(-1, log_message)

        self.mtoc_on_sendTextRequest = 0.
        self.mtoc_on_sendLineRequest = 0.
        self.mtoc_on_sendLinesRequest = 0.
        self.mtoc_on_sendFileRequest = 0.
        self.mtoc_read = 0.
        self.mtoc_readlines = 0.
        self.mtoc_write = 0.
        self.mtoc_on_scanPortsRequest = 0.
        self.mtoc_on_changePortRequest = 0.
        self.mtoc_on_changeBaudRateRequest = 0.
        self.mtoc_on_serialStatusRequest = 0.

    # Receive Data
    # ----------------------------------------
    @pyqtSlot()
    @profile
    def on_dataReady(self) -> None:
        """
        Reading bytes from serial RX
        Then splitting them into list of lines or directly sending them to the UI
        """

        if PROFILEME:
            tic = time.perf_counter()

        qba = self.QSer.readAll()

        if not qba:
            return

        self.bytes_received += len(qba)

        if self.eol:  
            
            # EOL-based reading -> processing line by line 
            #------------------------------------------------------------------------

            self.bufferIn.extend(qba)

            # Cap buffer size to avoid unbounded growth
            if len(self.bufferIn) > self.bufferIn_max:
                self.bufferIn[:] = self.bufferIn[-self.bufferIn_max:]

            now = time.perf_counter()
            lines = None

            if self.eol in self.bufferIn:
                # Found current EOL, reset counters and eol detect window
                self.dataReady_calls = 0
                self.eolWindow_start = 0.0
                lines = self.bufferIn.split(self.eol)

            else:
                # EOL auto-detection if current EOL not observed for a while

                self.dataReady_calls += 1
                if self.eolWindow_start == 0.0:
                    self.eolWindow_start = now
                elapsed = now - self.eolWindow_start

                if (self.dataReady_calls >= self.dataReady_calls_threshold
                    and elapsed >= self.eolDetection_timeThreshold):

                    # Do we have any eol in the buffer?
                    buf = self.bufferIn                                        # local alias
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
                        # Notify UI of the change
                        self.statusReady.emit(
                            self.portName,
                            self.portHWID,
                            self.baud,
                            self.eol,
                            True,
                        )
                        # parse immediately using new delimiter
                        lines = self.bufferIn.split(self.eol)

                    elif elapsed >= self.eolFallback_timeout:
                        # No delimiter seen for a long time -> switch to raw
                        self.eol = b""
                        self.dataReady_calls = 0
                        self.eolWindow_start = 0.0
                        self.logSignal.emit(logging.INFO,
                            f"[{self.instance_name[:15]:<15}]: No delimiter seen for {self.eolFallback_timeout:.1f}s -> switching to raw bytes."
                        )
                        # Notify UI of the change
                        self.statusReady.emit(
                            self.portName,
                            self.portHWID,
                            self.baud,
                            self.eol,
                            True,
                        )
                        # Continue this call with buffered data; next calls will emit raw
                        # Emit buffered data once and clear, then return (raw mode handles future chunks)
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
                    # Remove tail from the list of completed lines
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
                        f"[{self.instance_name[:15]:<15}]: Rx {len(chunk)} bytes from {len(lines)} lines."
                    )
            else:
                if PROFILEME:
                    toc = time.perf_counter()
                    self.mtoc_readlines = max((toc - tic), self.mtoc_readlines)

        else:

            # Raw byte reading
            # ----------------------------------------

            chunk = bytearray(qba)
            self.receivedData.emit(chunk)                                      # single chunk, emit it right away

            if PROFILEME:
                toc = time.perf_counter()
                self.mtoc_read = max((toc - tic), self.mtoc_read)

            if DEBUGSERIAL:
                total_bytes = len(chunk)
                self.logSignal.emit(logging.DEBUG,
                    f"[{self.instance_name[:15]:<15}]: Rx {total_bytes} bytes."
                )

    # ==========================================================================
    # Slots
    # ==========================================================================

    # Setting up Worker in separate thread
    # ----------------------------------------

    @pyqtSlot()
    @profile
    def on_setupTransceiverRequest(self) -> None:
        """
        Set up QTimer for throughput measurements
        This needs to be run after the worker was move to different thread
        """

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else -1

        self.QSer = QSerialPort(self)                                          # serial port object

        self.QSer.errorOccurred.connect(
            lambda err: (
                (err != Serial_NoError) and
                self.logSignal.emit(
                    logging.ERROR,
                    f"[{self.instance_name[:15]:<15}]: Serial Error {err}: {self.QSer.errorString()}"
                )
            )
        )

        # setup the throughput measurement timer
        self.throughputTimer = QTimer(self)
        self.throughputTimer.setInterval(1000)
        self.throughputTimer.timeout.connect(self.on_throughputTimer)

        self.setupTransceiverFinished.emit()
        self.logSignal.emit(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Setup throughput timer."
        )

    @pyqtSlot()
    def on_startThroughputRequest(self) -> None:
        """
        Start QTimer for reading throughput
        This will be called by main program when user presses start button for text display or charting
        """
        self.throughputTimer.start()
        self.logSignal.emit(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Started throughput timer."
        )

    @pyqtSlot()
    def on_stopThroughputRequest(self) -> None:
        """
        Stop QTimer for reading throughput
        This will be called by main program when user presses the stop button to end text display or charting
        """
        self.throughputTimer.stop()
        self.throughputReady.emit(0, 0)
        self.logSignal.emit(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Stopped throughput timer."
        )

    @pyqtSlot()
    def on_throughputTimer(self) -> None:
        """
        Report throughput numbers
        """
        self.throughputReady.emit(
            self.bytes_received, self.bytes_sent
        )

    @pyqtSlot()
    def on_startTransceiverRequest(self) -> None:
        """
        Start the receiving serial data
        This will be called from main program if text display or charting is requested
        """
        if not self.receiverIsRunning:
            if self.QSer and self.QSer.isOpen():
                self.clearPort()
                # self.QSer.readyRead.connect(self.on_dataReady, Qt.QueuedConnection)
                if connect(self.QSer.readyRead, self.on_dataReady):
                    self.receiverIsRunning  = True
                    self.workerStateChanged.emit(True)                         # serial worker is running
                    self.logSignal.emit(logging.INFO,
                        f"[{self.instance_name[:15]:<15}]: Receiver started."
                    )
                else:
                    self.logSignal.emit(logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: Receiver start not successful."
                    )
            else:
                self.logSignal.emit(logging.ERROR,
                    f"[{self.instance_name[:15]:<15}]: Receiver not started, serial port not open."
                )
        else:
            self.logSignal.emit(logging.DEBUG,
                f"[{self.instance_name[:15]:<15}]: Receiver already running."
            )

    @pyqtSlot()
    def on_stopTransceiverRequest(self) -> None:
        """
        Stop receiving serial data
        This will be called from main program if text display or charting is no longer running
        """
        if self.receiverIsRunning:
            if disconnect(self.QSer.readyRead, self.on_dataReady):
                self.receiverIsRunning  = False
                self.workerStateChanged.emit(False)                            # serial worker not running
                self.logSignal.emit(logging.INFO,
                    f"[{self.instance_name[:15]:<15}]: Stopped receiver."
                )
            else:
                self.logSignal.emit(logging.ERROR,
                    f"[{self.instance_name[:15]:<15}]: Receiver stop not successful."
                )

            if hasattr(self, 'throughputTimer'):
                self.throughputTimer.stop()
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Throughput timer stopped."
                )
        else:
            self.logSignal.emit(logging.DEBUG,
                f"[{self.instance_name[:15]:<15}]: Receiver already stopped."
            )

    @pyqtSlot()
    def on_finishWorkerRequest(self) -> None:
        """Handle Cleanup of the worker."""

        self.on_stopThroughputRequest()
        self.on_stopTransceiverRequest()

        self.clearPort()
        self.closePort()

        self.bytes_received = 0
        self.bytes_sent = 0
        self.partial_line = b""

        self.logSignal.emit(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Stopped worker."
        )

        # Emit finished signal
        self.finished.emit()

    # ==========================================================================
    # UI request responses
    # ==========================================================================

    @pyqtSlot(bytes)
    def on_changeLineTerminationRequest(self, lineTermination: bytes) -> None:
        """
        Set the new line termination sequence.
        """
        if lineTermination is None:
            self.logSignal.emit(logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: Line termination not changed, line termination string not provided."
            )
            return
        else:
            self.eol = lineTermination
            self.dataReady_calls = 0
            self.eolWindow_start = 0.0
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Changed line termination to {repr(self.eol)}."
            )

    @pyqtSlot(str, int)
    def on_changePortRequest(self, name: str, baud: int) -> None:
        """
        Request to change port received
        """
        if name != "":
            if self.openPort( name = name, baud = baud):
                self.logSignal.emit(logging.INFO,
                    f"[{self.instance_name[:15]:<15}]: Port {name} opened with baud {baud}."
                )
            else:
                self.logSignal.emit(logging.ERROR,
                    f"[{self.instance_name[:15]:<15}]: Failed to open port {name}."
                )
        else:
            self.logSignal.emit(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Port not provided."
            )

        
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

        if PROFILEME:
            tic = time.perf_counter()

        if (baud is None) or (baud <= 0):
            self.logSignal.emit(logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: Range error, baudrate not changed to {baud}."
            )
        else:
            if self.QSer.isOpen():
                rates = getattr(self, "serialBaudRates", [])
                if baud in rates:
                    self.QSer.setBaudRate(baud)
                    self.baud = self.QSer.baudRate()
                    if (self.baud == baud):                                    # check if new value matches desired value
                        self.logSignal.emit(logging.INFO,
                            f"[{self.instance_name[:15]:<15}]: Changed baudrate to {baud}."
                        )
                    else:
                        # self.serialBaudRate = self.PSer.baud
                        self.logSignal.emit(logging.ERROR,
                            f"[{self.instance_name[:15]:<15}]: Failed to set baudrate to {baud}."
                        )
                else:
                    self.logSignal.emit(logging.ERROR,
                        f"[{self.instance_name[:15]:<15}]: Baudrate {baud} not available."
                    )
            else:
                self.logSignal.emit(logging.ERROR,
                    f"[{self.instance_name[:15]:<15}]: Failed to set baudrate, serial port not open!"
                )
        if PROFILEME:

            toc = time.perf_counter()
            self.mtoc_on_changeBaudRateRequest = max((toc - tic), self.mtoc_on_changeBaudRateRequest)

    @pyqtSlot()
    def on_scanPortsRequest(self) -> None:
        """ 
        Request to scan for serial ports received 
        """
        if PROFILEME:
            tic = time.perf_counter()

        self.scanPorts()
        self.newPortListReady.emit(self.serialPorts, self.serialPortNames, self.serialPortHWIDs)
        self.logSignal.emit(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Port(s) {self.serialPortNames} available."
        )

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_on_scanPortsRequest = max((toc - tic), self.mtoc_on_scanPortsRequest) # End performance tracking

    @pyqtSlot()
    def on_scanBaudRatesRequest(self) -> None:
        """
        Request to report serial baud rates received
        """
        try:
            self.serialBaudRates = [int(b) for b in QSerialPortInfo.standardBaudRates()]
        except Exception:
            self.serialBaudRates = [DEFAULT_BAUDRATE]

        if len(self.serialBaudRates) > 0:
            self.logSignal.emit(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Baudrate(s) {self.serialBaudRates} available."
            )
        else:
            self.logSignal.emit(logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: No baudrates available, port is closed."
            )
            self.serialBaudRates = [DEFAULT_BAUDRATE]

        self.newBaudListReady.emit(self.serialBaudRates)

    @pyqtSlot()
    def on_serialStatusRequest(self) -> None:
        """
        Request to report of serial status received
        """

        if PROFILEME:
            tic = time.perf_counter()

        self.logSignal.emit(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Providing serial status."
        )
        if self.QSer.isOpen():
            self.statusReady.emit(
                self.portName,
                self.portHWID,
                self.baud,
                self.eol,
                True,
            )
        else:
            self.statusReady.emit(
                "",
                "",
                self.baud,
                self.eol,
                False,
            )

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_on_serialStatusRequest = max((toc - tic), self.mtoc_on_serialStatusRequest)

    # ==========================================================================
    # Response Functions for Sending & Receiving (Transceiver)
    # ==========================================================================

    # Send Text
    # ----------------------------------------

    @pyqtSlot(bytes)
    @profile
    def on_sendTextRequest(self, byte_array: bytes) -> None:
        """
        Request to transmit text to serial TX line
        """
        if PROFILEME: 
            tic = time.perf_counter()

        self.writeData(byte_array)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_sendTextRequest = max((toc - tic), self.mtoc_on_sendTextRequest) # End performance tracking

    # Send Line(s)
    # ----------------------------------------

    @pyqtSlot(bytes)
    @profile
    def on_sendLineRequest(self, line: bytes) -> None:
        """
        Request to transmit a line of text to serial TX line
        Terminate the text with eol characters.
        """

        if PROFILEME: 
            tic = time.perf_counter()

        self.writeData(line + self.eol)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_sendLineRequest = max((toc - tic), self.mtoc_on_sendLineRequest) # End performance tracking

    @pyqtSlot(list)
    @profile
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
            self.mtoc_on_sendLinesRequest = max((toc - tic), self.mtoc_on_sendLinesRequest) # End performance tracking

    # Send File
    # ----------------------------------------

    @pyqtSlot(Path)
    @profile
    def on_sendFileRequest(self, filePath: Path) -> None:
        """
        Request to transmit file to serial TX line
        """

        if PROFILEME: 
            tic = time.perf_counter()

        if not filePath:
            self.logSignal.emit(logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: No Tx file name provided."
            )
            return
        
        if not self.QSer or not self.QSer.isOpen():
            self.logSignal.emit(logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Tx port not opened."
            )
            return

        try:
            data = Path(filePath).read_bytes()
        except FileNotFoundError:
            self.logSignal.emit(logging.ERROR, 
                f'File "{Path(filePath).name}" not found.'
            )
            return
        except Exception as e:
            self.logSignal.emit(logging.ERROR, 
                f'Unexpected error transmitting "{Path(filePath).name}": {e}'
            )
            return
        
        if not data:
            self.logSignal.emit(logging.WARNING,
                f'[{self.instance_name[:15]}]: File "{Path(filePath).name}" is empty.'
            )
            return        

        file_size = len(data)
        self.logSignal.emit(logging.INFO, 
            f'Starting transmission of "{Path(filePath).name}" ({file_size} bytes).'
        )
        self.writeData(data)

        if PROFILEME: 
            toc = time.perf_counter()
            self.mtoc_on_sendFileRequest = max((toc - tic), self.mtoc_on_sendFileRequest) # End performance tracking

    @pyqtSlot()
    def on_toggleDTRRequest(self) -> None:
        self.toggleDTR()

    @pyqtSlot()
    def on_resetESPRequest(self) -> None:
        self.espHardReset()


############################################################################################################################################
# Testing
############################################################################################################################################

if __name__ == "__main__":
    # not implemented
    pass