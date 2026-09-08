/* Reports / Decision Intelligence page.
   Consumes authenticated DRF endpoints under /api/accounting/, /api/clients/,
   /api/projects/ using the dashboard session (SessionAuthentication + CSRF).
   Read-only: no write operations from this page. */
(() => {
  "use strict";

  const E = {
    profitLoss: "/api/accounting/reports/profit-loss/",
    trend: "/api/accounting/reports/trend/",
    aging: "/api/clients/clients/aging/",
    portfolioBudget: "/api/projects/budgets/portfolio-summary/",
    transactions: "/api/accounting/financial-transactions/",
  };

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (v) => Number(v || 0).toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

  const state = {
    dateFrom: "",
    dateTo: "",
    activePanel: null,
    ledgerPage: 1,
    ledgerNext: null,
    ledgerPrev: null,
    ledgerCount: 0,
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

  function buildParams() {
    const p = new URLSearchParams();
    if (state.dateFrom) p.set("date_from", state.dateFrom);
    if (state.dateTo) p.set("date_to", state.dateTo);
    return p.toString();
  }

  /* ---- Loading states ---- */
  function setLoading(panel, loading) {
    const el = $(`[data-panel="${panel}"]`);
    if (!el) return;
    if (loading) el.classList.add("loading");
    else el.classList.remove("loading");
  }

  function showError(panel, msg) {
    const el = $(`[data-panel="${panel}"]`);
    if (!el) return;
    const existing = el.querySelector(".panel-error");
    if (existing) existing.remove();
    const div = document.createElement("div");
    div.className = "panel-error";
    div.style.cssText = "border-radius:7px;background:#f7d7d1;color:#7f2018;padding:10px;margin-bottom:14px;font-size:11px";
    div.textContent = msg;
    el.querySelector(".panel-head").after(div);
  }

  /* ---- Stat cards ---- */
  function renderStats(plData, agingData, budgetData) {
    const revenue = Number(plData.revenue?.total || 0);
    const expenses = Number(plData.expenses?.total || 0);
    const netProfit = Number(plData.net_profit || 0);
    const receivables = Number(agingData.total_outstanding || 0);
    /* Backend variance = actual − budgeted, so under budget ⇔ variance ≤ 0. */
    const underBudget = (budgetData.projects || []).filter((r) => Number(r.variance) <= 0).length;

    $("[data-metric=revenue]").textContent = money(revenue);
    $("[data-metric=expenses]").textContent = money(expenses);
    $("[data-metric=net_profit]").textContent = money(netProfit);
    $("[data-metric=receivables]").textContent = money(receivables);
    $("[data-metric=under_budget]").textContent = underBudget;
  }

  /* ---- Report card quick values ---- */
  function renderCardValues(plData, agingData, budgetData, ledgerCount) {
    const $v = (sel, val) => { const el = $(sel); if (el) el.textContent = val; };
    $v("[data-card-value=pnl-profit]", money(plData.net_profit || 0));
    $v("[data-card-value=aging-overdue]", money(agingData.total_outstanding || 0));
    const underBudget = (budgetData.projects || []).filter((r) => Number(r.variance) <= 0).length;
    const totalProjects = (budgetData.projects || []).length;
    $v("[data-card-value=budget-variance]", `${underBudget}/${totalProjects}`);
    $v("[data-card-value=ledger-count]", ledgerCount.toLocaleString());
  }

  /* ---- P&L panel ---- */
  function renderPL(data) {
    $("[data-pnl-period]").textContent = data.date_from || data.date_to
      ? `${data.date_from || 'Start'} – ${data.date_to || 'End'}`
      : "Full period";
    $("[data-pnl-revenue]").textContent = money(data.revenue?.total);
    $("[data-pnl-expenses]").textContent = money(data.expenses?.total);
    $("[data-pnl-net]").textContent = money(data.net_profit);

    function renderAccounts(container, accounts) {
      const el = $(container);
      if (!accounts || !accounts.length) { el.innerHTML = '<span style="font-size:11px;color:#607b76">No accounts</span>'; return; }
      el.innerHTML = accounts.map((a) =>
        `<div class="pnl-account-row"><span>${esc(a.code)} ${esc(a.name)}</span><strong>${money(a.amount)}</strong></div>`
      ).join("");
    }
    renderAccounts("[data-pnl-revenue-accounts]", data.revenue?.accounts);
    renderAccounts("[data-pnl-expense-accounts]", data.expenses?.accounts);

    renderPLDonut(data);
  }

  /* ---- P&L donut (SVG): revenue vs expenses = 100%, net in the center ---- */
  function renderPLDonut(data) {
    const revenue = Math.max(Number(data.revenue?.total || 0), 0);
    const expenses = Math.max(Number(data.expenses?.total || 0), 0);
    const net = Number(data.net_profit || 0);
    const hole = $("[data-pnl-donut]");
    const legendEl = $("[data-pnl-donut-legend]");
    if (!hole || !legendEl) return;

    const CX = 100, CY = 100, R = 78, SW = 30, CIRC = 2 * Math.PI * R;
    const total = revenue + expenses;
    const profit = net >= 0;

    if (total <= 0) {
      hole.innerHTML = `<svg viewBox="0 0 200 200" class="donut-svg" role="img" aria-label="No profit and loss data">
        <circle cx="${CX}" cy="${CY}" r="${R}" fill="none" stroke="#dfe8e3" stroke-width="${SW}"/>
        <text x="${CX}" y="96" text-anchor="middle" class="donut-center-value">${money(net)}</text>
        <text x="${CX}" y="114" text-anchor="middle" class="donut-center-empty">No data yet</text>
      </svg>`;
      legendEl.innerHTML = "";
      return;
    }

    const revFrac = revenue / total;
    const expFrac = expenses / total;
    const revLen = revFrac * CIRC;
    const expLen = expFrac * CIRC;

    /* % labels sit on each slice's midpoint; hidden for slivers under 7% */
    const polar = (frac) => {
      const a = (-90 + frac * 360) * (Math.PI / 180);
      return [CX + R * Math.cos(a), CY + R * Math.sin(a)];
    };
    const [rx, ry] = polar(revFrac / 2);
    const [ex, ey] = polar(revFrac + expFrac / 2);
    const pct = (f) => `${Math.round(f * 100)}%`;

    hole.innerHTML = `<svg viewBox="0 0 200 200" class="donut-svg" role="img" aria-label="Revenue ${money(revenue)}, expenses ${money(expenses)}">
      <circle cx="${CX}" cy="${CY}" r="${R}" fill="none" stroke="#eef3f0" stroke-width="${SW}"/>
      <circle cx="${CX}" cy="${CY}" r="${R}" fill="none" stroke="#0a8f85" stroke-width="${SW}"
        stroke-dasharray="${revLen} ${CIRC - revLen}" transform="rotate(-90 ${CX} ${CY})">
        <title>Revenue: ${money(revenue)} (${pct(revFrac)})</title>
      </circle>
      <circle cx="${CX}" cy="${CY}" r="${R}" fill="none" stroke="#c0604a" stroke-width="${SW}"
        stroke-dasharray="${expLen} ${CIRC - expLen}" stroke-dashoffset="${-revLen}" transform="rotate(-90 ${CX} ${CY})">
        <title>Expenses: ${money(expenses)} (${pct(expFrac)})</title>
      </circle>
      ${revFrac >= 0.07 ? `<text x="${rx.toFixed(1)}" y="${(ry + 5).toFixed(1)}" text-anchor="middle" class="donut-slice-pct">${pct(revFrac)}</text>` : ""}
      ${expFrac >= 0.07 ? `<text x="${ex.toFixed(1)}" y="${(ey + 5).toFixed(1)}" text-anchor="middle" class="donut-slice-pct">${pct(expFrac)}</text>` : ""}
      <text x="${CX}" y="96" text-anchor="middle" class="donut-center-value ${profit ? "" : "loss"}">${money(net)}</text>
      <text x="${CX}" y="114" text-anchor="middle" class="donut-center-label">${profit ? "Net profit" : "Net loss"}</text>
    </svg>`;

    const legendItems = [
      { color: "#0a8f85", label: "Revenue", value: money(revenue), share: pct(revFrac) },
      { color: "#c0604a", label: "Expenses", value: money(expenses), share: pct(expFrac) },
    ];
    legendEl.innerHTML = legendItems.map((l) =>
      `<div class="legend-item"><i style="background:${l.color}"></i>${esc(l.label)}<span class="legend-share">${l.share}</span><strong>${l.value}</strong></div>`
    ).join("");
  }

  /* ---- Trend chart: one SVG with gridlines, value labels and net line ----
     Bars start at a true zero (no fake minimum height). If net profit goes
     negative the zero line lifts off the bottom so losses stay visible. */
  function renderTrend(series) {
    const wrap = $("[data-trend-wrap]");
    if (!wrap) return;

    if (!series || !series.length) {
      wrap.innerHTML = '<div class="empty-chart">No trend data available. Post transactions to see monthly trends.</div>';
      $("[data-trend-period]").textContent = "Full period";
      return;
    }

    const months = series.map((r) => r.month);
    $("[data-trend-period]").textContent = months.length > 1
      ? `${months[0]} – ${months[months.length - 1]}`
      : months[0];

    const revs = series.map((r) => Number(r.revenue || 0));
    const exps = series.map((r) => Number(r.expense || 0));
    const nets = series.map((r, i) => revs[i] - exps[i]);

    const W = 680, H = 320, ML = 58, MR = 14, MT = 30, MB = 36;
    const plotW = W - ML - MR, plotH = H - MT - MB;
    const hi = Math.max(...revs, ...exps, ...nets, 1);
    const lo = Math.min(0, ...nets);
    const y = (v) => MT + ((hi - v) / (hi - lo || 1)) * plotH;
    const zeroY = y(0);

    /* Gridlines + y labels */
    const TICKS = 4;
    let grid = "";
    for (let t = 0; t <= TICKS; t++) {
      const v = lo + ((hi - lo) * t) / TICKS;
      const gy = y(v).toFixed(1);
      const isZero = Math.abs(v) < (hi - lo) / TICKS / 2;
      grid += `<line x1="${ML}" y1="${gy}" x2="${W - MR}" y2="${gy}" class="${isZero ? "grid-zero" : "grid-line"}"/>` +
        `<text x="${ML - 8}" y="${(+gy + 4).toFixed(1)}" text-anchor="end" class="axis-label">${shortMoney(v)}</text>`;
    }

    /* Grouped bars with values on top */
    const n = series.length;
    const slot = plotW / n;
    const barW = Math.max(Math.min(26, slot * 0.28), 4);
    const showValues = n <= 12;
    let bars = "";
    series.forEach((r, i) => {
      const cx = ML + slot * i + slot / 2;
      const revX = cx - barW - 2, expX = cx + 2;
      const revY = y(revs[i]), expY = y(exps[i]);
      const revH = Math.max(zeroY - revY, 0), expH = Math.max(zeroY - expY, 0);
      bars += `<g>` +
        `<rect x="${revX.toFixed(1)}" y="${revY.toFixed(1)}" width="${barW.toFixed(1)}" height="${revH.toFixed(1)}" rx="3" class="trend-bar-rev"><title>Revenue ${xLabel(r.month, i, months)}: ${money(revs[i])}</title></rect>` +
        `<rect x="${expX.toFixed(1)}" y="${expY.toFixed(1)}" width="${barW.toFixed(1)}" height="${expH.toFixed(1)}" rx="3" class="trend-bar-exp"><title>Expense ${xLabel(r.month, i, months)}: ${money(exps[i])}</title></rect>`;
      if (showValues) {
        bars += `<text x="${(revX + barW / 2).toFixed(1)}" y="${Math.max(revY - 5, MT - 14).toFixed(1)}" text-anchor="middle" class="bar-value">${shortMoney(revs[i])}</text>` +
          `<text x="${(expX + barW / 2).toFixed(1)}" y="${Math.max(expY - 5, MT - 14).toFixed(1)}" text-anchor="middle" class="bar-value bar-value-exp">${shortMoney(exps[i])}</text>`;
      }
      bars += `<text x="${cx.toFixed(1)}" y="${H - 12}" text-anchor="middle" class="axis-label">${xLabel(r.month, i, months)}</text></g>`;
    });

    /* Net profit line with dots */
    const pts = series.map((r, i) => {
      const cx = ML + slot * i + slot / 2;
      return `${cx.toFixed(1)},${y(nets[i]).toFixed(1)}`;
    });
    const dots = series.map((r, i) => {
      const cx = ML + slot * i + slot / 2;
      return `<circle cx="${cx.toFixed(1)}" cy="${y(nets[i]).toFixed(1)}" r="3.5" class="trend-net-dot"><title>Net ${xLabel(r.month, i, months)}: ${money(nets[i])}</title></circle>`;
    }).join("");

    wrap.innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="trend-svg" role="img" aria-label="Monthly revenue and expense trend">` +
      grid +
      `<line x1="${ML}" y1="${zeroY.toFixed(1)}" x2="${W - MR}" y2="${zeroY.toFixed(1)}" class="grid-zero"/>` +
      bars +
      `<polyline points="${pts.join(" ")}" fill="none" class="trend-net-line"/>` +
      dots +
      `</svg>`;
  }

  /* X label: "Mar", plus the year on the first month and when it changes. */
  function xLabel(month, i, months) {
    const base = monthLabel(month);
    const year = String(month || "").slice(0, 4);
    const prevYear = i > 0 ? String(months[i - 1] || "").slice(0, 4) : "";
    return (i === 0 || (year && year !== prevYear)) && year ? `${base} ’${year.slice(2)}` : base;
  }

  function shortMoney(v) {
    const n = Math.abs(Number(v || 0));
    if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
    if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}k`;
    return `$${n.toFixed(0)}`;
  }

  function monthLabel(month) {
    const [y, m] = String(month || "").split("-");
    const names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return names[Number(m) - 1] || "";
  }

  /* ---- Aging panel — pure charts (no table) ---- */
  function renderAging(data) {
    $("[data-aging-as-of]").textContent = `As of ${data.as_of || "today"}`;
    const buckets = data.buckets || [];
    const bucketEls = $$("[data-aging-buckets] .aging-bucket");
    buckets.forEach((b, i) => {
      if (bucketEls[i]) {
        bucketEls[i].querySelector("strong").textContent = money(b.total);
      }
    });
    renderAgingChart(buckets);
    renderAgingDonut(buckets);
  }

  /* Aging bars: money on top of every bar, 4 distinct colors, no table fallback */
  function renderAgingChart(buckets) {
    const container = $("[data-aging-chart]");
    if (!container) return;
    if (!buckets || !buckets.length || buckets.every((b) => Number(b.total || 0) === 0)) {
      container.innerHTML = '<div class="empty-chart">No outstanding invoices — all caught up.</div>';
      return;
    }
    const maxTotal = Math.max(...buckets.map((b) => Number(b.total || 0)), 1);
    const fallback = ["Current (0–30)", "31–60 days", "61–90 days", "90+ days"];
    container.innerHTML = buckets.map((b, i) => {
      const total = Number(b.total || 0);
      const h = total > 0 ? Math.max((total / maxTotal) * 100, 6) : 0;
      const label = b.label || fallback[i] || `Bucket ${i + 1}`;
      return `<div class="aging-barchart-cat"><b class="aging-val">${money(total)}</b>` +
        `<span class="aging-bar ab-${Math.min(i, 3)}" style="height:${h}%" title="${esc(label)}: ${money(total)}"></span>` +
        `<span class="aging-bar-cat-label">${esc(label)}</span></div>`;
    }).join("");
  }

  /* Aging donut pie: share of outstanding per bucket — quick overdue insight */
  function renderAgingDonut(buckets) {
    const hole = $("[data-aging-donut]");
    const legendEl = $("[data-aging-donut-legend]");
    if (!hole || !legendEl) return;
    const totals = buckets.map((b) => Math.max(Number(b.total || 0), 0));
    const grand = totals.reduce((a, b) => a + b, 0);
    const labels = buckets.map((b, i) => b.label || ["Current (0–30)", "31–60", "61–90", "90+"][i] || `Bucket ${i + 1}`);
    const colors = ["#0a8f85", "#d9a03f", "#e4907a", "#a23a31"];
    if (grand <= 0) {
      hole.innerHTML = `<svg viewBox="0 0 200 200" class="donut-svg" role="img" aria-label="No outstanding receivables"><circle cx="100" cy="100" r="70" fill="none" stroke="#dfe8e3" stroke-width="28"/><text x="100" y="96" text-anchor="middle" class="donut-center-value">$0.00</text><text x="100" y="114" text-anchor="middle" class="donut-center-empty">All clear</text></svg>`;
      legendEl.innerHTML = "";
      return;
    }
    const CIRC = 2 * Math.PI * 70;
    let offset = 0;
    let slices = `<circle cx="100" cy="100" r="70" fill="none" stroke="#eef3f0" stroke-width="28"/>`;
    totals.forEach((v, i) => {
      if (v <= 0) return;
      const len = (v / grand) * CIRC;
      slices += `<circle cx="100" cy="100" r="70" fill="none" stroke="${colors[i % colors.length]}" stroke-width="28" stroke-dasharray="${len} ${CIRC - len}" stroke-dashoffset="${-offset}" transform="rotate(-90 100 100)"><title>${esc(labels[i])}: ${money(v)} (${Math.round((v / grand) * 100)}%)</title></circle>`;
      offset += len;
    });
    const pct = (v) => `${Math.round((v / grand) * 100)}%`;
    hole.innerHTML = `<svg viewBox="0 0 200 200" class="donut-svg" role="img" aria-label="Receivables aging distribution">${slices}<text x="100" y="96" text-anchor="middle" class="donut-center-value">${money(grand)}</text><text x="100" y="114" text-anchor="middle" class="donut-center-label">Outstanding</text></svg>`;
    legendEl.innerHTML = buckets.map((b, i) => {
      const v = totals[i];
      return `<div class="legend-item"><i style="background:${colors[i % colors.length]}"></i>${esc(labels[i])}<span class="legend-share">${pct(v)}</span><strong>${money(v)}</strong></div>`;
    }).join("");
  }

  /* ---- Budget panel — pure chart (no table) ---- */
  function renderBudget(data) {
    const rows = data.projects || [];
    const totals = data.totals || {};
    const setT = (sel, val) => { const el = $(sel); if (el) el.textContent = money(val); };
    setT("[data-budget-total-budgeted]", totals.budgeted);
    setT("[data-budget-total-actual]", totals.actual);
    setT("[data-budget-total-variance]", totals.variance);
    setT("[data-budget-total-remaining]", totals.remaining);
    renderBudgetChart(rows);
  }

  /* ---- Budget bars: each track is 100% of that project's budget, the fill
     is actual spend, and the head chip reads "NN% used" or "Over by $X". ---- */
  function renderBudgetChart(rows) {
    const container = $("[data-budget-chart]");
    if (!container) return;
    if (!rows.length) {
      container.innerHTML = '<div class="empty-chart">No projects with active budgets — set a budget on a project to see it here.</div>';
      return;
    }
    container.innerHTML = rows.map((r) => {
      const budgeted = Number(r.budgeted || 0);
      const actual = Number(r.actual || 0);
      const variance = Number(r.variance || 0);
      const pct = budgeted > 0 ? (actual / budgeted) * 100 : (actual > 0 ? 100 : 0);
      /* Backend defines variance = actual − budgeted, so over ⇔ variance > 0. */
      const over = variance > 0;
      const fillW = Math.min(Math.max(pct, 0), 100);
      const chip = over
        ? `<span class="bc-chip over">Over by ${money(Math.abs(variance))}</span>`
        : `<span class="bc-chip under">${Math.round(pct)}% used</span>`;
      return `<div class="budget-chart-row">
        <div class="bc-head"><span>${esc(r.project_name)} <small>(${esc(r.project_code)})</small></span>${chip}</div>
        <div class="bc-track" title="Budgeted ${money(budgeted)} · Actual ${money(actual)}"><span class="bc-actual ${over ? "over" : "under"}" style="width:${fillW}%"></span></div>
        <div class="bc-legend-line"><span>Budgeted ${money(budgeted)}</span><span>Actual ${money(actual)}</span><span>Remaining ${money(r.remaining)}</span></div>
      </div>`;
    }).join("");
  }

  /* ---- Ledger panel — charts only (no table) ---- */
  async function loadLedger(page = 1) {
    state.ledgerPage = page;
    const p = new URLSearchParams();
    p.set("page", page);
    if (state.dateFrom) p.set("transaction_date_after", state.dateFrom);
    if (state.dateTo) p.set("transaction_date_before", state.dateTo);
    p.set("status", "POSTED");
    p.set("ordering", "-transaction_date");

    try {
      const data = await api(`${E.transactions}?${p}`);
      const rows = data.results || [];
      state.ledgerNext = data.next;
      state.ledgerPrev = data.previous;
      state.ledgerCount = data.count || 0;

      let pageDebit = 0, pageCredit = 0;
      rows.forEach((t) => { pageDebit += Number(t.total_debit || 0); pageCredit += Number(t.total_credit || 0); });

      const debitEl = $("[data-ledger-total-debit]");
      const creditEl = $("[data-ledger-total-credit]");
      if (debitEl) debitEl.textContent = money(pageDebit);
      if (creditEl) creditEl.textContent = money(pageCredit);
      const cntEl = $("[data-ledger-count]");
      if (cntEl) cntEl.textContent = String(state.ledgerCount);

      renderLedgerDonut(pageDebit, pageCredit);
      renderLedgerBars(rows);

      const info = $("[data-ledger-page-info]");
      if (info) info.textContent = `Page ${state.ledgerPage} · ${rows.length} transactions`;
      const prevBtn = $("[data-ledger-prev]");
      const nextBtn = $("[data-ledger-next]");
      if (prevBtn) prevBtn.disabled = !state.ledgerPrev;
      if (nextBtn) nextBtn.disabled = !state.ledgerNext;
    } catch (err) {
      showError("ledger", err.message);
    }
  }

  function renderLedgerDonut(debit, credit) {
    const hole = $("[data-ledger-donut]");
    const legendEl = $("[data-ledger-donut-legend]");
    if (!hole || !legendEl) return;
    const total = debit + credit;
    if (total <= 0) {
      hole.innerHTML = `<svg viewBox="0 0 200 200" class="donut-svg" role="img" aria-label="No ledger totals"><circle cx="100" cy="100" r="70" fill="none" stroke="#dfe8e3" stroke-width="28"/><text x="100" y="96" text-anchor="middle" class="donut-center-value">$0.00</text><text x="100" y="114" text-anchor="middle" class="donut-center-empty">No data</text></svg>`;
      legendEl.innerHTML = "";
      return;
    }
    const CIRC = 2 * Math.PI * 70;
    const dLen = (debit / total) * CIRC, cLen = (credit / total) * CIRC;
    const pct = (v) => `${Math.round((v / total) * 100)}%`;
    // polar mid-points for % labels
    const mid = (frac) => { const a = (-90 + frac * 360) * Math.PI / 180; return [100 + 70 * Math.cos(a), 100 + 70 * Math.sin(a)]; };
    const [dx, dy] = mid((debit / total) / 2);
    const [cx, cy] = mid((debit / total) + (credit / total) / 2);
    hole.innerHTML = `<svg viewBox="0 0 200 200" class="donut-svg" role="img" aria-label="Debit ${money(debit)}, credit ${money(credit)}">` +
      `<circle cx="100" cy="100" r="70" fill="none" stroke="#eef3f0" stroke-width="28"/>` +
      `<circle cx="100" cy="100" r="70" fill="none" stroke="#0a8f85" stroke-width="28" stroke-dasharray="${dLen} ${CIRC - dLen}" transform="rotate(-90 100 100)"><title>Debit ${money(debit)} (${pct(debit)})</title></circle>` +
      `<circle cx="100" cy="100" r="70" fill="none" stroke="#d9a03f" stroke-width="28" stroke-dasharray="${cLen} ${CIRC - cLen}" stroke-dashoffset="${-dLen}" transform="rotate(-90 100 100)"><title>Credit ${money(credit)} (${pct(credit)})</title></circle>` +
      `${(debit / total) >= 0.07 ? `<text x="${dx.toFixed(1)}" y="${(dy + 4).toFixed(1)}" text-anchor="middle" class="donut-slice-pct">${pct(debit)}</text>` : ""}` +
      `${(credit / total) >= 0.07 ? `<text x="${cx.toFixed(1)}" y="${(cy + 4).toFixed(1)}" text-anchor="middle" class="donut-slice-pct">${pct(credit)}</text>` : ""}` +
      `<text x="100" y="96" text-anchor="middle" class="donut-center-value">${money(total)}</text><text x="100" y="114" text-anchor="middle" class="donut-center-label">Page total</text></svg>`;
    legendEl.innerHTML = [
      { color: "#0a8f85", label: "Debit", value: money(debit), share: pct(debit) },
      { color: "#d9a03f", label: "Credit", value: money(credit), share: pct(credit) },
    ].map((l) => `<div class="legend-item"><i style="background:${l.color}"></i>${esc(l.label)}<span class="legend-share">${l.share}</span><strong>${l.value}</strong></div>`).join("");
  }

  function renderLedgerBars(rows) {
    const wrap = $("[data-ledger-bars]");
    if (!wrap) return;
    if (!rows || !rows.length) {
      wrap.innerHTML = '<div class="empty-chart">No posted transactions for this page.</div>';
      return;
    }
    const maxVal = Math.max(...rows.flatMap((r) => [Number(r.total_debit || 0), Number(r.total_credit || 0)]), 1);
    wrap.innerHTML = `<div class="ledger-bars-head"><span>Grouped debit (teal) vs credit (amber) per transaction — hover for details</span></div>` +
      rows.map((t) => {
        const d = Number(t.total_debit || 0), c = Number(t.total_credit || 0);
        const dW = maxVal > 0 ? (d / maxVal) * 100 : 0;
        const cW = maxVal > 0 ? (c / maxVal) * 100 : 0;
        const label = esc(t.transaction_number || t.id || "—");
        const date = esc(t.transaction_date || "");
        const proj = esc(t.project_name || "—");
        return `<div class="ledger-bar-row">` +
          `<div class="lb-label"><b>${label}</b><small>${date} · ${proj}</small></div>` +
          `<div class="lb-tracks">` +
          `<div class="lb-track"><span class="lb-fill lb-debit" style="width:${dW.toFixed(1)}%" title="Debit: ${money(d)}"></span><em>${d > 0 ? money(d) : "—"}</em></div>` +
          `<div class="lb-track"><span class="lb-fill lb-credit" style="width:${cW.toFixed(1)}%" title="Credit: ${money(c)}"></span><em>${c > 0 ? money(c) : "—"}</em></div>` +
          `</div></div>`;
      }).join("");
  }

  /* ---- Panel navigation ---- */
  function openPanel(name) {
    if (state.activePanel === name) {
      $$("[data-panel]").forEach((el) => el.hidden = true);
      state.activePanel = null;
      return;
    }
    $$("[data-panel]").forEach((el) => el.hidden = true);
    const panel = $(`[data-panel="${name}"]`);
    if (panel) {
      panel.hidden = false;
      requestAnimationFrame(() => {
        const top = panel.getBoundingClientRect().top + window.pageYOffset - 70;
        window.scrollTo({ top, behavior: "smooth" });
      });
    }
    state.activePanel = name;
  }

  /* ---- Full load ---- */
  async function loadAll() {
    const params = buildParams();
    try {
      const [plData, agingData, budgetData] = await Promise.all([
        api(`${E.profitLoss}?${params}`),
        api(E.aging),
        api(E.portfolioBudget),
      ]);

      renderStats(plData, agingData, budgetData);
      renderCardValues(plData, agingData, budgetData, state.ledgerCount);

      renderPL(plData);

      const trendData = await api(`${E.trend}?${params}`);
      renderTrend(trendData);
      $("[data-card-value=trend-months]").textContent = `${trendData.length} month${trendData.length !== 1 ? "s" : ""}`;

      renderAging(agingData);
      renderBudget(budgetData);
      await loadLedger(state.ledgerPage);
    } catch (err) {
      console.error("Reports load error:", err);
    }
  }

  /* ---- Init ---- */
  function init() {
    /* Report card navigation */
    $$(".report-card[data-report-nav]").forEach((card) => {
      card.addEventListener("click", (e) => {
        if (e.target.tagName === "BUTTON" && e.target.disabled) return;
        openPanel(card.dataset.reportNav);
      });
    });

    /* Date filter changes */
    $("[data-date-from]").addEventListener("change", (e) => {
      state.dateFrom = e.target.value;
      loadAll();
    });
    $("[data-date-to]").addEventListener("change", (e) => {
      state.dateTo = e.target.value;
      loadAll();
    });

    /* Ledger pagination */
    $("[data-ledger-prev]").addEventListener("click", () => { if (state.ledgerPrev) loadLedger(state.ledgerPage - 1); });
    $("[data-ledger-next]").addEventListener("click", () => { if (state.ledgerNext) loadLedger(state.ledgerPage + 1); });

    loadAll();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
