import sys, time, collections

# Minimal and Threaded PyQt Serial Reader (Optimized)
# =======================================
# Provides two modes:
# 1) SerialReader: minimal, reads on main thread
# 2) ThreadedSerialReader: reads in QThread and signals main GUI
# Uses QPlainTextEdit for efficient text appending

try:
    from PyQt6.QtWidgets import QApplication, QWidget, QPlainTextEdit, QVBoxLayout
    from PyQt6.QtSerialPort import QSerialPort, QSerialPortInfo
    from PyQt6.QtCore import QIODevice, QThread, pyqtSignal, pyqtSlot, QObject,  QTimer, QCoreApplication, QTimer
    from PyQt6.QtGui import QTextOption, QTextCursor
    hasQt6 = True
except ImportError:
    from PyQt5.QtWidgets import QApplication, QWidget, QPlainTextEdit, QVBoxLayout
    from PyQt5.QtSerialPort import QSerialPort, QSerialPortInfo
    from PyQt5.QtCore import QIODevice, QThread, pyqtSignal, pyqtSlot, QObject, QTimer, QCoreApplication, QTimer
    from PyQt5.QtGui import QTextOption, QTextCursor
    hasQt6 = False

MAX_LINES = 100
UPDATE_INTERVAL = 100  # milliseconds

# ----------------------
# SerialReader (no thread)
# ----------------------
class SerialReader(QWidget):
    def __init__(self, port_name, baud=9600):
        super().__init__()
        self.setWindowTitle("Minimal Serial Reader")
        # Efficient text widget
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text)

        self.text.setReadOnly(True)  # Prevent user edits
        self.text.setWordWrapMode(QTextOption.NoWrap)  # No wrapping for better performance
        self.text.setUndoRedoEnabled(False)
        self.text.setMaximumBlockCount(MAX_LINES)

        # Configure serial port (8N1, no flow control)
        self.serial = QSerialPort(self)
        self.serial.setPortName(port_name)
        self.serial.setBaudRate(baud)
        self.serial.setDataBits(QSerialPort.Data8)
        self.serial.setParity(QSerialPort.NoParity)
        self.serial.setStopBits(QSerialPort.OneStop)
        self.serial.setFlowControl(QSerialPort.NoFlowControl)
        if not self.serial.open(QIODevice.ReadWrite):
            print(f"Failed to open port: {port_name}")
            sys.exit(1)
        self.serial.readyRead.connect(self.read_data)
        self.serial.errorOccurred.connect(self.on_serial_error)

        # Signal read to receive data
        self.serial.setRequestToSend(False)
        self.serial.setDataTerminalReady(True)
        QThread.msleep(50)
        self.serial.setDataTerminalReady(False)

        self.last_time = time.perf_counter()
        self.charsReceived = 0

    def read_data(self):
        # print(text, end='')

        scroll_bar = self.text.verticalScrollBar()
        at_bottom = scroll_bar.value() >= (scroll_bar.maximum() - scroll_bar.pageStep())

        if not at_bottom:
            return # dont update when user is browsing history

        data = bytes(self.serial.readAll())
        self.charsReceived += len(data)
        text = data.decode('utf-8', errors='replace')

        current_time = time.perf_counter()
        delta = current_time - self.last_time
        if  delta >= 1.0:
            self.last_time = current_time
            print(f"Chars received kBytes/s: {self.charsReceived/1024/delta}")
            self.charsReceived = 0

        lines = text.splitlines()
        if not lines:
            return

        self.text.setUpdatesEnabled(False)

        # if too many lines, do full redraw 
        if len(lines) > MAX_LINES:
            # full redraw
            display_text = '\n'.join(lines[-MAX_LINES:])
            self.text.setPlainText(display_text)
        else:
            # fast append 
            self.text.moveCursor(QTextCursor.End)
            self.text.insertPlainText(text)

        scroll_bar.setValue(scroll_bar.maximum())  # Scroll to bottom for autoscroll
        self.text.setUpdatesEnabled(True)

    def on_serial_error(self, error):
        print(f"Serial error: {error}")

# --------------------------
# ThreadedSerialReader
# --------------------------
class SerialWorker(QObject):
    data_received = pyqtSignal(bytes)

    def __init__(self, port_name, baud=9600):
        super().__init__()
        self.port_name = port_name
        self.baud = baud
        self.serial = None

    @pyqtSlot()
    def start(self):
        # Instantiate serial port in worker thread
        self.serial = QSerialPort()
        self.serial.setPortName(self.port_name)
        self.serial.setBaudRate(self.baud)
        self.serial.setDataBits(QSerialPort.Data8)
        self.serial.setParity(QSerialPort.NoParity)
        self.serial.setStopBits(QSerialPort.OneStop)
        self.serial.setFlowControl(QSerialPort.NoFlowControl)
        if not self.serial.open(QIODevice.ReadWrite):
            print(f"Failed to open port in worker: {self.port_name}")
            return
        
        self.serial.setRequestToSend(False)
        self.serial.setDataTerminalReady(True)
        QThread.msleep(50)
        self.serial.setDataTerminalReady(False)

        #  buffer needs to be cleared, otherwise readyRead is not triggered
        self.serial.clear(QSerialPort.AllDirections)
        QCoreApplication.processEvents()
        _ = bytes(self.serial.readAll())
        self.serial.flush()

        self.serial.readyRead.connect(self.handle_ready)
        self.serial.errorOccurred.connect(self.on_serial_error)

    def handle_ready(self):
        self.data_received.emit(bytes(self.serial.readAll()))

    def on_serial_error(self, error):
        print(f"Serial error: {error}")

class ThreadedSerialReader(QWidget):
    def __init__(self, port_name, baud=9600):
        super().__init__()
        self.setWindowTitle("Threaded Serial Reader")
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text)

        self.text.setReadOnly(True)  # Prevent user edits
        self.text.setWordWrapMode(QTextOption.NoWrap)  # No wrapping for better performance
        self.text.setUndoRedoEnabled(False)
        self.text.setMaximumBlockCount(MAX_LINES)

        # Setup worker thread
        self.worker = SerialWorker(port_name, baud)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)
        self.worker.data_received.connect(self.on_data)
        self.thread.start()

        self.last_time = time.perf_counter()
        self.charsReceived = 0

        self.byteArrayBuffer = bytearray()
        self.byteArrayBufferTimer = QTimer()
        self.byteArrayBufferTimer.setInterval(UPDATE_INTERVAL)
        self.byteArrayBufferTimer.timeout.connect(self.flushByteArrayBuffer)
        self.byteArrayBufferTimer.start()

    def on_data(self, data: bytes):
        self.byteArrayBuffer.extend(data)
        self.charsReceived += len(data)

        current_time = time.perf_counter()
        delta = current_time - self.last_time
        if  delta >= 1.0:
            self.last_time = current_time
            print(f"Chars received kBytes/s: {self.charsReceived/1024/delta}")
            self.charsReceived = 0

    def flushByteArrayBuffer(self):

        if not self.byteArrayBuffer:
            return
        
        scroll_bar = self.text.verticalScrollBar()
        at_bottom = scroll_bar.value() >= (scroll_bar.maximum() - scroll_bar.pageStep())

        if not at_bottom:
            return # dont update when user is browsing history

        text = self.byteArrayBuffer.decode('utf-8', errors='replace')
        self.byteArrayBuffer.clear()

        lines = text.splitlines()
        if not lines:
            return

        self.text.setUpdatesEnabled(False)

        # if too many lines, do full redraw 
        if len(lines) > MAX_LINES:
            # full redraw
            display_text = '\n'.join(lines[-MAX_LINES:])
            self.text.setPlainText(display_text)
        else:
            # fast append 
            self.text.moveCursor(QTextCursor.End)
            self.text.insertPlainText(text)

        scroll_bar.setValue(scroll_bar.maximum())  # Scroll to bottom for autoscroll
        self.text.setUpdatesEnabled(True)

    def closeEvent(self, event):
        if self.worker.serial and self.worker.serial.isOpen():
            self.worker.serial.close()
        self.thread.quit()
        self.thread.wait()
        event.accept()

# add option to pause and log in background

# -------------------
# Entry point
# -------------------
if __name__ == '__main__':
    app = QApplication(sys.argv)
    found = None
    for info in QSerialPortInfo.availablePorts():
        desc = info.description().strip()
        if not desc or desc.lower() == 'n/a':
            continue
        if not (info.hasVendorIdentifier() and info.hasProductIdentifier()):
            continue
        tester = QSerialPort(info)
        if tester.open(QIODevice.ReadWrite):
            tester.close()
            found = info.portName()
            break
    if not found:
        print("No valid serial ports found.")
        sys.exit(1)
    # Launch appropriate UI:
    window = SerialReader(found)
    #window = ThreadedSerialReader(found)
    window.resize(600, 400)
    window.show()
    sys.exit(app.exec())

# Maximum numbers to reach with teensy 4.0
# Display on command line:
# lines/sec: 528,211
# chars received / second: 18,1 MBytes/s
# "count=100123123, lines/sec: 518516\n\r" 36 characters, should result in 18,1 kBytes/sec

# -------------------
# Threaded performance
#
# Display in QPlainTextEdit:
# lines/sec: 488k lines/sec
# chars received / second: 17.2 MBytes/s

# -------------------
# Performance without buffer and thread
#
# Display in QPlainTextEdit:
# lines/sec: 170k ines/sec
# chars received / second: 2.2 MBytes/s
# There is data loss as we should be receive 5MBytes/s