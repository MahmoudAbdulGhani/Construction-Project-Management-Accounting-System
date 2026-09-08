/* Expenses page (1A-1 list/filters/metrics, 1A-2 create/edit + status
   actions). Consumes the DRF endpoints served by the expenses app under
   /api/expenses/ using the authenticated session (SessionAuthentication)
   -- same fetch/CSRF/escape conventions as receipts.js / contractors.js.

   Filters map 1:1 to the existing API query parameters:
     search   -> ?search=         (description, project__name, project__code)
     status   -> ?status=PENDING|APPROVED|PAID|REJECTED
     category -> ?category=<id>
     project  -> ?project=<id>
     dates    -> ?date_from= & ?date_to=

   The API paginates (PageNumberPagination, 25/page); the list walks the
   `next` links so the rendered dataset -- and the metrics computed from
   it -- always cover the whole filtered result set.

   Stale-request protection: every refresh() captures a monotonically
   increasing sequence token. Only the refresh that issued the LATEST
   token is allowed to render rows/metrics, so a slow older request can
   never overwrite the results of a newer filter selection. */
(() => {
  "use strict";

  const API = "/api/expenses/expenses/";
  const CATEGORIES_API = "/api/expenses/expense-categories/";
  const PROJECTS_API = "/api/projects/projects/";
  const SUPPLIERS_API = "/api/suppliers/suppliers/";
  const CURRENCY = "USD";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const state = {
    expenses: [],
    statusFilter: "all",
    category: "",
    project: "",
    dateFrom: "",
    dateTo: "",
    search: "",
    // Cached lookup lists for the create/edit dialog. Projects and
    // categories are reused from the same fetches that populate the
    // filter dropdowns; suppliers are only fetched once the dialog first
    // opens (this page has no supplier filter).
    options: { projects: [], categories: [], suppliers: [] },
    suppliersLoaded: false,
  };

  // Monotonic guard against stale responses overwriting newer ones.
  let requestSeq = 0;

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

  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const fmtMoney = v => {
    const n = Number(v);
    return Number.isFinite(n)
      ? n.toLocaleString("en-US", { style: "currency", currency: CURRENCY, minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : (v == null || v === "" ? `${CURRENCY} 0.00` : `${CURRENCY} ${v}`);
  };

  const expenseStatusPill = s => {
    const cls = s === "APPROVED" || s === "PAID" ? " active" : (s === "REJECTED" ? " on-hold" : "");
    return `<span class="status${cls}"><i></i>${esc(s || "PENDING")}</span>`;
  };

  function buildParams() {
    const params = new URLSearchParams();
    if (state.search.trim()) params.set("search", state.search.trim());
    if (state.statusFilter !== "all") params.set("status", state.statusFilter);
    if (state.category) params.set("category", state.category);
    if (state.project) params.set("project", state.project);
    if (state.dateFrom) params.set("date_from", state.dateFrom);
    if (state.dateTo) params.set("date_to", state.dateTo);
    return params;
  }

  // Row actions per status -- mirrors the backend transition rules
  // (services.transition_status: PENDING->APPROVED|REJECTED,
  // APPROVED->PAID|REJECTED; PAID/REJECTED terminal). Delete is a UI
  // policy only: it is offered for PENDING and REJECTED even though the
  // API's ModelViewSet destroy accepts any status. All buttons are read
  // by the delegated tbody click handler; ids are UUID strings.
  function rowActions(e) {
    const btn = (label, action) =>
      `<button class="quiet-button" data-expense-action="${action}" data-id="${esc(e.id)}">${label}</button>`;
    const del = () =>
      `<button class="quiet-button danger" data-expense-action="delete" data-id="${esc(e.id)}">Delete</button>`;
    const buttons = [btn("Edit", "edit")];
    if (e.status === "PENDING") {
      buttons.push(btn("Approve", "approve"), btn("Reject", "reject"), del());
    } else if (e.status === "APPROVED") {
      buttons.push(btn("Mark paid", "mark_paid"), btn("Reject", "reject"));
    } else if (e.status === "REJECTED") {
      buttons.push(del());
    }
    return buttons.join("");
  }

  function renderRows() {
    const tbody = $("[data-expense-rows]");
    if (!tbody) return;
    if (!state.expenses.length) {
      tbody.innerHTML = `
        <tr class="empty-row">
          <td colspan="8"><strong>No expenses found</strong><span>Try adjusting the search or filters.</span></td>
        </tr>`;
      return;
    }
    tbody.innerHTML = state.expenses.map(e => `
      <tr>
        <td><strong>${esc(e.description)}</strong><span>${esc(e.expense_date || "")}</span></td>
        <td><strong>${esc(e.project_name || "—")}</strong><span>${esc(e.project_code || "")}</span></td>
        <td>${esc(e.category_name || "—")}</td>
        <td>${esc(e.supplier_name || "—")}</td>
        <td>${esc(e.expense_date || "—")}</td>
        <td>${fmtMoney(e.amount)}${Number(e.tax_amount) > 0 ? `<span>+ tax ${fmtMoney(e.tax_amount)}</span>` : ""}</td>
        <td>${expenseStatusPill(e.status)}</td>
        <td class="expense-row-actions">${rowActions(e)}</td>
      </tr>`).join("");
  }

  function renderMetrics() {
    const total = state.expenses.length;
    const pending = state.expenses.filter(e => e.status === "PENDING").length;
    const sum = state.expenses.reduce((acc, e) => acc + Number(e.amount || 0) + Number(e.tax_amount || 0), 0);

    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth();
    const monthSum = state.expenses.reduce((acc, e) => {
      const d = new Date(e.expense_date + "T00:00:00Z");
      if (d.getUTCFullYear() === year && d.getUTCMonth() === month) {
        return acc + Number(e.amount || 0) + Number(e.tax_amount || 0);
      }
      return acc;
    }, 0);

    $("[data-metric=total]").textContent = total;
    $("[data-metric=pending]").textContent = pending;
    $("[data-metric=sum]").textContent = fmtMoney(sum);
    $("[data-metric=month]").textContent = fmtMoney(monthSum);
  }

  async function refresh() {
    const seq = ++requestSeq;
    const params = buildParams();
    const tbody = $("[data-expense-rows]");
    if (tbody) {
      tbody.innerHTML = `
        <tr class="empty-row">
          <td colspan="8"><strong>Loading expenses…</strong><span>Fetching from the expenses API.</span></td>
        </tr>`;
    }
    try {
      const expenses = await fetchAll(`${API}?${params.toString()}`);
      if (seq !== requestSeq) return; // stale response -- a newer filter is in flight
      state.expenses = expenses;
      renderMetrics();
      renderRows();
    } catch (e) {
      if (seq !== requestSeq) return; // stale failure -- ignore
      state.expenses = [];
      renderMetrics();
      if (tbody) {
        tbody.innerHTML = `
          <tr class="empty-row">
            <td colspan="8"><strong>Could not load expenses</strong><span>${esc(e.message)}</span></td>
          </tr>`;
      }
    }
  }

  function bindSearch() {
    let debounceTimer;
    const input = $("#expense-search-input");
    if (!input) return;
    input.addEventListener("input", e => {
      state.search = e.target.value;
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(refresh, 300);
    });
  }

  function bindStatusFilters() {
    const sel = document.getElementById("expense-status-filter");
    if (sel) {
      sel.addEventListener("change", () => {
        state.statusFilter = sel.value;
        refresh();
      });
      return;
    }
    $$("[data-status-filter]").forEach(btn => {
      btn.addEventListener("click", () => {
        state.statusFilter = btn.dataset.statusFilter;
        $$("[data-status-filter]").forEach(b => b.classList.toggle("active", b === btn));
        refresh();
      });
    });
  }

  async function bindCategoryDropdown() {
    const select = $("#expense-category-filter");
    if (!select) return;
    try {
      const categories = await fetchAll(CATEGORIES_API);
      state.options.categories = categories;
      const fragment = document.createDocumentFragment();
      for (const c of categories) {
        const opt = document.createElement("option");
        opt.value = c.id;
        opt.textContent = c.name;
        fragment.appendChild(opt);
      }
      select.appendChild(fragment);
    } catch (e) { /* leave "Category: All" -- the list must still work */ }
    select.addEventListener("change", () => { state.category = select.value; refresh(); });
  }

  async function bindProjectDropdown() {
    const select = $("#expense-project-filter");
    if (!select) return;
    try {
      const projects = await fetchAll(PROJECTS_API);
      state.options.projects = projects;
      const fragment = document.createDocumentFragment();
      for (const p of projects) {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = `${p.code} — ${p.name}`;
        fragment.appendChild(opt);
      }
      select.appendChild(fragment);
    } catch (e) { /* leave "Project: All" -- the list must still work */ }
    select.addEventListener("change", () => { state.project = select.value; refresh(); });
  }

  function bindDateFilters() {
    const from = $("[data-date-from]");
    const to = $("[data-date-to]");
    if (from) from.addEventListener("change", e => { state.dateFrom = e.target.value; refresh(); });
    if (to) to.addEventListener("change", e => { state.dateTo = e.target.value; refresh(); });
  }

  /* ---- Create / edit dialog (1A-2) ---- */

  const todayStr = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };

  const formatApiError = err => {
    const match = err.message.match(/^(\d+):\s*(.*)$/s);
    if (!match) return err.message;
    try {
      const data = JSON.parse(match[2]);
      const lines = [];
      for (const [key, value] of Object.entries(data)) {
        lines.push(`${key}: ${Array.isArray(value) ? value.join(" ") : String(value)}`);
      }
      return lines.length ? lines.join("\n") : err.message;
    } catch (e) {
      return err.message;
    }
  };

  async function ensureFormChoices() {
    const tasks = [];
    if (!state.options.projects.length) {
      tasks.push(fetchAll(PROJECTS_API).then(r => { state.options.projects = r; }).catch(() => {}));
    }
    if (!state.options.categories.length) {
      tasks.push(fetchAll(CATEGORIES_API).then(r => { state.options.categories = r; }).catch(() => {}));
    }
    if (!state.suppliersLoaded) {
      state.suppliersLoaded = true; // mark attempted so a failed lookup isn't retried every open
      tasks.push(fetchAll(SUPPLIERS_API).then(r => { state.options.suppliers = r; }).catch(() => {}));
    }
    await Promise.all(tasks);
  }

  function fillSelect(select, items, { text } = {}) {
    select.innerHTML = "";
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "Select…";
    select.appendChild(blank);
    for (const item of items || []) {
      const opt = document.createElement("option");
      opt.value = item.id;
      opt.textContent = text ? text(item) : (item.name || item.id);
      select.appendChild(opt);
    }
  }

  function buildFormPayload(form, editing) {
    const payload = {};
    const fields = ["project", "category", "supplier", "expense_date", "description", "amount", "tax_amount", "payment_method", "notes"];
    for (const name of fields) {
      const value = form.elements[name].value.trim();
      if (value !== "") {
        payload[name] = value;
      } else if (editing) {
        // PATCH omits absent keys, so blank optionals are written
        // explicitly to let the user clear a previously set value.
        if (name === "supplier") payload[name] = null;
        else if (name === "payment_method" || name === "notes") payload[name] = "";
        else if (name === "tax_amount") payload[name] = "0.00";
      }
    }
    return payload;
  }

  async function openExpenseForm(expense = null) {
    const dialog = $("[data-expense-dialog]");
    const form = $("[data-expense-form]");
    if (!dialog || !form) return;

    const errorBox = $("[data-expense-error]", form);
    form.reset();
    delete form.dataset.id;
    $("[data-expense-form-title]").textContent = expense ? "Edit expense" : "Create expense";
    errorBox.hidden = true;

    await ensureFormChoices();

    fillSelect(form.elements.project, state.options.projects, { text: p => `${p.code} — ${p.name}` });
    fillSelect(form.elements.category, state.options.categories);
    fillSelect(form.elements.supplier, state.options.suppliers);

    if (expense) {
      form.dataset.id = expense.id;
      form.elements.project.value = expense.project || "";
      form.elements.category.value = expense.category || "";
      form.elements.supplier.value = expense.supplier || "";
      form.elements.expense_date.value = expense.expense_date || "";
      form.elements.description.value = expense.description || "";
      form.elements.amount.value = expense.amount ?? "";
      form.elements.tax_amount.value = expense.tax_amount ?? "";
      form.elements.payment_method.value = expense.payment_method || "";
      form.elements.notes.value = expense.notes || "";
    } else {
      form.elements.expense_date.value = todayStr();
    }
    dialog.showModal();
  }

  let savingExpense = false;

  async function saveExpense(ev) {
    ev.preventDefault();
    const form = $("[data-expense-form]");
    const dialog = $("[data-expense-dialog]");
    if (!form || savingExpense) return;
    const errorBox = $("[data-expense-error]", form);
    const saveBtn = $('footer .primary-button', form);
    savingExpense = true;
    saveBtn.disabled = true;
    errorBox.hidden = true;

    const editing = Boolean(form.dataset.id);
    const payload = buildFormPayload(form, editing);
    const url = editing ? `${API}${form.dataset.id}/` : API;
    const method = editing ? "PATCH" : "POST";

    try {
      await api(url, { method, body: JSON.stringify(payload) });
      dialog.close();
      refresh();
    } catch (err) {
      errorBox.textContent = formatApiError(err);
      errorBox.hidden = false;
    } finally {
      savingExpense = false;
      saveBtn.disabled = false;
    }
  }

  async function transitionExpense(id, action) {
    try {
      await api(`${API}${id}/${action}/`, { method: "POST" });
      refresh();
    } catch (err) {
      alert(`Could not ${action.replace("_", " ")} expense: ${formatApiError(err)}`);
    }
  }

  async function deleteExpense(id) {
    if (!confirm("Delete this expense? This cannot be undone.")) return;
    try {
      await api(`${API}${id}/`, { method: "DELETE" });
      refresh();
    } catch (err) {
      alert(`Could not delete expense: ${formatApiError(err)}`);
    }
  }

  function bindExpenseActions() {
    const tbody = $("[data-expense-rows]");
    if (!tbody) return;
    tbody.addEventListener("click", e => {
      const btn = e.target.closest("[data-expense-action]");
      if (!btn) return;
      const id = btn.dataset.id;
      const action = btn.dataset.expenseAction;
      const row = state.expenses.find(x => String(x.id) === String(id));
      if (action === "edit") openExpenseForm(row);
      else if (action === "delete") deleteExpense(id);
      else transitionExpense(id, action);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindSearch();
    bindStatusFilters();
    bindDateFilters();
    bindCategoryDropdown();
    bindProjectDropdown();
    bindExpenseActions();
    refresh();

    const newBtn = $("[data-expense-new]");
    if (newBtn) newBtn.addEventListener("click", () => openExpenseForm());

    const form = $("[data-expense-form]");
    if (form) form.addEventListener("submit", saveExpense);

    $$("[data-expense-close]").forEach(btn =>
      btn.addEventListener("click", () => btn.closest("dialog")?.close())
    );

    const dialog = $("[data-expense-dialog]");
    if (dialog) {
      dialog.addEventListener("click", e => { if (e.target === dialog) dialog.close(); });
    }
  });
})();