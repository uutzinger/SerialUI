# ble_nus_throughput.py
# pip install bleak
import asyncio, time, argparse, sys
from bleak import BleakClient, BleakScanner

# Standard Nordic UART Service UUIDs
NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_UUID      = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # Notify (Peripheral -> Central)
NUS_TX_UUID      = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # Write/WriteNR (Central -> Peripheral)

def human_rate(bps):
    return f"{bps:.0f} B/s ({bps*8/1000:.1f} kbps)"

class RollingStats:
    def __init__(self, window=1.0):
        self.win = float(window)
        self.t0 = time.perf_counter()
        self.tw = self.t0
        self.w_bytes = 0
        self.w_pkts = 0
        self.total_bytes = 0
        self.total_pkts = 0

    def add(self, nbytes: int):
        now = time.perf_counter()
        self.total_bytes += nbytes
        self.total_pkts += 1
        self.w_bytes += nbytes
        self.w_pkts += 1

        out = None
        dtw = now - self.tw
        if dtw >= self.win:
            bps = self.w_bytes / dtw if dtw > 0 else 0.0
            pps = self.w_pkts / dtw if dtw > 0 else 0.0
            avg_per_notif = (self.w_bytes / self.w_pkts) if self.w_pkts else 0.0
            out = (now - self.t0, bps, pps, avg_per_notif)
            self.w_bytes = 0
            self.w_pkts = 0
            self.tw = now
        return out

async def resolve_address(name_or_addr: str, timeout: float = 6.0):
    # If it looks like an address (has colons or is a UUID), return as-is; else scan by name substring
    s = name_or_addr.strip()
    if ":" in s or len(s) > 20:
        return s
    print(f"Scanning for device name containing '{s}' …")
    devs = await BleakScanner.discover(timeout=timeout)
    for d in devs:
        if d.name and s.lower() in d.name.lower():
            print(f"Found: {d.name} [{d.address}]")
            return d.address
    print("No device found by that name.")
    return None

def build_payload(cmd: str, line_ending: str) -> bytes:
    endings = {"none": "", "lf": "\n", "cr": "\r", "crlf": "\r\n"}
    suffix = endings.get(line_ending.lower(), "\n")
    return (cmd + suffix).encode("utf-8")

async def main(args):
    address = args.address
    if args.auto_name:
        addr = await resolve_address(args.auto_name, timeout=args.scan_timeout)
        if not addr:
            sys.exit(1)
        address = addr
    if not address:
        print("Error: provide an address or use --auto-name to find by name.")
        sys.exit(2)

    rx_uuid = (args.rx_uuid or NUS_RX_UUID).lower()
    tx_uuid = (args.tx_uuid or NUS_TX_UUID).lower()
    svc_uuid = (args.service_uuid or NUS_SERVICE_UUID).lower()

    print(f"Connecting to {address} …")
    client = BleakClient(address, adapter=args.adapter) if args.adapter else BleakClient(address)
    stats = RollingStats(window=args.window)

    # state shared with callback
    done_event = asyncio.Event()

    def on_notify(_, data: bytearray):
        out = stats.add(len(data))
        if out:
            elapsed, bps, pps, avg = out
            overall_avg = (stats.total_bytes / stats.total_pkts) if stats.total_pkts else 0.0
            print(f"[{elapsed:7.2f}s] {human_rate(bps)} | {pps:.0f} pkts/s | "
                  f"avg/notify: {avg:.1f} B (roll), {overall_avg:.1f} B (overall)")

    t_start = time.perf_counter()
    try:
        async with client:
            print("Connected.")
            svcs = await client.get_services()
            # Try to sanity-check presence of NUS service & chars
            service = svcs.get_service(svc_uuid) if svc_uuid else None
            if not service:
                # fallback: try to locate any service that has both a Notify and a Write char
                cand_rx, cand_tx = None, None
                for s in svcs:
                    rx = [c for c in s.characteristics if "notify" in c.properties]
                    tx = [c for c in s.characteristics if ("write" in c.properties or "write-without-response" in c.properties)]
                    if rx and tx:
                        cand_rx = rx[0]; cand_tx = tx[0]; service = s; break
                if cand_rx and cand_tx:
                    rx_uuid = cand_rx.uuid
                    tx_uuid = cand_tx.uuid
                    print(f"Warning: NUS service not found, using first Notify/Write pair on service {service.uuid}")
                else:
                    print("Error: Could not find a suitable Notify/Write characteristic pair.")
                    return
            else:
                # verify RX and TX on that service
                uuids = [c.uuid.lower() for c in service.characteristics]
                if rx_uuid not in uuids or tx_uuid not in uuids:
                    print("Warning: Provided RX/TX UUIDs not both present on the NUS service; attempting to locate by properties.")
                    rx_cands = [c for c in service.characteristics if "notify" in c.properties]
                    tx_cands = [c for c in service.characteristics if ("write" in c.properties or "write-without-response" in c.properties)]
                    if rx_cands: rx_uuid = rx_cands[0].uuid
                    if tx_cands: tx_uuid = tx_cands[0].uuid

            # Start notifications
            await client.start_notify(rx_uuid, on_notify)
            print(f"Subscribed to RX notify: {rx_uuid}")

            # Send commands
            p1 = build_payload(args.cmd1, args.line_ending)
            p2 = build_payload(args.cmd2, args.line_ending)

            # Prefer Write Without Response when available for speed
            # Bleak chooses automatically based on properties; we just set response=False to hint.
            print(f"Sending: {args.cmd1!r}")
            await client.write_gatt_char(tx_uuid, p1, response=False)
            await asyncio.sleep(args.gap)  # small gap between commands
            print(f"Sending: {args.cmd2!r}")
            await client.write_gatt_char(tx_uuid, p2, response=False)

            # Run until timeout or Ctrl+C
            if args.timeout > 0:
                try:
                    await asyncio.wait_for(done_event.wait(), timeout=args.timeout)
                except asyncio.TimeoutError:
                    pass
            else:
                try:
                    while True:
                        await asyncio.sleep(1)
                except asyncio.CancelledError:
                    pass
                except KeyboardInterrupt:
                    pass

            await client.stop_notify(rx_uuid)

    except KeyboardInterrupt:
        pass
    finally:
        dur = max(1e-6, time.perf_counter() - t_start)
        overall_bps = stats.total_bytes / dur
        overall_avg = (stats.total_bytes / stats.total_pkts) if stats.total_pkts else 0.0
        print("\n=== SUMMARY ===")
        print(f"Duration: {dur:.2f}s")
        print(f"Total: {stats.total_bytes} bytes in {stats.total_pkts} notifications")
        print(f"Overall rate: {human_rate(overall_bps)}")
        print(f"Overall avg bytes/notification: {overall_avg:.1f} B")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="NUS throughput: subscribe to RX, send two commands, measure notify rates.")
    ap.add_argument("address", nargs="?", help="Device MAC/Addr (Linux), or UUID (macOS/Windows). Omit if using --auto-name.")
    ap.add_argument("--auto-name", help="Instead of address, scan for a device whose name contains this string.")
    ap.add_argument("--scan-timeout", type=float, default=6.0, help="Seconds to scan when using --auto-name.")
    ap.add_argument("--adapter", help="Adapter name (Linux) e.g., hci0.")
    ap.add_argument("--service-uuid", default=NUS_SERVICE_UUID, help="NUS service UUID (optional override).")
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
    asyncio.run(main(args))
