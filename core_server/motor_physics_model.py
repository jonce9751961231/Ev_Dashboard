"""
===============================================================================
Project: EV Dashboard & Motor Predictive Thermal Management System
File: motor_physics_model.py
Description: High-Fidelity 4-Node Lumped Parameter Thermal Network (LPTN)
             Simulation for PMSM Traction Motors (150 kW automotive grade).
===============================================================================
"""

import math
from dataclasses import dataclass
from typing import Dict, Tuple, List


@dataclass
class MotorPhysicalSpecs:
    """Motor physical, electrical, and thermal parameters."""
    rated_power_kw: float = 150.0
    peak_torque_nm: float = 350.0
    max_speed_rpm: float = 12000.0
    pole_pairs: int = 4
    
    # Stator parameters
    R_stator_20C: float = 0.018         # Ohms (Phase resistance at 20°C)
    alpha_cu: float = 0.00393           # 1/°C (Copper thermal resistance coeff)
    C_stator_windings: float = 2800.0   # J/K (Heat capacity of windings)
    R_stator_to_core: float = 0.038     # K/W (Thermal resistance to iron teeth)

    # Stator iron core
    C_stator_core: float = 7200.0       # J/K (Heat capacity of silicon steel)
    R_core_to_frame: float = 0.024      # K/W (Thermal resistance to aluminum frame)
    k_hysteresis: float = 0.0022        # Hysteresis loss factor
    k_eddy: float = 0.000045            # Eddy current loss factor

    # Rotor & Permanent Magnets (NdFeB Grade N45SH)
    C_rotor_magnets: float = 3400.0     # J/K (Heat capacity of rotor stack)
    R_magnets_to_airgap: float = 0.110  # K/W (Resistance to airgap/shaft)
    R_airgap_to_frame: float = 0.075    # K/W (Resistance across airgap to frame)

    # Casing & Liquid Coolant Jacket (Water/Ethylene Glycol 50:50)
    C_frame_housing: float = 5600.0     # J/K (Heat capacity of aluminum housing)
    R_frame_to_coolant: float = 0.016   # K/W (Nominal base resistance to jacket)

    # Thermal Limits
    stator_warning_temp_C: float = 135.0
    stator_critical_temp_C: float = 160.0 # Class H insulation thermal limit
    rotor_warning_temp_C: float = 110.0
    rotor_critical_temp_C: float = 130.0  # NdFeB irreversible demagnetization limit


class PMSMMotorThermalPlant:
    """
    Simulates the physical thermal dynamics of the PMSM motor in real-time.
    Implements coupled ordinary differential equations (ODE) for 4 thermal nodes.
    """

    def __init__(self, specs: MotorPhysicalSpecs = None, ambient_temp_C: float = 30.0):
        self.specs = specs or MotorPhysicalSpecs()
        
        # State temperatures (°C)
        self.T_stator_winding = ambient_temp_C
        self.T_stator_core = ambient_temp_C
        self.T_rotor_magnet = ambient_temp_C
        self.T_housing_frame = ambient_temp_C
        self.ambient_temp_C = ambient_temp_C
        
        # Historical buffer for rate calculation
        self.dT_stator_dt = 0.0
        self.dT_rotor_dt = 0.0

    def compute_losses(self, i_d: float, i_q: float, speed_rpm: float, v_dc: float) -> Dict[str, float]:
        """Calculates electrical, magnetic, and mechanical losses in Watts."""
        # 1. Temperature-dependent copper resistance
        r_actual = self.specs.R_stator_20C * (1.0 + self.specs.alpha_cu * (self.T_stator_winding - 20.0))
        
        # 2. Stator Joule (Copper) loss: P_cu = 1.5 * (Id^2 + Iq^2) * Rs
        i_sq = (i_d ** 2) + (i_q ** 2)
        P_copper = 1.5 * i_sq * r_actual

        # 3. Core (Iron) loss
        freq_hz = abs(speed_rpm * self.specs.pole_pairs / 60.0)
        p_iron = (self.specs.k_hysteresis * freq_hz + self.specs.k_eddy * (freq_hz ** 2))
        p_iron *= 1.0 if v_dc > 50.0 else 0.1

        # 4. Mechanical & Windage loss
        omega_mech = abs(speed_rpm * 2.0 * math.pi / 60.0)
        p_mech = min(450.0, 0.000008 * (omega_mech ** 2.8))

        # 5. Rotor eddy current loss in permanent magnets
        p_rotor_eddy = 0.06 * p_iron + 0.0006 * i_sq

        total_loss = P_copper + p_iron + p_mech + p_rotor_eddy

        return {
            "p_copper": P_copper,
            "p_iron": p_iron,
            "p_mech": p_mech,
            "p_rotor_eddy": p_rotor_eddy,
            "total_loss": total_loss,
            "r_stator_actual": r_actual
        }

    def step(self, i_d: float, i_q: float, speed_rpm: float, v_dc: float,
             coolant_inlet_temp_C: float = 35.0, coolant_flow_lpm: float = 6.0,
             dt: float = 0.1) -> Dict[str, float]:
        """
        Integrates the 4-node thermal ODE forward by dt seconds.
        """
        losses = self.compute_losses(i_d, i_q, speed_rpm, v_dc)

        # Coolant flow effectiveness factor
        flow_factor = max(0.3, min(2.2, 1.0 + 0.12 * (coolant_flow_lpm - 5.0)))
        r_coolant = self.specs.R_frame_to_coolant / flow_factor

        # Heat flux between adjacent thermal nodes (Watts)
        q_stator_core = (self.T_stator_winding - self.T_stator_core) / self.specs.R_stator_to_core
        q_core_frame  = (self.T_stator_core - self.T_housing_frame) / self.specs.R_core_to_frame
        q_rotor_frame = (self.T_rotor_magnet - self.T_housing_frame) / (
            self.specs.R_magnets_to_airgap + self.specs.R_airgap_to_frame
        )
        q_frame_cool  = (self.T_housing_frame - coolant_inlet_temp_C) / r_coolant

        # Derivatives: dT/dt = (Heat In - Heat Out) / Thermal Capacity
        dT_stator = (losses["p_copper"] - q_stator_core) / self.specs.C_stator_windings
        dT_core   = (losses["p_iron"] + q_stator_core - q_core_frame) / self.specs.C_stator_core
        dT_rotor  = (losses["p_rotor_eddy"] - q_rotor_frame) / self.specs.C_rotor_magnets
        dT_frame  = (q_core_frame + q_rotor_frame - q_frame_cool) / self.specs.C_frame_housing

        # Euler numerical integration
        self.T_stator_winding += dT_stator * dt
        self.T_stator_core    += dT_core * dt
        self.T_rotor_magnet   += dT_rotor * dt
        self.T_housing_frame  += dT_frame * dt

        self.dT_stator_dt = dT_stator
        self.dT_rotor_dt  = dT_rotor

        return {
            "T_stator_winding": self.T_stator_winding,
            "T_stator_core": self.T_stator_core,
            "T_rotor_magnet": self.T_rotor_magnet,
            "T_housing_frame": self.T_housing_frame,
            "dT_stator_dt": self.dT_stator_dt,
            "dT_rotor_dt": self.dT_rotor_dt,
            **losses
        }
