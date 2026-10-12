(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const form = $("#authForm");
  const mode = form.dataset.mode;
  const csrfToken = $('meta[name="csrf-token"]').content;

  const ENDPOINTS = {
    "patient-login": "/api/auth/login",
    "register": "/api/auth/register",
    "doctor-login": "/api/auth/doctor-login",
  };

  // (window.__previewGo exists only in the clickable preview.)
  function go(url) {
    if (window.__previewGo) window.__previewGo(url); else window.location.assign(url);
  }

  function showStatus(message) {
    const box = $("#authStatus");
    box.textContent = message;
    box.hidden = !message;
  }

  function clearErrors() {
    showStatus("");
    $$("[data-error-for]").forEach((slot) => { slot.textContent = ""; });
    $$(".field.invalid").forEach((f) => f.classList.remove("invalid"));
  }

  function showFieldErrors(errors) {
    Object.entries(errors).forEach(([name, message]) => {
      const slot = $(`[data-error-for="${name}"]`);
      if (!slot) return;
      slot.textContent = message;
      slot.closest(".field").classList.add("invalid");
    });
    const first = Object.keys(errors).find((n) => form.elements[n]);
    if (first) form.elements[first].focus();
  }

  function values() {
    const out = {};
    Array.from(form.elements).forEach((el) => {
      if (el.name) out[el.name] = el.name.includes("password") ? el.value : el.value.trim();
    });
    return out;
  }

  function validate(v) {
    const errors = {};
    const phoneOk = (p) => /^\+?[0-9]{10,15}$/.test(p.replace(/[\s().-]/g, ""));
    if ("full_name" in v && !/^[\p{L}][\p{L} .'’-]{1,59}$/u.test(v.full_name.replace(/\s+/g, " "))) {
      errors.full_name = "Enter a name of 2-60 letters. Spaces, hyphens, apostrophes and dots are allowed.";
    }
    if ("phone" in v && !phoneOk(v.phone)) {
      errors.phone = "Enter a valid phone number: 10 to 15 digits, with an optional + at the start.";
    }
    if ("username" in v && !/^[A-Za-z0-9][A-Za-z0-9_.-]{2,49}$/.test(v.username)) {
      errors.username = "Enter your username (3-50 letters, digits, dots, dashes or underscores).";
    }
    if (!v.password) {
      errors.password = "Enter your password.";
    } else if (mode === "register") {
      if (v.password.length < 8 || v.password.length > 128) {
        errors.password = "Use 8 to 128 characters.";
      } else if (!/[A-Za-z]/.test(v.password) || !/[0-9]/.test(v.password)) {
        errors.password = "Include at least one letter and one number.";
      }
      if (!errors.password && v.confirm_password !== v.password) {
        errors.confirm_password = "The two passwords do not match.";
      }
    }
    return errors;
  }

  let sending = false;

  form.addEventListener("input", (event) => {
    const field = event.target.closest(".field");
    if (field) {
      field.classList.remove("invalid");
      const slot = $("[data-error-for]", field);
      if (slot) slot.textContent = "";
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (sending) return;
    clearErrors();
    const v = values();
    const errors = validate(v);
    if (Object.keys(errors).length) {
      showFieldErrors(errors);
      return;
    }

    sending = true;
    const button = $("#authSubmit");
    const idleText = button.textContent;
    button.disabled = true;
    button.textContent = "Please wait...";
    try {
      let response;
      try {
        response = await fetch(ENDPOINTS[mode], {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRF-Token": csrfToken },
          body: JSON.stringify(v),
        });
      } catch (_) {
        showStatus("Cannot reach the server. Check that the Flask app is still running.");
        return;
      }
      let data;
      try { data = await response.json(); } catch (_) { data = { ok: false, error: `Unexpected server response (${response.status}).` }; }
      if (data.ok) {
        go(data.redirect || "/");
        return;
      }
      if (data.fields) showFieldErrors(data.fields);
      showStatus(data.error || "Something went wrong. Please try again.");
      $("#password").value = "";
    } finally {
      sending = false;
      button.disabled = false;
      button.textContent = idleText;
    }
  });
})();
