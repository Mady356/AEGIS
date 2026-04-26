// AEGIS Crisis Mode — non-expert one-screen UI.
// Loaded only on /crisis. Renders intake → calls /api/crisis → renders crisis_view.

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // ---------- Intake form ----------

  function renderField(q) {
    const wrap = document.createElement("div");
    wrap.className = "cm-field" + (q.type === "text" || q.type === "vitals" ? " full" : "");

    const label = document.createElement("label");
    label.textContent = q.label;
    label.htmlFor = `q_${q.id}`;
    wrap.appendChild(label);

    if (q.help) {
      const help = document.createElement("span");
      help.className = "help";
      help.textContent = q.help;
      wrap.appendChild(help);
    }

    if (q.type === "choice") {
      const group = document.createElement("div");
      group.className = "cm-choices";
      group.dataset.qid = q.id;
      (q.options || []).forEach((opt) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "cm-chip";
        btn.textContent = opt;
        btn.setAttribute("aria-pressed", "false");
        btn.dataset.value = opt;
        btn.addEventListener("click", () => {
          group.querySelectorAll(".cm-chip").forEach((c) =>
            c.setAttribute("aria-pressed", "false")
          );
          btn.setAttribute("aria-pressed", "true");
        });
        group.appendChild(btn);
      });
      wrap.appendChild(group);
    } else if (q.type === "vitals") {
      const grid = document.createElement("div");
      grid.className = "cm-vitals";
      [
        { id: "pulse", placeholder: "Pulse (bpm)" },
        { id: "rr", placeholder: "Breathing/min" },
        { id: "spo2", placeholder: "Oxygen %" },
        { id: "bp", placeholder: "BP (e.g. 120/80)" },
      ].forEach((v) => {
        const i = document.createElement("input");
        i.type = "text";
        i.placeholder = v.placeholder;
        i.dataset.vital = v.id;
        i.id = `q_${q.id}_${v.id}`;
        grid.appendChild(i);
      });
      wrap.appendChild(grid);
    } else {
      const i = document.createElement(q.type === "textarea" ? "textarea" : "input");
      if (i.tagName === "INPUT") i.type = "text";
      i.id = `q_${q.id}`;
      i.dataset.qid = q.id;
      wrap.appendChild(i);
    }

    return wrap;
  }

  function collectResponses() {
    const responses = {};
    document.querySelectorAll("[data-qid]").forEach((el) => {
      const qid = el.dataset.qid;
      if (el.classList.contains("cm-choices")) {
        const pressed = el.querySelector('[aria-pressed="true"]');
        if (pressed) responses[qid] = pressed.dataset.value;
      } else if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
        const v = el.value.trim();
        if (v) responses[qid] = v;
      }
    });
    const vitals = {};
    document.querySelectorAll("[data-vital]").forEach((el) => {
      const v = el.value.trim();
      if (v) vitals[el.dataset.vital] = v;
    });
    if (Object.keys(vitals).length) responses.vitals = vitals;
    return responses;
  }

  async function loadIntake() {
    let questions = [];
    try {
      const r = await fetch("/api/intake/questions");
      const data = await r.json();
      questions = data.questions || [];
    } catch (e) {
      console.error("Failed to load intake questions:", e);
    }
    const form = $("intakeForm");
    form.innerHTML = "";
    questions.forEach((q) => form.appendChild(renderField(q)));
  }

  // ---------- Result rendering ----------

  function fillList(node, items) {
    node.innerHTML = "";
    (items || []).forEach((it) => {
      const li = document.createElement("li");
      li.textContent = String(it);
      node.appendChild(li);
    });
    if (!node.children.length) {
      const li = document.createElement("li");
      li.textContent = "—";
      li.style.color = "var(--ink-dim)";
      node.appendChild(li);
    }
  }

  function showResult(out) {
    $("intakeCard").hidden = true;
    $("failsafeCard").hidden = true;
    $("resultCard").hidden = false;

    const cv = out.crisis_view || {};
    const acuity = (cv.acuity || "yellow").toLowerCase();
    const badge = $("acuityBadge");
    badge.dataset.acuity = ["red", "yellow", "green"].includes(acuity) ? acuity : "yellow";
    $("acuityLabel").textContent =
      acuity === "red" ? "RED — CRITICAL"
      : acuity === "green" ? "GREEN — STABLE"
      : "YELLOW — URGENT";

    $("supportMessage").textContent = cv.support_message || "";

    fillList($("topActions"), cv.top_actions);
    fillList($("topRuleOuts"), cv.top_rule_outs);
    fillList($("nextQuestions"), cv.next_questions);

    const g = out.guidance || {};
    $("guidanceMessage").textContent = g.message || "";

    const lp = (out.learning && out.learning.learning_point) || "";
    $("learningPoint").textContent = lp;

    const fmt = (v) => JSON.stringify(v || {}, null, 2);
    $("rawTriage").textContent = fmt(out.triage);
    $("rawDiff").textContent = fmt(out.differential);
    $("rawProto").textContent = fmt(out.protocol);
    $("rawMissed").textContent = fmt(out.missed_signals);
    $("rawTrace").textContent = fmt(out.reasoning_trace);
    $("rawAudit").textContent = fmt(out.audit);

    // Reflect offline status if the server reports it.
    const off = out.offline_status || {};
    if (off.mode) $("offlineBadge").textContent = off.mode;
  }

  function showFailsafe(out) {
    $("intakeCard").hidden = true;
    $("resultCard").hidden = true;
    $("failsafeCard").hidden = false;
    const safety = out.safety || {};
    $("failsafeMessage").textContent =
      safety.message || "Not enough information to proceed safely.";
    fillList($("failsafeQuestions"), safety.questions || (out.crisis_view || {}).next_questions);
  }

  // ---------- Submit / restart ----------

  async function submit() {
    const responses = collectResponses();
    const btn = $("submitBtn");
    btn.disabled = true;
    btn.textContent = "Thinking…";
    try {
      const r = await fetch("/api/crisis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ responses }),
      });
      const out = await r.json();
      if ((out.safety && out.safety.status === "insufficient_data") ||
          out.status === "insufficient_data") {
        showFailsafe(out);
      } else {
        showResult(out);
      }
    } catch (e) {
      alert("Could not reach AEGIS. Check the connection and try again.");
    } finally {
      btn.disabled = false;
      btn.textContent = "Get help now";
    }
  }

  function restart() {
    $("resultCard").hidden = true;
    $("failsafeCard").hidden = true;
    $("intakeCard").hidden = false;
    document.querySelectorAll("[data-qid] input, [data-qid] textarea, [data-vital]")
      .forEach((el) => (el.value = ""));
    document.querySelectorAll(".cm-chip[aria-pressed='true']")
      .forEach((c) => c.setAttribute("aria-pressed", "false"));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // ---------- Boot ----------

  document.addEventListener("DOMContentLoaded", () => {
    loadIntake();
    $("submitBtn").addEventListener("click", submit);
    $("restartBtn").addEventListener("click", restart);
    $("failsafeBack").addEventListener("click", restart);
  });
})();
