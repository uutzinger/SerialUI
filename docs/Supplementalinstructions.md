## Supplemental Instructions

### Use in Conjunction with Arduino IDE
- To program your microcontroller while this program is running, click close serial port.
- Program the microcontroller.
- Make sure the Arduino IDE has the Serial Monitor or Serial Plotter closed.
- Click open serial port.

You can not open the serial port when it is in use by Arduino IDE serial monitor or serial plotter.

### Issues with Microcontroller Response
SerialUI attempts to reconnect when microcontroller is unplugged and reattached. Otherwise try to resolve issues in the following order:

- Click Reset ESP (for ESP type boards)
- Push the reset button on the microcontroller if available.
- Close the serial port. Unplug and replug the microcontroller. Scan for serial ports.
  
## How to make a Desktop Link for this Program

### Linux
In the `linux_app` folder edit `SerialUI.desktop` and in the main folder `run.sh` to match the location of your files. Run the provided `install.sh` script in the `linux_app` folder.

### Windows
Create a desktop short cut and then edit the short cut properties:
- change the target so that it includes the python executable followed by the python program `SerialUI.py`. Put quotation marks around the path to python executable and also around the location of the main python program.
- change the target folder to be the location of the `SerialUI.py` program.
- change the icon to a picture you can find in assets folder
