"""
===============================================================================
Project: EV Dashboard & Predictive Thermal & Energy Management System
File: battery_thermal_predictor.py
Description: Physical + ML Multi-Horizon Future Battery Temperature Predictor
             (Joule Heating + Entropic Heat + State of Charge (SoC) Dynamics).
===============================================================================
"""

import math
from typing import Dict, Any, List


class BatteryPhysicalSpecs:
    """Lithium-Ion Battery Pack specifications (e.g., 48V 50Ah prototype or 400V 60kWh pack)."""
    nominal_voltage_v: float = 48.0
    capacity_ah: float = 50.0
    total_energy_kwh: float = 2.4        # 48V * 50Ah = 2.4 kWh
    r_internal_25c_ohm: float = 0.045    # Pack internal resistance at 25°C
    c_thermal_pack_j_k: float = 8500.0   # Heat capacity of cell pack (J/K)
    r_thermal_to_amb_k_w: float = 0.85   # Thermal resistance to cooling air/jacket (K/W)
    
    # Entropic coefficient dU/dT (V/K) for NMC/LFP chemistry
    entropic_coeff_v_k: float = -0.00022
    
    # Safety Limits
    temp_optimal_min_c: float = 15.0
    temp_optimal_max_c: float = 38.0
    temp_warning_c: float = 45.0
    temp_critical_runaway_c: float = 60.0


class BatteryThermalPredictor:
    """
    Simulates instantaneous battery cell thermodynamics and forecasts future
    temperature over +1 min, +5 min, +15 min, and +30 min horizons.
    """

    def __init__(self, specs: BatteryPhysicalSpecs = None, initial_soc: float = 0.85, initial_temp_c: float = 28.0):
        self.specs = specs or BatteryPhysicalSpecs()
        self.current_soc = initial_soc      # 0.0 to 1.0 (85% SoC)
        self.current_temp_c = initial_temp_c
        self.ambient_temp_c = 28.0
        self.history_temps: List[float] = [initial_temp_c]
        self.horizons = [60, 300, 900, 1800] # 1m, 5m, 15m, 30m

    def step(self, current_draw_a: float, dt: float = 0.1) -> Dict[str, Any]:
        """
        Integrates battery SoC and thermal state forward by dt seconds.
        current_draw_a > 0: Discharging (Driving)
        current_draw_a < 0: Charging (Regenerative braking)
        """
        # 1. Update State of Charge (Coulomb Counting)
        delta_ah = (current_draw_a * (dt / 3600.0))
        self.current_soc = max(0.02, min(1.0, self.current_soc - (delta_ah / self.specs.capacity_ah)))

        # 2. Temperature & SoC dependent internal resistance
        # R_i increases at low temps (<10°C) and extreme low SoC (<20%)
        temp_factor = math.exp(-0.025 * (self.current_temp_c - 25.0))
        soc_factor = 1.0 + (0.35 if self.current_soc < 0.20 else 0.0)
        r_internal_actual = self.specs.r_internal_25c_ohm * temp_factor * soc_factor

        # 3. Heat Generation Breakdown
        # A. Joule / Ohmic Heating (I^2 * R)
        p_joule = (current_draw_a ** 2) * r_internal_actual

        # B. Reversible Entropic Heat: Q_rev = I * T * (dU/dT)
        temp_kelvin = self.current_temp_c + 273.15
        p_entropic = current_draw_a * temp_kelvin * self.specs.entropic_coeff_v_k

        p_total_heat_gen = p_joule + p_entropic

        # 4. Heat Dissipation to Ambient / Cooling
        q_dissipated = (self.current_temp_c - self.ambient_temp_c) / self.specs.r_thermal_to_amb_k_w

        # 5. Differential Temperature Rate
        dT_dt = (p_total_heat_gen - q_dissipated) / self.specs.c_thermal_pack_j_k
        self.current_temp_c += dT_dt * dt

        self.history_temps.append(self.current_temp_c)
        if len(self.history_temps) > 50:
            self.history_temps.pop(0)

        # 6. Multi-Horizon Forward Predictions
        tau_pack = self.specs.c_thermal_pack_j_k * self.specs.r_thermal_to_amb_k_w # ~7200 seconds
        t_asymptotic = self.ambient_temp_c + (p_total_heat_gen * self.specs.r_thermal_to_amb_k_w)

        horizon_forecasts = {}
        labels = ["1m", "5m", "15m", "30m"]
        for sec, lbl in zip(self.horizons, labels):
            pred_temp = t_asymptotic + (self.current_temp_c - t_asymptotic) * math.exp(-sec / tau_pack)
            horizon_forecasts[lbl] = {
                "horizon_sec": sec,
                "predicted_temp_c": round(pred_temp, 2),
                "status": self._get_battery_status(pred_temp)
            }

        # 7. Proactive BMS Derating Limits
        max_discharge_current = 40.0 # Nominal 40A
        pred_5m = horizon_forecasts["5m"]["predicted_temp_c"]
        bms_derate_active = False

        if pred_5m > self.specs.temp_warning_c:
            derate_factor = (self.specs.temp_critical_runaway_c - pred_5m) / (self.specs.temp_critical_runaway_c - self.specs.temp_warning_c)
            max_discharge_current = max(5.0, 40.0 * max(0.1, min(1.0, derate_factor)))
            bms_derate_active = True

        return {
            "current_temp_c": round(self.current_temp_c, 2),
            "soc_percentage": round(self.current_soc * 100.0, 1),
            "remaining_capacity_ah": round(self.current_soc * self.specs.capacity_ah, 2),
            "internal_resistance_ohm": round(r_internal_actual, 4),
            "heat_generation_w": {
                "joule_heating": round(p_joule, 2),
                "entropic_heating": round(p_entropic, 2),
                "total_heat_w": round(p_total_heat_gen, 2)
            },
            "asymptotic_temp_c": round(t_asymptotic, 2),
            "horizons": horizon_forecasts,
            "bms_limits": {
                "max_discharge_current_a": round(max_discharge_current, 1),
                "bms_derate_active": bms_derate_active,
                "thermal_runaway_margin_c": round(self.specs.temp_critical_runaway_c - self.current_temp_c, 1)
            }
        }

    def _get_battery_status(self, temp: float) -> str:
        if temp >= self.specs.temp_critical_runaway_c:
            return "CRITICAL_RUNAWAY_RISK"
        elif temp >= self.specs.temp_warning_c:
            return "HIGH_TEMPERATURE_DERATE"
        elif temp < self.specs.temp_optimal_min_c:
            return "COLD_CELL_REDUCED_POWER"
        return "OPTIMAL_NORMAL"
