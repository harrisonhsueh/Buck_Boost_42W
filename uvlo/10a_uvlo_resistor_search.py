#!/usr/bin/env python
"""
10a -- EN/UVLO divider design: resistor search for the LM5176 EN pin + TLV431 latch.

RUNNING THIS ON WINDOWS
    Use `python 10a_uvlo_resistor_search.py` from the activated venv, NOT
    `py ...`. The `py` launcher obeys this file's shebang and resolves it
    against PATH; a Windows venv provides python.exe but no python3.exe, so
    `py` can silently fall through to a system interpreter that lacks numpy /
    matplotlib -- the search still runs (built-in resistor list) but the
    FIGURES ARE SILENTLY SKIPPED.

WHY THIS CIRCUIT EXISTS
    The LM5176's built-in pre-bias startup does not survive this design's very
    slow control loop (low crossover, forced by the large output bank): after a
    brief VIN dropout the part can restart into a still-charged output and
    misbehave. TI support could not resolve it and only suggested raising the
    crossover frequency, which conflicts with the stability design (see
    notebooks/07_control_loop_stability.ipynb). The fix is a discrete lockout
    latch (10b_uvlo_latch.py / uvlo_latch.tex): on input dropout it pulls
    EN/UVLO low and holds it until VOUT has fully discharged, so every restart
    begins from a dead output.

WHAT THIS SCRIPT DOES
    Sizes the three EN/UVLO divider resistors. Topology (single EN/UVLO node):

        VIN --[R2]-- EN --[R1b]-- REF --[R1a]-- GND

    The TLV431 REF pin sits on the REF node (draws Iref into the pin); the
    LM5176 sources I_S = I_STBY + I_H out of the EN pin (I_H = 0 in standby,
    I_HYS while running). Core equations (derived in uvlo_tlv431.tex):

        V_EN  = [Vin*(R1a+R1b) + I_S*R2*(R1a+R1b) - Iref*R1a*R2] / (R1a+R1b+R2)
        V_REF = R1a*(V_EN - Iref*R1b) / (R1a+R1b)
        V_EN at TLV trip (V_REF = V_TLV) = V_TLV*(R1a+R1b)/R1a + Iref*R1b
                                           [independent of Vin, R2, EN currents]

    The search sweeps (R2, R1a, R1b) over stocked JLCPCB basic-part values and
    keeps only triples that satisfy constraints C1-C4 at the WORST tolerance /
    parameter corner (resistors at +/-R_TOL, every chip parameter at min/max).

CONSTRAINTS (worst case, every unit)
    The latch defaults to ENGAGED and is dearmed only while V_REF > V_TLV, with
    no arm-after-release grace. So the TLV431 trip point Vlatch must sit inside
    the LM5176's own hysteresis window on every unit:  Voff < Vlatch < Von.
      C1  turn-on guaranteed by VIN_ON (weak USB rail must still start us)
      C2  Vlatch < Von : V_REF is already above V_TLV the instant the converter
          turns on -> latch is dearmed at turn-on, even on an arbitrarily slow
          VIN rise (no running-but-not-dearmed window)
      C3  Vlatch > Voff: on a falling input, the latch fires before the LM5176
          would drop out on its own
      C4  earliest possible turn-on stays above VON_MIN (don't load an unsettled
          rail / don't boost from an impractically low input)
    Budget identity linking C2 and C3 (derived in the tex doc):
        (Von - Vlatch) = I_HYS*R2 - (Vlatch - Voff)
    Both gaps share the I_HYS*R2 hysteresis budget, and the Vth (+/-60 mV) and
    V_TLV (+/-30 mV) spreads inflate the C3 gap, so a large R2 is forced and the
    feasible region is a thin sliver. See uvlo_tlv431.tex sec. "Design
    constraints" for the full argument, and the two PNG figures this script
    writes for a picture of it.

RESULT (SERIES="JLCPCB", COMPOSITE R2; VTLV_MIN includes the full onsemi
Vka excursion)
    Single basic parts have NO passing triple; composite R2 gives 19 passers.
    Selection criterion: gaps only need to be positive (guaranteed per-unit),
    so prefer the highest worst-case earliest turn-on Von_min (a higher Von
    floor eases the latch's dearm-before-arm race). Chosen:
        R2 = 420k (120k + 300k series), R1a = 150k, R1b = 15k
    Von_min 2.75 V, gaps 52/41 mV, turn-on band 2.75..4.49 V.

    Figure geometry (all in the (S, R2) plane, S = R1a + R1b, fixed R1a).
    C1, C4 and the iso-Von_min contours are ONE family -- the turn-on locus
        R2 = S*(V - Vth) / (Vth + Iref*R1a - Istby*S)
    with V = VIN_ON (C1, Istby_min, Vth_max), V = VON_MIN (C4, Istby_max,
    Vth_min), or any contour level. These are NOT straight lines: they pass
    through the origin, then steepen and diverge at the vertical asymptote
        S_inf = (Vth + Iref*R1a) / Istby
    = ~1.35M for C1 (off-plot, so it looks gently curved) and ~409k for C4
    (inside the 4-panel window -> its steep right-hand sweep). The linear
    approximation R2 ~ S(V-Vth)/Vth holds only while Istby*S << Vth (13% error
    for C1 at S=165k, 42% for C4).
      C3  S >= R1a*(Vth_max - Iref*R1b)/VTLV_min        vertical (R2-free)
      C2  R2 >= D*S/(Ihys_min*S - D),  D = VTLV_max*S/R1a + Iref*R1b - Vth_min
    Higher Von_min = up-left, bounded by the C1 ceiling.

USAGE
    python 10a_uvlo_resistor_search.py
    Edit the PARAMETERS block below to match your datasheet revision; figures
    are written next to this file in figures/.
"""

import sys
from pathlib import Path
from itertools import product, combinations_with_replacement

# constants.py lives at the repo root (one level up)
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
FIG_DIR = Path(__file__).resolve().parent / "figures"

# --------------------------------------------------------------------------
# Resistor value source: real JLCPCB basic-part 0603 library (constants.py)
# --------------------------------------------------------------------------
# Restricts the search to resistors that are basic parts at JLCPCB (no
# extended-part fee, no stock-out risk), at the cost of coarser coverage than
# a generated E96 sweep.
# Fallback copy of MFG.BASIC_0603_RESISTORS, used only if constants.py cannot
# be imported (e.g. running a Python without numpy, which constants.py needs).
# Keep in sync with constants.py -- it is the authoritative source.
_FALLBACK_BASIC_0603 = [
    1e3, 1.2e3, 1.5e3, 1.8e3, 2e3, 2.2e3, 2.4e3, 2.7e3, 3e3, 3.6e3, 3.9e3,
    4.7e3, 4.99e3, 5.1e3, 5.6e3, 6.2e3, 6.8e3, 7.5e3, 8.2e3,
    10e3, 12e3, 15e3, 18e3, 20e3, 22e3, 24e3, 27e3, 30e3, 36e3, 39e3,
    47e3, 49.9e3, 51e3, 56e3, 68e3, 75e3, 82e3,
    100e3, 120e3, 150e3, 200e3, 220e3, 270e3, 300e3, 330e3, 470e3, 510e3,
    1e6, 2e6, 10e6,
]

try:
    from constants import MFG
    _JLCPCB_VALUES = sorted(float(v) for v in MFG.BASIC_0603_RESISTORS)
except Exception as _e:                      # ImportError, numpy missing, ...
    _JLCPCB_VALUES = sorted(_FALLBACK_BASIC_0603)
    print(f"note: constants.py unavailable ({type(_e).__name__}: {_e});\n"
          f"      using the built-in copy of the JLCPCB basic-0603 list "
          f"({len(_JLCPCB_VALUES)} values) -- results unaffected while that\n"
          f"      list matches constants.py.\n"
          f"      interpreter: {sys.executable}\n"
          f"      If that is not your venv python, re-run with "
          f"`python {Path(__file__).name}` (not `py`).")

# --------------------------------------------------------------------------
# PARAMETERS (edit to match your datasheet revision)
# --------------------------------------------------------------------------
VIN_ON      = 4.5      # V  turn-on must be guaranteed by here. 4.5 V already folds
                       #    in USB cable drop + source tolerance; extra margin comes
                       #    from sitting away from the boundary, not lowering this.
VIN_MAX     = 22.0     # V  input maximum (USB PD max + tolerance)

VTH_MIN     = 1.17     # V  LM5176 EN/UVLO operating threshold, min
VTH_MAX     = 1.29     # V  ... max

ISTBY_MIN   = 1.0e-6   # A  EN standby source current
ISTBY_MAX   = 3.0e-6
IHYS_MIN    = 2.15e-6  # A  EN hysteresis source current (added after turn-on)
IHYS_MAX    = 4.25e-6
IREF_MIN    = 0.0      # A  TLV431 REF input current
IREF_MAX    = 0.38e-6

VTLV_MIN    = 1.193    # V  effective TLV431 reference, min: 1.240 - 6.2m (0.5%)
                       #    - 20m (temp) - 21m (Vka shift: -1.5 mV/V over the
                       #    ~1.24..15.4 V cathode excursion during the trip
                       #    transition -- onsemi part, K floats to ~15.4 V)
VTLV_MAX    = 1.266    # V  1.240 + 6.2m + 20m (Vka term only shifts down)

R_TOL       = 0.03     # resistor tolerance (+/-): 1% purchase + ~0.4% tempco
                       # (100 ppm/C over 0-50 C) + ~1.5% load-life/soldering
                       # drift. Budget-derived, not a round guess.

# C2/C3 margins on the per-unit gaps. 0 by default: R_TOL is already pessimistic
# and every parameter sits at its worst corner, so an explicit margin here is
# redundant. Buy headroom by picking an interior solution (SORT_MODE="interior"),
# not by inflating these. Set >0 only to force extra slack.
HYST_LO     = 0.0      # V  required per-unit (Vlatch - Voff)   [C3]
HYST_HI     = 0.0      # V  required per-unit (Von   - Vlatch)  [C2]

# Reject designs whose divider current is too weak vs the LM5176 bias currents,
# i.e. where the EN pin is held up by I_STBY/I_HYS rather than tracking VIN.
BIAS_RATIO_MIN = 1.0   # min (divider current at turn-on) / (total bias current)

# C4 floor. CAUTION -- C4 fights C2: forcing Vlatch < Von needs a large R2, which
# (with I_STBY spanning 1-3 uA) smears turn-on across a ~1.5 V band and drags the
# worst-case earliest Von down. Achievable Von floor vs C2/C3 margin (4.5 V ceiling):
#     margin 0.10 V -> floor <= ~1.9 V | 0.05 V -> ~2.2 V | 0.00 V -> ~2.6 V
# So 2.5 V fits only at ~0 margin, leaving a thin sliver of feasible designs.
# Lower VON_MIN if you want more room to back away from the edges.
VON_MIN     = 2.5      # V  worst-case earliest turn-on floor

# Search space
SERIES      = "JLCPCB" # "JLCPCB" -> real stocked 0603 basic-part values from
                       #     constants.py (MFG.BASIC_0603_RESISTORS)
                       # "E24"/"E96" -> generated series (ignores real stock)
                       # (values assumed at +/- R_TOL regardless of series choice)
R1A_RANGE   = (20e3, 1.0e6)    # bottom resistor nominal search range
R1B_RANGE   = (2e3, 500e3)     # mid resistor nominal search range
R2_RANGE    = (20e3, 3.0e6)    # top resistor nominal search range
VIN_ON_FLOOR= 1.5      # V  reject if nominal turn-on falls below this
TOP_N       = 15       # how many solutions to print
MAKE_PLOT   = True     # write the two PNG figures (needs numpy + matplotlib)
SORT_MODE   = "von_min"  # "von_min" -> highest worst-case earliest turn-on
                       #     (C4 headroom; gaps only need to be positive, and a
                       #     higher Von floor eases the downstream latch race)
                       # "interior"-> furthest from all 4 boundaries
                       # "balanced"-> largest min(gap_lo, gap_hi)
                       # "gap_lo"  -> most margin between latch-off and LM5176 dropout
                       # "gap_hi"  -> most hysteresis between latch-off and turn-on
                       # "tight"   -> turn-on closest to VIN_ON
                       # "low_en22"-> smallest EN-node voltage at VIN_MAX

# Composite legs (SERIES="JLCPCB" only): build one leg from TWO basic-part 0603
# resistors (series or parallel) to fill gaps between the ~50 stocked values.
# Still no extended-part fee, just one extra placement. Tolerance stays valid:
# a series/parallel pair of equal-tolerance parts is never worse than a single
# R_TOL part in the corner search. R2-only is the best default: singles alone
# find nothing, R2-composite finds ~10 mV interior margin in ~5 s; enabling
# R1A/R1B instead finds thinner margins (~7-8 mV), needs two extra placements,
# and takes ~3 min. Enable them only to explore alternatives.
COMPOSITE   = {"R1A": False, "R1B": False, "R2": True}

# --------------------------------------------------------------------------
# Circuit equations (derivations in uvlo_tlv431.tex)
# --------------------------------------------------------------------------
def v_en(vin, r2, r1a, r1b, i_s, iref):
    """EN/UVLO node voltage for a given input and EN-pin current state."""
    num = vin*(r1a+r1b) + i_s*r2*(r1a+r1b) - iref*r1a*r2
    return num/(r1a+r1b+r2)

def v_ref(vin, r2, r1a, r1b, i_s, iref):
    """TLV431 REF node voltage."""
    return r1a*(v_en(vin, r2, r1a, r1b, i_s, iref) - iref*r1b)/(r1a+r1b)

def v_en_at_trip(r1a, r1b, vtlv, iref):
    """EN voltage at the TLV431 trip (V_REF = V_TLV). Vin/R2/I_S-independent."""
    return vtlv*(r1a+r1b)/r1a + iref*r1b

def vin_for_ven(ven, r2, r1a, r1b, i_s, iref):
    """Input voltage that produces a given EN voltage (inverse of v_en)."""
    return (ven*(r1a+r1b+r2) - i_s*r2*(r1a+r1b) + iref*r1a*r2)/(r1a+r1b)

# --------------------------------------------------------------------------
# Candidate resistor values (E-series or JLCPCB stock, optionally composite)
# --------------------------------------------------------------------------
E24 = [1.0,1.1,1.2,1.3,1.5,1.6,1.8,2.0,2.2,2.4,2.7,3.0,3.3,3.6,3.9,
       4.3,4.7,5.1,5.6,6.2,6.8,7.5,8.2,9.1]
E96 = [1.00,1.02,1.05,1.07,1.10,1.13,1.15,1.18,1.21,1.24,1.27,1.30,1.33,1.37,
       1.40,1.43,1.47,1.50,1.54,1.58,1.62,1.65,1.69,1.74,1.78,1.82,1.87,1.91,
       1.96,2.00,2.05,2.10,2.15,2.21,2.26,2.32,2.37,2.43,2.49,2.55,2.61,2.67,
       2.74,2.80,2.87,2.94,3.01,3.09,3.16,3.24,3.32,3.40,3.48,3.57,3.65,3.74,
       3.83,3.92,4.02,4.12,4.22,4.32,4.42,4.53,4.64,4.75,4.87,4.99,5.11,5.23,
       5.36,5.49,5.62,5.76,5.90,6.04,6.19,6.34,6.49,6.65,6.81,6.98,7.15,7.32,
       7.50,7.68,7.87,8.06,8.25,8.45,8.66,8.87,9.09,9.31,9.53,9.76]

def fmt_r(x):
    """1234567 -> '1.234567M', 12000 -> '12k' (matplotlib/report friendly)."""
    if x >= 1e6: return f"{x/1e6:g}M"
    if x >= 1e3: return f"{x/1e3:g}k"
    return f"{x:g}"

# Recipes: leg name -> {rounded_value: "how to build it"}; filled in by
# eseries_values() so the report can print BOM detail for composite legs.
_RECIPES = {}

def _composite_pool(base_vals, lo, hi):
    """All values buildable from one or two JLCPCB basic-part resistors within
    [lo, hi]. Returns (sorted_values, recipes)."""
    recipes = {}
    for v in base_vals:
        if lo <= v <= hi:
            recipes[round(v, 6)] = f"{fmt_r(v)} (single)"
    for a, b in combinations_with_replacement(base_vals, 2):
        s = a + b
        if lo <= s <= hi:
            recipes.setdefault(round(s, 6), f"{fmt_r(a)}+{fmt_r(b)} series")
        p = a*b/(a+b)
        if lo <= p <= hi:
            recipes.setdefault(round(p, 6), f"{fmt_r(a)}||{fmt_r(b)} parallel")
    return sorted(recipes.keys()), recipes

def eseries_values(name, lo, hi, leg=None):
    """Candidate nominal values for one leg, honoring SERIES and COMPOSITE."""
    if name == "JLCPCB":
        if leg is not None and COMPOSITE.get(leg, False):
            values, recipes = _composite_pool(_JLCPCB_VALUES, lo, hi)
            _RECIPES[leg] = recipes
            return values
        singles = [v for v in _JLCPCB_VALUES if lo <= v <= hi]
        if leg is not None:
            _RECIPES[leg] = {round(v, 6): f"{fmt_r(v)} (single)" for v in singles}
        return singles
    base = E24 if name == "E24" else E96
    out = []
    decade = 1.0
    while decade*base[0] <= hi*10:
        for b in base:
            v = b*decade
            if lo <= v <= hi:
                out.append(round(v, 3))
        decade *= 10
    out = sorted(set(out))
    if leg is not None:
        _RECIPES[leg] = {round(v, 6): f"{fmt_r(v)} (single)" for v in out}
    return out

def describe(leg, value):
    """Human-readable build recipe for a resistor value on a given leg."""
    return _RECIPES.get(leg, {}).get(round(value, 6), f"{fmt_r(value)} (single)")

# resistor tolerance corners: (R2, R1a, R1b) each at -tol / +tol  -> 8 corners
_CORNERS = list(product((1-R_TOL, 1+R_TOL), repeat=3))

# --------------------------------------------------------------------------
# Worst-case constraint evaluation
# --------------------------------------------------------------------------
_ISTBY = (ISTBY_MIN, ISTBY_MAX)
_IHYS  = (IHYS_MIN, IHYS_MAX)
_IREF  = (IREF_MIN, IREF_MAX)
_VTH   = (VTH_MIN, VTH_MAX)
_VTLV  = (VTLV_MIN, VTLV_MAX)

def hysteresis_worst(r2n, r1an, r1bn):
    """Worst-case PER-UNIT hysteresis gaps (in VIN volts).

    For each device (resistors + chip params held consistent), three events
    share the same currents, so their differences are clean:
        Von    = VIN where V_EN(standby) = V_th             (LM5176 turn-on)
        Voff   = VIN where V_EN(running) = V_th             (LM5176 self-dropout)
        Vlatch = VIN where V_EN(running) = V_EN_trip(V_TLV) (TLV431 latch)
    We need Voff < Vlatch < Von for every unit:
        glo = min over corners of (Vlatch - Voff)  [C3]
        ghi = min over corners of (Von   - Vlatch) [C2]
    Identity: (Von - Vlatch) = I_HYS*R2 - (Vlatch - Voff), so glo + ghi <= I_HYS*R2.
    """
    glo, ghi = 1e9, 1e9
    for a, b, c in _CORNERS:
        r2, r1a, r1b = r2n*a, r1an*b, r1bn*c
        for vth in _VTH:
            for vtl in _VTLV:
                for irf in _IREF:
                    vtrip = v_en_at_trip(r1a, r1b, vtl, irf)
                    for ist in _ISTBY:
                        for ih in _IHYS:
                            isr = ist + ih
                            voff = vin_for_ven(vth,   r2, r1a, r1b, isr, irf)
                            vlat = vin_for_ven(vtrip, r2, r1a, r1b, isr, irf)
                            von  = vin_for_ven(vth,   r2, r1a, r1b, ist, irf)
                            glo = min(glo, vlat - voff)
                            ghi = min(ghi, von - vlat)
    return glo, ghi

def worst_case(r2n, r1an, r1bn):
    """Return dict of worst-case values, or None if any hard constraint fails."""
    # C1: turn-on guaranteed by VIN_ON <=> min V_EN(standby, VIN_ON) >= Vth_max.
    c1 = min(v_en(VIN_ON, r2n*a, r1an*b, r1bn*c, ISTBY_MIN, IREF_MAX)
             for a, b, c in _CORNERS)
    if c1 < VTH_MAX:
        return None

    # Bias-domination guard: divider current at turn-on vs LM5176 bias currents.
    # Worst (weakest) corner: smallest (VIN_ON - Vth)/R2, largest bias.
    i_div = (VIN_ON - VTH_MAX) / (r2n * (1 + R_TOL))
    bias_ratio = i_div / (ISTBY_MAX + IHYS_MAX)
    if bias_ratio < BIAS_RATIO_MIN:
        return None

    # C4: earliest possible turn-on (Vth low, I_STBY high) must stay >= VON_MIN.
    von_min_wc = min(
        vin_for_ven(vth, r2n*a, r1an*b, r1bn*c, ist, irf)
        for a, b, c in _CORNERS
        for vth in _VTH for ist in _ISTBY for irf in _IREF)
    if von_min_wc < VON_MIN:
        return None

    glo, ghi = hysteresis_worst(r2n, r1an, r1bn)
    if not (glo >= HYST_LO and ghi >= HYST_HI):   # C3 and C2
        return None

    # worst-case (highest) Vlatch over corners, reported for reference
    vlatch_max = max(
        vin_for_ven(v_en_at_trip(r1an*b, r1bn*c, vtl, irf),
                    r2n*a, r1an*b, r1bn*c, ist+ih, irf)
        for a, b, c in _CORNERS
        for vtl in _VTLV for irf in _IREF
        for ist in _ISTBY for ih in _IHYS)

    return {
        "c1_ven_on": c1,            # >= VTH_MAX
        "slack_c1": c1 - VTH_MAX,
        "von_min": von_min_wc,      # >= VON_MIN (C4)
        "slack_c4": von_min_wc - VON_MIN,
        "gap_lo": glo,              # Vlatch - Voff  (>= HYST_LO)
        "gap_hi": ghi,              # Von    - Vlatch (>= HYST_HI)
        "vlatch_max": vlatch_max,
        "bias_ratio": bias_ratio,
    }

def vin_ranges(r2n, r1an, r1bn):
    """Worst-case [min,max] of the three VIN events, each over its OWN extremes.

    These are honest population spans of each event, but they are NOT directly
    comparable to each other -- see latch_margin_worst() / hysteresis_worst()
    for the per-unit guarantees. Two events whose population bands overlap on
    paper never overlap within a single device, because shared parameters
    cancel in the difference.
    """
    von, voff, vlatch = [], [], []
    for a, b, c in _CORNERS:
        r2, r1a, r1b = r2n*a, r1an*b, r1bn*c
        for vth in _VTH:
            for ist in _ISTBY:
                for irf in _IREF:
                    von.append(vin_for_ven(vth, r2, r1a, r1b, ist, irf))   # standby
                    for ih in _IHYS:
                        voff.append(vin_for_ven(vth, r2, r1a, r1b, ist+ih, irf))
        for vtl in _VTLV:
            for irf in _IREF:
                vtrip = v_en_at_trip(r1a, r1b, vtl, irf)
                for ist in _ISTBY:
                    for ih in _IHYS:
                        vlatch.append(vin_for_ven(vtrip, r2, r1a, r1b, ist+ih, irf))
    return (min(von), max(von)), (min(voff), max(voff)), (min(vlatch), max(vlatch))

def latch_margin_worst(r2n, r1an, r1bn):
    """Worst-case PER-UNIT (Vlatch - Voff), in volts of VIN.

    Both are running-state events of the SAME device at the SAME instant, so
    I_STBY, I_HYS, VIN and R2 are identical for both and cancel:
        Vlatch - Voff = (V_EN_trip - V_th) * (R1a+R1b+R2)/(R1a+R1b),
    with V_EN_trip - V_th independent of any current. Minimised over resistor
    corners and the (V_th, V_TLV, I_ref) extremes that shrink the gap.
    """
    gaps = []
    Is_dummy = 0.5*(ISTBY_MIN+ISTBY_MAX) + 0.5*(IHYS_MIN+IHYS_MAX)  # cancels anyway
    for a, b, c in _CORNERS:
        r2, r1a, r1b = r2n*a, r1an*b, r1bn*c
        for vth in _VTH:
            for vtl in _VTLV:
                for irf in _IREF:
                    vtrip = v_en_at_trip(r1a, r1b, vtl, irf)
                    gaps.append(vin_for_ven(vtrip, r2, r1a, r1b, Is_dummy, irf)
                                - vin_for_ven(vth, r2, r1a, r1b, Is_dummy, irf))
    return min(gaps)

def _verify_cancellation():
    """Self-test: the per-unit latch gap is invariant to the LM5176 currents."""
    r2, r1a, r1b = 287e3, 110e3, 16.2e3
    vtrip = v_en_at_trip(r1a, r1b, VTLV_MIN, 0.0)
    g_lo = (vin_for_ven(vtrip, r2, r1a, r1b, ISTBY_MIN+IHYS_MIN, 0.0)
            - vin_for_ven(VTH_MAX, r2, r1a, r1b, ISTBY_MIN+IHYS_MIN, 0.0))
    g_hi = (vin_for_ven(vtrip, r2, r1a, r1b, ISTBY_MAX+IHYS_MAX, 0.0)
            - vin_for_ven(VTH_MAX, r2, r1a, r1b, ISTBY_MAX+IHYS_MAX, 0.0))
    return abs(g_lo - g_hi) < 1e-12, g_lo, g_hi

def nominal_report(r2, r1a, r1b):
    """Nominal (typ-parameter) operating points for a passing candidate."""
    vth_typ  = 0.5*(VTH_MIN+VTH_MAX)
    istby_typ = 0.5*(ISTBY_MIN+ISTBY_MAX)
    ihys_typ = 0.5*(IHYS_MIN+IHYS_MAX)
    iref_typ = 0.5*(IREF_MIN+IREF_MAX)
    vtlv_typ = 0.5*(VTLV_MIN+VTLV_MAX)

    vin_on     = vin_for_ven(vth_typ, r2, r1a, r1b, istby_typ, iref_typ)
    vin_off_lm = vin_for_ven(vth_typ, r2, r1a, r1b, istby_typ+ihys_typ, iref_typ)
    ven_trip   = v_en_at_trip(r1a, r1b, vtlv_typ, iref_typ)
    vin_latch  = vin_for_ven(ven_trip, r2, r1a, r1b, istby_typ+ihys_typ, iref_typ)
    ven_22     = v_en(VIN_MAX, r2, r1a, r1b, istby_typ+ihys_typ, iref_typ)
    i_22       = (VIN_MAX - ven_22)/r2      # rough quiescent through R2 at 22 V
    return dict(vin_on=vin_on, vin_off_lm=vin_off_lm, vin_latch=vin_latch,
                ven_22=ven_22, i_22=i_22)

# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------
def search():
    r1a_vals = eseries_values(SERIES, *R1A_RANGE, leg="R1A")
    r1b_vals = eseries_values(SERIES, *R1B_RANGE, leg="R1B")
    r2_vals  = eseries_values(SERIES, *R2_RANGE, leg="R2")
    print(f"Series {SERIES}: {len(r1a_vals)} R1a x {len(r1b_vals)} R1b x "
          f"{len(r2_vals)} R2 candidates")

    istby_typ = 0.5*(ISTBY_MIN+ISTBY_MAX)
    iref_typ  = 0.5*(IREF_MIN+IREF_MAX)
    vth_typ   = 0.5*(VTH_MIN+VTH_MAX)

    results = []
    for r1a in r1a_vals:
        for r1b in r1b_vals:
            ratio = r1b/r1a
            if ratio < 0.03 or ratio > 1.0:          # cheap ratio prune
                continue
            for r2 in r2_vals:
                # cheap nominal turn-on window prune
                vin_on = vin_for_ven(vth_typ, r2, r1a, r1b, istby_typ, iref_typ)
                if vin_on > VIN_ON or vin_on < VIN_ON_FLOOR:
                    continue
                # cheap nominal hysteresis prune
                ven_trip = v_en_at_trip(r1a, r1b, 0.5*(VTLV_MIN+VTLV_MAX), iref_typ)
                vlatch = vin_for_ven(ven_trip, r2, r1a, r1b,
                                     istby_typ+0.5*(IHYS_MIN+IHYS_MAX), iref_typ)
                voff = vin_for_ven(vth_typ, r2, r1a, r1b,
                                   istby_typ+0.5*(IHYS_MIN+IHYS_MAX), iref_typ)
                if vlatch < voff + HYST_LO or vlatch > vin_on - HYST_HI:
                    continue
                wc = worst_case(r2, r1a, r1b)
                if wc is None:
                    continue
                rep = nominal_report(r2, r1a, r1b)
                rep.update(gap_lo=wc["gap_lo"], gap_hi=wc["gap_hi"],
                           vlatch_max=wc["vlatch_max"], bias_ratio=wc["bias_ratio"])
                # interior = worst-case distance (V) to the nearest of the 4 boundaries
                von_r, _, _ = vin_ranges(r2, r1a, r1b)
                rep["interior"] = min(wc["gap_lo"], wc["gap_hi"],
                                      VIN_ON - von_r[1],          # C1 headroom
                                      wc["von_min"] - VON_MIN)    # C4 headroom
                margin = min(wc["gap_lo"], wc["gap_hi"])
                results.append((margin, r2, r1a, r1b, wc, rep))

    keyfns = {
        "von_min":  lambda x: -x[4]["von_min"],
        "gap_lo":   lambda x: -x[5]["gap_lo"],
        "gap_hi":   lambda x: -x[5]["gap_hi"],
        "balanced": lambda x: -x[0],
        "tight":    lambda x: -x[5]["vin_on"],
        "low_en22": lambda x:  x[5]["ven_22"],
        "interior": lambda x: -x[5]["interior"],
    }
    results.sort(key=keyfns.get(SORT_MODE, keyfns["interior"]))
    return results

# --------------------------------------------------------------------------
# Constraint-margin helpers (used by the figures)
# --------------------------------------------------------------------------
def c1_margin(r2, r1a, r1b):
    return min(v_en(VIN_ON, r2*a, r1a*b, r1b*c, ISTBY_MIN, IREF_MAX)
               for a, b, c in _CORNERS) - VTH_MAX

def c2_margin(r2, r1a, r1b):
    return hysteresis_worst(r2, r1a, r1b)[1] - HYST_HI   # gap_hi

def c3_margin(r2, r1a, r1b):
    return hysteresis_worst(r2, r1a, r1b)[0] - HYST_LO   # gap_lo

def c4_margin(r2, r1a, r1b):
    return min(vin_for_ven(vth, r2*a, r1a*b, r1b*c, ist, irf)
               for a, b, c in _CORNERS for vth in _VTH
               for ist in _ISTBY for irf in _IREF) - VON_MIN

def _eseries_dots(r1a, S_lo, S_hi, R2_lo, R2_hi):
    """Available (R1b, R2) parts at fixed R1a in the plot window; split pass/fail."""
    r1b_opts = [v for v in eseries_values(SERIES, max(R1B_RANGE[0], 2e3),
                                          R1B_RANGE[1], leg="R1B")
                if S_lo <= r1a + v <= S_hi]
    r2_opts = [v for v in eseries_values(SERIES, R2_RANGE[0], R2_RANGE[1], leg="R2")
               if R2_lo <= v <= R2_hi]
    pS, pR2, fS, fR2 = [], [], [], []
    for r1b in r1b_opts:
        for r2 in r2_opts:
            ok = worst_case(r2, r1a, r1b) is not None
            (pS if ok else fS).append((r1a + r1b) / 1e3)
            (pR2 if ok else fR2).append(r2 / 1e3)
    return pS, pR2, fS, fR2

# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------
def plot_constraints(path=None, r1a_vals=(105e3, 150e3, 217e3),
                     recommended=(420e3, 150e3, 15e3)):
    """Four-panel figure: each worst-case constraint boundary in the
    (R1a+R1b, R2) plane, for several R1a values, plus available parts."""
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
    except ImportError as e:
        print("\n" + "!"*72 + f"\n!! FIGURES NOT WRITTEN: {e}\n"
              f"!! interpreter: {sys.executable}\n"
              f"!! Re-run with `python {Path(__file__).name}` from the venv "
              f"(the `py`\n!! launcher follows this file's shebang and can pick "
              f"the wrong Python).\n" + "!"*72)
        return None
    if path is None:
        FIG_DIR.mkdir(exist_ok=True)
        path = FIG_DIR / "uvlo_constraints.png"

    # Each panel shows the zero-margin boundary AND its closed form, obtained
    # by setting that margin to zero in the V_IN equation (S = R1a + R1b):
    panels = [("C1: turn-on guaranteed by %.1f V" % VIN_ON, c1_margin,
               "$R_2 \\leq S(%.1f-V_{th}^{max})/"
               "(V_{th}^{max}+I_{ref}R_{1a}-I_{STBY}^{min}S)$\n"
               "curve through origin; asymptote $S_\\infty\\approx1.35$M"
               % VIN_ON),
              ("C2: latch-off below turn-on (Vlatch < Von)", c2_margin,
               r"$R_2 \geq \Delta S/(I_{HYS}^{min}S-\Delta)$" "\n"
               r"$\Delta=V_{TLV}^{max}S/R_{1a}+I_{ref}R_{1b}-V_{th}^{min}$"
               "\nhyperbola, asymptote $S=\\Delta/I_{HYS}$"),
              ("C3: latch-off above LM5176 dropout (Vlatch > Voff)", c3_margin,
               r"$S \geq R_{1a}(V_{th}^{max}-I_{ref}R_{1b})/V_{TLV}^{min}$"
               "\nvertical: independent of $R_2$"),
              ("C4: turn-on not below %.1f V" % VON_MIN, c4_margin,
               "$R_2 \\geq S(%.1f-V_{th}^{min})/"
               "(V_{th}^{min}+I_{ref}R_{1a}-I_{STBY}^{max}S)$\n"
               "same family as C1; asymptote $S_\\infty\\approx409$k\n"
               "(inside this window -> the steep right-hand sweep)" % VON_MIN)]
    colors = ["#2a6f97", "#e07a1f", "#7d5fa6"]
    S = np.linspace(120e3, 520e3, 52)
    R2 = np.linspace(120e3, 1.2e6, 52)
    SS, RR = np.meshgrid(S, R2)
    rec_S = recommended[1] + recommended[2]
    rec_R2 = recommended[0]

    def grid(fn, r1a):
        Z = np.full_like(SS, np.nan)
        for i in range(SS.shape[0]):
            for j in range(SS.shape[1]):
                r1b = SS[i, j] - r1a
                if r1b > 2e3:
                    Z[i, j] = fn(RR[i, j], r1a, r1b)
        return Z

    # available parts at the middle R1a; green if the triple passes ALL four
    r1a_dot = r1a_vals[1]
    pass_S, pass_R2, fail_S, fail_R2 = _eseries_dots(r1a_dot, S[0], S[-1], R2[0], R2[-1])
    n_pass = len(pass_S)

    fig, axs = plt.subplots(2, 2, figsize=(11, 8.6))
    for ax, (title, fn, eqn) in zip(axs.ravel(), panels):
        ax.contourf(SS/1e3, RR/1e3, (grid(fn, r1a_vals[1]) >= 0).astype(float),
                    levels=[0.5, 1.5], colors=["#bfe3c0"], alpha=0.45)
        ax.scatter(fail_S, fail_R2, s=4, c="#c7c7c7", alpha=0.30, linewidths=0, zorder=2)
        ax.scatter(pass_S, pass_R2, s=24, c="#16a34a", alpha=1.0,
                   edgecolors="#0b5d23", linewidths=0.4, zorder=5)
        for r1a, col in zip(r1a_vals, colors):
            ax.contour(SS/1e3, RR/1e3, grid(fn, r1a), levels=[0],
                       colors=[col], linewidths=2, zorder=4)
        ax.plot(rec_S/1e3, rec_R2/1e3, marker="*", ms=16, color="#b8002e",
                mec="white", mew=0.8, zorder=6)
        ax.grid(True, which="both", ls=":", lw=0.6, color="#cccccc", alpha=0.8, zorder=0)
        ax.set_axisbelow(True)
        ax.set_title(title, fontsize=10.5, pad=6)
        ax.text(0.97, 0.96, eqn, transform=ax.transAxes, ha="right", va="top",
                fontsize=8.6, bbox=dict(boxstyle="round,pad=0.28", fc="white",
                                        ec="#999999", alpha=0.9))
        ax.set_xlabel(r"$R_{1a}+R_{1b}$  (k$\Omega$)", fontsize=9.5)
        ax.set_ylabel(r"$R_2$  (k$\Omega$)", fontsize=9.5)
        ax.tick_params(labelsize=8.5)

    handles = [Line2D([0], [0], color=c, lw=2, label=f"$R_{{1a}}$={int(r/1e3)}k")
               for r, c in zip(r1a_vals, colors)]
    handles += [Line2D([0], [0], marker="o", ls="", ms=8, color="#16a34a",
                       mec="#0b5d23", label=f"{SERIES} part: passes all 4 (n={n_pass})"),
                Line2D([0], [0], marker="o", ls="", ms=6, color="#c7c7c7",
                       label=f"{SERIES} part: fails >=1"),
                Line2D([0], [0], marker="*", ls="", ms=13, color="#b8002e",
                       mec="white", label="chosen (max $V_{on}^{min}$)")]
    fig.legend(handles=handles, loc="upper center", ncol=3, fontsize=9,
               bbox_to_anchor=(0.5, 1.02), frameon=False)
    fig.suptitle(r"Worst-case constraint boundaries in the $(R_{1a}{+}R_{1b},\,R_2)$ plane",
                 y=1.05, fontsize=12, weight="bold")
    fig.text(0.5, -0.012, "Shading + dots are for the middle $R_{1a}$ (the recommended one). "
             "Dots are available %s parts; green pass all four constraints. C1/C4 (turn-on) "
             "barely move with the split; C2/C3 (latch placement) follow the $R_{1a}/R_{1b}$ "
             "ratio and fan out. True feasible set = intersection of all four." % SERIES,
             ha="center", fontsize=8.4, style="italic")
    fig.tight_layout(rect=[0, 0.01, 1, 0.99])
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"plot_constraints: wrote {path}")
    return path

def plot_overlap(path=None, recommended=(420e3, 150e3, 15e3)):
    """Single combined figure at the recommended R1a: all four boundaries plus
    the shaded all-four overlap, with available-part dots, so the size of the
    feasible region is obvious at a glance."""
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
    except ImportError as e:
        print(f"plot_overlap: skipped ({e}) -- see the banner above.")
        return None
    if path is None:
        FIG_DIR.mkdir(exist_ok=True)
        path = FIG_DIR / "uvlo_overlap.png"

    r1a = recommended[1]
    rec_S = (recommended[1] + recommended[2]) / 1e3
    rec_R2 = recommended[0] / 1e3
    S = np.linspace(150e3, 215e3, 72)        # zoomed onto the overlap neighborhood
    R2 = np.linspace(280e3, 520e3, 72)
    SS, RR = np.meshgrid(S, R2)

    fns = [("C1  turn-on <= %.1f V" % VIN_ON, c1_margin, "#2a6f97"),
           ("C2  Vlatch < Von",               c2_margin, "#e07a1f"),
           ("C3  Vlatch > Voff",              c3_margin, "#7d5fa6"),
           ("C4  turn-on >= %.1f V" % VON_MIN, c4_margin, "#1a8a3a")]

    Zs = []
    feas = np.ones_like(SS, dtype=bool)
    for _, fn, _ in fns:
        Z = np.full_like(SS, np.nan)
        for i in range(SS.shape[0]):
            for j in range(SS.shape[1]):
                r1b = SS[i, j] - r1a
                if r1b > 2e3:                         # nan elsewhere -> no spurious
                    Z[i, j] = fn(RR[i, j], r1a, r1b)  # contour; (nan>=0)=False
        Zs.append(Z)
        feas &= (Z >= 0)

    fig, ax = plt.subplots(figsize=(8.4, 6.2))
    ax.contourf(SS/1e3, RR/1e3, feas.astype(float), levels=[0.5, 1.5],
                colors=["#9ad6a6"], alpha=0.55, zorder=1)
    for (label, _, col), Z in zip(fns, Zs):
        ax.contour(SS/1e3, RR/1e3, Z, levels=[0], colors=[col], linewidths=2.2, zorder=3)

    # Equi-turn-on (iso-Von_min) curves. From the VIN equation at Ven = Vth,
    # I_S = I_STBY:  Von_min = Vth + (R2/S)*(Vth + Iref*R1a - I_STBY*S), whose
    # level sets are R2 = S(V - Vth)/(Vth + Iref*R1a - I_STBY*S) -- the SAME
    # family as the C1/C4 boundaries (their V = VIN_ON and VON_MIN members).
    # NOT straight lines: they pass through the origin but steepen and diverge
    # at S_inf = (Vth + Iref*R1a)/I_STBY (~409k here, shared with C4).
    # Design improves by moving up-left onto a higher curve, until it leaves
    # the feasible region at the C1 ceiling.
    VON = np.full_like(SS, np.nan)
    for i in range(SS.shape[0]):
        for j in range(SS.shape[1]):
            r1b = SS[i, j] - r1a
            if r1b > 2e3:
                VON[i, j] = c4_margin(RR[i, j], r1a, r1b) + VON_MIN
    lv = [l for l in (2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 3.0)
          if np.nanmin(VON) < l < np.nanmax(VON)]
    if lv:
        cs = ax.contour(SS/1e3, RR/1e3, VON, levels=lv, colors="#666666",
                        linestyles="--", linewidths=1.0, alpha=0.85, zorder=2)
        ax.clabel(cs, fmt=lambda v: f"{v:.1f} V", fontsize=7.5, inline=True)

    pS, pR2, fS, fR2 = _eseries_dots(r1a, S[0], S[-1], R2[0], R2[-1])
    ax.scatter(fS, fR2, s=14, c="#cfcfcf", alpha=0.5, linewidths=0, zorder=2)
    ax.scatter(pS, pR2, s=46, c="#16a34a", edgecolors="#0b5d23", linewidths=0.6, zorder=4)
    ax.plot(rec_S, rec_R2, marker="*", ms=20, color="#b8002e", mec="white", mew=0.9, zorder=5)

    ax.grid(True, ls=":", lw=0.6, color="#cccccc", alpha=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.set_xlabel(r"$R_{1a}+R_{1b}$  (k$\Omega$)", fontsize=10)
    ax.set_ylabel(r"$R_2$  (k$\Omega$)", fontsize=10)
    ax.set_title(r"Combined feasible region at $R_{1a}=%d\,$k$\Omega$ (green = all four pass, n=%d)"
                 % (round(r1a/1e3), len(pS)), fontsize=11.5, weight="bold")

    handles = [Line2D([0], [0], color=col, lw=2.2, label=label) for label, _, col in fns]
    handles += [Line2D([0], [0], marker="s", ls="", ms=11, color="#9ad6a6",
                       label="overlap (all four)"),
                Line2D([0], [0], marker="o", ls="", ms=8, color="#16a34a", mec="#0b5d23",
                       label="part: passes all four"),
                Line2D([0], [0], ls="--", color="#666666", lw=1.0,
                       label="equi-turn-on $V_{on}^{min}$ (move up-left)"),
                Line2D([0], [0], marker="*", ls="", ms=13, color="#b8002e", mec="white",
                       label="chosen (max $V_{on}^{min}$)")]
    ax.legend(handles=handles, loc="upper left", fontsize=8.6, framealpha=0.9)
    fig.text(0.5, -0.02,
             "Boundaries are zero-margin loci. C1/C4 and the dashed equi-turn-on contours are one "
             "family, $R_2=S(V-V_{th})/(V_{th}+I_{ref}R_{1a}-I_{STBY}S)$ -- through the origin but "
             "curving up to a vertical asymptote at $S_\\infty=(V_{th}+I_{ref}R_{1a})/I_{STBY}$ "
             "($\\approx$409k for C4, 1.35M for C1). C3 is vertical ($R_2$-free); C2 is a "
             "hyperbola. Higher $V_{on}^{min}$ = up-left, bounded by the C1 ceiling.",
             ha="center", fontsize=8.2, style="italic", wrap=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"plot_overlap: wrote {path}")
    return path

# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def main():
    ok, glo, ghi = _verify_cancellation()
    print(f"Cancellation self-test: per-unit latch gap invariant to LM5176 currents "
          f"-> {'PASS' if ok else 'FAIL'} (gap={glo*1000:.1f} mV at both current extremes)\n")

    results = search()
    print(f"\n{len(results)} resistor combinations pass all worst-case constraints "
          f"(sorted by SORT_MODE='{SORT_MODE}').\n")
    if not results:
        print("No solution. Causes to check: VON_MIN (C4) may exceed what C2 allows at"
              " these tolerances (see the VON_MIN note); else lower HYST_LO/HYST_HI,"
              " widen R2 range, enable COMPOSITE legs, or relax VIN_ON_FLOOR.")
        return

    def rng(lohi):
        return f"{lohi[0]:.2f}-{lohi[1]:.2f}"

    hdr = (f"{'R2':>8} {'R1a':>8} {'R1b':>7} | {'Von (on)':>11} {'Voff (LM)':>11} "
           f"{'Vlatch':>11} | {'gap_lo':>6} {'gap_hi':>6} {'Vonmin':>6} | {'EN@22':>5}")
    print(hdr)
    print("-"*len(hdr))
    for margin, r2, r1a, r1b, wc, rep in results[:TOP_N]:
        von_r, voff_r, vlatch_r = vin_ranges(r2, r1a, r1b)
        print(f"{fmt_r(r2):>8} {fmt_r(r1a):>8} {fmt_r(r1b):>7} | "
              f"{rng(von_r):>11} {rng(voff_r):>11} {rng(vlatch_r):>11} | "
              f"{rep['gap_lo']:6.2f} {rep['gap_hi']:6.2f} {wc['von_min']:6.2f} | "
              f"{rep['ven_22']:5.2f}")
        notes = [f"{leg}: {describe(leg, val)}"
                 for leg, val in (("R2", r2), ("R1A", r1a), ("R1B", r1b))
                 if COMPOSITE.get(leg)]
        if notes:
            print("           -> " + "; ".join(notes))

    print("\nColumn key (all VIN values in volts; ranges are worst-case min-max bands):")
    print(f"  Von (on)  = turn-on VIN, standby. Whole band must sit below {VIN_ON:.1f} (C1).")
    print("  Voff (LM) = VIN where the LM5176 alone WOULD drop out. The latch fires first,")
    print("              so this point is never actually reached.")
    print("  Vlatch    = VIN where V_REF = V_TLV. Above it the latch is held off (dearmed);")
    print("              below it the latch engages. Must sit between Voff and Von per unit.")
    print("  gap_lo    = GUARANTEED per-unit (Vlatch - Voff): the latch trips this far ABOVE")
    print("              the LM5176's own dropout on a falling input (C3). >0 always.")
    print("  gap_hi    = GUARANTEED per-unit (Von - Vlatch): the latch-off point sits this")
    print("              far BELOW turn-on (C2) -> V_REF is above V_TLV at turn-on, so the")
    print("              latch is dearmed before it can grab. >0 always.")
    print("              Larger R2 (more LM5176 hysteresis) is what buys room for both.")
    print(f"  Vonmin    = worst-case EARLIEST turn-on. Must stay >= {VON_MIN:.1f} V (C4: don't")
    print("              turn on before the rail/converter is ready). Fights C2 -- see the")
    print("              VON_MIN note in the parameter block.")
    print("  EN@22     = nominal EN-node voltage at 22 V (informational; the LM5176 EN pin")
    print("              only -- TLV431 Vka is set by the separate latch circuit).")
    print("\nBoth gap columns are correlated per-unit differences (shared currents cancel),")
    print("so they cannot be read off the Von/Voff/Vlatch band extremes -- those bands can")
    print("overlap on paper while every individual device still keeps Voff < Vlatch < Von.")
    print("\nReminder (latch circuit, not the divider): the latch defaults to engaged and")
    print("is held off only while V_REF > V_TLV. Vlatch < Von guarantees V_REF is above")
    print("V_TLV at turn-on; the latch is powered from VOUT, so at cold start (VOUT = 0)")
    print("it cannot grab before the converter starts -- see 10b_uvlo_latch.py.")

    if MAKE_PLOT and results:
        rec = (results[0][1], results[0][2], results[0][3])
        r1a = rec[1]
        plot_constraints(r1a_vals=(0.7*r1a, r1a, 1.45*r1a), recommended=rec)
        plot_overlap(recommended=rec)

if __name__ == "__main__":
    main()
