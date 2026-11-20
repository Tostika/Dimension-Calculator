// ESP32 firmware for the dimension measuring device.
// Controls the LED strip brightness (PWM through the IRLZ44N MOSFET) and the camera lift
// (NEMA 17 through a DRV8825 driver, T8 lead screw with 2 mm lead, limit switch at the TOP).
//
// Serial, 115200 baud, one command per line:
//   PING        -> PONG
//   LED 0..100  -> OK                 LED brightness in percent
//   HOME        -> OK HOME            moves up until the limit switch, then sets Z = Z_HOME_MM
//   Z 300       -> OK Z 300.0         moves the camera so the lens is 300 mm above the base
//   Z?          -> Z 300.0
//   EN 0 / EN 1 -> OK                 motor power off / on (it is switched off after every move)
//
// Board: "ESP32 Dev Module". Works with ESP32 Arduino core 2.x and 3.x.

// ---------- pins ----------
const int PIN_LED   = 25;   // to MOSFET gate through 100 ohm, 10 k pull-down to GND
const int PIN_STEP  = 26;
const int PIN_DIR   = 27;
const int PIN_EN    = 14;   // DRV8825 EN: LOW = motor on
const int PIN_LIMIT = 33;   // limit switch between this pin and GND (pressed = LOW)

// ---------- mechanics: measure and adjust these after building ----------
const float STEPS_PER_MM = 200.0 * 16.0 / 2.0; // 200 steps/rev, 1/16 microstep, 2 mm per turn = 1600
const float Z_HOME_MM    = 450.0;  // lens height above the base when the limit switch clicks
const float Z_MIN_MM     = 350.0;  // the app uses 35-40 cm; never go lower than this
const bool  DIR_UP_LEVEL = HIGH;   // if the camera goes down on HOME, change to LOW
const float SPEED_MM_S   = 6.0;    // top speed
const float ACCEL_MM_S2  = 20.0;

// ---------- LED PWM ----------
const int PWM_FREQ = 20000;        // 20 kHz: no flicker in the camera image
const int PWM_BITS = 10;

float zNow = -1;                   // -1 = not homed yet
String line;

void ledWritePercent(int p) {
  p = constrain(p, 0, 100);
  uint32_t duty = (uint32_t)((p / 100.0) * ((1 << PWM_BITS) - 1));
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(PIN_LED, duty);
#else
  ledcWrite(0, duty);
#endif
}

void motorEnable(bool on) { digitalWrite(PIN_EN, on ? LOW : HIGH); }

bool limitPressed() { return digitalRead(PIN_LIMIT) == LOW; }

// Moves `steps` steps (positive = up) with a simple speed ramp. Stops early if going up and the switch clicks.
long moveSteps(long steps, bool stopAtLimit) {
  if (steps == 0) return 0;
  bool up = steps > 0;
  long total = labs(steps);
  digitalWrite(PIN_DIR, up ? DIR_UP_LEVEL : !DIR_UP_LEVEL);
  motorEnable(true);
  delay(5);
  float vmax = SPEED_MM_S * STEPS_PER_MM;          // steps per second
  float acc = ACCEL_MM_S2 * STEPS_PER_MM;
  float v = 200;                                   // start speed
  long done = 0;
  while (done < total) {
    if (up && stopAtLimit && limitPressed()) break;
    long left = total - done;
    float vStop = sqrt(2.0 * acc * left);          // slow down near the end
    float target = min(vmax, vStop);
    if (v < target) v = min(target, v + acc / v); else v = max(200.0f, target);
    unsigned long half = (unsigned long)(500000.0 / v);
    digitalWrite(PIN_STEP, HIGH);
    delayMicroseconds(half);
    digitalWrite(PIN_STEP, LOW);
    delayMicroseconds(half);
    done++;
  }
  motorEnable(false);                              // lead screw holds the camera by itself
  return up ? done : -done;
}

bool home() {
  // go up until the switch clicks (at most 400 mm), back off 3 mm, touch it again slowly
  moveSteps((long)(400 * STEPS_PER_MM), true);
  if (!limitPressed()) return false;
  moveSteps(-(long)(3 * STEPS_PER_MM), false);
  digitalWrite(PIN_DIR, DIR_UP_LEVEL);
  motorEnable(true);
  for (long i = 0; i < (long)(5 * STEPS_PER_MM) && !limitPressed(); i++) {
    digitalWrite(PIN_STEP, HIGH); delayMicroseconds(400);
    digitalWrite(PIN_STEP, LOW);  delayMicroseconds(400);
  }
  motorEnable(false);
  zNow = Z_HOME_MM;
  return true;
}

void handle(String cmd) {
  cmd.trim();
  if (cmd == "PING") { Serial.println("PONG"); return; }
  if (cmd.startsWith("LED ")) { ledWritePercent(cmd.substring(4).toInt()); Serial.println("OK"); return; }
  if (cmd == "HOME") { Serial.println(home() ? "OK HOME" : "ERR LIMIT"); return; }
  if (cmd == "Z?") { Serial.print("Z "); Serial.println(zNow, 1); return; }
  if (cmd.startsWith("Z ")) {
    if (zNow < 0 && !home()) { Serial.println("ERR LIMIT"); return; }
    float target = constrain(cmd.substring(2).toFloat(), Z_MIN_MM, Z_HOME_MM);
    long steps = lround((target - zNow) * STEPS_PER_MM);  // up = camera higher = positive
    moveSteps(steps, true);
    zNow = target;
    if (limitPressed()) zNow = Z_HOME_MM;
    Serial.print("OK Z "); Serial.println(zNow, 1);
    return;
  }
  if (cmd == "EN 1") { motorEnable(true); Serial.println("OK"); return; }
  if (cmd == "EN 0") { motorEnable(false); Serial.println("OK"); return; }
  Serial.println("ERR UNKNOWN");
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_STEP, OUTPUT);
  pinMode(PIN_DIR, OUTPUT);
  pinMode(PIN_EN, OUTPUT);
  pinMode(PIN_LIMIT, INPUT_PULLUP);
  motorEnable(false);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PIN_LED, PWM_FREQ, PWM_BITS);
#else
  ledcSetup(0, PWM_FREQ, PWM_BITS);
  ledcAttachPin(PIN_LED, 0);
#endif
  ledWritePercent(0);
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (line.length()) handle(line);
      line = "";
    } else if (line.length() < 40) {
      line += c;
    }
  }
}
