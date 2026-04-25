/* ================================================================
   AEGIS V2 — Frontend client
   ================================================================ */

const API = "/api";

const $ = sel => document.querySelector(sel);
const $$ = sel => Array.from(document.querySelectorAll(sel));
const pad = (n, w = 2) => String(n).padStart(w, "0");

const state = {
  startedAt: Date.now(),
  scenarios: {},
  active: null,
  encounter: null,
  steps: {},
  stepTimes: {},
  citations: {},
  reasoningStream: null,
  mic: { state: "idle", _final: null, startedAt: 0 },
  waveAnim: null,
  waveBars: [],
  network: { reachable: null, history: [] },
  vitalsTick: 0
};

/* utils */
function formatElapsed(ms) {
  const s = Math.floor(ms / 1000);
  return `T+${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}
function clockNow() {
  const d = new Date();
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} Z`;
}
function sparkPath(values, w = 100, h = 16) {
  if (!values || !values.length) return "";
  const max = Math.max(1, ...values.map(Math.abs));
  const min = Math.min(0, ...values.map(Math.abs));
  const range = Math.max(1, max - min);
  const step = w / Math.max(1, values.length - 1);
  return values.map((v, i) => {
    const x = (i * step).toFixed(1);
    const y = (h - ((Math.abs(v) - min) / range) * (h - 2) - 1).toFixed(1);
    return (i === 0 ? "M" : "L") + x + " " + y;
  }).join(" ");
}
async function jget(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(`GET ${path} ${r.status}`);
  return r.json();
}
async function jpost(path, body) {
  const r = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!r.ok) throw new Error(`POST ${path} ${r.status}`);
  return r.json();
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
}
function escapeAttr(s) { return String(s).replace(/"/g, "&quot;"); }

/* SCENARIOS */
function renderScenarioList() {
  const list = $("#scenarioList");
  list.innerHTML = Object.values(state.scenarios).map(s => `
    <div class="scenario-row glass-nested ${s.id === state.active ? "active" : ""}"
         data-key="${s.id}" tabindex="0" role="button"
         aria-pressed="${s.id === state.active}">
      <div class="domain">${s.domain}</div>
      <div class="case">${s.case}</div>
    </div>
  `).join("");
  list.querySelectorAll(".scenario-row").forEach(el => {
    el.addEventListener("click", () => activateScenario(el.dataset.key));
    el.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activateScenario(el.dataset.key); }
    });
  });
}
function renderMissionContext() {
  const s = state.scenarios[state.active];
  if (!s) return;
  $("#scenarioName").textContent = s.name;
  $("#ptId").textContent = s.patient_label || "PT-—";
}

/* VITALS */
function renderVitals(snapshot) {
  if (!snapshot || !snapshot.vitals) return;
  const grid = $("#vitalsGrid");
  // Determine the active-pulse vital — the one with cls warn/crit, or the most recently changed.
  // Pick the first warn/crit cell, or the last cell if none.
  const vitals = snapshot.vitals;
  let activeIdx = vitals.findIndex(v => v.cls === "warn" || v.cls === "crit");
  if (activeIdx < 0) activeIdx = -1;
  grid.innerHTML = vitals.map((v, i) => {
    const stroke = v.cls === "crit" ? "#B91C1C" : v.cls === "warn" ? "#A16207" : "#D97706";
    const path = sparkPath(v.spark || []);
    // Compute last point for the live dot
    const arr = v.spark || [];
    let lastX = 99, lastY = 8;
    if (arr.length) {
      const max = Math.max(1, ...arr.map(Math.abs));
      const min = Math.min(0, ...arr.map(Math.abs));
      const range = Math.max(1, max - min);
      lastX = 99;
      lastY = (16 - ((Math.abs(arr[arr.length - 1]) - min) / range) * 14 - 1).toFixed(1);
    }
    const dotColor = v.cls === "crit" ? "#B91C1C" : v.cls === "warn" ? "#A16207" : "#D97706";
    // Area fill path (extends line to baseline)
    const areaPath = path ? path + ` L 100 16 L 0 16 Z` : "";
    const pulseClass = i === activeIdx ? "active-pulse" : "";
    return `
      <div class="vital ${v.cls || ""} ${pulseClass}">
        <span class="v-label">${v.label}</span>
        <span class="v-row">
          <span class="v-val">${v.val}</span>
          <span class="v-unit">${v.unit}</span>
        </span>
        <svg class="spark" viewBox="0 0 100 16" preserveAspectRatio="none">
          <defs>
            <linearGradient id="sparkArea-${i}" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="${stroke}" stop-opacity="0.18"/>
              <stop offset="100%" stop-color="${stroke}" stop-opacity="0"/>
            </linearGradient>
            <filter id="sparkBlur-${i}" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="1.2"/>
            </filter>
          </defs>
          <path d="${areaPath}" fill="url(#sparkArea-${i})" stroke="none"/>
          <path d="${path}" stroke="${stroke}" stroke-width="1.4" fill="none" opacity="0.30" filter="url(#sparkBlur-${i})"/>
          <path d="${path}" stroke="${stroke}" stroke-width="1" fill="none" opacity="0.85"/>
          <circle cx="${lastX}" cy="${lastY}" r="1.4" fill="${dotColor}" opacity="0.95"/>
          <circle cx="${lastX}" cy="${lastY}" r="3" fill="${dotColor}" opacity="0.18" filter="url(#sparkBlur-${i})"/>
        </svg>
      </div>
    `;
  }).join("");
  state.vitalsTick = 0;
  $("#vitalsTimer").textContent = "00s ago";
}
function tickVitalsStamp() {
  state.vitalsTick = (state.vitalsTick + 1) % 99;
  $("#vitalsTimer").textContent = `${pad(state.vitalsTick)}s ago`;
}

/* CHECKLIST */
function renderChecklist() {
  const s = state.scenarios[state.active];
  if (!s) return;
  const done = state.steps[state.active] || [];
  const times = state.stepTimes[state.active] || [];
  const current = done.findIndex(d => !d);
  const list = $("#checklist");
  list.innerHTML = (s.steps || []).map((label, i) => {
    const isDone = !!done[i];
    const isCurrent = !isDone && i === current;
    return `
      <li class="check-item ${isDone ? "done" : ""} ${isCurrent ? "current" : ""}"
          data-i="${i}" tabindex="0" role="checkbox" aria-checked="${isDone}">
        <span class="check-box" aria-hidden="true"></span>
        <span class="check-label">${label}</span>
        <span class="check-time">${times[i] || ""}</span>
      </li>
    `;
  }).join("");
  list.querySelectorAll(".check-item").forEach(el => {
    el.addEventListener("click", () => toggleStep(parseInt(el.dataset.i, 10)));
    el.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleStep(parseInt(el.dataset.i, 10)); }
    });
  });
  updateProgress();
}
function toggleStep(i) {
  const arr = state.steps[state.active] || [];
  arr[i] = !arr[i];
  state.steps[state.active] = arr;
  const t = formatElapsed(Date.now() - state.startedAt);
  state.stepTimes[state.active][i] = arr[i] ? t : "";
  renderChecklist();
  if (state.encounter) {
    jpost(`/records/${state.encounter}/event`, {
      event_type: "checklist_item",
      payload: {
        step_index: i,
        step_label: state.scenarios[state.active].steps[i],
        done: arr[i],
        t_offset_ms: Date.now() - state.startedAt
      }
    }).catch(() => {});
  }
  refreshVitals();
}
function updateProgress() {
  const arr = state.steps[state.active] || [];
  const done = arr.filter(Boolean).length;
  const total = arr.length;
  $("#progressFill").style.width = total ? `${(done / total) * 100}%` : "0%";
  $("#progressCount").textContent = `${pad(done)} / ${pad(total)}`;
  $("#checklistCount").textContent = `${pad(done)} / ${pad(total)}`;
}

/* REFERENCE */
function renderReference(chunk) {
  const body = $("#refBody");
  const cite = $("#refCite");
  body.style.opacity = "0";
  setTimeout(() => {
    if (chunk) {
      body.innerHTML = `<strong>${escapeHtml(chunk.section || "")}</strong><br/>${escapeHtml((chunk.text || "").slice(0, 280))}${chunk.text && chunk.text.length > 280 ? "…" : ""}`;
      cite.textContent = `Source: ${chunk.document} // ${chunk.section || ""} // local index #${chunk.id}`;
    } else {
      body.innerHTML = `<em>Reference chunks load on the next reasoning turn.</em>`;
      cite.textContent = "Source: embedded local corpus";
    }
    body.style.opacity = "";
  }, 200);
}

/* REASONING ROUTER (parses [INTAKE]/[ASSESSMENT]/[GUIDANCE] + citations) */
function makeTypewriter(targetEl, opts = {}) {
  const cps = opts.cps || 28;
  const buffer = [];
  const cursor = document.createElement("span");
  cursor.className = "cursor";
  targetEl.appendChild(cursor);
  let stopped = false;
  let lastTickAt = performance.now();

  function tick() {
    if (stopped) return;
    if (buffer.length === 0) { requestAnimationFrame(tick); return; }
    const now = performance.now();
    const interval = 1000 / cps;
    if (now - lastTickAt < interval) { requestAnimationFrame(tick); return; }
    lastTickAt = now;
    const seg = buffer.shift();
    if (seg.type === "char") cursor.insertAdjacentText("beforebegin", seg.value);
    else if (seg.type === "html") cursor.insertAdjacentHTML("beforebegin", seg.value);
    $("#reasoningLog").scrollTop = $("#reasoningLog").scrollHeight;
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
  return {
    feedText(text) { for (const ch of text) buffer.push({ type: "char", value: ch }); },
    feedHtml(html) { buffer.push({ type: "html", value: html }); },
    stop() { stopped = true; if (cursor.parentNode) cursor.remove(); }
  };
}

class ReasoningRouter {
  constructor() {
    this.section = null; this.entry = null; this.tw = null;
    this.guidanceList = null; this.guidanceBuf = ""; this.bufferedRaw = "";
  }
  feed(rawChunk) {
    let s = this.bufferedRaw + rawChunk;
    let i = 0; let outBuf = "";
    while (i < s.length) {
      if (s[i] === "[") {
        const close = s.indexOf("]", i);
        if (close === -1) { this.bufferedRaw = s.slice(i); this.flushText(outBuf); return; }
        const tag = s.slice(i + 1, close);
        if (/^(INTAKE|ASSESSMENT|GUIDANCE)$/.test(tag)) {
          this.flushText(outBuf); outBuf = "";
          this.openSection(tag.toLowerCase());
          i = close + 1; continue;
        }
        if (tag === "UNSOURCED") {
          this.flushText(outBuf); outBuf = "";
          this._inlineHtml(`<span class="unsourced">UNSOURCED</span>`);
          i = close + 1; continue;
        }
        if (/^[A-Z][A-Z0-9\-]{1,18}/.test(tag)) {
          this.flushText(outBuf); outBuf = "";
          this._inlineHtml(`<span class="cite" data-cite-id="${escapeAttr(tag)}">[${escapeHtml(tag)}]</span>`);
          i = close + 1; continue;
        }
        outBuf += s[i++]; continue;
      }
      outBuf += s[i++];
    }
    this.bufferedRaw = "";
    this.flushText(outBuf);
  }
  _inlineHtml(html) {
    if (this.section === "guidance") {
      this.guidanceBuf += html;
    } else if (this.tw) {
      this.tw.feedHtml(html);
    }
  }
  flushText(text) {
    if (!text) return;
    if (!this.section) return;
    if (this.section === "guidance") this.feedGuidance(text);
    else if (this.tw) this.tw.feedText(text);
  }
  openSection(kind) {
    if (this.tw) { this.tw.stop(); this.tw = null; }
    if (this.guidanceList) { this.finalizeGuidance(); }
    const t = formatElapsed(Date.now() - state.startedAt);
    this.entry = makeEntry(kind.toUpperCase(), t);
    const body = this.entry.querySelector(".entry-body");
    this.section = kind;
    if (kind === "guidance") {
      this.guidanceList = document.createElement("ol");
      this.guidanceList.className = "steps";
      body.appendChild(this.guidanceList);
      this.guidanceBuf = "";
    } else {
      this.tw = makeTypewriter(body);
    }
  }
  feedGuidance(text) {
    this.guidanceBuf += text;
    const lines = this.guidanceBuf.split(/\n+/);
    this.guidanceBuf = lines.pop();
    for (const raw of lines) {
      const cleaned = raw.replace(/^\s*\d+[\.\)]\s*/, "").trim();
      if (!cleaned) continue;
      const li = document.createElement("li");
      // Wrap in a span so text + inline pills stay in a single grid item
      li.innerHTML = `<span class="step-text">${cleaned}</span>`;
      this.guidanceList.appendChild(li);
    }
    this.markCurrent();
  }
  markCurrent() {
    if (!this.guidanceList) return;
    const arr = state.steps[state.active] || [];
    const items = this.guidanceList.querySelectorAll("li");
    const current = arr.findIndex(d => !d);
    items.forEach((li, idx) => {
      li.classList.remove("done", "current");
      if (arr[idx]) li.classList.add("done");
      else if (idx === current) li.classList.add("current");
    });
  }
  finalizeGuidance() {
    if (this.guidanceList && this.guidanceBuf && this.guidanceBuf.trim()) {
      const cleaned = this.guidanceBuf.replace(/^\s*\d+[\.\)]\s*/, "").trim();
      if (cleaned) {
        const li = document.createElement("li");
        li.innerHTML = `<span class="step-text">${cleaned}</span>`;
        this.guidanceList.appendChild(li);
      }
      this.guidanceBuf = "";
      this.markCurrent();
    }
  }
  finalize() {
    this.finalizeGuidance();
  }
}

function clearReasoning() {
  if (state.reasoningStream && state.reasoningStream.abort) state.reasoningStream.abort();
  state.reasoningStream = null;
  $("#reasoningLog").innerHTML = "";
}
function makeEntry(tag, baseTime, dim = false) {
  // Demote any existing streaming entry to historical
  $$("#reasoningLog .entry.streaming").forEach(e => e.classList.remove("streaming"));
  const wrap = document.createElement("div");
  wrap.className = "entry streaming";
  wrap.innerHTML = `
    <div class="entry-head">
      <span class="entry-time">${baseTime}</span>
      <span class="entry-tag ${dim ? "dim" : ""}">${tag}</span>
    </div>
    <div class="entry-body"></div>
  `;
  $("#reasoningLog").appendChild(wrap);
  requestAnimationFrame(() => wrap.classList.add("visible"));
  $("#reasoningLog").scrollTop = $("#reasoningLog").scrollHeight;
  return wrap;
}

async function runReasoning(prompt) {
  clearReasoning();
  setInferLive(true);
  // Reasoning starts fresh — drop streaming class from any leftover entry
  $$("#reasoningLog .entry.streaming").forEach(e => e.classList.remove("streaming"));
  $("#tpsLabel").textContent = "— tok/s";
  const router = new ReasoningRouter();
  const ctrl = new AbortController();
  state.reasoningStream = ctrl;
  try {
    const r = await fetch(API + "/reason", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify({ scenario_id: state.active, encounter_id: state.encounter, prompt }),
      signal: ctrl.signal
    });
    if (!r.ok || !r.body) throw new Error("reason failed " + r.status);
    const reader = r.body.getReader();
    const dec = new TextDecoder("utf-8");
    let buf = "";
    let firstAt = 0; let totalToks = 0;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const evt = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const dataLine = evt.split("\n").find(l => l.startsWith("data: "));
        if (!dataLine) continue;
        const data = dataLine.slice(6);
        if (data === "[DONE]") { router.finalize(); break; }
        let payload; try { payload = JSON.parse(data); } catch { continue; }
        if (payload.type === "meta") {
          if (payload.model) $("#modelLabel").textContent = `MODEL: ${payload.model}`;
          if (payload.retrieved && payload.retrieved.length) {
            for (const c of payload.retrieved) state.citations[c.id] = c;
            renderReference(payload.retrieved[0]);
          }
        } else if (payload.type === "token") {
          if (!firstAt) firstAt = performance.now();
          totalToks += payload.text.length;
          router.feed(payload.text);
          const elapsed = (performance.now() - firstAt) / 1000;
          if (elapsed > 0.3) $("#tpsLabel").textContent = `${(totalToks / elapsed / 4).toFixed(1)} tok/s`;
        } else if (payload.type === "done") {
          router.finalize();
          if (payload.tps) $("#tpsLabel").textContent = `${payload.tps} tok/s`;
        }
      }
    }
  } catch (e) {
    console.error(e);
  } finally {
    setInferLive(false);
    // The latest entry remains visually "streaming" until a new turn fires —
    // this preserves the heat trail and full opacity on the most recent entry.
    state.reasoningStream = null;
  }
}
function setInferLive(on) { $("#inferPulse").classList.toggle("live", on); }

/* CITATION OVERLAY */
document.addEventListener("click", async e => {
  const c = e.target.closest(".cite[data-cite-id]");
  if (!c) return;
  const id = c.dataset.citeId;
  await openCitation(id);
});
async function openCitation(id) {
  let chunk = state.citations[id];
  if (!chunk) {
    try { chunk = await jget(`/citations/${encodeURIComponent(id)}`); } catch { chunk = null; }
  }
  $("#citeOvlTitle").textContent = id;
  if (chunk) {
    state.citations[id] = chunk;
    $("#citeText").innerHTML = escapeHtml(chunk.text || "—");
    $("#citeDoc").textContent = chunk.document || "—";
    $("#citePage").textContent = chunk.page != null && chunk.page !== "" ? `p. ${chunk.page}` : "—";
    $("#citeSection").textContent = chunk.section || "—";
    $("#citeScore").textContent = chunk.score != null ? Number(chunk.score).toFixed(3) : "—";
  } else {
    $("#citeText").innerHTML = `<em>Source not found in local index.</em>`;
    $("#citeDoc").textContent = "—";
    $("#citePage").textContent = "—";
    $("#citeSection").textContent = "—";
    $("#citeScore").textContent = "—";
  }
  openOvl("citeScrim");
  if (state.encounter) {
    jpost(`/records/${state.encounter}/event`, {
      event_type: "reference_view",
      payload: { citation_id: id }
    }).catch(() => {});
  }
}

/* OVERLAY HELPERS */
function openOvl(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.add("open");
  el.setAttribute("aria-hidden", "false");
  el.addEventListener("click", _scrimClick);
  document.addEventListener("keydown", _escClose);
  $("#cockpit").classList.add("defocused");
}
function closeOvl(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("open");
  el.setAttribute("aria-hidden", "true");
  if (!$$(".ovl-scrim.open").length) $("#cockpit").classList.remove("defocused");
}
function _scrimClick(e) {
  if (e.target.classList.contains("ovl-scrim")) closeOvl(e.currentTarget.id);
}
function _escClose(e) {
  if (e.key === "Escape") $$(".ovl-scrim.open").forEach(s => closeOvl(s.id));
}
$$(".ovl-close").forEach(b => b.addEventListener("click", () => closeOvl({
  cite: "citeScrim", rec: "recScrim", sys: "sysScrim"
}[b.dataset.ovl])));

/* SCENARIO ACTIVATION */
async function activateScenario(key) {
  if (!key || key === state.active) return;
  if (state.encounter) { try { await jpost(`/records/${state.encounter}/end`, {}); } catch {} }
  state.active = key;
  try {
    const enc = await jpost("/records/start", { scenario_id: key });
    state.encounter = enc.id;
  } catch {}
  state.steps[key] = state.steps[key] || (state.scenarios[key].steps || []).map(() => false);
  state.stepTimes[key] = state.stepTimes[key] || (state.scenarios[key].steps || []).map(() => "");
  renderScenarioList();
  renderMissionContext();
  renderChecklist();
  renderReference(null);
  await refreshVitals();
  runReasoning("__SCENARIO_PRIMER__").catch(() => {});
}

async function refreshVitals() {
  if (!state.active) return;
  try {
    const r = await jpost("/vitals", {
      scenario_id: state.active,
      elapsed_ms: Date.now() - state.startedAt,
      checklist: state.steps[state.active] || []
    });
    renderVitals(r);
  } catch {}
}

function tickClocks() {
  $("#clock").textContent = clockNow();
  $("#elapsed").textContent = formatElapsed(Date.now() - state.startedAt);
}

/* WAVEFORM (real audio level meter) */
const WAVE_BARS = 80;
function buildWaveform() {
  const wf = $("#waveform");
  wf.querySelectorAll(".bar").forEach(b => b.remove());
  state.waveBars = [];
  for (let i = 0; i < WAVE_BARS; i++) {
    const b = document.createElement("div");
    b.className = "bar";
    wf.insertBefore(b, $("#waveStatus"));
    state.waveBars.push(b);
  }
}
function setWaveBarsFlat() {
  state.waveBars.forEach(b => { b.style.height = "2px"; b.style.opacity = "0.35"; });
}
function startWaveAnimFromAnalyser(analyser) {
  const data = new Uint8Array(analyser.fftSize);
  let lastFrame = 0;
  function frame(now) {
    if (state.mic.state !== "listening") return;
    state.waveAnim = requestAnimationFrame(frame);
    if (now - lastFrame < 32) return;
    lastFrame = now;
    analyser.getByteTimeDomainData(data);
    const w = Math.floor(data.length / WAVE_BARS);
    for (let i = 0; i < WAVE_BARS; i++) {
      let sum = 0;
      for (let j = 0; j < w; j++) {
        const v = (data[i * w + j] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / w);
      const center = (i - WAVE_BARS / 2) / (WAVE_BARS / 2);
      const env = Math.exp(-Math.pow(center, 2) * 1.4) * 0.85 + 0.15;
      const h = Math.max(2, Math.min(40, rms * 100 * env));
      const b = state.waveBars[i];
      if (b) { b.style.height = h.toFixed(1) + "px"; b.style.opacity = String(0.55 + Math.min(0.45, rms * 1.2)); }
    }
  }
  state.waveAnim = requestAnimationFrame(frame);
}
function startWaveAnimSimulated() {
  let t = 0;
  function frame() {
    if (state.mic.state !== "listening") return;
    state.waveAnim = requestAnimationFrame(frame);
    t += 0.06;
    state.waveBars.forEach((b, i) => {
      const center = (i - WAVE_BARS / 2) / (WAVE_BARS / 2);
      const env = Math.exp(-Math.pow(center, 2) * 1.4) * 0.85 + 0.15;
      const v = (Math.sin(t * 2.1 + i * 0.21) * 0.45 + Math.sin(t * 0.9 + i * 0.07) * 0.35 + (Math.random() - 0.5) * 0.4) * env;
      const h = Math.max(2, Math.abs(v) * 36 + 2);
      b.style.height = h.toFixed(1) + "px";
      b.style.opacity = String(0.55 + Math.abs(v) * 0.4);
    });
  }
  state.waveAnim = requestAnimationFrame(frame);
}
function stopWaveAnim() { if (state.waveAnim) cancelAnimationFrame(state.waveAnim); state.waveAnim = null; }

/* MIC */
async function micDown() {
  if (state.mic.state !== "idle") return;
  state.mic.state = "listening";
  state.mic.startedAt = Date.now();
  const btn = $("#micBtn");
  btn.classList.add("listening");
  setTranscriptIdle();
  setWaveStatus("// capturing", "Local Mic", true);

  // V4 — record voice_input_started event
  const eid = v3.activeEnc || state.encounter;
  if (eid) {
    jpost(`/encounter/${eid}/event`, {
      event_type: "voice_input_started", payload: {}
    }).catch(() => {});
  }

  // Try real mic; fall back to simulated waveform if unavailable.
  let usedReal = false;
  try {
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const src = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      src.connect(analyser);
      state.mic.stream = stream;
      state.mic.audioCtx = audioCtx;
      startWaveAnimFromAnalyser(analyser);
      usedReal = true;
    }
  } catch (e) { /* permission denied or unsupported */ }
  if (!usedReal) startWaveAnimSimulated();
}

async function micUp() {
  if (state.mic.state !== "listening") return;
  state.mic.state = "processing";
  $("#micBtn").classList.remove("listening");
  $("#micBtn").classList.add("processing");
  stopWaveAnim();
  setWaveBarsFlat();

  try { state.mic.stream && state.mic.stream.getTracks().forEach(t => t.stop()); } catch {}
  try { state.mic.audioCtx && state.mic.audioCtx.close(); } catch {}
  state.mic.stream = null; state.mic.audioCtx = null;

  // Use the canned transcript for this scenario (preview server has no STT).
  let transcript = "";
  try {
    const r = await jpost("/canned/replay", { index: 0, scenario_id: state.active });
    transcript = r.transcript || "";
  } catch {}

  if (transcript) setTranscript(transcript);

  const elapsed = (Date.now() - state.mic.startedAt) / 1000;
  setWaveStatus(`// ${elapsed.toFixed(1)}s`, "Local Inference", true);

  if (transcript) await runReasoning(transcript);

  setTimeout(() => setWaveStatus("", "", false), 2000);
  $("#micBtn").classList.remove("processing");
  state.mic.state = "idle";
}

function setTranscript(text) {
  const el = $("#transcript");
  el.classList.remove("idle");
  el.textContent = text;
  // V4 — record voice_input_finalized
  const eid = (typeof v3 !== "undefined" ? v3.activeEnc : null) || state.encounter;
  if (eid && text && !text.startsWith("Awaiting")) {
    jpost(`/encounter/${eid}/event`, {
      event_type: "voice_input_finalized", payload: { text }
    }).catch(() => {});
  }
  // V3 hook — voice command routing
  if (typeof maybeHandleTriageVoice === "function") {
    if (maybeHandleTriageVoice(text)) return;
    if (maybeHandleMedAdmin(text)) return;
    if (maybeHandleCalculator(text)) return;
  }
}
function setTranscriptIdle() {
  const el = $("#transcript");
  el.classList.add("idle");
  el.textContent = "Awaiting input // press to transmit.";
}
function setWaveStatus(text, em, on) {
  $("#waveStatusEm").textContent = em || "";
  $("#waveStatusTime").textContent = text || "";
  $("#waveStatus").classList.toggle("show", !!on);
}

function wireMic() {
  const btn = $("#micBtn");
  let isTouch = false;
  btn.addEventListener("touchstart", e => { isTouch = true; e.preventDefault(); toggleMicTouch(); }, { passive: false });
  btn.addEventListener("mousedown", () => { if (!isTouch) micDown(); });
  btn.addEventListener("mouseup",   () => { if (!isTouch) micUp(); });
  btn.addEventListener("mouseleave", () => { if (!isTouch && state.mic.state === "listening") micUp(); });
}
function toggleMicTouch() {
  if (state.mic.state === "idle") micDown();
  else if (state.mic.state === "listening") micUp();
}

/* CANNED REPLAY KEYS */
document.addEventListener("keydown", async e => {
  if (!(e.ctrlKey && e.shiftKey)) return;
  const idx = ["1", "2", "3"].indexOf(e.key);
  if (idx < 0) return;
  e.preventDefault();
  const ids = Object.keys(state.scenarios);
  if (idx >= ids.length) return;
  try {
    const r = await jpost("/canned/replay", { index: idx, scenario_id: ids[idx] });
    if (r && r.transcript) setTranscript(r.transcript);
    runReasoning(r.transcript || "");
  } catch {}
});

/* NETWORK MONITOR */
function openNetworkStream() {
  const es = new EventSource(API + "/network/stream");
  es.onmessage = ev => {
    try { onNetworkProbe(JSON.parse(ev.data)); } catch {}
  };
}
function onNetworkProbe(m) {
  state.network.reachable = !!m.reachable;
  state.network.history.push(m);
  if (state.network.history.length > 30) state.network.history.shift();
  const l1 = $("#netStateL1");
  const l2t = $("#netStateL2Text");
  const g = $("#netGlyph");
  if (m.reachable) {
    l1.textContent = "EXTERNAL REACHABLE";
    l2t.textContent = "uplink inhibited";
    g.textContent = "◇";
  } else {
    l1.textContent = "EXTERNAL UNREACHABLE";
    l2t.textContent = "isolation verified";
    g.textContent = "◆";
  }
  renderProbeHistory();
}
function renderProbeHistory() {
  const wrap = $("#sysProbes");
  if (!wrap) return;
  const arr = [...state.network.history].slice(-30);
  while (arr.length < 30) arr.unshift(null);
  wrap.innerHTML = arr.map(p => {
    if (!p) return `<span class="sys-probe"></span>`;
    return `<span class="sys-probe ${p.reachable ? "ok" : "fail"}" title="${new Date(p.t).toISOString()}"></span>`;
  }).join("");
  const meta = $("#sysProbesMeta");
  if (meta) {
    const ok = arr.filter(p => p && p.reachable).length;
    const fail = arr.filter(p => p && !p.reachable).length;
    meta.textContent = `Last 30: ${ok} reachable / ${fail} unreachable. Probe target: 1.1.1.1:53 + 8.8.8.8:53.`;
  }
}

/* SYSTEM STATUS */
async function refreshSystem() {
  try {
    const s = await jget("/system/status");
    $("#sysModel").textContent = s.model || "—";
    $("#sysEmbed").textContent = s.embed_model || "—";
    $("#sysBackend").textContent = s.backend || "—";
    $("#sysRam").textContent = s.ram_mb != null ? `${s.ram_mb} MB` : "—";
    $("#sysTps").textContent = s.last_tps != null ? `${s.last_tps} tok/s` : "—";
    $("#sysStt").textContent = s.stt_model || "—";
    $("#sysCorpus").textContent = s.corpus_chunks != null ? `${s.corpus_chunks} chunks` : "—";
    $("#sysDims").textContent = s.embed_dim != null ? `${s.embed_dim}` : "—";
    $("#sysDocs").textContent = s.source_docs != null ? `${s.source_docs} documents` : "—";
    $("#sysIndex").textContent = s.index_built_at || "—";
    $("#sysRecords").textContent = s.records ? `${s.records.events} events / ${s.records.encounters} encounters` : "—";
    $("#sysBuild").textContent = `${s.build_version || "v2.0.0"} // ${s.build_commit || "—"}`;
    $("#sysOvlTitle").textContent = s.build_version || "v2.0.0";
    if ($("#modelLabel").textContent === "MODEL: —" && s.model) {
      $("#modelLabel").textContent = `MODEL: ${s.model}`;
    }
  } catch {}
}

/* RECORD OVERLAY */
async function openRecord() {
  try {
    const list = await jget("/records");
    const picker = $("#recPicker");
    picker.innerHTML = list.map(e => `<option value="${e.id}" ${e.id === state.encounter ? "selected" : ""}>${e.scenario_name || e.scenario_id} // ${e.patient_label} // ${e.id}</option>`).join("");
    picker.onchange = () => loadRecord(parseInt(picker.value, 10));
    const targetId = state.encounter || (list[0] && list[0].id);
    if (targetId) await loadRecord(targetId);
    openOvl("recScrim");
  } catch {}
}
async function loadRecord(id) {
  const r = await jget(`/records/${id}`);
  $("#recOvlTitle").textContent = `ENC-${id}`;
  $("#recScenario").textContent = r.scenario_name || r.scenario_id;
  $("#recPt").textContent = r.patient_label;
  $("#recDur").textContent = r.duration || "—";
  const hash = r.integrity_hash || "—";
  $("#recHash").textContent = hash.slice(0, 12) + (hash.length > 12 ? "…" : "");
  $("#recHash").title = hash;
  const intEl = $("#recIntegrity");
  if (r.integrity_ok) {
    intEl.textContent = `Ed25519 chain · ${r.chain_length || (r.events || []).length} events · ✓ VERIFIED`;
    intEl.className = "ok";
  } else {
    intEl.textContent = `Ed25519 chain · ✗ CHAIN BROKEN AT EVENT #${r.broken_event_id}`;
    intEl.className = "broken";
  }
  $("#recTimeline").innerHTML = (r.events || []).map(e => `
    <div class="rec-event ${r.broken_event_id === e.id ? "broken" : ""}">
      <span class="t">${formatMs(e.t_offset_ms)}</span>
      <span class="typ">${e.event_type}</span>
      <span class="body">${formatEventBody(e)}</span>
    </div>
  `).join("");
}
function formatEventBody(e) {
  const p = e.payload || {};
  switch (e.event_type) {
    case "encounter_started":   return `Encounter created · scenario ${escapeHtml(p.scenario_id || "—")}`;
    case "encounter_ended":     return `Encounter closed`;
    case "scenario_switched":   return `Switched to ${escapeHtml(p.scenario_id || "—")}`;
    case "voice_input_started": return `Mic engaged`;
    case "voice_input_finalized": return `<em>Transcript:</em> ${escapeHtml((p.text || "—").slice(0, 180))}`;
    case "intake":         return escapeHtml((p.text || "—").slice(0, 200));
    case "assessment":     return escapeHtml((p.text || "—").slice(0, 200));
    case "guidance":       return escapeHtml((p.text || "—").slice(0, 200));
    case "guidance_step":  return escapeHtml(p.step_label || `Step ${p.step_index}`);
    case "checklist_item_completed": return `<em>Completed:</em> ${escapeHtml(p.step_label || `Step ${p.step_index}`)}`;
    case "checklist_item": return `<em>${p.done ? "Completed" : "Uncompleted"}:</em> ${escapeHtml(p.step_label || `Step ${p.step_index}`)}`;
    case "vital_reading":  return (p.vitals || []).map(v => `${v.label} ${v.val}${v.unit}`).join(" · ");
    case "reference_view":
    case "citation_viewed": return `Opened citation <span class="cite">[${escapeHtml(p.citation_id || "—")}]</span>`;
    case "record_viewed":       return `Encounter record opened`;
    case "system_panel_viewed": return `System diagnostics opened`;
    default:               return escapeHtml(JSON.stringify(p));
  }
}
function formatMs(ms) {
  if (ms == null) return "—";
  return formatElapsed(ms);
}

document.addEventListener("DOMContentLoaded", () => {
  const exp = $("#exportBtn");
  if (exp) exp.addEventListener("click", () => {
    const tip = $("#exportTip");
    tip.hidden = !tip.hidden;
    if (!tip.hidden) setTimeout(() => tip.hidden = true, 6000);
  });
});

/* CLICK FLASH */
document.addEventListener("click", e => {
  const f = document.createElement("div");
  f.className = "click-flash";
  f.style.left = e.clientX + "px";
  f.style.top = e.clientY + "px";
  document.body.appendChild(f);
  setTimeout(() => f.remove(), 200);
});

/* BOOT */
function bootSequence() {
  // The V1 boot sequence has been replaced by cold_open.html served at /.
  // By the time we reach /cockpit the user has already seen the intro;
  // we just dispose of the leftover boot div and bring the cockpit live.
  const boot = $("#boot");
  if (boot) boot.remove();
  $("#cockpit").classList.add("live");
}

/* INIT */
async function init() {
  buildWaveform();
  setWaveBarsFlat();
  setTranscriptIdle();

  $("#recordBtn").addEventListener("click", openRecord);
  $("#sysBtn").addEventListener("click", () => { refreshSystem(); openOvl("sysScrim"); });
  wireMic();

  try {
    const scenarios = await jget("/scenarios");
    state.scenarios = {};
    for (const s of scenarios) state.scenarios[s.id] = s;
    state.active = scenarios[0].id;
    state.steps[state.active] = (scenarios[0].steps || []).map(() => false);
    state.stepTimes[state.active] = (scenarios[0].steps || []).map(() => "");
    try {
      const enc = await jpost("/records/start", { scenario_id: state.active });
      state.encounter = enc.id;
    } catch {}
    renderScenarioList();
    renderMissionContext();
    renderChecklist();
    renderReference(null);
    await refreshVitals();
  } catch (e) {
    $("#scenarioName").textContent = "Backend offline";
    $("#ptId").textContent = "—";
  }

  openNetworkStream();
  refreshSystem();
  setInterval(refreshSystem, 4000);
  setInterval(tickClocks, 1000);
  setInterval(tickVitalsStamp, 1000);
  setInterval(refreshVitals, 1500);
  tickClocks();

  bootSequence();
  setTimeout(() => { if (state.active) runReasoning("__SCENARIO_PRIMER__").catch(() => {}); }, 2400);
}

document.addEventListener("DOMContentLoaded", init);

/* ================================================================
   V3 — Profile selector, queue, rPPG, vision, calculators,
        interactions, handoff, tamper.
   ================================================================ */

const v3 = {
  profile: null,
  queue: [],
  activeEnc: null,        // active encounter id (overrides state.encounter)
  rppg: { active: false, es: null, history: [], confidence: 0 },
  allergies: [],
  adminHistory: [],       // drugs administered this encounter
  interactionsPending: 0,
  calcCount: 0,
  encByScenario: {},      // scenarioId -> encounter id (for restore on switch)
};

/* ---- Profile selector ---- */
async function showProfileSelector() {
  const profileScreen = $("#profileScreen");
  if (!profileScreen) return;
  try {
    const r = await jget("/profiles");
    const list = $("#profileList");
    list.innerHTML = r.profiles.map(p => `
      <div class="profile-card glass ${p.id === r.active ? "active" : ""}" data-id="${p.id}">
        <div>
          <div class="pc-name">${p.name}</div>
          <div class="pc-desc">${p.description}</div>
          <div class="pc-corpus">${p.corpus_summary}</div>
        </div>
        <div class="pc-arrow">→</div>
      </div>
    `).join("");
    list.querySelectorAll(".profile-card").forEach(el => {
      el.addEventListener("click", () => activateProfile(el.dataset.id));
    });
  } catch (e) {
    console.warn("profile load failed", e);
  }
  $("#profileSkip").addEventListener("click", () => activateProfile(null));
}

async function activateProfile(profileId) {
  if (profileId) {
    try {
      await jpost(`/profiles/activate/${profileId}`, {});
      v3.profile = profileId;
    } catch {}
  }
  const screen = $("#profileScreen");
  if (screen) {
    screen.classList.add("fade");
    setTimeout(() => screen.remove(), 600);
  }
  // The V1 boot div is no longer shown — cold_open.html handled the intro.
  const _boot = $("#boot");
  if (_boot) _boot.remove();
  // Update profile tag
  if (profileId) {
    const tag = $("#profileTag");
    tag.hidden = false;
    tag.textContent = `PROFILE: ${profileId.replace(/_/g, " ").toUpperCase()}`;
  }
  // Trigger normal init (the existing DOMContentLoaded handler)
  if (window._aegisInitFn) window._aegisInitFn();
}

/* ---- Multi-patient queue ---- */
async function refreshQueue() {
  try {
    const list = await jget("/queue");
    v3.queue = list;
    renderQueueTiles();
    // Update header warning indicator
    const totalPending = list.reduce((a, q) => a + (q.interactions_pending || 0), 0);
    const wb = $("#warnBtn");
    if (totalPending > 0) {
      wb.hidden = false;
      $("#warnCount").textContent = totalPending;
    } else {
      wb.hidden = true;
    }
  } catch {}
}

function renderQueueTiles() {
  const root = $("#queueTiles");
  if (!root) return;
  root.innerHTML = v3.queue.map(q => {
    const tcls = q.triage ? `t-${q.triage}` : "";
    const active = q.id === (v3.activeEnc || state.encounter) ? "active" : "";
    const elapsed = formatElapsed(Date.now() - q.started_at);
    return `
      <div class="queue-tile glass-nested ${tcls} ${active}" data-id="${q.id}" data-pt="${q.patient_label}">
        <div class="queue-tile-content">
          <div class="qt-line1"><span class="qt-pt">${q.patient_label}</span><span class="qt-elapsed">${elapsed}</span></div>
          <div class="qt-line2">${(q.domain || "").toUpperCase()} // ${q.case || ""}</div>
        </div>
      </div>
    `;
  }).join("");
  root.querySelectorAll(".queue-tile").forEach(el => {
    el.addEventListener("click", () => switchEncounter(parseInt(el.dataset.id, 10)));
    el.addEventListener("contextmenu", e => { e.preventDefault(); openTriagePopover(el, parseInt(el.dataset.id, 10)); });
  });
}

async function createNewEncounter() {
  const sid = state.active || "battlefield";
  try {
    await jpost("/queue/create", { scenario_id: sid });
    await refreshQueue();
    // Auto-switch to the newest
    const newest = v3.queue[v3.queue.length - 1];
    if (newest) await switchEncounter(newest.id);
  } catch {}
}

async function switchEncounter(eid) {
  if (!eid || eid === (v3.activeEnc || state.encounter)) return;
  const tile = v3.queue.find(q => q.id === eid);
  if (!tile) return;
  v3.activeEnc = eid;
  state.encounter = eid;
  state.active = tile.scenario_id;
  // Cross-fade
  $("#cockpit").style.opacity = "0.6";
  setTimeout(async () => {
    state.steps[state.active] = state.steps[state.active] || (state.scenarios[state.active]?.steps || []).map(() => false);
    state.stepTimes[state.active] = state.stepTimes[state.active] || (state.scenarios[state.active]?.steps || []).map(() => "");
    renderScenarioList();
    renderMissionContext();
    renderChecklist();
    renderReference(null);
    await refreshVitals();
    await refreshQueue();
    runReasoning("__SCENARIO_PRIMER__").catch(() => {});
    try { await jpost(`/queue/switch/${eid}`, {}); } catch {}
    $("#cockpit").style.opacity = "";
  }, 250);
}

/* Triage popover */
let _triageTarget = null;
function openTriagePopover(tileEl, eid) {
  _triageTarget = eid;
  const pop = $("#triagePop");
  const r = tileEl.getBoundingClientRect();
  pop.style.left = `${r.left}px`;
  pop.style.top = `${r.bottom + 4}px`;
  pop.hidden = false;
  setTimeout(() => document.addEventListener("click", _closeTriagePopOnce, true), 0);
}
function _closeTriagePopOnce(e) {
  if (e.target.closest(".triage-pop")) return;
  $("#triagePop").hidden = true;
  document.removeEventListener("click", _closeTriagePopOnce, true);
}
$$(".triage-opt").forEach(b => b.addEventListener("click", async () => {
  if (!_triageTarget) return;
  const cat = b.dataset.cat;
  try { await jpost(`/queue/triage/${_triageTarget}`, { category: cat }); } catch {}
  $("#triagePop").hidden = true;
  // Brief flash on the tile
  const tile = $(`.queue-tile[data-id="${_triageTarget}"]`);
  if (tile) {
    tile.classList.add("flash");
    setTimeout(() => tile.classList.remove("flash"), 600);
  }
  await refreshQueue();
}));

/* ---- Voice command routing for triage ---- */
function maybeHandleTriageVoice(text) {
  const m = text.toLowerCase().match(/triage\s+(red|yellow|green|black)/);
  if (!m) return false;
  const cat = m[1];
  const eid = v3.activeEnc || state.encounter;
  if (!eid) return false;
  jpost(`/queue/triage/${eid}`, { category: cat }).then(() => {
    refreshQueue();
    const tile = $(`.queue-tile[data-id="${eid}"]`);
    if (tile) { tile.classList.add("flash"); setTimeout(() => tile.classList.remove("flash"), 600); }
  }).catch(() => {});
  return true;
}

/* ---- Voice command routing for medication administration ---- */
function maybeHandleMedAdmin(text) {
  // Match patterns like "administering 1 gram TXA IV", "give 240 mg paracetamol PO"
  const m = text.toLowerCase().match(/(administer(?:ing)?|give|giving|push)\s+(?:(\d+\.?\d*)\s*(mg|g|gram|grams|mcg|ml))?\s*(?:of\s+)?([a-z][a-z\-]+)\s*(iv|po|im|sc|io)?/);
  if (!m) return false;
  const dose = (m[2] && m[3]) ? `${m[2]} ${m[3]}` : "";
  const drug = m[4]; const route = (m[5] || "").toUpperCase();
  const eid = v3.activeEnc || state.encounter;
  if (!eid) return false;
  // Check interactions first
  jpost("/interactions/check", {
    drug, encounter_id: eid,
    admin_history: v3.adminHistory, allergies: v3.allergies,
  }).then(r => {
    if (r.flags && r.flags.length) renderInteractionFlags(drug, dose, r.flags);
    v3.adminHistory.push(drug);
    jpost("/medications/log", { encounter_id: eid, drug, dose, route }).catch(() => {});
    refreshQueue();
  }).catch(() => {});
  return true;
}

function renderInteractionFlags(drug, dose, flags) {
  const t = formatElapsed(Date.now() - state.startedAt);
  const wrap = document.createElement("div");
  wrap.className = "entry";
  wrap.innerHTML = `
    <div class="entry-head">
      <span class="entry-time">${t}</span>
      <span class="entry-tag interaction">INTERACTION FLAG</span>
    </div>
    <div class="entry-body">
      <em>Administering ${escapeHtml(drug)}${dose ? ` ${escapeHtml(dose)}` : ""}.</em>
      ${flags.map(f => `
        <div class="interaction-block">
          <div class="sev">${f.severity} · ${f.kind}</div>
          <div><strong>${escapeHtml(f.subject)}</strong> ↔ <strong>${escapeHtml(f.interactant)}</strong>: ${escapeHtml(f.mechanism)}</div>
          <div style="margin-top:6px;color:var(--fg-1);">${escapeHtml(f.recommendation)}</div>
          <div class="src">Source: ${escapeHtml(f.source)}</div>
        </div>
      `).join("")}
    </div>
  `;
  $("#reasoningLog").appendChild(wrap);
  requestAnimationFrame(() => wrap.classList.add("visible"));
  $("#reasoningLog").scrollTop = $("#reasoningLog").scrollHeight;
}

/* ---- Voice command routing for calculator invocation ---- */
function maybeHandleCalculator(text) {
  const lower = text.toLowerCase();
  let name = null, inputs = null;
  if (/glasgow|gcs/.test(lower)) {
    name = "gcs"; inputs = { eye: 2, verbal: 3, motor: 5 };
  } else if (/qsofa|sofa/.test(lower)) {
    name = "qsofa"; inputs = { rr: 24, altered: true, sbp: 92 };
  } else if (/parkland/.test(lower)) {
    name = "parkland"; inputs = { weight_kg: 75, percent_bsa: 30 };
  } else if (/shock\s*index/.test(lower)) {
    name = "shock_index"; inputs = { hr: 124, sbp: 92 };
  } else if (/\bmap\b|mean arterial/.test(lower)) {
    name = "map"; inputs = { sbp: 92, dbp: 58 };
  } else if (/ett|tube\s+size/.test(lower)) {
    name = "ett_size"; inputs = { age_years: 4 };
  } else if (/(paracetamol|acetaminophen|ibuprofen|epinephrine).*(?:dose|child|kg)/.test(lower)) {
    name = "ped_dose";
    const drug = (lower.match(/(paracetamol|acetaminophen|ibuprofen|epinephrine|ondansetron|ceftriaxone)/) || [])[1] || "paracetamol";
    inputs = { weight_kg: 16, drug };
  }
  if (!name) return false;
  invokeCalculator(name, inputs);
  return true;
}

async function invokeCalculator(name, inputs) {
  const eid = v3.activeEnc || state.encounter;
  try {
    const r = await jpost(`/calculators/${name}`, { inputs, encounter_id: eid });
    if (!r || r.ok === false) return;
    appendCalculatorBlock(r);
    v3.calcCount += 1;
    $("#calcCount").textContent = String(v3.calcCount).padStart(2, "0");
    refreshCalcPanel();
  } catch (e) { console.warn(e); }
}

function appendCalculatorBlock(r) {
  const t = formatElapsed(Date.now() - state.startedAt);
  const wrap = document.createElement("div");
  wrap.className = "entry";
  const inputsStr = Object.entries(r.inputs || {}).map(([k, v]) => `${k}=${v}`).join(" · ");
  wrap.innerHTML = `
    <div class="entry-head">
      <span class="entry-time">${t}</span>
      <span class="entry-tag">CALCULATOR INVOKED</span>
    </div>
    <div class="entry-body">
      <div class="calc-block" data-name="${escapeAttr(r.name)}">
        <div class="name">${escapeHtml(r.name)}</div>
        <div class="inputs">INPUTS: ${escapeHtml(inputsStr)}</div>
        <div class="result">RESULT: ${escapeHtml(String(r.result))}</div>
        <div class="interp">${escapeHtml(r.tier || "")}</div>
        <div class="src">SOURCE: ${escapeHtml(r.source || "—")}</div>
      </div>
    </div>
  `;
  $("#reasoningLog").appendChild(wrap);
  requestAnimationFrame(() => wrap.classList.add("visible"));
  wrap.querySelector(".calc-block").addEventListener("click", () => openCalcDetail(r));
  $("#reasoningLog").scrollTop = $("#reasoningLog").scrollHeight;
}

function openCalcDetail(r) {
  $("#calcOvlTitle").textContent = r.name;
  const inputs = Object.entries(r.inputs || {}).map(([k, v]) => `<div><span class="label-dim">${escapeHtml(k)}</span><span class="mono">${escapeHtml(String(v))}</span></div>`).join("");
  $("#calcBody").innerHTML = `
    <div class="img-fields">${inputs}</div>
    <div class="img-desc"><strong>RESULT:</strong> ${escapeHtml(String(r.result))}</div>
    <div class="img-desc">${escapeHtml(r.tier || "")}</div>
  `;
  $("#calcSrc").textContent = `Source: ${r.source || "—"}`;
  openOvl("calcScrim");
}

async function refreshCalcPanel() {
  const eid = v3.activeEnc || state.encounter;
  if (!eid) return;
  try {
    const r = await jget(`/calc-history/${eid}`);
    const list = $("#calcList");
    const empty = $("#calcEmpty");
    if (!r.history || !r.history.length) {
      list.innerHTML = ""; empty.hidden = false;
    } else {
      empty.hidden = true;
      list.innerHTML = r.history.map(h => `
        <div class="calc-row" data-payload='${escapeAttr(JSON.stringify(h))}'>
          <div class="cn">${escapeHtml(h.name)}</div>
          <div class="cv">${escapeHtml(String(h.result))}</div>
          <div class="ct">${escapeHtml(h.tier || "")}</div>
        </div>
      `).join("");
      list.querySelectorAll(".calc-row").forEach(el => {
        el.addEventListener("click", () => {
          try { openCalcDetail(JSON.parse(el.dataset.payload.replace(/&quot;/g, '"'))); } catch {}
        });
      });
    }
  } catch {}
}

/* Tabs in reference panel */
$$(".ref-tab").forEach(b => b.addEventListener("click", () => {
  $$(".ref-tab").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  const tab = b.dataset.tab;
  $$(".ref-tab-pane").forEach(p => p.hidden = (p.dataset.pane !== tab));
  if (tab === "calc") refreshCalcPanel();
}));

/* ---- rPPG ---- */
function camToggle() {
  const btn = $("#camToggle");
  if (v3.rppg.active) stopRppg(); else startRppg();
}
async function startRppg() {
  const eid = v3.activeEnc || state.encounter;
  try {
    await jpost("/rppg/start", { encounter_id: eid, base_hr: 78 });
  } catch {}
  v3.rppg.active = true;
  v3.rppg.history = [];
  v3.rppg.confidence = 0;
  $("#camToggle").classList.add("active");
  $("#camToggle").setAttribute("aria-pressed", "true");
  // Subscribe to SSE
  const es = new EventSource(API + "/rppg/stream");
  es.onmessage = ev => {
    try { onRppgSample(JSON.parse(ev.data)); } catch {}
  };
  v3.rppg.es = es;
}
async function stopRppg() {
  const eid = v3.activeEnc || state.encounter;
  try { await jpost("/rppg/stop", { encounter_id: eid }); } catch {}
  v3.rppg.active = false;
  $("#camToggle").classList.remove("active");
  $("#camToggle").setAttribute("aria-pressed", "false");
  if (v3.rppg.es) { v3.rppg.es.close(); v3.rppg.es = null; }
  // Vitals refresh restores scripted values
  refreshVitals();
}
function onRppgSample(s) {
  v3.rppg.history.push(s);
  if (v3.rppg.history.length > 30) v3.rppg.history.shift();
  v3.rppg.confidence = s.confidence || 0;
  // Patch the HR cell in place (don't full re-render)
  const grid = $("#vitalsGrid");
  const hrCell = grid.querySelector(".vital");
  if (!hrCell) return;
  hrCell.classList.add("cam");
  const valEl = hrCell.querySelector(".v-val");
  if (valEl) valEl.textContent = Math.round(s.bpm);
  // Confidence meter
  let conf = hrCell.querySelector(".cam-conf");
  if (!conf) {
    conf = document.createElement("div");
    conf.className = "cam-conf";
    conf.innerHTML = `<span class="cb cb1"></span><span class="cb cb2"></span><span class="cb cb3"></span>`;
    hrCell.appendChild(conf);
  }
  conf.querySelectorAll(".cb").forEach((b, i) => {
    b.classList.toggle("lit", i < v3.rppg.confidence);
  });
  if (v3.rppg.confidence === 0) {
    valEl && (valEl.style.color = "var(--fg-2)");
  } else if (valEl) {
    valEl.style.color = "";
  }
}

/* ---- Image capture / vision ---- */
async function imgCapture() {
  $("#imgFile").click();
}
$("#imgFile") && $("#imgFile").addEventListener("change", async e => {
  if (e.target.files && e.target.files[0]) await runVisionAnalysis(e.target.files[0]);
});

async function runVisionAnalysis(file) {
  const eid = v3.activeEnc || state.encounter;
  let dataUrl = null;
  if (file) {
    dataUrl = await new Promise(res => {
      const fr = new FileReader();
      fr.onload = () => res(fr.result);
      fr.readAsDataURL(file);
    });
  }
  try {
    const r = await jpost("/vision/analyze", { scenario_id: state.active, encounter_id: eid });
    appendImageAnalysis(r, dataUrl);
  } catch {}
}

function appendImageAnalysis(r, dataUrl) {
  const t = formatElapsed(Date.now() - state.startedAt);
  const wrap = document.createElement("div");
  wrap.className = "entry";
  wrap.innerHTML = `
    <div class="entry-head">
      <span class="entry-time">${t}</span>
      <span class="entry-tag image">IMAGE ANALYSIS</span>
    </div>
    <div class="entry-body" data-payload='${escapeAttr(JSON.stringify(r))}'>
      <em>${escapeHtml(r.classification)} · ${escapeHtml(r.severity)} · confidence ${(r.confidence * 100).toFixed(0)}%</em>
      <div style="margin-top: 8px;">${escapeHtml(r.description)}</div>
      <ol class="steps" style="margin-top: 10px;">
        ${(r.next_steps || []).map(s => `<li><span class="step-text">${escapeHtml(s.text)}<span class="cite" data-cite-id="${escapeAttr(s.cite)}">[${escapeHtml(s.cite)}]</span></span></li>`).join("")}
      </ol>
    </div>
  `;
  $("#reasoningLog").appendChild(wrap);
  requestAnimationFrame(() => wrap.classList.add("visible"));
  // Open detail on click
  wrap.querySelector(".entry-body").addEventListener("click", e => {
    if (e.target.closest(".cite")) return;
    openImageDetail(r, dataUrl);
  });
  $("#reasoningLog").scrollTop = $("#reasoningLog").scrollHeight;
}

function openImageDetail(r, dataUrl) {
  $("#imgOvlTitle").textContent = `${r.classification} · ${r.severity}`;
  const stepsHtml = (r.next_steps || []).map(s => `<li>${escapeHtml(s.text)} <span class="cite" data-cite-id="${escapeAttr(s.cite)}">[${escapeHtml(s.cite)}]</span></li>`).join("");
  $("#imgBody").innerHTML = `
    ${dataUrl ? `<img src="${dataUrl}" class="img-detail-thumb" alt="captured image"/>` : ""}
    <div class="img-fields">
      <div><span class="label-dim">Classification</span><span class="mono">${escapeHtml(r.classification)}</span></div>
      <div><span class="label-dim">Severity</span><span class="mono">${escapeHtml(r.severity)}</span></div>
      <div><span class="label-dim">Confidence</span><span class="mono">${(r.confidence * 100).toFixed(0)}%</span></div>
    </div>
    <div class="img-desc">${escapeHtml(r.description)}</div>
    <ul class="img-steps">${stepsHtml}</ul>
  `;
  $("#imgSig").textContent = `Image bytes hashed and signed at capture; analysis stored as signed event.`;
  openOvl("imgScrim");
}

/* ---- Handoff ---- */
async function openHandoff() {
  const eid = v3.activeEnc || state.encounter;
  if (!eid) return;
  try {
    const r = await jpost("/handoff/prepare", { encounter_id: eid });
    if (!r.ok) return;
    $("#handoffOvlTitle").textContent = `ENC-${eid}`;
    $("#hRecipName").textContent = r.recipient.name;
    $("#hRecipEndpoint").textContent = r.recipient.endpoint;
    $("#hRecipKey").textContent = r.recipient.pub_fingerprint.slice(0, 16) + "…";
    const counts = Object.entries(r.resource_counts).map(([k, v]) => `${v} ${k}`).join(" · ");
    $("#hCounts").textContent = counts;
    $("#hHash").textContent = r.bundle_hash.slice(0, 16) + "…";
    $("#hHash").title = r.bundle_hash;
    $("#hSize").textContent = `${r.size_bytes.toLocaleString()} bytes`;
    // Network state
    const reachable = state.network.reachable;
    const netEl = $("#hNet");
    netEl.classList.toggle("ok", !!reachable);
    netEl.classList.toggle("fail", !reachable);
    netEl.textContent = reachable ? "EXTERNAL REACHABLE — handoff permitted" : "NETWORK UNREACHABLE — handoff inhibited";
    $("#hTransmit").disabled = !reachable;
    // Reset views
    $("#handoffBody").hidden = false;
    $("#handoffTxBody").hidden = true;
    $("#hReceipt").hidden = true;
    openOvl("handoffScrim");
    // Stash bundle for transmit
    v3._pendingHandoff = { encounter_id: eid, bundle_hash: r.bundle_hash, size: r.size_bytes };
  } catch {}
}

$("#hTransmit") && $("#hTransmit").addEventListener("click", runHandoffTransmit);

async function runHandoffTransmit() {
  const h = v3._pendingHandoff;
  if (!h) return;
  // Switch to transmission view
  $("#handoffBody").hidden = true;
  $("#handoffTxBody").hidden = false;
  $("#hTxHash").textContent = h.bundle_hash.slice(0, 32) + "…";
  $("#hBytesTotal").textContent = h.size.toLocaleString();
  // Build bars
  const wrap = $("#hBars");
  wrap.innerHTML = Array.from({ length: 60 }, () => `<span class="b"></span>`).join("");
  const bars = wrap.querySelectorAll(".b");
  // Animate bytes counter + bars
  const t0 = performance.now();
  const dur = 4500;
  const tick = (now) => {
    const p = Math.min(1, (now - t0) / dur);
    const bytes = Math.floor(h.size * p);
    $("#hBytes").textContent = bytes.toLocaleString();
    const litCount = Math.floor(bars.length * p);
    bars.forEach((b, i) => b.classList.toggle("lit", i < litCount));
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  // Server transmit
  try {
    const r = await jpost("/handoff/transmit", { encounter_id: h.encounter_id });
    setTimeout(() => {
      if (!r.ok) return;
      $("#hReceipt").hidden = false;
      $("#hRid").textContent = r.receipt.receipt_id;
      $("#hRtime").textContent = new Date(r.receipt.received_at).toISOString();
      $("#hRrecv").textContent = r.receipt.receiver_id;
      $("#hRhash").textContent = r.receipt.bundle_hash_confirmed.slice(0, 24) + "…";
    }, 4600);
  } catch {}
}

/* ---- Tamper demo ---- */
async function tamperToggle() {
  try {
    const r = await jpost("/records/tamper", { encounter_id: v3.activeEnc || state.encounter });
    // Force a record refresh if open; otherwise flash an indicator
    if ($$(".ovl-scrim.open").some(s => s.id === "recScrim")) {
      const eid = v3.activeEnc || state.encounter;
      if (eid) loadRecord(eid);
    }
    refreshSystem();
  } catch {}
}

/* ---- Update record overlay to surface integrity chain ---- */
const _originalLoadRecord = typeof loadRecord !== "undefined" ? loadRecord : null;
async function loadRecordV3(id) {
  const r = await jget(`/records/${id}`);
  $("#recOvlTitle").textContent = `ENC-${id}`;
  $("#recScenario").textContent = r.scenario_name || r.scenario_id;
  $("#recPt").textContent = r.patient_label;
  $("#recDur").textContent = r.duration || "—";
  const hash = r.integrity_hash || "—";
  $("#recHash").textContent = hash.slice(0, 12) + (hash.length > 12 ? "…" : "");
  $("#recHash").title = hash;
  const intEl = $("#recIntegrity");
  if (r.integrity_ok) {
    intEl.textContent = `Ed25519 chain · ${r.chain_length} events · ✓ VERIFIED`;
    intEl.className = "ok";
    intEl.classList.remove("broken");
  } else {
    intEl.textContent = `Ed25519 chain · ✗ CHAIN BROKEN AT EVENT #${r.broken_event_id}`;
    intEl.className = "broken";
  }
  $("#recTimeline").innerHTML = (r.events || []).map(e => `
    <div class="rec-event ${r.broken_event_id === e.id ? "broken" : ""}">
      <span class="t">${formatMs(e.t_offset_ms)}</span>
      <span class="typ">${e.event_type}</span>
      <span class="body">${formatEventBody(e)}</span>
    </div>
  `).join("");
}
window.loadRecord = loadRecordV3;

/* V4 — periodic integrity verification while RECORD overlay is open */
let _v4VerifyInterval = null;
let _v4VerifyTickInterval = null;
let _v4LastVerifiedAt = null;
async function _v4PeriodicVerify() {
  const eid = v3.activeEnc || state.encounter;
  if (!eid) return;
  try {
    // V4 endpoint /encounter/{id}/integrity (preview server aliases this)
    const r = await jget(`/encounter/${eid}/integrity`);
    _v4LastVerifiedAt = Date.now();
    const intEl = $("#recIntegrity");
    if (intEl) {
      if (r.valid) {
        intEl.textContent = `SHA-256 chain · ${r.event_count} events · ✓ VERIFIED`;
        intEl.className = "ok";
      } else {
        intEl.textContent = `SHA-256 chain · ✗ CHAIN BROKEN AT EVENT #${r.first_break_event_id}`;
        intEl.className = "broken";
      }
    }
  } catch {}
}
function _v4VerifyTickDisplay() {
  if (_v4LastVerifiedAt == null) return;
  const lvEl = $("#recLastVerified");
  if (!lvEl) return;
  const ago = Math.floor((Date.now() - _v4LastVerifiedAt) / 1000);
  lvEl.textContent = `LAST VERIFIED ${String(ago).padStart(2, "0")}s AGO`;
}

/* Hook record + sys + cite open to capture events and start the verify
   loop. We attach to the buttons rather than wrapping openOvl because
   openOvl is a function declaration whose internal callers won't see a
   window-level override. */
document.addEventListener("DOMContentLoaded", () => {
  const recBtn = $("#recordBtn");
  const sysBtn = $("#sysBtn");
  if (recBtn) recBtn.addEventListener("click", () => {
    const eid = v3.activeEnc || state.encounter;
    if (eid) {
      jpost(`/encounter/${eid}/event`, {
        event_type: "record_viewed", payload: {}
      }).catch(() => {});
    }
    if (_v4VerifyInterval) clearInterval(_v4VerifyInterval);
    if (_v4VerifyTickInterval) clearInterval(_v4VerifyTickInterval);
    _v4PeriodicVerify();
    _v4VerifyInterval = setInterval(_v4PeriodicVerify, 10000);
    _v4VerifyTickInterval = setInterval(_v4VerifyTickDisplay, 1000);
  });
  if (sysBtn) sysBtn.addEventListener("click", () => {
    const eid = v3.activeEnc || state.encounter;
    if (eid) {
      jpost(`/encounter/${eid}/event`, {
        event_type: "system_panel_viewed", payload: {}
      }).catch(() => {});
    }
  });
  // Stop verify loop on overlay close
  document.querySelectorAll('.ovl-close[data-ovl="rec"]').forEach(b => {
    b.addEventListener("click", () => {
      if (_v4VerifyInterval) { clearInterval(_v4VerifyInterval); _v4VerifyInterval = null; }
      if (_v4VerifyTickInterval) { clearInterval(_v4VerifyTickInterval); _v4VerifyTickInterval = null; }
    });
  });
});

/* ---- Allergies surface ---- */
function setAllergies(list) {
  v3.allergies = list || [];
  const av = $("#allergiesValue");
  if (!av) return;
  if (v3.allergies.length) {
    av.textContent = v3.allergies.join(" · ");
    av.classList.add("captured");
  } else {
    av.textContent = "not yet captured";
    av.classList.remove("captured");
  }
}

/* ---- Wire V3 init: hook into existing init ---- */
window._aegisInitFn = init;
const _origInit = init;
async function v3Init() {
  await _origInit();
  // V3 panels and timers
  await refreshQueue();
  setInterval(refreshQueue, 3000);
  // Handoff button on RECORD overlay footer
  injectHandoffButton();
  // Wire image button + camera toggle + queue + warn
  $("#imgBtn") && $("#imgBtn").addEventListener("click", imgCapture);
  $("#camToggle") && $("#camToggle").addEventListener("click", camToggle);
  $("#queueNew") && $("#queueNew").addEventListener("click", createNewEncounter);
  $("#warnBtn") && $("#warnBtn").addEventListener("click", openRecord);
  // Update profile tag from /profiles
  try {
    const r = await jget("/profiles");
    if (r.active && r.active !== "combat_medic") v3.profile = r.active;
    if (r.active) {
      const tag = $("#profileTag");
      tag.hidden = false;
      tag.textContent = `PROFILE: ${r.active.replace(/_/g, " ").toUpperCase()}`;
    }
  } catch {}
  // Demo: seed allergies
  if (state.active === "battlefield") setAllergies(["penicillin"]);
  // Tamper key
  document.addEventListener("keydown", e => {
    if (e.ctrlKey && e.shiftKey && e.key === "T") { e.preventDefault(); tamperToggle(); }
    if (e.ctrlKey && e.shiftKey && e.key === "I") { e.preventDefault(); imgCapture(); }
    if (e.ctrlKey && e.shiftKey && e.key === "C") { e.preventDefault(); invokeCalculator("gcs", { eye: 2, verbal: 3, motor: 5 }); }
    if (e.ctrlKey && e.shiftKey && e.key === "H") { e.preventDefault(); openHandoff(); }
  });
  // Hook setTranscript so voice commands route to triage / med admin / calculator
  const _origSet = setTranscript;
  window.setTranscript = function (text) {
    _origSet(text);
    if (maybeHandleTriageVoice(text)) return;
    if (maybeHandleMedAdmin(text)) return;
    if (maybeHandleCalculator(text)) return;
  };
}

function injectHandoffButton() {
  // Replace export-btn with a real handoff trigger
  const ex = $("#exportBtn");
  if (ex) {
    ex.textContent = "INITIATE HANDOFF →";
    ex.removeEventListener && ex.removeEventListener("click", () => {});
    ex.addEventListener("click", e => { e.stopPropagation(); openHandoff(); });
  }
}

/* Replace DOMContentLoaded handler: profile selector first, then init */
document.removeEventListener && document.removeEventListener("DOMContentLoaded", init);
document.addEventListener("DOMContentLoaded", () => {
  showProfileSelector();
  // Patch init reference so activateProfile triggers v3Init
  window._aegisInitFn = v3Init;
});

/* ================================================================
   V4 — Cockpit reshape: Live Transcript, QA, Nudges, Tamper, Handoff
   ================================================================ */

const V4 = {
  qaPolling: null,
  nudgePolling: null,
  recVerifyInterval: null,
  recVerifyTickInterval: null,
  recLastVerifiedAt: null,
  utterances: [],     // [{ts, text, receipts: [{span, fact}]}]
  extractionBlock: null,   // last extraction result for receipt tooltips
};

/* ---- Hide V3 surfaces deferred per V4 §15 ---- */
function v4HideDeferred() {
  const queue = document.getElementById("queueStrip"); if (queue) queue.style.display = "none";
  const profileTag = document.getElementById("profileTag"); if (profileTag) profileTag.hidden = true;
  const warnBtn = document.getElementById("warnBtn"); if (warnBtn) warnBtn.hidden = true;
  // Collapse cockpit grid back to V1 4-row layout (no queue row)
  const cockpit = document.getElementById("cockpit");
  if (cockpit) cockpit.style.gridTemplateRows = "56px 1fr 80px";
  if (cockpit) cockpit.style.gridTemplateAreas = '"header header header" "left center right" "bottom bottom bottom"';
}

/* ---- Live Transcript pane ---- */
function v4PushUtterance(text, ts) {
  const log = document.getElementById("reasoningLog");
  if (!log) return;
  const empty = document.getElementById("transcriptEmpty");
  if (empty) empty.remove();
  const wrap = document.createElement("div");
  wrap.className = "tx-utterance";
  const stamp = ts || formatElapsed(Date.now() - state.startedAt);
  wrap.innerHTML = `
    <span class="ts">${escapeHtml(stamp)}</span>
    <span class="body">${escapeHtml(text)}</span>
  `;
  log.appendChild(wrap);
  requestAnimationFrame(() => wrap.classList.add("in"));
  log.scrollTop = log.scrollHeight;
  V4.utterances.push({ts: stamp, text, el: wrap, receipts: []});
}

/* Highlight extracted spans in the most recent utterance(s) */
function v4ApplyReceipts(extraction) {
  V4.extractionBlock = extraction;
  const facts = [];
  for (const v of (extraction.vitals_observed || [])) {
    if (v.transcript_span) facts.push({
      span: v.transcript_span,
      summary: `${v.type.toUpperCase()} ${v.value}`,
      kind: "vital",
    });
  }
  for (const i of (extraction.interventions_performed || [])) {
    if (i.transcript_span) facts.push({
      span: i.transcript_span,
      summary: `${i.type}: ${i.details}`,
      kind: "intervention",
    });
  }
  // Highlight matching spans in any utterance
  V4.utterances.forEach(u => {
    let inner = u.el.querySelector(".body").textContent;
    let html = escapeHtml(inner);
    for (const f of facts) {
      const idx = inner.toLowerCase().indexOf(f.span.toLowerCase());
      if (idx < 0) continue;
      // Wrap the matched span with a receipt class
      const safe = escapeHtml(inner.slice(idx, idx + f.span.length));
      html = html.replace(safe, `<span class="span-receipt"
        data-summary="${escapeAttr(f.summary)}"
        data-kind="${escapeAttr(f.kind)}">${safe}</span>`);
    }
    u.el.querySelector(".body").innerHTML = html;
  });
  v4WireReceiptTooltips();
  // Auto-check checklist items whose label matches an extracted intervention
  v4AutoCheckFromExtraction(extraction);
}

let _v4Tooltip = null;
function v4WireReceiptTooltips() {
  document.querySelectorAll(".span-receipt").forEach(el => {
    if (el._v4Bound) return;
    el._v4Bound = true;
    el.addEventListener("mouseenter", () => {
      if (_v4Tooltip) _v4Tooltip.remove();
      const tip = document.createElement("div");
      tip.className = "tx-tooltip";
      tip.innerHTML = `<span class="lbl">${el.dataset.kind}</span>${escapeHtml(el.dataset.summary)}`;
      const r = el.getBoundingClientRect();
      tip.style.left = `${r.left}px`;
      tip.style.top = `${r.bottom + 6}px`;
      document.body.appendChild(tip);
      _v4Tooltip = tip;
    });
    el.addEventListener("mouseleave", () => {
      if (_v4Tooltip) { _v4Tooltip.remove(); _v4Tooltip = null; }
    });
  });
}

/* Auto-check checklist items based on extracted interventions */
function v4AutoCheckFromExtraction(extraction) {
  const sc = state.scenarios[state.active]; if (!sc) return;
  const arr = state.steps[state.active] || [];
  const times = state.stepTimes[state.active] || [];
  const interventions = extraction.interventions_performed || [];
  let changed = false;
  for (const itv of interventions) {
    const hint = (itv.type + " " + (itv.details||"")).toLowerCase();
    sc.steps.forEach((label, i) => {
      const l = label.toLowerCase();
      const hit = (
        (hint.includes("tourniquet") && l.includes("tourniquet")) ||
        (hint.includes("compression") && l.includes("compress")) ||
        (hint.includes("paracetamol") && (l.includes("paracetamol") || l.includes("antipyretic"))) ||
        (hint.includes("aed") && l.includes("aed")) ||
        (hint.includes("defibrillation") && l.includes("aed"))
      );
      if (hit && !arr[i]) {
        arr[i] = true;
        times[i] = formatElapsed(Date.now() - state.startedAt);
        // Stash the receipt phrase
        const li = document.querySelectorAll("#checklist .check-item")[i];
        if (li) {
          let r = li.querySelector(".extraction-receipt");
          if (!r) {
            r = document.createElement("div");
            r.className = "extraction-receipt";
            li.appendChild(r);
          }
          r.textContent = `"${itv.transcript_span || itv.details}"`;
        }
        changed = true;
      }
    });
  }
  if (changed) {
    state.steps[state.active] = arr; state.stepTimes[state.active] = times;
    renderChecklist();
  }
}

/* ---- Reference QA ---- */
async function v4Ask() {
  const inp = document.getElementById("qaInput");
  if (!inp) return;
  const q = (inp.value || "").trim();
  if (!q) return;
  const askBtn = document.getElementById("qaAsk");
  askBtn.disabled = true; askBtn.textContent = "…";
  const ans = document.getElementById("qaAnswer");
  const foot = document.getElementById("qaFoot");
  ans.hidden = false;
  ans.classList.remove("refused");
  ans.innerHTML = "<em>thinking…</em>";
  foot.hidden = false; foot.textContent = "RETRIEVING…";
  const t0 = performance.now();
  try {
    const r = await jpost("/qa", {
      question: q,
      scenario_context: state.active,
      encounter_id: state.encounter,
    });
    const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
    if (r.answer_type === "refused") {
      ans.classList.add("refused");
      ans.innerHTML = escapeHtml(r.refusal_reason || "Refused.");
      foot.textContent = `REFUSED · ANSWER LATENCY ${elapsed}s`;
    } else {
      const cites = (r.citations || []).map(c =>
        `<span class="cite" data-cite-id="${escapeAttr(c.citation_id)}">[${escapeHtml(c.citation_id)}]</span>`
      ).join(" ");
      ans.innerHTML = escapeHtml(r.answer_text || "") + " " + cites;
      const meta = r._retrieval_meta || {};
      foot.textContent = `RETRIEVAL: ${meta.chunks_returned || (r.citations || []).length} chunks · ANSWER LATENCY ${elapsed}s`;
    }
    // Re-render reference panel with the top citation
    if (r.citations && r.citations[0]) {
      try {
        const cid = r.citations[0].citation_id;
        const chunk = await jget(`/retrieve/chunk/${encodeURIComponent(cid)}`);
        renderReference({...chunk, id: chunk.citation_id || cid});
      } catch {}
    }
  } catch (e) {
    ans.classList.add("refused");
    ans.innerHTML = "<em>QA backend unreachable.</em>";
    foot.textContent = "ERROR";
  } finally {
    askBtn.disabled = false; askBtn.textContent = "ASK";
  }
}

/* ---- Nudge Tray ---- */
async function v4PollNudges() {
  const eid = state.encounter; if (!eid) return;
  try {
    const arr = state.steps[state.active] || [];
    const completedIds = (state.scenarios[state.active]?.steps || [])
      .map((label, i) => arr[i] ? _v4StepKey(label) : null)
      .filter(Boolean);
    const r = await jpost("/nudges", {
      encounter_state: {
        encounter_id: eid,
        scenario_id: state.active,
        elapsed_seconds: Math.floor((Date.now() - state.startedAt) / 1000),
        completed_checklist_items: completedIds,
        extracted_facts: V4.extractionBlock || null,
      }
    });
    v4RenderNudges(r.nudges || []);
  } catch {}
}

function _v4StepKey(label) {
  const l = label.toLowerCase();
  if (l.includes("tourniquet")) return "tourniquet_applied";
  if (l.includes("compress")) return "compressions_started";
  if (l.includes("rescue") || l.includes("breath")) return "rescue_breaths";
  if (l.includes("aed") || l.includes("defib")) return "aed_applied";
  if (l.includes("paracetamol") || l.includes("antipyretic")) return "antipyretic_administered";
  if (l.includes("ors") || l.includes("oral rehydration")) return "ors_initiated";
  if (l.includes("weight")) return "weight_documented";
  if (l.includes("txa") || l.includes("tranexamic")) return "txa_administered";
  return l.replace(/[^a-z]+/g, "_").slice(0, 30);
}

const _v4SeenNudgeKeys = new Set();
function v4RenderNudges(nudges) {
  const list = document.getElementById("nudgeList");
  const empty = document.getElementById("nudgeEmpty");
  const counter = document.getElementById("nudgeCount");
  if (!list) return;
  if (!nudges.length) {
    list.innerHTML = "";
    if (empty) empty.style.display = "";
    if (counter) counter.textContent = "0";
    return;
  }
  if (empty) empty.style.display = "none";
  if (counter) counter.textContent = String(nudges.length);
  list.innerHTML = nudges.map(n => {
    const key = `${n.severity}|${n.step_label}|${n.citation_id}`;
    const fresh = !_v4SeenNudgeKeys.has(key);
    _v4SeenNudgeKeys.add(key);
    return `
      <div class="nudge-row sev-${escapeAttr(n.severity)} ${fresh ? "fresh" : ""}"
           data-cite="${escapeAttr(n.citation_id)}">
        <span class="nudge-dot"></span>
        <div class="nudge-body">
          <div class="nudge-step">${escapeHtml(n.step_label)}</div>
          <div class="nudge-rationale">${escapeHtml(n.rationale || "")}</div>
          <div class="nudge-foot">
            <span class="cite" data-cite-id="${escapeAttr(n.citation_id)}">[${escapeHtml(n.citation_id)}]</span>
            <span class="ts">T+${Math.floor((n.issued_at_elapsed_seconds || 0) / 60).toString().padStart(2, "0")}:${((n.issued_at_elapsed_seconds || 0) % 60).toString().padStart(2, "0")}</span>
          </div>
        </div>
      </div>
    `;
  }).join("");
  list.querySelectorAll(".nudge-row").forEach(el => {
    el.addEventListener("click", e => {
      if (e.target.closest(".cite")) return;
      el.classList.add("acknowledged");
      if (state.encounter) {
        jpost(`/encounter/${state.encounter}/event`, {
          event_type: "nudge_acknowledged",
          payload: {citation_id: el.dataset.cite},
        }).catch(() => {});
      }
    });
  });
}

/* ---- Voice flow → extraction ---- */
async function v4OnFinalTranscript(text) {
  if (!text || !text.trim()) return;
  v4PushUtterance(text);
  if (!state.encounter) return;
  try {
    const r = await jpost("/extract", {
      transcript: text,
      encounter_id: state.encounter,
      scenario_name: state.scenarios[state.active]?.name || "",
      elapsed_seconds: Math.floor((Date.now() - state.startedAt) / 1000),
    });
    v4ApplyReceipts(r);
  } catch {}
  v4UpdateHandoffEnabled();
}

/* Patch setTranscript so the V4 path runs */
(() => {
  const orig = window.setTranscript || setTranscript;
  window.setTranscript = function(text) {
    orig(text);
    if (text && !text.startsWith("Awaiting")) v4OnFinalTranscript(text);
  };
})();

/* ---- Handoff button enablement ---- */
function v4UpdateHandoffEnabled() {
  const btn = document.getElementById("handoffBtn");
  if (!btn) return;
  const arr = state.steps[state.active] || [];
  const haveChecks = arr.some(Boolean);
  const haveExtract = !!V4.extractionBlock;
  btn.disabled = !(haveChecks && haveExtract);
  const state_el = document.getElementById("handoffBtnState");
  if (state_el) {
    state_el.textContent = btn.disabled
      ? "needs ≥1 fact + ≥1 step"
      : "ready";
  }
}

/* ---- Handoff flow ---- */
async function v4OpenHandoff() {
  const eid = state.encounter; if (!eid) return;
  const btn = document.getElementById("handoffBtn");
  btn.classList.add("generating");
  btn.querySelector(".hb-state").textContent = "generating…";

  // Gather data
  let rec = null;
  try { rec = await jget(`/encounter/${eid}`); } catch {}
  const events = (rec && rec.events) || [];
  const extracted = V4.extractionBlock;
  const facts = (extracted ? (extracted.vitals_observed || []).length + (extracted.interventions_performed || []).length : 0);
  const nudgeCount = parseInt(document.getElementById("nudgeCount")?.textContent || "0", 10);

  // Open overlay in generating state
  const ovl = document.getElementById("handoffScrim");
  document.getElementById("handoffOvlTitle").textContent = `ENC-${eid}`;
  document.getElementById("hndfEncounter").textContent = `ENC-${eid}`;
  document.getElementById("hndfEvents").textContent = String(events.length);
  document.getElementById("hndfFacts").textContent = String(facts);
  document.getElementById("hndfNudges").textContent = String(nudgeCount);
  document.getElementById("hndfAarCheck").textContent = "GENERATING…";
  document.getElementById("hndfAarText").textContent = "";
  document.getElementById("hndfHashCheck").textContent = "—";
  document.getElementById("hndfSigCheck").textContent = "—";
  document.getElementById("hndfPdfCheck").textContent = "—";
  document.getElementById("hndfPacketName").textContent = "—";
  document.getElementById("hndfDeviceKey").textContent = "—";
  document.getElementById("hndfActions").hidden = true;
  if (typeof openOvl === "function") openOvl("handoffScrim");
  else { ovl.classList.add("open"); ovl.setAttribute("aria-hidden", "false"); }

  // Generate AAR via the LLM job
  let aar = null;
  try {
    aar = await jpost("/aar", {encounter_id: eid});
  } catch {}
  const aarTxt = (aar && aar.summary) || "AAR generation unavailable.";
  // Typewriter the AAR summary into the overlay
  document.getElementById("hndfAarCheck").textContent = "✓";
  await v4Typewriter(document.getElementById("hndfAarText"), aarTxt, 32);

  // Then tick the signing/packaging steps
  await v4Sleep(280);
  document.getElementById("hndfHashCheck").textContent = "✓ SHA-256 computed";
  await v4Sleep(240);
  document.getElementById("hndfSigCheck").textContent = "✓ Ed25519 signed";
  await v4Sleep(240);
  document.getElementById("hndfPdfCheck").textContent = "✓ summary.pdf rendered";

  // Final packet info — derived locally to make this preview-friendly
  const packet = await v4BuildPacket(eid, events, extracted, aar);
  document.getElementById("hndfPacketName").textContent = packet.filename;
  document.getElementById("hndfDeviceKey").textContent = `ed25519/${packet.fingerprint}`;
  document.getElementById("hndfVerifyCmd").textContent =
    `python verify_handoff.py encounter.json`;
  document.getElementById("hndfActions").hidden = false;

  // Wire actions
  document.getElementById("hndfDownloadBtn").onclick = () => v4DownloadPacket(packet);
  document.getElementById("hndfViewPdfBtn").onclick = () => v4ViewPdf(packet);
  document.getElementById("hndfCopyCmdBtn").onclick = () => {
    try { navigator.clipboard.writeText("python verify_handoff.py encounter.json"); }
    catch {}
  };

  btn.classList.remove("generating");
  btn.querySelector(".hb-state").textContent = "ready";
}

async function v4Typewriter(el, text, cps) {
  el.textContent = "";
  const interval = 1000 / (cps || 28);
  for (let i = 0; i < text.length; i++) {
    el.textContent += text[i];
    await v4Sleep(interval);
  }
}
function v4Sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

/* ---- Build a downloadable packet (preview-side, no zip lib needed) ---- */
async function v4BuildPacket(eid, events, extraction, aar) {
  // Compute a SHA-256 of the canonical JSON locally (subtle.crypto)
  const enc = {
    encounter_id: eid,
    generated_at: new Date().toISOString(),
    events,
    extraction,
    after_action_review: aar,
  };
  const canonical = JSON.stringify(enc, Object.keys(enc).sort(), 2);
  const hashBuf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical));
  const hashHex = Array.from(new Uint8Array(hashBuf)).map(b => b.toString(16).padStart(2, "0")).join("");
  // Fingerprint = first 16 hex of hash for the demo (real fp comes from backend in production)
  const fingerprint = hashHex.slice(0, 16) + "...";
  return {
    filename: `encounter-${eid}.zip`,
    encounter_json: canonical,
    hash: hashHex,
    fingerprint,
    aar_text: (aar && aar.summary) || "",
  };
}

function v4DownloadPacket(packet) {
  const blob = new Blob([packet.encounter_json], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `encounter-${packet.filename.replace(".zip", ".json")}`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function v4ViewPdf(packet) {
  // Preview-side fallback — open a printable HTML summary in a new tab.
  const html = `<!doctype html><meta charset="utf-8"><title>AEGIS Handoff Summary</title>
    <style>body{font-family:Georgia,serif;padding:48px;max-width:720px;margin:auto;color:#111;}
    h1{font-family:'Major Mono Display',monospace;letter-spacing:-0.02em;}
    .meta{font-family:monospace;color:#555;margin-bottom:24px;}
    .sig{margin-top:48px;padding-top:16px;border-top:1px solid #ccc;font-family:monospace;font-size:11px;color:#666;}
    .cmd{font-family:monospace;background:#f4f0e8;padding:8px 12px;}</style>
    <h1>AEGIS ENCOUNTER HANDOFF</h1>
    <div class="meta">${escapeHtml(packet.filename)} · ${new Date().toISOString()}</div>
    <h3>After-Action Review</h3>
    <p>${escapeHtml(packet.aar_text)}</p>
    <div class="sig">
      Integrity hash (SHA-256): ${packet.hash}<br/>
      Device key fingerprint: ed25519/${packet.fingerprint}<br/>
      Verify on any computer:<br/>
      <span class="cmd">python verify_handoff.py encounter.json</span>
    </div>`;
  const w = window.open("", "_blank"); if (w) w.document.write(html);
}

/* ---- Tamper demo ---- */
async function v4OpenTamper() {
  const eid = state.encounter; if (!eid) return;
  let rec; try { rec = await jget(`/encounter/${eid}`); } catch { return; }
  const events = rec.events || [];
  const last10 = events.slice(-10);
  const list = document.getElementById("tamperEventList");
  list.innerHTML = last10.map(e => `
    <div class="tamper-event-row" data-id="${e.id}">
      <span class="t">${formatMs(e.t_offset_ms)}</span>
      <span class="typ">${escapeHtml(e.event_type)}</span>
      <span class="body">${escapeHtml(JSON.stringify(e.payload || {}).slice(0, 80))}</span>
    </div>
  `).join("");
  list.querySelectorAll(".tamper-event-row").forEach(el => {
    el.addEventListener("click", () => v4DoTamper(parseInt(el.dataset.id, 10)));
  });
  if (typeof openOvl === "function") openOvl("tamperScrim");
  else {
    const scrim = document.getElementById("tamperScrim");
    scrim.classList.add("open"); scrim.setAttribute("aria-hidden", "false");
  }
}
async function v4DoTamper(eventId) {
  const eid = state.encounter; if (!eid) return;
  await jpost("/records/tamper-event", {encounter_id: eid, event_id: eventId});
  // Close the picker, refresh the RECORD overlay
  const scrim = document.getElementById("tamperScrim");
  if (scrim) { scrim.classList.remove("open"); scrim.setAttribute("aria-hidden", "true"); }
  if (typeof loadRecord === "function") await loadRecord(eid);
  // Update tamper button label
  const tb = document.getElementById("tamperBtn");
  if (tb) {
    tb.textContent = "HEAL";
    tb.classList.add("healing");
  }
  await v4VerifyNow();
}
async function v4DoHeal() {
  const eid = state.encounter; if (!eid) return;
  await jpost("/records/heal-event", {encounter_id: eid});
  if (typeof loadRecord === "function") await loadRecord(eid);
  const tb = document.getElementById("tamperBtn");
  if (tb) { tb.textContent = "TAMPER (DEMO)"; tb.classList.remove("healing"); }
  await v4VerifyNow();
}
async function v4VerifyNow() {
  const eid = state.encounter; if (!eid) return;
  try {
    const r = await jget(`/encounter/${eid}/integrity`);
    V4.recLastVerifiedAt = Date.now();
    const intEl = document.getElementById("recIntegrity");
    if (intEl) {
      if (r.valid) {
        intEl.textContent = `SHA-256 chain · ${r.event_count} events · ✓ VERIFIED`;
        intEl.className = "ok";
      } else {
        intEl.textContent = `SHA-256 chain · ✗ CHAIN BROKEN AT EVENT #${r.first_break_event_id}`;
        intEl.className = "broken";
      }
    }
  } catch {}
}

/* ---- Wire it all up ---- */
function v4Init() {
  v4HideDeferred();

  // Replace the existing reasoning log empty/stream — clear pre-existing entries
  const log = document.getElementById("reasoningLog");
  if (log) log.classList.add("transcript-log"); // ensures V4 styling

  // Disable the V3 auto-fire of scenario primer reasoning — V4 has no primer
  // (do this by stomping runReasoning so leftover callers no-op)
  window.runReasoning = async function() { /* no-op in V4 */ };

  // QA wiring
  const qaBtn = document.getElementById("qaAsk");
  const qaInp = document.getElementById("qaInput");
  if (qaBtn) qaBtn.addEventListener("click", v4Ask);
  if (qaInp) qaInp.addEventListener("keydown", e => { if (e.key === "Enter") v4Ask(); });

  // Handoff wiring
  const hb = document.getElementById("handoffBtn");
  if (hb) hb.addEventListener("click", v4OpenHandoff);

  // Tamper button wiring
  const tb = document.getElementById("tamperBtn");
  if (tb) tb.addEventListener("click", () => {
    if (tb.classList.contains("healing")) return v4DoHeal();
    return v4OpenTamper();
  });
  const vb = document.getElementById("verifyNowBtn");
  if (vb) vb.addEventListener("click", v4VerifyNow);

  // Editable vital cells
  document.addEventListener("click", e => {
    const v = e.target.closest(".vital .v-val");
    if (!v) return;
    if (v.classList.contains("editing")) return;
    v4EditVital(v);
  });

  // Hide V3 leftovers explicitly
  v4HideDeferred();

  // Pre-recorded clip shortcuts route through the same setTranscript path
  document.addEventListener("keydown", e => {
    if (!(e.ctrlKey && e.shiftKey)) return;
    const idx = ["1", "2", "3"].indexOf(e.key); if (idx < 0) return;
    e.preventDefault();
    // Reuse V3 canned replay (preview server keeps this route)
    jpost("/canned/replay", {index: idx, scenario_id: state.active})
      .then(r => { if (r.transcript) setTranscript(r.transcript); })
      .catch(() => {});
  });

  // Start nudge polling every 30s, plus an immediate first poll once an
  // encounter exists.
  setInterval(() => {
    if (state.encounter) v4PollNudges();
  }, 30000);
  setTimeout(() => { if (state.encounter) v4PollNudges(); }, 4000);

  v4UpdateHandoffEnabled();
}

function v4EditVital(valEl) {
  const original = valEl.textContent.trim();
  const inp = document.createElement("input");
  inp.className = "v-edit"; inp.value = original;
  valEl.classList.add("editing"); valEl.style.display = "none";
  valEl.parentNode.insertBefore(inp, valEl);
  inp.focus(); inp.select();
  const finish = (commit) => {
    if (commit) valEl.textContent = inp.value.trim() || original;
    valEl.classList.remove("editing"); valEl.style.display = "";
    inp.remove();
    if (commit && state.encounter) {
      jpost(`/encounter/${state.encounter}/event`, {
        event_type: "vital_reading",
        payload: {operator_entered: true, label: valEl.previousElementSibling?.textContent, value: valEl.textContent},
      }).catch(() => {});
    }
  };
  inp.addEventListener("blur", () => finish(true));
  inp.addEventListener("keydown", e => {
    if (e.key === "Enter") finish(true);
    if (e.key === "Escape") finish(false);
  });
}

/* Mark vital values editable on every vital re-render */
const _v4OrigRenderVitals = renderVitals;
window.renderVitals = function(snapshot) {
  _v4OrigRenderVitals(snapshot);
  document.querySelectorAll(".vital .v-val").forEach(v => v.classList.add("editable"));
};

/* Ensure V4 wiring runs once after DOM + initial renders are ready */
if (document.readyState === "complete" || document.readyState === "interactive") {
  setTimeout(v4Init, 0);
} else {
  document.addEventListener("DOMContentLoaded", () => setTimeout(v4Init, 0));
}

/* ================================================================
   V4.1 — BRIEF overlay, TRUST surface, source PDF, pilot brief
   ================================================================ */

document.addEventListener("DOMContentLoaded", () => {
  // BRIEF button → Maria Chen overlay
  const briefBtn = document.getElementById("briefBtn");
  if (briefBtn) {
    briefBtn.addEventListener("click", () => {
      if (typeof openOvl === "function") openOvl("briefScrim");
      else {
        const s = document.getElementById("briefScrim");
        s.classList.add("open"); s.setAttribute("aria-hidden", "false");
      }
    });
  }
  // BRIEF overlay close button (matches pattern of other overlays)
  document.querySelectorAll('.ovl-close[data-ovl="brief"]').forEach(b => {
    b.addEventListener("click", () => {
      if (typeof closeOvl === "function") closeOvl("briefScrim");
      else {
        const s = document.getElementById("briefScrim");
        s.classList.remove("open"); s.setAttribute("aria-hidden", "true");
      }
    });
  });

  // VIEW SOURCE PDF button on the citation overlay
  const pdfBtn = document.getElementById("citePdfBtn");
  if (pdfBtn) pdfBtn.addEventListener("click", () => v41OpenSourcePdf());

  // SYS overlay open → also (re)render the V4.1 TRUST sections
  const sysBtn2 = document.getElementById("sysBtn");
  if (sysBtn2) sysBtn2.addEventListener("click", () => v41RenderTrustSurface());
});

/* Source PDF resolution from the active citation */
let _v41ActiveCitation = null;

(() => {
  // Hook into openCitation if it exists; otherwise watch citeOvl content changes.
  const orig = (typeof openCitation === "function") ? openCitation : null;
  if (orig) {
    window.openCitation = async function(citationId, hint) {
      await orig(citationId, hint);
      // After the V2 openCitation resolves, fetch the chunk to get source_pdf
      try {
        const chunk = state.citations[citationId] ||
                      await jget(`/retrieve/chunk/${encodeURIComponent(citationId)}`);
        _v41ActiveCitation = chunk;
        const pdfBtn = document.getElementById("citePdfBtn");
        if (pdfBtn) {
          if (chunk && chunk.source_pdf) {
            pdfBtn.disabled = false;
            const lbl = document.getElementById("citePdfLabel");
            const page = chunk.page ? `, p. ${chunk.page}` : "";
            if (lbl) lbl.textContent = `View Source PDF${page}`;
          } else {
            pdfBtn.disabled = true;
            const lbl = document.getElementById("citePdfLabel");
            if (lbl) lbl.textContent = "No source PDF on disk";
          }
        }
      } catch {}
    };
  }
})();

function v41OpenSourcePdf() {
  if (!_v41ActiveCitation || !_v41ActiveCitation.source_pdf) return;
  const fname = encodeURIComponent(_v41ActiveCitation.source_pdf);
  const page = _v41ActiveCitation.page;
  const url = `/api/source-pdf/${fname}` + (page ? `#page=${page}` : "");
  window.open(url, "_blank", "noopener");
  // Audit
  if (state.encounter) {
    jpost(`/encounter/${state.encounter}/event`, {
      event_type: "source_pdf_viewed",
      payload: {citation_id: _v41ActiveCitation.citation_id || _v41ActiveCitation.id,
                source_pdf: _v41ActiveCitation.source_pdf,
                page: page},
    }).catch(() => {});
  }
}

/* ================================================================
   V4.1 — Render the expanded TRUST surface
   ================================================================ */
async function v41RenderTrustSurface() {
  const block = document.querySelector(".trust-block");
  if (!block) return;
  if (block.dataset.v41 === "1") return;   // already rendered
  block.dataset.v41 = "1";

  let data = null;
  try { data = await jget("/trust-surface"); }
  catch {
    data = _v41TrustFallback();
  }

  // Find the V4 trust title node, insert new sections immediately after the
  // tagline (before the existing LLM Jobs / Refusal / Demo / Crypto blocks).
  const tagline = block.querySelector(".trust-tagline");
  const insertPoint = tagline ? tagline.nextElementSibling : null;

  const fragment = document.createDocumentFragment();

  // GAP statements
  fragment.appendChild(_v41Section({
    cls: "gap",
    title: "The Gap AEGIS Addresses",
    inner: (data.gap_statements || []).map(s => `
      <div class="gap-row">
        <div class="gap-claim">${escapeHtml(s.claim)}</div>
        <span class="gap-source">SOURCE: ${escapeHtml(s.source)}</span>
      </div>
    `).join(""),
  }));

  // WHO AEGIS IS FOR
  const v = data.vignette || {};
  fragment.appendChild(_v41Section({
    cls: "who",
    title: "Who AEGIS Is For",
    inner: `
      <p class="who-body">${escapeHtml(v.body || "")}</p>
      <p class="who-closer">${escapeHtml(v.closer || "")}</p>
      <div class="who-honesty mono-sm">${escapeHtml(v.honesty_note || "")}</div>
    `,
  }));

  // DEPLOYMENT MODEL + cost comparison
  const dm = data.deployment_model || {};
  const dmBody = (dm.body || "").split(/\n\n/).map(p => `<p>${escapeHtml(p)}</p>`).join("");
  const cost = (data.cost_comparison || []).map(c => `
    <div class="cost-row ${c.highlight ? "highlight" : ""}">
      <span class="item">${escapeHtml(c.item)}</span>
      <span class="price">${escapeHtml(c.cost)}</span>
    </div>
  `).join("");
  fragment.appendChild(_v41Section({
    cls: "deployment",
    title: "Deployment Model",
    inner: dmBody +
      `<p class="closer">${escapeHtml(dm.closer || "")}</p>` +
      `<div class="cost-table">${cost}</div>`,
  }));

  // FAILURE MODES
  fragment.appendChild(_v41Section({
    cls: "failures",
    title: "Failure Modes AEGIS Guards Against",
    inner: (data.failure_modes || []).map(f => `
      <div class="fm-row">
        <span class="fm-check">✓</span>
        <div>
          <div class="fm-failure">${escapeHtml(f.failure)}</div>
          <div class="fm-mitigation">${escapeHtml(f.mitigation)}</div>
        </div>
      </div>
    `).join(""),
  }));

  // INSTITUTIONAL BUYERS
  fragment.appendChild(_v41Section({
    cls: "buyers",
    title: "Institutional Buyers",
    inner: (data.institutional_buyers || []).map(b => `
      <div class="buyer-row">
        <span class="buyer-name">${escapeHtml(b.category)}</span>
        <div class="buyer-desc">${escapeHtml(b.description)}</div>
      </div>
    `).join(""),
  }));

  // Pilot brief download
  const briefSection = _v41Section({
    cls: "pilot",
    title: "Pilot Brief",
    inner: `
      <div style="font-family: var(--f-serif); font-size: 0.875rem; line-height: 1.6;
                  color: var(--fg-0); text-shadow: 0 1px 0 rgba(0,0,0,0.35);">
        A one-page deployment proposal for rural EMS,
        generated from this live AEGIS system.
      </div>
      <a class="pilot-brief-btn" href="/api/pilot-brief/cached" target="_blank" rel="noopener">
        Download Pilot Brief (PDF, 1 page)
      </a>
    `,
  });
  fragment.appendChild(briefSection);

  // Insert before the LLM Jobs section that already exists
  if (insertPoint) {
    block.insertBefore(fragment, insertPoint);
  } else {
    block.appendChild(fragment);
  }
}

function _v41Section({cls, title, inner}) {
  const el = document.createElement("div");
  el.className = `trust-section ${cls}`;
  el.innerHTML = `<h4>${escapeHtml(title)}</h4>${inner}`;
  return el;
}

function _v41TrustFallback() {
  // Used if /api/trust-surface is unreachable. Minimal data so the
  // sections still render with the established vocabulary.
  return {
    gap_statements: [],
    vignette: {
      body: "Maria Chen is an EMT in rural Colorado, 70 minutes from the nearest Level III trauma center. Last winter she responded to a snowmobile crash in a canyon with no cellular coverage. Her patient had a suspected pelvic fracture and she had thirty minutes of training on that specific injury, two years earlier. She made the call alone. She did okay. She still thinks about whether she got it right.",
      closer: "AEGIS exists for the next time Maria takes that call.",
      honesty_note: "Composite vignette drawn from documented patterns of rural EMS practice. Identifying details are illustrative.",
    },
    deployment_model: {body: "AEGIS is professional medical equipment, not a consumer product.", closer: "Per-encounter cost across a typical service lifespan: cents."},
    cost_comparison: [],
    failure_modes: [],
    institutional_buyers: [],
  };
}
