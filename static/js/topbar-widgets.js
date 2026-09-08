/* Topbar widgets (CPMAS-58): notifications bell + global search overlay.
   Loaded on every dashboard page (see base_dashboard.html) since the
   topbar itself is a shared partial. Talks to the DRF API using the
   authenticated dashboard session (SessionAuthentication + CSRF),
   same pattern as suppliers.js. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

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
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json();
  }

  /* ---------------------------------------------------------------- */
  /* Notifications                                                    */
  /* ---------------------------------------------------------------- */

  function initNotifications() {
    const topbar = $(".topbar");
    const userId = topbar?.dataset.appUserId;
    const widget = $("[data-notif-widget]");
    const toggle = $("[data-notif-toggle]");
    const dropdown = $("[data-notif-dropdown]");
    const badge = $("[data-notif-badge]");
    const list = $("[data-notif-list]");
    const markAllBtn = $("[data-notif-mark-all]");
    if (!widget || !toggle || !dropdown) return;

    // No bridged users.User for this dashboard session yet (see
    // construction/context_processors.py) -- degrade quietly rather
    // than firing requests with no way to scope them.
    if (!userId) {
      dropdown.addEventListener("click", (e) => e.stopPropagation());
      toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        list.innerHTML = `<p class="notif-empty">No linked account for notifications yet.</p>`;
        dropdown.hidden = !dropdown.hidden;
      });
      return;
    }

    const NOTIF_API = "/api/notifications/notifications/";

    function timeAgo(iso) {
      const diffMs = Date.now() - new Date(iso).getTime();
      const minutes = Math.max(0, Math.round(diffMs / 60000));
      if (minutes < 1) return "just now";
      if (minutes < 60) return `${minutes}m ago`;
      const hours = Math.round(minutes / 60);
      if (hours < 24) return `${hours}h ago`;
      return `${Math.round(hours / 24)}d ago`;
    }

    function renderList(notifications) {
      if (!notifications.length) {
        list.innerHTML = `<p class="notif-empty">You're all caught up.</p>`;
        return;
      }
      list.innerHTML = notifications.map((n) => `
        <button type="button" class="notif-item ${n.is_read ? "" : "is-unread"}" data-notif-id="${n.id}">
          <b>${esc(n.title)}</b>
          <span>${esc(n.message)}</span>
          <time>${timeAgo(n.created_at)}</time>
        </button>`).join("");

      $$("[data-notif-id]", list).forEach((btn) => {
        btn.addEventListener("click", async () => {
          try {
            await api(`${NOTIF_API}${btn.dataset.notifId}/mark_read/`, { method: "POST" });
            btn.classList.remove("is-unread");
            refreshBadge();
          } catch (e) { /* leave as-is on failure */ }
        });
      });
    }

    async function loadList() {
      list.innerHTML = `<p class="notif-empty">LoadingΓÇª</p>`;
      try {
        const data = await api(`${NOTIF_API}?user=${userId}&ordering=-created_at`);
        renderList((data.results || []).slice(0, 20));
      } catch (e) {
        list.innerHTML = `<p class="notif-empty">Could not load notifications.</p>`;
      }
    }

    async function refreshBadge() {
      try {
        const data = await api(`${NOTIF_API}?user=${userId}&is_read=false`);
        const count = data.count ?? 0;
        if (count > 0) {
          badge.hidden = false;
          badge.textContent = count > 99 ? "99+" : String(count);
        } else {
          badge.hidden = true;
        }
      } catch (e) { /* leave badge as-is */ }
    }

    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      const opening = dropdown.hidden;
      dropdown.hidden = !dropdown.hidden;
      if (opening) {
        loadList();
        // Opening notifications closes the account dropdown.
        const userMenuList = document.querySelector("[data-user-menu-list]");
        if (userMenuList) userMenuList.hidden = true;
        const userMenuBtn = document.querySelector("[data-user-menu-toggle]");
        if (userMenuBtn) {
          userMenuBtn.classList.remove("open");
          userMenuBtn.setAttribute("aria-expanded", "false");
        }
      }
    });
    document.addEventListener("click", () => { dropdown.hidden = true; });
    dropdown.addEventListener("click", (e) => e.stopPropagation());

    markAllBtn?.addEventListener("click", async (e) => {
      e.stopPropagation();
      try {
        await api(`${NOTIF_API}mark_all_read/?user=${userId}`, { method: "POST" });
        await loadList();
        await refreshBadge();
      } catch (err) { /* ignore */ }
    });

    refreshBadge();
  }

  /* ---------------------------------------------------------------- */
  /* Global search                                                    */
  /* ---------------------------------------------------------------- */

  function initSearch() {
    const input = $("[data-search-input]");
    const results = $("[data-search-results]");
    if (!input || !results) return;

    const SOURCES = [
      { label: "Projects", url: "/api/projects/projects/", render: (r) => ({ title: r.name, sub: r.code, href: `/projects/${r.id}/` }) },
      { label: "Clients", url: "/api/clients/clients/", render: (r) => ({ title: r.name, sub: r.company_name || r.email || "" }) },
      { label: "Suppliers", url: "/api/suppliers/suppliers/", render: (r) => ({ title: r.name, sub: r.company_name || r.email || "" }) },
      { label: "Client invoices", url: "/api/invoicing/client-invoices/", render: (r) => ({ title: r.invoice_number, sub: `${r.client_name || ""} ┬╖ ${r.status}` }) },
      { label: "Supplier invoices", url: "/api/invoicing/supplier-invoices/", render: (r) => ({ title: r.invoice_number, sub: `${r.supplier_name || ""} ┬╖ ${r.status}` }) },
      { label: "Materials", url: "/api/inventory/materials/", render: (r) => ({ title: r.name, sub: r.sku }) },
      { label: "Tax rates", url: "/api/taxes/tax-rates/", render: (r) => ({ title: r.name, sub: `${r.tax_type} ┬╖ ${r.rate}%` }) },
    ];

    let requestToken = 0;

    function showResults(html) { results.innerHTML = html; results.hidden = false; }
    function hideResults() { results.hidden = true; }

    input.addEventListener("focus", () => {
      if (input.value.trim()) { /* keep results if already searching */ }
      else showResults(`<p class="search-empty">Start typing to search across the workspace.</p>`);
    });
    input.addEventListener("blur", () => {
      // Allow click-through of result links before hiding.
      setTimeout(hideResults, 150);
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".global-search")) hideResults();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { input.blur(); hideResults(); }
    });

    let debounceTimer;
    input.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      const q = input.value.trim();
      if (!q) {
        hideResults();
        return;
      }
      showResults(`<p class="search-empty">SearchingΓÇª</p>`);
      debounceTimer = setTimeout(() => runSearch(q), 250);
    });

    async function runSearch(query) {
      const token = ++requestToken;
      const groups = await Promise.all(SOURCES.map(async (source) => {
        try {
          const data = await api(`${source.url}?search=${encodeURIComponent(query)}`);
          return { label: source.label, rows: (data.results || []).slice(0, 5).map(source.render) };
        } catch (e) {
          return { label: source.label, rows: [] };
        }
      }));

      if (token !== requestToken) return; // a newer keystroke superseded this search

      const nonEmpty = groups.filter((g) => g.rows.length);
      if (!nonEmpty.length) {
        showResults(`<p class="search-empty">No matches for "${esc(query)}".</p>`);
        return;
      }

      showResults(nonEmpty.map((g) => `
        <div class="search-group-label">${esc(g.label)}</div>
        ${g.rows.map((r) => r.href
          ? `<a class="search-result" href="${r.href}"><b>${esc(r.title)}</b><span>${esc(r.sub)}</span></a>`
          : `<div class="search-result"><b>${esc(r.title)}</b><span>${esc(r.sub)}</span></div>`
        ).join("")}
      `).join(""));
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    initNotifications();
    initSearch();
  });
})();
