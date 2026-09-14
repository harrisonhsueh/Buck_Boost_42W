# data/

Part databases and analysis inputs. Loaded by name (not column position), so new columns can be appended safely.

| File | One row per | Contents |
|---|---|---|
| `inductors.csv` | inductor part | electrical specs, SPICE-model values, size, price |
| `mosfets.csv` | MOSFET part | electrical/thermal specs, price |
| `capacitors.csv` | capacitor part | specs |
| `inductor_losses_measured.csv` | inductor part × operating point × fsw | Würth REDEXPERT loss results |
| `efficiency_analysis.csv` | analysis output | — |

## Price columns (`inductors.csv`, `mosfets.csv`)

Two prices are kept because they answer different questions.

**Reference price** — used to compare candidate parts on equal terms.

| Column | Convention |
|---|---|
| `Price_Ref_50_USD` | Unit price in USD for a 50 pc order: the highest listed break ≤ 50. Use cut tape (or tray, if that is the only packaging) — never a full-reel break. Never extrapolate a break that isn't listed. |
| `Price_Ref_Qty` | Quantity break the reference price was read at (e.g. `50`, or `25` if the next break is above 50). |
| `Price_Ref_Source` | `DigiKey`, or `Mouser` if DigiKey does not stock the part. Authorized distributors only. |
| `Price_Ref_URL` | Product page link, for traceability. |
| `Price_Ref_Date` | Date the price was read, `YYYY-MM-DD`. |

Why 50 pcs: this is a DIY board, so the reference is a realistic small batch (boards built
for others), not a production volume. Real production pricing (1k+) comes from manufacturer
quotes, not catalog breaks — and catalog breaks for the inductors stop at 270–600 pcs, at
different quantities per part, so a "1ku" catalog price compares parts at unequal volume.
At 50 pcs every candidate is past its single-piece handling markup (+14 % to +31 % at 1 pc,
varying by part) and is still on cut tape or tray. Decisions that depend on price should be
checked at 1 pc and at the highest catalog break too — the ranking can change with quantity
(e.g. Würth litz `74437429203xxx` is cheaper than TDK ERU 24 at 1 pc, but dearer at 50 pc).

**Build price** — what the V1 board actually cost through JLCPCB assembly; explains the V1 choices.

| Column | Convention |
|---|---|
| `Price_Build_USD` | LCSC unit price in USD at `Price_Build_Qty`. Blank if not stocked at LCSC. |
| `Price_Build_Qty` | Quantity break the build price was read at (the quantity actually ordered). |
| `LCSC_PN` | LCSC part number (`C…`), as used in the JLCPCB BOM. |
| `Price_Build_Date` | Date the price was read, `YYYY-MM-DD`. |

JLCPCB's one-time extended-part fee (per unique part, per order) is not included in `Price_Build_USD`.

## `inductor_losses_measured.csv`

Inputs (`Freq_kHz`, `Duty_pct`, `I_avg_A`, `dI_pp_A`) are pre-computed for the Würth REDEXPERT calculator; outputs (`P_ac_mW`, `P_dc_mW`, `P_total_mW`, `dT_K`) are entered by hand. V1 design basis is `5V_3A_input`: Vin = 5 V, Iin = 3 A (boost mode, so I_L,avg = 3 A independent of efficiency), Vout = 12 V. Rows at 150/200/300 kHz exist for the 22/33/47 µH 2013 parts to check the fsw choice.

### Calculator input precision (REDEXPERT quantization)

REDEXPERT cannot accept the exact operating point, so the table records both the
physically correct value and the value actually typed in.

| Field | Tool resolution | Column pair |
|---|---|---|
| Duty cycle | 2 decimals of a fraction (`0.58`) | `Duty_pct` -> `Duty_entered` |
| Current, < 1 A | 1 mA (mA field) | `dI_pp_A` -> `dI_pp_entered_A` |
| Current, >= 1 A | 10 mA (amps field, 2 decimals) | `dI_pp_A` -> `dI_pp_entered_A` |

`Duty_pct` / `dI_pp_A` are the true computed operating point; `Duty_entered` /
`dI_pp_entered_A` are what to type, so any result can be reproduced exactly. Type the
`*_entered` values.

**Enter the true ripple, not the ripple implied by the rounded duty.** Ripple amplitude
sets the flux swing directly (dB = L*dI/(N*Ae)) and core loss goes as dB^beta with
beta ~ 2-3, so dI is first-order; duty only shapes waveform asymmetry, a second-order
correction. Back-computing dI from the rounded duty would add ~0.6% dB error to chase
consistency in the field that matters least.

Note the amps field is the coarse one: 884 mA is enterable exactly, but as amps it
would round to 0.88 A (0.45% error). At the V1 design point (5 V in, 12 V out, 100 kHz,
D = 0.5833) the candidate inductors that matter -- 33 uH (884 mA) and 47 uH (621 mA) --
fall below 1 A and get the precise field. Only the low-inductance parts, already
rejected on ripple, are forced into the coarse field.

**Total error budget:** duty rounding 0.57%, dI rounding <= 0.32% on any surviving
candidate, so under ~1% on core loss. Comparisons of interest span factors of 2 or more,
so this quantization affects reproducibility, not conclusions.
