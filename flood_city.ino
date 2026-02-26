// flood_city.ino
// Arduino UNO - 3 zones: raindrop sensors (analog), RG LEDs, 3 pump relays (one pump at a time lock)

#include <Arduino.h>

static const bool RELAY_ACTIVE_LOW = true;  // mets false si ton relais s'active en HIGH

// --- Pins ---
const int SENS_PINS[3] = {A0, A1, A2};

// LED RG (R,G) par zone
const int LED_R_PINS[3] = {2, 4, 6};
const int LED_G_PINS[3] = {3, 5, 7};

// Relais pompes
const int RELAY_PINS[3] = {8, 9, 10}; // Z1,Z2,Z3

// --- Paramètres détection ---
int THRESH[3] = {500, 500, 500};      // seuil initial (à calibrer)
int HYST = 40;                        // hystérésis
bool flooded[3] = {false, false, false};

// --- Mode ---
enum Mode { MODE_AUTO, MODE_MANUAL };
Mode mode = MODE_AUTO;

// --- Lock pompe ---
int pump_active_idx = -1;             // -1 = aucune pompe, sinon 0..2
unsigned long pump_started_ms = 0;
const unsigned long PUMP_MAX_MS = 15000; // sécurité: coupe après 15s

// --- Sampling / smoothing ---
int smooth_read(int pin) {
  long sum = 0;
  const int N = 10;
  for (int i=0;i<N;i++){
    sum += analogRead(pin);
    delay(2);
  }
  return (int)(sum / N);
}

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
  for (int i=0;i<3;i++) relay_write(RELAY_PINS[i], false);
  pump_active_idx = -1;
}

bool pump_start(int idx) {
  if (pump_active_idx != -1 && pump_active_idx != idx) {
    return false; // lock: une seule pompe à la fois
  }
  pump_active_idx = idx;
  pump_started_ms = millis();
  relay_write(RELAY_PINS[idx], true);
  return true;
}

void pump_stop(int idx) {
  relay_write(RELAY_PINS[idx], false);
  if (pump_active_idx == idx) pump_active_idx = -1;
}

void update_flood_states(int raw[3]) {
  // hysteresis around THRESH
  for (int i=0;i<3;i++) {
    if (!flooded[i]) {
      // SAFE -> FLOODED if raw >= THRESH
      if (raw[i] >= THRESH[i]) flooded[i] = true;
    } else {
      // FLOODED -> SAFE if raw <= THRESH - HYST
      if (raw[i] <= (THRESH[i] - HYST)) flooded[i] = false;
    }
  }
}

void auto_control(int raw[3]) {
  // LEDs always reflect flood state
  for (int i=0;i<3;i++) set_led(i, flooded[i]);

  // Pump logic: if any flooded -> start pump for first flooded found (priority Z1>Z2>Z3)
  // Stop pump when its zone becomes safe OR timeout
  if (pump_active_idx != -1) {
    // safety timeout
    if (millis() - pump_started_ms > PUMP_MAX_MS) {
      pump_stop(pump_active_idx);
      return;
    }
    // stop if zone is now safe
    if (!flooded[pump_active_idx]) {
      pump_stop(pump_active_idx);
      return;
    }
    return; // keep running
  }

  // no pump active -> find a flooded zone
  for (int i=0;i<3;i++) {
    if (flooded[i]) {
      pump_start(i);
      break;
    }
  }
}

String readLine() {
  static String line = "";
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      String out = line;
      line = "";
      out.trim();
      return out;
    } else {
      line += c;
    }
  }
  return "";
}

int zoneToIdx(const String &z) {
  if (z == "Z1") return 0;
  if (z == "Z2") return 1;
  if (z == "Z3") return 2;
  return -1;
}

void handleCommand(const String &cmd) {
  if (cmd.length() == 0) return;

  // MODE AUTO|MANUAL
  if (cmd.startsWith("MODE ")) {
    String m = cmd.substring(5);
    m.trim();
    if (m == "AUTO") { mode = MODE_AUTO; Serial.println("OK MODE AUTO"); return; }
    if (m == "MANUAL") { mode = MODE_MANUAL; pumps_all_off(); Serial.println("OK MODE MANUAL"); return; }
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
  if (cmd.startsWith("THRESH ")) {
    // "THRESH Z1 520"
    int sp1 = cmd.indexOf(' ', 7);
    if (sp1 < 0) { Serial.println("ERR bad THRESH"); return; }
    String z = cmd.substring(7, sp1); z.trim();
    String n = cmd.substring(sp1+1); n.trim();
    int idx = zoneToIdx(z);
    int val = n.toInt();
    if (idx < 0 || val < 0 || val > 1023) { Serial.println("ERR bad THRESH args"); return; }
    THRESH[idx] = val;
    Serial.print("OK THRESH "); Serial.print(z); Serial.print(" "); Serial.println(val);
    return;
  }

  // PUMP Zx ON|OFF (manual or forced)
  if (cmd.startsWith("PUMP ")) {
    // "PUMP Z2 ON"
    int sp1 = cmd.indexOf(' ', 5);
    if (sp1 < 0) { Serial.println("ERR bad PUMP"); return; }
    String z = cmd.substring(5, sp1); z.trim();
    String act = cmd.substring(sp1+1); act.trim();

    int idx = zoneToIdx(z);
    if (idx < 0) { Serial.println("ERR bad zone"); return; }

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

void sendState(int raw[3]) {
  Serial.print("STATE ");
  for (int i=0;i<3;i++) {
    Serial.print("Z"); Serial.print(i+1);
    Serial.print("=");
    Serial.print(raw[i]); Serial.print(",");
    Serial.print(flooded[i] ? 1 : 0);
    Serial.print(" ");
  }
  Serial.print("P=");
  if (pump_active_idx == -1) Serial.print("NONE");
  else { Serial.print("Z"); Serial.print(pump_active_idx+1); }
  Serial.print(" MODE=");
  Serial.println(mode == MODE_AUTO ? "AUTO" : "MANUAL");
}

unsigned long lastStateMs = 0;

void setup() {
  Serial.begin(115200);

  // LED pins
  for (int i=0;i<3;i++){
    pinMode(LED_R_PINS[i], OUTPUT);
    pinMode(LED_G_PINS[i], OUTPUT);
    set_led(i, false); // start SAFE (green)
  }

  // Relay pins
  for (int i=0;i<3;i++){
    pinMode(RELAY_PINS[i], OUTPUT);
    relay_write(RELAY_PINS[i], false); // OFF
  }
}

void loop() {
  // Read sensors
  int raw[3];
  for (int i=0;i<3;i++) raw[i] = smooth_read(SENS_PINS[i]);

  update_flood_states(raw);

  // Serial commands
  String cmd = readLine();
  if (cmd.length() > 0) handleCommand(cmd);

  // Auto logic
  if (mode == MODE_AUTO) auto_control(raw);
  else {
    // MANUAL: LEDs still show flooded state
    for (int i=0;i<3;i++) set_led(i, flooded[i]);
    // pumps only by commands
  }

  // Send state every 1s
  if (millis() - lastStateMs > 1000) {
    lastStateMs = millis();
    sendState(raw);
  }
}