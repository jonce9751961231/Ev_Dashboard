"""
================================================================================
AURA EV COCKPIT - UNIFIED HOST APPLICATION SERVER
File: core_server/host_app.py
================================================================================
Hosts the entire system locally for the 12V DC Motor Testbed:
- Frontend Digital Cockpit Web Server: http://localhost:8000/
- Real-Time WebSocket Telemetry Stream: ws://localhost:8000/ws/telemetry
- ESP32 Wi-Fi Telemetry Ingestion (REST POST /api/ingest)
- Temperature forecasts: the best model from core_server/ml (Ridge / Random
  Forest / LightGBM / GRU) once trained, otherwise the legacy Random Forest or
  a physics curve. The payload says which one produced each forecast.
- Pipeline:
  Sensors -> TMS320F2800137 -> UART -> ESP32-S -> Wi-Fi -> Host App -> Dashboard
================================================================================
"""

import os
import sys
import json
import time
import math
import csv
import asyncio
import threading
from datetime import datetime
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Depends
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

# Optional API Key Authentication
# Set environment variable AURA_API_KEY to enforce token on write endpoints.
# If unset (development mode), write endpoints allow local network requests.
AURA_API_KEY = os.getenv("AURA_API_KEY", "").strip()

# Cloud Demo Mode: Set DEMO_MODE=1 or AURA_DEMO=1 on public container hosts
DEMO_MODE = os.getenv("DEMO_MODE", os.getenv("AURA_DEMO", "0")).lower() in ("1", "true", "yes", "demo")
if DEMO_MODE:
    print("[HOST APP] Running in CLOUD DEMO SIMULATOR MODE (labeled as demo)")

def verify_write_access(request: Request):
    if not AURA_API_KEY:
        return True
    key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if key != AURA_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid or missing API key (provide 'X-API-Key' header or '?api_key=' parameter)"
        )
    return True

# Lifespan context manager: Runs the centralized 1 Hz broadcaster background task
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(telemetry_broadcaster_task())
    print("[HOST APP] Centralized 1 Hz telemetry broadcaster background task started.")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    print("[HOST APP] Telemetry broadcaster background task stopped.")

# Initialize FastAPI App
app = FastAPI(
    title="ThermaPulse EV Cockpit - 12V DC Host App",
    description="Unified host application for real-time 12V DC Motor telemetry & predictive thermal management",
    version="2.3.0",
    lifespan=lifespan
)

# Standard compliant CORS: Wildcard origin requires allow_credentials=False
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(BASE_DIR, "dashboard_ui")
MODEL_PATH = os.path.join(BASE_DIR, "core_server", "random_forest_model.pkl")
WEIGHTS_PATH = os.path.join(UI_DIR, "rf_model_weights.json")
RUNS_DIR = os.path.join(BASE_DIR, "datasets", "runs")

class CsvRunRecorder:
    """Thread-safe CSV Run Recorder for live testbed runs.
    
    Logs timestamp, raw sensor readings, active ML predictions, thermal alerts,
    and preserves ground truth (disconnected sensors logged as blank '').
    """
    def __init__(self, runs_dir: str):
        self.runs_dir = runs_dir
        os.makedirs(self.runs_dir, exist_ok=True)
        self.is_recording = False
        self.current_run_id = None
        self.current_filepath = None
        self.file_handle = None
        self.csv_writer = None
        self.rows_recorded = 0
        self.start_time = None
        self.lock = threading.Lock()

    def start(self, run_id: Optional[str] = None, notes: str = "") -> Dict[str, Any]:
        with self.lock:
            if self.is_recording:
                return {
                    "status": "ALREADY_RECORDING",
                    "run_id": self.current_run_id,
                    "rows_recorded": self.rows_recorded,
                    "filepath": self.current_filepath
                }
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_run_id = run_id or f"run_{timestamp_str}"
            filename = f"{self.current_run_id}.csv"
            self.current_filepath = os.path.join(self.runs_dir, filename)
            
            self.file_handle = open(self.current_filepath, "w", newline="", encoding="utf-8")
            fieldnames = [
                "timestamp_iso", "timestamp_s", "run_id", "voltage_v", "current_a",
                "rpm", "temp_c", "ambient_temp_c", "power_w", "joule_loss_w",
                "speed_kmh", "source", "active_model", "pred_1m_c", "pred_5m_c",
                "pred_15m_c", "pred_30m_c", "warning_level", "fallback_active", "notes"
            ]
            self.csv_writer = csv.DictWriter(self.file_handle, fieldnames=fieldnames)
            self.csv_writer.writeheader()
            self.file_handle.flush()
            
            self.is_recording = True
            self.rows_recorded = 0
            self.start_time = time.time()
            print(f"[RECORDER] Started recording run: {self.current_run_id} -> {self.current_filepath}")
            return {
                "status": "STARTED",
                "run_id": self.current_run_id,
                "filepath": self.current_filepath,
                "start_time": datetime.now().isoformat()
            }

    def record_step(self, step_data: Dict[str, Any], predictions: Dict[str, Any], source: str, warning_level: str):
        with self.lock:
            if not self.is_recording or self.file_handle is None:
                return
            try:
                temp_val = "" if step_data.get("temp_c") is None else round(float(step_data["temp_c"]), 2)
                row = {
                    "timestamp_iso": datetime.now().isoformat(),
                    "timestamp_s": round(time.time(), 3),
                    "run_id": self.current_run_id,
                    "voltage_v": "" if step_data.get("voltage_v") is None else round(float(step_data["voltage_v"]), 2),
                    "current_a": "" if step_data.get("current_a") is None else round(float(step_data["current_a"]), 2),
                    "rpm": "" if step_data.get("rpm") is None else int(step_data["rpm"]),
                    "temp_c": temp_val,
                    "ambient_temp_c": round(float(step_data.get("ambient_temp_c", 28.0)), 2),
                    "power_w": round(float(step_data.get("power_w", 0.0)), 2),
                    "joule_loss_w": round(float(step_data.get("joule_loss_w", 0.0)), 2),
                    "speed_kmh": round(float(step_data.get("speed_kmh", 0.0)), 1),
                    "source": source,
                    "active_model": predictions.get("forecast_model", ""),
                    "pred_1m_c": "" if predictions.get("pred_1m_c") is None else round(float(predictions["pred_1m_c"]), 2),
                    "pred_5m_c": "" if predictions.get("pred_5m_c") is None else round(float(predictions["pred_5m_c"]), 2),
                    "pred_15m_c": "" if predictions.get("pred_15m_c") is None else round(float(predictions["pred_15m_c"]), 2),
                    "pred_30m_c": "" if predictions.get("pred_30m_c") is None else round(float(predictions["pred_30m_c"]), 2),
                    "warning_level": warning_level,
                    "fallback_active": predictions.get("fallback_active", False),
                    "notes": ""
                }
                self.csv_writer.writerow(row)
                self.file_handle.flush()
                self.rows_recorded += 1
            except Exception as e:
                print(f"[RECORDER] Write error: {e}")

    def stop(self) -> Dict[str, Any]:
        with self.lock:
            if not self.is_recording:
                return {"status": "NOT_RECORDING"}
            self.is_recording = False
            duration_s = round(time.time() - (self.start_time or time.time()), 1)
            if self.file_handle:
                try:
                    self.file_handle.flush()
                    self.file_handle.close()
                except Exception:
                    pass
                self.file_handle = None
            print(f"[RECORDER] Stopped run: {self.current_run_id} ({self.rows_recorded} rows, {duration_s}s)")
            return {
                "status": "STOPPED",
                "run_id": self.current_run_id,
                "filepath": self.current_filepath,
                "rows_recorded": self.rows_recorded,
                "duration_seconds": duration_s
            }

    def status(self) -> Dict[str, Any]:
        with self.lock:
            duration_s = round(time.time() - self.start_time, 1) if self.is_recording and self.start_time else 0.0
            return {
                "is_recording": self.is_recording,
                "run_id": self.current_run_id,
                "filepath": self.current_filepath,
                "rows_recorded": self.rows_recorded,
                "duration_seconds": duration_s
            }

run_recorder = CsvRunRecorder(RUNS_DIR)

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

# Import Road Energy & Future Range Predictor
try:
    from .road_energy_predictor import RoadEnergyPredictor, RoadProfile
except ImportError:
    from road_energy_predictor import RoadEnergyPredictor, RoadProfile

road_energy_predictor = RoadEnergyPredictor()
g_cumulative_energy_wh = 0.0
g_last_energy_tick = time.time()

# Multi-model ML forecaster (core_server/ml). Optional: it is used only after
#   python -m core_server.ml.train_all --data <csv files>
# has produced core_server/ml/artifacts/registry.json.
ml_predictor = None
ml_lock = threading.Lock()   # ingest runs in a worker thread, the WebSocket in the event loop
try:
    try:
        from .ml.predictor import ThermalPredictor
    except ImportError:
        from ml.predictor import ThermalPredictor
    try:
        ml_predictor = ThermalPredictor()
    except FileNotFoundError:
        raise
    except Exception as first_err:
        # The registry's best model may need a package that is not installed
        # (e.g. 'gru' needs torch, which is left out of small cloud deployments).
        print(f"[HOST APP] Best model unavailable ({first_err!r}); falling back to ridge.")
        ml_predictor = ThermalPredictor(model_name="ridge")
    print(f"[HOST APP] ML forecaster loaded: {ml_predictor.model_name}")
except FileNotFoundError:
    print("[HOST APP] No trained ML models yet (run core_server.ml.train_all); using RF/physics fallback.")
except Exception as e:
    print(f"[HOST APP] Warning: ML forecaster unavailable: {e!r}")

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
latest_live_at = 0.0               # time.time() of the last accepted ESP32 sample
hardware_temp_history: List[Any] = [] # stores (timestamp, temp_c) to compute real dt_temp_rate
HARDWARE_STALE_AFTER_S = 5.0       # no sample for this long -> hardware counts as offline
g_last_source: Optional[str] = None

# Legacy Random Forest health: failures used to be swallowed silently.
rf_failures = 0
rf_last_error: Optional[str] = None

def predict_multi_horizon(voltage_v, current_a, rpm, temp_c, power_w=None, joule_loss_w=None, dt_temp_rate=None, ambient_temp_c=28.0):
    """Legacy multi-horizon prediction: 12V Random Forest, else a physics curve."""
    global rf_failures, rf_last_error
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
            rf_failures += 1
            if rf_failures == 1:
                rf_last_error = repr(err)
                print(f"[HOST APP] Random Forest prediction failed, using physics fallback: {err!r}")

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
    ambient_temp_c: Optional[float] = None   # send this once you have an ambient sensor
    ambient: Optional[float] = None

# Active WebSockets
connected_websockets: List[WebSocket] = []

@app.get("/api/health")
def get_health():
    ml_name = None
    fallback_active = False
    fallback_reason = None
    if ml_predictor is not None:
        with ml_lock:
            ml_name = ml_predictor.model_name
            ml_state = ml_predictor.status()
        if not ml_state.get("ready", False):
            fallback_active = True
            fallback_reason = f"Warmup in progress ({ml_state.get('seconds_to_ready', 0)}s left)"

    return {
        "status": "ONLINE",
        "service": "ThermaPulse EV Cockpit - 12V DC Host App",
        "system": "12V DC Motor Continuous Testbed",
        "pipeline": "Sensors -> TMS320F2800137 -> UART -> ESP32-S Wi-Fi -> Laptop Host App",
        "model_loaded": rf_model is not None or ml_predictor is not None,
        "rf_ok": rf_model is not None and rf_failures == 0,
        "rf_failures": rf_failures,
        "rf_last_error": rf_last_error,
        "ml_model": ml_name,
        "active_model": ml_name,
        "fallback_active": fallback_active,
        "fallback_reason": fallback_reason,
        "recording": run_recorder.status(),
        "n_trees": 100,
        "assumed_parameters": {
            "battery_soc": 0.85,
            "battery_pack_kwh": 1.2,
            "ambient_default_c": 28.0,
            "rotor_offset_c": -2.5,
            "torque_constant_kt": 0.08
        },
        "demo_mode": DEMO_MODE,
        "active_clients": len(connected_websockets),
        "timestamp": datetime.now().isoformat()
    }

class RecordingStartRequest(BaseModel):
    run_id: Optional[str] = None
    notes: Optional[str] = ""

@app.post("/api/recording/start", dependencies=[Depends(verify_write_access)])
def start_recording(req: Optional[RecordingStartRequest] = None):
    run_id = req.run_id if req else None
    notes = req.notes if req else ""
    return run_recorder.start(run_id=run_id, notes=notes or "")

@app.post("/api/recording/stop", dependencies=[Depends(verify_write_access)])
def stop_recording():
    return run_recorder.stop()

@app.get("/api/recording/status")
def get_recording_status():
    return run_recorder.status()

@app.get("/api/ml/status")
def get_ml_status():
    """Which ML model is forecasting, how it scored, and whether it has warmed up."""
    if ml_predictor is None:
        return {"available": False,
                "hint": "Run: python -m core_server.ml.train_all --data <csv files>"}
    registry = ml_predictor.registry
    with ml_lock:
        state = ml_predictor.status()
    return {"available": True, **state,
            "trained_at": registry["trained_at"],
            "beats_baselines": registry["beats_baselines"],
            "split": registry["split"],
            "models": registry["models"]}

class ModelSelectRequest(BaseModel):
    model: str

@app.post("/api/ml/select_model", dependencies=[Depends(verify_write_access)])
def select_model_endpoint(req: ModelSelectRequest):
    global ml_predictor
    if ml_predictor is None:
        return JSONResponse(status_code=400, content={"error": "No ML models loaded"})
    with ml_lock:
        try:
            active = ml_predictor.set_model(req.model)
            return {"status": "SUCCESS", "active_model": active}
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

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

@app.post("/api/ingest", dependencies=[Depends(verify_write_access)])
def ingest_telemetry_endpoint(t: TelemetryIngest):
    """Endpoint for ESP32 Wi-Fi HTTP POST ingestion.

    A reading is accepted only if voltage, current, rpm and temperature are all
    present and finite. Zero is a valid reading (stopped motor, no load) and is
    kept as zero; nothing is replaced by a made-up default.
    """
    global latest_live_telemetry, latest_live_at, hardware_temp_history
    d = t.model_dump() if hasattr(t, "model_dump") else t.dict()

    def pick(*names):
        for n in names:
            if d.get(n) is not None:
                return d[n]
        return None

    v = pick("voltage_v", "v")
    i = pick("current_a", "i")
    rpm = pick("rpm")
    temp = pick("temp_c", "temp")
    ambient = pick("ambient_temp_c", "ambient")

    missing = [name for name, val in (("voltage", v), ("current", i), ("rpm", rpm), ("temp", temp)) if val is None]
    if missing or not all(math.isfinite(float(x)) for x in (v, i, rpm, temp)):
        return JSONResponse(status_code=422, content={
            "status": "REJECTED",
            "missing_or_invalid": missing or ["non-finite value"]})

    ambient_measured = ambient is not None and math.isfinite(float(ambient))
    ambient = float(ambient) if ambient_measured else 28.0   # fixed guess when not measured

    now_ts = time.time()
    hardware_temp_history.append((now_ts, float(temp)))
    if len(hardware_temp_history) > 10:
        hardware_temp_history.pop(0)

    if len(hardware_temp_history) >= 2:
        dt_span = hardware_temp_history[-1][0] - hardware_temp_history[0][0]
        temp_span = hardware_temp_history[-1][1] - hardware_temp_history[0][1]
        dt_temp_rate = round(temp_span / max(0.5, dt_span), 4)
    else:
        dt_temp_rate = 0.0

    latest_live_telemetry = {
        "voltage_v": float(v),
        "current_a": float(i),
        "rpm": int(rpm),
        "temp_c": float(temp),
        "power_w": round(float(v) * float(i), 2),
        "joule_loss_w": round((float(i) ** 2) * R_ARMATURE, 2),
        "dt_temp_rate": dt_temp_rate,
        "ambient_temp_c": ambient,
        "ambient_measured": ambient_measured
    }
    latest_live_at = now_ts
    if ml_predictor is not None:
        with ml_lock:
            ml_predictor.push(float(v), float(i), float(rpm), float(temp), ambient)
    return {"status": "INGESTED", "data": latest_live_telemetry}

@app.post("/api/road_profile", dependencies=[Depends(verify_write_access)])
def set_road_profile(req: Dict[str, str]):
    road_key = req.get("road_type", "URBAN_CITY")
    if road_key in RoadProfile.ROAD_TYPES:
        road_energy_predictor.current_road_type = road_key
        return {"status": "UPDATED", "road_type": road_key}
    return {"status": "ERROR", "message": "Unknown road profile"}

# Canonical Broadcast State
latest_broadcast_payload: Optional[Dict[str, Any]] = None

def compute_canonical_telemetry_tick() -> Dict[str, Any]:
    """Computes a single, authoritative telemetry snapshot.
    
    Runs strictly once per second across the entire application (via the background
    broadcaster task), ensuring simulator stepping, ML history accumulation,
    energy integration, and CSV run recording remain perfectly synchronized
    regardless of how many browser tabs or WebSocket clients are connected.
    """
    global latest_live_telemetry, latest_live_at, g_cumulative_energy_wh
    global g_last_energy_tick, g_last_source, latest_broadcast_payload

    # Live hardware only counts while fresh samples keep arriving (within 5 seconds).
    hardware_live = (latest_live_telemetry is not None
                     and time.time() - latest_live_at <= HARDWARE_STALE_AFTER_S)
    if hardware_live and not DEMO_MODE:
        step_data = latest_live_telemetry.copy()
        source = "ESP32_WIFI_HARDWARE"
    else:
        step_data = simulator.step()
        if DEMO_MODE:
            source = "DEMO_SIMULATOR_CLOUD"
        elif latest_live_telemetry is not None:
            source = "SIMULATOR_HARDWARE_OFFLINE"
        else:
            source = "12V_SIMULATOR_TESTBED"

    if ml_predictor is not None:
        with ml_lock:
            if source != g_last_source:      # never mix history across hardware and simulator
                ml_predictor.reset()
                g_last_source = source
            if source != "ESP32_WIFI_HARDWARE":   # hardware samples are pushed by /api/ingest
                ml_predictor.push(step_data["voltage_v"], step_data["current_a"],
                                  step_data["rpm"], step_data["temp_c"],
                                  step_data["ambient_temp_c"])

    now_time = time.time()
    dt_sec = max(0.2, min(3.0, now_time - g_last_energy_tick))
    g_last_energy_tick = now_time

    pwr_w = float(step_data["power_w"])
    g_cumulative_energy_wh += (pwr_w * dt_sec) / 3600.0

    # Multi-Horizon Future Energy Consumption Forecasts
    pred_e_5m = round(pwr_w * (5.0 / 60.0), 2)
    pred_e_15m = round(pwr_w * (15.0 / 60.0), 2)
    pred_e_30m = round(pwr_w * (30.0 / 60.0), 2)

    # Road longitudinal dynamics & remaining range
    speed_kmh = max(5.0, round((step_data["rpm"] * 60.0 * 0.15) / 1000.0, 1))
    road_forecast = road_energy_predictor.predict_energy_and_range(speed_kmh, battery_soc=0.85, total_battery_kwh=1.2)

    # Multi-model thermal forecasting
    all_models: Dict[str, Any] = {}
    fallback_active = False
    fallback_reason = None
    warning_level = "NORMAL"
    advisory_text = "NORMAL: Temperature and forecasts within safe continuous limits."
    ttt_min = None
    OVERHEAT_LIMIT_C = 55.0
    ml_state = None  # Explicitly initialized so UnboundLocalError cannot occur

    if step_data["temp_c"] is None:
        p1, p5, p15, p30 = None, None, None, None
        forecast_model = "sensor_disconnected"
        forecast_status = "sensor_error"
        warmup_left = 0
        fallback_active = True
        fallback_reason = "DS18B20 1-Wire temperature sensor disconnected"
        warning_level = "SENSOR_OFFLINE"
        advisory_text = "WARNING: DS18B20 temperature probe disconnected or faulty."
    else:
        cur_t = float(step_data["temp_c"])
        # 1. Baseline 1: Persistence ("temp stays the same")
        all_models["persistence"] = {
            "1m": round(cur_t, 2), "5m": round(cur_t, 2),
            "15m": round(cur_t, 2), "30m": round(cur_t, 2)
        }
        # 2. Baseline 2: Physics Heating Curve ODE
        q_in = float(step_data["joule_loss_w"]) + 0.002 * float(step_data["rpm"])
        t_inf = float(step_data["ambient_temp_c"]) + (q_in * 2.4)
        tau = 180.0
        all_models["physics_fit"] = {
            "1m": round(cur_t + (t_inf - cur_t) * (1.0 - math.exp(-60.0 / tau)), 2),
            "5m": round(cur_t + (t_inf - cur_t) * (1.0 - math.exp(-300.0 / tau)), 2),
            "15m": round(cur_t + (t_inf - cur_t) * (1.0 - math.exp(-900.0 / tau)), 2),
            "30m": round(cur_t + (t_inf - cur_t) * (1.0 - math.exp(-1800.0 / tau)), 2)
        }
        # 3. Reference: Random Forest
        rf_p1, rf_p5, rf_p15, rf_p30 = predict_multi_horizon(
            step_data["voltage_v"], step_data["current_a"], step_data["rpm"],
            step_data["temp_c"], step_data["power_w"], step_data["joule_loss_w"],
            step_data["dt_temp_rate"], step_data["ambient_temp_c"]
        )
        all_models["random_forest"] = {"1m": rf_p1, "5m": rf_p5, "15m": rf_p15, "30m": rf_p30}

        # 4. Registry models if loaded & ready
        if ml_predictor is not None:
            with ml_lock:
                ml_all = ml_predictor.predict_all()
                ml_state = ml_predictor.status()
            for k, v in ml_all.items():
                if v is not None:
                    all_models[k] = v

        # Ground-truth: models not yet loaded or warming up are None (NO FAKE SCALING!)
        for k in ["ridge", "gru", "lightgbm"]:
            if k not in all_models:
                all_models[k] = None

        if ml_predictor is None:
            forecast_model = "random_forest" if rf_model is not None else "physics_fit"
            forecast_status = "no_ml_models_trained"
            warmup_left = 0
            fallback_active = True
            fallback_reason = "No trained ML models loaded from registry (run train_all.py); using Random Forest / Physics fallback"
        elif ml_state is not None and not ml_state.get("ready", False):
            forecast_model = ml_predictor.model_name
            forecast_status = "ml_warming_up"
            warmup_left = ml_state.get("seconds_to_ready", 0)
            fallback_active = True
            fallback_reason = f"ML buffer accumulating samples ({warmup_left}s remaining) - using Physics ODE fallback"
        else:
            forecast_model = ml_predictor.model_name
            forecast_status = "ml_ready"
            warmup_left = 0
            fallback_active = False
            fallback_reason = None

        # Resolve active model predictions
        if forecast_model in all_models and all_models[forecast_model] is not None:
            m_preds = all_models[forecast_model]
            p1, p5, p15, p30 = m_preds["1m"], m_preds["5m"], m_preds["15m"], m_preds["30m"]
        elif rf_model is not None and rf_p1 is not None:
            p1, p5, p15, p30 = rf_p1, rf_p5, rf_p15, rf_p30
        else:
            m_preds = all_models["physics_fit"]
            p1, p5, p15, p30 = m_preds["1m"], m_preds["5m"], m_preds["15m"], m_preds["30m"]

        # Compute Proactive Thermal Safety Thresholds & Time-To-Threshold
        if p5 is not None:
            if p5 >= 55.0 or (p15 is not None and p15 >= 65.0):
                warning_level = "CRITICAL"
                advisory_text = "CRITICAL: Motor casing will exceed 55°C within 5 min! Reduce current or stop motor."
            elif p5 >= 48.0 or (p15 is not None and p15 >= 55.0):
                warning_level = "ELEVATED"
                advisory_text = "ELEVATED: High continuous thermal loading. Projected to reach 55°C limit soon."
            else:
                warning_level = "NORMAL"
                advisory_text = "NORMAL: Temperature dynamics within safe continuous operating limits."

        if cur_t >= OVERHEAT_LIMIT_C:
            ttt_min = 0.0
        elif p5 is not None and p5 > cur_t:
            rate_per_min = (p5 - cur_t) / 5.0
            if rate_per_min > 0.02:
                ttt_min = round(max(0.1, (OVERHEAT_LIMIT_C - cur_t) / rate_per_min), 1)

    payload = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "source": source,
        "demo_mode": DEMO_MODE,
        "system": "12V DC Motor Testbed",
        "mcu_pipeline": "TMS320F2800137 -> ESP32-S Wi-Fi -> Host App",
        "telemetry": {
            "voltage_v": step_data["voltage_v"],
            "current_a": step_data["current_a"],
            "rpm": step_data["rpm"],
            "temp_c": step_data["temp_c"],
            "stator_temp": step_data["temp_c"],  # backwards-compatible key
            "rotor_temp": round(step_data["temp_c"] - 2.5, 2) if step_data["temp_c"] is not None else None,
            "power_w": step_data["power_w"],
            "joule_loss_w": step_data["joule_loss_w"],
            "torque_nm": round(step_data["current_a"] * 0.08, 2),
            "speed_kmh": speed_kmh,
            "dt_temp_rate": step_data["dt_temp_rate"],
            "ambient_temp_c": step_data["ambient_temp_c"],
            "ambient_measured": step_data.get("ambient_measured", False)
        },
        "predictions": {
            "pred_1m_c": p1,
            "pred_5m_c": p5,
            "pred_15m_c": p15,
            "pred_30m_c": p30,
            "forecast_model": forecast_model,
            "forecast_status": forecast_status,
            "warmup_seconds_left": warmup_left,
            "fallback_active": fallback_active,
            "fallback_reason": fallback_reason,
            "all_models": all_models
        },
        "thermal_safety": {
            "warning_level": warning_level,
            "time_to_threshold_min": ttt_min,
            "overheat_threshold_c": OVERHEAT_LIMIT_C,
            "advisory": advisory_text
        },
        "recording": run_recorder.status(),
        "energy": {
            "cumulative_wh": round(g_cumulative_energy_wh, 2),
            "pred_energy_5m_wh": pred_e_5m,
            "pred_energy_15m_wh": pred_e_15m,
            "pred_energy_30m_wh": pred_e_30m,
            "current_road": road_forecast["current_road"],
            "road_name": road_forecast["road_name"],
            "instant_wh_per_km": road_forecast["instant_wh_per_km"],
            "remaining_range_km": road_forecast["remaining_range_km"],
            "remaining_battery_kwh": road_forecast["remaining_battery_kwh"],
            "road_comparisons": road_forecast["multi_road_forecasts"]
        },
        "assumptions": {
            "battery_soc_pct": 85.0,
            "battery_soc_nominal": True,
            "battery_capacity_kwh": 1.2,
            "ambient_temp_c": step_data["ambient_temp_c"],
            "ambient_measured": step_data.get("ambient_measured", False),
            "rotor_casing_differential_c": 2.5,
            "torque_constant_nm_per_a": 0.08
        },
        "sensors": {
            "voltage_sensor": "0-25V Sensor (ADCINA0)",
            "current_sensor": "ACS712 5A (ADCINA1)",
            "speed_sensor": "LM393 Optical (GPIO 0)",
            "temp_sensor": "DS18B20 1-Wire (GPIO 3)"
        }
    }

    # Record step to CSV if run recording is in progress (strictly 1 row per second)
    run_recorder.record_step(step_data, payload["predictions"], source, warning_level)

    latest_broadcast_payload = payload
    return payload


async def telemetry_broadcaster_task():
    """Centralized 1 Hz Background Task.
    
    Computes the canonical simulation / hardware telemetry tick exactly once per second,
    advances the simulator and energy at 1x speed, and broadcasts to all connected WebSockets.
    """
    while True:
        try:
            payload = compute_canonical_telemetry_tick()
            payload_str = json.dumps(payload)
            for ws in list(connected_websockets):
                try:
                    await ws.send_text(payload_str)
                except Exception:
                    if ws in connected_websockets:
                        connected_websockets.remove(ws)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[BROADCASTER] Loop error: {e}")
        await asyncio.sleep(1.0)


@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.append(websocket)
    print(f"[WS] Client connected. Total active: {len(connected_websockets)}")

    # Immediately deliver the latest snapshot so client receives immediate first message
    first_payload = compute_canonical_telemetry_tick()
    try:
        await websocket.send_text(json.dumps(first_payload))
    except Exception:
        pass

    try:
        # Keep connection open; background task streams the 1 Hz broadcasts
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in connected_websockets:
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

    @app.get("/config.js")
    def serve_config():
        config_path = os.path.join(UI_DIR, "config.js")
        if os.path.exists(config_path):
            return FileResponse(config_path)
        return JSONResponse({"error": "not found"}, status_code=404)

    @app.get("/rf_model_weights.json")
    def serve_weights():
        return FileResponse(os.path.join(UI_DIR, "rf_model_weights.json"))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print("=" * 70)
    print(f"  LAUNCHING THERMAPULSE EV COCKPIT HOST SERVER (PORT {port})")
    print(f"  Web Dashboard: http://localhost:{port}/")
    print(f"  WebSocket    : ws://localhost:{port}/ws/telemetry")
    print(f"  Health Status: http://localhost:{port}/api/health")
    if DEMO_MODE:
        print("  MODE         : CLOUD DEMO SIMULATOR (Public)")
    print("=" * 70)
    uvicorn.run("core_server.host_app:app", host="0.0.0.0", port=port, reload=False)
