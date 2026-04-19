"""
dashboard.py — Live web dashboard for the Smart Adaptive Gripper

Runs SlipDetector in a background thread, then serves a Flask page at
http://localhost:5000 with live Chart.js graphs of acceleration, distance,
and slip events.

Usage:
    pip install flask pyserial
    python dashboard.py --port /dev/cu.usbmodemXXXX
"""

import argparse
from flask import Flask, jsonify, render_template_string, request
from slip_detection import SlipDetector

# ── Tunable constants ─────────────────────────────────────────
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000

app = Flask(__name__)
detector: SlipDetector = None  # assigned in main before app.run()

# ── Inline HTML/JS — no separate template file needed ─────────
_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Smart Gripper Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body   { font-family: monospace; background: #111; color: #eee; padding: 20px; }
    h1     { color: #4fc3f7; margin-bottom: 16px; }
    #slip-log {
      background: #1a1a1a; border-radius: 8px; padding: 12px;
      height: 90px; overflow-y: auto; font-size: 12px;
      margin-bottom: 16px; border: 1px solid #333;
    }
    .slip-event { color: #ff5252; }
    .no-slips   { color: #555; font-style: italic; }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    .card {
      background: #1a1a1a; border-radius: 8px;
      padding: 12px; border: 1px solid #333;
    }
    .card h2 { font-size: 13px; color: #aaa; margin-bottom: 8px; }
  </style>
</head>
<body>
  <h1>Smart Adaptive Gripper — Live Dashboard</h1>

  <div id="slip-log">
    <span class="no-slips">No slip events yet.</span>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Acceleration (g)</h2>
      <canvas id="accelChart" height="180"></canvas>
    </div>
    <div class="card">
      <h2>Distance (cm)</h2>
      <canvas id="distChart" height="180"></canvas>
    </div>
  </div>

<script>
const MAX_PTS = 80;

// Helper: create a Chart.js line chart
function makeChart(id, datasets) {
  return new Chart(document.getElementById(id), {
    type: 'line',
    data: {
      labels: [],
      datasets: datasets.map(d => ({
        label: d.label,
        data: [],
        borderColor: d.color,
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.2,
        fill: false,
      }))
    },
    options: {
      animation: false,
      responsive: true,
      scales: {
        x: { ticks: { color: '#666', maxTicksLimit: 5 }, grid: { color: '#222' } },
        y: { ticks: { color: '#666' },                   grid: { color: '#222' } }
      },
      plugins: { legend: { labels: { color: '#aaa', boxWidth: 12 } } }
    }
  });
}

const accelChart = makeChart('accelChart', [
  { label: 'ax', color: '#ef5350' },
  { label: 'ay', color: '#66bb6a' },
  { label: 'az', color: '#42a5f5' },
]);

const distChart = makeChart('distChart', [
  { label: 'distance', color: '#ffa726' },
]);

// Track the newest timestamp we have already rendered
let lastTimestamp = 0;
let slipCount = 0;
const slipLog = document.getElementById('slip-log');

// Push new values onto a chart, dropping oldest when full
function pushToChart(chart, timeLabel, values) {
  chart.data.labels.push(timeLabel);
  chart.data.datasets.forEach((ds, i) => ds.data.push(values[i]));
  if (chart.data.labels.length > MAX_PTS) {
    chart.data.labels.shift();
    chart.data.datasets.forEach(ds => ds.data.shift());
  }
  chart.update('none');  // 'none' skips animation for smooth streaming
}

async function fetchAndRender() {
  try {
    const res  = await fetch('/data?since=' + lastTimestamp);
    const rows = await res.json();

    rows.forEach(row => {
      const t = new Date(row.timestamp * 1000).toLocaleTimeString();

      pushToChart(accelChart, t, [row.ax, row.ay, row.az]);
      pushToChart(distChart,  t, [row.distance]);

      if (row.slip) {
        slipCount++;
        // Clear the placeholder text on first event
        const placeholder = slipLog.querySelector('.no-slips');
        if (placeholder) placeholder.remove();

        const entry = document.createElement('div');
        entry.className = 'slip-event';
        entry.textContent =
          `[${t}]  SLIP #${slipCount}  — ax variation exceeded threshold`;
        slipLog.appendChild(entry);
        slipLog.scrollTop = slipLog.scrollHeight;
      }

      lastTimestamp = row.timestamp;
    });
  } catch (err) {
    // Silently skip — server might not have data yet
  }
}

// Poll every 300 ms
setInterval(fetchAndRender, 300);
fetchAndRender();
</script>
</body>
</html>
"""

# ── Flask routes ──────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(_HTML)


@app.route("/data")
def data():
    """Return all rows newer than the 'since' query param (epoch seconds)."""
    since = float(request.args.get("since", 0))
    rows  = [r for r in detector.get_latest() if r["timestamp"] > since]
    return jsonify(rows)


# ── Entrypoint ────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gripper live dashboard")
    parser.add_argument("--port", default="/dev/cu.usbmodem21201",
                        help="Serial port (default: %(default)s)")
    args = parser.parse_args()

    detector = SlipDetector(port=args.port)
    detector.start()

    print(f"Slip detector running on {args.port}")
    print(f"Dashboard → http://localhost:{FLASK_PORT}\n")

    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)
