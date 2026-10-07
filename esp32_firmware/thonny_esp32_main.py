"""
============================================================================
Aura EV - ESP32-S MicroPython Bridge for Thonny IDE
Receives UART from TMS320F2800137 LaunchPad, computes power, and prints.
============================================================================
"""
from machine import UART, Pin
import network
import ujson
import time

# 1. Configure UART2 for C2000 LaunchPad
# RX2 = GPIO 16 (C2000 GPIO 29 TX), TX2 = GPIO 17 (C2000 GPIO 28 RX)
uart = UART(2, baudrate=115200, rx=16, tx=17, timeout=200)

print("\n" + "=" * 70)
print("   AURA EV ESP32-S MICROPYTHON SENSOR BRIDGE (THONNY IDE)")
print("   Listening on UART2: RX=GPIO16, TX=GPIO17 (115200 baud)")
print("=" * 70)
print(f"{'TIME':<8} | {'TEMP (°C)':<10} | {'VOLT (V)':<9} | {'CURR (A)':<9} | {'RPM':<8} | {'POWER (W)':<9}")
print("-" * 70)

while True:
    if uart.any():
        try:
            raw_line = uart.readline().decode('utf-8').strip()
            if raw_line.startswith("{") and raw_line.endswith("}"):
                data = ujson.loads(raw_line)
                v = float(data.get("v", 12.10))
                i = float(data.get("i", 2.20))
                rpm = int(data.get("rpm", 2150))
                temp = float(data.get("temp", 34.5))
                power = round(v * i, 1)

                timestamp = time.localtime()
                time_str = "{:02d}:{:02d}:{:02d}".format(timestamp[3], timestamp[4], timestamp[5])

                # Print clean, formatted output in Thonny Terminal
                print(f"{time_str:<8} | {temp:>8.1f} °C | {v:>7.2f} V | {i:>7.2f} A | {rpm:>6d} | {power:>7.1f} W")
        except Exception:
            pass
    time.sleep(0.05)
