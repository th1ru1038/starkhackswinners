"""
dashboard.py — Live web dashboard for the Smart Adaptive Gripper

Usage:
    python dashboard.py --port /dev/cu.usbmodemXXXX
"""

import argparse
import collections
import math
import random
import threading
import time
from flask import Flask, jsonify, render_template_string, request
from slip_detection import SlipDetector

FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000

app = Flask(__name__)
detector: SlipDetector = None

_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Smart Adaptive Gripper — Ford Hackathon</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg:        #07080f;
      --surface:   #0e1019;
      --surface2:  #141622;
      --border:    #1e2235;
      --blue:      #2d7ef7;
      --blue-glow: rgba(45,126,247,0.18);
      --cyan:      #00c8ff;
      --red:       #ff2d55;
      --red-dim:   rgba(255,45,85,0.15);
      --green:     #30d158;
      --yellow:    #ffd60a;
      --text:      #e8eaf0;
      --text-dim:  #6b7280;
      --text-mid:  #9ca3af;
      --mono:      'JetBrains Mono', monospace;
    }

    html, body {
      height: 100%;
      background: var(--bg);
      color: var(--text);
      font-family: 'Inter', sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }

    /* ── Layout ── */
    .shell {
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      padding: 24px 32px 32px;
      gap: 20px;
      max-width: 1400px;
      margin: 0 auto;
    }

    /* ── Header ── */
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--border);
    }
    .header-left { display: flex; flex-direction: column; gap: 2px; }
    .header-title {
      font-size: 22px;
      font-weight: 700;
      letter-spacing: -0.3px;
      color: var(--text);
    }
    .header-subtitle {
      font-size: 12px;
      color: var(--text-dim);
      font-weight: 400;
      letter-spacing: 0.5px;
      text-transform: uppercase;
    }
    .header-badge {
      display: flex;
      align-items: center;
      gap: 8px;
      background: var(--surface2);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 16px;
    }
    .live-dot {
      width: 8px; height: 8px;
      border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 8px var(--green);
      animation: pulse-dot 1.8s ease-in-out infinite;
    }
    @keyframes pulse-dot {
      0%, 100% { opacity: 1; }
      50%       { opacity: 0.35; }
    }
    .live-label {
      font-size: 12px;
      font-weight: 600;
      color: var(--green);
      letter-spacing: 1px;
      text-transform: uppercase;
    }

    /* ── Slip Banner ── */
    #slip-banner {
      display: none;
      position: relative;
      overflow: hidden;
      border-radius: 12px;
      border: 1px solid var(--red);
      background: var(--red-dim);
      padding: 18px 24px;
    }
    #slip-banner.active { display: flex; align-items: center; gap: 20px; }
    .banner-flash {
      position: absolute; inset: 0;
      background: var(--red);
      opacity: 0;
      animation: flash 0.6s ease-in-out infinite;
      pointer-events: none;
      border-radius: 12px;
    }
    @keyframes flash {
      0%, 100% { opacity: 0; }
      50%       { opacity: 0.12; }
    }
    .banner-icon {
      font-size: 36px;
      flex-shrink: 0;
      animation: shake 0.4s ease-in-out infinite;
    }
    @keyframes shake {
      0%, 100% { transform: translateX(0); }
      25%       { transform: translateX(-3px); }
      75%       { transform: translateX(3px); }
    }
    .banner-body { flex: 1; }
    .banner-title {
      font-size: 20px;
      font-weight: 700;
      color: var(--red);
      letter-spacing: 1.5px;
      text-transform: uppercase;
    }
    .banner-msg {
      margin-top: 4px;
      font-size: 13px;
      color: var(--text-mid);
      font-family: var(--mono);
    }
    .banner-timer {
      font-size: 11px;
      color: var(--text-dim);
      font-family: var(--mono);
      text-align: right;
      min-width: 32px;
    }

    /* ── Stat Cards ── */
    .stats-row {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
    }
    .stat-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 18px 20px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      position: relative;
      overflow: hidden;
      transition: border-color 0.3s;
    }
    .stat-card::before {
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 2px;
    }
    .stat-card.blue::before  { background: var(--blue); }
    .stat-card.red::before   { background: var(--red); }
    .stat-card.cyan::before  { background: var(--cyan); }
    .stat-card.green::before { background: var(--green); }

    .stat-label {
      font-size: 11px;
      font-weight: 600;
      color: var(--text-dim);
      letter-spacing: 0.8px;
      text-transform: uppercase;
    }
    .stat-value {
      font-size: 36px;
      font-weight: 700;
      font-family: var(--mono);
      letter-spacing: -1px;
      line-height: 1;
    }
    .stat-card.blue  .stat-value { color: var(--blue); }
    .stat-card.red   .stat-value { color: var(--red); }
    .stat-card.cyan  .stat-value { color: var(--cyan); }
    .stat-card.green .stat-value { color: var(--green); }
    .stat-unit {
      font-size: 13px;
      font-weight: 400;
      color: var(--text-dim);
      margin-left: 4px;
    }
    .stat-sub {
      font-size: 11px;
      color: var(--text-dim);
      font-family: var(--mono);
    }

    /* Servo angle arc */
    .servo-arc-wrap {
      display: flex;
      align-items: center;
      gap: 14px;
    }
    .servo-arc-wrap svg { flex-shrink: 0; }

    /* ── Charts ── */
    .charts-row {
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 16px;
    }
    .chart-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px 20px 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .chart-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .chart-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--text-mid);
      letter-spacing: 0.3px;
    }
    .chart-legend {
      display: flex;
      gap: 14px;
    }
    .legend-item {
      display: flex;
      align-items: center;
      gap: 5px;
      font-size: 11px;
      color: var(--text-dim);
      font-family: var(--mono);
    }
    .legend-dot {
      width: 8px; height: 8px;
      border-radius: 50%;
    }

    /* ── Slip Log ── */
    .log-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .log-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--text-mid);
      letter-spacing: 0.3px;
    }
    .log-entries {
      flex: 1;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 6px;
      max-height: 130px;
      font-family: var(--mono);
      font-size: 11px;
    }
    .log-entries::-webkit-scrollbar { width: 4px; }
    .log-entries::-webkit-scrollbar-track { background: transparent; }
    .log-entries::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
    .log-entry {
      display: flex;
      gap: 10px;
      padding: 6px 10px;
      background: var(--surface2);
      border-radius: 6px;
      border-left: 3px solid var(--red);
    }
    .log-time { color: var(--text-dim); flex-shrink: 0; }
    .log-text { color: var(--text); }
    .log-empty { color: var(--text-dim); font-style: italic; font-size: 11px; font-family: var(--mono); }

    /* ── Footer ── */
    .footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-top: 16px;
      border-top: 1px solid var(--border);
    }
    .footer-left { font-size: 11px; color: var(--text-dim); }
    .footer-right { font-size: 11px; color: var(--text-dim); font-family: var(--mono); }
  </style>
</head>
<body>
<div class="shell">

  <!-- Header -->
  <div class="header">
    <div class="header-left">
      <span class="header-title">Smart Adaptive Gripper</span>
      <span class="header-subtitle">Ford Motor Company Hackathon &mdash; Real-Time Control Dashboard</span>
    </div>
    <div class="header-badge">
      <div class="live-dot"></div>
      <span class="live-label">Live</span>
    </div>
  </div>

  <!-- Slip Banner -->
  <div id="slip-banner">
    <div class="banner-flash"></div>
    <div class="banner-icon">⚠</div>
    <div class="banner-body">
      <div class="banner-title">Slip Detected</div>
      <div class="banner-msg" id="banner-msg">Grip instability detected — servo tightening...</div>
    </div>
    <div class="banner-timer" id="banner-timer">5s</div>
  </div>

  <!-- Stat Cards -->
  <div class="stats-row">
    <div class="stat-card red">
      <span class="stat-label">Slip Events</span>
      <div>
        <span class="stat-value" id="stat-slips">0</span>
      </div>
      <span class="stat-sub" id="stat-last-slip">No events yet</span>
    </div>

    <div class="stat-card cyan">
      <span class="stat-label">Servo Angle</span>
      <div class="servo-arc-wrap">
        <svg id="servo-svg" width="56" height="56" viewBox="0 0 56 56">
          <circle cx="28" cy="28" r="22" fill="none" stroke="#1e2235" stroke-width="5"/>
          <circle id="servo-arc" cx="28" cy="28" r="22" fill="none"
            stroke="#00c8ff" stroke-width="5"
            stroke-dasharray="0 138.23"
            stroke-dashoffset="34.56"
            stroke-linecap="round"
            transform="rotate(-220 28 28)"
          />
        </svg>
        <div>
          <span class="stat-value" id="stat-servo">90</span><span class="stat-unit">°</span>
        </div>
      </div>
      <span class="stat-sub">Max 175°</span>
    </div>

    <div class="stat-card blue">
      <span class="stat-label">ax Std Dev</span>
      <div>
        <span class="stat-value" id="stat-axstd">—</span><span class="stat-unit" id="stat-axstd-unit"></span>
      </div>
      <span class="stat-sub">Slip threshold: 0.30 g</span>
    </div>

    <div class="stat-card green">
      <span class="stat-label">Distance</span>
      <div>
        <span class="stat-value" id="stat-dist">—</span><span class="stat-unit" id="stat-dist-unit"></span>
      </div>
      <span class="stat-sub" id="stat-touch">Touch: —</span>
    </div>
  </div>

  <!-- Charts -->
  <div class="charts-row">
    <div class="chart-card">
      <div class="chart-header">
        <span class="chart-title">Acceleration (g)</span>
        <div class="chart-legend">
          <span class="legend-item"><span class="legend-dot" style="background:#ef5350"></span>ax</span>
          <span class="legend-item"><span class="legend-dot" style="background:#66bb6a"></span>ay</span>
          <span class="legend-item"><span class="legend-dot" style="background:#42a5f5"></span>az</span>
          <span class="legend-item"><span class="legend-dot" style="background:#ff2d55;border-radius:2px"></span>slip</span>
        </div>
      </div>
      <canvas id="accelChart" height="160"></canvas>
    </div>

    <div class="chart-card">
      <div class="chart-header">
        <span class="chart-title">Object Distance (cm)</span>
      </div>
      <canvas id="distChart" height="160"></canvas>
    </div>
  </div>

  <!-- Slip Log -->
  <div class="log-card">
    <span class="log-title">Slip Event Log</span>
    <div class="log-entries" id="slip-log">
      <span class="log-empty">No slip events recorded.</span>
    </div>
  </div>

  <!-- Footer -->
  <div class="footer">
    <span class="footer-left">Smart Adaptive Gripper &mdash; Arduino Mega 2560 / MPU-6050 / MG90S Servo</span>
    <span class="footer-right" id="footer-ts">—</span>
  </div>

</div>

<script>
Chart.register(window['chartjs-plugin-annotation']);

const MAX_PTS = 100;

function makeChart(id, datasets, yLabel) {
  return new Chart(document.getElementById(id), {
    type: 'line',
    data: {
      labels: [],
      datasets: datasets.map(d => ({
        label: d.label,
        data: [],
        borderColor: d.color,
        backgroundColor: d.fill || 'transparent',
        borderWidth: 1.8,
        pointRadius: 0,
        tension: 0.3,
        fill: !!d.fill,
      }))
    },
    options: {
      animation: false,
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: {
          ticks: { color: '#4b5563', maxTicksLimit: 6, font: { family: "'JetBrains Mono'" } },
          grid: { color: '#141622' },
          border: { color: '#1e2235' },
        },
        y: {
          ticks: { color: '#4b5563', font: { family: "'JetBrains Mono'" } },
          grid: { color: '#141622' },
          border: { color: '#1e2235' },
          title: yLabel ? { display: true, text: yLabel, color: '#4b5563', font: { size: 11 } } : {},
        }
      },
      plugins: {
        legend: { display: false },
        annotation: { annotations: {} },
        tooltip: {
          backgroundColor: '#0e1019',
          borderColor: '#1e2235',
          borderWidth: 1,
          titleColor: '#9ca3af',
          bodyColor: '#e8eaf0',
          bodyFont: { family: "'JetBrains Mono'" },
        }
      }
    }
  });
}

const accelChart = makeChart('accelChart', [
  { label: 'ax', color: '#ef5350' },
  { label: 'ay', color: '#66bb6a' },
  { label: 'az', color: '#42a5f5' },
]);

const distChart = makeChart('distChart', [
  { label: 'distance (cm)', color: '#00c8ff', fill: 'rgba(0,200,255,0.06)' },
], 'cm');

// State
let lastTimestamp  = 0;
let slipCount      = 0;
let slipAnnotIdx   = 0;
let bannerTimer    = null;
let bannerCountdown = null;
let axHistory      = [];

const slipBanner = document.getElementById('slip-banner');
const bannerMsg  = document.getElementById('banner-msg');
const bannerTimerEl = document.getElementById('banner-timer');

function showBanner(msg) {
  bannerMsg.textContent = msg;
  slipBanner.classList.add('active');

  if (bannerTimer) { clearTimeout(bannerTimer); clearInterval(bannerCountdown); }

  let secs = 5;
  bannerTimerEl.textContent = secs + 's';
  bannerCountdown = setInterval(() => {
    secs--;
    bannerTimerEl.textContent = secs + 's';
    if (secs <= 0) clearInterval(bannerCountdown);
  }, 1000);

  bannerTimer = setTimeout(() => {
    slipBanner.classList.remove('active');
  }, 5000);
}

function addSlipAnnotation(labelIndex) {
  const id = 'slip_' + slipAnnotIdx++;
  accelChart.options.plugins.annotation.annotations[id] = {
    type: 'line',
    xMin: labelIndex,
    xMax: labelIndex,
    borderColor: 'rgba(255,45,85,0.7)',
    borderWidth: 1.5,
    borderDash: [4, 3],
    label: {
      display: true,
      content: 'SLIP',
      position: 'start',
      color: '#ff2d55',
      font: { size: 9, family: "'JetBrains Mono'", weight: '600' },
      backgroundColor: 'rgba(255,45,85,0.15)',
      padding: { x: 4, y: 2 },
      yAdjust: 4,
    }
  };
}

function updateServoArc(angle) {
  const arc = document.getElementById('servo-arc');
  const r = 22;
  const circ = 2 * Math.PI * r;       // ~138.23
  const maxAngle = 175;
  const dashLen = (angle / maxAngle) * circ;
  arc.setAttribute('stroke-dasharray', dashLen.toFixed(2) + ' ' + circ.toFixed(2));
}

function stdDev(arr) {
  if (arr.length < 2) return null;
  const mean = arr.reduce((a,b) => a+b, 0) / arr.length;
  const variance = arr.reduce((s,v) => s + (v-mean)**2, 0) / arr.length;
  return Math.sqrt(variance);
}

function pushToChart(chart, label, values) {
  chart.data.labels.push(label);
  chart.data.datasets.forEach((ds, i) => ds.data.push(values[i]));
  if (chart.data.labels.length > MAX_PTS) {
    chart.data.labels.shift();
    chart.data.datasets.forEach(ds => ds.data.shift());
    // shift annotation indices
    Object.values(chart.options.plugins.annotation.annotations).forEach(a => {
      if (a.xMin !== undefined) { a.xMin--; a.xMax--; }
    });
    // remove annotations that scrolled off
    for (const [k, a] of Object.entries(chart.options.plugins.annotation.annotations)) {
      if (a.xMin < 0) delete chart.options.plugins.annotation.annotations[k];
    }
  }
  chart.update('none');
}

async function fetchAndRender() {
  try {
    const res  = await fetch('/data?since=' + lastTimestamp);
    const rows = await res.json();

    rows.forEach(row => {
      const t = new Date(row.timestamp * 1000).toLocaleTimeString('en-US', { hour12: false });

      axHistory.push(row.ax);
      if (axHistory.length > 30) axHistory.shift();

      const labelIdx = accelChart.data.labels.length;
      pushToChart(accelChart, t, [row.ax, row.ay, row.az]);
      pushToChart(distChart,  t, [row.distance < 400 ? row.distance : null]);

      // Live stats
      document.getElementById('stat-dist').textContent =
        row.distance < 400 ? row.distance.toFixed(1) : '—';
      document.getElementById('stat-dist-unit').textContent =
        row.distance < 400 ? ' cm' : '';
      document.getElementById('stat-touch').textContent =
        'Touch: ' + (row.touch ? 'ACTIVE' : 'none');

      const sd = stdDev(axHistory);
      if (sd !== null) {
        document.getElementById('stat-axstd').textContent = sd.toFixed(3);
        document.getElementById('stat-axstd-unit').textContent = ' g';
      }

      if (row.slip) {
        slipCount++;
        document.getElementById('stat-slips').textContent = slipCount;
        document.getElementById('stat-last-slip').textContent =
          'Last: ' + t;

        addSlipAnnotation(labelIdx);

        const msg = 'Warning. Grip instability detected. Servo tightened.';
        showBanner(msg);

        const log = document.getElementById('slip-log');
        const placeholder = log.querySelector('.log-empty');
        if (placeholder) placeholder.remove();
        const entry = document.createElement('div');
        entry.className = 'log-entry';
        entry.innerHTML = `<span class="log-time">${t}</span><span class="log-text">Slip #${slipCount} — ax variation exceeded threshold</span>`;
        log.appendChild(entry);
        log.scrollTop = log.scrollHeight;
      }

      lastTimestamp = row.timestamp;
      document.getElementById('footer-ts').textContent =
        'Last update: ' + new Date().toLocaleTimeString('en-US', { hour12: false });
    });
  } catch (_) {}
}

async function fetchStatus() {
  try {
    const res  = await fetch('/status');
    const data = await res.json();
    document.getElementById('stat-servo').textContent = data.servo_angle;
    updateServoArc(data.servo_angle);
  } catch (_) {}
}

setInterval(fetchAndRender, 300);
setInterval(fetchStatus,    500);
fetchAndRender();
fetchStatus();
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(_HTML)


@app.route("/analysis")
def analysis():
    return jsonify({"text": detector.get_latest_analysis()})


@app.route("/status")
def status():
    return jsonify({
        "servo_angle": detector.get_servo_angle(),
        "slip_count":  detector.get_slip_count(),
    })


@app.route("/data")
def data():
    since = float(request.args.get("since", 0))
    rows  = [r for r in detector.get_latest() if r["timestamp"] > since]
    return jsonify(rows)


class DemoDetector:
    """Generates synthetic sensor data at ~20 Hz. Fires a slip event every 10 s."""

    SLIP_INTERVAL = 10.0   # seconds between simulated slips
    RATE          = 0.05   # seconds between samples (~20 Hz)
    MAX_ROWS      = 200

    def __init__(self):
        self._lock         = threading.Lock()
        self._data         = collections.deque(maxlen=self.MAX_ROWS)
        self._analysis     = ""
        self._servo_angle  = 90
        self._slip_count   = 0
        self._running      = False
        self._t            = 0.0   # phase tracker for smooth waveforms
        self._last_slip    = 0.0

    def start(self):
        self._running   = True
        self._last_slip = time.time()
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def get_latest(self):
        with self._lock:
            return list(self._data)

    def get_latest_analysis(self):
        with self._lock:
            return self._analysis

    def get_servo_angle(self):
        with self._lock:
            return self._servo_angle

    def get_slip_count(self):
        with self._lock:
            return self._slip_count

    def send_command(self, cmd: str) -> None:
        with self._lock:
            if cmd == 'O':
                self._servo_angle = 0
                print(f"[DEMO] Command 'O' → OPEN  (servo 0°)")
            elif cmd == 'G':
                self._servo_angle = 90
                print(f"[DEMO] Command 'G' → GRIP  (servo 90°)")

    # ── Internal ──────────────────────────────────────────────

    def _loop(self):
        while self._running:
            now = time.time()
            self._t += self.RATE

            slip = (now - self._last_slip) >= self.SLIP_INTERVAL

            # Normal sensor waveforms
            ax = (0.05 * math.sin(self._t * 1.3)
                  + random.gauss(0, 0.02))
            ay = (0.03 * math.cos(self._t * 0.9)
                  + random.gauss(0, 0.015))
            az = (1.0  + 0.02 * math.sin(self._t * 0.5)
                  + random.gauss(0, 0.01))
            distance = (15.0 + 3.0 * math.sin(self._t * 0.4)
                        + random.gauss(0, 0.3))
            touch = 1

            if slip:
                # Spike ax to simulate a jolt
                ax += random.choice([-1, 1]) * random.uniform(0.45, 0.75)
                with self._lock:
                    self._servo_angle = min(self._servo_angle + 5, 175)
                    self._slip_count += 1
                    count = self._slip_count
                    angle = self._servo_angle
                self._analysis = (
                    f"Warning. Grip instability detected. "
                    f"Acceleration spike of {abs(ax):.2f} g. "
                    f"Servo tightened."
                )
                self._last_slip = now
                print(f"[DEMO] Slip #{count}  ax={ax:.3f}g  servo={angle}°")

            row = {
                "timestamp": now,
                "ax": round(ax, 4),
                "ay": round(ay, 4),
                "az": round(az, 4),
                "distance": round(distance, 2),
                "touch": touch,
                "slip": slip,
            }
            with self._lock:
                self._data.append(row)

            time.sleep(self.RATE)


def _gamepad_thread(det) -> None:
    """Read USB gamepad events and route O/G commands through the detector."""
    try:
        import inputs as _inputs
    except ImportError:
        print("[gamepad] 'inputs' package not installed — skipping controller support")
        print("[gamepad] Run: pip install inputs")
        return

    gamepads = _inputs.devices.gamepads
    if not gamepads:
        print("[gamepad] No gamepad detected — controller support disabled")
        print("[gamepad] Check USB connection and try again")
        return

    gamepad = gamepads[0]
    print(f"[gamepad] Connected: {gamepad.name}")
    print(f"[gamepad] X button → Open (0°)   Circle button → Grip (90°)")

    while True:
        try:
            for event in gamepad.read():
                if event.ev_type != "Key" or event.state != 1:
                    continue
                if event.code == "BTN_SOUTH":    # X button
                    print(f"[gamepad] X → OPEN")
                    det.send_command("O")
                elif event.code == "BTN_EAST":   # Circle button
                    print(f"[gamepad] Circle → GRIP")
                    det.send_command("G")
        except Exception as e:
            print(f"[gamepad] Error: {e} — retrying in 2 s")
            time.sleep(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gripper live dashboard")
    parser.add_argument("--port", default="/dev/cu.usbmodem21201",
                        help="Serial port (default: %(default)s)")
    parser.add_argument("--demo", action="store_true",
                        help="Run with simulated data — no Arduino required")
    args = parser.parse_args()

    if args.demo:
        detector = DemoDetector()
        detector.start()
        print("Demo mode — simulated sensor data (slip every 10 s)")
    else:
        detector = SlipDetector(port=args.port)
        detector.start()
        print(f"Slip detector running on {args.port}")

    threading.Thread(target=_gamepad_thread, args=(detector,), daemon=True).start()

    print(f"Dashboard → http://localhost:{FLASK_PORT}\n")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)
