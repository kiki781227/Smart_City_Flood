// flood_city_mega_ultrasonic.ino
// Arduino Mega - 3 zones with ultrasonic sensors, RG LEDs, 3 pump relays
// Compatible with Streamlit interface expecting:
// STATE Z1=raw,flood Z2=raw,flood Z3=raw,flood P=Zx|NONE MODE=AUTO|MANUAL
//
// Here "raw" = water level percentage (0..100)

#include <Arduino.h>

static const bool RELAY_ACTIVE_LOW = false;   // false if your relay is active HIGH

// =====================================================
// PINS - ARDUINO MEGA
// =====================================================

// Ultrasonic sensors: TRIG + ECHO for each zone
const int TRIG_PINS[3] = {22, 24, 26};
const int ECHO_PINS[3] = {23, 25, 27};

// LEDs per zone (Red, Green)
const int LED_R_PINS[3] = {2, 4, 6};
const int LED_G_PINS[3] = {3, 5, 7};

// Pump relays
const int RELAY_PINS[3] = {8, 9, 10};   // Z1, Z2, Z3

// =====================================================
// WATER LEVEL CONFIG
// =====================================================

// Maximum useful water depth for each zone in cm
// Example: if container depth is 20 cm, use 20.0
float MAX_WATER_DEPTH_CM[3] = {20.0, 20.0, 20.0};

// Distance from sensor to water when zone is empty/safe
// Usually close to MAX_WATER_DEPTH_CM if sensor is mounted at top
float EMPTY_DISTANCE_CM[3] = {20.0, 20.0, 20.0};

// Distance from sensor to water when zone is full / critical
// Could be near 2-3 cm depending on sensor placement
float FULL_DISTANCE_CM[3]  = {3.0, 3.0, 3.0};

// Flood threshold in percentage
int THRESH_PCT[3] = {60, 60, 60};

// Hysteresis in percentage
int HYST = 5;

// Flood states
bool flooded[3] = {false, false, false};

// =====================================================
// MODE
// =====================================================
enum Mode { MODE_AUTO, MODE_MANUAL };
Mode mode = MODE_AUTO;

// =====================================================
// PUMP LOCK
// =====================================================
int pump_active_idx = -1;                    // -1 = none, else 0..2
unsigned long pump_started_ms = 0;
const unsigned long PUMP_MAX_MS = 15000;     // safety cutoff after 15 seconds

// =====================================================
// SERIAL / TIMING
// =====================================================
unsigned long lastStateMs = 0;
const unsigned long STATE_INTERVAL_MS = 1000;

// =====================================================
// HELPERS
// =====================================================

void relay_write(int pin, bool on) {
  if (RELAY_ACTIVE_LOW) {
    digitalWrite(pin, on ? LOW : HIGH);
  } else {
    digitalWrite(pin, on ? HIGH : LOW);
  }
}

void set_led(int idx, bool isFlooded) {
  // Safe = green, Flooded = red
  digitalWrite(LED_R_PINS[idx], isFlooded ? HIGH : LOW);
  digitalWrite(LED_G_PINS[idx], isFlooded ? LOW : HIGH);
}

void pumps_all_off() {
  for (int i = 0; i < 3; i++) {
    relay_write(RELAY_PINS[i], false);
  }
  pump_active_idx = -1;
}

bool pump_start(int idx) {
  if (pump_active_idx != -1 && pump_active_idx != idx) {
    return false; // one pump at a time
  }
  pump_active_idx = idx;
  pump_started_ms = millis();
  relay_write(RELAY_PINS[idx], true);
  return true;
}

void pump_stop(int idx) {
  relay_write(RELAY_PINS[idx], false);
  if (pump_active_idx == idx) {
    pump_active_idx = -1;
  }
}

int zoneToIdx(const String &z) {
  if (z == "Z1") return 0;
  if (z == "Z2") return 1;
  if (z == "Z3") return 2;
  return -1;
}

// Clamp integer to range
int clampInt(int value, int minVal, int maxVal) {
  if (value < minVal) return minVal;
  if (value > maxVal) return maxVal;
  return value;
}

// =====================================================
// ULTRASONIC
// =====================================================

// Returns distance in cm. If invalid, returns -1.
float read_distance_cm(int trigPin, int echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(3);

  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  unsigned long duration = pulseIn(echoPin, HIGH, 30000UL); // timeout ~30ms

  if (duration == 0) {
    return -1.0; // timeout / no echo
  }

  // HC-SR04 distance formula
  float distance = duration * 0.0343f / 2.0f;
  return distance;
}

// Average a few readings for stability
float smooth_distance_cm(int trigPin, int echoPin) {
  const int N = 5;
  float sum = 0.0;
  int count = 0;

  for (int i = 0; i < N; i++) {
    float d = read_distance_cm(trigPin, echoPin);
    if (d > 0) {
      sum += d;
      count++;
    }
    delay(20);
  }

  if (count == 0) return -1.0;
  return sum / count;
}

// Convert distance -> water level percentage 0..100
int distance_to_level_pct(int idx, float distance_cm) {
  if (distance_cm < 0) {
    return 0; // fallback if invalid reading
  }

  float emptyDist = EMPTY_DISTANCE_CM[idx];
  float fullDist  = FULL_DISTANCE_CM[idx];

  // If sensor sees farther than empty => 0%
  if (distance_cm >= emptyDist) return 0;

  // If water is near sensor => 100%
  if (distance_cm <= fullDist) return 100;

  // Normalize inversely:
  // distance empty -> 0%
  // distance full  -> 100%
  float pct = ((emptyDist - distance_cm) / (emptyDist - fullDist)) * 100.0f;

  int pctInt = (int)(pct + 0.5f);
  return clampInt(pctInt, 0, 100);
}

// =====================================================
// FLOOD LOGIC
// =====================================================

void update_flood_states(int levelPct[3]) {
  for (int i = 0; i < 3; i++) {
    if (!flooded[i]) {
      // SAFE -> FLOODED
      if (levelPct[i] >= THRESH_PCT[i]) {
        flooded[i] = true;
      }
    } else {
      // FLOODED -> SAFE with hysteresis
      if (levelPct[i] <= (THRESH_PCT[i] - HYST)) {
        flooded[i] = false;
      }
    }
  }
}

void auto_control() {
  // LEDs always reflect flood state
  for (int i = 0; i < 3; i++) {
    set_led(i, flooded[i]);
  }

  // If one pump is already active
  if (pump_active_idx != -1) {
    // timeout safety
    if (millis() - pump_started_ms > PUMP_MAX_MS) {
      pump_stop(pump_active_idx);
      return;
    }

    // stop if zone is safe again
    if (!flooded[pump_active_idx]) {
      pump_stop(pump_active_idx);
      return;
    }

    return; // keep current pump running
  }

  // No pump active: pick first flooded zone (priority Z1 > Z2 > Z3)
  for (int i = 0; i < 3; i++) {
    if (flooded[i]) {
      pump_start(i);
      break;
    }
  }
}

// =====================================================
// SERIAL COMMANDS
// =====================================================

String readLine() {
  static String line = "";

  while (Serial.available()) {
    char c = (char)Serial.read();

    if (c == '\n') {
      String out = line;
      line = "";
      out.trim();
      return out;
    } else if (c != '\r') {
      line += c;
    }
  }

  return "";
}

void handleCommand(const String &cmd) {
  if (cmd.length() == 0) return;

  // MODE AUTO|MANUAL
  if (cmd.startsWith("MODE ")) {
    String m = cmd.substring(5);
    m.trim();

    if (m == "AUTO") {
      mode = MODE_AUTO;
      Serial.println("OK MODE AUTO");
      return;
    }

    if (m == "MANUAL") {
      mode = MODE_MANUAL;
      pumps_all_off();
      Serial.println("OK MODE MANUAL");
      return;
    }

    Serial.println("ERR bad MODE");
    return;
  }

  // STOP ALL
  if (cmd == "STOP ALL") {
    pumps_all_off();
    Serial.println("OK STOP ALL");
    return;
  }

  // THRESH Zx N
  // Example: THRESH Z1 70
  if (cmd.startsWith("THRESH ")) {
    int sp1 = cmd.indexOf(' ', 7);
    if (sp1 < 0) {
      Serial.println("ERR bad THRESH");
      return;
    }

    String z = cmd.substring(7, sp1);
    z.trim();

    String n = cmd.substring(sp1 + 1);
    n.trim();

    int idx = zoneToIdx(z);
    int val = n.toInt();

    if (idx < 0 || val < 0 || val > 100) {
      Serial.println("ERR bad THRESH args");
      return;
    }

    THRESH_PCT[idx] = val;
    Serial.print("OK THRESH ");
    Serial.print(z);
    Serial.print(" ");
    Serial.println(val);
    return;
  }

  // PUMP Zx ON|OFF
  if (cmd.startsWith("PUMP ")) {
    int sp1 = cmd.indexOf(' ', 5);
    if (sp1 < 0) {
      Serial.println("ERR bad PUMP");
      return;
    }

    String z = cmd.substring(5, sp1);
    z.trim();

    String act = cmd.substring(sp1 + 1);
    act.trim();

    int idx = zoneToIdx(z);
    if (idx < 0) {
      Serial.println("ERR bad zone");
      return;
    }

    if (act == "ON") {
      bool ok = pump_start(idx);
      if (!ok) Serial.println("ERR pump locked");
      else Serial.println("OK PUMP ON");
      return;
    }

    if (act == "OFF") {
      pump_stop(idx);
      Serial.println("OK PUMP OFF");
      return;
    }

    Serial.println("ERR bad PUMP action");
    return;
  }

  Serial.println("ERR unknown cmd");
}

// =====================================================
// STATE SENDING
// raw = water level percentage
// flooded = 0/1
// =====================================================

void sendState(int levelPct[3]) {
  Serial.print("STATE ");

  for (int i = 0; i < 3; i++) {
    Serial.print("Z");
    Serial.print(i + 1);
    Serial.print("=");
    Serial.print(levelPct[i]);
    Serial.print(",");
    Serial.print(flooded[i] ? 1 : 0);
    Serial.print(" ");
  }

  Serial.print("P=");
  if (pump_active_idx == -1) {
    Serial.print("NONE");
  } else {
    Serial.print("Z");
    Serial.print(pump_active_idx + 1);
  }

  Serial.print(" MODE=");
  Serial.println(mode == MODE_AUTO ? "AUTO" : "MANUAL");
}

// =====================================================
// SETUP / LOOP
// =====================================================

void setup() {
  Serial.begin(115200);

  // Ultrasonic pins
  for (int i = 0; i < 3; i++) {
    pinMode(TRIG_PINS[i], OUTPUT);
    pinMode(ECHO_PINS[i], INPUT);
    digitalWrite(TRIG_PINS[i], LOW);
  }

  // LED pins
  for (int i = 0; i < 3; i++) {
    pinMode(LED_R_PINS[i], OUTPUT);
    pinMode(LED_G_PINS[i], OUTPUT);
    set_led(i, false); // safe at boot
  }

  // Relay pins
  for (int i = 0; i < 3; i++) {
    pinMode(RELAY_PINS[i], OUTPUT);
    relay_write(RELAY_PINS[i], false); // OFF
  }

  pumps_all_off();

  Serial.println("OK BOOT");
}

void loop() {
  int levelPct[3];

  // Read each zone
  for (int i = 0; i < 3; i++) {
    float distance = smooth_distance_cm(TRIG_PINS[i], ECHO_PINS[i]);
    levelPct[i] = distance_to_level_pct(i, distance);
  }

  // Update flood states
  update_flood_states(levelPct);

  // Read serial commands
  String cmd = readLine();
  if (cmd.length() > 0) {
    handleCommand(cmd);
  }

  // Control logic
  if (mode == MODE_AUTO) {
    auto_control();
  } else {
    // MANUAL: LEDs still reflect flood state
    for (int i = 0; i < 3; i++) {
      set_led(i, flooded[i]);
    }
    // Pumps only react to serial commands
  }

  // Send state every second
  if (millis() - lastStateMs > STATE_INTERVAL_MS) {
    lastStateMs = millis();
    sendState(levelPct);
  }
}