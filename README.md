# Graphical User Interface for Serial Communication
![Serial Monitor](assets/serial_96.png)

## Description
Serial interface to send and receive text from the serial port.

It includes a serial plotter to display numbers. 
A predefined number of values can be extracted from a line of text and displayed as traces.
One can zoom, save and clear this display.

This framework has been optimized to visualize signals and text at high data rates.

The display of data allows adjustments not available in the Arduino IDE Serial Plotter.

Urs Utzinger
2022, 2023, 2024

<img src="assets/SerialMonitor.png" alt="Serial Monitor" width="800"/>
<img src="assets/SerialPlotter.png" alt="Serial Plotter" width="800"/>

## Installation Requirements
- pip3 install pyqt5 (GNU General Public License (GPL))
- pip3 install pyqtgraph (MIT License)
- pip3 install pyopengl (BSD license)
- pip3 install numpy (BSD license)
- pip3 install pyserial (Python Software Foundation License)
- pip3 install markdown (BSD license)

The main program is ```main_window.py```. It depends on the files in the ```assets``` and ```helper``` folder.

## How to use this program

### Setting Serial Port

- plug in your device and hit scan ports
- select serial port
- select the baud rate
- select the line termination (\r\n is most common)

Line termination ```none``` displays text as it arrived from serial port but you can not display data in a chart.

### Use in Conjunction with Arduino IDE

When you use this application together with Arduino IDE, you can not program your microcontroller while this application has the port open as serial ports are usually not shared.

- Click close serial port
- Program the microcontroller
- Click open serial port

### Issues with Microcontroller Response

If Serial UI does not pick up data from your microcontroller, the following sequence is suggested:

- Close the serial port
- Unplug and replug the microcontroller
- Scan for serial ports
- Open the serial port
- Adjust baud rate if necessary
- Start the serial text display
- Push the reset button on the microcontroller if available

### Receiving data for Text Display

To receive and display data for the serial monitor:

- Complete setting serial port section above
- Select the serial monitor tab
- Start the text display
- You can save and clear the current content of the display window
- If you scroll one page backwards, the display will stop scrolling
- If you scroll to most recent text, the display will start scrolling

### Sending data

- Complete setting serial port section above
- Enter text in the line edit box
- Transmit it by hiting enter on the keyboard
- Recall previous text sent with up and down arrows

Send complete text files with the send file button. 
The file will need to fit into serial buffer. Only smaller text files will work.

### Plotting data

To plot data with qtgraph. The system can plot up to 5 traces. When data is formatted "Name:Value, ..." Name will appear in the legend.

- Complete setting serial port section above
- Open the Serial Plotter tab
- Select data separator or none if there is only one number per line, most common separator is comma or tab. 
- Click start
- Adjust the view with the horizontal slider
- You can save and clear the currently plotted data
- Click stop and zoom with mouse

The vertical axis is auto scaled based on currently visible data. 

## Modules

### User Interface

The user interface is ``mainWindow.ui``` in the assets folder and was designed with QT Designer.

### Main

The main program loads the user interface and adjust its size to specified with and height compensating for scaling issues with high resolution screens. Almost all QT signal connections to slots are created in the main program. It spawns a new thread for the serial interface handling (python remains a single core application though). Plotting occurs in the main thread as it interacts with the user interface (moving a worker to a separate thread removes access from user interface).

### Serial Helper

The serial helper contains three classes. *```QSerialUI```* handles the interaction between the user interface and *```QSerial```*. It remains in the main thread and emits signals to which *```QSerial```* subscribes. QSerial runs on its own thread and sends data to QSerialUI with signals. *```PSerial```* interfaces with the pySerial module. It provides a unified interface to the serial port capable of obtaining all currently available bytes in the buffer and it can convert these into lines of bytes for plotting and display purpose.

The serial helpers allow to open, close and change serial port by specifying the baud rate and port. They allow reading and sending byte strings and multiple lines of byte strings. Selecting text encoding and end of line character handling is implemented with custom code not using the textIOWrapper. Data is collated so that we can process several lines of text at once and take advantage of numpy arrays and need less frequent updates of the text display window.

The serial helpers uses 3 continuous timers. One to periodically check for new data on the receiver line. Once new data is arriving the timer interval is reduced to adjust for continuous high throughput. A second timer that emits throughput data (amount of characters received and transmitted) once a second. These 2 timers are setup after QSerial is moved to its own thread (as timers can only interact with the thread where they were started). A third timer trims the displayed text in the display window once per minute.

The challenges in this code is how to run a driver in a separate thread and how to collate text so that processing and visualization can occur with high data rates. Using multithreading in pyQT does not release the Global Interpreter Lock and therefore might not result in performance increase or increased GUI responsiveness.

### Plotter Helper

The plotter helper provides a plotting interface using pyqtgraph. Data is plotted where the newest data is added on the right (chart) and the amount of data shown is selected through an adjustable slider. Vertical axis is auto scaled based on the data available in the buffer.

The plotter helper extracts values from lines of text and appends them to a numpy array. The data array is organized in a circular buffer. The maximum size of that data array is predetermined. A signal trace is a column in the data array and the number of traces is adjusted depending on the numbers present in the line of text but it can not exceed MAX_COLUMNS (5) (in Qgraph_helper.py).

A timer is used to update the chart 10 times per second. Faster updating is not necessary as visual perception is not improved.

Plotting occurs in the main thread as it needs to interact with the Graphical User Interface.

### Future: ADPCM or serialized data transfer

Compressed data or serialized data reception is *```not implemented```* yet.

Data can be encoded on a microcontroller with a codec and decoded on the receiver. ADPCM is a lossy codec that uses little resources on microcontrollers. It would allow to transmit audio data at common baudrates with a compression factor of 4. For example 500k baud allows 50kBytes/second and with 16 bit audio and compression of 4 would allow stereo data transmission. 

For internal reference:

- [ADPCM](https://github.com/pschatzmann/adpcm)
- [Python Implementation Matt](https://github.com/mattleaverton/stream-audio-compression/)
- [Python Implementation acida](https://github.com/acida/pyima)

An alternative is to serialize data frames using MessagePack to send packets of data in a simple structure.
