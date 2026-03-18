import os
import re
import time
import threading

try:
    import serial
except ImportError:
    serial = None


STATE_RE = re.compile(
    r"STATE\s+Z1=(\d+),(\d)\s+Z2=(\d+),(\d)\s+Z3=(\d+),(\d)\s+P=([A-Z0-9]+)\s+MODE=(AUTO|MANUAL)"
)


class SerialManager:
    def __init__(self, port=None, baud=115200):
        self.port = port or os.getenv("SERIAL_PORT", "COM9")
        self.baud = baud
        self.ser = None
        self.lock = threading.Lock()
        self.running = False
        self.thread = None

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
        self.log_limit = 80

    def add_log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.logs.append(f"{ts} - {msg}")
        self.logs = self.logs[-self.log_limit:]

    def water_percentage(self, raw_value):
        return max(0, min(100, int(raw_value)))

    def connect(self):
        if serial is None:
            self.add_log("pyserial not installed")
            self.state["connected"] = False
            return

        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
            self.state["connected"] = True
            self.add_log(f"Serial connected: {self.port}")
        except Exception as e:
            self.ser = None
            self.state["connected"] = False
            self.add_log(f"Serial connect error: {e}")

    def start(self):
        if self.running:
            return
        self.running = True
        self.connect()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while self.running:
            self.poll_once()
            time.sleep(0.05)

    def poll_once(self):
        if not self.ser or not getattr(self.ser, "is_open", False):
            return

        try:
            line = self.ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                return

            m = STATE_RE.match(line)
            if not m:
                return

            z1_raw, z1_f, z2_raw, z2_f, z3_raw, z3_f, p, mode = m.groups()

            with self.lock:
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

        except Exception as e:
            with self.lock:
                self.state["connected"] = False
            self.add_log(f"Poll error: {e}")

    def send(self, cmd: str):
        clean_cmd = cmd.strip()

        if self.ser and getattr(self.ser, "is_open", False):
            try:
                self.ser.write((clean_cmd + "\n").encode("utf-8"))
                self.add_log(f"> {clean_cmd}")
                return {"ok": True, "simulated": False}
            except Exception as e:
                self.add_log(f"Send error: {e}")

        self.add_log(f"[SIMULATION] > {clean_cmd}")
        self._simulate_command(clean_cmd)
        return {"ok": True, "simulated": True}

    def _simulate_command(self, clean_cmd: str):
        with self.lock:
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
        return {
            "state": state,
            "logs": self.logs[-25:],
        }
    
    def demo_fill(self):
        with self.lock:
            self.state["Z1"]["raw"] = (self.state["Z1"]["raw"] + 10) % 101
            self.state["Z1"]["pct"] = self.state["Z1"]["raw"]
            self.state["Z1"]["flood"] = 1 if self.state["Z1"]["raw"] >= 60 else 0

            self.state["Z2"]["raw"] = (self.state["Z2"]["raw"] + 15) % 101
            self.state["Z2"]["pct"] = self.state["Z2"]["raw"]
            self.state["Z2"]["flood"] = 1 if self.state["Z2"]["raw"] >= 60 else 0

            self.state["Z3"]["raw"] = (self.state["Z3"]["raw"] + 20) % 101
            self.state["Z3"]["pct"] = self.state["Z3"]["raw"]
            self.state["Z3"]["flood"] = 1 if self.state["Z3"]["raw"] >= 60 else 0

            self.state["last"] = int(time.time())