#!/usr/bin/env py
"""
Resistor sizing for an LM5176 EN/UVLO threshold with a TLV431 latch.

Topology (single EN/UVLO node):
    VIN --[R2]-- EN --[R1b]-- REF --[R1a]-- GND
TLV431 REF pin sits on the REF node and draws Iref into the pin.
LM5176 sources I_S = I_STBY + I_H out of the EN pin (I_H = 0 standby, I_HYS running).

Core equations (see uvlo_tlv431.tex):
    V_EN  = [Vin*(R1a+R1b) + I_S*R2*(R1a+R1b) - Iref*R1a*R2] / (R1a+R1b+R2)
    V_REF = R1a*(V_EN - Iref*R1b) / (R1a+R1b)
    V_EN at TLV trip (V_REF = V_TLV) = V_TLV*(R1a+R1b)/R1a + Iref*R1b   [Vin-independent]

The search finds (R2, R1a, R1b) from an E-series that satisfy every design
constraint at the worst tolerance/parameter corner. Resistors are treated as
+/- TOL (default 5%); every parameter sweeps its min/max extreme.

Latch behavior assumed here:
    The external latch (powered from VIN) defaults to ENGAGED and is held off
    only while V_REF > V_TLV ("dearmed"). There is no arm-after-first-release
    grace: if V_REF ever sits below V_TLV while the converter is running, the
    latch grabs and pulls EN low until a power cycle. So the trip point Vlatch
    must sit inside the LM5176 hysteresis window for EVERY unit:
        Voff < Vlatch < Von
        Von    = LM5176 turn-on   (standby threshold crossing)
        Voff   = LM5176 dropout   (running threshold crossing)
        Vlatch = TLV431 trip      (V_REF = V_TLV, running)
    Vlatch < Von means V_REF is already above V_TLV the instant the converter
    turns on, so the latch is dearmed at turn-on and a slow rise leaves no
    running-but-not-dearmed window. Vlatch > Voff means the latch fires before
    the LM5176's own UVLO on the way down.
    Identity:  Von - Vlatch = I_HYS*R2 - (Vlatch - Voff). The latch-off point can
    only sit below turn-on if the LM5176 hysteresis I_HYS*R2 exceeds the
    Vlatch-Voff gap; the Vth (+/-0.06) and V_TLV (+/-0.03) spreads blow that gap
    up by ~K, so satisfying it is tight -- it forces a large R2 (hence a low,
    soft turn-on with divider current near the LM5176 bias current). The
    BIAS_RATIO_MIN guard rejects the degenerate region where the bias currents,
    not VIN, set the EN voltage.
    Resistor source (SERIES="JLCPCB", default): values come straight from
    constants.py (MFG.BASIC_0603_RESISTORS) -- the real stocked JLCPCB basic-part
    0603 list, so any hit is buildable with no extended-part fee. That list is
    far coarser than a full E96 sweep, and the feasible region here is already a
    thin sliver (see VON_MIN note below), so with SINGLE basic-part resistors on
    every leg there is NO triple that clears all four constraints (closest miss:
    300k/120k/8.2k, short by ~35 mV on C2/C3).
    COMPOSITE (series/parallel pairs of basic parts, see COMPOSITE dict below)
    closes that gap: with just R2 built from two basic parts (R1a, R1b stay
    single), best result is R2=390k (120k+270k series) / R1a=150k / R1b=12k,
    clearing every constraint by >=10.5 mV worst-case -- one extra placement,
    still zero extended-part fees. Enabling composite on R1a/R1b instead finds
    solutions too, but with thinner margin (~7-8 mV) and two extra placements
    instead of one, so R2-only is the better default (see COMPOSITE below).
"""

from itertools import product, combinations_with_replacement

# --------------------------------------------------------------------------
# Resistor value source: real JLCPCB basic-part 0603 library (constants.py)
# --------------------------------------------------------------------------
# Pulls the actual stocked 0603 values from constants.py (MFG.BASIC_0603_RESISTORS)
# instead of a generated E24/E96 series. This restricts the search to resistors
# that are basic parts at JLCPCB (no extended-part fee, no stock-out risk), at the
# cost of coarser coverage than a full E96 sweep (constants.py's list is curated,
# not every E96 mantissa in every decade).
try:
    from constants import MFG
    _JLCPCB_VALUES = sorted(float(v) for v in MFG.BASIC_0603_RESISTORS)
except ImportError:
    _JLCPCB_VALUES = None
    print("warning: could not import MFG from constants.py -- SERIES=\"JLCPCB\" will "
          "raise at search time. Put constants.py on the path, or switch SERIES to "
          "\"E24\"/\"E96\" to fall back to a generated series.")

# --------------------------------------------------------------------------
# Parameters (edit to match your datasheet revision)
# --------------------------------------------------------------------------
VIN_ON      = 4.5      # V  turn-on must be guaranteed by here. 4.5 V already folds in
                       #     USB cable drop + source tolerance; extra margin comes from
                       #     sitting away from the boundary, not from lowering this.
VIN_MAX     = 22.0     # V  input maximum (USB max)

VTH_MIN     = 1.17     # V  LM5176 EN/UVLO operating threshold, min
VTH_MAX     = 1.29     # V  ... max

ISTBY_MIN   = 1.0e-6   # A  standby source current
ISTBY_MAX   = 3.0e-6
IHYS_MIN    = 2.15e-6  # A  hysteresis source current (added after turn-on)
IHYS_MAX    = 4.25e-6
IREF_MIN    = 0.0      # A  TLV431 REF input current
IREF_MAX    = 0.38e-6

VTLV_MIN    = 1.206    # V  effective TLV431 reference, min
VTLV_MAX    = 1.266    # V  ... max

R_TOL       = 0.05     # resistor tolerance (+/-)
# The latch defaults to ENGAGED and is held off ("dearmed") only while
# V_REF > V_TLV. So V_REF must cross V_TLV during turn-on and stay above it
# throughout normal operation, or the latch grabs. That forces the trip point
# Vlatch to sit INSIDE the LM5176 hysteresis window for EVERY unit:
#       Voff  <  Vlatch  <  Von
# HYST_LO = required per-unit (Vlatch - Voff): latch trips this far ABOVE the
#           LM5176's own dropout on a falling input (C3).
# HYST_HI = required per-unit (Von - Vlatch): latch-off sits this far BELOW
#           turn-on (C2). Below turn-on, V_REF is already above V_TLV at the
#           moment the converter starts, so the latch is dearmed at turn-on and
#           a slow rise cannot leave a running-but-not-dearmed window.
# Identity: (Von - Vlatch) = I_HYS*R2 - (Vlatch - Voff), so HYST_LO + HYST_HI
# must fit inside the LM5176 hysteresis I_HYS*R2 -> larger R2 buys room, but
# only until the divider current sinks to the LM5176 bias currents (see below).
# Margins are 0 by default: the constraints already use 5% resistors (looser than
# JLCPCB 1% 0603 + 100 ppm/C) and worst-case TLV431/LM5176 values, so a further
# explicit margin is redundant. Buy headroom by sitting inside the feasible area
# (SORT_MODE="interior"), not by inflating these. Set >0 only to force extra slack.
HYST_LO     = 0.0      # V
HYST_HI     = 0.0      # V

# Reject designs whose divider current is too weak vs the LM5176 bias currents,
# i.e. where the EN pin is held up by I_STBY/I_HYS rather than tracking VIN.
BIAS_RATIO_MIN = 1.0   # min (divider current at turn-on) / (total bias current)

# C4: do not turn on too early. The earliest possible turn-on (worst-case Von)
# must stay above this, e.g. so a not-yet-settled USB rail isn't loaded and the
# buck-boost isn't asked to operate/boost from an impractically low input.
#
# CAUTION -- C4 fights C2. Forcing Vlatch < Von (C2) needs a large R2, which (with
# I_STBY spanning 1-3 uA) smears turn-on across a ~1.5 V band, dragging the
# worst-case earliest Von down. Achievable floor vs. C2/C3 margin (4.5 V ceiling):
#       margin 0.10 V -> Von floor <= ~1.9 V
#       margin 0.05 V -> Von floor <= ~2.2 V
#       margin 0.00 V -> Von floor <= ~2.6 V
# So 2.5 V fits only at ~0 margin; the feasible overlap is then a thin sliver and
# the most-interior design clears every boundary by only ~0.05 V. Lower VON_MIN if
# you want more room to back away from the edges.
VON_MIN     = 2.5      # V  worst-case earliest turn-on floor

# Search space
SERIES      = "JLCPCB" # "JLCPCB" -> real stocked 0603 basic-part values from
                       #     constants.py (MFG.BASIC_0603_RESISTORS); avoids extended-
                       #     part fees / stock-outs, at coarser coverage than E96.
                       # "E24"/"E96" -> generated series (fallback, ignores real stock)
                       # (values assumed at +/- R_TOL regardless of series choice)
R1A_RANGE   = (20e3, 1.0e6)    # bottom resistor nominal search range
R1B_RANGE   = (2e3, 500e3)     # mid resistor nominal search range
R2_RANGE    = (20e3, 3.0e6)    # top resistor nominal search range
VIN_ON_FLOOR= 1.5      # V  reject if nominal turn-on falls below this (self-consistency forces low turn-on)
TOP_N       = 15       # how many solutions to print
MAKE_PLOT   = True     # write uvlo_constraints.png (needs numpy + matplotlib)
SORT_MODE   = "interior" # "interior"-> furthest from all 4 boundaries (most robust pick)
                       # "balanced"-> largest min(gap_lo, gap_hi)
                       # "gap_lo"  -> most margin between latch-off and LM5176 dropout
                       # "gap_hi"  -> most hysteresis between latch-off and turn-on
                       # "tight"   -> turn-on closest to VIN_ON
                       # "low_en22"-> smallest EN-node voltage at VIN_MAX

# Series/parallel synthesis from JLCPCB basic-part values (SERIES="JLCPCB" only):
# combine TWO basic-part 0603 resistors at one node -- still no extended-part
# fee, just one extra placement -- to fill in gaps between the ~50 stocked
# values. Valid at the same R_TOL used everywhere else: the fractional
# tolerance of a series or parallel pair of equal-tolerance parts is bounded by
# that same tolerance (exactly for series; generally tighter for parallel), so
# a composite leg is never worse than a single R_TOL-toleranced part in the
# worst-case corner search -- it's just another candidate value.
# Per-leg toggle -- OFF by default except R2. Turning more legs on multiplies
# the candidate counts (~50 singles -> ~1500-2500 composites per leg) and
# search time; empirically R2-only composite already finds solutions (singles
# alone find none -- see docstring), with BETTER worst-case margin than adding
# R1A/R1B composite instead (~10.5 mV interior vs ~7-8 mV), at 1 extra placement
# instead of 2, and in ~5 s instead of ~3 min. Enable R1A/R1B too only if you
# want to explore alternatives.
COMPOSITE   = {"R1A": False, "R1B": False, "R2": True}

# --------------------------------------------------------------------------
# Equations
# --------------------------------------------------------------------------
def v_en(vin, r2, r1a, r1b, i_s, iref):
    num = vin*(r1a+r1b) + i_s*r2*(r1a+r1b) - iref*r1a*r2
    return num/(r1a+r1b+r2)

def v_ref(vin, r2, r1a, r1b, i_s, iref):
    return r1a*(v_en(vin, r2, r1a, r1b, i_s, iref) - iref*r1b)/(r1a+r1b)

def v_en_at_trip(r1a, r1b, vtlv, iref):
    return vtlv*(r1a+r1b)/r1a + iref*r1b

def vin_for_ven(ven, r2, r1a, r1b, i_s, iref):
    return (ven*(r1a+r1b+r2) - i_s*r2*(r1a+r1b) + iref*r1a*r2)/(r1a+r1b)

# --------------------------------------------------------------------------
# E-series
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

# Recipes: leg name -> {rounded_value: "how to build it"} for reporting BOM
# detail on any leg that used COMPOSITE (series/parallel pair) synthesis.
_RECIPES = {}

def _composite_pool(base_vals, lo, hi):
    """All values buildable from one or two JLCPCB basic-part resistors,
    within [lo, hi]. Returns (sorted_values, recipes) where recipes maps each
    rounded value to a short description of the parts/topology to build it."""
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
    if name == "JLCPCB":
        if _JLCPCB_VALUES is None:
            raise RuntimeError(
                "SERIES=\"JLCPCB\" but MFG could not be imported from constants.py. "
                "Put constants.py on the Python path, or set SERIES to \"E24\"/\"E96\".")
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
    """Human-readable recipe for a resistor value on a given leg."""
    rec = _RECIPES.get(leg, {})
    return rec.get(round(value, 6), f"{fmt_r(value)} (single)")

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
    """Worst-case per-unit hysteresis gaps, in VIN volts.

    For each device (resistors + chip params held consistent), three running-state
    events share the same currents, so their differences are clean:
        Von   = VIN where V_EN(standby) = V_th             (LM5176 turn-on)
        Voff  = VIN where V_EN(running) = V_th             (LM5176 self-dropout)
        Vlatch= VIN where V_EN(running) = V_EN_trip(V_TLV) (TLV431 latch threshold)
    We need  Voff < Vlatch < Von  for every unit:
        glo = min over corners of (Vlatch - Voff)   [C3: latch trips before dropout]
        ghi = min over corners of (Von    - Vlatch) [C2: latch-off below turn-on]
    Identity:  (Von - Vlatch) = I_HYS*R2 - (Vlatch - Voff), so glo + ghi <= I_HYS*R2.
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
    # C1: turn-on guaranteed by VIN_ON. Equivalent to min V_EN(standby,4.5) >= Vth_max.
    c1 = min(v_en(VIN_ON, r2n*a, r1an*b, r1bn*c, ISTBY_MIN, IREF_MAX)
             for a, b, c in _CORNERS)
    if c1 < VTH_MAX:
        return None

    # Bias-domination guard: divider current at turn-on vs LM5176 bias currents.
    # Worst (weakest) corner: smallest (VIN_ON - Vth)/R2, largest bias.
    i_div = (VIN_ON - VTH_MAX) / (r2n * 1.05)
    bias_ratio = i_div / (ISTBY_MAX + IHYS_MAX)
    if bias_ratio < BIAS_RATIO_MIN:
        return None

    # C4: turn-on must NOT occur below VON_MIN, worst case (earliest possible Von).
    # Earliest turn-on = lowest VIN that lifts standby V_EN to Vth: Vth low, I_STBY high.
    von_min_wc = min(
        vin_for_ven(vth, r2n*a, r1an*b, r1bn*c, ist, irf)
        for a, b, c in _CORNERS
        for vth in _VTH for ist in _ISTBY for irf in _IREF)
    if von_min_wc < VON_MIN:
        return None

    glo, ghi = hysteresis_worst(r2n, r1an, r1bn)
    ok_c3 = glo >= HYST_LO     # Vlatch - Voff  (latch trips before LM5176 dropout)
    ok_c2 = ghi >= HYST_HI     # Von    - Vlatch (latch dearmed below turn-on)
    if not (ok_c2 and ok_c3):
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

    These are honest spans of each event across the population, but they are NOT
    directly comparable to each other -- see latch_margin_worst() for the per-unit
    guarantee. Two different events whose bands appear to overlap never overlap
    within a single device, because shared parameters cancel in the difference.
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

    Both events are running-state events of the SAME device at the SAME instant,
    so I_STBY, I_HYS, VIN and R2 are identical for both and cancel in the
    difference. The gap therefore depends only on the lower leg:
        Vlatch - Voff = (V_EN_trip - V_th) * (R1a+R1b+R2)/(R1a+R1b),
    with V_EN_trip - V_th independent of any current. We minimise it over the
    resistor corners and the (V_th, V_TLV, I_ref) extremes that shrink the gap.
    """
    gaps = []
    Is_dummy = 0.5*(ISTBY_MIN+ISTBY_MAX) + 0.5*(IHYS_MIN+IHYS_MAX)  # cancels anyway
    for a, b, c in _CORNERS:
        r2, r1a, r1b = r2n*a, r1an*b, r1bn*c
        for vth in _VTH:
            for vtl in _VTLV:
                for irf in _IREF:
                    vtrip = v_en_at_trip(r1a, r1b, vtl, irf)
                    g = (vin_for_ven(vtrip, r2, r1a, r1b, Is_dummy, irf)
                         - vin_for_ven(vth, r2, r1a, r1b, Is_dummy, irf))
                    gaps.append(g)
    return min(gaps)

def _verify_cancellation():
    """Confirm the per-unit latch gap is invariant to the LM5176 currents."""
    r2, r1a, r1b = 287e3, 110e3, 16.2e3
    vtrip = v_en_at_trip(r1a, r1b, VTLV_MIN, 0.0)
    g_lo = (vin_for_ven(vtrip, r2, r1a, r1b, ISTBY_MIN+IHYS_MIN, 0.0)
            - vin_for_ven(VTH_MAX, r2, r1a, r1b, ISTBY_MIN+IHYS_MIN, 0.0))
    g_hi = (vin_for_ven(vtrip, r2, r1a, r1b, ISTBY_MAX+IHYS_MAX, 0.0)
            - vin_for_ven(VTH_MAX, r2, r1a, r1b, ISTBY_MAX+IHYS_MAX, 0.0))
    return abs(g_lo - g_hi) < 1e-12, g_lo, g_hi

def nominal_report(r2, r1a, r1b):
    """Nominal operating points for a passing candidate."""
    # turn-on VIN (standby), typ threshold
    vth_typ = 0.5*(VTH_MIN+VTH_MAX)
    istby_typ = 0.5*(ISTBY_MIN+ISTBY_MAX)
    ihys_typ = 0.5*(IHYS_MIN+IHYS_MAX)
    iref_typ = 0.5*(IREF_MIN+IREF_MAX)
    vtlv_typ = 0.5*(VTLV_MIN+VTLV_MAX)

    vin_on = vin_for_ven(vth_typ, r2, r1a, r1b, istby_typ, iref_typ)
    vin_off_lm = vin_for_ven(vth_typ, r2, r1a, r1b, istby_typ+ihys_typ, iref_typ)
    ven_trip = v_en_at_trip(r1a, r1b, vtlv_typ, iref_typ)
    vin_latch = vin_for_ven(ven_trip, r2, r1a, r1b, istby_typ+ihys_typ, iref_typ)
    ven_22 = v_en(VIN_MAX, r2, r1a, r1b, istby_typ+ihys_typ, iref_typ)
    # divider current at 22 V (rough quiescent through R2)
    i_22 = (VIN_MAX - ven_22)/r2
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
    iref_typ = 0.5*(IREF_MIN+IREF_MAX)
    vth_typ = 0.5*(VTH_MIN+VTH_MAX)

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
                # cheap nominal hysteresis prune (mode-aware)
                ven_trip = v_en_at_trip(r1a, r1b, 0.5*(VTLV_MIN+VTLV_MAX), iref_typ)
                vlatch = vin_for_ven(ven_trip, r2, r1a, r1b, istby_typ+0.5*(IHYS_MIN+IHYS_MAX), iref_typ)
                voff = vin_for_ven(vth_typ, r2, r1a, r1b, istby_typ+0.5*(IHYS_MIN+IHYS_MAX), iref_typ)
                if vlatch < voff + HYST_LO:
                    continue
                if vlatch > vin_on - HYST_HI:
                    continue
                wc = worst_case(r2, r1a, r1b)
                if wc is None:
                    continue
                rep = nominal_report(r2, r1a, r1b)
                rep["gap_lo"] = wc["gap_lo"]
                rep["gap_hi"] = wc["gap_hi"]
                rep["vlatch_max"] = wc["vlatch_max"]
                rep["bias_ratio"] = wc["bias_ratio"]
                # interior = worst-case distance (V) to the nearest of the 4 boundaries
                von_r, _, _ = vin_ranges(r2, r1a, r1b)
                rep["interior"] = min(wc["gap_lo"], wc["gap_hi"],
                                      VIN_ON - von_r[1],          # C1 headroom below ceiling
                                      wc["von_min"] - VON_MIN)    # C4 headroom above floor
                margin = min(wc["gap_lo"], wc["gap_hi"])   # balanced robustness metric
                results.append((margin, r2, r1a, r1b, wc, rep))

    # sort
    if SORT_MODE == "gap_lo":
        results.sort(key=lambda x: -x[5]["gap_lo"])            # most margin before dropout
    elif SORT_MODE == "gap_hi":
        results.sort(key=lambda x: -x[5]["gap_hi"])            # most hysteresis below turn-on
    elif SORT_MODE == "balanced":
        results.sort(key=lambda x: -x[0])                     # max min(gap_lo, gap_hi)
    elif SORT_MODE == "tight":
        results.sort(key=lambda x: (-x[5]["vin_on"]))          # turn-on near VIN_ON
    elif SORT_MODE == "low_en22":
        results.sort(key=lambda x: (x[5]["ven_22"]))           # minimize EN at 22 V
    else:
        results.sort(key=lambda x: -x[5]["interior"])          # interior: furthest from all edges
    return results

def fmt_r(x):
    if x >= 1e6: return f"{x/1e6:.3f}M".rstrip('0').rstrip('.')+"M" if False else f"{x/1e6:g}M"
    if x >= 1e3: return f"{x/1e3:g}k"
    return f"{x:g}"

def c1_margin(r2, r1a, r1b):
    return min(v_en(VIN_ON, r2*a, r1a*b, r1b*c, ISTBY_MIN, IREF_MAX)
               for a, b, c in _CORNERS) - VTH_MAX
def c4_margin(r2, r1a, r1b):
    return min(vin_for_ven(vth, r2*a, r1a*b, r1b*c, ist, irf)
               for a, b, c in _CORNERS for vth in _VTH
               for ist in _ISTBY for irf in _IREF) - VON_MIN
def c2_margin(r2, r1a, r1b):
    return hysteresis_worst(r2, r1a, r1b)[1] - HYST_HI   # gap_hi
def c3_margin(r2, r1a, r1b):
    return hysteresis_worst(r2, r1a, r1b)[0] - HYST_LO   # gap_lo

def _eseries_dots(r1a, S_lo, S_hi, R2_lo, R2_hi):
    """Available E-series (R1b, R2) parts at fixed R1a in the window; split pass/fail."""
    r1b_opts = [v for v in eseries_values(SERIES, max(R1B_RANGE[0], 2e3), R1B_RANGE[1], leg="R1B")
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

def plot_constraints(path="uvlo_constraints.png", r1a_vals=(162e3, 232e3, 336e3),
                     recommended=(402e3, 154e3, 14e3)):
    """Render the four worst-case constraint boundaries in the (R1a+R1b, R2) plane.

    For each constraint, the zero-margin boundary is drawn for several R1a values.
    C1/C4 (turn-on) barely depend on the R1a/R1b split; C2/C3 (latch placement)
    depend on the ratio and fan out. The feasible region (shaded) is shown for the
    middle R1a. Requires numpy + matplotlib; skipped with a note if unavailable.
    """
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
    except ImportError:
        print("plot_constraints: numpy/matplotlib not available; skipping figure.")
        return None

    panels = [("C1: turn-on guaranteed by %.1f V" % VIN_ON, c1_margin,
               r"$\min\,V_{EN}(%.1f) \geq V_{th}^{\max}$  (~ sum)" % VIN_ON),
              ("C2: latch-off below turn-on (Vlatch < Von)", c2_margin,
               r"$\min(V_{on}-V_{latch}) \geq \Delta_{hi}$  (ratio & scale)"),
              ("C3: latch-off above LM5176 dropout (Vlatch > Voff)", c3_margin,
               r"$\min(V_{latch}-V_{off}) \geq \Delta_{lo}$  (~ ratio)"),
              ("C4: turn-on not below %.1f V" % VON_MIN, c4_margin,
               r"$\min\,V_{on} \geq %.1f$  (~ sum)" % VON_MIN)]
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

    # available E-series parts (at the middle R1a) that fall in the plot window;
    # green if (R1a, R1b, R2) passes ALL four constraints, else grey.
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
                       mec="white", label="recommended")]
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

def plot_overlap(path="uvlo_overlap.png", recommended=(402e3, 154e3, 14e3)):
    """Single combined plot at the recommended R1a: all four boundaries plus the
    shaded all-four overlap, with E-series dots, so the size of the feasible region
    is obvious at a glance."""
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
    except ImportError:
        print("plot_overlap: numpy/matplotlib not available; skipping figure.")
        return None

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
                if r1b > 2e3:                       # nan elsewhere -> no spurious contour,
                    Z[i, j] = fn(RR[i, j], r1a, r1b)  # and (nan>=0)=False keeps mask correct
        Zs.append(Z)
        feas &= (Z >= 0)

    fig, ax = plt.subplots(figsize=(8.4, 6.2))
    ax.contourf(SS/1e3, RR/1e3, feas.astype(float), levels=[0.5, 1.5],
                colors=["#9ad6a6"], alpha=0.55, zorder=1)
    for (label, _, col), Z in zip(fns, Zs):
        ax.contour(SS/1e3, RR/1e3, Z, levels=[0], colors=[col], linewidths=2.2, zorder=3)

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
                       label="E-series part: passes all four"),
                Line2D([0], [0], marker="*", ls="", ms=13, color="#b8002e", mec="white",
                       label="recommended")]
    ax.legend(handles=handles, loc="upper left", fontsize=8.6, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"plot_overlap: wrote {path}")
    return path

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
              " widen R2 range, or relax VIN_ON_FLOOR.")
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
              f"{rep['gap_lo']:6.2f} {rep['gap_hi']:6.2f} {wc['von_min']:6.2f} | {rep['ven_22']:5.2f}")
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
    print("              latch is dearmed before it can grab. >0 always.  Note")
    print("              R2 (more LM5176 hysteresis) is what buys room for both.")
    print(f"  Vonmin    = worst-case EARLIEST turn-on. Must stay >= {VON_MIN:.1f} V (C4: don't")
    print("              turn on before the rail/converter is ready). Fights C2 -- see header.")
    print("  EN@22     = nominal EN-node voltage at 22 V (informational; the LM5176 EN pin")
    print("              only -- TLV431 Vka is set by the separate latch circuit).")
    print("\nBoth gap columns are correlated per-unit differences (shared currents cancel),")
    print("so they cannot be read off the Von/Voff/Vlatch band extremes -- those bands can")
    print("overlap on paper while every individual device still keeps Voff < Vlatch < Von.")
    print("\nReminder (latch circuit, not the divider): the latch defaults to engaged")
    print("and is held off only while V_REF > V_TLV. Vlatch < Von guarantees V_REF is")
    print("above V_TLV at turn-on; ensure your startup also lets EN reach turn-on before")
    print("the latch can grab (a brief power-up release / RC delay on the latch).")

    if MAKE_PLOT and results:
        top = results[0]
        r1a = top[2]
        plot_constraints(r1a_vals=(0.7*r1a, r1a, 1.45*r1a),
                         recommended=(top[1], top[2], top[3]))
        plot_overlap(recommended=(top[1], top[2], top[3]))

if __name__ == "__main__":
    main()
