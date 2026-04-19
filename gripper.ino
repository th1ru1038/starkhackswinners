// gripper.ino — Smart Adaptive Gripper
// Arduino Mega 2560
// Streams CSV over Serial: ax,ay,az,distance,touch
// Receives 'T' to tighten, 'O' to open, 'G' to grip

#include <Wire.h>
#include <Servo.h>

// ── Pin assignments ───────────────────────────────────────────
#define TRIG_PIN   9    // HC-SR04 trigger
#define ECHO_PIN   10   // HC-SR04 echo
#define TOUCH_PIN  7    // TTP223 capacitive touch
#define SERVO_PIN  6    // MG90S servo signal

// ── Tunable constants ─────────────────────────────────────────
#define GRIP_DISTANCE_CM  20    // close gripper when object closer than this
#define TIGHTEN_DEGREES   5     // degrees added per slip command
#define SERVO_OPEN        0     // fully open angle
#define SERVO_GRIP        90    // initial grip angle
#define SERVO_MAX         175   // safety ceiling

// ── MPU-6050 ──────────────────────────────────────────────────
#define MPU_ADDR  0x68          // I2C address (AD0 pin low)

Servo gripper;
int   servoAngle = SERVO_OPEN;
bool  gripping   = false;

// ─────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  // Wake up MPU-6050 (it starts in sleep mode)
  Wire.begin();
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);   // PWR_MGMT_1 register
  Wire.write(0x00);   // 0 = wake
  Wire.endTransmission(true);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(TOUCH_PIN, INPUT);

  gripper.attach(SERVO_PIN);
  gripper.write(servoAngle);

  delay(200);  // let sensors stabilise
}

// ─────────────────────────────────────────────────────────────
void loop() {
  checkSerialCommands();

  float ax, ay, az;
  readMPU(ax, ay, az);

  float distance = readDistance();
  int   touch    = digitalRead(TOUCH_PIN);

  updateGripLogic(distance, touch);

  // CSV output: ax,ay,az,distance,touch
  Serial.print(ax, 3);      Serial.print(",");
  Serial.print(ay, 3);      Serial.print(",");
  Serial.print(az, 3);      Serial.print(",");
  Serial.print(distance, 2); Serial.print(",");
  Serial.println(touch);

  delay(50);  // ~20 Hz
}

// ── Read accelerometer from MPU-6050 via I2C ─────────────────
void readMPU(float &ax, float &ay, float &az) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);                   // ACCEL_XOUT_H register
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, 6, true);

  int16_t rawX = (Wire.read() << 8) | Wire.read();
  int16_t rawY = (Wire.read() << 8) | Wire.read();
  int16_t rawZ = (Wire.read() << 8) | Wire.read();

  // Default ±2g range → 16384 LSB per g
  ax = rawX / 16384.0;
  ay = rawY / 16384.0;
  az = rawZ / 16384.0;
}

// ── Measure distance in cm with HC-SR04 ──────────────────────
float readDistance() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // 30 ms timeout avoids blocking when nothing is in range
  long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duration == 0) return 999.0;
  return duration * 0.0343 / 2.0;
}

// ── Auto open/close logic ─────────────────────────────────────
void updateGripLogic(float distance, int touch) {
  if (!gripping && distance < GRIP_DISTANCE_CM) {
    servoAngle = SERVO_GRIP;
    gripper.write(servoAngle);
    gripping = true;
  } else if (gripping && distance >= GRIP_DISTANCE_CM && touch == 0) {
    servoAngle = SERVO_OPEN;
    gripper.write(servoAngle);
    gripping = false;
  }
}

// ── Handle serial commands from Python ───────────────────────
// T — tighten (+5°, max SERVO_MAX)
// O — open    (0°,  gripping = false)
// G — grip    (90°, gripping = true)
void checkSerialCommands() {
  while (Serial.available()) {
    char cmd = Serial.read();
    if (cmd == 'T') {
      servoAngle = min(servoAngle + TIGHTEN_DEGREES, SERVO_MAX);
      gripper.write(servoAngle);
    } else if (cmd == 'O') {
      servoAngle = SERVO_OPEN;
      gripper.write(servoAngle);
      gripping = false;
    } else if (cmd == 'G') {
      servoAngle = SERVO_GRIP;
      gripper.write(servoAngle);
      gripping = true;
    }
  }
}
