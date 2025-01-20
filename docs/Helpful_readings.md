## Signals and Slots and Threads

### [Using PyQt's QThread to Prevent Freezing GUIs](https://realpython.com/python-pyqt-qthread/)
This tutorial on Real Python explains how to use PyQt's `QThread` to handle long-running tasks without freezing the GUI. It covers creating reusable threads with `QThreadPool` and `QRunnable`, managing interthread communication using signals and slots, and best practices for multithreaded GUI applications in PyQt.

### [PyQt Signals and Slots](https://www.tutorialspoint.com/pyqt/pyqt_signals_and_slots.htm)
This Tutorialspoint article explains the concept of signals and slots in PyQt, which is used to handle events in a GUI application. It provides examples of connecting signals to slots using both the old and new syntax, demonstrating how to respond to user actions like button clicks by connecting signals to custom slot functions.

### [How to Use QThread in the Right Way (Part 1)](http://blog.debao.me/2013/08/how-to-use-qthread-in-the-right-way-part-1/)
This blog post by Debao Zhang details the correct usage of QThread in PyQt. It explains the pitfalls of subclassing QThread and reimplementing its run() method, especially when using slots and the Qt event loop. The recommended approach involves creating worker objects and moving them to separate threads using `QObject::moveToThread` to ensure proper execution of slots and prevent blocking the main GUI thread.

##   Examples with Worker Tread

### [PyQt5: How to Send a Signal to a Worker Thread](https://stackoverflow.com/questions/41026032/PyQt5-how-to-send-a-signal-to-a-worker-thread)
This Stack Overflow discussion provides solutions for sending signals to a worker thread in PyQt5. The key point is to create the signal-emitting object within the worker thread to ensure thread safety. The example demonstrates creating a `Communicate` class to define custom signals, and then connecting these signals to slots within the worker thread. The provided example code highlights the proper setup for bi-directional communication between the main thread and worker threads using `QThread` and `pyqtSignal`.

### [Stopping an Infinite Loop in a Worker Thread in PyQt5](https://stackoverflow.com/questions/68163578/stopping-an-infinite-loop-in-a-worker-thread-in-PyQt5-the-simplest-way)
This Stack Overflow post discusses solutions for stopping an infinite loop within a PyQt5 worker thread without blocking the event loop. The preferred method involves using a `QTimer` to replace the while loop, allowing the event loop to remain active and handle signals. Another solution is to use a control variable (e.g., a dictionary) shared between the main thread and the worker to manage the loop's execution state. These approaches ensure the application remains responsive and can properly process signals and events.

### [Threading with QRunnable - Proper Manner of Sending Bi-Directional Callbacks](https://stackoverflow.com/questions/61625043/threading-with-qrunnable-proper-manner-of-sending-bi-directional-callbacks)
This Stack Overflow post addresses how to use QRunnable for threading in PyQt applications, focusing on bi-directional communication between the main thread and worker threads. The recommended solution involves using `QObject` to define signals and slots, ensuring the same signal object is used for both connection and emission. The example demonstrates creating a `Worker` class inheriting from `QRunnable` and a `WorkerSignals` class for defining custom signals. This setup allows for robust inter-thread communication, enabling the main GUI to send and receive signals from the worker thread effectively.

### [PyQt5 Signal Communication Between Worker Thread and Main Window Not Working](https://stackoverflow.com/questions/52973090/PyQt5-signal-communication-between-worker-thread-and-main-window-is-not-working)
This Stack Overflow post discusses troubleshooting issues with signal communication between a worker thread and the main window in PyQt5. The main issue addressed is the common misconception about `QThread`. `QThread` is not a Qt thread but rather a thread handler. The solution involves using a `QObject` as the base class for the worker, moving it to a new thread with `moveToThread()`, and ensuring signal-slot connections are properly set up. The provided example demonstrates creating a worker object, connecting signals for button updates, and managing thread communication without blocking the GUI.

## Timer, infinite loop

### [How to Use a QTimer in a Separate QThread](https://stackoverflow.com/questions/55651718/how-to-use-a-qtimer-in-a-separate-qthread)
This Stack Overflow post explains that to use a QTimer in a separate QThread, you must ensure the QTimer is created after the QThread has started its event loop. By default, `QThread.run()` starts a local event loop, but overriding it prevents the timer events from being processed. The recommended approach is to create a worker QObject, move it to a separate thread, and set up the QTimer within this worker. The example provided demonstrates proper setup, ensuring the timer runs in the correct thread and processes events via signals and slots.

### [QTimer in Worker Thread](https://stackoverflow.com/questions/23607294/qtimer-in-worker-thread)
This Stack Overflow post discusses the canonical way to use a QTimer within a worker thread. The key points include ensuring that the QTimer is owned by a QObject-based worker class and that this worker is moved to a separate thread. The worker's event loop handles the timer's timeout events, and all inter-thread communication is managed through signals and slots. The post emphasizes the importance of thread-safe communication and provides an example of a worker class utilizing a QTimer to process periodic tasks in a separate thread.

### [How to Properly Stop QTimer from Another Thread](https://stackoverflow.com/questions/60649644/how-to-properly-stop-qtimer-from-another-thread)
This Stack Overflow post explains that to stop a QTimer from another thread, you must ensure the QTimer is created and controlled within the same thread it operates. The recommended solution involves moving the QTimer to the desired thread and using signals and slots to control its start and stop operations. The example provided demonstrates a worker class where the QTimer is created and managed within the same thread, ensuring thread-safe operations.

### [Use QTimer to Run Functions in an Infinite Loop](https://stackoverflow.com/questions/47661854/use-qtimer-to-run-functions-in-an-infinte-loop)
This Stack Overflow post discusses how to use QTimer to run functions in an infinite loop within a PyQt application. The key point is to avoid blocking the event loop, which can be achieved by periodically processing pending events. The preferred approach is to move the blocking task into a separate worker thread to ensure the main event loop remains responsive. The provided example demonstrates setting up a QTimer to repeatedly call a function at specified intervals, and using a QThread to handle the loop without blocking the GUI.

### [Starting QTimer in a QThread](https://stackoverflow.com/questions/10492480/starting-qtimer-in-a-qthread)
This Stack Overflow post discusses how to properly start a QTimer within a QThread. The key point is ensuring that the QTimer is created and moved to the same thread it will operate in. The recommended approach is to connect the QTimer's `start` method to the QThread's `started` signal. This ensures the QTimer starts when the thread's event loop begins. An example is provided to demonstrate setting up a worker object and connecting the QTimer's timeout signal to a slot that performs the desired work.

### [No Event Loop or Use of QTimer in Non-GUI/Qt Threads](https://programmer.ink/think/no-event-loop-or-use-of-qtimer-in-non-gui-qt-threads.html)
This article explains the necessity of having an event loop when using QTimer in non-GUI or non-Qt threads. It provides two solutions: creating a local QEventLoop manually or using QThreads with their own event loops. The examples demonstrate how to implement both methods, ensuring that QTimer functions correctly in non-GUI threads by processing events properly. The provided code examples show how to set up and manage QTimers within these threads effectively.

### [How to Use QTimer inside QThread which uses QWaitCondition? (pyside)](https://www.pythonfixing.com/2022/03/fixed-how-to-use-qtimer-inside-qthread.html)
This article addresses the challenge of using QTimer within a QThread that also employs QWaitCondition. The main issue is that the event loop required by QTimer is not active when QWaitCondition is used. The solution involves calling `QCoreApplication::processEvents()` within the loop to ensure that queued events are processed. This allows the QTimer to function correctly within the thread, handling signals and slots even in a continuous loop scenario.


## Examples using pySerial

### [Python Uses PyQt5 to Write a Simple Serial Assistant](https://programmer.group/python-uses-pyqt5-to-write-a-simple-serial-assistant.html)
This article details the creation of a simple serial assistant in Python using PyQt5. The assistant is designed to communicate between a PC and a serial device. It covers setting the serial port and baud rate, sending and receiving data, and building the interface with PyQt5. The guide includes code examples for initializing the serial port, creating the UI with grid layout, and handling data transmission. Additionally, it discusses adding signal-slot connections for button actions to manage serial port operations effectively.

### [Serial Communication GUI Program](https://github.com/mcagriaksoy/Serial-Communication-GUI-Program)
This GitHub repository contains a free COM (serial communication) client tool written in PyQt6, serves as a reference. The tool allows users to send and receive data via the serial port (COM port) of their computer. Key features include support for multiple COM ports, automatic detection of available ports, configurable communication parameters (e.g., baud rate), and a user-friendly interface displaying data in hexadecimal, decimal, ASCII, or binary formats.

### [PyQt Serial Terminal](https://hl4rny.tistory.com/433)
This blog post provides a detailed guide on creating a simple serial terminal using PyQt. It demonstrates how to use threading to manage serial communication without freezing the GUI. Key features include handling incoming and outgoing serial data, using signals for thread-safe communication, and integrating a basic user interface for displaying and sending data. The post includes code snippets for setting up the serial connection, managing threads, and creating the UI with PyQt.

### [PyQt Serial Terminal Code](https://iosoft.blog/pyqt-serial-terminal-code)
This blog post describes creating a simple serial terminal using PyQt. The application demonstrates threading in PyQt, enabling serial communication without freezing the GUI. Key features include managing incoming and outgoing serial data, using signals for thread-safe communication, and implementing a basic user interface with PyQt. The post includes detailed code examples for setting up the serial connection, handling threads, and creating the UI. It also discusses methods for managing serial data efficiently and ensuring the application remains responsive.

## Examples using QSerialPort

### [Connect to Serial from a PyQt GUI](https://stackoverflow.com/questions/55070483/connect-to-serial-from-a-pyqt-gui)
This Stack Overflow post provides guidance on establishing a serial connection from a PyQt GUI. The solution involves creating a QSerialPort object and connecting it to the appropriate signals for reading and writing data. The example code demonstrates setting up a button to toggle the serial connection, reading incoming data, and sending data through the serial port.

### [PyQt5 Serial Monitor](https://web.archive.org/web/20230401015052/https://ymt-lab.com/en/post/2021/pyqt5-serial-monitor/)
This guide from YMT Lab details the creation of a serial port monitor using PyQt5's QSerialPort, demonstrating how to configure and interact with serial ports through a graphical interface. Key features include setting up serial port parameters, sending and receiving data, and displaying the data in both text and hexadecimal formats. The article provides a comprehensive code example, showing how to build the user interface, handle serial communication, and update the display with received data.

## PyQtGraph

### [Embedding PyQtGraph Custom Widgets in a Qt App](https://www.pythonguis.com/tutorials/embed-pyqtgraph-custom-widgets-qt-app/)
This tutorial provides a step-by-step guide on how to embed custom PyQtGraph widgets in a Qt application using Qt Designer. It covers the process of creating a placeholder widget in Qt Designer, promoting it to a PyQtGraph widget, and loading the UI file in a Python script to display the custom plot.

### [PyQtGraph Documentation](https://www.pyqtgraph.org/)
The official PyQtGraph website provides comprehensive documentation, including installation instructions, examples, and API reference. It is the main resource for understanding the technical capabilities and usage of PyQtGraph for creating interactive plots in Python apps.

### [Plotting with PyQtGraph](https://www.pythonguis.com/tutorials/plotting-pyqtgraph/)
This tutorial focuses on creating interactive plots using PyQtGraph. It demonstrates how to set up a plotting widget, customize plot appearance (e.g., line color, width, style), add markers, titles, and axis labels, and manage plot legends and background grids.

### [PyQtGraph Example - Scrolling Plots](https://github.com/pyqtgraph/pyqtgraph/blob/master/pyqtgraph/examples/scrollingPlots.py)
An example script from the PyQtGraph GitHub repository that shows how to create scrolling plots, useful for understanding how to handle real-time data updates and visualize them dynamically.

### [PyQtGraph Scrolling Plots - StackOverflow](https://stackoverflow.com/questions/65332619/pyqtgraph-scrolling-plots-plot-in-chunks-show-only-latest-10s-samples-in-curre)
StackOverflow discussion that provides good reference for implementing scrolling plots with PyQtGraph. It includes code snippets and explanations for plotting data in chunks and displaying only the most recent samples.

## Example Applications

### [EKG Monitor](https://github.com/pbmanis/EKGMonitor)
This repository provides a Python-based EKG monitor using PyQtGraph. It can read input from a soundcard or an Arduino with the Olimex EKG/EMG shield. The monitor filters and amplifies the signal, displaying heart rate and variability. It includes real-time data acquisition, filtering, and saving of recorded data for further analysis.