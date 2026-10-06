# Aura EV Digital Cockpit & 12V DC Motor Continuous Testbed Predictive Thermal Management System

An automotive digital cockpit and real-time predictive thermal management system for an Electric Vehicle / Motor testbed powered by a **12V DC Motor (Continuous Run)**, featuring **TMS320F2800137 LaunchPad Primary Acquisition**, **ESP32-S (38-Pin) Wi-Fi Telemetry Streaming**, and a **100-Tree Random Forest Multi-Horizon AI Thermal Regressor** (+1 min, +5 min, +15 min, +30 min).

**GitHub Repository:** [https://github.com/jonce9751961231/Ev_Dashboard](https://github.com/jonce9751961231/Ev_Dashboard)

---

## 1. System Pipeline Architecture

```text
 ┌──────────────────────┐
 │   12V DC MOTOR &     │
 │    THE 4 SENSORS     │
 └──────────┬───────────┘
            │ Physical Sensor Signals (0-2.4V Analog, Pulses, 1-Wire)
            ▼
 ┌──────────────────────┐
 │   TMS320F2800137     │  • Primary Real-Time Sensor Acquisition
 │      LAUNCHPAD       │  • ADCINA0 (Volt), ADCINA1 (Curr), GPIO 0 (RPM), GPIO 3 (Temp)
 └──────────┬───────────┘
            │ High-Speed UART (115200 bps): GPIO 29 (TX) ──► GPIO 16 (RX2)
            ▼
 ┌──────────────────────┐
 │   ESP32-S (38-PIN)   │  • Microcontroller Wi-Fi Telemetry Bridge
 │      DEV BOARD       │  • Transmits JSON Packets over TCP / WebSocket / HTTP
 └──────────┬───────────┘
            │ Wireless Wi-Fi Link (WebSocket ws://localhost:8000/ws/telemetry)
            ▼
 ┌──────────────────────┐
 │   LAPTOP HOST APP    │  • FastAPI + WebSocket Host Server (Port 8000)
 │   & AI PREDICTOR     │  • 100-Tree Random Forest Multi-Horizon Thermal Forecast
 └──────────┬───────────┘
            │ Real-time in-browser rendering (10 Hz)
            ▼
 ┌──────────────────────┐
 │   AUTOMOTIVE WEB     │  • Glassmorphic Instrument Cluster
 │      COCKPIT         │  • Live Dials: 12V Bus, ACS712 Current, LM393 Speed, DS18B20 Temp
 └──────────────────────┘
```

---

## 2. Hardware Bill of Materials (BOM)

| Component / Sensor | Model / Specification | Purpose in System | Connected Pin |
| :--- | :--- | :--- | :--- |
| **Actuator** | 12V DC Motor | Constant continuous physical load (No MOSFET switch) | Direct 12V Loop via ACS712 |
| **Microcontroller 1** | TI TMS320F2800137 LaunchPad | Primary high-speed sensor acquisition & UART stream | LAUNCHXL-F2800137 |
| **Microcontroller 2** | ESP32-S 38-Pin Dev Board | Wi-Fi Telemetry bridge & JSON streamer to Laptop | NodeMCU ESP32-S |
| **Voltage Sensor** | Standard 0–25V Sensor Module | Measures 12V DC Link (5:1 divider, 12V $\rightarrow$ 2.4V) | C2000 **ADCINA0** (J3-27) |
| **Current Sensor** | Allegro ACS712 (5A Variant) | Measures armature current (185 mV/A, 2.5V zero offset) | C2000 **ADCINA1** (J3-28) |
| **Speed Sensor** | LM393 Optical Sensor Module | Slotted photo-interrupter with 20-slot disc on motor shaft | C2000 **GPIO 0** (J2-13, XINT1) |
| **Temperature Sensor**| Dallas DS18B20 Waterproof Probe| Surface casing temperature probe (with 4.7kΩ pull-up) | C2000 **GPIO 3** (J1-6) |

---

## 3. Complete Wire-by-Wire Wiring Schematic

### Section A: 12V Motor High-Current Loop (Direct Constant Run)
* **Wire W-01 (🔴 Thick Red):** 12V Power Supply (+) $\longrightarrow$ ACS712 Screw Terminal 1 (`IP+`)
* **Wire W-02 (🔴 Thick Red):** ACS712 Screw Terminal 2 (`IP-`) $\longrightarrow$ 12V DC Motor (+) Terminal
* **Wire W-03 (⚫ Thick Black):** 12V DC Motor (–) Terminal $\longrightarrow$ 12V Power Supply (–) GND
* **Wire W-04 (🔴 Red):** 12V Power Supply (+) $\longrightarrow$ 0–25V Voltage Sensor `VCC` Screw Terminal
* **Wire W-05 (⚫ Black):** 12V Power Supply (–) $\longrightarrow$ 0–25V Voltage Sensor `GND` Screw Terminal
* **Wire W-06 (⚫ Black):** 12V Power Supply (–) $\longrightarrow$ C2000 LaunchPad **GND** (Header J1 Pin 22) *(Mandatory Common Ground)*

### Section B: The 4 Sensors $\longrightarrow$ TMS320F2800137 LaunchPad
* **Wire W-07 (🟡 Yellow):** Voltage Sensor `S` (Signal) $\longrightarrow$ C2000 **ADCINA0** (Header J3 Pin 27)
* **Wire W-08 (⚫ Black):** Voltage Sensor `–` (Minus) $\longrightarrow$ C2000 **GND** (Header J1 Pin 22)
* **Wire W-09 (🔴 Red):** C2000 **5.0V** (Header J1 Pin 21) $\longrightarrow$ ACS712 `VCC`
* **Wire W-10 (⚫ Black):** ACS712 `GND` $\longrightarrow$ C2000 **GND** (Header J1 Pin 22)
* **Wire W-11 (🔵 Blue):** ACS712 `OUT` $\longrightarrow$ C2000 **ADCINA1** (Header J3 Pin 28)
* **Wire W-12 (🔴 Red):** C2000 **3.3V** (Header J1 Pin 1) $\longrightarrow$ LM393 Speed `VCC`
* **Wire W-13 (⚫ Black):** LM393 Speed `GND` $\longrightarrow$ C2000 **GND** (Header J1 Pin 22)
* **Wire W-14 (🟠 Orange):** LM393 Speed `D0` $\longrightarrow$ C2000 **GPIO 0** (Header J2 Pin 13, External Interrupt `XINT1`)
* **Wire W-15 (🔴 Red):** C2000 **3.3V** (Header J1 Pin 1) $\longrightarrow$ DS18B20 `VCC` (Red Wire)
* **Wire W-16 (⚫ Black):** DS18B20 `GND` (Black Wire) $\longrightarrow$ C2000 **GND** (Header J1 Pin 22)
* **Wire W-17 (🟡 Yellow):** DS18B20 `DATA` (Yellow Wire) $\longrightarrow$ C2000 **GPIO 3** (Header J1 Pin 6)
* **Component R-01 (🟤 4.7 kΩ Resistor):** Connected between DS18B20 Yellow (DATA) and Red (3.3V) lines

### Section C: TMS320F2800137 LaunchPad $\longrightarrow$ ESP32-S (38-Pin) UART Link
* **Wire W-18 (🟢 Green):** C2000 **GPIO 29 (SCIA_TX)** (Header J1 Pin 4) $\longrightarrow$ ESP32-S **GPIO 16 (RX2)**
* **Wire W-19 (🔵 Blue):** ESP32-S **GPIO 17 (TX2)** $\longrightarrow$ C2000 **GPIO 28 (SCIA_RX)** (Header J1 Pin 3)
* **Wire W-20 (⚫ Black):** C2000 **GND** (Header J1 Pin 22) $\longrightarrow$ ESP32-S **GND**

---

## 4. Random Forest AI Model Performance

A 100-Tree Multi-Output Random Forest Regressor was trained on the continuous 12V DC motor thermodynamic dataset (12,000 samples) taking into account Joule heating ($I^2 R$), armature dynamics, friction, and casing heat transfer:

| Forecast Horizon | $R^2$ Score (Accuracy) | Mean Absolute Error (MAE) | Root Mean Squared Error (RMSE) |
| :--- | :--- | :--- | :--- |
| **+1 Minute** | **99.54%** ($R^2 = 0.9954$) | **0.12 °C** | 0.17 °C |
| **+5 Minutes** | **98.06%** ($R^2 = 0.9806$) | **0.24 °C** | 0.34 °C |
| **+15 Minutes**| **98.59%** ($R^2 = 0.9859$) | **0.21 °C** | 0.29 °C |
| **+30 Minutes**| **98.60%** ($R^2 = 0.9860$) | **0.22 °C** | 0.29 °C |

### Feature Importance (Explainable AI - XAI):
1. **Measured Temp (`temp_c` / DS18B20)**: **84.9%**
2. **Ambient Reference (`ambient_temp_c`)**: **10.5%**
3. **Thermal Rate of Change (`dt_temp_rate`)**: **3.6%**
4. **DC Bus Voltage (`voltage_v` / 0–25V Sensor)**: **0.7%**
5. **Motor Speed (`rpm` / LM393)**: **0.1%**
6. **Joule Loss & Current (`current_a` / ACS712)**: **0.2%**

---

## 5. How to Run the System

### Option A: 1-Click Desktop Launcher
Double-click **`RUN_HOST_APP.bat`** on your Desktop:
```text
C:\Users\ELCOT\OneDrive\Desktop\RUN_HOST_APP.bat
```
* Starts the FastAPI backend server on port 8000.
* Opens the live Cockpit Dashboard in your browser at `http://localhost:8000/`.
* Connects the real-time WebSocket telemetry stream at `ws://localhost:8000/ws/telemetry`.

### Option B: Terminal Command
```powershell
py -3.11 -m core_server.host_app
```

---

## 6. Repository Structure
```
ev_c2000_dashboard/
├── c2000_firmware/
│   ├── src/main_f2800137.c        # C2000 ADC sampling, speed pulse ISR, JSON UART output
│   └── include/                   # C2000 headers & telemetry structures
├── esp32_firmware/
│   ├── esp32_c2000_wifi_bridge.ino # ESP32 UART2 receiver & Wi-Fi JSON streamer to Laptop
│   └── esp32_bldc_csv_logger.ino  # CSV LittleFS logger fallback
├── core_server/
│   ├── host_app.py                # Unified FastAPI + WebSocket + Live AI Host Server
│   ├── train_random_forest.py     # 12V DC Motor 100-Tree Random Forest training engine
│   └── random_forest_model.pkl    # Serialized trained model
├── dashboard_ui/
│   ├── index.html                 # Automotive Digital Cockpit with Hardware & Wiring tab
│   ├── app.js                     # 10 Hz WebSocket rendering & live gauge animations
│   ├── styles.css                 # Glassmorphic UI styling
│   └── rf_model_weights.json      # Model metadata & feature importances
├── RUN_HOST_APP.bat               # 1-Click Desktop launcher
├── PUSH_TO_GITHUB.bat             # 1-Click GitHub sync helper
└── README.md                      # System documentation
```
