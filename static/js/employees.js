/* Employee Management page.
   Consumes the DRF endpoints served by EmployeeViewSet under
   /api/employees/ using the authenticated session (SessionAuthentication).
   No employee login/role here -- the endpoints only let authenticated
   internal users (Owner/Accountant) through, enforced server-side. */
(() => {
  "use strict";

  const API = "/api/employees/";
  const PROJECTS_API = "/api/projects/projects/";
  const CURRENCY = "USD";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const state = { employees: [], assignments: [], statusFilter: "all", search: "" };

  /* ---- CSRF token for unsafe methods (SessionAuthentication + CSRF) ---- */
  function getCookie(name) {
    const m = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[2]) : "";
  }

  async function api(url, options = {}) {
    const opts = { credentials: "same-origin", headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options };
    if (options.method && !["GET", "HEAD"].includes(options.method)) {
      opts.headers["X-CSRFToken"] = getCookie("csrftoken");
    }
    const res = await fetch(url, opts);
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = JSON.stringify(await res.json()); } catch (e) { /* ignore */ }
      throw new Error(`${res.status}: ${detail}`);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  async function fetchAll(url) {
    const rows = [];
    let next = url;
    while (next) {
      const data = await api(next);
      rows.push(...(data.results || []));
      next = data.next;
    }
    return rows;
  }

  const fmtMoney = v => {
    const n = Number(v);
    return Number.isFinite(n)
      ? n.toLocaleString("en-US", { style: "currency", currency: CURRENCY, minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : (v == null || v === "" ? `${CURRENCY} 0.00` : `${CURRENCY} ${v}`);
  };

  const statusPill = s => {
    const safe = s || "ACTIVE";
    const cls = safe === "ACTIVE" ? " active" : (safe === "TERMINATED" ? " warning" : "");
    return `<span class="status${cls}"><i></i>${safe}</span>`;
  };

  /* ---- Table rendering ---- */
  function renderRows() {
    const tbody = $("[data-employee-rows]");
    let list = state.employees;
    if (state.statusFilter !== "all") list = list.filter(e => e.employment_status === state.statusFilter);
    const q = state.search.trim().toLowerCase();
    if (q) list = list.filter(e => [e.name, e.employee_number, e.position, e.department, e.email].some(v => (v || "").toLowerCase().includes(q)));

    if (!list.length) {
      tbody.innerHTML = `<tr><td><strong>No employees found</strong><span>Try adjusting the search or status filter.</span></td><td>—</td><td>—</td><td>—</td><td><span class="status"><i></i>—</span></td></tr>`;
      return;
    }
    tbody.innerHTML = list.map(e => `
      <tr class="row-click" data-employee-id="${e.id}">
        <td><strong>${esc(e.name)}</strong><span>${esc(e.employee_number)}</span></td>
        <td>${esc(e.position || "—")}</td>
        <td>${esc(e.department || "—")}</td>
        <td>${e.labor_rate != null ? fmtMoney(e.labor_rate) : "—"}</td>
        <td>${statusPill(e.employment_status)}</td>
      </tr>`).join("");

    $$("[data-employee-id]", tbody).forEach(row => {
      row.addEventListener("click", () => openDetail(row.dataset.employeeId));
    });
  }

  async function renderMetrics() {
    const employees = state.employees;
    const active = employees.filter(e => e.employment_status === "ACTIVE").length;
    const onleave = employees.filter(e => e.employment_status === "ON_LEAVE").length;
    $("[data-metric=total]").textContent = employees.length;
    $("[data-metric=active]").textContent = active;
    $("[data-metric=onleave]").textContent = onleave;
    $("[data-metric=assignments]").textContent = state.assignments.length;
  }

  /* ---- Detail dialog ---- */
  const dialog = $("[data-employee-dialog]");
  let detailEmployeeId = null;
  let detailEmployee = null;
  let activeTab = "assignments";
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function openDetail(id) {
    detailEmployeeId = id;
    try {
      const detail = await api(`${API}${id}/`);
      detailEmployee = detail;
      $("[data-detail-name]").textContent = detail.name || "—";
      $("[data-detail-number]").textContent = detail.employee_number || "";
      $("[data-detail-number-2]").textContent = detail.employee_number || "—";
      $("[data-detail-phone]").textContent = detail.phone || "—";
      $("[data-detail-email]").textContent = detail.email || "—";
      $("[data-detail-position]").textContent = detail.position || "—";
      $("[data-detail-department]").textContent = detail.department || "—";
      $("[data-detail-rate]").textContent = detail.labor_rate != null ? fmtMoney(detail.labor_rate) : "—";
      const status = $("[data-detail-status]");
      status.className = "status" + (detail.employment_status === "ACTIVE" ? " active" : (detail.employment_status === "TERMINATED" ? " warning" : ""));
      status.innerHTML = `<i></i>${detail.employment_status || "ACTIVE"}`;
      dialog.showModal();
      loadTab(activeTab);
    } catch (e) {
      alert("Could not load employee: " + e.message);
    }
  }

  async function loadAssignments() {
    try {
      state.assignments = await api(`${API}${detailEmployeeId}/projects/`);
    } catch (e) {
      state.assignments = [];
    }
    await renderMetrics();
  }

  function assignmentTable() {
    const cols = ["Project", "Role", "Assigned", "Released", ""];
    const head = `<table><thead><tr>${cols.map(c => `<th>${c}</th>`).join("")}</tr></thead>`;
    if (!state.assignments.length) {
      return `${head}<tbody><tr><td colspan="${cols.length}"><strong>No project assignments for this employee.</strong></td></tr></tbody></table>`;
    }
    const rows = state.assignments.map(a => `
      <tr>
        <td><strong>${esc(a.project.name)}</strong><span>${esc(a.project.code)}</span></td>
        <td>${esc(a.role_on_project || "—")}</td>
        <td>${esc(a.assigned_at || "—")}</td>
        <td>${esc(a.released_at || "—")}</td>
        <td>
          <button type="button" class="tab-action" data-release="${a.id}" ${a.released_at ? "disabled" : ""}>Release</button>
          <button type="button" class="tab-action danger" data-unassign="${a.id}">Unassign</button>
        </td>
      </tr>`).join("");
    return `${head}<tbody>${rows}</tbody></table>`;
  }

  function assignForm() {
    const options = (state.projects || []).map(p => `<option value="${p.id}">${esc(p.code)} — ${esc(p.name)}</option>`).join("");
    return `
      <form class="employee-assign-form" data-assign-form>
        <label>Project *
          <select name="project_id" required>
            <option value="" disabled selected>Select project…</option>
            ${options}
          </select>
        </label>
        <label>Role on project <input type="text" name="role_on_project" placeholder="e.g. Site Lead"></label>
        <label>Assigned date * <input type="date" name="assigned_at" required></label>
        <button type="submit" class="primary-button">Assign</button>
        <button type="button" class="quiet-button" data-assign-cancel>Cancel</button>
      </form>`;
  }

  async function loadTab(tab) {
    activeTab = tab;
    const panel = $("[data-tab-panel]");
    $$("[data-tab]").forEach(b => b.classList.toggle("active", b === tab || b.dataset.tab === tab));
    if (tab === "assignments") {
      await loadAssignments();
      panel.innerHTML = assignmentTable();
      bindAssignmentActions(panel);
    } else if (tab === "assign") {
      if (!state.projects) {
        try { state.projects = await fetchAll(PROJECTS_API); } catch (e) { state.projects = []; }
      }
      panel.innerHTML = assignForm();
      const form = $("[data-assign-form]");
      $("[data-assign-cancel]").addEventListener("click", () => loadTab("assignments"));
      form.addEventListener("submit", async e => {
        e.preventDefault();
        const payload = Object.fromEntries(new FormData(form).entries());
        if (!payload.role_on_project) delete payload.role_on_project;
        try {
          await api(`${API}${detailEmployeeId}/projects/`, { method: "POST", body: JSON.stringify(payload) });
          loadTab("assignments");
        } catch (err) {
          alert("Could not assign project: " + err.message);
        }
      });
    }
  }

  function bindAssignmentActions(panel) {
    $$("[data-release]", panel).forEach(btn => {
      btn.addEventListener("click", async () => {
        const aid = btn.dataset.release;
        if (!confirm("Release this assignment?")) return;
        try {
          await api(`${API}${detailEmployeeId}/projects/${aid}/`, {
            method: "PATCH",
            body: JSON.stringify({ released_at: new Date().toISOString().slice(0, 10) }),
          });
          loadTab("assignments");
        } catch (e) {
          alert("Could not release assignment: " + e.message);
        }
      });
    });
    $$("[data-unassign]", panel).forEach(btn => {
      btn.addEventListener("click", async () => {
        const aid = btn.dataset.unassign;
        if (!confirm("Remove this assignment entirely?")) return;
        try {
          await api(`${API}${detailEmployeeId}/projects/${aid}/`, { method: "DELETE" });
          loadTab("assignments");
        } catch (e) {
          alert("Could not unassign: " + e.message);
        }
      });
    });
  }

  function bindDialog() {
    const actions = $(".employee-dialog-actions");
    actions.insertAdjacentHTML("afterbegin", '<button type="button" class="quiet-button" data-employee-edit>Edit</button><button type="button" class="quiet-button" data-employee-delete>Delete</button>');
    $("[data-employee-edit]").addEventListener("click", editEmployee);
    $("[data-employee-delete]").addEventListener("click", deleteEmployee);
    $("[data-employee-close]").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", e => { if (e.target === dialog) dialog.close(); });
    $$("[data-tab]").forEach(btn => {
      btn.addEventListener("click", () => loadTab(btn.dataset.tab));
    });
  }

  async function editEmployee() {
    if (!detailEmployee) return;
    const name = prompt("Employee name", detailEmployee.name || ""); if (name === null) return;
    const position = prompt("Position", detailEmployee.position || ""); if (position === null) return;
    const rate = prompt("Labor rate", detailEmployee.labor_rate || ""); if (rate === null) return;
    try { await api(`${API}${detailEmployeeId}/`, { method: "PATCH", body: JSON.stringify({ name: name.trim(), position: position.trim(), labor_rate: rate || null }) }); await refresh(); await openDetail(detailEmployeeId); }
    catch (e) { alert("Could not update employee: " + e.message); }
  }

  async function deleteEmployee() {
    if (!detailEmployeeId || !confirm("Delete this employee? Existing protected assignments may prevent deletion.")) return;
    try { await api(`${API}${detailEmployeeId}/`, { method: "DELETE" }); dialog.close(); await refresh(); }
    catch (e) { alert("Could not delete employee: " + e.message); }
  }

  /* ---- Create employee ---- */
  async function populateEmployeeAssignFields() {
    const select = $("[data-employee-assign-project]");
    if (!select) return;
    if (!state.projects) {
      try { state.projects = await fetchAll(PROJECTS_API); } catch (e) { state.projects = []; }
    }
    if (select.options.length <= 1) {
      state.projects.forEach(p => {
        const option = document.createElement("option");
        option.value = p.id;
        option.textContent = `${p.code} — ${p.name}`;
        select.appendChild(option);
      });
    }
    const dateInput = $("[data-employee-assign-date]");
    if (dateInput && !dateInput.value) {
      dateInput.value = new Date().toISOString().slice(0, 10);
    }
  }

  function bindCreate() {
    const overlay = $("[data-employee-create]");
    $("[data-employee-new]").addEventListener("click", () => { populateEmployeeAssignFields(); overlay.hidden = false; });
    $("[data-employee-create-close]").addEventListener("click", () => { overlay.hidden = true; });
    $("[data-employee-create-cancel]").addEventListener("click", () => { overlay.hidden = true; });
    $("[data-employee-form]").addEventListener("submit", async e => {
      e.preventDefault();
      const form = e.currentTarget;
      const formData = Object.fromEntries(new FormData(form).entries());
      const payload = Object.fromEntries(new FormData(form).entries());
      delete payload.assign_project;
      delete payload.assigned_at;
      if (!payload.labor_rate) delete payload.labor_rate;
      if (!payload.phone) delete payload.phone;
      if (!payload.email) delete payload.email;
      if (!payload.position) delete payload.position;
      if (!payload.department) delete payload.department;
      try {
        const created = await api(API, { method: "POST", body: JSON.stringify(payload) });
        const assignProject = formData.assign_project || "";
        if (assignProject && created?.id) {
          await api(`${API}${created.id}/projects/`, {
            method: "POST",
            body: JSON.stringify({ project_id: assignProject, assigned_at: formData.assigned_at || new Date().toISOString().slice(0, 10) }),
          });
        }
        overlay.hidden = true;
        form.reset();
        await refresh();
      } catch (err) {
        alert("Could not create employee: " + err.message);
      }
    });
  }

  /* ---- Filters & search ---- */
  function bindFilters() {
    $$("[data-status-filter]").forEach(btn => {
      btn.addEventListener("click", () => {
        state.statusFilter = btn.dataset.statusFilter;
        $$("[data-status-filter]").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        renderRows();
      });
    });
    const searchInput = $("#employee-search-input");
    searchInput.addEventListener("input", () => { state.search = searchInput.value; renderRows(); });
  }

  async function refresh() {
    state.employees = await fetchAll(API);
    await renderMetrics();
    renderRows();
  }

  document.addEventListener("DOMContentLoaded", async () => {
    bindDialog();
    bindCreate();
    bindFilters();
    try {
      await refresh();
      state.assignments = [];
      state.projects = null;
    } catch (e) {
      $("[data-employee-rows]").innerHTML = `<tr><td><strong>Could not load employees</strong><span>${esc(e.message)}</span></td><td>—</td><td>—</td><td>—</td><td><span class="status"><i></i>—</span></td></tr>`;
    }
  });
})();
