## Detailed Usage Instructions

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
The indicator helper provides an interface to display data in numeric text fields. I also provides ability to display vectors.

### Future Enhancements
- ADPCM or serialized data transfer for compressed data reception.

#### References
- [ADPCM](https://github.com/pschatzmann/adpcm)
- [Python Implementation Matt](https://github.com/mattleaverton/stream-audio-compression/)
- [Python Implementation acida](https://github.com/acida/pyima)
- [MessagePack](https://msgpack.org/)

