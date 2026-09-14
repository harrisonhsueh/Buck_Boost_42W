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
| `Price_Ref_1ku_USD` | Unit price in USD when buying 1,000 pcs. If there is no 1,000 break, use the highest break ≤ 1,000 (the price actually paid for a 1,000 pc order). Use the cut-tape price; if only full reels are sold, use the reel unit price. |
| `Price_Ref_Source` | `DigiKey`, or `Mouser` if DigiKey does not stock the part. Authorized distributors only. |
| `Price_Ref_URL` | Product page link, for traceability. |
| `Price_Ref_Date` | Date the price was read, `YYYY-MM-DD`. |

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
