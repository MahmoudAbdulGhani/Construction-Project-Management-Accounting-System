/* Accounting / Financial Transactions page (CPMAS-34).
   Consumes the authenticated DRF endpoints under /api/accounting/ using the
   dashboard session (SessionAuthentication + CSRF), same fetch/CSRF pattern
   as payments.js/procurement.js.

   The backend FinancialTransactionSerializer does NOT accept nested writable
   lines, so a transaction is created as: POST header -> POST each line ->
   (optional) POST post_entry. The UI presents this as one form even though
   it performs several requests, and handles partial failure without
   claiming success. Status lifecycle rules are enforced by the backend and
   mirrored here: DRAFT (view/edit/delete/post), POSTED (view/void),
   VOIDED (view only). This page never claims a transaction is POSTED unless
   the post_entry API returns success. */
(() => {
  "use strict";

  const E = {
    financialTransactions: "/api/accounting/financial-transactions/",
    transactionLines: "/api/accounting/transaction-lines/",
    accounts: "/api/accounting/accounts/",
    projects: "/api/projects/projects/",
    clients: "/api/clients/clients/",
    suppliers: "/api/suppliers/suppliers/",
  };

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (v) => Number(v || 0).toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

  const state = {
    rows: [],           // current page of transactions
    page: 1,
    next: null,
    prev: null,
    count: 0,
    filters: { search: "", status: "", project: "", client: "", supplier: "", dateFrom: "", dateTo: "" },
    accounts: [],       // active accounts for line selector
    projects: [],       // light list for header + filters
    clients: [],
    suppliers: [],
    txn: { id: null, mode: "create", editMode: "post" }, // create/edit context
  };

  function cookie(name) {
    const m = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[2]) : "";
  }

  async function api(url, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body) headers["Content-Type"] = "application/json";
    if (options.method && !["GET", "HEAD"].includes(options.method)) headers["X-CSRFToken"] = cookie("csrftoken");
    const response = await fetch(url, { credentials: "same-origin", ...options, headers });
    if (!response.ok) {
      let message = response.statusText || `Request failed (${response.status})`;
      try {
        const body = await response.json();
        if (body && typeof body === "object") {
          message = Object.entries(body)
            .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(" ") : (typeof v === "object" ? JSON.stringify(v) : v)}`)
            .join("\n");
        } else if (body) {
          message = String(body);
        }
      } catch (_) { /* non-JSON / network body */ }
      throw new Error(message || `Request failed (${response.status})`);
    }
    return response.status === 204 ? null : response.json();
  }

  async function all(url) {
    const rows = [];
    while (url) {
      const data = await api(url);
      if (Array.isArray(data)) return data;
      rows.push(...(data.results || []));
      url = data.next;
    }
    return rows;
  }

  async function page(url) {
    return api(url);
  }

  /* ---- helpers ---- */
  const statusPill = (s) => {
    const klass = { DRAFT: "", POSTED: " active", VOIDED: " warning" }[s] || "";
    return `<span class="status${klass}"><i></i>${esc(s || "—")}</span>`;
  };

  const currentUserId = () => document.querySelector(".topbar")?.dataset.appUserId || "";

  function lineTotals(body) {
    let debit = 0, credit = 0;
    body.querySelectorAll("[data-line-debit], [data-line-credit]").forEach((el) => {
      const v = Number(el.value || 0);
      if (!isFinite(v) || v < 0) return;
      if (el.hasAttribute("data-line-debit")) debit += v;
      else credit += v;
    });
    return { debit, credit };
  }

  function updateBalanceBar() {
    const { debit, credit } = lineTotals($("[data-txn-form]"));
    const diff = debit - credit;
    const statusEl = $("[data-balance-status]");
    $("[data-balance-debit]").textContent = money(debit);
    $("[data-balance-credit]").textContent = money(credit);
    statusEl.textContent = diff === 0 ? "Balance: Balanced" : `Balance: ${money(Math.abs(diff))} out of balance`;
    statusEl.className = "txn-balance-status " + (diff === 0 ? "ok" : "bad");
    return diff === 0;
  }

  /* ---- rendering: metrics ---- */
  function renderStats() {
    // Full-history metrics: load ALL pages once (background) so counts and
    // debit/credit totals reflect the complete ledger, not just page 1.
    all(E.financialTransactions).then((txns) => {
      const draft = txns.filter((t) => t.status === "DRAFT").length;
      const posted = txns.filter((t) => t.status === "POSTED").length;
      const voided = txns.filter((t) => t.status === "VOIDED").length;
      const totalDebit = txns.reduce((s, t) => s + Number(t.total_debit || 0), 0);
      const totalCredit = txns.reduce((s, t) => s + Number(t.total_credit || 0), 0);
      $("[data-metric=draft]").textContent = draft;
      $("[data-metric=posted]").textContent = posted;
      $("[data-metric=voided]").textContent = voided;
      $("[data-metric=total_debit]").textContent = money(totalDebit);
      $("[data-metric=total_credit]").textContent = money(totalCredit);
    }).catch(() => { /* metrics stay "—" / $0 on failure; list error is shown */ });
  }

  /* ---- rendering: transactions table ---- */
  function renderTable() {
    const body = $("[data-transaction-rows]");
    if (!state.rows.length) {
      body.innerHTML = `<tr class="empty-row"><td colspan="11"><b>No transactions found</b><span>Try adjusting the search or filters.</span></td></tr>`;
    } else {
      body.innerHTML = state.rows.map((t) => {
        const actions = statusActions(t);
        return `<tr>
          <td><strong>${esc(t.transaction_number)}</strong><a class="accounting-row-link" data-detail-open="${t.id}">View details</a></td>
          <td>${esc(t.transaction_date || "—")}</td>
          <td>${esc(t.description || "—")}</td>
          <td><span class="source-tag${t.source_type ? "" : " manual"}">${esc(t.source_label || "Manual")}</span></td>
          <td>${esc(t.project_name || "—")}</td>
          <td>${esc(t.client_name || "—")}</td>
          <td>${esc(t.supplier_name || "—")}</td>
          <td>${t.total_debit ? money(t.total_debit) : "—"}</td>
          <td>${t.total_credit ? money(t.total_credit) : "—"}</td>
          <td>${statusPill(t.status)}</td>
          <td><div class="payment-actions">${actions}</div></td>
        </tr>`;
      }).join("");

      $$("[data-detail-open]", body).forEach((a) => (a.onclick = () => openDetail(a.dataset.detailOpen)));
      $$("[data-action-post]", body).forEach((b) => (b.onclick = () => confirmPost(b.dataset.actionPost)));
      $$("[data-action-void]", body).forEach((b) => (b.onclick = () => confirmVoid(b.dataset.actionVoid)));
      $$("[data-action-edit]", body).forEach((b) => (b.onclick = () => openEdit(b.dataset.actionEdit)));
      $$("[data-action-delete]", body).forEach((b) => (b.onclick = () => confirmDelete(b.dataset.actionDelete)));
    }

    $("[data-page-next]").disabled = !state.next;
    $("[data-page-prev]").disabled = !state.prev;
    $("[data-page-info]").textContent = `Page ${state.page} · ${state.count} result${state.count === 1 ? "" : "s"}`;
  }

  function statusActions(t) {
    const view = `<button type="button" class="accounting-row-action" data-detail-open="${t.id}">View</button>`;
    // System-generated entries (backed by a source document) are managed by
    // their operational app -- posted by the source workflow, voided and
    // re-booked by the source handler. The accounting page is read-only for
    // them: no Edit/Post/Delete, and voiding happens through the source.
    if (t.source_type) return view;
    if (t.status === "DRAFT") {
      return view + `<button type="button" class="accounting-row-action" data-action-edit="${t.id}">Edit</button>` +
        `<button type="button" class="accounting-row-action post" data-action-post="${t.id}">Post</button>` +
        `<button type="button" class="accounting-row-action danger" data-action-delete="${t.id}">Delete</button>`;
    }
    if (t.status === "POSTED") {
      return view + `<button type="button" class="accounting-row-action danger" data-action-void="${t.id}">Void</button>`;
    }
    return view;
  }

  /* ---- filters + pagination ---- */
  function listUrl() {
    const p = new URLSearchParams({ page: String(state.page) });
    const f = state.filters;
    if (f.search) p.set("search", f.search);
    if (f.status) p.set("status", f.status);
    if (f.project) p.set("project", f.project);
    if (f.client) p.set("client", f.client);
    if (f.supplier) p.set("supplier", f.supplier);
    if (f.dateFrom) p.set("date_from", f.dateFrom);
    if (f.dateTo) p.set("date_to", f.dateTo);
    return `${E.financialTransactions}?${p.toString()}`;
  }

  async function loadTransactions() {
    const data = await page(listUrl());
    state.rows = data.results || [];
    state.next = data.next;
    state.prev = data.previous;
    state.count = data.count || 0;
    renderTable();
  }

  async function refreshAll() {
    try {
      await loadTransactions();
      renderStats();
    } catch (e) {
      $("[data-transaction-rows]").innerHTML = `<tr class="empty-row"><td colspan="11"><b>Could not load transactions</b><span>${esc(e.message)}</span></td></tr>`;
      $("[data-page-next]").disabled = true;
      $("[data-page-prev]").disabled = true;
    }
  }

  /* ---- lookups for selects ---- */
  async function loadAccounts() {
    state.accounts = await all(`${E.accounts}?is_active=true`);
    // refresh any already-open line rows that were created before accounts arrived (ui-fixes fancy)
    refreshLineSelects();
  }
  function refreshLineSelects() {
    $$("[data-txn-lines] select[data-line-account]").forEach(function (sel) {
      var cur = sel.value;
      sel.innerHTML = accountOptions(cur);
      // if ui-fixes fancy is active, its MutationObserver will sync the button label/pop
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    });
    $$("[data-txn-lines] select[data-line-project]").forEach(function (sel) {
      var cur = sel.value;
      sel.innerHTML = projectOptions(cur);
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }

  async function loadLookups() {
    const [projects, clients, suppliers] = await Promise.allSettled([
      all(E.projects), all(E.clients), all(E.suppliers),
    ]);
    state.projects = projects.status === "fulfilled" ? projects.value : [];
    state.clients = clients.status === "fulfilled" ? clients.value : [];
    state.suppliers = suppliers.status === "fulfilled" ? suppliers.value : [];
    if (projects.status !== "fulfilled") console.warn("projects lookup failed:", projects.reason);
    if (clients.status !== "fulfilled") console.warn("clients lookup failed:", clients.reason);
    if (suppliers.status !== "fulfilled") console.warn("suppliers lookup failed:", suppliers.reason);
    // if dialog already open, refresh its header selects so fancy pop isn't stuck empty
    if ($("[data-txn-dialog]") && $("[data-txn-dialog]").open) {
      populateHeaderDimensions();
    }
    refreshLineSelects();
  }

  function populateLookupSelect(selector, rows, label, valueKey, textFn) {
    const select = $(selector);
    if (!select) { console.warn("populateLookupSelect: missing", selector); return; }
    const current = select.value;
    select.innerHTML = `<option value="">${esc(label)}</option>` +
      rows.map((r) => `<option value="${r[valueKey]}">${esc(textFn(r))}</option>`).join("");
    select.value = current || "";
    // force ui-fixes fancy to re-render (was cached empty if opened before fetch)
    select.dispatchEvent(new Event("change", { bubbles: true }));
    console.log("populate", selector, "rows:", rows.length, "options now:", select.options.length);
  }

  function populateFilters() {
    populateLookupSelect("[data-project-filter]", state.projects, "Project: All", "id", (r) => `${r.code} — ${r.name}`);
    populateLookupSelect("[data-client-filter]", state.clients, "Client: All", "id", (r) => r.name);
    populateLookupSelect("[data-supplier-filter]", state.suppliers, "Supplier: All", "id", (r) => r.name);
  }

  function populateHeaderDimensions() {
    populateLookupSelect("[data-txn-form] select[name=project]", state.projects, "Project (optional)", "id", (r) => `${r.code} — ${r.name}`);
    populateLookupSelect("[data-txn-form] select[name=client]", state.clients, "Client (optional)", "id", (r) => r.name);
    populateLookupSelect("[data-txn-form] select[name=supplier]", state.suppliers, "Supplier (optional)", "id", (r) => r.name);
    // notify ui-fixes fancy to re-render (header was empty if dialog opened before lookups finished)
    document.querySelectorAll("[data-txn-form] select[name=project], [data-txn-form] select[name=client], [data-txn-form] select[name=supplier]").forEach(function (s) {
      s.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }

  /* ---- line editor ---- */
  function accountOptions(selected) {
    return '<option value="">Select account…</option>' +
      state.accounts.map((a) => `<option value="${a.id}" ${a.id === selected ? "selected" : ""}>${esc(a.code)} — ${esc(a.name)}</option>`).join("");
  }

  function projectOptions(selected) {
    return '<option value="">—</option>' +
      state.projects.map((p) => `<option value="${p.id}" ${p.id === selected ? "selected" : ""}>${esc(`${p.code} — ${p.name}`)}</option>`).join("");
  }

  function txnLineRow(line) {
    line = line || {};
    return `<tr data-line-id="${esc(line.id || "")}">` +
      `<td><select class="account-select" data-line-account>${accountOptions(line.account || "")}</select></td>` +
      `<td><input class="line-input" data-line-description placeholder="Optional" value="${esc(line.description || "")}"></td>` +
      `<td><select class="account-select" data-line-project>${projectOptions(line.project || "")}</select></td>` +
      `<td><input type="number" class="line-amount" data-line-debit min="0" step="0.01" placeholder="0.00" value="${line.debit > 0 ? line.debit : ""}"></td>` +
      `<td><input type="number" class="line-amount" data-line-credit min="0" step="0.01" placeholder="0.00" value="${line.credit > 0 ? line.credit : ""}"></td>` +
      `<td><button type="button" class="line-remove" data-line-remove aria-label="Remove line">×</button></td>` +
      `</tr>`;
  }

  function addLineRow(line) {
    const body = $("[data-txn-lines]");
    if (!body) throw new Error("Line table is missing. Refresh the page and try again.");
    body.insertAdjacentHTML("beforeend", txnLineRow(line || {}));
    const row = body.lastElementChild;

    row.querySelector("[data-line-remove]").onclick = () => { row.remove(); updateBalanceBar(); };

    row.querySelector("[data-line-debit]").addEventListener("input", () => {
      const d = Number(row.querySelector("[data-line-debit]").value || 0);
      const c = Number(row.querySelector("[data-line-credit]").value || 0);
      if (d > 0 && c > 0) row.querySelector("[data-line-credit]").value = "";
      updateBalanceBar();
    });
    row.querySelector("[data-line-credit]").addEventListener("input", () => {
      const d = Number(row.querySelector("[data-line-debit]").value || 0);
      const c = Number(row.querySelector("[data-line-credit]").value || 0);
      if (d > 0 && c > 0) row.querySelector("[data-line-debit]").value = "";
      updateBalanceBar();
    });
    updateBalanceBar();
  }

  function collectedLines() {
    const lines = [];
    $$("[data-txn-lines] tr[data-line-id]").forEach((row) => {
      const debit = Number(row.querySelector("[data-line-debit]").value || 0);
      const credit = Number(row.querySelector("[data-line-credit]").value || 0);
      const account = row.querySelector("[data-line-account]").value;
      if (debit < 0 || credit < 0) return;
      if (debit > 0 && credit > 0) return;
      if (debit === 0 && credit === 0) return;
      lines.push({
        id: row.dataset.lineId || null,
        account,
        description: row.querySelector("[data-line-description]").value.trim(),
        project: row.querySelector("[data-line-project]").value || null,
        debit: debit,
        credit: credit,
      });
    });
    return lines;
  }

  /* ---- dialog lifecycle ---- */
  function resetTxnForm() {
    const form = $("[data-txn-form]");
    form.reset();
    form.elements.transaction_date.value = new Date().toISOString().slice(0, 10);
    $("[data-txn-error]").hidden = true;
    $("[data-txn-lines]").innerHTML = "";
    $("[data-txn-dialog-title]").textContent = "New transaction";
    populateHeaderDimensions();
    // seed two empty lines for a journal entry
    addLineRow();
    addLineRow();
  }

  function showTxnError(e) {
    const n = $("[data-txn-error]");
    n.textContent = e.message || "Something went wrong.";
    n.hidden = false;
  }

  function dialogOpen(dialog) {
    if (!dialog.open) dialog.showModal();
  }
  function dialogClose(dialog) {
    if (dialog.open) dialog.close();
  }

  /* ---- Create / Edit ---- */
  function openCreate() {
    state.txn = { id: null, mode: "create", editMode: "post" };
    try {
      resetTxnForm();
    } catch (e) {
      $("[data-txn-lines]").innerHTML = "";
      try { addLineRow(); addLineRow(); } catch (_) { /* keep the dialog openable */ }
      showTxnError(e);
    }
    dialogOpen($("[data-txn-dialog]"));
  }

  async function openEdit(id) {
    try {
      const t = await api(`${E.financialTransactions}${id}/`);
      if (t.status !== "DRAFT") {
        alert("Only draft transactions can be edited.");
        return;
      }
      state.txn = { id, mode: "edit", editMode: "post" };
      resetTxnForm();
      const form = $("[data-txn-form]");
      form.elements.transaction_number.value = t.transaction_number || "";
      form.elements.transaction_date.value = t.transaction_date || "";
      form.elements.description.value = t.description || "";
      form.elements.reference.value = t.reference || "";
      form.elements.project.value = t.project || "";
      form.elements.client.value = t.client || "";
      form.elements.supplier.value = t.supplier || "";
      $("[data-txn-error]").hidden = true;
      $("[data-txn-lines]").innerHTML = "";
      (t.lines || []).forEach((l) => addLineRow({
        id: l.id, account: l.account, description: l.description, project: l.project, debit: Number(l.debit), credit: Number(l.credit),
      }));
      if (!t.lines || !t.lines.length) { addLineRow(); addLineRow(); }
      $("[data-txn-dialog-title]").textContent = `Edit ${t.transaction_number}`;
      dialogOpen($("[data-txn-dialog]"));
    } catch (e) {
      // Surface the failure inside the (always-opened) form dialog instead
      // of a native browser alert, so the popup still appears.
      const form = $("[data-txn-form]");
      state.txn = { id, mode: "edit", editMode: "post" };
      $("[data-txn-lines]").innerHTML = "";
      try { addLineRow(); } catch (_) { /* keep the dialog openable */ }
      if (form) form.elements.description.value = "";
      showTxnError(new Error(`Could not load transaction: ${e.message}`));
      dialogOpen($("[data-txn-dialog]"));
    }
  }

  function formHeaderPayload(form) {
    return {
      transaction_number: form.elements.transaction_number.value.trim(),
      transaction_date: form.elements.transaction_date.value,
      description: form.elements.description.value.trim(),
      reference: form.elements.reference.value.trim() || null,
      project: form.elements.project.value || null,
      client: form.elements.client.value || null,
      supplier: form.elements.supplier.value || null,
    };
  }

  async function createOrUpdateHeader(form, txnId) {
    if (txnId) {
      return api(`${E.financialTransactions}${txnId}/`, { method: "PATCH", body: JSON.stringify(formHeaderPayload(form)) });
    }
    const userId = currentUserId();
    if (!userId) throw new Error("No linked user account for recording this transaction.");
    return api(E.financialTransactions, { method: "POST", body: JSON.stringify({ ...formHeaderPayload(form), created_by: userId }) });
  }

  async function submitTxn(mode) {
    const form = $("[data-txn-form]");
    $("[data-txn-error]").hidden = true;
    const lines = collectedLines();
    if (!lines.length) { showTxnError(new Error("Add at least one line with a debit or credit greater than zero.")); return; }

    const submitBtn = mode === "post" ? $("[data-save-post]") : $("[data-save-draft]");
    const original = submitBtn.innerHTML;
    submitBtn.disabled = true;

    try {
      // 1. Header (create or PATCH existing)
      const header = await createOrUpdateHeader(form, state.txn.id);
      const txnId = state.txn.id || header.id;
      state.txn.id = txnId;

      // 2. Sync lines (diff-based in edit mode; pure-create in create mode)
      if (state.txn.mode === "edit") {
        await syncLines(txnId, lines);
      } else {
        for (const line of lines) {
          await api(E.transactionLines, { method: "POST", body: JSON.stringify({
            transaction: txnId, account: line.account, description: line.description || null,
            project: line.project, debit: String(line.debit), credit: String(line.credit),
          }) });
        }
      }

      // 3. Optional post
      if (mode === "post") {
        const balanced = updateBalanceBar();
        if (!balanced) throw new Error("Cannot post an out-of-balance transaction. Fix the lines and try again.");
        try {
          await api(`${E.financialTransactions}${txnId}/post_entry/`, { method: "POST" });
        } catch (postErr) {
          // Preserve the DRAFT and surface the backend error; do NOT claim posted.
          showTxnError(new Error(`Transaction saved as DRAFT but could not be posted:\n${postErr.message}`));
          submitBtn.disabled = false;
          dialogClose($("[data-txn-dialog]"));
          await refreshAll();
          return;
        }
      }

      dialogClose($("[data-txn-dialog]"));
      await refreshAll();
    } catch (e) {
      // Partial-failure handling: the header (and likely the lines) already
      // exist as a DRAFT. The two common failures are an out-of-balance
      // entry (lines saved fine, post rejected) and a genuine line-save
      // error -- the message must not conflate them.
      if (state.txn.id && state.txn.mode !== "edit") {
        const unbalanced = /out-of-balance|out of balance|unbalanced/i.test(e.message);
        showTxnError(new Error(unbalanced
          ? `Saved as DRAFT — the entry is out of balance (debits ≠ credits), so it can't be posted yet. Add a matching line on the other side so the totals match, then open it and post.`
          : `Header created but not all lines could be saved. It is preserved as a DRAFT — open it and retry.\n${e.message}`));
      } else {
        showTxnError(e);
      }
      submitBtn.disabled = false;
    }
  }

  /* Diff-based line synchronization for editing an existing DRAFT:
     - load the current server lines (from the header detail)
     - PATCH lines that still exist and changed
     - POST brand-new lines (no id)
     - DELETE lines present server-side but removed in the form */
  async function syncLines(txnId, formLines) {
    const current = await api(`${E.financialTransactions}${txnId}/`);
    const serverLines = current.lines || [];
    const byId = new Map(formLines.filter((l) => l.id).map((l) => [l.id, l]));
    const submittedIds = new Set(formLines.filter((l) => l.id).map((l) => l.id));

    // POST new lines
    for (const line of formLines) {
      if (line.id) continue;
      await api(E.transactionLines, { method: "POST", body: JSON.stringify({
        transaction: txnId, account: line.account, description: line.description || null,
        project: line.project, debit: String(line.debit), credit: String(line.credit),
      }) });
    }

    // PATCH existing changed lines
    for (const s of serverLines) {
      const f = byId.get(s.id);
      if (!f) continue;
      const changed = String(f.account) !== String(s.account) || String(f.description || "") !== String(s.description || "") ||
        String(f.debit) !== String(s.debit) || String(f.credit) !== String(s.credit) || String(f.project || "") !== String(s.project || "");
      if (changed) {
        await api(`${E.transactionLines}${s.id}/`, { method: "PATCH", body: JSON.stringify({
          account: f.account, description: f.description || null, project: f.project || null,
          debit: String(f.debit), credit: String(f.credit),
        }) });
      }
    }

    // DELETE removed lines
    for (const s of serverLines) {
      if (!submittedIds.has(s.id)) {
        await api(`${E.transactionLines}${s.id}/`, { method: "DELETE" });
      }
    }
  }

  /* ---- Delete (DRAFT only) ---- */
  function confirmDelete(id) {
    const dialog = $("[data-confirm-dialog]");
    $("[data-confirm-title]").textContent = "Delete transaction?";
    $("[data-confirm-message]").textContent = "This will permanently delete the draft transaction and all of its lines. This cannot be undone.";
    $("[data-confirm-ok]").className = "primary-button";
    dialogOpen(dialog);
    const ok = $("[data-confirm-ok]");
    ok.onclick = async () => {
      ok.disabled = true;
      try {
        await api(`${E.financialTransactions}${id}/`, { method: "DELETE" });
        dialogClose(dialog);
        await refreshAll();
      } catch (e) {
        alert(`Could not delete: ${e.message}`);
        ok.disabled = false;
        dialogClose(dialog);
      }
    };
    $("[data-confirm-cancel]").onclick = () => dialogClose(dialog);
  }

  /* ---- Post (DRAFT, balanced) ---- */
  async function confirmPost(id) {
    // Local balance check: only DRAFT rows get a Post button; verify the entry balances before post.
    const balance = await fetchBalance(id);
    const dialog = $("[data-confirm-dialog]");
    $("[data-confirm-title]").textContent = "Post transaction?";
    $("[data-confirm-message]").textContent = balance.balanced
      ? "Post this journal entry? Once posted it can no longer be edited or deleted (it may still be voided)."
      : `This entry is out of balance by ${money(Math.abs(balance.diff))} and cannot be posted. Fix the lines first.`;
    $("[data-confirm-ok]").className = "primary-button" + (balance.balanced ? "" : " disabled");
    dialogOpen(dialog);
    const ok = $("[data-confirm-ok]");
    ok.onclick = async () => {
      if (!balance.balanced) { alert("This transaction is out of balance and cannot be posted."); return; }
      ok.disabled = true;
      try {
        await api(`${E.financialTransactions}${id}/post_entry/`, { method: "POST" });
        dialogClose(dialog);
        await refreshAll();
      } catch (e) {
        dialogClose(dialog);
        alert(`Could not post: ${e.message}`);
      }
    };
    $("[data-confirm-cancel]").onclick = () => dialogClose(dialog);
  }

  async function fetchBalance(id) {
    try {
      const t = await api(`${E.financialTransactions}${id}/`);
      const diff = (Number(t.total_debit) || 0) - (Number(t.total_credit) || 0);
      return { balanced: diff === 0, diff };
    } catch (_) {
      return { balanced: true, diff: 0 };
    }
  }

  /* ---- Void ---- */
  function confirmVoid(id) {
    const dialog = $("[data-confirm-dialog]");
    $("[data-confirm-title]").textContent = "Void transaction?";
    $("[data-confirm-message]").textContent = "Void this transaction? It will become VOIDED and can no longer be edited or posted. This cannot be undone.";
    $("[data-confirm-ok]").className = "primary-button";
    dialogOpen(dialog);
    const ok = $("[data-confirm-ok]");
    ok.onclick = async () => {
      ok.disabled = true;
      try {
        await api(`${E.financialTransactions}${id}/void/`, { method: "POST" });
        dialogClose(dialog);
        await refreshAll();
      } catch (e) {
        alert(`Could not void: ${e.message}`);
        ok.disabled = false;
        dialogClose(dialog);
      }
    };
    $("[data-confirm-cancel]").onclick = () => dialogClose(dialog);
  }

  /* ---- Detail (read-only) ---- */
  async function openDetail(id) {
    const dialog = $("[data-detail-dialog]");
    $("[data-detail-fields]").innerHTML = "<p>Loading transaction…</p>";
    $("[data-detail-lines]").innerHTML = "";
    $("[data-detail-actions]").innerHTML = "";
    dialogOpen(dialog);
    try {
      const t = await api(`${E.financialTransactions}${id}/`);
      $("[data-detail-title]").textContent = t.transaction_number || "Transaction detail";
      const fields = [
        ["Number", t.transaction_number], ["Date", t.transaction_date], ["Status", t.status],
        ["Source", t.source_label || "Manual"], ["Project", t.project_name || "—"], ["Client", t.client_name || "—"], ["Supplier", t.supplier_name || "—"],
        ["Description", t.description || "—"], ["Reference", t.reference || "—"],
      ];
      $("[data-detail-fields]").innerHTML = fields.map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");

      const lines = t.lines || [];
      $("[data-detail-lines]").innerHTML = lines.length
        ? lines.map((l) => `<tr><td><strong>${esc(l.account_code) || ""}</strong><span>${esc(l.account_name || "")}</span></td><td>${esc(l.description || "—")}</td><td>${esc(l.project ? "Set" : "—")}</td><td>${l.debit ? money(l.debit) : "—"}</td><td>${l.credit ? money(l.credit) : "—"}</td></tr>`).join("")
        : `<tr class="empty-row"><td colspan="5"><b>No lines on this transaction.</b></td></tr>`;

      $("[data-detail-total-debit]").textContent = money(t.total_debit);
      $("[data-detail-total-credit]").textContent = money(t.total_credit);
      const diff = (Number(t.total_debit) || 0) - (Number(t.total_credit) || 0);
      const bal = $("[data-detail-balance]");
      bal.textContent = diff === 0 ? "Balance: Balanced" : `Balance: ${money(Math.abs(diff))} out of balance`;
      bal.className = "txn-balance-status " + (diff === 0 ? "ok" : "bad");

      // Status-aware footer actions (backend remains authoritative).
      // System-generated entries are read-only here -- their lifecycle is
      // driven by the source document's own workflow.
      let actions = "";
      if (t.source_type) {
        actions += `<p class="txn-context">Generated by the ${esc(t.source_label || "source")} workflow — managed from that module.</p>`;
      } else if (t.status === "DRAFT") {
        actions += `<button type="button" class="accounting-row-action" data-detail-edit>Edit</button>` +
          `<button type="button" class="accounting-row-action post" data-detail-post>Post</button>`;
      } else if (t.status === "POSTED") {
        actions += `<button type="button" class="accounting-row-action danger" data-detail-void>Void</button>`;
      }
      $("[data-detail-actions]").innerHTML = actions;
      const editBtn = $("[data-detail-actions] [data-detail-edit]");
      if (editBtn) editBtn.onclick = () => { dialogClose(dialog); openEdit(t.id); };
      const postBtn = $("[data-detail-actions] [data-detail-post]");
      if (postBtn) postBtn.onclick = () => { dialogClose(dialog); confirmPost(t.id); };
      const voidBtn = $("[data-detail-actions] [data-detail-void]");
      if (voidBtn) voidBtn.onclick = () => { dialogClose(dialog); confirmVoid(t.id); };
    } catch (e) {
      $("[data-detail-fields]").innerHTML = `<p class="form-error">${esc(e.message)}</p>`;
    }
  }

  /* ---- events ---- */
  function bind() {
    $("[data-open-create]").onclick = openCreate;

    $("[data-txn-form]").addEventListener("submit", (e) => {
      e.preventDefault();
      submitTxn((e.submitter && e.submitter.hasAttribute("data-save-post")) ? "post" : "draft");
    });
    $("[data-add-line]").onclick = () => addLineRow();
    $$("[data-txn-close], [data-txn-cancel]").forEach((b) => (b.onclick = () => dialogClose($("[data-txn-dialog]"))));
    $("[data-detail-close]").onclick = () => dialogClose($("[data-detail-dialog]"));
    $$(".accounting-dialog").forEach((d) => d.addEventListener("click", (e) => { if (e.target === d) d.close(); }));

    let searchTimer;
    $("#transaction-search-input").addEventListener("input", (e) => {
      state.filters.search = e.target.value.trim();
      state.page = 1;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(async () => { try { await refreshAll(); } catch (_) {} }, 300);
    });
    $$("[data-status-filter]").forEach((s) => (s.onchange = async () => { state.filters.status = s.value; state.page = 1; try { await refreshAll(); } catch (_) {} }));
    $("[data-project-filter]").onchange = async (e) => { state.filters.project = e.target.value; state.page = 1; try { await refreshAll(); } catch (_) {} };
    $("[data-client-filter]").onchange = async (e) => { state.filters.client = e.target.value; state.page = 1; try { await refreshAll(); } catch (_) {} };
    $("[data-supplier-filter]").onchange = async (e) => { state.filters.supplier = e.target.value; state.page = 1; try { await refreshAll(); } catch (_) {} };
    $("[data-date-from]").onchange = async (e) => { state.filters.dateFrom = e.target.value; state.page = 1; try { await refreshAll(); } catch (_) {} };
    $("[data-date-to]").onchange = async (e) => { state.filters.dateTo = e.target.value; state.page = 1; try { await refreshAll(); } catch (_) {} };

    $("[data-page-prev]").onclick = async () => { if (!state.prev) return; state.page -= 1; try { await refreshAll(); } catch (_) {} };
    $("[data-page-next]").onclick = async () => { if (!state.next) return; state.page += 1; try { await refreshAll(); } catch (_) {} };
  }

  document.addEventListener("DOMContentLoaded", async () => {
    bind();
    try {
      await Promise.allSettled([loadAccounts(), loadLookups()]);
      populateFilters();
      await refreshAll();
    } catch (e) {
      $("[data-transaction-rows]").innerHTML = `<tr class="empty-row"><td colspan="11"><b>Could not load transactions</b><span>${esc(e && e.message || "Unknown error")}</span></td></tr>`;
    }
  });
})();
