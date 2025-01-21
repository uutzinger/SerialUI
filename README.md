# Graphical User Interface for Serial Communication
![Serial Monitor](assets/serial_96.png)
![BLE Serial Monitor](assets/BLE_96.png)

## Description
**SerialUI** provides a graphical interface to send and receive text from the serial port, including a serial plotter for displaying numerical data. It offers features beyond the Arduino IDE Serial Plotter. 

From an ESP32 we can retrieve about 400kBytes/s. For simple simulated data more than 20k samples/second can be retrieved and plotted.

**BLESerialUI** is equivalent to SerialUI but uses the Nordic Serial UART on a BLE connection (Experimental)

<img src="docs/SerialMonitor.png" alt="Serial Monitor" width="600"/>
<img src="docs/SerialPlotter.png" alt="Serial Plotter" width="600"/>

## Installation Requirements
*One liner Windows:* 
    - `pip3 install pyqt5 pyqtgraph numpy pyserial markdown wmi bleak qasync`

*One liner Linux:* 
    - `pip3 install pyqt5 pyqtgraph numpy pyserial markdown pyudev bleak qasync`

- `pyqt5` or `pyqt6` user interface
- `pyqtgraph` display
- `numpy` data gathering and manipulation
- `pyserial` serial interface
- `markdown` help file
- `wmi` on Windows for USB device notifications
- `pyudev` on Linux  for USB device notifications
- `qasync` and `bleak` for bluetooth communication

Installation of PyQt5/6 has its own dependencies. If it fails, read the suggested solution in the error messages.

The main programs are `SerialUI.py` and `BLESerialUI.py`. The use files in the `assets` and `helper` folders.

## How to Use This Program
- [Usage instructions](docs/Instructions.md).
- [Supplemental instructions](docs/Supplementalinstructions.md).
- [Helpful reading for QT and qtgraph](docs/Helpful_readings.md).

## Data Parsing
- [Data Parsing](docs/Dataparsing.md)

## Indicating Data
- [Feature not implemented yet](docs/Indicating.md).

## Arduino Test Programs
In the `Arduino_programs` folder are example programs that simulate data for display.

## Author
Urs Utzinger, 2022-2025 (University of Arizona)

## Contributors
Cameron K Brooks, 2024 (Western University)