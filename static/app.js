// Spooky Halloween Sounds dashboard
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let cfg = null;          // our working copy of the config
let state = null;        // latest /api/state
let soundsKey = "";      // detects when the sound list changes
let saveTimer = null;
let pending = {};

// Yard map positions (percent), one per placement, in sidewalk order
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
  const { radio, denon: dn, ambience, lights, ring, ...rest } = patch;
  Object.assign(cfg, rest);
  pending = { ...pending, ...rest };
  showSaved("Saving…");
  for (const [k, v] of [["radio", radio], ["denon", dn], ["ambience", ambience], ["lights", lights], ["ring", ring]]) {
    if (!v) continue;
    cfg[k] = { ...cfg[k], ...v };
    pending[k] = { ...(pending[k] || {}), ...v };
  }
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const body = pending;
    pending = {};
    try {
      await api("/api/config", body);   // keep our local copy: it already has the edits
      showSaved("Saved ✓");
    } catch {
      showSaved("Not saved: can't reach the Pi", true);
    }
  }, 350);
}
const savePlacements = () => save({ placements: cfg.placements });

function showSaved(text, bad) {
  const el = $("saveState");
  el.textContent = text;
  el.className = "save-state show" + (bad ? " bad" : "");
  clearTimeout(showSaved.timer);
  if (!bad && text !== "Saving…") showSaved.timer = setTimeout(() => (el.className = "save-state"), 1800);
}

// ---------- Rendering ----------

function renderYard() {
  const yard = $("yard");
  yard.querySelectorAll(".spot").forEach((n) => n.remove());
  cfg.placements.forEach((p, i) => {
    const b = document.createElement("button");
    b.className = "spot";
    b.dataset.id = p.id;
    b.style.left = p.x + "%";
    b.style.top = p.y + "%";
    b.title = (p.enabled ? `Tap to play a sound from the ${p.name}` : `${p.name} is turned off`) + ". Drag to move it.";
    b.innerHTML = `<div class="dot">${i + 1}</div><div class="label">${esc(p.name)}</div>`;
    makeDraggable(b, p.id);
    yard.appendChild(b);
  });
  updateLive();
}

// Drag a speaker around the yard map; a tap without moving plays a sound there.
function makeDraggable(el, id) {
  let start = null;
  el.addEventListener("pointerdown", (e) => {
    start = { x: e.clientX, y: e.clientY, moved: false };
    el.setPointerCapture(e.pointerId);
  });
  el.addEventListener("pointermove", (e) => {
    if (!start) return;
    if (!start.moved && Math.hypot(e.clientX - start.x, e.clientY - start.y) < 6) return;
    start.moved = true;
    el.classList.add("dragging");
    const box = $("yard").getBoundingClientRect();
    const x = Math.min(97, Math.max(3, ((e.clientX - box.left) / box.width) * 100));
    const y = Math.min(92, Math.max(5, ((e.clientY - box.top) / box.height) * 100));
    el.style.left = x + "%";
    el.style.top = y + "%";
    Object.assign(cfg.placements.find((p) => p.id === id), { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 });
  });
  const end = () => {
    if (!start) return;
    const moved = start.moved;
    start = null;
    el.classList.remove("dragging");
    if (moved) {
      savePlacements();
      renderSweepOrder();
    } else {
      playAt(id);
    }
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
}

// Show the left-to-right order sweeps will travel
function renderSweepOrder() {
  const on = cfg.placements.filter((p) => p.enabled).sort((a, b) => a.x - b.x || a.y - b.y);
  $("sweepOrder").textContent = on.length > 1 ? "Sweep order: " + on.map((p) => p.name).join(" → ") : "";
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
    const id = p.id;
    const P = () => cfg.placements.find((x) => x.id === id);
    const [nameIn, enabledIn] = card.querySelectorAll("input");
    const chSel = card.querySelector("select");
    const vol = card.querySelector("input[type=range]");
    nameIn.oninput = () => { P().name = nameIn.value; savePlacements(); renderYard(); renderMatrix(true); renderRadioSpots(); renderAtmosSettings(); renderSweepOrder(); renderLights(); };
    nameIn.onblur = () => { if (!nameIn.value.trim()) { nameIn.value = P().name = `Speaker ${i + 1}`; savePlacements(); renderYard(); } };
    nameIn.onkeydown = (e) => { if (e.key === "Enter") nameIn.blur(); };
    enabledIn.onchange = () => { P().enabled = enabledIn.checked; card.classList.toggle("off", !enabledIn.checked); savePlacements(); renderYard(); renderMatrix(true); renderSweepOrder(); };
    chSel.onchange = () => { P().channel = +chSel.value; savePlacements(); };
    vol.oninput = () => { P().volume = +vol.value; card.querySelector("output").textContent = Math.round(vol.value * 100) + "%"; savePlacements(); };
    card.querySelector("[data-act=beep]").onclick = () => { const ch = P().channel; api("/api/beep", { channel: ch }); toast(`Beeping HDMI channel ${ch}: listen for 3 beeps`); };
    card.querySelector("[data-act=play]").onclick = () => playAt(id);
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
  const isOff = (name) => cfg.disabled_sounds.includes(name);
  const sweeps = (name) => cfg.sweep_sounds.includes(name);
  const rows = state.sounds.map((s) => {
    const cells = cfg.placements.map((p) =>
      `<td><input type="checkbox" data-sound="${esc(s.name)}" data-id="${p.id}" ${p.muted_sounds.includes(s.name) ? "" : "checked"} aria-label="${esc(s.label)} on ${esc(p.name)}"></td>`).join("");
    return `<tr data-sound="${esc(s.name)}" class="${isOff(s.name) ? "sound-off" : ""}">
      <td class="name"><button class="icon-btn" data-play="${esc(s.name)}" title="Play in the yard">▶</button><button class="icon-btn preview-btn" data-preview="${esc(s.name)}" title="Preview on this device (not in the yard)">🎧</button>${esc(s.label)}<small>${s.seconds}s</small></td>
      <td class="onoff"><label class="switch" title="Turn this sound on or off everywhere"><input type="checkbox" data-onoff="${esc(s.name)}" ${isOff(s.name) ? "" : "checked"}><span></span></label></td>
      <td class="onoff"><label class="switch sweep" title="Always sweep this sound across the whole yard"><input type="checkbox" data-sweep="${esc(s.name)}" ${sweeps(s.name) ? "checked" : ""}><span></span></label></td>
      <td class="onoff light-color"><input type="color" data-color="${esc(s.name)}" value="${s.color}" title="Light color for this sound${s.custom_color ? "" : " (automatic)"}"><button class="icon-btn reset-color ${s.custom_color ? "" : "hidden"}" data-reset="${esc(s.name)}" title="Back to the automatic color">↺</button></td>
      ${cells}
      <td><button class="icon-btn" data-del="${esc(s.name)}" title="Remove sound">🗑</button></td></tr>`;
  }).join("");
  t.innerHTML = `<thead><tr><th style="text-align:left">Sound</th><th>On</th><th>Sweep</th><th>Light</th>${head}<th></th></tr></thead><tbody>${rows}</tbody>`;
  t.querySelectorAll("[data-onoff]").forEach((cb) => {
    cb.onchange = () => {
      const name = cb.dataset.onoff;
      const off = cfg.disabled_sounds.filter((n) => n !== name);
      save({ disabled_sounds: cb.checked ? off : [...off, name] });
      cb.closest("tr").classList.toggle("sound-off", !cb.checked);
    };
  });
  t.querySelectorAll("[data-color]").forEach((inp) => {
    inp.oninput = () => {
      save({ sound_colors: { ...cfg.sound_colors, [inp.dataset.color]: inp.value } });
      inp.nextElementSibling.classList.remove("hidden");
      inp.title = "Light color for this sound";
    };
  });
  t.querySelectorAll("[data-reset]").forEach((b) => (b.onclick = async () => {
    const { [b.dataset.reset]: _, ...rest } = cfg.sound_colors;
    save({ sound_colors: rest });
    b.classList.add("hidden");
    setTimeout(async () => {   // show the automatic color again
      state = await api("/api/state");
      renderMatrix(true);
    }, 600);
  }));
  t.querySelectorAll("[data-sweep]").forEach((cb) => {
    cb.onchange = () => {
      const name = cb.dataset.sweep;
      const rest = cfg.sweep_sounds.filter((n) => n !== name);
      save({ sweep_sounds: cb.checked ? [...rest, name] : rest });
    };
  });
  t.querySelectorAll("input[data-id]").forEach((cb) => {
    cb.onchange = () => {
      const p = cfg.placements.find((x) => x.id === cb.dataset.id);
      const name = cb.dataset.sound;
      p.muted_sounds = cb.checked ? p.muted_sounds.filter((n) => n !== name) : [...p.muted_sounds, name];
      savePlacements();
    };
  });
  t.querySelectorAll("[data-preview]").forEach((b) => (b.onclick = () => preview(b.dataset.preview)));
  markPreview();
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

function renderSweep() {
  setSweepSecs(cfg.sweep_seconds);
  const sel = $("sweepSound");
  sel.innerHTML = `<option value="">Random</option>` +
    state.sounds.map((s) => `<option value="${esc(s.name)}">${esc(s.label)}</option>`).join("");
  sel.value = state.sounds.some((s) => s.name === cfg.sweep_sound) ? cfg.sweep_sound : "";
}

function setSweepSecs(v) {
  $("sweepSecs").value = v;
  $("sweepSecsOut").textContent = v + "s";
}

async function doSweep(direction) {
  const r = await api("/api/sweep", { direction });
  if (!r.ok) toast(r.error);
  setTimeout(refresh, 150);
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

// ---------- Preview on this device ----------
// Plays the file through this computer's or phone's own speakers, not the yard's.

let previewAudio = null;
let previewName = null;

function preview(name) {
  const same = previewName === name;
  stopPreview();
  if (same) return;  // second tap stops it
  previewName = name;
  previewAudio = new Audio("/sounds/" + name.split("/").map(encodeURIComponent).join("/"));
  previewAudio.onended = stopPreview;
  previewAudio.play().catch(() => { toast("This browser couldn't play that file"); stopPreview(); });
  toast("🎧 Previewing on this device. Tap 🎧 again to stop.");
  markPreview();
}

function stopPreview() {
  if (previewAudio) { previewAudio.pause(); previewAudio = null; }
  previewName = null;
  markPreview();
}

function markPreview() {
  document.querySelectorAll("[data-preview]").forEach((b) => b.classList.toggle("previewing", b.dataset.preview === previewName));
}

// ---------- Ring doorbell ----------

function renderRing() {
  const rg = cfg.ring;
  $("ringOn").checked = rg.enabled;
  $("ringMotionOn").checked = rg.motion_on;
  $("ringDingOn").checked = rg.ding_on;
  $("ringCooldown").value = rg.cooldown;
  $("ringHours").checked = rg.active_hours_only;
  const sounds = [["", "Random"], ...state.sounds.map((s) => [s.name, s.label])];
  options($("ringMotionSound"), sounds, rg.motion_sound);
  options($("ringDingSound"), sounds, rg.ding_sound);
  options($("ringSpot"), [["", "Automatic (the porch speaker)"], ...cfg.placements.map((p) => [p.id, p.name + (p.enabled ? "" : " (off)")])], rg.placement);
}

function updateRing() {
  const r = state.status.ring || {};
  const box = $("ringStatus");
  const good = r.state === "connected";
  const label = { connected: "Connected", "not signed in": "Not connected yet", "not installed": "Needs the installer", starting: "Connecting…", error: "Connection problem" }[r.state] || r.state;
  box.innerHTML = [`<span class="tag ${good ? "good" : r.state === "error" ? "bad" : ""}">${esc(label)}</span>`,
    good && r.devices?.length ? `<span class="tag">${esc(r.devices.join(", "))}</span>` : "",
    r.last_event ? `<span class="tag">Last: ${r.last_event.kind === "ding" ? "🔔 doorbell" : "🚶 motion"} at ${esc(r.last_event.t)}</span>` : "",
    r.error ? `<span class="muted small">${esc(r.error)}</span>` : ""].join("");
  if (!good && r.state === "not signed in") $("ringSetup").open = true;
}

// ---------- Govee lights ----------

function renderLights() {
  const li = cfg.lights;
  $("lightsOn").checked = li.enabled;
  $("lightsIdleColor").value = li.idle_color;
  setSlider("lightsIdle", li.idle_brightness);
  $("lightsIdleOut").textContent = li.idle_brightness + "%";
  setSlider("lightsFlash", li.flash_brightness);
  $("lightsFlashOut").textContent = li.flash_brightness + "%";
  $("lightsFlicker").checked = li.flicker;
  setSlider("lightsRipple", li.ripple, true);
  $("lightsSched").checked = li.schedule;
  $("lightsBefore").value = li.minutes_before;
  $("lightsOff").value = li.off_time;
  $("lightsPlace").value = li.place;
  const box = $("lightsList");
  if (!li.devices.length) {
    box.innerHTML = `<p class="muted small">No lights yet. Press <b>Find lights</b>.</p>`;
    return;
  }
  const spotOptions = (sel) => [`<option value="all" ${sel === "all" ? "selected" : ""}>All spots</option>`,
    ...cfg.placements.map((p) => `<option value="${p.id}" ${sel === p.id ? "selected" : ""}>${esc(p.name)}${p.enabled ? "" : " (off)"}</option>`)].join("");
  box.innerHTML = li.devices.map((d, i) => `
    <div class="light-row ${d.on ? "" : "off"}" data-i="${i}">
      <span class="bulb">💡</span>
      <div><input type="text" value="${esc(d.name)}" maxlength="30" aria-label="Light name"><div class="meta">${esc(d.sku)} · ${esc(d.ip)}</div></div>
      <select aria-label="Yard spot">${spotOptions(d.placement)}</select>
      <label class="switch" title="Use this light"><input type="checkbox" ${d.on ? "checked" : ""}><span></span></label>
      <button class="btn small" data-test>Test</button>
      <div class="chain-opts">
        <label class="toggle"><input type="checkbox" data-chain ${d.chain ? "checked" : ""}><span>Chain across the yard: light only the bulbs nearest each sound, and follow sweeps</span></label>
        <span class="chain-detail ${d.chain ? "" : "hidden"}">
          <label title="One per light or bulb section in the chain">Segments <input type="number" data-segs min="2" max="100" value="${d.segments}"></label>
          <label class="toggle"><input type="checkbox" data-rev ${d.reverse ? "checked" : ""}><span>First bulb is on the east end</span></label>
        </span>
      </div>
    </div>`).join("");
  box.querySelectorAll(".light-row").forEach((row) => {
    const d = () => cfg.lights.devices[+row.dataset.i];
    const saveDevices = () => save({ lights: { devices: cfg.lights.devices } });
    row.querySelector("input[type=text]").oninput = (e) => { d().name = e.target.value; saveDevices(); };
    row.querySelector("select").onchange = (e) => { d().placement = e.target.value; saveDevices(); };
    row.querySelector(".switch input").onchange = (e) => { d().on = e.target.checked; row.classList.toggle("off", !d().on); saveDevices(); };
    row.querySelector("[data-chain]").onchange = (e) => {
      d().chain = e.target.checked;
      row.querySelector(".chain-detail").classList.toggle("hidden", !d().chain);
      row.querySelector("select").disabled = d().chain;
      saveDevices();
    };
    row.querySelector("[data-segs]").onchange = (e) => { d().segments = Math.max(2, Math.min(100, +e.target.value || 4)); saveDevices(); };
    row.querySelector("[data-rev]").onchange = (e) => { d().reverse = e.target.checked; saveDevices(); };
    row.querySelector("select").disabled = d().chain;
    row.querySelector("[data-test]").onclick = () => { api("/api/lights/test", { ip: d().ip }); toast(`Flashing ${d().name}`); };
  });
}

function updateLightsSchedule() {
  const li = cfg.lights, s = state.status.lights_schedule, el = $("lightsSchedInfo");
  if (!li.schedule) el.textContent = "Lights stay on all the time (while syncing is on).";
  else if (li.lat == null) el.innerHTML = "<b>Set your town</b> so the Pi knows when sunset is. Until then the lights stay on.";
  else if (s) el.textContent = `${s.on ? "🟢 On now" : "⚫ Off now"} · Tonight: on at ${s.on_at} (sunset ${s.sunset}), off at ${s.off_at}. Location: ${li.place}`;
}

async function lookUpPlace() {
  const q = $("lightsPlace").value.trim();
  const box = $("lightsPlaces");
  box.innerHTML = `<span class="muted small">Looking up “${esc(q)}”…</span>`;
  const r = await api("/api/geocode?q=" + encodeURIComponent(q));
  if (!r.ok) { box.innerHTML = `<span class="muted small">${esc(r.error)}</span>`; return; }
  if (!r.places.length) { box.innerHTML = `<span class="muted small">No places found. Try "City, State".</span>`; return; }
  box.innerHTML = r.places.map((p, i) => `<button class="chip" data-i="${i}">${esc(p.name)}</button>`).join("");
  box.querySelectorAll("[data-i]").forEach((b) => (b.onclick = () => {
    const p = r.places[+b.dataset.i];
    save({ lights: { lat: p.lat, lon: p.lon, place: p.name } });
    $("lightsPlace").value = p.name;
    box.innerHTML = "";
    toast(`Sunset times for ${p.name}`);
    setTimeout(refresh, 600);
  }));
}

async function findLights() {
  toast("Looking for Govee lights…");
  const r = await api("/api/lights/find", {});
  if (!r.ok) return toast(r.error);
  cfg.lights = r.lights;
  renderLights();
  toast(r.found ? `Found ${r.found} light(s)` : "No lights answered. Is LAN Control on in the Govee app?");
}

// ---------- Background atmosphere ----------

const ATMOS_ICONS = [["grave", "🪦"], ["cemet", "🪦"], ["sewer", "🐀"], ["asylum", "🏚️"], ["ward", "🏚️"],
  ["thunder", "⛈️"], ["storm", "⛈️"], ["rain", "🌧️"], ["forest", "🌲"], ["lab", "⚗️"], ["witch", "🧙"],
  ["cauldron", "🧙"], ["wind", "🌬️"], ["swamp", "🐸"], ["crypt", "⚰️"], ["church", "⛪"]];
const atmosIcon = (name) => (ATMOS_ICONS.find(([k]) => name.toLowerCase().includes(k)) || [, "👻"])[1];
let atmosKey = "";

function renderAtmos(force) {
  const key = state.ambience.map((a) => a.name).join("|");
  if (!force && key === atmosKey) return;
  atmosKey = key;
  const box = $("atmos");
  if (!state.ambience.length) {
    box.innerHTML = `<p class="muted">No background loops yet. Add one below.</p>`;
    return;
  }
  box.innerHTML = state.ambience.map((a) =>
    `<button class="atmos-tile" data-track="${esc(a.name)}"><span class="ico">${atmosIcon(a.name)}</span>${esc(a.label)}<span class="del" data-del="${esc(a.name)}" title="Remove">🗑</span><span class="pv preview-btn" data-preview="ambience/${esc(a.name)}" title="Preview on this device (not in the yard)">🎧</span></button>`).join("");
  box.querySelectorAll(".atmos-tile").forEach((b) => (b.onclick = (e) => {
    if (e.target.dataset.del) return removeAtmos(e.target.dataset.del);
    if (e.target.dataset.preview) return preview(e.target.dataset.preview);
    const playingThis = cfg.ambience.on && cfg.ambience.track === b.dataset.track;
    save({ ambience: playingThis ? { on: false } : { on: true, track: b.dataset.track } });
    toast(playingThis ? "Atmosphere fading out" : `Atmosphere: ${b.textContent.replace("🗑", "").trim()}`);
    updateAtmos();
  }));
  updateAtmos();
  markPreview();
}

async function removeAtmos(name) {
  if (!confirm(`Remove the background "${name}" from the Pi?`)) return;
  await api("/api/sounds/" + encodeURIComponent(name) + "?kind=ambience", undefined, "DELETE");
  refresh();
}

function renderAtmosSettings() {
  setSlider("atmosVol", cfg.ambience.volume, true);
  $("atmosHours").checked = cfg.ambience.active_hours_only;
  const wrap = $("atmosSpots");
  wrap.innerHTML = "";
  cfg.placements.forEach((p) => {
    const on = cfg.ambience.placements.includes(p.id);
    const c = document.createElement("button");
    c.className = "chip" + (on ? " on" : "");
    c.textContent = p.name + (p.enabled ? "" : " (off)");
    c.onclick = () => {
      const list = on ? cfg.ambience.placements.filter((x) => x !== p.id) : [...cfg.ambience.placements, p.id];
      save({ ambience: { placements: list } });
      renderAtmosSettings();
    };
    wrap.appendChild(c);
  });
}

function updateAtmos() {
  const st = state.status.ambience || {};
  document.querySelectorAll(".atmos-tile").forEach((b) => {
    const chosen = cfg.ambience.on && cfg.ambience.track === b.dataset.track;
    b.classList.toggle("on", chosen && st.playing === b.dataset.track);
    b.classList.toggle("waiting", chosen && !st.want && st.playing !== b.dataset.track);
  });
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
  options($("denonInput"), [["", "–"], ...inputs], "");
  options($("denonMode"), [["", "–"], ...modes], "");
  $("denonMax").value = dn.max_db; $("denonMaxOut").textContent = dB(dn.max_db);
  $("denonVol").max = dn.max_db;
  $("denonHost").value = dn.host;
}

async function denon(action, value) {
  if (["on", "find"].includes(action)) toast(action === "find" ? "Looking for the Denon…" : "Talking to the Denon…");
  const r = await api("/api/denon", { action, value });
  if (!r.ok) toast(r.error);
  else if (action === "find") { toast(`Found the Denon at ${r.denon.host}`); refreshCfg(); }
  state.status.denon = r.denon;
  updateDenon();
}

async function refreshCfg() {
  cfg.denon = (await api("/api/config", {})).denon;
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
  let playing = st.now_playing ? st.now_playing.spots : [];
  if (st.now_playing && st.now_playing.progress != null && playing.length > 1) {
    playing = [playing[Math.round(st.now_playing.progress * (playing.length - 1))]];
  }
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
    const amb = st.ambience && st.ambience.playing;
    const ambLabel = amb ? (state.ambience.find((a) => a.name === amb)?.label || amb) : "";
    now.textContent = radioOn ? `🎵 Radio: ${st.radio.name}` : amb ? `${atmosIcon(amb)} Atmosphere: ${ambLabel}` : "Quiet… for now.";
    now.classList.toggle("on", radioOn || !!amb);
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
    renderYard(); renderPlacements(); renderTiming(); renderRadioSettings(); renderMatrix(true); renderDenonSettings(); renderAtmos(true); renderAtmosSettings(); renderSweep(); renderSweepOrder(); renderLights(); renderRing();
  } else {
    const before = soundsKey;
    renderMatrix(false);
    if (soundsKey !== before) { renderSweep(); renderRing(); }
    renderAtmos(false);
  }
  updateAtmos();
  updateLive();
  updateDenon();
  updateLightsSchedule();
  updateRing();
}

// ---------- Wire up static controls ----------

function wire() {
  $("scareBtn").onclick = async () => {
    const r = await api("/api/scare", {});
    toast(r.started ? "Boo!" : "Already playing. Hang on…");
    setTimeout(refresh, 150);
  };
  $("sweepLtr").onclick = () => doSweep("ltr");
  $("sweepRtl").onclick = () => doSweep("rtl");
  $("sweepSecs").oninput = () => { setSweepSecs(+$("sweepSecs").value); save({ sweep_seconds: +$("sweepSecs").value }); };
  $("sweepSound").onchange = () => save({ sweep_sound: $("sweepSound").value });
  $("ringOn").onchange = () => save({ ring: { enabled: $("ringOn").checked } });
  $("ringMotionOn").onchange = () => save({ ring: { motion_on: $("ringMotionOn").checked } });
  $("ringDingOn").onchange = () => save({ ring: { ding_on: $("ringDingOn").checked } });
  $("ringMotionSound").onchange = () => save({ ring: { motion_sound: $("ringMotionSound").value } });
  $("ringDingSound").onchange = () => save({ ring: { ding_sound: $("ringDingSound").value } });
  $("ringSpot").onchange = () => save({ ring: { placement: $("ringSpot").value } });
  $("ringCooldown").onchange = () => save({ ring: { cooldown: +$("ringCooldown").value } });
  $("ringHours").onchange = () => save({ ring: { active_hours_only: $("ringHours").checked } });
  document.querySelectorAll("[data-ring-test]").forEach((b) => (b.onclick = async () => {
    await api("/api/ring/test", { kind: b.dataset.ringTest });
    toast(b.dataset.ringTest === "ding" ? "🔔 Doorbell test" : "🚶 Motion test");
    setTimeout(refresh, 200);
  }));
  $("lightsFind").onclick = findLights;
  $("lightsOn").onchange = () => save({ lights: { enabled: $("lightsOn").checked } });
  $("lightsIdleColor").oninput = () => save({ lights: { idle_color: $("lightsIdleColor").value } });
  $("lightsIdle").oninput = () => { $("lightsIdleOut").textContent = $("lightsIdle").value + "%"; save({ lights: { idle_brightness: +$("lightsIdle").value } }); };
  $("lightsFlash").oninput = () => { $("lightsFlashOut").textContent = $("lightsFlash").value + "%"; save({ lights: { flash_brightness: +$("lightsFlash").value } }); };
  $("lightsFlicker").onchange = () => save({ lights: { flicker: $("lightsFlicker").checked } });
  $("lightsSched").onchange = () => save({ lights: { schedule: $("lightsSched").checked } });
  $("lightsBefore").onchange = () => save({ lights: { minutes_before: +$("lightsBefore").value } });
  $("lightsOff").onchange = () => save({ lights: { off_time: $("lightsOff").value } });
  $("lightsPlaceBtn").onclick = lookUpPlace;
  $("lightsPlace").onkeydown = (e) => { if (e.key === "Enter") lookUpPlace(); };
  $("lightsRipple").oninput = () => { setSlider("lightsRipple", +$("lightsRipple").value, true); save({ lights: { ripple: +$("lightsRipple").value } }); };
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
  $("denonMax").oninput = () => {
    const m = +$("denonMax").value;
    $("denonMaxOut").textContent = dB(m);
    $("denonVol").max = m;
    save({ denon: { max_db: m } });
  };
  $("denonHost").onchange = () => save({ denon: { host: $("denonHost").value.trim() } });

  $("atmosVol").oninput = () => { setSlider("atmosVol", +$("atmosVol").value, true); save({ ambience: { volume: +$("atmosVol").value } }); };
  $("atmosHours").onchange = () => save({ ambience: { active_hours_only: $("atmosHours").checked } });
  $("atmosFile").onchange = async () => {
    const files = $("atmosFile").files;
    if (!files.length) return;
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    toast(`Uploading ${files.length} background(s)…`);
    const r = await (await fetch("/api/sounds?kind=ambience", { method: "POST", body: fd })).json();
    toast(r.saved.length ? `Added ${r.saved.length} background(s)` : "No audio files in that upload");
    $("atmosFile").value = "";
    refresh();
  };

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

// Send any unsaved change right away if the page is closed or hidden
window.addEventListener("pagehide", () => {
  if (!Object.keys(pending).length) return;
  clearTimeout(saveTimer);
  navigator.sendBeacon("/api/config", new Blob([JSON.stringify(pending)], { type: "application/json" }));
  pending = {};
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

wire();
refresh().then(searchRadio);
setInterval(refresh, 1500);
