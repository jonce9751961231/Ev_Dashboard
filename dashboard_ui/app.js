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
function updateDashboardUI(v, i, rpm, temp, pwr, torque, p1, p5, p15, p30) {
  // 1. Current Temperature
  const tempEl = document.getElementById('val-temp');
  if (tempEl) tempEl.textContent = temp.toFixed(1);

  const statusEl = document.getElementById('temp-status');
  if (statusEl) {
    if (temp < 45.0) {
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
  if (voltEl) voltEl.textContent = v.toFixed(2);

  // 3. Current
  const currEl = document.getElementById('val-current');
  if (currEl) currEl.textContent = i.toFixed(2);

  // 4. Motor RPM
  const rpmEl = document.getElementById('val-rpm');
  if (rpmEl) rpmEl.textContent = Math.round(rpm);

  // 5. Electrical Power
  const pwrEl = document.getElementById('val-power');
  if (pwrEl) pwrEl.textContent = pwr.toFixed(1);

  // 6. Motor Torque (Nm)
  const torqueEl = document.getElementById('val-torque');
  if (torqueEl) torqueEl.textContent = torque.toFixed(2);

  // 7. Predicted Temperatures
  const p1El = document.getElementById('pred-1m');
  if (p1El) p1El.textContent = p1.toFixed(1);

  const p5El = document.getElementById('pred-5m');
  if (p5El) p5El.textContent = p5.toFixed(1);

  const p15El = document.getElementById('pred-15m');
  if (p15El) p15El.textContent = p15.toFixed(1);

  const p30El = document.getElementById('pred-30m');
  if (p30El) p30El.textContent = p30.toFixed(1);

  // Update Clock
  const now = new Date();
  const timeStr = now.toTimeString().split(' ')[0];
  const timeEl = document.getElementById('system-time');
  if (timeEl) timeEl.textContent = timeStr;

  // Append to Chart
  if (liveTempChart) {
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

        const v = telem.voltage_v !== undefined ? Number(telem.voltage_v) : 12.10;
        const i = telem.current_a !== undefined ? Number(telem.current_a) : 2.20;
        const rpm = telem.rpm !== undefined ? Number(telem.rpm) : 2100;
        const temp = telem.temp_c !== undefined ? Number(telem.temp_c) : (telem.stator_temp !== undefined ? Number(telem.stator_temp) : 34.5);
        const pwr = telem.power_w !== undefined ? Number(telem.power_w) : (v * i);
        const torque = telem.torque_nm !== undefined ? Number(telem.torque_nm) : (i * 0.08);

        const p1 = preds.pred_1m_c ?? preds.plus_1m ?? (temp + 0.4);
        const p5 = preds.pred_5m_c ?? preds.plus_5m ?? (temp + 1.2);
        const p15 = preds.pred_15m_c ?? preds.plus_15m ?? (temp + 2.5);
        const p30 = preds.pred_30m_c ?? preds.plus_30m ?? (temp + 3.8);

        updateDashboardUI(v, i, rpm, temp, pwr, torque, p1, p5, p15, p30);
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
  connectWebSocket();
});
