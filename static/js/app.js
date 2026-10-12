(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const form = $("#patientForm");
  const csrfToken = $('meta[name="csrf-token"]').content;

  const FIELD_NAMES = ["patient_name", "phone", "birth_year", "sex", "cp", "trestbps", "chol",
    "fbs", "restecg", "thalach", "exang", "oldpeak", "slope", "ca", "thal"];

  const LABELS = {
    sex: { 0: "Female", 1: "Male" },
    fbs: { 0: "False (0)", 1: "True (1)" },
    exang: { 0: "No (0)", 1: "Yes (1)" },
    cp: { 0: "Typical angina", 1: "Atypical angina", 2: "Non-anginal pain", 3: "Asymptomatic" },
    slope: { 0: "Upsloping", 1: "Flat", 2: "Downsloping" },
  };

  const COLORS = { red: "#d42b42", blue: "#0f7c8a", gray: "#7f9aa1", soft: "#f4c7cd" };

  const state = {
    config: null,
    prediction: null,   // { fingerprint, result, key, payload }
    saved: false,
    busy: false,
    busyAction: null,
    charts: [],
  };

  // ------------------------------------------------------------ helpers
  // (window.__previewGo exists only in the clickable preview.)
  function go(url) {
    if (window.__previewGo) window.__previewGo(url); else window.location.assign(url);
  }

  function uuid() {
    if (window.crypto && typeof crypto.randomUUID === "function") return crypto.randomUUID();
    const hex = (n) => Array.from({ length: n }, () => Math.floor(Math.random() * 16).toString(16)).join("");
    return `${hex(8)}-${hex(4)}-4${hex(3)}-a${hex(3)}-${hex(12)}`;
  }

  function setStatus(type, message) {
    const box = $("#status");
    box.className = `status ${type}`;
    box.textContent = message;
    box.hidden = false;
  }

  function clearStatus() {
    const box = $("#status");
    box.hidden = true;
    box.textContent = "";
  }

  function readForm() {
    const values = {};
    FIELD_NAMES.forEach((name) => {
      const el = form.elements[name];
      values[name] = ((el && el.value) || "").trim();
    });
    return values;
  }

  function fingerprint() {
    return JSON.stringify(readForm());
  }

  function showFieldErrors(errors) {
    clearFieldErrors();
    Object.entries(errors).forEach(([name, message]) => {
      const slot = $(`[data-error-for="${name}"]`);
      if (!slot) return;
      slot.textContent = message;
      const field = slot.closest(".field");
      if (field) field.classList.add("invalid");
    });
    const first = Object.keys(errors).find((n) => form.elements[n]);
    if (first) {
      const el = form.elements[first];
      (el instanceof RadioNodeList ? el[0] : el).focus();
    }
  }

  function clearFieldErrors() {
    $$("[data-error-for]").forEach((slot) => { slot.textContent = ""; });
    $$(".field.invalid").forEach((f) => f.classList.remove("invalid"));
  }

  function formatDate(date) {
    return date.toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" });
  }

  function isoDateLocal(date) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }

  function refreshDates() {
    const now = new Date();
    $("#todayLabel").textContent = formatDate(now);
    $("#todayLabel").dateTime = isoDateLocal(now);
    $("#registration_date").value = isoDateLocal(now);
  }

  // ---------------------------------------------------------------- API
  async function api(path, method, body) {
    let response;
    try {
      response = await fetch(path, {
        method,
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (_) {
      return { ok: false, error: "Cannot reach the server. Check that the Flask app is still running." };
    }
    let data;
    try {
      data = await response.json();
    } catch (_) {
      data = { ok: false, error: `Unexpected server response (${response.status}).` };
    }
    data.status = response.status;
    if (response.status === 401) {          // session expired: back to the sign-in page
      go("/login");
    }
    return data;
  }

  // --------------------------------------------------------- validation
  function validate() {
    const v = readForm();
    const errors = {};
    const limits = state.config.limits;

    const name = v.patient_name.replace(/\s+/g, " ").trim();
    if (!/^[\p{L}][\p{L} .'’-]{1,59}$/u.test(name)) {
      errors.patient_name = "Enter a name of 2-60 letters. Spaces, hyphens, apostrophes and dots are allowed.";
    }

    if (!/^\+?[0-9]{10,15}$/.test(v.phone.replace(/[\s().-]/g, ""))) {
      errors.phone = "Enter a valid phone number: 10 to 15 digits, with an optional + at the start.";
    }

    if (!/^[0-9]{4}$/.test(v.birth_year)) {
      errors.birth_year = "Enter the birth year as 4 digits, for example 1975. A full date is not accepted.";
    } else {
      const year = Number(v.birth_year);
      if (year < limits.birth_year.min || year > limits.birth_year.max) {
        errors.birth_year = `Birth year must be between ${limits.birth_year.min} and ${limits.birth_year.max}.`;
      }
    }

    ["sex", "fbs", "exang"].forEach((n) => { if (v[n] === "") errors[n] = "Choose one option."; });
    ["cp", "restecg", "slope", "ca", "thal"].forEach((n) => { if (v[n] === "") errors[n] = "Select a value."; });

    Object.entries(limits.numeric).forEach(([n, lim]) => {
      const raw = v[n];
      if (raw === "") { errors[n] = "Enter a value."; return; }
      const num = Number(raw);
      if (!Number.isFinite(num)) {
        errors[n] = "Enter a number.";
      } else if (num < lim.min || num > lim.max) {
        errors[n] = `${lim.label} must be between ${lim.min} and ${lim.max}${lim.unit ? " " + lim.unit : ""}.`;
      }
    });
    return errors;
  }

  // ------------------------------------------------------------ buttons
  function updateButtons() {
    $("#predictBtn").disabled = state.busy || !state.config;
    $("#predictBtn").textContent = state.busyAction === "predict" ? "Predicting..." : "Predict Heart Disease Risk";
    const canSave = !!state.prediction && !state.saved && !state.busy
      && state.prediction.fingerprint === fingerprint();
    $("#saveBtn").disabled = !canSave;
    $("#saveBtn").textContent = state.busyAction === "save" ? "Saving..."
      : state.saved ? "Saved" : "Save Record";
  }

  function setBusy(action) {
    state.busyAction = action;   // "predict", "save" or null
    state.busy = action !== null;
    updateButtons();
  }

  // ------------------------------------------------------------- result
  function renderResult(res) {
    const card = $("#resultCard");
    card.hidden = false;
    const badge = $("#resultBadge");
    badge.textContent = res.label;
    badge.className = `badge badge-${res.tone}`;
    $("#resultExplanation").textContent = res.explanation;
    $("#resultPatient").textContent = res.patient_name;
    $("#resultAge").textContent = `${res.age} years`;
    $("#resultTime").textContent = new Date(res.assessed_at).toLocaleString();

    const list = $("#resultWarnings");
    list.textContent = "";
    (res.warnings || []).forEach((w) => {
      const li = document.createElement("li");
      li.textContent = w;
      list.appendChild(li);
    });
    list.hidden = !(res.warnings && res.warnings.length);

    const heading = $("#resultTitle");
    heading.focus({ preventScroll: true });
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    card.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "nearest" });
  }

  function hideResult() {
    $("#resultCard").hidden = true;
    $("#resultWarnings").textContent = "";
  }

  // ------------------------------------------------------------- charts
  function destroyCharts() {
    state.charts.forEach((c) => c.destroy());
    state.charts = [];
    $$(".chart-card").forEach((card) => { card.dataset.ready = "false"; });
    ["note1", "note2", "note3", "note4"].forEach((id) => { $("#" + id).textContent = ""; });
  }

  function pct(value, min, max) {
    if (max === min) return 50;
    return Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
  }

  function categoryRange(key) {
    const values = state.config.category_values[key];
    return { min: Math.min(...values), max: Math.max(...values) };
  }

  function baseOptions() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
    };
  }

  function renderCharts(inputs) {
    destroyCharts();
    if (typeof Chart === "undefined") {
      $$(".chart-empty").forEach((el) => {
        el.textContent = "Charts need an internet connection to load the Chart.js library.";
      });
      return;
    }
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = "#586275";

    const numeric = state.config.numeric_ranges;
    const label = (map, key) => (map[key] && map[key][inputs[key]] !== undefined ? map[key][inputs[key]] : `Code ${inputs[key]}`);

    // Chart 1 - patient characteristics (coded 0/1 values)
    const c1Text = [label(LABELS, "sex"), label(LABELS, "fbs"), label(LABELS, "exang")];
    state.charts.push(new Chart($("#chart1"), {
      type: "bar",
      data: {
        labels: ["Sex", "Fasting blood sugar", "Exercise-induced angina"],
        datasets: [{
          data: [inputs.sex, inputs.fbs, inputs.exang],
          backgroundColor: [COLORS.blue, COLORS.red, COLORS.gray],
          borderRadius: 6, minBarLength: 6,
        }],
      },
      options: {
        ...baseOptions(),
        scales: {
          y: {
            min: 0, max: 1,
            ticks: { stepSize: 1, callback: (v) => (v === 1 ? "1" : v === 0 ? "0" : "") },
            title: { display: true, text: "Coded value (0 or 1)" },
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => c1Text[ctx.dataIndex] } },
        },
      },
    }));
    $("#note1").textContent = `Sex: ${c1Text[0]}; fasting blood sugar: ${c1Text[1]}; exercise-induced angina: ${c1Text[2]}. Bars show the coded value (0 or 1).`;

    // Helper for charts 2 and 3: position within the range seen in heart.csv
    function rangeChart(canvasId, noteId, items) {
      const data = items.map((it) => pct(it.value, it.min, it.max));
      state.charts.push(new Chart($(canvasId), {
        type: "bar",
        data: {
          labels: items.map((it) => it.label),
          datasets: [{ data, backgroundColor: COLORS.red, borderRadius: 6, minBarLength: 4 }],
        },
        options: {
          ...baseOptions(),
          indexAxis: "y",
          scales: {
            x: { min: 0, max: 100, title: { display: true, text: "Position within the range in heart.csv (%)" } },
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => {
                  const it = items[ctx.dataIndex];
                  const outside = it.value < it.min || it.value > it.max ? " (outside training range)" : "";
                  return `${it.text} - training range ${it.min} to ${it.max}${outside}`;
                },
              },
            },
          },
        },
      }));
      $(noteId).textContent = items.map((it) => `${it.label}: ${it.text}`).join("; ") +
        ". 0% is the lowest value in heart.csv and 100% the highest.";
    }

    rangeChart("#chart2", "#note2", [
      { label: "Age", value: inputs.age, text: `${inputs.age} years`, ...numeric.age },
      { label: "Resting blood pressure", value: inputs.trestbps, text: `${inputs.trestbps} mm Hg`, ...numeric.trestbps },
      { label: "Cholesterol", value: inputs.chol, text: `${inputs.chol} mg/dl`, ...numeric.chol },
      { label: "Max heart rate", value: inputs.thalach, text: `${inputs.thalach} bpm`, ...numeric.thalach },
    ]);

    rangeChart("#chart3", "#note3", [
      { label: "Oldpeak", value: inputs.oldpeak, text: String(inputs.oldpeak), ...numeric.oldpeak },
      { label: "Resting ECG", value: inputs.restecg, text: `code ${inputs.restecg}`, ...categoryRange("restecg") },
      { label: "Chest pain type", value: inputs.cp, text: `${inputs.cp} - ${LABELS.cp[inputs.cp]}`, ...categoryRange("cp") },
    ]);

    // Chart 4 - categorical codes
    const c4Text = [
      `${inputs.slope} - ${LABELS.slope[inputs.slope]}`,
      `${inputs.ca} major vessel(s)`,
      `code ${inputs.thal}`,
    ];
    const top = Math.max(...["slope", "ca", "thal"].map((k) => categoryRange(k).max));
    state.charts.push(new Chart($("#chart4"), {
      type: "bar",
      data: {
        labels: ["Slope", "Major vessels", "Thal"],
        datasets: [{
          data: [inputs.slope, inputs.ca, inputs.thal],
          backgroundColor: [COLORS.blue, COLORS.red, COLORS.gray],
          borderRadius: 6, minBarLength: 6,
        }],
      },
      options: {
        ...baseOptions(),
        scales: {
          y: { min: 0, max: top, ticks: { stepSize: 1, precision: 0 }, title: { display: true, text: "Coded value" } },
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => c4Text[ctx.dataIndex] } },
        },
      },
    }));
    $("#note4").textContent = `Slope: ${c4Text[0]}; major vessels: ${c4Text[1]}; thal: ${c4Text[2]}. Bars show category codes, not measurements.`;

    $$(".chart-card").forEach((card) => { card.dataset.ready = "true"; });
  }

  // --------------------------------------------------- invalidate / reset
  function invalidateResults(message) {
    const had = !!state.prediction;
    state.prediction = null;
    state.saved = false;
    hideResult();
    destroyCharts();
    updateButtons();
    if (had && message) setStatus("info", message);
  }

  function onFormChange(event) {
    const field = event.target.closest(".field");
    if (field) {
      field.classList.remove("invalid");
      const slot = $("[data-error-for]", field);
      if (slot) slot.textContent = "";
    }
    if (state.prediction && state.prediction.fingerprint !== fingerprint()) {
      invalidateResults("The form changed, so the previous result and charts were cleared. Run the prediction again.");
    } else {
      updateButtons();
    }
  }

  function resetAll() {
    if (state.prediction && !state.saved &&
        !window.confirm("Clear the form and discard the unsaved prediction? Saved records are not affected.")) {
      return;
    }
    form.reset();
    clearFieldErrors();
    clearStatus();
    state.prediction = null;
    state.saved = false;
    hideResult();
    destroyCharts();
    $("#registration_number").value = "Assigned when saved";
    refreshDates();
    updateButtons();
    $("#birth_year").focus();
  }

  // -------------------------------------------------------------- actions
  async function onPredict() {
    if (state.busy || !state.config) return;
    clearStatus();
    const errors = validate();
    if (Object.keys(errors).length) {
      showFieldErrors(errors);
      setStatus("error", "Please correct the highlighted fields.");
      return;
    }
    clearFieldErrors();

    const payload = readForm();
    const sentFingerprint = fingerprint();
    setBusy("predict");
    try {
      const res = await api("/api/predict", "POST", payload);
      if (!res.ok) {
        if (res.fields) showFieldErrors(res.fields);
        setStatus("error", res.error || "The prediction failed.");
        return;
      }
      if (fingerprint() !== sentFingerprint) {
        setStatus("info", "The form changed while predicting. Run the prediction again.");
        return;
      }
      state.prediction = { fingerprint: sentFingerprint, result: res, key: uuid(), payload };
      state.saved = false;
      $("#registration_number").value = "Assigned when saved";
      renderResult(res);
      renderCharts(res.inputs);
    } finally {
      setBusy(null);
    }
  }

  async function onSave() {
    if (state.busy || state.saved) return;
    clearStatus();
    if (!state.prediction || state.prediction.fingerprint !== fingerprint()) {
      invalidateResults("The form changed, so run the prediction again before saving.");
      return;
    }
    const errors = validate();
    if (Object.keys(errors).length) {
      showFieldErrors(errors);
      setStatus("error", "Please correct the highlighted fields.");
      return;
    }

    const payload = {
      ...state.prediction.payload,
      smoking: $("#smoking").checked ? 1 : 0,
      alcohol: $("#alcohol").checked ? 1 : 0,
      idempotency_key: state.prediction.key,
    };
    setBusy("save");
    try {
      const res = await api("/api/patients", "POST", payload);
      if (!res.ok) {
        if (res.fields) showFieldErrors(res.fields);
        setStatus("error", res.error || "The record could not be saved.");
        return;
      }
      state.saved = true;
      $("#registration_number").value = `#${res.id}`;
      setStatus("success", res.message || `Record #${res.id} saved.`);
    } finally {
      setBusy(null);
    }
  }

  // ---------------------------------------------------------------- setup
  function fillSelect(id, values, prefix) {
    const select = $(id);
    values.forEach((value) => {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = prefix ? `${prefix} ${value}` : String(value);
      select.appendChild(option);
    });
  }

  async function loadConfig() {
    const res = await api("/api/config", "GET");
    if (!res.ok) {
      setStatus("error", res.error || "The server could not load the model settings.");
      updateButtons();
      return;
    }
    state.config = res;
    fillSelect("#ca", res.category_values.ca);
    fillSelect("#thal", res.category_values.thal, "Code");
    const m = res.model;
    $("#modelNote").textContent =
      `Model: ${m.algorithm}, trained on ${m.rows_in_dataset} rows of heart.csv. ` +
      `Held-out test-set accuracy: ${(m.test_accuracy * 100).toFixed(1)}%. ${m.test_accuracy_note}`;
    updateButtons();
  }

  function setupDialog() {
    const dialog = $("#infoDialog");
    $("#infoBtn").addEventListener("click", () => dialog.showModal());
    $("#infoClose").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();  // click on the dark backdrop
    });
  }

  function init() {
    refreshDates();
    setupDialog();
    form.addEventListener("input", onFormChange);
    form.addEventListener("change", onFormChange);
    form.addEventListener("submit", (e) => e.preventDefault());
    $("#predictBtn").addEventListener("click", onPredict);
    $("#saveBtn").addEventListener("click", onSave);
    $$(".js-reset").forEach((btn) => btn.addEventListener("click", resetAll));
    $("#logoutBtn").addEventListener("click", async () => {
      if (state.prediction && !state.saved &&
          !window.confirm("You have an unsaved prediction. Log out anyway?")) return;
      const res = await api("/api/logout", "POST", {});
      go(res.redirect || "/login");
    });
    updateButtons();
    loadConfig();
  }

  init();
})();
