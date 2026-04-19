# STARVIS — Smart Adaptive Gripper | Ford Hackathon

Real-time grip slip detection on a robot arm. MPU-6050 detects instability, dashboard fires a red banner, Mac speaks a voice alert. Controller moves all 6 arm joints via button-only gamepad input.

---

## Hardware

| Component | Part | Connection |
|-----------|------|------------|
| Microcontroller | Arduino Mega 2560 | USB → `/dev/cu.usbmodem21201` |
| IMU | MPU-6050 | I2C — SDA pin 20, SCL pin 21 |
| Distance sensor | HC-SR04 ultrasonic | Trig pin 9, Echo pin 10 |
| Servo controller | Waveshare Bus Servo Adapter (A) | USB → `/dev/cu.usbmodem5A7C1172351` |
| Power | 12V 5A external supply | Powers Waveshare board |
| Controller | ShanWan Q34B gamepad | USB wired |

**No breadboard — direct wire connections. No MG90S servo. No buck converter.**

---

## Serial Ports

| Port | Device | Purpose |
|------|--------|---------|
| `/dev/cu.usbmodem21201` | Arduino Mega | IMU + distance sensor data stream |
| `/dev/cu.usbmodem5A7C1172351` | Waveshare Bus Servo Adapter (A) | Robot arm servo control |

---

## Files

### `gripper.ino`
Arduino sketch. Runs on the Mega 2560.

- Reads MPU-6050 accelerometer via direct I2C register reads (no library)
- Reads HC-SR04 distance via `pulseIn()`
- Streams CSV at ~20 Hz over Serial at 115200 baud: `ax,ay,az,distance`
- No serial commands received — Arduino is read-only
- Libraries used: `Wire.h` (built-in)

### `slip_detection.py`
Core Python module. Imported by `dashboard.py`, also runnable standalone.

- Opens Arduino serial port, parses 4-field CSV at 115200 baud
- Maintains a 500 ms rolling window of ax values
- Slip detected when ax std dev > `SLIP_THRESHOLD_G` (0.3g) AND cooldown elapsed
- On slip: fires background thread for macOS `say` voice alert, logs to CSV
- Stores last 200 rows in memory for dashboard polling
- CSV log: `timestamp, ax, ay, az, distance, slip`

### `dashboard.py`
Flask web app at `http://localhost:5000`.

- Imports `SlipDetector` from `slip_detection.py`, runs it in a background thread
- Imports `GamepadController` from `gamepad_controller.py`, starts it on launch
- `--no-arm` flag skips servo controller (no Waveshare board needed)
- Dark-theme professional UI built for Ford hackathon demo
- **`--demo` flag**: synthetic sensor data, slip fires every 10 s, no Arduino needed
- `/` — serves dashboard HTML
- `/data?since=<epoch>` — returns JSON rows newer than timestamp
- `/analysis` — returns latest slip alert text
- `/status` — returns slip count
- `/servo_status` — returns servo positions and connection state
- Acceleration chart with red dashed vertical lines at each slip event
- Distance chart, slip event log, stat cards (slip count, ax std dev, distance)
- Full-width red flashing SLIP DETECTED banner, 5-second countdown, auto-hides
- `DemoDetector` class mirrors `SlipDetector` public API for UI testing

### `gamepad_controller.py`
Threaded arm controller. Imported by `dashboard.py`, also usable standalone.

- Opens Waveshare servo port at 1,000,000 baud using `scservo_sdk`
- On startup: **reads** current positions of all 6 servos — writes nothing
- `pygame` polls gamepad at 20 Hz; `inputs` library is NOT used (no macOS joystick support)
- **Button-only control** — no joystick axis input at all
- D-pad and face buttons each control exactly one servo; no crossover
- LT/RT are analog axes thresholded at `> 0.5` (strict greater-than prevents false trigger on pygame init)
- Position limits: 500–3500 global; gripper: 1000–3000
- `STEP = 30` units per tick; servo moves while button held, stops on release
- Logs each servo move to stdout: `[SERVO] ID 3 (elbow): 2949 → 2979`
- ID 2 (shoulder) is excluded from all write paths — read-only at startup
- `DEBUG_GAMEPAD = True` prints all raw button/hat/axis values for remapping

### `scan_servos.py`
One-shot scan script. Not part of live system.

- Probes servo IDs 1–10 on the Waveshare port and prints which respond with their current positions
- Used to discover servo IDs when arm was expanded from 4 to 6 servos

### `gripper_log.csv`
Auto-generated. Created on first run.
Columns: `timestamp, ax, ay, az, distance, slip`

### `test_voice.py`
Standalone ElevenLabs voice test. Sends a hardcoded message and plays via `afplay`.
Uses `eleven_flash_v2_5` model. Not part of the live system.

### `.env`
API credentials. Never committed.
```
ELEVENLABS_API_KEY=...   # used only by test_voice.py
```

---

## Servo IDs (confirmed by physical testing 2026-04-19)

| Servo ID | Position at scan | Joint | Status |
|----------|-----------------|-------|--------|
| 1 | 966 | Gripper | Active — not physically responding yet |
| 2 | 1786 | Shoulder | **LOCKED — never commanded, forever** |
| 3 | 2949 | Elbow | Working (LT/RT confirmed) |
| 4 | 1864 | Base rotation | Working (D-pad LEFT/RIGHT confirmed) |
| 5 | 1000 | Forearm up/down | Active — not physically responding yet |
| 6 | 1578 | Wrist clockwise/anticlockwise | Working (X/B confirmed) |

IDs confirmed by physical testing. IDs 7–10 did not respond to `scan_servos.py`.
ID 2 (shoulder) is permanently locked — do not send any write commands to it.

---

## Gamepad Button Mappings (button-only — no joystick axis input)

Controller: ShanWan Q34B (detected by pygame as "Nintendo Switch Pro Controller", 6 axes, 20 buttons)

| Input | pygame index | Servo ID | Joint | Direction |
|-------|-------------|----------|-------|-----------|
| D-pad UP | hat(0) y=+1 | 1 | Gripper | close |
| D-pad DOWN | hat(0) y=−1 | 1 | Gripper | open |
| D-pad LEFT | hat(0) x=−1 | 4 | Base | left |
| D-pad RIGHT | hat(0) x=+1 | 4 | Base | right |
| LB button | btn 4 | 4 | Base | left (alternate) |
| RB button | btn 5 | 4 | Base | right (alternate) |
| Y button | btn 2 | 5 | Forearm | up |
| A button | btn 1 | 5 | Forearm | down |
| X button | btn 3 | 6 | Wrist | clockwise |
| B button | btn 0 | 6 | Wrist | counter-clockwise |
| RT (axis 5 > 0.5) | axis 5 | 3 | Elbow | up |
| LT (axis 4 > 0.5) | axis 4 | 3 | Elbow | down |
| — | — | 2 | Shoulder | **LOCKED — never commanded** |

Step size: 30 units/tick at 20 Hz. Servo moves while held, stops immediately on release.
Input library: `pygame` — `inputs` library has no macOS joystick support and must not be used.

**If a button does the wrong thing:** set `DEBUG_GAMEPAD = True` at the top of `gamepad_controller.py`. It prints `btns=` / `hats=` / `axes=` on every active event. Note the index that lights up and update the corresponding `BTN_*` constant.

---

## Known Bugs Fixed

### Arm moves on startup (2026-04-19)
**Symptom:** Elbow moves as soon as dashboard launches, before any button is pressed.
**Cause:** pygame initializes analog trigger axes to `0.0` before the first hardware HID event. After remap `(0.0 + 1.0) / 2 = 0.5`. The old threshold check was `>= 0.5`, so both `lt_held` and `rt_held` were `True` on the very first servo tick.
**Fix:** Changed threshold check to `> TRIGGER_THRESHOLD` (strict greater-than). The startup default of exactly `0.5` no longer registers as a press. Hardware resting value after the first real event is `0.0`, well below the threshold.

---

## Current Issues

### Gripper (ID 1) not physically responding
Servo responds to scan (position 966) but does not move when D-pad UP/DOWN is pressed. Electrical or mechanical issue — servo communication appears OK.

### Forearm (ID 5) not physically responding
Servo responds to scan (position 1000) but does not move when Y/A is pressed. Same class of issue as gripper.

### Previous "wrist ID 2" issue — resolved by remapping
ID 2 is physically the shoulder joint (locked). The earlier non-response was because we were sending commands to the wrong servo. Wrist is ID 6, now correctly mapped to X/B.

---

## Demo Flow

1. Press D-pad UP → gripper closes, grabs object
2. Shake arm → MPU-6050 ax std dev spikes above 0.3g
3. Slip detected → Mac speaks "Warning. Grip instability detected. Acceleration spike of X g."
4. Dashboard fires red flashing banner, logs event, marks red line on acceleration chart

---

## Feature Status

| Feature | Status | Notes |
|---------|--------|-------|
| IMU streaming over Serial | Working | ~20 Hz, 4-field CSV |
| Ultrasonic distance | Working | 30 ms timeout for out-of-range |
| Slip detection (rolling std dev) | Working | 500 ms window, 0.3g threshold |
| Slip cooldown | Working | 2 s between events |
| CSV logging (throttled) | Working | 1 Hz normal, immediate on slip |
| macOS voice alert | Working | `say` command, non-blocking thread |
| Flask live dashboard | Working | Polls at 300 ms |
| Slip banner (flashing red) | Working | 5 s countdown, auto-hides |
| Acceleration chart + slip markers | Working | Red dashed vertical lines |
| Distance chart | Working | Last 100 points |
| Slip event log panel | Working | Timestamped list |
| Demo mode (`--demo`) | Working | No Arduino needed |
| SCServo arm control | Working | `scservo_sdk` via PyPI, all 6 IDs scanned and confirmed |
| Button-only gamepad control | Working | pygame backend; D-pad, face buttons, LT/RT |
| Startup motion bug | Fixed | Trigger `>=` → `>` threshold; no writes before first button press |
| Servo ID remapping | Fixed | Physical testing confirmed correct IDs; shoulder (ID 2) permanently locked |
| Elbow (ID 3) LT/RT | Working | Confirmed physically |
| Base (ID 4) D-pad LEFT/RIGHT | Working | Confirmed physically |
| Wrist (ID 6) X/B | Working | Confirmed physically |
| Gripper (ID 1) D-pad UP/DOWN | **Not responding** | Electrical/mechanical — servo scans OK |
| Forearm (ID 5) Y/A | **Not responding** | Electrical/mechanical — servo scans OK |

---

## Tunable Constants (`gamepad_controller.py`)

| Constant | Value | Effect |
|----------|-------|--------|
| `STEP` | 30 | Position units per tick per button press |
| `SERVO_SPEED` | 1000 | Servo travel speed (0–32767) |
| `LOOP_HZ` | 20 | Control loop frequency |
| `TRIGGER_THRESHOLD` | 0.5 | LT/RT axis value (0–1) above which trigger counts as held |
| `POSITION_MIN` | 500 | Global lower clamp for all servos |
| `POSITION_MAX` | 3500 | Global upper clamp for all servos |
| `GRIPPER_MIN` | 1000 | Gripper-specific lower clamp |
| `GRIPPER_MAX` | 3000 | Gripper-specific upper clamp |
| `DEBUG_GAMEPAD` | False | Set True to print all raw button/hat/axis events |

---

## Tunable Constants (`slip_detection.py`)

| Constant | Value | Effect |
|----------|-------|--------|
| `SERIAL_PORT` | `/dev/cu.usbmodem21201` | Arduino serial port |
| `SERIAL_BAUD` | 115200 | Must match `Serial.begin()` in Arduino |
| `SLIP_WINDOW_MS` | 500 | Rolling window length for std dev |
| `SLIP_THRESHOLD_G` | 0.3 | ax std dev above this triggers slip |
| `SLIP_COOLDOWN_S` | 2.0 | Minimum seconds between slip events |
| `MAX_STORED_ROWS` | 200 | Rows kept in memory for dashboard |
| `LOG_FILE` | `gripper_log.csv` | Output CSV filename |

---

## How to Run

```bash
# Install dependencies
pip install flask pyserial python-dotenv pygame scservo_sdk

# Run dashboard (starts slip detector + arm controller)
python3 dashboard.py

# Run in demo mode (no Arduino needed)
python3 dashboard.py --demo

# Skip arm controller (no Waveshare board)
python3 dashboard.py --no-arm

# Run slip detector alone
python3 slip_detection.py

# Scan servo IDs (run once to discover IDs)
python3 scan_servos.py
```

Open `http://localhost:5000` in a browser.

---

## Serial Data Format

Arduino → Python, CSV, ~20 Hz:
```
ax,ay,az,distance
-0.02,0.01,1.00,14.32
```
