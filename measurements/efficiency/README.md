# Efficiency measurements (V1 board)

INA226-logged efficiency sweeps of the V1 board. Captures come from `efficiency_logger.py`
running against `efficiency_esp32.ino`; the tools live in
`measurements/test setup/efficiency_esp32/`. All numbers here are **measured** with the board's
INA226s, corrected by DMM calibration points where stated. Calibration caveats are below. Read
them before quoting an absolute efficiency.

## Session 2026-09-15

Load: fans on the 12 V fan rail, PWM ramped 0 → 100 → 0 % at 0.83 %/s (120 s each way) unless
the 3 A input limit turned the ramp around early. Bench supply at a fixed voltage per run.

| File | Conditions | Status |
|---|---|---|
| `114836_fans_5V` | 3 × Arctic P14 (not Pro), one each on headers 1–3, facing a table; 5 V; no tach | OK, uncalibrated era |
| `115614_fans_9V` | same 3 fans; 9 V; no tach | OK, uncalibrated era |
| `133151_shunt_cal_in` | input shunt vs DMM (10 A range), 20 V and 5 V series; DMM in the harness between bench supply and the board's input connector (board current path unchanged) | used |
| `135055_shunt_cal_fan12_fan1_fan2_fan3` | fan rail vs DMM (10 A range). DMM wired to **one** of the two parallel jumper sets just ahead of the fan12 shunt (second set removed); upstream of the 5 V buck tap, so it read fan + 5 V buck input current | **superseded** by `154613`: its fan12 fit does not hold in normal operation (below); fan1–3 fits invalid (no single header carried the DMM current) |
| `140050_fans_5V` | started at 14.7 V with PWM left at 100 % from the calibration, then Vin lowered to 4.3 V (~5.3 A nominal input) | **excluded** |
| `140201_fans_5V` | 10 fans on headers 1–3 (reported ~4 / ~5 / 1); 5 V; DMM still in the 12 V path (0.37 Ω, confirmed) | superseded by `151555`; with the drop added back it agrees within 0.1–0.4 points |
| `140503_fans_9V` | 10 fans; 9 V; DMM still in the 12 V path (0.37 Ω, confirmed) | superseded by `151955`; agrees within 0.0–0.3 points after correction |
| `141025_fans_15V` | 10 fans; 15 V; no DMM; full 0–100–0 % | clean |
| `141459_fans_20V` | 10 fans; 20 V; no DMM; full 0–100–0 % | clean |
| `151050`, `151326`, `151441_fans_5V` | 10 fans; 5 V; ramp limit 3.34 A nominal | **failed**: fan start surge tripped the input limit at 5.9 % PWM (below) |
| `151555_fans_5V` | 10 fans; 5 V; no DMM; `ramp 150` (0.66 %/s), limit 3.34 A nominal | clean; turned at 3.36 A nominal ≈ 3.02 A calibrated, Vin 4.64 V |
| `151955_fans_9V` | 10 fans; 9 V; no DMM; limit 3.34 A nominal | clean; turned at 85 % PWM, ≈ 3.02 A calibrated |
| `154613_shunt_cal_fan12` | fan rail vs DMM (10 A range), 10 fans, 15 V. DMM wired to **both** jumper sets, so current reaches the shunt as in normal operation; still upstream of the 5 V buck tap | used, fit with `::b5in` |
| `2026-09-15_efficiency_summary.png/.csv` | calculated from `151555`, `151955`, `141025`, `141459` by `compare_efficiency.py` | derived |

**Fan start surge at 5 V.** All ten fans share one PWM duty, so they start together at ~6 %. In
the three failed attempts the surge fell inside one 282 ms reading: 3.82 A nominal input (≈ 3.4 A
calibrated; the true peak inside the window is higher) and 1.29 A on the fan rail, then 2.8 A the
next reading. The ramp reversed on that single reading. In `151555` the same surge split across
two readings (2.98 and 3.13 A), both under the limit. The slower ramp was not what let it pass.
The sketch now holds the ramp while Iin is over the limit and reverses only after 3 readings in a
row. For a real 5 V / 3 A source this simultaneous start is an input-current spike; staggering
fan starts across the ten PWM pins would spread it (firmware only).

Fan count check: at 100 % PWM the three headers drew 1.16 / 1.53 / 0.37 A (nominal) at similar
tach speeds. If the fans are alike, that is closer to 3 / 4 / 1 fans than 4 / 5 / 1. Not confirmed.

## Calibration results and precision

Calibration set in use: `133151_shunt_cal_in.csv` and `154613_shunt_cal_fan12.csv::b5in`.

| Channel | Weighted fit (used) | Unweighted, ± 1 s.e. | Effective shunt |
|---|---|---|---|
| `in` | 0.8996 × nominal + 4.3 mA | 0.9026 ± 0.0019 | 1.112 mΩ |
| `fan12` | 0.9141 × nominal − 0.7 mA | 0.9156 ± 0.0012 | 1.094 mΩ |
| `fansum` (ten per-fan channels) | 0.9852 × nominal + 2.4 mA | 0.9856 ± 0.0008 | — |

- **DMM readings were unsteady.** Fan current fluctuates (commutation ripple, speed wobble,
  airflow against the table), so the DMM display jumped and each entered value is a visual
  median. The INA226's own 0.28 s readings vary 0.5–0.7 % rms within each 8 s point.
  - First sessions (`133151`, `135055`): points scatter 0.5 % rms (max 1.3 %) around the fits.
  - `154613`: residuals of 2.8 mA rms (`fansum`) and 4.5 mA rms (`fan12`).
  - Any bias from reading the median by eye is not quantified.
- **Resolution:** DMM 10 A range, 1 mA below ~1.8 A and mostly 10 mA above.
- **The 1 mΩ fan12 reading depends on how current is fed to the shunt.**
  - With the DMM on one of the two parallel jumper sets ahead of the shunt (`135055`), fan12 read
    1.051 × the per-fan sum. In every normal run it read 1.076–1.078, and with the DMM on both
    sets (`154613`) 1.080.
  - The one-set calibration therefore did not hold in normal runs: fan12-based efficiency came
    out 2.5 points above the per-fan result, over 100 % at 15 V and 20 V. With `154613` the two
    agree within 0.23–0.35 points at 5, 9, 15 and 20 V.
  - The shift is 27 µΩ (1.067 → 1.094 mΩ effective), about 0.05 square of 1 oz copper
    (~0.49 mΩ/□). That fits a redistribution of current near the pads that the sense
    connections see, not the whole jumper-to-shunt copper, which is in series either way.
    Copper weight assumed, not checked.
  - The 10 mΩ per-fan shunts are ten times less sensitive to this. Their summed gain agreed
    between the two sessions to 0.1 % (0.9866 vs 0.9856).
  - **Analysis keeps the per-fan sum as the output reference.** fan12 is the cross-check (grey
    dashed line in the per-run plots).
- **Light-load precision is set by offsets.** ±2 mA on the fan rail is ±24 mW, about ±1.3 points
  at 1.8 W output (negligible at 36 W). Replacing the `135055` fit (+4.4 mA offset) with `154613`
  (+2.4 mA) lowered the ~1.8 W efficiencies by ~1.2 points. The lowest calibration point had 57 mA
  of fan idle current, not zero.
- **The input (1 mΩ) calibration should transfer.** The DMM was in the supply harness, so current
  entered the board through its connector exactly as in the efficiency runs. There is no second
  input shunt to confirm it. It sets the absolute level: with nominal input readings, efficiency
  would be ~9 points lower (~88 %, i.e. ~4 W of loss at 36 W). A cheap confirmation is to compare
  the bench supply's current display with `in_A` during a normal run.
- **Series differ:** the 20 V and 5 V calibration series differ by ~1.3 % in gain, not explained.
  Treat voltage-to-voltage efficiency differences smaller than ~1 point with caution.
## Best estimate so far

Calibration set above applied; output = fan-rail voltage × (sum of the ten per-fan currents) +
5 V buck input power from its own INA226 (~0.44 W, uncalibrated 33 mΩ shunt).
From `2026-09-15_efficiency_summary.csv`:

| Input | Peak efficiency | At ~1.8 W out (±~1.3 points) | Highest-power bin |
|---|---|---|---|
| 5 V | 97.2 % at 9.0 W | 93.5 % (0.13 W loss) | 96.8 % at 13.0 W, 0.43 W loss, Iin 2.88 A, Vin 4.66 V |
| 9 V | 98.6 % at 16.3 W | 95.0 % (0.10 W) | 98.4 % at 25.5 W, 0.42 W loss, Iin 2.97 A |
| 15 V | 98.8 % at 21.2 W | 94.1 % (0.11 W) | 98.6 % at 35.8 W, 0.51 W loss |
| 20 V | 98.3 % at 23.7 W | 91.8 % (0.16 W) | 98.2 % at 35.8 W, 0.65 W loss |

The 5 V row is close to the Objective 1 corner (3 A in) but at 4.66 V, not 5.0 V, at the board.
At that point the measured 0.43 W total loss exceeds the 258 mW that the notebooks calculate for
the inductor (122 mW, REDEXPERT) plus FETs (136 mW, notebook 04) at 5 V / 3 A, as it must.

`notebooks/11_efficiency_measured_vs_model.ipynb` compares these runs with the notebook 03/04 loss
model at every measured point. The model accounts for ~68 % of the loss at ~3 A in boost, and 55–59 %
in buck.

Ramp rate (15 V and 20 V, up to 36 W): tach speed lags PWM by 0.1–0.3 s, and efficiency up vs down
agrees within 0.1 point above ~5 W, so 120 s per 0–100 % is slow enough. Fan current reads higher
on the up ramp (−3.6 % PWM offset); that is rotor acceleration power, not a lag.

## Open items and recommendations for the next session

1. **Optional input check:** in a normal run, compare the bench supply's own current display with
   `in_A` at a few held PWM levels (expect about 0.90 × `in_A`).
2. **Calibrate the per-fan channels with fixed power resistors, one header at a time.** A steady
   DC current gives a steady DMM reading, which removes the visual-median uncertainty of the fan
   sessions. No electronic load or MOSFET load is needed.
   - **Put the DMM in the resistor's lead**, on the header, never spliced into the board. The
     current then flows past that header's shunt exactly as a fan's would — the mistake that
     invalidated the first fan12 calibration.
   - **Calibrate each per-fan channel separately** (`run COM5 fan1`, then `fan2`, …). The analysis
     takes the output current from the sum of these channels, so each one carries the DMM current
     on its own and no whole-rail wiring is needed. `fan12` then only needs to stay a cross-check.
   - **Points per header:** nothing connected (enter 0, pins the offset), 16 Ω (two 8 Ω in series,
     0.75 A), 8 Ω (1.5 A). Those are 6–23 mW in the header's 10 mΩ shunt; 4 Ω (3 A, 91 mW) is
     above what a fan header ever sees, so it is not worth the risk.
   - **Let the resistors warm for a minute** before taking a point; their value drifts as they heat,
     and the script's drift warning will catch it.
   - **Input channel:** DMM in the supply harness as before, sweeping current by input voltage and
     resistor combination.
3. **Keep the input DMM in the bench-supply harness**, as in this session, and record the
   insertion point.
4. **Before each efficiency run:** remove the DMM from the 12 V path (the fan-rail sag should be
   ~5 mΩ × current), and send `stop` before changing Vin.
5. **Objective 1 point at the board:** raise the supply until `in_V` ≈ 5.0 V near full load
   (the harness drops ~0.13–0.15 Ω × Iin), with the ramp limit in nominal units
   (`ramp 120 100 3.34` ≈ 3.0 A calibrated). With the sketch's 3-reading hold, the start surge
   should no longer reverse the ramp, so `ramp 120` is fine again.
6. **Fans stay the load for the efficiency sweeps.** Their current fluctuates, but input and output
   convert in the same window, and a single reading's efficiency scatters only 0.3–0.55 points, so a
   30-reading bin averages to 0.06–0.10 points — below the calibration systematics (0.08 % gain
   standard error on the per-fan sum, 0.19 % on the input). Averaging more readings is cheaper than
   any load hardware. The one thing a steady load would fix is a systematic: P = V̄ · Ī drops the
   in-phase ripple product, worth 0.01–0.09 points at 36 W. One resistor-load efficiency point at a
   power the fans also reach would measure that directly.
7. **Tach:** `efficiency_esp32.ino` now times the median tach interval. The 2026-09-15 captures
   used first-to-last edge and have ~10–15 % glitch rows, so analysis applies a 7-row median.
   Neither sketch change (median tach, 3-reading input limit) has run on hardware yet.
