# Task List

## Auto select Serial Port
When program boots up and serial port finds a suitable port it should select the first non empty port automatically and not the empty item.
[Status: done]
[Implemented: when the serial port list is refreshed and no port is currently connected, the first detected real port is selected instead of the trailing None entry.]

## BLE Connection
If BLE serial device is already connected to system a scanning attempt will not find it.
[Status: done]
[Implemented: on shutdown, SerialUI now requests BLE disconnect before the BLE worker thread and event loop are torn down, so the device is cleanly disconnected when the program closes.]


## Zooming and Panning while Life Update
When charting is paused or stopped one can pan and zoom but when charting is running autoscaling is enabled and one can not zoom into the data while its updating. pyqtgraph has option to deselect plot items in the legend menu. Is it possible to autoscale only to the the items selected in the legend?
[Status: done for pyqtgraph, postponed for fastplotlib]
[Implemented: chart updates keep running while pyqtgraph mouse pan/zoom stays enabled. Manual pan/zoom suspends live x/y follow on the changed axis, and pyqtgraph View All or auto-range can re-enable live follow.]


## Label Parsing
With the data shown below received over BLEserial and displayed in terminal and with C accelerated parser enabled I get duplicate legend lables such as CH0_AVG_1 and and CH0_AVG_2 for all of the items except for "corr". The duplicates do not contain data on the chart.

CH0_AVG:836.9,CH0_RMS:120.36,CH1_AVG:827.1,CH1_RMS:0.00,lag:-15,phase_60Hz:-26.0,corr:0.06
CH0_AVG:837.4,CH0_RMS:120.35,CH1_AVG:827.1,CH1_RMS:0.00,lag:-8,phase_60Hz:-27.9,corr:0.07
CH0_AVG:837.9,CH0_RMS:120.29,CH1_AVG:827.1,CH1_RMS:0.00,lag:9,phase_60Hz:-20.1,corr:0.06

[Status: done]
[Implemented: reproduced the duplicate labels in both the Python and C++ header parsers. The root cause was a trailing comma before the next header being interpreted as an extra empty sub-channel, so labels such as CH0_AVG became CH0_AVG_1 and CH0_AVG_2. Both parsers were updated to ignore that separator-only trailing segment, and the C++ parser module was rebuilt in place.]
