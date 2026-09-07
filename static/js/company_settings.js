// Company settings page: tab switching and the logo file picker.
(function () {
  const tabs = Array.prototype.slice.call(document.querySelectorAll("[data-settings-tab]"));
  const panes = Array.prototype.slice.call(document.querySelectorAll("[data-settings-pane]"));
  const logoInput = document.getElementById("settings-logo-input");
  const logoReplace = document.querySelector("[data-logo-replace]");
  const logoPreview = document.getElementById("settings-logo-preview");

  function showTab(name) {
    tabs.forEach(function (tab) {
      tab.classList.toggle("active", tab.getAttribute("data-settings-tab") === name);
    });
    panes.forEach(function (pane) {
      pane.classList.toggle("active", pane.getAttribute("data-settings-pane") === name);
    });
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      showTab(tab.getAttribute("data-settings-tab"));
    });
  });

  var cancel = document.querySelector("[data-settings-cancel]");
  if (cancel) {
    cancel.addEventListener("click", function () {
      window.location.reload();
    });
  }

  if (logoReplace && logoInput) {
    logoReplace.addEventListener("click", function () {
      logoInput.click();
    });
    logoInput.addEventListener("change", function () {
      if (!logoInput.files.length) {
        return;
      }
      var file = logoInput.files[0];
      logoReplace.textContent = file.name;
      if (logoPreview) {
        var objectUrl = URL.createObjectURL(file);
        var img = document.createElement("img");
        img.className = "brand-logo";
        img.src = objectUrl;
        img.alt = "Company logo";
        img.onload = function () { URL.revokeObjectURL(objectUrl); };
        logoPreview.textContent = "";
        logoPreview.appendChild(img);
      }
    });
  }

  /* ---- Users & roles pane ---- */
  // The Users & roles tab talks to the OWNER-only /api/auth/users/ endpoints.
  // It authenticates via the browser session + CSRF cookie (the DRF pipeline
  // accepts both JWT and session auth). Only load when the page renders the
  // pane and the caller is an Owner (only Owners see the Settings nav).
  var usersPane = document.querySelector('[data-settings-pane="users"]');
  if (!usersPane) { return; }
  initUsersPane();

  var taxesPane = document.querySelector('[data-settings-pane="taxes"]');
  if (taxesPane) { try { initTaxesPane(); } catch (e) { console.error("taxes", e); } }

  var auditPane = document.querySelector('[data-settings-pane="audit"]');
  if (auditPane) { initAuditPane(); }

  var finPane = document.querySelector('[data-settings-pane="financial"]');
  if (finPane) { initFinancialPane(); }
  if (auditPane) { try { initAuditPane(); } catch (e) { console.error("audit", e); } }

  var finPane = document.querySelector('[data-settings-pane="financial"]');
  if (finPane) { try { initFinancialPane(); } catch (e) { console.error("financial", e); } }

  var notifPane = document.querySelector('[data-settings-pane="notifications"]');
  if (notifPane) { try { initNotificationsPane(); } catch (e) { console.error("notifications", e); } }
})();

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function fancySelect(select) {
  "use strict";
  function svg(points) {
    var d = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    d.setAttribute("viewBox", "0 0 24 24");
    d.setAttribute("width", "12");
    d.setAttribute("height", "12");
    d.setAttribute("fill", "none");
    d.setAttribute("stroke", "currentColor");
    d.setAttribute("stroke-width", "2.5");
    d.setAttribute("stroke-linecap", "round");
    d.setAttribute("stroke-linejoin", "round");
    d.innerHTML = points;
    return d;
  }
  var chevron = svg('<polyline points="6 9 12 15 18 9"></polyline>');
  var check = svg('<polyline points="20 6 9 17 4 12"></polyline>');

  var wrap = document.createElement("span");
  wrap.className = "users-select";

  var btn = document.createElement("button");
  btn.type = "button";
  btn.className = "users-select-btn";
  btn.setAttribute("aria-haspopup", "listbox");
  btn.setAttribute("aria-expanded", "false");

  var label = document.createElement("span");
  label.className = "users-select-label";
  var chevronWrap = document.createElement("span");
  chevronWrap.className = "users-select-chevron";
  chevronWrap.appendChild(chevron);
  btn.appendChild(label);
  btn.appendChild(chevronWrap);

  var pop = document.createElement("div");
  pop.className = "users-options";
  pop.setAttribute("role", "listbox");
  pop.hidden = true;

  wrap.appendChild(btn);
  wrap.appendChild(pop);

  select.classList.add("users-select-native");
  select.parentNode.insertBefore(wrap, select);
  wrap.appendChild(select);

  function renderOptions() {
    pop.innerHTML = "";
    Array.prototype.forEach.call(select.options, function (o) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "users-option" + (o.selected ? " is-active" : "");
      b.setAttribute("data-value", o.value);
      b.appendChild(check.cloneNode(true));
      b.appendChild(document.createTextNode(o.text));
      pop.appendChild(b);
    });
  }

  function sync() {
    var o = select.options[select.selectedIndex];
    label.textContent = o ? o.text : "";
    if (pop.hidden) { renderOptions(); }
    btn.setAttribute("aria-expanded", pop.hidden ? "false" : "true");
  }

  function setValue(v) {
    select.value = v;
    sync();
  }

  function openPop() {
    renderOptions();
    pop.hidden = false;
    btn.classList.add("is-open");
    btn.setAttribute("aria-expanded", "true");
    var r = btn.getBoundingClientRect();
    var w = pop.offsetWidth || 170;
    var h = pop.offsetHeight || 120;
    var left = Math.min(r.left, Math.max(8, window.innerWidth - w - 8));
    var openUp = (window.innerHeight - r.bottom - 8) < h && r.top > h;
    var top = openUp ? r.top - h - 4 : r.bottom + 4;
    top = Math.max(8, Math.min(top, window.innerHeight - h - 8));
    pop.style.left = left + "px";
    pop.style.top = top + "px";
  }

  function closePop() {
    if (pop.hidden) { return; }
    pop.hidden = true;
    btn.classList.remove("is-open");
    btn.setAttribute("aria-expanded", "false");
  }

  btn.addEventListener("click", function (ev) {
    ev.stopPropagation();
    if (pop.hidden) { openPop(); } else { closePop(); }
  });

  pop.addEventListener("click", function (ev) {
    var opt = ev.target.closest ? ev.target.closest(".users-option") : null;
    if (!opt) { return; }
    select.value = opt.getAttribute("data-value");
    sync();
    closePop();
  });

  document.addEventListener("click", function (ev) {
    if (!wrap.contains(ev.target)) { closePop(); }
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && !pop.hidden) { closePop(); }
  });

  sync();
  return { sync: sync, setValue: setValue };
}

function initTaxesPane() {
  "use strict";
  var API = "/api/taxes/tax-rates/";
  var state = { rates: [], query: "" };

  var el = function (sel, root) { return (root || document).querySelector(sel); };
  var els = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  var banner = el("[data-taxes-banner]");
  var body = el("[data-taxes-body]");
  var empty = el("[data-taxes-empty]");
  var loading = el("[data-taxes-loading]");
  var count = el("[data-taxes-count]");
  var search = el("[data-taxes-search]");
  var modal = el("[data-taxes-modal]");
  var form = el("[data-taxes-form]");
  var modalTitle = el("[data-taxes-modal-title]");

  var dateInput = el("[data-taxes-date-input]");
  var dateValue = form.elements["effective_date"];
  var dateToggle = el("[data-taxes-date-toggle]");
  var calendar = el("[data-taxes-calendar]");
  var statusSelect = fancySelect(form.elements["is_active"]);

  function getCookie(name) {
    var m = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[2]) : "";
  }

  async function api(url, options) {
    options = options || {};
    var opts = {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    };
    if (options.method && !["GET", "HEAD"].includes(options.method)) {
      opts.headers["X-CSRFToken"] = getCookie("csrftoken");
    }
    var res = await fetch(url, opts);
    if (!res.ok) {
      var detail = res.statusText;
      try { detail = JSON.stringify(await res.json()); } catch (e) { /* ignore */ }
      throw new Error(detail || ("HTTP " + res.status));
    }
    if (res.status === 204) { return null; }
    return res.json();
  }

  function showBanner(text, type) {
    banner.textContent = text;
    banner.className = "users-banner" + (type ? " " + type : "");
    banner.hidden = false;
    clearTimeout(banner._t);
    banner._t = setTimeout(function () { banner.hidden = true; }, 5000);
  }

  function hideBanner() { banner.hidden = true; }

  function statusWord(isActive) {
    return isActive ? "active" : "inactive";
  }

  function fmtRate(rate) {
    var n = Number(rate);
    if (isNaN(n)) { return rate; }
    var s = n.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
    return s + "%";
  }

  /* ---- Custom calendar (Effective date) ---- */
  var calView = (function () {
    var now = new Date();
    var year = now.getFullYear();
    var month = now.getMonth(); // 0-based
    var selected = ""; // "YYYY-MM-DD"

    var MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
    var DOWS = ["Su","Mo","Tu","We","Th","Fr","Sa"];

    function fmt(d) {
      var m = String(d.getMonth() + 1).padStart(2, "0");
      var day = String(d.getDate()).padStart(2, "0");
      return d.getFullYear() + "-" + m + "-" + day;
    }
    function display(d) {
      return !!d ? d : "Select date";
    }

    function renderCal() {
      var first = new Date(year, month, 1);
      var startDow = first.getDay();
      var daysInMonth = new Date(year, month + 1, 0).getDate();
      var todayStr = fmt(new Date());

      var cells = DOWS.map(function (d) { return '<span class="users-cal-dow">' + d + '</span>'; }).join("");

      var dayCells = "";
      for (var i = 0; i < startDow; i++) {
        dayCells += '<span></span>';
      }
      for (var d = 1; d <= daysInMonth; d++) {
        var ds = year + "-" + String(month + 1).padStart(2, "0") + "-" + String(d).padStart(2, "0");
        var cls = "users-cal-day";
        if (ds === todayStr) { cls += " today"; }
        if (ds === selected) { cls += " sel"; }
        dayCells += '<button type="button" class="' + cls + '" data-date="' + ds + '">' + d + '</button>';
      }

      calendar.innerHTML =
          '<div class="users-cal-head">'
        +   '<button type="button" class="users-cal-nav" data-cal-prev>‹</button>'
        +   '<span class="users-cal-title">' + MONTHS[month] + ' ' + year + '</span>'
        +   '<button type="button" class="users-cal-nav" data-cal-next>›</button>'
        + '</div>'
        + '<div class="users-cal-grid">' + cells + dayCells + '</div>';
    }

    function show() {
      if (selected) {
        var parts = selected.split("-");
        year = Number(parts[0]);
        month = Number(parts[1]) - 1;
      } else {
        var nowD = new Date();
        year = nowD.getFullYear();
        month = nowD.getMonth();
      }
      renderCal();
      document.body.appendChild(calendar);
      calendar.hidden = false;
      position();
    }

    function position() {
      var rect = dateInput.getBoundingClientRect();
      var calW = calendar.offsetWidth || 264;
      var calH = calendar.offsetHeight || 250;
      var left = Math.min(Math.max(rect.left, 8), window.innerWidth - calW - 8);
      var below = rect.bottom + 6 + calH <= window.innerHeight - 8;
      var top = below ? rect.bottom + 6 : Math.max(8, rect.top - calH - 6);
      calendar.style.left = left + "px";
      calendar.style.top = top + "px";
      calendar.style.maxHeight = (window.innerHeight - 16) + "px";
      calendar.style.overflowY = "auto";
    }

    function hide() { calendar.hidden = true; }

    function select(ds) {
      selected = ds;
      dateValue.value = ds;
      dateInput.value = display(ds);
      hide();
    }

    function init() {
      dateToggle.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (calendar.hidden) { show(); } else { hide(); }
      });
      dateInput.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (calendar.hidden) { show(); } else { hide(); }
      });
      document.addEventListener("click", function (ev) {
        if (calendar.hidden) { return; }
        if (!calendar.contains(ev.target) && !dateToggle.contains(ev.target) && !dateInput.contains(ev.target)) {
          hide();
        }
      });
      calendar.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var prev = ev.target.closest("[data-cal-prev]");
        if (prev) {
          month -= 1;
          if (month < 0) { month = 11; year -= 1; }
          renderCal();
          return;
        }
        var next = ev.target.closest("[data-cal-next]");
        if (next) {
          month += 1;
          if (month > 11) { month = 0; year += 1; }
          renderCal();
          return;
        }
        var day = ev.target.closest("[data-date]");
        if (day) { select(day.getAttribute("data-date")); }
      });
    }

    return { init: init, show: show, hide: hide, setSelected: function (ds) { selected = ds || ""; } };
  })();

  function render() {
    var q = state.query.toLowerCase();
    var list = state.rates.filter(function (t) {
      if (!q) { return true; }
      return (t.name || "").toLowerCase().indexOf(q) !== -1
        || (t.tax_type || "").toLowerCase().indexOf(q) !== -1;
    });

    count.textContent = list.length + " of " + state.rates.length + " tax rates";
    empty.classList.toggle("visible", list.length === 0);
    loading.style.display = "none";

    body.innerHTML = list.map(function (t) {
      var type = t.tax_type || "—";
      return ''
        + '<tr data-id="' + t.id + '">'
        +   '<td><span class="users-name">' + t.name + '</span></td>'
        +   '<td class="users-rate">' + fmtRate(t.rate) + '</td>'
        +   '<td class="users-email">' + type + '</td>'
        +   '<td class="users-lastlogin">' + (t.effective_date || "—") + '</td>'
        +   '<td><span class="users-status ' + statusWord(t.is_active) + '"><i class="users-dot" aria-hidden="true"></i>' + (t.is_active ? "Active" : "Inactive") + '</span></td>'
        +   '<td class="users-actions">'
        +     (t.is_active
        ? '<button type="button" class="users-link" data-taxes-act="deactivate" data-id="' + t.id + '">Deactivate</button>'
        : '<button type="button" class="users-link" data-taxes-act="activate" data-id="' + t.id + '">Activate</button>')
        +     '<button type="button" class="users-link" data-taxes-act="edit" data-id="' + t.id + '">Edit</button>'
        +     '<button type="button" class="users-link danger" data-taxes-act="delete" data-id="' + t.id + '">Delete</button>'
        +   '</td>'
        + '</tr>';
    }).join("");
  }

  async function loadRates() {
    loading.style.display = "block";
    try {
      var data = await api(API + "?page_size=100");
      state.rates = data.results || data;
      render();
    } catch (err) {
      loading.style.display = "none";
      body.innerHTML = "";
      empty.classList.remove("visible");
      showBanner("Could not load tax rates: " + err.message, "error");
    }
  }

  function showModal() {
    document.body.appendChild(modal);
    modal.hidden = false;
    calView.hide();
  }

  function openAdd() {
    modalTitle.textContent = "Add tax rate";
    form.reset();
    form.elements["id"].value = "";
    form.elements["is_active"].value = "true";
    el('[data-taxes-save]').textContent = "Create tax rate";
    statusSelect.sync();
    dateInput.value = "Select date";
    dateValue.value = "";
    calView.setSelected("");
    showModal();
    form.elements["name"].focus();
  }

  function openEdit(tax) {
    modalTitle.textContent = "Edit tax rate";
    form.reset();
    form.elements["id"].value = tax.id;
    form.elements["name"].value = tax.name || "";
    form.elements["rate"].value = Number(tax.rate);
    form.elements["tax_type"].value = tax.tax_type || "";
    form.elements["effective_date"].value = tax.effective_date || "";
    form.elements["is_active"].value = tax.is_active ? "true" : "false";
    statusSelect.sync();
    el('[data-taxes-save]').textContent = "Save changes";
    var ed = tax.effective_date || "";
    dateValue.value = ed;
    dateInput.value = ed || "Select date";
    calView.setSelected(ed);
    showModal();
  }

  function closeModal() { modal.hidden = true; calView.hide(); }

  async function submitForm(ev) {
    ev.preventDefault();
    hideBanner();

    var id = form.elements["id"].value;
    var payload = {
      name: form.elements["name"].value.trim(),
      rate: form.elements["rate"].value,
      tax_type: form.elements["tax_type"].value.trim(),
      effective_date: form.elements["effective_date"].value,
      is_active: form.elements["is_active"].value === "true",
    };

    try {
      if (id) {
        await api(API + id + "/", { method: "PATCH", body: JSON.stringify(payload) });
        showBanner("Tax rate updated.", "success");
      } else {
        await api(API, { method: "POST", body: JSON.stringify(payload) });
        showBanner("Tax rate created.", "success");
      }
      closeModal();
      loadRates();
    } catch (err) {
      showBanner("Could not save tax rate: " + err.message, "error");
    }
  }

  async function toggleStatus(id, activate) {
    hideBanner();
    try {
      await api(API + id + "/" + (activate ? "activate" : "deactivate") + "/", { method: "POST" });
      showBanner(activate ? "Tax rate activated." : "Tax rate deactivated.", "success");
      loadRates();
    } catch (err) {
      showBanner("Could not change status: " + err.message, "error");
    }
  }

  var deleteModal = el("[data-taxes-delete-modal]");
  var deleteName = el("[data-taxes-delete-name]");
  var deletingId = null;

  function showDeleteConfirm(id) {
    var tax = state.rates.find(function (t) { return t.id === id; });
    deletingId = id;
    deleteName.textContent = tax ? tax.name : "this tax rate";
    document.body.appendChild(deleteModal);
    deleteModal.hidden = false;
  }
  function hideDeleteConfirm() {
    deleteModal.hidden = true;
    deletingId = null;
  }

  async function removeTax(id) {
    hideBanner();
    try {
      await api(API + id + "/", { method: "DELETE" });
      showBanner("Tax rate deleted.", "success");
      loadRates();
    } catch (err) {
      showBanner("Could not delete tax rate: " + err.message, "error");
    }
  }

  body.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-taxes-act]");
    if (!btn) { return; }
    var act = btn.getAttribute("data-taxes-act");
    var id = btn.getAttribute("data-id");
    var tax = state.rates.find(function (t) { return t.id === id; });
    if (act === "deactivate") { toggleStatus(id, false); }
    else if (act === "activate") { toggleStatus(id, true); }
    else if (act === "edit" && tax) { openEdit(tax); }
    else if (act === "delete") { showDeleteConfirm(id); }
  });

  search.addEventListener("input", function () {
    state.query = this.value.trim();
    render();
  });

  el('[data-taxes-open-add]').addEventListener("click", openAdd);
  els("[data-taxes-modal-close]").forEach(function (b) {
    b.addEventListener("click", closeModal);
  });
  modal.addEventListener("click", function (ev) { if (ev.target === modal) { closeModal(); } });
  form.addEventListener("submit", submitForm);

  calView.init();

  els("[data-taxes-delete-close]").forEach(function (b) {
    b.addEventListener("click", hideDeleteConfirm);
  });
  el("[data-taxes-delete-confirm]").addEventListener("click", function () {
    var id = deletingId;
    hideDeleteConfirm();
    if (id) { removeTax(id); }
  });
  deleteModal.addEventListener("click", function (ev) {
    if (ev.target === deleteModal) { hideDeleteConfirm(); }
  });

  loadRates();
}

function initFinancialPane() {
  "use strict";
  var API = "/api/accounting/accounts/";
  var RULES_API = "/api/company/financial-settings/";
  var TAXES_API = "/api/taxes/tax-rates/?page_size=100";
  var state = { accounts: [], query: "" };

  var el = function (sel, root) { return (root || document).querySelector(sel); };

  var banner = el("[data-fin-banner]");
  var body = el("[data-fin-body]");
  var empty = el("[data-fin-empty]");
  var loading = el("[data-fin-loading]");
  var count = el("[data-fin-count]");
  var search = el("[data-fin-search]");
  var modal = el("[data-fin-modal]");
  var form = el("[data-fin-form]");
  var modalTitle = el("[data-fin-modal-title]");
  var parentSelect = form.elements["parent_account"];
  var statusSelect = fancySelect(form.elements["is_active"]);
  var parentAccountSelect = fancySelect(parentSelect);

  var statTotal = el("[data-fin-stat-total]");
  var statActive = el("[data-fin-stat-active]");
  var statInactive = el("[data-fin-stat-inactive]");

  var rulesForm = el("[data-fin-rules-form]");
  var rulesBanner = el("[data-fin-rules-banner]");
  var rulesStatus = el("[data-fin-rules-status]");
  var rulesField = function (name) {
    return rulesForm ? rulesForm.elements[name] : null;
  };

  function getCookie(name) {
    var m = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[2]) : "";
  }

  async function api(url, options) {
    options = options || {};
    var opts = {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    };
    if (options.method && !["GET", "HEAD"].includes(options.method)) {
      opts.headers["X-CSRFToken"] = getCookie("csrftoken");
    }
    var res = await fetch(url, opts);
    if (!res.ok) {
      var detail = res.statusText;
      try { detail = JSON.stringify(await res.json()); } catch (e) { /* ignore */ }
      throw new Error(detail || ("HTTP " + res.status));
    }
    if (res.status === 204) { return null; }
    return res.json();
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function showBanner(text, type) {
    banner.textContent = text;
    banner.className = "users-banner" + (type ? " " + type : "");
    banner.hidden = false;
    clearTimeout(banner._t);
    banner._t = setTimeout(function () { banner.hidden = true; }, 5000);
  }

  function hideBanner() { banner.hidden = true; }

  function statusWord(isActive) {
    return isActive ? "active" : "inactive";
  }

  function typeClass(type) {
    var t = String(type || "").toLowerCase();
    var map = {
      asset: "t-asset", revenue: "t-revenue",
      liability: "t-liability", equity: "t-equity", expense: "t-expense",
    };
    return map[t] || "t-other";
  }

  function buildParentOptions(excludeId) {
    parentSelect.innerHTML =
        '<option value="">— None —</option>'
      + state.accounts
          .filter(function (a) { return a.id !== excludeId; })
          .sort(function (a, b) { return String(a.code).localeCompare(String(b.code), undefined, { numeric: true }); })
          .map(function (a) {
            return '<option value="' + a.id + '">' + escapeHtml(a.code + " — " + a.name) + '</option>';
          })
          .join("");
    parentAccountSelect.sync();
  }

  function render() {
    var q = state.query.toLowerCase().trim();
    var list = state.accounts.filter(function (a) {
      if (!q) { return true; }
      return (a.code || "").toLowerCase().indexOf(q) !== -1
        || (a.name || "").toLowerCase().indexOf(q) !== -1
        || (a.account_type || "").toLowerCase().indexOf(q) !== -1;
    });

    count.textContent = list.length + " of " + state.accounts.length + " accounts";
    empty.classList.toggle("visible", list.length === 0);
    loading.style.display = "none";

    var activeCount = state.accounts.filter(function (a) { return a.is_active; }).length;
    if (statTotal) { statTotal.textContent = state.accounts.length; }
    if (statActive) { statActive.textContent = activeCount; }
    if (statInactive) { statInactive.textContent = state.accounts.length - activeCount; }

    body.innerHTML = list.map(function (a) {
      return ''
        + '<tr data-id="' + a.id + '">'
        +   '<td class="fin-code">' + escapeHtml(a.code) + '</td>'
        +   '<td><span class="users-name">' + escapeHtml(a.name) + '</span></td>'
        +   '<td><span class="fin-type-pill ' + typeClass(a.account_type) + '">' + escapeHtml(a.account_type || "—") + '</span></td>'
        +   '<td><span class="users-status ' + statusWord(a.is_active) + '"><i class="users-dot" aria-hidden="true"></i>' + (a.is_active ? "Active" : "Inactive") + '</span></td>'
        +   '<td class="users-actions">'
        +     (a.is_active
        ? '<button type="button" class="users-link" data-fin-act="deactivate" data-id="' + a.id + '">Deactivate</button>'
        : '<button type="button" class="users-link" data-fin-act="activate" data-id="' + a.id + '">Activate</button>')
        +     '<button type="button" class="users-link" data-fin-act="edit" data-id="' + a.id + '">Edit</button>'
        +   '</td>'
        + '</tr>';
    }).join("");
  }

  async function loadAccounts() {
    loading.style.display = "block";
    try {
      var data = await api(API + "?page_size=100");
      state.accounts = data.results || data;
      render();
    } catch (err) {
      loading.style.display = "none";
      body.innerHTML = "";
      empty.classList.remove("visible");
      showBanner("Could not load the chart of accounts: " + err.message, "error");
    }
  }

  function showModal() {
    document.body.appendChild(modal);
    modal.hidden = false;
  }

  function openAdd() {
    modalTitle.textContent = "Add account";
    form.reset();
    form.elements["id"].value = "";
    form.elements["is_active"].value = "true";
    el("[data-fin-save]").textContent = "Create account";
    buildParentOptions("");
    statusSelect.sync();
    showModal();
    form.elements["code"].focus();
  }

  function openEdit(account) {
    modalTitle.textContent = "Edit account";
    form.reset();
    form.elements["id"].value = account.id;
    form.elements["code"].value = account.code || "";
    form.elements["name"].value = account.name || "";
    form.elements["account_type"].value = account.account_type || "";
    form.elements["is_active"].value = account.is_active ? "true" : "false";
    el("[data-fin-save]").textContent = "Save changes";
    buildParentOptions(account.id);
    parentAccountSelect.setValue(account.parent_account || "");
    statusSelect.sync();
    showModal();
  }

  function closeModal() { modal.hidden = true; }

  async function submitForm(ev) {
    ev.preventDefault();
    hideBanner();

    var id = form.elements["id"].value;
    var payload = {
      code: form.elements["code"].value.trim(),
      name: form.elements["name"].value.trim(),
      account_type: form.elements["account_type"].value.trim(),
      parent_account: form.elements["parent_account"].value || null,
      is_active: form.elements["is_active"].value === "true",
    };

    try {
      if (id) {
        await api(API + id + "/", { method: "PATCH", body: JSON.stringify(payload) });
        showBanner("Account updated.", "success");
      } else {
        await api(API, { method: "POST", body: JSON.stringify(payload) });
        showBanner("Account created.", "success");
      }
      closeModal();
      loadAccounts();
    } catch (err) {
      showBanner("Could not save account: " + err.message, "error");
    }
  }

  async function toggleStatus(id, activate) {
    hideBanner();
    try {
      await api(API + id + "/", { method: "PATCH", body: JSON.stringify({ is_active: activate }) });
      showBanner(activate ? "Account activated." : "Account deactivated.", "success");
      loadAccounts();
    } catch (err) {
      showBanner("Could not change status: " + err.message, "error");
    }
  }

  function showRulesBanner(text, type) {
    rulesBanner.textContent = text;
    rulesBanner.className = "users-banner" + (type ? " " + type : "");
    rulesBanner.hidden = false;
    clearTimeout(rulesBanner._t);
    rulesBanner._t = setTimeout(function () { rulesBanner.hidden = true; }, 5000);
  }

  function setRulesField(name, value) {
    var field = rulesField(name);
    if (!field) { return; }
    if (field.type === "checkbox") { field.checked = !!value; }
    else { field.value = value == null ? "" : String(value); }
  }

  function populateTaxRateSelect(rates) {
    var select = rulesField("default_tax_rate");
    if (!select) { return; }
    var options = '<option value="">— No default —</option>';
    (rates || []).forEach(function (r) {
      options += '<option value="' + r.id + '">'
        + escapeHtml(r.name + " (" + r.rate + "%)")
        + '</option>';
    });
    select.innerHTML = options;
  }

  async function loadRules() {
    if (!rulesForm) { return; }
    try {
      var data = await api(RULES_API);
      var rates = [];
      try {
        var taxes = await api(TAXES_API);
        rates = taxes.results || taxes;
      } catch (taxErr) { /* tax dropdown is optional */ }
      populateTaxRateSelect(rates);
      setRulesField("fiscal_year_start_month", data.fiscal_year_start_month);
      setRulesField("fiscal_year_start_day", data.fiscal_year_start_day);
      setRulesField("lock_financial_periods", data.lock_financial_periods);
      setRulesField("period_lock_after_days", data.period_lock_after_days);
      setRulesField("default_tax_rate", data.default_tax_rate || "");
      setRulesField("default_payment_terms", data.default_payment_terms);
      setRulesField("retention_percent", data.retention_percent);
      setRulesField("budget_alert_percent", data.budget_alert_percent);
      if (rulesStatus) {
        rulesStatus.textContent = "Defaults synced";
        rulesStatus.classList.remove("is-saved");
      }
    } catch (err) {
      showRulesBanner("Could not load financial rules: " + err.message, "error");
    }
  }

  async function saveRules(ev) {
    ev.preventDefault();
    rulesBanner.hidden = true;
    var days = rulesField("period_lock_after_days").value;
    var payload = {
      fiscal_year_start_month: parseInt(rulesField("fiscal_year_start_month").value, 10),
      fiscal_year_start_day: parseInt(rulesField("fiscal_year_start_day").value, 10),
      lock_financial_periods: rulesField("lock_financial_periods").checked,
      period_lock_after_days: days === "" ? null : parseInt(days, 10),
      default_tax_rate: rulesField("default_tax_rate").value || null,
      default_payment_terms: rulesField("default_payment_terms").value,
      retention_percent: rulesField("retention_percent").value,
      budget_alert_percent: rulesField("budget_alert_percent").value,
    };
    try {
      var saved = await api(RULES_API, { method: "PATCH", body: JSON.stringify(payload) });
      showRulesBanner("Financial rules saved.", "success");
      if (rulesStatus) {
        rulesStatus.textContent = "Saved";
        rulesStatus.classList.add("is-saved");
      }
      loadRules();
    } catch (err) {
      showRulesBanner("Could not save financial rules: " + err.message, "error");
    }
  }

  body.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-fin-act]");
    if (!btn) { return; }
    var act = btn.getAttribute("data-fin-act");
    var id = btn.getAttribute("data-id");
    var account = state.accounts.find(function (a) { return a.id === id; });
    if (act === "deactivate") { toggleStatus(id, false); }
    else if (act === "activate") { toggleStatus(id, true); }
    else if (act === "edit" && account) { openEdit(account); }
  });

  search.addEventListener("input", function () {
    state.query = this.value.trim();
    render();
  });

  el("[data-fin-open-add]").addEventListener("click", openAdd);
  Array.prototype.forEach.call(document.querySelectorAll("[data-fin-modal-close]"), function (b) {
    b.addEventListener("click", closeModal);
  });
  modal.addEventListener("click", function (ev) { if (ev.target === modal) { closeModal(); } });
  form.addEventListener("submit", submitForm);
  if (rulesForm) {
    rulesForm.addEventListener("submit", saveRules);
    loadRules();
  }

  var subTabs = document.querySelectorAll("[data-fin-subtab]");
  var subSections = document.querySelectorAll("[data-fin-section]");
  function activateSubTab(name) {
    subTabs.forEach(function (b) {
      b.classList.toggle("active", b.getAttribute("data-fin-subtab") === name);
    });
    subSections.forEach(function (s) {
      s.hidden = s.getAttribute("data-fin-section") !== name;
    });
  }
  subTabs.forEach(function (b) {
    b.addEventListener("click", function () {
      activateSubTab(b.getAttribute("data-fin-subtab"));
    });
  });

  loadAccounts();
}

function initNotificationsPane() {
  "use strict";
  var API = "/api/notifications/preferences/";
  var list = document.querySelector("[data-notif-prefs-list]");
  var banner = document.querySelector("[data-notif-banner]");
  var status = document.querySelector("[data-notif-status]");
  var state = {};

  function getCookie(name) {
    var m = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[2]) : "";
  }

  async function api(url, options) {
    options = options || {};
    var opts = {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    };
    if (options.method && !["GET", "HEAD"].includes(options.method)) {
      opts.headers["X-CSRFToken"] = getCookie("csrftoken");
    }
    var res = await fetch(url, opts);
    if (!res.ok) {
      var detail = res.statusText;
      try { detail = JSON.stringify(await res.json()); } catch (e) { /* ignore */ }
      throw new Error(detail || ("HTTP " + res.status));
    }
    if (res.status === 204) { return null; }
    return res.json();
  }

  function showBanner(text, type) {
    banner.textContent = text;
    banner.className = "users-banner" + (type ? " " + type : "");
    banner.hidden = false;
    clearTimeout(banner._t);
    banner._t = setTimeout(function () { banner.hidden = true; }, 5000);
  }

  var order = [
    "OVERDUE_INVOICE", "PAYMENT_DUE", "LOW_INVENTORY",
    "PO_AWAITING_APPROVAL", "BUDGET_OVERRUN", "DEADLINE_APPROACHING",
  ];

  function hasWindow(type) {
    return type === "PAYMENT_DUE" || type === "DEADLINE_APPROACHING";
  }

  function render() {
    list.innerHTML = order.map(function (type) {
      var p = state[type] || {};
      var label = p.label || type;
      var role = p.role || "OWNER";
      var desc = p.description || "";
      var checked = p.is_enabled !== false;
      var windowInput = hasWindow(type)
        ? '<input type="number" class="notif-window" min="1" max="180" step="1" data-notif-type="'
            + type + '" value="' + (p.window_days == null ? "" : p.window_days) + '" placeholder="—">'
        : "";
      return ''
        + '<div class="notif-row" data-notif-type="' + type + '">'
        +   '<div class="notif-row-main">'
        +     '<div class="notif-row-title">'
        +       '<strong>' + escapeHtml(label) + '</strong>'
        +       '<span class="notif-role">' + role + '</span>'
        +     '</div>'
        +     '<p>' + escapeHtml(desc) + '</p>'
        +   '</div>'
        +   '<div class="notif-row-controls">'
        +     (hasWindow(type)
        ?       '<div class="notif-window-wrap"><label>' + escapeHtml(windowLabel(type)) + '</label>' + windowInput + '<em>days</em></div>'
        :       '')
        +     '<label class="fin-switch">'
        +       '<input type="checkbox" data-notif-toggle data-notif-type="' + type + '"' + (checked ? ' checked' : '') + '>'
        +       '<span class="fin-switch-track"><span class="fin-switch-thumb"></span></span>'
        +     '</label>'
        +   '</div>'
        + '</div>';
    }).join("");
  }

  function windowLabel(type) {
    return type === "DEADLINE_APPROACHING" ? "Look ahead" : "Due soon";
  }

  function setStatus(saved) {
    if (status) {
      status.textContent = saved ? "Saved" : "Current settings";
      status.classList.toggle("is-saved", !!saved);
    }
  }

  function rowNode(type) {
    return list.querySelector('[data-notif-type="' + type + '"]');
  }

  function patch(type) {
    var row = rowNode(type);
    if (!row) { return; }
    var toggle = row.querySelector('[data-notif-toggle]');
    var windowInput = row.querySelector(".notif-window");
    var payload = {};
    var prefs = { is_enabled: toggle.checked };
    if (windowInput) {
      var v = windowInput.value;
      prefs.window_days = v === "" ? null : Math.max(1, parseInt(v, 10) || 1);
    }
    payload[type] = prefs;
    api(API, { method: "PATCH", body: JSON.stringify(payload) })
      .then(function () {
        return load();
      })
      .then(function () {
        setStatus(true);
        showBanner(labelFor(type) + " updated.", "success");
      })
      .catch(function (err) {
        load();
        showBanner("Could not save: " + err.message, "error");
      });
  }

  function labelFor(type) {
    return (state[type] && state[type].label) || type;
  }

  list.addEventListener("change", function (ev) {
    var toggle = ev.target.closest('[data-notif-toggle]');
    if (toggle) { patch(toggle.getAttribute("data-notif-type")); return; }
    var win = ev.target.closest(".notif-window");
    if (win) { patch(win.getAttribute("data-notif-type")); }
  });

  async function load() {
    try {
      var data = await api(API);
      state = data || {};
      render();
      return state;
    } catch (err) {
      list.innerHTML = '';
      showBanner("Could not load notification preferences: " + err.message, "error");
    }
  }

  load();
}

function initUsersPane() {
  "use strict";
  var API = "/api/auth/users/";
  var currentUserInput = document.getElementById("current-user-id");
  var CURRENT_USER_ID = currentUserInput ? currentUserInput.value : "";

  var state = { users: [], search: "", query: "" };

  var el = function (sel, root) { return (root || document).querySelector(sel); };
  var els = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  var banner = el("[data-users-banner]");
  var body = el("[data-users-body]");
  var empty = el("[data-users-empty]");
  var loading = el("[data-users-loading]");
  var count = el("[data-users-count]");
  var search = el("[data-users-search]");
  var modal = el("[data-users-modal]");
  var form = el("[data-users-form]");
  var modalTitle = el("[data-users-modal-title]");
  var createHint = el("[data-users-create-hint]");

  var roleSelect = fancySelect(form.elements["role"]);
  var statusSelect = fancySelect(form.elements["is_active"]);

  function getCookie(name) {
    var m = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[2]) : "";
  }

  async function api(url, options) {
    options = options || {};
    var opts = {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    };
    if (options.method && !["GET", "HEAD"].includes(options.method)) {
      opts.headers["X-CSRFToken"] = getCookie("csrftoken");
    }
    var res = await fetch(url, opts);
    if (!res.ok) {
      var detail = res.statusText;
      try { detail = JSON.stringify(await res.json()); } catch (e) { /* ignore */ }
      throw new Error(detail || ("HTTP " + res.status));
    }
    if (res.status === 204) { return null; }
    return res.json();
  }

  function initials(u) {
    return ((u.first_name || "?")[0] + (u.last_name || "?")[0]).toUpperCase();
  }

  function initialsName(u) {
    return (u.first_name || "") + " " + (u.last_name || "");
  }

  function roleWord(role) {
    return role === "OWNER" ? "owner" : role === "ACCOUNTANT" ? "accountant" : "user";
  }

  function statusWord(isActive) {
    return isActive ? "active" : "inactive";
  }

  function lastLogin(u) {
    if (!u.last_login) { return "Never"; }
    return new Date(u.last_login).toLocaleString();
  }

  function showBanner(text, type) {
    banner.textContent = text;
    banner.className = "users-banner" + (type ? " " + type : "");
    banner.hidden = false;
    clearTimeout(banner._t);
    banner._t = setTimeout(function () { banner.hidden = true; }, 5000);
  }

  function hideBanner() { banner.hidden = true; }

  function render() {
    var q = state.query.toLowerCase();
    var list = state.users.filter(function (u) {
      if (!q) { return true; }
      return (u.first_name || "").toLowerCase().indexOf(q) !== -1
        || (u.last_name || "").toLowerCase().indexOf(q) !== -1
        || (u.username || "").toLowerCase().indexOf(q) !== -1
        || (u.email || "").toLowerCase().indexOf(q) !== -1
        || (u.role || "").toLowerCase().indexOf(q) !== -1;
    });

    count.textContent = list.length + " of " + state.users.length + " users";
    empty.classList.toggle("visible", list.length === 0);
    loading.style.display = "none";

    body.innerHTML = list.map(function (u) {
      var isSelf = CURRENT_USER_ID && u.id === CURRENT_USER_ID;
      var roleLabel = u.role_display || u.role;
      var actions = "";
      if (isSelf) {
        actions = '<span class="users-self">You</span>';
      } else {
        actions = ''
          + (u.is_active
            ? '<button type="button" class="users-link" data-users-act="deactivate" data-id="' + u.id + '">Deactivate</button>'
            : '<button type="button" class="users-link" data-users-act="activate" data-id="' + u.id + '">Activate</button>')
          + '<button type="button" class="users-link" data-users-act="edit" data-id="' + u.id + '">Edit</button>'
          + '<button type="button" class="users-link danger" data-users-act="delete" data-id="' + u.id + '">Delete</button>';
      }
      return ''
        + '<tr data-id="' + u.id + '">'
        +   '<td><div class="users-identity">'
        +     '<span class="users-avatar">' + initials(u) + '</span>'
        +     '<div><div class="users-name">' + (u.first_name || "") + ' ' + (u.last_name || "") + '</div>'
        +     '<div class="users-username">@' + (u.username || "") + '</div></div>'
        +   '</div></td>'
        +   '<td class="users-email">' + (u.email || "") + '</td>'
        +   '<td><span class="users-badge ' + roleWord(u.role) + '">' + roleLabel + '</span></td>'
        +   '<td><span class="users-status ' + statusWord(u.is_active) + '"><i class="users-dot" aria-hidden="true"></i>' + (u.is_active ? "Active" : "Inactive") + '</span></td>'
        +   '<td class="users-lastlogin">' + lastLogin(u) + '</td>'
        +   '<td class="users-actions">' + actions + '</td>'
        + '</tr>';
    }).join("");
  }

  async function loadUsers() {
    loading.style.display = "block";
    try {
      var data = await api(API + "?page_size=100");
      state.users = data.results || data;
      render();
    } catch (err) {
      loading.style.display = "none";
      body.innerHTML = "";
      empty.classList.remove("visible");
      showBanner("Could not load users: " + err.message, "error");
    }
  }

  function openAdd() {
    modalTitle.textContent = "Add user";
    createHint.style.display = "block";
    form.reset();
    form.elements["id"].value = "";
    form.elements["is_active"].value = "true";
    var saveBtn = el('[data-users-save]');
    saveBtn.textContent = "Create user";
    roleSelect.sync();
    statusSelect.sync();
    document.body.appendChild(modal);
    modal.hidden = false;
    form.elements["first_name"].focus();
  }

  function openEdit(user) {
    modalTitle.textContent = "Edit user";
    createHint.style.display = "none";
    form.reset();
    form.elements["id"].value = user.id;
    form.elements["first_name"].value = user.first_name || "";
    form.elements["last_name"].value = user.last_name || "";
    form.elements["email"].value = user.email || "";
    form.elements["phone"].value = user.phone || "";
    form.elements["role"].value = user.role;
    form.elements["is_active"].value = user.is_active ? "true" : "false";
    var saveBtn = el('[data-users-save]');
    saveBtn.textContent = "Save changes";
    roleSelect.sync();
    statusSelect.sync();
    document.body.appendChild(modal);
    modal.hidden = false;
  }

  function closeModal() { modal.hidden = true; }

  async function submitForm(ev) {
    ev.preventDefault();
    hideBanner();

    var id = form.elements["id"].value;
    var payload = {
      first_name: form.elements["first_name"].value.trim(),
      last_name: form.elements["last_name"].value.trim(),
      email: form.elements["email"].value.trim(),
      phone: form.elements["phone"].value.trim(),
      role: form.elements["role"].value,
      is_active: form.elements["is_active"].value === "true",
    };

    try {
      if (id) {
        await api(API + id + "/", { method: "PATCH", body: JSON.stringify(payload) });
        showBanner("User updated.", "success");
      } else {
        await api(API, { method: "POST", body: JSON.stringify({
          first_name: payload.first_name,
          last_name: payload.last_name,
          email: payload.email,
          role: payload.role,
          phone: payload.phone || undefined,
        }) });
        showBanner("User created. Their login credentials were emailed.", "success");
      }
      closeModal();
      loadUsers();
    } catch (err) {
      showBanner("Could not save user: " + err.message, "error");
    }
  }

  async function toggleStatus(id, activate) {
    hideBanner();
    try {
      await api(API + id + "/" + (activate ? "activate" : "deactivate") + "/", { method: "POST" });
      showBanner(activate ? "User activated." : "User deactivated.", "success");
      loadUsers();
    } catch (err) {
      showBanner("Could not change status: " + err.message, "error");
    }
  }

  async function removeUser(id) {
    hideBanner();
    if (!confirm("Delete this user? This cannot be undone.")) { return; }
    try {
      await api(API + id + "/", { method: "DELETE" });
      showBanner("User deleted.", "success");
      loadUsers();
    } catch (err) {
      showBanner("Could not delete user: " + err.message, "error");
    }
  }

  body.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-users-act]");
    if (!btn) { return; }
    var act = btn.getAttribute("data-users-act");
    var id = btn.getAttribute("data-id");
    var user = state.users.find(function (u) { return u.id === id; });
    if (act === "deactivate") { toggleStatus(id, false); }
    else if (act === "activate") { toggleStatus(id, true); }
    else if (act === "edit" && user) { openEdit(user); }
    else if (act === "delete") { removeUser(id); }
  });

  search.addEventListener("input", function () {
    state.query = this.value.trim();
    render();
  });

  el('[data-users-open-add]').addEventListener("click", openAdd);
  els("[data-users-modal-close]").forEach(function (b) {
    b.addEventListener("click", closeModal);
  });
  modal.addEventListener("click", function (ev) { if (ev.target === modal) { closeModal(); } });
  form.addEventListener("submit", submitForm);

  loadUsers();
}

/* ---- Audit trail pane ---- */
  function initAuditPane() {
  "use strict";
  var API = "/api/audit/audit-logs/";
  var ENTITIES_API = "/api/audit/entities/";
  var entityOptions = [];
  var state = { entries: [], query: "", entity_type: "", dateFrom: "", dateTo: "", total: 0 };

  var el = function (sel, root) { return (root || document).querySelector(sel); };

  var banner = el("[data-audit-banner]");
  var body = el("[data-audit-body]");
  var empty = el("[data-audit-empty]");
  var loading = el("[data-audit-loading]");
  var count = el("[data-audit-count]");
  var search = el("[data-audit-search]");
  var entityWrap = el("[data-audit-entity-wrap]");
  var entityToggle = el("[data-audit-entity-toggle]");
  var entityLabelEl = el("[data-audit-entity-label]");
  var entityMenu = el("[data-audit-entity-menu]");
  var entityCats = el("[data-audit-entity-cats]");
  var entitySub = el("[data-audit-entity-sub]");
  if (!entityToggle || !entityMenu) {
    console.warn("audit entity dropdown missing", {entityToggle: !!entityToggle, entityMenu: !!entityMenu});
  }
  var entityGroups = [];
  var clearBtn = el("[data-audit-clear]");
  var detailModal = el("[data-audit-detail-modal]");
  var detailMeta = el("[data-audit-detail-meta]");
  var detailDiff = el("[data-audit-detail-diff]");

  /* ---- Custom calendars (From / To dates) ---- */
  function buildCal(containerEl, hiddenInputEl, textInputEl, anchorEl, onUpdate) {
    var YEAR = new Date().getFullYear();
    var MONTH = new Date().getMonth();
    var selected = "";
    var MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
    var DOWS = ["Su","Mo","Tu","We","Th","Fr","Sa"];
    function fmt(d) {
      var m = String(d.getMonth() + 1).padStart(2, "0");
      var day = String(d.getDate()).padStart(2, "0");
      return d.getFullYear() + "-" + m + "-" + day;
    }
    function render() {
      var first = new Date(YEAR, MONTH, 1);
      var startDow = first.getDay();
      var daysInMonth = new Date(YEAR, MONTH + 1, 0).getDate();
      var todayStr = fmt(new Date());
      var html = '<div class="users-cal-head">'
        + '<button type="button" class="users-cal-nav" data-cal-prev aria-label="Previous month">‹</button>'
        + '<span class="users-cal-title">' + MONTHS[MONTH] + " " + YEAR + "</span>"
        + '<button type="button" class="users-cal-nav" data-cal-next aria-label="Next month">›</button></div>'
        + '<div class="users-cal-grid">';
      for (var d = 0; d < DOWS.length; d++) { html += '<div class="users-cal-dow">' + DOWS[d] + "</div>"; }
      for (var b = 0; b < startDow; b++) { html += '<div class="users-cal-day out"></div>'; }
      for (var day = 1; day <= daysInMonth; day++) {
        var ds = fmt(new Date(YEAR, MONTH, day));
        var cls = "users-cal-day";
        if (ds === todayStr) { cls += " today"; }
        if (selected === ds) { cls += " sel"; }
        html += '<button type="button" class="' + cls + '" data-date="' + ds + '">' + day + "</button>";
      }
      containerEl.innerHTML = html + "</div>";
    }
    containerEl.addEventListener("click", function (ev) {
      ev.stopPropagation();
      if (ev.target.closest("[data-cal-prev]")) {
        MONTH -= 1;
        if (MONTH < 0) { MONTH = 11; YEAR -= 1; }
        render();
        return;
      }
      if (ev.target.closest("[data-cal-next]")) {
        MONTH += 1;
        if (MONTH > 11) { MONTH = 0; YEAR += 1; }
        render();
        return;
      }
      var day = ev.target.closest("[data-date]");
      if (day) { select(day.getAttribute("data-date")); }
    });
    function position() {
      var rect = anchorEl.getBoundingClientRect();
      var calW = containerEl.offsetWidth || 272;
      var calH = containerEl.offsetHeight || 250;
      var left = Math.min(Math.max(rect.left, 8), window.innerWidth - calW - 8);
      var below = rect.bottom + 6 + calH <= window.innerHeight - 8;
      var top = below ? rect.bottom + 6 : Math.max(8, rect.top - calH - 6);
      containerEl.style.left = left + "px";
      containerEl.style.top = top + "px";
      containerEl.style.maxHeight = (window.innerHeight - 16) + "px";
      containerEl.style.overflowY = "auto";
    }
    function select(ds) {
      selected = ds;
      hiddenInputEl.value = ds;
      textInputEl.value = ds;
      hide();
      if (onUpdate) { onUpdate(ds); }
      render();
    }
    function show() {
      if (selected) {
        var parts = selected.split("-");
        YEAR = Number(parts[0]);
        MONTH = Number(parts[1]) - 1;
      }
      render();
      document.body.appendChild(containerEl);
      containerEl.hidden = false;
      position();
    }
    function hide() { containerEl.hidden = true; }
    render();
    return {
      show: show,
      hide: hide,
      clear: function () { selected = ""; hiddenInputEl.value = ""; textInputEl.value = ""; render(); },
      setHidden: function (v) { containerEl.hidden = v; },
    };
  }
  var fromCal = buildCal(el("[data-audit-calendar-from]"), el("[data-audit-from-value]"), el("[data-audit-from-input]"), el("[data-audit-from-toggle]"), function (ds) { state.dateFrom = ds; load(); });
  var toCal   = buildCal(el("[data-audit-calendar-to]"),   el("[data-audit-to-value]"),   el("[data-audit-to-input]"),   el("[data-audit-to-toggle]"),     function (ds) { state.dateTo = ds; load(); });
  el("[data-audit-from-toggle]").addEventListener("click", function (ev) { ev.stopPropagation(); toCal.setHidden(true); fromCal.show(); });
  el("[data-audit-to-toggle]").addEventListener("click",   function (ev) { ev.stopPropagation(); fromCal.setHidden(true); toCal.show(); });
  el("[data-audit-from-input]").addEventListener("click", function (ev) { ev.stopPropagation(); toCal.setHidden(true); fromCal.show(); });
  el("[data-audit-to-input]").addEventListener("click",   function (ev) { ev.stopPropagation(); fromCal.setHidden(true); toCal.show(); });

  var ACTION_META = {
    CREATE: { label: "Created", cls: "create" },
    UPDATE: { label: "Updated", cls: "update" },
    DELETE: { label: "Deleted", cls: "delete" },
    ACTIVATE: { label: "Activated", cls: "activate" },
    DEACTIVATE: { label: "Deactivated", cls: "deactivate" },
    LOGIN: { label: "Logged in", cls: "login" },
    LOGOUT: { label: "Logged out", cls: "login" },
  };
  var ENTITY_LABELS = (function () {
    var fallback = { user: "User", company_profile: "Company profile", tax_rate: "Tax rate", project: "Project", employee: "Employee", client: "Client", supplier: "Supplier", contractor: "Contractor", purchase_order: "Purchase order", goods_receipt: "Goods receipt", supplier_invoice: "Supplier invoice", client_invoice: "Client invoice", expense: "Expense", payment: "Payment", receipt: "Receipt", material: "Material" };
    var m = {};
    Object.keys(fallback).forEach(function (k) { m[k] = fallback[k]; });
    return m;
  })();

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function getCookie(name) {
    var m = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[2]) : "";
  }

  async function api(url, options) {
    options = options || {};
    var opts = {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    };
    if (options.method && !["GET", "HEAD"].includes(options.method)) {
      opts.headers["X-CSRFToken"] = getCookie("csrftoken");
    }
    var res = await fetch(url, opts);
    if (!res.ok) {
      var detail = res.statusText;
      try { detail = JSON.stringify(await res.json()); } catch (e) { /* ignore */ }
      throw new Error(detail || ("HTTP " + res.status));
    }
    if (res.status === 204) { return null; }
    return res.json();
  }

  function showBanner(text, type) {
    banner.textContent = text;
    banner.className = "users-banner" + (type ? " " + type : "");
    banner.hidden = false;
    clearTimeout(banner._t);
    banner._t = setTimeout(function () { banner.hidden = true; }, 5000);
  }
  function hideBanner() { banner.hidden = true; }

  function fmtDateTime(iso) {
    if (!iso) { return "—"; }
    var d = new Date(iso);
    if (isNaN(d.getTime())) { return iso; }
    var pad = function (n) { return String(n).padStart(2, "0"); };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate())
      + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function entityLabel(et) { return ENTITY_LABELS[et] || esc(et.replace(/_/g, " ")); }

  function shortId(id) {
    return id ? String(id).slice(0, 8) + "…" : "—";
  }

  function actionBadge(a) {
    var m = ACTION_META[a] || { label: a, cls: "" };
    return '<span class="users-audit-action ' + esc(m.cls) + '">' + esc(m.label) + "</span>";
  }

  function render() {
    count.textContent = state.total + (state.total === 1 ? " entry" : " entries");
    loading.style.display = "none";
    empty.classList.toggle("visible", state.entries.length === 0);

    body.innerHTML = state.entries.map(function (e) {
      return ""
        + "<tr data-id='" + esc(e.id) + "'>"
        +   "<td class='users-lastlogin'>" + fmtDateTime(e.created_at) + "</td>"
        +   "<td>" + (e.user_name ? esc(e.user_name) : '<span class="users-system">system</span>') + "</td>"
        +   "<td>" + actionBadge(e.action) + "</td>"
        +   "<td>" + entityLabel(e.entity_type) + "</td>"
        +   "<td class='users-lastlogin'>" + shortId(e.entity_id) + "</td>"
        +   "<td class='users-actions'><button type='button' class='users-link' data-audit-detail data-id='" + esc(e.id) + "'>Details</button></td>"
        + "</tr>";
    }).join("");
  }

  function syncFilterBar() {
    var active = !!(state.query || state.entity_type || state.dateFrom || state.dateTo);
    clearBtn.hidden = !active;
  }

  async function load() {
    hideBanner();
    loading.style.display = "block";
    var params = new URLSearchParams();
    params.set("page_size", "100");
    if (state.query) { params.set("search", state.query); }
    if (state.entity_type) { params.set("entity_type", state.entity_type); }
    if (state.dateFrom) { params.set("created_after", state.dateFrom + "T00:00:00"); }
    if (state.dateTo) { params.set("created_before", state.dateTo + "T23:59:59"); }
    try {
      var data = await api(API + "?" + params.toString());
      state.entries = data.results || data;
      state.total = data.count != null ? data.count : state.entries.length;
      render();
    } catch (err) {
      loading.style.display = "none";
      body.innerHTML = "";
      empty.classList.remove("visible");
      showBanner("Could not load the audit trail: " + err.message, "error");
    }
    syncFilterBar();
  }

  var searchTimer = null;
  search.addEventListener("input", function () {
    state.query = this.value.trim();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(load, 250);
  });

  document.addEventListener("click", function () { fromCal.hide(); toCal.hide(); closeEntityMenu(); });

  clearBtn.addEventListener("click", function () {
    state.query = "";
    state.entity_type = "";
    state.dateFrom = "";
    state.dateTo = "";
    search.value = "";
    setEntityFilter("");
    fromCal.clear();
    toCal.clear();
    syncFilterBar();
    load();
  });

  function hideDetail() {
    detailModal.hidden = true;
    detailMeta.innerHTML = "";
    detailDiff.innerHTML = "";
  }

  function beautifyField(f) {
    var map = {
      id: "ID",
      name: "Name",
      rate: "Rate",
      tax_type: "Tax type",
      is_active: "Status",
      effective_date: "Effective date",
      username: "Username",
      email: "Email",
      role: "Role",
      first_name: "First name",
      last_name: "Last name",
      phone: "Phone",
      is_superuser: "Superuser",
      is_archived: "Archived",
    };
    if (map[f]) { return map[f]; }
    return f.replace(/_/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  function beautifyVal(field, v) {
    if (v === null || v === undefined) { return "—"; }
    if (typeof v === "boolean") {
      return field === "is_active" ? (v ? "Active" : "Inactive") : (v ? "Yes" : "No");
    }
    if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v)) {
      var parts = v.split("-");
      var MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
      return parts[2] + " " + MON[Number(parts[1]) - 1] + " " + parts[0];
    }
    return String(v);
  }

  function fieldRows(oldV, newV) {
    var keys = oldV ? Object.keys(oldV) : [];
    if (newV) {
      Object.keys(newV).forEach(function (k) { if (keys.indexOf(k) === -1) { keys.push(k); } });
    }
    var rows = [];
    keys.forEach(function (k) {
      var hasOld = !!(oldV && oldV.hasOwnProperty(k));
      var hasNew = !!(newV && newV.hasOwnProperty(k));
      if ((hasOld && hasNew) && String(oldV[k]) === String(newV[k])) { return; }
      rows.push({
        field: beautifyField(k),
        old: hasOld ? beautifyVal(k, oldV[k]) : null,
        new: hasNew ? beautifyVal(k, newV[k]) : null,
        hasOld: hasOld,
        hasNew: hasNew,
      });
    });
    return rows;
  }

  function changeRowHtml(r) {
    var cell = "<span class='users-change-field'>" + esc(r.field) + "</span>";
    var body;
    if (r.hasOld && r.hasNew) {
      body = "<span class='users-change-old'>" + esc(r.old) + "</span><span class='users-change-arrow'>→</span><span class='users-change-new'>" + esc(r.new) + "</span>";
    } else if (r.hasNew) {
      body = "<span class='users-change-item'>" + esc(r.new) + "</span>";
    } else {
      body = "<span class='users-change-item'>" + esc(r.old) + "</span>";
    }
    return "<div class='users-change-row'>" + cell + body + "</div>";
  }

  function changeRowsHtml(rows) {
    if (!rows.length) {
      return "<div class='users-audit-note'>No field-level changes recorded for this entry.</div>";
    }
    return rows.map(changeRowHtml).join("");
  }

  function rawBlock(before, after) {
    var wrap = document.createElement("div");
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "users-audit-raw-toggle";
    btn.textContent = "Show raw data";
    btn.setAttribute("aria-expanded", "false");
    var box = document.createElement("div");
    box.className = "users-audit-raw";
    box.hidden = true;
    var pre = document.createElement("pre");
    pre.className = "users-audit-json";
    pre.textContent = JSON.stringify({ before: before, after: after }, null, 2);
    box.appendChild(pre);
    btn.addEventListener("click", function () {
      var willShow = box.hidden;
      box.hidden = !willShow;
      btn.textContent = willShow ? "Hide raw data" : "Show raw data";
      btn.setAttribute("aria-expanded", String(willShow));
    });
    wrap.appendChild(btn);
    wrap.appendChild(box);
    return wrap;
  }

  function showDetail(entry) {
    var m = ACTION_META[entry.action] || { label: entry.action, cls: "" };
    var rows = [
      ["Action", '<span class="users-audit-action ' + esc(m.cls) + '">' + esc(m.label) + "</span>"],
      ["Date &amp; time", fmtDateTime(entry.created_at)],
      ["Actor", entry.user_name ? esc(entry.user_name) : '<span class="users-system">system</span>'],
      ["IP address", entry.ip_address ? esc(entry.ip_address) : "—"],
      ["Entity", entityLabel(entry.entity_type) + " <span class='users-lastlogin'>(" + (entry.entity_id ? esc(entry.entity_id) : "—") + ")</span>"],
    ];
    detailMeta.innerHTML = rows.map(function (r) {
      return "<div class='users-audit-row'><span class='users-audit-key'>" + r[0] + "</span><span class='users-audit-val'>" + r[1] + "</span></div>";
    }).join("");

    detailDiff.innerHTML = "";
    var title = document.createElement("div");
    title.className = "users-audit-diff-title";
    if (entry.action === "CREATE") {
      title.textContent = "New record";
      detailDiff.appendChild(title);
      detailDiff.insertAdjacentHTML("beforeend", changeRowsHtml(fieldRows(null, entry.new_values)));
    } else if (entry.action === "DELETE") {
      title.textContent = "Deleted record";
      detailDiff.appendChild(title);
      detailDiff.insertAdjacentHTML("beforeend", changeRowsHtml(fieldRows(entry.old_values, null)));
    } else if (entry.old_values || entry.new_values) {
      title.textContent = "Changes";
      detailDiff.appendChild(title);
      detailDiff.insertAdjacentHTML("beforeend", changeRowsHtml(fieldRows(entry.old_values, entry.new_values)));
    } else {
      detailDiff.insertAdjacentHTML("beforeend", "<div class='users-audit-note'>No record data recorded for this action.</div>");
    }
    if (entry.old_values != null || entry.new_values != null) {
      detailDiff.appendChild(rawBlock(entry.old_values, entry.new_values));
    }

    document.body.appendChild(detailModal);
    detailModal.hidden = false;
  }

  body.addEventListener("click", async function (ev) {
    var btn = ev.target.closest("[data-audit-detail]");
    if (!btn) { return; }
    var id = btn.getAttribute("data-id");
    var entry = state.entries.find(function (x) { return x.id === id; });
    if (!entry) {
      try {
        entry = await api(API + id + "/");
      } catch (err) {
        showBanner("Could not load entry: " + err.message, "error");
        return;
      }
    }
    showDetail(entry);
  });

  function loadEntities() {
    return api(ENTITIES_API)
      .then(function (list) {
        entityOptions = list || [];
        ENTITY_LABELS = {};
        entityOptions.forEach(function (e) { ENTITY_LABELS[e.entity_type] = e.label; });
        populateEntitySelect();
      })
      .catch(function (err) {
        showBanner("Could not load entity list: " + err.message, "error");
      });
  }

  function populateEntitySelect() {
    var groups = {};
    entityOptions.forEach(function (e) {
      var cat = e.category || "Other";
      (groups[cat] = groups[cat] || []).push(e);
    });
    entityGroups = [];
    var order = { "Access & settings": 0, Projects: 1, People: 2, Partners: 3, Operations: 4, Money: 5 };
    Object.keys(groups).sort(function (a, b) {
      return (order[a] != null ? order[a] : 9) - (order[b] != null ? order[b] : 9);
    }).forEach(function (cat) {
      groups[cat].sort(function (a, b) { return a.label.localeCompare(b.label); });
      entityGroups.push({ label: cat, items: groups[cat] });
    });
    renderEntityMenu();
  }

  function setEntityFilter(value) {
    state.entity_type = value || "";
    entityLabelEl.textContent = state.entity_type
      ? (ENTITY_LABELS[state.entity_type] || state.entity_type)
      : "All entities";
    closeEntityMenu();
    load();
  }

  function renderEntityMenu() {
    var html = '<button type="button" class="users-audit-entity-catsel' + (state.entity_type ? "" : " is-active") + '" data-audit-entity-all>All entities</button>';
    entityGroups.forEach(function (g) {
      var active = !!state.entity_type && g.items.some(function (i) { return i.entity_type === state.entity_type; });
      html += '<button type="button" class="users-audit-entity-cat' + (active ? " is-active" : "") + '" data-audit-entity-cat="' + esc(g.label) + '">' + esc(g.label) + "</button>";
    });
    entityCats.innerHTML = html;
  }

  function showEntitySub(label) {
    var group = null;
    entityGroups.forEach(function (g) { if (g.label === label) { group = g; } });
    if (!group) { entitySub.hidden = true; return; }
    entitySub.innerHTML = group.items.map(function (i) {
      return '<button type="button" class="users-audit-entity-opt' + (state.entity_type === i.entity_type ? " is-active" : "") + '" data-audit-entity-value="' + esc(i.entity_type) + '">' + esc(i.label) + "</button>";
    }).join("");
    entitySub.hidden = false;

    var catEl = entityCats.querySelector('[data-audit-entity-cat="' + label + '"]');
    var catTop = catEl ? catEl.offsetTop : 0;
    entitySub.style.top = catTop + "px";

    var subW = entitySub.offsetWidth || 200;
    var menuRect = entityMenu.getBoundingClientRect();
    if (menuRect.right + subW + 8 > window.innerWidth) {
      entitySub.style.left = "auto";
      entitySub.style.right = "100%";
      entitySub.style.marginLeft = "0";
      entitySub.style.marginRight = "4px";
    } else {
      entitySub.style.left = "100%";
      entitySub.style.right = "auto";
      entitySub.style.marginLeft = "4px";
      entitySub.style.marginRight = "0";
    }

    // Keep the flyout fully on screen: shift it up when it would run past the
    // bottom of the viewport (last category near the screen edge otherwise
    // clips its options with nothing left to scroll).
    var subH = entitySub.offsetHeight || 220;
    var topInViewport = menuRect.top + catTop;
    var overflowBottom = topInViewport + subH + 8 - window.innerHeight;
    if (overflowBottom > 0) {
      entitySub.style.top = Math.max(0, catTop - overflowBottom) + "px";
    }
  }

  function hideEntitySub() {
    entitySub.hidden = true;
    entitySub.innerHTML = "";
  }

  function openEntityMenu() {
    renderEntityMenu();
    document.body.appendChild(entityMenu);
    entityMenu.hidden = false;
    var rect = entityToggle.getBoundingClientRect();
    var mw = entityMenu.offsetWidth || 200;
    var mh = entityMenu.offsetHeight || 220;
    var left = Math.min(Math.max(rect.left, 8), window.innerWidth - mw - 8);
    var below = rect.bottom + 6 + mh <= window.innerHeight - 8;
    var top = below ? rect.bottom + 6 : Math.max(8, rect.top - mh - 6);
    entityMenu.style.left = left + "px";
    entityMenu.style.top = top + "px";
    entityToggle.setAttribute("aria-expanded", "true");

    if (state.entity_type) {
      var group = null;
      entityGroups.forEach(function (g) { if (g.items.some(function (i) { return i.entity_type === state.entity_type; })) { group = g; } });
      if (group) { showEntitySub(group.label); } else { hideEntitySub(); }
    } else {
      hideEntitySub();
    }
  }

  function closeEntityMenu() {
    if (entityMenu.hidden) { return; }
    entityMenu.hidden = true;
    entityToggle.setAttribute("aria-expanded", "false");
    hideEntitySub();
  }

  if (entityToggle && entityMenu) {
    entityToggle.addEventListener("click", function (ev) {
      ev.stopPropagation();
      ev.preventDefault();
      if (entityMenu.hidden) { openEntityMenu(); } else { closeEntityMenu(); }
    });
  }

  entityCats.addEventListener("mouseover", function (ev) {
    var cat = ev.target.closest("[data-audit-entity-cat]");
    var all = ev.target.closest("[data-audit-entity-all]");
    if (cat) { showEntitySub(cat.getAttribute("data-audit-entity-cat")); }
    else if (all) { hideEntitySub(); }
  });

  entityMenu.addEventListener("click", function (ev) {
    ev.stopPropagation();
    var opt = ev.target.closest("[data-audit-entity-value]");
    var all = ev.target.closest("[data-audit-entity-all]");
    if (opt) { setEntityFilter(opt.getAttribute("data-audit-entity-value")); }
    else if (all) { setEntityFilter(""); }
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && !entityMenu.hidden) { closeEntityMenu(); }
  });

  el("[data-audit-detail-close]").addEventListener("click", hideDetail);
  detailModal.addEventListener("click", function (ev) {
    if (ev.target === detailModal) { hideDetail(); }
  });

  loadEntities().then(load);
}
