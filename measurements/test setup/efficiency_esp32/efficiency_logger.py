"""
efficiency_logger.py -- laptop side of efficiency_esp32.ino

  capture  stream CSV rows to measurements/efficiency/<timestamp>_<label>.csv (+ .log)
  dump     save the ESP32's flash log to measurements/efficiency/<timestamp>_flash_dump.csv
  cmd      send one command (info, erase, pause, resume, help) and print the reply

Run from the repo root with the venv active:
  python "measurements/test setup/efficiency_esp32/efficiency_logger.py" capture COM5 series_16ohm
  python "measurements/test setup/efficiency_esp32/efficiency_logger.py" dump COM5
  python "measurements/test setup/efficiency_esp32/efficiency_logger.py" cmd COM5 erase
List ports: python -m serial.tools.list_ports

While the PCB is powered, connect through a USB cable with VBUS cut (see the sketch header).
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import serial

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "measurements" / "efficiency"
BAUD = 115200


def open_port(port):
    ser = serial.serial_for_url(port, do_not_open=True)
    ser.baudrate = BAUD
    ser.timeout = 1.0
    # Keep DTR/RTS deasserted so opening the port does not reset the ESP32 through the
    # Feather's auto-reset circuit (a reset mid-sweep starts a new run).
    ser.dtr = False
    ser.rts = False
    ser.open()
    return ser


def read_line(ser):
    """Return a stripped line, "" for a blank line, or None on timeout."""
    raw = ser.readline()
    if not raw:
        return None
    return raw.decode("ascii", errors="replace").strip()


def send(ser, command):
    ser.write((command + "\n").encode("ascii"))
    ser.flush()


def capture(ser, csv_file, log_file):
    """Write data rows until Ctrl+C. Returns the number of rows written."""
    send(ser, "header")
    header = None
    rows = 0
    t0 = time.monotonic()
    try:
        while True:
            line = read_line(ser)
            if not line:
                continue
            pc_t = time.monotonic() - t0
            if line.startswith("#"):
                print(line)
                log_file.write(f"{pc_t:.1f} {line}\n")
                log_file.flush()
            elif line.startswith("run,"):
                if header is None:
                    header = line
                    csv_file.write(header + ",pc_time_s\n")
                elif line != header:
                    print("WARNING: sketch CSV header changed; start a new capture file.")
            elif header is not None:
                if line.count(",") != header.count(","):
                    log_file.write(f"{pc_t:.1f} # skipped malformed row: {line}\n")
                    continue
                csv_file.write(f"{line},{pc_t:.2f}\n")
                csv_file.flush()
                rows += 1
    except KeyboardInterrupt:
        pass
    return rows


def dump(ser, out_file, start_timeout_s=10.0, idle_timeout_s=5.0):
    """Copy the flash log between #BEGIN_DUMP and #END_DUMP. Returns (rows, runs)."""
    ser.reset_input_buffer()
    send(ser, "dump")

    deadline = time.monotonic() + start_timeout_s
    expected = None
    while expected is None:
        line = read_line(ser)
        if line and line.startswith("#BEGIN_DUMP"):
            expected = int(line.split("bytes=")[1])
        elif time.monotonic() > deadline:
            sys.exit("No #BEGIN_DUMP reply. Is the sketch running on this port?")

    received = 0
    rows = 0
    runs = set()
    last_data = time.monotonic()
    while True:
        line = read_line(ser)
        if line is None:
            if time.monotonic() - last_data > idle_timeout_s:
                sys.exit(f"Dump stalled after {received} of {expected} bytes; file is incomplete.")
            continue
        last_data = time.monotonic()
        if line == "#END_DUMP":
            break
        out_file.write(line + "\n")
        received += len(line) + 1
        if line and not line.startswith("run,"):
            runs.add(line.split(",", 1)[0])
            rows += 1

    if received != expected:
        print(f"WARNING: received {received} bytes, sketch reported {expected}.")
    return rows, sorted(runs, key=int)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p_cap = sub.add_parser("capture")
    p_cap.add_argument("port")
    p_cap.add_argument("label", help="load scenario, e.g. series_16ohm")
    p_dump = sub.add_parser("dump")
    p_dump.add_argument("port")
    p_cmd = sub.add_parser("cmd")
    p_cmd.add_argument("port")
    p_cmd.add_argument("command", choices=["info", "erase", "pause", "resume", "help"])
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    if args.action == "capture":
        csv_path = OUT_DIR / f"{stamp}_{args.label}.csv"
        with open_port(args.port) as ser, \
                open(csv_path, "w", newline="") as csv_file, \
                open(csv_path.with_suffix(".log"), "w") as log_file:
            log_file.write(f"# capture start {datetime.now().isoformat(timespec='seconds')} "
                           f"port={args.port} label={args.label}\n")
            print(f"Writing {csv_path}  (Ctrl+C to stop)")
            rows = capture(ser, csv_file, log_file)
        print(f"Saved {rows} rows to {csv_path}")

    elif args.action == "dump":
        path = OUT_DIR / f"{stamp}_flash_dump.csv"
        with open_port(args.port) as ser, open(path, "w", newline="") as out_file:
            rows, runs = dump(ser, out_file)
        print(f"Saved {rows} rows (runs {', '.join(runs) or 'none'}) to {path}")
        print("Check the file, then 'cmd <port> erase'. Flash logging stays paused until "
              "'cmd <port> resume' or a reboot.")

    elif args.action == "cmd":
        with open_port(args.port) as ser:
            send(ser, args.command)
            end = time.monotonic() + 2.0
            while time.monotonic() < end:
                line = read_line(ser)
                if line and line.startswith("#"):
                    print(line)


if __name__ == "__main__":
    main()
