/* Procurement page -- Purchase Orders + Goods Receiving (CPMAS-31).
   Consumes the authenticated DRF endpoints under /api/purchasing/,
   /api/suppliers/ and /api/inventory/ using the dashboard session
   (SessionAuthentication + CSRF), same fetch/CSRF pattern as payments.js.

   Purchase Order (CPMAS-30) authoring: the page creates PO headers via
   POST /purchase-orders/ and each line via POST /purchase-order-items/
   (totals are always computed by the backend), edits DRAFT POs via
   PATCH/DELETE, and drives status only through the submit/approve/cancel
   actions. DRAFT-lock and transition validation live in the backend and
   remain authoritative -- the UI refuse to expose actions the backend
   would reject.

   Receiving is append-only: the page only lists and reads goods receipts
   and creates new ones -- there is no edit/delete UI and no PATCH/PUT/DELETE
   calls for receipts. The purchasing backend remains the final authority on
   validation (over-receiving, PO status, atomic stock updates). */
(() => {
  "use strict";

  const E = {
    pos: "/api/purchasing/purchase-orders/",
    items: "/api/purchasing/purchase-order-items/",
    goodsReceipts: "/api/purchasing/goods-receipts/",
    warehouses: "/api/inventory/warehouses/",
    suppliers: "/api/suppliers/suppliers/",
    materials: "/api/inventory/materials/",
  };

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (v) => Number(v || 0).toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
  const fmtQty = (v) => Number(v || 0).toLocaleString("en-US", { maximumFractionDigits: 3 });

  const state = {
    pos: [],             // full PO list (load-all)
    receipts: [],        // current page of goods receipts
    receiptPage: 1,
    receiptNext: null,
    receiptPrev: null,
    receiptTotal: 0,
    poSearch: "",
    poStatus: "",
    receiptSearch: "",
    receiptPoFilter: "",
    receivablePos: [],   // APPROVED + PARTIALLY_RECEIVED
    warehouses: [],
    currentPo: null,     // PO detail loaded into the receive dialog
    poSuppliers: [],     // supplier catalog for the PO dialog
    poMaterials: [],     // material catalog for PO dialog lines
    poDialogMode: "create", // "create" | "edit"
    poDialogId: null,    // PO being edited
    poLoadedLines: {},   // id -> original line values loaded in edit mode
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
            .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(" ") : v}`)
            .join("\n");
        } else if (body) {
          message = String(body);
        }
      } catch (_) { /* non-JSON / network body */ }
      throw new Error(message || `Request failed (${response.status})`);
    }
    return response.status === 204 ? null : response.json();
  }

  // Load a full list across all pages.
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

  // Load a single page of a paginated endpoint (returns the paginated wrapper).
  async function page(url) {
    return api(url);
  }

  /* ---- helpers ---- */
  const RECEIVABLE = ["APPROVED", "PARTIALLY_RECEIVED"];
  const CLOSED = ["CANCELLED", "RECEIVED"];

  function poReceived(po) {
    const items = po.items || [];
    const ordered = items.reduce((s, i) => s + Number(i.quantity || 0), 0);
    const received = items.reduce((s, i) => s + Number(i.quantity_received || 0), 0);
    return { received, ordered };
  }

  function poIsFullyReceived(po) {
    const { received, ordered } = poReceived(po);
    return ordered > 0 && received >= ordered;
  }

  const statusPill = (s) => {
    const map = {
      DRAFT: "", SUBMITTED: "", APPROVED: " active",
      PARTIALLY_RECEIVED: " active", RECEIVED: " active", CANCELLED: " warning",
    };
    return `<span class="status${map[s] || ""}"><i></i>${esc(s || "—")}</span>`;
  };

  // Status-driven row actions. Only surfaces transitions the backend
  // ALLOWED_TRANSITIONS map permits (PARTIALLY_RECEIVED/RECEIVED/CANCELLED
  // are terminal; APPROVED/SUBMITTED add matching next steps).
  function poActions(p) {
    const actions = {
      DRAFT: [["edit", "Edit", "data-po-edit"], ["submit", "Submit", "data-po-submit-action"], ["cancel", "Cancel", "data-po-cancel"]],
      SUBMITTED: [["approve", "Approve", "data-po-approve"], ["cancel", "Cancel", "data-po-cancel"]],
      APPROVED: [["cancel", "Cancel", "data-po-cancel"], ["receive", "Receive", "data-receive"]],
      PARTIALLY_RECEIVED: [["receive", "Receive", "data-receive"]],
      RECEIVED: [],
      CANCELLED: [],
    }[p.status] || [];

    return actions
      .map(([kind, label, attr]) =>
        `<button type="button" class="row-action${kind === "cancel" ? " danger" : ""}" data-id="${p.id}" ${attr}="${p.id}">${label}</button>`)
      .join("");
  }

  /* ---- rendering: Purchase Orders ---- */
  function renderPos() {
    const body = $("[data-po-rows]");
    let list = state.pos;
    if (state.poStatus) list = list.filter((p) => p.status === state.poStatus);
    const q = state.poSearch.trim().toLowerCase();
    if (q) list = list.filter((p) => [p.po_number, p.supplier_name].some((v) => (v || "").toLowerCase().includes(q)));

    if (!list.length) {
      body.innerHTML = `<tr class="empty-row"><td colspan="8"><b>No purchase orders found</b><span>Try adjusting the search or status filter.</span></td></tr>`;
      return;
    }
    body.innerHTML = list.map((p) => {
      const { received, ordered } = poReceived(p);
      const pct = ordered > 0 ? Math.round((received / ordered) * 100) : 0;
      return `<tr>
        <td><strong>${esc(p.po_number)}</strong></td>
        <td>${esc(p.supplier_name || "—")}</td>
        <td>${esc(p.order_date || "—")}</td>
        <td>${esc(p.expected_delivery_date || "—")}</td>
        <td>${money(p.total_amount)}</td>
        <td>${pct}% <span class="received-note">${fmtQty(received)} / ${fmtQty(ordered)}</span></td>
        <td>${statusPill(p.status)}</td>
        <td><div class="po-row-actions">${poActions(p)}</div></td>
      </tr>`;
    }).join("");
  }

  /* ---- rendering: Goods Receiving ---- */
  function renderReceipts() {
    const body = $("[data-receipt-rows]");
    if (!state.receipts.length) {
      body.innerHTML = `<tr class="empty-row"><td colspan="7"><b>No goods receipts found</b><span>Try adjusting the search or purchase order filter.</span></td></tr>`;
    } else {
      body.innerHTML = state.receipts.map((r) => `
        <tr>
          <td><strong>${esc(r.receipt_number)}</strong></td>
          <td>${esc(r.purchase_order_number || "—")}</td>
          <td>${esc(r.warehouse_name || "—")}</td>
          <td>${esc(r.received_date || "—")}</td>
          <td>${(r.items_detail || []).length}</td>
          <td>${esc(r.notes || "—")}</td>
          <td><div class="payment-actions"><button type="button" class="procurement-row-view" data-receipt-detail="${r.id}">View details</button></div></td>
        </tr>`).join("");
      $$("[data-receipt-detail]", body).forEach((b) => (b.onclick = () => openReceiptDetail(b.dataset.receiptDetail)));
    }
    // Pagination state
    $("[data-page-next]").disabled = !state.receiptNext;
    $("[data-page-prev]").disabled = !state.receiptPrev;
    $("[data-page-info]").textContent = `Page ${state.receiptPage}`;
  }

  /* ---- metrics ---- */
  function renderStats() {
    const openPos = state.pos.filter((p) => !CLOSED.includes(p.status)).length;
    const receivable = state.pos.filter((p) => RECEIVABLE.includes(p.status)).length;
    const awaiting = state.pos.filter((p) => p.status === "APPROVED" && !poIsFullyReceived(p)).length;
    $("[data-metric=open_pos]").textContent = openPos;
    $("[data-metric=receivable]").textContent = receivable;
    $("[data-metric=goods_received]").textContent = state.receiptTotal;
    $("[data-metric=awaiting_delivery]").textContent = awaiting;
  }

  /* ---- data loads ---- */
  function poSearchParams() {
    const p = new URLSearchParams();
    if (state.poSearch) p.set("search", state.poSearch);
    if (state.poStatus) p.set("status", state.poStatus);
    return p;
  }

  async function loadPos() {
    state.pos = await all(`${E.pos}?${poSearchParams().toString()}`);
    renderPos();
  }

  function receiptListUrl() {
    const p = new URLSearchParams({ page: String(state.receiptPage) });
    if (state.receiptSearch) p.set("search", state.receiptSearch);
    if (state.receiptPoFilter) p.set("purchase_order", state.receiptPoFilter);
    return `${E.goodsReceipts}?${p.toString()}`;
  }

  async function loadReceipts() {
    const data = await page(receiptListUrl());
    state.receipts = data.results || [];
    state.receiptNext = data.next;
    state.receiptPrev = data.previous;
    state.receiptTotal = data.count || 0;
    renderReceipts();
  }

  /* ---- Refresh everything (after load, create, edit, transition, or receive) ---- */
  async function refreshAll() {
    try {
      await Promise.all([loadPos(), loadReceipts()]);
      populatePoFilter();
      renderStats();
    } catch (e) {
      $("[data-po-rows]").innerHTML = `<tr class="empty-row"><td colspan="8"><b>Could not load purchase orders</b><span>${esc(e.message)}</span></td></tr>`;
      $("[data-receipt-rows]").innerHTML = `<tr class="empty-row"><td colspan="7"><b>Could not load goods receipts</b><span>${esc(e.message)}</span></td></tr>`;
    }
  }

  /* ---- Receive Goods dialog ---- */
  const currentUser = () => document.querySelector(".topbar")?.dataset.appUserId || "";

  async function loadWarehouses() {
    if (state.warehouses.length) return;
    try {
      state.warehouses = await all(E.warehouses);
    } catch (e) {
      state.warehouses = [];
    }
  }

  function populateWarehouses() {
    const select = $("[data-warehouse-select]");
    const allWarehouses = [...state.warehouses].sort((a, b) => (Number(b.is_active) - Number(a.is_active)));
    select.innerHTML = '<option value="">Select warehouse…</option>' +
      allWarehouses.map((w) => `<option value="${w.id}">${esc(w.name)}${w.location ? ` — ${esc(w.location)}` : ""}${w.is_active ? "" : " (inactive)"}</option>`).join("");
  }

  async function loadReceivablePos() {
    const [a, p] = await Promise.all([
      all(`${E.pos}?status=APPROVED`),
      all(`${E.pos}?status=PARTIALLY_RECEIVED`),
    ]);
    const seen = new Set();
    const merged = [];
    [...a, ...p].forEach((po) => {
      if (!seen.has(po.id)) { seen.add(po.id); merged.push(po); }
    });
    state.receivablePos = merged.sort((x, y) => x.po_number.localeCompare(y.po_number));
  }

  function populateReceivablePos() {
    const select = $("[data-receive-po-select]");
    select.innerHTML = '<option value="">Select purchase order…</option>' +
      state.receivablePos.map((po) => `<option value="${po.id}">${esc(po.po_number)} — ${esc(po.supplier_name || "")}</option>`).join("");
  }

  function populatePoFilter() {
    const select = $("[data-receipt-po-filter]");
    const opts = state.pos.slice().sort((a, b) => a.po_number.localeCompare(b.po_number));
    const current = select.value;
    select.innerHTML = '<option value="">Purchase order: All</option>' +
      opts.map((po) => `<option value="${po.id}">${esc(po.po_number)}</option>`).join("");
    select.value = current || "";
  }

  async function openReceiveDialog(preSelectedPoId) {
    const dialog = $("[data-receive-dialog]");
    const form = $("[data-receive-form]");
    form.reset();
    $("[data-receive-error]").hidden = true;
    form.elements.received_date.value = new Date().toISOString().slice(0, 10);

    // Pre-load warehouses and receivable POs.
    try {
      await Promise.all([loadWarehouses(), loadReceivablePos()]);
      populateWarehouses();
      populateReceivablePos();
      form.elements.purchase_order.value = preSelectedPoId || "";
      if (preSelectedPoId) {
        $("[data-receive-items]").innerHTML = `<tr class="empty-row"><td colspan="5">Loading items…</td></tr>`;
        await onPoSelected(preSelectedPoId);
      } else {
        $("[data-receive-items]").innerHTML = `<tr class="empty-row"><td colspan="5">Select a purchase order to load its items.</td></tr>`;
      }
    } catch (e) {
      showReceiveError(e);
    }
    dialog.showModal();
  }

  async function onPoSelected(poId) {
    const body = $("[data-receive-items]");
    if (!poId) {
      state.currentPo = null;
      body.innerHTML = `<tr class="empty-row"><td colspan="5">Select a purchase order to load its items.</td></tr>`;
      return;
    }
    body.innerHTML = `<tr class="empty-row"><td colspan="5"><b>Loading items…</b><span>Fetching PO lines.</span></td></tr>`;
    try {
      state.currentPo = await api(`${E.pos}${poId}/`);
      const items = state.currentPo.items || [];
      if (!items.length) {
        body.innerHTML = `<tr class="empty-row"><td colspan="5"><b>No line items on this purchase order.</b></td></tr>`;
        return;
      }
      body.innerHTML = items.map((it) => {
        const remaining = Number(it.quantity_remaining || 0);
        const disabled = remaining <= 0;
        return `<tr>
          <td><strong>${esc(it.material_name || "—")}</strong><span>${esc(it.material_sku || "")}</span></td>
          <td>${fmtQty(it.quantity)}</td>
          <td>${fmtQty(it.quantity_received)}</td>
          <td>${fmtQty(it.quantity_remaining)}</td>
          <td><input type="number" class="qty-input" name="qty_${it.id}" data-item="${it.id}" min="0" max="${remaining}" step="0.001" value="0" ${disabled ? "disabled" : ""}></td>
        </tr>`;
      }).join("");

      // Live clamp: keep 0 <= qty <= remaining (defense-in-depth; backend remains authoritative).
      $$("[data-item]", body).forEach((input) => {
        input.addEventListener("input", () => {
          const max = Number(input.max);
          const val = Number(input.value);
          if (Number.isFinite(val) && val > max) input.value = max;
          else if (Number.isFinite(val) && val < 0) input.value = 0;
        });
      });
    } catch (e) {
      body.innerHTML = `<tr class="empty-row"><td colspan="5"><b>Could not load items</b><span>${esc(e.message)}</span></td></tr>`;
    }
  }

  function showReceiveError(e) {
    const n = $("[data-receive-error]");
    n.textContent = e.message || "Something went wrong.";
    n.hidden = false;
  }

  async function submitReceive(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const errorEl = $("[data-receive-error]");
    errorEl.hidden = true;

    const userId = currentUser();
    if (!userId) {
      showReceiveError(new Error("No linked user account for recording this receipt."));
      return;
    }

    const values = Object.fromEntries(new FormData(form).entries());
    if (!values.notes) delete values.notes;

    // Build only the item rows with a received quantity > 0.
    const items = state.currentPo && state.currentPo.items ? state.currentPo.items
      .map((it) => {
        const qty = form.elements[`qty_${it.id}`];
        if (!qty || qty.disabled) return null;
        const q = Number(qty.value || 0);
        if (!(q > 0)) return null;
        return { purchase_order_item: it.id, quantity_received: String(q) };
      })
      .filter(Boolean) : [];

    if (!items.length) {
      showReceiveError(new Error("Enter a quantity greater than zero on at least one item."));
      return;
    }

    const payload = {
      purchase_order: values.purchase_order,
      receipt_number: values.receipt_number,
      received_date: values.received_date,
      warehouse: values.warehouse,
      recorded_by: userId,
      items,
    };

    try {
      await api(E.goodsReceipts, { method: "POST", body: JSON.stringify(payload) });
      form.closest("[data-receive-dialog]").close();
      $("[data-receive-items]").innerHTML = `<tr class="empty-row"><td colspan="5">Select a purchase order to load its items.</td></tr>`;
      state.currentPo = null;
      await refreshAll(); // re-fetch so PO status / received quantities reflect the backend transaction
    } catch (e) {
      // Keep the dialog open with entered values intact; surface the DRF error.
      showReceiveError(e);
    }
  }

  /* ---- Purchase Order create/edit dialog ---- */
  let suppliersLoaded = false;
  let materialsLoaded = false;

  async function loadSuppliers() {
    if (suppliersLoaded && state.poSuppliers.length) return;
    try {
      state.poSuppliers = await all(E.suppliers);
      suppliersLoaded = true;
    } catch (e) {
      state.poSuppliers = [];
    }
  }

  async function loadMaterials() {
    if (materialsLoaded && state.poMaterials.length) return;
    try {
      state.poMaterials = await all(E.materials);
      materialsLoaded = true;
    } catch (e) {
      state.poMaterials = [];
    }
  }

  function supplierOptions(selectedId) {
    const sorted = [...state.poSuppliers].sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
    return '<option value="">Select supplier…</option>' +
      sorted.map((s) => `<option value="${s.id}" ${String(s.id) === String(selectedId || "") ? "selected" : ""}>${esc(s.name || s.company_name || "Unnamed supplier")}</option>`).join("");
  }

  function materialOptions(selectedId) {
    const sorted = [...state.poMaterials].sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
    return '<option value="">Select material…</option>' +
      sorted.map((m) => `<option value="${m.id}" ${String(m.id) === String(selectedId || "") ? "selected" : ""}>${esc(m.name)}${m.sku ? ` — ${esc(m.sku)}` : ""}</option>`).join("");
  }

  function lineValue(v) {
    return v == null ? "" : String(v);
  }

  function poLineRow(line) {
    const lineId = line && line.id ? esc(line.id) : "";
    return `<tr class="po-line-row" data-po-line${lineId ? ` data-line-item-id="${lineId}"` : ""}>
      <td><select name="material" data-line-material required>${materialOptions(line && line.material)}</select></td>
      <td><input type="number" name="quantity" data-line-quantity class="line-input" required min="0.001" step="0.001" value="${lineValue(line && line.quantity)}" placeholder="0"></td>
      <td><input type="number" name="unit_price" data-line-price class="line-input" required min="0" step="0.01" value="${lineValue(line && line.unit_price)}" placeholder="0.00"></td>
      <td><input type="text" name="description" data-line-description class="line-desc" value="${line && line.description ? esc(line.description) : ""}" placeholder="Optional details"></td>
      <td><button type="button" class="line-remove" data-po-remove-item aria-label="Remove line">×</button></td>
    </tr>`;
  }

  function addLineRow(line) {
    $("[data-po-item-rows]").insertAdjacentHTML("beforeend", poLineRow(line));
    $("[data-po-error]").hidden = true;
  }

  function renderItemRows(lines) {
    const body = $("[data-po-item-rows]");
    body.innerHTML = lines.length ? lines.map((l) => poLineRow(l)).join("") : "";
    if (!$$("[data-po-line]", body).length) addLineRow();
  }

  function showPoError(e) {
    const n = $("[data-po-error]");
    n.textContent = e.message || "Something went wrong.";
    n.hidden = false;
  }

  function showPageError(e) {
    const n = $("[data-po-page-error]");
    n.textContent = e.message || "Something went wrong.";
    n.hidden = false;
    const panel = n.closest(".module-table");
    if (panel) panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function openPoDialog(mode, poId) {
    const dialog = $("[data-po-dialog]");
    const form = $("[data-po-form]");
    form.reset();
    $("[data-po-save]").disabled = false;
    $("[data-po-error]").hidden = true;
    $("[data-po-page-error]").hidden = true;

    state.poDialogMode = mode;
    state.poDialogId = poId || null;
    state.poLoadedLines = {};

    $("[data-po-title]").textContent = mode === "edit" ? "Edit purchase order" : "New purchase order";
    $("[data-po-save]").textContent = mode === "edit" ? "Save changes" : "Create purchase order";
    form.elements.order_date.value = new Date().toISOString().slice(0, 10);

    try {
      await Promise.all([loadSuppliers(), loadMaterials()]);
      const supplierSelect = $("[data-po-supplier]");
      supplierSelect.innerHTML = supplierOptions("");

      if (mode === "edit" && poId) {
        const po = await api(`${E.pos}${poId}/`);
        state.poDialogId = po.id;
        supplierSelect.value = po.supplier || "";
        form.elements.po_number.value = po.po_number || "";
        form.elements.order_date.value = po.order_date || "";
        form.elements.expected_delivery_date.value = po.expected_delivery_date || "";
        (po.items || []).forEach((it) => {
          state.poLoadedLines[it.id] = {
            material: it.material || "",
            quantity: it.quantity == null ? "" : String(it.quantity),
            unit_price: it.unit_price == null ? "" : String(it.unit_price),
            description: it.description || "",
          };
        });
        renderItemRows(po.items || []);
      } else {
        renderItemRows([]);
      }
    } catch (e) {
      showPoError(e);
    }
    dialog.showModal();
  }

  function disablePoSave() {
    $("[data-po-save]").disabled = true;
  }

  function enablePoSave() {
    $("[data-po-save]").disabled = false;
  }

  async function submitPo(event) {
    event.preventDefault();
    const form = event.currentTarget;
    $("[data-po-error]").hidden = true;
    disablePoSave();

    try {
      const userId = currentUser();
      if (!userId) {
        showPoError(new Error("No linked user account for recording this purchase order."));
        enablePoSave();
        return;
      }

      const formData = Object.fromEntries(new FormData(form).entries());

      const allRows = $$("[data-po-line]", $("[data-po-item-rows]")).map((row) => ({
        itemId: row.dataset.lineItemId || "",
        material: row.querySelector("[data-line-material]").value,
        quantity: row.querySelector("[data-line-quantity]").value.trim(),
        unitPrice: row.querySelector("[data-line-price]").value.trim(),
        description: row.querySelector("[data-line-description]").value.trim(),
      }));
      // Rows left entirely blank are ignored; a partially filled row is validated.
      const lines = allRows.filter((r) => r.material || r.quantity !== "" || r.unitPrice !== "" || r.description);

      const errs = [];
      if (!formData.supplier) errs.push("Select a supplier.");
      if (!formData.po_number || !formData.po_number.trim()) errs.push("Enter a PO number.");
      if (!formData.order_date) errs.push("Enter an order date.");
      if (!lines.length) errs.push("Add at least one line item.");
      lines.forEach((r, i) => {
        if (!r.material) errs.push(`Line ${i + 1}: select a material.`);
        if (!(r.quantity !== "" && Number(r.quantity) > 0)) errs.push(`Line ${i + 1}: quantity must be greater than zero.`);
        if (r.unitPrice === "" || Number(r.unitPrice) < 0) errs.push(`Line ${i + 1}: unit price cannot be negative.`);
      });
      if (errs.length) {
        showPoError(new Error(errs.join("\n")));
        enablePoSave();
        return;
      }

      const headerPayload = {
        supplier: formData.supplier,
        po_number: formData.po_number.trim(),
        order_date: formData.order_date,
        created_by: userId,
      };
      if (formData.expected_delivery_date) headerPayload.expected_delivery_date = formData.expected_delivery_date;

      if (state.poDialogMode === "edit" && state.poDialogId) {
        const patch = { ...headerPayload };
        delete patch.created_by; // created_by is an audit field, not something a DRAFT edit rewrites
        await api(`${E.pos}${state.poDialogId}/`, { method: "PATCH", body: JSON.stringify(patch) });

        const keptIds = new Set(lines.filter((l) => l.itemId).map((l) => l.itemId));
        for (const id of Object.keys(state.poLoadedLines)) {
          if (!keptIds.has(id)) await api(`${E.items}${id}/`, { method: "DELETE" });
        }
        for (const line of lines) {
          if (!line.itemId) {
            const payload = { purchase_order: state.poDialogId, material: line.material, quantity: line.quantity, unit_price: line.unitPrice };
            if (line.description) payload.description = line.description;
            await api(E.items, { method: "POST", body: JSON.stringify(payload) });
          } else {
            const original = state.poLoadedLines[line.itemId] || {};
            const changed = original.material !== line.material ||
              original.quantity !== line.quantity ||
              original.unit_price !== line.unitPrice ||
              original.description !== line.description;
            if (changed) {
              const payload = { material: line.material, quantity: line.quantity, unit_price: line.unitPrice };
              if (line.description) payload.description = line.description;
              await api(`${E.items}${line.itemId}/`, { method: "PATCH", body: JSON.stringify(payload) });
            }
          }
        }
        $("[data-po-dialog]").close();
        await refreshAll();
      } else {
        const created = await api(E.pos, { method: "POST", body: JSON.stringify(headerPayload) });
        try {
          for (const line of lines) {
            const payload = { purchase_order: created.id, material: line.material, quantity: line.quantity, unit_price: line.unitPrice };
            if (line.description) payload.description = line.description;
            await api(E.items, { method: "POST", body: JSON.stringify(payload) });
          }
        } catch (e) {
          // Header created, lines failed: surface the actual failure, do not
          // hide it, do not invent rollback -- the PO stays visible to Edit.
          showPageError(new Error(`Purchase order ${created.po_number} was created, but adding line items failed:\n${e.message}`));
          $("[data-po-dialog]").close();
          await refreshAll();
          return;
        }
        $("[data-po-dialog]").close();
        $("[data-po-item-rows]").innerHTML = "";
        $("[data-po-page-error]").hidden = true;
        await refreshAll();
      }
    } catch (e) {
      showPoError(e);
      enablePoSave();
    }
  }

  /* ---- PO status transitions (submit/approve/cancel) ---- */
  let transitionBusy = false;

  const poConfirmText = {
    submit: { title: "Submit purchase order?", message: "Submit this purchase order to the supplier? The order can then be approved and received against.", okText: "Submit order" },
    approve: { title: "Approve purchase order?", message: "Approve this purchase order? Approved orders can be received into stock.", okText: "Approve order" },
    cancel: { title: "Cancel purchase order?", message: "Cancel this purchase order? This cannot be undone.", okText: "Cancel order" },
  };

  function confirmPoAction(kind) {
    const { title, message, okText } = poConfirmText[kind];
    return new Promise((resolve) => {
      const dialog = $("[data-po-confirm-dialog]");
      $("[data-po-confirm-title]").textContent = title;
      $("[data-po-confirm-message]").textContent = message;
      let settled = false;
      const settle = (value) => { if (settled) return; settled = true; resolve(value); };
      const ok = $("[data-po-confirm-ok]");
      ok.textContent = okText;
      ok.onclick = () => { settle(true); dialog.close(); };
      $("[data-po-confirm-cancel]").onclick = () => dialog.close();
      dialog.oncancel = () => dialog.close();   // Esc key
      dialog.onclose = () => settle(false);
      dialog.onclick = (e) => { if (e.target === dialog) dialog.close(); };  // click on backdrop
      dialog.showModal();
    });
  }

  async function runPoAction(kind, id) {
    if (transitionBusy) return;
    const endpoint = { submit: "submit", approve: "approve", cancel: "cancel" }[kind];
    if (!endpoint) return;
    const confirmed = await confirmPoAction(kind);
    if (!confirmed) return;

    transitionBusy = true;
    try {
      await api(`${E.pos}${id}/${endpoint}/`, { method: "POST" });
      $("[data-po-page-error]").hidden = true;
      await refreshAll();
    } catch (e) {
      // Backend validation (including invalid transitions) is authoritative.
      showPageError(e);
    } finally {
      transitionBusy = false;
    }
  }

  /* ---- Receipt detail (read-only) ---- */
  async function openReceiptDetail(id) {
    const dialog = $("[data-receipt-detail-dialog]");
    $("[data-receipt-detail-fields]").innerHTML = "<p>Loading receipt…</p>";
    $("[data-receipt-detail-items]").innerHTML = "";
    dialog.showModal();
    try {
      const r = await api(`${E.goodsReceipts}${id}/`);
      $("[data-receipt-detail-title]").textContent = r.receipt_number || "Receipt detail";
      const fields = [
        ["Receipt number", r.receipt_number],
        ["Purchase order", r.purchase_order_number],
        ["Warehouse", r.warehouse_name],
        ["Received date", r.received_date],
        ["Notes", r.notes || "—"],
      ];
      $("[data-receipt-detail-fields]").innerHTML = fields
        .map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
      const items = r.items_detail || [];
      $("[data-receipt-detail-items]").innerHTML = items.length
        ? items.map((it) => `<tr><td>${esc(it.material_name || "—")}</td><td>${fmtQty(it.quantity_received)}</td><td>${esc(it.notes || "—")}</td></tr>`).join("")
        : `<tr class="empty-row"><td colspan="3"><b>No items on this receipt.</b></td></tr>`;
    } catch (e) {
      $("[data-receipt-detail-fields]").innerHTML = `<p class="form-error">${esc(e.message)}</p>`;
    }
  }

  /* ---- events ---- */
  function bind() {
    $$("[data-open-receive]").forEach((b) => (b.onclick = () => openReceiveDialog()));
    $("[data-receive-po-select]").addEventListener("change", (e) => onPoSelected(e.target.value));
    $("[data-receive-form]").addEventListener("submit", submitReceive);

    $$("[data-receive-close]").forEach((b) => (b.onclick = () => $("[data-receive-dialog]").close()));
    $("[data-receipt-detail-close]").onclick = () => $("[data-receipt-detail-dialog]").close();
    $$(".procurement-dialog").forEach((d) => d.addEventListener("click", (e) => { if (e.target === d) d.close(); }));

    // Purchase Order authoring
    $$("[data-open-po]").forEach((b) => (b.onclick = () => openPoDialog("create")));
    $$("[data-po-close]").forEach((b) => (b.onclick = () => {
      $("[data-po-dialog]").close();
      $("[data-po-save]").disabled = false;
    }));
    $("[data-po-form]").addEventListener("submit", submitPo);
    $("[data-po-add-item]").addEventListener("click", () => addLineRow());
    $("[data-po-item-rows]").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-po-remove-item]");
      if (!btn) return;
      e.preventDefault();
      const row = btn.closest("[data-po-line]");
      if (!row) return;
      if ($$("[data-po-line]", $("[data-po-item-rows]")).length <= 1) {
        showPoError(new Error("A purchase order needs at least one line item."));
        return;
      }
      row.remove();
      $("[data-po-error]").hidden = true;
    });

    // Delegated PO row actions survive table re-renders after refreshAll().
    $("[data-po-rows]").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-po-edit], [data-po-submit-action], [data-po-approve], [data-po-cancel], [data-receive]");
      if (!btn) return;
      e.preventDefault();
      const id = btn.getAttribute("data-id");
      if (btn.hasAttribute("data-po-edit")) return openPoDialog("edit", id);
      if (btn.hasAttribute("data-po-submit-action")) return runPoAction("submit", id);
      if (btn.hasAttribute("data-po-approve")) return runPoAction("approve", id);
      if (btn.hasAttribute("data-po-cancel")) return runPoAction("cancel", id);
      if (btn.hasAttribute("data-receive")) return openReceiveDialog(id);
    });

    let poTimer;
    $("#po-search-input").addEventListener("input", (e) => {
      state.poSearch = e.target.value.trim();
      clearTimeout(poTimer);
      poTimer = setTimeout(async () => { try { await loadPos(); } catch (err) { /* handled in render */ } }, 300);
    });
    $("[data-po-status]").addEventListener("change", async (e) => {
      state.poStatus = e.target.value;
      try { await loadPos(); } catch (err) { /* handled */ }
    });

    let rcTimer;
    $("#receipt-search-input").addEventListener("input", (e) => {
      state.receiptSearch = e.target.value.trim();
      state.receiptPage = 1;
      clearTimeout(rcTimer);
      rcTimer = setTimeout(async () => { try { await refreshAll(); } catch (err) { /* handled */ } }, 300);
    });
    $("[data-receipt-po-filter]").addEventListener("change", async (e) => {
      state.receiptPoFilter = e.target.value;
      state.receiptPage = 1;
      try { await refreshAll(); } catch (err) { /* handled */ }
    });
    $("[data-page-prev]").addEventListener("click", async () => {
      if (!state.receiptPrev) return;
      state.receiptPage -= 1;
      try { await refreshAll(); } catch (err) { /* handled */ }
    });
    $("[data-page-next]").addEventListener("click", async () => {
      if (!state.receiptNext) return;
      state.receiptPage += 1;
      try { await refreshAll(); } catch (err) { /* handled */ }
    });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    bind();
    try {
      // Load POs first so the receipt PO filter and metrics can use them.
      await refreshAll();
    } catch (e) {
      $("[data-po-rows]").innerHTML = `<tr class="empty-row"><td colspan="8"><b>Could not load purchase orders</b><span>${esc(e.message)}</span></td></tr>`;
    }
  });
})();