## Performance

***Summary:*** The SerialUI is as performant as other terminal programs. The maximum text transfer of an ESP32-S3 is about 800k bytes/s over USB and 100k bytes/s over BLE. A Cortex-M7 reaches about 7M bytes/s.

### Materials and Methods

The following programs were used to measure serial transfer performance:
- [SerialUI](https://github.com/uutzinger/SerialUI)
- [Arduino IDE (2.3.5)](https://www.pjrc.com/improving-arduino-serial-monitor-performance/)
- [Putty](https://www.putty.org/)
- [Nordic Serial Terminal]() 
- `cat /dev/ttyACM0 | pv -r > /dev/null`
- `screen /dev/ttyACM0 4000000`

A text line generator for [USB](../Arduino_programs/testSerial/testSerial.ino) and [BLE](../Arduino_programs/testBLESerial/testBLESerial.ino) were used to measure the text transferred per second. The line generator produces lines with the following content:
`count= 10293517, lines/sec=  3768` It sends these lines to a ring buffer which is consumed in the main loop. The test program also responds to serial input and blinks the LED.

The developer of the Teensy microcontroller Paul Stoffregen created a simple [test program](https://github.com/PaulStoffregen/USB-Serial-Print-Speed-Test/blob/master/usb_serial_print_speed.ino)  which continuously sends text to the serial port. This program is simpler than the text line generator above as it does not use a buffer between data producer and consumer and does not handle serial input.

Charting performance was evaluated using SerialUI and ArduinoIDE. Values from two phase shifted sine waves at 100Hz were generated and transmitted as comma separated values. The sample rate was set to 200,000, 80,000 and 24,000 samples per second for each channel. Chart refresh rate of Serial UI was set to 10 Hz in the config file. The window length was increased until the transfer rate started decreasing, indicating that the serial receiver could not keep up.

The reference computer was a notebook with AMD Ryzen 7, 4800H, RTX3060M.

### Results

Cortex-M7 microcontroller is about 8 times faster than ESP32-S3. BLE text transfer is about 8 times slower than USB text transfer. We achieved about 1M bit/s BLE through compared to reported real world throughput of 1.4M bit/s.

With pyqtgraph framework the plotting window length is limited when serial transfer rate is large.

With fastplotlib the plotting window length did not affect the transfer rate. Because of its ability to update portions of the signal trace at low sampling rates and large window lengths much less data needed to be transferred to the plotting engine.

BLE transfer ....

#### Test Display

Table 1: Text line generator:

| lines/sec | bytes/sec | Application |
|----------:|----------:|--------------|
| **USB**  |
| *ESP32-S3 Feather*|
|  26322    | 874 k     | SerialUI     |
|  26380    | 876 k     | ArduinoIDE   |
|  26366    | 875 k     | Putty        |
|  26373    | 876 k     | Nordic Serial Terminal |
| *Cortex-M7 Teensy 4.0*|
| 211 k    | 7.0 M     | SerialUI |
| 212 k    | 7.03 M    | ArduinoIDE |
| 211 k    | 7.0 M     | Putty        |
| 212 k    | 7.03 M    | Nordic Serial Terminal |
| **BLE** |
| *ESP32-S3 Feather*|
|   3840    | 128 k     | Serial UI (BLEAK)|

Table 2: Text line generator Stoffregen:

| lines/sec | bytes/sec | Application |
|----------:|----------:|--------------|
| **USB**  |
| *ESP32-S3 Feather*|
| 26917 |  942 k     | SerialUI     |
| 26914 |  942 k     | ArduinoIDE   |
| 26915 |  942 k     | Putty        |
| 26903 |  942 k     | Nordic Serial Terminal |
| 26257 |  919 K     | cat |
| 26906 |  942 k     | screen |
| *Cortex-M7 Teensy 4.0*|
|  525 k | 18 M     | SerialUI |
|  530 k | 18 M     | ArduinoIDE |
|  330 k | 11 M     | Putty        |
|  528 k | 18 M     | Nordic Serial Terminal |
|  514 k | 17.6 M   | cat |
|  150 K | 5.1 M    | screen |

#### Charting

Limits on the reference notebook computer (AMD Ryzen 7, 4800H, RTX3060M) when plotting two 100Hz sine waves (stereo) with no labels. 

| Window length | Samples/sec/channel| Serial Input Bytes/sec | Points/sec | Painter | Resolution |
| ---: | ---:|---:|---:|---:|---|
| **USB** | | | | | |
|  8192 | 200 k | 2.0 M | 160 k | qtgraph | 1280x800  |
|  7000 | 200 k | 2.0 M | 141 k | qtgraph | 2560x1440 |
| 20480 |  80 k | 870 k | 400 k | qtgraph | 1280x800  |
| 18000 |  80 k | 870 k | 351 k | qtgraph | 2560x1440 |
| 30000 |  24 k | 252 k | 586 k | qtgraph | 1280x800  |
| 24000 |  24 k | 252 k | 469 k | qtgraph | 2560x1440 |
|  | | | | |
| 131072 | 200 k | 2.1 M | 390 k | fastplotlib | 1280x800  |
| 131072 | 200 k | 2.1 M | 390 k | fastplotlib | 2560x1440 |
| 131072 |  80 k | 840 k | 150 k | fastplotlib | 1280x800  |
| 131072 |  80 k | 840 k | 150 k | fastplotlib | 2560x1440 |
| 131072 |  24 k | 245 k |  44 k | fastplotlib | 1280x800  |
| 131072 |  24 k | 245 k |  44 k | fastplotlib | 2560x1440 |
| **BLE** | | | |
| 512 | 16 k | 10.2 k | | qtgraph | |
| TBD  | TBD  | TBD  | | fastplotlib | |

Arduino IDE plots 50 samples in a window but does not provide performance metrics. The Window length can not be adjusted.

### Conclusions

The SerialUI is as fast as other comparable programs.

### Discussion

#### Text Dislay

The `Qt plain text display widget` poses a limit for text display in Python. It can display about 70k lines/sec. It considers a line of text a paragraph. To achieve higher lines/sec rate, in the SerialUI display, only the most recent text is displayed. The user selects the text history length. SerialUI skips data that does not fit into the text history until the next window refresh. When data recording is selected, received data is saved to a file without skipping. Recording does not seem to slow the display. The text history length in Arduino IDE is about 1M byte or 30,000 lines. SerialUI limits it to 5,000 lines. If faster scrollable text display is needed, one would need to program it from scratch using an QOpenGLWidget or pygfx approach.

#### Charting

With **pyqtgraph** it is possible to plot about 6 Million line segments per second while the main python thread experiences 80% utilization and several CPU cores are supporting the charting task. However we can not reach those numbers in SerialUI as we also handle the serial port and other events.

**fastplotlib** can utilize a GPU and handles about 15 Million line segments per second (OpenGL) with 85% utilization or 10 Million line segments with 60% utilization (Vulkan) in a 800x600 display frame. With full screen display, the rates drop to 1/2 to 1/3. Fastplotlib also has good performance with CPU integrated GPUs.
