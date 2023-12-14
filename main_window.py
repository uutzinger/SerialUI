################################################################################################
# Serial Communication GUI
# ========================
# Provides serial interface to send and receive text to/from serial port similar to Arduino IDE.
# Plots of data on up to 4 traces with zoom, save and clear.
# This framework was setup to visualize signals at high data rates.
# Because its implemented in python and QT it can be easily extended to incorporate serial
# message encoding as well as drivers for serial devices. 
# 
# Urs Utzinger, 2022, 2023
# University of Arizona
################################################################################################

# QT imports
from PyQt5 import QtCore, QtWidgets, QtGui, uic
from PyQt5.QtCore import QThread, QTimer
from PyQt5.QtWidgets import QMainWindow, QLineEdit, QSlider, QMessageBox, QDialog, QVBoxLayout, QTextEdit
from PyQt5.QtGui import QIcon

# Markdown for documentation
from markdown import markdown

# System
import logging
import os
from datetime import datetime

# Custom imports
from helpers.Qserial_helper     import QSerial, QSerialUI
from helpers.Qgraph_helper      import QChartUI, MAX_ROWS

# QT
# Deal with high resolution displays
if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)

if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
        
###########################################################################################
# Main Window
###########################################################################################

class mainWindow(QMainWindow):
    """
    Create the main window that stores all of the widgets necessary for the application.
    """
        
    #-------------------------------------------------------------------------------------
    # Initialize
    #-------------------------------------------------------------------------------------

    def __init__(self, parent=None):
        """
        Initialize the components of the main window.
        This will create the connections between slots and signals in both directions.
        
        Serial:
        Create serial worker and move it to separate thread.
        
        """
        super(mainWindow, self).__init__(parent) # parent constructor
        
        self.logger = logging.getLogger("Main___")

        main_dir = os.path.dirname(os.path.abspath(__file__))
        
        #----------------------------------------------------------------------------------------------------------------------
        # User Interface
        #----------------------------------------------------------------------------------------------------------------------
        self.ui = uic.loadUi('assets/mainWindow.ui', self)
        icon_path = os.path.join(main_dir, 'assets', 'serial_48.png')
        window_icon = QIcon(icon_path)
        self.setWindowIcon(QIcon(window_icon))
        self.setWindowTitle("Serial GUI")

        #----------------------------------------------------------------------------------------------------------------------
        # Serial
        #----------------------------------------------------------------------------------------------------------------------
       
        # Serial Thread 
        self.serialThread = QThread()                                                                      # create QThread object
        self.serialThread.start()                                                                          # start thread which will start worker

        # Create serial worker
        self.serialWorker = QSerial()                                                                      # create serial worker object

        # Create user interface hook for serial
        self.serialUI     = QSerialUI(ui=self.ui, worker = self.serialWorker)                              # create serial user interface object

        # Connect worker / thread
        self.serialWorker.finished.connect(                 self.serialThread.quit                       ) # if worker emits finished quite worker thread
        self.serialWorker.finished.connect(                 self.serialWorker.deleteLater                ) # delete worker at some time
        self.serialThread.finished.connect(                 self.serialThread.deleteLater                ) # delete thread at some time

        # Signals from Serial to Serial-UI
        # ---------------------------------
        self.serialWorker.textReceived.connect(             self.serialUI.on_SerialReceivedText         ) # connect text display to serial receiver signal
        self.serialWorker.linesReceived.connect(            self.serialUI.on_SerialReceivedLines         ) # connect text display to serial receiver signal
        self.serialWorker.newPortListReady.connect(         self.serialUI.on_newPortListReady            ) # connect new port list to its ready signal
        self.serialWorker.newBaudListReady.connect(         self.serialUI.on_newBaudListReady            ) # connect new baud list to its ready signal
        self.serialWorker.serialStatusReady.connect(        self.serialUI.on_serialStatusReady           ) # connect display serial status to ready signal
        self.serialWorker.throughputReady.connect(          self.serialUI.on_throughputReceived          ) # connect display throughput status 
        self.serialWorker.serialWorkerStateChanged.connect( self.serialUI.on_serialWorkerStateChanged    ) # mirror serial worker state to serial UI

        # Signals from Serial-UI to Serial
        # ---------------------------------
        self.serialUI.changePortRequest.connect(            self.serialWorker.on_changePortRequest       ) # connect changing port
        self.serialUI.closePortRequest.connect(             self.serialWorker.on_closePortRequest        ) # connect close port
        self.serialUI.changeBaudRequest.connect(            self.serialWorker.on_changeBaudRateRequest   ) # connect changing baudrate
        self.serialUI.changeLineTerminationRequest.connect( self.serialWorker.on_changeLineTerminationRequest) # connect changing baudrate
        self.serialUI.scanPortsRequest.connect(             self.serialWorker.on_scanPortsRequest        ) # connect request to scan ports
        self.serialUI.scanBaudRatesRequest.connect(         self.serialWorker.on_scanBaudRatesRequest    ) # connect request to scan baudrates
        self.serialUI.setupReceiverRequest.connect(         self.serialWorker.on_setupReceiverRequest    ) # connect start receiver
        self.serialUI.startReceiverRequest.connect(         self.serialWorker.on_startReceiverRequest    ) # connect start receiver
        self.serialUI.stopReceiverRequest.connect(          self.serialWorker.on_stopReceiverRequest     ) # connect start receiver
        self.serialUI.sendTextRequest.connect(              self.serialWorker.on_sendTextRequest         ) # connect sending text
        self.serialUI.sendLineRequest.connect(              self.serialWorker.on_sendLineRequest         ) # connect sending text
        self.serialUI.sendLinesRequest.connect(             self.serialWorker.on_sendLinesRequest        ) # connect sending lines of text
        self.serialUI.serialStatusRequest.connect(          self.serialWorker.on_serialStatusRequest     ) # connect request for serial status
        self.serialUI.finishWorkerRequest.connect(          self.serialWorker.on_stopWorkerRequest       ) # connect finish request
        self.serialUI.startThroughputRequest.connect(       self.serialWorker.on_startThroughputRequest  ) # start throughput
        self.serialUI.stopThroughputRequest.connect(        self.serialWorker.on_stopThroughputRequest   ) # stop throughput
        self.serialUI.serialSendFileRequest.connect(        self.serialWorker.on_sendFileRequest         ) # send file to serial port

        # Prepare the Serial Worker and User Interface
        # --------------------------------------------
        self.serialWorker.moveToThread(                     self.serialThread                             ) # move worker to thread
        self.serialUI.scanPortsRequest.emit()                                                               # request to scan for serial ports
        self.serialUI.setupReceiverRequest.emit()                                                           # establishes QTimer in the QThread above
        # do not initialize baudrate, serial port or line termination, user will need to select at startup

        # Signals from User Interface to Serial-UI
        # ----------------------------------------
        # User selected port or baud 
        self.ui.comboBoxDropDown_SerialPorts.currentIndexChanged.connect(
                                                            self.serialUI.on_comboBoxDropDown_SerialPorts )
        self.ui.comboBoxDropDown_BaudRates.currentIndexChanged.connect(
                                                            self.serialUI.on_comboBoxDropDown_BaudRates   )
        # User changed line termination
        self.ui.comboBoxDropDown_LineTermination.currentIndexChanged.connect( 
                                                            self.serialUI.on_comboBoxDropDown_LineTermination )
        # User clicked scan ports, start send, clear or save
        self.ui.pushButton_SerialScan.clicked.connect(      self.serialUI.on_pushButton_SerialScan        ) # Scan for ports
        self.ui.pushButton_SerialStartStop.clicked.connect( self.serialUI.on_pushButton_SerialStartStop   ) # Start/Stop serial receive
        self.ui.pushButton_SerialSend.clicked.connect(      self.serialUI.on_serialSendFile               ) # Send text from a file to serial port
        self.ui.lineEdit_SerialText.returnPressed.connect(  self.serialUI.on_serialMonitorSend            ) # Send text as soon as enter key is pressed
        self.ui.pushButton_SerialClearOutput.clicked.connect(
                                                            self.serialUI.on_pushButton_SerialClearOutput ) # Clear serial receive window
        self.ui.pushButton_SerialSave.clicked.connect(      self.serialUI.on_pushButton_SerialSave        ) # Save text from serial receive window
        self.ui.pushButton_SerialOpenClose.clicked.connect( self.serialUI.on_pushButton_SerialOpenClose   ) # Open/Close serial port
        # User hit up/down arrow in serial lineEdit
        self.shortcutUpArrow   = QtWidgets.QShortcut(QtGui.QKeySequence.MoveToPreviousLine, self.ui.lineEdit_SerialText, self.serialUI.on_serialMonitorSendUpArrowPressed)
        self.shortcutDownArrow = QtWidgets.QShortcut(QtGui.QKeySequence.MoveToNextLine,     self.ui.lineEdit_SerialText, self.serialUI.on_serialMonitorSendDownArrowPressed)

        # Done with Serial
        self.logger.log(logging.INFO, "[{}]: serial initialized.".format(int(QThread.currentThreadId())))

        #----------------------------------------------------------------------------------------------------------------------
        # Serial Plotter
        #----------------------------------------------------------------------------------------------------------------------
        # Create user interface hook for chart plotting
        self.chartUI  = QChartUI(ui=self.ui, serialUI=self.serialUI, serialWorker = self.serialWorker) # create chart user interface object

        self.ui.pushButton_ChartStartStop.clicked.connect(  self.chartUI.on_pushButton_StartStop         )
        self.ui.pushButton_ChartClear.clicked.connect(      self.chartUI.on_pushButton_Clear             )
        self.ui.pushButton_ChartSave.clicked.connect(       self.chartUI.on_pushButton_Save              )

        self.ui.comboBoxDropDown_DataSeparator.currentIndexChanged.connect(
                                                            self.chartUI.on_changeDataSeparator          )        

        # Horizontal Zoom
        self.horizontalSlider_Zoom = self.ui.findChild(QSlider, "horizontalSlider_Zoom")
        self.horizontalSlider_Zoom.setMinimum(0)  
        self.horizontalSlider_Zoom.setMaximum(MAX_ROWS)
        self.horizontalSlider_Zoom.valueChanged.connect(    self.chartUI.on_HorizontalSliderChanged     )

        self.lineEdit_Zoom = self.ui.findChild(QLineEdit, "lineEdit_Horizontal")
        self.lineEdit_Zoom.returnPressed.connect( self.chartUI.on_HorizontalLineEditChanged )

        # Done with Plotter
        self.logger.log(logging.INFO, "[{}]: plotter initialized.".format(int(QThread.currentThreadId())))
        
        #----------------------------------------------------------------------------------------------------------------------
        # Menu Bar
        #----------------------------------------------------------------------------------------------------------------------
        # Connect the action_about action to the show_about_dialog slot
        self.ui.action_About.triggered.connect(self.show_about_dialog)
        self.ui.action_Help.triggered.connect(self.show_help_dialog)
        
        #----------------------------------------------------------------------------------------------------------------------
        # Status Bar
        #----------------------------------------------------------------------------------------------------------------------
        self.statusTimer = QTimer(self)
        self.statusTimer.timeout.connect(self.on_resetStatusBar)
        self.statusTimer.start(10000)  # Trigger every 10 seconds

        #----------------------------------------------------------------------------------------------------------------------
        # Finish up
        #----------------------------------------------------------------------------------------------------------------------
        self.show() 

    def on_resetStatusBar(self):
        now = datetime.now()
        formatted_date_time = now.strftime("%Y-%m-%d %H:%M")
        self.ui.statusbar.showMessage("University of Arizona. " + formatted_date_time)

    def show_about_dialog(self):
        # Information to be displayed
        info_text = "Serial Terminal & Plotter\nVersion: 1.0\nAuthor: Urs Utzinger\n2022,2023"
        # Create and display the MessageBox
        QMessageBox.about(self, "About Program", info_text)       
        self.show()
 
    def show_help_dialog(self):
        # Load Markdown content from readme file
        with open("Readme.md", "r") as file:
            markdown_content = file.read()
        html_content = markdown(markdown_content)

        # somehow h3 font size is not applied, not sure how to fix
        html_with_style = f"""
        <style>
            body {{ font-size: 16px; }}
            h1 {{ font-size: 24px; }}
            h2 {{ font-size: 20px; }}
            h3 {{ font-size: 18px; font-style: italic; }}
            p {{ font-size: 16px; }}
            li {{ font-size: 16px; }}
        </style>
        {html_content}
        """

        # Create a QDialog to display the content
        dialog = QDialog(self)
        dialog.setWindowTitle("Help")
        layout = QVBoxLayout(dialog)

        # Create a QTextEdit instance for displaying the HTML content
        text_edit = QTextEdit()
        text_edit.setHtml(html_with_style)
        text_edit.setReadOnly(True)  # Make the text edit read-only
        layout.addWidget(text_edit)

        dialog_width  = 1024  # Example width
        dialog_height = 800   # Example height
        dialog.resize(dialog_width, dialog_height)

        # Show the dialog
        dialog.exec_()
        
###########################################################################################
# Testing Main Window
###########################################################################################

if __name__ == "__main__":
    import sys
    from PyQt5 import QtWidgets
    import logging
    
    # set logging level
    # CRITICAL  50
    # ERROR     40
    # WARNING   30
    # INFO      20
    # DEBUG     10
    # NOTSET     0
    logging.basicConfig(level=logging.INFO)
    
    app = QtWidgets.QApplication(sys.argv)
    
    win = mainWindow()
    d = app.desktop()
    scalingX = d.logicalDpiX()/96.0
    scalingY = d.logicalDpiY()/96.0
    win.resize(int(1200*scalingX), int(665*scalingY))
    # 1200 and 670 are the dimension of the UI in QT Designer
    # You will need to adjust these numbers if you change the UI
    win.show()
    sys.exit(app.exec_())
    
