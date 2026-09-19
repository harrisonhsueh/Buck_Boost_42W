# TODO — Buck_Boost_42W

Working list, opened 2026-09-18. Scope: close the open items in the V1 design record,
verify and build the UVLO lockout latch, and take the measurements the notebooks say
would settle their weakest claims.

Conventions: `[ ]` open, `[x]` done, `[~]` in progress. Each item names the file it
touches and what evidence would close it, per the evidence standard in `CLAUDE.md`.
**P** marks items that block the 45-minute presentation.

---

## 0. Corrections — things the repo states wrongly today

- [x] **P — EN/UVLO divider values are stale in README and presentation.**
  `README.md:106` and `presentation.md:501` both say *R2 = 390 k (120 k + 270 k),
  R1a = 150 k, R1b = 12 k*. The actual search result is **R2 = 420 k (120 k + 300 k
  series), R1a = 150 k, R1b = 15 k** — `uvlo/10a_uvlo_resistor_search.py:68`,
  `uvlo/uvlo_tlv431.tex:53,329`, and the schematic `simulation/en_uvlo_lockoutv3_tlv.asc`
  all agree on 420/150/15 k. Fix both documents to match 10a.
- [ ] **P — Decide what slide 27 and the README photo caption are allowed to claim.**
  `presentation.md:529` says the rework wire near EN/UVLO *is* this latch and that the
  board "starts reliably across the PD range"; `README.md:13` repeats it. The latch is
  not built yet (§2 below). Either the wire is the input-filter rework from notebook 08
  and the caption is wrong, or the claim is written forward-looking. Settle it and make
  both files say what is true on the day.
- [ ] **`DRAWN` dict in `uvlo/10b_uvlo_latch.py:152` does not match the schematic.**
  It carries R3 = 15 k, R8 = 22 k, R9 = 10 k, R10 = 810 Ω; the `.asc` is at R3 = 130 k,
  R8 = 2 M, R9 = 2.2 k, R10 = 39 k. It is dead code (`V = RECOMMENDED`), so this is a
  trap for the next reader, not a live bug — update it or delete it.
- [ ] **R10 comment contradicts the chosen value.** `uvlo/10b_uvlo_latch.py:161-165`
  derives *R10 ≤ 44.4 k → largest basic = 39 k*, but `RECOMMENDED` sets R10 = 47 k and
  all 21 checks pass at 47 k. One of the two is wrong. Re-derive the Q2-off residual
  bound and fix whichever it is — this is a value that gets ordered.

---

## 1. Design checks — recheck

- [ ] **Re-run every notebook that is allowed to be re-run** (00–06, 11) top-to-bottom
  after the constants/data changes, and confirm no stored output moved.
  Do **not** re-run 07 or 08 (multi-minute sims, outputs preserved — `CLAUDE.md`).
- [ ] **Re-run `uvlo/10b_uvlo_latch.py`** after the §2 schematic edits. Current state:
  21 checks, 0 FAIL, 2 WARN (the 59–61 µA I_KA razor, and the onsemi-only vendor note).
- [ ] **Startup-race margin is thin.** Check B2 passes at 50 °C with only **37 mV**
  (374 mV at 0 °C, 205 mV at 25 °C). Decide whether 37 mV over the Vbe box is enough to
  build, or whether R3 should move. This is the check most likely to bite on hardware.
- [ ] **30 V FET margin at 20 V in** (`README.md` gap 4). BSC0902NSI is a 30 V part; V1
  was chosen believing it was 40 V. Needs the switch-node measurement in §5 to close.
- [ ] **Confirm the LM5176 MODE setting on V1** (forced PWM vs diode emulation) from the
  schematic/BOM. Notebook 11 lists it as the unknown that decides the light-load model.
- [ ] **Confirm the TPS563201 absolute-max input voltage from its datasheet** — not in
  the repo (`presentation.md:915`). If it is below the output TVS clamp, the TVS is set
  by the housekeeping buck, not by the fans.
- [ ] **Read the LM5176 bootstrap refresh mechanism** in `datasheets/controllers/lm5176.pdf`
  before being asked about deep-boost operation (backup slide B1).

---

## 2. Latch: verify → order → build → measure

**Verify (desk)**

- [ ] Close §0 items 3 and 4 (the `DRAWN` dict and the R10 bound).
- [ ] **Update `simulation/en_uvlo_lockoutv3_tlv.asc` to the final values.** 10b reports
  the remaining deltas itself: **R9 2.2 k → 1.5 k (2 × 3 k parallel), R10 39 k → 47 k.**
  The EN/UVLO divider in the `.asc` is already at 420/150/15 k and needs no change.
- [ ] Re-run the LTspice transient, regenerate `uvlo/figures/uvlo_latch_sim.png`, and
  re-run `10b_uvlo_latch.py` so the automatic `.raw` cross-check passes on final values.
- [ ] Rebuild `uvlo/uvlo_latch.pdf` and drop the "simulated circuit still carries two
  intermediate values" paragraph once the `.asc` matches.
- [ ] **Open safety item (`uvlo/uvlo_latch.tex:342`):** confirm by bench and simulation
  that LM5176 pre-biased startup performs no reverse energy transfer for Vout below the
  arm point. The concern is a boost into the 90× smaller input bank
  (Cout ≈ 18.9 mF vs Cin ≈ 0.21 mF → ≈ 34 V against 35 V input electrolytics). Until
  measured, the low-Vout band stays a documented, accepted exposure.

**Order**

- [ ] **Draw the latch BOM** from `RECOMMENDED` in `uvlo/10b_uvlo_latch.py:169`:
  R3 130 k, R4 300 k, R5 82 k, R6 1 k, R7 30 k, R8 2 M, R9 2 × 3 k parallel,
  R10 47 k, R11 100 k, R12 100 k, plus the EN/UVLO divider 120 k + 300 k / 150 k / 15 k,
  the three BJTs, and U1.
- [ ] **U1 must be the onsemi TLV431 (Vka max 16 V) — the TI part (6 V) will not work.**
  Check G1 shows keeping Vk ≤ 6 V would require a dearm point ≥ 18.3 V, above Vout_max.
  Mark it on the BOM so it cannot be substituted.
- [ ] Confirm every resistor is still a JLCPCB basic part / in stock, or note the
  substitution and re-run the worst-case search.
- [ ] Place the order. Buy spares of the small-value parts — this goes on as rework.

**Build**

- [ ] Build the latch as rework on the V1 board.
- [ ] Bench-verify the states against the simulated sequence in `uvlo/uvlo_latch.tex`:
  **arm** (VB3 clamps ≈ 0.64 V), **engage** (EN clamps at Vin ≈ 3.47 V), **hold**
  (EN ≤ 10 mV through a full Vin re-application at Vout = 12 V), **release** (at
  Vout ≈ 1.08 V, predicted band 1.0–1.8 V), **dearmed** (Vref ≈ 1.88 V while running).
- [ ] Measure the dearmed quiescent draw and compare to the predicted **6.9 mA / 83 mW**
  (check D3). At the mission profile this sits alongside the 5 V buck's 0.44 W as a
  constant term — worth having a measured number.
- [ ] **P — Before/after pre-bias startup scope capture** for slide 27
  (`presentation.md:533`). This is the payoff shot for Act 4.

---

## 3. Notebook cleanup

`CLAUDE.md` notebook style: header with **Project / Purpose / Design basis (V1) /
Key result — decision / See also**, and a closing `Final Conclusions`. Current state:

| Notebook | Missing header fields | `Final Conclusions` |
|---|---|---|
| 00, 01, 03, 04, 11 | — | yes |
| `02_fan_load_analysis` | Design basis, Key result, See also | **no** |
| `05_output_input_capacitors` | Design basis | **no** |
| `06_ripple_analysis` | Design basis, Key result | **no** |
| `07_stability_compensation` | Design basis, Key result | **no** |
| `08_input_filter_redesign` | Design basis, Key result | **no** |

- [ ] **02** — full header + Final Conclusions. Worst of the five.
- [ ] **05** — add Design basis + Final Conclusions.
- [ ] **06** — add Design basis, Key result, Final Conclusions.
- [ ] **07** — same. **Markdown cells only — do not re-execute.**
- [ ] **08** — same. **Markdown cells only — do not re-execute.**

---

## 4. Test setup

- [ ] **Enclosure rig for the fan-load rerun.** Ten P14 Pro behind two Filtrete 1900
  filters in a representative enclosure — the arrangement the unit actually uses.
  This is the rig that closes the repo's single biggest caveat (§5.1).
- [ ] **Switch-node probing setup.** Short ground spring, known attenuation, bandwidth
  recorded. Notebook 11 names SW1/SW2 as the first measurement to take.
- [ ] **Thermal imaging setup** — camera, emissivity, a run long enough to settle.
- [ ] **Per-fan harness:** one fan per header, so the ten INA226 channels resolve
  per-fan current and speed spread.
- [ ] **Fan-start stagger (firmware).** All ten fans share one PWM duty and start
  together at ~6 %, which tripped the 3 A input limit three times on 2026-09-15
  (`measurements/efficiency/README.md`). Staggering the ten PWM pins is firmware-only
  and also removes a real input-current spike on a 5 V / 3 A source.
- [ ] **Record probe attenuation and stop conditions** in the capture metadata — the old
  stop capture's attenuation, and whether the stop was PWM-commanded or a supply
  removal, were not recorded (`presentation.md:848`).

---

## 5. Measurements

Ordered by how much each closes.

- [ ] **P — 1. One full ramp with the fans enclosed** (15 V or 20 V). Every load number
  in the repo is open-air, at a different point on the fans' P-Q curve than the finished
  unit. The direction of the shift should not be assumed. Closes notebook 00 §7 and the
  README caveat; then update the mission profile and presentation slides 6, 7, 33.
- [ ] **2. SW1 and SW2 waveforms at 20 V and 5 V.** Notebook 11's first-named
  measurement. Gives real transition times against the model's 5.5 ns (the unexplained
  0.10–0.25 W would need 59–86 ns of V–I overlap), *and* answers the 30 V FET margin
  question from `README.md` gap 4. Two open items, one capture.
- [ ] **3. One fan per header** — per-fan current and speed spread. Also settles the
  3/4/1 vs 4/5/1 fan-count-per-header question in the efficiency README.
- [ ] **4. Thermal image at 20 V / 36 W and at 5 V / 3 A** — which parts actually run hot.
- [ ] **5. Rail ripple current of the running fan array**, to replace the single-fan
  estimate used to rule out capacitor ESR in notebook 11.
- [ ] **6. Confirm the fan model** used in the 10-fan runs (count is confirmed at ten;
  model is not — notebook 00 §7.3).
- [ ] **7. Clean converter-cut experiment:** cut the converter at full speed and watch
  Vout and input current together, for the backup-slide regeneration argument.
  Not yet done.
- [ ] **8. Anemometer traverse at the filter face** at both settings. Every CFM figure
  in notebook 00 is a web calculator's output, never an observation. Lowest priority —
  notebook 00 §7.2 accepts this deliberately rather than resolving it.

---

## 6. Data gaps — hand-entered lookups

Never fabricate or interpolate these (`CLAUDE.md`). Blank is better than invented.

- [ ] **REDEXPERT / Coilcraft loss data: 39 of 63 rows in
  `data/inductor_losses_measured.csv` have no `P_total_mW`.** All are at the
  `5V_3A_input` point. Priority rows: **TDK ERU 24 `B82559A0303A024`** (notebook 03 says
  it could still beat the V1 part if its AC loss is under 89 mW), **SPM12565VT-220M-D**
  (the cheap candidate, $2.78 vs $6.45), the 68 µH HCF 2920 round-wire part, and the
  100 µH+ litz parts.
- [ ] **REDEXPERT runs for 7443634700 at 9, 15 and 20 V** (notebook 11 item 4) — the V1
  part is only characterised at the 5 V point.
- [ ] **Reference prices: `data/inductors.csv` has 10 of 78 rows priced**, `mosfets.csv`
  3 of 20. Objective 2 cannot run without them. Price for a 50-board build per
  `data/README.md`. Fill at least every part that is a live candidate in 03 or 04.
- [ ] **`Price_Ref_URL` is filled for only 2 of 10 priced inductors and 1 of 3 MOSFETs.**
  Backfill so the prices are re-checkable.
- [ ] **`data/capacitors.csv` has 2 rows and no price columns at all.** Decide whether
  capacitors enter Objective 2; if yes, add the price columns per `data/README.md`.
- [ ] Reconcile the new `data/BOM-BUCK_BOOST_42W_V1P4_removed_nm - BOM-BUCK_BOOST_42W.csv`
  against the part databases, and give it a shorter filename.

---

## 7. New analysis

- [ ] **`notebooks/09_operational_cost.ipynb` — Objective 2.** Does not exist yet.
  BOM (50-board `Price_Ref_50_USD`) + electricity over the mission profile at $0.20/kWh.
  **Use the measured profile from notebook 00** — 4.3 W @ 95 %, 14.0 W @ 4 %,
  35.9 W @ 1 %, averaging 5.0 W — not the archived `42 W × duty³` figures. Blocked on §6
  prices. Expected to be BOM-dominated and to disagree with Objective 1; say so
  explicitly rather than picking a winner silently.
- [ ] **Analyse the 5 V housekeeping buck.** Constant **0.44 W measured**, 10 % of the
  load at the quiet setting, never scales down, never analysed in V1. At the mission
  profile's weighting it outweighs every power-stage part difference in 03 and 04.
  Currently a V2 item with no home in the repo.
- [ ] **Add a realistic switching term to the loss model** before choosing parts on
  14–84 mW differences (notebook 11's decision). Blocked on measurement §5.2.
- [ ] **Electrolytic life calculation** for the 4 × 4.7 mF bulk bank — named in the Q&A
  prep as a "more time or budget" item, not done.
- [ ] **Conducted-emissions scan** — same list, not done.

---

## 8. Presentation

- [ ] **P** — §0 items 1 and 2 (stale divider values; slide 27's build claim).
- [ ] **P** — Export notebook 02's commutation-zoom and startup-ramp plots to `figures/`
  (`presentation.md:314`).
- [ ] **P** — Export one ripple-vs-Vin figure from notebook 06 to `figures/`
  (`presentation.md:398`).
- [ ] **P** — Before/after pre-bias startup capture for slide 27 (§2).
- [ ] Fix the regeneration argument on backup slide B2: the stored-energy version does
  not survive a ½Jω² check (≈ 20 J of rotor energy vs 1.36 J in Cout). The correct
  argument is that the return path conducts only while back-EMF exceeds the rail, and
  the kinetic energy leaves as air movement over ≈ 0.6 s (`presentation.md:810`).
- [ ] Decide whether to cut slides 19 and 21 for time — the running budget is 39 + 10
  against a hard 45.
- [ ] After the enclosure measurement lands, update slides 6, 7 and 33.

---

## 9. Repo hygiene

- [ ] **Commit the untracked work:** `notebooks/00_design_goals.ipynb`,
  `notebooks/11_efficiency_measured_vs_model.ipynb`, `presentation.md`, the seven new
  `figures/*.png`, the new datasheets, and the 2026-09-15 `151555`/`151955` runs.
  These are the two newest notebooks and they are not in git.
- [ ] Three capacitor datasheets show as deleted and re-added under LCSC part numbers —
  confirm that rename is intended before committing.
- [ ] Add notebook 09 and the 5 V buck analysis to the design-flow table in `README.md`
  once they exist.
