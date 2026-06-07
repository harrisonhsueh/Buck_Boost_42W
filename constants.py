"""
constants.py
Project: USB-C PD to 12V Fan Array Controller
Version: 1.4.0

Import-safety note (1.4.0):
    This module NO LONGER touches the filesystem at import time. The CSV-backed
    inductor/FET parts are loaded on demand via `make_design(load_parts=True)`
    (or `build_design_parts()`), and `component_utils` is imported only inside
    that function. As a result, `import constants` succeeds anywhere with just
    numpy installed, and the pure spec values (IC_LM5176, DESIGN_TARGETS, USB,
    FAN, MFG) are always available to this and any other script.

    Rationale: those spec values are the single source of truth for the UVLO /
    threshold analysis and must import without dragging in component_utils or
    the data/*.csv files. Scripts that actually need the part database call
    make_design(load_parts=True) and get a clear error if the files are missing.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Final, Dict, Optional, Tuple

# ==========================================
# 1. COMPONENT TEMPLATES (Blueprints)
# ==========================================

class IC_LM5176:
    # --- ENABLE / UVLO PIN SPECS ---
    # Thresholds (V)
    V_EN_NOM: Final = 1.22
    V_EN_MIN: Final = 1.17
    V_EN_MAX: Final = 1.29

    # Currents (A)
    I_HYS_NOM: Final = 3.15e-6
    I_HYS_MIN: Final = 2.15e-6
    I_HYS_MAX: Final = 4.25e-6

    I_STBY_NOM: Final = 2.0e-6
    I_STBY_MAX: Final = 4.0e-6  # Statically worst-case

    # Derived Sigma (Legal Min/Max treated as 4-sigma for Monte Carlo)
    V_EN_SIGMA: Final = (V_EN_MAX - V_EN_NOM) / 4
    I_HYS_SIGMA: Final = (I_HYS_MAX - I_HYS_NOM) / 4

class DESIGN_TARGETS:
    V_USB_MIN: Final = 4.50       # Hard Ceiling, must turn on before this point
    V_ON_SAFE_FLOOR: Final = 3.8  # Soft Floor for Gate Health, dont turn on before this
    V_HYS_MIN: Final = 0.2
    V_OFF_MIN: Final = 3.6        # must be off if fall below this
    HYS_MIN_GAP: Final = 0.25     # Min gap before Latch takes over
    MAX_DIVIDER_UW: Final = 500   # Power budget

@dataclass(frozen=True)
class InductorPart:
    PART_NUMBER: str
    L: float
    DCR: float
    I_SAT: float
    RP: float = 0.0
    RS_SPICE: float = 0.0
    CORE_LOSS_COEFF: float = 0.0

@dataclass(frozen=True)
class MosfetPart:
    PART_NUMBER: str
    MANUFACTURER: str
    RDSON_TYP: float
    RDSON_MAX: float
    QG_TYP: float
    QGD_TYP: float
    QGS_TYP: float
    VGS_TH_TYP: float
    RG_INT: float
    RTH_JC: float
    RTH_JA: float

# ==========================================
# 2. DATABASE / LIBRARY LOADING (lazy)
# ==========================================
# NOTE: No file I/O happens at import time. Call build_design_parts() (or
# make_design(load_parts=True)) where you actually need the part database.

ACTIVE_IND_ID = "7443634700"
ACTIVE_FET_ID = "BSC0902NS"

def build_design_parts(
    ind_csv: str = "data/inductors.csv",
    fet_csv: str = "data/mosfets.csv",
) -> Tuple[InductorPart, MosfetPart]:
    """Load the active inductor + FET from CSV.

    `component_utils` is imported here (not at module load) so that importing
    `constants` never requires it. Raises a clear error if the helper or the
    CSV files are unavailable.
    """
    from component_utils import get_component_specs  # local import on purpose

    ind_raw = get_component_specs(ACTIVE_IND_ID, ind_csv)
    fet_raw = get_component_specs(ACTIVE_FET_ID, fet_csv)

    inductor = InductorPart(
        PART_NUMBER=str(ind_raw['Part_Number']),
        L=float(ind_raw['Inductance_uH']) * 1e-6,
        DCR=float(ind_raw['DCR_typ_mOhm']) / 1000.0,
        I_SAT=float(ind_raw['Isat_10pct_A']),
        RP=float(ind_raw['Rp_Ohm']),
        RS_SPICE=float(ind_raw['Rs_spice_Ohm']),
        CORE_LOSS_COEFF=1.42,
    )

    mosfet = MosfetPart(
        PART_NUMBER=str(fet_raw['Part_Number']),
        MANUFACTURER=str(fet_raw['Manufacturer']),
        RDSON_TYP=float(fet_raw['RDSon_4.5V_Typ']) / 1000.0,
        RDSON_MAX=float(fet_raw['RDSon_4.5V_Max']) / 1000.0,
        QG_TYP=float(fet_raw['Qg_4.5V_Typ']) * 1e-9,
        QGD_TYP=float(fet_raw['Qgd_Typ']) * 1e-9,
        QGS_TYP=float(fet_raw['Qgs_Typ']) * 1e-9,
        VGS_TH_TYP=float(fet_raw['VGS_th_Typ']),
        RG_INT=float(fet_raw['RG_Internal_Typ']),
        RTH_JC=float(fet_raw['RthJC_Max']),
        RTH_JA=float(fet_raw['RthJA_Max']),
    )
    return inductor, mosfet

# ==========================================
# 3. SYSTEM & DESIGN CONFIGURATION
# ==========================================

@dataclass(frozen=True)
class USBCSpecs:
    V_MIN: float = 5.0
    V_MAX: float = 20.0
    V_TOLERANCE: float = 0.10
    I_MAX_HIGH_POWER: float = 5.0
    I_MAX_STANDARD: float = 3.0

@dataclass(frozen=True)
class FanSpecs:
    V_NOMINAL: float = 12.0
    I_MAX_PRO: float = 0.35
    I_MAX_PWM: float = 0.12
    MAX_COUNT: int = 10

@dataclass(frozen=True)
class DesignChoices:
    # Parts default to None so this dataclass (and the whole module) imports
    # without the CSVs. Populate them via make_design(load_parts=True).
    INDUCTOR: Optional[InductorPart] = None
    MOSFET: Optional[MosfetPart] = None
    F_SW_HZ: float = 100_000.0
    C_OUT_NOMINAL: float = (4.7e-3 * 4) + (10e-6 * 9)
    C_OUT_DERATING: float = 0.70
    C_OUT_DF_BASE: float = 0.16
    C_OUT_DF_MOD: float = 0.02
    C_IN_NOMINAL: float = (47e-6 * 4) + (10e-6 * 2)
    C_IN_DERATING: float = 0.80

def make_design(
    load_parts: bool = False,
    ind_csv: str = "data/inductors.csv",
    fet_csv: str = "data/mosfets.csv",
) -> DesignChoices:
    """Return a DesignChoices.

    load_parts=False (default): config only; INDUCTOR/MOSFET are None.
    load_parts=True: also load the CSV-backed parts (needs component_utils + data).
    """
    if not load_parts:
        return DesignChoices()
    inductor, mosfet = build_design_parts(ind_csv, fet_csv)
    return DesignChoices(INDUCTOR=inductor, MOSFET=mosfet)

# ==========================================
# 4. INSTANTIATION & DERIVED CONSTANTS
# ==========================================

USB = USBCSpecs()
FAN = FanSpecs()
# Config-only design (parts are None). Call make_design(load_parts=True) when
# you need the inductor/FET, e.g. for power-stage / thermal calculations.
DESIGN = make_design()

# Calculation for I_LOGIC_TOTAL (14x INA226 + ESP32)
I_LOGIC_TOTAL: Final = 0.120 + (14 * 330e-6)
MIN_SYSTEM_LOAD_WATTS: Final = (I_LOGIC_TOTAL * 5.0) / 0.85

MAX_FAN_LOAD_WATTS: Final = FAN.V_NOMINAL * FAN.I_MAX_PRO * FAN.MAX_COUNT
TOTAL_MAX_LOAD_WATTS: Final = MAX_FAN_LOAD_WATTS + MIN_SYSTEM_LOAD_WATTS

# Part-dependent: None until parts are loaded. For real power-stage math, build a
# design with make_design(load_parts=True) and read design.INDUCTOR.L off it.
SYSTEM_L_HENRY: Final = DESIGN.INDUCTOR.L if DESIGN.INDUCTOR is not None else None

# Pure (literal-derived) — always available.
C_OUT_EFFECTIVE: Final = DESIGN.C_OUT_NOMINAL * DESIGN.C_OUT_DERATING

# Standard ESR estimation formula
C_OUT_ESR_OHMS: Final = (
    (DESIGN.C_OUT_DF_BASE + DESIGN.C_OUT_DF_MOD) /
    (2 * np.pi * 120.0 * DESIGN.C_OUT_NOMINAL)
)

# ==========================================
# 5. MANUFACTURING CONSTRAINTS (DFM)
# ==========================================
@dataclass(frozen=True)
class JLCPCBConstraints:
    # Resistor library for auto-selection scripts
    BASIC_0603_RESISTORS: np.ndarray = field(default_factory=lambda: np.array([
        1e3, 1.2e3, 1.5e3, 1.8e3, 2e3, 2.2e3, 2.4e3, 2.7e3, 3e3, 3.6e3, 3.9e3,
        4.7e3, 4.99e3, 5.1e3, 5.6e3, 6.2e3, 6.8e3, 7.5e3, 8.2e3,
        10e3, 12e3, 15e3, 18e3, 20e3, 22e3, 24e3, 27e3, 30e3, 36e3, 39e3,
        47e3, 49.9e3, 51e3, 56e3, 68e3, 75e3, 82e3,
        100e3, 120e3, 150e3, 200e3, 220e3, 270e3, 300e3, 330e3, 470e3, 510e3,
        1e6, 2e6, 10e6
    ]))

    RES_PPM_MAPPING: Dict[float, int] = field(default_factory=lambda: {
        2.0: 200, 5.1: 200,
        1.0: 400, 2.2: 400, 4.7: 400, 10.0: 400,
        0.0: 0
    })

    BASE_TOLERANCE: float = 0.01
    EXTENDED_FEE_USD: float = 3.00

MFG = JLCPCBConstraints()
