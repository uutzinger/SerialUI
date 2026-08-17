import asyncio
import sys
import types
import unittest
from concurrent.futures import Future
from types import SimpleNamespace


if "bleak" not in sys.modules:
    bleak = types.ModuleType("bleak")
    bleak.BleakClient = type("BleakClient", (), {})
    bleak.BleakScanner = type("BleakScanner", (), {})
    bleak.BleakError = type("BleakError", (Exception,), {})
    device = types.ModuleType("bleak.backends.device")
    device.BLEDevice = type("BLEDevice", (), {})
    sys.modules.update({
        "bleak": bleak,
        "bleak.backends": types.ModuleType("bleak.backends"),
        "bleak.backends.device": device,
    })

from helpers.General_helper import connect
from helpers.QBLE_helper import BleakWorker
from helpers.Qserial_helper import Serial

graph = types.ModuleType("helpers.Qgraph_helper")
graph.QChart = type("QChart", (), {})
sys.modules.setdefault("helpers.Qgraph_helper", graph)
from SerialUI import mainWindow

try:
    from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
except ImportError:
    from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot


class FakeBleClient:
    def __init__(self):
        self.is_connected = True
        self.start_calls = 0
        self.stop_calls = 0

    async def start_notify(self, _characteristic, _callback):
        self.start_calls += 1

    async def stop_notify(self, _characteristic):
        self.stop_calls += 1


class ReconnectClient(FakeBleClient):
    def __init__(self):
        super().__init__()
        self.is_connected = False
        self.mtu_size = 247
        self._backend = object()
        characteristic = object()
        service = SimpleNamespace(get_characteristic=lambda _uuid: characteristic)
        self.services = SimpleNamespace(get_service=lambda _uuid: service)

    async def connect(self, timeout):
        self.is_connected = True


class ControlledBleWorker(BleakWorker):
    def __init__(self):
        super().__init__()
        self.client = FakeBleClient()
        self.char_tx = object()
        self.pending = []

    def schedule(self, coroutine):
        future = Future()
        self.pending.append((coroutine, future))
        return future

    def complete_next(self):
        coroutine, future = self.pending.pop(0)
        try:
            asyncio.run(coroutine)
        except Exception as error:
            future.set_exception(error)
        else:
            future.set_result(None)


class Producer(QObject):
    received = pyqtSignal(bytearray)


class Consumer(QObject):
    def __init__(self):
        super().__init__()
        self.calls = 0

    @pyqtSlot(bytearray)
    def receive(self, _data):
        self.calls += 1


class FakeSerialPort(QObject):
    readyRead = pyqtSignal()

    def isOpen(self):
        return True

    def clear(self, _directions):
        return True

    def readAll(self):
        return b""

    def flush(self):
        return True


class SignalBus(QObject):
    sendFileRequest = pyqtSignal(object)
    sendTextRequest = pyqtSignal(bytes)
    sendLineRequest = pyqtSignal(bytes)
    sendLinesRequest = pyqtSignal(list)
    rxStartRequest = pyqtSignal()
    rxStopRequest = pyqtSignal()
    throughputStartRequest = pyqtSignal()
    throughputStopRequest = pyqtSignal()


class FakeTransport(QObject):
    sendFileRequest = pyqtSignal(object)
    sendTextRequest = pyqtSignal(bytes)
    sendLineRequest = pyqtSignal(bytes)
    sendLinesRequest = pyqtSignal(list)
    startTransceiverRequest = pyqtSignal()
    stopTransceiverRequest = pyqtSignal()
    startThroughputRequest = pyqtSignal()
    stopThroughputRequest = pyqtSignal()

    textLineTerminator = b"\n"

    def connect_receivedLines(self, _slot):
        pass

    def connect_receivedData(self, _slot):
        pass

    def disconnect_receivedLines(self, _slot):
        pass

    def disconnect_receivedData(self, _slot):
        pass

    def on_receivedLines(self, _lines):
        pass

    def on_receivedData(self, _data):
        pass


class FakeWidget:
    def setText(self, _text):
        pass

    def setEnabled(self, _enabled):
        pass


class BleLifecycleTests(unittest.TestCase):
    def test_repeated_start_schedules_one_subscription(self):
        worker = ControlledBleWorker()
        worker.start_transceiver()
        worker.start_transceiver()

        self.assertEqual(len(worker.pending), 1)
        self.assertEqual(worker.notification_state, worker.NOTIFY_STARTING)
        worker.complete_next()
        self.assertEqual(worker.client.start_calls, 1)
        self.assertEqual(worker.notification_state, worker.NOTIFY_STARTED)

    def test_stop_during_start_settles_stopped(self):
        worker = ControlledBleWorker()
        worker.start_transceiver()
        worker.stop_transceiver()
        worker.complete_next()

        self.assertEqual(worker.notification_state, worker.NOTIFY_STOPPING)
        worker.complete_next()
        self.assertEqual(worker.client.start_calls, 1)
        self.assertEqual(worker.client.stop_calls, 1)
        self.assertEqual(worker.notification_state, worker.NOTIFY_STOPPED)

    def test_start_during_stop_restarts_once(self):
        worker = ControlledBleWorker()
        worker.start_transceiver()
        worker.complete_next()
        worker.stop_transceiver()
        worker.start_transceiver()
        worker.complete_next()

        self.assertEqual(worker.notification_state, worker.NOTIFY_STARTING)
        worker.complete_next()
        self.assertEqual(worker.client.start_calls, 2)
        self.assertEqual(worker.client.stop_calls, 1)
        self.assertEqual(worker.notification_state, worker.NOTIFY_STARTED)

    def test_stale_start_cannot_mark_new_connection_started(self):
        worker = ControlledBleWorker()
        old_client = worker.client
        worker.start_transceiver()
        worker._reset_notification_state(preserve_wanted=True)
        worker.client = FakeBleClient()
        worker.char_tx = object()
        worker.start_transceiver()

        worker.complete_next()
        self.assertEqual(old_client.start_calls, 1)
        self.assertEqual(worker.notification_state, worker.NOTIFY_STARTING)
        worker.complete_next()
        self.assertEqual(worker.client.start_calls, 1)
        self.assertEqual(worker.notification_state, worker.NOTIFY_STARTED)

    def test_reconnect_uses_guarded_subscription_once(self):
        worker = ControlledBleWorker()
        worker.client = ReconnectClient()
        worker.device = SimpleNamespace(name="device")
        worker.reconnect = True
        worker.notification_wanted = True

        asyncio.run(worker._handle_reconnection())
        self.assertEqual(len(worker.pending), 1)
        self.assertEqual(worker.notification_state, worker.NOTIFY_STARTING)
        worker.complete_next()
        self.assertEqual(worker.client.start_calls, 1)


class SignalConnectionTests(unittest.TestCase):
    def test_consumers_each_receive_once_after_duplicate_connect_attempts(self):
        producer = Producer()
        terminal = Consumer()
        plotter = Consumer()

        for consumer in (terminal, plotter):
            self.assertTrue(connect(producer.received, consumer.receive, unique=True))
            self.assertTrue(connect(producer.received, consumer.receive, unique=True))

        producer.received.emit(bytearray(b"one notification"))
        self.assertEqual(terminal.calls, 1)
        self.assertEqual(plotter.calls, 1)

    def test_repeated_serial_start_retains_one_ready_read_connection(self):
        worker = Serial()
        worker.QSer = FakeSerialPort()
        calls = []
        worker.on_dataReady = lambda: calls.append(True)

        worker.on_startTransceiverRequest()
        worker.on_startTransceiverRequest()
        worker.QSer.readyRead.emit()
        self.assertEqual(len(calls), 1)

        worker.on_stopTransceiverRequest()
        worker.on_stopTransceiverRequest()
        worker.QSer.readyRead.emit()
        self.assertEqual(len(calls), 1)

    def test_repeated_ble_ready_starts_new_transport_once(self):
        bus = SignalBus()
        ble = FakeTransport()
        context = SimpleNamespace(
            ble=ble,
            receiverDemandActive=True,
            txrxReady_wired_to_ble=False,
            textLineTerminator=b"",
            instance_name="test",
            handle_log=lambda *_args: None,
        )
        for name in (
            "sendFileRequest", "sendTextRequest", "sendLineRequest",
            "sendLinesRequest", "rxStartRequest", "rxStopRequest",
            "throughputStartRequest", "throughputStopRequest",
        ):
            setattr(context, name, getattr(bus, name))

        starts = []
        ble.startTransceiverRequest.connect(lambda: starts.append(True))
        mainWindow.update_sendreceive_targets_ble(context, True)
        mainWindow.update_sendreceive_targets_ble(context, True)
        self.assertEqual(len(starts), 1)

        mainWindow.update_sendreceive_targets_ble(context, False)
        mainWindow.update_sendreceive_targets_ble(context, True)
        self.assertEqual(len(starts), 2)

    def test_aggregate_demand_emits_only_on_transitions(self):
        bus = SignalBus()
        context = SimpleNamespace(
            serial=FakeTransport(),
            ble=FakeTransport(),
            chart=object(),
            ui=SimpleNamespace(
                pushButton_ReceiverStartStop=FakeWidget(),
                lineEdit_Text=FakeWidget(),
                pushButton_SendFile=FakeWidget(),
            ),
            isMonitoring=False,
            isPlotting=False,
            receiverDemandActive=False,
            txrxReady_wired_to_serial=True,
            txrxReady_wired_to_ble=True,
            instance_name="test",
            handle_log=lambda *_args: None,
        )
        context.sender = lambda: context
        context.rxStartRequest = bus.rxStartRequest
        context.rxStopRequest = bus.rxStopRequest
        context.throughputStartRequest = bus.throughputStartRequest
        context.throughputStopRequest = bus.throughputStopRequest
        starts, stops = [], []
        bus.rxStartRequest.connect(lambda: starts.append(True))
        bus.rxStopRequest.connect(lambda: stops.append(True))

        mainWindow.handle_ReceiverRunning(context, True)
        mainWindow.handle_ReceiverRunning(context, True)
        mainWindow.handle_ReceiverRunning(context, False)
        mainWindow.handle_ReceiverRunning(context, False)
        self.assertEqual((len(starts), len(stops)), (1, 1))

if __name__ == "__main__":
    unittest.main()
