"""
===============================================================================
Project: 48V EV BLDC Predictive Dashboard - Laptop Serial Bridge
File: serial_laptop_bridge.py
Description: Reads real-time $EV_48V telemetry packets from TI C2000 LaunchPad
             over USB Virtual COM Port and streams to the Web Dashboard.
===============================================================================
"""

import sys
import time
import json
import asyncio
try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="48V BLDC Laptop Telemetry Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

connected_websockets = set()
latest_telemetry_frame = {}


def find_ti_c2000_port():
    """Auto-detects TI XDS110 Virtual COM Port."""
    if not serial:
        return None
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if "XDS110" in port.description or "Texas Instruments" in port.description:
            return port.device
    # Fallback to first available port if found
    return ports[0].device if ports else None


async def serial_reader_task():
    """Background task to continuously read from USB Serial COM port."""
    global latest_telemetry_frame
    com_port = find_ti_c2000_port()
    print(f"[Serial Bridge] Target USB Port: {com_port or 'Simulation Mode (Auto-Fallback)'}")

    ser = None
    if com_port and serial:
        try:
            ser = serial.Serial(com_port, 115200, timeout=0.5)
            print(f"[Serial Bridge] Connected to TI C2000 on {com_port} @ 115200 bps")
        except Exception as e:
            print(f"[Serial Bridge] Could not open {com_port}: {e}. Falling back to simulation.")

    while True:
        try:
            if ser and ser.is_open:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line.startswith("$EV_48V") and line.endswith("*"):
                    parts = line[1:-1].split(',')
                    # $EV_48V,Time,StatorT,RotorT,Idc,Vdc,RPM,Pred1m,Pred5m,Pred15m,SoC,WhKm,Range,Derate
                    latest_telemetry_frame = {
                        "timestamp_ms": int(parts[1]),
                        "stator_temp_c": float(parts[2]),
                        "rotor_magnet_temp_c": float(parts[3]),
                        "dc_bus_current_a": float(parts[4]),
                        "dc_bus_voltage_v": float(parts[5]),
                        "rotor_speed_rpm": float(parts[6]),
                        "pred_stator_1m_c": float(parts[7]),
                        "pred_stator_5m_c": float(parts[8]),
                        "pred_stator_15m_c": float(parts[9]),
                        "battery_soc_pct": float(parts[10]),
                        "energy_rate_wh_per_km": float(parts[11]),
                        "remaining_range_km": float(parts[12]),
                        "derate_active": int(parts[13])
                    }
                    # Broadcast to Laptop Browser
                    if connected_websockets:
                        msg = json.dumps(latest_telemetry_frame)
                        dead = set()
                        for ws in connected_websockets:
                            try:
                                await ws.send_text(msg)
                            except Exception:
                                dead.add(ws)
                        connected_websockets.difference_update(dead)
            await asyncio.sleep(0.05)
        except Exception as e:
            await asyncio.sleep(0.1)


@app.on_event("startup")
async def on_startup():
    asyncio.create_task(serial_reader_task())


@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_websockets.remove(websocket)


if __name__ == "__main__":
    uvicorn.run("core_server.serial_laptop_bridge:app", host="127.0.0.1", port=8000)
