let showLog = false;

async function sendCommand(cmd) {
  const res = await fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cmd })
  });

  return res.json();
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function updateZone(zoneId, data, activePump) {
  const zone = document.getElementById(`zone-${zoneId}`);
  const water = document.getElementById(`water-${zoneId}`);
  const pct = document.getElementById(`pct-${zoneId}`);
  const raw = document.getElementById(`raw-${zoneId}`);
  const badge = document.getElementById(`badge-${zoneId}`);
  const pump = document.getElementById(`pump-${zoneId}`);

  const flooded = Number(data.flood) === 1;

  zone.classList.toggle("flooded", flooded);
  water.style.height = `${data.pct}%`;
  pct.textContent = `${data.pct}%`;
  raw.textContent = `SENSOR: ${data.raw} units`;

  badge.className = `badge ${flooded ? "flooded" : "safe"}`;
  badge.textContent = flooded ? "⚠ FLOODED" : "✓ SAFE";

  pump.classList.toggle("active", activePump === zoneId);
}

function updateButtons(state) {
  const mode = state.MODE;
  const pump = state.P;

  const btnAuto = document.getElementById("btnAuto");
  const btnManual = document.getElementById("btnManual");

  btnAuto.classList.toggle("active", mode === "AUTO");
  btnManual.classList.toggle("active", mode === "MANUAL");

  const manualEnabled = mode === "MANUAL";
  const info = document.getElementById("manualInfo");

  info.className = `manual-info ${manualEnabled ? "ok" : "warning"}`;
  info.textContent = manualEnabled
    ? "Manual control enabled"
    : "Manual controls disabled in AUTO mode";

  const mappings = [
    ["btnZ1On", pump !== "NONE" && pump !== "Z1"],
    ["btnZ1Off", pump !== "Z1"],
    ["btnZ2On", pump !== "NONE" && pump !== "Z2"],
    ["btnZ2Off", pump !== "Z2"],
    ["btnZ3On", pump !== "NONE" && pump !== "Z3"],
    ["btnZ3Off", pump !== "Z3"]
  ];

  mappings.forEach(([id, cond]) => {
    const btn = document.getElementById(id);
    btn.disabled = !manualEnabled || cond;
  });
}

function updateAlert(state) {
  const flooded = ["Z1", "Z2", "Z3"].filter(z => Number(state[z].flood) === 1);
  const safe = ["Z1", "Z2", "Z3"].filter(z => Number(state[z].flood) === 0);
  const banner = document.getElementById("alertBanner");

  if (flooded.length > 0) {
    banner.className = "banner alert";
    banner.textContent = `🚨 FLOOD ALERT: ${flooded.join(", ")} COMPROMISED  |  Safe zones: ${safe.length ? safe.join(", ") : "None"}`;
  } else {
    banner.className = "banner safe";
    banner.textContent = "✅ ALL ZONES OPERATIONAL — No flooding detected";
  }
}

function updateTopStatus(state) {
  const online = !!state.connected;
  const topDot = document.getElementById("topDot");
  const topStatus = document.getElementById("topStatus");

  topDot.classList.toggle("online", online);
  topStatus.textContent = online ? "ONLINE" : "OFFLINE";

  setText("statusMode", state.MODE);
  setText("statusPump", state.P);
  setText("statusConnected", online ? "Yes" : "No");

  setText("hubMode", state.MODE);
  setText("hubPump", state.P);

  const floodCount = ["Z1", "Z2", "Z3"].filter(z => Number(state[z].flood) === 1).length;
  setText("hubFloodCount", `${floodCount} / 3 ZONES`);
}

function updateLogs(logs) {
  const body = document.getElementById("logBody");
  body.innerHTML = logs.join("<br>");
  body.scrollTop = body.scrollHeight;
}

async function refreshState() {
  try {
    const res = await fetch("/api/state");
    const data = await res.json();
    const state = data.state;

    updateZone("Z1", state.Z1, state.P);
    updateZone("Z2", state.Z2, state.P);
    updateZone("Z3", state.Z3, state.P);

    updateButtons(state);
    updateAlert(state);
    updateTopStatus(state);
    updateLogs(data.logs);
  } catch (e) {
    console.error("State refresh failed", e);
  }
}

function bindButtons() {
  document.getElementById("btnAuto").addEventListener("click", () => sendCommand("MODE AUTO"));
  document.getElementById("btnManual").addEventListener("click", () => sendCommand("MODE MANUAL"));
  document.getElementById("btnStop").addEventListener("click", () => sendCommand("STOP ALL"));

  document.getElementById("btnZ1On").addEventListener("click", () => sendCommand("PUMP Z1 ON"));
  document.getElementById("btnZ1Off").addEventListener("click", () => sendCommand("PUMP Z1 OFF"));
  document.getElementById("btnZ2On").addEventListener("click", () => sendCommand("PUMP Z2 ON"));
  document.getElementById("btnZ2Off").addEventListener("click", () => sendCommand("PUMP Z2 OFF"));
  document.getElementById("btnZ3On").addEventListener("click", () => sendCommand("PUMP Z3 ON"));
  document.getElementById("btnZ3Off").addEventListener("click", () => sendCommand("PUMP Z3 OFF"));

  document.getElementById("btnLog").addEventListener("click", () => {
    showLog = !showLog;
    document.getElementById("logTerminal").classList.toggle("open", showLog);
    document.getElementById("btnLog").textContent = showLog ? "❌ HIDE LOG" : "SHOW LOG";
  });
}

bindButtons();
refreshState();
setInterval(refreshState, 1000);