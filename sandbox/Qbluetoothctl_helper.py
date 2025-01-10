############################################################################################
# Qt Bluetoothctl Wrapper
############################################################################################
# This module provides a class to interact with linux bluetoothctl utility.
# It is designed to be used in a PyQt application.
# This class provides methods to perform 
#   pairing / removing
#   connecting / disconnecting 
#   scanning
#   trusting / distrusting
#   getting device info
#   finding device by name or mac
# Many of these methods are not available in other bluetooth libraries.
############################################################################################
# November 2024: initial release
#
# This code is maintained by Urs Utzinger
############################################################################################

try:
    from PyQt6.QtCore import (
        QObject, QProcess, pyqtSignal, pyqtSlot, 
        QTimer, QMutex, QMutexLocker, QThread,
        QEventLoop,
    )
    PYQT6 = True
except:
    from PyQt5.QtCore import (
        QObject, QProcess, pyqtSignal, pyqtSlot, 
        QTimer, QMutex, QMutexLocker, QThread,
        QEventLoop,
    )
    PYQT6 = False

import logging
import re
import numbers

class BluetoothctlWrapper(QObject):
    """
    Wrapper for executing and managing shell commands using QProcess, with command result verification.

    Signals
    
        Low-Level

        log_signal(int level, str message):     Emitted for logging purposes.
        output_ready_signal(str output):        Emitted when new output is ready.
        error_ready_signal(str error):          Emitted when an error occurs.
        finished_signal():                      Emitted when the process finishes.
        command_completed_signal():             Emitted when a command's output is successfully verified.
        command_failed_signal():                Emitted if a command fails.
        command_expired_signal():               Emitted if a command times out during output verification.
        timeout_signal():                       Emitted if output verification times out.
        startup_completed_signal():             Emitted when the expected startup output is detected.
        all_commands_processed_signal():        Emitted when all commands have been processed.


        Device Related

        device_scan_started_signal():               Emitted when device scanning starts.
        device_scan_start_failed_signal():          Emitted when starting device scanning fails.
        device_scan_stopped_signal():               Emitted when device scanning stops.
        device_scan_stop_failed_signal():           Emitted when stopping device scanning fails.
        device_found_signal(str mac, str name):     Emits MAC address and name when a device is found.
        device_not_found_signal(str device):        Emits the target device if it isn't found.
        device_info_ready_signal(dict info):        Emits a dictionary containing device information.
        device_info_failed_signal(str mac):         Emits the MAC address if device info retrieval fails.
        device_pair_succeeded_signal(str mac):      Emits MAC address on successful device pairing.
        device_pair_failed_signal(str mac):         Emits MAC address on failed device pairing.
        device_remove_succeeded_signal(str mac):    Emits MAC address on successful device removal.
        device_remove_failed_signal(str mac):       Emits MAC address on failed device removal.
        device_connect_succeeded_signal(str mac):   Emits MAC address on successful connection.
        device_connect_failed_signal(str mac):      Emits MAC address on failed connection.
        device_disconnect_succeeded_signal(str mac): Emits MAC address on successful disconnection.
        device_disconnect_failed_signal(str mac):   Emits MAC address on failed disconnection.
        device_trust_succeeded_signal(str mac):     Emits MAC address on successful trust command.
        device_trust_failed_signal(str mac):        Emits MAC address on failed trust command.
        device_distrust_succeeded_signal(str mac):  Emits MAC address on successful distrust command.
        device_distrust_failed_signal(str mac):     Emits MAC address on failed distrust command.

    Slots

        start(str expected_startup_output, int timeout_duration):   Starts the process with expected output and a timeout.
        stop():                                                     Stops the process gracefully.
        send_str(str text):                                         Sends text input (like a PIN) during pairing.
        send_command(str command, list expected_command_response=None, list failed_command_response=None, list retry_intervals=None, int timeout=None): 
                                                                    Sends a command and sets expectations for its response.
        send_multiple_commands(list commands, list expected_command_responses=None, list failed_command_responses=None, list retry_intervals=None, int timeout=None): 
                                                                    Sends multiple commands in sequence.
        enable_scan():                                              Enables Bluetooth scanning.
        disable_scan():                                             Disables Bluetooth scanning.
        find_device(str device, int scan_time=1000):                Finds a device by name or MAC address.
        get_device_info(str mac, int timeout=2000):                 Retrieves device information for a given MAC address.
        pair(str mac, str pin, int timeout=5000, int scan_time=1000): 
                                                                    Attempts to pair with a device using its MAC address and PIN.
        remove(str mac, int timeout=5000):                          Attempts to remove a device by its MAC address.
        trust(str mac, int timeout=2000):                           Attempts to trust a device by its MAC address.
        distrust(str mac, int timeout=2000):                        Attempts to distrust a device by its MAC address.
        connect(str mac, int timeout=5000):                         Attempts to connect to a device by its MAC address.
        disconnect(str mac, int timeout=2000):                      Attempts to disconnect a device by its MAC address.
        emit_log(int level, str message):                           Emits a log signal with the specified level and message.

    """
    
    # Constants
    ################################################################################################

    # default values if none are provided to the function calls
    STARTUP_TIMEOUT         = 5000  # 5 seconds
    WAIT_FOR_FINISHED       = 2000  # 2 seconds
    RETRY_INTERVALS         = [150, 200, 500]
    TOTAL_RETRY_TIME        = 5000  # for send command
    COMMAND_TIMEOUT         = 5000  #

    # Output after executing start() command

    C_STARTUP_EXPECTED_OUTPUT = "Agent registered"

    # Suggested Initialization Commands

    # "agent off", 
    C_AGENT_OFF              = "Agent unregistered"
    # "agent on", 
    C_AGENT_ON               = ["Agent registered", "Agent is already registered"]
    # "power off", 
    C_POWER_OFF              = "Changing power off succeeded"
    # "power on", 
    C_POWER_ON               = "Changing power on succeeded"
    # "default-agent" 
    C_DEFAULT_AGENT          = "Default agent request successful"
    # "pairable on"   
    C_PAIRABLE_ON            = "Changing pairable on succeeded"
    # "pairable off", 
    C_PAIRABLE_OFF           = "Changing pairable off succeeded"
    # "discoverable on",  
    C_DISCOVERABLE_ON        = "Changing discoverable on succeeded"
    #"discoverable off", 
    C_DISCOVERABLE_OFF       = "Changing discoverable off succeeded"

    # bleutoothctl commands

    # "devices", 
    NAME_PATTERN             = re.compile(r"Device\s+([A-F0-9:]+)\s+(.*)")
    MAC_PATTERN              = re.compile(r"([0-9A-Fa-f]{2}:){5}([0-9A-Fa-f]{2})")
    # "info",
    C_NAME_S                 = "Name:"
    C_CONNECTED_S            = "Connected:"
    C_TRUSTED_S              = "Trusted:"
    C_PAIRED_S               = "Paired:"
    C_BLOCKED_S              = "Blocked:"
    C_RSSI_S                 = "RSSI:"
    # "pair"
    C_PAIRED                 = "Pairing successful"
    C_PIN                    = ["Enter passkey", "Enter PIN", "PIN code"]
    C_REMOVED                = "Device has been removed"
    # "trust"
    C_TRUSTED                = "trust succeeded"
    C_DISTRUSTED             = "untrust succeeded"
    # "connect"
    C_CONNECTED              = "Connection successful"
    # "disconnect"
    C_DISCONNECTED           = "Successful disconnected"
    # "scan on"
    C_DISCOVERY_STARTED      = "Discovery started"
    C_DISCOVERY_START_FAILED = "Failed to start discovery"
    # scan off
    C_DISCOVERY_STOPPED      = "Discovery stopped"
    C_DISCOVERY_STOP_FAILED  = "Failed to stop discovery"
    # General
    C_YES                    = "yes"
    C_NO                     = "no"
    C_FAILED                 = ["Failed", "failed", "not available"]
    C_SUCCESS                = ["Success", "success", "done", "Done"]
    C_ERROR                  = ["Error", "error", "Invalid", "invalid", "not available", "Not available"]

    # Signals
    ################################################################################################
    log_signal                       = pyqtSignal(int, str)  # Emitted for logging purposes
    output_ready_signal              = pyqtSignal(str) # Emitted when new output is ready
    error_ready_signal               = pyqtSignal(str) # Emitted when an error occurs
    finished_signal                  = pyqtSignal()    # Emitted when the process finishes
    startup_completed_signal         = pyqtSignal()    # Emitted when the expected output is found during _handle_startup_output

    command_completed_signal         = pyqtSignal()    # Emitted when command output is verified
    command_failed_signal            = pyqtSignal()    # Emitted if command failed
    command_expired_signal           = pyqtSignal()    # Emitted if command expired
    timeout_signal                   = pyqtSignal()    # Emitted if output verification times out
    all_commands_processed_signal    = pyqtSignal()    # Emitted when all commands are processed

    device_scan_started_signal       = pyqtSignal()    # Emitted when device scanning is started
    device_scan_start_failed_signal  = pyqtSignal()    # Emitted when device scanning is started
    device_scan_stopped_signal       = pyqtSignal()    # Emitted when device scanning is stopped
    device_scan_stop_failed_signal   = pyqtSignal()    # Emitted when device scanning is stopped

    device_found_signal              = pyqtSignal(str, str)   # Emits MAC address and name
    device_not_found_signal          = pyqtSignal(str) # Emits the target device

    device_info_ready_signal         = pyqtSignal(dict)# Emits device_info dictionary
    device_info_failed_signal        = pyqtSignal(str) # Emits the MAC address if retrieval fails

    device_pair_succeeded_signal     = pyqtSignal(str) # Emits device_info dictionary
    device_pair_failed_signal        = pyqtSignal(str) # Emits the MAC address if retrieval fails
    device_remove_succeeded_signal   = pyqtSignal(str) # Emits the MAC address on device removal success
    device_remove_failed_signal      = pyqtSignal(str) # Emits the MAC address on device removal failure

    device_connect_succeeded_signal  = pyqtSignal(str) # Emits the MAC address on device connection success
    device_connect_failed_signal     = pyqtSignal(str) # Emits the MAC address on device connection failure
    device_disconnect_succeeded_signal = pyqtSignal(str)  # Emits the MAC address on device disconnect success
    device_disconnect_failed_signal  = pyqtSignal(str) # Emits the MAC address on device disconnect failure

    device_trust_succeeded_signal    = pyqtSignal(str) # Emits the MAC address on device trust success
    device_trust_failed_signal       = pyqtSignal(str) # Emits the MAC address on device trust failure
    device_distrust_succeeded_signal = pyqtSignal(str) # Emits the MAC address on device distrust success
    device_distrust_failed_signal    = pyqtSignal(str) # Emits the MAC address on device distrust failure

    def __init__(self, process_command: str, parent=None):
        super().__init__(parent)
        self.process_command = process_command  # Command to execute in the process

        # Mutex for thread safety
        self.mutex = QMutex()

        # Placeholder for process-related properties
        self.process                    = None
        self.startup_timeout_timer      = None

        self.startup_expected_text_found = False
        self.command_expected_text_found = False
        # self.stop_verification          = False

        self.expected_command_response  = []
        self.expected_startup_output    = []
        self.output_buffer              = ""
        
        self.pending_command            = None
        self.retry_intervals            = []
        self.max_total_retry_time       = self.TOTAL_RETRY_TIME
        self.retry_count                = 0
        self.total_retry_time           = 0

    def emit_log(self, level, message):
        """Emit the log signal with a level and message."""
        self.log_signal.emit(level, message)

    def start(self, expected_startup_output=C_STARTUP_EXPECTED_OUTPUT, timeout_duration=STARTUP_TIMEOUT):
        """Start the process and set up to wait for specific output."""
        self.process = QProcess()

        # Timer for handling the startup timeout
        self.startup_timeout_timer = QTimer()
        self.startup_timeout_timer.setSingleShot(True)
        self.startup_timeout_timer.timeout.connect(self._handle_startup_timeout)

        # Connect signals to QProcess slots
        self.process.readyReadStandardOutput.connect(self._handle_startup_output)
        self.process.readyReadStandardError.connect(self._handle_error)
        self.process.finished.connect(self._handle_finished)
        self.process.stateChanged.connect(self._handle_state_changed)

        self.expected_startup_output = expected_startup_output or self.C_STARTUP_EXPECTED_OUTPUT

        if self.process.state() == QProcess.NotRunning:
            self.process.setProgram(self.process_command)
            self.process.start()
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Started process \"{self.process_command}\"")
            self.startup_timeout_timer.start(timeout_duration)
        else:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Process is already running.")

    @pyqtSlot()
    def _handle_startup_output(self):
        """Handle startup output.Expects process output indicating bluetoothctl agent is present"""

        # Read the output from the process
        output = self.process.readAllStandardOutput().data().decode().strip()

        # Append new output to the buffer
        self.output_buffer += output

        # Check if the target startup message is present
        if not self.startup_expected_text_found and self.expected_startup_output in self.output_buffer:
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: \"{self.expected_startup_output}\" found.")

            # stop the timeout timer as we found the expected output
            if self.startup_timeout_timer and self.startup_timeout_timer.isActive():
                self.startup_timeout_timer.stop()

            try: 
                self.startup_timeout_timer.timeout.disconnect(self._handle_startup_timeout)
            except TypeError:
                self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _handle_startup_timeout.")

            # Disconnect this slot as it's no longer needed after startup
            try:
                self.process.readyReadStandardOutput.disconnect(self._handle_startup_output)
            except TypeError:
                self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _handle_startup_output.")
            
            # Set the flag to indicate startup text is found
            self.startup_expected_text_found = True

            # If the process is already in the Running state, emit the startup completed signal
            if self.process.state() == QProcess.Running:
                self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Process is fully running.")
                self.startup_completed_signal.emit()

        # Emit the log text for general purposes
        if output:
            formatted_output = output.replace("\r\n", ", ").replace("\r", ", ").replace("\n", ", ").strip(", ")
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: {self.process_command}: {formatted_output}")

    @pyqtSlot()
    def stop(self):
        """Stop the process gracefully."""

        # # Stop verification process if running
        # with QMutexLocker(self.mutex):
        #     self.stop_verification = True
        if self.process and self.process.state() != QProcess.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(self.WAIT_FOR_FINISHED):
                self.process.kill()
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Process terminated.")
            self._cleanup()
        else:
            self.emit_log(logging.WARNING, "Process is not running, nothing to stop.")
        self.finished_signal.emit()

    def _cleanup(self):
        """Clean up the resources."""

        # Disconnect remaining signals
        try:
            self.process.readyReadStandardError.disconnect()
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: readyReadStandardError already disconnected.")

        try:
            self.process.finished.disconnect()
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: finished already disconnected.")

        try:
            self.process.stateChanged.disconnect()
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: stateChanged already disconnected.")

        # Reset state
        self.startup_expected_text_found = False
        self.pending_command = None
        self.output_buffer = ""

        self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Cleanup complete.")
            
    @pyqtSlot()
    def _handle_error(self):
        """Handle error data from the process's standard error."""
        error = self.process.readAllStandardError().data().decode().strip()
        self.emit_log(logging.ERROR, f"[{int(QThread.currentThreadId())}]: Process error: {error}")
        self.error_ready_signal.emit(error)

    @pyqtSlot(int, QProcess.ExitStatus)
    def _handle_finished(self, exit_code, exit_status):
        """Handle process termination."""
        if exit_status == QProcess.NormalExit:
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Process finished with exit code {exit_code}.")
        else:
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Process crashed with exit code {exit_code}.")
        self.finished_signal.emit()

    @pyqtSlot(QProcess.ProcessState)
    def _handle_state_changed(self, new_state):
        """Handle state changes of the QProcess from starting to running."""
        if new_state == QProcess.Running and self.startup_expected_text_found:
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Process is now running.")
            self.startup_completed_signal.emit()

    @pyqtSlot()
    def _handle_startup_timeout(self):
        """Handle the case when waiting for exepcted startup times out."""
        self.emit_log(logging.ERROR, f"Timeout occurred while waiting for expected output: \"{self.expected_startup_output}\"")

        try:
            self.startup_timeout_timer.timeout.disconnect(self._handle_startup_timeout)
            self.process.readyReadStandardOutput.disconnect(self._handle_startup_output)
            self.process.readyReadStandardError.disconnect(self._handle_error)
        except TypeError:
            self.emit_log(logging.ERROR, f"[{int(QThread.currentThreadId())}]: Already disconnected the signals for _handle_startup_output and _handle_error.")

        # Stop the process if it's still running
        if self.process.state() == QProcess.Running or self.process.state() == QProcess.Starting:
            self.process.terminate()
            if not self.process.waitForFinished(2000):  # Grace period of 2 seconds to stop
                self.process.kill()
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Process terminated due to timeout.")

        # Emit the timeout signal to notify that we have timed out while waiting for the expected output
        self.timeout_signal.emit()

    # Functions
    ################################
    @pyqtSlot(str)
    def send_str(self, text: str):
        """
        Send the text such as PIN during the pairing process.
        The text is sent without expecting an explicit confirmation.
        """
        if self.process.state() == QProcess.Running:
            self.process.write((text + '\n').encode())  # Write the text to the process without expecting feedback
        else:
            self.emit_log(logging.ERROR, "Bluetoothctl process not running.")

    def send_command(self,  command: str,
                            expected_command_response=None,
                            failed_command_response=None,
                            retry_intervals=None,
                            timeout=None):
        """Send a command to the running process and set an expected output to verify."""
        
        # Set default values if not provided
        if retry_intervals is None:
            retry_intervals = self.RETRY_INTERVALS
        if timeout is None:
            timeout = self.TOTAL_RETRY_TIME

        # Validate and set up expected and failed command responses
        if isinstance(expected_command_response, str):
            expected_command_response = [expected_command_response]
        elif expected_command_response is None:
            expected_command_response = []
        elif not isinstance(expected_command_response, list):
            self.emit_log(logging.ERROR, "Invalid \"expected_command_response\" type")
            self.command_expired_signal.emit()
            return

        if isinstance(failed_command_response, str):
            failed_command_response = [failed_command_response]
        elif failed_command_response is None:
            failed_command_response = []
        elif not isinstance(failed_command_response, list):
            self.emit_log(logging.ERROR, "Invalid \"failed_command_response\" type")
            self.command_expired_signal.emit()
            return

        if isinstance(timeout, numbers.Number):
            self.max_total_retry_time = timeout
        else:
            self.emit_log(logging.ERROR, "Invalid \"timeout\" type")
            self.command_expired_signal.emit()
            return

        if self.process.state() == QProcess.Running:

            # Clear the buffer to remove any previous output
            self.output_buffer = ""

            # Read the existing process output to clear any residual output
            self.process.readAllStandardOutput()

            command_str = command + "\n"
            self.process.write(command_str.encode())
            self.emit_log(logging.INFO, f"Sent command: {command}")
            
            # Set the expected output and start the verification timer
            with QMutexLocker(self.mutex):
                self.pending_command           = command
                self.expected_command_response = expected_command_response
                self.failed_command_response   = failed_command_response
                self.retry_intervals           = retry_intervals
                self.retry_count               = 0
                self.total_retry_time          = 0

            # Collect output from the process
            try:
                self.process.readyReadStandardOutput.disconnect(self._handle_command_output)
            except TypeError:
                pass
            self.process.readyReadStandardOutput.connect(self._handle_command_output)
            
            # Start the verification attempt after sending the command
            QTimer.singleShot(self.retry_intervals[0], self._verify_command_result)
        else:
            self.emit_log(logging.ERROR, "Attempted to send command, but process is not running.")
            self.error_ready_signal.emit("Process is not running")

    @pyqtSlot()
    def _handle_command_output(self):
        """Handle output for command verification."""
        output = self.process.readAllStandardOutput().data().decode().strip()
        self.output_buffer += output

        # Emit the log text for general purposes
        if output:
            formatted_output = output.replace("\r\n", ", ").replace("\r", ", ").replace("\n", ", ").strip(", ")
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: {self.process_command}: {formatted_output}")

    @pyqtSlot()
    def _verify_command_result(self):
        """Verify if the expected output is present in the output buffer."""

        # if self.stop_verification:
        #     self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Verification should be stopped.")
        #     return
        
        # Check for expected responses
        if any(key in self.output_buffer for key in self.expected_command_response):
            self.emit_log(logging.INFO, f"Command '{self.pending_command}' verified successfully.")
            self._command_cleanup()
            self.command_completed_signal.emit()
            return
    
        # Check for failed responses
        if any(key in self.output_buffer for key in self.failed_command_response):
            self.emit_log(logging.INFO, f"Command '{self.pending_command}' failed.")
            self._command_cleanup()
            self.command_failed_signal.emit()
            return
    
        # Retry logic if the expected output is not found
        self.retry_count += 1
        next_interval = self.retry_intervals[min(self.retry_count, len(self.retry_intervals) - 1)]
        self.total_retry_time += next_interval

        if self.total_retry_time < self.max_total_retry_time:
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Expected output from {self.pending_command} not found. Retrying in {next_interval} ms ({self.retry_count})...")
            QTimer.singleShot(next_interval, self._verify_command_result)
        else:
            self.emit_log(logging.ERROR, f"Command '{self.pending_command}' failed to verify after maximum retry time.")
            self._command_cleanup()
            self.command_expired_signal.emit()

    def _command_cleanup(self):
        try:
            self.process.readyReadStandardOutput.disconnect(self._handle_command_output)
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: readyReadStandardOutput already disconnected.")

    @pyqtSlot(list, list, list, object, object)
    def send_multiple_commands(self, 
            commands: list, 
            expected_command_responses: list = None, 
            failed_command_responses: list = None, 
            retry_intervals=None,
            timeout = None):
        
        """Send multiple commands in sequence."""
        self.commands_queue = commands.copy()
        num_commands = len(commands)

        # Prepare expected responses
        if expected_command_responses is None:
            self.expected_command_responses_queue = [None] * num_commands
        else:
            self.expected_command_responses_queue = expected_command_responses.copy()

        # Prepare failed responses
        if failed_command_responses is None:
            self.failed_command_responses_queue = [None] * num_commands
        else:
            self.failed_command_responses_queue = failed_command_responses.copy()

        # Prepare retry intervals
        if retry_intervals is None:
            self.retry_intervals = self.RETRY_INTERVALS
        elif isinstance(retry_intervals, list):
            self.retry_intervals = retry_intervals.copy()
        else:
            self.retry_intervals = [retry_intervals]

        if timeout is None:
            self.timeout = self.TOTAL_RETRY_TIME
        else:
            self.timeout = timeout

        # Connect command completion signals
        self.command_completed_signal.connect(self._on_multicommand_completed)
        self.command_failed_signal.connect(self._on_multicommand_failed)
        self.command_expired_signal.connect(self._on_multicommand_expired)

        # Start sending commands
        self._send_next_command()

    def _send_next_command(self):
        if self.commands_queue:
            # Get the next command and its responses
            command             = self.commands_queue.pop(0)
            expected_response   = self.expected_command_responses_queue.pop(0)
            failed_response     = self.failed_command_responses_queue.pop(0)
            retry_intervals     = self.retry_intervals
            timeout             = self.timeout

            # Send the command
            self.send_command(command, expected_response, failed_response, retry_intervals, timeout)
        else:
            # All commands have been processed
            self.emit_log(logging.INFO, "All commands have been processed.")
            # Disconnect signals
            self.command_completed_signal.disconnect(self._on_multicommand_completed)
            self.command_failed_signal.disconnect(self._on_multicommand_failed)
            self.command_expired_signal.disconnect(self._on_multicommand_expired)
            # Emit completion signal
            self.all_commands_processed_signal.emit()

    def _on_multicommand_completed(self):
        # Proceed to send the next command
        self._send_next_command()

    def _on_multicommand_failed(self):
        # Command failed, decide whether to stop or continue
        self.emit_log(logging.ERROR, f"Command '{self.pending_command}' failed.")
        self._send_next_command()

    def _on_multicommand_expired(self):
        # Commands timed out, handle accordingly
        self.emit_log(logging.ERROR, f"Command '{self.pending_command}' expired.")
        self._send_next_command()

    # Wrapped Commands
    ###########################################################################################

    # Enable / Disable Scan
    # ==========================================================================================

    def enable_scan(self):
        """Enable Bluetooth scanning."""
        # Send the "scan on" command
        self.send_command(
            command="scan on",
            expected_command_response = self.C_DISCOVERY_STARTED,
            failed_command_response = self.C_DISCOVERY_START_FAILED,
            retry_intervals = [250, 500],
            timeout = 5000
        )
        # Connect signals to handle the command result
        try:
            self.command_completed_signal.disconnect()
            self.command_failed_signal.disconnect()
            self.command_expired_signal.disconnect()
        except:
            pass
        finally:
            self.command_completed_signal.connect(self._on_scan_started_success)
            self.command_failed_signal.connect(self._on_scan_started_failure)
            self.command_expired_signal.connect(self._on_scan_started_failure)

    def _on_scan_started_success(self):
        """Handle the successful result of the 'scan on' command."""
        # Emit the device_scan_started_signal
        # Disconnect signals to avoid multiple connections
        self._disconnect_scan_started_signals()
        self.device_scan_started_signal.emit()

    def _on_scan_started_failure(self):
        """Handle the failed or expired result of the 'scan on' command."""
        # Optionally handle failure
        self.emit_log(logging.ERROR, "Failed to start scanning.")
        # Disconnect signals
        self._disconnect_scan_started_signals()
        self.device_scan_start_failed_signal.emit()

    def _disconnect_scan_started_signals(self):
        """Disconnect scan started command signals to avoid multiple connections."""
        try:
            self.command_completed_signal.disconnect(self._on_scan_started_success)
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _on_scan_started_success.")
        try:
            self.command_failed_signal.disconnect(self._on_scan_started_failure)
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _on_scan_started_failure.")
        try:
            self.command_expired_signal.disconnect(self._on_scan_started_failure)
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _on_scan_started_failure.")

    ######

    def disable_scan(self):
        """Disable Bluetooth scanning."""
        # Send the "scan off" command
        self.send_command(
            command="scan off",
            expected_command_response = self.C_DISCOVERY_STOPPED,
            failed_command_response = self.C_DISCOVERY_STOP_FAILED,
            retry_intervals = [250, 500],
            timeout = 2000
        )
        # Connect signals to handle the command result
        try:
            self.command_completed_signal.disconnect()
            self.command_failed_signal.disconnect()
            self.command_expired_signal.disconnect()
        except:
            pass
        finally:
            self.command_completed_signal.connect(self._on_scan_stopped_success)
            self.command_failed_signal.connect(self._on_scan_stopped_failure)
            self.command_expired_signal.connect(self._on_scan_stopped_failure)

    def _on_scan_stopped_success(self):
        """Handle the successful result of the 'scan off' command."""
        # Emit the device_scan_stopped_signal
        self.device_scan_stopped_signal.emit()
        # Disconnect signals to avoid multiple connections
        self._disconnect_scan_stopped_signals()

    def _on_scan_stopped_failure(self):
        """Handle the failed or expired result of the 'scan off' command."""
        # Optionally handle failure
        self.device_scan_stop_failed_signal.emit()
        self.emit_log(logging.ERROR, "Failed to stop scanning.")
        # Disconnect signals
        self._disconnect_scan_stopped_signals()

    def _disconnect_scan_stopped_signals(self):
        """Disconnect scan stopped command signals to avoid multiple connections."""
        try:
            self.command_completed_signal.disconnect(self._on_scan_stopped_success)
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _on_scan_stopped_success.")
        try:
            self.command_failed_signal.disconnect(self._on_scan_stopped_failure)
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _on_scan_stopped_failure.")
        try:
            self.command_expired_signal.disconnect(self._on_scan_stopped_failure)
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _on_scan_stopped_failure.")

    # Find Device
    # ==========================================================================================

    # find_device(device: str) # device is either a name or a mac address
    # 1. Start Scanning
    # 2. Delay for 1 second to allow scanning to find devices
    # 3. Stop scanning
    # 3. Execute "devices" command to list all devices
    # 4. The output will be multiple lines each containing a mac and name 
    #    a) if find device input was a name parse through list until name was found
    #    b) if find device input was a mac parse through list until mac was found
    # 5. Emit the mac and name of the device as completion signal

    def find_device(self, device: str, scan_time=1000):
        """Find a device by name or MAC address."""
        self.target_device = device.strip()
        self.search_for_mac = bool(self.MAC_PATTERN.match(self.target_device))
        self.device_found = False
        self.devices_output_buffer = ""
        self.collecting_devices_output = False
        self.scan_time = scan_time
        self.partialLine = ""

        # Connect to device_scan_started_signal
        try:
            self.device_scan_started_signal.disconnect()
        except TypeError:
            pass
        finally:
            self.device_scan_started_signal.connect(self._on_scanning_started_for_find_device)

        # Start scanning
        self.enable_scan()

    def _on_scanning_started_for_find_device(self):
        """Proceed after scanning has started."""
        # Disconnect the signal to avoid multiple connections
        try:
            self.device_scan_started_signal.disconnect(self._on_scanning_started_for_find_device)
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _on_scanning_started_for_find_device.")

        # Wait for `scan_time` milliseconds to allow scanning to discover devices
        QTimer.singleShot(self.scan_time, self._stop_scanning_and_get_devices)

    def _stop_scanning_and_get_devices(self):
        """Stop scanning and prepare to send 'devices' command."""
        # Connect to device_scan_stopped_signal
        self.device_scan_stopped_signal.connect(self._on_scanning_stopped_for_find_device)

        # Stop scanning
        self.disable_scan()

    def _on_scanning_stopped_for_find_device(self):
        """Proceed after scanning has stopped."""
        # Disconnect the signal
        try:
            self.device_scan_stopped_signal.disconnect(self._on_scanning_stopped_for_find_device)
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _on_scanning_stopped_for_find_device.")

        # Connect to readyReadStandardOutput to collect devices output
        self.process.readyReadStandardOutput.connect(self._handle_devices_output)

        # Send 'devices' command
        self.collecting_devices_output = True
        self.devices_output_buffer = ""
        command_str = "devices\n"
        self.process.write(command_str.encode())
        self.emit_log(logging.INFO, f"Sent command: devices")

        # Set up a timer to delay the initial parsing of devices output
        QTimer.singleShot(200, self._parse_devices_output)

        # Set up a timeout timer to stop collecting devices output
        self.parse_device_timeout_timer = QTimer()
        self.parse_device_timeout_timer.setSingleShot(True)
        self.parse_device_timeout_timer.timeout.connect(self._handle_parse_devices_output_timeout)
        self.parse_device_timeout_timer.start(1000)

    def _handle_devices_output(self):
        """Collect output from 'devices' command."""
        if self.collecting_devices_output:
            output = self.process.readAllStandardOutput().data().decode()
            self.devices_output_buffer += output
        else:
            # Read and discard any output not related to 'devices' command
            self.process.readAllStandardOutput()

        # Emit the log text for general purposes
        if output:
            formatted_output = output.replace("\r\n", ", ").replace("\r", ", ").replace("\n", ", ").strip(", ")
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: {self.process_command}: {formatted_output}")


    def _parse_devices_output(self):
        """Parse the output of 'devices' command to find the target device."""
        if self.device_found:
            return  # Device already found, no need to parse further

        _data = self.devices_output_buffer
        self.devices_output_buffer = ""

        # Combine with any partial line from the previous read
        if self.partialLine:
            _data = self.partialLine + _data
            self.partialLine = ""

        # Split the output into lines
        lines = _data.split('\n')

        # Check if the last line is incomplete
        if _data and _data[-1] != '\n':
            self.partialLine = lines.pop()  # Save it for the next read

        # Iterate through lines to find the device
        for line in lines:
            match = self.NAME_PATTERN.search(line.strip())
            if match:
                mac = match.group(1)
                name = match.group(2).strip()
                if self.search_for_mac:  # Target is MAC
                    if mac.lower() == self.target_device.lower():
                        # Device found
                        self.device_found = True
                else:  # Target is name
                    if name == self.target_device:
                        # Device found
                        self.device_found = True

                if self.device_found:
                    # Stop collecting output
                    self.collecting_devices_output = False
                    # Disconnect signals
                    try:
                        self.process.readyReadStandardOutput.disconnect(self._handle_devices_output)
                    except TypeError:
                        self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _handle_devices_output.")
                    self.parse_device_timeout_timer.stop()
                    try:
                        self.parse_device_timeout_timer.timeout.disconnect(self._handle_parse_devices_output_timeout)
                    except:
                        self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _handle_parse_devices_output_timeout.")
                    self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Device found: {mac} {name}")
                    self.device_found_signal.emit(mac, name)
                    return

        # Schedule the next parsing if timeout has not occurred
        if not self.device_found and self.parse_device_timeout_timer.isActive():
            QTimer.singleShot(100, self._parse_devices_output)

    def _handle_parse_devices_output_timeout(self):
        """Handle the timeout of parsing devices output."""
        if not self.device_found:
            self.collecting_devices_output = False
            # Disconnect the readyReadStandardOutput signal
            try:
                self.process.readyReadStandardOutput.disconnect(self._handle_devices_output)
            except TypeError:
                self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _handle_devices_output.")
            try:
                self.parse_device_timeout_timer.timeout.disconnect(self._handle_parse_devices_output_timeout)
            except:
                self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _handle_parse_devices_output_timeout.")

            self.emit_log(logging.ERROR, f"[{int(QThread.currentThreadId())}]: Device '{self.target_device}' not found.")
            self.device_not_found_signal.emit(self.target_device)

    # get device info
    # ==========================================================================================

    def get_device_info(self, mac: str, timeout=2000):
        """Retrieve device information for a given MAC address."""

        self.target_mac = mac.strip()
        self.device_info = {
            "mac": self.target_mac,
            "name": None,
            "paired": None,
            "trusted": None,
            "connected": None,
            "blocked": None,
            "rssi": None
        }

        self.info_output_buffer = ""
        self.info_timeout = timeout
        self.name_found = False
        self.paired_found = False
        self.connected_found = False
        self.blocked_found = False
        self.trusted_found = False
        self.rssi_found = False
        self.info_found = False
        self.collecting_info_output = True
        self.partialLine = ""

        # Connect to readyReadStandardOutput to collect info output
        try:
            self.process.readyReadStandardOutput.disconnect()
        except TypeError:
            pass
        finally:
            self.process.readyReadStandardOutput.connect(self._handle_info_output)

        # Send the 'info <MAC>' command
        command_str = f"info {self.target_mac}\n"
        self.process.write(command_str.encode())
        self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Sent command: info {self.target_mac}")

        # Set up a timer to delay the initial parsing of info output
        QTimer.singleShot(200, self._parse_info_output)

        # Set up a timeout timer to stop collecting info output
        self.parse_info_timeout_timer = QTimer()
        self.parse_info_timeout_timer.setSingleShot(True)
        self.parse_info_timeout_timer.timeout.connect(self._handle_parse_info_output_timeout)
        self.parse_info_timeout_timer.start(timeout)

    def _handle_info_output(self):
        """Collect output from 'info' command."""
        if self.collecting_info_output:
            output = self.process.readAllStandardOutput().data().decode()
            self.info_output_buffer += output
        else:
            # Read and discard any output not related to 'info' command
            self.process.readAllStandardOutput()

        # Emit the log text for general purposes
        if output:
            formatted_output = output.replace("\r\n", ", ").replace("\r", ", ").replace("\n", ", ").strip(", ")
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: {self.process_command}: {formatted_output}")

    def _parse_info_output(self):
        """Parse the output of 'info <MAC>' command to obtain device info."""

        if self.info_found:
            return  # Info completed, no need to parse further

        _data = self.info_output_buffer
        self.info_output_buffer = ""

        # Combine with any partial line from the previous read
        if self.partialLine:
            _data = self.partialLine + _data
            self.partialLine = ""

        # Split the output into lines
        lines = _data.split('\n')

        # Check if the last line is incomplete
        if _data and _data[-1] != '\n':
            self.partialLine = lines.pop()  # Save it for the next read

        # Iterate through lines to find the device information
        for line in lines:
            line = line.strip()

            # Check for "Name"
            if self.C_NAME_S in line and not self.name_found:
                self.device_info["name"] = line.split(self.C_NAME_S)[1].strip()
                self.name_found = True

            # Check for "Connected" status
            elif self.C_CONNECTED_S in line and not self.connected_found:
                status = line.split(self.C_CONNECTED_S)[1].strip().lower()
                self.device_info["connected"] = status == self.C_YES
                self.connected_found = True

            # Check for "Trusted" status
            elif self.C_TRUSTED_S in line and not self.trusted_found:
                status = line.split(self.C_TRUSTED_S)[1].strip().lower()
                self.device_info["trusted"] = status == self.C_YES
                self.trusted_found = True

            # Check for "Paired" status
            elif self.C_PAIRED_S in line and not self.paired_found:
                status = line.split(self.C_PAIRED_S)[1].strip().lower()
                self.device_info["paired"] = status == self.C_YES
                self.paired_found = True

            # Check for "Paired" status
            elif self.C_BLOCKED_S in line and not self.blocked_found:
                status = line.split(self.C_BLOCKED_S)[1].strip().lower()
                self.device_info["blocked"] = status == self.C_YES
                self.blocked_found = True

            # Check for RSSI information
            elif self.C_RSSI_S in line and not self.rssi_found:
                try:
                    rssi_value = int(line.split(self.C_RSSI_S)[1].strip())
                    self.device_info["rssi"] = rssi_value
                    self.rssi_found = True
                except ValueError:
                    self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Failed to parse RSSI value for {self.target_mac}.")

        # Emit relevant logs
        if self.connected_found:
            status = "connected" if self.device_info["connected"] else "not connected"
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: {self.target_mac} is {status}.")

        if self.trusted_found:
            status = "trusted" if self.device_info["trusted"] else "not trusted"
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: {self.target_mac} is {status}.")

        if self.paired_found:
            status = "paired" if self.device_info["paired"] else "not paired"
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: {self.target_mac} is {status}.")

        if self.blocked_found:
            status = "blocked" if self.device_info["paired"] else "not blocked"
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: {self.target_mac} is {status}.")

        if self.rssi_found:
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: {self.target_mac} RSSI: {self.device_info['rssi']} dBm.")

        self.info_found = (
            self.name_found and self.paired_found and
            self.trusted_found and self.connected_found and
            self.blocked_found
        )

        # Schedule the next parsing if timeout has not occurred
        if not self.info_found and self.parse_info_timeout_timer.isActive():
            QTimer.singleShot(100, self._parse_info_output)
        else:
            self.parse_info_timeout_timer.stop()
            try:
                self.parse_info_timeout_timer.timeout.disconnect(self._handle_parse_info_output_timeout)
            except:
                pass

            # Disconnect the signal
            try:
                self.process.readyReadStandardOutput.disconnect(self._handle_info_output)
            except TypeError:
                self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _handle_info_output.")
            self.collecting_info_output = False
            if self.info_found:
                self.device_info_ready_signal.emit(self.device_info)
            else:
                self.emit_log(logging.ERROR, f"[{int(QThread.currentThreadId())}]: Failed to retrieve full info for {self.target_mac}")
                self.device_info_failed_signal.emit(self.target_mac)

    def _handle_parse_info_output_timeout(self):
        """Handle the timeout of parsing device info output."""
        if not self.info_found:
            # Disconnect the signal
            try:
                self.process.readyReadStandardOutput.disconnect(self._handle_info_output)
            except TypeError:
                self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _handle_info_output.")
            try:
                self.parse_info_timeout_timer.timeout.disconnect(self._handle_parse_info_output_timeout)
            except:
                self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _handle_parse_info_output_timeout.")
            self.collecting_info_output = False
            self.emit_log(logging.ERROR, f"[{int(QThread.currentThreadId())}]: Timeout occurred while retrieving info for {self.target_mac}")
            self.device_info_failed_signal.emit(self.target_mac)

    # Pair / Remove Device
    # ==========================================================================================
    def pair(self, mac: str, pin: str, timeout=5000, scan_time=1000):
        """Attempt to pair with a device given its MAC address and PIN."""

        self.target_mac = mac.strip()
        self.pin = pin
        self.scan_time = scan_time

        self.pair_output_buffer = ""
        self.pair_timeout = timeout
        self.pairing_completed = False
        self.pairing_failed = False
        self.pairing_done = False
        self.pin_found = False
        self.collecting_pair_output = True
        self.partial_line = ""

        # Connect to device_scan_started_signal
        try:
            self.device_scan_started_signal.disconnect()
        except TypeError:
            pass
        finally:
            self.device_scan_started_signal.connect(self._on_scanning_started_for_pair_device)

        # Start scanning
        self.enable_scan()


    def _on_scanning_started_for_pair_device(self):
        """Proceed with pairing after scanning."""
        # Disconnect the signal to avoid multiple connections
        try:
            self.device_scan_started_signal.disconnect(self._on_scanning_started_for_pair_device)
        except:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _on_scanning_started_for_pair_device.")

        # Wait for `scan_time` milliseconds to allow scanning to discover devices
        QTimer.singleShot(self.scan_time, self._stop_scanning_and_pair_device)

    def _stop_scanning_and_pair_device(self):
        """Pair with the device."""

        # Connect to readyReadStandardOutput to collect pair output
        self.process.readyReadStandardOutput.connect(self._handle_pair_output)

        # Send the 'pair <MAC>' command
        command_str = f"pair {self.target_mac}\n"
        self.process.write(command_str.encode())
        self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Sent command: pair {self.target_mac}")

        # Set up a timer to delay the initial parsing of pair output
        QTimer.singleShot(200, self._parse_pair_output)

        # Set up a timeout timer to stop collecting pair output
        self.parse_pair_timeout_timer = QTimer()
        self.parse_pair_timeout_timer.setSingleShot(True)
        self.parse_pair_timeout_timer.timeout.connect(self._handle_parse_pair_output_timeout)
        self.parse_pair_timeout_timer.start(self.pair_timeout)

    def _handle_pair_output(self):
        """Collect output from 'pair' command."""
        if self.collecting_pair_output:
            output = self.process.readAllStandardOutput().data().decode()
            self.pair_output_buffer += output
        else:
            # Read and discard any output not related to 'pair' command
            self.process.readAllStandardOutput()

        # Emit the log text for general purposes
        if output:
            formatted_output = output.replace("\r\n", ", ").replace("\r", ", ").replace("\n", ", ").strip(", ")
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: {self.process_command}: {formatted_output}")

    def _parse_pair_output(self):
        """Parse the output of 'pair <MAC>' command."""

        if self.pairing_done:
            return  # Pairing completed, no need to parse further

        _data = self.pair_output_buffer
        self.pair_output_buffer = ""

        # Combine with any partial line from the previous read
        if self.partial_line:
            _data = self.partial_line + _data
            self.partial_line = ""

        # Split the output into lines
        lines = _data.split('\n')

        # Check if the last line is incomplete
        if _data and _data[-1] != '\n':
            self.partial_line = lines.pop()  # Save it for the next read

        # Iterate through lines to find pairing information
        for line in lines:
            line = line.strip()

            # Check for "Enter PIN code"
            if any(key in line for key in self.C_PIN) and not self.pin_found:
                self.pin_found = True
                command_str = f"{self.pin}\n"
                self.process.write(command_str.encode())
                self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Sent PIN code for {self.target_mac}.")
                self.pair_output_buffer = ""
                break

            # Check for "Pairing successful"
            if self.C_PAIRED in line and not self.pairing_completed:
                self.pairing_completed = True
                self.pairing_done = True

            # Check for "Failed"
            elif any(key in line for key in self.C_FAILED) and not self.pairing_failed:
                self.pairing_failed = True
                self.pairing_done = True

        # Schedule the next parsing if timeout has not occurred
        if not self.pairing_done and self.parse_pair_timeout_timer.isActive():
            QTimer.singleShot(200, self._parse_pair_output)
        elif self.pairing_failed:
            self.parse_pair_timeout_timer.stop()
            self.collecting_pair_output = False
            if self.pin_found:
                self.emit_log(logging.ERROR, f"[{int(QThread.currentThreadId())}]: {self.target_mac} pairing failed with PIN.")
            else:
                self.emit_log(logging.ERROR, f"[{int(QThread.currentThreadId())}]: {self.target_mac} pairing failed.")
            self._pairing_cleanup()
            self.device_pair_failed_signal.emit(self.target_mac)
        elif self.pairing_completed:
            self.parse_pair_timeout_timer.stop()
            # Disconnect the signal
            self.collecting_pair_output = False
            self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: {self.target_mac} pairing completed.")
            self._pairing_cleanup()
            self.device_pair_succeeded_signal.emit(self.target_mac)
        else:
            self.emit_log(logging.ERROR, f"[{int(QThread.currentThreadId())}]: Pairing command program logic failed for {self.target_mac}")
            self._pairing_cleanup()
            self.device_pair_failed_signal.emit(self.target_mac)

    def _handle_parse_pair_output_timeout(self):
        """Handle the timeout of parsing pairing device output."""
        # Disconnect the signal
        self.collecting_pair_output = False
        self.emit_log(logging.ERROR, f"[{int(QThread.currentThreadId())}]: Timeout occurred while pairing {self.target_mac}")
        self._pairing_cleanup()
        self.device_pair_failed_signal.emit(self.target_mac)

    def _pairing_cleanup(self):
        try:
            self.process.readyReadStandardOutput.disconnect(self._handle_pair_output)
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _handle_pair_output.")
        try:
            self.parse_pair_timeout_timer.timeout.disconnect(self._handle_parse_pair_output_timeout)
        except:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected _handle_parse_pair_output_timeout.")

        self.disable_scan()

    ######

    def remove(self, mac: str, timeout=5000):
        """Attempt to remove a device given its MAC address."""
        self.target_mac = mac.strip()

        # Disconnect any previous connections to avoid multiple emissions
        try:
            self.command_completed_signal.disconnect()
            self.command_failed_signal.disconnect()
            self.command_expired_signal.disconnect()
        except TypeError:
            pass
        finally:
            # Connect signals to appropriate handlers
            self.command_completed_signal.connect(self._handle_remove_success)
            self.command_failed_signal.connect(self._handle_remove_failure)
            self.command_expired_signal.connect(self._handle_remove_failure)

        self.send_command(
            command                     = f"remove {self.target_mac}", 
            expected_command_response   = self.C_REMOVED, 
            failed_command_response     = self.C_FAILED,
            retry_intervals             = [500, 1000],
            timeout                    = timeout,
        )

    def _handle_remove_success(self):
        self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Device {self.target_mac} has been removed.")
        self._disconnect_remove_command_signals()
        self.device_remove_succeeded_signal.emit(self.target_mac)

    def _handle_remove_failure(self):
        self.emit_log(logging.ERROR, f"[{int(QThread.currentThreadId())}]: Failed to remove device {self.target_mac}.")
        self._disconnect_remove_command_signals()
        self.device_remove_failed_signal.emit(self.target_mac)

    def _disconnect_remove_command_signals(self):
        """Disconnect command signals to avoid multiple emissions."""
        try:
            self.command_completed_signal.disconnect(self._handle_remove_success)
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected remove command complete signals.")

        try:
            self.command_failed_signal.disconnect(self._handle_remove_failure)
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected remove command failed signals.")

        try:
            self.command_expired_signal.disconnect(self._handle_remove_failure)
        except TypeError:
            self.emit_log(logging.WARNING, f"[{int(QThread.currentThreadId())}]: Already disconnected remove command expired signals.")

    # Trust / Distrust Device
    # ==========================================================================================

    def trust(self, mac: str, timeout=2000):
        """Attempt to trust a device given its MAC address."""
        self.target_mac = mac.strip()

        # Disconnect any previous connections to avoid multiple emissions
        try:
            self.command_completed_signal.disconnect()
            self.command_failed_signal.disconnect()
            self.command_expired_signal.disconnect()
        except TypeError:
            pass
        finally:
            # Connect signals to appropriate handlers
            self.command_completed_signal.connect(self._handle_trust_success)
            self.command_failed_signal.connect(self._handle_trust_failure)
            self.command_expired_signal.connect(self._handle_trust_failure)

        self.send_command(
            command                     = f"trust {self.target_mac}", 
            expected_command_response   = self.C_TRUSTED, 
            failed_command_response     = self.C_FAILED,
            retry_intervals             = [200, 500],
            timeout                    = timeout,
        )

    def _handle_trust_success(self):
        self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Device {self.target_mac} is trusted.")
        self._disconnect_trust_command_signals()
        self.device_trust_succeeded_signal.emit(self.target_mac)

    def _handle_trust_failure(self):
        self.emit_log(logging.ERROR, f"[{int(QThread.currentThreadId())}]: Failed to distrust device {self.target_mac}.")
        self._disconnect_trust_command_signals()
        self.device_trust_failed_signal.emit(self.target_mac)

    def _disconnect_trust_command_signals(self):
        """Disconnect command signals to avoid multiple emissions."""
        try:
            self.command_completed_signal.disconnect(self._handle_trust_success)
        except TypeError:
            self.emit_log(logging.WARNING, f"Failed to disconnect \"command_completed_signal\" for trust command.")
        try:
            self.command_failed_signal.disconnect(self._handle_trust_failure)
        except TypeError:
            self.emit_log(logging.WARNING, f"Failed to disconnect \"command_failed_signal\" for trust command.")
        try:
            self.command_expired_signal.disconnect(self._handle_trust_failure)
        except TypeError:
            self.emit_log(logging.WARNING, f"Failed to disconnect \"command_expired_signal\" for trust command.")

    ######

    def distrust(self, mac: str, timeout=2000):
        """Attempt to distrust a device given its MAC address."""
        self.target_mac = mac.strip()

        # Disconnect any previous connections to avoid multiple emissions
        try:
            self.command_completed_signal.disconnect()
            self.command_failed_signal.disconnect()
            self.command_expired_signal.disconnect()
        except TypeError:
            pass
        finally:
            # Connect signals to appropriate handlers
            self.command_completed_signal.connect(self._handle_distrust_success)
            self.command_failed_signal.connect(self._handle_distrust_failure)
            self.command_expired_signal.connect(self._handle_distrust_failure)

        self.send_command(
            command                     = f"untrust {self.target_mac}", 
            expected_command_response   = self.C_DISTRUSTED, 
            failed_command_response     = self.C_FAILED,
            retry_intervals             = [200, 500],
            timeout                    = timeout,
        )

    def _handle_distrust_success(self):
        self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Device {self.target_mac} is distrusted.")
        self._disconnect_distrust_command_signals()
        self.device_distrust_succeeded_signal.emit(self.target_mac)

    def _handle_distrust_failure(self):
        self.emit_log(logging.ERROR, f"[{int(QThread.currentThreadId())}]: Failed to distrust device {self.target_mac}.")
        self._disconnect_distrust_command_signals()
        self.device_distrust_failed_signal.emit(self.target_mac)

    def _disconnect_distrust_command_signals(self):
        """Disconnect command signals to avoid multiple emissions."""
        try:
            self.command_completed_signal.disconnect(self._handle_distrust_success)
        except TypeError:
            self.emit_log(logging.WARNING, f"Failed to disconnect \"command_completed_signal\" for distrust command.")
        try:
            self.command_failed_signal.disconnect(self._handle_distrust_failure)
        except TypeError:
            self.emit_log(logging.WARNING, f"Failed to disconnect \"command_failed_signal\" for distrust command.")
        try:
            self.command_expired_signal.disconnect(self._handle_distrust_failure)
        except TypeError:
            self.emit_log(logging.WARNING, f"Failed to disconnect \"command_expired_signal\" for distrust command.")

    # Connect / Disconnect Device
    # ==========================================================================================

    def connect(self, mac: str, timeout=5000):
        """Attempt to connect to a device given its MAC address."""
        self.target_mac = mac.strip()

        # Disconnect any previous connections to avoid multiple emissions
        try:
            self.command_completed_signal.disconnect()
            self.command_failed_signal.disconnect()
            self.command_expired_signal.disconnect()
        except TypeError:
            pass
        finally:
            # Connect signals to appropriate handlers
            self.command_completed_signal.connect(self._handle_connect_success)
            self.command_failed_signal.connect(self._handle_connect_failure)
            self.command_expired_signal.connect(self._handle_connect_failure)

        self.send_command(
            command                     = f"connect {self.target_mac}", 
            expected_command_response   = self.C_CONNECTED, 
            failed_command_response     = self.C_FAILED,
            retry_intervals             = [200, 500],
            timeout                    = timeout,
        )

    def _handle_connect_success(self):
        self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Device {self.target_mac} is connected.")
        self._disconnect_connect_command_signals()
        self.device_connect_succeeded_signal.emit(self.target_mac)

    def _handle_connect_failure(self):
        self.emit_log(logging.ERROR, f"[{int(QThread.currentThreadId())}]: Failed to connect device {self.target_mac}.")
        self._disconnect_connect_command_signals()
        self.device_connect_failed_signal.emit(self.target_mac)

    def _disconnect_connect_command_signals(self):
        """Disconnect command signals to avoid multiple emissions."""
        try:
            self.command_completed_signal.disconnect(self._handle_connect_success)
        except TypeError:
            self.emit_log(logging.WARNING, f"Failed to disconnect \"command_completed_signal\" for connect command.")
        try:
            self.command_failed_signal.disconnect(self._handle_connect_failure)
        except TypeError:
            self.emit_log(logging.WARNING, f"Failed to disconnect \"command_failed_signal\" for connect command.")
        try:
            self.command_expired_signal.disconnect(self._handle_connect_failure)
        except TypeError:
            self.emit_log(logging.WARNING, f"Failed to disconnect \"command_expired_signal\" for connect command.")

    ######

    def disconnect(self, mac: str, timeout=2000):
        """Attempt to disconnect a device given its MAC address."""
        self.target_mac = mac.strip()

        # Disconnect any previous connections to avoid multiple emissions
        try:
            self.command_completed_signal.disconnect()
            self.command_failed_signal.disconnect()
            self.command_expired_signal.disconnect()
        except TypeError:
            pass
        finally:
            # Connect signals to appropriate handlers
            self.command_completed_signal.connect(self._handle_disconnect_success)
            self.command_failed_signal.connect(self._handle_disconnect_failure)
            self.command_expired_signal.connect(self._handle_disconnect_failure)

        self.send_command(
            command                     = f"disconnect {self.target_mac}", 
            expected_command_response   = self.C_DISCONNECTED, 
            failed_command_response     = self.C_FAILED,
            retry_intervals             = [200, 500],
            timeout                    = timeout,
        )

    def _handle_disconnect_success(self):
        self.emit_log(logging.INFO, f"[{int(QThread.currentThreadId())}]: Device {self.target_mac} is disconnected.")
        self._disconnect_disconnect_command_signals()
        self.device_disconnect_succeeded_signal.emit(self.target_mac)

    def _handle_disconnect_failure(self):
        self.emit_log(logging.ERROR, f"[{int(QThread.currentThreadId())}]: Failed to disconnect device {self.target_mac}.")
        self._disconnect_disconnect_command_signals()
        self.device_disconnect_failed_signal.emit(self.target_mac)

    def _disconnect_disconnect_command_signals(self):
        """Disconnect command signals to avoid multiple emissions."""
        try:
            self.command_completed_signal.disconnect(self._handle_disconnect_success)
        except TypeError:
            self.emit_log(logging.WARNING, f"Failed to disconnect \"command_completed_signal\" for disconnect command.")
        try:
            self.command_failed_signal.disconnect(self._handle_disconnect_failure)
        except TypeError:
            self
        try:
            self.command_expired_signal.disconnect(self._handle_disconnect_failure)
        except TypeError:
            self.emit_log(logging.WARNING,f"Failed to disconnect \"command_expired_signal\" for disconnect command.")


# Main Program for Testing
###########################################################################################
from PyQt5.QtWidgets import QApplication
from Qbluetoothcl_helper import BluetoothctlWrapper

if __name__ == "__main__":

    device_name = "MediBrick_BLE"
    device_pin  = 123456
    
    device_info = {
        "mac": None,
        "name": device_name,
        "paired": False,
        "trusted": False,
        "connected": False,
        "rssi": -999
    }

    app = QApplication([])

    # Create and configure the logger
    #################################

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("BluetoothctlWrapper")

    def handle_log(level, message):
        if level == logging.INFO:
            logger.info(message)
        elif level == logging.WARNING:
            logger.warning(message)
        elif level == logging.ERROR:
            logger.error(message)
        else:
            logger.log(level, message)

    # Initialize the wrapper
    ########################
    
    wrapper = BluetoothctlWrapper("bluetoothctl")


    # Connect wrapper signals to handle output and other events
    wrapper.output_ready_signal.connect(    lambda output:  print(f"MAIN: Output: {output}"))
    wrapper.error_ready_signal.connect(     lambda error:   print(f"MAIN: Error: {error}"))
    wrapper.finished_signal.connect(        lambda:         print( "MAIN: Process finished."))
    wrapper.finished_signal.connect(                        app.quit)
    wrapper.log_signal.connect(                             handle_log)

    # Single Command Example
    #########################

    # def on_startup_complete():
    #     wrapper.send_command(command="power on", 
    #                          expected_command_response = BluetoothctlWrapper.C_POWER_ON,
    #                          failed_command_response   = BluetoothctlWrapper.C_FAILED,
    #                          retry_intervals           = BluetoothctlWrapper.RETRY_INTERVALS,
    #     )

    # # Define the behavior when the command verification is complete
    # def on_command_completed():
    #     print("MAIN: Power on command successfully verified.")
    #     wrapper.stop()
        
    # # Define the behavior when the command verification fails
    # def on_command_failed():
    #     print("MAIN: Power on command verification failed.")
    #     wrapper.stop()
        
    # # Define the behavior when the command verification fails
    # def on_command_expired():
    #     print("MAIN: Power on command expired.")
    #     wrapper.stop()

    # wrapper.command_completed_signal.connect(lambda:        print( "MAIN: Command succeeded."))
    # wrapper.command_failed_signal.connect(  lambda:         print( "MAIN: Command failed."))
    # wrapper.command_expired_signal.connect( lambda:         print( "MAIN: Command expired."))

    # Multiple Commands Example
    ###########################
    #
    # This will 
    #  1 startup the bluetoothctl process
    #  2 find specified device
    #  3 obtain device info
    #  4 remove the device it its already paired
    #  5 find the device again
    #  6 obtain device infor 
    #  7 pair with the device
    #  8 connect to the device
    #  9 trust the device

    # Define the commands and expected responses
    commands = [
                "power on",
                "agent on",
                "default-agent",
                "pairable on",
                "discoverable on",
    ]
    
    expected_responses = [
        BluetoothctlWrapper.C_POWER_ON,
        BluetoothctlWrapper.C_AGENT_ON,
        BluetoothctlWrapper.C_DEFAULT_AGENT,
        BluetoothctlWrapper.C_PAIRABLE_ON,
        BluetoothctlWrapper.C_DISCOVERABLE_ON,
    ]
    failed_responses = [
        BluetoothctlWrapper.C_FAILED,
        BluetoothctlWrapper.C_FAILED,
        BluetoothctlWrapper.C_FAILED,
        BluetoothctlWrapper.C_FAILED,
        BluetoothctlWrapper.C_FAILED,
    ]

    # Define the behavior when the startup output is found
    def on_startup_complete():
        wrapper.send_multiple_commands(
            commands                   = commands, 
            expected_command_responses = expected_responses, 
            failed_command_responses   = failed_responses,
            retry_intervals            = BluetoothctlWrapper.RETRY_INTERVALS,
            timeout                    = BluetoothctlWrapper.COMMAND_TIMEOUT
        )

    def on_all_commands_processed():
        print("MAIN: All commands have been processed.")
        wrapper.find_device(device_name, scan_time=2000)

    def on_device_found(mac, name):
        print(f"MAIN: Device found - MAC: {mac}, Name: {name}")
        device_info["mac"] = mac
        device_info["name"] = name
        # You can proceed with further actions here, like pairing or connecting
        # For now, we'll stop the process
        wrapper.get_device_info(mac)

    def on_device_not_found(device):
        print(f"MAIN: Device '{device}' not found.")
        wrapper.stop()

    def on_device_info_ready(info):
        print(f"MAIN: Device info retrieved: {info}")
        device_info.update(info)
        # Proceed with further actions, e.g., pairing or connecting
        if device_info["paired"]:
            wrapper.remove(device_info["mac"], timeout=5000)
        else:
            wrapper.pair(mac=device_info["mac"], pin=device_pin, timeout=10000, scan_time=2000)

    def on_device_info_failed(mac):
        print(f"MAIN: Failed to retrieve device info for MAC: {mac}")
        wrapper.stop()

    def on_pairing_completed(mac):
        print(f"MAIN: {mac} paired.")
        # Proceed with further actions, e.g., pairing or connecting
        wrapper.connect(mac)
 
    def on_pairing_failed(mac):
        print(f"MAIN: {mac} pairing failed.")
        # Proceed with further actions, e.g., pairing or connecting
        wrapper.stop()

    def on_removing_completed(mac):
        print(f"MAIN: {mac} removed.")
        # Proceed with further actions, e.g., pairing or connecting
        wrapper.find_device(device_name, scan_time=2000)
 
    def on_removing_failed(mac):
        print(f"MAIN: {mac} removing failed.")
        # Proceed with further actions, e.g., pairing or connecting
        wrapper.stop()

    def on_connecting_completed(mac):
        print(f"MAIN: {mac} connected.")
        # Proceed with further actions, e.g., pairing or connecting
        wrapper.trust(mac)
 
    def on_connecting_failed(mac):
        print(f"MAIN: {mac} connecting failed.")
        # Proceed with further actions, e.g., pairing or connecting
        wrapper.stop()

    def on_disconnecting_completed(mac):
        print(f"MAIN: {mac} disconnected.")
        # Proceed with further actions, e.g., pairing or connecting
        wrapper.find_device(device_name, scan_time=2000)
 
    def on_disconnecting_failed(mac):
        print(f"MAIN: {mac} disconnecting failed.")
        # Proceed with further actions, e.g., pairing or connecting
        wrapper.stop()

    def on_trusting_completed(mac):
        print(f"MAIN: {mac} trusted.")
        # Proceed with further actions, e.g., pairing or connecting
        wrapper.stop()
 
    def on_trusting_failed(mac):
        print(f"MAIN: {mac} trusting failed.")
        # Proceed with further actions, e.g., pairing or connecting
        wrapper.stop()

    def on_distrusting_completed(mac):
        print(f"MAIN: {mac} distrusted.")
        # Proceed with further actions, e.g., pairing or connecting
        wrapper.stop()
 
    def on_distrusting_failed(mac):
        print(f"MAIN: {mac} distrusting failed.")
        # Proceed with further actions, e.g., pairing or connecting
        wrapper.stop()

    # Connect the signals
    wrapper.startup_completed_signal.connect(on_startup_complete)
    wrapper.all_commands_processed_signal.connect(on_all_commands_processed)

    wrapper.device_found_signal.connect(on_device_found)
    wrapper.device_not_found_signal.connect(on_device_not_found)

    wrapper.device_info_ready_signal.connect(on_device_info_ready)
    wrapper.device_info_failed_signal.connect(on_device_info_failed)

    wrapper.device_pair_succeeded_signal.connect(on_pairing_completed)
    wrapper.device_pair_failed_signal.connect(on_pairing_failed)
    wrapper.device_remove_succeeded_signal.connect(on_removing_completed)
    wrapper.device_remove_failed_signal.connect(on_removing_failed)

    wrapper.device_connect_succeeded_signal.connect(on_connecting_completed)
    wrapper.device_connect_failed_signal.connect(on_connecting_failed)
    wrapper.device_disconnect_succeeded_signal.connect(on_disconnecting_completed)
    wrapper.device_disconnect_failed_signal.connect(on_disconnecting_failed)

    wrapper.device_trust_succeeded_signal.connect(on_trusting_completed)
    wrapper.device_trust_failed_signal.connect(on_trusting_failed)
    wrapper.device_distrust_succeeded_signal.connect(on_distrusting_completed)
    wrapper.device_distrust_failed_signal.connect(on_distrusting_failed)


    # Startup the process
    wrapper.start(
        expected_startup_output = BluetoothctlWrapper.C_STARTUP_EXPECTED_OUTPUT, 
        timeout_duration        = BluetoothctlWrapper.STARTUP_TIMEOUT
    )

    app.exec_()
