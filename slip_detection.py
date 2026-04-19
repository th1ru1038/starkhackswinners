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

import math
import time
import threading
import argparse
from collections import deque

import serial

# ── Tunable constants ─────────────────────────────────────────
SERIAL_PORT      = "/dev/cu.usbmodem21201"
SERIAL_BAUD      = 115200
SLIP_WINDOW_MS   = 500    # rolling window length in milliseconds
SLIP_THRESHOLD_G = 0.5   # std dev above this → slip event
SLIP_COOLDOWN_S  = 2.0   # minimum seconds between slip events
MAX_STORED_ROWS  = 200    # rows kept in memory for the dashboard


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

    # ── Public API ────────────────────────────────────────────

    def start(self):
        """Open serial port and begin reading in a background thread."""
        self.ser = serial.Serial(self.port, self.baud, timeout=1)
        # Arduino resets on serial open; wait for it to boot
        time.sleep(2)
        self._running = True
        t = threading.Thread(target=self._read_loop, daemon=True)
        t.start()

    def stop(self):
        """Stop reading and close the serial port."""
        self._running = False
        if self.ser and self.ser.is_open:
            self.ser.close()

    def get_latest(self) -> list:
        """Return a thread-safe copy of the most recent data rows."""
        with self._lock:
            return list(self._data)

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
                    print(f"[{_fmt_time(now)}] SLIP DETECTED  "
                          f"ax_std={self._std():.3f}g  →  tightening servo")

                row = {
                    "timestamp": now,
                    "ax": ax, "ay": ay, "az": az,
                    "distance": distance,
                    "touch": touch,
                    "slip": slip,
                }

                with self._lock:
                    self._data.append(row)

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


def _fmt_time(epoch: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(epoch))


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
