## Modules

### User Interface
The UI is defined in `serialUI.ui` (assets folder) and designed with QT Designer 5. If you modify it with Designer 6 it will no longer work with Qt5.

### Main Program
The main program (`SerialUI.py`) loads the UI, adjusts its size, handles QT signal connections, and manages the serial, BLE, USB monitor threads. Plotting occurs in the main thread.

### Serial Helper
Includes two classes:
- `QSerial`: Manages UI interaction, runs in the main thread.
- `Serial`: Runs on its own thread, communicates with `QSerial`.

### BLE Helper
Includes classes:
- Async scheduler for bleak commands. Since bleak utilized async framework its necessary to integrate a custom worker to run bleak in separate thread. Qt async interface utilizes the main thread.
- `QBLESerial`: Manages UI interaction, runs in the main thread.
- `BleakWorker`: Runs bleak commands on its own loop, communicates with `QBLESerial`.
- `BluetoothctlWorker`: Interfaces Bluetoothctl helper for pairing and trusting.

### Bluetoothctl Helper
Provides interface to bluetoothctl utility on Unix like systems.

### Graphing Helper
Uses pyqtgraph or fastplotlib for plotting. Data is stored in a circular buffer, and plotting occurs in the main thread.
The figure is initialized once the user interface is established and the user selects the plotting tab the first time.
`updatePlot` was optimized for high data rate plotting.

### Indicator Helper
The indicator helper provides an interface to display data in numeric text fields. It also provides ability to display vectors. This is not implemented yet.

### General Helper
Reoccurring functions are collected in this module. It also provides optimized environment variables to handle the operating system and user interface as well as handling signals in Qt.

### Current Developement
- binary data transmission including ADPCM, zlib, tamp for compressed data reception.
- indicator
