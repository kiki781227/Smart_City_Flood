// flood_city_mega_ultrasonic_STABLE.ino
// Arduino Mega - 3 zones with ultrasonic sensors, RG LEDs, 3 pump relays
// Version stabilisée avec FILTRE MÉDIAN (Anti-Bruit)

#include <Arduino.h>

static const bool RELAY_ACTIVE_LOW = false;

// =====================================================
// PINS - ARDUINO MEGA
// =====================================================
const int TRIG_PINS[3] = {10, 46, 47};
const int ECHO_PINS[3] = {9, 44, 45};

const int LED_R_PINS[3] = {7, 52, 53};
const int LED_G_PINS[3] = {6, 50, 51};

const int RELAY_PINS[3] = {12, 41, 40}; 

// =====================================================
// WATER LEVEL CONFIG
// =====================================================
float MAX_WATER_DEPTH_CM[3] = {1.2, 1.2, 1.2};
float EMPTY_DISTANCE_CM[3] = {5.5, 6.1, 6.3};
float FULL_DISTANCE_CM[3]  = {4.3, 4.9, 5.1};

int THRESH_PCT[3] = {30, 30, 30};
int HYST = 15;
bool flooded[3] = {false, false, false};

unsigned long flood_change_timestamp[3] = {0, 0, 0};
const unsigned long DEBOUNCE_MS = 2000; 

// =====================================================
// MODE & PUMP LOCK
// =====================================================
enum Mode { MODE_AUTO, MODE_MANUAL };
Mode mode = MODE_AUTO;

int pump_active_idx = -1;
unsigned long pump_started_ms = 0;
const unsigned long PUMP_MAX_MS = 15000; 

unsigned long lastStateMs = 0;
const unsigned long STATE_INTERVAL_MS = 1000;

// =====================================================
// HELPERS (LED, RELAY, PUMPS)
// =====================================================
void relay_write(int pin, bool on) {
  digitalWrite(pin, (RELAY_ACTIVE_LOW ? (on ? LOW : HIGH) : (on ? HIGH : LOW)));
}

void set_led(int idx, bool isFlooded) {
  digitalWrite(LED_R_PINS[idx], isFlooded ? LOW : HIGH);
  digitalWrite(LED_G_PINS[idx], isFlooded ? HIGH : LOW);
}

void pumps_all_off() {
  for (int i = 0; i < 3; i++) relay_write(RELAY_PINS[i], false);
  pump_active_idx = -1;
}

bool pump_start(int idx) {
  if (pump_active_idx != -1 && pump_active_idx != idx) return false;
  pump_active_idx = idx;
  pump_started_ms = millis();
  relay_write(RELAY_PINS[idx], true);
  return true;
}

void pump_stop(int idx) {
  relay_write(RELAY_PINS[idx], false);
  if (pump_active_idx == idx) pump_active_idx = -1;
}

int zoneToIdx(const String &z) {
  if (z == "Z1") return 0;
  if (z == "Z2") return 1;
  if (z == "Z3") return 2;
  return -1;
}

int clampInt(int value, int minVal, int maxVal) {
  return (value < minVal) ? minVal : (value > maxVal ? maxVal : value);
}

// =====================================================
// ULTRASONIC - STABILIZED WITH MEDIAN FILTER
// =====================================================

float read_raw_distance(int trigPin, int echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(3);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  unsigned long duration = pulseIn(echoPin, HIGH, 30000UL);
  if (duration == 0) return -1.0;
  return duration * 0.0343f / 2.0f;
}

// FILTRE MÉDIAN : Prend 7 mesures, les trie et garde celle du milieu.
// Cela élimine mathématiquement les valeurs aberrantes (bruit).
float smooth_distance_cm(int trigPin, int echoPin) {
  const int N = 7; 
  float samples[N];
  int validCount = 0;

  for (int i = 0; i < N; i++) {
    float d = read_raw_distance(trigPin, echoPin);
    if (d > 0 && d < 400) { // Ignorer les erreurs manifestes (> 4m)
      samples[validCount] = d;
      validCount++;
    }
    delay(15); // Laisser l'écho se dissiper
  }

  if (validCount == 0) return -1.0;

  // Tri à bulles (Bubble Sort)
  for (int i = 0; i < validCount - 1; i++) {
    for (int j = 0; j < validCount - i - 1; j++) {
      if (samples[j] > samples[j + 1]) {
        float temp = samples[j];
        samples[j] = samples[j + 1];
        samples[j + 1] = temp;
      }
    }
  }

  return samples[validCount / 2]; // Retourne la médiane
}

int distance_to_level_pct(int idx, float distance_cm) {
  if (distance_cm < 0) return 0;
  float emptyDist = EMPTY_DISTANCE_CM[idx];
  float fullDist  = FULL_DISTANCE_CM[idx];
  if (distance_cm >= emptyDist) return 0;
  if (distance_cm <= fullDist) return 100;
  float pct = ((emptyDist - distance_cm) / (emptyDist - fullDist)) * 100.0f;
  return clampInt((int)(pct + 0.5f), 0, 100);
}

// =====================================================
// LOGIC & SERIAL
// =====================================================

void update_flood_states(int levelPct[3]) {
  unsigned long now = millis();
  for (int i = 0; i < 3; i++) {
    if (!flooded[i]) {
      if (levelPct[i] >= THRESH_PCT[i]) {
        if (flood_change_timestamp[i] == 0) flood_change_timestamp[i] = now;
        else if (now - flood_change_timestamp[i] >= DEBOUNCE_MS) {
          flooded[i] = true;
          flood_change_timestamp[i] = 0;
        }
      } else flood_change_timestamp[i] = 0;
    } else {
      if (levelPct[i] <= (THRESH_PCT[i] - HYST)) {
        if (flood_change_timestamp[i] == 0) flood_change_timestamp[i] = now;
        else if (now - flood_change_timestamp[i] >= DEBOUNCE_MS) {
          flooded[i] = false;
          flood_change_timestamp[i] = 0;
        }
      } else flood_change_timestamp[i] = 0;
    }
  }
}

void handleCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;

  if (cmd.startsWith("MODE ")) {
    mode = (cmd.substring(5) == "MANUAL") ? MODE_MANUAL : MODE_AUTO;
    if (mode == MODE_MANUAL) pumps_all_off();
    Serial.println("OK MODE");
  } else if (cmd == "STOP ALL") {
    pumps_all_off();
    Serial.println("OK STOP");
  } else if (cmd.startsWith("PUMP ")) {
    int sp1 = cmd.indexOf(' ', 5);
    int idx = zoneToIdx(cmd.substring(5, sp1));
    String act = cmd.substring(sp1 + 1);
    if (idx >= 0) {
      if (act == "ON") {
        if (pump_start(idx)) Serial.println("OK PUMP ON");
        else Serial.println("ERR PUMP LOCKED");
      } else {
        pump_stop(idx);
        Serial.println("OK PUMP OFF");
      }
    }
  }
}

void sendState(int levelPct[3]) {
  Serial.print("STATE ");
  for (int i = 0; i < 3; i++) {
    Serial.print("Z"); Serial.print(i + 1); Serial.print("=");
    Serial.print(levelPct[i]); Serial.print(",");
    Serial.print(flooded[i] ? 1 : 0); Serial.print(" ");
  }
  Serial.print("P="); Serial.print(pump_active_idx == -1 ? "NONE" : "Z" + String(pump_active_idx + 1));
  Serial.print(" MODE="); Serial.println(mode == MODE_AUTO ? "AUTO" : "MANUAL");
}

// =====================================================
// MAIN
// =====================================================
void setup() {
  Serial.begin(115200);
  for (int i = 0; i < 3; i++) {

    pinMode(TRIG_PINS[i], OUTPUT);
    pinMode(ECHO_PINS[i], INPUT);

    pinMode(LED_R_PINS[i], OUTPUT);
    pinMode(LED_G_PINS[i], OUTPUT);

    pinMode(RELAY_PINS[i], OUTPUT);

    relay_write(RELAY_PINS[i], false);
    set_led(i, false);
  }
  Serial.println("OK BOOT STABLE");
}

void loop() {
  int levelPct[3];
  for (int i = 0; i < 3; i++) {
    float d = smooth_distance_cm(TRIG_PINS[i], ECHO_PINS[i]);
    levelPct[i] = distance_to_level_pct(i, d);
  }

  update_flood_states(levelPct);

  if (Serial.available()) {
    handleCommand(Serial.readStringUntil('\n'));
  }

  if (mode == MODE_AUTO) {
    for (int i = 0; i < 3; i++) set_led(i, flooded[i]);
    if (pump_active_idx != -1) {
      if (millis() - pump_started_ms > PUMP_MAX_MS || !flooded[pump_active_idx]) {
        pump_stop(pump_active_idx);
      }
    }
  } else {
    for (int i = 0; i < 3; i++) set_led(i, flooded[i]);
  }

  if (millis() - lastStateMs > STATE_INTERVAL_MS) {
    lastStateMs = millis();
    sendState(levelPct);
  }
}