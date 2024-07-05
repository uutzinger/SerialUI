# Graphical User Interface for Serial Communication
![Serial Monitor](assets/serial_96.png)

## Description
SerialUI provides a graphical interface to send and receive text from the serial port, including a serial plotter for displaying numerical data. It optimizes high data rate visualization of signals and text, offering features beyond the Arduino IDE Serial Plotter.

<img src="docs/SerialMonitor.png" alt="Serial Monitor" width="600"/>
<img src="docs/SerialPlotter.png" alt="Serial Plotter" width="600"/>

## Installation Requirements
- `pip3 install pyqt5`
- `pip3 install pyqtgraph`
- `pip3 install numpy`
- `pip3 install pyserial`
- `pip3 install markdown`
- *One liner:* 
    - `pip3 install pyqt5 pyqtgraph numpy pyserial markdown`

The main program is `main_window.py`, uses files in the `assets` and `helper` folders.

## How to Use This Program

### Setting Serial Port
1. Plug in your device and hit scan ports.
2. Select serial port, baud rate, and line termination (`\r\n` is most common).

### Use with Arduino IDE
1. Close serial port in SerialUI.
2. Program the microcontroller using Arduino IDE.
3. Reopen the serial port in SerialUI.

### Microcontroller Response Issues
1. Close serial port.
2. Unplug and replug the microcontroller.
3. Scan for serial ports.
4. Open serial port.
5. Adjust baud rate if necessary.
6. Start the serial text display.
7. Reset microcontroller if needed.

### Receiving Data for Text Display
1. Set serial port as described.
2. Select the serial monitor tab.
3. Start the text display.
4. Save and clear displayed data as needed.

### Sending Data
1. Set serial port as described.
2. Enter text in the line edit box and hit enter.
3. Use up/down arrows to recall previous text.

### Plotting Data
1. Set serial port as described.
2. Open the Serial Plotter tab.
3. Select data separator (comma, tab, etc.).
4. Start plotting.
5. Adjust view with the horizontal slider.
6. Save and clear plotted data.

## Modules

### User Interface
The UI is defined in `mainWindow.ui` (assets folder) and designed with QT Designer.

### Main Program
The main program (`main_window.py`) loads the UI, adjusts its size, handles QT signal connections, and manages the serial interface thread. Plotting occurs in the main thread.

### Serial Helper
Includes three classes:
- `QSerialUI`: Manages UI interaction, runs in the main thread.
- `QSerial`: Runs on its own thread, communicates with `QSerialUI`.
- `PSerial`: Interfaces with pySerial, provides unified serial port interface.

### Plotter Helper
Uses pyqtgraph for plotting. Data is stored in a circular buffer, and plotting occurs in the main thread.

### Future Enhancements
- ADPCM or serialized data transfer for compressed data reception.

## References
- [ADPCM](https://github.com/pschatzmann/adpcm)
- [Python Implementation Matt](https://github.com/mattleaverton/stream-audio-compression/)
- [Python Implementation acida](https://github.com/acida/pyima)
- [MessagePack](https://msgpack.org/)

## Acknowledgments
Urs Utzinger, 2022-2024

---

## Detailed Usage Instructions
Move the following detailed usage instructions to a new markdown document under the `docs` folder.

### Setting Serial Port
- Plug in your device and hit scan ports.
- Select serial port.
- Select the baud rate.
- Select the line termination (\r\n is most common).

### Use in Conjunction with Arduino IDE
- Click close serial port.
- Program the microcontroller.
- Click open serial port.

### Issues with Microcontroller Response
- Close the serial port.
- Unplug and replug the microcontroller.
- Scan for serial ports.
- Open the serial port.
- Adjust baud rate if necessary.
- Start the serial text display.
- Push the reset button on the microcontroller if available.

### Receiving Data for Text Display
- Complete setting serial port section above.
- Select the serial monitor tab.
- Start the text display.
- You can save and clear the current content of the display window.
- If you scroll one page backwards, the display will stop scrolling.
- If you scroll to the most recent text, the display will start scrolling.

### Sending Data
- Complete setting serial port section above.
- Enter text in the line edit box.
- Transmit it by hitting enter on the keyboard.
- Recall previous text sent with up and down arrows.

Send complete text files with the send file button. 
The file will need to fit into the serial buffer. Only smaller text files will work.

### Plotting Data
- Complete setting serial port section above.
- Open the Serial Plotter tab.
- Select data separator or none if there is only one number per line, most common separator is comma or tab. 
- Click start.
- Adjust the view with the horizontal slider.
- You can save and clear the currently plotted data.
- Click stop and zoom with the mouse.

The vertical axis is auto-scaled based on currently visible data.
