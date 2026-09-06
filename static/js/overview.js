(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const money = v => Number(v || 0).toLocaleString("en-US", {style: "currency", currency: "USD", minimumFractionDigits: 2});
  const money0 = v => Number(v || 0).toLocaleString("en-US", {style: "currency", currency: "USD", maximumFractionDigits: 0});
  const label = v => String(v || "—").replaceAll("_", " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);

  const pad = n => String(n).padStart(2, "0");
  function todayStr() { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
  function monthStartStr() { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-01`; }
  function addDays(iso, n) { const [y, m, d] = iso.split("-").map(Number); const dt = new Date(y, m - 1, d + n); return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`; }
  function shortMonth(iso) { const [y, m] = iso.split("-").map(Number); return new Date(y, m - 1, 1).toLocaleString("en-US", {month: "short"}).toUpperCase(); }
  function dayOf(iso) { const [, , d] = iso.split("-").map(Number); return pad(d); }

  async function api(url) {
    const response = await fetch(url, {credentials: "same-origin", headers: {Accept: "application/json"}});
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return response.json();
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

  // Dashboard-only "overdue" rule (read-only, never writes statuses):
  // an invoice counts as overdue when its status is SENT or PARTIALLY_PAID,
  // its due_date is before today, and its outstanding_balance is above zero.
  // The backend only ever stores DRAFT/SENT/PARTIALLY_PAID/PAID/CANCELLED —
  // no OVERDUE transition exists — so the dashboard derives it here.
  const BAD_STATUS = new Set(["DRAFT", "CANCELLED"]);
  const OVERDUE_OPEN = new Set(["SENT", "PARTIALLY_PAID"]);

  const setMetric = (name, value) => { const el = $(`[data-ov-metric="${name}"]`); if (el) el.textContent = value; };
  const setText = (sel, value) => { const el = $(sel); if (el) el.textContent = value; };

  function invoiceStats(invoices, today) {
    let outstanding = 0, overdueAmt = 0, overdueCount = 0;
    for (const inv of invoices || []) {
      if (BAD_STATUS.has(inv.status)) continue;
      const bal = Number(inv.outstanding_balance || 0);
      outstanding += bal;
      if (bal > 0 && OVERDUE_OPEN.has(inv.status) && inv.due_date && inv.due_date < today) {
        overdueAmt += bal;
        overdueCount += 1;
      }
    }
    return {outstanding, overdueAmt, overdueCount};
  }

  function drawDonut(el, pct) {
    if (!el) return;
    const deg = Math.max(0, Math.min(100, pct || 0)) * 3.6;
    el.style.background = `conic-gradient(#18352b 0deg ${deg}deg, #dfe7e2 ${deg}deg 360deg)`;
  }

  function setAttention(overdueCount, pendingCount) {
    const strip = $(".attention-strip");
    if (!strip) return;
    const total = (overdueCount || 0) + (pendingCount || 0);
    if (total === 0) { strip.style.display = "none"; return; }
    const parts = [];
    if (overdueCount) parts.push(`${overdueCount} overdue invoice${overdueCount === 1 ? "" : "s"}`);
    if (pendingCount) parts.push(`${pendingCount} expense line${pendingCount === 1 ? "" : "s"} awaiting approval`);
    setText("[data-ov-attention-count]", String(total));
    setText("[data-ov-attention-text]", `${cap(parts.join(" and "))}.`);
  }

  // ------------------------------------------------------------------ owner
  function renderOwnerMetrics(projects, portfolio, stats) {
    if (projects) {
      const active = projects.filter(p => p.status === "ACTIVE").length;
      const portfolioValue = projects.reduce((t, p) => t + Number(p.contract_value || 0), 0);
      setMetric("active-projects", String(active));
      setText("[data-ov-active-sub]", `Across ${projects.length} projects`);
      setMetric("portfolio-value", money(portfolioValue));
      setText("[data-ov-portfolio-sub]", `Across ${projects.length} projects`);
    } else {
      setMetric("active-projects", "—");
      setText("[data-ov-active-sub]", "Unavailable");
      setMetric("portfolio-value", "—");
      setText("[data-ov-portfolio-sub]", "Unavailable");
    }
    if (portfolio) {
      const totals = portfolio.totals || {};
      const budgeted = Number(totals.budgeted || 0), actual = Number(totals.actual || 0);
      const spent = budgeted > 0 ? Math.round(actual / budgeted * 100) : 0;
      setMetric("actual-cost", money(actual));
      setText("[data-ov-actual-sub]", `${spent}% of approved budget`);
    } else {
      setMetric("actual-cost", "—");
      setText("[data-ov-actual-sub]", "Unavailable");
    }
    if (stats) {
      setMetric("outstanding-ar", money(stats.outstanding));
      setText("[data-ov-overdue-sub]", `${money(stats.overdueAmt)} currently overdue`);
      setText("[data-ov-ar-status]", stats.overdueAmt > 0 ? "Overdue" : "Current");
    } else {
      setMetric("outstanding-ar", "—");
      setText("[data-ov-overdue-sub]", "Unavailable");
    }
  }

  function renderPortfolio(portfolio) {
    if (!portfolio) return;
    const totals = portfolio.totals || {};
    const budgeted = Number(totals.budgeted || 0), actual = Number(totals.actual || 0);
    const remaining = Number(totals.remaining || 0);
    const spent = budgeted > 0 ? Math.round(actual / budgeted * 100) : 0;
    setText("[data-ov-spent-pct]", `${spent}%`);
    drawDonut($('[data-ov-donut="portfolio"]'), spent);
    setText("[data-ov-approved]", money(budgeted));
    setText("[data-ov-actual]", money(actual));
    setText("[data-ov-remaining]", money(remaining));
    setText("[data-ov-portfolio-note]", `${money(remaining)} budget remaining`);
  }

  function renderMilestones(phases, projects) {
    const host = $("[data-ov-milestones]");
    if (!host) return;
    if (!phases) { host.innerHTML = `<div class="empty-row"><b>Could not load milestones</b><span>The phases API is unavailable.</span></div>`; return; }
    const start = todayStr(), end = addDays(start, 30);
    const nameMap = {};
    (projects || []).forEach(p => { nameMap[p.id] = p.name; });
    const upcoming = phases
      .filter(ph => ph.start_date && ph.start_date >= start && ph.start_date <= end && ["NOT_STARTED", "IN_PROGRESS"].includes(ph.status))
      .sort((a, b) => a.start_date < b.start_date ? -1 : a.start_date > b.start_date ? 1 : 0);
    if (!upcoming.length) { host.innerHTML = `<div class="empty-row"><b>No upcoming milestones</b><span>Nothing scheduled in the next 30 days.</span></div>`; return; }
    host.innerHTML = upcoming.map(ph => `<div class="milestone"><div class="date-chip"><strong>${esc(dayOf(ph.start_date))}</strong><span>${esc(shortMonth(ph.start_date))}</span></div><div><strong>${esc(ph.name)}</strong><span>${esc(nameMap[ph.project_id] || "—")}</span></div></div>`).join("");
  }

  function renderProjectsTable(projects) {
    const body = $("[data-project-rows]");
    if (!body) return;
    if (!projects) { body.innerHTML = `<tr><td colspan="6"><strong>Could not load projects.</strong><span>The projects API is unavailable.</span></td></tr>`; return; }
    body.innerHTML = projects.length
      ? projects.map(p => `<tr><td><a href="/projects/${encodeURIComponent(p.id)}/"><strong>${esc(p.name)}</strong><span>${esc(p.code)}</span></a></td><td><span class="status ${esc(String(p.status).toLowerCase().replaceAll("_", "-"))}"><i></i>${esc(label(p.status))}</span></td><td>${esc(label(p.project_type))}</td><td>${money0(p.contract_value)}</td><td>${esc(p.start_date)}</td><td>${esc(p.expected_completion_date)}</td></tr>`).join("")
      : `<tr><td colspan="6"><strong>No projects found.</strong></td></tr>`;
  }

  async function loadOwner() {
    const results = await Promise.allSettled([
      all("/api/projects/projects/"),
      api("/api/projects/budgets/portfolio-summary/"),
      all("/api/invoicing/client-invoices/"),
      all("/api/projects/phases/"),
    ]);
    const projects = results[0].status === "fulfilled" ? results[0].value : null;
    const portfolio = results[1].status === "fulfilled" ? results[1].value : null;
    const invoices = results[2].status === "fulfilled" ? results[2].value : null;
    const phases = results[3].status === "fulfilled" ? results[3].value : null;
    const stats = invoices ? invoiceStats(invoices, todayStr()) : null;
    renderOwnerMetrics(projects, portfolio, stats);
    renderPortfolio(portfolio);
    renderMilestones(phases, projects);
    renderProjectsTable(projects);
    setAttention(stats ? stats.overdueCount : 0, 0);
  }

  // ------------------------------------------------------------- accountant
  function renderCashDonut(received, outstanding, expenses) {
    const pct = (received + outstanding) > 0 ? Math.round(received / (received + outstanding) * 100) : 0;
    setText("[data-ov-collected-pct]", `${pct}%`);
    drawDonut($('[data-ov-donut="cash"]'), pct);
    setText("[data-ov-received]", money(received));
    setText("[data-ov-cash-outstanding]", money(outstanding));
    setText("[data-ov-cash-expenses]", money(expenses));
    setText("[data-ov-cash-note]", `${pct}% of open receivables collected this month`);
  }

  function renderReceivables(invoices) {
    const host = $("[data-ov-receivables]");
    if (!host) return;
    if (!invoices) { host.innerHTML = `<div class="empty-row"><b>Could not load receivables</b><span>The invoices API is unavailable.</span></div>`; return; }
    const start = todayStr(), end = addDays(start, 30);
    const due = invoices
      .filter(i => !BAD_STATUS.has(i.status) && Number(i.outstanding_balance || 0) > 0 && i.due_date && i.due_date >= start && i.due_date <= end)
      .sort((a, b) => a.due_date < b.due_date ? -1 : a.due_date > b.due_date ? 1 : 0);
    if (!due.length) { host.innerHTML = `<div class="empty-row"><b>No receivables due</b><span>Nothing outstanding in the next 30 days.</span></div>`; return; }
    host.innerHTML = due.map(i => `<div class="milestone"><div class="date-chip"><strong>${esc(dayOf(i.due_date))}</strong><span>${esc(shortMonth(i.due_date))}</span></div><div><strong>${esc(i.invoice_number)}</strong><span>${esc(money(i.outstanding_balance))} · ${esc(i.client_name)}</span></div></div>`).join("");
  }

  function renderRecentReceipts(receipts) {
    const body = $("[data-ov-recent-rows]");
    if (!body) return;
    if (!receipts) { body.innerHTML = `<tr class="empty-row"><td colspan="5"><b>Could not load receipts</b><span>The payments API is unavailable.</span></td></tr>`; return; }
    const latest = receipts.slice().sort((a, b) => a.receipt_date < b.receipt_date ? 1 : -1).slice(0, 5);
    if (!latest.length) { body.innerHTML = `<tr class="empty-row"><td colspan="5"><b>No receipts yet</b><span>Incoming payments appear here once a receipt is issued.</span></td></tr>`; return; }
    body.innerHTML = latest.map(r => `<tr><td><strong>${esc(r.receipt_number)}</strong><span>${esc(r.receipt_date)}</span></td><td>${esc(r.client_name || r.supplier_name || "—")}</td><td>${esc(r.receipt_date)}</td><td>${esc(r.payment_method || "—")}</td><td>${money(r.amount)}</td></tr>`).join("");
  }

  async function loadAccountant() {
    const start = todayStr(), ms = monthStartStr();
    const results = await Promise.allSettled([
      all("/api/invoicing/client-invoices/"),
      all(`/api/payments/payments/?direction=INCOMING&date_from=${ms}&date_to=${start}`),
      all(`/api/expenses/expenses/?date_from=${ms}&date_to=${start}`),
      all("/api/expenses/expenses/?status=PENDING"),
      all("/api/payments/receipts/"),
    ]);
    const invoices = results[0].status === "fulfilled" ? results[0].value : null;
    const payments = results[1].status === "fulfilled" ? results[1].value : null;
    const monthExpenses = results[2].status === "fulfilled" ? results[2].value : null;
    const pending = results[3].status === "fulfilled" ? results[3].value : null;
    const receipts = results[4].status === "fulfilled" ? results[4].value : null;

    const stats = invoices ? invoiceStats(invoices, start) : null;
    const monthInvoices = (invoices || []).filter(i => !BAD_STATUS.has(i.status) && i.invoice_date >= ms && i.invoice_date <= start);
    const invoiced = monthInvoices.reduce((t, i) => t + Number(i.total_amount || 0), 0);
    const received = (payments || []).reduce((t, p) => t + Number(p.amount || 0), 0);
    const spent = (monthExpenses || []).filter(e => ["APPROVED", "PAID"].includes(e.status));
    const expenseTotal = spent.reduce((t, e) => t + Number(e.amount || 0) + Number(e.tax_amount || 0), 0);

    if (invoices) {
      setMetric("invoiced-mtd", money(invoiced));
      setText("[data-ov-invoiced-sub]", `Across ${monthInvoices.length} invoices`);
    } else {
      setMetric("invoiced-mtd", "—");
      setText("[data-ov-invoiced-sub]", "Unavailable");
    }
    if (payments) {
      setMetric("payments-received", money(received));
      setText("[data-ov-payments-sub]", `${payments.length} payments this month`);
    } else {
      setMetric("payments-received", "—");
      setText("[data-ov-payments-sub]", "Unavailable");
    }
    if (stats) {
      setMetric("outstanding-ar", money(stats.outstanding));
      setText("[data-ov-overdue-sub]", `${money(stats.overdueAmt)} currently overdue`);
      setText("[data-ov-ar-status]", stats.overdueAmt > 0 ? "Overdue" : "Current");
    } else {
      setMetric("outstanding-ar", "—");
      setText("[data-ov-overdue-sub]", "Unavailable");
    }
    if (monthExpenses) {
      setMetric("expenses-mtd", money(expenseTotal));
      setText("[data-ov-expenses-sub]", `Across ${spent.length} expense lines`);
    } else {
      setMetric("expenses-mtd", "—");
      setText("[data-ov-expenses-sub]", "Unavailable");
    }

    renderCashDonut(received, stats ? stats.outstanding : 0, expenseTotal);
    renderReceivables(invoices);
    renderRecentReceipts(receipts);
    setAttention(stats ? stats.overdueCount : 0, pending ? pending.length : 0);
  }

  document.addEventListener("DOMContentLoaded", () => {
    if ($('[data-ov-metric="active-projects"]')) loadOwner();
    else if ($('[data-ov-metric="invoiced-mtd"]')) loadAccountant();
  });
})();