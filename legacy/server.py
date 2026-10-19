"""
===============================================================================
Project: EV Dashboard & Predictive Thermal & Energy Management System
File: server.py
Description: FastAPI & WebSocket Telemetry Server with Live TI C2000 Serial
             Driver, Dual Predictive Thermal Engines (Motor + Battery),
             and Road Energy Forecaster.
===============================================================================
"""

import asyncio
import json
import time
import math
from typing import Set, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from .c2000_interface import C2000VirtualHILSimulator, C2000PacketParser
from .battery_thermal_predictor import BatteryThermalPredictor
from .road_energy_predictor import RoadEnergyPredictor

app = FastAPI(title="EV Dashboard & TI C2000 Predictive Telemetry Server")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connected WebSocket Clients
connected_clients: Set[WebSocket] = set()

# Unified Predictive State Engines
motor_hil = C2000VirtualHILSimulator()
battery_predictor = BatteryThermalPredictor()
road_predictor = RoadEnergyPredictor()

# Telemetry streaming background task
stream_task: Optional[asyncio.Task] = None
is_streaming = True
serial_port_name: Optional[str] = None


async def telemetry_broadcaster():
    """10 Hz Telemetry broadcast loop (100 ms)."""
    while is_streaming:
        try:
            # 1. Step Motor Thermal & Kinematics Plant
            motor_data = motor_hil.step(dt=0.1)

            # 2. Step Battery Pack Thermal & SoC Predictor
            # Battery current drawn by inverter based on motor electrical power
            batt_current_a = (motor_data["motor_dynamics"]["electrical_power_kw"] * 1000.0) / 48.0
            batt_data = battery_predictor.step(current_draw_a=batt_current_a, dt=0.1)

            # 3. Step Multi-Road Energy & Range Predictor
            road_data = road_predictor.predict_energy_and_range(
                current_speed_kmh=motor_data["motor_dynamics"]["speed_kmh"],
                battery_soc=battery_predictor.current_soc,
                total_battery_kwh=2.4
            )

            # 4. Assemble Unified Dashboard Payload
            unified_payload = {
                "timestamp_ms": motor_data["timestamp_ms"],
                "hardware_source": "TI TMS320F2800137 (HIL Simulation / COM)",
                "scenario": motor_data["scenario"],
                "motor_dynamics": motor_data["motor_dynamics"],
                "motor_thermal_live": motor_data["thermal_live"],
                "motor_losses": motor_data["losses_watts"],
                "motor_predictions": motor_data["predictions"],
                "battery_telemetry": batt_data,
                "road_energy_forecast": road_data
            }

            # 5. Broadcast to all active WebSocket clients
            if connected_clients:
                json_str = json.dumps(unified_payload)
                dead_clients = set()
                for client in connected_clients:
                    try:
                        await client.send_text(json_str)
                    except Exception:
                        dead_clients.add(client)
                connected_clients.difference_update(dead_clients)

        except Exception as e:
            print(f"[Telemetry Broadcast Error]: {e}")

        await asyncio.sleep(0.10) # 10 Hz (100 ms)


@app.on_event("startup")
async def on_startup():
    global stream_task
    stream_task = asyncio.create_task(telemetry_broadcaster())
    print("=== EV Predictive Telemetry Server Started on Port 8000 ===")


@app.on_event("shutdown")
async def on_shutdown():
    global is_streaming
    is_streaming = False
    if stream_task:
        stream_task.cancel()


@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    print(f"[Client Connected] Active clients: {len(connected_clients)}")

    try:
        while True:
            # Receive commands from dashboard (e.g. switch road profile or ambient temp)
            data_text = await websocket.receive_text()
            cmd = json.loads(data_text)
            
            if "set_scenario" in cmd:
                motor_hil.set_scenario(cmd["set_scenario"])
                # Also synchronize road predictor
                scen_to_road = {
                    "ECO_CITY": "URBAN_CITY",
                    "HIGHWAY_CRUISE": "HIGHWAY_EXPRESS",
                    "MOUNTAIN_CLIMB": "MOUNTAIN_GRADE",
                    "AGGRESSIVE_TRACK": "HIGHWAY_EXPRESS",
                    "COOLING_DEGRADED": "MOUNTAIN_GRADE"
                }
                if cmd["set_scenario"] in scen_to_road:
                    road_predictor.current_road_type = scen_to_road[cmd["set_scenario"]]

            if "set_ambient_temp" in cmd:
                motor_hil.plant.ambient_temp_C = float(cmd["set_ambient_temp"])
                battery_predictor.ambient_temp_c = float(cmd["set_ambient_temp"])

    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        print(f"[Client Disconnected] Remaining: {len(connected_clients)}")


@app.get("/api/health")
def health_check():
    return {
        "status": "ONLINE",
        "target_mcu": "TI TMS320F2800137",
        "active_clients": len(connected_clients),
        "current_scenario": motor_hil.current_scenario
    }


if __name__ == "__main__":
    uvicorn.run("core_server.server:app", host="0.0.0.0", port=8000, reload=False)
