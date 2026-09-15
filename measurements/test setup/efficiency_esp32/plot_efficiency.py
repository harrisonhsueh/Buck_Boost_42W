"""
plot_efficiency.py -- plot a fan-PWM-ramp capture from efficiency_logger.py

  python "measurements/test setup/efficiency_esp32/plot_efficiency.py" measurements/efficiency/<capture>.csv
  python "measurements/test setup/efficiency_esp32/plot_efficiency.py" <capture>.csv --cal <shunt_cal files>

Saves <capture>.png (or <capture>_cal.png with --cal) next to the CSV and prints the
up/down-ramp comparison. --cal applies I = gain * I_nominal + offset per channel, fitted by
calibrate_shunts.py; channels without calibration points stay at nominal shunt values.

Efficiency definitions:
  P_out     = V_fan12 * I_fans + P_b5in    buck-boost output (fan rail + 5 V buck input), fan-rail
                                           current from the sum of the ten per-fan 10 mOhm shunts
  eta       = P_out / P_in
  eta_fan12 = (P_fan12 + P_b5in) / P_in    fan-rail current from the 1 mOhm fan12 shunt (cross-check)
The per-fan sum is the output reference because the 1 mOhm fan12 shunt's reading shifted 2.6 %
relative to it when a DMM was added to the 12 V path (2026-09-15), so a 1 mOhm calibration taken
with a DMM inserted need not hold in normal operation. If the per-fan channels carry less than
half the fan-rail current (e.g. a resistor wired straight to the rail), fan12 is used instead.
The ramp is split into up/down halves at the peak PWM row.

Series resistance in the 12 V path: if the fan-rail voltage sags by more than 50 mOhm x
(fan-rail + 5 V buck current), something (e.g. a DMM left in series) sits between the converter
output and the INA226s. Its drop is added back to the fan-rail and 5 V buck bus voltages so P_out
is the converter's output power, and the run is labelled. (2026-09-15 5 V and 9 V runs: ~0.37 Ohm;
15 V and 20 V runs without the DMM: 4-6 mOhm.)
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from calibrate_shunts import load_calibration

UP_COLOR = "#2a78d6"
DOWN_COLOR = "#eb6834"
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

CONNECTED_FAN_MIN_A = 0.02   # a per-fan channel counts as connected above this peak current
SERIES_R_LIMIT_OHM = 0.05    # 12 V path sag above this is corrected and labelled
TACH_MEDIAN_ROWS = 7         # rolling median for tach speed (older captures have glitch rows)


def correct_12v_series_r(df):
    """Add back the drop of extra series resistance between converter output and INA226s.
    Returns the resistance removed (0 if below SERIES_R_LIMIT_OHM or not measurable)."""
    i12 = df["fan12_A"] + df["b5in_A"]
    if i12.max() - i12.min() < 0.3:
        return 0.0
    r = -np.polyfit(i12, df["fan12_V"], 1)[0]
    if r < SERIES_R_LIMIT_OHM:
        return 0.0
    for col in [c for c in df.columns if c.endswith("_V") and c not in ("in_V", "b5out_V")]:
        df[col] = df[col] + r * i12
    return r


def load(path, cal=None):
    df = pd.read_csv(path)
    for ch, (gain, offset) in (cal or {}).items():
        if f"{ch}_A" in df:
            df[f"{ch}_A"] = gain * df[f"{ch}_A"] + offset
    df.attrs["series_r_ohm"] = correct_12v_series_r(df)
    df["t_s"] = (df["t_ms"] - df["t_ms"].iloc[0]) / 1000.0
    for ch in ["in", "fan12", "b5in", "b5out"]:
        df[f"P_{ch}"] = df[f"{ch}_V"] * df[f"{ch}_A"]
    fans = [f"fan{k}" for k in range(1, 11)
            if f"fan{k}_A" in df and df[f"fan{k}_A"].max() > CONNECTED_FAN_MIN_A]
    # all ten channels (unconnected ones add their small offsets), matching the fansum calibration
    df["fans_A"] = df[[f"fan{k}_A" for k in range(1, 11) if f"fan{k}_A" in df]].sum(axis=1)
    if cal and "fansum" in cal:
        gain, offset = cal["fansum"]
        df["fans_A"] = gain * df["fans_A"] + offset
    df["P_fans"] = df["fan12_V"] * df["fans_A"]
    use_fans = bool(fans) and df["fans_A"].max() > 0.5 * df["fan12_A"].max()
    df.attrs["output_ref"] = "per-fan shunts" if use_fans else "fan12 shunt"
    df["P_out"] = (df["P_fans"] if use_fans else df["P_fan12"]) + df["P_b5in"]
    df["eta"] = df["P_out"] / df["P_in"]
    df["eta_fan12"] = (df["P_fan12"] + df["P_b5in"]) / df["P_in"]
    peak = df["pwm_pct"].idxmax()
    df["dir"] = np.where(df.index <= peak, "up", "down")
    rpm_cols = [c for c in df.columns if c.endswith("_rpm") and df[c].max() > 0]
    if rpm_cols:
        smooth = [df.groupby("dir")[c].transform(
                      lambda s: s.rolling(TACH_MEDIAN_ROWS, center=True, min_periods=3).median())
                  for c in rpm_cols]
        df["rpm_median"] = pd.concat(smooth, axis=1).median(axis=1)
    df.attrs["rpm_cols"] = rpm_cols
    active = df[df["pwm_pct"] > 0]  # drop the 0 % tails before and after the ramp
    return df, active, fans


def ramp_slope(active):
    """PWM %/s of the up half (the ramp may turn around early at the Iin limit)."""
    up = active[active["dir"] == "up"]
    return (up["pwm_pct"].max() - up["pwm_pct"].min()) / (up["t_s"].max() - up["t_s"].min())


def overlap_grid(active, margin=6.0):
    """PWM grid covered by both halves, kept `margin` % inside so shifted lookups don't clamp."""
    lo = max(20.0, active["pwm_pct"].min() + margin)
    hi = min(95.0, active["pwm_pct"].max() - margin)
    return np.linspace(lo, hi, 200)


def binned(active, x, y, bins):
    out = {}
    for d in ["up", "down"]:
        sub = active[active["dir"] == d]
        g = sub.groupby(pd.cut(sub[x], bins, include_lowest=True), observed=True)
        out[d] = pd.DataFrame({"x": g[x].mean(), "mean": g[y].mean(),
                               "se": g[y].std() / np.sqrt(g[y].count()), "n": g[y].count()})
    return out


def lag_fit(active, slope_pct_per_s, x="pwm_pct", y="fans_A"):
    """Half-shift d (in PWM %) that best overlays the up and down curves; tau = d / slope.

    A response lagging PWM by tau reads y_up(p) = f(p - d) and y_down(p) = f(p + d), with
    d = slope * tau, so positive d means lag. Negative d means the up ramp reads high, e.g.
    extra current to accelerate the rotors. Checked against a synthetic 2.0 s first-order
    lag (recovered 1.8 s)."""
    up = active[active["dir"] == "up"].dropna(subset=[y]).sort_values(x)
    dn = active[active["dir"] == "down"].dropna(subset=[y]).sort_values(x)
    grid = overlap_grid(active)
    best = min(((d, np.sqrt(np.mean((np.interp(grid + d, up[x], up[y]) -
                                     np.interp(grid - d, dn[x], dn[y])) ** 2)))
                for d in np.linspace(-5, 5, 401)), key=lambda p: p[1])
    return best[0], best[0] / slope_pct_per_s, best[1]


def lag_text(fit, unit_fmt):
    d, tau, rms = fit
    kind = "lags PWM" if tau >= 0 else "up ramp reads high (not a lag)"
    return (f"best overlay: up/down offset {2 * d:+.2f} % PWM\n"
            f"τ = {tau:+.2f} s, {kind}; residual {unit_fmt(rms)} rms")


def style(ax, title, xlabel, ylabel):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=10, color=INK, pad=8)
    ax.set_xlabel(xlabel, fontsize=9, color=INK_2)
    ax.set_ylabel(ylabel, fontsize=9, color=INK_2)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    for side in ["left", "bottom"]:
        ax.spines[side].set_color(AXIS)


def scatter_up_down(ax, active, x, y, **kw):
    for d, c in [("up", UP_COLOR), ("down", DOWN_COLOR)]:
        sub = active[active["dir"] == d]
        ax.scatter(sub[x], sub[y], s=6, color=c, alpha=0.35, linewidths=0, **kw)


def main(csv_path, cal_paths=None):
    csv_path = Path(csv_path)
    cal = load_calibration(cal_paths) if cal_paths else {}
    for ch, (gain, offset) in cal.items():
        print(f"calibration {ch}: I = {gain:.5f} * I_nominal {offset * 1e3:+.2f} mA")
    df, active, fans = load(csv_path, cal)
    cal_note = f"calibrated: {', '.join(cal)}" if cal else "nominal shunts, uncalibrated"
    if df.attrs["series_r_ohm"]:
        cal_note += f"; {df.attrs['series_r_ohm'] * 1e3:.0f} mΩ 12 V series drop added back"
        print(f"WARNING: 12 V path has {df.attrs['series_r_ohm'] * 1e3:.0f} mOhm extra series resistance "
              f"(DMM left in?); its drop is added back to the fan-rail and 5 V buck bus voltages")

    slope = ramp_slope(active)
    shift, tau, rms = lag_fit(active, slope)
    k_gain, k_off = np.polyfit(active.loc[active["fans_A"] > 0.1, "fans_A"],
                               active.loc[active["fans_A"] > 0.1, "fan12_A"], 1)
    droop_r, droop_v0 = np.polyfit(active["in_A"], active["in_V"], 1)
    p_bins = np.linspace(active["P_out"].min(), active["P_out"].max(), 13)
    eta = binned(active, "P_out", "eta", p_bins)
    eta_alt = binned(active, "P_out", "eta_fan12", p_bins)
    ref = df.attrs["output_ref"]

    fig, axes = plt.subplots(2, 3, figsize=(15, 8.5), facecolor=SURFACE)
    fig.suptitle(f"{csv_path.stem}: fans {', '.join(f[3:] for f in fans)} on the fan rail, "
                 f"Vin {active['in_V'].max():.2f}-{active['in_V'].min():.2f} V, "
                 f"ramp {slope:.2f} %/s ({cal_note})", x=0.01, ha="left", fontsize=12, color=INK)

    ax = axes[0, 0]
    style(ax, "Fan PWM ramp", "Time (s)", "PWM duty (%)")
    for d, c in [("up", UP_COLOR), ("down", DOWN_COLOR)]:
        sub = df[df["dir"] == d]
        ax.plot(sub["t_s"], sub["pwm_pct"], color=c, linewidth=2, label=f"{d} ramp")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK_2)

    ax = axes[0, 1]
    style(ax, f"Buck-boost efficiency, up vs down ramp (output from {ref})",
          "Output power, fan rail + 5 V buck input (W)", "Efficiency P_out / P_in")
    scatter_up_down(ax, active, "P_out", "eta")
    for d, c in [("up", UP_COLOR), ("down", DOWN_COLOR)]:
        b = eta[d]
        ax.errorbar(b["x"], b["mean"], yerr=b["se"], color=c, linewidth=2, marker="o",
                    markersize=5, markeredgecolor=SURFACE, markeredgewidth=1.5, capsize=0,
                    label=f"{d}, binned mean ± s.e.")
    alt = pd.concat([eta_alt["up"], eta_alt["down"]]).groupby(level=0, observed=True).mean()
    ax.plot(alt["x"], alt["mean"], color=MUTED, linewidth=1.5, linestyle="--",
            label="both, output from 1 mΩ fan12 shunt")
    ax.set_ylim(0.75, 1.02)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK_2, loc="lower right")

    ax = axes[0, 2]
    style(ax, "Fan current vs PWM (settling check)", "PWM duty (%)",
          f"Sum of per-fan currents, fans {', '.join(f[3:] for f in fans)} (A)")
    for d, c in [("up", UP_COLOR), ("down", DOWN_COLOR)]:
        sub = active[active["dir"] == d]
        ax.plot(sub["pwm_pct"], sub["fans_A"], color=c, linewidth=1.5, label=f"{d} ramp")
    ax.text(0.03, 0.97, lag_text((shift, tau, rms), lambda v: f"{v * 1e3:.1f} mA"),
            transform=ax.transAxes, va="top", fontsize=8, color=INK_2)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK_2, loc="lower right")

    ax = axes[1, 0]
    style(ax, "Fan-rail shunt vs per-fan shunts", "Sum of per-fan currents, 10 mΩ shunts (A)",
          "Fan-rail current, 1 mΩ shunt (A)")
    ax.scatter(active["fans_A"], active["fan12_A"], s=6, color=UP_COLOR, alpha=0.5, linewidths=0)
    lim = [0, max(active["fans_A"].max(), active["fan12_A"].max()) * 1.05]
    ax.plot(lim, lim, color=MUTED, linewidth=1, label="1 : 1")
    ax.plot(lim, np.polyval([k_gain, k_off], lim), color=INK_2, linewidth=1.5,
            label=f"fit: {k_gain:.3f} × sum {k_off * 1e3:+.1f} mA")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK_2, loc="upper left")

    ax = axes[1, 1]
    style(ax, "Input voltage sag (source + wiring)", "Input current (A)", "Vin at input INA226 (V)")
    ax.scatter(active["in_A"], active["in_V"], s=6, color=UP_COLOR, alpha=0.5, linewidths=0)
    xs = np.array([active["in_A"].min(), active["in_A"].max()])
    ax.plot(xs, np.polyval([droop_r, droop_v0], xs), color=INK_2, linewidth=1.5,
            label=f"fit: {droop_v0:.3f} V − {-droop_r * 1e3:.0f} mΩ × Iin")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK_2)

    ax = axes[1, 2]
    rpm_cols = df.attrs["rpm_cols"]
    rpm_fit = None
    if rpm_cols:
        rpm_fit = lag_fit(active, slope, y="rpm_median")
        names = ", ".join(c[3:-4] for c in rpm_cols)
        style(ax, "Tach speed vs PWM (settling check)", "PWM duty (%)",
              f"Speed, median of fans {names}, {TACH_MEDIAN_ROWS}-row median (rpm)")
        for d, c in [("up", UP_COLOR), ("down", DOWN_COLOR)]:
            sub = active[active["dir"] == d]
            ax.plot(sub["pwm_pct"], sub["rpm_median"], color=c, linewidth=1.5, label=f"{d} ramp")
        ax.text(0.03, 0.97, lag_text(rpm_fit, lambda v: f"{v:.0f} rpm"),
                transform=ax.transAxes, va="top", fontsize=8, color=INK_2)
        ax.legend(frameon=False, fontsize=8, labelcolor=INK_2, loc="lower right")
    else:
        style(ax, "5 V housekeeping buck", "Output power P_fan12 + P_b5in (W)", "Power (W)")
        ax.scatter(active["P_out"], active["P_b5in"], s=6, color=UP_COLOR, alpha=0.5,
                   linewidths=0, label="5 V buck input (12 V side)")
        ax.scatter(active["P_out"], active["P_b5out"], s=6, color=DOWN_COLOR, alpha=0.5,
                   linewidths=0, label="5 V buck output")
        ax.set_ylim(0, None)
        ax.legend(frameon=False, fontsize=8, labelcolor=INK_2, loc="lower right", markerscale=3)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = csv_path.with_name(csv_path.stem + ("_cal" if cal else "") + ".png")
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    print(f"Saved {out}")

    # --- printed summary ---
    print(f"\nconnected fans: {fans}; ramp slope {slope:.3f} %/s; rows {len(active)}")
    print(f"eta (output from {ref}) up vs down (bins of P_out):")
    cmp = pd.DataFrame({"P_out_W": eta["up"]["x"], "up": eta["up"]["mean"],
                        "down": eta["down"]["mean"],
                        "up_minus_down": eta["up"]["mean"] - eta["down"]["mean"],
                        "se_diff": np.sqrt(eta["up"]["se"] ** 2 + eta["down"]["se"] ** 2),
                        "eta_fan12": alt["mean"]})
    print(cmp.round(4).to_string(index=False))
    grid = overlap_grid(active, margin=0.0)
    up_s = active[active["dir"] == "up"].sort_values("pwm_pct")
    dn_s = active[active["dir"] == "down"].sort_values("pwm_pct")
    mean_diff = np.mean(np.interp(grid, up_s["pwm_pct"], up_s["fans_A"]) -
                        np.interp(grid, dn_s["pwm_pct"], dn_s["fans_A"]))
    print(f"fan current, same PWM ({grid[0]:.0f}-{grid[-1]:.0f} %): up minus down {mean_diff * 1e3:+.2f} mA; "
          f"overlay offset {2 * shift:+.2f} % PWM, tau {tau:+.2f} s (+ = lag), residual {rms * 1e3:.2f} mA rms")
    if rpm_fit:
        print(f"tach speed: overlay offset {2 * rpm_fit[0]:+.2f} % PWM, tau {rpm_fit[1]:+.2f} s (+ = lag), "
              f"residual {rpm_fit[2]:.1f} rpm rms")
    print(f"fan12_A = {k_gain:.4f} * fans_A {k_off * 1e3:+.2f} mA")
    print(f"Vin = {droop_v0:.4f} V {droop_r * 1e3:+.1f} mOhm * Iin")
    print(f"5 V buck: P_in {active['P_b5in'].mean():.3f} W, P_out {active['P_b5out'].mean():.3f} W, "
          f"eta {(active['P_b5out'] / active['P_b5in']).mean():.3f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv")
    parser.add_argument("--cal", nargs="+", help="shunt calibration point files from calibrate_shunts.py")
    args = parser.parse_args()
    main(args.csv, args.cal)
