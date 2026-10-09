"""
============================================================================
Aura EV - Laptop Terminal Live Monitor for Thonny IDE
Connects to ws://localhost:8000/ws/telemetry and prints all metrics:
Temp, Voltage, Current, RPM, Power, Torque, Energy, and Predictions.
============================================================================
"""
import asyncio
import json
import websockets
from datetime import datetime

WS_URL = "ws://localhost:8000/ws/telemetry"

async def monitor():
    print("=" * 105)
    print("      AURA EV 12V DC MOTOR REAL-TIME TERMINAL MONITOR (THONNY IDE)")
    print(f"      Connecting to: {WS_URL}")
    print("=" * 105)

    header = f"{'TIME':<8} | {'TEMP':<8} | {'VOLT':<8} | {'CURR':<7} | {'RPM':<6} | {'POWER':<7} | {'TORQUE':<7} | {'ENERGY':<8} | {'PRED +1m':<9} | {'PRED +5m':<9}"
    print(header)
    print("-" * 105)

    while True:
        try:
            async with websockets.connect(WS_URL) as ws:
                print(f"[ONLINE] Connected! Receiving live telemetry...\n")
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)

                    t = data.get("telemetry", {})
                    p = data.get("predictions", {})
                    e = data.get("energy", {})

                    time_now = datetime.now().strftime("%H:%M:%S")
                    temp = t.get("temp_c", 0.0)
                    volt = t.get("voltage_v", 0.0)
                    curr = t.get("current_a", 0.0)
                    rpm  = t.get("rpm", 0)
                    pwr  = t.get("power_w", volt * curr)
                    trq  = t.get("torque_nm", curr * 0.08)

                    energy_wh = e.get("cumulative_wh", 0.0)
                    p1m  = p.get("pred_1m_c", 0.0)
                    p5m  = p.get("pred_5m_c", 0.0)

                    # Print formatted line in Thonny console
                    print(f"{time_now:<8} | {temp:>6.1f}°C | {volt:>6.2f}V | {curr:>5.2f}A | {rpm:>6d} | {pwr:>5.1f}W | {trq:>5.2f}Nm | {energy_wh:>6.2f}Wh | {p1m:>7.1f}°C | {p5m:>7.1f}°C")

        except Exception as err:
            print(f"[RECONNECTING] Host app offline or reconnecting ({err})...")
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(monitor())
