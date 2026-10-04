# Aura EV Digital Cockpit & 48V-96V BLDC Multi-Horizon AI Thermal Management System

An automotive digital cockpit and real-time predictive thermal management system for Electric Vehicles powered by **48V to 96V BLDC Motors**, featuring **ESP32 CSV Data Logging** and **Physics-Informed Multi-Horizon AI Temperature Forecasting** (+1 min, +5 min, +15 min, +30 min).

**GitHub Repository:** [https://github.com/jonce9751961231/Ev_Dashboard](https://github.com/jonce9751961231/Ev_Dashboard)

---

## System Architecture

```
ev_c2000_dashboard/
├── esp32_firmware/
│   ├── esp32_bldc_csv_logger.ino  # ESP32 48V-96V ADC, DS18B20, LittleFS CSV Logger & Web Server
│   ├── bldc_ai_weights.h          # Embedded C header with trained AI weights for on-chip ESP32 inference
│   └── esp32_cloud_logger.ino     # Wi-Fi Cloud HTTP POST uploader
├── core_server/
│   ├── train_bldc_ai_model.py     # Multi-voltage (48V-96V) BLDC AI model training & weights exporter
│   ├── esp_csv_ai_predictor.py    # Python CLI tool to ingest ESP CSV files and predict future temperatures
│   ├── bldc_ai_model_weights.json # Calibrated AI model weights (used by Python and browser JS)
│   ├── server.py                  # FastAPI & WebSocket telemetry streaming server
│   └── c2000_interface.py         # Hardware-in-the-Loop virtual driver & binary packet parser
├── dashboard_ui/
│   ├── index.html                 # Automotive glassmorphic cluster with 48V-96V selector & ESP CSV AI tab
│   ├── app.js                     # 10 Hz real-time rendering, in-browser AI predictor & Web Serial driver
│   └── styles.css                 # Dark-mode automotive cockpit styling & dropzone animations
├── datasets/
│   ├── bldc_48v_commute.csv       # 48V BLDC sample city commute ride telemetry
│   ├── bldc_72v_hill_climb.csv    # 72V BLDC steep 12% grade mountain climb test
│   └── bldc_96v_high_speed.csv    # 96V BLDC high-speed thermal stress dataset
└── README.md                      # Complete documentation & wiring guide
```

---

## 1. Hardware Circuit & Wiring Guide (48V - 96V BLDC)

### 1.1 Precision Voltage Divider (Safe for 3.3V ESP32 ADC)
Measuring **48V to 96V DC** (which peaks up to **115V DC** under full charge or regenerative braking) requires a safe voltage divider with overvoltage clamping:

```
Battery (+) [48V - 96V] ----[ R1: 270 kΩ (1W) ]----+----[ R2: 8.2 kΩ (0.25W) ]---- Battery (-) / GND
                                                   |
                                                   +----[ 3.3V Zener Diode (Cathode) ] to GND (Anode)
                                                   |     (Prevents voltage spikes above 3.3V)
                                                   +----[ 100 nF Ceramic Filter Cap ] to GND
                                                   |
                                                   +----> ESP32 GPIO 34 (ADC1_CH6)
```
- **Division Ratio**:
  $$\text{Ratio} = \frac{R_2}{R_1 + R_2} = \frac{8.2}{270 + 8.2} = 0.029475 \implies \text{Multiplier} = 33.93$$
- At **48.0V**: $48.0 \times 0.029475 = 1.41\text{V}$ (Safe)
- At **72.0V**: $72.0 \times 0.029475 = 2.12\text{V}$ (Safe)
- At **96.0V**: $96.0 \times 0.029475 = 2.83\text{V}$ (Safe)
- At **115.0V** Peak: $3.39\text{V} \implies$ **Zener clamps safely at 3.3V** to protect the ESP32.

### 1.2 Sensor Pinout Table
| Sensor / Function | Sensor Model | ESP32 Pin | Notes |
| :--- | :--- | :--- | :--- |
| **Bus Voltage (48V-96V)** | Resistor Divider (270k / 8.2k) | `GPIO 34` (ADC1) | Averaged 16x ADC oversampling |
| **Motor Current (0-100A)** | Allegro ACS758ECB-100B / ACS770 | `GPIO 35` (ADC1) | 20 mV/A sensitivity, 2.5V zero point |
| **Stator Winding Temp** | Dallas DS18B20 1-Wire Digital | `GPIO 4` | Requires 4.7 kΩ pull-up to 3.3V |
| **Motor Speed (RPM)** | BLDC Hall Sensor (Phase A/B) | `GPIO 18` (Interrupt) | Counts rising edge pulses per revolution |
| **Status LED** | Onboard Blue LED | `GPIO 2` | Pulses during active CSV logging |

---

## 2. ESP32 Firmware: CSV Data Logging & Web Server

The firmware [`esp32_firmware/esp32_bldc_csv_logger.ino`](file:///C:/Users/ELCOT/.gemini/antigravity/scratch/ev_c2000_dashboard/esp32_firmware/esp32_bldc_csv_logger.ino) provides:
1. **Sampling at 5 Hz (200 ms)**: Acquires bus voltage, current, RPM, and stator temperature.
2. **CSV Conversion**: Automatically formats telemetry rows:
   ```csv
   timestamp_ms,voltage_v,current_a,speed_rpm,stator_temp_c,ambient_temp_c,power_w
   12400,71.80,32.40,4100,52.40,30.0,2326.3
   ```
3. **Internal Storage**: Appends to `/telemetry.csv` in ESP32 internal flash memory using `LittleFS`.
4. **USB Serial Streaming**: Streams CSV lines over Serial (115200 baud) for laptop capture or Web Serial connection.
5. **Built-in Wi-Fi Web Server**:
   - ESP32 hosts an Access Point named **`ESP32_EV_TELEMETRY`** (Password: `12345678`).
   - Open browser on phone or laptop to `http://192.168.4.1/`:
     - **Live Cockpit Gauges**: Displays live Voltage, Current, Speed, and Temperature.
     - **One-Click Download**: Click **"Download telemetry.csv"** (`/download_csv`) to save the logged drive file.
     - **Clear Log**: Click **"Clear CSV"** (`/clear`) to wipe the file for a fresh test run.

---

## 3. Physics-Informed AI Future Temperature Prediction

Rather than reacting only after the motor overheats, the AI system predicts future temperatures across **multi-horizons (+1m, +5m, +15m, +30m)**:

$$\begin{aligned}
P_{\text{cu}} &= 3 I_{\text{rms}}^2 R_0 [1 + \alpha_{\text{cu}} (T_{\text{stator}} - 20^\circ\text{C})] \\
P_{\text{fe}} &= k_h f_e B^n + k_e f_e^2 B^2 \quad \left(f_e = \frac{p \cdot \text{RPM}}{60}\right) \\
T_{\infty} &= T_{\text{ambient}} + (P_{\text{cu}} + P_{\text{fe}}) R_{\text{thermal, total}} \\
T(t + \tau) &= T_{\infty} + (T_{\text{current}} - T_{\infty}) e^{-\frac{\tau}{\tau_{\text{stator}}}} + \beta \frac{dT}{dt}
\end{aligned}$$

### Safety Limits & Proactive Derating:
- **Stator Winding Warn**: **110.0°C**
- **Stator Class F Trip Limit**: **135.0°C**
- **NdFeB Permanent Magnet Warn**: **90.0°C**
- **Demagnetization Critical Trip**: **115.0°C**
- If the predicted temperature at $+5\text{ min}$ exceeds 110°C, maximum allowable current is smoothly scaled back before physical damage occurs.

---

## 4. How to Launch & Use the EV Dashboard

### Step 1: Open the Dashboard
Navigate to:
```
C:\Users\ELCOT\.gemini\antigravity\scratch\ev_c2000_dashboard\dashboard_ui\index.html
```
Double-click **`index.html`** or open it in any web browser (Google Chrome, Microsoft Edge, Firefox).

### Step 2: Select Your DC Bus Voltage
In the top header, click your vehicle's nominal voltage:
- **48V** (13S/14S Li-ion or 16S LFP)
- **60V** (16S Li-ion / 20S LFP)
- **72V** (20S Li-ion / 24S LFP)
- **84V** (23S Li-ion)
- **96V** (26S Li-ion / 32S LFP)

### Step 3: Run AI Temperature Prediction on ESP CSV Files
1. Switch to the **"ESP CSV & AI Model"** tab.
2. Click one of the quick sample buttons:
   - **`Load 48V Commute CSV`**
   - **`Load 72V Hill Climb CSV`**
   - **`Load 96V High Speed CSV`**
3. Or **drag and drop** your own `telemetry.csv` downloaded from the ESP32!
4. **Immediate AI Inference**:
   - The browser automatically executes the AI model on each CSV row.
   - Plots the historical stator temperature curve followed by the forward **+1m, +5m, +15m, and +30m** prediction trajectory.
   - Displays thermal safety status, time-to-trip, and proactive throttle derating percentage.
   - Scrub through the time slider or click **"Play Telemetry"** to replay the recorded ride!
5. **Connect ESP32 via USB**:
   - Click **"Connect ESP32 (USB)"** to use the Web Serial API (Chrome/Edge) to read live CSV lines directly from the microcontroller.

---

## 5. Running the Python AI Model (Optional)

If you have Python installed:
1. **Train or re-calibrate the AI model**:
   ```bash
   python core_server/train_bldc_ai_model.py
   ```
2. **Ingest and predict from any ESP CSV file**:
   ```bash
   python core_server/esp_csv_ai_predictor.py datasets/bldc_72v_hill_climb.csv
   ```
   This outputs a full terminal forecast summary and exports `core_server/latest_esp_ai_predictions.json`.
