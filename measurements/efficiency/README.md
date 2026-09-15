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
| `133151_shunt_cal_in` | input shunt vs DMM (10 A range), 20 V and 5 V series; DMM insertion point not recorded | see caveats |
| `135055_shunt_cal_fan12_fan1_fan2_fan3` | fan rail vs DMM (10 A range). DMM spliced into the 12 V output before the fan12 and 5 V buck shunts, so it read fan + 5 V buck input current (confirmed) | fit with `::b5in`; the fan1–3 fits are invalid (no single header carried the DMM current); fan12 fit does not transfer (below) |
| `140050_fans_5V` | started at 14.7 V with PWM left at 100 % from the calibration, then Vin lowered to 4.3 V (~5.3 A nominal input) | **excluded** |
| `140201_fans_5V` | 10 fans on headers 1–3 (reported ~4 / ~5 / 1); 5 V; DMM still in the 12 V path (0.37 Ω) | usable with series-drop correction; ramp turned at 3.0 A nominal ≈ 2.74 A calibrated, Vin sagged to 4.67 V |
| `140503_fans_9V` | 10 fans; 9 V; DMM still in the 12 V path (0.37 Ω) | usable with series-drop correction; ramp turned at 3.0 A nominal |
| `141025_fans_15V` | 10 fans; 15 V; no DMM; full 0–100–0 % | clean |
| `141459_fans_20V` | 10 fans; 20 V; no DMM; full 0–100–0 % | clean |
| `2026-09-15_efficiency_summary.png/.csv` | calculated from the four 10-fan runs by `compare_efficiency.py` | derived |

Fan count check: at 100 % PWM the three headers drew 1.16 / 1.53 / 0.37 A (nominal) at similar
tach speeds. If the fans are alike, that is closer to 3 / 4 / 1 fans than 4 / 5 / 1. Not confirmed.

## Calibration results and precision

Fits used by the scripts (weighted): `in` I = 0.8996 × nominal + 4.3 mA; `fansum` (sum of the ten
per-fan channels) I = 0.9838 × nominal + 4.4 mA; `fan12` I = 0.9371 × nominal + 3.9 mA.
Unweighted fits with 1 standard error: `in` 0.9026 ± 0.0019, `fansum` 0.9866 ± 0.0030,
`fan12` 0.9386 ± 0.0027.

- **DMM readings were unsteady.** Fan current fluctuates (commutation ripple, speed wobble,
  airflow against the table), so the DMM display jumped and each entered value is a visual
  median. The INA226's own 0.28 s readings vary 0.5–0.7 % rms within each 8 s point.
  Calibration points scatter 0.5 % rms (max 1.3 %) around the fits. Any bias from reading the
  median by eye is not quantified.
- **Resolution:** DMM 10 A range, 1 mA below ~1.8 A and 10 mA above.
- **The fan12 (1 mΩ) calibration does not transfer to normal operation.** The fan12 / per-fan-sum
  reading ratio is 1.050 whenever the DMM was in the 12 V path (calibration session and the 5 V
  and 9 V runs), and 1.076 without it (15 V and 20 V runs). Splicing in the DMM changed the current
  path near the 1 mΩ shunt: 2.6 % is only ~26 µΩ on a 1 mΩ shunt, but would need ~260 µΩ on a
  10 mΩ one. With the calibration applied, efficiency computed from fan12 matches the per-fan
  result within 0.06 points in the 5 V and 9 V runs, and reads 2.5 points high (above 100 %) at
  15 V and 20 V. **The analysis therefore takes output current from the per-fan shunts.**
- **The input (1 mΩ) calibration may have the same problem**, and there is no second input shunt
  to check it against. It is the main uncertainty in the absolute efficiency: with nominal input
  readings, efficiency would be ~9 points lower (~88 %, i.e. ~4 W of loss at 36 W).
- **Series differ:** the 20 V and 5 V calibration series differ by ~1.3 % in gain.

## Best estimate so far

With the input calibration and per-fan output (`2026-09-15_efficiency_summary.csv`): 97–99 %
from ~5 W to 36 W output at 5–20 V input. Loss rises with input voltage at the same power
(0.53 W at 15 V vs 0.69 W at 20 V, ~36 W). Output power includes the 5 V buck input (~0.44 W).
Valid only if the input calibration transfers (see the check below).

Ramp rate (15 V and 20 V, up to 36 W): tach speed lags PWM by 0.1–0.3 s, and efficiency up vs down
agrees within 0.1 point above ~5 W, so 120 s per 0–100 % is slow enough. Fan current reads higher
on the up ramp (−3.6 % PWM offset); that is rotor acceleration power, not a lag.

## Open items and recommendations for the next session

1. **Check the input calibration without changing board wiring.** In a normal run, hold a few
   PWM levels and compare the bench supply's own current display with `in_A`. About 0.90 × `in_A`
   supports the calibration; close to `in_A` means it does not transfer.
2. **Use an electronic load for calibration and step-and-hold efficiency points.**
   - A constant-current e-load gives a steady current (a stable DMM reading), any chosen value
     up to the 42 W / 3.5 A design point, and its own current readout as a second reference.
   - Connect it where the fans connect, and put the DMM in the e-load lead rather than spliced
     into the board, so current flows past the shunts as it does in normal operation.
   - At multi-amp currents, check the header connector and per-fan shunt ratings, or land on
     the rail after the fan12 shunt.
   - Change current slowly: the V1 loop is deliberately slow (f_bw ≈ 11 Hz, notebook 07).
   - Keep one fan run to confirm the fans give the same efficiency at the same power.
3. **Put the input DMM in the bench-supply lead**, and record the insertion point.
4. **Before each efficiency run:** remove the DMM from the 12 V path (the fan-rail sag should be
   ~5 mΩ × current), and send `stop` before changing Vin.
5. **Redo 5 V and 9 V.**
   - For the 5 V / 3 A point, raise the supply until `in_V` ≈ 5.0 V at full load.
   - Set the ramp limit in nominal units: `ramp 120 100 3.34` ≈ 3.0 A true, if the input
     calibration holds.
6. **Tach:** `efficiency_esp32.ino` now times the median tach interval. The 2026-09-15 captures
   used first-to-last edge and have ~10–15 % glitch rows, so analysis applies a 7-row median.
