"""
===============================================================================
Project: 48V - 96V EV BLDC Predictive AI Engine - ESP CSV Ingestion
File: esp_csv_ai_predictor.py
Description: Ingests telemetry CSV files recorded by ESP32 / ESP8266, computes
             BLDC electro-thermal losses, and runs the Multi-Horizon AI Model
             to predict future stator winding and rotor magnet temperatures.
===============================================================================
"""

import os
import sys
import csv
import json
import math
from typing import Dict, List, Any, Optional
import numpy as np


class ESPCSVAIPredictor:
    """
    Ingests CSV logged by ESP32, applies physics-informed features,
    and calculates multi-horizon future temperature forecasts.
    """

    def __init__(self, weights_json_path: Optional[str] = None, ambient_fallback: float = 30.0):
        self.ambient_fallback = ambient_fallback
        
        # Default fallback weights path
        if not weights_json_path:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            weights_json_path = os.path.join(script_dir, "bldc_ai_model_weights.json")

        self.weights_loaded = False
        if os.path.exists(weights_json_path):
            with open(weights_json_path, "r", encoding="utf-8") as f:
                model_data = json.load(f)
                self.means = np.array(model_data["means"], dtype=np.float32)
                self.stds = np.array(model_data["stds"], dtype=np.float32)
                self.bias = np.array(model_data["bias"], dtype=np.float32)
                self.weights = np.array(model_data["weights"], dtype=np.float32)
                self.target_names = model_data.get("target_names", [
                    "pred_stator_plus_1m_c", "pred_stator_plus_5m_c",
                    "pred_stator_plus_15m_c", "pred_stator_plus_30m_c",
                    "pred_rotor_plus_5m_c"
                ])
                self.weights_loaded = True
        else:
            print(f"[WARNING] Weights file '{weights_json_path}' not found. Using physics analytical fallback.")

        # BLDC Motor Physical Constants (typical 48V-96V EV platform)
        self.R_phase_20c = 0.085       # Stator resistance (Ohms)
        self.alpha_cu = 0.00393        # Copper temp coefficient (1/K)
        self.pole_pairs = 4            # 8-pole BLDC motor
        self.tau_stator = 190.0        # Stator thermal time constant (seconds)
        self.tau_rotor = 520.0         # Rotor thermal time constant (seconds)
        self.R_th_stator = 2.15        # Thermal resistance to ambient (K/W)
        self.R_th_rotor = 3.40         # Rotor thermal resistance (K/W)

        # Thresholds
        self.STATOR_WARN_TEMP = 110.0   # Thermal warning (°C)
        self.STATOR_TRIP_TEMP = 135.0   # Class F insulation trip limit (°C)
        self.ROTOR_WARN_TEMP  = 90.0    # NdFeB permanent magnet demag warning (°C)

    def process_csv(self, csv_filepath: str) -> List[Dict[str, Any]]:
        """
        Parses the ESP CSV file and evaluates AI future predictions for each row.
        Expected CSV columns:
          timestamp_ms, voltage_v, current_a, speed_rpm, stator_temp_c, (ambient_temp_c, power_w)
        """
        if not os.path.exists(csv_filepath):
            raise FileNotFoundError(f"Cannot find CSV at: {csv_filepath}")

        records = []
        temp_history = []
        timestamps = []

        with open(csv_filepath, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Normalize field names to lowercase stripped
            field_map = {k.strip().lower(): k for k in reader.fieldnames or []}

            def get_val(row, keys, default=0.0):
                for k in keys:
                    if k in field_map:
                        v = row.get(field_map[k], "")
                        if v != "":
                            return float(v)
                return default

            for row_idx, row in enumerate(reader):
                try:
                    time_ms = int(get_val(row, ["timestamp_ms", "time", "timestamp"], default=row_idx * 500))
                    voltage_v = get_val(row, ["voltage_v", "voltage", "vdc", "v"], default=72.0)
                    current_a = get_val(row, ["current_a", "current", "idc", "i"], default=0.0)
                    rpm = get_val(row, ["speed_rpm", "rpm", "speed"], default=0.0)
                    stator_temp = get_val(row, ["stator_temp_c", "temp_c", "temp", "stator_temp"], default=32.0)
                    ambient_temp = get_val(row, ["ambient_temp_c", "amb_temp", "ambient"], default=self.ambient_fallback)
                    power_w = get_val(row, ["power_w", "power"], default=voltage_v * current_a)

                    temp_history.append(stator_temp)
                    timestamps.append(time_ms)
                    if len(temp_history) > 10:
                        temp_history.pop(0)
                        timestamps.pop(0)

                    # 1. Physics Calculations
                    # Copper Loss
                    i_phase_rms = current_a * 0.816
                    r_actual = self.R_phase_20c * (1.0 + self.alpha_cu * (stator_temp - 20.0))
                    p_copper = 3.0 * (i_phase_rms ** 2) * r_actual

                    # High-frequency Iron loss
                    fe_hz = (self.pole_pairs * rpm) / 60.0
                    p_iron = (0.015 * fe_hz) + (0.00018 * (fe_hz ** 2))

                    # Rotor eddy current loss
                    p_rotor_eddy = (0.055 * p_iron) + (0.0008 * (i_phase_rms ** 2))
                    total_loss_w = p_copper + p_iron + p_rotor_eddy

                    # Rate of temperature change (dT/dt) in °C/s
                    dT_dt = 0.0
                    if len(temp_history) >= 2:
                        dt_sec = max((timestamps[-1] - timestamps[0]) / 1000.0, 0.2)
                        dT_dt = (temp_history[-1] - temp_history[0]) / dt_sec

                    # 2. Asymptotic Thermal Equilibrium (T_infinity)
                    t_stator_inf = ambient_temp + ((p_copper + p_iron) * self.R_th_stator)
                    t_rotor_inf  = ambient_temp + ((p_rotor_eddy + 0.08 * p_copper) * self.R_th_rotor)

                    # 3. Model Inference or Analytical Fallback
                    if self.weights_loaded:
                        features = np.array([
                            voltage_v, current_a, rpm, power_w,
                            stator_temp, dT_dt, ambient_temp,
                            p_copper, p_iron
                        ], dtype=np.float32)
                        features_norm = (features - self.means) / self.stds
                        preds = features_norm @ self.weights + self.bias
                        pred_1m  = float(preds[0])
                        pred_5m  = float(preds[1])
                        pred_15m = float(preds[2])
                        pred_30m = float(preds[3])
                        pred_rotor_5m = float(preds[4])
                    else:
                        pred_1m  = t_stator_inf + (stator_temp - t_stator_inf) * math.exp(-60.0 / self.tau_stator) + (dT_dt * 2.5)
                        pred_5m  = t_stator_inf + (stator_temp - t_stator_inf) * math.exp(-300.0 / self.tau_stator) + (dT_dt * 6.0)
                        pred_15m = t_stator_inf + (stator_temp - t_stator_inf) * math.exp(-900.0 / self.tau_stator)
                        pred_30m = t_stator_inf + (stator_temp - t_stator_inf) * math.exp(-1800.0 / self.tau_stator)
                        pred_rotor_5m = t_rotor_inf + (stator_temp - 2.0 - t_rotor_inf) * math.exp(-300.0 / self.tau_rotor)

                    # 4. Proactive Derating & Safety Analysis
                    derate_required = False
                    derate_pct = 0.0
                    if pred_5m >= self.STATOR_WARN_TEMP:
                        derate_required = True
                        excess = pred_5m - self.STATOR_WARN_TEMP
                        derate_pct = min(100.0, (excess / (self.STATOR_TRIP_TEMP - self.STATOR_WARN_TEMP)) * 100.0)
                    elif pred_rotor_5m >= self.ROTOR_WARN_TEMP:
                        derate_required = True
                        derate_pct = min(100.0, ((pred_rotor_5m - self.ROTOR_WARN_TEMP) / 20.0) * 100.0)

                    # Time-to-Trip (insulation breakdown at 135°C)
                    time_to_trip = "SAFE (No Overheat)"
                    if t_stator_inf > self.STATOR_TRIP_TEMP and stator_temp < self.STATOR_TRIP_TEMP:
                        ratio = (self.STATOR_TRIP_TEMP - t_stator_inf) / (stator_temp - t_stator_inf)
                        if 0 < ratio < 1:
                            sec_to_trip = -self.tau_stator * math.log(ratio)
                            time_to_trip = f"{int(sec_to_trip / 60)} min {int(sec_to_trip % 60)} sec"

                    record = {
                        "row_index": row_idx,
                        "timestamp_ms": time_ms,
                        "inputs": {
                            "voltage_v": round(voltage_v, 2),
                            "current_a": round(current_a, 2),
                            "speed_rpm": round(rpm, 0),
                            "power_w": round(power_w, 1),
                            "stator_temp_c": round(stator_temp, 2),
                            "ambient_temp_c": round(ambient_temp, 1),
                            "dT_dt": round(dT_dt, 3)
                        },
                        "losses_w": {
                            "copper_loss": round(p_copper, 2),
                            "iron_loss": round(p_iron, 2),
                            "rotor_loss": round(p_rotor_eddy, 2),
                            "total_loss": round(total_loss_w, 2)
                        },
                        "ai_predictions": {
                            "pred_stator_plus_1m_c": round(pred_1m, 2),
                            "pred_stator_plus_5m_c": round(pred_5m, 2),
                            "pred_stator_plus_15m_c": round(pred_15m, 2),
                            "pred_stator_plus_30m_c": round(pred_30m, 2),
                            "pred_rotor_plus_5m_c": round(pred_rotor_5m, 2),
                            "asymptotic_equilibrium_c": round(t_stator_inf, 2),
                            "time_to_trip": time_to_trip
                        },
                        "thermal_status": {
                            "derate_active": derate_required,
                            "recommended_derate_pct": round(derate_pct, 1),
                            "alert_level": "CRITICAL_TRIP" if stator_temp >= self.STATOR_TRIP_TEMP else (
                                "OVERHEAT_DERATE" if derate_required else "OPTIMAL"
                            )
                        }
                    }
                    records.append(record)

                except Exception as e:
                    continue

        return records


def print_cli_summary(records: List[Dict[str, Any]], filepath: str):
    """Prints a clear terminal summary of the processed CSV and predictions."""
    if not records:
        print(f"[ERROR] No valid records parsed from {filepath}")
        return

    print("\n" + "=" * 78)
    print(f" 🚀 48V-96V BLDC AI TEMPERATURE FORECAST REPORT: {os.path.basename(filepath)}")
    print("=" * 78)
    print(f"Total Telemetry Rows Analyzed: {len(records)}")

    first_rec = records[0]
    last_rec = records[-1]
    
    print(f"Initial Stator Temp: {first_rec['inputs']['stator_temp_c']}°C  -->  Final Stator Temp: {last_rec['inputs']['stator_temp_c']}°C")
    print(f"Peak Current: {max(r['inputs']['current_a'] for r in records):.1f}A | Peak Power: {max(r['inputs']['power_w'] for r in records):.0f}W")
    print(f"Max Voltage Recorded: {max(r['inputs']['voltage_v'] for r in records):.1f}V | Min Voltage: {min(r['inputs']['voltage_v'] for r in records):.1f}V")

    print("\n" + "-" * 78)
    print(" 🔮 LATEST MULTI-HORIZON AI PREDICTION (End of Recorded Drive):")
    print("-" * 78)
    preds = last_rec["ai_predictions"]
    status = last_rec["thermal_status"]
    inputs = last_rec["inputs"]

    print(f"Current Measured Stator Temp:  {inputs['stator_temp_c']:.2f} °C (Ambient: {inputs['ambient_temp_c']:.1f}°C)")
    print(f"  ├─ Future Temp at +1 min:     {preds['pred_stator_plus_1m_c']:.2f} °C")
    print(f"  ├─ Future Temp at +5 min:     {preds['pred_stator_plus_5m_c']:.2f} °C  <-- [Critical Derating Horizon]")
    print(f"  ├─ Rotor Demag Temp at +5m:   {preds['pred_rotor_plus_5m_c']:.2f} °C")
    print(f"  ├─ Future Temp at +15 min:    {preds['pred_stator_plus_15m_c']:.2f} °C")
    print(f"  ├─ Future Temp at +30 min:    {preds['pred_stator_plus_30m_c']:.2f} °C")
    print(f"  └─ Asymptotic Equilibrium:    {preds['asymptotic_equilibrium_c']:.2f} °C")

    print("\n🛡️  SAFETY & DERATING ASSESSMENT:")
    print(f"  • Alert Level:            [{status['alert_level']}]")
    print(f"  • Proactive Derate Flag:  {'YES - Throttle Limiting Active' if status['derate_active'] else 'NO - System Safe'}")
    if status['derate_active']:
        print(f"  • Recommended Torque Cut: {status['recommended_derate_pct']:.1f}%")
    print(f"  • Estimated Time-to-Trip: {preds['time_to_trip']}")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_csv = sys.argv[1]
    else:
        # Default sample
        script_dir = os.path.dirname(os.path.abspath(__file__))
        target_csv = os.path.join(script_dir, "..", "datasets", "sample_bldc_telemetry.csv")

    predictor = ESPCSVAIPredictor()
    results = predictor.process_csv(target_csv)
    print_cli_summary(results, target_csv)

    # Export results JSON
    out_json = "core_server/latest_esp_ai_predictions.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"[EXPORT] Full predictions saved to '{out_json}'")
