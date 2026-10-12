"""
compare_efficiency.py -- efficiency and loss vs output power for several fan-ramp captures

  python "measurements/test setup/efficiency_esp32/compare_efficiency.py" <capture>.csv [...] \
      [--cal <shunt_cal files, file.csv::b5in>] [--out <name>.png]

Each run is loaded exactly as plot_efficiency.py does (calibration, 12 V series-drop
correction, output current from the per-fan shunts). Up and down halves are pooled.
Saves the figure and the binned table (<out>.csv, calculated from the captures) and prints it.

Panels: efficiency and loss vs output power per input voltage; the fan12 / per-fan-sum shunt
ratio per run and in the calibration session (shows whether a fan12 calibration carries over);
the input-shunt calibration ratio (INA226 / DMM) per calibration series.
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from calibrate_shunts import load_calibration, read_points
from plot_efficiency import AXIS, INK, INK_2, MUTED, SURFACE, load, style

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
PD_ORDER = [5, 9, 15, 20]   # fixed colour slot per USB PD voltage; others follow
P_BINS = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.5, 8.0, 10.0, 12.5, 15.0, 17.5, 20.0,
          22.5, 25.0, 27.5, 30.0, 32.5, 35.0, 37.5, 40.0, 42.5]


def nominal_vin(df):
    return int(round(df["in_V"].iloc[:5].median()))


def colour_for(vin, seen):
    order = PD_ORDER + sorted(v for v in seen if v not in PD_ORDER)
    return SERIES[order.index(vin) % len(SERIES)]


def main(csvs, cal_specs, out):
    cal = load_calibration(cal_specs) if cal_specs else {}
    runs = []
    for path in csvs:
        df, active, fans = load(path, cal)
        raw, _, _ = load(path, None)          # nominal currents, for the shunt-ratio panel
        runs.append({"path": Path(path), "vin": nominal_vin(df), "active": active,
                     "raw": raw[raw["pwm_pct"] > 0], "series_r": df.attrs["series_r_ohm"],
                     "ref": df.attrs["output_ref"]})
    runs.sort(key=lambda r: r["vin"])
    vins = [r["vin"] for r in runs]

    table = []
    for r in runs:
        a = r["active"]
        g = a.groupby(pd.cut(a["P_out"], P_BINS), observed=True)
        b = pd.DataFrame({"P_out_W": g["P_out"].mean(), "eta": g["eta"].mean(),
                          "loss_W": (g["P_in"].mean() - g["P_out"].mean()),
                          "Vin_V": g["in_V"].mean(), "Iin_A": g["in_A"].mean(), "rows": g.size()})
        b = b[b["rows"] >= 3].reset_index(drop=True)
        b.insert(0, "run", r["path"].stem)
        b.insert(1, "vin_nominal", r["vin"])
        r["binned"] = b
        table.append(b)
    table = pd.concat(table, ignore_index=True)

    fig, axes = plt.subplots(2, 2, figsize=(14, 10), facecolor=SURFACE)
    notes = [f"input: {'calibrated' if 'in' in cal else 'nominal shunt'}",
             f"output: {runs[0]['ref']}{' (calibrated)' if 'fansum' in cal else ''} + 5 V buck input"]
    corrected = [f"{r['vin']} V" for r in runs if r["series_r"]]
    if corrected:
        notes.append(f"{', '.join(corrected)}: 12 V series drop "
                     f"({', '.join(f'{r['series_r'] * 1e3:.0f}' for r in runs if r['series_r'])} mΩ) added back")
    fig.suptitle("Buck-boost efficiency vs output power, fan-PWM ramps\n" + "; ".join(notes),
                 x=0.01, ha="left", fontsize=11, color=INK)

    for ax, col, title, ylabel in [(axes[0, 0], "eta", "Efficiency", "Efficiency P_out / P_in"),
                                   (axes[0, 1], "loss_W", "Loss", "Loss P_in − P_out (W)")]:
        style(ax, title, "Output power, fan rail + 5 V buck input (W)", ylabel)
        for r in runs:
            b, c = r["binned"], colour_for(r["vin"], vins)
            ax.plot(b["P_out_W"], b[col], color=c, linewidth=2, marker="o", markersize=5,
                    markeredgecolor=SURFACE, markeredgewidth=1.5, label=f"{r['vin']} V in")
            ax.annotate(f"{r['vin']} V", (b["P_out_W"].iloc[-1], b[col].iloc[-1]),
                        xytext=(6, 0), textcoords="offset points", va="center", fontsize=8, color=INK_2)
        ax.legend(frameon=False, fontsize=8, labelcolor=INK_2, loc="lower right" if col == "eta" else "upper left")
    axes[0, 0].axhline(1.0, color=AXIS, linewidth=1)

    ax = axes[1, 0]
    style(ax, "1 mΩ fan12 shunt vs sum of per-fan 10 mΩ shunts (nominal)", "Fan-rail current, fan12 nominal (A)",
          "fan12 / per-fan sum")
    for r in runs:
        raw = r["raw"]
        m = raw["fan12_A"] > 0.3
        label = f"{r['vin']} V run" + (" (DMM in 12 V path)" if r["series_r"] else "")
        ax.scatter(raw.loc[m, "fan12_A"], raw.loc[m, "fan12_A"] / raw.loc[m, "fans_A"], s=5, alpha=0.4,
                   color=colour_for(r["vin"], vins), linewidths=0, label=label)
    if cal_specs:
        pts = read_points(cal_specs)
        fan_cols = [f"fan{k}_A" for k in range(1, 11)]
        fr = pts[pts["channels"].str.split().apply(lambda c: "fan12" in c)]
        if len(fr) and all(c in fr for c in fan_cols):
            m = fr["fan12_A"] > 0.3
            ax.scatter(fr.loc[m, "fan12_A"], fr.loc[m, "fan12_A"] / fr.loc[m, fan_cols].sum(axis=1), s=40,
                       marker="x", color=INK, linewidths=1.5, label="fan-rail calibration points")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK_2, loc="lower right", markerscale=2)

    ax = axes[1, 1]
    style(ax, "Input shunt calibration: INA226 nominal / DMM", "DMM current (A)", "in_A / DMM")
    if cal_specs:
        pts = read_points(cal_specs)
        pin = pts[pts["channels"].str.split().apply(lambda c: "in" in c) & (pts["dmm_A"] > 0.05)]
        for (vlo, vhi), marker, ink in [((0, 7), "o", INK), ((7, 30), "s", MUTED)]:
            s = pin[(pin["in_V"] >= vlo) & (pin["in_V"] < vhi)]
            if len(s):
                ax.scatter(s["dmm_A"], s["in_A"] / s["dmm_A"], s=40, marker=marker, color=ink,
                           label=f"Vin {s['in_V'].min():.1f}–{s['in_V'].max():.1f} V ({len(s)} points)")
        if "in" in cal:
            gain, offset = cal["in"]
            x = np.linspace(max(0.05, pin["dmm_A"].min()), pin["dmm_A"].max(), 100)
            ax.plot(x, (x - offset) / gain / x, color=INK_2, linewidth=1.5,
                    label=f"fit: I = {gain:.4f} × nominal {offset * 1e3:+.1f} mA")
        ax.legend(frameon=False, fontsize=8, labelcolor=INK_2, loc="lower right")

    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    table.to_csv(Path(out).with_suffix(".csv"), index=False)
    print(f"Saved {out} and {Path(out).with_suffix('.csv')}")
    print(table.round(4).to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csvs", nargs="+")
    parser.add_argument("--cal", nargs="+", help="shunt calibration point files (file.csv::b5in marks dmm_also)")
    parser.add_argument("--out", help="output PNG (default: next to the first capture)")
    args = parser.parse_args()
    first = Path(args.csvs[0])
    out = args.out or str(first.with_name(first.stem.split("_fans")[0][:10] + "_efficiency_summary.png"))
    main(args.csvs, args.cal, out)
