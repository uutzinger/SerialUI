#############################################################################################
# BLE_Serial.py
#
# Description: A simple BLE terminal application using Qt and Bleak library to communicate with a BLE device.
#
# pip install asyncio  bleak gasync PyQt5
#
# run bluetoothctl 
#   agent on 
#   default-agent
#   info 24:58:7C:DC:39:55
#   trust 24:58:7C:DC:39:55
#   pairable on
#   discoverable on
#   pair 24:58:7C:DC:39:55
#   connect 24:58:7C:DC:39:55
#
#############################################################################################

import sys
import re
import logging
import time

# Qt Libraries
try:
    from PyQt6.QtCore import (
        pyqtSlot, QEventLoop, QTimer
    )
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QPushButton, QLabel,
        QTextEdit, QVBoxLayout, QWidget, QComboBox, QHBoxLayout, QSizePolicy
    )
    from PyQt6.QtGui import QTextCursor

    qsPolicy = QSizePolicy.Policy
    MOVE_END  = QTextCursor.MoveOperation.End

except:
    from PyQt5.QtCore import (
        pyqtSlot, QEventLoop, QTimer
    )
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QPushButton, QLabel,
        QTextEdit, QVBoxLayout, QWidget, QComboBox, QHBoxLayout, QSizePolicy
    )
    from PyQt5.QtGui import QIcon, QTextCursor, QTextOption

    qsPolicy = QSizePolicy
    MOVE_END  = QTextCursor.End

# Bluetooth libraries
import asyncio
from qasync import QEventLoop, asyncSlot                            # Library to integrate asyncio with Qt
from bleak import BleakClient, BleakScanner, BleakError             #
from bleak.backends.characteristic import BleakGATTCharacteristic   #

# bluetoothctl program wrapper
from helpers.Qbluetoothctl_helper import BluetoothctlWrapper

# BLE Nordic Serial UART Service
SERVICE_UUID           = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"     # Nordic UART Service (NUS), serial over BLE 
RX_CHARACTERISTIC_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"     # Send to BLE device
TX_CHARACTERISTIC_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"     # Received from BLE device
# BLE
TARGET_DEVICE_NAME     = "MediBrick_BLE"                            # The name of the BLE device to search for
BLETIMEOUT             = 30                                         # Timeout for BLE operations
BLEPIN                 = 123456                                     # Known pairing pin for Medibrick_BLE

# Remove ANSI escape sequences
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Qt BLE Terminal")
        self.resize(400, 300)

        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger("BLE_Serial")

        # BLE connection client
        self.client = None        # General BLE client
        self.device = None        # ESP32 BLE target

        # Throughput tracking
        self.bytes_received = 0
        self.last_time = time.time()
        self.throughput_label = QLabel("Throughput: 0 Bps", self)  # Label for throughput
        self.throughput_label.setFixedWidth(155)  # Adjust as needed
        self.throughput_timer = QTimer(self)
        self.throughput_timer.timeout.connect(self.calculate_throughput)
        self.throughput_timer.start(1000)  # Calculate throughput every second

        # Text Boxes
        self.output_area = QTextEdit(self)        # BLE logs
        self.output_area.setReadOnly(True)
        self.ble_output_area = QTextEdit(self)    # Serial output
        self.ble_output_area.setReadOnly(True)
        self.input_area = QTextEdit(self)         # Serial input

        # Buttons
        self.device_combobox = QComboBox(self)
        self.send_button    = QPushButton("Send", self)
        self.scan_button    = QPushButton("Scan for Device", self)
        self.connect_button = QPushButton("Connect", self)
        self.pair_button    = QPushButton("Pair", self)

        # Connect Button Signals
        self.send_button.clicked.connect(self.on_SendDataRequest)
        self.scan_button.clicked.connect(self.on_StartScan)
        self.connect_button.clicked.connect(self.on_ConnectRequest)
        self.pair_button.clicked.connect(self.on_Pair)
        self.device_combobox.currentIndexChanged.connect(self.on_device_selected)

        # Adjust Text Input_to be single-line
        self.input_area.setFixedHeight(30)  # Adjust height to make it single-line
        # Adjust BLE Text Output window to be smaller than output_area
        self.ble_output_area.setSizePolicy(qsPolicy.Expanding, qsPolicy.Expanding)
        # Adjust Text Output window
        self.output_area.setSizePolicy(qsPolicy.Expanding, qsPolicy.Minimum)
        self.output_area.setFixedHeight(100)  # Set a smaller fixed height for BLE output

        # Layout Configuration

        # Vertical Layout
        layout = QVBoxLayout()
        # Add text windows
        layout.addWidget(self.ble_output_area, stretch=3)  # Larger stretch for output_area
        layout.addWidget(self.output_area, stretch=1)  # Smaller stretch for ble_output_area
        layout.addWidget(self.input_area)
        # Horizontal Layout for the send button and throughput label
        send_layout = QHBoxLayout()
        send_layout.addWidget(self.send_button)
        send_layout.addWidget(self.throughput_label)
        # Horizontal Layout for the other buttons
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.scan_button)
        button_layout.addWidget(self.connect_button)
        button_layout.addWidget(self.pair_button)
        button_layout.addWidget(self.device_combobox)
        # Add the Button Layouts
        layout.addLayout(send_layout)
        layout.addLayout(button_layout)

        # Container Widget
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.set_buttons(True, False, False, False)  # Enable scan button, disable send, connect and pair buttons

        # Signals for pairing and connecting
        self.bluetoothctlWrapper = BluetoothctlWrapper("bluetoothctl")
        self.device_info = {
            "mac":          None,
            "name":         None,
            "paired":       None,
            "trusted":      None,
            "connected":    None,
            "rssi":         None
        }
        self.bluetoothctlWrapper.log_signal.connect(self.handle_log)
        self.bluetoothctlWrapper.start()

    @pyqtSlot(int, str)
    def handle_log(self, level, message):
        if level == logging.INFO:
            self.logger.info(message)
            self.append_output_text(message)
        elif level == logging.WARNING:
            self.logger.warning(message)
            self.append_output_text(message)
        elif level == logging.ERROR:
            self.logger.error(message)
            self.append_output_text(message)
        else:
            self.logger.log(level, message)
            self.append_output_text(message)

    def append_output_text(self, text):
        """Appends text to the output area."""
        text = ANSI_ESCAPE.sub('', text)
        cursor = self.output_area.textCursor()
        cursor.movePosition(MOVE_END)
        self.output_area.setTextCursor(cursor)
        self.output_area.insertPlainText(text.strip() + '\n')        

    def append_ble_output_text(self, text, add_newline=False):
        """Appends text to the BLE output area."""
        cursor = self.ble_output_area.textCursor()
        cursor.movePosition(MOVE_END)
        self.ble_output_area.setTextCursor(cursor)
        self.ble_output_area.insertPlainText(text)        
        if add_newline:
            self.ble_output_area.insertPlainText("\n")

    def set_buttons(self, scan_enabled, send_enabled, connect_enable, pair_enable):
        """Enables or disables buttons."""
        self.scan_button.setEnabled(scan_enabled)
        self.send_button.setEnabled(send_enabled)
        self.connect_button.setEnabled(connect_enable)
        self.pair_button.setEnabled(pair_enable)

    def handle_rx(self, sender, data):
        """Handles incoming data."""
        self.append_ble_output_text(data.decode())  # Append data without extra newlines
        self.bytes_received += len(data)  # Update throughput measurement
    
    def calculate_throughput(self):
        """Calculate and update the throughput display."""
        current_time = time.time()
        elapsed_time = current_time - self.last_time
        self.last_time = current_time
        if elapsed_time > 0:  # Avoid division by zero
            bps = self.bytes_received / elapsed_time
            self.throughput_label.setText(f"Throughput: {bps:.0f} Bps")
        self.bytes_received = 0 # reset counter

    def on_Pair(self):
        """Trigger pairing with a device when the pair button is clicked."""
        if self.device is not None:
            self.btCTL_pair_signal.emit(self.device.address, BLEPIN)
            self.set_buttons(True, False, True, True) # Enable scan button, disable send, enable connect and pair buttons
            self.handle_log(logging.INFO, f"Paired with {TARGET_DEVICE_NAME}")
            self.pair_button.setText("Remove")
            self.pair_button.clicked.disconnect(self.on_Pair)
            self.pair_button.clicked.connect(self.on_Remove)

    def on_Remove(self):
        if self.device is not None:
            self.btCTL_remove_signal.emit(self.device.address)
            self.handle_log(logging.INFO, f"{TARGET_DEVICE_NAME} removed")
            self.pair_button.setText("Pair")
            self.set_buttons(True, False, False, True) # Enable scan button, disable send, enable connect and pair buttons
            self.pair_button.clicked.disconnect(self.on_Remove)
            self.pair_button.clicked.connect(self.on_Pair)

    @asyncSlot()
    async def on_ConnectRequest(self):
        if self.device is not None:
            self.client = BleakClient(self.device, disconnected_callback=self.on_DeviceDisconnected, timeout=BLETIMEOUT)
            try:
                await self.client.connect()
                self.handle_log(logging.INFO, f"Connected to {TARGET_DEVICE_NAME}")
                self.connect_button.setText("Disconnect")
                self.set_buttons(False, True, True, False)
                await self.client.start_notify(TX_CHARACTERISTIC_UUID, self.handle_rx)
                self.connect_button.clicked.disconnect(self.on_ConnectRequest)
                self.connect_button.clicked.connect(self.on_DisconnectRequest)
            except BleakError as e:
                # Handle specific pairing-related errors
                if "not found" in str(e).lower():
                    self.handle_log(logging.ERROR, f"Connection error: {e}")
                    self.handle_log(logging.ERROR, "Device is likely not paired. Please pair the device first by clicking the 'Pair' button.")
                else:
                    self.handle_log(logging.ERROR, f"Connection error: {e}")
            except Exception as e:
                    self.handle_log(logging.ERROR, f"Unexpected error: {e}")

    @pyqtSlot()
    def on_DeviceDisconnected(self, client):
        """Handle unexpected disconnection from the BLE device."""
        self.handle_log(logging.WARNING, "Device unexpectedly disconnected.")
        # Reset the client and UI
        self.client = None
        self.set_buttons(True, False, True, True)  # Enable scan and connect buttons, disable others
        self.connect_button.setText("Connect")
        # Disconnect UI signals related to connect/disconnect
        try:
            self.connect_button.clicked.disconnect(self.on_DisconnectRequest)
            self.connect_button.clicked.connect(self.on_ConnectRequest)
        except Exception:
            pass  # Ignore if signals were already disconnected

    @asyncSlot()
    async def on_DisconnectRequest(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            self.client = None
        self.handle_log(logging.INFO,"Disconnected from BLE device.")
        self.set_buttons(True, False, True, True) # Enable scan button, disable send, enable connect and pair buttons
        self.connect_button.setText("Connect")
        try:
            self.connect_button.clicked.disconnect(self.on_DisconnectRequest)
            self.connect_button.clicked.connect(self.on_ConnectRequest)
        except Exception:
            pass   

    @asyncSlot()
    async def on_SendDataRequest(self):
        # Get text from input area and send to ESP32
        text = self.input_area.toPlainText()
        if text and self.client and self.client.is_connected:
            await self.client.write_gatt_char(RX_CHARACTERISTIC_UUID, text.encode())
            self.handle_log(logging.INFO,f"Sent: {text}")
            self.input_area.clear()
        else:
            self.output_area.append("Not connected or no data to send.")

    @asyncSlot()
    async def on_StartScan(self):
        self.handle_log(logging.INFO, "Scanning for BLE devices.")
        devices = await BleakScanner.discover(timeout=5, return_adv=True)
        # Clear combobox items before repopulating
        self.device_combobox.clear()        
        for device, adv in devices.values():
            # Optionally filter for devices with specific characteristics (e.g., Nordic UART)
            # Assuming you want to filter devices based on UUIDs:
            for service_uuid in adv.service_uuids:
                if service_uuid.lower() == SERVICE_UUID.lower():
                    self.device_combobox.addItem(f"{device.name} ({device.address})", device)
        if self.device_combobox.count() == 0:
            self.handle_log(logging.INFO, "No matching devices found.")
        else:
            self.handle_log(logging.INFO, "Scan complete. Select a device from the dropdown.")
        self.set_buttons(True, False, True, True) # Enable scan button, disable send, enable connect and pair buttons

    def on_device_selected(self, index):
        """Updates the selected device when the combobox item is changed."""
        if index >= 0:
            self.device = self.device_combobox.itemData(index)
            self.handle_log(logging.INFO, f"Selected device: {self.device.name}, Address: {self.device.address}")
            self.set_buttons(True, False, True, True) # Enable scan button, disable send, enable connect and pair buttons

    def closeEvent(self, event):
        # Check if client is connected and disconnect asynchronously if needed
        if self.client and self.client.is_connected:
            # Run the asynchronous disconnection in a synchronous context
            asyncio.run(self.client.disconnect())
        event.accept()  # Properly accept the close event without returning

async def run_app():
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = MainWindow()
    window.show()
    with loop:
        loop.run_forever()

# Main function to start the Qt application
if __name__ == "__main__":
    asyncio.run(run_app())
