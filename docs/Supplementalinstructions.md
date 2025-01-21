## Supplemental Instructions

### Use in Conjunction with Arduino IDE
- Click close serial port.
- Program the microcontroller.
- Click open serial port.

### Issues with Microcontroller Response
- Code attempts to reconnect when microcontroller is unplugged and reattached.

Otherwise try:
- Close the serial port.
- Unplug and replug the microcontroller.
- Scan for serial ports.
- Open the serial port.
- Adjust baud rate if necessary.
- Start the serial text display.
- Push the reset button on the microcontroller if available.

## How to make a Desktop Link for this Program

### Linux
In the `linux_app` folder edit `SerialUI.desktop` and in the main folder `run.sh` to match the location of your files. Run the provided `install.sh` script in the `linux_app` folder.

### Windows
Create a desktop short cut and.
Then edit the short cut properties:
- change the target so that it includes the python executable followed by the python program `SerialUI.py`. Put quotation marks around the path to python executable and also around the location of the main python program.
- change the target folder to be the location of the `SerialUI.py` program.
- change the icon to the file you can find in assets

## Modules

### User Interface
The UI is defined in `mainWindow.ui` (assets folder) and designed with QT Designer.

### Main Program
The main program (`SerialUI.py`) loads the UI, adjusts its size, handles QT signal connections, and manages the serial interface thread. Plotting occurs in the main thread.

### Serial Helper
Includes three classes:
- `QSerialUI`: Manages UI interaction, runs in the main thread.
- `QSerial`: Runs on its own thread, communicates with `QSerialUI`.
- `PSerial`: Interfaces with pySerial, provides unified serial port interface.

### Graphing Helper
Uses pyqtgraph for plotting. Data is stored in a circular buffer, and plotting occurs in the main thread.

### Indicator Helper
The indicator helper provides an interface to display data in numeric text fields. I also provides ability to display vectors. This is incomplete.

### Current Developement
- BLE Serial
- Binary data transmission including ADPCM, zlib, tamp for compressed data reception.
