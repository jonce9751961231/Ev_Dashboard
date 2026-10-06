"""
================================================================================
AURA EV DIGITAL COCKPIT - 12V DC MOTOR RANDOM FOREST TRAINING ENGINE
File: core_server/train_random_forest.py
================================================================================
Trains a 100-Tree Multi-Horizon Random Forest Regressor calibrated for the:
- 12V DC Motor Continuous Run Testbed
- 4 Hardware Sensors:
  1. 0-25V Voltage Sensor Module (ADCINA0 on C2000)
  2. ACS712 5A Current Sensor (ADCINA1 on C2000)
  3. LM393 Speed Measuring Sensor (GPIO 0 on C2000)
  4. DS18B20 1-Wire Temperature Sensor (GPIO 3 on C2000)
Outputs:
- Multi-Horizon Predictions: +1 Min, +5 Min, +15 Min, +30 Min Future Temp
- Model serialized to: core_server/random_forest_model.pkl
- Exported weights/metadata to: dashboard_ui/rf_model_weights.json
================================================================================
"""

import os
import sys
import json
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import joblib

# Ensure UTF-8 output encoding for Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def train_and_export():
    print("=" * 75)
    print("  AURA EV - 12V DC MOTOR CONTINUOUS RUN RANDOM FOREST TRAINING ENGINE  ")
    print("  Target: TMS320F2800137 -> ESP32-S Wi-Fi -> Laptop Host App Cockpit   ")
    print("=" * 75)

    # 1. Synthesize 12,000-sample continuous 12V DC Motor thermal run dataset
    print("[1/5] Generating 12,000-sample 12V DC Motor Continuous Run Dataset...")
    n_samples = 12000
    np.random.seed(42)
    time_seconds = np.arange(n_samples) * 10.0  # 10s step

    # 12V supply with small load drop and ripple
    base_voltage = 12.2 - (time_seconds / time_seconds.max()) * 0.8
    voltage_v = np.clip(base_voltage + np.random.normal(0, 0.08, n_samples), 11.0, 13.5)

    # Continuous running DC motor current (0.8A no-load to 4.2A loaded)
    cycle_phase = (time_seconds % 900) / 900.0
    current_a = np.where(
        cycle_phase < 0.40, np.random.uniform(1.2, 2.2, n_samples),
        np.where(cycle_phase < 0.80, np.random.uniform(2.5, 4.2, n_samples),
                 np.random.uniform(1.8, 3.2, n_samples))
    )
    current_a = np.clip(current_a + np.random.normal(0, 0.05, n_samples), 0.5, 4.8)

    # Speed from LM393 sensor: 12V DC motor runs at 1500 - 2800 RPM
    rpm = np.clip(2600.0 - (current_a * 250.0) + np.random.normal(0, 30, n_samples), 1000, 3000)

    # Ambient room temperature
    ambient_temp_c = 28.0 + 3.0 * np.sin(time_seconds / 18000.0)

    # 12V DC Motor thermal dynamics (DS18B20 on outer casing)
    # R_armature = 0.45 Ohm
    motor_temp = np.zeros(n_samples)
    motor_temp[0] = ambient_temp_c[0] + 1.5
    R_armature = 0.45

    for t in range(1, n_samples):
        # Joule loss: I^2 * R
        p_joule = (current_a[t] ** 2) * R_armature * (1.0 + 0.00393 * (motor_temp[t-1] - 20.0))
        # Mechanical friction loss
        p_friction = 0.002 * rpm[t]
        q_in = p_joule + p_friction
        # Heat dissipation to ambient (thermal resistance ~ 2.4 K/W, heat capacitance ~ 180 J/K)
        q_dissipate = (motor_temp[t-1] - ambient_temp_c[t]) / 2.4
        dT_dt = (q_in - q_dissipate) / 180.0
        motor_temp[t] = motor_temp[t-1] + dT_dt * 10.0

    # Temperature rate of change
    dt_temp = np.gradient(motor_temp, 10.0)
    electrical_power_w = voltage_v * current_a
    joule_loss_w = (current_a ** 2) * R_armature

    # Multi-horizon forecasting targets (+1m, +5m, +15m, +30m)
    step_1m = 6    # 6 * 10s = 60s
    step_5m = 30   # 30 * 10s = 300s
    step_15m = 90  # 90 * 10s = 900s
    step_30m = 180 # 180 * 10s = 1800s

    target_1m = pd.Series(motor_temp).shift(-step_1m).bfill().ffill().values
    target_5m = pd.Series(motor_temp).shift(-step_5m).bfill().ffill().values
    target_15m = pd.Series(motor_temp).shift(-step_15m).bfill().ffill().values
    target_30m = pd.Series(motor_temp).shift(-step_30m).bfill().ffill().values

    # Feature Matrix (4 Primary Sensors + Physics Features)
    feature_names = [
        "voltage_v",          # 0-25V Sensor (ADCINA0)
        "current_a",          # ACS712 5A Sensor (ADCINA1)
        "rpm",                # LM393 Optical Sensor (GPIO 0)
        "temp_c",             # DS18B20 Sensor (GPIO 3)
        "power_w",            # V * I
        "joule_loss_w",       # I^2 * R
        "dt_temp_rate",       # dT / dt
        "ambient_temp_c"      # Ambient Reference
    ]

    df = pd.DataFrame({
        "voltage_v": voltage_v,
        "current_a": current_a,
        "rpm": rpm,
        "temp_c": motor_temp,
        "power_w": electrical_power_w,
        "joule_loss_w": joule_loss_w,
        "dt_temp_rate": dt_temp,
        "ambient_temp_c": ambient_temp_c
    })

    X = df[feature_names].fillna(0)
    Y = pd.DataFrame({
        "target_1m": target_1m,
        "target_5m": target_5m,
        "target_15m": target_15m,
        "target_30m": target_30m
    }).fillna(0)

    # 2. Train-Test Split
    print("[2/5] Splitting data into 80% Train and 20% Test sets...")
    X_train, X_test, Y_train, Y_test = train_test_split(X, Y, test_size=0.20, random_state=42, shuffle=True)

    # 3. Fit 100-Tree Random Forest Regressor
    print("[3/5] Training 100-Tree Multi-Output Random Forest Regressor...")
    rf = RandomForestRegressor(
        n_estimators=100,
        max_depth=16,
        min_samples_split=4,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1
    )
    rf.fit(X_train, Y_train)

    # 4. Evaluate Model Across Horizons
    print("[4/5] Evaluating Multi-Horizon Validation Metrics...")
    Y_pred = rf.predict(X_test)
    horizons = ["+1 Min", "+5 Min", "+15 Min", "+30 Min"]
    metrics_summary = []

    print("-" * 65)
    print(f"{'Horizon':<12} | {'R-Squared (R2)':<16} | {'MAE (deg C)':<14} | {'RMSE (deg C)':<12}")
    print("-" * 65)

    for i, col in enumerate(Y.columns):
        r2 = r2_score(Y_test[col], Y_pred[:, i])
        mae = mean_absolute_error(Y_test[col], Y_pred[:, i])
        rmse = np.sqrt(mean_squared_error(Y_test[col], Y_pred[:, i]))
        print(f"{horizons[i]:<12} | {r2 * 100:.2f}% (R2={r2:.4f})  | {mae:.2f} deg C     | {rmse:.2f} deg C")
        metrics_summary.append({
            "horizon": horizons[i],
            "r2": round(float(r2), 4),
            "mae_degc": round(float(mae), 2),
            "rmse_degc": round(float(rmse), 2)
        })
    print("-" * 65)

    # Calculate Feature Importances (XAI)
    feature_importances = rf.feature_importances_
    total_imp = np.sum(feature_importances)
    importance_pct = [(feature_names[i], round(float(feature_importances[i] / total_imp * 100.0), 2))
                      for i in range(len(feature_names))]
    importance_pct.sort(key=lambda x: x[1], reverse=True)

    print("\n[Explainable AI - Feature Importances across 100 Trees]:")
    for feat, pct in importance_pct:
        bar = "#" * int(pct // 2)
        print(f"  * {feat:<16}: {pct:>5.1f}%  | {bar}")

    # 5. Export Model & Artifacts
    print("\n[5/5] Exporting Trained Model and Frontend Model Weights...")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model_pkl_path = os.path.join(base_dir, "core_server", "random_forest_model.pkl")
    weights_json_path = os.path.join(base_dir, "dashboard_ui", "rf_model_weights.json")

    joblib.dump(rf, model_pkl_path)
    print(f"  [SAVED] Serialized RF Model: {model_pkl_path}")

    # Export weights & metadata for real-time frontend integration
    metadata = {
        "model_type": "RandomForestRegressor",
        "system": "12V DC Motor Continuous Testbed",
        "mcu_pipeline": "TMS320F2800137 -> ESP32-S Wi-Fi -> Laptop",
        "sensors": {
            "voltage": "0-25V Sensor Module (ADCINA0)",
            "current": "ACS712 5A Module (ADCINA1)",
            "speed": "LM393 Optical Sensor (GPIO 0)",
            "temp": "DS18B20 1-Wire Probe (GPIO 3)"
        },
        "n_estimators": 100,
        "feature_names": feature_names,
        "feature_importances_pct": dict(importance_pct),
        "validation_metrics": metrics_summary,
        "feature_means": [float(X[f].mean()) for f in feature_names],
        "feature_stds": [float(X[f].std()) for f in feature_names],
        "last_trained": pd.Timestamp.now().isoformat()
    }

    with open(weights_json_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"  [SAVED] Frontend Model Weights & Metadata: {weights_json_path}")
    print("\n[SUCCESS] 12V DC Motor Random Forest Pipeline Ready!")

if __name__ == "__main__":
    train_and_export()
