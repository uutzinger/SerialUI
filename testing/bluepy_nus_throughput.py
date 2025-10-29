# bluepy_nus_throughput.py
# pip install bluepy
from bluepy import btle
import argparse, time, sys, binascii, re, os

# Default Nordic UART Service UUIDs
NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_UUID      = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # Notify (Peripheral -> Central)
NUS_TX_UUID      = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # Write/WriteNR (Central -> Peripheral)
CCCD_UUID        = "00002902-0000-1000-8000-00805f9b34fb"

def human_rate(bps):
    return f"{bps:.0f} B/s ({bps*8/1000:.1f} kbps)"

def adapter_to_iface(adapter: str|None) -> int:
    # "hci0" -> 0, "hci1" -> 1; default 0
    if not adapter:
        return 0
    m = re.match(r"^hci(\d+)$", adapter.lower())
    return int(m.group(1)) if m else 0

def build_payload(cmd: str, ending: str) -> bytes:
    endings = {"none":"", "lf":"\n", "cr":"\r", "crlf":"\r\n"}
    return (cmd + endings.get(ending.lower(), "\n")).encode("utf-8")

class RollingStats:
    def __init__(self, window=1.0):
        self.win = float(window)
        self.t0 = time.perf_counter()
        self.tw = self.t0
        self.w_bytes = 0
        self.w_pkts = 0
        self.total_bytes = 0
        self.total_pkts = 0

    def add(self, n: int):
        now = time.perf_counter()
        self.total_bytes += n
        self.total_pkts += 1
        self.w_bytes += n
        self.w_pkts += 1
        if now - self.tw >= self.win:
            dt = now - self.tw
            bps = self.w_bytes / dt if dt > 0 else 0.0
            pps = self.w_pkts / dt if dt > 0 else 0.0
            avg_roll = (self.w_bytes / self.w_pkts) if self.w_pkts else 0.0
            avg_all  = (self.total_bytes / self.total_pkts) if self.total_pkts else 0.0
            print(f"[{now - self.t0:7.2f}s] {human_rate(bps)} | {pps:.0f} pkts/s | "
                  f"avg/notify: {avg_roll:.1f} B (roll), {avg_all:.1f} B (overall)")
            self.w_bytes = 0
            self.w_pkts = 0
            self.tw = now

class NUSDelegate(btle.DefaultDelegate):
    def __init__(self, stats: RollingStats):
        super().__init__()
        self.stats = stats
    def handleNotification(self, cHandle, data: bytes):
        self.stats.add(len(data))

def resolve_by_name(name_substr: str, iface: int, scan_timeout: float):
    print(f"Scanning for device name containing '{name_substr}' …")
    sc = btle.Scanner(iface=iface)
    try:
        devs = sc.scan(scan_timeout)
    except btle.BTLEManagementError as e:
        if "Permission Denied" in str(e) or getattr(e, 'code', None) == 20:
            print("ERROR: Permission denied starting BLE scan.")
            print("Fix (no sudo run needed afterwards):")
            print("  sudo setcap 'cap_net_raw,cap_net_admin+eip' $(python3 -c \"import bluepy,os;print(os.path.join(os.path.dirname(bluepy.__file__),'bluepy-helper'))\")")
        else:
            print(f"Scan failed: {e}")
        return None

    name_sub_l = name_substr.lower()
    for d in devs:
        # Try complete and short local name AD types
        nm = (
            d.getValueText(btle.ScanEntry.COMPLETE_LOCAL_NAME) or
            d.getValueText(btle.ScanEntry.SHORT_LOCAL_NAME) or
            ""
        )
        if nm and name_sub_l in nm.lower():
            print(f"Found: {nm} [{d.addr}] RSSI={d.rssi} dBm")
            return d.addr

    print("No device found by that name.")
    return None

def find_cccd_handle(periph: btle.Peripheral, rx_char: btle.Characteristic) -> int|None:
    # Preferred: actually locate the 0x2902 descriptor
    try:
        # Restrict search within the service handle range for speed
        svc = rx_char.getDescriptors()  # bluepy returns all descs (can be empty)
        # Fallback: enumerate descriptors via service range
    except Exception:
        svc = []
    for d in rx_char.getDescriptors(forUUID=CCCD_UUID):
        return d.handle
    # Heuristic fallback: CCCD is usually char.value_handle + 1
    return rx_char.getHandle() + 1

def main():
    ap = argparse.ArgumentParser(description="NUS throughput (bluepy): subscribe to RX, send two commands, measure notify rates.")
    ap.add_argument("address", nargs="?", help="Device MAC (Linux). Omit if using --auto-name.")
    ap.add_argument("--auto-name", help="Scan for a device whose name contains this string.")
    ap.add_argument("--scan-timeout", type=float, default=6.0, help="Seconds to scan when using --auto-name.")
    ap.add_argument("--adapter", help="Adapter name (Linux) e.g., hci0.")
    ap.add_argument("--service-uuid", default=NUS_SERVICE_UUID, help="NUS service UUID override.")
    ap.add_argument("--rx-uuid", default=NUS_RX_UUID, help="RX (Notify) characteristic UUID.")
    ap.add_argument("--tx-uuid", default=NUS_TX_UUID, help="TX (Write/WriteNR) characteristic UUID.")
    ap.add_argument("--cmd1", default="scenario 20", help="First command to send.")
    ap.add_argument("--cmd2", default="resume", help="Second command to send.")
    ap.add_argument("--line-ending", choices=["none","lf","cr","crlf"], default="lf",
                    help="Line ending appended to each command (default: lf).")
    ap.add_argument("--gap", type=float, default=0.2, help="Seconds between cmd1 and cmd2.")
    ap.add_argument("--timeout", type=float, default=0.0, help="Seconds to run; 0 = until Ctrl+C.")
    ap.add_argument("--window", type=float, default=1.0, help="Rolling window seconds for rate printouts.")
    args = ap.parse_args()

    iface = adapter_to_iface(args.adapter)
    address = args.address
    if args.auto_name and not address:
        address = resolve_by_name(args.auto_name, iface, args.scan_timeout)
        if not address:
            sys.exit(1)
    if not address:
        print("Error: provide an address or use --auto-name.")
        sys.exit(2)

    svc_uuid = args.service_uuid.lower()
    rx_uuid  = args.rx_uuid.lower()
    tx_uuid  = args.tx_uuid.lower()

    print(f"Connecting to {address} …")
    p = btle.Peripheral(deviceAddr=address, iface=iface)
    stats = RollingStats(window=args.window)
    p.setDelegate(NUSDelegate(stats))

    try:
        # Resolve services and chars
        svc = p.getServiceByUUID(svc_uuid)
        rx_char = svc.getCharacteristics(rx_uuid)[0]
        tx_char = svc.getCharacteristics(tx_uuid)[0]

        # Enable notifications on RX (write 0x0100 to CCCD)
        cccd_handle = find_cccd_handle(p, rx_char)
        try:
            p.writeCharacteristic(cccd_handle, b"\x01\x00", withResponse=True)
        except btle.BTLEException:
            # Some stacks allow without response
            p.writeCharacteristic(cccd_handle, b"\x01\x00", withResponse=False)

        # Send commands
        payload1 = build_payload(args.cmd1, args.line_ending)
        payload2 = build_payload(args.cmd2, args.line_ending)
        print(f"Subscribed to RX notify: {rx_uuid}")
        print(f"Sending: {args.cmd1!r}")
        p.writeCharacteristic(tx_char.getHandle(), payload1, withResponse=False)
        time.sleep(max(0.0, args.gap))
        print(f"Sending: {args.cmd2!r}")
        p.writeCharacteristic(tx_char.getHandle(), payload2, withResponse=False)

        # Receive loop
        print("Receiving… (Ctrl+C to stop)" if args.timeout == 0 else f"Receiving for {args.timeout:.1f}s …")
        t0 = time.perf_counter()
        if args.timeout > 0:
            end = time.time() + args.timeout
            while time.time() < end:
                p.waitForNotifications(1.0)
        else:
            while True:
                p.waitForNotifications(1.0)

    except KeyboardInterrupt:
        pass
    finally:
        dur = max(1e-6, time.perf_counter() - stats.t0)
        overall_bps = stats.total_bytes / dur
        overall_avg = (stats.total_bytes / stats.total_pkts) if stats.total_pkts else 0.0
        print("\n=== SUMMARY ===")
        print(f"Duration: {dur:.2f}s")
        print(f"Total: {stats.total_bytes} bytes in {stats.total_pkts} notifications")
        print(f"Overall rate: {human_rate(overall_bps)}")
        print(f"Overall avg bytes/notification: {overall_avg:.1f} B")
        try:
            p.disconnect()
        except Exception:
            pass

if __name__ == "__main__":
    main()
