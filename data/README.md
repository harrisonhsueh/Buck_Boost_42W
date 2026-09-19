# data/

Part databases and analysis inputs. Loaded by name (not column position), so new columns can be appended safely.

| File | One row per | Contents |
|---|---|---|
| `inductors.csv` | inductor part | electrical specs, SPICE-model values, size, price |
| `mosfets.csv` | MOSFET part | electrical/thermal specs from datasheet tables, test conditions, datasheet revision, price |
| `mosfet_figure_reads.csv` | part × quantity | values read by eye from datasheet *figures* (plateau voltage, C_oss integrals, curve points), with uncertainty |
| `capacitors.csv` | capacitor part | specs |
| `inductor_losses_measured.csv` | inductor part × operating point × fsw | manufacturer loss-calculator results (Würth REDEXPERT, Coilcraft Power Inductor Finder) |
| `efficiency_analysis.csv` | analysis output | — |
| `BOM-BUCK_BOOST_42W_V1P4_removed_nm - BOM-BUCK_BOOST_42W.csv` | line item (grouped designators) | **as-built BOM for the V1.4 board**, LCSC part numbers, `_removed_nm` = do-not-populate parts already stripped |

## As-built BOM

`BOM-BUCK_BOOST_42W_V1P4_removed_nm - BOM-BUCK_BOOST_42W.csv` is the BOM the V1.4 board was
actually assembled from — the ground truth for "what is on the board", as opposed to
`inductors.csv` / `mosfets.csv` / `capacitors.csv`, which are *candidate* databases for
comparing parts. Columns are `Comment, Designator, Footprint, LCSC, Quantity`; one row per
value/footprint group, with designators comma-separated inside the quoted field.

Things worth knowing when reading it against `constants.py`:

- **Output capacitance is split into two banks** either side of `R24`, a 0 Ω 0612 link in
  the output current-sense position (that sense channel is unused). 9 × 10 µF 1206 ceramics
  on one side, 4 × 4.7 mF radial electrolytics on the other. `constants.C_OUT_NOMINAL`
  already sums all 13 → 18.89 mF. Notebook 05 keeps their ESRs separate, which is the part
  that matters at 100 kHz.
- **17 × 10 µF 1206 are on the board in total** (`C13585`); only 9 are output bulk. Two more
  are input (`constants.C_IN_NOMINAL` = 4 × 47 µF + 2 × 10 µF); the rest are local decoupling.
- **Sense resistors:** `R22`+`R23` = 2 × 20 mΩ in parallel = the LM5176's 10 mΩ current
  sense (notebook 07). `R5`, `R7` = 1 mΩ, the input and fan-rail INA226 shunts. `R33`–`R42`
  = 10 mΩ, the ten per-fan shunts. `R8` and `R24` are spare/unused sense positions.
- **The fitted FET is `BSC0902NSI`** (`C534382`), matching `constants.ACTIVE_FET_ID` — not
  the `BSC0902NS` that the old parts table mis-listed as a 40 V part.

## Price columns (`inductors.csv`, `mosfets.csv`)

Two prices are kept because they answer different questions.

**Reference price** — used to compare candidate parts on equal terms.

| Column | Convention |
|---|---|
| `Price_Ref_50_USD` | Unit price in USD for a **50-board** build: the highest listed break ≤ 50 × (parts per board). Inductor: 1 per board, so break ≤ 50. MOSFET: 4 per board, so break ≤ 200 (DigiKey lists 100, then 500). Use cut tape (or tray, if that is the only packaging) — never a full-reel break. Never extrapolate a break that isn't listed. |
| `Price_Ref_Qty` | Quantity break the reference price was read at (e.g. `50` for an inductor, `100` for a MOSFET, or lower if the next break is above the 50-board quantity). |
| `Price_Ref_Source` | `DigiKey`, or `Mouser` if DigiKey does not stock the part. Authorized distributors only. |
| `Price_Ref_URL` | Product page link, for traceability. |
| `Price_Ref_Date` | Date the price was read, `YYYY-MM-DD`. |

Why 50 boards: part cost only matters above one-off quantities, so the reference (and the
Objective 2 BOM, notebook 09) is a 50-board batch, even if it is never built. It is still a
small batch, not a production volume. Real production pricing (1k+) comes from manufacturer
quotes, not catalog breaks — and catalog breaks for the inductors stop at 270–600 pcs, at
different quantities per part, so a "1ku" catalog price compares parts at unequal volume.
At 50-board quantities every candidate is past its single-piece handling markup (+14 % to +31 % at 1 pc,
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

## `mosfets.csv`

Every electrical/thermal value is copied from the **table** of the datasheet named in
`Datasheet_File` (in `datasheets/mosfets/`), revision in `Datasheet_Rev`. Rules:

- **Blank means the datasheet table does not give it.** Never fill a typical from a
  min/max midpoint, a max from a typical, or a value from a similar part. (Many
  Infineon parts give only VGS(th) min/max; EPC and GaN Systems give RthJC/RthJA
  without a max, so those cells stay blank and the value goes in `Data_Notes`.)
- **`_4.5V` / `_10V` columns are only for data taken at those gate voltages.** Data at
  another V_GS goes in `RDSon_Alt_*` / `Qg_Alt_*` with the voltage in `*_Alt_VGS(V)`
  (e.g. TPH1R104PB at 6 V, ISC230N10NM6 at 8 V, EPC2024 at 5 V, GS61008P at 6 V).
- **Test conditions that change the number are recorded:** `Cap_Test_VDS(V)` for
  `Coss_Typ` / `Qoss_Typ`, `VSD_Test_IF(A)`, `Qrr_Test_IF(A)` and `Qrr_Test_diFdt(A/us)`.
  Conditions that vary but matter less (RDS(on) test current, gate-charge V_DD, which
  side RthJC is measured on, RthJA board size) go in `Data_Notes`.
- `RthJA_Max` board conditions differ by manufacturer (Infineon 6 cm² one-layer;
  TI and AOS 1 in² 2 oz Cu), so compare it only within one manufacturer.
- `Technology` uses the manufacturer's own name. Infineon parts with no generation
  number on the product page (BSZ0901NS, BSZ0902NS, BSC0902NS/NSI) are `OptiMOS`.
- `Part_Number` is the orderable base part, not the reel suffix (`BSC014N04LS`, not
  `BSC014N04LSATMA1`).

Anything read from a datasheet **figure** does not go here; it goes in
`mosfet_figure_reads.csv` with the figure number, reading uncertainty and method.
Notebook 04 uses those reads only where the table has no value.

## `inductor_losses_measured.csv`

Inputs (`Freq_kHz`, `Duty_pct`, `I_avg_A`, `dI_pp_A`) are pre-computed for the manufacturers' loss calculators; outputs (`P_ac_mW`, `P_dc_mW`, `P_total_mW`, `dT_K`) are entered by hand. V1 design basis is `5V_3A_input`: Vin = 5 V, Iin = 3 A (boost mode, so I_L,avg = 3 A independent of efficiency), Vout = 12 V. Rows at 150/200/300 kHz exist for the 22/33/47 µH 2013 parts to check the fsw choice.

Column order is the same for every manufacturer: `Part_Number, Manufacturer, Series, Size_Code, …`, with `Part_Number` matching `inductors.csv` exactly (the notebook joins on it). `Source` holds the calculator URL, which identifies the tool:

| Manufacturer | Tool | Output resolution as entered |
|---|---|---|
| Würth Elektronik | REDEXPERT | 3 significant figures |
| Coilcraft | Power Inductor Finder | 1 mW, 1 K |

Both tools report `P_dc_mW` as I_L,avg² × typical DCR (checked in notebook 03), so `P_ac_mW` holds core loss plus the ripple's winding loss. The quantization section below applies to REDEXPERT; the Power Inductor Finder's input resolution has not been documented yet. TDK ERU 24 `B82559A0303A024` is not available in TDK's calculator.

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
