# Graphical User Interface for Serial Communication

![Serial Monitor](assets/serial_96.png)
**SerialUI** provides a graphical interface to send and receive text from the serial port, including a serial plotter for displaying numerical data. It offers features beyond the Arduino IDE Serial Plotter. 

![BLE Serial Monitor](assets/BLE_96.png)
**BLESerialUI** is equivalent to SerialUI but uses the Nordic Serial UART on a BLE connection (Experimental, Unfinished Code)

## Efficiency

Comparing Arduino IDE with SerialUI:

**Text Display**

Teensy 4.0 using the Test Program from [Paul Stoffregen](https://github.com/PaulStoffregen/USB-Serial-Print-Speed-Test/blob/master/usb_serial_print_speed.ino) with default settings:

- [Arduino IDE](https://www.pjrc.com/improving-arduino-serial-monitor-performance/) : 526k lines/sec
- [SerialUI](https://github.com/uutzinger/SerialUI): >64k lines/sec and 800 kBytes/sec

Arduino IDE is about 8 times faster in raw text display.

ESP32-S3 Adafruit Feather:

- [Arduino IDE](https://www.pjrc.com/improving-arduino-serial-monitor-performance/) : 17k lines/sec
- [Serial UI](https://github.com/uutzinger/SerialUI): 17k lines/sec and 560 kBytes/sec

There is no difference between Arduino IDE and SerialUI.

**Charting**

With simple simulated data from Teensy 4.0 we can retrieve and plot about 2 channels with 80k samples/second/channel.

Arduino IDE plotter does not provide performance metrics.

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

In future version we will also need:

- `scipy` image decompression
- `numba` acceleration of numpy code
- `cobs` serial data encoding (byte stuffing)
- `zlib` and `tamp` for compression 

Installation of PyQt5/6 has its own dependencies. If it fails, read the suggested solution in the error messages.
For example pyOpenGL might be required.

The main programs are `SerialUI.py` and `BLESerialUI.py`. The use files in the `assets` and `helper` folders.

## Description
<img src="docs/SerialMonitor.png" alt="Serial Monitor" width="600"/>
<img src="docs/SerialPlotter.png" alt="Serial Plotter" width="600"/>

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