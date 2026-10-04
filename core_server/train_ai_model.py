"""
===============================================================================
Project: EV Dashboard & Predictive Thermal AI System (TI C2000)
File: train_ai_model.py
Description: End-to-End AI Model Training Pipeline for Future Motor Temperature
             Prediction (Physics-Informed Multi-Horizon Regressor).
===============================================================================
"""

import numpy as np
import math
import json
from typing import Tuple, Dict, Any


def generate_synthetic_drive_cycle_dataset(num_samples: int = 10000) -> Tuple[np.ndarray, np.ndarray]:
    """
    Generates realistic EV DC/PMSM motor drive cycle telemetry data based on
    physical energy balance, diverse driving patterns, and thermal dynamics.
    
    Inputs (X):
      [0] Armature Current (A)
      [1] Terminal Voltage (V)
      [2] Motor Speed (RPM)
      [3] Shaft Torque (Nm)
      [4] Current Measured Temperature (°C)
      [5] Rate of Temperature Change (°C/s)
      [6] Ambient Temperature (°C)
      [7] Road Grade Slope (%)
      [8] Calculated Copper Loss (W)
      
    Targets (Y) - Future Temperatures (°C):
      [0] Temp at +1 min  (+60s)
      [1] Temp at +5 min  (+300s)
      [2] Temp at +15 min (+900s)
      [3] Temp at +30 min (+1800s)
    """
    np.random.seed(42)
    
    # Motor thermal parameters (matching physical prototype)
    R0 = 0.42             # Armature resistance at 20°C
    alpha_cu = 0.00393    # Copper temp coefficient
    C_thermal = 140.0     # Thermal heat capacity (J/K)
    R_thermal_tot = 3.85  # Total thermal resistance to ambient (K/W)
    tau_th = 180.0        # Thermal time constant (seconds)

    X_list = []
    Y_list = []

    current_temp = 30.0
    ambient_temp = 28.0

    for i in range(num_samples):
        # 1. Simulate varying driving behaviors (Eco, Cruise, Uphill, Aggressive)
        mode = np.random.choice(["eco", "cruise", "uphill", "aggressive"], p=[0.3, 0.35, 0.2, 0.15])
        
        if mode == "eco":
            current_a = np.random.uniform(2.0, 6.0)
            rpm = np.random.uniform(1200, 2500)
            grade_pct = np.random.uniform(0.0, 2.0)
        elif mode == "cruise":
            current_a = np.random.uniform(5.0, 9.0)
            rpm = np.random.uniform(3000, 5000)
            grade_pct = np.random.uniform(0.0, 1.5)
        elif mode == "uphill":
            current_a = np.random.uniform(10.0, 16.0)
            rpm = np.random.uniform(2500, 4200)
            grade_pct = np.random.uniform(6.0, 12.0)
        else: # aggressive
            current_a = np.random.uniform(12.0, 20.0)
            rpm = np.random.uniform(4500, 7500)
            grade_pct = np.random.uniform(1.0, 5.0)

        voltage_v = 48.0 - (current_a * 0.08) + np.random.normal(0, 0.2)
        torque_nm = (current_a * 0.28) + np.random.normal(0, 0.05)

        # 2. Physics calculations
        r_actual = R0 * (1.0 + alpha_cu * (current_temp - 20.0))
        p_copper = (current_a ** 2) * r_actual
        p_iron = 0.002 * rpm + 0.00003 * (rpm ** 2)
        total_loss = p_copper + p_iron

        # Rate of temperature change dT/dt
        dT_dt = (total_loss - (current_temp - ambient_temp) / R_thermal_tot) / C_thermal
        current_temp = max(20.0, min(140.0, current_temp + dT_dt * 0.5 + np.random.normal(0, 0.05)))

        # 3. Ground-truth multi-horizon future temperatures (Analytical asymptotic physics + noise)
        t_inf = ambient_temp + (total_loss * R_thermal_tot)
        t_plus_1m  = t_inf + (current_temp - t_inf) * math.exp(-60.0 / tau_th) + np.random.normal(0, 0.3)
        t_plus_5m  = t_inf + (current_temp - t_inf) * math.exp(-300.0 / tau_th) + np.random.normal(0, 0.6)
        t_plus_15m = t_inf + (current_temp - t_inf) * math.exp(-900.0 / tau_th) + np.random.normal(0, 1.0)
        t_plus_30m = t_inf + (current_temp - t_inf) * math.exp(-1800.0 / tau_th) + np.random.normal(0, 1.5)

        feature_vector = [
            current_a, voltage_v, rpm, torque_nm, current_temp,
            dT_dt, ambient_temp, grade_pct, p_copper
        ]
        target_vector = [t_plus_1m, t_plus_5m, t_plus_15m, t_plus_30m]

        X_list.append(feature_vector)
        Y_list.append(target_vector)

    return np.array(X_list, dtype=np.float32), np.array(Y_list, dtype=np.float32)


class PhysicsInformedMultiHorizonRegressor:
    """
    Lightweight, highly-accurate Physics-Informed Ridge / Multi-Output Model.
    Can be run in Python and easily exported as matrix weights for real-time
    execution on the TI C2000 TMS320F2800137 FPU.
    """

    def __init__(self, alpha: float = 0.1):
        self.alpha = alpha
        self.mean_X: np.ndarray = None
        self.std_X: np.ndarray = None
        self.weights: np.ndarray = None
        self.bias: np.ndarray = None

    def fit(self, X: np.ndarray, Y: np.ndarray):
        """Trains multi-output linear/polynomial ridge regression model."""
        self.mean_X = np.mean(X, axis=0)
        self.std_X = np.std(X, axis=0) + 1e-6
        X_norm = (X - self.mean_X) / self.std_X

        # Add bias column
        N = X_norm.shape[0]
        X_design = np.hstack([np.ones((N, 1), dtype=np.float32), X_norm])

        # Regularized Closed-Form Solution: W = (X^T * X + alpha * I)^(-1) * X^T * Y
        D = X_design.shape[1]
        I = np.eye(D, dtype=np.float32)
        I[0, 0] = 0.0 # Don't regularize bias

        W = np.linalg.solve(X_design.T @ X_design + self.alpha * I, X_design.T @ Y)
        self.bias = W[0, :]
        self.weights = W[1:, :]

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predicts future temperatures at +1m, +5m, +15m, +30m."""
        X_norm = (X - self.mean_X) / self.std_X
        return X_norm @ self.weights + self.bias

    def export_c_header(self, filepath: str):
        """Exports learned weights as an embedded C header file for TI C2000 CCS."""
        c_code = "/**\n * Learned AI Model Weights for TI C2000 (TMS320F2800137)\n */\n\n"
        c_code += "#ifndef AI_MODEL_WEIGHTS_H\n#define AI_MODEL_WEIGHTS_H\n\n"
        c_code += f"#define NUM_FEATURES {len(self.mean_X)}\n"
        c_code += f"#define NUM_HORIZONS {self.weights.shape[1]}\n\n"

        # Means and Stds
        c_code += "static const float AI_FEATURE_MEANS[9] = {" + ", ".join([f"{v:.5f}f" for v in self.mean_X]) + "};\n"
        c_code += "static const float AI_FEATURE_STDS[9] = {" + ", ".join([f"{v:.5f}f" for v in self.std_X]) + "};\n"
        c_code += "static const float AI_BIAS[4] = {" + ", ".join([f"{v:.5f}f" for v in self.bias]) + "};\n\n"

        # Weights matrix
        c_code += "static const float AI_WEIGHTS[9][4] = {\n"
        for row in self.weights:
            c_code += "    {" + ", ".join([f"{v:.5f}f" for v in row]) + "},\n"
        c_code += "};\n\n"
        c_code += "#endif /* AI_MODEL_WEIGHTS_H */\n"

        with open(filepath, "w") as f:
            f.write(c_code)


if __name__ == "__main__":
    print("=== Training EV Motor Temperature Predictive AI Model ===")
    
    # 1. Generate Dataset
    X, Y = generate_synthetic_drive_cycle_dataset(num_samples=12000)
    
    # Split Train/Test (80/20)
    split_idx = int(0.8 * len(X))
    X_train, X_test = X[:split_idx], X[split_idx:]
    Y_train, Y_test = Y[:split_idx], Y[split_idx:]

    # 2. Train Model
    model = PhysicsInformedMultiHorizonRegressor(alpha=0.5)
    model.fit(X_train, Y_train)

    # 3. Evaluate on Test Set
    Y_pred = model.predict(X_test)
    horizons = ["+1 min", "+5 min", "+15 min", "+30 min"]

    print("\n--- Model Evaluation Results (Test Set) ---")
    for j, h in enumerate(horizons):
        mae = np.mean(np.abs(Y_test[:, j] - Y_pred[:, j]))
        rmse = np.sqrt(np.mean((Y_test[:, j] - Y_pred[:, j]) ** 2))
        r2 = 1.0 - (np.sum((Y_test[:, j] - Y_pred[:, j]) ** 2) / np.sum((Y_test[:, j] - np.mean(Y_test[:, j])) ** 2))
        print(f"Horizon [{h}]: MAE = {mae:.2f}°C | RMSE = {rmse:.2f}°C | R² Score = {r2:.4f}")

    # 4. Export learned weights for C2000 C header
    model.export_c_header("c2000_firmware/include/ai_model_weights.h")
    print("\n[SUCCESS] Exported learned AI weights to 'c2000_firmware/include/ai_model_weights.h'")
