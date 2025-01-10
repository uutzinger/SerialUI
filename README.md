# Graphical User Interface for Serial Communication
![Serial Monitor](assets/serial_96.png)
![BLE Serial Monitor](assets/BLE_96.png)

## Description
**SerialUI** provides a graphical interface to send and receive text from the serial port, including a serial plotter for displaying numerical data. It optimizes high data rate visualization of signals and text, offering features beyond the Arduino IDE Serial Plotter.

**BLE_SerialUI** is equivalent to SerialUI but uses the Nordic Serial UART on a BLE connection (Experimental)

<img src="docs/SerialMonitor.png" alt="Serial Monitor" width="600"/>
<img src="docs/SerialPlotter.png" alt="Serial Plotter" width="600"/>

## Installation Requirements
- `pip3 install pyqt5` or `pip3 install pyqt6` user interface
- `pip3 install pyqtgraph` display
- `pip3 install numpy` data gathering and manipulation
- `pip3 install pyserial` serial interface
- `pip3 install markdown` help file
- `pip3 install wmi` on Windows for USB device notifications
- `pip3 install pyudev` on Linux  for USB device notifications
- *One liner Windows:* 
    - `pip3 install pyqt5 pyqtgraph numpy pyserial markdown wmi`
- *One liner Linux:* 
    - `pip3 install pyqt5 pyqtgraph numpy pyserial markdown pyudev`

Installation of PyQt5/6 has its own dependencies. If it fails, read the suggested solution in the error messages.

The main programs are `SerialUI.py` and `BLESerialUI.py`, which use files in the `assets` and `helper` folders.

## How to Use This Program

### Setting Serial Port
1. Plug in your device and hit scan ports.
2. Select serial port, baud rate, and line termination (`\r\n` is most common).

### Receiving Data for Text Display
1. Set serial port as described above.
2. Select the serial monitor tab.
3. Start the text display.
4. Save and clear displayed data as needed.

### Sending Data
1. Set serial port as described above.
2. Enter text in the line edit box and hit enter.
3. Use up/down arrows to recall previous text.

### Plotting Data
1. Set serial port as described above.
2. Open the Serial Plotter tab.
3. Select data separator (Simple or with Headers).
4. Start plotting.
5. Adjust view with the horizontal slider.
6. Click stop and zoom with the mouse.
7. Save and clear plotted data.

### Indicating data
To display data in numeric fields ... Feature not implemented yet.

## More detailed usage instructions
[Usage instructions](docs/Detailed_Usage_Instructions.md).

## Author
Urs Utzinger, 2022-2024 (University of Arizona)

## Contributors
Cameron K Brooks, 2024 (Western University)