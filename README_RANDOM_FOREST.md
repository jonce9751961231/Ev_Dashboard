# 🚗⚡ 48V BLDC Electric Vehicle: Random Forest Predictive Thermal Management System

This directory contains the complete end-to-end implementation for predicting future 48V BLDC motor temperatures using a **100-Tree Random Forest Regressor**, complete with Google Colab training, local Python streaming, and an interactive **Frontend Digital Cockpit Dashboard**.

---

## 📁 Project Structure

```
ev_c2000_dashboard/
├── google_colab/
│   ├── EV_48V_Random_Forest_Thermal_Prediction.ipynb  <-- Upload to Google Colab
│   └── train_in_colab.py                             <-- Standalone Python script
├── core_server/
│   ├── train_random_forest.py                        <-- Local Python training engine
│   ├── rf_continuous_server.py                       <-- Real-time WebSocket streaming server (Port 8765)
│   └── random_forest_model.pkl                       <-- Saved trained model (joblib)
├── dashboard_ui/
│   ├── index.html                                    <-- Interactive Digital Cockpit
│   ├── app.js                                        <-- Random Forest & physics logic
│   ├── styles.css                                    <-- Dark-mode styling
│   └── rf_model_weights.json                         <-- Pre-computed weights & XAI metrics
├── datasets/
│   ├── sample_bldc_telemetry.csv                     <-- 48V BLDC Drive Cycle CSV
│   └── bldc_48v_commute.csv
├── run_rf_pipeline.bat                               <-- 1-Click Dashboard & AI Launcher
└── README_RANDOM_FOREST.md
```

---

## 🚀 How to Run the System & View Output in the Frontend Dashboard

### Method 1: 1-Click Launch (Recommended)
1. Double-click **`run_rf_pipeline.bat`** in the project folder.
2. The interactive **Aura EV Digital Cockpit** will immediately launch in your default web browser (`dashboard_ui/index.html`).
3. Click on the tab: **"ESP CSV & AI Model"**:
   - View the **Random Forest Regressor (100 Trees)** panel.
   - See the **Explainable AI (XAI) Feature Importance Bar Chart** ($I^2R$ Joule Loss, RPM, Voltage, Temperature).
   - View the multi-horizon predictions: **$+1\text{ min}$, $+5\text{ mins}$, $+15\text{ mins}$, $+30\text{ mins}$**.
   - Use the slider to scrub through any telemetry row and watch the temperature forecast curves update instantly.

---

### Method 2: Training in Google Colab
1. Go to [Google Colab](https://colab.research.google.com/).
2. Click **Upload** and select:
   `google_colab/EV_48V_Random_Forest_Thermal_Prediction.ipynb`
3. Click **Runtime > Run All**:
   - The notebook trains the 100 decision trees.
   - Generates accuracy plots ($R^2 > 0.98$, MAE $< 1.2^\circ\text{C}$).
   - Plots the Feature Importance breakdown.
   - Automatically exports `random_forest_model.pkl` and `rf_model_weights.json`.

---

### Method 3: Running the Real-Time Python Streaming Server (Port 8765)
If you have Python installed with `websockets` and `scikit-learn`:
```bash
python -m core_server.rf_continuous_server
```
- The server will stream live sensor telemetry and Random Forest predictions at **1 Hz** to `ws://localhost:8765`.
- The dashboard status badge will light up: `🟢 LIVE STREAM (1 Hz)`.

---

## 🎯 Sensor Suite & Technical Parameters

* **Motor:** 48V 3-Phase BLDC Motor (750W–1000W)
* **Temperature Sensor:** Maxim DS18B20 1-Wire Digital Probe (Connected to ESP32 GPIO4)
* **Current Sensor:** Allegro ACS712 5A Hall Module (DC link)
* **Voltage Sensor:** Standard Blue 0–25V Module + $100\text{k}\Omega$ series resistor (48V DC bus)
* **Speed Sensor:** BLDC Built-in Hall A Pulse (GPIO0 eCAP)
* **AI Model:** Random Forest Regressor (100 Estimators, max depth 14)
* **Inference Time:** $< 1.8\text{ ms}$
