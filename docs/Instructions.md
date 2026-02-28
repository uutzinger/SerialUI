### Setting Serial Port

1. Plug in your device and accept the autodetection or click scan ports.
2. If necessary select the serial port, baud rate, and line termination (`\r\n` or `\n` are most common).

### Setting BLE Device

1. Switch to BLE by clicking the BLE button.
2. Scan for BLE devices, only devices programmed to provide Nordic UART Service will be listed.
3. Select device.
4. Connect device.
5. Select line termination (`\r\n` or `\n` are most common).
6. If a device uses secure connection you will need to pair the device first.
7. If a device has been paired and trusted, you still will need to use Connect, it will not autoconnect to the program.
8. Pair, Trust, Status are only available on Unix like systems. On other systems you will need to use the operating system to pair a device for a secure connection.

### Receiving Data for Text Display

1. Set serial port or BLE as described above.
2. Select the serial monitor tab.
3. Start the text display. 
4. Select whether text from Serial port or BLE or both are displayed.
5. Adjust retained data length. If incoming data exceeds the display length, only the most recent data is displayed.
6. Save and clear displayed data as needed.
7. Record the received data as needed. All incoming data will be recorded regardless of whether it was displayed.

### Sending Data

1. Set serial port or BLE device as described above.
2. Enter text in the line edit box and hit enter. An empty line will transmit `\r\n`.
3. Use up/down arrows to recall previous text.
4. Optional: send a file.


### Plotting Data

1. Set serial port or BLE as described above.
2. You will need to select a line termination other than None.
3. Open the Plotter tab.
4. Select data separator (Simple or with Headers). For supported format read [parsing documentation](../docs/Dataparsing.md).
5. Start plotting.
6. Adjust view with the horizontal slider.
7. Click stop or pause and zoom and pan with the mouse.
8. Save and clear plotted data or save the figure.
9. Whether you plot with pyqtgraph or fastplotlib is set in the configuration file. You can not change it when you use the precompiled executable.
10. pyqtgrpah can save figures are vetorgraphics (svg). fastplotlib saves as bitmap (png) only.
11. Please be aware that when selecting plotting tab the first time with fastplotlib, it will take about 5-10 sec to build the chart.
