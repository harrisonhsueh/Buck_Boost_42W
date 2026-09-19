# Buck-Boost 42 W — USB-C PD to 12 V Fan-Array Controller

A 4-switch buck-boost (TI LM5176) that takes USB-C PD at any negotiated voltage
(5–20 V, ≤ 3 A) and delivers 12 V to an array of up to 10 PC fans for an air-purifier
build. **V1 is designed, fabricated, assembled, and measured** — including a startup
failure found on the bench that the vendor could not root-cause, and the discrete
workaround designed to fix it.

![V1 board, assembled](images/IMG_7734.JPG)

*V1: LM5176 power stage (Würth 7443634700, 47 µH), 4 × 4.7 mF bulk output, 5 V
housekeeping buck, ESP32 control, 10 fan headers. The wire near the EN/UVLO network is
the lockout-latch rework described below.*

This repo is the complete design record: sizing notebooks, measured scope data, LTspice
simulations, LaTeX circuit analysis, and the part databases behind every component
choice.

---

## V1 scope — what was deliberately not attempted

V1's goal was a **reliable first spin that works across the entire USB PD voltage
range**, not a maximally efficient converter. The topology is therefore a
**hard-switched** 4-switch buck-boost: a well-documented TI reference topology with a
controller that handles buck, boost, and the buck-boost transition region natively.

Deliberately out of scope for V1:

| Not attempted | Why |
|---|---|
| ZVS / soft-switching | Outside my current experience. Timing and dead-time design would need study I could not fit before the first spin, with real risk of a board that does not work. |
| Multiphase interleaving | Same unfamiliarity, plus more parts and more layout risk, for no benefit at the power level that actually constrains this design. |

Both remain reasonable V2 directions. The V1 position was that an understood topology
that works is worth more than an efficient topology I would be debugging for the first
time.

## Optimization objectives

**Objective 1 — efficiency at the source-limited corner (what V1 optimized).**
Maximize efficiency at **Vin = 5 V, Iin = 3 A (15 W input), boost mode**, with part cost
unconstrained.

This is the binding corner, not an arbitrary one. 5 V / 3 A is what a non-PD USB battery
bank or a plain USB Type-C @ 3 A source provides — the lowest input voltage, highest
input current, and highest boost ratio. Because the source is *power-limited* there,
every milliwatt of converter loss comes straight out of the fan power available.
Efficiency at this point buys **capability**, not electricity savings. At 9/15/20 V the
design is *checked* (ripple, saturation, 42 W peak capability) rather than optimized.

**Objective 2 — operational cost (planned, notebook 09).** Minimize BOM cost plus
lifetime electricity over the real mission profile. BOM cost is priced for a 50-board
build (DigiKey cut tape at 50 inductors or 200 MOSFETs; conventions in `data/README.md`).

The profile is set by the two fan speeds the unit is designed around (notebook 00). The
pre-build power figures came from a `42 W × (PWM duty)³` model; the measured column
replaces them and is what notebook 09 should use.

| Setting | Duty | Assumed (cube law) | **Measured** (notebook 00) |
|---|---|---|---|
| quiet, 33 % PWM | 95 % | 1.5 W | **4.3 W** |
| high, 67 % PWM | 4 % | 12.6 W | **14.0 W** |
| peak, 100 % PWM | 1 % | 42 W | **35.9 W** |
| **average** | | 2.35 W | **5.0 W** |

The cube model was wrong in the direction that matters: measured fan power goes as
PWM^1.56 (rpm^2.07), so the setting that occupies 95 % of the hours costs 2.8× what was
assumed. At $0.20/kWh the profile delivers ≈ 43.8 kWh/yr, ≈ **$8.75/yr of delivered
energy** — roughly double the $4.12/yr the cube model implied.

**Caveat: the measured column is open-air.** Those runs had the ten fans on the bench with
no enclosure, filters or static pressure, so they sat at a different point on the fans'
P-Q curve than the finished unit uses. The direction of the shift should not be assumed —
axial fans classically draw more power as flow is restricted. Repeating one full ramp with
the fans enclosed is the open item (notebook 00, §7).

That doubling does not change the objective's expected conclusion: converter-loss
differences between candidate parts are still worth *cents* per year, so Objective 2 is
expected to be BOM-dominated and to favour different parts than Objective 1. Where the two
objectives disagree, the notebooks say so explicitly rather than picking a winner silently.
Notebook 00 also flags a term that outweighs every power-stage part difference at this
profile: the 5 V housekeeping buck draws a constant **0.44 W** (measured) and was never
analysed in V1.

---

## The V1 story: design → build → measure → failure → fix

The part of this project worth reading is what happened after the board came back.

**The failure.** The LM5176's pre-bias startup misbehaves with this design's
intentionally slow control loop: after a brief VIN dropout, the controller restarts
badly into a still-charged output. TI support could not root-cause it and suggested only
a higher crossover frequency — which directly conflicts with the loop design
(f_bw ≈ 11 Hz) chosen in notebook 07 to keep the converter from fighting the fan array's
commutation current.

**The fix.** A discrete lockout latch, powered from VOUT, that pulls EN/UVLO low on
input dropout and holds it there until the output has discharged — so the LM5176 only
ever starts into a known state. Designing it meant a three-resistor divider whose
feasible region is a thin sliver once tolerances are applied, searched over parts JLCPCB
actually stocks.

- `uvlo/10a_uvlo_resistor_search.py` — worst-case search for the EN/UVLO divider over
  JLCPCB basic parts. Result: R2 = 420 k (120 k + 300 k), R1a = 150 k, R1b = 15 k.
- `uvlo/uvlo_tlv431.tex` / `.pdf` — divider equations, tolerance analysis, the four
  design constraints, and why the feasible region is narrow.
- `uvlo/10b_uvlo_latch.py` — worst-case DC checks of the latch, cross-checked
  automatically against the LTspice `.raw` output.
- `uvlo/uvlo_latch.tex` / `.pdf` — latch documentation: operating states, equations,
  simulation results, open review items.
- Schematic / simulation: `simulation/en_uvlo_lockoutv3_tlv.asc`.

The same design → measure → revise loop appears in miniature in notebook 08, where
measured input behaviour forced an input-filter redesign as a V1 rework.

## Design flow (read in order)

| # | Notebook / folder | What it decides |
|---|---|---|
| 00 | `notebooks/00_design_goals.ipynb` | Air-quality requirement → airflow → fan count → load and mission profile; what each USB supply can actually deliver |
| 01 | `notebooks/01_power_budget.ipynb` | Operating envelope (source- vs load-limited), mode map, power-stage currents, measured loss budget |
| 02 | `notebooks/02_fan_load_analysis.ipynb` | Measured fan startup/commutation current (the real load) |
| 03 | `notebooks/03_inductor_selection.ipynb` | L = 47 µH, Würth 7443634700 |
| 04 | `notebooks/04_mosfet_selection.ipynb` | BSC0902NSI switches (V1); BSZ0501NSI recorded as V2 candidate |
| 05 | `notebooks/05_output_input_capacitors.ipynb` | C_out = 4 × 4.7 mF + ceramics, C_in = 4 × 47 µF |
| 06 | `notebooks/06_ripple_analysis.ipynb` | 100 kHz ripple across the input range |
| 07 | `notebooks/07_stability_compensation.ipynb` | LM5176 pin components + deliberately slow loop (f_bw ≈ 11 Hz) |
| 08 | `notebooks/08_input_filter_redesign.ipynb` | Input smoothing via average-current-limit method (PCB v1 rework) |
| 10 | `uvlo/` | UVLO lockout latch (above) |
| 11 | `notebooks/11_efficiency_measured_vs_model.ipynb` | Measured efficiency vs the 03/04 loss model; sizes what the model misses |

## Known gaps in the V1 selection method

These are real limitations in how V1's parts were chosen, found while cleaning up the
design documents. They are listed rather than quietly patched, because they change how
much weight the V1 conclusions deserve.

1. **AC core loss was approximated.** V1's inductor comparison estimated AC loss from the
   SPICE-model parallel resistance, not manufacturer core-loss data. The fix is
   `data/inductor_losses_measured.csv`, holding manufacturer loss-calculator results
   (Würth REDEXPERT, Coilcraft Power Inductor Finder) at the 5 V / 3 A point, now for
   15 parts at 100 kHz. The V1 part (7443634700, 47 µH, 2013 size) has 122 mW of inductor
   loss (ΔT ≈ 3.0 K). Eight parts from four other series (Würth HCF 2815, HCF 2818 and
   HCF 2920 round wire; Coilcraft AGP2923) have less, 38–104 mW. That is 17–84 mW less
   converter loss, 0.12–0.56 % of the 15 W input. None of the eight is stocked at JLCPCB
   (checked 2026-09-14), so the V1 part is the lowest-loss *stocked* part, not the
   lowest-loss part. At 47 µH the ripple is small (0.62 A pk-pk) and DC loss dominates
   (110 of 122 mW), which is also why the V1 part barely improves from 100 to 300 kHz
   (122 → 114 mW).
2. **Part cost was never in the optimization.** There was no basis for saying whether a
   cheaper, less efficient part should win. `Price_Ref_*` and `Price_Build_*` columns now
   exist in the part databases (conventions in `data/README.md`); reference prices are
   filled for ten inductors and three MOSFETs so far, priced for a 50-board build. The V1
   inductor is not the cheapest of them ($6.45 vs $2.78 for `SPM12565VT-220M-D`).
3. **Coverage is incomplete.** TDK ERU 24 and SPM12565VT, the 68 µH HCF 2920 round-wire
   part and the 100 µH+ litz parts still have no manufacturer loss data, and parts outside
   the database were not searched. By notebook 03's AC-loss budget, TDK ERU 24
   `B82559A0303A024` could still beat the V1 part if its AC loss is under 89 mW.
   Inductor loss is also not converter efficiency: ripple sets RMS current and so MOSFET
   loss.
4. **The MOSFET table was not datasheet data.** 16 of its 19 rows were drafted with AI
   help and added in one commit without being checked against datasheets. When checked,
   most values did not match, and five part numbers could not be found at their
   manufacturer. It mattered for V1: the MOSFET was meant to be a 40 V part, for input
   margin at 20 V PD. The table listed BSC0902NS as 40 V, which made it the best "40 V"
   silicon part. It is actually a 30 V part, and so is the BSC0902NSI the board was built
   with (not in the table at all), so V1 does not have the 40 V margin it was chosen for.
   The table has since been re-transcribed from datasheet tables, with revision and test
   conditions per row (`data/README.md`). Notebook 04 now evaluates RDS(on) and Q_g at
   the LM5176's actual gate voltage (BIAS is tied to VOUT on V1, so 7.35 V) and adds
   C_oss, dead-time and reverse-recovery loss. On that basis BSC0902NSI is mid-field at
   the 5 V / 3 A point: 136 mW of FET loss (#4 of 16), 24 mW above the best part checked.
   BSZ0501NSI is 14 mW lower, at $1.49 more per board (50-board DigiKey pricing).
   Whether 30 V is enough on the input side needs a switch-node measurement at 20 V in.

Where this stands: for Objective 1 neither V1 power part is a verified optimum. The
inductor is the lowest-loss JLCPCB-stocked part with manufacturer data, and eight
unstocked parts are 17–84 mW better. The MOSFET is 14–24 mW behind the best checked
part. Objective 2 is expected to be BOM-dominated, given how little
the electricity term is worth at this mission profile, and so may favour a cheaper part
than V1 used. Reconciling the two belongs in notebook 09.

## Repository layout

```
notebooks/      design notebooks 00–11 (cleaned, re-executed*)
presentation.md slide source for the 45-minute end-to-end design talk
uvlo/           UVLO latch: scripts, LaTeX docs + PDFs, figures
constants.py    single source of truth for specs & part database access
component_utils.py
data/           part databases (inductors, mosfets, capacitors) + analysis CSVs
measurements/   scope captures (fan load, pre-bias startup tests) + parquet cache
simulation/     LTspice (.asc/.net/.raw): UVLO latch v1–v3, input bounce tests
datasheets/     component datasheets
app_notes/      application notes (layout/EMI, gate resistors)
figures/        exported figures from the notebooks
images/         board photos
archive/        superseded originals (old notebooks, UVLO iterations, old data)
```

\* 07 and 08 contain multi-minute simulations; their outputs are preserved from the
original runs (code cleaned & paths fixed). All other notebooks were re-executed
top-to-bottom.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows   (source .venv/bin/activate on Linux/Mac)
pip install -r requirements.txt
```

Notebooks assume the working directory `notebooks/` (they reference `../data`,
`../measurements`, and import `constants.py` from the repo root). The LaTeX docs compile
with plain `pdflatex` (siunitx optional — a fallback is built in).

## Old → new file map

| Old (archive/) | New |
|---|---|
| `9_Power_Budget.ipynb` | `notebooks/01_power_budget.ipynb` |
| `6_Fan_Load_Analysis.ipynb` | `notebooks/02_fan_load_analysis.ipynb` |
| `1_Buck_Boost_Inductor.ipynb` | `notebooks/03_inductor_selection.ipynb` |
| `2_Buck_Boost_Mosfets.ipynb` | `notebooks/04_mosfet_selection.ipynb` |
| `3_Buck_Boost_Cout_Cin.ipynb` | `notebooks/05_output_input_capacitors.ipynb` |
| `4_Ripple.ipynb` | `notebooks/06_ripple_analysis.ipynb` |
| `5_stability.ipynb` (+ `7_Miscellaneous`) | `notebooks/07_stability_compensation.ipynb` |
| `8_redesign_load_filter_method.ipynb` | `notebooks/08_input_filter_redesign.ipynb` |
| `10_UVLO_Latch*.ipynb`, `10a_*` | `uvlo/` (10a script + both .tex docs + 10b) |
