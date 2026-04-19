# Smart Adaptive Gripper — Project Context

Ford Hackathon project. An Arduino-controlled robotic gripper that autonomously detects when it is losing grip (slip) using an IMU, tightens itself, speaks a voice warning, and streams live sensor data to a web dashboard.

---

## Hardware

| Component | Part | Connection |
|-----------|------|------------|
| Microcontroller | Arduino Mega 2560 | USB → `/dev/cu.usbmodem21201` |
| IMU | MPU-6050 | I2C — SDA pin 20, SCL pin 21 |
| Distance sensor | HC-SR04 ultrasonic | Trig pin 9, Echo pin 10 |
| Touch sensor | TTP223 capacitive | Pin 7 |
| Servo | MG90S | Pin 6 |

---

## Files

### `gripper.ino`
Arduino sketch. Runs on the Mega 2560.

- Reads MPU-6050 accelerometer via direct I2C register reads (no library)
- Reads HC-SR04 distance via `pulseIn()`
- Reads TTP223 touch via `digitalRead()`
- Auto-grip logic: closes servo to 90° when object within `GRIP_DISTANCE_CM`; reopens when object gone and touch is 0
- Listens for `'T'` over Serial → tightens servo by `TIGHTEN_DEGREES` (max `SERVO_MAX`)
- Streams CSV at ~20 Hz over Serial at 115200 baud: `ax,ay,az,distance,touch`
- Libraries used: `Wire.h`, `Servo.h` (both built-in, no install needed)

### `slip_detection.py`
Core Python module. Can run standalone or be imported by `dashboard.py`.

- Opens serial port, parses CSV from Arduino at 115200 baud
- Maintains a rolling time window of ax values (`SLIP_WINDOW_MS`)
- Computes population std dev of ax within the window every reading
- Slip detected when std dev > `SLIP_THRESHOLD_G` AND cooldown has elapsed
- On slip: sends `'T\n'` to Arduino, fires background thread for speech
- Speech: builds message with real ax_std value → POST to ElevenLabs API → plays MP3 via `afplay`
- CSV logging: every 1 second for normal data, immediately on every slip
- Stores last `MAX_STORED_ROWS` rows in memory for dashboard polling
- All pipeline steps print timestamped trace logs to terminal

### `dashboard.py`
Flask web app at `http://localhost:5000`.

- Imports `SlipDetector` from `slip_detection.py`, runs it in a background thread
- `/` — serves inline HTML page with Chart.js live graphs
- `/data?since=<epoch>` — returns JSON of rows newer than timestamp
- `/analysis` — returns latest ElevenLabs speech text (polled by JS after slip)
- Live charts: Acceleration (ax, ay, az) and Distance, each updating every 300 ms
- Red SLIP DETECTED banner appears on slip, shows the spoken message, auto-hides after 12 s
- Slip log panel records every event with timestamp

### `gripper_log.csv`
Auto-generated data log. Created in the working directory on first run.

- Columns: `timestamp, ax, ay, az, distance, touch, slip`
- Normal rows: written at most once per second
- Slip rows: written immediately regardless of the 1-second throttle

### `.env`
API credentials. Never commit this file.

```
GEMINI_API_KEY=...           # unused currently (Gemini removed)
ELEVENLABS_API_KEY=...       # required for voice alerts
ELEVENLABS_VOICE_ID=...      # optional, defaults to Rachel
```

---

## Feature Status

| Feature | Status | Notes |
|---------|--------|-------|
| IMU streaming over Serial | Working | ~20 Hz, CSV format |
| Ultrasonic distance | Working | 30 ms timeout for out-of-range |
| Capacitive touch | Working | Digital read on pin 7 |
| Auto-grip on proximity | Working | Triggers at 20 cm |
| Slip detection (rolling std dev) | Working | 500 ms window, 0.3g threshold |
| Servo tighten on slip | Working | +5° per slip command, max 175° |
| Slip cooldown | Working | 2 s between events |
| CSV logging (throttled) | Working | 1 Hz normal, immediate on slip |
| ElevenLabs voice alert | Working | Speaks ax_std value aloud |
| Flask live dashboard | Working | Polls at 300 ms |
| Live acceleration chart | Working | ax, ay, az last 80 points |
| Live distance chart | Working | Last 80 points |
| Red slip banner | Working | Shows spoken message, hides after 12 s |
| Slip event log panel | Working | Timestamped list in dashboard |

---

## Tunable Constants

### `gripper.ino`

| Constant | Value | Effect |
|----------|-------|--------|
| `GRIP_DISTANCE_CM` | 20 | Object must be closer than this (cm) to trigger grip |
| `TIGHTEN_DEGREES` | 5 | Degrees added to servo angle on each `'T'` command |
| `SERVO_OPEN` | 0° | Resting/open position |
| `SERVO_GRIP` | 90° | Initial grip angle when object detected |
| `SERVO_MAX` | 175° | Hard ceiling — servo never exceeds this |

### `slip_detection.py`

| Constant | Value | Effect |
|----------|-------|--------|
| `SERIAL_PORT` | `/dev/cu.usbmodem21201` | Arduino serial port |
| `SERIAL_BAUD` | 115200 | Must match `Serial.begin()` in Arduino |
| `SLIP_WINDOW_MS` | 500 | Rolling window length for std dev calculation |
| `SLIP_THRESHOLD_G` | 0.3 | ax std dev above this triggers slip (lower = more sensitive) |
| `SLIP_COOLDOWN_S` | 2.0 | Minimum seconds between consecutive slip events |
| `MAX_STORED_ROWS` | 200 | How many rows kept in memory for dashboard |
| `LOG_FILE` | `gripper_log.csv` | Output CSV filename |
| `ELEVENLABS_VOICE` | Rachel (`21m00Tcm4TlvDq8ikWAM`) | Override via `ELEVENLABS_VOICE_ID` in `.env` |

### `dashboard.py`

| Constant | Value | Effect |
|----------|-------|--------|
| `FLASK_HOST` | `127.0.0.1` | Change to `0.0.0.0` to expose on local network |
| `FLASK_PORT` | 5000 | Dashboard URL port |

---

## How to Run

```bash
# 1. Install dependencies
pip install flask pyserial python-dotenv requests

# 2. Fill in .env
echo "ELEVENLABS_API_KEY=your_key_here" >> .env

# 3. Upload gripper.ino via Arduino IDE (Board: Mega 2560)

# 4. Run dashboard (starts everything)
python dashboard.py

# — or — run slip detector alone (no browser)
python slip_detection.py
```

Open `http://localhost:5000` in a browser.

---

## Serial Data Format

Arduino → Python, CSV, ~20 Hz:
```
ax,ay,az,distance,touch
-0.02,0.01,1.00,14.32,1
```

Python → Arduino, on slip:
```
T\n
```
