"""
slip_detection.py — Gripper slip detector

Reads CSV from Arduino (ax,ay,az,distance,touch), maintains a 100 ms rolling
window of ax values, and sends 'T' back to the Arduino when the std dev
exceeds the slip threshold.

Standalone usage:
    python slip_detection.py --port /dev/cu.usbmodemXXXX

Importable usage (used by dashboard.py):
    from slip_detection import SlipDetector
    detector = SlipDetector(port="/dev/cu.usbmodemXXXX")
    detector.start()
    rows = detector.get_latest()   # list of dicts
"""

import csv
import math
import os
import time
import threading
import argparse
from collections import deque

import serial
from dotenv import load_dotenv

load_dotenv()  # reads GEMINI_API_KEY and ELEVENLABS_API_KEY from .env

def _log(msg: str):
    """Timestamped print for tracing the slip pipeline."""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ── Tunable constants ─────────────────────────────────────────
SERIAL_PORT      = "/dev/cu.usbmodem21201"
SERIAL_BAUD      = 115200
SLIP_WINDOW_MS   = 500    # rolling window length in milliseconds
SLIP_THRESHOLD_G = 0.3   # std dev above this → slip event
SLIP_COOLDOWN_S  = 2.0   # minimum seconds between slip events
MAX_STORED_ROWS  = 200    # rows kept in memory for the dashboard
LOG_FILE         = "gripper_log.csv"
ELEVENLABS_VOICE = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel
CSV_HEADERS      = ["timestamp", "ax", "ay", "az", "distance", "touch", "slip"]


class SlipDetector:
    """Reads Arduino serial data, detects slip, commands tighten."""

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

        # Latest slip analysis text (polled by dashboard)
        self._latest_analysis: str = ""

        # Servo angle tracker (starts at grip angle, +5° per slip, max 175°)
        self._servo_angle: int = 90
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
        """Open serial port and begin reading in a background thread."""
        gemini_ok    = bool(os.getenv("GEMINI_API_KEY"))
        elevenlabs_ok = bool(os.getenv("ELEVENLABS_API_KEY"))
        _log(f"API keys — Gemini: {'OK' if gemini_ok else 'MISSING'} | "
             f"ElevenLabs: {'OK' if elevenlabs_ok else 'MISSING'}")
        self.ser = serial.Serial(self.port, self.baud, timeout=1)
        _log(f"Serial open on {self.port} at {self.baud} baud — waiting for Arduino boot...")
        time.sleep(2)
        self._running = True
        t = threading.Thread(target=self._read_loop, daemon=True)
        t.start()
        _log("Read loop started")

    def stop(self):
        """Stop reading and close the serial port and log file."""
        self._running = False
        if self.ser and self.ser.is_open:
            self.ser.close()
        self._csv_file.close()

    def get_latest(self) -> list:
        """Return a thread-safe copy of the most recent data rows."""
        with self._lock:
            return list(self._data)

    def get_latest_analysis(self) -> str:
        with self._lock:
            return self._latest_analysis

    def get_servo_angle(self) -> int:
        with self._lock:
            return self._servo_angle

    def get_slip_count(self) -> int:
        with self._lock:
            return self._slip_count

    def send_command(self, cmd: str) -> None:
        """Send a single-byte command to the Arduino over the shared serial port."""
        with self._lock:
            if cmd == 'O':
                self._servo_angle = 0
            elif cmd == 'G':
                self._servo_angle = 90
        self.ser.write(cmd.encode())
        _log(f"Command sent: '{cmd}'")

    # ── Internal ──────────────────────────────────────────────

    def _read_loop(self):
        while self._running:
            try:
                raw = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if not raw or raw.count(",") != 4:
                    continue  # skip header lines or garbage

                parts = raw.split(",")
                ax, ay, az, distance, touch = (float(p) for p in parts)
                touch = int(touch)
                now   = time.time()

                slip = self._check_slip(now, ax)

                if slip:
                    self.ser.write(b"T\n")  # tell Arduino to tighten
                    with self._lock:
                        self._servo_angle = min(self._servo_angle + 5, 175)
                        self._slip_count += 1
                    _log(f"SLIP DETECTED  ax_std={self._std():.3f}g  → tightening servo to {self._servo_angle}°")

                row = {
                    "timestamp": now,
                    "ax": ax, "ay": ay, "az": az,
                    "distance": distance,
                    "touch": touch,
                    "slip": slip,
                }

                # Log slip events immediately; normal rows throttled to 1 Hz
                if slip or (now - self._last_csv_time) >= 1.0:
                    self._csv_writer.writerow({k: row[k] for k in CSV_HEADERS})
                    self._csv_file.flush()
                    if not slip:
                        self._last_csv_time = now

                with self._lock:
                    self._data.append(row)

                # On slip: speak warning in background (non-blocking)
                if slip:
                    ax_std = self._std()
                    _log(f"Starting speech thread (ax_std={ax_std:.3f}g)")
                    threading.Thread(
                        target=self._analyze_slip,
                        args=(ax_std,),
                        daemon=True,
                    ).start()

            except ValueError:
                continue  # malformed CSV line
            except serial.SerialException as e:
                print(f"Serial error: {e}")
                break

    def _check_slip(self, now: float, ax: float) -> bool:
        """Add sample to rolling window, prune old entries, return slip flag."""
        cutoff = now - (SLIP_WINDOW_MS / 1000.0)

        self._window.append((now, ax))

        # Drop samples that have aged out of the window
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()

        if len(self._window) < 3:
            return False  # need at least 3 points for a meaningful std dev

        # Enforce cooldown — ignore slip if one fired recently
        if (now - self._last_slip_time) < SLIP_COOLDOWN_S:
            return False

        if self._std() > SLIP_THRESHOLD_G:
            self._last_slip_time = now
            return True

        return False

    def _std(self) -> float:
        """Population standard deviation of ax values in the rolling window."""
        values = [v for _, v in self._window]
        n      = len(values)
        if n < 2:
            return 0.0
        mean     = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        return math.sqrt(variance)

    # ── Speech pipeline (runs in background thread on slip) ──

    def _analyze_slip(self, ax_std: float):
        message = (
            f"Warning. Grip instability detected. "
            f"Acceleration spike of {ax_std:.2f} g. "
            f"Servo tightened."
        )
        _log(f"Speaking: {message}")
        with self._lock:
            self._latest_analysis = message
        self._speak(message)

    def _speak(self, text: str):
        _log(f"say: {text}")
        os.system(f'say "{text}"')



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
                    f"dist={r['distance']:6.1f}cm  touch={r['touch']}  slip={r['slip']}"
                )
            time.sleep(0.1)
    except KeyboardInterrupt:
        detector.stop()
        print("\nStopped.")
