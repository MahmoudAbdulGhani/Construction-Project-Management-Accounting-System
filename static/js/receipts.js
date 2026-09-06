/* Receipts page (CPMAS-58). Consumes the DRF endpoints served by
   ReceiptViewSet under /api/payments/receipts/ using the authenticated
   session (SessionAuthentication) -- same fetch/CSRF pattern as
   suppliers.js. */
(() => {
  "use strict";

  const API = "/api/payments/receipts/";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const state = { receipts: [], search: "", dateFrom: "", dateTo: "" };

  async function api(url) {
    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json();
  }

  async function fetchAllReceipts() {
    const params = new URLSearchParams();
    if (state.search) params.set("search", state.search);
    if (state.dateFrom) params.set("date_from", state.dateFrom);
    if (state.dateTo) params.set("date_to", state.dateTo);

    const rows = [];
    let url = `${API}?${params.toString()}`;
    while (url) {
      const data = await api(url);
      rows.push(...(data.results || []));
      url = data.next;
    }
    return rows;
  }

  const fmtMoney = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 }) : (v ?? "0.00");
  };

  function renderRows() {
    const tbody = $("[data-receipt-rows]");
    if (!state.receipts.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="7"><b>No receipts found</b><span>Try adjusting the search or date range.</span></td></tr>`;
      return;
    }
    tbody.innerHTML = state.receipts.map((r) => `
      <tr>
        <td><strong>${esc(r.receipt_number)}</strong></td>
        <td>${esc(r.receipt_date)}</td>
        <td>${esc(r.payment_number)}</td>
        <td>${esc(r.payee_name || r.client_name || r.supplier_name || r.contractor_name || r.employee_name || "—")}</td>
        <td>${esc(r.payment_method)}</td>
        <td>${fmtMoney(r.amount)}</td>
        <td><a class="receipt-download" href="${API}${r.id}/download/">Download PDF</a></td>
      </tr>`).join("");
  }

  function renderMetrics() {
    $("[data-metric=total]").textContent = state.receipts.length;
    const now = new Date();
    const thisMonth = state.receipts.filter((r) => {
      const d = new Date(r.receipt_date);
      return d.getUTCFullYear() === now.getUTCFullYear() && d.getUTCMonth() === now.getUTCMonth();
    }).length;
    $("[data-metric=this-month]").textContent = thisMonth;
  }

  async function refresh() {
    try {
      state.receipts = await fetchAllReceipts();
      renderMetrics();
      renderRows();
    } catch (e) {
      $("[data-receipt-rows]").innerHTML = `<tr class="empty-row"><td colspan="7"><b>Could not load receipts</b><span>${esc(e.message)}</span></td></tr>`;
    }
  }

  function bindFilters() {
    let debounceTimer;
    $("#receipt-search-input").addEventListener("input", (e) => {
      state.search = e.target.value;
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(refresh, 300);
    });
    $("[data-date-from]").addEventListener("change", (e) => { state.dateFrom = e.target.value; refresh(); });
    $("[data-date-to]").addEventListener("change", (e) => { state.dateTo = e.target.value; refresh(); });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindFilters();
    refresh();
  });
})();
