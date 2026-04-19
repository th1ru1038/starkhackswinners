"""
slip_detection.py — Gripper slip detector

Reads CSV from Arduino (ax,ay,az,distance), maintains a rolling window of ax
values, and fires a slip event when the std dev exceeds the threshold.

On slip:
  - Logs the event immediately to CSV
  - Speaks a voice alert via macOS `say`
  - Updates in-memory state polled by dashboard.py

Standalone usage:
    python slip_detection.py --port /dev/cu.usbmodemXXXX

Importable usage (used by dashboard.py):
    from slip_detection import SlipDetector
    detector = SlipDetector(port="/dev/cu.usbmodemXXXX")
    detector.start()
    rows = detector.get_latest()   # list of dicts
"""

import argparse
import csv
import math
import os
import time
import threading
from collections import deque

import serial
from dotenv import load_dotenv

load_dotenv()

def _log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ── Tunable constants ─────────────────────────────────────────
SERIAL_PORT      = "/dev/cu.usbmodem21201"
SERIAL_BAUD      = 115200
SLIP_WINDOW_MS   = 500   # rolling window length in milliseconds
SLIP_THRESHOLD_G = 0.3   # ax std dev above this → slip event
SLIP_COOLDOWN_S  = 2.0   # minimum seconds between slip events
MAX_STORED_ROWS  = 200   # rows kept in memory for the dashboard
LOG_FILE         = "gripper_log.csv"
CSV_HEADERS      = ["timestamp", "ax", "ay", "az", "distance", "slip"]


class SlipDetector:
    """Reads Arduino serial data and detects grip slip via ax std dev."""

    def __init__(self, port: str, baud: int = SERIAL_BAUD):
        self.port = port
        self.baud = baud
        self.ser  = None

        self._lock    = threading.Lock()
        self._running = False

        # Rolling window: deque of (epoch_seconds, ax_value)
        self._window: deque = deque()

        # Timestamp of last slip event (for cooldown)
        self._last_slip_time: float = 0.0

        # Recent rows for the dashboard
        self._data: deque = deque(maxlen=MAX_STORED_ROWS)

        # Latest slip alert text (polled by dashboard)
        self._latest_analysis: str = ""

        # Slip counter
        self._slip_count: int = 0

        # Timestamp of last routine CSV write (throttled to 1 Hz)
        self._last_csv_time: float = 0.0

        # CSV log file
        new_file = not os.path.exists(LOG_FILE)
        self._csv_file   = open(LOG_FILE, "a", newline="")
        self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=CSV_HEADERS)
        if new_file:
            self._csv_writer.writeheader()

    # ── Public API ────────────────────────────────────────────

    def start(self):
        self.ser = serial.Serial(self.port, self.baud, timeout=1)
        _log(f"Serial open on {self.port} at {self.baud} baud — waiting for Arduino boot...")
        time.sleep(2)
        self._running = True
        threading.Thread(target=self._read_loop, daemon=True).start()
        _log("Read loop started")

    def stop(self):
        self._running = False
        if self.ser and self.ser.is_open:
            self.ser.close()
        self._csv_file.close()

    def get_latest(self) -> list:
        with self._lock:
            return list(self._data)

    def get_latest_analysis(self) -> str:
        with self._lock:
            return self._latest_analysis

    def get_slip_count(self) -> int:
        with self._lock:
            return self._slip_count

    # ── Internal ──────────────────────────────────────────────

    def _read_loop(self):
        while self._running:
            try:
                raw = self.ser.readline().decode("utf-8", errors="ignore").strip()
                fields = raw.split(",") if raw else []
                if len(fields) not in (4, 5):
                    continue  # expect ax,ay,az,distance or ax,ay,az,distance,touch

                ax, ay, az, distance = (float(f) for f in fields[:4])
                touch = int(float(fields[4])) if len(fields) == 5 else 0
                now  = time.time()
                slip = self._check_slip(now, ax)

                if slip:
                    with self._lock:
                        self._slip_count += 1
                    _log(f"SLIP DETECTED  ax_std={self._std():.3f}g")

                row = {
                    "timestamp": now,
                    "ax": ax, "ay": ay, "az": az,
                    "distance": distance,
                    "touch": touch,
                    "slip": slip,
                }

                # Slip rows logged immediately; normal rows throttled to 1 Hz
                if slip or (now - self._last_csv_time) >= 1.0:
                    self._csv_writer.writerow({k: row[k] for k in CSV_HEADERS})
                    self._csv_file.flush()
                    if not slip:
                        self._last_csv_time = now

                with self._lock:
                    self._data.append(row)

                if slip:
                    ax_std = self._std()
                    _log(f"Starting speech thread (ax_std={ax_std:.3f}g)")
                    threading.Thread(
                        target=self._alert,
                        args=(ax_std,),
                        daemon=True,
                    ).start()

            except ValueError:
                continue
            except serial.SerialException as e:
                print(f"Serial error: {e}")
                break

    def _check_slip(self, now: float, ax: float) -> bool:
        cutoff = now - (SLIP_WINDOW_MS / 1000.0)
        self._window.append((now, ax))
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()

        if len(self._window) < 3:
            return False

        if (now - self._last_slip_time) < SLIP_COOLDOWN_S:
            return False

        if self._std() > SLIP_THRESHOLD_G:
            self._last_slip_time = now
            return True

        return False

    def _std(self) -> float:
        values = [v for _, v in self._window]
        n = len(values)
        if n < 2:
            return 0.0
        mean = sum(values) / n
        return math.sqrt(sum((v - mean) ** 2 for v in values) / n)

    def _alert(self, ax_std: float):
        message = (
            f"Warning. Grip instability detected. "
            f"Acceleration spike of {ax_std:.2f} g."
        )
        _log(f"Speaking: {message}")
        with self._lock:
            self._latest_analysis = message
        os.system(f'say "{message}"')


# ── Standalone entrypoint ─────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gripper slip detector (standalone)")
    parser.add_argument("--port", default=SERIAL_PORT,
                        help="Serial port (default: %(default)s)")
    args = parser.parse_args()

    detector = SlipDetector(port=args.port)
    detector.start()

    print(f"Listening on {args.port} at {SERIAL_BAUD} baud.")
    print("Shake the gripper to trigger slip detection. Ctrl-C to quit.\n")

    try:
        while True:
            rows = detector.get_latest()
            if rows:
                r = rows[-1]
                print(
                    f"ax={r['ax']:+.3f}g  ay={r['ay']:+.3f}g  az={r['az']:+.3f}g  "
                    f"dist={r['distance']:6.1f}cm  slip={r['slip']}"
                )
            time.sleep(0.1)
    except KeyboardInterrupt:
        detector.stop()
        print("\nStopped.")
