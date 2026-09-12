# Buck-Boost 42 W — USB-C PD to 12 V Fan-Array Controller

LM5176 4-switch buck-boost converting USB-C PD (5–20 V, ≤3 A) to 12 V for an
array of up to 10 PC fans (air purifier build). This repo is the complete design
record: sizing notebooks, measured data, LTspice simulations, and the UVLO
lockout-latch design that works around an LM5176 pre-bias startup failure.

## Design flow (read in order)

| # | Notebook / folder | What it decides |
|---|---|---|
| 01 | `notebooks/01_power_budget.ipynb` | Operating envelope, total load, 45 W source headroom |
| 02 | `notebooks/02_fan_load_analysis.ipynb` | Measured fan startup/commutation current (the real load) |
| 03 | `notebooks/03_inductor_selection.ipynb` | L = 47 µH, Würth 7443634700 |
| 04 | `notebooks/04_mosfet_selection.ipynb` | BSC0902NS switches |
| 05 | `notebooks/05_output_input_capacitors.ipynb` | C_out = 4×4.7 mF + ceramics, C_in = 4×47 µF |
| 06 | `notebooks/06_ripple_analysis.ipynb` | 100 kHz ripple across the input range |
| 07 | `notebooks/07_stability_compensation.ipynb` | LM5176 pin components + deliberately slow loop (f_bw ≈ 11 Hz) |
| 08 | `notebooks/08_input_filter_redesign.ipynb` | Input smoothing via average-current-limit method (PCB v1 rework) |
| 10 | `uvlo/` | **UVLO lockout latch** — see below |

## uvlo/ — pre-bias startup workaround (10a / 10b)

The LM5176's pre-bias startup fails with this design's slow control loop: after a
brief VIN dropout it restarts badly into a still-charged output (TI support could
not root-cause it; suggested only a higher crossover frequency, which conflicts
with the loop design). Fix: a discrete lockout latch, powered from VOUT, that
pulls EN/UVLO low on input dropout and holds it until the output has discharged.

- `uvlo/10a_uvlo_resistor_search.py` — sizes the 3-resistor EN/UVLO divider
  (worst-case search over JLCPCB basic parts). Result: R2 = 390k (120k+270k),
  R1a = 150k, R1b = 12k.
- `uvlo/uvlo_tlv431.tex` / `.pdf` — divider equations, tolerance analysis, the
  four design constraints, and why the feasible region is a thin sliver.
- `uvlo/10b_uvlo_latch.py` — worst-case DC checks of the latch itself,
  cross-checked automatically against the LTspice `.raw`.
- `uvlo/uvlo_latch.tex` / `.pdf` — latch circuit documentation (operating
  states, equations, simulation results, review items).
- Schematic/sim: `simulation/en_uvlo_lockoutv3_tlv.asc`.

## Repository layout

```
notebooks/      design notebooks 01–08 (cleaned, re-executed*)
uvlo/           UVLO latch: scripts, LaTeX docs + PDFs, figures
constants.py    single source of truth for specs & part database access
component_utils.py
data/           part databases (inductors, mosfets, capacitors) + analysis CSVs
measurements/   scope captures (fan load, pre-bias startup tests) + parquet cache
simulation/     LTspice (.asc/.net/.raw): UVLO latch v1–v3, input bounce tests
datasheets/     component datasheets
app_notes/      application notes (layout/EMI, gate resistors)
figures/        exported figures from the notebooks
archive/        superseded originals (old notebooks, UVLO iterations, old data)
```

\* 07 and 08 contain multi-minute simulations; their outputs are preserved from
the original runs (code cleaned & paths fixed). All other notebooks were
re-executed top-to-bottom.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows   (source .venv/bin/activate on Linux/Mac)
pip install -r requirements.txt
```

Notebooks assume the working directory `notebooks/` (they reference
`../data`, `../measurements`, and import `constants.py` from the repo root).
The LaTeX docs compile with plain `pdflatex` (siunitx optional — a fallback is
built in).

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
