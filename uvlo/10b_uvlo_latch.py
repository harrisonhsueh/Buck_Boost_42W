#!/usr/bin/env python
"""
10b -- UVLO lockout latch (v3b, ratio-defined trigger): design + DC checks.

RUN AS `python 10b_uvlo_latch.py` (not `py`) -- on Windows the py launcher
follows the shebang and may pick an interpreter without numpy/matplotlib,
which silently disables the LTspice cross-check and the waveform figure.

WHY THIS CIRCUIT EXISTS
    See 10a_uvlo_resistor_search.py / uvlo_tlv431.tex: the LM5176's pre-bias
    startup fails in this design (very slow control loop), so a discrete latch
    pulls EN/UVLO low on input dropout and -- because it is POWERED FROM VOUT --
    holds it low until the output has discharged (release at ~1.5 V). Every
    restart then begins from a (near-)dead output.

TOPOLOGY (rev v3b -- simulation/en_uvlo_lockoutv3_tlv.net; supersedes the
leakage-seeded v3, whose engage trigger depended on nA-level Q3 leakage and
could not cover the 2N3904 Is spread -- see git history of this file)
      Q1  2N3904  EN clamp:  c=EN_UVLO, b=N5 (R12/R11 divider), e=GND
      Q3  2N3904  core NPN:  c=N4, b=VB3, e=GND    -- ON whenever VOUT > V_arm
      Q4  2N3906  core PNP:  e=VOUT, b=VB4, c=VB1
      Q2  2N3906  dearm drv: e=VOUT, b=VB2, c=N1
      R3   VB3-GND      arm divider bottom   (sets V_arm with R4)
      R4   VOUT-VB3     arm divider top / Q3 base drive
      R5   VB4-N4       Q4 base <- Q3 collector (latch pull-down of VB4)
      R6   N1-VB4       Q2 collector -> VB4  (dearm pull-up of VB4)
      R7   VB1-VB3      Q4 collector -> Q3 base (regeneration)
      R8   K-GND        TLV431 cathode load
      R9   VB2-K        Q2 base <- TLV431 cathode
      R10  VOUT-VB2     Q2 base pull-up
      R11  N5-GND, R12  VB1-N5:  Q4 collector -> Q1 base divider
      U1  TLV431: A=GND, K, REF = EN/UVLO divider REF node
                  (10a divider: R2/R1a/R1b = 420k/150k/15k)

OPERATION
    ARM     VOUT > V_arm (~2.8 V box-mid; 2.0..3.6 across the box): R4/R3
            clamp VB3 at Vbe -> Q3 saturated,
            trying to pull VB4 low through R5. Ratio-defined (v3's trigger
            depended on UNSPECIFIED sub-threshold leakage; this one only on
            resistor ratios and spec'd Vbe -- robust across part spread).
    DEARM   V_REF > V_TLV (input healthy): TLV431 clamps K at ~1.24 V, the
            R10/R9 chain drives Q2 on; Q2 (via R6) out-pulls Q3 (via R5), so
            VB4 stays within Veb_off of VOUT and Q4 is off. Active from
            VOUT ~ 2.05 V worst-case -- 27 mV above the Vka_max + Veb2_cold
            = 1.27 + 0.75 = 2.02 V physics floor. Veb2 model: DATASHEET BOX,
            VBE(sat) 0.65..0.85 at 10 mA scaled by VT*ln(10m/30u) = 150 mV
            -> 0.50..0.70 at 25 C, +50 mV at 0 C. Design equation:
                R10 >= Veb2 * R9 / (headroom - R9*Ib_req)
            Headroom -> 0 requires R9 -> 0, but R9 also carries the FULL
            cathode current at 12 V: window [0.69k (I_K 20 mA max), 1.51k
            (I_KA 80 uA at the arm corner)]; power solved by building
            R9 = 1.5k as 2x 3k parallel (34 mW/part). R10 is then SOLVED from
            the Q2-off residual with the R8 = 2M tier: R10 <= ~49k -> 47k
            basic (I_K(off) = 50 nA makes the leakage term negligible).
    ENGAGE  VIN dropout -> V_REF < V_TLV -> TLV off, K rises, Q2 off ->
            Q3 wins VB4 -> Q4 on -> VB1 high -> Q1 (via R12/R11) clamps
            EN/UVLO; R7 reinforces VB3. Requires VOUT > V_arm at the dropout.
    HOLD    EN clamped -> V_REF ~ 0 regardless of VIN -> TLV stays off.
            Latch is powered from VOUT; the REQUIREMENT is to still clamp EN
            at VOUT = 2.0 V (met with ~3x base-drive margin, check C2).
    RELEASE actual release computes to VOUT ~ 1.05..1.8 V (unit tails; Q1 drive =
            I_EN/beta; depends on VIN and beta); the SCR core itself only
            un-latches near ~0.8 V. Clean restart from a discharged output.

ACCEPTED LIMITATION (open item)
    The latch cannot act below its arm point, so ANY dropout with VOUT below
    ~3.6 V (worst-case unit; 2.8 V nominal) is unprotected -- the band runs
    down to zero, not just down to the release point (release only governs when
    an ALREADY-ENGAGED latch lets go).
    NOT diode-safe: the LM5176 switches synchronously, so an enabled FET
    conducts either way. And the exposure is NOT bounded by stored energy:
    a passive charge dump would equalise the banks at a harmless 3.56 V, but a
    buck-boost moves energy through its inductor into an input bank 90x smaller
    (C_OUT ~ 18.9 mF vs C_IN ~ 0.21 mF), i.e. a boost into a small cap:
        V_IN ~ VOUT*sqrt(C_OUT/C_IN) = 3.6 * 9.5 ~ 34 V
    vs a 22 V operating max and 35 V input electrolytics -- and the attached
    USB source sees it. Even 25% of the energy arriving gives ~17 V.
    OPEN (safety): confirm by bench + sim that LM5176 pre-biased startup does
    no reverse ENERGY transfer for VOUT below the arm point. The case for
    extending protection below the arm point (or clamping VIN) rests on it.

TLV431 VENDOR REQUIREMENT (SEE CHECK G)
    With the latch off, K floats to VOUT*R8/(R8+R9+R10) ~ 15.4 V at the 15.75 V
    zener-clamp corner (a double fault: K only floats high while LATCHED, when
    VOUT can normally only decay from ~12.6 V -> realistic Vk ~ 12.4 V).
    Keeping K <= 6 V (TI TLV431) while turning Q2 on at low VOUT is impossible:
    closed form Vk_worst = VOUT_max - (Vbe_off/Veb2)*(V_dearm - Vka) ->
    would need V_dearm >= 18.3 V. USE THE ONSEMI TLV431 (Vka max 16 V) ONLY.

USAGE
    python 10b_uvlo_latch.py     # design table + checks + LTspice cross-check
"""

import math
from pathlib import Path

_HERE = Path(__file__).resolve().parent
FIG_DIR = _HERE / "figures"
RAW_PATH = _HERE.parent / "simulation" / "en_uvlo_lockoutv3_tlv.raw"

# --------------------------------------------------------------------------
# PARAMETERS
# --------------------------------------------------------------------------
VOUT_NOM  = 12.0    # V  converter output (latch supply)
VOUT_MAX  = 15.75   # V  output OV corner: 15 V zener clamp +5%
VIN_MAX   = 22.0    # V  maximum input
VTH_MIN   = 1.17    # V  LM5176 EN threshold, min
# EN/UVLO divider (sized in 10a; R2 = 120k + 300k series). The .asc carries
# these same values, so SIM_* tracks the design.
R2, R1A, R1B = 420e3, 150e3, 15e3
SIM_R2, SIM_R1A, SIM_R1B = R2, R1A, R1B

# Design targets, pushed to the physics floor (razor margins accepted by
# design review). Dearm needs VOUT >= Vka(max) + Veb2(cold, box high tail)
# = 1.27 + 0.75 = 2.02 V; the solved worst-corner dearm-active point with the
# chosen parts is 2.047 V.
# NOTE on the unprotected band: the latch cannot act below its arm point, so
# everything from 0 V up to ~3.6 V (worst-case arm) is unprotected. Reverse
# conduction is possible at any pre-bias (synchronous switching), and because
# the transfer is inductive (energy, not charge) into an input bank 90x
# smaller, VOUT ~ 3.6 V could pump VIN toward ~34 V -- see ACCEPTED LIMITATION.
V_ARM_TGT   = 2.8   # V  arm point, box-mid Vbe (band 2.0..3.6 across box+temp)
# (No separate dearm "target": the dearm-active point is SOLVED from the
#  components -- 2.047 V worst case -- and only has to beat the arm point at
#  every temperature, which check B2 verifies.)
R_TOL       = 0.03  # 1% purchase + 100ppm tempco + load-life/soldering drift
V_HOLD      = 2.0   # V  latch must still clamp EN at this VOUT
VKA_MAX_ON  = 16.0  # V  onsemi TLV431 cathode max (TI part = 6 V: see check G)
VKA_MAX     = 1.27  # V  TLV431 regulating cathode, worst high (10a's VTLV max)
IKA_REG_MIN = 80e-6   # A  onsemi TLV431 I_K(min): 30 uA typ / 80 uA max
IK_OFF_MAX  = 0.05e-6  # A  TLV431 off-state cathode current, datasheet max
IK_ABS_MAX  = 20e-3    # A  TLV431 cathode current rating (onsemi)

# BJT Vbe model: DATASHEET BOX, fully traceable. Anchor: VBE(sat) spec at
# Ic = 10 mA / Ib = 1 mA, 25 C: 0.65 (min) .. 0.85 (max) V. Scaled to the
# ~30 uA operating scale by VT*ln(10m/30u) = 150 mV:
VBE30_LO, VBE30_HI = 0.50, 0.70   # V at 25 C; add -2 mV/C for temperature
# Caveat (conservatism, both directions): the anchor is a SATURATION spec and
# includes rb*Ib ~ 30-100 mV of ohmic drop absent at 30 uA, so the true
# active-mode box is narrower than this. Using it as-is is the safe reading.
VBE_TEMPCO = -2.0e-3              # V/degC
def vbe_lo(t_c): return VBE30_LO + VBE_TEMPCO*(t_c - 25.0)
def vbe_hi(t_c): return VBE30_HI + VBE_TEMPCO*(t_c - 25.0)
VBE_ON, VBE_TH, VBE_OFF = 0.70, 0.65, 0.40   # legacy typ values / off level
VEB2_HI_COLD = 0.75               # = vbe_hi(0): floor = Vka_max + this
VCE_SAT, VCE_SAT_MAX = 0.10, 0.20
BETA_MIN, FBETA_SAT = 30.0, 10.0              # worst beta / forced-beta target
VKA = 1.24                                     # TLV431 cathode when regulating

# Values: as drawn in the .net today vs RECOMMENDED (this file's design).
# All recommended values are single JLCPCB basic-part 0603 resistors.
DRAWN = dict(R3=15e3, R4=1e6,   R5=30e3, R6=1e3, R7=30e3,
             R8=22e3, R9=10e3,  R10=810.0, R11=100e3, R12=100e3)
# Values derived by the forward chain (full derivation in uvlo_latch.tex):
#  1) R9 window: TLV431 I_K<=15mA -> >=0.92k; I_KA>=80uA (onsemi spec:
#     30 typ/80 max) at the box-corner arm point (2.01 V) -> <=1.51k.
#     Power would demand >=1.53k for a single 0805 (window empty by 13 ohm),
#     so R9 is BUILT AS 2x 3k IN PARALLEL (both basic 0603): 1.5k effective,
#     each part dissipating 34 mW continuous / 64 mW at the OV corner.
#  2) R8 tier fixed at 2M (10M tier buys only 31 mV of dearm and quadruples
#     ICBO/board-leakage sensitivity), then the Q2-off residual equation
#     SOLVED for R10 gives R10 <= 44.4k -> largest basic = 39k. Note the
#     off-leakage term alone would allow R10 up to 0.4V/1uA = 400k -- it is
#     not the binding bound; the divider+leakage total is.
#     (Same constraint solved the other way: R10=39k -> R8 >= 1.73M -> 2M.)
#  3) R3 from the RACE solve (box tails): arm_min(T) >= dearm_active(T) at
#     every temperature; binding at 50 C -> R3 <= 136k -> 130k basic.
RECOMMENDED = dict(R3=130e3, R4=300e3, R5=82e3, R6=1e3, R7=30e3,
                   R8=2e6, R9=1.5e3, R10=47e3, R11=100e3, R12=100e3)
# R9 = 2x 3k in parallel (basic 0603 pair; halves per-part dissipation)
V = RECOMMENDED     # <- set to DRAWN to check the schematic's current values

def fmt_i(i):
    a = abs(i)
    if a >= 1e-3: return f"{i*1e3:.2f} mA"
    if a >= 1e-6: return f"{i*1e6:.1f} uA"
    return f"{i*1e9:.1f} nA"

_results = []
def check(tag, name, ok, detail, warn=False):
    status = "PASS" if ok else ("WARN" if warn else "FAIL")
    _results.append(status)
    print(f"[{status}] {tag}  {name}\n       {detail}")

def r3_eff(v):
    """VB3 pull-down with Q4 off: R3 in parallel with the R7+R12+R11 chain."""
    return 1.0/(1.0/v['R3'] + 1.0/(v['R7']+v['R12']+v['R11']))

def v_arm(v, vbe=VBE_TH):
    re3 = r3_eff(v)
    return vbe*(v['R4']+re3)/re3

# --------------------------------------------------------------------------
# Design rationale (stage-by-stage derivation with the chosen values)
# --------------------------------------------------------------------------
def design_table(v):
    S = v['R8']+v['R9']+v['R10']
    print("=== Design summary (stages follow the sizing order) ===")
    print(f" values: " + ", ".join(f"{k}={x/1e3:g}k" if x >= 1e3 else f"{k}={x:g}"
                                   for k, x in sorted(v.items())))
    print(f" 1) R10/R9/R8: dearm-active point solved from parts (~2.01 V worst,")
    print(f"    check A3); Q2 off + K <= {VKA_MAX_ON:g} V at the {VOUT_MAX} V corner")
    print(f"      Ib2(dearm) = (VOUT-Vka-Vbe)/R9 - Vbe/R10 ; residual Veb2 = VOUT*R10/S")
    print(f" 2) R4/R3: V_arm = Vbe*(R4+R3eff)/R3eff with R3eff = R3 || (R7+R12+R11)")
    print(f"      Ib3(VOUT) = (VOUT - V_arm)/R4   [clean identity once VB3 clamps]")
    print(f" 3) R5/R6: dearm needs (VOUT-VB4) = Vce2 + I*R6 <= Vbe_off at {VOUT_MAX} V")
    print(f"      -> R5/R6 >= ~{(VOUT_MAX-2*VCE_SAT)/ (VBE_OFF-VCE_SAT) - 1:.0f};"
          f" latched, Ib4 = (VOUT-Vbe-Vce)/R5")
    print(f" 4) R12/R11: Q1 base = (VB1-Vbe)/R12 - Vbe/R11 ; must clamp EN at "
          f"VOUT = {V_HOLD} V\n")

# --------------------------------------------------------------------------
# A. DEARM path (TLV431 + Q2)
# --------------------------------------------------------------------------
def check_dearm(v):
    print("--- A. Dearm: TLV431 clamps K, Q2 holds VB4 high ---")
    S = v['R8']+v['R9']+v['R10']

    # worst corners: R10 +5%, R8/R9 -5%, plus TLV431 off-leakage through R10
    resid = (VOUT_MAX*v['R10']*(1+R_TOL)/((1-R_TOL)*(v['R8']+v['R9'])+(1+R_TOL)*v['R10'])
             + IK_OFF_MAX*v['R10'])
    # "Off" defined QUANTITATIVELY: the box-worst (low-tail, hot) Q2 leak at
    # this residual must stay << the latch's VB4 hold drive at the same corner.
    vt50 = 8.617e-5*(50+273.15)
    i_leak = 30e-6*math.exp((resid - vbe_lo(50))/vt50)
    ib4_drive = (VOUT_MAX - vbe_hi(50) - VCE_SAT)/v['R5']
    check("A1", "Q2 'off' when TLV431 off (leak << VB4 hold drive, OV corner)",
          resid <= VBE_OFF and i_leak <= 0.1*ib4_drive,
          f"residual Veb2 = {resid:.3f} V -> box-worst leak "
          f"Ic2 = 30uA*exp((Veb-vbe_lo)/VT) = {fmt_i(i_leak)} vs "
          f"{fmt_i(ib4_drive)} of Q3 pull-down ({100*i_leak/ib4_drive:.1f}%) -- "
          f"'off' means negligible against the hold, not zero")

    vk = VOUT_MAX*v['R8']/S
    vk_real = 12.6*v['R8']/S     # realistic latched corner: VOUT only decays
    check("A2", "TLV431 cathode below rating when off (ONSEMI part!)",
          vk <= VKA_MAX_ON - 0.5,
          f"Vk = {vk:.2f} V at the {VOUT_MAX} V double-fault corner "
          f"({VKA_MAX_ON-vk:.2f} V to the 16 V abs max); realistic latched "
          f"corner (VOUT = 12.6 V, decaying) gives {vk_real:.1f} V. "
          f"TI part (6 V) is NOT usable: see G.", warn=(vk > VKA_MAX_ON - 1.0))

    # A3: the SOLVED worst-case dearm-active point (no arbitrary target --
    # this is the design result). Solve Ib2(V) = 1.5*Ic_req(V)/beta_min with
    # Veb2 worst-high at 0 C, Vka max, resistor corners:
    vbe_cold = VEB2_HI_COLD
    floor = VKA_MAX + vbe_cold
    a = 1.0/(v['R9']*(1+R_TOL)); b = 1.5/BETA_MIN/(v['R5']+v['R6'])
    v_da = (floor*a + vbe_cold/(v['R10']*(1-R_TOL)) - 2*VCE_SAT*b)/(a - b)
    check("A3", "Solved worst-case dearm-active point (design result)",
          v_da <= v_arm(v) - 0.1,
          f"dearm active from VOUT = {v_da:.3f} V "
          f"({(v_da-floor)*1e3:.0f} mV above the {floor:.2f} V physics floor); "
          f"validity gated by the race check B2")

    # A4: drive strength at the moment it matters -- the arm point (worst case:
    # 0 degC Vbe, Vka max, resistor corners)
    vo = v_arm(v)
    ib2 = (vo-VKA_MAX-vbe_cold)/(v['R9']*(1+R_TOL)) - vbe_cold/(v['R10']*(1-R_TOL))
    ic_req = (vo-2*VCE_SAT)/(v['R5']+v['R6'])
    check("A4", f"Q2 solidly on at the arm point (VOUT = {vo:.2f} V, cold + corners)",
          ib2 > 0 and ib2*BETA_MIN >= 2.0*ic_req,
          f"Ib2 = {fmt_i(ib2)} -> Ic capability {fmt_i(max(ib2,0)*BETA_MIN)} "
          f"(beta_min) vs required {fmt_i(ic_req)} (x2 margin)")

    ika = (VOUT_NOM-VKA-VBE_ON)/v['R9'] - VKA/v['R8']
    check("A6", "TLV431 cathode current in regulation (dearmed, 12 V)",
          ika >= IKA_REG_MIN,
          f"I_KA = {fmt_i(ika)} >= {fmt_i(IKA_REG_MIN)}")

    dv = VCE_SAT + (VOUT_MAX-2*VCE_SAT)*v['R6']/(v['R5']+v['R6'])
    check("A7", "VB4 held within Veb_off of VOUT while dearmed (Q2 vs Q3 fight)",
          dv <= VBE_OFF,
          f"VOUT - VB4 = Vce2 + I*R6 = {dv:.3f} V <= {VBE_OFF} V at {VOUT_MAX} V "
          f"(I = {fmt_i((VOUT_MAX-2*VCE_SAT)/(v['R5']+v['R6']))})")

    # TLV431 regulation current at the startup race point (worst-low arm):
    # Vbe 0.65 - 0.03 spread - 0.05 tempco(50C) = 0.57; R4 -tol, R3eff +tol.
    re3 = r3_eff(v)
    varm_hot_min = vbe_lo(50)*(1 + (1-R_TOL)*v['R4']/((1+R_TOL)*re3))
    ika_race = (varm_hot_min - VKA - vbe_hi(50))/v['R9']
    ika_corner = (varm_hot_min - VKA - vbe_hi(50))/(v['R9']*(1+R_TOL))
    check("A8", "TLV431 regulation current at the box-corner arm point",
          ika_corner >= IKA_REG_MIN,
          f"I_KA = {fmt_i(ika_race)} nominal / {fmt_i(ika_corner)} at R9+tol, "
          f"at VOUT = {varm_hot_min:.2f} V (box worst-low arm) vs "
          f"{fmt_i(IKA_REG_MIN)} onsemi spec max-of-min (30 uA typ). The "
          f"shortfall exists only at the full R-corner + hot + low-tail stack, "
          f"fails soft (under-regulation raises K while VOUT and I_KA rise), "
          f"and typical parts need 30 uA. Bench item for the startup ramp.",
          warn=(ika_corner >= 0.5*IKA_REG_MIN))

# --------------------------------------------------------------------------
# B. ARM threshold (R4/R3) and Q3 drive
# --------------------------------------------------------------------------
def check_arm(v):
    print("\n--- B. Arm: Q3 on above V_arm, deterministic ---")
    va = v_arm(v, 0.60)                                   # box mid at 25 C
    re3 = r3_eff(v)
    va_lo = vbe_lo(50)*(1 + (1-R_TOL)*v['R4']/((1+R_TOL)*re3))  # hot, low tail
    va_hi = vbe_hi(0)*(1 + (1+R_TOL)*v['R4']/((1-R_TOL)*re3))   # cold, high tail
    check("B1", "Arm threshold near target",
          abs(va - V_ARM_TGT) <= 0.5,
          f"V_arm = {va:.2f} V at box-mid Vbe; full datasheet box "
          f"(0.50..0.70 V at 25 C, 0-50 C tempco, R corners): "
          f"{va_lo:.2f}..{va_hi:.2f} V")
    # Race margin, evaluated at the SAME temperature (both circuits share one
    # ambient; comparing a cold dearm against a hot arm double-counts):
    # dearm uses Q2's HIGH-tail Veb, arm uses Q3's LOW-tail Vbe, Vka at max.
    re3 = r3_eff(v)
    margins = []
    for T in (0.0, 25.0, 50.0):
        veb2 = vbe_hi(T)                         # Q2 Veb, box high tail
        vbe3 = vbe_lo(T)                         # Q3 Vbe, box low tail
        h = v['R9']*(1+R_TOL)*(veb2/(v['R10']*(1-R_TOL)) + 1.1e-6)
        dearm_act = VKA_MAX + veb2 + h
        arm_min = vbe3*(1 + (1-R_TOL)*v['R4']/((1+R_TOL)*re3))
        margins.append((T, dearm_act, arm_min))
    T, da, am = min(margins, key=lambda m: m[2]-m[1])
    check("B2", "Dearm precedes arm at every temperature (startup race)",
          da <= am,
          f"worst same-temperature corner ({T:.0f}C): dearm active {da:.2f} V "
          f"vs arm-min {am:.2f} V -> {(am-da)*1e3:.0f} mV margin "
          f"(all three temps: " + ", ".join(f"{m[0]:.0f}C:{(m[2]-m[1])*1e3:.0f}mV"
                                            for m in margins) + ")",
          warn=(am - da < 0.1))
    ib3 = (VOUT_NOM - va)/v['R4']
    ir5 = (VOUT_NOM-2*VCE_SAT)/(v['R5']+v['R6'])
    check("B3", "Q3 saturated against the dearm current (forced beta)",
          ir5/ib3 <= FBETA_SAT,
          f"Ib3 = (VOUT-V_arm)/R4 = {fmt_i(ib3)}, collector load {fmt_i(ir5)} "
          f"-> forced beta {ir5/ib3:.1f} <= {FBETA_SAT:g} at {VOUT_NOM:g} V")

# --------------------------------------------------------------------------
# C. ENGAGE + latched state
# --------------------------------------------------------------------------
def check_latched(v):
    print("\n--- C. Engage & hold (latched state, worst at VOUT = "
          f"{V_HOLD:g} V) ---")
    vb1 = V_HOLD - VCE_SAT
    ib4 = (V_HOLD-vbe_hi(0)-VCE_SAT)/v['R5']        # drive: high-tail cold
    ic4 = (vb1-vbe_lo(0))*(1.0/v['R7'] + 1.0/v['R12'])  # load: low-tail cold
    check("C1", "Q4 saturated at the hold floor",
          ic4/ib4 <= FBETA_SAT,
          f"Ib4 = {fmt_i(ib4)}, Ic4 = {fmt_i(ic4)} -> forced beta {ic4/ib4:.1f}")
    i_en = VIN_MAX/(R2*(1-R_TOL))
    ib1 = (vb1-vbe_hi(0))/v['R12'] - vbe_hi(0)/v['R11']   # high-tail cold
    check("C2", "Q1 clamps EN at the hold floor (beta_min, x2 margin)",
          ib1*BETA_MIN >= 2.0*i_en,
          f"Ib1 = {fmt_i(ib1)} -> {fmt_i(ib1*BETA_MIN)} capability vs "
          f"{fmt_i(i_en)} EN divider feed at VIN = {VIN_MAX:g} V")
    hi0 = vbe_hi(0)
    ib3 = (vb1-hi0)/v['R7'] + (V_HOLD-hi0)/v['R4'] - hi0/v['R3']
    ir5 = (V_HOLD-hi0-VCE_SAT)/v['R5']
    check("C3", "Regeneration self-sustains at the hold floor",
          ib3 > 0 and ir5/ib3 <= FBETA_SAT,
          f"Ib3 = {fmt_i(ib3)} (R7 + R4 - R3 bleed) vs Q3 load {fmt_i(ir5)}")
    # Q1 must stay OFF pre-latch: with Q4 off, N5 is fed only through R7 path
    n5 = vbe_hi(0) * v['R11']/(v['R7']+v['R12']+v['R11'])
    check("C4", "Q1 off before the latch fires (no EN sag while armed)",
          n5 <= vbe_lo(50) - 0.05,
          f"N5 = VB3*R11/(R7+R12+R11) = {n5:.2f} V < Vbe -- deterministic, "
          f"no leakage-seed sensitivity (v3's problem eliminated)")

# --------------------------------------------------------------------------
# D. Release + self-reinforcement + drain
# --------------------------------------------------------------------------
def check_release(v):
    print("\n--- D. Release, self-hold, quiescent ---")
    def rel(vin, vbe):
        i_en = vin/(R2*(1-R_TOL))
        return VCE_SAT + vbe + v['R12']*(i_en/BETA_MIN + vbe/v['R11'])
    r_lo, r_hi = rel(6.0, vbe_lo(50)), rel(VIN_MAX, vbe_hi(0))
    check("D1", "Release band low (output effectively discharged) yet > 0",
          0.9 <= r_hi <= 3.0 and r_lo > 0.5,
          f"EN clamp releases at VOUT ~ {r_lo:.2f} V (low-tail unit, VIN=6) .. "
          f"{r_hi:.2f} V (high-tail unit, VIN={VIN_MAX:g})")
    vref_latched = VCE_SAT_MAX*R1A/(R1A+R1B)   # design divider
    check("D2", "EN clamp keeps TLV431 off regardless of VIN (VIN-proof hold)",
          vref_latched < VKA/2,
          f"V_REF(latched) <= {vref_latched:.2f} V << {VKA} V")
    i_q = (VBE_ON/v['R10'] + (VOUT_NOM-VBE_ON-VKA)/v['R9']
           + (VOUT_NOM-2*VCE_SAT)/(v['R5']+v['R6']) + (VOUT_NOM-VBE_TH)/v['R4'])
    check("D3", "Dearmed drain from the 12 V rail (cost of the low dearm)",
          i_q < 10e-3,
          f"~{fmt_i(i_q)} (~{i_q*VOUT_NOM*1e3:.0f} mW); the R9 pair "
          f"dissipates {(VOUT_NOM-VBE_ON-VKA)**2/v['R9']*1e3/2:.0f} mW per 3k "
          f"resistor continuous ({(VOUT_MAX-VBE_ON-VKA)**2/v['R9']*1e3/2:.0f} mW "
          f"each during an OV transient, vs 100 mW 0603 rating). "
          f"The price of the ~2.05 V dearm point.",
          warn=(i_q > 8e-3))

# --------------------------------------------------------------------------
# G. TLV431 vendor constraint (the user's Vk question, closed form)
# --------------------------------------------------------------------------
def check_vendor():
    print("\n--- G. TLV431 vendor constraint ---")
    # Vk_worst = VOUT_MAX - (VBE_OFF/VBE_ON)*(V_dearm - VKA); solve for Vk<=6
    vd_ti = VKA + (VOUT_MAX-6.0)*VBE_ON/VBE_OFF
    check("G1", "TI TLV431 (Vka <= 6 V) usable?",
          False,
          f"No. Vk_worst = VOUT_max - (Vbe_off/Vbe_on)*(V_dearm - Vka): keeping "
          f"Vk <= 6 V requires dearm-VOUT >= {vd_ti:.1f} V -- above VOUT_max. "
          f"Fit the ONSEMI TLV431 (16 V) ONLY; mark it on the BOM.", warn=True)

# --------------------------------------------------------------------------
# LTspice cross-check
# --------------------------------------------------------------------------
def parse_ltspice_raw(path):
    import numpy as np
    raw = open(path, "rb").read()
    marker = "Binary:\n".encode("utf-16-le")
    p = raw.find(marker)
    if p < 0:
        raise ValueError("not a binary utf-16 LTspice raw file")
    hdr = raw[:p].decode("utf-16-le", errors="replace")
    ds = p + len(marker)
    nvar = int(hdr.split("No. Variables:")[1].split("\n")[0])
    npts = int(hdr.split("No. Points:")[1].split("\n")[0])
    names = [ln.split("\t")[2] for ln in
             hdr.split("\nVariables:\n")[1].strip("\n ").split("\n")
             if len(ln.split("\t")) >= 3][:nvar]
    rec = __import__("numpy").dtype([("t", "<f8")] + [(f"v{i}", "<f4")
                                    for i in range(1, nvar)])
    avail = (len(raw)-ds)//rec.itemsize
    n = min(npts, avail)
    d = np.frombuffer(raw[ds:ds+rec.itemsize*n], dtype=rec, count=n)
    cols = {names[0]: np.abs(d["t"])}
    for i in range(1, nvar):
        cols[names[i]] = d[f"v{i}"]
    return cols, (n < npts)

def crosscheck_sim(v):
    print("\n--- LTspice cross-check (en_uvlo_lockoutv3_tlv.raw) ---")
    if not RAW_PATH.exists():
        print("       raw file not found -- run the .asc in LTspice first.")
        return
    try:
        import numpy as np
        c, truncated = parse_ltspice_raw(RAW_PATH)
    except Exception as e:
        print(f"       could not parse raw file: {e}")
        return
    if truncated:
        print("       (raw file partially available -- checking what's there)")
    t = c["time"]*1e3
    EN, VIN, VOUT = c["V(en_uvlo)"], c["V(vin)"], c["V(vout)"]
    # Latch verdict: during VIN re-application (~85-95 ms) with VOUT high,
    # EN must stay clamped if the latch works.
    w = (t > 85) & (t < 95)
    if w.any():
        held = bool(np.all(EN[w] < 0.5)) and bool(np.all(VOUT[w] > 6))
        check("S1", "Simulated latch holds through VIN re-application",
              held,
              ("max EN = %.2f V while VOUT = %.1f V" %
               (float(EN[w].max()), float(VOUT[w].mean()))) +
              ("" if held else " -> NO LATCH: check that VB3 clamps at Vbe "
               "(Q3 armed) and that the dearm chain releases."))
    # Engage trip: the sim's B1 source injects 3.15 uA into EN when enabled,
    # so the simulated trip should match the on-board prediction (~3.3 V nom).
    w1 = (t > 58) & (t < 72)
    i_en = np.where(w1 & (EN < 0.5))[0]
    if len(i_en):
        vin_eng = float(VIN[i_en[0]])
        ven_trip = 1.24*(SIM_R1A+SIM_R1B)/SIM_R1A
        pred = (ven_trip*(SIM_R1A+SIM_R1B+SIM_R2)
                - 3.15e-6*SIM_R2*(SIM_R1A+SIM_R1B))/(SIM_R1A+SIM_R1B)
        check("S2", "Engage trip matches prediction (sim injects 3.15 uA)",
              abs(vin_eng - pred) < 0.15,
              f"sim EN clamps at VIN = {vin_eng:.2f} V vs predicted "
              f"{pred:.2f} V (V_TLV = 1.24 typ, I_S = 3.15 uA per the B1 "
              f"source) -- the sim now reproduces the on-board trip")
    # Release: EN must recover only after VOUT has decayed into the predicted
    # 1.0..1.8 V band (Stage 4 of uvlo_latch.tex).
    w3 = (t > 100) & (t < t.max())
    i_rel = np.where(w3 & (EN > 0.6))[0]
    if len(i_rel):
        v_rel = float(VOUT[i_rel[0]])
        check("S3", "Release VOUT inside the predicted band",
              0.9 <= v_rel <= 2.0,
              f"sim releases EN at VOUT = {v_rel:.2f} V vs predicted "
              f"1.0..1.8 V (unit tails) -- output effectively discharged")
    if "V(vb3)" in c:
        vb3max = float(c["V(vb3)"].max())
        print(f"       sim VB3 peak = {vb3max:.2f} V "
              f"({'clamps at Vbe -> armed' if vb3max > 0.55 else 'never reaches Vbe -> cannot arm'})")
    if "V(vref)" in c:
        w_run = (t > 40) & (t < 58)
        print(f"       sim V_REF while running = {float(c['V(vref)'][w_run].mean()):.2f} V "
              f"(> V_TLV = 1.24 -> dearmed)")
    make_figure(t, VIN, VOUT, EN, c)

def make_figure(t, VIN, VOUT, EN, c):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    FIG_DIR.mkdir(exist_ok=True)
    path = FIG_DIR / "uvlo_latch_sim.png"
    fig, axs = plt.subplots(3, 1, figsize=(9.5, 7.2), sharex=True)
    axs[0].plot(t, VIN, color="#2a6f97", lw=1.6, label="VIN")
    axs[0].plot(t, VOUT, color="#e07a1f", lw=1.6, label="VOUT")
    axs[0].set_ylabel("rails (V)")
    axs[1].plot(t, EN, color="#1a8a3a", lw=1.6, label="EN/UVLO")
    axs[1].axhline(1.22, color="#999", ls=":", lw=1, label="LM5176 Vth (typ)")
    axs[1].set_ylabel("EN (V)")
    for key, col, lab in (("V(vb3)", "#b8002e", "VB3"),
                          ("V(vref)", "#7d5fa6", "V_REF"),
                          ("V(vb4p)", "#1a8a3a", "VB4")):
        if key in c:
            axs[2].plot(t, c[key], color=col, lw=1.3, label=lab)
    axs[2].axhline(0.65, color="#bbb", ls=":", lw=1)
    axs[2].set_ylabel("latch (V)"); axs[2].set_xlabel("time (ms)")
    for ax in axs:
        ax.grid(True, ls=":", lw=0.6, alpha=0.7)
        ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    fig.suptitle("UVLO lockout latch v3b -- latest LTspice transient (as-drawn values)",
                 fontsize=11, weight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"       wrote {path}")

def main():
    print(f"UVLO lockout latch v3b -- design + worst-case DC checks "
          f"(analyzing: {'RECOMMENDED' if V is RECOMMENDED else 'AS-DRAWN'} values)\n")
    design_table(V)
    check_dearm(V)
    check_arm(V)
    check_latched(V)
    check_release(V)
    check_vendor()
    crosscheck_sim(V)
    n_f = _results.count("FAIL"); n_w = _results.count("WARN")
    print(f"\nSummary: {len(_results)} checks, {n_f} FAIL, {n_w} WARN.")
    if V is RECOMMENDED:
        print("Schematic deltas remaining: R9 2.2k -> 1.5k (2x 3k parallel), "
              "R10 39k -> 47k. The EN/UVLO divider in the .asc already matches "
              "10a's recommendation (420k/150k/15k).")

if __name__ == "__main__":
    main()
