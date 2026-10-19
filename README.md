# ThermaPulse EV: Real-Time Edge Telemetry & Multi-Horizon AI Thermal Cockpit

An automotive digital cockpit and real-time predictive thermal management system for an Electric Vehicle / Motor testbed powered by a **12V DC Motor (Continuous Run)**, featuring **TI TMS320F2800137 LaunchPad Primary Acquisition**, **ESP32-S Wi-Fi Telemetry Streaming**, **Multi-Horizon AI Thermal Forecasting** (+1 min, +5 min, +15 min, +30 min), and **Zero-Silent-Fallback Proactive Safety Controls**.

**GitHub Repository:** [https://github.com/jonce9751961231/Ev_Dashboard](https://github.com/jonce9751961231/Ev_Dashboard)

---

## 1. System Pipeline Architecture

```text
 ┌────────────────────────┐
 │     12V DC MOTOR &     │
 │     THE 4 SENSORS      │
 └───────────┬────────────┘
             │ Physical Sensor Signals (0-2.4V Analog, Pulses, 1-Wire)
             ▼
 ┌────────────────────────┐
 │     TMS320F2800137     │  • Primary Real-Time Sensor Acquisition (120 MHz C2000)
 │       LAUNCHPAD        │  • ADCINA0 (Volt), ADCINA1 (Curr with 2:3 divider), GPIO 0 (RPM), GPIO 3 (DS18B20)
 └───────────┬────────────┘  • Honest telemetry: disconnected sensors report 0 / null, never fabricated defaults
             │ SCIA UART (115200 bps): GPIO 29 (TX) ──► ESP32 GPIO 16 (RX2)
             ▼
 ┌────────────────────────┐
 │    ESP32-S (38-PIN)    │  • Hardware Wi-Fi Telemetry Bridge
 │       DEV BOARD        │  • HTTP POST to http://<LAPTOP_IP>:8000/api/ingest at 1 Hz
 └───────────┬────────────┘
             │ Local Wi-Fi (JSON Ingestion Endpoint)
             ▼
 ┌────────────────────────┐
 │    LAPTOP HOST APP     │  • FastAPI + WebSocket Host Server (Port 8000)
 │     & ML REGISTRY      │  • Multi-Horizon Thermal Forecaster (Ridge / GRU / RF / LightGBM)
 └───────────┬────────────┘  • Auto-expiry: marks data as STALE / OFFLINE if ESP32 drops out
             │ WebSocket Stream: ws://localhost:8000/ws/telemetry (1 Hz)
             ▼
 ┌────────────────────────┐
 │     AUTOMOTIVE WEB     │  • Glassmorphic Instrument Cluster UI (HTML5 / Tailwind / Chart.js)
 │        COCKPIT         │  • Live Dials, Data Source Badges (Hardware vs Simulator), Error Indicators
 └────────────────────────┘
```

---

## 2. Hardware Bill of Materials (BOM) & Safety Notes

| Component / Sensor | Model / Specification | Purpose in System | Connected Pin |
| :--- | :--- | :--- | :--- |
| **Actuator** | 12V DC Motor | Constant continuous physical load | Direct 12V Loop via ACS712 |
| **Microcontroller 1** | TI TMS320F2800137 LaunchPad | Primary high-speed sensor acquisition & UART stream | LAUNCHXL-F2800137 |
| **Microcontroller 2** | NodeMCU ESP32-S (38-Pin) | Wi-Fi Telemetry bridge & JSON streamer to Laptop | NodeMCU ESP32-S |
| **Voltage Sensor** | Standard 0–25V Module | Measures 12V DC Link (5:1 divider: 12V $\rightarrow$ 2.4V) | C2000 **ADCINA0** (J3-27) |
| **Current Sensor** | Allegro ACS712 (5A Variant) | Armature current (185 mV/A, 2.5V zero offset) | **Via 2:3 Voltage Divider** $\rightarrow$ C2000 **ADCINA1** (J3-28) |
| **Speed Sensor** | LM393 Optical Sensor Module | Slotted photo-interrupter with 20-slot disc on motor shaft | C2000 **GPIO 0** (J2-13, XINT1) |
| **Temperature Sensor**| Dallas DS18B20 Waterproof Probe| Surface casing probe (Real 1-Wire protocol) | C2000 **GPIO 3** (J1-6, 4.7kΩ pull-up) |

> [!WARNING]
> **ACS712 Voltage Level Safety on C2000 ADC:**
> The ACS712 is powered by 5.0V. At 0A it outputs 2.50V, and under positive load (5A) it outputs up to 3.425V. Connecting the ACS712 directly to the C2000 ADC pin will exceed the 3.3V maximum ADC rating ($V_{DDA}$).
> A **2:3 resistor voltage divider** ($10\text{ k}\Omega$ in series, $20\text{ k}\Omega$ to GND) must be placed between ACS712 `OUT` and C2000 `ADCINA1`.
> - At 0A: $2.50\text{V} \times (2/3) \approx 1.667\text{V}$ (matches `#define ACS712_ZERO_OFFSET_V 1.667f`).
> - At 5A: $3.425\text{V} \times (2/3) \approx 2.283\text{V} \le 3.3\text{V}$ (completely safe).
> - Effective sensitivity: $0.185\text{ V/A} \times (2/3) = 0.1233\text{ V/A}$.

---

## 3. Complete Wire-by-Wire Wiring Schematic

### Section A: 12V Motor High-Current Loop
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
* **Component R-DIV (Divider):** ACS712 `OUT` $\longrightarrow$ $10\text{ k}\Omega$ resistor $\longrightarrow$ C2000 **ADCINA1** (Header J3 Pin 28), with $20\text{ k}\Omega$ resistor from ADCINA1 to **GND**
* **Wire W-12 (🔴 Red):** C2000 **3.3V** (Header J1 Pin 1) $\longrightarrow$ LM393 Speed `VCC`
* **Wire W-13 (⚫ Black):** LM393 Speed `GND` $\longrightarrow$ C2000 **GND** (Header J1 Pin 22)
* **Wire W-14 (🟠 Orange):** LM393 Speed `D0` $\longrightarrow$ C2000 **GPIO 0** (Header J2 Pin 13, External Interrupt `XINT1`)
* **Wire W-15 (🔴 Red):** C2000 **3.3V** (Header J1 Pin 1) $\longrightarrow$ DS18B20 `VCC` (Red Wire)
* **Wire W-16 (⚫ Black):** DS18B20 `GND` (Black Wire) $\longrightarrow$ C2000 **GND** (Header J1 Pin 22)
* **Wire W-17 (🟡 Yellow):** DS18B20 `DATA` (Yellow Wire) $\longrightarrow$ C2000 **GPIO 3** (Header J1 Pin 6)
* **Component R-PULLUP (🟤 4.7 kΩ Resistor):** Connected between DS18B20 Yellow (DATA) and Red (3.3V) lines

### Section C: TMS320F2800137 LaunchPad $\longrightarrow$ ESP32-S (38-Pin) UART Link
* **Wire W-18 (🟢 Green):** C2000 **GPIO 29 (SCIA_TX)** (Header J1 Pin 4) $\longrightarrow$ ESP32-S **GPIO 16 (RX2)**
* **Wire W-19 (🔵 Blue):** ESP32-S **GPIO 17 (TX2)** $\longrightarrow$ C2000 **GPIO 28 (SCIA_RX)** (Header J1 Pin 3)
* **Wire W-20 (⚫ Black):** C2000 **GND** (Header J1 Pin 22) $\longrightarrow$ ESP32-S **GND**

---

## 4. Multi-Horizon Predictive Thermal Modeling (Phase 2 Results)

All models were evaluated on the **exact same time-ordered whole-run split** (8 training runs / 2 validation runs / 2 held-out test runs), predicting temperature change ($\Delta T$) across multiple horizons:

### Mean Absolute Error (MAE in °C, Lower is Better)

| Model | +1 min | +5 min | +15 min | +30 min | Mean MAE | Beats Baselines on Test? |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Persistence (Baseline 1: $\Delta T = 0$)** | 0.588 | 2.621 | 5.164 | 7.811 | 4.046 °C | Baseline |
| **Physics Heating Curve (Baseline 2: Fitted ODE)** | 0.542 | 2.095 | 4.339 | 6.149 | 3.281 °C | Baseline |
| **Ridge Regression** | **0.181** | **1.546** | **4.498** | **6.059** | **3.071 °C** | **YES (Beats both baselines)** |
| **GRU (PyTorch Sequence Model)** | 0.272 | 1.795 | 4.926 | 6.415 | 3.352 °C | Beats Persistence, close to Physics |
| **LightGBM** | 0.178 | 2.080 | 5.231 | 6.843 | 3.583 °C | Beats Persistence |
| **Random Forest** | 0.251 | 2.242 | 6.087 | 7.282 | 3.965 °C | Barely beats Persistence |

### Model Resource Comparison

| Model | Model Size | Inference Latency | Target Deployment |
| :--- | :---: | :---: | :--- |
| **Ridge Regression** | **2 KB** | **0.31 ms** | **Can run directly on ESP32, C2000, or Laptop** |
| **GRU** | 19 KB | 1.56 ms | Laptop Host Server |
| **LightGBM** | 59 KB | 7.02 ms | Laptop Host Server |
| **Random Forest** | 4,790 KB | 42.51 ms | Laptop Host Server |

The best model is dynamically loaded by name via `core_server/ml/artifacts/registry.json`.

---

## 5. How to Run the System

### Option A: 1-Click Dashboard & Host Launcher
Double-click **`run_dashboard.bat`** in the repository root:
* Launches FastAPI + WebSocket host server on `http://localhost:8000/`.
* Automatically opens the Web Cockpit in your browser.
* Ingests live telemetry from ESP32 (`/api/ingest`) and broadcasts live updates at 1 Hz (`/ws/telemetry`).

### Option B: Flashing C2000 LaunchPad
Double-click **`FLASH_C2000.bat`** on your Desktop:
* Compiles `empty_driverlib_main.c` with TI CGT C2000 compiler.
* Flashes program via Texas Instruments XDS110 debug probe into `TMS320F2800137`.

### Option C: Arduino IDE for ESP32
* Open `ESP32_WIFI_BRIDGE.ino` (or `ESP32_ALL_SENSORS.ino`).
* Board: **ESP32 Dev Module** | Port: **COM17**.
* Flash Frequency: **40MHz** | Flash Mode: **DIO** | Baud Rate: **115200**.

---

## 6. Repository Layout
```
ev_c2000_dashboard/
├── c2000_firmware/            # C2000 project headers and source files
├── esp32_firmware/            # ESP32 sketches for Wi-Fi bridge and sensors
├── core_server/
│   ├── host_app.py            # Unified FastAPI server (/api/ingest, /ws/telemetry)
│   ├── road_energy_predictor.py # Road profile longitudinal dynamics & range model
│   └── ml/                    # Phase 2 Multi-Model Predictive ML Engine
│       ├── models.py          # Persistence, Physics ODE, Ridge, RF, LightGBM, GRU
│       ├── data.py            # Whole-run time-ordered train/val/test splits & lag features
│       ├── train_all.py       # Automated trainer & evaluator
│       ├── predictor.py       # Live registry-driven forecaster
│       └── artifacts/         # registry.json, report.md, saved weights
├── dashboard_ui/
│   ├── index.html             # Glassmorphic cockpit UI with data source & model badges
│   ├── app.js                 # Real-time WebSocket consumer & Chart.js rendering
│   └── styles.css             # Dark automotive theme
├── datasets/runs/             # Time-series telemetry runs for ML training
├── legacy/                    # Archived 48V/PMSM historical files
├── requirements.txt           # Python dependencies (fastapi, pandas, scikit-learn, etc.)
└── run_dashboard.bat          # 1-Click Launcher
```
