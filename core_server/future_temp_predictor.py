"""
===============================================================================
Project: EV Dashboard & Motor Predictive Thermal Management System
File: future_temp_predictor.py
Description: Multi-Horizon Future Motor Temperature Prediction Engine
             (Physics-Informed + Machine Learning Hybrid Forecasting).
===============================================================================
"""

import math
import numpy as np
from typing import Dict, List, Any
from .motor_physics_model import MotorPhysicalSpecs


class MotorFutureTemperaturePredictor:
    """
    Advanced Multi-Horizon Motor Thermal Predictor.
    
    Combines:
    1. Physics-Informed Equivalent Circuit Asymptotic Extrapolation
    2. Drive Cycle Trend & Dynamic Throttle Autoregressive Momentum
    3. Multi-Horizon Future Forecasts (+1 min, +5 min, +15 min, +30 min)
    4. Proactive Thermal Derating & Safe Operation Time (Time-to-Overheat)
    """

    def __init__(self, specs: MotorPhysicalSpecs = None):
        self.specs = specs or MotorPhysicalSpecs()
        
        # History buffer for trend identification
        self.history_window_size = 50
        self.history_stator_temps: List[float] = []
        self.history_rotor_temps: List[float] = []
        self.history_currents: List[float] = []
        self.history_rpms: List[float] = []
        
        # Horizons in seconds: 1 min, 5 min, 15 min, 30 min
        self.horizons = [60, 300, 900, 1800]

    def update_history(self, stator_temp: float, rotor_temp: float, i_rms: float, rpm: float):
        """Maintains rolling buffer of recent telemetry."""
        self.history_stator_temps.append(stator_temp)
        self.history_rotor_temps.append(rotor_temp)
        self.history_currents.append(i_rms)
        self.history_rpms.append(rpm)

        if len(self.history_stator_temps) > self.history_window_size:
            self.history_stator_temps.pop(0)
            self.history_rotor_temps.pop(0)
            self.history_currents.pop(0)
            self.history_rpms.pop(0)

    def predict(self, 
                current_stator_temp: float,
                current_rotor_temp: float,
                current_housing_temp: float,
                i_d: float,
                i_q: float,
                speed_rpm: float,
                coolant_inlet_temp: float = 35.0,
                coolant_flow_lpm: float = 6.0,
                projected_load_factor: float = 1.0) -> Dict[str, Any]:
        """
        Computes forward predictions across all time horizons.
        
        Args:
            current_stator_temp: Measured/estimated stator temp (°C)
            current_rotor_temp: Estimated magnet temp (°C)
            current_housing_temp: Casing temp (°C)
            i_d, i_q: Motor direct and quadrature currents (A)
            speed_rpm: Motor mechanical speed (RPM)
            coolant_inlet_temp: Radiator / chiller fluid temp (°C)
            coolant_flow_lpm: Flow rate (Liters per min)
            projected_load_factor: Multiplier for anticipated upcoming road load
            
        Returns:
            Dictionary containing predictions, confidence bounds, time-to-limit,
            and derating recommendation.
        """
        # Calculate current RMS current
        i_rms = math.sqrt((i_d ** 2 + i_q ** 2) / 2.0)
        self.update_history(current_stator_temp, current_rotor_temp, i_rms, speed_rpm)

        # 1. Copper & Iron loss projections under anticipated load
        r_stator_est = self.specs.R_stator_20C * (1.0 + self.specs.alpha_cu * (current_stator_temp - 20.0))
        effective_i_sq = ((i_d ** 2 + i_q ** 2) * (projected_load_factor ** 2))
        p_cu_proj = 1.5 * effective_i_sq * r_stator_est

        freq_hz = abs(speed_rpm * self.specs.pole_pairs / 60.0)
        p_fe_proj = (self.specs.k_hysteresis * freq_hz + self.specs.k_eddy * (freq_hz ** 2))
        p_rotor_eddy_proj = 0.06 * p_fe_proj + 0.0006 * effective_i_sq

        # 2. Thermal Resistance Network to Coolant
        flow_factor = max(0.3, min(2.2, 1.0 + 0.12 * (coolant_flow_lpm - 5.0)))
        r_coolant = self.specs.R_frame_to_coolant / flow_factor

        r_th_stator_total = self.specs.R_stator_to_core + self.specs.R_core_to_frame + r_coolant
        r_th_rotor_total = self.specs.R_magnets_to_airgap + self.specs.R_airgap_to_frame + r_coolant

        # 3. Asymptotic Steady-State Equilibrium Temperatures
        t_stator_inf = coolant_inlet_temp + (p_cu_proj * 0.92 + p_fe_proj * 0.8) * r_th_stator_total
        t_rotor_inf  = coolant_inlet_temp + (p_cu_proj * 0.18 + p_fe_proj * 0.4 + p_rotor_eddy_proj) * r_th_rotor_total

        # 4. Thermal time constants (tau = R * C)
        tau_stator = self.specs.C_stator_windings * self.specs.R_stator_to_core + 95.0   # ~200s
        tau_rotor  = self.specs.C_rotor_magnets * (self.specs.R_magnets_to_airgap + self.specs.R_airgap_to_frame) + 260.0 # ~650s

        # 5. Calculate rate of temperature rise trend from history
        dT_dt_trend = 0.0
        if len(self.history_stator_temps) >= 5:
            dT_dt_trend = (self.history_stator_temps[-1] - self.history_stator_temps[0]) / (len(self.history_stator_temps) * 0.1)

        # 6. Multi-Horizon Predictions
        horizon_predictions = {}
        time_labels = ["1m", "5m", "15m", "30m"]

        for horizon_sec, label in zip(self.horizons, time_labels):
            # Physical exponential asymptotic decay
            exp_stator = math.exp(-horizon_sec / tau_stator)
            exp_rotor  = math.exp(-horizon_sec / tau_rotor)

            pred_stator_phys = t_stator_inf + (current_stator_temp - t_stator_inf) * exp_stator
            pred_rotor_phys  = t_rotor_inf + (current_rotor_temp - t_rotor_inf) * exp_rotor

            # ML / Trend residual correction
            trend_correction = dT_dt_trend * min(horizon_sec, 180.0) * 0.15
            
            final_pred_stator = round(pred_stator_phys + trend_correction, 1)
            final_pred_rotor  = round(pred_rotor_phys + trend_correction * 0.6, 1)

            # Confidence uncertainty bands (+/- °C)
            uncertainty = round(1.2 + 0.003 * horizon_sec, 1)

            horizon_predictions[label] = {
                "horizon_seconds": horizon_sec,
                "predicted_stator_temp_C": final_pred_stator,
                "stator_confidence_lower": round(final_pred_stator - uncertainty, 1),
                "stator_confidence_upper": round(final_pred_stator + uncertainty, 1),
                "predicted_rotor_temp_C": final_pred_rotor,
                "rotor_confidence_lower": round(final_pred_rotor - uncertainty * 0.8, 1),
                "rotor_confidence_upper": round(final_pred_rotor + uncertainty * 0.8, 1),
                "stator_status": self._get_status(final_pred_stator, self.specs.stator_warning_temp_C, self.specs.stator_critical_temp_C),
                "rotor_status": self._get_status(final_pred_rotor, self.specs.rotor_warning_temp_C, self.specs.rotor_critical_temp_C)
            }

        # 7. Time to Critical Thermal Limit (Seconds to reach trip temp)
        time_to_stator_trip = self._calculate_time_to_limit(current_stator_temp, t_stator_inf, tau_stator, self.specs.stator_critical_temp_C)
        time_to_rotor_trip  = self._calculate_time_to_limit(current_rotor_temp, t_rotor_inf, tau_rotor, self.specs.rotor_critical_temp_C)

        # 8. Dynamic Proactive Derating Calculation
        pred_5m_stator = horizon_predictions["5m"]["predicted_stator_temp_C"]
        pred_5m_rotor  = horizon_predictions["5m"]["predicted_rotor_temp_C"]
        
        max_torque_allowed = self.specs.peak_torque_nm
        derate_active = False
        derate_reason = "Nominal"

        if pred_5m_stator > self.specs.stator_warning_temp_C:
            factor = (self.specs.stator_critical_temp_C - pred_5m_stator) / (self.specs.stator_critical_temp_C - self.specs.stator_warning_temp_C)
            max_torque_allowed = min(max_torque_allowed, self.specs.peak_torque_nm * max(0.2, min(1.0, factor)))
            derate_active = True
            derate_reason = "Stator 5-Min Predicted Overheat"

        if pred_5m_rotor > self.specs.rotor_warning_temp_C:
            factor_rotor = (self.specs.rotor_critical_temp_C - pred_5m_rotor) / (self.specs.rotor_critical_temp_C - self.specs.rotor_warning_temp_C)
            torque_rotor_limit = self.specs.peak_torque_nm * max(0.15, min(1.0, factor_rotor))
            if torque_rotor_limit < max_torque_allowed:
                max_torque_allowed = torque_rotor_limit
                derate_active = True
                derate_reason = "Permanent Magnet Demagnetization Risk"

        # 9. Smart Coolant Pump Optimization Recommendation
        highest_future_temp = max(pred_5m_stator, pred_5m_rotor)
        if highest_future_temp < 65.0:
            rec_pump_pwm = 20
        elif highest_future_temp < 105.0:
            rec_pump_pwm = int(20 + (highest_future_temp - 65.0) * 1.8)
        else:
            rec_pump_pwm = 100

        return {
            "current_temps": {
                "stator_winding_C": round(current_stator_temp, 1),
                "rotor_magnet_C": round(current_rotor_temp, 1),
                "housing_frame_C": round(current_housing_temp, 1),
                "coolant_inlet_C": round(coolant_inlet_temp, 1)
            },
            "asymptotic_temps": {
                "stator_inf_C": round(t_stator_inf, 1),
                "rotor_inf_C": round(t_rotor_inf, 1)
            },
            "loss_distribution_W": {
                "copper_loss": round(p_cu_proj, 1),
                "iron_loss": round(p_fe_proj, 1),
                "rotor_eddy_loss": round(p_rotor_eddy_proj, 1),
                "total_loss": round(p_cu_proj + p_fe_proj + p_rotor_eddy_proj, 1)
            },
            "horizons": horizon_predictions,
            "safety_envelope": {
                "time_to_stator_limit_sec": time_to_stator_trip,
                "time_to_rotor_limit_sec": time_to_rotor_trip,
                "derate_active": derate_active,
                "derate_reason": derate_reason,
                "max_allowable_torque_nm": round(max_torque_allowed, 1),
                "derate_percentage": round((1.0 - (max_torque_allowed / self.specs.peak_torque_nm)) * 100.0, 1),
                "recommended_cooling_pump_pwm": rec_pump_pwm
            }
        }

    def _get_status(self, temp: float, warn: float, crit: float) -> str:
        if temp >= crit:
            return "CRITICAL_OVERHEAT"
        elif temp >= warn:
            return "WARNING_ELEVATED"
        return "OPTIMAL_NORMAL"

    def _calculate_time_to_limit(self, t_curr: float, t_inf: float, tau: float, t_limit: float) -> Any:
        if t_inf <= t_limit:
            return "SAFE_NO_LIMIT"  # Will never reach limit in continuous operation
        if t_curr >= t_limit:
            return 0  # Already breached

        # t_limit = t_inf + (t_curr - t_inf) * exp(-t / tau)
        # exp(-t / tau) = (t_limit - t_inf) / (t_curr - t_inf)
        ratio = (t_limit - t_inf) / (t_curr - t_inf)
        if ratio <= 0:
            return 0
        t_sec = -tau * math.log(ratio)
        return max(0, int(t_sec))
