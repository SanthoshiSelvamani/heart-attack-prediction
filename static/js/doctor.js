(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const csrfToken = $('meta[name="csrf-token"]').content;

  const SEX = { 0: "Female", 1: "Male" };
  const FBS = { 0: "False (0)", 1: "True (1)" };
  const EXANG = { 0: "No (0)", 1: "Yes (1)" };
  const CP = { 0: "0 - Typical angina", 1: "1 - Atypical angina", 2: "2 - Non-anginal pain", 3: "3 - Asymptomatic" };
  const SLOPE = { 0: "0 - Upsloping", 1: "1 - Flat", 2: "2 - Downsloping" };

  const state = { page: 1, q: "", records: [], loading: false };

  // (window.__previewGo exists only in the clickable preview.)
  function go(url) {
    if (window.__previewGo) window.__previewGo(url); else window.location.assign(url);
  }

  async function api(path, method, body) {
    let response;
    try {
      response = await fetch(path, {
        method,
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRF-Token": csrfToken },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (_) {
      return { ok: false, error: "Cannot reach the server. Check that the Flask app is still running." };
    }
    let data;
    try { data = await response.json(); } catch (_) { data = { ok: false, error: `Unexpected server response (${response.status}).` }; }
    if (response.status === 401) go("/doctor/login");
    return data;
  }

  function showError(message) {
    const box = $("#status");
    box.textContent = message;
    box.hidden = !message;
  }

  function cell(text, className) {
    const td = document.createElement("td");
    td.textContent = text;
    if (className) td.className = className;
    return td;
  }

  function renderRows(records) {
    const body = $("#recordsBody");
    body.textContent = "";
    records.forEach((r, index) => {
      const tr = document.createElement("tr");
      tr.appendChild(cell(`#${r.id}`));
      tr.appendChild(cell(r.created_at));
      tr.appendChild(cell(r.patient_name));
      tr.appendChild(cell(r.phone || "Not recorded"));
      tr.appendChild(cell(String(r.age)));

      const result = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = `badge badge-${r.prediction_tone}`;
      badge.textContent = r.prediction_label;
      result.appendChild(badge);
      tr.appendChild(result);

      const action = document.createElement("td");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-ghost btn-small";
      button.textContent = "View";
      button.setAttribute("aria-label", `View details for ${r.patient_name}, record ${r.id}`);
      button.addEventListener("click", () => openDetails(state.records[index]));
      action.appendChild(button);
      tr.appendChild(action);
      body.appendChild(tr);
    });
  }

  function openDetails(r) {
    const rows = [
      ["Record", `#${r.id}`], ["Saved", r.created_at], ["Patient", r.patient_name],
      ["Phone", r.phone || "Not recorded"], ["Birth year", r.birth_year], ["Age", `${r.age} years`],
      ["Sex", SEX[r.sex] ?? r.sex], ["Chest pain type", CP[r.cp] ?? r.cp],
      ["Resting blood pressure", `${r.trestbps} mm Hg`], ["Cholesterol", `${r.chol} mg/dl`],
      ["Fasting blood sugar", FBS[r.fbs] ?? r.fbs], ["Resting ECG", `code ${r.restecg}`],
      ["Maximum heart rate", `${r.thalach} bpm`], ["Exercise-induced angina", EXANG[r.exang] ?? r.exang],
      ["Oldpeak", r.oldpeak], ["Slope", SLOPE[r.slope] ?? r.slope],
      ["Major vessels", r.ca], ["Thal", `code ${r.thal}`],
      ["Smoker (not a model input)", r.smoking === null ? "Not recorded" : (r.smoking ? "Yes" : "No")],
      ["Alcohol (not a model input)", r.alcohol == null ? "Not recorded" : (r.alcohol ? "Yes" : "No")],
      ["Model result", r.prediction_label],
    ];
    const list = $("#detailList");
    list.textContent = "";
    rows.forEach(([label, value]) => {
      const wrap = document.createElement("div");
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = label;
      dd.textContent = String(value);
      wrap.append(dt, dd);
      list.appendChild(wrap);
    });
    $("#detailDialog").showModal();
  }

  async function load() {
    if (state.loading) return;
    state.loading = true;
    showError("");
    const params = new URLSearchParams({ page: String(state.page) });
    if (state.q) params.set("q", state.q);
    const res = await api(`/api/doctor/records?${params}`, "GET");
    state.loading = false;
    if (!res.ok) {
      showError(res.error || "The records could not be loaded.");
      return;
    }
    state.records = res.records;
    state.page = res.page;
    renderRows(res.records);

    $("#statTotal").textContent = String(res.stats.total);
    res.stats.classes.forEach((c) => {
      $(`#statLabel${c.value}`).textContent = c.label;
      $(`#statClass${c.value}`).textContent = String(c.count);
    });

    const empty = $("#emptyMsg");
    empty.hidden = res.records.length > 0;
    empty.textContent = state.q ? "No records match your search." : "No records have been saved yet.";
    $("#pageInfo").textContent = `Page ${res.page} of ${res.pages} (${res.total} record${res.total === 1 ? "" : "s"})`;
    $("#prevBtn").disabled = res.page <= 1;
    $("#nextBtn").disabled = res.page >= res.pages;
  }

  let timer = null;
  $("#searchBox").addEventListener("input", (event) => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.q = event.target.value.trim(); state.page = 1; load(); }, 300);
  });
  $("#prevBtn").addEventListener("click", () => { state.page = Math.max(1, state.page - 1); load(); });
  $("#nextBtn").addEventListener("click", () => { state.page += 1; load(); });

  const dialog = $("#detailDialog");
  $("#detailClose").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });

  $("#logoutBtn").addEventListener("click", async () => {
    const res = await api("/api/logout", "POST", {});
    go(res.redirect || "/doctor/login");
  });

  load();
})();
