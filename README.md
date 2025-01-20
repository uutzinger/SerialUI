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

### Setting Serial Port
1. Plug in your device and hit scan ports.
2. Select serial port, baud rate, and line termination (`\r\n` or `\n` are most common).

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

## Data Parsing
The data source will need to format data. Simple parsing with no variable names and parsing with names is supported.

Values separated with spaces are consider belonging to same channel. 

Values separated by comma are considered belonging to new channel.

### Simple Parsing No Header
With a new line, the values will be added to the previous line's channels.
If more channels arrive, the previous channels will be incorporated.

```
Line 1: "value1, value2"
``` 
Results in two channels

```
Line 1: "value1 value2"
```
Results in one channel with two values

```
Line 1: "value1 value2, value3"
```
Results in two channels whereas second channel has one value and second value is NaN.

```
Line 1: "value1, value2"
Line 2: "value1, value2, value3"
```
Results in 3 channels with 2 values but 3rd channel is internally prepended with NaN.

During plotting, NaN values are not included, allowing to plot data from channels with many data points simultaneously with channels with fewer data points on the same graph.

### Parsing with Header
```
Line 1: "HeaderA: value1 value 2 HeaderB: value1"
```
Results in Channel named "HeaderA" with two values and Channel named HeaderB with two values whereas second one is internally set to NaN.

```
Line 1: "HeaderA: value1, value 2 HeaderB: value1"
```
Results in Channel named "HeaderA_1" with value1 and Channel named HeaderA_1 with value2 and Channel named "HeaderB" with value1.


## Indicating Data
Feature not implemented yet.

## More Detailed Usage Instructions
[Usage instructions](docs/Detailed_Usage_Instructions.md).

## Arduino Test Programs
In the `Arduino_programs` folder are example programs that simulate data for display.

## Author
Urs Utzinger, 2022-2025 (University of Arizona)

## Contributors
Cameron K Brooks, 2024 (Western University)