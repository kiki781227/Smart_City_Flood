import time
import re
import serial
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import os

st.set_page_config(page_title="Flood Smart City", layout="wide")

# ---- CONFIG ----
SERIAL_PORT = os.getenv("SERIAL_PORT", "COM3")  # Lisible via variable d'environnement
BAUD = 115200

# ---- Session init ----
if "ser" not in st.session_state:
    st.session_state.ser = None
if "state" not in st.session_state:
    st.session_state.state = {
        "Z1": {"raw": 0, "flood": 0},
        "Z2": {"raw": 0, "flood": 0},
        "Z3": {"raw": 0, "flood": 0},
        "P": "NONE",
        "MODE": "AUTO",
        "last": None,
        "connected": False,
    }
if "log" not in st.session_state:
    st.session_state.log = []

def log(msg):
    st.session_state.log.append(f"{time.strftime('%H:%M:%S')} - {msg}")
    st.session_state.log = st.session_state.log[-60:]

def connect_serial():
    if st.session_state.ser is None:
        try:
            st.session_state.ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)
            st.session_state.state["connected"] = True
            log(f"Serial connected: {SERIAL_PORT}")
        except Exception as e:
            st.session_state.state["connected"] = False
            log(f"Serial connect error: {e}")

def send(cmd: str):
    ser = st.session_state.ser
    if ser and ser.is_open:
        ser.write((cmd.strip() + "\n").encode("utf-8"))
        log(f"> {cmd.strip()}")

STATE_RE = re.compile(r"STATE\s+Z1=(\d+),(\d)\s+Z2=(\d+),(\d)\s+Z3=(\d+),(\d)\s+P=([A-Z0-9]+)\s+MODE=(AUTO|MANUAL)")

def poll():
    ser = st.session_state.ser
    if not ser or not ser.is_open:
        return
    try:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            return
        m = STATE_RE.match(line)
        if not m:
            return
        z1_raw, z1_f, z2_raw, z2_f, z3_raw, z3_f, p, mode = m.groups()
        st.session_state.state["Z1"] = {"raw": int(z1_raw), "flood": int(z1_f)}
        st.session_state.state["Z2"] = {"raw": int(z2_raw), "flood": int(z2_f)}
        st.session_state.state["Z3"] = {"raw": int(z3_raw), "flood": int(z3_f)}
        st.session_state.state["P"] = p
        st.session_state.state["MODE"] = mode
        st.session_state.state["last"] = time.time()
        st.session_state.state["connected"] = True
    except Exception as e:
        st.session_state.state["connected"] = False
        log(f"Poll error: {e}")

def zone_color(flood: int):
    return "#ff3b3b" if flood == 1 else "#00c853"

def svg_city(stt):
    # 2x2 tiles: Z1 top-left, Z2 top-right, Z3 bottom-left, HUB bottom-right (fixed)
    z1 = zone_color(stt["Z1"]["flood"])
    z2 = zone_color(stt["Z2"]["flood"])
    z3 = zone_color(stt["Z3"]["flood"])
    hub = "#2b2b2b"
    border = "#111"

    # Pump indicator
    p = stt["P"]
    def pump_badge(zone):
        return "🟦 PUMP" if p == zone else ""

    return f"""
<svg width="520" height="520" viewBox="0 0 520 520" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="520" height="520" fill="#0b0b0b" rx="18"/>

  <!-- Z1 -->
  <rect x="20" y="20" width="230" height="230" fill="{z1}" stroke="{border}" stroke-width="6" rx="18"/>
  <text x="40" y="60" fill="#0b0b0b" font-size="26" font-family="Arial" font-weight="700">Z1</text>
  <text x="40" y="95" fill="#0b0b0b" font-size="16" font-family="Arial">raw: {stt["Z1"]["raw"]}</text>
  <text x="40" y="125" fill="#0b0b0b" font-size="16" font-family="Arial">{pump_badge("Z1")}</text>

  <!-- Z2 -->
  <rect x="270" y="20" width="230" height="230" fill="{z2}" stroke="{border}" stroke-width="6" rx="18"/>
  <text x="290" y="60" fill="#0b0b0b" font-size="26" font-family="Arial" font-weight="700">Z2</text>
  <text x="290" y="95" fill="#0b0b0b" font-size="16" font-family="Arial">raw: {stt["Z2"]["raw"]}</text>
  <text x="290" y="125" fill="#0b0b0b" font-size="16" font-family="Arial">{pump_badge("Z2")}</text>

  <!-- Z3 -->
  <rect x="20" y="270" width="230" height="230" fill="{z3}" stroke="{border}" stroke-width="6" rx="18"/>
  <text x="40" y="310" fill="#0b0b0b" font-size="26" font-family="Arial" font-weight="700">Z3</text>
  <text x="40" y="345" fill="#0b0b0b" font-size="16" font-family="Arial">raw: {stt["Z3"]["raw"]}</text>
  <text x="40" y="375" fill="#0b0b0b" font-size="16" font-family="Arial">{pump_badge("Z3")}</text>

  <!-- HUB fixed -->
  <rect x="270" y="270" width="230" height="230" fill="{hub}" stroke="{border}" stroke-width="6" rx="18"/>
  <text x="290" y="310" fill="#ffffff" font-size="22" font-family="Arial" font-weight="700">CONTROL HUB</text>
  <text x="290" y="345" fill="#bdbdbd" font-size="14" font-family="Arial">Serial: {"OK" if stt["connected"] else "OFF"}</text>
  <text x="290" y="370" fill="#bdbdbd" font-size="14" font-family="Arial">Mode: {stt["MODE"]}</text>
  <text x="290" y="395" fill="#bdbdbd" font-size="14" font-family="Arial">Pump lock: {stt["P"]}</text>
</svg>
"""

# --- Auto refresh 1s ---
st_autorefresh(interval=1000, key="tick")

# --- Connect & poll ---
connect_serial()
poll()
stt = st.session_state.state

# --- Header ---
st.title("Flood Smart City — Control Center")
if any(stt[z]["flood"] == 1 for z in ["Z1", "Z2", "Z3"]):
    flooded = [z for z in ["Z1", "Z2", "Z3"] if stt[z]["flood"] == 1]
    safe = [z for z in ["Z1", "Z2", "Z3"] if stt[z]["flood"] == 0]
    st.error(f"⚠️ ALERTE INONDATION: {', '.join(flooded)}  |  Zones SAFE: {', '.join(safe) if safe else 'Aucune'}")
else:
    st.success("✅ VILLE SAFE — aucune inondation détectée")

# --- Layout ---
left, right = st.columns([1.2, 1])

with left:
    st.markdown(svg_city(stt), unsafe_allow_html=True)

with right:
    st.subheader("Contrôle")
    # Pump lock rule: one pump at a time (also manual)
    locked = (stt["P"] != "NONE")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("MODE AUTO", use_container_width=True):
            send("MODE AUTO")
        if st.button("MODE MANUAL", use_container_width=True):
            send("MODE MANUAL")
    with c2:
        if st.button("🛑 STOP ALL", use_container_width=True):
            send("STOP ALL")

    st.divider()
    st.write("Pompes (1 seule à la fois):")
    for z in ["Z1", "Z2", "Z3"]:
        cols = st.columns([1, 1])
        with cols[0]:
            st.button(f"🚰 {z} ON", use_container_width=True, disabled=(locked and stt["P"] != z),
                      on_click=lambda zz=z: send(f"PUMP {zz} ON"))
        with cols[1]:
            st.button(f"{z} OFF", use_container_width=True, disabled=(stt["P"] != z),
                      on_click=lambda zz=z: send(f"PUMP {zz} OFF"))

    st.divider()
    st.subheader("Journal")
    st.code("\n".join(st.session_state.log[::-1]) if st.session_state.log else "—", language="text")