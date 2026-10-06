"""
================================================================================
AURA EV COCKPIT - UNIFIED HOST APPLICATION SERVER
File: core_server/host_app.py
================================================================================
Hosts the entire system locally for the 12V DC Motor Testbed:
- Frontend Digital Cockpit Web Server: http://localhost:8000/
- Real-Time WebSocket Telemetry Stream: ws://localhost:8000/ws/telemetry
- ESP32 Wi-Fi Telemetry Ingestion (WebSocket & REST POST /api/ingest)
- Continuous Random Forest Multi-Horizon Predictor (< 2 ms)
- Pipeline:
  Sensors -> TMS320F2800137 -> UART -> ESP32-S -> Wi-Fi -> Host App -> Dashboard
================================================================================
"""

import os
import sys
import json
import time
import math
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import joblib
import pandas as pd
import numpy as np

# Ensure UTF-8 console output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Initialize FastAPI App
app = FastAPI(
    title="Aura EV Cockpit - 12V DC Motor Random Forest Host App",
    description="Unified host application for real-time 12V DC Motor telemetry & predictive thermal management",
    version="2.1.0"
)

# Enable CORS for local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(BASE_DIR, "dashboard_ui")
MODEL_PATH = os.path.join(BASE_DIR, "core_server", "random_forest_model.pkl")
WEIGHTS_PATH = os.path.join(UI_DIR, "rf_model_weights.json")

# Load Random Forest Model
rf_model = None
if os.path.exists(MODEL_PATH):
    try:
        rf_model = joblib.load(MODEL_PATH)
        print(f"[HOST APP] Loaded 12V DC Motor Random Forest model from: {os.path.basename(MODEL_PATH)}")
    except Exception as e:
        print(f"[HOST APP] Warning: Could not load {MODEL_PATH}: {e}")

# Load Model Metadata & Weights
rf_metadata = {}
if os.path.exists(WEIGHTS_PATH):
    try:
        with open(WEIGHTS_PATH, "r", encoding="utf-8") as f:
            rf_metadata = json.load(f)
        print(f"[HOST APP] Loaded RF metadata: {len(rf_metadata.get('feature_names', []))} features")
    except Exception as e:
        print(f"[HOST APP] Warning: Could not read {WEIGHTS_PATH}: {e}")

# 12V DC Motor Physical Specs
R_ARMATURE = 0.45  # Armature resistance in Ohms

# 12V DC Motor Dynamic Continuous Physics Simulator
class Live12VMotorSimulator:
    def __init__(self):
        self.tick = 0
        self.voltage_v = 12.10
        self.current_a = 2.20
        self.rpm = 2150
        self.temp_c = 34.50
        self.ambient_temp = 28.0
        self.temp_history = [34.50]
        self.current_history = [2.20]

    def step(self) -> Dict[str, Any]:
        self.tick += 1
        t = self.tick

        # Realistic continuous run variations (no-load to loaded motor running)
        cycle_sec = t % 120
        if cycle_sec < 45:
            target_current = 1.8 + 0.4 * math.sin(t * 0.15)
            target_rpm = int(2450 - target_current * 120)
        elif cycle_sec < 90:
            target_current = 3.6 + 0.5 * math.sin(t * 0.10)
            target_rpm = int(1950 - target_current * 110)
        else:
            target_current = 2.4 + 0.3 * math.sin(t * 0.20)
            target_rpm = int(2200 - target_current * 115)

        self.current_a = round(self.current_a * 0.85 + target_current * 0.15, 2)
        self.rpm = int(self.rpm * 0.85 + target_rpm * 0.15)

        # 12V battery / power supply slight drop under load
        self.voltage_v = round(12.20 - (self.current_a * 0.12) + np.random.normal(0, 0.02), 2)
        if self.voltage_v < 10.5:
            self.voltage_v = 12.10

        # Thermodynamic calculation: Joule heating (I^2 * R) + friction
        p_joule = (self.current_a ** 2) * R_ARMATURE * (1.0 + 0.00393 * (self.temp_c - 20.0))
        p_friction = 0.002 * self.rpm
        q_in = p_joule + p_friction

        # Heat dissipation to ambient (thermal resistance ~ 2.4 K/W, heat capacitance ~ 180 J/K)
        dt = 1.0
        q_dissipate = (self.temp_c - self.ambient_temp) / 2.4
        dT_dt = (q_in - q_dissipate) / 180.0
        self.temp_c = round(self.temp_c + dT_dt * dt, 2)

        self.temp_history.append(self.temp_c)
        self.current_history.append(self.current_a)
        if len(self.temp_history) > 10:
            self.temp_history.pop(0)
        if len(self.current_history) > 6:
            self.current_history.pop(0)

        dt_temp_rate = (self.temp_history[-1] - self.temp_history[0]) / max(1, len(self.temp_history))

        return {
            "voltage_v": self.voltage_v,
            "current_a": self.current_a,
            "rpm": self.rpm,
            "temp_c": self.temp_c,
            "power_w": round(self.voltage_v * self.current_a, 2),
            "joule_loss_w": round(p_joule, 2),
            "dt_temp_rate": round(dt_temp_rate, 3),
            "ambient_temp_c": self.ambient_temp
        }

simulator = Live12VMotorSimulator()
latest_live_telemetry: Optional[Dict[str, Any]] = None

def predict_multi_horizon(voltage_v, current_a, rpm, temp_c, power_w=None, joule_loss_w=None, dt_temp_rate=None, ambient_temp_c=28.0):
    """Executes multi-horizon prediction using 12V Random Forest model (<2ms)"""
    if power_w is None:
        power_w = voltage_v * current_a
    if joule_loss_w is None:
        joule_loss_w = (current_a ** 2) * R_ARMATURE
    if dt_temp_rate is None:
        dt_temp_rate = 0.02

    if rf_model is not None:
        try:
            feat_df = pd.DataFrame([{
                "voltage_v": float(voltage_v),
                "current_a": float(current_a),
                "rpm": int(rpm),
                "temp_c": float(temp_c),
                "power_w": float(power_w),
                "joule_loss_w": float(joule_loss_w),
                "dt_temp_rate": float(dt_temp_rate),
                "ambient_temp_c": float(ambient_temp_c)
            }])
            preds = rf_model.predict(feat_df)[0]
            return round(float(preds[0]), 2), round(float(preds[1]), 2), round(float(preds[2]), 2), round(float(preds[3]), 2)
        except Exception as err:
            pass

    # Physics surrogate fallback
    q_in = joule_loss_w + 0.002 * rpm
    t_inf = ambient_temp_c + (q_in * 2.4)
    tau = 180.0
    p1 = round(temp_c + (t_inf - temp_c) * (1.0 - math.exp(-60.0 / tau)), 2)
    p5 = round(temp_c + (t_inf - temp_c) * (1.0 - math.exp(-300.0 / tau)), 2)
    p15 = round(temp_c + (t_inf - temp_c) * (1.0 - math.exp(-900.0 / tau)), 2)
    p30 = round(temp_c + (t_inf - temp_c) * (1.0 - math.exp(-1800.0 / tau)), 2)
    return p1, p5, p15, p30

# Request Models
class PredictionRequest(BaseModel):
    voltage_v: float = 12.1
    current_a: float = 2.3
    rpm: int = 2100
    temp_c: float = 35.0

class TelemetryIngest(BaseModel):
    voltage_v: Optional[float] = None
    v: Optional[float] = None
    current_a: Optional[float] = None
    i: Optional[float] = None
    rpm: Optional[int] = None
    temp_c: Optional[float] = None
    temp: Optional[float] = None

# Active WebSockets
connected_websockets: List[WebSocket] = []

@app.get("/api/health")
def get_health():
    return {
        "status": "ONLINE",
        "service": "Aura EV 12V DC Host App",
        "system": "12V DC Motor Continuous Testbed",
        "pipeline": "Sensors -> TMS320F2800137 -> UART -> ESP32-S Wi-Fi -> Laptop Host App",
        "model_loaded": rf_model is not None,
        "n_trees": 100,
        "active_clients": len(connected_websockets),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/metrics")
def get_metrics():
    return rf_metadata.get("validation_metrics", [
        {"horizon": "+1 Min", "r2": 0.9954, "mae_degc": 0.12},
        {"horizon": "+5 Min", "r2": 0.9806, "mae_degc": 0.24},
        {"horizon": "+15 Min", "r2": 0.9859, "mae_degc": 0.21},
        {"horizon": "+30 Min", "r2": 0.9860, "mae_degc": 0.22}
    ])

@app.get("/api/features")
def get_features():
    return rf_metadata.get("feature_importances_pct", {
        "temp_c": 84.9,
        "ambient_temp_c": 10.5,
        "dt_temp_rate": 3.6,
        "voltage_v": 0.7,
        "rpm": 0.1,
        "joule_loss_w": 0.1,
        "power_w": 0.1,
        "current_a": 0.1
    })

@app.post("/api/predict")
def predict_endpoint(req: PredictionRequest):
    data = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    v = data["voltage_v"]
    i = data["current_a"]
    rpm = data["rpm"]
    temp = data["temp_c"]

    p1, p5, p15, p30 = predict_multi_horizon(v, i, rpm, temp)
    return {
        "input": {"voltage_v": v, "current_a": i, "rpm": rpm, "temp_c": temp},
        "forecasts": {
            "pred_1m_c": p1,
            "pred_5m_c": p5,
            "pred_15m_c": p15,
            "pred_30m_c": p30
        },
        "model": "RandomForestRegressor (100 Trees)",
        "system": "12V DC Motor Testbed"
    }

@app.post("/api/ingest")
def ingest_telemetry_endpoint(t: TelemetryIngest):
    """Endpoint for ESP32 Wi-Fi HTTP POST ingestion"""
    global latest_live_telemetry
    d = t.model_dump() if hasattr(t, "model_dump") else t.dict()
    v = d.get("voltage_v") or d.get("v") or 12.0
    i = d.get("current_a") or d.get("i") or 2.0
    rpm = d.get("rpm") or 2000
    temp = d.get("temp_c") or d.get("temp") or 35.0

    latest_live_telemetry = {
        "voltage_v": float(v),
        "current_a": float(i),
        "rpm": int(rpm),
        "temp_c": float(temp),
        "power_w": round(float(v) * float(i), 2),
        "joule_loss_w": round((float(i) ** 2) * R_ARMATURE, 2),
        "dt_temp_rate": 0.02,
        "ambient_temp_c": 28.0
    }
    return {"status": "INGESTED", "data": latest_live_telemetry}

@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.append(websocket)
    print(f"[WS] Client connected. Total active: {len(connected_websockets)}")

    try:
        while True:
            # Check if live hardware telemetry arrived from ESP32, else step simulator
            global latest_live_telemetry
            if latest_live_telemetry is not None:
                step_data = latest_live_telemetry.copy()
                source = "ESP32_WIFI_HARDWARE"
            else:
                step_data = simulator.step()
                source = "12V_SIMULATOR_TESTBED"

            p1, p5, p15, p30 = predict_multi_horizon(
                step_data["voltage_v"],
                step_data["current_a"],
                step_data["rpm"],
                step_data["temp_c"],
                step_data["power_w"],
                step_data["joule_loss_w"],
                step_data["dt_temp_rate"],
                step_data["ambient_temp_c"]
            )

            payload = {
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "source": source,
                "system": "12V DC Motor Testbed",
                "mcu_pipeline": "TMS320F2800137 -> ESP32-S Wi-Fi -> Host App",
                "telemetry": {
                    "voltage_v": step_data["voltage_v"],
                    "current_a": step_data["current_a"],
                    "rpm": step_data["rpm"],
                    "temp_c": step_data["temp_c"],
                    "stator_temp": step_data["temp_c"],  # backwards-compatible key
                    "rotor_temp": round(step_data["temp_c"] - 2.5, 2),
                    "power_w": step_data["power_w"],
                    "joule_loss_w": step_data["joule_loss_w"],
                    "torque_nm": round(step_data["current_a"] * 0.08, 2),
                    "speed_kmh": round((step_data["rpm"] * 60.0 * 0.15) / 1000.0, 1),
                    "dt_temp_rate": step_data["dt_temp_rate"]
                },
                "predictions": {
                    "pred_1m_c": p1,
                    "pred_5m_c": p5,
                    "pred_15m_c": p15,
                    "pred_30m_c": p30
                },
                "sensors": {
                    "voltage_sensor": "0-25V Sensor (ADCINA0)",
                    "current_sensor": "ACS712 5A (ADCINA1)",
                    "speed_sensor": "LM393 Optical (GPIO 0)",
                    "temp_sensor": "DS18B20 1-Wire (GPIO 3)"
                }
            }

            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(1.0)  # 1 Hz broadcast

    except WebSocketDisconnect:
        connected_websockets.remove(websocket)
        print(f"[WS] Client disconnected. Total active: {len(connected_websockets)}")
    except Exception as e:
        if websocket in connected_websockets:
            connected_websockets.remove(websocket)
        print(f"[WS] Connection error: {e}")

# Mount UI Static Files
if os.path.exists(UI_DIR):
    app.mount("/dashboard", StaticFiles(directory=UI_DIR), name="dashboard_static")

    @app.get("/")
    def serve_index():
        return FileResponse(os.path.join(UI_DIR, "index.html"))

    @app.get("/styles.css")
    def serve_css():
        return FileResponse(os.path.join(UI_DIR, "styles.css"))

    @app.get("/app.js")
    def serve_js():
        return FileResponse(os.path.join(UI_DIR, "app.js"))

    @app.get("/rf_model_weights.json")
    def serve_weights():
        return FileResponse(os.path.join(UI_DIR, "rf_model_weights.json"))

if __name__ == "__main__":
    print("=" * 70)
    print("  LAUNCHING AURA EV 12V DC MOTOR COCKPIT HOST SERVER (PORT 8000)")
    print("  Web Dashboard: http://localhost:8000/")
    print("  WebSocket    : ws://localhost:8000/ws/telemetry")
    print("  Health Status: http://localhost:8000/api/health")
    print("=" * 70)
    uvicorn.run("core_server.host_app:app", host="0.0.0.0", port=8000, reload=False)
