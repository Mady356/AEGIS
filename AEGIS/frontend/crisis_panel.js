// AEGIS Crisis Mode panel — drops into the existing cockpit center column.
// Talks to the backend /api/crisis endpoint. Independent of app.js.

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // ---------- Helpers ----------

  function setAcuity(acuity) {
    const el = $("cpAcuity");
    const lbl = $("cpAcuityLabel");
    if (!el) return;
    const a = (acuity || "").toLowerCase();
    if (a === "red")        { el.dataset.acuity = "red";    lbl.textContent = "RED — CRITICAL"; }
    else if (a === "green") { el.dataset.acuity = "green";  lbl.textContent = "GREEN — STABLE"; }
    else if (a === "yellow"){ el.dataset.acuity = "yellow"; lbl.textContent = "YELLOW — URGENT"; }
    else                    { el.dataset.acuity = "idle";   lbl.textContent = "AWAITING INPUT"; }
  }

  function fillList(node, items) {
    if (!node) return;
    node.innerHTML = "";
    const list = (items || []).filter(x => x !== undefined && x !== null && String(x).trim() !== "");
    if (!list.length) {
      const li = document.createElement("li");
      li.className = "cp-empty";
      li.textContent = "—";
      node.appendChild(li);
      return;
    }
    list.forEach((it) => {
      const li = document.createElement("li");
      li.textContent = typeof it === "string"
        ? it
        : (it.text || it.label || it.action || it.question || it.rule_out || JSON.stringify(it));
      node.appendChild(li);
    });
  }

  function collectResponses() {
    const responses = {};
    const cc = ($("cpComplaint").value || "").trim();
    if (cc) responses.chief_complaint = cc;
    document.querySelectorAll(".cp-chips").forEach((group) => {
      const qid = group.dataset.cpQid;
      const pressed = group.querySelector('.cp-chip[aria-pressed="true"]');
      if (qid && pressed) responses[qid] = pressed.dataset.value;
    });
    return responses;
  }

  // -- Cross-module: write the steplist into window.state.aiChecklist
  //    and notify the cockpit so renderChecklist() picks it up.
  function publishChecklist(scenarioId, topActions) {
    const items = (topActions || [])
      .map((it, i) => {
        if (typeof it === "string") {
          return { id: "ai-" + String(i + 1).padStart(3, "0"),
                   label: it.trim(), keywords: [], source: "ai" };
        }
        if (it && typeof it === "object" && (it.label || it.text)) {
          return {
            id: it.id || ("ai-" + String(i + 1).padStart(3, "0")),
            label: String(it.label || it.text || "").trim(),
            keywords: Array.isArray(it.keywords)
              ? it.keywords.map(k => String(k).toLowerCase()).filter(Boolean)
              : [],
            source: "ai",
          };
        }
        return null;
      })
      .filter(x => x && x.label);
    const w = window;
    w.state = w.state || {};
    if (items.length) {
      w.state.aiChecklist = items;
      w.state.aiChecklistScenarioId = scenarioId || null;
      w.state.aiChecklistOffline = false;
    } else {
      w.state.aiChecklist = null;
      w.state.aiChecklistScenarioId = scenarioId || null;
      w.state.aiChecklistOffline = true;
    }
    w.dispatchEvent(new CustomEvent("aegis:checklist-updated", {
      detail: { scenarioId: scenarioId || null,
                offline: w.state.aiChecklistOffline,
                count: items.length },
    }));
  }

  function clearChecklist(scenarioId) {
    const w = window;
    w.state = w.state || {};
    w.state.aiChecklist = null;
    w.state.aiChecklistScenarioId = scenarioId || null;
    w.state.aiChecklistOffline = true;
    w.dispatchEvent(new CustomEvent("aegis:checklist-updated", {
      detail: { scenarioId: scenarioId || null, offline: true, count: 0 },
    }));
  }

  // ---------- Render ----------

  function showResult(out) {
    $("cpIntake").hidden = true;
    $("cpFailsafe").hidden = true;
    $("cpResult").hidden = false;

    const cv = out.crisis_view || {};
    setAcuity(cv.acuity);
    $("cpSupport").textContent = cv.support_message || "";
    fillList($("cpActions"), cv.top_actions);
    fillList($("cpRuleOuts"), cv.top_rule_outs);
    fillList($("cpNext"), cv.next_questions);

    $("cpGuidance").textContent = (out.guidance && out.guidance.message) || "";
    $("cpLearning").textContent = (out.learning && out.learning.learning_point) || "";

    const fmt = (v) => JSON.stringify(v || {}, null, 2);
    $("cpRawTriage").textContent = fmt(out.triage);
    $("cpRawDiff").textContent = fmt(out.differential);
    $("cpRawProto").textContent = fmt(out.protocol);
    $("cpRawMissed").textContent = fmt(out.missed_signals);

    const off = out.offline_status || {};
    if (off.mode) $("cpOffline").textContent = off.mode;

    // Cockpit's procedural checklist mirrors the same top_actions.
    publishChecklist(out.scenario_id || null, cv.top_actions);
  }

  function showFailsafe(out) {
    $("cpIntake").hidden = true;
    $("cpResult").hidden = true;
    $("cpFailsafe").hidden = false;

    const safety = out.safety || {};
    $("cpFailsafeMsg").textContent =
      safety.message || "Not enough information to proceed safely.";
    fillList($("cpFailsafeQs"),
      safety.questions || (out.crisis_view && out.crisis_view.next_questions) || []);
    setAcuity("yellow");
  }

  function showIntake() {
    $("cpResult").hidden = true;
    $("cpFailsafe").hidden = true;
    $("cpIntake").hidden = false;
    $("cpComplaint").value = "";
    document.querySelectorAll('.cp-chip[aria-pressed="true"]')
      .forEach((c) => c.setAttribute("aria-pressed", "false"));
    setAcuity(null);
  }

  // ---------- Submit ----------

  async function submit() {
    const responses = collectResponses();
    const btn = $("cpSubmit");
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Thinking…";
    const scenarioId = (window.state && window.state.active) || null;
    try {
      const r = await fetch("/api/crisis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ responses, scenario_id: scenarioId }),
      });
      const out = await r.json();
      const isFailsafe =
        (out.safety && out.safety.status === "insufficient_data") ||
        out.status === "insufficient_data";
      if (out.fallback) {
        // Backend signaled the LLM bundle failed — clear AI checklist
        // so the cockpit falls back to scenarios.steps.
        clearChecklist(scenarioId);
      }
      if (isFailsafe) showFailsafe(out);
      else            showResult(out);
    } catch (e) {
      console.error("crisis_panel: fetch failed", e);
      $("cpSupport").textContent = "Could not reach AEGIS. Try again.";
      clearChecklist(scenarioId);
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  }

  // Auto-fire when a scenario is selected so the checklist + crisis
  // panel populate without requiring the operator to type anything.
  // app.js calls this from activateScenario().
  async function triggerForScenario(scenarioId) {
    if (!scenarioId) return;
    const w = window;
    const sc = (w.state && w.state.scenarios && w.state.scenarios[scenarioId]) || {};
    const responses = {
      // Use the scenario's case as a stand-in chief complaint so the
      // backend can build a coherent encounter without operator input.
      chief_complaint: sc.case || sc.name || "",
    };
    try {
      const r = await fetch("/api/crisis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ responses, scenario_id: scenarioId }),
      });
      const out = await r.json();
      // Drop stale responses if the user has switched scenarios while
      // we were in flight.
      const stillActive = (w.state && w.state.active) === scenarioId;
      if (!stillActive) return;
      if (out.fallback) {
        clearChecklist(scenarioId);
        return;
      }
      // Update the panel UI silently — same code path as manual submit.
      const isFailsafe =
        (out.safety && out.safety.status === "insufficient_data") ||
        out.status === "insufficient_data";
      if (isFailsafe) showFailsafe(out);
      else            showResult(out);
    } catch (e) {
      console.error("crisis_panel.triggerForScenario failed", e);
      clearChecklist(scenarioId);
    }
  }

  // Public surface for app.js.
  window.AEGISCrisis = Object.freeze({
    triggerForScenario,
    submit,
  });

  // ---------- Wire up ----------

  function wireChips() {
    document.querySelectorAll(".cp-chips").forEach((group) => {
      group.addEventListener("click", (ev) => {
        const chip = ev.target.closest(".cp-chip");
        if (!chip || !group.contains(chip)) return;
        group.querySelectorAll(".cp-chip").forEach((c) =>
          c.setAttribute("aria-pressed", "false")
        );
        chip.setAttribute("aria-pressed", "true");
      });
    });
  }

  function init() {
    if (!$("cpSubmit")) return;     // panel not on this page
    wireChips();
    $("cpSubmit").addEventListener("click", submit);
    $("cpRestart").addEventListener("click", showIntake);
    $("cpFailsafeBack").addEventListener("click", showIntake);
    $("cpComplaint").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); submit(); }
    });
    setAcuity(null);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
