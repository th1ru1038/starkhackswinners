// gripper.ino — Smart Adaptive Gripper
// Arduino Mega 2560
// Hardware: MPU-6050 (SDA pin 20, SCL pin 21), HC-SR04 (Trig 9, Echo 10)
// Streams CSV over Serial at 115200 baud: ax,ay,az,distance

#include <Wire.h>

// ── Pin assignments ───────────────────────────────────────────
#define TRIG_PIN   9    // HC-SR04 trigger
#define ECHO_PIN   10   // HC-SR04 echo

// ── MPU-6050 ──────────────────────────────────────────────────
#define MPU_ADDR  0x68  // I2C address (AD0 pin low)

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

  delay(200);  // let sensors stabilise
}

// ─────────────────────────────────────────────────────────────
void loop() {
  float ax, ay, az;
  readMPU(ax, ay, az);

  float distance = readDistance();

  // CSV output: ax,ay,az,distance
  Serial.print(ax, 3);       Serial.print(",");
  Serial.print(ay, 3);       Serial.print(",");
  Serial.print(az, 3);       Serial.print(",");
  Serial.println(distance, 2);

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
