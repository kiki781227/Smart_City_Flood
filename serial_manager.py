import re
import time
import threading

try:
    import serial
except ImportError:
    serial = None

from telegram_notifier import TelegramNotifier


STATE_RE = re.compile(
    r"STATE\s+Z1=(\d+),(\d)\s+Z2=(\d+),(\d)\s+Z3=(\d+),(\d)\s+P=([A-Z0-9]+)\s+MODE=(AUTO|MANUAL)"
)


class SerialManager:
    ZONES = ("Z1", "Z2", "Z3")

    def __init__(self, port=None, baud=115200):
        self.port = port or "COM6"
        self.baud = baud
        self.ser = None
        self.lock = threading.Lock()
        self.running = False
        self.thread = None

        self.zone_threshold = 60
        self.auto_delay_sec = 8

        self.state = {
            "Z1": {"raw": 0, "flood": 0, "pct": 0},
            "Z2": {"raw": 0, "flood": 0, "pct": 0},
            "Z3": {"raw": 0, "flood": 0, "pct": 0},
            "P": "NONE",
            "MODE": "AUTO",
            "connected": False,
            "last": None,
        }

        self.logs = []
        self.log_limit = 120

        self.prev_mode = self.state["MODE"]
        self.prev_flood = {z: 0 for z in self.ZONES}

        self.auto_pending = {}

        self.notifier = TelegramNotifier(
            token="8557381776:AAFXl7OCoIRbb2EKecmVeqK3wgSfg9F6xug",
            chat_id="8746700326",
            enabled=True,
        )

        self.runtime = {
            "telegram_enabled": self.notifier.is_configured(),
            "telegram_last_ok": None,
            "telegram_error": None,
            "countdowns": {"Z1": None, "Z2": None, "Z3": None},
            "auto_delay_sec": self.auto_delay_sec,
            "emergency_stop": False,
        }

    def add_log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.logs.append(f"{ts} - {msg}")
        self.logs = self.logs[-self.log_limit:]

    def water_percentage(self, raw_value):
        return max(0, min(100, int(raw_value)))

    def connect(self):
        if serial is None:
            self.add_log("pyserial not installed")
            with self.lock:
                self.state["connected"] = False
            return

        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
            with self.lock:
                self.state["connected"] = True
            self.add_log(f"Serial connected: {self.port}")
        except Exception as e:
            self.ser = None
            with self.lock:
                self.state["connected"] = False
            self.add_log(f"Serial connect error: {e}")

    def start(self):
        if self.running:
            return
        self.running = True
        self.connect()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self._cancel_all_auto_actions("manager stopped")
        try:
            if self.ser and getattr(self.ser, "is_open", False):
                self.ser.close()
        except Exception:
            pass

    def _loop(self):
        while self.running:
            self.poll_once()
            self._refresh_countdowns()
            time.sleep(0.05)

    def poll_once(self):
        if not self.ser or not getattr(self.ser, "is_open", False):
            return

        try:
            line = self.ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                return

            if line.startswith("OK ") or line.startswith("ERR "):
                self.add_log(line)
                return

            m = STATE_RE.match(line)
            if not m:
                return

            z1_raw, z1_f, z2_raw, z2_f, z3_raw, z3_f, p, mode = m.groups()
            events = []

            with self.lock:
                old_mode = self.state["MODE"]
                old_flood = {z: int(self.state[z]["flood"]) for z in self.ZONES}

                self.state["Z1"] = {
                    "raw": int(z1_raw),
                    "flood": int(z1_f),
                    "pct": self.water_percentage(int(z1_raw)),
                }
                self.state["Z2"] = {
                    "raw": int(z2_raw),
                    "flood": int(z2_f),
                    "pct": self.water_percentage(int(z2_raw)),
                }
                self.state["Z3"] = {
                    "raw": int(z3_raw),
                    "flood": int(z3_f),
                    "pct": self.water_percentage(int(z3_raw)),
                }
                self.state["P"] = p
                self.state["MODE"] = mode
                self.state["connected"] = True
                self.state["last"] = int(time.time())

                if old_mode != mode:
                    events.append(("mode_changed", old_mode, mode))
                    self.prev_mode = mode

                for zone in self.ZONES:
                    before = old_flood[zone]
                    after = int(self.state[zone]["flood"])
                    if before != after:
                        if after == 1:
                            events.append(("zone_flooded", zone))
                        else:
                            events.append(("zone_safe", zone))
                        self.prev_flood[zone] = after

            if events:
                self._handle_events(events)

        except Exception as e:
            with self.lock:
                self.state["connected"] = False
            self.add_log(f"Poll error: {e}")

    def _handle_events(self, events):
        for event in events:
            kind = event[0]

            if kind == "mode_changed":
                _, old_mode, new_mode = event
                self.add_log(f"Mode changed: {old_mode} -> {new_mode}")
                self._notify(f"⚙️ Mode actif : {new_mode}")

                if new_mode == "MANUAL":
                    self._cancel_all_auto_actions("mode manuel activé")
                else:
                    with self.lock:
                        self.runtime["emergency_stop"] = False

            elif kind == "zone_flooded":
                _, zone = event
                mode = self.get_state()["MODE"]
                self.add_log(f"Flood detected on {zone} ({mode})")

                if mode == "MANUAL":
                    flooded = self._current_flooded_zones()
                    self._notify(
                        f"⚠️ Alerte manuelle : {', '.join(flooded)} dépassent le seuil d'inondation. Aucune action automatique n'est lancée."
                    )
                elif mode == "AUTO":
                    self._schedule_auto_pump(zone)

            elif kind == "zone_safe":
                _, zone = event
                self.add_log(f"{zone} returned to safe level")
                self._cancel_auto_action(zone, f"{zone} redevenue safe")

                with self.lock:
                    active_pump = self.state["P"]

                if active_pump == zone:
                    self.send(f"PUMP {zone} OFF", internal=True)
                    self.add_log(f"Pump stopped on {zone}: zone safe")

    def _current_flooded_zones(self):
        with self.lock:
            return [z for z in self.ZONES if int(self.state[z]["flood"]) == 1]

    def _notify(self, text: str):
        res = self.notifier.send(text)

        with self.lock:
            self.runtime["telegram_enabled"] = self.notifier.is_configured()
            self.runtime["telegram_last_ok"] = None if res.get("disabled") else bool(res.get("ok", False))
            self.runtime["telegram_error"] = None if res.get("ok") else res.get("error")

        if res.get("ok"):
            self.add_log(f"Telegram sent: {text}")
        elif res.get("disabled"):
            self.add_log("Telegram disabled or not configured")
        else:
            self.add_log(f"Telegram error: {res.get('error')}")

    def _schedule_auto_pump(self, zone: str):
        with self.lock:
            if zone in self.auto_pending:
                return

            if self.runtime["emergency_stop"]:
                self.add_log(f"Auto action blocked for {zone}: emergency stop active")
                return

            deadline = time.time() + self.auto_delay_sec
            timer = threading.Timer(self.auto_delay_sec, self._auto_activate_pump, args=(zone,))
            self.auto_pending[zone] = {"deadline": deadline, "timer": timer}
            self.runtime["countdowns"][zone] = self.auto_delay_sec

        self.add_log(f"Auto countdown started for {zone}: {self.auto_delay_sec}s")
        self._notify(f"🚨 {zone} inondée — la pompe va s'activer dans {self.auto_delay_sec} secondes")
        timer.start()

    def _auto_activate_pump(self, zone: str):
        with self.lock:
            pending = self.auto_pending.get(zone)
            if not pending:
                return

            mode = self.state["MODE"]
            flooded = int(self.state[zone]["flood"])
            active_pump = self.state["P"]
            emergency = self.runtime["emergency_stop"]

            if mode != "AUTO":
                reason = "mode non AUTO"
            elif emergency:
                reason = "emergency stop actif"
            elif flooded != 1:
                reason = "zone non inondée à la fin du délai"
            elif active_pump not in ("NONE", zone):
                reason = f"pompe déjà active sur {active_pump}"
            else:
                reason = None

        if reason:
            self._cancel_auto_action(zone, reason)
            return

        self.send(f"PUMP {zone} ON", internal=True)
        self.add_log(f"Pump auto-activated for {zone}")
        self._notify(f"✅ Pompe {zone} activée automatiquement après délai")

        with self.lock:
            self.auto_pending.pop(zone, None)
            self.runtime["countdowns"][zone] = None

    def _cancel_auto_action(self, zone: str, reason: str = ""):
        with self.lock:
            pending = self.auto_pending.pop(zone, None)
            self.runtime["countdowns"][zone] = None

        if pending:
            try:
                pending["timer"].cancel()
            except Exception:
                pass
            self.add_log(f"Auto countdown cancelled for {zone}: {reason}")

    def _cancel_all_auto_actions(self, reason: str = ""):
        for zone in list(self.ZONES):
            self._cancel_auto_action(zone, reason)

    def _refresh_countdowns(self):
        now = time.time()
        with self.lock:
            for zone in self.ZONES:
                pending = self.auto_pending.get(zone)
                if not pending:
                    self.runtime["countdowns"][zone] = None
                    continue

                remaining = int(max(0, round(pending["deadline"] - now)))
                self.runtime["countdowns"][zone] = remaining

    def send(self, cmd: str, internal: bool = False):
        clean_cmd = cmd.strip()
        if not clean_cmd:
            return {"ok": False, "error": "Empty command"}

        if clean_cmd == "STOP ALL":
            with self.lock:
                self.runtime["emergency_stop"] = True
            self._cancel_all_auto_actions("stop all")

        elif clean_cmd == "MODE AUTO":
            with self.lock:
                self.runtime["emergency_stop"] = False

        elif clean_cmd == "MODE MANUAL":
            self._cancel_all_auto_actions("mode manuel forcé")

        with self.lock:
            if self.ser and getattr(self.ser, "is_open", False):
                try:
                    self.ser.write((clean_cmd + "\n").encode("utf-8"))
                    self.ser.flush()  # Force immediate transmission to Arduino
                    if not internal:
                        self.add_log(f"> {clean_cmd}")
                    return {"ok": True, "simulated": False}
                except Exception as e:
                    self.add_log(f"Send error: {e}")
                    return {"ok": False, "error": str(e), "simulated": False}

        self.add_log(f"Serial unavailable, command NOT sent: {clean_cmd}")
        return {"ok": False, "error": "Serial unavailable", "simulated": False}

    def _simulate_command(self, clean_cmd: str):
        events = []

        with self.lock:
            old_mode = self.state["MODE"]
            old_flood = {z: int(self.state[z]["flood"]) for z in self.ZONES}

            if clean_cmd == "MODE AUTO":
                self.state["MODE"] = "AUTO"
            elif clean_cmd == "MODE MANUAL":
                self.state["MODE"] = "MANUAL"
                self.state["P"] = "NONE"
            elif clean_cmd == "STOP ALL":
                self.state["P"] = "NONE"
            elif clean_cmd == "PUMP Z1 ON":
                self.state["P"] = "Z1"
            elif clean_cmd == "PUMP Z1 OFF" and self.state["P"] == "Z1":
                self.state["P"] = "NONE"
            elif clean_cmd == "PUMP Z2 ON":
                self.state["P"] = "Z2"
            elif clean_cmd == "PUMP Z2 OFF" and self.state["P"] == "Z2":
                self.state["P"] = "NONE"
            elif clean_cmd == "PUMP Z3 ON":
                self.state["P"] = "Z3"
            elif clean_cmd == "PUMP Z3 OFF" and self.state["P"] == "Z3":
                self.state["P"] = "NONE"

            self.state["last"] = int(time.time())

            if old_mode != self.state["MODE"]:
                events.append(("mode_changed", old_mode, self.state["MODE"]))

            for zone in self.ZONES:
                if old_flood[zone] != int(self.state[zone]["flood"]):
                    if int(self.state[zone]["flood"]) == 1:
                        events.append(("zone_flooded", zone))
                    else:
                        events.append(("zone_safe", zone))

        if events:
            self._handle_events(events)

    def get_state(self):
        with self.lock:
            return {
                "Z1": dict(self.state["Z1"]),
                "Z2": dict(self.state["Z2"]),
                "Z3": dict(self.state["Z3"]),
                "P": self.state["P"],
                "MODE": self.state["MODE"],
                "connected": self.state["connected"],
                "last": self.state["last"],
            }

    def get_payload(self):
        state = self.get_state()

        with self.lock:
            runtime = {
                "telegram_enabled": self.runtime["telegram_enabled"],
                "telegram_last_ok": self.runtime["telegram_last_ok"],
                "telegram_error": self.runtime["telegram_error"],
                "countdowns": dict(self.runtime["countdowns"]),
                "auto_delay_sec": self.runtime["auto_delay_sec"],
                "emergency_stop": self.runtime["emergency_stop"],
            }

        return {
            "state": state,
            "runtime": runtime,
            "logs": self.logs[-25:],
        }

    def demo_fill(self):
        events = []

        with self.lock:
            old_flood = {z: int(self.state[z]["flood"]) for z in self.ZONES}

            self.state["Z1"]["raw"] = (self.state["Z1"]["raw"] + 10) % 101
            self.state["Z1"]["pct"] = self.state["Z1"]["raw"]
            self.state["Z1"]["flood"] = 1 if self.state["Z1"]["raw"] >= self.zone_threshold else 0

            self.state["Z2"]["raw"] = (self.state["Z2"]["raw"] + 15) % 101
            self.state["Z2"]["pct"] = self.state["Z2"]["raw"]
            self.state["Z2"]["flood"] = 1 if self.state["Z2"]["raw"] >= self.zone_threshold else 0

            self.state["Z3"]["raw"] = (self.state["Z3"]["raw"] + 20) % 101
            self.state["Z3"]["pct"] = self.state["Z3"]["raw"]
            self.state["Z3"]["flood"] = 1 if self.state["Z3"]["raw"] >= self.zone_threshold else 0

            self.state["last"] = int(time.time())

            for zone in self.ZONES:
                if old_flood[zone] != int(self.state[zone]["flood"]):
                    if int(self.state[zone]["flood"]) == 1:
                        events.append(("zone_flooded", zone))
                    else:
                        events.append(("zone_safe", zone))

        if events:
            self._handle_events(events)