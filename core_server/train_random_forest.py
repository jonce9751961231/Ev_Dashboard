"""
================================================================================
AURA EV DIGITAL COCKPIT - LOCAL RANDOM FOREST TRAINING ENGINE
File: core_server/train_random_forest.py
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
from sklearn.linear_model import Ridge
import joblib

# Ensure UTF-8 output encoding
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def train_and_export():
    print("=" * 70)
    print("     AURA EV - 48V BLDC RANDOM FOREST THERMAL MODEL TRAINING     ")
    print("=" * 70)

    # 1. Synthesize rich 12,000 sample 48V thermal profile for high precision
    print("[1/5] Generating 12,000-sample 48V BLDC Drive Cycle Dataset...")
    n_samples = 12000
    np.random.seed(42)
    time_seconds = np.arange(n_samples) * 10.0

    base_voltage = 48.0 - (time_seconds / time_seconds.max()) * 4.5
    voltage_v = np.clip(base_voltage + np.random.normal(0, 0.15, n_samples), 42.0, 52.0)

    cycle_phase = (time_seconds % 1200) / 1200.0
    current_a = np.where(
        cycle_phase < 0.35, np.random.uniform(1.5, 3.5, n_samples),
        np.where(cycle_phase < 0.70, np.random.uniform(3.5, 4.8, n_samples),
                 np.random.uniform(2.2, 4.2, n_samples))
    )
    current_a = np.clip(current_a + np.random.normal(0, 0.1, n_samples), 0.0, 5.0)
    rpm = np.clip(current_a * 650.0 + np.random.normal(0, 50, n_samples), 0, 3200)
    ambient_temp_c = 28.0 + 4.0 * np.sin(time_seconds / 20000.0)

    stator_temp = np.zeros(n_samples)
    stator_temp[0] = ambient_temp_c[0] + 2.0
    R_phase = 0.085

    for t in range(1, n_samples):
        i_rms = current_a[t] * 0.816
        p_cu = 3.0 * (i_rms ** 2) * R_phase * (1.0 + 0.00393 * (stator_temp[t-1] - 20.0))
        fe_hz = (4 * rpm[t]) / 60.0
        p_fe = (0.015 * fe_hz) + (0.00018 * (fe_hz ** 2))
        q_in = p_cu + p_fe
        q_dissipate = (stator_temp[t-1] - ambient_temp_c[t]) / 1.85
        stator_temp[t] = stator_temp[t-1] + (10.0 / 240.0) * (q_in - q_dissipate)

    df = pd.DataFrame({
        "voltage_v": np.round(voltage_v, 2),
        "current_a": np.round(current_a, 2),
        "rpm": np.round(rpm, 0).astype(int),
        "temp_c": np.round(stator_temp, 2),
        "ambient_temp_c": np.round(ambient_temp_c, 2)
    })

    # Save to dataset path so frontend and user have the full telemetry file
    dataset_path = os.path.join(os.path.dirname(__file__), "..", "datasets", "sample_bldc_telemetry.csv")
    df.to_csv(dataset_path, index=False)
    print(f"  -> Saved training telemetry to: {os.path.basename(dataset_path)} ({len(df)} rows)")

    # 2. Physics-Informed Feature Engineering
    print("[2/5] Engineering Thermodynamic Features (I^2R, Iron Losses, Thermal Differentials)...")
    df["p_joule_loss"] = 3.0 * ((df["current_a"] * 0.816) ** 2) * R_phase
    df["p_elec"] = df["voltage_v"] * df["current_a"]
    df["temp_rate_of_change"] = df["temp_c"].diff().fillna(0.0)
    df["current_rolling_60s"] = df["current_a"].rolling(window=6, min_periods=1).mean()

    # Multi-Horizon Targets (+1m, +5m, +15m, +30m with 10s steps)
    df["target_plus_1m"]  = df["temp_c"].shift(-6).ffill().bfill()
    df["target_plus_5m"]  = df["temp_c"].shift(-30).ffill().bfill()
    df["target_plus_15m"] = df["temp_c"].shift(-90).ffill().bfill()
    df["target_plus_30m"] = df["temp_c"].shift(-180).ffill().bfill()

    feature_cols = [
        "voltage_v", "current_a", "rpm", "temp_c",
        "p_joule_loss", "p_elec", "temp_rate_of_change", "current_rolling_60s"
    ]
    target_cols = ["target_plus_1m", "target_plus_5m", "target_plus_15m", "target_plus_30m"]

    # Fill any edge NaNs cleanly
    df[feature_cols] = df[feature_cols].ffill().bfill().fillna(0.0)
    df[target_cols] = df[target_cols].ffill().bfill().fillna(df["temp_c"])

    X = df[feature_cols]
    y = df[target_cols]

    # Split with shuffle=True to ensure broad generalization across dynamic phases
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, shuffle=True)

    # 3. Train Random Forest
    print("[3/5] Training Random Forest Regressor (100 Decision Trees)...")
    rf = RandomForestRegressor(
        n_estimators=100,
        max_depth=14,
        min_samples_split=4,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1
    )
    rf.fit(X_train, y_train)

    # 4. Evaluation
    print("\n[4/5] Multi-Horizon Validation Results:")
    y_pred = rf.predict(X_test)
    metrics_summary = []
    horizons = ["+1 Min", "+5 Min", "+15 Min", "+30 Min"]
    for i, h in enumerate(horizons):
        r2 = r2_score(y_test.iloc[:, i], y_pred[:, i])
        mae = mean_absolute_error(y_test.iloc[:, i], y_pred[:, i])
        rmse = np.sqrt(mean_squared_error(y_test.iloc[:, i], y_pred[:, i]))
        metrics_summary.append({"Horizon": h, "R2": r2, "MAE": mae, "RMSE": rmse})
        print(f"  * Horizon {h:8s} -> R2 Score: {r2:.4f} ({r2*100:.2f}%) | MAE: {mae:.2f} deg C | RMSE: {rmse:.2f} deg C")

    # Feature Importances (XAI)
    print("\n[XAI] Sensor Feature Importance (% Variance Contribution):")
    for f, imp in sorted(zip(feature_cols, rf.feature_importances_), key=lambda x: x[1], reverse=True):
        print(f"  * {f:22s}: {imp * 100:.2f}%")

    # 5. Export Python Pickle and Frontend JSON
    print("\n[5/5] Exporting Models for Production...")
    
    # Save .pkl in core_server
    pkl_path = os.path.join(os.path.dirname(__file__), "random_forest_model.pkl")
    joblib.dump(rf, pkl_path)
    print(f"  -> Saved Python Model: {os.path.basename(pkl_path)}")

    # Train linear surrogate for fast in-browser JavaScript evaluation
    surrogate = Ridge(alpha=1.0)
    surrogate.fit(X_train, y_train)

    # Save .json in dashboard_ui
    json_path = os.path.join(os.path.dirname(__file__), "..", "dashboard_ui", "rf_model_weights.json")
    export_dict = {
        "model_name": "RandomForest_48V_BLDC_Thermal_Predictor",
        "n_trees": 100,
        "feature_names": feature_cols,
        "feature_importances_pct": [round(float(x) * 100, 2) for x in rf.feature_importances_],
        "metrics": [{"horizon": m["Horizon"], "r2": round(m["R2"], 4), "mae_degc": round(m["MAE"], 2)} for m in metrics_summary],
        "linear_weights": surrogate.coef_.tolist(),
        "intercepts": surrogate.intercept_.tolist(),
        "means": X_train.mean().tolist(),
        "stds": X_train.std().tolist()
    }

    with open(json_path, "w") as f:
        json.dump(export_dict, f, indent=2)
    print(f"  -> Saved Browser JSON: {os.path.basename(json_path)}")

    print("\n[SUCCESS] Random Forest Model trained and exported successfully!\n")

if __name__ == "__main__":
    train_and_export()
