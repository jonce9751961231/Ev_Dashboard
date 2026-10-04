"""
===============================================================================
Project: 48V - 96V EV BLDC Motor Multi-Horizon AI Temperature Forecaster
File: train_bldc_ai_model.py
Description: End-to-End AI Model Training Pipeline for 48V, 60V, 72V, 84V, 96V
             BLDC motors. Learns electro-thermal dynamics, resistive Joule
             heating, high-frequency iron core losses, and predicts future
             temperatures at +1m, +5m, +15m, +30m.
===============================================================================
"""

import os
import json
import math
import numpy as np
from typing import Tuple, Dict, Any


def generate_bldc_multivoltage_dataset(num_samples: int = 15000) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """
    Generates realistic 48V - 96V EV BLDC motor drive cycle telemetry data based on
    coupled electromagnetic losses, varying voltage systems, and thermal dynamics.

    Input Features (X):
      [0] Voltage (V) [48V - 96V nominal, 42V - 110V dynamic]
      [1] Current (A) [0 - 65A]
      [2] Motor Speed (RPM) [0 - 8500 RPM]
      [3] Electrical Power (W)
      [4] Current Measured Stator Temp (°C)
      [5] Rate of Temp Change dT/dt (°C/s)
      [6] Ambient Temp (°C) [20°C - 45°C]
      [7] Estimated Copper Loss P_cu (W)
      [8] Estimated High-Frequency Iron Loss P_fe (W)

    Target Horizons (Y) - Future Temperatures (°C):
      [0] Stator Temp at +1 min  (+60s)
      [1] Stator Temp at +5 min  (+300s) [Primary Derating Horizon]
      [2] Stator Temp at +15 min (+900s)
      [3] Stator Temp at +30 min (+1800s)
      [4] Rotor Magnet Temp at +5 min (+300s) [Demagnetization Horizon]
    """
    np.random.seed(42)

    # 48V-96V BLDC Motor Physical Constants (typical 3 kW - 10 kW hub / mid-drive motor)
    R_phase_20c = 0.085         # Stator phase resistance at 20°C (Ohms)
    alpha_cu = 0.00393          # Copper temperature coefficient (1/K)
    pole_pairs = 4              # 8 poles (4 electrical cycles / mechanical revolution)
    C_stator = 240.0            # Stator thermal capacitance (J/K)
    C_rotor = 310.0             # Rotor permanent magnets thermal capacitance (J/K)
    R_th_stator_air = 2.15      # Thermal resistance to ambient (K/W)
    R_th_rotor_air = 3.40       # Rotor thermal resistance to ambient (K/W)
    tau_stator = 190.0          # Stator thermal time constant (seconds)
    tau_rotor = 520.0           # Rotor thermal time constant (seconds)

    X_list = []
    Y_list = []

    # Nominal voltage systems supported
    voltage_systems = [48.0, 60.0, 72.0, 84.0, 96.0]

    for sys_v in voltage_systems:
        samples_per_sys = num_samples // len(voltage_systems)
        stator_temp = np.random.uniform(28.0, 45.0)
        rotor_temp = stator_temp - 2.0
        ambient_temp = np.random.uniform(25.0, 38.0)
        temp_history = [stator_temp]

        for i in range(samples_per_sys):
            # Select driving regime
            regime = np.random.choice(["idle", "eco_commute", "cruise", "hill_climb", "sprint"],
                                      p=[0.10, 0.30, 0.30, 0.20, 0.10])

            # Max power scales with voltage: at 48V ~3kW, at 72V ~6kW, at 96V ~9kW
            v_ratio = sys_v / 48.0

            if regime == "idle":
                current_a = np.random.uniform(0.0, 1.5)
                rpm = np.random.uniform(0.0, 200.0)
            elif regime == "eco_commute":
                current_a = np.random.uniform(3.0, 10.0) * (0.8 + 0.2 * v_ratio)
                rpm = np.random.uniform(1500, 3200) * (0.85 + 0.15 * v_ratio)
            elif regime == "cruise":
                current_a = np.random.uniform(8.0, 18.0) * (0.8 + 0.2 * v_ratio)
                rpm = np.random.uniform(3000, 5200) * (0.85 + 0.15 * v_ratio)
            elif regime == "hill_climb":
                current_a = np.random.uniform(20.0, 45.0) * (0.8 + 0.2 * v_ratio)
                rpm = np.random.uniform(2000, 4200) * (0.85 + 0.15 * v_ratio)
            else:  # sprint
                current_a = np.random.uniform(30.0, 60.0) * (0.8 + 0.2 * v_ratio)
                rpm = np.random.uniform(5000, 7800) * (0.85 + 0.15 * v_ratio)

            # Bus voltage with battery internal resistance sag (0.05 Ohm pack IR)
            voltage_v = sys_v - (current_a * 0.05) + np.random.normal(0, 0.3)
            power_w = voltage_v * current_a

            # 1. Copper Loss: P_cu = 3 * I_rms^2 * R(T)
            i_phase_rms = current_a * 0.816
            r_actual = R_phase_20c * (1.0 + alpha_cu * (stator_temp - 20.0))
            p_copper = 3.0 * (i_phase_rms ** 2) * r_actual

            # 2. Iron Core Loss: Steinmetz equation P_fe = k_h * f + k_e * f^2
            fe_hz = (pole_pairs * rpm) / 60.0
            p_iron = (0.015 * fe_hz) + (0.00018 * (fe_hz ** 2))

            # 3. Rotor Permanent Magnet Eddy Loss
            p_rotor_eddy = (0.055 * p_iron) + (0.0008 * (i_phase_rms ** 2))

            # Thermal rate of change
            total_stator_loss = p_copper + p_iron
            dT_stator_dt = (total_stator_loss - (stator_temp - ambient_temp) / R_th_stator_air) / C_stator
            dT_rotor_dt = (p_rotor_eddy + 0.08 * p_copper - (rotor_temp - ambient_temp) / R_th_rotor_air) / C_rotor

            # Step physical plant
            stator_temp = float(np.clip(stator_temp + dT_stator_dt * 0.5 + np.random.normal(0, 0.04), 18.0, 150.0))
            rotor_temp = float(np.clip(rotor_temp + dT_rotor_dt * 0.5 + np.random.normal(0, 0.03), 18.0, 130.0))

            temp_history.append(stator_temp)
            if len(temp_history) > 10:
                temp_history.pop(0)

            # Historical rate of temp change (°C/s)
            dT_dt_hist = (temp_history[-1] - temp_history[0]) / max(0.5 * len(temp_history), 0.5)

            # 4. Multi-Horizon Forward Targets (Analytical physics equilibrium + dynamic transient)
            t_stator_inf = ambient_temp + (total_stator_loss * R_th_stator_air)
            t_rotor_inf = ambient_temp + ((p_rotor_eddy + 0.08 * p_copper) * R_th_rotor_air)

            t_plus_1m = t_stator_inf + (stator_temp - t_stator_inf) * math.exp(-60.0 / tau_stator) + (dT_dt_hist * 2.5) + np.random.normal(0, 0.3)
            t_plus_5m = t_stator_inf + (stator_temp - t_stator_inf) * math.exp(-300.0 / tau_stator) + (dT_dt_hist * 6.0) + np.random.normal(0, 0.6)
            t_plus_15m = t_stator_inf + (stator_temp - t_stator_inf) * math.exp(-900.0 / tau_stator) + np.random.normal(0, 1.0)
            t_plus_30m = t_stator_inf + (stator_temp - t_stator_inf) * math.exp(-1800.0 / tau_stator) + np.random.normal(0, 1.4)
            t_rotor_plus_5m = t_rotor_inf + (rotor_temp - t_rotor_inf) * math.exp(-300.0 / tau_rotor) + np.random.normal(0, 0.5)

            feature_row = [
                voltage_v, current_a, rpm, power_w,
                stator_temp, dT_dt_hist, ambient_temp,
                p_copper, p_iron
            ]
            target_row = [
                t_plus_1m, t_plus_5m, t_plus_15m, t_plus_30m,
                t_rotor_plus_5m
            ]

            X_list.append(feature_row)
            Y_list.append(target_row)

    meta = {
        "num_samples": len(X_list),
        "voltage_range": "48V - 96V",
        "feature_names": [
            "voltage_v", "current_a", "speed_rpm", "power_w",
            "stator_temp_c", "dT_dt", "ambient_temp_c",
            "copper_loss_w", "iron_loss_w"
        ],
        "target_names": [
            "pred_stator_plus_1m_c",
            "pred_stator_plus_5m_c",
            "pred_stator_plus_15m_c",
            "pred_stator_plus_30m_c",
            "pred_rotor_magnet_plus_5m_c"
        ]
    }
    return np.array(X_list, dtype=np.float32), np.array(Y_list, dtype=np.float32), meta


class BLDCMultiHorizonAIRegressor:
    """
    Physics-Informed Regularized AI Regressor.
    Supports matrix export for fast execution in Python, JavaScript (browser),
    and C++ (ESP32 / C2000).
    """

    def __init__(self, alpha: float = 0.2):
        self.alpha = alpha
        self.mean_X: np.ndarray = None
        self.std_X: np.ndarray = None
        self.weights: np.ndarray = None
        self.bias: np.ndarray = None
        self.feature_names = []
        self.target_names = []

    def fit(self, X: np.ndarray, Y: np.ndarray, feature_names=None, target_names=None):
        self.feature_names = feature_names or []
        self.target_names = target_names or []

        self.mean_X = np.mean(X, axis=0)
        self.std_X = np.std(X, axis=0) + 1e-6
        X_norm = (X - self.mean_X) / self.std_X

        # Bias expansion
        N = X_norm.shape[0]
        X_design = np.hstack([np.ones((N, 1), dtype=np.float32), X_norm])

        # Regularized Closed-Form Solution: W = (X^T * X + alpha * I)^(-1) * X^T * Y
        D = X_design.shape[1]
        I = np.eye(D, dtype=np.float32)
        I[0, 0] = 0.0  # Do not regularize bias

        W = np.linalg.solve(X_design.T @ X_design + self.alpha * I, X_design.T @ Y)
        self.bias = W[0, :]
        self.weights = W[1:, :]

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predicts future temperature array across all horizons."""
        X_arr = np.asarray(X, dtype=np.float32)
        if X_arr.ndim == 1:
            X_arr = X_arr.reshape(1, -1)
        X_norm = (X_arr - self.mean_X) / self.std_X
        return X_norm @ self.weights + self.bias

    def export_json(self, filepath: str):
        """Exports model parameters to a JSON file for JavaScript / Web Dashboard."""
        model_dict = {
            "model_type": "BLDCMultiHorizonAIRegressor",
            "voltage_coverage": "48V - 96V",
            "feature_names": self.feature_names,
            "target_names": self.target_names,
            "means": [float(v) for v in self.mean_X],
            "stds": [float(v) for v in self.std_X],
            "bias": [float(v) for v in self.bias],
            "weights": [[float(val) for val in row] for row in self.weights]
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(model_dict, f, indent=2)
        print(f"[EXPORT] Saved AI Model weights to '{filepath}'")

    def export_c_header(self, filepath: str):
        """Exports model parameters to a C/C++ header for ESP32 / C2000 firmware."""
        code = "/**\n * 48V-96V BLDC Multi-Horizon Temperature AI Weights\n"
        code += " * Generated by train_bldc_ai_model.py\n */\n\n"
        code += "#ifndef BLDC_AI_WEIGHTS_H\n#define BLDC_AI_WEIGHTS_H\n\n"
        code += f"#define AI_NUM_FEATURES {len(self.mean_X)}\n"
        code += f"#define AI_NUM_HORIZONS {self.weights.shape[1]}\n\n"

        code += "static const float AI_FEATURE_MEANS[9] = {" + ", ".join([f"{v:.5f}f" for v in self.mean_X]) + "};\n"
        code += "static const float AI_FEATURE_STDS[9]  = {" + ", ".join([f"{v:.5f}f" for v in self.std_X]) + "};\n"
        code += "static const float AI_BIAS[5]          = {" + ", ".join([f"{v:.5f}f" for v in self.bias]) + "};\n\n"

        code += "static const float AI_WEIGHTS[9][5] = {\n"
        for row in self.weights:
            code += "    {" + ", ".join([f"{v:.5f}f" for v in row]) + "},\n"
        code += "};\n\n"
        code += "#endif /* BLDC_AI_WEIGHTS_H */\n"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"[EXPORT] Saved C header weights to '{filepath}'")


def main():
    print("=================================================================")
    print(" ⚡ Training 48V-96V BLDC Multi-Horizon Temperature AI Model ⚡  ")
    print("=================================================================")

    # 1. Generate Dataset
    print("[1/4] Generating synthetic 48V - 96V BLDC drive cycle dataset...")
    X, Y, meta = generate_bldc_multivoltage_dataset(num_samples=16000)
    print(f"      Generated {len(X)} samples across 48V, 60V, 72V, 84V, 96V systems.")

    # 2. Train / Test Split (80% / 20%)
    split_idx = int(0.80 * len(X))
    X_train, X_test = X[:split_idx], X[split_idx:]
    Y_train, Y_test = Y[:split_idx], Y[split_idx:]

    # 3. Fit Model
    print("[2/4] Training Physics-Informed Multi-Horizon Regressor...")
    model = BLDCMultiHorizonAIRegressor(alpha=0.3)
    model.fit(X_train, Y_train, meta["feature_names"], meta["target_names"])

    # 4. Evaluate Test Set Metrics
    print("[3/4] Evaluating Accuracy on 48V-96V Test Set...")
    Y_pred = model.predict(X_test)

    print("\n--- Test Set Evaluation Metrics ---")
    for j, target_name in enumerate(meta["target_names"]):
        actual = Y_test[:, j]
        pred = Y_pred[:, j]
        mae = float(np.mean(np.abs(actual - pred)))
        rmse = float(np.sqrt(np.mean((actual - pred) ** 2)))
        ss_res = np.sum((actual - pred) ** 2)
        ss_tot = np.sum((actual - np.mean(actual)) ** 2)
        r2 = float(1.0 - (ss_res / ss_tot))
        print(f"  • {target_name:30s} | MAE: {mae:.2f}°C | RMSE: {rmse:.2f}°C | R² Score: {r2:.4f}")

    # 5. Export Weights
    print("\n[4/4] Exporting Model Weights...")
    os.makedirs("core_server", exist_ok=True)
    os.makedirs("esp32_firmware", exist_ok=True)
    
    json_path = os.path.join("core_server", "bldc_ai_model_weights.json")
    model.export_json(json_path)

    c_header_path = os.path.join("esp32_firmware", "bldc_ai_weights.h")
    model.export_c_header(c_header_path)

    print("\n[SUCCESS] 48V-96V BLDC AI Model successfully trained and exported!")


if __name__ == "__main__":
    main()
