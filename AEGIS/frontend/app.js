/* ============================================================
   AEGIS V5 — frontend wiring
   ============================================================
   - Top bar: clock, status pills, BRIEF / RECORD / SYS overlays
   - Left column: scenario, allergies, mission elapsed,
                   environment, context log
   - Center column: crisis strip, current step, jump-to-step,
                    question, mark step complete
   - Right column: vitals 2x2 grid, why-this-matters, checklist,
                   ask aegis (QA)
   - Procedural state advances via /api/encounter/{id}/advance-step
   ============================================================ */

(() => {
  "use strict";

  const $  = (id) => document.getElementById(id);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const state = {
    scenarioId: null,
    scenarioName: "—",
    patientLabel: "PT-—",
    encounterId: null,
    elapsedStartMs: null,
    vitalsLastUpdate: 0,
    currentStep: null,
    stepGraph: [],
    stepStatus: {},
    // V6 — index of the furthest-reached step. Updated only when the
    // operator advances forward; backward navigation (goToStep) leaves
    // it untouched so the cockpit can show a "reviewing" indicator.
    latestStepIdx: 0,
    allergies: [],
    askBusy: false,
    // V5.1 — situation-aware chat
    situation: "",          // operator-supplied; persisted via /api/encounter/{id}/situation
    chatHistory: [],        // [{role:'user'|'assistant', content:str}], in-memory
  };

  document.addEventListener("DOMContentLoaded", boot);

  async function boot() {
    bindTopBar();
    bindCenterColumn();
    bindAsk();
    bindSituation();
    bindOverlays();

    startElapsed();

    $("profileScreen").hidden = true;
    $("cockpit").hidden = false;

    bootIntake();
  }

  // V6 — intake-first. The cockpit boots with no scenario loaded.
  // The operator's typed situation is POSTed to /api/encounter/begin,
  // where the LLM produces the title, patient label, ordered procedural
  // steps, and an initial brief. Procedural-steps load + vitals/context
  // polling start inside submitIntakeSituation() once the encounter exists.
  function bootIntake() {
    $("scenarioName").textContent = "—";
    $("ptId").textContent = "PT-—";
    showIntakeOverlay();
  }

  // Top bar -------------------------------------------------------
  // V6 — only Mission Elapsed remains as a time display. The Z clock
  // and the vitals-age "00s ago" indicator have been removed.
  function startElapsed() {
    state.elapsedStartMs = Date.now();
    const z = (n) => String(n).padStart(2, "0");
    setInterval(() => {
      const ms = Date.now() - state.elapsedStartMs;
      const s = Math.floor(ms / 1000);
      $("elapsed").textContent =
        `T+${z(Math.floor(s / 3600))}:${z(Math.floor((s % 3600) / 60))}:${z(s % 60)}`;
    }, 1000);
  }

  function bindTopBar() {
    $("briefBtn").addEventListener("click", () => openOvl("brief"));
    $("recordBtn").addEventListener("click", () => openOvl("rec"));
    $("sysBtn").addEventListener("click", openSys);
  }

  // Overlays ------------------------------------------------------
  function bindOverlays() {
    $$("[data-ovl]").forEach((b) => {
      b.addEventListener("click", () => closeOvl(b.dataset.ovl));
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        ["brief", "rec", "sys", "cite"].forEach(closeOvl);
      }
    });
    $$(".ovl-scrim").forEach((s) => {
      s.addEventListener("click", (e) => {
        if (e.target === s) {
          const id = s.id.replace("Scrim", "");
          closeOvl(id);
        }
      });
    });
  }

  function openOvl(name) {
    const el = $(`${name}Scrim`);
    if (el) el.classList.add("open");
  }
  function closeOvl(name) {
    const el = $(`${name}Scrim`);
    if (el) el.classList.remove("open");
  }

  async function openSys() {
    openOvl("sys");
    try {
      const r = await fetch("/api/system/status");
      if (!r.ok) throw new Error();
      const j = await r.json();
      $("sysBody").textContent = JSON.stringify(j, null, 2);
    } catch {
      $("sysBody").textContent = "System status unavailable.";
    }
  }

  // Procedural steps ----------------------------------------------
  async function loadProceduralSteps() {
    if (!state.encounterId) return;
    try {
      const r = await fetch(`/api/encounter/${state.encounterId}/procedural-steps`);
      if (!r.ok) throw new Error();
      const j = await r.json();
      state.stepGraph = j.graph || [];
      state.stepStatus = {};
      state.stepGraph.forEach((s) => (state.stepStatus[s.id] = false));
      renderStep(j.current);
      renderChecklist();
    } catch {}
  }

  function renderStep(step) {
    if (!step) return;

    if (step.complete) {
      $("csTitle").textContent = "ENCOUNTER COMPLETE";
      $("csInstruction").textContent =
        "All procedural steps marked complete. Download the transfer PDF and hand it to the receiving clinician.";
      $("csIcon").innerHTML = svgIcon("check");
      $("csProgressLbl").textContent = `STEP ${step.step_count} OF ${step.step_count}`;
      $("csProgressFill").style.width = "100%";
      $("jumpSection").hidden = true;
      $("questionSection").hidden = true;
      $("completeConfirm").textContent = "Download the patient transfer PDF.";
      $("completeBtn").querySelector(".complete-primary span:first-child").textContent = "Download Transfer PDF";
      Object.keys(state.stepStatus).forEach((k) => (state.stepStatus[k] = true));
      renderChecklist();
      return;
    }

    state.currentStep = step;

    // V6 — when the operator is on a step earlier than the furthest
    // reached one (i.e. they clicked a past row to review), show a
    // small "reviewing previous step" tag on the CURRENT STEP card.
    const stepCard = $("currentStep");
    if (stepCard) {
      const stepIdx = state.stepGraph.findIndex((s) => s.id === step.id);
      const reviewing = stepIdx >= 0 && stepIdx < state.latestStepIdx;
      stepCard.classList.toggle("reviewing", reviewing);
    }

    const fade = $("csFade");
    fade.classList.add("hidden");
    setTimeout(() => {
      $("csIcon").innerHTML = svgIcon(step.icon);
      $("csTitle").textContent = step.title;
      // Render inline [CITATION_ID] markers as clickable pills that
      // open the underlying corpus chunk in the citation overlay.
      const ci = $("csInstruction");
      ci.innerHTML = renderTextWithCitations(step.instruction || "");
      wireCitationPills(ci);
      fade.classList.remove("hidden");
    }, 160);

    const idx = step.step_index || 1;
    const total = step.step_count || state.stepGraph.length || 1;
    $("csProgressLbl").textContent = `STEP ${idx} OF ${total}`;
    $("csProgressFill").style.width = `${(idx / total) * 100}%`;

    $("completeConfirm").textContent = confirmLine(step);

    renderJumpCards(step.jump_to || []);
    renderQuestion(step.question);
    // V6 — re-render the checklist so its prerequisites-only window
    // expands to include the new current step the moment it becomes
    // active. Without this the checklist lags one click behind.
    renderChecklist();
  }

  function confirmLine(step) {
    // V6 — prefer the LLM-supplied per-step affirmation; it's written
    // by the intake call to mirror the exact step the operator just
    // ran (see backend/llm_agents.py _normalize_intake).
    const llmAff = (step.affirmation || "").trim();
    if (llmAff) return llmAff;

    // Legacy hardcoded scenarios (battlefield / maritime / disaster)
    // hit these substring rules.
    const t = (step.title || "").toLowerCase();
    if (t.includes("bleed"))      return "I have stopped the bleeding.";
    if (t.includes("tourniquet")) return "I have placed the tourniquet.";
    if (t.includes("verify"))     return "I have verified cessation.";
    if (t.includes("mark"))       return "I have marked the casualty.";
    if (t.includes("circulation"))return "I have checked circulation.";
    if (t.includes("evac"))       return "Evacuation is staged.";
    if (t.includes("scene"))      return "The scene is safe.";
    if (t.includes("compression"))return "I am delivering compressions.";
    if (t.includes("breath"))     return "I have delivered the breaths.";
    if (t.includes("aed"))        return "I have placed the AED.";
    if (t.includes("iv"))         return "I have established access.";
    if (t.includes("airway"))     return "The airway is placed.";
    if (t.includes("paracetamol"))return "I have given the dose.";
    if (t.includes("ors"))        return "I have started ORS.";
    if (t.includes("weight"))     return "I have confirmed the weight.";
    if (t.includes("review"))     return "I have queued the patient.";
    if (t.includes("reassess"))   return "I have reassessed the patient.";

    // Generic fallback for LLM-driven steps that didn't ship an
    // affirmation field for some reason — derive from the title.
    const titleClean = (step.title || "").replace(/\s+/g, " ").trim();
    if (titleClean) {
      // Use the title in title-case form so the bare imperative
      // ("USE AED") becomes the natural-sounding "I have used AED".
      return `I have completed ${titleClean.toLowerCase()}.`;
    }
    return "I have completed this step.";
  }

  function renderJumpCards(cards) {
    const list = $("jumpList");
    list.innerHTML = "";
    if (!cards.length) {
      $("jumpSection").hidden = true;
      return;
    }
    $("jumpSection").hidden = false;
    cards.forEach((c) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = "jump-card";
      el.innerHTML = `
        <span class="j-icon">${svgIcon(c.icon)}</span>
        <span class="j-text">
          <span class="j-title">${escapeHtml(c.title)}</span>
          <span class="j-desc">${escapeHtml(c.description)}</span>
        </span>
        <span class="j-chev"><svg viewBox="0 0 24 24" stroke="currentColor" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"/></svg></span>
      `;
      el.addEventListener("click", () => jumpToStep(c.id));
      list.appendChild(el);
    });
  }

  function renderQuestion(q) {
    const sec = $("questionSection");
    if (!q) { sec.hidden = true; return; }
    sec.hidden = false;
    $("questionText").textContent = q.text;
    $("qYes").onclick = () => answerQuestion("yes");
    $("qNo").onclick  = () => answerQuestion("no");
  }

  async function answerQuestion(decision) {
    const btn = decision === "yes" ? $("qYes") : $("qNo");
    btn.classList.add("flash");
    setTimeout(() => btn.classList.remove("flash"), 200);
    await advance(decision);
  }

  // V6 — backward navigation. The checklist now hands every graph
  // entry the full step shape (instruction, why_matters, icon,
  // affirmation, citations) so going back renders the original step
  // card faithfully — not the blanked-out "synthetic step from title
  // alone" the V4 jumpToStep produced.
  async function goToStep(stepId) {
    if (!state.encounterId) return;
    const target = state.stepGraph.find((s) => s.id === stepId);
    if (!target) return;
    const idx = state.stepGraph.findIndex((s) => s.id === stepId);
    if (idx < 0) return;

    // Audit event so the encounter chain captures every navigation
    // (the integrity hash on the transfer PDF reflects this).
    fetch(`/api/encounter/${state.encounterId}/event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_type: "step_returned_to",
        payload: {
          from: state.currentStep && state.currentStep.id,
          to: stepId,
        },
      }),
    }).catch(() => {});

    // Render the chosen step from the cached full graph entry.
    const full = {
      id: target.id,
      title: target.title,
      icon: target.icon || stepIconFor(target.id),
      instruction: target.instruction || target.checklist_text || "",
      checklist_text: target.checklist_text || target.title || "",
      why_matters: target.why_matters || "",
      affirmation: target.affirmation || "",
      question: target.question || null,
      jump_to: [],
      step_index: idx + 1,
      step_count: state.stepGraph.length,
    };
    renderStep(full);
  }

  // Backwards-compatible alias — the existing jump-card UI (used by
  // legacy hardcoded scenarios) calls jumpToStep(); route it through
  // the new path so both backward and forward jumps share the code.
  const jumpToStep = goToStep;

  function stepIconFor(id) {
    if (id.includes("bleed") || id.includes("tourniquet")) return "crosshair";
    if (id.includes("circ") || id.includes("compress") || id.includes("reassess") || id.includes("verify")) return "pulse";
    if (id.includes("evac")) return "ambulance";
    if (id.includes("breath") || id.includes("airway")) return "breath";
    if (id.includes("aed")) return "bolt";
    if (id.includes("iv") || id.includes("ors") || id.includes("fluid")) return "drop";
    if (id.includes("paracet")) return "pill";
    if (id.includes("weight")) return "ruler";
    if (id.includes("scene") || id.includes("safety")) return "shield";
    return "tag";
  }

  async function advance(decision) {
    if (!state.encounterId || !state.currentStep) return;
    setThinking(true);
    try {
      const r = await fetch(`/api/encounter/${state.encounterId}/advance-step`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ step_id: state.currentStep.id, decision }),
      });
      const j = await r.json();
      state.stepStatus[state.currentStep.id] = true;
      // V6 — bump the high-water mark so the "reviewing previous step"
      // indicator can detect when the operator clicks back. Only the
      // forward path (advance) moves this; goToStep leaves it alone.
      if (j.next && !j.next.complete) {
        const nextIdx = state.stepGraph.findIndex((s) => s.id === j.next.id);
        if (nextIdx > state.latestStepIdx) state.latestStepIdx = nextIdx;
      } else if (j.next && j.next.complete) {
        state.latestStepIdx = state.stepGraph.length - 1;
      }
      renderChecklist();
      renderStep(j.next);
    } catch {}
    finally { setThinking(false); }
  }

  function bindCenterColumn() {
    $("completeBtn").addEventListener("click", async () => {
      $("completeBtn").classList.add("flash");
      setTimeout(() => $("completeBtn").classList.remove("flash"), 200);
      if ($("csTitle").textContent === "ENCOUNTER COMPLETE") {
        await buildHandoff();
        return;
      }
      await advance(null);
    });
  }

  // V6 — handoff is a single comprehensive PDF (was a signed zip in V4).
  // The PDF itself contains every clinically relevant fact plus the
  // integrity hash + signature in its footer, so the receiving clinician
  // needs only this one file.
  async function buildHandoff() {
    if (!state.encounterId) return;
    if (state.handoffInFlight) return;
    state.handoffInFlight = true;
    setThinking(true);
    const confirmEl = $("completeConfirm");
    if (confirmEl) confirmEl.textContent = "Generating transfer PDF…";
    try {
      const r = await fetch("/api/handoff/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ encounter_id: state.encounterId }),
      });
      if (!r.ok) {
        const detail = await r.text().catch(() => "");
        throw new Error(`HTTP ${r.status} ${detail.slice(0, 120)}`);
      }
      // fetch + Content-Disposition alone does not auto-download; we
      // need to materialize the bytes as a Blob and trigger an anchor.
      const hash = r.headers.get("X-AEGIS-Bundle-Hash") || "";
      const cd = r.headers.get("Content-Disposition") || "";
      const m = /filename="?([^";]+)"?/i.exec(cd);
      const filename = (m && m[1]) ||
        `aegis-transfer-${state.encounterId}.pdf`;
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      if (confirmEl) {
        confirmEl.innerHTML =
          `Transfer PDF saved · <span class="mono-sm">${escapeHtml(filename)}</span>` +
          (hash ? ` · integrity <span class="mono-sm" title="${escapeHtml(hash)}">` +
            `${escapeHtml(hash.slice(0, 12))}…</span>` : "");
      }
    } catch (e) {
      if (confirmEl) confirmEl.textContent = `Handoff failed: ${e.message || e}`;
      console.error("buildHandoff failed:", e);
    } finally {
      setThinking(false);
      state.handoffInFlight = false;
    }
  }

  function setThinking(on) {
    $("crisisThink").classList.toggle("on", on);
  }

  // Checklist ----------------------------------------------------
  // V6 — the checklist is now a "what's already done + what you're on
  // right now" list, not a forward-looking roadmap. Future steps are
  // hidden until the operator advances onto them. This matches the
  // prerequisites-of-the-current-step model: the operator sees only
  // what should already be true (or actively in progress) by now.
  function renderChecklist() {
    const list = $("checklist");
    list.innerHTML = "";
    const total = state.stepGraph.length;
    const currentIdx = state.currentStep
      ? state.stepGraph.findIndex((s) => s.id === state.currentStep.id)
      : -1;

    // Visible window: steps 0..currentIdx (prerequisites + current).
    // If we don't have a current step yet (e.g. the encounter just
    // started and no step renders), fall back to showing nothing.
    const visibleEnd = currentIdx >= 0 ? currentIdx + 1 : 0;
    let done = 0;

    for (let i = 0; i < visibleEnd; i++) {
      const s = state.stepGraph[i];
      const isDone = !!state.stepStatus[s.id];
      const isActive = state.currentStep && state.currentStep.id === s.id;
      if (isDone) done++;

      const li = document.createElement("li");
      li.className = "chk-row";
      if (isDone) li.classList.add("done");
      if (isActive) li.classList.add("active");
      // Past rows (not the active one) are clickable to navigate back;
      // the cursor + a hover highlight live in CSS.
      if (!isActive) li.classList.add("nav");
      li.title = isActive
        ? "Current step"
        : "Click to review this step";
      li.innerHTML = `
        <span class="chk-box" data-role="toggle"
              title="Toggle complete">
          <svg viewBox="0 0 24 24" stroke="currentColor" fill="none" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="5 12 10 17 19 7"/></svg>
        </span>
        <span class="chk-text">${escapeHtml(s.checklist_text)}</span>
        <span class="chk-time"></span>
      `;
      // V6 — split the click handler. Clicking the checkbox toggles
      // the done state (kept from V5). Clicking anywhere else on the
      // row navigates back to that step. The active row is a no-op
      // for navigation since you're already there.
      li.addEventListener("click", (ev) => {
        const onCheckbox = ev.target.closest('[data-role="toggle"]');
        if (onCheckbox) {
          state.stepStatus[s.id] = !state.stepStatus[s.id];
          renderChecklist();
          return;
        }
        if (!isActive) {
          goToStep(s.id);
        }
      });
      list.appendChild(li);
    }

    // Header count keeps the operator's mental model of total scope —
    // "01 / 05" still reads as "one of five overall", but only the
    // first one is shown until they reach step 2.
    $("chkCount").textContent =
      `${String(done).padStart(2, "0")} / ${String(total).padStart(2, "0")}`;
  }

  function highlightActiveChecklistRow() {
    // The active row is now always the last visible one (the current
    // step), since future rows aren't rendered. Re-running render
    // after every step advance keeps this in sync; this helper is
    // kept so existing callers don't break.
    $$(".chk-row").forEach((r) => r.classList.remove("active"));
    if (!state.currentStep) return;
    const rows = $$(".chk-row");
    const last = rows[rows.length - 1];
    if (last) last.classList.add("active");
  }

  // Vitals -------------------------------------------------------
  async function pollVitals() {
    if (!state.scenarioId) return;
    try {
      const elapsedMs = Date.now() - state.elapsedStartMs;
      const checklistArr = state.stepGraph.map((s) => state.stepStatus[s.id] ? 1 : 0);
      const r = await fetch("/api/vitals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scenario_id: state.scenarioId,
          elapsed_ms: elapsedMs,
          checklist: checklistArr,
        }),
      });
      const j = await r.json();
      renderVitals(j.vitals || []);
      state.vitalsLastUpdate = Date.now();
    } catch {}
  }

  // V6 — when a vital channel reports no usable value (null, undefined,
  // empty string, or NaN), render an em-dash plus a "no signal"
  // annotation rather than leaving the cell visually empty. The
  // annotation reads via a dedicated `.v-nosignal` slot below the value.
  function isMissingVital(v) {
    if (v == null) return true;
    if (typeof v === "string" && !v.trim()) return true;
    if (typeof v === "number" && !Number.isFinite(v)) return true;
    return false;
  }

  function renderVitals(vitals) {
    const grid = $("vitalsGrid");
    if (!grid.children.length) {
      grid.innerHTML = vitals.map((v) => {
        const missing = isMissingVital(v.val);
        return `
        <div class="vital-cell ${v.cls || ""}${missing ? " missing" : ""}" data-k="${escapeHtml(v.label)}">
          <span class="v-lbl">${escapeHtml(v.label)}</span>
          <div class="v-val-row">
            <span class="v-val">${missing ? "—" : escapeHtml(String(v.val))}</span>
            <span class="v-unit">${missing ? "" : escapeHtml(v.unit)}</span>
          </div>
          <span class="v-nosignal">${missing ? "no signal" : ""}</span>
          <svg class="v-spark" viewBox="0 0 100 28" preserveAspectRatio="none"><path d=""/></svg>
        </div>
      `;
      }).join("");
    }
    vitals.forEach((v) => {
      const cell = grid.querySelector(`[data-k="${cssEscape(v.label)}"]`);
      if (!cell) return;
      const missing = isMissingVital(v.val);
      cell.className = `vital-cell ${v.cls || ""}${missing ? " missing" : ""}`;
      const valEl = cell.querySelector(".v-val");
      const nextVal = missing ? "—" : String(v.val);
      if (valEl.textContent !== nextVal) {
        valEl.style.opacity = "0";
        setTimeout(() => {
          valEl.textContent = nextVal;
          valEl.style.opacity = "1";
        }, 150);
      }
      cell.querySelector(".v-unit").textContent = missing ? "" : v.unit;
      const ns = cell.querySelector(".v-nosignal");
      if (ns) ns.textContent = missing ? "no signal" : "";
      const path = cell.querySelector(".v-spark path");
      path.setAttribute("d", missing ? "" : sparkPath(v.spark || []));
    });
  }

  function sparkPath(samples) {
    if (!samples.length) return "";
    const max = Math.max(...samples), min = Math.min(...samples);
    const span = (max - min) || 1;
    const w = 100, h = 28, n = samples.length;
    return samples.map((s, i) => {
      const x = (i / Math.max(n - 1, 1)) * w;
      const y = h - ((s - min) / span) * h;
      return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    }).join(" ");
  }

  // Context log --------------------------------------------------
  let _lastCtxCount = 0;
  async function pollContextLog() {
    if (!state.encounterId) return;
    try {
      const r = await fetch(`/api/encounter/${state.encounterId}/context-log`);
      const j = await r.json();
      renderContextLog(j.entries || []);
    } catch {}
  }

  function renderContextLog(entries) {
    const list = $("ctxList");
    const wasAtBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 30;
    list.innerHTML = entries.map((e, i) => `
      <div class="ctx-row${i >= _lastCtxCount ? " flash" : ""}">
        <span class="t">${escapeHtml(e.t)}</span>
        <span class="body">${escapeHtml(e.text)}</span>
      </div>
    `).join("");
    _lastCtxCount = entries.length;
    if (wasAtBottom) list.scrollTop = list.scrollHeight;

    const allergies = entries
      .map((e) => extractAllergy(e.text))
      .filter(Boolean);
    if (allergies.length && JSON.stringify(allergies) !== JSON.stringify(state.allergies)) {
      state.allergies = allergies;
      renderAllergies();
    }
  }

  function extractAllergy(text) {
    const m = text && text.match(/allerg(?:y|ic)\s+to\s+([a-z][a-z\- ]+)/i);
    return m ? m[1].trim().toLowerCase() : null;
  }

  function renderAllergies() {
    const el = $("allergyList");
    if (!state.allergies.length) {
      el.innerHTML = '<div class="allergy-empty">Not yet captured</div>';
      return;
    }
    el.innerHTML = state.allergies
      .map((a) => `<div class="allergy-item">${escapeHtml(a)}</div>`)
      .join("");
  }

  // Ask AEGIS — multi-turn chat ---------------------------------
  function bindAsk() {
    $("askBtn").addEventListener("click", askQuery);
    $("askInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        askQuery();
      }
    });
  }

  function renderChat() {
    const out = $("askOutput");
    if (!out) return;
    if (!state.chatHistory.length) {
      out.classList.add("empty");
      out.innerHTML = "";
      return;
    }
    out.classList.remove("empty");
    out.classList.add("chat-log");
    out.innerHTML = state.chatHistory.map((turn, i) => {
      const role = turn.role === "user" ? "user" : "assistant";
      // Inline [CITATION_ID] markers in the assistant's text become
      // clickable pills directly. The optional citations array is no
      // longer appended as trailing pills since the inline form is more
      // useful — the operator sees which sentence each source backs.
      const content = role === "assistant"
        ? renderTextWithCitations(turn.content || "")
        : escapeHtml(turn.content || "");
      const meta = turn.meta
        ? `<div class="ask-foot">${escapeHtml(turn.meta)}</div>`
        : "";
      return `<div class="chat-bubble chat-${role}" data-i="${i}">
        <div class="bubble-body">${content}</div>${meta}
      </div>`;
    }).join("");
    wireCitationPills(out);
    // scroll to bottom
    out.scrollTop = out.scrollHeight;
  }

  async function askQuery() {
    if (state.askBusy) return;
    const q = $("askInput").value.trim();
    if (!q) return;
    $("askInput").value = "";
    state.askBusy = true;

    // Append user turn locally and render immediately.
    state.chatHistory.push({ role: "user", content: q });
    // Placeholder assistant bubble shows "thinking…" until reply lands.
    state.chatHistory.push({ role: "assistant", content: "…" });
    renderChat();

    const t0 = performance.now();
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          encounter_id: state.encounterId,
          scenario_id: state.scenarioId,
          situation: state.situation || "",
          // Send history WITHOUT the placeholder; backend expects the
          // last entry to be the user's question.
          history: state.chatHistory.slice(0, -1).map(t => ({
            role: t.role, content: t.content,
          })),
          current_step: state.currentStep ? {
            id: state.currentStep.id,
            title: state.currentStep.title,
            instruction: state.currentStep.instruction,
          } : null,
        }),
      });
      if (!r.ok) {
        const err = await r.text().catch(() => "");
        throw new Error(`HTTP ${r.status} ${err.slice(0, 120)}`);
      }
      const j = await r.json();
      const reply = j.reply || "(no reply)";
      const latency = ((performance.now() - t0) / 1000).toFixed(1) + "s";
      const cites = j.citations || [];
      console.info("[aegis] chat latency:", latency,
                   "·", cites.length, "chunks");
      // Replace placeholder with real assistant turn. The visible meta
      // line carries only the citation count (clinically meaningful);
      // latency is logged to the dev console only.
      state.chatHistory[state.chatHistory.length - 1] = {
        role: "assistant",
        content: reply,
        citations: cites,
        meta: cites.length
          ? `${cites.length} CHUNK${cites.length === 1 ? "" : "S"}`
          : "",
      };
      renderChat();
    } catch (e) {
      state.chatHistory[state.chatHistory.length - 1] = {
        role: "assistant",
        content: `(chat failed: ${e.message || e})`,
        meta: "ERROR",
      };
      renderChat();
    } finally {
      state.askBusy = false;
    }
  }

  // Situation -----------------------------------------------------
  function bindSituation() {
    const ta = $("situationInput");
    const btn = $("situationSave");
    if (!ta || !btn) return;
    btn.addEventListener("click", saveSituation);
    ta.addEventListener("blur", saveSituation);
    ta.addEventListener("keydown", (e) => {
      // Cmd/Ctrl+Enter saves without leaving focus
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        saveSituation();
      }
    });
  }

  function showIntakeOverlay() {
    const ovl = $("intakeScrim");
    if (!ovl) return;
    openOvl("intake");
    const ta = $("intakeSituationInput");
    if (ta) {
      ta.value = state.situation || "";
      // give the textarea focus once the overlay's transition settles
      setTimeout(() => ta.focus(), 120);
    }
    const submit = $("intakeSubmitBtn");
    const skip = $("intakeSkipBtn");
    if (submit && !submit._wired) {
      submit._wired = true;
      submit.addEventListener("click", submitIntakeSituation);
    }
    if (skip && !skip._wired) {
      skip._wired = true;
      skip.addEventListener("click", () => closeOvl("intake"));
    }
    if (ta && !ta._wired) {
      ta._wired = true;
      ta.addEventListener("keydown", (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
          e.preventDefault();
          submitIntakeSituation();
        }
      });
    }
  }

  // V6 — Begin Encounter. POST the typed situation to /api/encounter/begin;
  // the backend asks the LLM to produce the title, patient label, ordered
  // procedural steps, and an initial brief. We then bind state, render
  // the brief into the chat panel, and start procedural-steps + vitals
  // + context-log polling against the new encounter.
  //
  // Shared by the intake overlay submit and the left-column SITUATION panel
  // save (when no encounter exists yet — operator may have closed intake).
  async function beginEncounterFromText(text) {
    text = (text || "").trim();
    if (!text) return false;
    if (state.beginInFlight) return false;
    state.beginInFlight = true;

    const submit = $("intakeSubmitBtn");
    if (submit) { submit.disabled = true; submit.textContent = "Generating…"; }
    const sitStatus = $("sitStatus");
    if (sitStatus) sitStatus.textContent = "generating…";

    try {
      const r = await fetch("/api/encounter/begin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ situation: text }),
      });
      if (!r.ok) {
        const err = await r.text().catch(() => "");
        throw new Error(`HTTP ${r.status} ${err.slice(0, 160)}`);
      }
      const j = await r.json();

      state.encounterId = j.encounter_id || j.id;
      state.scenarioId = j.scenario_id;
      state.scenarioName = j.title || "Encounter";
      state.patientLabel = j.patient_label || "PT-—";
      state.situation = text;

      $("scenarioName").textContent = state.scenarioName;
      $("ptId").textContent = state.patientLabel;
      const panel = $("situationInput");
      if (panel && panel.value !== text) panel.value = text;
      if (sitStatus) sitStatus.textContent = "saved";

      // Render the LLM-produced brief as the first assistant turn.
      // V6 — the latency is logged to the dev console only; the chat
      // bubble shows just "BRIEF" so the operator's eye isn't drawn
      // to a millisecond count that has no clinical meaning.
      if (j.brief && j.brief.text) {
        if (j.latency_ms !== undefined) {
          console.info("[aegis] brief latency:", j.latency_ms, "ms");
        }
        state.chatHistory.push({ role: "user",
                                  content: "Brief me on this encounter." });
        state.chatHistory.push({
          role: "assistant",
          content: j.brief.text,
          citations: [],
          meta: "BRIEF",
        });
        renderChat();
      }

      closeOvl("intake");

      // Now that the encounter exists, load steps and start polling.
      await Promise.all([
        loadProceduralSteps(),
        pollVitals(),
        pollContextLog(),
      ]);
      if (!state.pollingStarted) {
        state.pollingStarted = true;
        setInterval(pollVitals, 1500);
        setInterval(pollContextLog, 4000);
      }

      if (submit) {
        submit.disabled = false;
        submit.textContent = "Begin Encounter";
      }
      return true;
    } catch (e) {
      if (submit) {
        submit.disabled = false;
        submit.textContent = "Retry";
      }
      if (sitStatus) sitStatus.textContent = "begin failed";
      console.error("Begin Encounter failed:", e);
      return false;
    } finally {
      state.beginInFlight = false;
    }
  }

  async function submitIntakeSituation() {
    const ta = $("intakeSituationInput");
    const text = ((ta && ta.value) || "").trim();
    if (!text) return;       // V6: situation is required; do nothing on empty
    await beginEncounterFromText(text);
  }

  let _sitSaveTimer = null;
  async function saveSituation() {
    const ta = $("situationInput");
    if (!ta) return;
    const text = (ta.value || "").trim();
    if (text === state.situation) return;       // no-op
    if (!text) { state.situation = ""; return; } // POST refuses empty

    // V6: if no encounter exists yet (operator closed intake and typed
    // here directly), this save IS the begin-encounter trigger. Route
    // through the LLM intake flow instead of the situation event POST.
    if (!state.encounterId) {
      await beginEncounterFromText(text);
      return;
    }

    const st = $("sitStatus");
    if (st) st.textContent = "saving…";
    if (_sitSaveTimer) clearTimeout(_sitSaveTimer);
    _sitSaveTimer = setTimeout(async () => {
      try {
        const r = await fetch(
          `/api/encounter/${state.encounterId}/situation`,
          { method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }) }
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        state.situation = text;
        if (st) st.textContent = "saved";
      } catch (e) {
        if (st) st.textContent = "save failed";
      }
    }, 200);
  }

  async function openCitation(id) {
    if (!id) return;
    try {
      const r = await fetch(`/api/retrieve/chunk/${encodeURIComponent(id)}`);
      const j = await r.json();
      $("citeOvlTitle").textContent = id;
      $("citeText").textContent = j.text || j.content || "(no text)";
      $("citeMeta").textContent = `${j.document || ""} ${j.section || ""}`.trim();
      openOvl("cite");
    } catch {}
  }

  // Icons -------------------------------------------------------
  function svgIcon(name) {
    const s = `stroke="currentColor" fill="none" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"`;
    switch (name) {
      case "crosshair":
        return `<svg viewBox="0 0 56 56" ${s}><circle cx="28" cy="28" r="20"/><circle cx="28" cy="28" r="3"/><line x1="28" y1="2" x2="28" y2="14"/><line x1="28" y1="42" x2="28" y2="54"/><line x1="2" y1="28" x2="14" y2="28"/><line x1="42" y1="28" x2="54" y2="28"/></svg>`;
      case "pulse":
        return `<svg viewBox="0 0 56 56" ${s}><polyline points="2,32 14,32 20,16 28,46 36,22 42,32 54,32"/></svg>`;
      case "ambulance":
        return `<svg viewBox="0 0 56 56" ${s}><rect x="4" y="18" width="36" height="22" rx="2"/><path d="M40 24h8l4 6v10H40z"/><circle cx="16" cy="44" r="4"/><circle cx="42" cy="44" r="4"/><line x1="20" y1="26" x2="28" y2="26"/><line x1="24" y1="22" x2="24" y2="30"/></svg>`;
      case "tag":
        return `<svg viewBox="0 0 56 56" ${s}><path d="M30 6H10v20l24 24 20-20z"/><circle cx="18" cy="18" r="2.5"/></svg>`;
      case "shield":
        return `<svg viewBox="0 0 56 56" ${s}><path d="M28 4 L48 12 V28 C48 40 38 48 28 52 C18 48 8 40 8 28 V12 Z"/></svg>`;
      case "bolt":
        return `<svg viewBox="0 0 56 56" ${s}><polygon points="30,4 12,32 26,32 22,52 44,22 28,22"/></svg>`;
      case "drop":
        return `<svg viewBox="0 0 56 56" ${s}><path d="M28 4 C16 22 12 30 12 38 a16 16 0 0 0 32 0 C44 30 40 22 28 4 Z"/></svg>`;
      case "breath":
        return `<svg viewBox="0 0 56 56" ${s}><path d="M8 28 C16 16 40 16 48 28"/><path d="M8 36 C16 28 40 28 48 36"/><circle cx="28" cy="28" r="3"/></svg>`;
      case "pill":
        return `<svg viewBox="0 0 56 56" ${s}><rect x="6" y="20" width="44" height="16" rx="8"/><line x1="28" y1="20" x2="28" y2="36"/></svg>`;
      case "ruler":
        return `<svg viewBox="0 0 56 56" ${s}><rect x="4" y="22" width="48" height="12" rx="1"/><line x1="12" y1="22" x2="12" y2="28"/><line x1="20" y1="22" x2="20" y2="30"/><line x1="28" y1="22" x2="28" y2="28"/><line x1="36" y1="22" x2="36" y2="30"/><line x1="44" y1="22" x2="44" y2="28"/></svg>`;
      case "check":
        return `<svg viewBox="0 0 56 56" ${s}><polyline points="10 28 24 42 46 16"/></svg>`;
      default:
        return `<svg viewBox="0 0 56 56" ${s}><circle cx="28" cy="28" r="20"/></svg>`;
    }
  }

  // Helpers -----------------------------------------------------
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
  // Escape text and convert inline [CITATION_ID] markers (UPPERCASE
  // slugs like AHA-COMPRESSION-RATE) into clickable pills that route
  // through openCitation(). Used by step instructions and chat bubbles.
  const _CITE_RE = /\[([A-Z][A-Z0-9_-]{2,})\]/g;
  function renderTextWithCitations(s) {
    const escaped = escapeHtml(s);
    return escaped.replace(_CITE_RE, (_m, id) =>
      `<span class="cite-pill" data-cid="${escapeHtml(id)}">${escapeHtml(id)}</span>`
    );
  }
  function wireCitationPills(root) {
    if (!root) return;
    root.querySelectorAll(".cite-pill").forEach((p) => {
      if (p._wired) return; p._wired = true;
      p.addEventListener("click", () => openCitation(p.dataset.cid));
    });
  }
  function cssEscape(s) {
    return String(s).replace(/[^\w-]/g, (c) => `\\${c}`);
  }

})();
