"""
constants.py
Project: USB-C PD to 12V Fan Array Controller
Version: 1.1.0

This file serves as the Single Source of Truth for the project. 
It contains physical constants (datasheet values) and design decisions 
(calculated values from previous optimization passes).
"""

from dataclasses import dataclass
from typing import Final

@dataclass(frozen=True)
class USBCSpecs:
    """Standard USB-C Power Delivery limits and tolerances."""
    V_MIN: float = 5.0
    V_MAX: float = 20.0
    V_TOLERANCE: float = 0.10          # 10% standard ripple/tolerance
    I_MAX_HIGH_POWER: float = 5.0      # Requires E-marked cable
    I_MAX_STANDARD: float = 3.0        # Standard PD limit

@dataclass(frozen=True)
class FanSpecs:
    """Physical specifications for Arctic P14 series fans."""
    V_NOMINAL: float = 12.0
    I_MAX_PRO: float = 0.35            # Max current draw (P14 Pro)
    I_MAX_PWM: float = 0.12            # Max current draw (P14 PWM PST)
    MAX_COUNT: int = 10                # Target array size

@dataclass(frozen=True)
class DesignChoices:
    """
    Optimized values derived from simulation notebooks.
    
    Inductance: Selected in '01_Buck_Boost_Initial_Calculations.ipynb' 
    Targeting lowest combined DCR and Core loss at 100kHz.
    
    Capacitance: Selected in '03_Buck_Boost_Cout_Cin.ipynb'
    """
    # Power Stage Decisions
    F_SW_HZ: float = 100_000.0         # 100 kHz
    L_HENRY: float = 47e-6             # 47 uH (Optimized for ripple/size)
    
    # Output Filter (4x 4700uF Electrolytic Bank + 9x 10uF Ceramic)
    C_OUT_NOMINAL: float = 4.7e-3 * 4 + 10e-6 * 9  # 4x 4700uF + 9x 10uF ceramic
    C_OUT_DERATING_FACTOR: float = 0.70    # 70% retention based on 12V DC Bias
    
    # Input Filter (2x 47uF Electrolytic + 2x 10uF Ceramic)
    C_IN_NOMINAL: float = 47e-6 * 4 + 10e-6 * 2
    C_IN_DERATING_FACTOR: float = 0.80     # 80% retention based on 20V DC Bias

    # ESR Parameters (Derived from Dissipation Factor @ 120Hz)
    C_OUT_CAP_DF_BASE: float = 0.16          
    C_OUT_CAP_DF_MODIFIER: float = 0.02      # Aging/Temp modifier
    C_OUT_F_DF_REF_HZ: float = 120.0

    # MOSFET Selection (BSC0902NS)
    
@dataclass(frozen=True)
class ControlSystemSpecs:
    """Power requirements for the ESP32 and Sensor Suite."""
    V_LOGIC: float = 5.0
    
    # ESP32-WROOM typically pulls 80-150mA depending on WiFi state
    I_ESP32_AVG_AMPS: float = 0.120 
    
    # INA226 Quiescent current is ~330uA per chip
    I_INA226_TOTAL_AMPS: float = 14 * 330e-6
    
    # Efficiency of the 12V -> 5V Buck converter
    LOGIC_BUCK_EFFICIENCY: float = 0.85 

# --- Derived Minimum Load ---
# Power required just to keep the controller alive (Fans OFF)
MIN_SYSTEM_LOAD_WATTS: Final[float] = (
    ((ControlSystemSpecs.I_ESP32_AVG_AMPS + ControlSystemSpecs.I_INA226_TOTAL_AMPS) 
     * ControlSystemSpecs.V_LOGIC) 
    / ControlSystemSpecs.LOGIC_BUCK_EFFICIENCY
)

# --- Instantiate Namespaces for Global Access ---

USB = USBCSpecs()
FAN = FanSpecs()
DESIGN = DesignChoices()

# --- Derived System Constants (Read-Only) ---

# Total capacity required for the fan array
MAX_LOAD_WATTS: Final[float] = FAN.V_NOMINAL * FAN.I_MAX_PRO * FAN.MAX_COUNT

# Effective capacitance after hardware derating
C_OUT_EFFECTIVE: Final[float] = DESIGN.C_OUT_NOMINAL * DESIGN.C_OUT_DERATING_FACTOR

# Calculated ESR based on Design Choices
# Formula: ESR = DF / (2 * pi * f * C)
import numpy as np
C_OUT_TOTAL_ESR_OHMS: Final[float] = (
    (DESIGN.C_OUT_CAP_DF_BASE + DESIGN.C_OUT_CAP_DF_MODIFIER) / 
    (2 * np.pi * DESIGN.C_OUT_F_DF_REF_HZ * DESIGN.C_OUT_NOMINAL)
)