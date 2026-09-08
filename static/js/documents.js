/* Document Management page (CPMAS-25). Consumes the DRF endpoints served
   by DocumentViewSet under /api/documents/documents/ using the
   authenticated session (SessionAuthentication) -- same fetch/CSRF
   pattern as suppliers.js/procurement.js. uploaded_by is derived
   server-side from the session, never sent by this page. */
(() => {
  "use strict";

  const API = "/api/documents/documents/";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const state = { docs: [], search: "", entityType: "" };

  function getCookie(name) {
    const m = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[2]) : "";
  }

  async function api(url, options = {}) {
    const opts = { credentials: "same-origin", ...options };
    opts.headers = { ...(options.headers || {}) };
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
    while (url) {
      const data = await api(url);
      rows.push(...(data.results || []));
      url = data.next;
    }
    return rows;
  }

  async function fetchAllDocs() {
    const params = new URLSearchParams();
    if (state.search) params.set("search", state.search);
    if (state.entityType) params.set("entity_type", state.entityType);
    return fetchAll(`${API}?${params.toString()}`);
  }

  const ENTITY_LABELS = {
    client: "Client", supplier: "Supplier", contractor: "Contractor", project: "Project",
    purchase_order: "Purchase order", expense: "Expense", client_invoice: "Client invoice",
    supplier_invoice: "Supplier invoice", change_order: "Change order",
  };

  // Where to find live records for each entity type so the upload form can
  // offer a pick-list instead of a hand-typed UUID. Each entry maps to that
  // module's list API and how to format one of its rows for display.
  const ENTITY_SOURCES = {
    client: { url: "/api/clients/clients/", label: (r) => r.company_name || r.name },
    supplier: { url: "/api/suppliers/suppliers/", label: (r) => r.company_name || r.name },
    contractor: { url: "/api/contractors/", label: (r) => r.company_name || r.name },
    project: { url: "/api/projects/projects/", label: (r) => `${r.name}${r.code ? ` (${r.code})` : ""}` },
    purchase_order: { url: "/api/purchasing/purchase-orders/", label: (r) => r.po_number },
    expense: { url: "/api/expenses/expenses/", label: (r) => r.description },
    client_invoice: { url: "/api/invoicing/client-invoices/", label: (r) => r.invoice_number },
    supplier_invoice: { url: "/api/invoicing/supplier-invoices/", label: (r) => r.invoice_number },
    change_order: { url: "/api/projects/change-orders/", label: (r) => r.number },
  };

  function fmtSize(bytes) {
    const n = Number(bytes);
    if (!Number.isFinite(n) || n <= 0) return "—";
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  }

  function renderRows() {
    const tbody = $("[data-doc-rows]");
    if (!state.docs.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="7"><b>No documents found</b><span>Try adjusting the search or entity filter.</span></td></tr>`;
      return;
    }
    tbody.innerHTML = state.docs.map((d) => `
      <tr data-doc-id="${d.id}">
        <td><strong>${esc(d.file_name)}</strong></td>
        <td><span class="doc-entity-badge">${esc(ENTITY_LABELS[d.entity_type] || d.entity_type)}</span></td>
        <td>${esc(d.document_type || "—")}</td>
        <td>${fmtSize(d.file_size)}</td>
        <td>${esc(d.uploaded_by_name || "—")}</td>
        <td>${esc((d.uploaded_at || "").slice(0, 10))}</td>
        <td class="doc-row-actions">
          <a href="#" data-doc-download="${d.id}" data-file-name="${esc(d.file_name)}">Download</a>
          <button type="button" class="quiet-button" data-doc-delete="${d.id}">Delete</button>
        </td>
      </tr>`).join("");

    $$("[data-doc-download]", tbody).forEach((btn) => {
      btn.addEventListener("click", (e) => { e.preventDefault(); downloadDoc(btn.dataset.docDownload, btn.dataset.fileName); });
    });
    $$("[data-doc-delete]", tbody).forEach((btn) => {
      btn.addEventListener("click", () => deleteDoc(btn.dataset.docDelete));
    });
  }

  async function downloadDoc(id, fileName) {
    const response = await fetch(`${API}${id}/download/`, { credentials: "same-origin" });
    if (!response.ok) {
      let detail = response.statusText;
      try { const body = await response.json(); detail = body.detail || detail; } catch (e) { /* ignore */ }
      showDownloadError(detail);
      return;
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = fileName || "document";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  }

  function showDownloadError(message) {
    $("[data-doc-error-message]").textContent = message;
    $("[data-doc-error-dialog]").showModal();
  }

  function renderMetrics() {
    $("[data-metric=total]").textContent = state.docs.length;
    const now = new Date();
    const thisMonth = state.docs.filter((d) => {
      const uploaded = new Date(d.uploaded_at);
      return uploaded.getUTCFullYear() === now.getUTCFullYear() && uploaded.getUTCMonth() === now.getUTCMonth();
    }).length;
    $("[data-metric=this-month]").textContent = thisMonth;
  }

  async function refresh() {
    try {
      state.docs = await fetchAllDocs();
      renderMetrics();
      renderRows();
    } catch (e) {
      $("[data-doc-rows]").innerHTML = `<tr class="empty-row"><td colspan="7"><b>Could not load documents</b><span>${esc(e.message)}</span></td></tr>`;
    }
  }

  async function deleteDoc(id) {
    if (!confirm("Delete this document? This cannot be undone.")) return;
    try {
      await api(`${API}${id}/`, { method: "DELETE" });
      await refresh();
    } catch (e) {
      alert("Could not delete document: " + e.message);
    }
  }

  function bindFilters() {
    let debounceTimer;
    $("#doc-search-input").addEventListener("input", (e) => {
      state.search = e.target.value;
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(refresh, 300);
    });
    $("#doc-entity-filter").addEventListener("change", (e) => {
      state.entityType = e.target.value;
      refresh();
    });
  }

  async function populateEntitySelect(entityType) {
    const select = $("[data-entity-select]");
    if (!select) return;
    const placeholder = '<option value="">Select a record…</option>';
    select.innerHTML = placeholder;
    if (!entityType) {
      select.disabled = true;
      return;
    }
    select.disabled = true;
    select.insertAdjacentHTML("beforeend", '<option value="">Loading records…</option>');
    const src = ENTITY_SOURCES[entityType];
    try {
      const rows = await fetchAll(src.url);
      select.innerHTML = placeholder;
      if (!rows.length) {
        select.insertAdjacentHTML("beforeend", '<option value="">No records found</option>');
      } else {
        rows.forEach((r) => select.insertAdjacentHTML("beforeend", `<option value="${esc(r.id)}">${esc(String(src.label(r) || r.id))}</option>`));
      }
      select.disabled = false;
    } catch (e) {
      select.innerHTML = placeholder;
      select.insertAdjacentHTML("beforeend", `<option value="">Could not load records: ${esc(e.message)}</option>`);
      select.disabled = false;
    }
  }

  function bindUpload() {
    const overlay = $("[data-doc-upload]");
    const form = $("[data-doc-upload-form]");
    const manualField = $("[data-doc-manual-field]");
    const manualInput = $("[data-entity-id-manual]");
    const entityTypeSelect = $("[data-entity-type]");
    const entityIdSelect = $("[data-entity-select]");
    if (!overlay || !form) return;

    $("[data-doc-new]").addEventListener("click", () => {
      overlay.hidden = false;
      manualField.hidden = true;
      manualInput.value = "";
      populateEntitySelect(entityTypeSelect ? entityTypeSelect.value : "");
    });
    $("[data-doc-upload-close]").addEventListener("click", () => { overlay.hidden = true; });
    $("[data-doc-upload-cancel]").addEventListener("click", () => { overlay.hidden = true; });
    $("[data-doc-manual-toggle]").addEventListener("click", () => {
      manualField.hidden = !manualField.hidden;
      if (!manualField.hidden) manualInput.focus();
    });

    // Delegated so a stale/partial DOM can't break binding; fill the record
    // list whenever the chosen entity type changes.
    form.addEventListener("change", (e) => {
      if (e.target && e.target.hasAttribute("data-entity-type")) {
        populateEntitySelect(e.target.value);
      }
    });
    if (entityIdSelect) {
      entityIdSelect.addEventListener("change", () => {
        manualField.hidden = true;
        manualInput.value = "";
      });
    }

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const formData = new FormData(form);
      const selectedId = entityIdSelect ? entityIdSelect.value : "";
      const manualId = manualInput.value.trim();
      if (selectedId) {
        formData.set("entity_id", selectedId);
      } else if (manualId) {
        formData.set("entity_id", manualId);
      } else {
        alert("Select a record or enter an Entity ID manually.");
        return;
      }
      try {
        await api(API, { method: "POST", body: formData });
        overlay.hidden = true;
        form.reset();
        manualField.hidden = true;
        await refresh();
      } catch (err) {
        alert("Could not upload document: " + err.message);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindFilters();
    bindUpload();
    document.querySelectorAll("[data-doc-error-close]").forEach((b) => b.addEventListener("click", () => $("[data-doc-error-dialog]").close()));
    refresh();
  });
})();
