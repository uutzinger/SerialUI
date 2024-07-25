"""
IMURec.py - Recorder GUI for IMU devices

This program was based on the FreeIMU Calibration GUI by Fabio Varesano,
but it was rewritten to run Python 3.x and PyQt5. 

Its purpose is to record data from IMU via ZMQ or serial link.

Once data is recorded, calibration can be accomplished with separate scripts (provided).

Copyright (C) 2023 Urs Utzinger
"""

from PyQt5 import uic
from PyQt5.QtCore import QThread, QSettings, QObject, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QLineEdit
from PyQt5.QtGui import QIcon, QVector3D
import pyqtgraph as pg
import pyqtgraph.opengl as gl

import sys
import numpy as np
import serial, time
import struct
import logging
import pathlib
import zmq
import msgpack

######################################################################
# User Settings
######################################################################
# because on raspian: pyqtgraph.opengl: Requires >= OpenGL 2.0 (not ES); Found b'OpenGL ES 3.1 Mesa 20.3.5'
USE3DPLOT = True
# We dont want to plot every data point
DATADISPLAYINTERVAL = 25 # number of readings to receive before displaying one data point
# SERIAL
BAUDRATE = 115200
# ZMQ
ZMQTIMEOUT = 1000 # in milliseconds

acc_range = 15   # Initial Display Range is around 1.5g
mag_range = 100  # Initial Display Range is around 100uT
gyr_range = 10   # Initial Display Range is around 100rpm

######################################################################
# Support Function
######################################################################

class dict2obj:
    '''
    Decoding nested dictionary to object
      ZMQ can transmit native data types. 
      Variables in classes need to be converted to dictionaries.
      This function converts dictionaries back to objects:
        dict['x'] becomes object.x
    '''
    def __init__(self, data):
        for key, value in data.items():
            if isinstance(value, dict): setattr(self, key, dict2obj(value))
            else:                       setattr(self, key, value)

######################################################################
# ZMQ Worker
######################################################################

class zmqWorker(QObject):

    dataReady = pyqtSignal(list)
    finished  = pyqtSignal()

    def __init__(self, parent=None):
        super(zmqWorker, self).__init__(parent)
        self.running = False
        self.paused  = False
        self.zmqPort = 'tcp:\\localhost:5556'
                
        self.acc_file_name = 'acc_data.txt'
        self.gyr_file_name = 'gyr_data.txt'
        self.mag_file_name = 'mag_data.txt'
        
        self.acc_record = False
        self.acc_append = False
        self.gyr_record = False
        self.gyr_append = False
        self.mag_record = False
        self.mag_append = False
                
        self.timeout_counter = 0
    
    def start(self):
        self.running = True
        self.paused  = False

        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        socket.setsockopt(zmq.SUBSCRIBE, b"imu") # subscribe to "imu" topic
        socket.connect(self.zmqPort)
        
        poller = zmq.Poller()
        poller.register(socket, zmq.POLLIN)
        
        if self.acc_record:
            if self.acc_append: self.acc_file = open(self.acc_file_name, 'a')
            else:               self.acc_file = open(self.acc_file_name, 'w')
        else:                   self.acc_file = None
        
        if self.gyr_record: 
            if self.gyr_append: self.gyr_file = open(self.gyr_file_name, 'a')
            else:               self.gyr_file = open(self.gyr_file_name, 'w')
        else:                   self.gyr_file = None
        
        if self.mag_record:
            if self.mag_append: self.mag_file = open(self.mag_file_name, 'a')
            else:               self.mag_file = open(self.mag_file_name, 'w')
        else:                   self.mag_file = None
        
        counter = 0              # for transferring data to GUI for plotting after DATADISPLAYINTERVAL readings
        self.timeout_counter = 0 # for detecting if ZMQ has connection to server
        
        while self.running:
            
            events = dict(poller.poll(timeout = ZMQTIMEOUT))
            if socket in events and events[socket] == zmq.POLLIN:
                self.timeout_counter = 0
                response = socket.recv_multipart()
                if len(response) == 2:
                    [topic, msg_packed] = response
                    if topic == b"imu":
                        if not self.paused: 
                            msg_dict = msgpack.unpackb(msg_packed)
                            data_imu = dict2obj(msg_dict)
                            if hasattr(data_imu, 'acc') and hasattr(data_imu, 'gyr') and hasattr(data_imu, 'mag'): 
                                # the recorded file appears to have NULL characters in it, hope this helps
                                # if (type(data_imu.acc.x) == float and type(data_imu.acc.y) == float and type(data_imu.acc.z) == float) and \
                                #    (type(data_imu.gyr.x) == float and type(data_imu.gyr.y) == float and type(data_imu.gyr.z) == float) and \
                                #    (type(data_imu.mag.x) == float and type(data_imu.mag.y) == float and type(data_imu.mag.z) == float):
                                    if self.acc_record:
                                        acc_readings_line = '{:f} {:f} {:f}\n'.format(data_imu.acc.x, data_imu.acc.y, data_imu.acc.z)
                                        self.acc_file.write(acc_readings_line)
                                    if self.gyr_record: 
                                        gyr_readings_line = '{:f} {:f} {:f}\n'.format(data_imu.gyr.x, data_imu.gyr.y, data_imu.gyr.z)
                                        self.gyr_file.write(gyr_readings_line)
                                    if self.mag_record:
                                        mag_readings_line = '{:f} {:f} {:f}\n'.format(data_imu.mag.x, data_imu.mag.y, data_imu.mag.z)
                                        self.mag_file.write(mag_readings_line)
                                    if counter % DATADISPLAYINTERVAL == 0:
                                        self.dataReady.emit([data_imu.acc.x, data_imu.acc.y, data_imu.acc.z, 
                                                            data_imu.gyr.x, data_imu.gyr.y, data_imu.gyr.z, 
                                                            data_imu.mag.x, data_imu.mag.y, data_imu.mag.z])
                                        # flush files every once in a while
                                        if self.acc_record: self.acc_file.flush()
                                        if self.gyr_record: self.gyr_file.flush()
                                        if self.mag_record: self.mag_file.flush()  
                                    counter += 1
            else: # ZMQ TIMEOUT
                self.timeout_counter += 1
                if self.timeout_counter > 10:
                    socket.close()
                    socket = context.socket(zmq.SUB)
                    socket.connect(self.zmqPort)
                    socket.setsockopt(zmq.SUBSCRIBE, b"imu") # subscribe to "imu" topic
                                    
        # closing acc,gyr and mag files
        if self.acc_record: 
            self.acc_file.flush()
            self.acc_file.close()
        if self.gyr_record: 
            self.gyr_file.flush()
            self.gyr_file.close()
        if self.mag_record: 
            self.mag_file.flush()
            self.mag_file.close() 
            
        socket.close()
        context.term()
        self.finished.emit()
        
    def stop(self):
        self.running         = False
        self.paused          = False
        self.acc_file_name   = None
        self.gyr_file_name   = None
        self.mag_file_name   = None
        self.timeout_counter = 0
        
    def set_save_file(self, acc_file_name, gyr_file_name, mag_file_name):
        self.acc_file_name = acc_file_name
        self.gyr_file_name = gyr_file_name
        self.mag_file_name = mag_file_name

    def set_save_options(self, acc_record, acc_append, gyr_record, gyr_append, mag_record, mag_append):        
        self.acc_append = acc_append
        self.gyr_append = gyr_append
        self.mag_append = mag_append
        self.acc_record = acc_record
        self.gyr_record = gyr_record  
        self.mag_record = mag_record
        
    def set_zmqPort(self, port):
        self.zmqPort = port

    def pause(self):
        self.paused = not self.paused

###################################################################
# Main Window
###################################################################
   
class MainWindow(QMainWindow):

    ###################################################################
    # Init
    ###################################################################
    
    def __init__(self):
        super(MainWindow, self).__init__()

        self.logger = logging.getLogger('IMURecorder')

        self.zmqWorker       = None
        self.zmqWorkerThread = None

        # Load UI and setup widgets -------------------------
        
        self.ui = uic.loadUi('imu_recorder.ui', self)
        if USE3DPLOT ==  True:
            self.ui.acc3D.setEnabled(True)
            self.ui.gyr3D.setEnabled(True)
            self.ui.mag3D.setEnabled(True)
        else:
            self.ui.acc3D.setEnabled(False)
            self.ui.gyr3D.setEnabled(False)
            self.ui.mag3D.setEnabled(False)
      
        self.setWindowTitle('IMU Recorder')
        
        current_directory = str(pathlib.Path(__file__).parent.absolute())
        path = current_directory + '/IMURec.png'
        self.setWindowIcon(QIcon(path))
        
        # Load user settings --------------------------------
        self.settings = QSettings('IMU Recorder Application', 'Urs Utzinger')

        # Port: restore previous port used ------------------
        self.ui.PortEdit.setText(self.settings.value('recgui/PortEdit', 'tcp://localhost:5556'))
        # when user hits enter, we generate the clicked signal to the button so that connection starts
        self.ui.PortEdit.returnPressed.connect(lambda: setattr(self, 'port', str(self.ui.PortEdit.text())))

        # Restore Acc,Gyr,Mag File Names --------------------
        self.ui.accFile.setText(self.settings.value('recgui/acc_file_name', 'acc_data.txt'))
        self.ui.gyrFile.setText(self.settings.value('recgui/gyr_file_name', 'gyr_data.txt'))
        self.ui.magFile.setText(self.settings.value('recgui/mag_file_name', 'mag_data.txt'))

        self.ui.accFile.setEnabled(True)
        self.ui.gyrFile.setEnabled(True)
        self.ui.magFile.setEnabled(True)

        self.ui.accFile.returnPressed.connect(lambda: setattr(self, 'acc_file_name', self.ui.accFile.text()))
        self.ui.gyrFile.returnPressed.connect(lambda: setattr(self, 'gyr_file_name', self.ui.gyrFile.text()))
        self.ui.magFile.returnPressed.connect(lambda: setattr(self, 'mag_file_name', self.ui.magFile.text()))
        
        # Buttons -------------------------------------------
        
        self.ui.samplingToggleButton.clicked.connect(self.start_worker)
        self.ui.samplingToggleButton.setEnabled(True)

        self.ui.clearButton.clicked.connect(self.clear_data)
        self.ui.clearButton.setEnabled(False)

        self.ui.samplingStopButton.clicked.connect(self.stop_worker)
        self.ui.samplingStopButton.setEnabled(False)

        self.set_status('Disconnected')

        # Check Marks --------------------------------------
        
        self.ui.accDisplay.setChecked(True)
        self.ui.gyrDisplay.setChecked(True)
        self.ui.magDisplay.setChecked(True)

        self.ui.accAppend.setChecked(False)
        self.ui.gyrAppend.setChecked(False)
        self.ui.magAppend.setChecked(False)

        self.ui.accRecord.setChecked(False)
        self.ui.gyrRecord.setChecked(False)
        self.ui.magRecord.setChecked(False)

        # Data Stores --------------------------------------
        
        self.acc_data = np.zeros([1,3])
        self.mag_data = np.zeros([1,3])
        self.gyr_data = np.zeros([1,3])

        # Graphs for Accelerometer --------------------------
        
        self.ui.accXY.setXRange(-acc_range, acc_range)
        self.ui.accYZ.setXRange(-acc_range, acc_range)
        self.ui.accZX.setXRange(-acc_range, acc_range)
        
        self.ui.accXY.setAspectLocked()
        self.ui.accYZ.setAspectLocked()
        self.ui.accZX.setAspectLocked()

        self.ui.accXY.setBackground('w')
        self.ui.accYZ.setBackground('w')
        self.ui.accZX.setBackground('w')

        self.accXY_sp = pg.ScatterPlotItem([],[], symbol='o', symbolSize=8, pen=pg.mkPen(None), symbolBrush='r')
        self.ui.accXY.addItem(self.accXY_sp)
        self.accYZ_sp = pg.ScatterPlotItem([],[], symbol='o', symbolSize=8, pen=pg.mkPen(None), symbolBrush='g')
        self.ui.accYZ.addItem(self.accYZ_sp)
        self.accZX_sp = pg.ScatterPlotItem([],[], symbol='o', symbolSize=8, pen=pg.mkPen(None), symbolBrush='b')
        self.ui.accZX.addItem(self.accZX_sp)
        
        if USE3DPLOT is True:

            ag = gl.GLGridItem(antialias=True, glOptions='opaque')
            ag.setSize(x=acc_range*2, y=acc_range*2)  # Set the grid size (xSpacing, ySpacing)
            ag.setSpacing(x=acc_range/10, y=acc_range/10)  # Set the grid size (xSpacing, ySpacing)
            ag.setColor((0, 0, 0, 255)) 
            self.ui.acc3D.addItem(ag)

            self.acc3D_sp = gl.GLScatterPlotItem()
            self.acc3D_sp.setGLOptions('translucent')
            self.ui.acc3D.addItem(self.acc3D_sp)

            self.acc3Dline_sp = gl.GLLinePlotItem()
            self.acc3Dline_sp.setGLOptions('translucent')
            self.ui.acc3D.addItem(self.acc3Dline_sp)

            self.ui.acc3D.opts['center'] = QVector3D(0, 0, 0) 
            self.ui.acc3D.opts['bgcolor'] = (255, 255, 255, 255)  # Set background color to white
            self.ui.acc3D.opts['distance'] = 1.*acc_range
            self.ui.acc3D.opts['translucent'] = True
            self.ui.acc3D.show()
            self.ui.acc3D.update()
        
        # Graphs for Gyroscope --------------------------
        
        self.ui.gyrXY.setXRange(-gyr_range, gyr_range)
        self.ui.gyrYZ.setXRange(-gyr_range, gyr_range)
        self.ui.gyrZX.setXRange(-gyr_range, gyr_range)
        
        self.ui.gyrXY.setAspectLocked()
        self.ui.gyrYZ.setAspectLocked()
        self.ui.gyrZX.setAspectLocked()

        self.ui.gyrXY.setBackground('w')
        self.ui.gyrYZ.setBackground('w')
        self.ui.gyrZX.setBackground('w')

        self.gyrXY_sp = pg.ScatterPlotItem([],[], symbol='o', symbolSize=8, pen=pg.mkPen(None), symbolBrush='r')
        self.ui.gyrXY.addItem(self.gyrXY_sp)
        self.gyrYZ_sp = pg.ScatterPlotItem([],[], symbol='o', symbolSize=8, pen=pg.mkPen(None), symbolBrush='g')
        self.ui.gyrYZ.addItem(self.gyrYZ_sp)
        self.gyrZX_sp = pg.ScatterPlotItem([],[], symbol='o', symbolSize=8, pen=pg.mkPen(None), symbolBrush='b')
        self.ui.gyrZX.addItem(self.gyrZX_sp)
        
        if USE3DPLOT is True:
            gg = gl.GLGridItem(antialias=True, glOptions='opaque')
            gg.setSize(x=gyr_range*2, y=gyr_range*2)  # Set the grid size (xSpacing, ySpacing)
            gg.setSpacing(x=gyr_range/10, y=gyr_range/10)  # Set the grid size (xSpacing, ySpacing)
            gg.setColor((0, 0, 0, 255)) 
            self.ui.gyr3D.addItem(gg)

            self.gyr3D_sp = gl.GLScatterPlotItem()
            self.gyr3D_sp.setGLOptions('translucent')
            self.ui.gyr3D.addItem(self.gyr3D_sp)

            self.gyr3Dline_sp = gl.GLLinePlotItem()
            self.gyr3Dline_sp.setGLOptions('translucent')
            self.ui.gyr3D.addItem(self.gyr3Dline_sp)

            self.ui.gyr3D.opts['center'] = QVector3D(0, 0, 0) 
            self.ui.gyr3D.opts['distance'] = 1.2*gyr_range
            self.ui.gyr3D.opts['bgcolor'] = (255, 255, 255, 255)  # Set background color to white
            self.ui.gyr3D.opts['translucent'] = True
            self.ui.gyr3D.show()
            self.ui.gyr3D.update()
            
        # Magnetometer ----------------------------------

        self.ui.magXY.setXRange(-mag_range, mag_range)
        self.ui.magYZ.setXRange(-mag_range, mag_range)
        self.ui.magZX.setXRange(-mag_range, mag_range)
        
        self.ui.magXY.setAspectLocked()
        self.ui.magYZ.setAspectLocked()
        self.ui.magZX.setAspectLocked()

        self.ui.magXY.setBackground('w')
        self.ui.magYZ.setBackground('w')
        self.ui.magZX.setBackground('w')

        self.magXY_sp = pg.ScatterPlotItem([],[], symbol='o', symbolSize=8, pen=pg.mkPen(None), symbolBrush='r')
        self.ui.magXY.addItem(self.magXY_sp)
        self.magYZ_sp = pg.ScatterPlotItem([],[], symbol='o', symbolSize=8, pen=pg.mkPen(None), symbolBrush='g')
        self.ui.magYZ.addItem(self.magYZ_sp)
        self.magZX_sp = pg.ScatterPlotItem([],[], symbol='o', symbolSize=8, pen=pg.mkPen(None), symbolBrush='b')
        self.ui.magZX.addItem(self.magZX_sp)
    
        if USE3DPLOT is True:

            mg = gl.GLGridItem(antialias=True, glOptions='opaque')
            mg.setSize(x=mag_range/10, y=mag_range/10)  # Set the grid size (xSpacing, ySpacing)
            mg.setSize(x=mag_range*2, y=mag_range*2)  # Set the grid size (xSpacing, ySpacing)
            mg.setSpacing(x=mag_range/10, y=mag_range/10)  # Set the grid size (xSpacing, ySpacing)
            mg.setColor((0, 0, 0, 255)) 
            self.ui.mag3D.addItem(mg)

            self.mag3D_sp = gl.GLScatterPlotItem()
            self.mag3D_sp.setGLOptions('translucent')
            self.ui.mag3D.addItem(self.mag3D_sp)

            self.mag3Dline_sp = gl.GLLinePlotItem()
            self.mag3Dline_sp.setGLOptions('translucent')
            self.ui.mag3D.addItem(self.mag3Dline_sp)
    
            self.ui.mag3D.opts['center'] = QVector3D(0, 0, 0) 
            self.ui.mag3D.opts['distance'] = 1.5*mag_range
            self.ui.mag3D.opts['bgcolor'] = (255, 255, 255, 255)  # Set background color to white
            self.ui.mag3D.opts['translucent'] = True
            self.ui.mag3D.show()
            self.ui.mag3D.update()

    ###################################################################
    # Status
    ###################################################################
        
    def set_status(self, status):
        self.ui.statusbar.showMessage(self.tr(status))            
        
    ###################################################################
    # Start, Pause, Continue, Stop
    ###################################################################
  
    def start_worker(self):
        if not self.zmqWorker or not self.zmqWorker.running:

            port = self.PortEdit.text()
            self.settings.setValue('recgui/PortEdit', port)
            if not port:
                return
            
            # Make sure we did not forget to switch to correct protocol
            if 'tcp' in port:
                if self.ui.Protocol.currentText() != 'IMU_ZMQ':
                    self.ui.Protocol.setCurrentText('IMU_ZMQ')
                
            self.set_status('Starting on ' + port)
    
            self.ui.PortEdit.setEnabled(False)
            self.ui.Protocol.setEnabled(False)
            
            self.settings.setValue('recgui/acc_file_name', self.ui.accFile.text())
            self.settings.setValue('recgui/gyr_file_name', self.ui.gyrFile.text())
            self.settings.setValue('recgui/mag_file_name', self.ui.magFile.text())

            self.ui.accFile.setEnabled(False)
            self.ui.gyrFile.setEnabled(False)
            self.ui.magFile.setEnabled(False)
            
            acc_file_name = self.ui.accFile.text()
            gyr_file_name = self.ui.gyrFile.text()
            mag_file_name = self.ui.magFile.text()

            self.ui.accRecord.setEnabled(False)
            self.ui.gyrRecord.setEnabled(False)
            self.ui.magRecord.setEnabled(False)

            acc_record = self.ui.accRecord.isChecked()
            gyr_record = self.ui.gyrRecord.isChecked()
            mag_record = self.ui.magRecord.isChecked()

            self.ui.accAppend.setEnabled(False)
            self.ui.gyrAppend.setEnabled(False)
            self.ui.magAppend.setEnabled(False)

            acc_append = self.ui.accAppend.isChecked()
            gyr_append = self.ui.gyrAppend.isChecked()
            mag_append = self.ui.magAppend.isChecked()

            self.set_status('Starting Sampling Worker')
    
            self.zmqWorker = zmqWorker()
            self.zmqWorkerThread = QThread()
            self.zmqWorker.moveToThread(self.zmqWorkerThread)
            self.zmqWorker.dataReady.connect(self.handle_new_data)
            self.zmqWorker.finished.connect(self.worker_finished)
            self.zmqWorkerThread.started.connect(self.zmqWorker.start)
            self.zmqWorkerThread.finished.connect(self.worker_thread_finished)
            
            self.zmqWorker.set_save_file(acc_file_name, gyr_file_name, mag_file_name)
            self.zmqWorker.set_save_options(acc_record, acc_append, gyr_record, gyr_append, mag_record, mag_append)
            self.zmqWorker.set_zmqPort(port)
            
            self.zmqWorkerThread.start()
            
            self.ui.samplingToggleButton.setText('Pause')
            self.ui.samplingToggleButton.setEnabled(True)
            
            self.ui.samplingStopButton.setEnabled(True)
            self.ui.clearButton.setEnabled(True)
            
        else:
            self.zmqWorker.pause()
            if self.zmqWorker.paused:
                self.ui.samplingToggleButton.setText('Continue')
            else:
                self.ui.samplingToggleButton.setText('Pause')            
            
    def stop_worker(self):
        self.zmqWorker.stop()
        self.zmqWorkerThread.quit()
        # self.zmqWorkerThread.wait()
        self.worker_finished()
        
    def worker_finished(self):
        self.ui.samplingToggleButton.setText('Start')
        self.ui.samplingToggleButton.setEnabled(True)
        self.ui.samplingStopButton.setEnabled(False)
        self.ui.PortEdit.setEnabled(True)
        self.ui.Protocol.setEnabled(True)
        self.ui.accFile.setEnabled(True)
        self.ui.gyrFile.setEnabled(True)
        self.ui.magFile.setEnabled(True)
        self.ui.accRecord.setEnabled(True)
        self.ui.gyrRecord.setEnabled(True)
        self.ui.magRecord.setEnabled(True)
        self.ui.accAppend.setEnabled(True)
        self.ui.gyrAppend.setEnabled(True)
        self.ui.magAppend.setEnabled(True)
        self.ui.clearButton.setEnabled(True)
        
    def worker_thread_finished(self):
        self.zmqWorkerThread.quit()
        self.zmqWorkerThread.wait()
        self.zmqWorkerThread.deleteLater()
        self.zmqWorker.deleteLater()
        self.zmqWorker = None

    ###################################################################
    # Plot New Data, Clear Plot
    ###################################################################

    def handle_new_data(self, readings: list):

        if self.ui.accDisplay.isChecked():
            self.acc_data = np.concatenate((self.acc_data, np.array([[readings[0],readings[1],readings[2]]])), axis=0)
            self.accXY_sp.setData(x=self.acc_data[1:-1,0], y=self.acc_data[1:-1,1])
            self.accYZ_sp.setData(x=self.acc_data[1:-1,1], y=self.acc_data[1:-1,2])
            self.accZX_sp.setData(x=self.acc_data[1:-1,2], y=self.acc_data[1:-1,0])
            if len(self.acc_data) > 2:
                acc_data_min = np.min(self.acc_data[1:-1,:], axis=0)
                acc_data_max = np.max(self.acc_data[1:-1,:], axis=0)
                self.ui.accXY.setXRange(acc_data_min[0], acc_data_max[0])
                self.ui.accXY.setYRange(acc_data_min[1], acc_data_max[1])
                self.ui.accYZ.setXRange(acc_data_min[1], acc_data_max[1])
                self.ui.accYZ.setYRange(acc_data_min[2], acc_data_max[2])
                self.ui.accZX.setXRange(acc_data_min[2], acc_data_max[2])
                self.ui.accZX.setYRange(acc_data_min[0], acc_data_max[0])

        if self.ui.gyrDisplay.isChecked():
            self.gyr_data = np.concatenate((self.gyr_data, np.array([[readings[3],readings[4],readings[5]]])), axis=0)
            self.gyrXY_sp.setData(x=self.gyr_data[1:-1,0], y=self.gyr_data[1:-1,1])
            self.gyrYZ_sp.setData(x=self.gyr_data[1:-1,1], y=self.gyr_data[1:-1,2])
            self.gyrZX_sp.setData(x=self.gyr_data[1:-1,2], y=self.gyr_data[1:-1,0])    
            if len(self.gyr_data) > 2:
                gyr_data_min = np.min(self.gyr_data[1:-1,:], axis=0)
                gyr_data_max = np.max(self.gyr_data[1:-1,:], axis=0)
                self.ui.gyrXY.setXRange(gyr_data_min[0], gyr_data_max[0])
                self.ui.gyrXY.setYRange(gyr_data_min[1], gyr_data_max[1])
                self.ui.gyrYZ.setXRange(gyr_data_min[1], gyr_data_max[1])
                self.ui.gyrYZ.setYRange(gyr_data_min[2], gyr_data_max[2])
                self.ui.gyrZX.setXRange(gyr_data_min[2], gyr_data_max[2])
                self.ui.gyrZX.setYRange(gyr_data_min[0], gyr_data_max[0])
                
        if self.ui.magDisplay.isChecked():
            self.mag_data = np.concatenate((self.mag_data, np.array([[readings[6],readings[7],readings[8]]])), axis=0)
            self.magXY_sp.setData(x=self.mag_data[1:-1,0], y=self.mag_data[1:-1,1])
            self.magYZ_sp.setData(x=self.mag_data[1:-1,1], y=self.mag_data[1:-1,2])
            self.magZX_sp.setData(x=self.mag_data[1:-1,2], y=self.mag_data[1:-1,0])
            if len(self.mag_data) > 2:
                mag_data_min = np.min(self.mag_data[1:-1,:], axis=0)
                mag_data_max = np.max(self.mag_data[1:-1,:], axis=0)
                self.ui.magXY.setXRange(mag_data_min[0], mag_data_max[0])
                self.ui.magXY.setYRange(mag_data_min[1], mag_data_max[1])
                self.ui.magYZ.setXRange(mag_data_min[1], mag_data_max[1])
                self.ui.magYZ.setYRange(mag_data_min[2], mag_data_max[2])
                self.ui.magZX.setXRange(mag_data_min[2], mag_data_max[2])
                self.ui.magZX.setYRange(mag_data_min[0], mag_data_max[0])

        if USE3DPLOT == True:
            color = (1., 0., 0., 0.5)
            size = 10.
            
            if self.ui.accDisplay.isChecked():
                n = self.acc_data.shape[0]
                self.acc3D_sp.setData(pos=self.acc_data[1:n,:], color = color, size=size)
                self.acc3Dline_sp.setData(pos=self.acc_data[1:n,:], width=3.0, color=(0.5, 0.5, 0.5, 0.5))
                # Calculate the data range
                if len(self.acc_data) > 2:
                    acc_data_range = np.linalg.norm(acc_data_max - acc_data_min)
                    acc_camera_distance = acc_data_range
                    self.ui.acc3D.opts['distance'] = acc_camera_distance
                    acc_data_center = acc_data_min + (acc_data_max - acc_data_min)/2 
                    self.ui.acc3D.opts['center'] = QVector3D(acc_data_center[0], acc_data_center[1], acc_data_center[2]) 
                self.ui.acc3D.update()
                    
            if self.ui.gyrDisplay.isChecked():
                n = self.gyr_data.shape[0]
                self.gyr3D_sp.setData(pos=self.gyr_data[1:n,:], color = color, size=size)
                self.gyr3Dline_sp.setData(pos=self.gyr_data[1:n,:], width=3.0, color=(0.5, 0.5, 0.5, 0.5))
                # Calculate the data range
                if len(self.gyr_data) > 2:
                    gyr_data_range = np.linalg.norm(gyr_data_max - gyr_data_min)
                    gyr_camera_distance = gyr_data_range
                    self.ui.gyr3D.opts['distance'] = gyr_camera_distance
                    gyr_data_center = gyr_data_min + (gyr_data_max - gyr_data_min)/2 
                    self.ui.gyr3D.opts['center'] = QVector3D(gyr_data_center[0], gyr_data_center[1], gyr_data_center[2]) 
                self.ui.gyr3D.update()
                
            if self.ui.magDisplay.isChecked():
                n = self.mag_data.shape[0]
                self.mag3D_sp.setData(pos=self.mag_data[1:n,:], color = color, size=size)
                self.mag3Dline_sp.setData(pos=self.mag_data[1:n,:], width=3.0, color=(0.5, 0.5, 0.5, 0.5))
                if len(self.mag_data) > 2:
                    mag_data_range = np.linalg.norm(mag_data_max - mag_data_min)
                    mag_camera_distance = mag_data_range
                    self.ui.mag3D.opts['distance'] = mag_camera_distance
                    mag_data_center = mag_data_min + (mag_data_max - mag_data_min)/2 
                    self.ui.mag3D.opts['center'] = QVector3D(mag_data_center[0], mag_data_center[1], mag_data_center[2]) 
                self.ui.mag3D.update()

    def clear_data(self):
        # display data
        if self.ui.accDisplay.isChecked():
            self.acc_data = np.zeros([1,3])
            self.accXY_sp.setData(x=self.acc_data[1:-1,0], y=self.acc_data[1:-1,1])
            self.accYZ_sp.setData(x=self.acc_data[1:-1,1], y=self.acc_data[1:-1,2])
            self.accZX_sp.setData(x=self.acc_data[1:-1,2], y=self.acc_data[1:-1,0])
            if USE3DPLOT == True:
                self.acc3D_sp.setData(pos=self.acc_data, color = (1, 1, 1, 1), size=2)
                self.acc3Dline_sp.setData(pos=self.acc_data, color = (1, 1, 1, 1), width=3.0)
        
        if self.ui.gyrDisplay.isChecked():
            self.gyr_data = np.zeros([1,3])
            self.gyrXY_sp.setData(x=self.gyr_data[1:-1,0], y=self.gyr_data[1:-1,1])
            self.gyrYZ_sp.setData(x=self.gyr_data[1:-1,1], y=self.gyr_data[1:-1,2])
            self.gyrZX_sp.setData(x=self.gyr_data[1:-1,2], y=self.gyr_data[1:-1,0])
            if USE3DPLOT == True:
                self.gyr3D_sp.setData(pos=self.gyr_data, color = (1, 1, 1, 1), size=2)
                self.gyr3Dline_sp.setData(pos=self.gyr_data, color = (1, 1, 1, 1), width=3.0)
        
        if self.ui.magDisplay.isChecked():
            self.mag_data = np.zeros([1,3])
            self.magXY_sp.setData(x=self.mag_data[1:-1,0], y=self.mag_data[1:-1,1])
            self.magYZ_sp.setData(x=self.mag_data[1:-1,1], y=self.mag_data[1:-1,2])
            self.magZX_sp.setData(x=self.mag_data[1:-1,2], y=self.mag_data[1:-1,0])
            if USE3DPLOT == True:
                self.mag3D_sp.setData(pos=self.mag_data, color = (1, 1, 1, 1), size=2)
                self.mag3Dline_sp.setData(pos=self.mag_data, color = (1, 1, 1, 1), width=3.0)
    
######################################################################
# Main Application
######################################################################

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
