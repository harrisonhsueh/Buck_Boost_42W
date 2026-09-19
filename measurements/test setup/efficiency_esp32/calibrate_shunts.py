"""
calibrate_shunts.py -- calibrate INA226 current channels against a DMM in series

  run  take calibration points interactively
  fit  print the fit from saved point files

Run from the repo root with the venv active (efficiency_esp32.ino on the board, VBUS-cut cable):
  python "measurements/test setup/efficiency_esp32/calibrate_shunts.py" run COM5 in
  python "measurements/test setup/efficiency_esp32/calibrate_shunts.py" run COM5 fan12 fan1
  python "measurements/test setup/efficiency_esp32/calibrate_shunts.py" run COM5 fan12 --dmm-also b5in
  python "measurements/test setup/efficiency_esp32/calibrate_shunts.py" fit measurements/efficiency/*_shunt_cal_*.csv

Every channel listed after the port must carry exactly the DMM current. If the DMM also carries
current that another INA226 measures (e.g. DMM in the 12 V output before the 5 V buck tap), name
that channel with --dmm-also; its reading is subtracted from the DMM value before fitting.
For point files recorded without that, append ::<channels> to the file name when fitting,
e.g.  some_shunt_cal_fan12.csv::b5in

Each point: set up the supply, load and DMM range; the script opens the port, sends an optional
sketch command (e.g. "pwm 60"), skips ~3 s of settling, then averages ~8 s of INA226 rows while
you watch the DMM. Type the DMM reading afterwards. The port is closed between points, so the
board can be power-cycled to move DMM leads.

Every point (DMM value plus the mean of every logged column) is saved to
measurements/efficiency/<timestamp>_shunt_cal_<channels>.csv as it is taken. The fit, per channel,
    I_true = gain * I_nominal + offset       (I_nominal = the sketch's <ch>_A, nominal shunt)
is reprinted after every point. plot_efficiency.py --cal <files> applies it. Point files from
several sessions can be combined; each channel is fitted from every point that lists it.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import serial

from efficiency_logger import OUT_DIR, open_port, read_line, send

NOMINAL_SHUNT_OHMS = {"in": 0.001, "fan12": 0.001, "b5in": 0.033, "b5out": 0.010,
                      **{f"fan{k}": 0.010 for k in range(1, 11)}}
# Virtual channel: sum of all ten per-fan channels. Fitted from every point whose DMM carried the
# whole fan-rail current (points listing fan12), however the fans were split across headers.
# Preferred output reference: the 1 mOhm fan12 reading depends on how current is fed to the shunt
# pads. On 2026-09-15 a DMM wired to only one of the two parallel jumper sets ahead of the shunt
# shifted fan12 by 2.6 % relative to the per-fan 10 mOhm shunts (1.051 vs 1.077 in normal runs);
# wired to both sets it matched (1.080). The per-fan sum's gain agreed to 0.1 % in both sessions.
FANSUM_CHANNELS = [f"fan{k}" for k in range(1, 11)]
FANSUM_SHUNT_OHMS = 0.010
INA226_SHUNT_LSB_V = 2.5e-6
SETTLE_ROWS = 10        # ~3.4 s skipped after the port opens or a sketch command
AVERAGE_ROWS = 24       # ~8 s averaged; read the DMM during this window
MAX_TIMEOUTS = 5        # consecutive 1 s serial timeouts before giving up on a point
DMM_WEIGHT_PCT = 0.5    # assumed DMM proportional error; only weights the fit, not a spec
MAX_GAIN_DEVIATION = 0.25  # fits further than this from gain 1 are reported but never applied
RANGE_UNITS = {"400ma": "ma", "10a": "a", "none": "a"}  # unit assumed when none is typed

PLAN_INPUT = """
Input shunt ('in'): DMM in series from the bench supply + lead to the board input.
  Opening this circuit removes board power: turn the supply OFF before moving leads or
  changing the DMM range. Each point reopens the port, so the ESP32 rebooting is fine.
  The calibration doesn't depend on Vin; Vin only sets which current you get. The board idles
  at ~0.7 W (measured at 5 V), so the lowest input current is roughly 0.7 W / Vin.
  Suggested points with the 3 fans connected (aim near these; exact values don't matter):
    400mA range   20 V, pwm 0     ~40 mA
                  20 V, pwm 60    ~140 mA
                  20 V, pwm 100   ~330 mA
    10A range     20 V, pwm 100   ~330 mA again (checks the two DMM ranges agree)
                  5 V,  pwm 100   ~1.35 A
                  8 ohm on the fan rail, pwm 0, lower Vin until the supply shows ~3 A (~6.5-7 V)
"""

PLAN_FAN_RAIL = """
Fan-rail shunt ('fan12', plus the per-fan channel of the header you use, e.g. 'fan1'):
  DMM in series with the load on ONE header, nothing else on the fan rail, so the DMM carries
  the whole fan-rail current. Remove the load before changing the DMM range (board can stay on).
  Only list a per-fan channel if ALL the DMM current goes through that one header. If the DMM
  sits in the 12 V output before the 5 V buck tap, it also carries the 5 V buck input: add
  --dmm-also b5in.
  Suggested points:
    none range    nothing connected, enter 0            pins the offset
    400mA range   one fan, pwm 40 / pwm 70 / pwm 100    ~25 / ~70 / ~150 mA
    10A range     one fan, pwm 100                      ~150 mA again (range check)
                  16 ohm ~0.75 A, 8 ohm ~1.5 A, 4 ohm ~3.0 A (4 ohm needs ~40 W in: use 20 V)
  Resistor points through a header put up to 3 A (90 mW) through that header's 10 mOhm shunt
  and connector. If that's too much for them, connect the resistor to the fan rail after the
  1 mOhm shunt and take those points in a separate 'run COM5 fan12' session.
"""


def parse_dmm(text, range_name):
    """'150.2', '150.2mA', '0.1502 A', or a fluctuating display as '148.2..151.0'.
    Returns (value_A, resolution_A, half_spread_A); resolution comes from the decimals typed."""
    t = text.strip().lower().replace(" ", "")
    unit = RANGE_UNITS[range_name]
    if t.endswith("ma"):
        unit, t = "ma", t[:-2]
    elif t.endswith("a"):
        unit, t = "a", t[:-1]
    scale = 1e-3 if unit == "ma" else 1.0
    parts = t.split("..")
    if len(parts) > 2 or not all(parts):
        raise ValueError(text)
    nums = [float(p) for p in parts]
    decimals = max(len(p.split(".")[1]) if "." in p else 0 for p in parts)
    resolution = 0.0 if range_name == "none" else 10.0 ** (-decimals) * scale
    return float(np.mean(nums)) * scale, resolution, (max(nums) - min(nums)) / 2 * scale


def collect_point(ser, channels, command=None, settle_rows=SETTLE_ROWS, average_rows=AVERAGE_ROWS):
    """Skip settle_rows data rows, then return the next average_rows flag-free rows as a DataFrame."""
    send(ser, "header")
    if command:
        send(ser, command)
    header, rows, seen, timeouts = None, [], 0, 0
    while len(rows) < average_rows:
        line = read_line(ser)
        if line is None:
            timeouts += 1
            if timeouts >= MAX_TIMEOUTS:
                raise RuntimeError("no data from the ESP32")
            continue
        timeouts = 0
        if not line:
            continue
        if line.startswith("#"):
            if "ERROR" in line or "boot" in line or "refused" in line or line.startswith("# fans"):
                print(f"\n  {line}")
            continue
        if line.startswith("run,"):
            header = line.split(",")
            continue
        values = line.split(",")
        if header is None or len(values) != len(header):
            continue
        row = {h: (float(v) if v != "" else np.nan) for h, v in zip(header, values)}
        seen += 1
        if seen > settle_rows and row["flags"] == 0:
            rows.append(row)
        live = "  ".join(f"{ch} {row.get(f'{ch}_A', np.nan):.4f} A" for ch in channels)
        state = "settling" if seen <= settle_rows else f"averaging {len(rows)}/{average_rows}"
        print(f"\r  {state:16s} {live}   ", end="", flush=True)
    print()
    return pd.DataFrame(rows)


def summarize(data):
    """Mean of every numeric column, plus std of each *_A column."""
    rec = {c: data[c].mean() for c in data.columns
           if c.endswith(("_A", "_uV", "_V", "_rpm")) or c == "pwm_pct"}
    rec.update({f"{c}_std": data[c].std() for c in data.columns if c.endswith("_A")})
    rec["n_rows"] = len(data)
    return rec


def dmm_minus_also(points):
    """DMM current minus the channels listed in dmm_also (current that bypasses the fitted shunt)."""
    ref = points["dmm_A"].copy()
    if "dmm_also" not in points:
        return ref
    for idx, also in points["dmm_also"].fillna("").items():
        for other in str(also).split():
            ref[idx] -= points.at[idx, f"{other}_A"]
    return ref


def add_fansum(points):
    """Add fansum_A (+ _std) = sum of the per-fan channels, if the point file has them."""
    cols = [f"{c}_A" for c in FANSUM_CHANNELS if f"{c}_A" in points]
    if len(cols) == len(FANSUM_CHANNELS):
        points = points.assign(fansum_A=points[cols].sum(axis=1),
                               fansum_A_std=np.sqrt((points[[f"{c}_std" for c in cols]] ** 2).sum(axis=1)))
    return points


def fit_channel(points, ch):
    """Weighted least squares of (dmm_A - dmm_also) on <ch>_A. Returns (gain, offset, table) or None."""
    points = add_fansum(points)
    if f"{ch}_A" not in points:
        return None
    carrier = "fan12" if ch == "fansum" else ch
    sel = points[points["channels"].str.split().apply(lambda c: carrier in c)]
    sel = sel.dropna(subset=[f"{ch}_A", "dmm_A"])
    if len(sel) < 2:
        return None
    sel = sel.assign(dmm_A=dmm_minus_also(sel))
    lsb = INA226_SHUNT_LSB_V / NOMINAL_SHUNT_OHMS.get(ch, FANSUM_SHUNT_OHMS)
    sigma = np.sqrt((DMM_WEIGHT_PCT / 100 * sel["dmm_A"]) ** 2 + (sel["dmm_res_A"] / 2) ** 2
                    + sel["dmm_spread_A"] ** 2
                    + (sel[f"{ch}_A_std"].fillna(0) / np.sqrt(sel["n_rows"])) ** 2 + lsb ** 2 / 12)
    gain, offset = np.polyfit(sel[f"{ch}_A"], sel["dmm_A"], 1, w=1 / sigma)
    cal = gain * sel[f"{ch}_A"] + offset
    table = pd.DataFrame({"range": sel["dmm_range"], "dmm_mA": sel["dmm_A"] * 1e3,
                          "ina_nominal_mA": sel[f"{ch}_A"] * 1e3, "ina_cal_mA": cal * 1e3,
                          "resid_mA": (cal - sel["dmm_A"]) * 1e3,
                          "resid_pct": np.where(sel["dmm_A"] > 0,
                                                (cal - sel["dmm_A"]) / sel["dmm_A"] * 100, np.nan),
                          "sigma_mA": sigma * 1e3})
    return gain, offset, table


def print_fits(points, channels):
    for ch in channels:
        result = fit_channel(points, ch)
        if result is None:
            print(f"  {ch}: need 2+ points to fit")
            continue
        gain, offset, table = result
        flag = ("   <- IMPLAUSIBLE, not applied: did all the DMM current go through this channel?"
                if abs(gain - 1) > MAX_GAIN_DEVIATION else "")
        r_nom = NOMINAL_SHUNT_OHMS.get(ch, FANSUM_SHUNT_OHMS)
        what = "per-fan shunts, summed" if ch == "fansum" else \
            f"effective shunt {r_nom / gain * 1e3:.4f} mOhm vs {r_nom * 1e3:g} nominal"
        print(f"\n  {ch}: I_true = {gain:.5f} * I_nominal {offset * 1e3:+.2f} mA   ({what}){flag}")
        print(table.round(3).to_string(index=False))


def read_points(specs):
    """Concatenate point files. 'file.csv::b5in' sets dmm_also=b5in for that file's points."""
    frames = []
    for spec in specs:
        path, _, also = str(spec).partition("::")
        df = pd.read_csv(path)
        if also:
            df["dmm_also"] = also.replace(",", " ")
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def point_channels(points):
    """Channels to fit: those listed, plus fansum when a whole-fan-rail (fan12) session exists."""
    channels = {c for cs in points["channels"] for c in cs.split()}
    if "fan12" in channels:
        channels.add("fansum")
    return sorted(channels)


def load_calibration(specs):
    """{channel: (gain, offset)} fitted from one or more point files (see read_points)."""
    points = read_points(specs)
    channels = point_channels(points)
    cal = {}
    for ch in channels:
        result = fit_channel(points, ch)
        if result is None:
            continue
        if abs(result[0] - 1) > MAX_GAIN_DEVIATION:
            print(f"calibration {ch}: gain {result[0]:.3f} is implausible, not applied")
            continue
        cal[ch] = result[:2]
    return cal


def run(port, channels, dmm_also=()):
    per_fan = [c for c in channels if c.startswith("fan") and c != "fan12"]
    if len(per_fan) > 1:
        sys.exit(f"List at most one per-fan channel ({', '.join(per_fan)} given): each listed channel "
                 "must carry the whole DMM current, which only one header can.")
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = OUT_DIR / f"{stamp}_shunt_cal_{'_'.join(channels)}.csv"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if "in" in channels:
        print(PLAN_INPUT)
    if any(c != "in" for c in channels):
        print(PLAN_FAN_RAIL)
    print(f"Points are saved to {path}")

    points, last_range = [], "400ma"
    while True:
        k = len(points) + 1
        command = input(f"\nPoint {k}: set supply, load, DMM range. Sketch command (e.g. 'pwm 60'), "
                        f"Enter for none, 'q' to finish: ").strip()
        if command.lower() == "q":
            break
        rng = input(f"  DMM range [400mA / 10A / none] (Enter = {last_range}): ").strip().lower() or last_range
        if rng not in RANGE_UNITS:
            print(f"  unknown range '{rng}'")
            continue
        last_range = rng
        print("  Watch the DMM while this averages.")
        try:
            with open_port(port) as ser:
                data = collect_point(ser, channels, command or None)
        except (serial.SerialException, RuntimeError) as e:
            print(f"\n  could not read the ESP32 ({e}). Is the PCB powered and the cable connected?")
            continue
        rec = summarize(data)
        for ch in channels:
            mean, std = rec.get(f"{ch}_A", np.nan), rec.get(f"{ch}_A_std", np.nan)
            half = len(data) // 2
            drift = data[f"{ch}_A"].iloc[half:].mean() - data[f"{ch}_A"].iloc[:half].mean()
            note = "  <- drifting, consider 'r'" if abs(drift) > 0.005 * abs(mean) + 1e-3 else ""
            print(f"  {ch}: {mean * 1e3:.2f} mA nominal, std {std * 1e3:.2f} mA, "
                  f"drift {drift * 1e3:+.2f} mA{note}")

        unit = RANGE_UNITS[rng]
        text = ""
        while True:
            text = input(f"  DMM reading in {'mA' if unit == 'ma' else 'A'} "
                         f"(fluctuating: low..high; 'r' redo, 's' skip): ").strip().lower()
            if text in ("r", "s"):
                break
            try:
                dmm_A, res_A, spread_A = parse_dmm(text, rng)
                break
            except ValueError:
                print("  could not read that, e.g. 152.3  or  1.523A  or  148.2..151.0")
        if text in ("r", "s"):
            continue

        rec.update({"time": datetime.now().isoformat(timespec="seconds"), "channels": " ".join(channels),
                    "dmm_also": " ".join(dmm_also), "sketch_cmd": command, "dmm_range": rng,
                    "dmm_A": dmm_A, "dmm_res_A": res_A, "dmm_spread_A": spread_A})
        points.append(rec)
        df = pd.DataFrame(points)
        front = ["time", "channels", "dmm_also", "sketch_cmd", "dmm_range", "dmm_A", "dmm_res_A",
                 "dmm_spread_A", "n_rows"]
        df[front + [c for c in df.columns if c not in front]].to_csv(path, index=False)
        print_fits(df, channels)

    if points:
        print(f"\nSaved {len(points)} points to {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("port")
    p_run.add_argument("channels", nargs="+", choices=sorted(NOMINAL_SHUNT_OHMS))
    p_run.add_argument("--dmm-also", nargs="+", default=[], choices=sorted(NOMINAL_SHUNT_OHMS),
                       help="channels whose current also flows through the DMM (subtracted)")
    p_fit = sub.add_parser("fit")
    p_fit.add_argument("files", nargs="+", help="point files; file.csv::b5in marks dmm_also for that file")
    args = parser.parse_args()

    if args.action == "run":
        run(args.port, args.channels, args.dmm_also)
    else:
        points = read_points(args.files)
        print_fits(points, point_channels(points))


if __name__ == "__main__":
    sys.exit(main())
