"""
gamepad_controller.py — Threaded gamepad → SCServo arm controller
Button-only control. No joystick axis input.

Servo IDs (confirmed by physical testing 2026-04-19):
  ID 1  gripper          D-pad UP (close) / D-pad DOWN (open)
  ID 2  shoulder         LOCKED — never commanded
  ID 3  elbow            RT (up)          / LT (down)
  ID 4  base rotation    D-pad RIGHT      / D-pad LEFT
  ID 5  forearm          Y button (up)    / A button (down)
  ID 6  wrist            X button (CW)    / B button (CCW)

Each held button moves its servo by STEP=30 units per tick (20 Hz).
Servo stops immediately when button released.

Port: /dev/cu.usbmodem5A7C1172351 at 1,000,000 baud
Input backend: pygame (macOS IOKit HID). `inputs` lib not used.
"""

import os
import threading
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

SERVO_PORT = "/dev/cu.usbmodem5A7C1172351"
SERVO_BAUD = 1_000_000

ADDR_GOAL_POSITION    = 42
ADDR_PRESENT_POSITION = 56

POSITION_MIN = 500
POSITION_MAX = 3500
GRIPPER_MIN  = 1000
GRIPPER_MAX  = 3000

# Servo IDs — confirmed by physical testing 2026-04-19
SERVO_GRIPPER  = 1
SERVO_SHOULDER = 2   # LOCKED — never written
SERVO_ELBOW    = 3
SERVO_BASE     = 4
SERVO_FOREARM  = 5
SERVO_WRIST    = 6

_SERVO_NAMES = {
    SERVO_GRIPPER:  "gripper",
    SERVO_SHOULDER: "shoulder(LOCKED)",
    SERVO_ELBOW:    "elbow",
    SERVO_BASE:     "base",
    SERVO_FOREARM:  "forearm",
    SERVO_WRIST:    "wrist",
}

_ACTIVE_SERVOS = (SERVO_GRIPPER, SERVO_ELBOW, SERVO_BASE, SERVO_FOREARM, SERVO_WRIST)

# ── Button indices (Nintendo Switch Pro Controller layout via pygame/macOS) ──
# Run with DEBUG_GAMEPAD=True to verify on your hardware.
BTN_B  = 0   # wrist CCW
BTN_A  = 1   # forearm down
BTN_Y  = 2   # forearm up
BTN_X  = 3   # wrist CW
BTN_LB = 4   # base rotate left
BTN_RB = 5   # base rotate right

# LT / RT are analog axes remapped to 0…1; threshold 0.5 → digital held-button
AXIS_LT = 4
AXIS_RT = 5
TRIGGER_THRESHOLD = 0.5   # fraction above which trigger counts as "held"

# D-pad via hat 0: get_hat(0) returns (x, y)
#   UP=(0,1)  DOWN=(0,-1)  LEFT=(-1,0)  RIGHT=(1,0)
HAT_INDEX = 0

STEP     = 30    # position units per tick while button held
SERVO_SPEED = 1000
LOOP_HZ  = 20

# Set True once to print all raw button/hat/axis events for layout verification
DEBUG_GAMEPAD = False


class GamepadController:
    def __init__(self, port: str = SERVO_PORT, baud: int = SERVO_BAUD):
        self._port = port
        self._baud = baud
        self._running = False
        self._lock = threading.Lock()

        self._positions: dict[int, int] = {}

        # Button states — True means actively held this tick
        self._dpad_up    = False
        self._dpad_down  = False
        self._dpad_left  = False
        self._dpad_right = False
        self._btn_y      = False   # forearm up
        self._btn_a      = False   # forearm down
        self._btn_x      = False   # wrist CW
        self._btn_b      = False   # wrist CCW
        self._btn_lb     = False   # base rotate left
        self._btn_rb     = False   # base rotate right
        self._lt_held    = False   # elbow down
        self._rt_held    = False   # elbow up

        self._servo_connected  = False
        self._gamepad_detected = False
        self._port_handler     = None
        self._packet_handler   = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        self._running = True
        threading.Thread(target=self._servo_loop, daemon=True, name="servo-ctrl").start()
        threading.Thread(target=self._input_loop, daemon=True, name="gamepad-in").start()

    def stop(self):
        self._running = False
        if self._port_handler:
            try:
                self._port_handler.closePort()
            except Exception:
                pass

    def get_status(self) -> dict:
        with self._lock:
            pos = dict(self._positions)
        return {
            "servo_connected":  self._servo_connected,
            "gamepad_detected": self._gamepad_detected,
            "positions": {
                "gripper":  pos.get(SERVO_GRIPPER,  0),
                "wrist":    pos.get(SERVO_WRIST,    0),
                "elbow":    pos.get(SERVO_ELBOW,    0),
                "base":     pos.get(SERVO_BASE,     0),
                "forearm":  pos.get(SERVO_FOREARM,  0),
                "shoulder": pos.get(SERVO_SHOULDER, 0),
            },
        }

    # ── Servo thread ──────────────────────────────────────────────────────────

    def _connect_servo(self) -> bool:
        try:
            from scservo_sdk import PortHandler, PacketHandler
        except ImportError:
            print("[SERVO] scservo_sdk not installed — run: pip install scservo_sdk")
            return False

        try:
            self._port_handler   = PortHandler(self._port)
            self._packet_handler = PacketHandler(0)

            if not self._port_handler.openPort():
                print(f"[SERVO] Cannot open {self._port}")
                return False
            if not self._port_handler.setBaudRate(SERVO_BAUD):
                print(f"[SERVO] Cannot set baud {SERVO_BAUD}")
                return False

            print("[SERVO] Reading current servo positions…")
            from scservo_sdk import COMM_SUCCESS
            positions = {}
            read_ok = True
            for sid in (SERVO_GRIPPER, SERVO_SHOULDER, SERVO_ELBOW,
                        SERVO_BASE, SERVO_FOREARM, SERVO_WRIST):
                pos, result, _ = self._packet_handler.read2ByteTxRx(
                    self._port_handler, sid, ADDR_PRESENT_POSITION
                )
                name = _SERVO_NAMES[sid]
                if result == COMM_SUCCESS:
                    positions[sid] = pos
                    lock = "  [LOCKED]" if sid == SERVO_SHOULDER else ""
                    print(f"  ID {sid} ({name:>16}): {pos}{lock}")
                else:
                    print(f"  ID {sid} ({name:>16}): READ FAILED — offline?")
                    if sid != SERVO_SHOULDER:
                        read_ok = False

            with self._lock:
                self._positions = positions
                self._servo_connected = read_ok

            print(f"[SERVO] {'All online' if read_ok else 'WARNING: some offline'}. "
                  f"Range {POSITION_MIN}–{POSITION_MAX}, step {STEP}/tick @ {LOOP_HZ} Hz")
            return True

        except Exception as exc:
            print(f"[SERVO] Connection error: {exc}")
            return False

    def _write_pos(self, servo_id: int, position: int):
        from scservo_sdk import SCS_LOBYTE, SCS_HIBYTE
        data = [
            SCS_LOBYTE(position), SCS_HIBYTE(position),
            0, 0,
            SCS_LOBYTE(SERVO_SPEED), SCS_HIBYTE(SERVO_SPEED),
        ]
        self._packet_handler.writeTxOnly(
            self._port_handler, servo_id, ADDR_GOAL_POSITION, 6, data
        )

    def _clamp(self, value: int) -> int:
        return max(POSITION_MIN, min(POSITION_MAX, value))

    def _servo_loop(self):
        if not self._connect_servo():
            return

        interval = 1.0 / LOOP_HZ
        while self._running:
            with self._lock:
                dpad_up    = self._dpad_up
                dpad_down  = self._dpad_down
                dpad_left  = self._dpad_left
                dpad_right = self._dpad_right
                btn_y      = self._btn_y
                btn_a      = self._btn_a
                btn_x      = self._btn_x
                btn_b      = self._btn_b
                btn_lb     = self._btn_lb
                btn_rb     = self._btn_rb
                lt_held    = self._lt_held
                rt_held    = self._rt_held
                old        = dict(self._positions)

            new = dict(old)

            # ID 1 — gripper: D-pad UP closes, D-pad DOWN opens
            if SERVO_GRIPPER in old:
                if dpad_up:
                    new[SERVO_GRIPPER] = max(GRIPPER_MIN, min(GRIPPER_MAX,
                                            old[SERVO_GRIPPER] + STEP))
                elif dpad_down:
                    new[SERVO_GRIPPER] = max(GRIPPER_MIN, min(GRIPPER_MAX,
                                            old[SERVO_GRIPPER] - STEP))

            # ID 2 — shoulder: intentionally excluded, never written

            # ID 3 — elbow: RT up, LT down
            if SERVO_ELBOW in old:
                if rt_held:
                    new[SERVO_ELBOW] = self._clamp(old[SERVO_ELBOW] + STEP)
                elif lt_held:
                    new[SERVO_ELBOW] = self._clamp(old[SERVO_ELBOW] - STEP)

            # ID 4 — base: D-pad RIGHT / RB rotate right, D-pad LEFT / LB rotate left
            if SERVO_BASE in old:
                if dpad_right or btn_rb:
                    new[SERVO_BASE] = self._clamp(old[SERVO_BASE] + STEP)
                elif dpad_left or btn_lb:
                    new[SERVO_BASE] = self._clamp(old[SERVO_BASE] - STEP)

            # ID 5 — forearm: Y up, A down
            if SERVO_FOREARM in old:
                if btn_y:
                    new[SERVO_FOREARM] = self._clamp(old[SERVO_FOREARM] + STEP)
                elif btn_a:
                    new[SERVO_FOREARM] = self._clamp(old[SERVO_FOREARM] - STEP)

            # ID 6 — wrist: X clockwise, B counterclockwise
            if SERVO_WRIST in old:
                if btn_x:
                    new[SERVO_WRIST] = self._clamp(old[SERVO_WRIST] + STEP)
                elif btn_b:
                    new[SERVO_WRIST] = self._clamp(old[SERVO_WRIST] - STEP)

            # ID 2 — shoulder: intentionally excluded, never written

            for sid in _ACTIVE_SERVOS:
                if sid in new and sid in old and new[sid] != old[sid]:
                    try:
                        self._write_pos(sid, new[sid])
                        print(f"[SERVO] ID {sid} ({_SERVO_NAMES[sid]:>7}): "
                              f"{old[sid]} → {new[sid]}")
                    except Exception as exc:
                        print(f"[SERVO] Write error (ID {sid}): {exc}")

            with self._lock:
                self._positions = new

            time.sleep(interval)

    # ── Gamepad input thread (pygame) ─────────────────────────────────────────

    def _input_loop(self):
        try:
            import pygame
        except ImportError:
            print("[GAMEPAD] pygame not installed — run: pip install pygame")
            return

        pygame.init()
        pygame.joystick.init()

        joystick = None
        interval = 1.0 / LOOP_HZ

        while self._running:
            if joystick is None:
                pygame.joystick.quit()
                pygame.joystick.init()
                if pygame.joystick.get_count() == 0:
                    with self._lock:
                        self._gamepad_detected = False
                    print("[GAMEPAD] No joystick found — retrying in 2 s…")
                    time.sleep(2)
                    continue

                joystick = pygame.joystick.Joystick(0)
                joystick.init()
                name   = joystick.get_name()
                n_btns = joystick.get_numbuttons()
                n_hats = joystick.get_numhats()
                print(f"[GAMEPAD] Connected: {name!r}  ({n_btns} buttons, {n_hats} hats)")
                print("[GAMEPAD] Button-only mode:")
                print("  D-pad UP/DOWN → gripper  | D-pad LEFT/RIGHT or LB/RB → base")
                print("  Y/A → forearm up/down     | X/B → wrist CW/CCW")
                print("  RT/LT → elbow up/down     | shoulder(ID2) LOCKED")
                if DEBUG_GAMEPAD:
                    print("[GAMEPAD] DEBUG: printing all non-zero buttons/hats/triggers")
                with self._lock:
                    self._gamepad_detected = True

            try:
                pygame.event.pump()

                if DEBUG_GAMEPAD:
                    btns = [i for i in range(joystick.get_numbuttons())
                            if joystick.get_button(i)]
                    hats = [joystick.get_hat(i) for i in range(joystick.get_numhats())]
                    axes = [round(joystick.get_axis(i), 3)
                            for i in range(joystick.get_numaxes())]
                    if btns or any(h != (0, 0) for h in hats) or any(abs(a) > 0.05 for a in axes):
                        print(f"[DBG] btns={btns}  hats={hats}  axes={axes}")

                # D-pad via hat
                hx, hy = joystick.get_hat(HAT_INDEX) if joystick.get_numhats() > 0 else (0, 0)
                dpad_up    = hy == 1
                dpad_down  = hy == -1
                dpad_left  = hx == -1
                dpad_right = hx == 1

                # Face buttons
                btn_y = bool(joystick.get_button(BTN_Y))
                btn_a = bool(joystick.get_button(BTN_A))
                btn_x = bool(joystick.get_button(BTN_X))
                btn_b = bool(joystick.get_button(BTN_B))

                # Shoulder buttons
                btn_lb = bool(joystick.get_button(BTN_LB))
                btn_rb = bool(joystick.get_button(BTN_RB))

                # LT / RT: analog axes → digital threshold
                lt_raw = (joystick.get_axis(AXIS_LT) + 1.0) / 2.0
                rt_raw = (joystick.get_axis(AXIS_RT) + 1.0) / 2.0
                lt_held = lt_raw > TRIGGER_THRESHOLD
                rt_held = rt_raw > TRIGGER_THRESHOLD

                with self._lock:
                    self._dpad_up    = dpad_up
                    self._dpad_down  = dpad_down
                    self._dpad_left  = dpad_left
                    self._dpad_right = dpad_right
                    self._btn_y      = btn_y
                    self._btn_a      = btn_a
                    self._btn_x      = btn_x
                    self._btn_b      = btn_b
                    self._btn_lb     = btn_lb
                    self._btn_rb     = btn_rb
                    self._lt_held    = lt_held
                    self._rt_held    = rt_held

            except Exception as exc:
                print(f"[GAMEPAD] Error: {exc}")
                joystick = None
                with self._lock:
                    self._gamepad_detected = False

            time.sleep(interval)

        pygame.quit()
