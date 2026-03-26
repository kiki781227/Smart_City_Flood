let showLog = false;

async function sendCommand(cmd) {
  try {
    const res = await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cmd })
    });
    return await res.json();
  } catch (e) {
    console.error("Command failed", e);
    return { ok: false, error: String(e) };
  }
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function updateZone(zoneId, data, activePump, countdown) {
  const zone = document.getElementById(`zone-${zoneId}`);
  const water = document.getElementById(`water-${zoneId}`);
  const pct = document.getElementById(`pct-${zoneId}`);
  const raw = document.getElementById(`raw-${zoneId}`);
  const badge = document.getElementById(`badge-${zoneId}`);
  const pump = document.getElementById(`pump-${zoneId}`);
  const countdownEl = document.getElementById(`countdown-${zoneId}`);

  const flooded = Number(data.flood) === 1;

  zone.classList.toggle("flooded", flooded);
  water.style.height = `${data.pct}%`;
  pct.textContent = `${data.pct}%`;
  raw.textContent = `SENSOR: ${data.raw} units`;

  badge.className = `badge ${flooded ? "flooded" : "safe"}`;
  badge.textContent = flooded ? "⚠ FLOODED" : "✓ SAFE";

  pump.classList.toggle("active", activePump === zoneId);

  if (countdownEl) {
    if (countdown !== null && countdown !== undefined) {
      countdownEl.textContent = `AUTO START IN ${countdown}s`;
      countdownEl.classList.add("active");
    } else {
      countdownEl.textContent = "";
      countdownEl.classList.remove("active");
    }
  }
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
    if (btn) btn.disabled = !manualEnabled || cond;
  });
}

function updateAlert(state, runtime) {
  const flooded = ["Z1", "Z2", "Z3"].filter(z => Number(state[z].flood) === 1);
  const safe = ["Z1", "Z2", "Z3"].filter(z => Number(state[z].flood) === 0);
  const banner = document.getElementById("alertBanner");

  const pending = runtime?.countdowns || {};
  const pendingZones = Object.entries(pending)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([z, v]) => `${z} (${v}s)`);

  if (pendingZones.length > 0) {
    banner.className = "banner alert";
    banner.textContent = `⏳ AUTO COUNTDOWN: ${pendingZones.join(", ")}`;
    return;
  }

  if (flooded.length > 0) {
    banner.className = "banner alert";
    banner.textContent = `🚨 FLOOD ALERT: ${flooded.join(", ")} COMPROMISED  |  Safe zones: ${safe.length ? safe.join(", ") : "None"}`;
  } else {
    banner.className = "banner safe";
    banner.textContent = "✅ ALL ZONES OPERATIONAL — No flooding detected";
  }
}

function updateTopStatus(state, runtime) {
  const online = !!state.connected;
  const topDot = document.getElementById("topDot");
  const topStatus = document.getElementById("topStatus");

  topDot.classList.toggle("online", online);
  topStatus.textContent = online ? "ONLINE" : "OFFLINE";

  setText("statusMode", state.MODE);
  setText("statusPump", state.P);
  setText("statusConnected", online ? "Yes" : "No");
  setText("statusTelegram", runtime?.telegram_ok ? "Yes" : "No");
  setText("statusDelay", `${runtime?.auto_delay_sec ?? 0}s`);

  setText("hubMode", state.MODE);
  setText("hubPump", state.P);
  setText("hubTelegram", runtime?.telegram_ok ? "ON" : "OFF");

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
    const runtime = data.runtime || {};

    updateZone("Z1", state.Z1, state.P, runtime.countdowns?.Z1 ?? null);
    updateZone("Z2", state.Z2, state.P, runtime.countdowns?.Z2 ?? null);
    updateZone("Z3", state.Z3, state.P, runtime.countdowns?.Z3 ?? null);

    updateButtons(state);
    updateAlert(state, runtime);
    updateTopStatus(state, runtime);
    updateLogs(data.logs || []);
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