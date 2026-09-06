(() => {
  "use strict";
  const E = {
    client: "/api/invoicing/client-invoices/",
    supplier: "/api/invoicing/supplier-invoices/",
    contractor: "/api/invoicing/contractor-invoices/",
    clientItems: "/api/invoicing/client-invoice-items/",
    supplierItems: "/api/invoicing/supplier-invoice-items/",
    contractorItems: "/api/invoicing/contractor-invoice-items/",
    clients: "/api/clients/clients/",
    suppliers: "/api/suppliers/suppliers/",
    contractors: "/api/contractors/",
    projects: "/api/projects/projects/",
    purchaseOrders: "/api/purchasing/purchase-orders/",
    taxRates: "/api/taxes/tax-rates/",
  };

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  const state = {
    client: [],           // client invoices (load-all)
    supplier: [],         // supplier invoices (load-all)
    contractor: [],       // contractor invoices (load-all)
    search: "",
    type: "all",
    status: "",
    detail: null,         // invoice detail currently open
    kind: null,           // "client" | "supplier" | "contractor" for detail/form context
    editingItem: null,    // item id being edited (null = adding)
  };

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (v) => Number(v || 0).toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

  function cookie(name) {
    const m = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[2]) : "";
  }

  async function api(url, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body) headers["Content-Type"] = "application/json";
    if (options.method && !["GET", "HEAD"].includes(options.method)) headers["X-CSRFToken"] = cookie("csrftoken");
    const r = await fetch(url, { credentials: "same-origin", ...options, headers });
    if (!r.ok) {
      let d = r.statusText;
      try { const b = await r.json(); d = Object.entries(b).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(" ") : v}`).join("\n"); } catch (_) {}
      throw new Error(`${r.status}: ${d}`);
    }
    return r.status === 204 ? null : r.json();
  }

  async function all(url) {
    const rows = [];
    while (url) {
      const d = await api(url);
      if (Array.isArray(d)) return d;
      rows.push(...(d.results || []));
      url = d.next;
    }
    return rows;
  }

  function combined() {
    return [
      ...state.client.map((x) => ({ kind: "client", ...x })),
      ...state.supplier.map((x) => ({ kind: "supplier", ...x })),
      ...state.contractor.map((x) => ({ kind: "contractor", ...x })),
    ];
  }

  function pill(s) {
    return `<span class="status${["PAID", "SENT"].includes(s) ? " active" : ["OVERDUE", "CANCELLED"].includes(s) ? " warning" : ""}"><i></i>${esc(s)}</span>`;
  }

  function render() {
    let rows = combined();
    if (state.type !== "all") rows = rows.filter((x) => x.kind === state.type);
    if (state.status) rows = rows.filter((x) => x.status === state.status);
    const q = state.search.toLowerCase();
    if (q) rows = rows.filter((x) => [x.invoice_number, x.client_name, x.supplier_name, x.contractor_name].some((v) => (v || "").toLowerCase().includes(q)));
    const kindLabel = { client: "Client", supplier: "Supplier", contractor: "Contractor" };
    const body = $("[data-invoice-rows]");
    body.innerHTML = rows.length
      ? rows.map((x) => `<tr><td><button class="invoice-link" data-view="${x.kind}:${x.id}"><strong>${esc(x.invoice_number)}</strong><span>View details</span></button></td><td>${kindLabel[x.kind]}</td><td>${esc(x.client_name || x.supplier_name || x.contractor_name)}</td><td>${esc(x.project_name || x.purchase_order_number || "—")}</td><td>${esc(x.invoice_date)}</td><td>${esc(x.due_date || "—")}</td><td>${money(x.total_amount)}</td><td>${money(x.outstanding_balance)}</td><td>${pill(x.status)}</td><td><div class="invoice-row-actions">${x.status === "DRAFT" ? `<button class="quiet-button" data-send="${x.kind}:${x.id}">Send</button><button class="quiet-button" data-edit="${x.kind}:${x.id}">Edit</button><button class="danger-action" data-delete="${x.kind}:${x.id}">Delete</button>` : ""}</div></td></tr>`).join("")
      : '<tr><td colspan="10"><strong>No invoices found</strong></td></tr>';
    $$("[data-view]", body).forEach((b) => (b.onclick = () => openDetail(...b.dataset.view.split(":"))));
    $$("[data-edit]", body).forEach((b) => (b.onclick = () => editHeader(...b.dataset.edit.split(":"))));
    $$("[data-send]", body).forEach((b) => (b.onclick = () => markSent(...b.dataset.send.split(":"))));
    $$("[data-delete]", body).forEach((b) => (b.onclick = () => deleteInvoice(...b.dataset.delete.split(":"))));
    const active = (x) => !["DRAFT", "CANCELLED"].includes(x.status);
    $("[data-metric=receivables]").textContent = money(state.client.filter(active).reduce((s, x) => s + Number(x.outstanding_balance), 0));
    $("[data-metric=payables]").textContent = money([...state.supplier, ...state.contractor].filter(active).reduce((s, x) => s + Number(x.outstanding_balance), 0));
    $("[data-metric=overdue]").textContent = money(combined().filter((x) => x.status === "OVERDUE").reduce((s, x) => s + Number(x.outstanding_balance), 0));
    $("[data-metric=total]").textContent = combined().length;
  }

  async function refresh() {
    [state.client, state.supplier, state.contractor] = await Promise.all([all(E.client), all(E.supplier), all(E.contractor)]);
    render();
  }

  async function choices() {
    const [clients, suppliers, contractors, projects, pos] = await Promise.all([
      all(E.clients), all(E.suppliers), all(E.contractors), all(E.projects), all(E.purchaseOrders),
    ]);
    const options = (rows, label) => '<option value="">Select…</option>' + rows.map((x) => `<option value="${x.id}">${esc(x[label])}</option>`).join("");
    $("[name=client]").innerHTML = options(clients, "name");
    $("[name=supplier]").innerHTML = options(suppliers, "name");
    $("[name=contractor_id]").innerHTML = options(contractors, "name");
    $("[name=project]").innerHTML = options(projects, "name");
    $("[name=purchase_order]").innerHTML = options(pos, "po_number");
  }

  async function openForm(kind, current = {}) {
    state.kind = kind;
    const f = $("[data-invoice-form]");
    f.reset();
    f.elements.kind.value = kind;
    $("[data-invoice-form-title]").textContent = `${current.id ? "Edit" : "Create"} ${kind} invoice`;
    $("[data-client-input]").hidden = kind !== "client";
    $("[data-supplier-input]").hidden = kind !== "supplier";
    $("[data-po-input]").hidden = kind !== "supplier";
    $("[data-contractor-input]").hidden = kind !== "contractor";
    // The Project select stays visible for every kind: supplier and
    // contractor invoices carry an optional project link too.
    f.elements.client.required = kind === "client";
    f.elements.supplier.required = kind === "supplier";
    f.elements.contractor_id.required = kind === "contractor";
    $("[data-invoice-error]").hidden = true;
    $("[data-invoice-dialog]").showModal();
    await choices();
    for (const [name, value] of Object.entries(current)) {
      if (f.elements[name] && value != null) f.elements[name].value = value;
    }
    f.dataset.id = current.id || "";
    if (!current.id) f.elements.invoice_date.value = new Date().toISOString().slice(0, 10);
  }

  async function editHeader(kind, id) {
    try { await openForm(kind, await api(`${E[kind]}${id}/`)); } catch (e) { alert(e.message); }
  }

  async function saveHeader(ev) {
    ev.preventDefault();
    const f = ev.currentTarget;
    const data = Object.fromEntries(new FormData(f));
    delete data.kind;
    ["due_date", "project", "purchase_order"].forEach((k) => { if (!data[k]) delete data[k]; });
    // Blank invoice_number is auto-generated by the backend (INV-<year>-<seq>).
    if (!data.invoice_number) delete data.invoice_number;
    // The client/supplier/contractor selects are hidden by kind, and
    // `required` is not enforced on hidden controls by the browser, so
    // validate here for a clear message instead of a raw 400.
    const partnerKey = { client: "client", supplier: "supplier", contractor: "contractor_id" }[state.kind];
    if (partnerKey && !data[partnerKey]) {
      const n = $("[data-invoice-error]");
      n.textContent = `Select ${partnerKey === "client" ? "a client" : partnerKey === "supplier" ? "a supplier" : "a contractor"} before saving.`;
      n.hidden = false;
      return;
    }
    try {
      const editing = Boolean(f.dataset.id);
      const saved = await api(editing ? `${E[state.kind]}${f.dataset.id}/` : E[state.kind], {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify(data),
      });
      $("[data-invoice-dialog]").close();
      await refresh();
      if (!editing) {
        // Open the new draft so line items (the actual money) can be
        // entered right away instead of leaving a $0.00 invoice behind.
        openDetail(state.kind, saved.id);
      }
    } catch (e) {
      const n = $("[data-invoice-error]");
      n.textContent = e.message;
      n.hidden = false;
    }
  }

  async function markSent(kind, id) {
    try {
      await api(`${E[kind]}${id}/mark_sent/`, { method: "POST" });
      await refresh();
    } catch (e) { alert(e.message); }
  }

  async function deleteInvoice(kind, id) {
    if (!confirm("Delete this draft invoice?")) return;
    try {
      await api(`${E[kind]}${id}/`, { method: "DELETE" });
      await refresh();
    } catch (e) { alert(e.message); }
  }

  async function openDetail(kind, id) {
    try {
      state.kind = kind;
      state.detail = await api(`${E[kind]}${id}/`);
      resetItemForm();
      const x = state.detail;
      $("[data-detail-kind]").textContent = `${kind.toUpperCase()} INVOICE`;
      $("[data-detail-title]").textContent = x.invoice_number;
      $("[data-detail-subtitle]").textContent = x.client_name || x.supplier_name || x.contractor_name;
      $("[data-detail-summary]").innerHTML = [
        ["Status", x.status], ["Subtotal", money(x.subtotal)], ["Tax", money(x.tax_amount)],
        ["Total", money(x.total_amount)], ["Outstanding", money(x.outstanding_balance)],
        ["Date", x.invoice_date], ["Due", x.due_date || "—"],
      ].map(([l, v]) => `<div><span>${l}</span><strong>${esc(v)}</strong></div>`).join("");
      $("[data-detail-actions]").innerHTML =
        x.status === "DRAFT"
          ? '<button class="primary-button" data-send>Mark sent</button><button class="danger-action" data-cancel>Cancel invoice</button>'
          : '<button class="danger-action" data-cancel>Cancel invoice</button>';
      $("[data-add-item]").hidden = x.status !== "DRAFT";
      renderItems();
      $("[data-invoice-detail] [data-send]") && ($("[data-invoice-detail] [data-send]").onclick = () => transition("mark_sent"));
      $("[data-cancel]") && ($("[data-cancel]").onclick = () => transition("cancel"));
      renderFinancial(x.project_id);
      const dialog = $("[data-invoice-detail]");
      if (!dialog.open) dialog.showModal();
    } catch (e) { alert(e.message); }
  }

  // When the invoice is linked to a project, show that project's financial
  // roll-up (revenue/expenses/net) so payment allocations against this
  // invoice are immediately visible in context.
  function renderFinancial(projectId) {
    const el = $("[data-financial-summary]");
    if (!projectId) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = '<p class="invoice-financial-load">Loading project financial summary…</p>';
    api(`/api/projects/projects/${projectId}/financial-summary/`)
      .then((f) => {
        const rows = [
          ["Revenue billed", f.revenue.billed], ["Revenue received", f.revenue.received],
          ["Expenses invoiced", f.expenses.invoiced], ["Expenses paid", f.expenses.paid],
          ["Outstanding (AR+AP)", f.net.outstanding], ["Net (cash)", f.net.cash],
        ];
        el.innerHTML = rows.map(([l, v]) => `<div><span>${l}</span><strong>${money(v)}</strong></div>`).join("");
      })
      .catch(() => { el.hidden = true; });
  }

  function renderItems() {
    const items = state.detail.items || [];
    const draft = state.detail.status === "DRAFT";
    $("[data-item-rows]").innerHTML = items.length
      ? items.map((i) => `<tr><td>${esc(i.description)}</td><td>${esc(i.quantity || "—")}</td><td>${money(i.unit_price)}</td><td>${money(i.discount_amount || 0)}</td><td>${money(i.total_amount)}</td><td>${draft ? `<button class="quiet-button" data-item-edit="${i.id}">Edit</button><button class="danger-action" data-item-delete="${i.id}">Delete</button>` : ""}</td></tr>`).join("")
      : draft
          ? '<tr><td colspan="6"><strong>No line items yet.</strong> <em>Add at least one before sending — it sets the invoice total.</em></td></tr>'
          : '<tr><td colspan="6">No line items on this invoice.</td></tr>';
    $$("[data-item-edit]").forEach((b) => (b.onclick = () => editItem(b.dataset.itemEdit)));
    $$("[data-item-delete]").forEach((b) => (b.onclick = () => deleteItem(b.dataset.itemDelete)));
  }

  // Supplier and contractor line items may be quantity-based (quantity +
  // unit_price) or a flat charge (total_amount with both left blank).
  // Client items are always quantity-based. line_type drives which fields
  // the form exposes.
  function configureItemFields() {
    const f = $("[data-item-form]");
    const payable = state.kind === "supplier" || state.kind === "contractor";
    const flat = payable && f.elements.line_type.value === "flat";
    $("[data-item-line-type]").hidden = !payable;
    $("[data-item-total]").hidden = !flat;
    $("[data-item-qty]").hidden = flat;
    $("[data-item-price]").hidden = flat;
    $("[data-item-discount]").hidden = payable;
    f.elements.quantity.required = !flat;
    f.elements.unit_price.required = !flat;
    f.elements.total_amount.required = flat;
  }

  function resetItemForm() {
    state.editingItem = null;
    const f = $("[data-item-form]");
    f.reset();
    f.elements.line_type.value = "qty";
    $("[data-item-error]").hidden = true;
    configureItemFields();
    f.hidden = true;
  }

  function openItemForm() {
    state.editingItem = null;
    const f = $("[data-item-form]");
    f.reset();
    f.elements.line_type.value = "qty";
    $("[data-item-error]").hidden = true;
    configureItemFields();
    f.hidden = false;
  }

  function editItem(id) {
    if (state.detail.status !== "DRAFT") return;
    const item = (state.detail.items || []).find((i) => i.id === id);
    if (!item) return;
    state.editingItem = id;
    const f = $("[data-item-form]");
    f.reset();
    const payable = state.kind === "supplier" || state.kind === "contractor";
    const flat = payable && (item.quantity == null || item.unit_price == null);
    f.elements.line_type.value = flat ? "flat" : "qty";
    configureItemFields();
    f.elements.description.value = item.description || "";
    if (flat) {
      f.elements.total_amount.value = item.total_amount || "";
    } else {
      f.elements.quantity.value = item.quantity || "";
      f.elements.unit_price.value = item.unit_price || "";
      if (!payable) f.elements.discount_amount.value = item.discount_amount || "0";
    }
    f.elements.tax_rate.value = item.tax_rate || "";
    f.hidden = false;
  }

  function itemPayload() {
    const f = $("[data-item-form]");
    const data = { description: f.elements.description.value };
    data[`${state.kind}_invoice`] = state.detail.id;
    const payable = state.kind === "supplier" || state.kind === "contractor";
    if ($("[data-tax-rate]").value) data.tax_rate = $("[data-tax-rate]").value;
    if (payable && f.elements.line_type.value === "flat") {
      data.total_amount = f.elements.total_amount.value;
      if (!data.total_amount) throw new Error("total_amount is required for a flat-charge line.");
    } else {
      data.quantity = f.elements.quantity.value;
      data.unit_price = f.elements.unit_price.value;
      if (!data.quantity || !data.unit_price) throw new Error("Enter both quantity and unit price.");
      if (!payable) data.discount_amount = f.elements.discount_amount.value || "0";
    }
    // tax_rate is optional; leave tax_rate unset when "No tax" is selected so
    // the serializer stores null (SET_NULL FK), never a fabricated rate.
    return data;
  }

  function itemsEndpoint(kind) {
    return kind === "client" ? E.clientItems : kind === "supplier" ? E.supplierItems : E.contractorItems;
  }

  async function saveItem(ev) {
    ev.preventDefault();
    const endpoint = itemsEndpoint(state.kind);
    const editing = state.editingItem;
    try {
      const data = itemPayload();
      await api(editing ? `${endpoint}${editing}/` : endpoint, {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify(data),
      });
      const detailId = state.detail.id;
      const kind = state.kind;
      resetItemForm();
      await openDetail(kind, detailId);
    } catch (e) {
      const n = $("[data-item-error]");
      n.textContent = e.message;
      n.hidden = false;
    }
  }

  async function deleteItem(id) {
    if (!confirm("Delete this line item?")) return;
    try {
      await api(`${itemsEndpoint(state.kind)}${id}/`, { method: "DELETE" });
      await openDetail(state.kind, state.detail.id);
    } catch (e) { alert(e.message); }
  }

  async function transition(action) {
    try {
      await api(`${E[state.kind]}${state.detail.id}/${action}/`, { method: "POST" });
      $("[data-invoice-detail]").close();
      await refresh();
    } catch (e) { alert(e.message); }
  }

  document.addEventListener("DOMContentLoaded", () => {
    // Populate the line-item tax-rate picker once; rates are configuration data.
    all(E.taxRates).then((rates) => {
      $("[data-tax-rate]").innerHTML =
        '<option value="">No tax</option>' +
        rates.map((r) => `<option value="${r.id}">${esc(r.name)} (${Number(r.rate).toLocaleString("en-US", { maximumFractionDigits: 4 })}%)</option>`).join("");
    }).catch(() => { /* tax picker stays at "No tax" if the endpoint is unavailable */ });

    $$("[data-new-invoice]").forEach((b) => (b.onclick = () => openForm(b.dataset.newInvoice)));
    $$("[data-invoice-close]").forEach((b) => (b.onclick = () => $("[data-invoice-dialog]").close()));
    $("[data-detail-close]").onclick = () => $("[data-invoice-detail]").close();
    $("[data-invoice-form]").onsubmit = saveHeader;
    $("[data-add-item]").onclick = () => openItemForm();
    $("[data-item-cancel]").onclick = () => { const n = $("[data-item-error]"); n.hidden = true; $("[data-item-form]").hidden = true; };
    $("[data-item-form]").onsubmit = saveItem;
    $("[data-item-line-type]").onchange = () => configureItemFields();
    $("[data-invoice-search]").oninput = (e) => { state.search = e.target.value; render(); };
    $("[data-type-filter]").onchange = (e) => { state.type = e.target.value; render(); };
    $("[data-status-filter]").onchange = (e) => { state.status = e.target.value; render(); };
    refresh().catch((e) => { $("[data-invoice-rows]").innerHTML = `<tr><td colspan="10">${esc(e.message)}</td></tr>`; });
  });
})();