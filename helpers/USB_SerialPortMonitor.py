############################################################################################################################################
#
# USB Serial Port Monitor
# 
# Monitors USB device insertion and removal on both Windows and Linux
# Emits signal when insertion/removal event occurs
# 
# This code is maintained by Urs Utzinger
############################################################################################################################################
#
# ==============================================================================
# Configuration
# ==============================================================================
from config import ( USB_POLLING_INTERVAL,
                     PROFILEME, DEBUG_LEVEL )
# ==============================================================================
# Imports
# ==============================================================================
import logging
import platform
import time
import textwrap
#
# QT Libraries
# ----------------------------------------
try: 
    from PyQt6.QtCore import (
        Qt, QObject, QThread, pyqtSignal, pyqtSlot
    )
    ConnectionType = Qt.ConnectionType
    from PyQt6.QtSerialPort import QSerialPortInfo as _QSPI
except Exception:
    from PyQt5.QtCore import (
        Qt, QObject, QThread, pyqtSignal, pyqtSlot
    )
    ConnectionType = Qt
    try:
        from PyQt5.QtSerialPort import QSerialPortInfo as _QSPI
    except Exception:
        _QSPI = None
#
from helpers.General_helper import wait_for_signal

############################################################################################################################################
#
# QUSBMonitor interaction with Graphical User Interface
#
############################################################################################################################################
#
class QUSBMonitor(QObject):
    """
    USB Monitor class to handle USB device insertion and removal events.
    This class is designed
    """
    # Signals
    # ==========================================================================
    mtocRequest                  = pyqtSignal()                                # Signal to request mtoc (measure time of code)
    finishWorkerRequest          = pyqtSignal()                                # Signal to finish the worker
    usb_event_detected           = pyqtSignal(str)                             # Signal to communicate with the main thread
    logSignal                    = pyqtSignal(int, str)                        # Logging

    # Init
    # ==========================================================================

    def __init__(self, parent=None, ui=None):

        super().__init__(parent)
        self.instance_name = self.objectName() if self.objectName() else self.__class__.__name__
        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else -1

        self.logger = logging.getLogger(self.instance_name[:10])
        self.logger.setLevel(DEBUG_LEVEL)
        if not self.logger.handlers:
            sh = logging.StreamHandler()
            fmt = "[%(levelname)-8s] [%(name)-10s] %(message)s"
            sh.setFormatter(logging.Formatter(fmt))
            self.logger.addHandler(sh)
        self.logger.propagate = False

        self.usbThread = QThread()
        self.usbWorker = USBMonitorWorker()
        self.usbWorker.moveToThread(self.usbThread)

        # Connect signals and slots
        self.usbThread.started.connect(             self.usbWorker.run, type=ConnectionType.QueuedConnection)
        self.usbThread.started.connect(             lambda: setattr(self, "isRunning", True))
        self.usbThread.started.connect(             self.usbWorker.on_thread_debug_init, type=ConnectionType.QueuedConnection)
        self.usbThread.finished.connect(            self.usbThread.deleteLater) # delete thread at some time
        self.usbThread.finished.connect(            self._on_worker_thread_finished)
        self.usbThread.destroyed.connect(           lambda: setattr(self, "usbThread", None))

        self.usbWorker.finished.connect(            self.usbThread.quit)       # if worker emits finished quite worker thread
        self.usbWorker.finished.connect(            self.usbWorker.deleteLater) # delete worker at some time
        self.usbWorker.destroyed.connect(lambda: setattr(self, "usbWorker", None))
        self.usbWorker.usb_event_detected.connect(  self.usb_event_detected, type=ConnectionType.QueuedConnection)
        self.usbWorker.logSignal.connect(           self.on_logSignal, type=ConnectionType.QueuedConnection)

        self.mtocRequest.connect(                   self.usbWorker.on_mtocRequest, type=ConnectionType.QueuedConnection) # connect mtoc request to worker
        self.finishWorkerRequest.connect(           self.usbWorker.on_finishWorkerRequest, type=ConnectionType.QueuedConnection) # connect finish worker request to worker

        # Start the USB monitor thread
        self.isRunning = False
        self.usbThread.start()

        # Done USB monitor
        self.logger.log(logging.INFO,
            f"[{self.instance_name[:15]:<15}]: USB monitor started."
        )

    @pyqtSlot()
    def _on_worker_thread_finished(self):
        self.isRunning = False
        self.logger.log(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: USB monitor stopped."
        )        

    @pyqtSlot()
    def on_mtocRequest(self) -> None:
        """Handle mtoc request to log the time taken by the USB monitor."""
        self.mtocRequest.emit()

    @pyqtSlot(int,str)
    def on_logSignal(self, level: int, message: str) -> None:
        """pickup log messages"""
        self.logSignal.emit(level, message)

    @pyqtSlot()
    def cleanup(self) -> None:
        """Cleanup the USB monitor."""
        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Cleanup called."
        )

        # Proactively flip the loop flag so the worker exits poll loops ASAP
        worker = getattr(self, "usbWorker", None)
        if worker is not None:
            try:
                worker.running = False
            except RuntimeError:
                pass

        # Request that worker finishes
        try:
            self.finishWorkerRequest.emit()
            ok, args, reason = wait_for_signal(
                self.usbWorker.finished,
                timeout_ms = 3000,
                sender=self.usbWorker
            )
            if not ok:
                self.logSignal.emit(logging.ERROR,
                    f"[{self.instance_name[:15]:<15}]: USB Worker finish timed out because of {reason}.")
            else:
                self.logSignal.emit(logging.DEBUG,
                    f"[{self.instance_name[:15]:<15}]: USB Worker finished: {args}."
                )
        except RuntimeError:
            return

        # Terminate Thread
        try:
            usbThread = getattr(self, "usbThread", None)
            if usbThread:
                if usbThread.isRunning():
                    if not usbThread.wait(1500):
                        usbThread.quit()
                        if not usbThread.wait(1000):
                            self.logSignal.emit(logging.WARNING,
                                f"[{self.instance_name[:15]:<15}]: Thread won’t quit; terminating as last resort."
                            )
                            try: 
                                usbThread.terminate()
                                usbThread.wait(500)
                            except RuntimeError:
                                pass
        except RuntimeError:
            pass

############################################################################################################################################
#
# Worker (separate thread)
#
############################################################################################################################################

class USBMonitorWorker(QObject):
    usb_event_detected = pyqtSignal(str)                                       # Signal to communicate with the main thread
    finished           = pyqtSignal() 
    logSignal          = pyqtSignal(int, str) 

    def __init__(self):
        super().__init__()

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else -1
        self.instance_name = self.objectName() if self.objectName() else self.__class__.__name__

        self.running = False
        self.mtoc_monitor_usb = 0
        self.observer = None

        # suppress duplicate (action, device_node) events for a short window
        self.recent_events = {}                                                # dict[(action, node)] = last_time_monotonic
        self.dedupe_secs   = 0.5                                               # tune as needed

        # Debugger
        self.debug_initialized = False

    @pyqtSlot()
    def on_thread_debug_init(self) -> None:
        # Runs in worker thread when QThread’s event loop starts
        self.ensure_debugger_attached()

    def ensure_debugger_attached(self) -> None:
        """Enable debugpy tracing for this QThread (idempotent)."""
        if self.debug_initialized:
            return
        try:
            import debugpy
            debugpy.debug_this_thread()
            self.debug_initialized = True
            try:
                self.logSignal.emit(logging.DEBUG, 
                    f"[{self.instance_name[:15]:<15}]: debugpy enabled for serial worker thread."
                )
            except Exception:
                pass
        except Exception as e:
            try:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: debugpy init failed: {e}"
                )
            except Exception:
                pass

    @pyqtSlot()
    def run(self):
        try:

            self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else -1
            self.running = True

            os_type = platform.system()

            if os_type == "Linux" or os_type == "Darwin":
                self.monitor_usb_unix()
            elif os_type == "Windows":
                self.monitor_usb_windows()
            else:
                self.logSignal.emit(logging.ERROR, 
                    f"Unsupported operating system: {os_type}"
                )
        except Exception as e:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Worker run() error: {e}"
            )
        finally:
            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Finished monitoring USB."
            )
            self.finished.emit()

    def monitor_usb_unix(self) -> None:
        """
        USB device insertion/removal monitoring on Unix-like systems
        """
        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Monitoring USB on Unix-like system."
        )

        poll_ms  = int(USB_POLLING_INTERVAL if USB_POLLING_INTERVAL > 10 else USB_POLLING_INTERVAL * 1000)
        poll_ms  = min(poll_ms, 500)

        try:
            self.poll_pyudev(poll_ms)        
        except Exception as e:
            self.logSignal.emit(logging.WARNING, 
                f"[{self.instance_name[:15]:<15}]: pyudev failed: {e}; falling back to serial port polling."
            )
            self.poll_ports(poll_ms)
        
    def poll_pyudev(self, poll_ms: int) -> None:
        import pyudev
        poll_secs = poll_ms / 1000.0 if poll_ms > 10 else float(poll_ms)
        poll_secs = min(poll_secs, 0.5)

        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)

        try:
            monitor.filter_by(subsystem='tty')
        except Exception as e:
            self.logSignal.emit(logging.WARNING, 
                f"[{self.instance_name[:15]:<15}]: filter_by failed: {e}"
            )

        try:
            monitor.start()
        except Exception as e:
            # monitor.start() is optional for poll on some versions; ignore failures
            self.logSignal.emit(logging.DEBUG, 
                f"[{self.instance_name[:15]:<15}]: monitor.start() ignored: {e}"
            )

        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Monitoring USB with interval {poll_secs}s"
        )
        while self.running:
            try:
                dev = monitor.poll(timeout=poll_secs)
                if not self.running: 
                    break
                if dev is None: 
                    continue

                # Drain queued events
                while dev is not None:
                    if PROFILEME:
                        tic = time.perf_counter()

                    action = getattr(dev, "action", None) or dev.get("ACTION")
                    device_node = getattr(dev, "device_node", None) or dev.get("DEVNAME") or "<unknown>"

                    # Be strict: only “add/remove”
                    if action not in ("add", "remove"):
                        dev = monitor.poll(timeout=0)
                        continue
                    if not device_node or not str(device_node).startswith("/dev/tty"):
                        dev = monitor.poll(timeout=0)
                        continue

                    # De-duplicate bursts from udev
                    now = time.monotonic()
                    key = (action, device_node)
                    last = self.recent_events.get(key, 0.0)
                    if (now - last) < self.dedupe_secs:
                        dev = monitor.poll(timeout=0)
                        continue
                    self.recent_events[key] = now
                    # keep dict small
                    if len(self.recent_events) > 256:
                        # remove oldest-ish entries
                        for k in list(self.recent_events)[:128]:
                            self.recent_events.pop(k, None)

                    if action == 'add':
                        self.usb_event_detected.emit(f"USB device added: {device_node}")
                    elif action == 'remove':
                        self.usb_event_detected.emit(f"USB device removed: {device_node}")

                    if PROFILEME:
                        toc = time.perf_counter()
                        self.mtoc_monitor_usb = max((toc - tic), self.mtoc_monitor_usb)

                    dev = monitor.poll(timeout=0)                              # Non-blocking poll for additional events

            except Exception as e:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: poll error: {e}"
                )
                QThread.msleep(max(50, poll_ms))

    def poll_ports(self, poll_ms: int) -> None:
        """
        Basic polling fallback when pyudev is not available (Darwin or minimal Linux).
        Emits added/removed events by diffing serial ports.
        """
        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Monitoring USB with serial port polling fallback and interval {poll_ms/1000}s"
        )

        if not _QSPI:
            self.logSignal.emit(logging.WARNING, 
                f"[{self.instance_name[:15]:<15}]: QSerialPortInfo not available for fallback polling."
            )
            return
        
        try:
            def current_set():
                ports = _QSPI.availablePorts()
                # Prefer absolute system path if available (Linux/Mac), else synthesize from portName
                items = []
                for p in ports:
                    try:
                        loc = p.systemLocation()                               # Qt5/6 API
                    except Exception:
                        try:
                            loc = "/dev/" + p.portName()
                        except Exception:
                            loc = p.portName()                                 # Windows: COMx
                    items.append(loc)
                return set(items)
        except Exception as e:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: QtSerialPort polling init failed: {e}"
            )
            return False

        try:
            prev = current_set()
            while self.running:
                if PROFILEME:
                    tic = time.perf_counter()

                now = current_set()
                added = now - prev
                removed = prev - now

                for dev in sorted(added):
                    self.usb_event_detected.emit(f"USB device added: {dev}")
                for dev in sorted(removed):
                    self.usb_event_detected.emit(f"USB device removed: {dev}")

                prev = now

                if PROFILEME:
                    toc = time.perf_counter()
                    self.mtoc_monitor_usb = max((toc - tic), self.mtoc_monitor_usb)

                QThread.msleep(max(50, poll_ms))
        except Exception as e:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: QtSerialPort polling error: {e}"
            )

    def monitor_usb_windows(self) -> None:
        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Monitoring usb on Windows."
        )

        poll_ms  = int(USB_POLLING_INTERVAL if USB_POLLING_INTERVAL > 10 else USB_POLLING_INTERVAL * 1000)
        poll_ms  = min(poll_ms, 500)

        try:
            import wmi
        except Exception as e:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: wmi module not available: {e}"
            )
            self.finished.emit()
            return        
        c = wmi.WMI()

        try:
            watchers = {
                "add": c.Win32_PnPEntity.watch_for(notification_type="Creation", delay_secs=0.2),
                "remove": c.Win32_PnPEntity.watch_for(notification_type="Deletion", delay_secs=0.2)
            }
        except Exception as e:
            self.logSignal.emit(logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Error setting up USB monitor: {e}"
            )
            return

        while self.running:
            if PROFILEME:
                tic = time.perf_counter()

            try:
                for action, watcher in watchers.items():
                    if not self.running:                                       # Early exit check
                        break

                    event = watcher(timeout_ms=poll_ms)                        # Wait for an event
                    if event and ('USB' in event.Description or 'COM' in event.Name):
                        message = f"USB device {'added' if action == 'add' else 'removed'}: {event.Description} ({event.Name})"
                        self.usb_event_detected.emit(message)

            except wmi.x_wmi_timed_out:
                continue                                                       # No event, continue waiting

            except Exception as e:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Error: {e}"
                )

            if PROFILEME:
                toc = time.perf_counter()
                self.mtoc_monitor_usb = max((toc - tic), self.mtoc_monitor_usb) # End performance tracking
        
    def stop(self):
        """Stop the worker safely."""

        self.running = False

        # Windows: Force an event to break `watch_for()`
        if platform.system() == "Windows":
            try:
                import wmi
                c = wmi.WMI()
                c.Win32_PnPEntity.watch_for(notification_type="Creation", delay_secs=0.1) # Force an event
            except Exception as e:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: Error forcing USB update: {e}."
                )

        if hasattr(self, "observer") and self.observer:
            try:
                self.observer.stop()
            except Exception:
                pass
            finally:
                self.observer = None

    @pyqtSlot()
    def on_mtocRequest(self) -> None:
        """Emit the mtoc signal with a function name and time in a single log call."""
        log_message = textwrap.dedent(f"""
            USB Monitor
            =============================================================
            monitor_usb             took {self.mtoc_monitor_usb*1000:.2f} ms.
        """)
        self.logSignal.emit(-1, log_message)
        self.mtoc_monitor_usb = 0.

    @pyqtSlot()
    def on_finishWorkerRequest(self) -> None:
        """Handle finish worker request."""
        self.logSignal.emit(logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Finish worker request received"
        )
        self.stop()
        # self.finished.emit()  # Emit finished signal to stop the thread
