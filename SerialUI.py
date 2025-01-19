#!/usr/bin/env python3
#############################################################################################################################################
# Serial Communication GUI
# ========================
#
# - Provides serial interface to send and receive text to/from serial port.
# - Plots of data on chart with zoom, save and clear.
#
# This code is maintained by Urs Utzinger
#############################################################################################################################################

# QT imports, QT5 or QT6
try:
    from PyQt6 import QtCore, QtWidgets, QtGui, uic
    from PyQt6.QtCore import QThread, QTimer, QEventLoop
    from PyQt6.QtWidgets import (
        QMainWindow, QLineEdit, QSlider, 
        QMessageBox, QDialog, QVBoxLayout, 
        QTextEdit, QTabWidget,
    )
    from PyQt6.QtGui import QIcon, QShortcut, QKeySequence
    hasQt6 = True
except:
    from PyQt5 import QtCore, QtWidgets, QtGui, uic
    from PyQt5.QtCore import QThread, QTimer, QEventLoop
    from PyQt5.QtWidgets import (
        QMainWindow, QLineEdit, QSlider, 
        QMessageBox, QDialog, QVBoxLayout, 
        QTextEdit, QTabWidget
    )
    from PyQt5.QtGui import QIcon, QTextCursor, QPalette, QColor
    hasQt6 = False

# Markdown for documentation
from markdown import markdown    

# System
import logging, os, sys
from datetime import datetime

# Custom program specific imports
from helpers.Qserial_helper     import QSerial, QSerialUI, USBMonitorWorker
from helpers.Qgraph_helper      import QChartUI, MAX_ROWS

if not hasQt6:
    # Deal with high resolution displays
    if hasattr(QtCore.Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(QtCore.Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

# Future release will include option for displaying data in indicators
#  and 3D vector plots.
USE3DPLOT = False

#############################################################################################################################################
#############################################################################################################################################
#
# Main Window
#
#    This is the Viewer of the Model - View - Controller (MVC) architecture.
#
#############################################################################################################################################
#############################################################################################################################################

class mainWindow(QMainWindow):
    """
    Create the main window that stores all of the widgets necessary for the application.
    """

    # ----------------------------------------------------------------------------------------------------------------------
    # Initialize
    # ----------------------------------------------------------------------------------------------------------------------

    def __init__(self, parent=None, logger=None):
        """
        Initialize the components of the main window.
        This will create the connections between slots and signals in both directions.

        Serial:
        Create serial worker and move it to separate thread.

        Serial Plotter:
        Create chart user interface object.
        """
        super(mainWindow, self).__init__(parent)  # parent constructor

        if logger is None:
            self.logger = logging.getLogger("Main___")
        else:
            self.logger = logger
        

        main_dir = os.path.dirname(os.path.abspath(__file__))

        # ----------------------------------------------------------------------------------------------------------------------
        # User Interface
        # ----------------------------------------------------------------------------------------------------------------------
        self.ui = uic.loadUi("assets/serialUI.ui", self)
        icon_path = os.path.join(main_dir, "assets", "serial_48.png")
        window_icon = QIcon(icon_path)
        self.setWindowIcon(QIcon(window_icon))
        self.setWindowTitle("Serial GUI")

        # Find the tabs and connect to tab change
        # ----------------------------------------------------------------------------------------------------------------------
        self.tabs = self.findChild(QTabWidget, "tabWidget_MainWindow")
        self.tabs.currentChanged.connect(self.on_tab_change)

        # 3D plot windows
        # ----------------------------------------------------------------------------------------------------------------------

        if USE3DPLOT ==  True:
            self.ui.ThreeD_1.setEnabled(True)
            self.ui.ThreeD_2.setEnabled(True)
            self.ui.ThreeD_3.setEnabled(True)
            self.ui.ThreeD_4.setEnabled(True)
        else:
            self.ui.ThreeD_1.setEnabled(False)
            self.ui.ThreeD_2.setEnabled(False)
            self.ui.ThreeD_3.setEnabled(False)
            self.ui.ThreeD_4.setEnabled(False)

        #----------------------------------------------------------------------------------------------------------------------
        # Serial
        # ----------------------------------------------------------------------------------------------------------------------

        # Serial Thread
        self.serialThread = QThread()                                      # create QThread object
        self.serialThread.start()                                          # start thread which will start worker

        # Create serial worker
        self.serialWorker = QSerial()                                      # create serial worker object

        # Create user interface hook for serial
        self.serialUI = QSerialUI(ui=self.ui, worker=self.serialWorker, logger=self.logger)    # create serial user interface object

        # Connect worker / thread
        self.serialWorker.finished.connect(self.serialThread.quit)         # if worker emits finished quite worker thread
        self.serialWorker.finished.connect(self.serialWorker.deleteLater)  # delete worker at some time
        self.serialThread.finished.connect(self.serialThread.deleteLater)  # delete thread at some time

        # Signals from Serial to Serial-UI
        # ---------------------------------
        self.serialWorker.textReceived.connect(     self.serialUI.on_SerialReceivedText)  # connect text display to serial receiver signal
        self.serialWorker.linesReceived.connect(    self.serialUI.on_SerialReceivedLines) # connect text display to serial receiver signal
        self.serialWorker.newPortListReady.connect( self.serialUI.on_newPortListReady)    # connect new port list to its ready signal
        self.serialWorker.newBaudListReady.connect( self.serialUI.on_newBaudListReady)    # connect new baud list to its ready signal
        self.serialWorker.serialStatusReady.connect(self.serialUI.on_serialStatusReady)   # connect display serial status to ready signal
        self.serialWorker.throughputReady.connect(  self.serialUI.on_throughputReceived)  # connect display throughput status
        self.serialWorker.serialWorkerStateChanged.connect( self.serialUI.on_serialWorkerStateChanged) # mirror serial worker state to serial UI
        self.serialWorker.logSignal.connect(        self.serialUI.on_logSignal)           # connect log messages to BLE UI

        # Signals from Serial-UI to Serial
        # ---------------------------------
        self.serialUI.changePortRequest.connect(     self.serialWorker.on_changePortRequest)     # connect changing port
        self.serialUI.closePortRequest.connect(      self.serialWorker.on_closePortRequest)      # connect close port
        self.serialUI.changeBaudRequest.connect(     self.serialWorker.on_changeBaudRateRequest) # connect changing baud rate
        self.serialUI.changeLineTerminationRequest.connect(self.serialWorker.on_changeLineTerminationRequest)  # connect changing line termination
        self.serialUI.scanPortsRequest.connect(      self.serialWorker.on_scanPortsRequest)      # connect request to scan ports
        self.serialUI.scanBaudRatesRequest.connect(  self.serialWorker.on_scanBaudRatesRequest)  # connect request to scan baud rates
        self.serialUI.setupReceiverRequest.connect(  self.serialWorker.on_setupReceiverRequest)  # connect start receiver
        self.serialUI.startReceiverRequest.connect(  self.serialWorker.on_startReceiverRequest)  # connect start receiver
        self.serialUI.stopReceiverRequest.connect(   self.serialWorker.on_stopReceiverRequest)   # connect start receiver
        self.serialUI.sendTextRequest.connect(       self.serialWorker.on_sendTextRequest)       # connect sending text
        self.serialUI.sendLineRequest.connect(       self.serialWorker.on_sendLineRequest)       # connect sending line of text
        self.serialUI.sendLinesRequest.connect(      self.serialWorker.on_sendLinesRequest)      # connect sending lines of text
        self.serialUI.serialStatusRequest.connect(   self.serialWorker.on_serialStatusRequest)   # connect request for serial status
        self.serialUI.finishWorkerRequest.connect(   self.serialWorker.on_stopWorkerRequest)     # connect finish request
        self.serialUI.startThroughputRequest.connect(self.serialWorker.on_startThroughputRequest) # start throughput
        self.serialUI.stopThroughputRequest.connect( self.serialWorker.on_stopThroughputRequest) # stop throughput
        self.serialUI.serialSendFileRequest.connect( self.serialWorker.on_sendFileRequest)       # send file to serial port

        # Prepare the Serial Worker and User Interface
        # --------------------------------------------
        self.serialWorker.moveToThread(self.serialThread)  # move worker to thread
        self.serialUI.scanPortsRequest.emit()              # request to scan for serial ports
        self.serialUI.scanBaudRatesRequest.emit()              # request to scan for serial ports
        self.serialUI.setupReceiverRequest.emit()          # establishes QTimer in the QThread above
        # do not initialize baud rate, serial port or line termination, user will need to select at startup

        # Signals from User Interface to Serial-UI
        # ----------------------------------------
        # User selected port or baud
        self.ui.comboBoxDropDown_SerialPorts.currentIndexChanged.connect(    self.serialUI.on_comboBoxDropDown_SerialPorts) # user changed serial port
        self.ui.comboBoxDropDown_BaudRates.currentIndexChanged.connect(      self.serialUI.on_comboBoxDropDown_BaudRates)   # user changed baud rate
        self.ui.comboBoxDropDown_LineTermination.currentIndexChanged.connect(self.serialUI.on_comboBoxDropDown_LineTermination) # User changed line termination
        self.ui.pushButton_SerialScan.clicked.connect(      self.serialUI.on_pushButton_SerialScan)         # Scan for ports
        self.ui.pushButton_SerialStartStop.clicked.connect( self.serialUI.on_pushButton_SerialStartStop)    # Start/Stop serial receive
        self.ui.pushButton_SerialSend.clicked.connect(      self.serialUI.on_serialSendFile)                # Send text from a file to serial port
        self.ui.lineEdit_SerialText.returnPressed.connect(  self.serialUI.on_serialMonitorSend)             # Send text as soon as enter key is pressed
        self.ui.pushButton_SerialClearOutput.clicked.connect(self.serialUI.on_pushButton_SerialClearOutput) # Clear serial receive window
        self.ui.pushButton_SerialSave.clicked.connect(      self.serialUI.on_pushButton_SerialSave)         # Save text from serial receive window
        self.ui.pushButton_SerialOpenClose.clicked.connect( self.serialUI.on_pushButton_SerialOpenClose)    # Open/Close serial port

        # User hit up/down arrow in serial lineEdit
        self.shortcutUpArrow   = QtWidgets.QShortcut(QtGui.QKeySequence.MoveToPreviousLine, self.ui.lineEdit_SerialText, self.serialUI.on_serialMonitorSendUpArrowPressed)
        self.shortcutDownArrow = QtWidgets.QShortcut(QtGui.QKeySequence.MoveToNextLine,     self.ui.lineEdit_SerialText, self.serialUI.on_serialMonitorSendDownArrowPressed)
        # ESP reset radio button
        self.ui.radioButton_ResetESPonOpen.clicked.connect( self.serialUI.on_resetESPonOpen) # Reset ESP32 on open
        # Done with Serial
        self.logger.log(
            logging.INFO,
            "[{}]: serial initialized.".format(int(QThread.currentThreadId())),
        )

        # ----------------------------------------------------------------------------------------------------------------------
        # Serial Plotter
        # ----------------------------------------------------------------------------------------------------------------------
        # Create user interface hook for chart plotting
        self.chartUI = QChartUI(ui=self.ui, serialUI=self.serialUI, serialWorker=self.serialWorker)  # create chart user interface object
        self.ui.pushButton_ChartStartStop.clicked.connect(self.chartUI.on_pushButton_StartStop)
        self.ui.pushButton_ChartClear.clicked.connect(    self.chartUI.on_pushButton_Clear)
        self.ui.pushButton_ChartSave.clicked.connect(     self.chartUI.on_pushButton_ChartSave)
        self.ui.pushButton_ChartSaveFigure.clicked.connect(self.chartUI.on_pushButton_ChartSaveFigure)

        self.ui.comboBoxDropDown_DataSeparator.currentIndexChanged.connect(self.chartUI.on_changeDataSeparator)

        # Horizontal Zoom
        self.horizontalSlider_Zoom = self.ui.findChild(QSlider, "horizontalSlider_Zoom")
        self.horizontalSlider_Zoom.setMinimum(8)
        self.horizontalSlider_Zoom.setMaximum(MAX_ROWS)
        self.horizontalSlider_Zoom.valueChanged.connect(   self.chartUI.on_HorizontalSliderChanged)

        self.lineEdit_Zoom = self.ui.findChild(QLineEdit, "lineEdit_Horizontal")
        self.lineEdit_Zoom.returnPressed.connect(          self.chartUI.on_HorizontalLineEditChanged)

        # Done with Plotter
        self.logger.log(
            logging.INFO,
            "[{}]: plotter initialized.".format(int(QThread.currentThreadId())),
        )

        # ----------------------------------------------------------------------------------------------------------------------
        # Menu Bar
        # ----------------------------------------------------------------------------------------------------------------------
        # Connect the action_about action to the show_about_dialog slot
        self.ui.action_About.triggered.connect(self.show_about_dialog)
        self.ui.action_Help.triggered.connect( self.show_help_dialog)

        # ----------------------------------------------------------------------------------------------------------------------
        # Status Bar
        # ----------------------------------------------------------------------------------------------------------------------
        self.statusTimer = QTimer(self)
        self.statusTimer.timeout.connect(self.on_resetStatusBar)
        self.statusTimer.start(10000)  # Trigger every 10 seconds

        # ----------------------------------------------------------------------------------------------------------------------
        # Finish up
        # ----------------------------------------------------------------------------------------------------------------------
        self.show()

        #----------------------------------------------------------------------------------------------------------------------
        # Check for USB device connect/disconnect
        #----------------------------------------------------------------------------------------------------------------------

        self.usbThread = QThread()
        self.usbWorker = USBMonitorWorker()
        self.usbWorker.moveToThread(self.usbThread)
        
        # Connect signals and slots
        self.usbThread.started.connect(   self.usbWorker.run)
        self.usbWorker.finished.connect(  self.usbThread.quit)          # if worker emits finished quite worker thread
        self.usbWorker.finished.connect(  self.usbWorker.deleteLater)   # delete worker at some time
        self.usbThread.finished.connect(  self.usbThread.deleteLater)   # delete thread at some time
        self.usbWorker.usb_event_detected.connect(self.serialUI.on_usb_event_detected)
        self.usbWorker.logSignal.connect( self.serialUI.on_logSignal)
        self.usbThread.started.connect(   self.usbWorker.run)

        # Start the USB monitor thread
        self.usbThread.start()

    def on_tab_change(self, index):
        """
        Respond to tab change event
        """
        tab_name = self.tabs.tabText(index)
        if tab_name == "Monitor":
            self.ui.plainTextEdit_SerialTextDisplay.verticalScrollBar().setValue(self.ui.plainTextEdit_SerialTextDisplay.verticalScrollBar().maximum())
            self.ui.plainTextEdit_SerialTextDisplay.ensureCursorVisible()
        elif tab_name == "Plotter":
            pass
        elif tab_name == "Indicator":
            pass
        else:
            try:
                self.logger.log(
                    logging.ERROR,
                    "[{}]: unknown tab name: {}".format(
                        int(QThread.currentThreadId()), tab_name
                    ),
                )
            except:
                pass

    def handle_usbThread_finished(self):
        self.logger.log(logging.INFO, "USB monitor thread finished.")

    def closeEvent(self, event):
        """
        Respond to window close event.
        Close the serial port, stop the serial thread and the chart update timer.
        """
        self.chartUI.ChartTimer.stop()  # stop the chart timer
        if self.serialWorker:
            if self.serialUI:
                self.serialUI.finishWorkerRequest.emit()     # emit signal to finish worker

                if self.usbWorker:                           # stop the USB monitor thread
                    self.usbWorker.stop()
                    self.usbThread.quit()

                loop = QEventLoop()                          # create event loop
                self.serialWorker.finished.connect(
                    loop.quit
                )                                            # connect the loop to finish signal
                loop.exec()                                  # wait until worker is finished
            else:
                self.logger.log(
                    logging.ERROR,
                    "[{}]: serialUI not initialized.".format(
                        int(QThread.currentThreadId())
                    ),
                )
        else:
            self.logger.log(
                logging.ERROR,
                "[{}]: serialWorker not initialized.".format(
                    int(QThread.currentThreadId())
                ),
            )

        event.accept()  # accept the close event to proceed closing the application

    def on_resetStatusBar(self):
        now = datetime.now()
        formatted_date_time = now.strftime("%Y-%m-%d %H:%M")
        self.ui.statusbar.showMessage("Serial User Interface. " + formatted_date_time)

    def show_about_dialog(self):
        # Information to be displayed
        info_text = "Serial Terminal & Plotter\nVersion: 1.0\nAuthor: Urs Utzinger\n2022,2023,2024"
        QMessageBox.about(self, "About Program", info_text) # Create and display the MessageBox
        self.show()

    def show_help_dialog(self):
        # Load Markdown content from readme file
        with open("README.md", "r") as file:
            markdown_content = file.read()
        html_content = markdown(markdown_content)

        html_with_style = f"""
        <style>
            body {{ font-size: 16px; }}
            h1 {{ font-size: 24px; }}
            h2 {{ font-size: 20px; }}
            h3 {{ font-size: 18px; font-style: italic; }}
            p  {{ font-size: 16px; }}
            li {{ font-size: 16px; }}
        </style>
        {html_content}
        """
        
        # Create a QDialog to display the readme content
        dialog = QDialog(self)
        dialog.setWindowTitle("Help")
        layout = QVBoxLayout(dialog)

        # Create a QTextEdit instance for displaying the HTML content
        text_edit = QTextEdit()
        text_edit.setHtml(html_with_style)
        text_edit.setReadOnly(True)  # Make the text edit read-only
        layout.addWidget(text_edit)

        dialog_width = 1024  # Example width
        dialog_height = 800  # Example height
        dialog.resize(dialog_width, dialog_height)

        # Show the dialog
        dialog.exec()


#############################################################################################################################################
# Main 
#############################################################################################################################################

if __name__ == "__main__":

    # set logging level
    # CRITICAL  50
    # ERROR     40
    # WARNING   30
    # INFO      20
    # DEBUG     10
    # NOTSET     0

    logging.basicConfig(level=logging.INFO)

    root_logger = logging.getLogger("SerialUI")
    current_level = root_logger.getEffectiveLevel()

    app = QtWidgets.QApplication(sys.argv)

    win = mainWindow(logger=root_logger)
    screen = app.primaryScreen()
    scalingX = screen.logicalDotsPerInchX() / 96.0
    scalingY = screen.logicalDotsPerInchY() / 96.0
    win.resize(int(1200 * scalingX), int(665 * scalingY))
    win.show()
    sys.exit(app.exec())
