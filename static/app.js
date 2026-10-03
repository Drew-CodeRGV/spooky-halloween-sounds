// Spooky Halloween Sounds dashboard
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let cfg = null;          // our working copy of the config
let state = null;        // latest /api/state
let soundsKey = "";      // detects when the sound list changes
let saveTimer = null;
let pending = {};

// Yard map positions (percent), one per placement, in sidewalk order
const SPOTS = [
  { x: 9, y: 58 }, { x: 25, y: 38 }, { x: 50, y: 52 }, { x: 75, y: 38 },
  { x: 91, y: 58 }, { x: 22, y: 78 }, { x: 78, y: 78 },
];
const MODE_HINTS = {
  off: "Nothing plays on its own. The buttons on this page still work.",
  motion: "A sound plays when the motion sensor sees someone walk by.",
  auto: "A random sound plays on its own every so often, no sensor needed.",
  both: "Plays on its own every so often AND whenever someone walks by.",
};
const RADIO_TAGS = ["halloween", "horror", "spooky", "soundtrack", "dark ambient", "oldies", "classic rock"];

async function api(path, body, method) {
  const opts = { method: method || (body === undefined ? "GET" : "POST") };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  return r.json();
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), 2600);
}

// Merge a change into the config and save it shortly after (debounced)
function save(patch) {
  const { radio, denon: dn, ...rest } = patch;
  Object.assign(cfg, rest);
  pending = { ...pending, ...rest };
  for (const [k, v] of [["radio", radio], ["denon", dn]]) {
    if (!v) continue;
    cfg[k] = { ...cfg[k], ...v };
    pending[k] = { ...(pending[k] || {}), ...v };
  }
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const body = pending;
    pending = {};
    cfg = await api("/api/config", body);
  }, 350);
}
const savePlacements = () => save({ placements: cfg.placements });

// ---------- Rendering ----------

function renderYard() {
  const yard = $("yard");
  yard.querySelectorAll(".spot").forEach((n) => n.remove());
  cfg.placements.forEach((p, i) => {
    const b = document.createElement("button");
    b.className = "spot";
    b.dataset.id = p.id;
    b.style.left = SPOTS[i].x + "%";
    b.style.top = SPOTS[i].y + "%";
    b.title = p.enabled ? `Play a sound from the ${p.name}` : `${p.name} is turned off`;
    b.innerHTML = `<div class="dot">${i + 1}</div><div class="label">${esc(p.name)}</div>`;
    b.onclick = () => playAt(p.id);
    yard.appendChild(b);
  });
  updateLive();
}

function renderPlacements() {
  const wrap = $("placements");
  wrap.innerHTML = "";
  const channels = [0, 1, 2, 3, 4, 5, 6, 7];
  cfg.placements.forEach((p, i) => {
    const card = document.createElement("div");
    card.className = "card" + (p.enabled ? "" : " off");
    card.dataset.id = p.id;
    card.innerHTML = `
      <div class="card-head">
        <span class="num">${i + 1}</span>
        <input type="text" value="${esc(p.name)}" maxlength="30" aria-label="Name">
      </div>
      <label class="toggle"><input type="checkbox" ${p.enabled ? "checked" : ""}><span>Speaker is here</span></label>
      <div class="meta">
        <span>Denon: ${esc(p.terminal)}</span>
        <label>HDMI ch <select>${channels.map((c) => `<option ${c === p.channel ? "selected" : ""}>${c}</option>`).join("")}</select></label>
      </div>
      <label class="slider-row"><span>Volume</span><input type="range" min="0" max="1" step="0.01" value="${p.volume}"><output>${Math.round(p.volume * 100)}%</output></label>
      <div class="actions">
        <button class="btn small" data-act="beep">🔔 Beep</button>
        <button class="btn small" data-act="play">▶ Play</button>
      </div>`;
    const [nameIn, enabledIn] = card.querySelectorAll("input");
    const chSel = card.querySelector("select");
    const vol = card.querySelector("input[type=range]");
    nameIn.oninput = () => { p.name = nameIn.value; savePlacements(); renderYard(); renderMatrix(true); renderRadioSpots(); };
    enabledIn.onchange = () => { p.enabled = enabledIn.checked; card.classList.toggle("off", !p.enabled); savePlacements(); renderYard(); renderMatrix(true); };
    chSel.onchange = () => { p.channel = +chSel.value; savePlacements(); };
    vol.oninput = () => { p.volume = +vol.value; card.querySelector("output").textContent = Math.round(p.volume * 100) + "%"; savePlacements(); };
    card.querySelector("[data-act=beep]").onclick = () => { api("/api/beep", { channel: p.channel }); toast(`Beeping HDMI channel ${p.channel}: listen for 3 beeps`); };
    card.querySelector("[data-act=play]").onclick = () => playAt(p.id);
    wrap.appendChild(card);
  });
}

function renderMatrix(force) {
  const key = state.sounds.map((s) => s.name).join("|");
  if (!force && key === soundsKey) return;
  soundsKey = key;
  const t = $("matrix");
  if (!state.sounds.length) {
    t.innerHTML = `<tr><td class="muted">No sounds yet. Add some below.</td></tr>`;
    return;
  }
  const head = cfg.placements.map((p, i) => `<th class="${p.enabled ? "" : "off"}">${i + 1}<br>${esc(p.name)}</th>`).join("");
  const rows = state.sounds.map((s) => {
    const cells = cfg.placements.map((p) =>
      `<td><input type="checkbox" data-sound="${esc(s.name)}" data-id="${p.id}" ${p.muted_sounds.includes(s.name) ? "" : "checked"} aria-label="${esc(s.label)} on ${esc(p.name)}"></td>`).join("");
    return `<tr data-sound="${esc(s.name)}">
      <td class="name"><button class="icon-btn" data-play="${esc(s.name)}" title="Play now">▶</button>${esc(s.label)}<small>${s.seconds}s</small></td>
      ${cells}
      <td><button class="icon-btn" data-del="${esc(s.name)}" title="Remove sound">🗑</button></td></tr>`;
  }).join("");
  t.innerHTML = `<thead><tr><th style="text-align:left">Sound</th>${head}<th></th></tr></thead><tbody>${rows}</tbody>`;
  t.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.onchange = () => {
      const p = cfg.placements.find((x) => x.id === cb.dataset.id);
      const name = cb.dataset.sound;
      p.muted_sounds = cb.checked ? p.muted_sounds.filter((n) => n !== name) : [...p.muted_sounds, name];
      savePlacements();
    };
  });
  t.querySelectorAll("[data-play]").forEach((b) => (b.onclick = async () => {
    const r = await api("/api/play", { sound: b.dataset.play });
    if (!r.ok) toast(r.error);
  }));
  t.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    if (!confirm(`Remove "${b.dataset.del}" from the Pi?`)) return;
    await api("/api/sounds/" + encodeURIComponent(b.dataset.del), undefined, "DELETE");
    refresh();
  }));
}

function renderTiming() {
  document.querySelectorAll("#mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === cfg.mode));
  $("modeHint").textContent = MODE_HINTS[cfg.mode];
  const unit = cfg.auto_min % 60 === 0 && cfg.auto_max % 60 === 0 ? 60 : 1;
  $("autoUnit").value = unit;
  $("autoMin").value = cfg.auto_min / unit;
  $("autoMax").value = cfg.auto_max / unit;
  $("coolMin").value = cfg.cooldown_min;
  $("coolMax").value = cfg.cooldown_max;
  setSlider("answer", cfg.answer_chance, true);
  setSlider("creep", cfg.creep_chance, true);
  $("hoursOn").checked = cfg.active_hours_enabled;
  $("hoursStart").value = cfg.active_start;
  $("hoursEnd").value = cfg.active_end;
  setSlider("master", cfg.master_volume, true);
  $("device").value = cfg.audio_device;
}

function setSlider(id, v, pct) {
  $(id).value = v;
  $(id + "Out").textContent = pct ? Math.round(v * 100) + "%" : v;
}

function renderRadioSpots() {
  const wrap = $("radioSpots");
  wrap.innerHTML = "";
  cfg.placements.forEach((p) => {
    const on = cfg.radio.placements.includes(p.id);
    const c = document.createElement("button");
    c.className = "chip" + (on ? " on" : "");
    c.textContent = p.name;
    c.onclick = () => {
      const list = on ? cfg.radio.placements.filter((x) => x !== p.id) : [...cfg.radio.placements, p.id];
      save({ radio: { placements: list } });
      renderRadioSpots();
    };
    wrap.appendChild(c);
  });
}

function renderRadioSettings() {
  setSlider("radioVol", cfg.radio.volume, true);
  $("radioOverride").checked = cfg.radio.override;
  $("radioAutoplay").checked = cfg.radio.autoplay;
  $("radioTags").innerHTML = RADIO_TAGS.map((t) => `<button class="chip" data-tag="${t}">${t}</button>`).join("");
  $("radioTags").querySelectorAll("[data-tag]").forEach((b) => (b.onclick = () => { $("radioQuery").value = b.dataset.tag; searchRadio(); }));
  renderRadioSpots();
}

async function searchRadio() {
  const q = $("radioQuery").value.trim() || "halloween";
  const box = $("stations");
  box.innerHTML = `<div class="muted">Searching for “${esc(q)}”…</div>`;
  const r = await api("/api/radio/search?q=" + encodeURIComponent(q));
  if (!r.ok) { box.innerHTML = `<div class="alert">${esc(r.error)}</div>`; return; }
  if (!r.stations.length) { box.innerHTML = `<div class="muted">No stations found. Try another word.</div>`; return; }
  box.innerHTML = "";
  r.stations.forEach((s) => {
    const d = document.createElement("div");
    d.className = "station";
    const details = [s.country, s.codec, s.bitrate ? s.bitrate + "k" : "", s.tags].filter(Boolean).join(" · ");
    d.innerHTML = `<div class="info"><b>${esc(s.name)}</b><span>${esc(details)}</span></div><button class="btn small">▶ Play</button>`;
    d.querySelector("button").onclick = () => playRadio(s.url, s.name);
    box.appendChild(d);
  });
}

async function playRadio(url, name) {
  const r = await api("/api/radio/play", { url, name });
  toast(r.ok ? `Tuning in: ${name}` : r.error);
  refresh();
}

async function playAt(id) {
  const r = await api("/api/play", { placement: id });
  if (!r.ok) toast(r.error);
  setTimeout(refresh, 150);
}

// ---------- Denon ----------

const dB = (v) => (v > 0 ? "+" : "") + Number(v).toFixed(1) + " dB";
let denonVolBusy = 0;   // don't yank the slider while someone is dragging it

function options(sel, list, current) {
  sel.innerHTML = list.map(([v, label]) => `<option value="${esc(v)}" ${v === current ? "selected" : ""}>${esc(label)}</option>`).join("");
}

function renderDenonSettings() {
  const dn = cfg.denon;
  const inputs = state.denon_inputs.map((i) => [i, i]);
  const modes = Object.entries(state.denon_modes);
  options($("denonReadyInput"), inputs, dn.input);
  options($("denonReadyMode"), modes, dn.mode);
  options($("denonInput"), [["", "–"], ...inputs], "");
  options($("denonMode"), [["", "–"], ...modes], "");
  $("denonMax").value = dn.max_db; $("denonMaxOut").textContent = dB(dn.max_db);
  $("denonReadyVol").max = dn.max_db; $("denonVol").max = dn.max_db;
  $("denonReadyVol").value = dn.volume_db; $("denonReadyVolOut").textContent = dB(dn.volume_db);
  $("denonAuto").checked = dn.auto_power;
  $("denonHost").value = dn.host;
}

async function denon(action, value) {
  if (["ready", "on", "find"].includes(action)) toast(action === "find" ? "Looking for the Denon…" : "Talking to the Denon…");
  const r = await api("/api/denon", { action, value });
  if (!r.ok) toast(r.error);
  else if (action === "find") { toast(`Found the Denon at ${r.denon.host}`); refreshCfg(); }
  else if (action === "ready") toast("Denon is ready to haunt");
  state.status.denon = r.denon;
  updateDenon();
}

async function refreshCfg() {
  cfg = await api("/api/config", {});
  renderDenonSettings();
}

function updateDenon() {
  const d = state.status.denon || {};
  const box = $("denonStatus");
  if (!d.connected) {
    box.innerHTML = `<span class="tag bad">Not connected</span><span class="muted small">${esc(d.error || "")}</span>`;
    return;
  }
  const on = d.power === "on";
  const modeName = state.denon_modes[d.mode] || d.mode || "?";
  box.innerHTML = [
    `<span class="tag ${on ? "good" : ""}">${on ? "On" : "Standby"}</span>`,
    on ? `<span class="tag">Input: ${esc(d.input || "?")}</span>` : "",
    on ? `<span class="tag">Mode: ${esc(modeName)}</span>` : "",
    on && d.volume_db != null ? `<span class="tag">${dB(d.volume_db)}${d.muted ? " · muted" : ""}</span>` : "",
    `<span class="tag muted">${esc(d.host)}</span>`,
  ].join("");
  $("denonMute").textContent = d.muted ? "🔊 Unmute" : "🔇 Mute";
  if (d.volume_db != null && Date.now() > denonVolBusy) {
    $("denonVol").value = d.volume_db;
    $("denonVolOut").textContent = dB(d.volume_db);
  }
  if (document.activeElement !== $("denonInput")) $("denonInput").value = state.denon_inputs.includes(d.input) ? d.input : "";
  if (document.activeElement !== $("denonMode")) $("denonMode").value = d.mode in state.denon_modes ? d.mode : "";
}

// ---------- Live status ----------

function updateLive() {
  if (!state) return;
  const st = state.status;
  const playing = st.now_playing ? st.now_playing.spots : [];
  const radioOn = st.radio.playing;

  document.querySelectorAll(".spot").forEach((n) => {
    const p = cfg.placements.find((x) => x.id === n.dataset.id);
    n.classList.toggle("off", !p.enabled);
    n.classList.toggle("playing", playing.includes(p.id));
    n.classList.toggle("radio", radioOn && cfg.radio.placements.includes(p.id));
  });
  document.querySelectorAll(".card").forEach((n) => n.classList.toggle("playing", playing.includes(n.dataset.id)));
  document.querySelectorAll(".matrix tr[data-sound]").forEach((n) =>
    n.classList.toggle("playing", !!st.now_playing && st.now_playing.sound === n.dataset.sound));

  const pill = $("pill");
  let cls = "armed", text = "Armed & waiting";
  if (st.now_playing) { cls = "playing"; text = "Scaring!"; }
  else if (radioOn && cfg.radio.override) { cls = "radio"; text = "Radio on"; }
  else if (cfg.mode === "off") { cls = "sleep"; text = "Off"; }
  else if (st.blocked) { cls = "sleep"; text = "Sleeping: " + st.blocked; }
  pill.className = "pill " + cls;
  pill.textContent = text;
  $("clock").textContent = st.time;

  const now = $("nowPlaying");
  if (st.now_playing) {
    const names = st.now_playing.spots.map((id) => cfg.placements.find((p) => p.id === id)?.name).join(" → ");
    const label = state.sounds.find((s) => s.name === st.now_playing.sound)?.label || st.now_playing.sound;
    now.textContent = `🔊 ${label} from the ${names}`;
    now.classList.add("on");
  } else {
    now.textContent = radioOn ? `🎵 Radio: ${st.radio.name}` : "Quiet… for now.";
    now.classList.toggle("on", radioOn);
  }

  const err = $("audioError");
  err.textContent = st.audio_error || "";
  err.classList.toggle("hidden", !st.audio_error);

  $("nextAuto").textContent = st.next_auto_in == null ? "Automatic mode is off."
    : st.blocked && st.blocked !== "playing" ? `Waiting: ${st.blocked}.` : `Next one in about ${fmtSecs(st.next_auto_in)}.`;
  $("sensorInfo").textContent = `Sensor: ${st.sensor}.` +
    (st.last_motion_ago != null ? ` Last motion ${fmtSecs(st.last_motion_ago)} ago.` : "");

  const rn = $("radioNow");
  if (radioOn) {
    rn.innerHTML = `<div class="live">🎵 <b>${esc(st.radio.name)}</b>${st.radio.buffering ? '<span class="muted">tuning in…</span>' : ""}<button class="btn small danger" id="radioStop">⏹ Stop radio</button></div>`;
    $("radioStop").onclick = async () => { await api("/api/radio/stop", {}); refresh(); };
  } else if (st.radio.error) {
    rn.innerHTML = `<div class="alert">${esc(st.radio.error)}</div>`;
  } else if (cfg.radio.last_url) {
    rn.innerHTML = `<button class="btn" id="radioResume">▶ Resume ${esc(cfg.radio.last_name)}</button>`;
    $("radioResume").onclick = () => playRadio(cfg.radio.last_url, cfg.radio.last_name);
  } else {
    rn.innerHTML = "";
  }

  $("log").innerHTML = state.log.map((l) => `<li><time>${esc(l.t)}</time><span>${esc(l.text)}</span></li>`).join("");
}

function fmtSecs(s) {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

async function refresh() {
  try {
    state = await api("/api/state");
  } catch {
    $("pill").className = "pill sleep";
    $("pill").textContent = "Can't reach the Pi";
    return;
  }
  if (!cfg) {
    cfg = state.config;
    renderYard(); renderPlacements(); renderTiming(); renderRadioSettings(); renderMatrix(true); renderDenonSettings();
  } else {
    renderMatrix(false);
  }
  updateLive();
  updateDenon();
}

// ---------- Wire up static controls ----------

function wire() {
  $("scareBtn").onclick = async () => {
    const r = await api("/api/scare", {});
    toast(r.started ? "Boo!" : "Already playing. Hang on…");
    setTimeout(refresh, 150);
  };
  $("motionBtn").onclick = async () => { await api("/api/motion", {}); setTimeout(refresh, 150); };
  $("stopBtn").onclick = async () => { await api("/api/stop", { radio: true }); toast("Silence."); refresh(); };
  $("master").oninput = () => { setSlider("master", +$("master").value, true); save({ master_volume: +$("master").value }); };

  document.querySelectorAll("#mode button").forEach((b) => (b.onclick = () => { save({ mode: b.dataset.mode }); renderTiming(); }));
  const saveAuto = () => {
    const u = +$("autoUnit").value;
    save({ auto_min: Math.max(1, +$("autoMin").value * u), auto_max: Math.max(1, +$("autoMax").value * u) });
  };
  ["autoMin", "autoMax"].forEach((id) => ($(id).onchange = saveAuto));
  $("autoUnit").onchange = saveAuto;
  ["coolMin", "coolMax"].forEach((id) => ($(id).onchange = () => save({ cooldown_min: +$("coolMin").value, cooldown_max: +$("coolMax").value })));
  $("answer").oninput = () => { setSlider("answer", +$("answer").value, true); save({ answer_chance: +$("answer").value }); };
  $("creep").oninput = () => { setSlider("creep", +$("creep").value, true); save({ creep_chance: +$("creep").value }); };
  $("hoursOn").onchange = () => save({ active_hours_enabled: $("hoursOn").checked });
  $("hoursStart").onchange = () => save({ active_start: $("hoursStart").value });
  $("hoursEnd").onchange = () => save({ active_end: $("hoursEnd").value });
  $("device").onchange = () => save({ audio_device: $("device").value.trim() });

  $("radioSearchBtn").onclick = searchRadio;
  $("radioQuery").onkeydown = (e) => { if (e.key === "Enter") searchRadio(); };
  $("radioUrlBtn").onclick = () => playRadio($("radioUrl").value.trim(), $("radioUrl").value.trim());
  $("radioVol").oninput = () => { setSlider("radioVol", +$("radioVol").value, true); save({ radio: { volume: +$("radioVol").value } }); };
  $("radioOverride").onchange = () => save({ radio: { override: $("radioOverride").checked } });
  $("radioAutoplay").onchange = () => save({ radio: { autoplay: $("radioAutoplay").checked } });

  document.querySelectorAll("[data-denon]").forEach((b) => (b.onclick = () => denon(b.dataset.denon, b.dataset.value)));
  $("denonVol").oninput = () => { denonVolBusy = Date.now() + 4000; $("denonVolOut").textContent = dB($("denonVol").value); };
  $("denonVol").onchange = () => { denonVolBusy = Date.now() + 2000; denon("volume", +$("denonVol").value); };
  $("denonInput").onchange = () => $("denonInput").value && denon("input", $("denonInput").value);
  $("denonMode").onchange = () => $("denonMode").value && denon("mode", $("denonMode").value);
  $("denonReadyInput").onchange = () => save({ denon: { input: $("denonReadyInput").value } });
  $("denonReadyMode").onchange = () => save({ denon: { mode: $("denonReadyMode").value } });
  $("denonReadyVol").oninput = () => { $("denonReadyVolOut").textContent = dB($("denonReadyVol").value); save({ denon: { volume_db: +$("denonReadyVol").value } }); };
  $("denonMax").oninput = () => {
    const m = +$("denonMax").value;
    $("denonMaxOut").textContent = dB(m);
    $("denonReadyVol").max = m; $("denonVol").max = m;
    save({ denon: { max_db: m } });
  };
  $("denonAuto").onchange = () => save({ denon: { auto_power: $("denonAuto").checked } });
  $("denonHost").onchange = () => save({ denon: { host: $("denonHost").value.trim() } });

  $("fileInput").onchange = async () => {
    const files = $("fileInput").files;
    if (!files.length) return;
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    toast(`Uploading ${files.length} file(s)…`);
    const r = await (await fetch("/api/sounds", { method: "POST", body: fd })).json();
    toast(r.saved.length ? `Added ${r.saved.length} sound(s)` : "No audio files in that upload");
    $("fileInput").value = "";
    refresh();
  };
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

wire();
refresh().then(searchRadio);
setInterval(refresh, 1500);
