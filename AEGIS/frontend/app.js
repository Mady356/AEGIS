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
    case "intake":         return escapeHtml((p.text || "—").slice(0, 200));
    case "assessment":     return escapeHtml((p.text || "—").slice(0, 200));
    case "guidance_step":  return escapeHtml(p.step_label || `Step ${p.step_index}`);
    case "checklist_item": return `<em>${p.done ? "Completed" : "Uncompleted"}:</em> ${escapeHtml(p.step_label || `Step ${p.step_index}`)}`;
    case "vital_reading":  return (p.vitals || []).map(v => `${v.label} ${v.val}${v.unit}`).join(" · ");
    case "reference_view": return `Opened citation <span class="cite">[${escapeHtml(p.citation_id || "—")}]</span>`;
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
  const sub = $("#bootSub");
  const text = "AUTONOMOUS EMERGENCY GUIDANCE & INTELLIGENCE SYSTEM";
  setTimeout(() => $("#bootMark").classList.add("in"), 80);
  let i = 0;
  setTimeout(function tick() {
    if (i <= text.length) { sub.textContent = text.slice(0, i++); setTimeout(tick, 22); }
  }, 520);
  setTimeout(() => $("#bootMeta").classList.add("in"), 1100);
  setTimeout(() => {
    $("#boot").classList.add("fade");
    $("#cockpit").classList.add("live");
    setTimeout(() => $("#boot").remove(), 700);
  }, 2200);
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
  // Reveal boot, then run normal init
  $("#boot").hidden = false;
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
