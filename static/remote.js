// Spooky phone remote
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const buzz = (ms = 30) => navigator.vibrate && navigator.vibrate(ms);

let state = null;
let layoutKey = "";

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return r.json();
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), 2200);
}

// ---------- actions ----------
async function scare() {
  buzz(60);
  const r = await api("/api/scare", {});
  toast(r.started ? "Boo! 👻" : "Already playing…");
  setTimeout(refresh, 150);
}
async function stopAll() {
  buzz();
  await api("/api/stop", { radio: true });
  toast("Silence.");
  refresh();
}
async function play(body) {
  buzz();
  const r = await api("/api/play", body);
  if (!r.ok) toast(r.error);
  setTimeout(refresh, 150);
}
async function denon(action, value) {
  buzz();
  const r = await api("/api/denon", { action, value });
  if (!r.ok) toast(r.error);
  setTimeout(refresh, 100);
}
async function setConfig(patch) {
  await api("/api/config", patch);
  refresh();
}

const ATMOS_ICONS = [["grave", "🪦"], ["cemet", "🪦"], ["sewer", "🐀"], ["asylum", "🏚️"], ["ward", "🏚️"],
  ["thunder", "⛈️"], ["storm", "⛈️"], ["rain", "🌧️"], ["forest", "🌲"], ["lab", "⚗️"], ["witch", "🧙"],
  ["cauldron", "🧙"], ["wind", "🌬️"], ["swamp", "🐸"], ["crypt", "⚰️"], ["church", "⛪"]];
const atmosIcon = (name) => (ATMOS_ICONS.find(([k]) => name.toLowerCase().includes(k)) || [, "👻"])[1];

// ---------- rendering ----------
function renderLayout() {
  const cfg = state.config;
  const key = JSON.stringify([cfg.placements.map((p) => [p.name, p.enabled, p.x]), state.sounds.map((s) => s.name),
    state.ambience.map((a) => a.name), cfg.sweep_sounds]);
  if (key === layoutKey) return;
  layoutKey = key;

  const ordered = cfg.placements.map((p, i) => ({ ...p, n: i + 1 })).sort((a, b) => a.x - b.x || a.y - b.y);
  $("spots").innerHTML = ordered.map((p) =>
    `<button class="btn r-spot ${p.enabled ? "" : "off"}" data-id="${p.id}"><b>${p.n}</b><span>${esc(p.name)}</span></button>`).join("");
  $("spots").querySelectorAll("[data-id]").forEach((b) => (b.onclick = () => play({ placement: b.dataset.id })));

  const target = $("target");
  const keep = target.value;
  target.innerHTML = `<option value="">Random speaker</option>` +
    cfg.placements.filter((p) => p.enabled).map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  target.value = [...target.options].some((o) => o.value === keep) ? keep : "";

  $("atmos").innerHTML = state.ambience.map((a) =>
    `<button class="atmos-tile" data-track="${esc(a.name)}"><span class="ico">${atmosIcon(a.name)}</span>${esc(a.label)}</button>`).join("");
  $("atmos").querySelectorAll("[data-track]").forEach((b) => (b.onclick = () => {
    buzz();
    const am = state.config.ambience;
    const playingThis = am.on && am.track === b.dataset.track;
    setConfig({ ambience: playingThis ? { on: false } : { on: true, track: b.dataset.track } });
  }));

  $("sounds").innerHTML = state.sounds.length
    ? state.sounds.map((s) => `<button class="btn r-sound" data-sound="${esc(s.name)}">${cfg.sweep_sounds.includes(s.name) ? "⇄" : "▶"} ${esc(s.label)}</button>`).join("")
    : `<p class="muted">No sounds yet. Add some from the full dashboard.</p>`;
  $("sounds").querySelectorAll("[data-sound]").forEach((b) =>
    (b.onclick = () => play({ sound: b.dataset.sound, placement: $("target").value || undefined })));
}

function renderLive() {
  const cfg = state.config, st = state.status;
  const playing = st.now_playing;
  const radioOn = st.radio.playing;

  let lit = playing ? playing.spots : [];
  if (playing && playing.progress != null && lit.length > 1) lit = [lit[Math.round(playing.progress * (lit.length - 1))]];
  document.querySelectorAll(".r-spot").forEach((b) => b.classList.toggle("playing", lit.includes(b.dataset.id)));
  document.querySelectorAll(".r-sound").forEach((b) => b.classList.toggle("playing", !!playing && playing.sound === b.dataset.sound));
  $("scareBtn").classList.toggle("busy", !!playing);

  const pill = $("pill");
  let cls = "armed", text = "Armed";
  if (playing) { cls = "playing"; text = "Scaring!"; }
  else if (radioOn && cfg.radio.override) { cls = "radio"; text = "Radio"; }
  else if (cfg.mode === "off") { cls = "sleep"; text = "Off"; }
  else if (st.blocked) { cls = "sleep"; text = "Sleeping"; }
  pill.className = "pill " + cls;
  pill.textContent = text;

  const now = $("nowPlaying");
  if (playing) {
    const where = playing.spots.map((id) => cfg.placements.find((p) => p.id === id)?.name).join(" → ");
    const label = state.sounds.find((s) => s.name === playing.sound)?.label || playing.sound;
    now.textContent = `🔊 ${label} · ${where}`;
  } else {
    now.textContent = radioOn ? `🎵 ${st.radio.name}` : st.blocked && cfg.mode !== "off" ? `Sleeping: ${st.blocked}` : "Quiet… for now.";
  }
  now.classList.toggle("on", !!playing || radioOn);

  document.querySelectorAll("#mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === cfg.mode));
  if (document.activeElement !== $("master")) $("master").value = cfg.master_volume;
  $("masterOut").textContent = Math.round(cfg.master_volume * 100) + "%";

  const amb = st.ambience || {};
  document.querySelectorAll(".atmos-tile").forEach((b) => {
    const chosen = cfg.ambience.on && cfg.ambience.track === b.dataset.track;
    b.classList.toggle("on", chosen && amb.playing === b.dataset.track);
    b.classList.toggle("waiting", chosen && !amb.want && amb.playing !== b.dataset.track);
  });
  if (document.activeElement !== $("atmosVol")) $("atmosVol").value = cfg.ambience.volume;
  $("atmosVolOut").textContent = Math.round(cfg.ambience.volume * 100) + "%";

  const radio = $("radio");
  if (radioOn) {
    radio.innerHTML = `<div class="r-row"><div class="now on" style="grid-column:1/-1;margin:0">🎵 ${esc(st.radio.name)}${st.radio.buffering ? " (tuning in…)" : ""}</div>
      <button class="btn danger" id="radioStop" style="grid-column:1/-1">⏹ Stop radio</button></div>`;
    $("radioStop").onclick = async () => { buzz(); await api("/api/radio/stop", {}); refresh(); };
  } else if (cfg.radio.last_url) {
    radio.innerHTML = `<button class="btn" id="radioGo" style="width:100%;padding:14px">▶ ${esc(cfg.radio.last_name)}</button>`;
    $("radioGo").onclick = async () => { buzz(); await api("/api/radio/play", { url: cfg.radio.last_url, name: cfg.radio.last_name }); refresh(); };
  } else {
    radio.innerHTML = `<p class="muted small">Pick a station on the <a href="/" style="color:inherit">full dashboard</a> first.</p>`;
  }

  const d = st.denon || {};
  $("denonMute").textContent = d.muted ? "Unmute" : "Mute";
  $("denonStatus").innerHTML = !d.connected
    ? `<span class="tag bad">Not connected</span>`
    : [`<span class="tag ${d.power === "on" ? "good" : ""}">${d.power === "on" ? "On" : "Standby"}</span>`,
       d.power === "on" && d.volume_db != null ? `<span class="tag">${d.volume_db.toFixed(1)} dB${d.muted ? " · muted" : ""}</span>` : "",
       d.power === "on" && d.input ? `<span class="tag">${esc(d.input)}</span>` : ""].join("");
}

async function refresh() {
  try {
    state = await api("/api/state");
  } catch {
    $("pill").className = "pill sleep";
    $("pill").textContent = "Can't reach the Pi";
    return;
  }
  renderLayout();
  renderLive();
}

// ---------- wiring ----------
$("scareBtn").onclick = scare;
$("motionBtn").onclick = async () => { buzz(); await api("/api/motion", {}); setTimeout(refresh, 150); };
$("stopBtn").onclick = stopAll;
const sweep = async (direction) => {
  buzz(40);
  const r = await api("/api/sweep", { direction });
  if (!r.ok) toast(r.error);
  setTimeout(refresh, 150);
};
$("sweepLtr").onclick = () => sweep("ltr");
$("sweepRtl").onclick = () => sweep("rtl");
document.querySelectorAll("#mode button").forEach((b) => (b.onclick = () => { buzz(); setConfig({ mode: b.dataset.mode }); }));
$("master").oninput = () => { $("masterOut").textContent = Math.round($("master").value * 100) + "%"; };
$("master").onchange = () => setConfig({ master_volume: +$("master").value });
$("atmosVol").oninput = () => { $("atmosVolOut").textContent = Math.round($("atmosVol").value * 100) + "%"; };
$("atmosVol").onchange = () => setConfig({ ambience: { volume: +$("atmosVol").value } });
document.querySelectorAll("[data-denon]").forEach((b) => (b.onclick = () => denon(b.dataset.denon, b.dataset.value)));

// Home-screen shortcuts: /remote?do=scare or ?do=stop
const action = new URLSearchParams(location.search).get("do");
if (action) {
  history.replaceState(null, "", "/remote");
  if (action === "scare") scare();
  if (action === "stop") stopAll();
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

refresh();
setInterval(() => { if (document.visibilityState === "visible") refresh(); }, 1500);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh(); });
