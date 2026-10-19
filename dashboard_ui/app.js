/**
 * ============================================================================
 * Aura EV Cockpit - Simple Real-Time AI Telemetry Dashboard
 * Target: 12V DC Motor Continuous Testbed
 * Metrics Displayed:
 *   1. Current Temperature (DS18B20)
 *   2. Voltage (0–25V Sensor)
 *   3. Current (ACS712 5A)
 *   4. Motor Speed / RPM (LM393)
 *   5. Electrical Power (Watts = V * I)
 *   6. Predicted Temperature (+1m, +5m, +15m, +30m Random Forest AI)
 * ============================================================================
 */

// Global Chart Instance
let liveTempChart = null;
let maxChartPoints = 25;
let timeLabels = [];
let measuredTempData = [];
let pred1mData = [];
let pred5mData = [];
let pred30mData = [];

let webSocket = null;
let isConnected = false;
let currentActiveModel = 'ridge';
let latestAllModels = {};

const MODEL_SPECS = {
  ridge: {
    title: "RIDGE REGRESSION",
    mae: "3.07 °C",
    rmse: "3.82 °C",
    size: "2 KB",
    latency: "0.31 ms",
    badge: "Beats Both Baselines on Test Set ✅",
    badgeClass: "bg-emerald-950/80 text-emerald-400 border-emerald-800"
  },
  gru: {
    title: "PYTORCH GRU SEQUENCE",
    mae: "3.35 °C",
    rmse: "4.04 °C",
    size: "19 KB",
    latency: "1.56 ms",
    badge: "Deep Learning Sequence Model (120s Window)",
    badgeClass: "bg-cyan-950/80 text-cyan-400 border-cyan-800"
  },
  physics_fit: {
    title: "PHYSICS HEATING CURVE (ODE)",
    mae: "3.28 °C",
    rmse: "3.99 °C",
    size: "0.1 KB",
    latency: "0.02 ms",
    badge: "Fitted 1st-Order Thermal Plant ODE",
    badgeClass: "bg-blue-950/80 text-blue-400 border-blue-800"
  },
  lightgbm: {
    title: "LIGHTGBM GRADIENT BOOSTING",
    mae: "3.58 °C",
    rmse: "4.25 °C",
    size: "59 KB",
    latency: "7.02 ms",
    badge: "Tabular Boosted Decision Trees",
    badgeClass: "bg-amber-950/80 text-amber-400 border-amber-800"
  },
  random_forest: {
    title: "RANDOM FOREST (100 TREES)",
    mae: "3.96 °C",
    rmse: "4.71 °C",
    size: "4,790 KB",
    latency: "42.5 ms",
    badge: "Standard Multi-Tree Reference Ensemble",
    badgeClass: "bg-purple-950/80 text-purple-400 border-purple-800"
  },
  persistence: {
    title: "PERSISTENCE (ΔT = 0)",
    mae: "4.05 °C",
    rmse: "4.66 °C",
    size: "0 KB",
    latency: "0.00 ms",
    badge: "Baseline: 'Temperature Stays The Same'",
    badgeClass: "bg-slate-900 text-slate-400 border-slate-800"
  }
};

async function loadModelRegistrySpecs() {
  try {
    const res = await fetch('/api/ml/status');
    if (!res.ok) return;
    const data = await res.json();
    if (!data.available || !data.models) return;

    for (const [key, m] of Object.entries(data.models)) {
      if (MODEL_SPECS[key]) {
        if (m.test_mae !== undefined) MODEL_SPECS[key].mae = `${Number(m.test_mae).toFixed(2)} °C`;
        if (m.test_rmse !== undefined) MODEL_SPECS[key].rmse = `${Number(m.test_rmse).toFixed(2)} °C`;
        if (m.size_bytes !== undefined) MODEL_SPECS[key].size = `${Math.round(m.size_bytes / 1024)} KB`;
        if (m.latency_ms !== undefined) MODEL_SPECS[key].latency = `${Number(m.latency_ms).toFixed(2)} ms`;
      }
    }

    if (data.active_model && MODEL_SPECS[data.active_model]) {
      switchActiveModel(data.active_model);
    } else {
      switchActiveModel(currentActiveModel);
    }
  } catch (err) {
    console.warn("[MODEL SPECS] Could not load dynamic registry:", err);
  }
}

window.switchActiveModel = function(modelKey) {
  if (!MODEL_SPECS[modelKey]) return;
  currentActiveModel = modelKey;

  // 1. Update button styling
  document.querySelectorAll('.model-toggle-btn').forEach(btn => {
    btn.className = "model-toggle-btn px-3 py-1.5 rounded-xl text-xs font-medium transition-all bg-slate-900 text-slate-400 border border-slate-800 hover:text-slate-200 hover:border-slate-600";
  });
  const activeBtn = document.getElementById(`btn-model-${modelKey}`);
  if (activeBtn) {
    activeBtn.className = "model-toggle-btn px-3 py-1.5 rounded-xl text-xs font-bold transition-all bg-cyan-900/80 text-cyan-200 border border-cyan-500 shadow-md shadow-cyan-500/20";
  }

  // 2. Update Model Specs Ribbon
  const spec = MODEL_SPECS[modelKey];
  const titleEl = document.getElementById('active-model-title');
  if (titleEl) titleEl.textContent = `Active: ${spec.title}`;
  const maeEl = document.getElementById('spec-mae');
  if (maeEl) maeEl.textContent = spec.mae;
  const rmseEl = document.getElementById('spec-rmse');
  if (rmseEl) rmseEl.textContent = spec.rmse;
  const sizeEl = document.getElementById('spec-size');
  if (sizeEl) sizeEl.textContent = spec.size;
  const latEl = document.getElementById('spec-latency');
  if (latEl) latEl.textContent = spec.latency;
  const skillEl = document.getElementById('spec-skill');
  if (skillEl) {
    skillEl.textContent = spec.badge;
    skillEl.className = `px-2 py-0.5 rounded-md text-[11px] font-bold border ${spec.badgeClass}`;
  }

  // 3. Inform Backend Server
  fetch('/api/ml/select_model', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: modelKey })
  }).catch(() => {});

  // 4. Update Prediction Display Immediately if cached
  if (latestAllModels && latestAllModels[modelKey]) {
    const m = latestAllModels[modelKey];
    const p1El = document.getElementById('pred-1m');
    if (p1El && m['1m'] !== undefined) p1El.textContent = Number(m['1m']).toFixed(1);
    const p5El = document.getElementById('pred-5m');
    if (p5El && m['5m'] !== undefined) p5El.textContent = Number(m['5m']).toFixed(1);
    const p15El = document.getElementById('pred-15m');
    if (p15El && m['15m'] !== undefined) p15El.textContent = Number(m['15m']).toFixed(1);
    const p30El = document.getElementById('pred-30m');
    if (p30El && m['30m'] !== undefined) p30El.textContent = Number(m['30m']).toFixed(1);
  }
};

// Initialize Live Chart
function initLiveChart() {
  const ctx = document.getElementById('liveTempChart');
  if (!ctx) return;

  liveTempChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: timeLabels,
      datasets: [
        {
          label: 'Measured Temp (Now)',
          data: measuredTempData,
          borderColor: '#f43f5e', // Rose
          backgroundColor: 'rgba(244, 63, 94, 0.15)',
          borderWidth: 2.5,
          tension: 0.3,
          fill: true,
          pointRadius: 3,
          pointBackgroundColor: '#f43f5e'
        },
        {
          label: '+1 Min Forecast',
          data: pred1mData,
          borderColor: '#22d3ee', // Cyan
          borderWidth: 2,
          borderDash: [4, 4],
          tension: 0.3,
          fill: false,
          pointRadius: 2,
          pointBackgroundColor: '#22d3ee'
        },
        {
          label: '+5 Min Forecast',
          data: pred5mData,
          borderColor: '#fbbf24', // Amber
          borderWidth: 2,
          borderDash: [5, 5],
          tension: 0.3,
          fill: false,
          pointRadius: 2,
          pointBackgroundColor: '#fbbf24'
        },
        {
          label: '+30 Min Forecast',
          data: pred30mData,
          borderColor: '#c084fc', // Purple
          borderWidth: 2,
          borderDash: [6, 4],
          tension: 0.3,
          fill: false,
          pointRadius: 2,
          pointBackgroundColor: '#c084fc'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: 'index',
          intersect: false,
          backgroundColor: '#0f172a',
          titleColor: '#e2e8f0',
          bodyColor: '#94a3b8',
          borderColor: '#334155',
          borderWidth: 1,
          padding: 10
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(51, 65, 85, 0.25)' },
          ticks: { color: '#64748b', font: { family: 'monospace', size: 10 } }
        },
        y: {
          grid: { color: 'rgba(51, 65, 85, 0.25)' },
          ticks: {
            color: '#64748b',
            font: { family: 'monospace', size: 10 },
            callback: (val) => `${val}°C`
          },
          suggestedMin: 25,
          suggestedMax: 60
        }
      }
    }
  });
}

// Update Dashboard UI with latest values
function updateDashboardUI(v, i, rpm, temp, pwr, torque, p1, p5, p15, p30, source, preds, telem) {
  // Ambient Temperature Indicator
  const ambEl = document.getElementById('ambient-indicator');
  if (ambEl && telem) {
    const ambVal = (telem.ambient_temp_c !== undefined && telem.ambient_temp_c !== null)
      ? Number(telem.ambient_temp_c).toFixed(1)
      : '28.0';
    if (telem.ambient_measured) {
      ambEl.innerHTML = `Ambient: ${ambVal}°C <span class="text-emerald-400 font-bold">(Sensor)</span>`;
    } else {
      ambEl.innerHTML = `Ambient: ${ambVal}°C <span class="text-slate-500 font-normal">(Nominal)</span>`;
    }
  }

  // 1. Current Temperature
  const tempEl = document.getElementById('val-temp');
  const statusEl = document.getElementById('temp-status');
  const isTempValid = temp !== null && !isNaN(temp) && temp > -50 && temp < 150;

  if (tempEl) {
    tempEl.textContent = isTempValid ? temp.toFixed(1) : '--';
  }

  if (statusEl) {
    if (!isTempValid) {
      statusEl.textContent = "Sensor Disconnected";
      statusEl.className = "text-rose-400 font-bold";
    } else if (temp < 45.0) {
      statusEl.textContent = "Optimal";
      statusEl.className = "text-emerald-400 font-semibold";
    } else if (temp < 60.0) {
      statusEl.textContent = "Elevated";
      statusEl.className = "text-amber-400 font-semibold";
    } else {
      statusEl.textContent = "High Temp";
      statusEl.className = "text-rose-400 font-bold";
    }
  }

  // 2. Voltage
  const voltEl = document.getElementById('val-voltage');
  if (voltEl) voltEl.textContent = (v !== null && !isNaN(v)) ? v.toFixed(2) : '--';

  // 3. Current
  const currEl = document.getElementById('val-current');
  if (currEl) currEl.textContent = (i !== null && !isNaN(i)) ? i.toFixed(2) : '--';

  // 4. Motor RPM
  const rpmEl = document.getElementById('val-rpm');
  if (rpmEl) rpmEl.textContent = (rpm !== null && !isNaN(rpm)) ? Math.round(rpm) : '--';

  // 5. Electrical Power
  const pwrEl = document.getElementById('val-power');
  if (pwrEl) pwrEl.textContent = (pwr !== null && !isNaN(pwr)) ? pwr.toFixed(1) : '--';

  // 6. Motor Torque (Nm)
  const torqueEl = document.getElementById('val-torque');
  if (torqueEl) torqueEl.textContent = (torque !== null && !isNaN(torque)) ? torque.toFixed(2) : '--';

  // 7. Predicted Temperatures
  const p1El = document.getElementById('pred-1m');
  if (p1El) p1El.textContent = (p1 !== null && !isNaN(p1)) ? p1.toFixed(1) : '--';

  const p5El = document.getElementById('pred-5m');
  if (p5El) p5El.textContent = (p5 !== null && !isNaN(p5)) ? p5.toFixed(1) : '--';

  const p15El = document.getElementById('pred-15m');
  if (p15El) p15El.textContent = (p15 !== null && !isNaN(p15)) ? p15.toFixed(1) : '--';

  const p30El = document.getElementById('pred-30m');
  if (p30El) p30El.textContent = (p30 !== null && !isNaN(p30)) ? p30.toFixed(1) : '--';

  // 8. Update Data Source Badge
  const sourceBadge = document.getElementById('source-badge');
  if (sourceBadge) {
    if (source === 'ESP32_WIFI_HARDWARE') {
      sourceBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> HARDWARE: ESP32 WI-FI`;
      sourceBadge.className = "px-2 py-0.5 text-xs font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800 rounded-full flex items-center gap-1.5";
    } else if (source === 'SIMULATOR_HARDWARE_OFFLINE') {
      sourceBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-400 animate-ping"></span> SIMULATOR (HW DROPPED)`;
      sourceBadge.className = "px-2 py-0.5 text-xs font-semibold bg-amber-950 text-amber-400 border border-amber-800 rounded-full flex items-center gap-1.5";
    } else {
      sourceBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-slate-400"></span> SIMULATOR (DEMO)`;
      sourceBadge.className = "px-2 py-0.5 text-xs font-semibold bg-slate-900 text-slate-400 border border-slate-800 rounded-full flex items-center gap-1.5";
    }
  }

  // 9. Update Model Badge
  const modelBadge = document.getElementById('model-badge');
  if (modelBadge && preds) {
    const modelName = preds.forecast_model || 'Unknown';
    const status = preds.forecast_status || '';
    const warmup = preds.warmup_seconds_left || 0;
    if (status === 'ml_ready') {
      modelBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-cyan-400"></span> MODEL: ${modelName.toUpperCase()}`;
      modelBadge.className = "px-2 py-0.5 text-xs font-semibold bg-cyan-950 text-cyan-300 border border-cyan-800 rounded-full flex items-center gap-1.5";
    } else if (status === 'ml_warming_up') {
      modelBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-400"></span> WARMING UP (${warmup}s) -> PHYSICS FALLBACK`;
      modelBadge.className = "px-2 py-0.5 text-xs font-semibold bg-amber-950 text-amber-300 border border-amber-800 rounded-full flex items-center gap-1.5";
    } else {
      modelBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-purple-400"></span> MODEL: ${modelName}`;
      modelBadge.className = "px-2 py-0.5 text-xs font-semibold bg-purple-950 text-purple-300 border border-purple-800 rounded-full flex items-center gap-1.5";
    }
  }

  // Update Clock
  const now = new Date();
  const timeStr = now.toTimeString().split(' ')[0];
  const timeEl = document.getElementById('system-time');
  if (timeEl) timeEl.textContent = timeStr;

  // Append to Chart only if temp is valid
  if (liveTempChart && isTempValid) {
    timeLabels.push(timeStr);
    measuredTempData.push(temp);
    pred1mData.push(p1);
    pred5mData.push(p5);
    pred30mData.push(p30);

    if (timeLabels.length > maxChartPoints) {
      timeLabels.shift();
      measuredTempData.shift();
      pred1mData.shift();
      pred5mData.shift();
      pred30mData.shift();
    }

    liveTempChart.update('none');
  }
}

// Update Future Energy & Road UI
function updateEnergyUI(energy) {
  if (!energy) return;

  // 1. Cumulative Energy
  const totalEl = document.getElementById('val-energy-total');
  if (totalEl && energy.cumulative_wh !== undefined) {
    totalEl.textContent = Number(energy.cumulative_wh).toFixed(2);
  }

  // 2. Consumption Rate
  const rateEl = document.getElementById('val-energy-rate');
  if (rateEl && energy.instant_wh_per_km !== undefined) {
    rateEl.textContent = Number(energy.instant_wh_per_km).toFixed(1);
  }

  // 3. Remaining Range
  const rangeEl = document.getElementById('val-remaining-range');
  if (rangeEl && energy.remaining_range_km !== undefined) {
    rangeEl.textContent = Number(energy.remaining_range_km).toFixed(1);
  }

  // 4. Future Energy Horizons
  const e5El = document.getElementById('pred-energy-5m');
  if (e5El && energy.pred_energy_5m_wh !== undefined) {
    e5El.textContent = Number(energy.pred_energy_5m_wh).toFixed(2);
  }

  const e15El = document.getElementById('pred-energy-15m');
  if (e15El && energy.pred_energy_15m_wh !== undefined) {
    e15El.textContent = Number(energy.pred_energy_15m_wh).toFixed(2);
  }

  const e30El = document.getElementById('pred-energy-30m');
  if (e30El && energy.pred_energy_30m_wh !== undefined) {
    e30El.textContent = Number(energy.pred_energy_30m_wh).toFixed(2);
  }

  // 5. Active Road Badge
  const roadBadge = document.getElementById('active-road-badge');
  if (roadBadge && energy.road_name) {
    roadBadge.textContent = `Road: ${energy.road_name}`;
  }

  // 6. Road Comparisons Cards
  const container = document.getElementById('road-cards-container');
  if (container && energy.road_comparisons) {
    let html = '';
    const entries = Object.entries(energy.road_comparisons);
    for (const [key, item] of entries) {
      const isCurrent = (key === energy.current_road);
      const borderClass = isCurrent ? 'border-emerald-500 bg-emerald-950/40 ring-1 ring-emerald-500/50' : 'border-slate-800 bg-slate-950/60 hover:border-slate-700';
      const badgeText = isCurrent ? '<span class="text-[10px] text-emerald-400 font-bold uppercase ml-1">● Active</span>' : '';

      html += `
        <div class="p-3 rounded-xl border ${borderClass} cursor-pointer transition-all" onclick="changeRoadProfile('${key}')">
          <div class="flex items-center justify-between text-[11px] font-bold text-slate-300">
            <span class="truncate">${item.name}</span>
            ${badgeText}
          </div>
          <div class="mt-2 text-slate-400 text-[11px]">
            <div>Rate: <span class="font-bold text-cyan-300">${item.energy_rate_wh_per_km}</span> Wh/km</div>
            <div>Range: <span class="font-bold text-amber-300">${item.projected_range_km}</span> km</div>
            <div>Grade: <span class="text-slate-400">${item.grade_pct}%</span></div>
          </div>
        </div>
      `;
    }
    container.innerHTML = html;
  }
}

// User changes active road profile
window.changeRoadProfile = function(roadKey) {
  const sel = document.getElementById('road-selector');
  if (sel && sel.value !== roadKey) {
    sel.value = roadKey;
  }
  fetch('/api/road_profile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ road_type: roadKey })
  }).catch(() => {});
};

// ============================================================================
// PHASE 3: PROACTIVE THERMAL SAFETY & TIME-TO-THRESHOLD UI
// ============================================================================
function updateThermalSafetyUI(thermalSafety, preds) {
  const banner = document.getElementById('thermal-alert-banner');
  if (!banner) return;

  const level = thermalSafety?.warning_level || 'NORMAL';
  const ttt = thermalSafety?.time_to_threshold_min;
  const advisory = thermalSafety?.advisory || 'Temperature dynamics within safe continuous operating limits.';
  const fallbackActive = preds?.fallback_active || false;
  const fallbackReason = preds?.fallback_reason || null;

  const levelEl = document.getElementById('thermal-alert-level');
  const tttEl = document.getElementById('thermal-alert-ttt');
  const msgEl = document.getElementById('thermal-alert-msg');
  const iconDiv = document.getElementById('thermal-alert-icon');
  const fallbackPill = document.getElementById('fallback-alert-pill');
  const fallbackText = document.getElementById('fallback-alert-text');

  banner.classList.remove('hidden');

  if (level === 'CRITICAL') {
    banner.className = "transition-all duration-300 rounded-2xl p-4 border border-rose-500 bg-rose-950/70 text-rose-200 flex flex-wrap items-center justify-between gap-4 shadow-lg shadow-rose-950/50 animate-pulse";
    if (levelEl) {
      levelEl.textContent = "CRITICAL OVERHEAT ALERT";
      levelEl.className = "text-xs font-black uppercase tracking-wider px-2 py-0.5 rounded-md bg-rose-600 text-white";
    }
    if (iconDiv) {
      iconDiv.className = "p-2.5 rounded-xl bg-rose-500/20 text-rose-300";
      iconDiv.innerHTML = '<i data-lucide="flame" class="w-5 h-5"></i>';
    }
  } else if (level === 'ELEVATED') {
    banner.className = "transition-all duration-300 rounded-2xl p-4 border border-amber-500/80 bg-amber-950/60 text-amber-200 flex flex-wrap items-center justify-between gap-4 shadow-lg shadow-amber-950/40";
    if (levelEl) {
      levelEl.textContent = "ELEVATED THERMAL LOAD";
      levelEl.className = "text-xs font-black uppercase tracking-wider px-2 py-0.5 rounded-md bg-amber-500 text-slate-950 font-bold";
    }
    if (iconDiv) {
      iconDiv.className = "p-2.5 rounded-xl bg-amber-500/20 text-amber-300";
      iconDiv.innerHTML = '<i data-lucide="alert-triangle" class="w-5 h-5"></i>';
    }
  } else if (level === 'SENSOR_OFFLINE') {
    banner.className = "transition-all duration-300 rounded-2xl p-4 border border-rose-800 bg-slate-900 text-rose-300 flex flex-wrap items-center justify-between gap-4 shadow-lg";
    if (levelEl) {
      levelEl.textContent = "SENSOR DISCONNECTED";
      levelEl.className = "text-xs font-black uppercase tracking-wider px-2 py-0.5 rounded-md bg-rose-900 text-rose-200";
    }
    if (iconDiv) {
      iconDiv.className = "p-2.5 rounded-xl bg-rose-900/30 text-rose-400";
      iconDiv.innerHTML = '<i data-lucide="alert-octagon" class="w-5 h-5"></i>';
    }
  } else {
    // NORMAL
    banner.className = "transition-all duration-300 rounded-2xl p-3.5 border border-slate-800/80 bg-slate-900/60 text-slate-300 flex flex-wrap items-center justify-between gap-4 shadow-sm";
    if (levelEl) {
      levelEl.textContent = "THERMAL STATUS: NORMAL";
      levelEl.className = "text-xs font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-emerald-950 text-emerald-400 border border-emerald-800";
    }
    if (iconDiv) {
      iconDiv.className = "p-2 rounded-xl bg-emerald-950 text-emerald-400";
      iconDiv.innerHTML = '<i data-lucide="shield-check" class="w-5 h-5"></i>';
    }
  }

  if (tttEl) {
    if (ttt !== null && ttt !== undefined && ttt > 0) {
      tttEl.textContent = `• Estimated Time-to-55°C Limit: ${ttt.toFixed(1)} min`;
    } else if (ttt === 0.0) {
      tttEl.textContent = `• AT/ABOVE 55°C THRESHOLD`;
    } else {
      tttEl.textContent = `• Equilibrium / Below Threshold`;
    }
  }

  if (msgEl) msgEl.textContent = advisory;

  // Fallback Pill
  if (fallbackPill) {
    if (fallbackActive && fallbackReason) {
      fallbackPill.classList.remove('hidden');
      fallbackPill.className = "px-3 py-1.5 rounded-xl border border-amber-700/80 bg-amber-950/70 text-amber-300 text-xs font-bold font-mono flex items-center gap-2";
      if (fallbackText) fallbackText.textContent = fallbackReason;
    } else {
      fallbackPill.classList.add('hidden');
    }
  }

  if (window.lucide) lucide.createIcons();
}

// ============================================================================
// PHASE 3: CSV RUN RECORDER CONTROLS
// ============================================================================
let isCurrentlyRecording = false;

function updateRecordingUI(rec) {
  const btn = document.getElementById('btn-record-run');
  const dot = document.getElementById('record-dot');
  const text = document.getElementById('record-text');
  if (!btn || !rec) return;

  isCurrentlyRecording = !!rec.is_recording;

  if (isCurrentlyRecording) {
    const mins = Math.floor((rec.duration_seconds || 0) / 60);
    const secs = Math.floor((rec.duration_seconds || 0) % 60);
    const timeFmt = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    btn.className = "flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-rose-500 bg-rose-950/90 text-rose-200 font-bold transition-all text-xs shadow-md shadow-rose-900/30 animate-pulse";
    if (dot) dot.className = "w-2.5 h-2.5 rounded-full bg-rose-400";
    if (text) text.textContent = `REC ${timeFmt} (${rec.rows_recorded} rows)`;
  } else {
    btn.className = "flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-slate-700 bg-slate-800/90 hover:bg-slate-700 text-slate-300 font-bold transition-all text-xs shadow-sm";
    if (dot) dot.className = "w-2.5 h-2.5 rounded-full bg-rose-500";
    if (text) text.textContent = "REC RUN";
  }
}

window.toggleRunRecording = function() {
  const endpoint = isCurrentlyRecording ? '/api/recording/stop' : '/api/recording/start';
  fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ notes: "Web Cockpit manual recording" })
  })
    .then(r => r.json())
    .then(data => {
      console.log("[RECORDER]", data);
    })
    .catch(err => console.error("[RECORDER ERROR]", err));
};

// Connect WebSocket to Python Host Server
function connectWebSocket() {
  const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const targetUrl = (location.host && location.protocol.startsWith('http'))
    ? `${wsProto}//${location.host}/ws/telemetry`
    : "ws://localhost:8000/ws/telemetry";

  try {
    webSocket = new WebSocket(targetUrl);

    webSocket.onopen = () => {
      isConnected = true;
      console.log(`[WS] Connected to Host App (${targetUrl})`);
      const badge = document.getElementById('conn-badge');
      if (badge) {
        badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> LIVE STREAM (1 Hz)`;
        badge.className = "px-2 py-0.5 text-xs font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800 rounded-full flex items-center gap-1.5";
      }
    };

    webSocket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        const telem = payload.telemetry || payload;
        const preds = payload.predictions || {};
        const energy = payload.energy || null;

        const v = telem.voltage_v !== undefined && telem.voltage_v !== null ? Number(telem.voltage_v) : null;
        const i = telem.current_a !== undefined && telem.current_a !== null ? Number(telem.current_a) : null;
        const rpm = telem.rpm !== undefined && telem.rpm !== null ? Number(telem.rpm) : null;
        const temp = telem.temp_c !== undefined && telem.temp_c !== null ? Number(telem.temp_c) : (telem.stator_temp !== undefined ? Number(telem.stator_temp) : null);
        const pwr = (v !== null && i !== null) ? (v * i) : (telem.power_w !== undefined ? Number(telem.power_w) : null);
        const torque = (i !== null) ? Number((i * 0.08).toFixed(2)) : (telem.torque_nm !== undefined ? Number(telem.torque_nm) : null);

        latestAllModels = preds.all_models || {};

        let p1 = preds.pred_1m_c ?? preds.plus_1m ?? null;
        let p5 = preds.pred_5m_c ?? preds.plus_5m ?? null;
        let p15 = preds.pred_15m_c ?? preds.plus_15m ?? null;
        let p30 = preds.pred_30m_c ?? preds.plus_30m ?? null;

        // Display forecasts for whichever model is currently active/selected by the user
        if (latestAllModels && latestAllModels[currentActiveModel]) {
          const m = latestAllModels[currentActiveModel];
          if (m["1m"] !== undefined && m["1m"] !== null) p1 = Number(m["1m"]);
          if (m["5m"] !== undefined && m["5m"] !== null) p5 = Number(m["5m"]);
          if (m["15m"] !== undefined && m["15m"] !== null) p15 = Number(m["15m"]);
          if (m["30m"] !== undefined && m["30m"] !== null) p30 = Number(m["30m"]);
        }

        updateDashboardUI(v, i, rpm, temp, pwr, torque, p1, p5, p15, p30, payload.source, preds, telem);
        if (energy) {
          updateEnergyUI(energy);
        }
        if (payload.thermal_safety || preds) {
          updateThermalSafetyUI(payload.thermal_safety, preds);
        }
        if (payload.recording) {
          updateRecordingUI(payload.recording);
        }
      } catch (err) {
        console.error("Payload error:", err);
      }
    };

    webSocket.onclose = () => {
      isConnected = false;
      const badge = document.getElementById('conn-badge');
      if (badge) {
        badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-400"></span> RECONNECTING...`;
        badge.className = "px-2 py-0.5 text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700 rounded-full flex items-center gap-1.5";
      }
      setTimeout(connectWebSocket, 2000);
    };

    webSocket.onerror = () => {
      if (webSocket) webSocket.close();
    };

  } catch (e) {
    setTimeout(connectWebSocket, 3000);
  }
}

// On Page Load
document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) {
    lucide.createIcons();
  }
  initLiveChart();
  loadModelRegistrySpecs();
  connectWebSocket();
});
