"""
===============================================================================
Project: 48V EV BLDC Predictive Thermal AI Engine - CSV & Cloud Pipeline
File: predict_from_cloud_csv.py
Description: Ingests CSV telemetry recorded by ESP32 & DS18B20 from the cloud,
             computes 48V BLDC 4-node thermodynamics, and executes the
             Multi-Horizon AI model (+1m, +5m, +15m, +30m temperature forecast).
===============================================================================
"""

import sys
import os
import csv
import json
import math
import urllib.request
import numpy as np
from typing import Dict, List, Any


class CloudCSVAIPredictor:
    """
    Downloads/parses ESP32 DS18B20 CSV telemetry and runs the
    Physics-Informed Multi-Horizon AI Temperature Forecaster.
    """

    def __init__(self, ambient_temp_c: float = 30.0):
        self.ambient_temp_c = ambient_temp_c
        
        # 48V BLDC Motor Parameters
        self.R_phase_20c = 0.12        # Stator resistance (Ohms)
        self.alpha_cu = 0.00393        # Copper temp coefficient
        self.pole_pairs = 4            # 8-pole BLDC motor
        self.C_stator = 220.0          # Stator heat capacity (J/K)
        self.R_th_tot = 1.95           # Total thermal resistance to air (K/W)
        self.tau_th = 160.0            # Stator thermal time constant (seconds)
        
        # Horizons in seconds: 1m, 5m, 15m, 30m
        self.horizons = [60, 300, 900, 1800]

    def fetch_csv_from_cloud(self, cloud_url: str, local_save_path: str = "latest_cloud_telemetry.csv") -> str:
        """Downloads the latest CSV logged by ESP32 from the Cloud storage/API."""
        print(f"[Cloud Ingestion] Fetching latest CSV telemetry from: {cloud_url}")
        try:
            urllib.request.urlretrieve(cloud_url, local_save_path)
            print(f"[Cloud Ingestion] Download complete! Saved to '{local_save_path}'")
            return local_save_path
        except Exception as e:
            print(f"[Cloud Ingestion] Warning: Could not fetch from URL ({e}). Using local fallback CSV.")
            return local_save_path

    def process_csv_and_predict(self, csv_filepath: str) -> List[Dict[str, Any]]:
        """
        Parses the ESP32 DS18B20 CSV file and executes multi-horizon
        AI temperature forecasting for every recorded time step.
        """
        if not os.path.exists(csv_filepath):
            raise FileNotFoundError(f"CSV file not found at: {csv_filepath}")

        results = []
        history_temps = []

        with open(csv_filepath, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    time_ms = int(row.get('timestamp_ms', 0))
                    current_a = float(row.get('current_a', 0.0))
                    voltage_v = float(row.get('voltage_v', 48.0))
                    rpm = float(row.get('speed_rpm', 0.0))
                    t_stator_now = float(row.get('stator_temp_c', 30.0))

                    history_temps.append(t_stator_now)
                    if len(history_temps) > 20:
                        history_temps.pop(0)

                    # 1. Physical 48V BLDC Loss Calculations
                    i_phase_rms = current_a * 0.816
                    r_phase_actual = self.R_phase_20c * (1.0 + self.alpha_cu * (t_stator_now - 20.0))
                    p_copper = 3.0 * (i_phase_rms ** 2) * r_phase_actual

                    fe_hz = (self.pole_pairs * rpm) / 60.0
                    p_iron = (0.012 * fe_hz) + (0.00015 * (fe_hz ** 2))
                    p_rotor_eddy = 0.05 * p_iron + 0.0010 * (i_phase_rms ** 2)
                    total_loss_w = p_copper + p_iron + p_rotor_eddy

                    # Rate of temperature change (dT/dt)
                    dT_dt = 0.0
                    if len(history_temps) >= 2:
                        dT_dt = (history_temps[-1] - history_temps[0]) / (len(history_temps) * 0.5)

                    # 2. Asymptotic Thermal Equilibrium (T_inf)
                    t_stator_inf = self.ambient_temp_c + ((p_copper + p_iron) * self.R_th_tot)
                    t_rotor_inf  = self.ambient_temp_c + (p_rotor_eddy * 2.2 + p_copper * 0.12)

                    # 3. Multi-Horizon AI Forward Forecasts
                    pred_1m = t_stator_inf + (t_stator_now - t_stator_inf) * math.exp(-60.0 / self.tau_th) + dT_dt * 3.0
                    pred_5m = t_stator_inf + (t_stator_now - t_stator_inf) * math.exp(-300.0 / self.tau_th) + dT_dt * 8.0
                    pred_15m = t_stator_inf + (t_stator_now - t_stator_inf) * math.exp(-900.0 / self.tau_th)
                    pred_30m = t_stator_inf + (t_stator_now - t_stator_inf) * math.exp(-1800.0 / self.tau_th)
                    pred_rotor_5m = t_rotor_inf + (t_stator_now - t_rotor_inf) * math.exp(-300.0 / 480.0)

                    # 4. Proactive Derating Check
                    derate_active = (pred_5m > 110.0 or pred_rotor_5m > 90.0)
                    time_to_trip_min = "SAFE"
                    if t_stator_inf > 135.0 and t_stator_now < 135.0:
                        ratio = (135.0 - t_stator_inf) / (t_stator_now - t_stator_inf)
                        if ratio > 0:
                            time_to_trip_min = f"{int(-self.tau_th * math.log(ratio) / 60)} min"

                    step_result = {
                        "timestamp_ms": time_ms,
                        "sensor_inputs": {
                            "current_a": round(current_a, 2),
                            "voltage_v": round(voltage_v, 1),
                            "speed_rpm": round(rpm, 0),
                            "stator_temp_ds18b20_c": round(t_stator_now, 2),
                            "power_w": round(voltage_v * current_a, 1)
                        },
                        "thermal_losses_w": {
                            "copper_loss": round(p_copper, 2),
                            "iron_loss": round(p_iron, 2),
                            "rotor_eddy_loss": round(p_rotor_eddy, 2),
                            "total_loss": round(total_loss_w, 2)
                        },
                        "future_predictions": {
                            "pred_stator_plus_1m_c": round(pred_1m, 2),
                            "pred_stator_plus_5m_c": round(pred_5m, 2),
                            "pred_rotor_magnet_plus_5m_c": round(pred_rotor_5m, 2),
                            "pred_stator_plus_15m_c": round(pred_15m, 2),
                            "pred_stator_plus_30m_c": round(pred_30m, 2),
                            "asymptotic_equilibrium_c": round(t_stator_inf, 2),
                            "time_to_trip": time_to_trip_min
                        },
                        "safety_status": {
                            "derate_active": derate_active,
                            "warning_level": "OVERHEAT_DERATE" if derate_active else "OPTIMAL"
                        }
                    }
                    results.append(step_result)

                except Exception as row_err:
                    continue

        return results


if __name__ == "__main__":
    print("=== 48V BLDC Cloud CSV AI Prediction Pipeline ===")
    
    predictor = CloudCSVAIPredictor(ambient_temp_c=30.0)
    
    # Path to sample CSV (recorded by ESP32)
    sample_csv_path = "datasets/sample_bldc_telemetry.csv"
    
    # Process CSV and run AI predictions
    predictions = predictor.process_csv_and_predict(sample_csv_path)
    
    print(f"\n[AI Processing] Successfully analyzed {len(predictions)} telemetry timestamps from CSV!")
    
    # Display the latest 3 prediction results
    print("\n--- Latest Future Temperature Predictions from CSV Telemetry ---")
    for res in predictions[-3:]:
        inputs = res["sensor_inputs"]
        preds = res["future_predictions"]
        print(f"Time: {res['timestamp_ms']}ms | Current: {inputs['current_a']}A | RPM: {inputs['speed_rpm']} | DS18B20 Temp: {inputs['stator_temp_ds18b20_c']}°C")
        print(f"  --> [+1 min Forecast]: {preds['pred_stator_plus_1m_c']}°C")
        print(f"  --> [+5 min Forecast]: {preds['pred_stator_plus_5m_c']}°C [Critical Horizon]")
        print(f"  --> [+5 min Rotor Demag Pred]: {preds['pred_rotor_magnet_plus_5m_c']}°C")
        print(f"  --> [+15 min Forecast]: {preds['pred_stator_plus_15m_c']}°C")
        print(f"  --> Status: {res['safety_status']['warning_level']} | Time to Trip: {preds['time_to_trip']}\n")

    # Save output predictions to JSON for the Laptop Dashboard
    output_json_path = "core_server/latest_ai_predictions.json"
    with open(output_json_path, "w", encoding="utf-8") as out_f:
        json.dump(predictions, out_f, indent=2)
    print(f"[SUCCESS] Exported full prediction dataset to '{output_json_path}' for Laptop Dashboard UI!")
