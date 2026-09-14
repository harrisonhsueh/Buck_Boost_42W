# CLAUDE.md

Working notes for agents. Project narrative and results live in `README.md` — don't
duplicate them here. This file is conventions, invariants, and gotchas.

## What this repo is

Design record for a built board: LM5176 4-switch buck-boost, USB-C PD (5–20 V) → 12 V,
42 W, driving up to 10 PC fans. V1 is fabricated, assembled, and measured.

V1 parts were chosen from draft calculations made before the build. Current work fills
in missing data and makes those calculations more robust, as a check on the V1 choices.
V1 is the reference design; changes here are documentation and analysis, not redesign.

## Design invariants (do not silently change these)

- **V1 topology is frozen:** hard-switched 4-switch buck-boost. ZVS/resonant and
  multiphase-interleaved are explicitly out of scope for V1. Don't propose them as
  "improvements" inside V1 docs; they belong in the V2 / future-work section only.
- **Optimization objective 1 (active):** maximize efficiency at **Vin = 5 V, Iin = 3 A
  (15 W) boost**, part cost unconstrained. This is the source-limited corner, so
  converter loss directly subtracts from deliverable fan power. In boost mode
  I_L,avg = I_in = 3 A independent of efficiency.
- **Optimization objective 2 (planned, notebook 09):** total operational cost =
  BOM + electricity over the mission profile 1.5 W @ 95 %, 12.6 W @ 4 %, 42 W @ 1 %,
  at $0.20/kWh. Not yet implemented.
- Higher PD voltages (9/15/20 V) are **checked** for ripple, I_sat, and 42 W capability,
  not optimized.

## Data conventions

- `constants.py` is the single source of truth for specs and part-database access.
  Add a constant there rather than hard-coding a number in a notebook.
- `data/*.csv` are loaded **by column name**, never by position — appending columns is safe.
- `data/README.md` defines the price-column conventions (`Price_Ref_*` = distributor
  price for fair part-to-part comparison; `Price_Build_*` = LCSC/JLCPCB price actually
  paid for V1). Follow it exactly when adding rows.
- `data/inductor_losses_measured.csv` holds **hand-entered Würth REDEXPERT output**
  (`P_ac_mW`, `P_dc_mW`, `P_total_mW`, `dT_K`). The input columns (`Freq_kHz`,
  `Duty_pct`, `I_avg_A`, `dI_pp_A`) are computed for feeding the calculator.

  REDEXPERT cannot accept the exact operating point (duty is 2 decimals; current is
  1 mA below 1 A but only 10 mA at/above 1 A), so `Duty_entered` and `dI_pp_entered_A`
  hold the as-typed values next to the true ones. Type the `*_entered` values, and enter
  the true ripple rather than the ripple implied by the rounded duty — see the
  quantization section in `data/README.md` for the reasoning and the error budget.

## Evidence standard

Every quantitative or design claim (notebooks, README, docs, replies) must trace to
something checkable: measured data in `measurements/`, a datasheet (part number +
table/figure), REDEXPERT output, LTspice results in `simulation/`, or a calculation
in a notebook.

- Say which kind of source it is: measured, simulated, calculated, or datasheet
  typical/max. They are not interchangeable.
- If the support doesn't exist yet, say so ("not yet measured", "needs a REDEXPERT
  run at 9 V") and name the data or calculation that would settle it. Being unsure
  and saying so is better than a confident guess.
- If the completed analysis favors a different part than V1 used, report that plainly
  and record it as a V2 candidate. 
- **Never fabricate or interpolate a REDEXPERT loss number or a distributor price.**
  Both are looked up by hand. If a value is missing, leave it blank and say which rows
  need filling. A plausible-looking invented number is worse than an empty cell.

## Gotchas

- Notebooks assume the working directory is `notebooks/` (they reference `../data`,
  `../measurements`, and import `constants.py` from the repo root).
- **Do not re-execute `07_stability_compensation.ipynb` or `08_input_filter_redesign.ipynb`**
  — they contain multi-minute simulations and their stored outputs are preserved from the
  original runs. Other notebooks can be re-run top-to-bottom.
- `archive/` is superseded history kept for traceability. Read it; don't edit it.
- LaTeX in `uvlo/` compiles with plain `pdflatex` (siunitx optional, fallback built in).
- `simulation/` `.raw` files are LTspice output; `uvlo/10b_uvlo_latch.py` cross-checks
  its DC analysis against them.

## Notebook style

Each notebook opens with a markdown header: **Project / Purpose / Design basis (V1) /
Key result — decision / See also**, and closes with a `Final Conclusions` section that
states the chosen part and the reason. Keep that shape when editing.
