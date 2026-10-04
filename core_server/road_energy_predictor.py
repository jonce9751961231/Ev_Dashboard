"""
===============================================================================
Project: EV Dashboard & Predictive Thermal & Energy Management System
File: road_energy_predictor.py
Description: Vehicle Longitudinal Dynamics & Multi-Road Energy & Range
             Forecasting Engine (City, Highway, Mountain Grade, Off-Road).
===============================================================================
"""

import math
from dataclasses import dataclass
from typing import Dict, Any, List


@dataclass
class VehiclePhysicalSpecs:
    """EV Prototype / Vehicle Dynamics Parameters."""
    vehicle_mass_kg: float = 350.0       # Prototype EV mass (or 1600kg for full EV)
    drag_coefficient_cd: float = 0.29    # Aerodynamic drag coefficient
    frontal_area_m2: float = 1.45        # Frontal cross-sectional area
    air_density_kg_m3: float = 1.225     # Sea-level air density
    gravity_m_s2: float = 9.81
    drivetrain_efficiency: float = 0.90  # Motor + Inverter + Gearbox efficiency
    regen_efficiency: float = 0.75       # Regenerative braking recovery efficiency


class RoadProfile:
    """Road type physical parameters and speed profile."""
    ROAD_TYPES = {
        "URBAN_CITY": {
            "name": "Urban City (Stop & Go)",
            "rolling_friction_crr": 0.012,
            "avg_speed_kmh": 35.0,
            "avg_grade_pct": 1.0,
            "regen_opportunity_factor": 0.85,
            "description": "Frequent regenerative braking, low aerodynamic resistance."
        },
        "HIGHWAY_EXPRESS": {
            "name": "Highway Expressway (110 km/h)",
            "rolling_friction_crr": 0.010,
            "avg_speed_kmh": 105.0,
            "avg_grade_pct": 0.5,
            "regen_opportunity_factor": 0.15,
            "description": "High aerodynamic drag, steady speed, minimal regen opportunity."
        },
        "MOUNTAIN_GRADE": {
            "name": "12% Mountain Uphill Grade",
            "rolling_friction_crr": 0.014,
            "avg_speed_kmh": 55.0,
            "avg_grade_pct": 10.5,
            "regen_opportunity_factor": 0.90, # High regen on downhill phase
            "description": "Heavy gravitational potential energy demand during climb."
        },
        "OFFROAD_GRAVEL": {
            "name": "Rough Gravel / Off-Road",
            "rolling_friction_crr": 0.032,
            "avg_speed_kmh": 40.0,
            "avg_grade_pct": 4.0,
            "regen_opportunity_factor": 0.40,
            "description": "High rolling resistance, rough traction loss, elevated energy rate."
        }
    }


class RoadEnergyPredictor:
    """
    Computes tractive power, energy consumption per km, and forecasts remaining range
    across different road topographies from live telemetry.
    """

    def __init__(self, specs: VehiclePhysicalSpecs = None):
        self.specs = specs or VehiclePhysicalSpecs()
        self.current_road_type = "MOUNTAIN_GRADE"
        self.distance_traveled_km = 0.0
        self.total_energy_used_kwh = 0.0
        self.total_energy_recovered_kwh = 0.0

    def calculate_tractive_force(self, speed_kmh: float, grade_pct: float, acceleration_m_s2: float, road_type_key: str) -> Dict[str, float]:
        """
        Longitudinal Dynamics:
        F_tractive = F_roll + F_aero + F_grade + F_accel
        """
        road_params = RoadProfile.ROAD_TYPES.get(road_type_key, RoadProfile.ROAD_TYPES["URBAN_CITY"])
        v_ms = max(0.0, speed_kmh / 3.6)
        theta_rad = math.atan(grade_pct / 100.0)

        # 1. Rolling Resistance Force
        f_roll = road_params["rolling_friction_crr"] * self.specs.vehicle_mass_kg * self.specs.gravity_m_s2 * math.cos(theta_rad)

        # 2. Aerodynamic Drag Force
        f_aero = 0.5 * self.specs.air_density_kg_m3 * self.specs.drag_coefficient_cd * self.specs.frontal_area_m2 * (v_ms ** 2)

        # 3. Gravitational Gradient Force
        f_grade = self.specs.vehicle_mass_kg * self.specs.gravity_m_s2 * math.sin(theta_rad)

        # 4. Inertial Acceleration Force
        f_accel = self.specs.vehicle_mass_kg * acceleration_m_s2

        f_total_tractive = f_roll + f_aero + f_grade + f_accel

        # Electrical Power required at battery terminal (Watts)
        if f_total_tractive >= 0:
            p_electrical_w = (f_total_tractive * v_ms) / self.specs.drivetrain_efficiency
            p_regen_w = 0.0
        else:
            p_electrical_w = 0.0
            p_regen_w = abs(f_total_tractive * v_ms) * self.specs.regen_efficiency

        return {
            "f_roll_n": round(f_roll, 1),
            "f_aero_n": round(f_aero, 1),
            "f_grade_n": round(f_grade, 1),
            "f_accel_n": round(f_accel, 1),
            "f_total_n": round(f_total_tractive, 1),
            "p_electrical_w": round(p_electrical_w, 1),
            "p_regen_w": round(p_regen_w, 1)
        }

    def predict_energy_and_range(self, current_speed_kmh: float, battery_soc: float, total_battery_kwh: float = 2.4) -> Dict[str, Any]:
        """
        Forecasts energy consumption rate (Wh/km) and remaining driving range (km)
        for the current road as well as all alternative road profiles.
        """
        remaining_battery_energy_kwh = max(0.0, battery_soc * total_battery_kwh)
        road_comparisons = {}

        for road_key, road_info in RoadProfile.ROAD_TYPES.items():
            sim_speed = road_info["avg_speed_kmh"]
            sim_grade = road_info["avg_grade_pct"]
            
            # Compute steady-state cruising dynamics
            forces = self.calculate_tractive_force(sim_speed, sim_grade, 0.0, road_key)
            net_power_kw = (forces["p_electrical_w"] - forces["p_regen_w"] * road_info["regen_opportunity_factor"]) / 1000.0
            net_power_kw = max(0.15, net_power_kw)

            # Energy consumption rate in Wh/km: Wh/km = (kW / km/h) * 1000
            wh_per_km = (net_power_kw / sim_speed) * 1000.0
            kwh_per_100km = wh_per_km / 10.0

            # Projected Remaining Range (km)
            projected_range_km = (remaining_battery_energy_kwh * 1000.0) / wh_per_km if wh_per_km > 0 else 0.0

            road_comparisons[road_key] = {
                "name": road_info["name"],
                "avg_speed_kmh": sim_speed,
                "grade_pct": sim_grade,
                "energy_rate_wh_per_km": round(wh_per_km, 1),
                "energy_rate_kwh_per_100km": round(kwh_per_100km, 2),
                "projected_range_km": round(projected_range_km, 1),
                "is_current": (road_key == self.current_road_type)
            }

        curr_road_stats = road_comparisons[self.current_road_type]

        return {
            "current_road": self.current_road_type,
            "road_name": curr_road_stats["name"],
            "instant_wh_per_km": curr_road_stats["energy_rate_wh_per_km"],
            "instant_kwh_per_100km": curr_road_stats["energy_rate_kwh_per_100km"],
            "remaining_range_km": curr_road_stats["projected_range_km"],
            "remaining_battery_kwh": round(remaining_battery_energy_kwh, 2),
            "multi_road_forecasts": road_comparisons
        }
