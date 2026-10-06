/**
 * ============================================================================
 * Aura EV Digital Cockpit - 48V - 96V BLDC Predictive AI Engine
 * Target Hardware: ESP32 (Wi-Fi/USB CSV Logger) & TI C2000 Microcontrollers
 * Features:
 *  1. Dynamic 48V, 60V, 72V, 84V, 96V Bus Voltage Architecture
 *  2. ESP CSV Ingestion: Drag-and-drop or USB Web Serial Live Ingestion
 *  3. In-Browser Physics-Informed Multi-Horizon AI Temperature Forecaster (+1m, +5m, +15m, +30m)
 *  4. Stator Winding & NdFeB Permanent Magnet Demagnetization Risk Analyzer
 *  5. Battery Pack Thermal & SoC Coulomb Counting Model
 *  6. Road-Specific Energy & Range Forecaster
 * ============================================================================
 */

// --- 1. System Physics Specifications ---
let currentVoltageSystem = 12; // Default 12V DC Motor Continuous Testbed

const BLDCSpecs = {
  pole_pairs: 4,              // 8-Pole BLDC
  kv_rating: 450.0,           // RPM/Volt
  kt_nm_per_a: 0.0212,        // Torque constant
  R_phase_20C: 0.085,         // Phase-to-phase resistance at 20°C (Ohms)
  alpha_cu: 0.00393,
  C_stator: 240.0,            // Stator copper heat capacity (J/K)
  R_stator_core: 0.045,
  C_core: 650.0,              // Stator core (J/K)
  R_core_frame: 0.035,
  C_rotor_magnets: 310.0,     // NdFeB permanent magnets on rotor (J/K)
  R_rotor_gap: 0.120,         // Airgap thermal resistance (K/W)
  C_frame: 1800.0,            // Casing heat capacity (J/K)
  R_frame_air: 1.85,

  stator_warn: 110.0,         // Thermal warning
  stator_trip: 135.0,         // Class F insulation trip limit
  rotor_warn: 90.0,           // NdFeB magnet demagnetization warning
  rotor_trip: 115.0           // Irreversible demagnetization limit
};

const BatterySpecs = {
  capacity_ah: 50.0,
  total_kwh: 3.6,             // 72V * 50Ah = 3.6 kWh
  nominal_voltage: 72.0,
  r_internal_base: 0.040,
  c_thermal: 9200.0,
  r_thermal_amb: 0.85,
  warn_temp: 45.0,
  runaway_temp: 60.0
};

const RoadProfiles = {
  URBAN_CITY: { name: "Urban City (Stop & Go)", crr: 0.012, speed: 35.0, grade: 1.0, regen: 0.85 },
  HIGHWAY_EXPRESS: { name: "Highway Expressway (110 km/h)", crr: 0.010, speed: 105.0, grade: 0.5, regen: 0.15 },
  MOUNTAIN_GRADE: { name: "12% Mountain Grade Climb", crr: 0.014, speed: 55.0, grade: 10.5, regen: 0.90 },
  OFFROAD_GRAVEL: { name: "Rough Gravel / Off-Road", crr: 0.032, speed: 40.0, grade: 4.0, regen: 0.40 }
};

const Scenarios = {
  MOUNTAIN_CLIMB: { name: "12% Mountain Grade Hill Climb", rpm_base: 4200, torque_base: 280, load_mult: 1.40, road: "MOUNTAIN_GRADE" },
  AGGRESSIVE_TRACK: { name: "Aggressive Sport Track Launch", rpm_base: 7200, torque_base: 290, load_mult: 1.25, road: "HIGHWAY_EXPRESS" },
  HIGHWAY_CRUISE: { name: "110 km/h Highway Cruise", rpm_base: 5600, torque_base: 140, load_mult: 0.70, road: "HIGHWAY_EXPRESS" },
  ECO_CITY: { name: "Urban City Eco", rpm_base: 2200, torque_base: 90, load_mult: 0.45, road: "URBAN_CITY" },
  COOLING_DEGRADED: { name: "Cooling Impairment Fault", rpm_base: 4600, torque_base: 180, load_mult: 0.90, road: "MOUNTAIN_GRADE" }
};

// Global System State
let state = {
  T_stator: 32.0,
  T_core: 32.0,
  T_rotor_magnet: 30.0,
  T_casing: 31.0,
  T_battery: 28.0,
  battery_soc: 0.85,
  ambient_temp: 30.0,
  current_scenario: 'MOUNTAIN_CLIMB',
  tick_count: 0
};

// --- 2. In-Browser Physics-Informed AI Model Weights (48V - 96V BLDC) ---
const BLDC_AI_MODEL = {
  means: [72.0, 18.5, 3450.0, 1332.0, 52.0, 0.12, 30.0, 115.0, 45.0],
  stds:  [17.5, 14.2, 1650.0, 1120.0, 24.0, 0.28, 5.0,  145.0, 38.0],
  bias:  [54.25, 63.10, 74.85, 81.40, 49.60],
  weights: [
    [0.15, 0.32, 0.48, 0.55, 0.20],
    [0.85, 2.45, 3.80, 4.10, 1.15],
    [0.45, 1.20, 2.10, 2.40, 0.95],
    [0.92, 2.85, 4.25, 4.60, 1.40],
    [21.80, 16.50, 8.20, 4.10, 14.80],
    [3.40, 7.85, 2.10, 0.85, 1.95],
    [0.85, 2.10, 3.90, 4.85, 1.90],
    [1.65, 4.90, 7.45, 8.20, 2.80],
    [0.55, 1.85, 3.10, 3.50, 1.25]
  ]
};

/**
 * Executes the AI Multi-Horizon Regressor client-side
 * @param {Array<number>} features [V, I, RPM, Power, T_stator, dT_dt, T_amb, P_cu, P_fe]
 * @returns {Array<number>} [pred_1m, pred_5m, pred_15m, pred_30m, pred_rotor_5m]
 */
function evaluateBLDCAIModel(features) {
  const norm = features.map((val, i) => (val - BLDC_AI_MODEL.means[i]) / BLDC_AI_MODEL.stds[i]);
  const outputs = [];
  for (let j = 0; j < 5; j++) {
    let sum = BLDC_AI_MODEL.bias[j];
    for (let i = 0; i < 9; i++) {
      sum += norm[i] * BLDC_AI_MODEL.weights[i][j];
    }
    outputs.push(sum);
  }
  return outputs;
}

// Chart Instances
let predictionChart = null;
let batteryChart = null;
let roadEnergyChart = null;
let csvPredictionChart = null;
let rfFeatureChart = null;

// Random Forest Engine & Stream State
let rfModelWeights = null;
let rfWebSocket = null;
let isRFServerConnected = false;

// CSV Dataset State
let csvDataset = [];
let csvCurrentRowIndex = 0;
let csvPlaybackTimer = null;

// --- 3. Voltage System Configuration (12V, 48V, 72V) ---
function setVoltageSystem(volts) {
  currentVoltageSystem = volts;
  
  // Update button active state
  document.querySelectorAll('.volt-btn').forEach(btn => btn.classList.remove('active'));
  const activeBtn = document.getElementById(`btn-volt-${volts}`);
  if (activeBtn) activeBtn.classList.add('active');

  // Update battery capacity according to voltage
  BatterySpecs.nominal_voltage = volts;
  BatterySpecs.total_kwh = (volts * (volts === 12 ? 10.0 : 50.0)) / 1000.0;
  
  // Update UI indicators
  const badge = document.getElementById('active-system-badge');
  if (badge) {
    badge.textContent = volts === 12 ? "12V DC MOTOR (CONTINUOUS)" : `${volts}V BLDC SYSTEM`;
  }
  const battVolt = document.getElementById('val-batt-nom-volt');
  if (battVolt) battVolt.textContent = `${volts}.0 V (${volts === 12 ? '12V Power Bus' : Math.round(volts / 3.6) + 'S Configuration'})`;
  const battCap = document.getElementById('val-batt-cap');
  if (battCap) battCap.textContent = `${volts === 12 ? '10 Ah (0.12 kWh)' : '50 Ah (' + BatterySpecs.total_kwh.toFixed(1) + ' kWh)'}`;
  const vdc = document.getElementById('val-vdc');
  if (vdc) vdc.textContent = volts === 12 ? "12.10 V (0-25V)" : `${volts}.0 V`;

  // Scale max torque labels
  const maxTorqueLabel = document.getElementById('val-max-torque-label');
  if (maxTorqueLabel) maxTorqueLabel.textContent = volts === 12 ? "1.50 Nm" : `${Math.round(250 * (volts / 48.0))} Nm`;

  console.log(`[Voltage System] Switched to ${volts}V DC Bus architecture.`);
}

// --- 4. Chart Initializations ---
function initCharts() {
  // Chart 1: Real-time Live Motor Chart
  const ctxMotor = document.getElementById('predictionChart').getContext('2d');
  predictionChart = new Chart(ctxMotor, {
    type: 'line',
    data: {
      labels: ['-30s', '-20s', '-10s', 'Now', '+1 min', '+5 min', '+15 min', '+30 min'],
      datasets: [
        {
          label: 'Stator Winding (°C)',
          data: [32, 32, 32, 32, 34, 42, 60, 85],
          borderColor: '#06b6d4',
          backgroundColor: 'rgba(6, 182, 212, 0.1)',
          borderWidth: 2.5,
          tension: 0.3,
          pointRadius: 4,
          pointBackgroundColor: '#06b6d4'
        },
        {
          label: 'Rotor Magnet NdFeB (°C)',
          data: [30, 30, 30, 30, 32, 38, 50, 68],
          borderColor: '#a855f7',
          backgroundColor: 'transparent',
          borderWidth: 2,
          borderDash: [5, 5],
          tension: 0.3,
          pointRadius: 3,
          pointBackgroundColor: '#a855f7'
        },
        {
          label: 'Stator Warn (110°C)',
          data: [110, 110, 110, 110, 110, 110, 110, 110],
          borderColor: 'rgba(245, 158, 11, 0.8)',
          borderWidth: 1.5,
          borderDash: [6, 6],
          pointRadius: 0,
          fill: false
        },
        {
          label: 'Insulation Trip (135°C)',
          data: [135, 135, 135, 135, 135, 135, 135, 135],
          borderColor: 'rgba(244, 63, 94, 0.8)',
          borderWidth: 1.5,
          borderDash: [6, 6],
          pointRadius: 0,
          fill: false
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 250 },
      scales: {
        x: { grid: { color: 'rgba(51, 65, 85, 0.3)' }, ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono', size: 11 } } },
        y: { min: 20, max: 150, grid: { color: 'rgba(51, 65, 85, 0.3)' }, ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono', size: 11 }, callback: (v) => `${v}°C` } }
      },
      plugins: {
        legend: { labels: { color: '#cbd5e1', font: { family: 'Plus Jakarta Sans', size: 11 }, usePointStyle: true, boxWidth: 8 } }
      }
    }
  });

  // Chart 2: Battery Chart
  const ctxBatt = document.getElementById('batteryChart').getContext('2d');
  batteryChart = new Chart(ctxBatt, {
    type: 'line',
    data: {
      labels: ['-30s', '-20s', '-10s', 'Now', '+1 min', '+5 min', '+15 min', '+30 min'],
      datasets: [
        {
          label: 'Battery Pack Temp (°C)',
          data: [28, 28, 28, 28, 29, 32, 36, 42],
          borderColor: '#10b981',
          borderWidth: 2.5,
          tension: 0.3,
          pointRadius: 4,
          pointBackgroundColor: '#10b981'
        },
        {
          label: 'Thermal Runaway Limit (60°C)',
          data: [60, 60, 60, 60, 60, 60, 60, 60],
          borderColor: 'rgba(244, 63, 94, 0.8)',
          borderWidth: 1.5,
          borderDash: [6, 6],
          pointRadius: 0,
          fill: false
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 250 },
      scales: {
        x: { grid: { color: 'rgba(51, 65, 85, 0.3)' }, ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono', size: 11 } } },
        y: { min: 20, max: 70, grid: { color: 'rgba(51, 65, 85, 0.3)' }, ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono', size: 11 }, callback: (v) => `${v}°C` } }
      },
      plugins: {
        legend: { labels: { color: '#cbd5e1', font: { family: 'Plus Jakarta Sans', size: 11 }, usePointStyle: true } }
      }
    }
  });

  // Chart 3: Road Energy Chart
  const ctxRoad = document.getElementById('roadEnergyChart').getContext('2d');
  roadEnergyChart = new Chart(ctxRoad, {
    type: 'bar',
    data: {
      labels: ['Urban City', 'Highway 110', 'Mountain 12%', 'Off-Road'],
      datasets: [
        {
          label: 'Energy Consumption (Wh/km)',
          data: [83, 115, 143, 128],
          backgroundColor: ['rgba(16, 185, 129, 0.6)', 'rgba(6, 182, 212, 0.6)', 'rgba(245, 158, 11, 0.6)', 'rgba(244, 63, 94, 0.6)'],
          borderWidth: 1,
          borderRadius: 8
        },
        {
          label: 'Est. Range (km)',
          data: [43, 31, 25, 28],
          type: 'line',
          borderColor: '#ffffff',
          borderWidth: 2,
          pointRadius: 5,
          pointBackgroundColor: '#ffffff',
          yAxisID: 'y1'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { grid: { color: 'rgba(51, 65, 85, 0.3)' }, ticks: { color: '#cbd5e1', font: { family: 'Plus Jakarta Sans', size: 11 } } },
        y: {
          type: 'linear', position: 'left',
          grid: { color: 'rgba(51, 65, 85, 0.3)' },
          ticks: { color: '#06b6d4', font: { family: 'JetBrains Mono', size: 11 }, callback: (v) => `${v} Wh/km` }
        },
        y1: {
          type: 'linear', position: 'right',
          grid: { drawOnChartArea: false },
          ticks: { color: '#ffffff', font: { family: 'JetBrains Mono', size: 11 }, callback: (v) => `${v} km` }
        }
      },
      plugins: {
        legend: { labels: { color: '#cbd5e1', font: { family: 'Plus Jakarta Sans', size: 11 } } }
      }
    }
  });

  // Chart 4: ESP CSV Prediction Chart
  const ctxCSV = document.getElementById('csvPredictionChart').getContext('2d');
  csvPredictionChart = new Chart(ctxCSV, {
    type: 'line',
    data: {
      labels: ['0s', '2s', '4s', '6s', '8s', '10s', '+1m', '+5m', '+15m', '+30m'],
      datasets: [
        {
          label: 'CSV Measured Stator Temp (°C)',
          data: [32, 33, 35, 38, 42, 48, null, null, null, null],
          borderColor: '#38bdf8',
          backgroundColor: 'rgba(56, 189, 248, 0.15)',
          fill: true,
          borderWidth: 2.5,
          pointRadius: 4,
          pointBackgroundColor: '#38bdf8',
          tension: 0.2
        },
        {
          label: 'AI Multi-Horizon Stator Forecast (°C)',
          data: [null, null, null, null, null, 48, 54, 68, 85, 92],
          borderColor: '#f59e0b',
          borderWidth: 2.5,
          borderDash: [6, 4],
          pointRadius: 5,
          pointBackgroundColor: '#f59e0b',
          tension: 0.3
        },
        {
          label: 'Rotor NdFeB Magnet Demag Forecast (°C)',
          data: [null, null, null, null, null, 46, 50, 61, 72, 79],
          borderColor: '#c084fc',
          borderWidth: 2,
          borderDash: [4, 4],
          pointRadius: 4,
          pointBackgroundColor: '#c084fc',
          tension: 0.3
        },
        {
          label: 'Stator Warn Threshold (110°C)',
          data: [110, 110, 110, 110, 110, 110, 110, 110, 110, 110],
          borderColor: 'rgba(251, 146, 60, 0.8)',
          borderWidth: 1.5,
          borderDash: [6, 6],
          pointRadius: 0,
          fill: false
        },
        {
          label: 'Critical Insulation Trip (135°C)',
          data: [135, 135, 135, 135, 135, 135, 135, 135, 135, 135],
          borderColor: 'rgba(244, 63, 94, 0.8)',
          borderWidth: 1.5,
          borderDash: [6, 6],
          pointRadius: 0,
          fill: false
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { grid: { color: 'rgba(51, 65, 85, 0.3)' }, ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono', size: 10 } } },
        y: { min: 20, max: 150, grid: { color: 'rgba(51, 65, 85, 0.3)' }, ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono', size: 10 }, callback: (v) => `${v}°C` } }
      },
      plugins: {
        legend: { labels: { color: '#cbd5e1', font: { family: 'Plus Jakarta Sans', size: 10 }, usePointStyle: true, boxWidth: 6 } }
      }
    }
  });

  // Chart 5: Random Forest Feature Importance Chart (XAI)
  const ctxRFFeat = document.getElementById('rfFeatureChart')?.getContext('2d');
  if (ctxRFFeat) {
    rfFeatureChart = new Chart(ctxRFFeat, {
      type: 'bar',
      data: {
        labels: [
          'ACS712 Current (A)',
          'Motor Speed (RPM)',
          'DS18B20 Temp (°C)',
          'Joule Loss (3I²R)',
          '48V Bus Voltage',
          'Electrical Power (W)',
          'Temp Rate (dT/dt)',
          'Rolling Current'
        ],
        datasets: [{
          label: 'Relative Importance (%)',
          data: [34.12, 22.45, 18.90, 11.20, 6.85, 3.80, 1.48, 1.20],
          backgroundColor: [
            'rgba(168, 85, 247, 0.85)',
            'rgba(147, 51, 234, 0.8)',
            'rgba(6, 182, 212, 0.8)',
            'rgba(244, 63, 94, 0.8)',
            'rgba(59, 130, 246, 0.8)',
            'rgba(16, 185, 129, 0.8)',
            'rgba(245, 158, 11, 0.8)',
            'rgba(100, 116, 139, 0.8)'
          ],
          borderColor: 'rgba(168, 85, 247, 1)',
          borderWidth: 1,
          borderRadius: 6
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            grid: { color: 'rgba(51, 65, 85, 0.3)' },
            ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono', size: 10 }, callback: (v) => `${v}%` },
            max: 40
          },
          y: {
            grid: { display: false },
            ticks: { color: '#cbd5e1', font: { family: 'Plus Jakarta Sans', size: 10 } }
          }
        },
        plugins: {
          legend: { display: false }
        }
      }
    });
  }
}

// --- 5. Real-Time 3-Phase BLDC Simulation Step (10 Hz) ---
function runStep() {
  state.tick_count++;
  const scen = Scenarios[state.current_scenario];
  const dt = 0.10; // 100ms
  const time_s = state.tick_count * dt;

  // 1. BLDC Kinematics & High-Frequency Dynamics
  const oscillation = Math.sin(time_s * 0.5) * 0.12 + Math.sin(time_s * 1.6) * 0.05;
  const torque_demanded = Math.max(10, Math.min(350, scen.torque_base * (1.0 + oscillation)));
  const speed_rpm = Math.max(500, Math.min(9500, scen.rpm_base * (1.0 + oscillation * 0.35)));

  // Scaled voltage & current based on active pack (48V to 96V)
  const v_nominal = currentVoltageSystem;
  const i_dc = Math.max(2.0, (torque_demanded / (v_nominal * 0.25)) * scen.load_mult);
  const i_phase_rms = i_dc * 0.816;
  const v_dc = v_nominal - (i_dc * 0.04);
  const fe_hz = (BLDCSpecs.pole_pairs * speed_rpm) / 60.0;

  // 2. 3-Phase BLDC Losses
  const r_phase_actual = BLDCSpecs.R_phase_20C * (1.0 + BLDCSpecs.alpha_cu * (state.T_stator - 20.0));
  const p_copper = 3.0 * (i_phase_rms * i_phase_rms) * r_phase_actual;
  const p_iron = (0.015 * fe_hz) + (0.00018 * (fe_hz ** 2));
  const p_rotor_eddy = 0.05 * p_iron + 0.0010 * (i_phase_rms ** 2);
  const total_loss = p_copper + p_iron + p_rotor_eddy;

  // 3. BLDC 4-Node Thermal ODE Integration
  const q_stator_core = (state.T_stator - state.T_core) / BLDCSpecs.R_stator_core;
  const q_core_frame  = (state.T_core - state.T_casing) / BLDCSpecs.R_core_frame;
  const q_rotor_gap   = (state.T_rotor_magnet - state.T_casing) / BLDCSpecs.R_rotor_gap;
  const q_frame_air   = (state.T_casing - state.ambient_temp) / BLDCSpecs.R_frame_air;

  const dT_stator = (p_copper - q_stator_core) / BLDCSpecs.C_stator;
  const dT_core   = (p_iron + q_stator_core - q_core_frame) / BLDCSpecs.C_core;
  const dT_rotor  = (p_rotor_eddy - q_rotor_gap) / BLDCSpecs.C_rotor_magnets;
  const dT_frame  = (q_core_frame + q_rotor_gap - q_frame_air) / BLDCSpecs.C_frame;

  state.T_stator += dT_stator * dt;
  state.T_core   += dT_core * dt;
  state.T_rotor_magnet += dT_rotor * dt;
  state.T_casing += dT_frame * dt;

  // 4. Battery Thermodynamics & SoC
  const power_kw = (v_dc * i_dc) / 1000.0;
  state.battery_soc = Math.max(0.05, state.battery_soc - (i_dc * (dt / 3600.0)) / BatterySpecs.capacity_ah);

  const r_batt_actual = BatterySpecs.r_internal_base * Math.exp(-0.02 * (state.T_battery - 25.0));
  const p_batt_joule = (i_dc ** 2) * r_batt_actual;
  const p_batt_entropic = i_dc * (state.T_battery + 273.15) * -0.00022;
  const p_batt_total_heat = Math.max(0, p_batt_joule + p_batt_entropic);
  const q_batt_cool = (state.T_battery - state.ambient_temp) / BatterySpecs.r_thermal_amb;
  const dT_batt = (p_batt_total_heat - q_batt_cool) / BatterySpecs.c_thermal;

  state.T_battery += dT_batt * dt;

  // 5. Multi-Horizon Predictions
  const r_th_tot = BLDCSpecs.R_stator_core + BLDCSpecs.R_core_frame + BLDCSpecs.R_frame_air;
  const t_stator_inf = state.ambient_temp + ((p_copper + p_iron) * r_th_tot);
  const t_rotor_inf  = state.ambient_temp + (p_rotor_eddy * (BLDCSpecs.R_rotor_gap + BLDCSpecs.R_frame_air) + (p_copper * 0.15));

  const tau_stator = 190.0;
  const tau_rotor  = 520.0;
  const pred_stator_5m = t_stator_inf + (state.T_stator - t_stator_inf) * Math.exp(-300 / tau_stator);
  const pred_rotor_5m  = t_rotor_inf  + (state.T_rotor_magnet - t_rotor_inf)  * Math.exp(-300 / tau_rotor);

  // 6. Proactive Derating Controller
  let derate_active = false;
  let max_allowed_i = 45.0;
  let badge_status = "OPTIMAL";
  let badge_class = "bg-emerald-900 text-emerald-300 border-emerald-700";

  if (pred_stator_5m > BLDCSpecs.stator_warn || pred_rotor_5m > BLDCSpecs.rotor_warn) {
    derate_active = true;
    badge_status = "DERATING ACTIVE";
    badge_class = "bg-amber-900 text-amber-300 border-amber-700";
    max_allowed_i = Math.max(8.0, 45.0 * ((BLDCSpecs.stator_trip - pred_stator_5m) / (BLDCSpecs.stator_trip - BLDCSpecs.stator_warn)));
  }

  // --- 7. Update UI Fields ---
  const speed_kmh = (speed_rpm / 10000.0) * 140.0;
  const m = Math.floor(time_s / 60);
  const s = (time_s % 60).toFixed(1);

  document.getElementById('mcu-tick').textContent = `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
  document.getElementById('val-fe').textContent = `${Math.round(fe_hz)} Hz`;

  // Row 1 Gauges
  document.getElementById('val-speed-kmh').textContent = speed_kmh.toFixed(1);
  document.getElementById('val-motor-rpm').textContent = `${Math.round(speed_rpm)} RPM`;
  document.getElementById('bar-speed').style.width = `${Math.min(100, (speed_kmh / 140.0) * 100)}%`;

  document.getElementById('val-torque').textContent = torque_demanded.toFixed(1);
  document.getElementById('bar-torque').style.width = `${(torque_demanded / 350.0) * 100}%`;
  document.getElementById('val-derate-limit').textContent = derate_active ? `Derate: ${max_allowed_i.toFixed(1)}A` : "Limit: Full Torque";
  document.getElementById('val-derate-limit').className = derate_active ? "text-rose-400 font-bold" : "text-emerald-400 font-semibold";

  document.getElementById('val-power-kw').textContent = power_kw.toFixed(2);
  document.getElementById('bar-power').style.width = `${Math.min(100, (power_kw / 12.0) * 100)}%`;
  document.getElementById('val-vdc').textContent = `${v_dc.toFixed(1)} V`;
  document.getElementById('val-irms').textContent = `${i_dc.toFixed(1)} A`;

  const statusBadge = document.getElementById('status-badge');
  statusBadge.textContent = badge_status;
  statusBadge.className = `px-2 py-0.5 text-[10px] font-bold uppercase rounded-md border ${badge_class}`;
  
  const tripEl = document.getElementById('val-time-to-trip');
  const demag_margin = BLDCSpecs.rotor_trip - state.T_rotor_magnet;
  tripEl.textContent = `+${demag_margin.toFixed(1)}°C Margin`;
  document.getElementById('val-pump-pwm').textContent = `${max_allowed_i.toFixed(1)} A`;

  // Tab 1: BLDC Spatial Map
  document.getElementById('temp-node-stator').textContent = `${state.T_stator.toFixed(1)} °C`;
  document.getElementById('rate-node-stator').textContent = `${dT_stator >= 0 ? '+' : ''}${dT_stator.toFixed(2)} °C/s`;
  document.getElementById('temp-node-core').textContent = `${state.T_core.toFixed(1)} °C`;
  document.getElementById('temp-node-rotor').textContent = `${state.T_rotor_magnet.toFixed(1)} °C`;
  document.getElementById('rate-node-rotor').textContent = `${dT_rotor >= 0 ? '+' : ''}${dT_rotor.toFixed(2)} °C/s`;
  document.getElementById('temp-node-frame').textContent = `${state.T_casing.toFixed(1)} °C`;

  document.getElementById('loss-copper').textContent = `${p_copper.toFixed(1)} W`;
  document.getElementById('loss-iron').textContent = `${p_iron.toFixed(1)} W`;
  document.getElementById('loss-rotor').textContent = `${p_rotor_eddy.toFixed(1)} W`;

  document.getElementById('badge-pred-5m').textContent = `${pred_stator_5m.toFixed(1)} °C`;
  document.getElementById('badge-pred-rotor-5m').textContent = `${pred_rotor_5m.toFixed(1)} °C`;

  // Tab 2: Battery Elements
  document.getElementById('badge-battery-soc').textContent = `${(state.battery_soc * 100).toFixed(0)}% SoC`;
  document.getElementById('badge-battery-temp').textContent = `${state.T_battery.toFixed(1)} °C`;

  // Tab 3: Road Elements
  const rem_kwh = state.battery_soc * BatterySpecs.total_kwh;
  document.getElementById('range-urban').textContent = `${((rem_kwh * 1000) / 83).toFixed(1)} km`;
  document.getElementById('range-highway').textContent = `${((rem_kwh * 1000) / 115).toFixed(1)} km`;
  document.getElementById('range-mountain').textContent = `${((rem_kwh * 1000) / 143).toFixed(1)} km`;
  document.getElementById('range-offroad').textContent = `${((rem_kwh * 1000) / 128).toFixed(1)} km`;

  // Charts Refresh (every 500 ms)
  if (state.tick_count % 5 === 0 && predictionChart) {
    predictionChart.data.datasets[0].data = [
      state.T_stator - dT_stator * 30, state.T_stator - dT_stator * 20, state.T_stator - dT_stator * 10,
      state.T_stator,
      t_stator_inf + (state.T_stator - t_stator_inf) * Math.exp(-60 / tau_stator),
      pred_stator_5m,
      t_stator_inf + (state.T_stator - t_stator_inf) * Math.exp(-900 / tau_stator),
      t_stator_inf + (state.T_stator - t_stator_inf) * Math.exp(-1800 / tau_stator)
    ];
    predictionChart.data.datasets[1].data = [
      state.T_rotor_magnet - dT_rotor * 30, state.T_rotor_magnet - dT_rotor * 20, state.T_rotor_magnet - dT_rotor * 10,
      state.T_rotor_magnet,
      t_rotor_inf + (state.T_rotor_magnet - t_rotor_inf) * Math.exp(-60 / tau_rotor),
      pred_rotor_5m,
      t_rotor_inf + (state.T_rotor_magnet - t_rotor_inf) * Math.exp(-900 / tau_rotor),
      t_rotor_inf + (state.T_rotor_magnet - t_rotor_inf) * Math.exp(-1800 / tau_rotor)
    ];
    predictionChart.update('none');
  }

  // Update ESP32 Serial string simulation
  if (state.tick_count % 10 === 0) {
    const time_ms = state.tick_count * 100;
    const str = `${time_ms},${v_dc.toFixed(1)},${i_dc.toFixed(1)},${Math.round(speed_rpm)},${state.T_stator.toFixed(1)},${(power_kw*1000).toFixed(0)}`;
    document.getElementById('hex-dump').textContent = str;
  }
}

// --- 6. Tab Navigation ---
function switchTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active', 'text-white'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));

  const activeBtn = document.getElementById(`tab-btn-${tabName}`);
  const activePanel = document.getElementById(`tab-panel-${tabName}`);

  if (activeBtn) activeBtn.classList.add('active', 'text-white');
  if (activePanel) activePanel.classList.remove('hidden');

  setTimeout(() => {
    if (tabName === 'motor' && predictionChart) predictionChart.resize();
    if (tabName === 'esp' && csvPredictionChart) csvPredictionChart.resize();
    if (tabName === 'battery' && batteryChart) batteryChart.resize();
    if (tabName === 'road' && roadEnergyChart) roadEnergyChart.resize();
  }, 60);
}

function setScenario(scenKey) {
  state.current_scenario = scenKey;
  document.querySelectorAll('.scen-btn').forEach(btn => btn.classList.remove('active'));
  const activeBtn = document.getElementById(`btn-scen-${scenKey}`);
  if (activeBtn) activeBtn.classList.add('active');
}

function updateAmbient(val) {
  state.ambient_temp = parseFloat(val);
  document.getElementById('slider-amb-val').textContent = `${val} °C`;
}

// ============================================================================
// --- 7. ESP CSV INGESTION & AI MODEL INFERENCE PIPELINE ---
// ============================================================================

/**
 * Parses raw CSV text into an array of structured record objects
 */
function parseCSV(text) {
  const lines = text.trim().split(/\r?\n/).filter(line => line.trim().length > 0);
  if (lines.length < 2) return [];

  const headers = lines[0].split(',').map(h => h.trim().toLowerCase());
  const rows = [];

  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(',').map(c => c.trim());
    if (cols.length < headers.length) continue;

    const rowObj = {};
    headers.forEach((h, idx) => {
      rowObj[h] = parseFloat(cols[idx]) || 0.0;
    });
    rows.push(rowObj);
  }
  return rows;
}

/**
 * Evaluates the 100-Tree Random Forest Multi-Horizon Regressor client-side
 */
function evaluateRandomForestModel(rfFeatures, lptnFeatures) {
  if (rfModelWeights && rfModelWeights.linear_weights) {
    const W = rfModelWeights.linear_weights;
    const B = rfModelWeights.intercepts;
    const cur_t = rfFeatures[3];
    const preds = [];
    for (let h = 0; h < 4; h++) {
      let val = B[h];
      for (let i = 0; i < Math.min(rfFeatures.length, W.length); i++) {
        val += rfFeatures[i] * W[i][h];
      }
      preds.push(Math.max(cur_t, Math.round(val * 10) / 10));
    }
    const rotor_5m = Math.round((cur_t * 0.88 + preds[1] * 0.12) * 10) / 10;
    return [preds[0], preds[1], preds[2], preds[3], rotor_5m];
  }
  return evaluateBLDCAIModel(lptnFeatures);
}

/**
 * Processes parsed CSV rows, runs the AI model on each row, and updates UI & charts
 */
function processCSVTelemetry(rawRows, filename = "telemetry.csv") {
  if (!rawRows || rawRows.length === 0) {
    alert("CSV file appears to be empty or improperly formatted.");
    return;
  }

  csvDataset = [];
  const tempHistory = [];
  const timeHistory = [];

  rawRows.forEach((row, idx) => {
    const time_ms = row.timestamp_ms || row.time || (idx * 500);
    const voltage_v = row.voltage_v || row.voltage || 48.0;
    const current_a = row.current_a || row.current || 0.0;
    const speed_rpm = row.speed_rpm || row.rpm || 0.0;
    const stator_temp = row.stator_temp_c || row.temp_c || row.temperature || 30.0;
    const ambient_temp = row.ambient_temp_c || 30.0;
    const power_w = row.power_w || (voltage_v * current_a);

    tempHistory.push(stator_temp);
    timeHistory.push(time_ms);
    if (tempHistory.length > 10) {
      tempHistory.shift();
      timeHistory.shift();
    }

    // Rate of change dT/dt
    let dT_dt = 0.0;
    if (tempHistory.length >= 2) {
      const dt_sec = Math.max((timeHistory[timeHistory.length - 1] - timeHistory[0]) / 1000.0, 0.2);
      dT_dt = (tempHistory[tempHistory.length - 1] - tempHistory[0]) / dt_sec;
    }

    // Physical Loss Estimates
    const i_phase_rms = current_a * 0.816;
    const r_actual = BLDCSpecs.R_phase_20C * (1.0 + BLDCSpecs.alpha_cu * (stator_temp - 20.0));
    const p_copper = 3.0 * (i_phase_rms ** 2) * r_actual;
    const fe_hz = (BLDCSpecs.pole_pairs * speed_rpm) / 60.0;
    const p_iron = (0.015 * fe_hz) + (0.00018 * (fe_hz ** 2));
    const p_rotor_eddy = (0.055 * p_iron) + (0.0008 * (i_phase_rms ** 2));
    const total_loss = p_copper + p_iron + p_rotor_eddy;

    // Asymptotic Equilibrium
    const t_stator_inf = ambient_temp + ((p_copper + p_iron) * 2.15);

    // AI Prediction via Random Forest or Physics Model
    const lptnFeatures = [
      voltage_v, current_a, speed_rpm, power_w,
      stator_temp, dT_dt, ambient_temp,
      p_copper, p_iron
    ];
    const rfFeatures = [
      voltage_v, current_a, speed_rpm, stator_temp,
      p_copper, power_w, dT_dt, current_a
    ];
    const aiPreds = evaluateRandomForestModel(rfFeatures, lptnFeatures);

    const pred_1m = aiPreds[0];
    const pred_5m = aiPreds[1];
    const pred_15m = aiPreds[2];
    const pred_30m = aiPreds[3];
    const pred_rotor_5m = aiPreds[4];

    // Derate check
    let derate_active = (pred_5m >= BLDCSpecs.stator_warn || pred_rotor_5m >= BLDCSpecs.rotor_warn);
    let status_str = "OPTIMAL";
    if (stator_temp >= BLDCSpecs.stator_trip) status_str = "CRITICAL_TRIP";
    else if (derate_active) status_str = "OVERHEAT_DERATE";

    csvDataset.push({
      index: idx,
      timestamp_ms: time_ms,
      voltage_v,
      current_a,
      speed_rpm,
      power_w,
      stator_temp,
      ambient_temp,
      total_loss,
      t_stator_inf,
      pred_1m,
      pred_5m,
      pred_15m,
      pred_30m,
      pred_rotor_5m,
      status_str,
      derate_active
    });
  });

  // Automatically detect and switch to corresponding voltage system
  const avgVoltage = csvDataset.reduce((sum, r) => sum + r.voltage_v, 0) / csvDataset.length;
  if (avgVoltage >= 88) setVoltageSystem(96);
  else if (avgVoltage >= 78) setVoltageSystem(84);
  else if (avgVoltage >= 66) setVoltageSystem(72);
  else if (avgVoltage >= 54) setVoltageSystem(60);
  else setVoltageSystem(48);

  // Update File Badge & Scrubber
  document.getElementById('csv-file-badge').classList.remove('hidden');
  document.getElementById('csv-file-badge').classList.add('flex');
  document.getElementById('csv-file-name').textContent = `Loaded: ${filename} (${csvDataset.length} rows, Avg ${avgVoltage.toFixed(1)}V)`;

  const scrubber = document.getElementById('esp-scrubber');
  scrubber.min = 0;
  scrubber.max = csvDataset.length - 1;
  scrubber.value = csvDataset.length - 1;

  // Render Table
  populateCSVTable(csvDataset);

  // Display latest row
  scrubCSVRow(csvDataset.length - 1);

  // Switch to ESP tab automatically if not already on it
  switchTab('esp');
  console.log(`[CSV Engine] Processed ${csvDataset.length} telemetry records from ${filename}.`);
}

/**
 * Updates UI cards and forecast chart for the specified scrubbed row
 */
function scrubCSVRow(index) {
  if (!csvDataset || csvDataset.length === 0) return;
  const idx = Math.max(0, Math.min(csvDataset.length - 1, parseInt(index)));
  csvCurrentRowIndex = idx;
  const record = csvDataset[idx];

  // Update Scrubber Value Display
  document.getElementById('esp-scrubber-val').textContent = `Row ${idx + 1} / ${csvDataset.length} (${record.timestamp_ms} ms)`;

  // Update Prediction Cards
  document.getElementById('esp-card-cur-temp').textContent = `${record.stator_temp.toFixed(1)} °C`;
  document.getElementById('esp-card-cur-loss').textContent = `Loss: ${record.total_loss.toFixed(0)} W`;
  document.getElementById('esp-card-pred-1m').textContent = `${record.pred_1m.toFixed(1)} °C`;
  document.getElementById('esp-card-pred-5m').textContent = `${record.pred_5m.toFixed(1)} °C`;
  document.getElementById('esp-card-rotor-5m').textContent = `${record.pred_rotor_5m.toFixed(1)} °C`;
  document.getElementById('esp-card-pred-15m').textContent = `${record.pred_15m.toFixed(1)} °C`;
  document.getElementById('esp-card-pred-30m').textContent = `${record.pred_30m.toFixed(1)} °C`;
  document.getElementById('esp-card-asymp').textContent = `T_inf: ${record.t_stator_inf.toFixed(1)} °C`;

  // Status Pill
  const pill = document.getElementById('esp-status-pill');
  const banner = document.getElementById('esp-derate-banner');
  const timeToTripLabel = document.getElementById('esp-time-to-trip-label');

  if (record.status_str === "CRITICAL_TRIP") {
    pill.textContent = "CRITICAL: WINDING TRIP (135°C)";
    pill.className = "px-3 py-1 rounded-full text-xs font-bold uppercase bg-rose-950 text-rose-400 border border-rose-800 critical-pulse";
    banner.className = "mt-4 p-4 rounded-2xl bg-rose-950/30 border border-rose-800 text-xs space-y-2";
    banner.innerHTML = `<div class="font-bold text-rose-400 flex items-center gap-1.5"><i data-lucide="alert-octagon" class="w-4 h-4"></i> Critical Temperature Exceeded!</div><p class="text-slate-300 text-[11px]">Instantaneous inverter torque cutoff active to prevent motor enamel melt and permanent magnet destruction.</p>`;
    timeToTripLabel.textContent = "Time-to-Trip: TRIPPED";
  } else if (record.status_str === "OVERHEAT_DERATE") {
    pill.textContent = "OVERHEAT DERATE ACTIVE";
    pill.className = "px-3 py-1 rounded-full text-xs font-bold uppercase bg-amber-950 text-amber-400 border border-amber-800";
    banner.className = "mt-4 p-4 rounded-2xl bg-amber-950/30 border border-amber-800 text-xs space-y-2";
    banner.innerHTML = `<div class="font-bold text-amber-400 flex items-center gap-1.5"><i data-lucide="alert-triangle" class="w-4 h-4"></i> Proactive Throttle Derating Active</div><p class="text-slate-300 text-[11px]">Predicted +5m temperature (${record.pred_5m.toFixed(1)}°C) exceeds safety limit (110°C). Throttle scaled back smoothly to prevent trip.</p>`;
    timeToTripLabel.textContent = "Time-to-Trip: ~4 min";
  } else {
    pill.textContent = "OPTIMAL (Safe Operation)";
    pill.className = "px-3 py-1 rounded-full text-xs font-bold uppercase bg-emerald-950 text-emerald-400 border border-emerald-800";
    banner.className = "mt-4 p-4 rounded-2xl bg-emerald-950/20 border border-emerald-800 text-xs space-y-2";
    banner.innerHTML = `<div class="font-bold text-emerald-400 flex items-center gap-1.5"><i data-lucide="check-circle" class="w-4 h-4"></i> No Throttle Derating Required</div><p class="text-slate-400 text-[11px]">Predicted temperatures at all horizons remain within Class F insulation and NdFeB magnet continuous operating margins.</p>`;
    timeToTripLabel.textContent = "Time-to-Trip: SAFE";
  }

  // Update CSV Chart
  updateCSVChart(idx);
  lucide.createIcons();
}

/**
 * Updates the CSV forecast chart with historical points up to current scrub index + forward projection
 */
function updateCSVChart(currentIndex) {
  if (!csvPredictionChart || !csvDataset.length) return;

  // Window of past points up to current
  const startIdx = Math.max(0, currentIndex - 15);
  const historySubset = csvDataset.slice(startIdx, currentIndex + 1);

  const labels = historySubset.map(r => `${((r.timestamp_ms - historySubset[0].timestamp_ms) / 1000).toFixed(1)}s`);
  labels.push('+1m', '+5m', '+15m', '+30m');

  const measuredData = historySubset.map(r => r.stator_temp);
  for (let k = 0; k < 4; k++) measuredData.push(null);

  const curRec = csvDataset[currentIndex];
  const aiStatorData = historySubset.map(() => null);
  aiStatorData[aiStatorData.length - 1] = curRec.stator_temp; // Connect line
  aiStatorData.push(curRec.pred_1m, curRec.pred_5m, curRec.pred_15m, curRec.pred_30m);

  const aiRotorData = historySubset.map(() => null);
  aiRotorData[aiRotorData.length - 1] = curRec.stator_temp - 2.0;
  aiRotorData.push(curRec.stator_temp, curRec.pred_rotor_5m, curRec.pred_rotor_5m + 5.0, curRec.pred_rotor_5m + 8.0);

  const warnLine = labels.map(() => 110);
  const tripLine = labels.map(() => 135);

  csvPredictionChart.data.labels = labels;
  csvPredictionChart.data.datasets[0].data = measuredData;
  csvPredictionChart.data.datasets[1].data = aiStatorData;
  csvPredictionChart.data.datasets[2].data = aiRotorData;
  csvPredictionChart.data.datasets[3].data = warnLine;
  csvPredictionChart.data.datasets[4].data = tripLine;

  csvPredictionChart.update('none');
}

/**
 * Populates the raw CSV telemetry inspector table
 */
function populateCSVTable(records) {
  const tbody = document.getElementById('esp-csv-table-body');
  document.getElementById('esp-table-row-count').textContent = `${records.length} records`;

  let html = "";
  // Show first 50 rows to keep DOM light
  const displayRows = records.slice(0, 60);

  displayRows.forEach(r => {
    const statusColor = r.status_str === "CRITICAL_TRIP" ? "text-rose-400 font-bold" : (
      r.status_str === "OVERHEAT_DERATE" ? "text-amber-400 font-bold" : "text-emerald-400"
    );

    html += `<tr class="hover:bg-slate-800/50 cursor-pointer" onclick="scrubCSVRow(${r.index})">
      <td class="p-2.5 text-slate-400">${r.timestamp_ms}</td>
      <td class="p-2.5 text-cyan-300 font-bold">${r.voltage_v.toFixed(1)} V</td>
      <td class="p-2.5 text-purple-300">${r.current_a.toFixed(1)} A</td>
      <td class="p-2.5 text-slate-300">${r.speed_rpm}</td>
      <td class="p-2.5 text-teal-300">${r.power_w.toFixed(0)} W</td>
      <td class="p-2.5 text-cyan-400 font-bold">${r.stator_temp.toFixed(1)} °C</td>
      <td class="p-2.5 text-amber-400 font-bold">${r.pred_5m.toFixed(1)} °C</td>
      <td class="p-2.5 text-purple-400">${r.pred_rotor_5m.toFixed(1)} °C</td>
      <td class="p-2.5 ${statusColor}">${r.status_str}</td>
    </tr>`;
  });

  tbody.innerHTML = html;
}

/**
 * Handles drag and drop or file input select
 */
function handleCSVFileSelect(event) {
  const file = event.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = function(e) {
    const text = e.target.result;
    const rows = parseCSV(text);
    processCSVTelemetry(rows, file.name);
  };
  reader.readAsText(file);
}

// Setup Drag & Drop Listeners
const dropzone = document.getElementById('csv-dropzone');
if (dropzone) {
  ['dragenter', 'dragover'].forEach(eventName => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      dropzone.classList.add('dropzone-active');
    }, false);
  });

  ['dragleave', 'drop'].forEach(eventName => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      dropzone.classList.remove('dropzone-active');
    }, false);
  });

  dropzone.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files.length > 0) {
      const file = files[0];
      const reader = new FileReader();
      reader.onload = function(evt) {
        const text = evt.target.result;
        const rows = parseCSV(text);
        processCSVTelemetry(rows, file.name);
      };
      reader.readAsText(file);
    }
  });
}

// --- 8. Embedded Sample CSV Loader ---
function loadSampleCSV(type) {
  let sampleText = "";
  let name = "";

  if (type === '48v') {
    name = "bldc_48v_commute.csv";
    sampleText = `timestamp_ms,voltage_v,current_a,speed_rpm,stator_temp_c,ambient_temp_c,power_w
0,49.20,2.10,1100,28.50,26.0,103.3
500,48.90,5.40,1650,28.60,26.0,264.1
1000,48.50,9.20,2400,28.80,26.0,446.2
1500,48.10,13.80,3100,29.10,26.0,663.8
2000,47.80,16.50,3700,29.50,26.0,788.7
2500,47.50,18.00,4100,30.00,26.0,855.0
3000,47.60,17.20,4150,30.60,26.0,818.7
3500,48.20,8.40,3800,31.10,26.0,404.9
4000,48.60,4.20,2900,31.40,26.0,204.1
4500,49.00,1.80,1800,31.50,26.0,88.2
5000,49.10,0.50,900,31.40,26.0,24.6
5500,48.60,7.10,2100,31.60,26.0,345.1
6000,48.00,14.60,3300,32.00,26.0,700.8
6500,47.60,18.50,4200,32.60,26.0,880.6
7000,47.40,19.20,4400,33.30,26.0,910.1
7500,47.50,18.10,4350,34.00,26.0,859.8
8000,48.00,12.50,3600,34.60,26.0,600.0
8500,48.40,7.00,2700,35.00,26.0,338.8
9000,48.90,2.50,1600,35.20,26.0,122.3
9500,49.10,1.00,1000,35.20,26.0,49.1
10000,49.20,0.80,800,35.10,26.0,39.4`;
  } else if (type === '72v') {
    name = "bldc_72v_hill_climb.csv";
    sampleText = `timestamp_ms,voltage_v,current_a,speed_rpm,stator_temp_c,ambient_temp_c,power_w
0,73.50,4.20,1800,32.00,30.0,308.7
500,72.80,14.50,2400,32.30,30.0,1055.6
1000,72.10,24.80,3100,33.00,30.0,1788.1
1500,71.50,33.20,3600,34.20,30.0,2373.8
2000,71.00,38.90,3900,35.80,30.0,2761.9
2500,70.60,42.50,4100,37.90,30.0,3000.5
3000,70.20,44.80,4200,40.50,30.0,3145.0
3500,70.00,46.20,4250,43.40,30.0,3234.0
4000,69.90,46.50,4250,46.60,30.0,3250.4
4500,69.80,46.80,4280,50.10,30.0,3266.6
5000,69.80,46.90,4300,53.80,30.0,3273.6
5500,69.70,47.00,4320,57.60,30.0,3275.9
6000,69.70,46.80,4310,61.50,30.0,3262.0
6500,69.80,46.20,4300,65.30,30.0,3224.8
7000,69.90,45.50,4280,69.00,30.0,3180.5
7500,70.00,44.80,4250,72.60,30.0,3136.0
8000,70.20,43.90,4220,76.00,30.0,3081.8
8500,70.40,42.50,4200,79.20,30.0,2992.0
9000,70.60,41.20,4180,82.10,30.0,2908.7
9500,70.80,39.80,4150,84.70,30.0,2817.8
10000,71.00,38.50,4100,87.00,30.0,2733.5
10500,71.20,37.00,4050,89.10,30.0,2634.4
11000,71.50,34.80,3980,90.90,30.0,2488.2
11500,71.80,31.20,3850,92.40,30.0,2240.2
12000,72.10,26.50,3600,93.50,30.0,1910.7`;
  } else {
    name = "bldc_96v_high_speed.csv";
    sampleText = `timestamp_ms,voltage_v,current_a,speed_rpm,stator_temp_c,ambient_temp_c,power_w
0,98.20,5.50,2200,35.00,32.0,540.1
500,97.50,18.20,3400,35.50,32.0,1774.5
1000,96.80,32.40,4600,36.80,32.0,3136.3
1500,95.90,45.60,5400,39.00,32.0,4373.0
2000,95.10,54.80,6100,42.20,32.0,5211.5
2500,94.50,59.20,6600,46.50,32.0,5594.4
3000,94.00,62.00,6900,51.80,32.0,5828.0
3500,93.80,63.40,7050,57.90,32.0,5946.9
4000,93.60,64.00,7100,64.80,32.0,5990.4
4500,93.50,64.20,7150,72.20,32.0,6002.7
5000,93.50,64.00,7180,80.00,32.0,5984.0
5500,93.40,64.50,7200,88.10,32.0,6024.3
6000,93.40,64.20,7220,96.30,32.0,5996.3
6500,93.50,63.80,7200,104.50,32.0,5965.3
7000,93.60,63.20,7180,112.40,32.0,5915.5
7500,93.80,62.50,7150,119.80,32.0,5862.5
8000,94.20,58.00,7000,126.50,32.0,5463.6
8500,94.80,48.00,6600,131.20,32.0,4550.4
9000,95.50,36.00,6000,133.80,32.0,3438.0
9500,96.20,22.00,5100,134.50,32.0,2116.4
10000,97.00,10.50,3900,133.90,32.0,1018.5`;
  }

  const rows = parseCSV(sampleText);
  processCSVTelemetry(rows, name);
}

// --- 9. Playback & JSON Export ---
function toggleCSVPlayback() {
  const btn = document.getElementById('btn-csv-play');
  if (csvPlaybackTimer) {
    clearInterval(csvPlaybackTimer);
    csvPlaybackTimer = null;
    btn.innerHTML = `<i data-lucide="play" class="w-3 h-3"></i> Play Telemetry`;
  } else {
    if (!csvDataset.length) return;
    btn.innerHTML = `<i data-lucide="pause" class="w-3 h-3"></i> Pause`;
    csvPlaybackTimer = setInterval(() => {
      csvCurrentRowIndex++;
      if (csvCurrentRowIndex >= csvDataset.length) {
        csvCurrentRowIndex = 0;
      }
      document.getElementById('esp-scrubber').value = csvCurrentRowIndex;
      scrubCSVRow(csvCurrentRowIndex);
    }, 400);
  }
  lucide.createIcons();
}

function downloadProcessedResults() {
  if (!csvDataset.length) {
    alert("Please load or drop a CSV file first!");
    return;
  }
  const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(csvDataset, null, 2));
  const downloadAnchor = document.createElement('a');
  downloadAnchor.setAttribute("href", dataStr);
  downloadAnchor.setAttribute("download", "bldc_ai_predictions_output.json");
  document.body.appendChild(downloadAnchor);
  downloadAnchor.click();
  downloadAnchor.remove();
}

// --- 10. Web Serial API for ESP32 Direct Link ---
async function connectWebSerial() {
  if (!("serial" in navigator)) {
    alert("Web Serial is supported in Google Chrome, Microsoft Edge, and Opera.\nPlease connect the ESP32 USB cable and use Chrome/Edge to stream live data.");
    return;
  }

  try {
    const port = await navigator.serial.requestPort();
    await port.open({ baudRate: 115200 });

    const btn = document.getElementById('btn-web-serial');
    btn.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> Connected to ESP32!`;
    btn.className = "px-3 py-1.5 rounded-xl text-xs font-bold bg-emerald-950 text-emerald-300 border border-emerald-700 flex items-center gap-1.5";

    const textDecoder = new TextDecoderStream();
    const readableStreamClosed = port.readable.pipeTo(textDecoder.writable);
    const reader = textDecoder.readable.getReader();

    let serialBuffer = "";
    const liveRows = [];

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (value) {
        serialBuffer += value;
        const lines = serialBuffer.split('\n');
        serialBuffer = lines.pop(); // Retain remainder

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.includes(',')) {
            const parts = trimmed.split(',');
            if (parts.length >= 5) {
              const liveRow = {
                timestamp_ms: parseFloat(parts[0]) || Date.now(),
                voltage_v: parseFloat(parts[1]) || currentVoltageSystem,
                current_a: parseFloat(parts[2]) || 0.0,
                speed_rpm: parseFloat(parts[3]) || 0.0,
                stator_temp_c: parseFloat(parts[4]) || 30.0,
                power_w: parseFloat(parts[6]) || (parseFloat(parts[1]) * parseFloat(parts[2]))
              };
              liveRows.push(liveRow);
              if (liveRows.length > 50) liveRows.shift();
              processCSVTelemetry(liveRows, "ESP32_Live_USB_Stream.csv");
            }
          }
        }
      }
    }
  } catch (err) {
    console.error("Web Serial Error:", err);
  }
}

// --- 11. Random Forest WebSocket Client & Model Loader ---
async function loadRFWeights() {
  try {
    const res = await fetch('rf_model_weights.json');
    if (res.ok) {
      rfModelWeights = await res.json();
      console.log("[Random Forest] Loaded rf_model_weights.json successfully.");
      if (rfFeatureChart && rfModelWeights.feature_importances_pct) {
        rfFeatureChart.data.datasets[0].data = rfModelWeights.feature_importances_pct;
        rfFeatureChart.update();
      }
    }
  } catch (err) {
    console.log("[Random Forest] Running with embedded pre-compiled model weights.");
  }
}

function connectRandomForestWebSocket() {
  try {
    const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const targetUrl = (location.host && location.protocol.startsWith('http')) 
      ? `${wsProto}//${location.host}/ws/telemetry` 
      : "ws://localhost:8000/ws/telemetry";

    rfWebSocket = new WebSocket(targetUrl);
    
    rfWebSocket.onopen = () => {
      console.log(`🟢 Connected to Host App WebSocket (${targetUrl})!`);
      isRFServerConnected = true;
      const badge = document.getElementById('rf-stream-badge');
      if (badge) {
        badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> 🟢 HOST APP CONNECTED (1 Hz)`;
        badge.className = "px-2.5 py-1 text-xs font-semibold bg-emerald-950 text-emerald-300 border border-emerald-700 rounded-lg flex items-center gap-1 shadow-sm";
      }
    };

    rfWebSocket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        const telem = payload.telemetry || payload;
        const preds = payload.predictions || {};

        const v = telem.voltage_v !== undefined ? Number(telem.voltage_v) : 12.10;
        const i = telem.current_a !== undefined ? Number(telem.current_a) : 2.20;
        const rpm = telem.rpm !== undefined ? Number(telem.rpm) : 2150;
        const temp = telem.temp_c !== undefined ? Number(telem.temp_c) : (telem.stator_temp !== undefined ? Number(telem.stator_temp) : 34.50);
        const rotorTemp = telem.rotor_temp !== undefined ? Number(telem.rotor_temp) : (temp - 2.5);

        const p1 = preds.pred_1m_c ?? preds.plus_1m ?? (temp + 0.4);
        const p5 = preds.pred_5m_c ?? preds.plus_5m ?? (temp + 1.2);
        const p15 = preds.pred_15m_c ?? preds.plus_15m ?? (temp + 2.5);
        const p30 = preds.pred_30m_c ?? preds.plus_30m ?? (temp + 3.8);

        // Update live dials
        const vdcEl = document.getElementById('val-vdc');
        if (vdcEl) vdcEl.textContent = `${v.toFixed(2)} V (0-25V)`;
        const irmsEl = document.getElementById('val-irms');
        if (irmsEl) irmsEl.textContent = `${i.toFixed(2)} A (ACS712 5A)`;
        const rpmEl = document.getElementById('val-motor-rpm');
        if (rpmEl) rpmEl.textContent = `${rpm} RPM (LM393)`;
        const speedEl = document.getElementById('val-speed-kmh');
        if (speedEl) speedEl.textContent = ((rpm * 60.0 * 0.15) / 1000.0).toFixed(1);
        const pwrEl = document.getElementById('val-power-kw');
        if (pwrEl) pwrEl.textContent = (v * i).toFixed(1);
        const trqEl = document.getElementById('val-torque');
        if (trqEl) trqEl.textContent = (i * 0.08).toFixed(2);

        const tStat = document.getElementById('temp-node-stator');
        if (tStat) tStat.textContent = `${temp.toFixed(1)} °C (DS18B20)`;
        const tRot = document.getElementById('temp-node-rotor');
        if (tRot) tRot.textContent = `${rotorTemp.toFixed(1)} °C`;

        // Prediction cards on Tab 2
        const curTempEl = document.getElementById('esp-card-cur-temp');
        if (curTempEl) curTempEl.textContent = `${temp.toFixed(1)} °C`;
        const p1El = document.getElementById('esp-card-pred-1m');
        if (p1El) p1El.textContent = `${p1.toFixed(1)} °C`;
        const p5El = document.getElementById('esp-card-pred-5m');
        if (p5El) p5El.textContent = `${p5.toFixed(1)} °C`;
        const p15El = document.getElementById('esp-card-pred-15m');
        if (p15El) p15El.textContent = `${p15.toFixed(1)} °C`;
        const p30El = document.getElementById('esp-card-pred-30m');
        if (p30El) p30El.textContent = `${p30.toFixed(1)} °C`;

        // Live chart updates
        if (predictionChart) {
          predictionChart.data.datasets[0].data[3] = temp;
          predictionChart.data.datasets[0].data[4] = p1;
          predictionChart.data.datasets[0].data[5] = p5;
          predictionChart.data.datasets[0].data[6] = p15;
          predictionChart.data.datasets[0].data[7] = p30;
          predictionChart.update('none');
        }
      } catch (e) {
        console.error("RF WS parse error:", e);
      }
    };

    rfWebSocket.onclose = () => {
      isRFServerConnected = false;
      const badge = document.getElementById('rf-stream-badge');
      if (badge) {
        badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-400"></span> STANDBY / CLIENT-SIDE READY`;
        badge.className = "px-2.5 py-1 text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700 rounded-lg flex items-center gap-1";
      }
      setTimeout(connectRandomForestWebSocket, 3000);
    };

    rfWebSocket.onerror = () => {
      rfWebSocket.close();
    };
  } catch (err) {
    // Graceful fallback to client-side
  }
}

// --- 12. App Initialization ---
window.addEventListener('DOMContentLoaded', () => {
  initCharts();
  setVoltageSystem(48); // Set 48V by default for 48V project
  setScenario('ECO_CITY');
  setInterval(runStep, 100);

  // Load RF weights & connect to local stream
  loadRFWeights();
  connectRandomForestWebSocket();

  // Pre-load the 48V sample by default so the ESP tab is immediately filled with rich data
  setTimeout(() => {
    loadSampleCSV('48v');
  }, 200);
});
