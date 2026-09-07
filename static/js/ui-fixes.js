// ui-fixes — global unification for dropdowns & calendars
// Reference: company_settings fancySelect + audit trail buildCal
// Runs on every dashboard page; upgrades all native <select> and <input type=date>
// to the same look + calendar icon as /settings → Audit trail.
(function () {
  "use strict";

  // ----- helpers -----
  function svgChevron() {
    var s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("width","12"); s.setAttribute("height","12");
    s.setAttribute("fill","none"); s.setAttribute("stroke","currentColor");
    s.setAttribute("stroke-width","2.5"); s.setAttribute("stroke-linecap","round"); s.setAttribute("stroke-linejoin","round");
    s.innerHTML = '<polyline points="6 9 12 15 18 9"></polyline>';
    return s;
  }
  function svgCheck() {
    var s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox","0 0 24 24"); s.setAttribute("width","12"); s.setAttribute("height","12");
    s.setAttribute("fill","none"); s.setAttribute("stroke","currentColor");
    s.setAttribute("stroke-width","2.5"); s.setAttribute("stroke-linecap","round"); s.setAttribute("stroke-linejoin","round");
    s.innerHTML = '<polyline points="20 6 9 17 4 12"></polyline>';
    return s;
  }
  function svgCalendar() {
    // exact audit icon: rect + 2 vertical lines + horizontal line — stroke 2
    var s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox","0 0 24 24"); s.setAttribute("width","14"); s.setAttribute("height","14");
    s.setAttribute("fill","none"); s.setAttribute("stroke","currentColor");
    s.setAttribute("stroke-width","2"); s.setAttribute("stroke-linecap","round"); s.setAttribute("stroke-linejoin","round");
    s.setAttribute("aria-hidden","true");
    s.innerHTML = '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>'
      + '<line x1="16" y1="2" x2="16" y2="6"></line>'
      + '<line x1="8" y1="2" x2="8" y2="6"></line>'
      + '<line x1="3" y1="10" x2="21" y2="10"></line>';
    return s;
  }

  // ----- DROPDOWN: fancySelect for every native <select> not already upgraded -----
  function isAlreadyFancy(select) {
    return select.classList.contains("users-select-native") || select.classList.contains("ui-fancy-native")
      || (select.parentElement && select.parentElement.classList.contains("users-select"))
      || (select.parentElement && select.parentElement.classList.contains("ui-fancy-wrap"));
  }
  function shouldEnhanceSelect(select) {
    if (isAlreadyFancy(select)) return false;
    // financial/taxes/users modals already use company_settings fancySelect — don't double-wrap
    if (select.closest("[data-fin-modal]") || select.closest("[data-taxes-modal]") || select.closest("[data-users-modal]")) return false;
    return true;
  }

  // global registry so opening one closes others (matches audit trail behavior + user request)
  var _openPops = [];
  var _openCals = [];
  function closeAllPops(except) {
    _openPops.slice().forEach(function (info) {
      if (info === except) return;
      if (!info.pop.hidden) { info.pop.hidden = true; info.btn.classList.remove("is-open"); info.btn.setAttribute("aria-expanded","false"); }
    });
  }
  function closeAllCals(except) {
    _openCals.slice().forEach(function (info) {
      if (info === except) return;
      if (!info.cal.hidden) { info.cal.hidden = true; }
    });
  }
  function closeAllUi() { closeAllPops(null); closeAllCals(null); }

  function enhanceSelect(select) {
    if (!shouldEnhanceSelect(select)) return;
    var chevron = svgChevron();
    var check = svgCheck();

    var wrap = document.createElement("span");
    wrap.className = "ui-fancy-wrap";
    var btn = document.createElement("button");
    btn.type = "button"; btn.className = "ui-fancy-btn";
    btn.setAttribute("aria-haspopup","listbox"); btn.setAttribute("aria-expanded","false");
    var label = document.createElement("span"); label.className = "ui-fancy-label";
    var chevronWrap = document.createElement("span"); chevronWrap.appendChild(chevron.cloneNode(true));
    btn.appendChild(label); btn.appendChild(chevronWrap);
    var pop = document.createElement("div");
    pop.className = "ui-fancy-pop"; pop.setAttribute("role","listbox"); pop.hidden = true;
    // keep pop as child of wrap initially so fixed positioning works even inside <dialog> top layer;
    // do NOT move to body on open — keep inside the same stacking context (dialog top layer vs body)
    wrap.appendChild(btn); wrap.appendChild(pop);
    select.classList.add("ui-fancy-native");
    // guard: parentNode may be null if select is inside a detached template
    if (!select.parentNode) return;
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);

    function render() {
      pop.innerHTML = "";
      Array.prototype.forEach.call(select.options, function (o) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "ui-fancy-opt" + (o.selected ? " is-active" : "");
        b.setAttribute("data-value", o.value);
        b.setAttribute("role","option");
        b.setAttribute("aria-selected", o.selected ? "true" : "false");
        b.appendChild(check.cloneNode(true));
        b.appendChild(document.createTextNode(o.text));
        pop.appendChild(b);
      });
    }
    function sync() {
      var o = select.options[select.selectedIndex];
      label.textContent = o ? o.text : (select.options[0] ? select.options[0].text : "");
      if (pop.hidden) render();
      btn.setAttribute("aria-expanded", pop.hidden ? "false" : "true");
    }
    function openPop() {
      closeAllPops(null); closeAllCals(null);
      render();
      pop.hidden = false; btn.classList.add("is-open");
      btn.setAttribute("aria-expanded","true");
      // keep pop in top-layer when inside <dialog> so fixed is not clipped by overflow:auto
      var host = select.closest("dialog");
      if (host) {
        if (pop.parentElement !== host) host.appendChild(pop);
      } else {
        if (pop.parentElement !== document.body) document.body.appendChild(pop);
      }
      var r = btn.getBoundingClientRect();
      var w = pop.offsetWidth || 170; var h = pop.offsetHeight || 120;
      var left = Math.min(r.left, Math.max(8, window.innerWidth - w - 8));
      var openUp = (window.innerHeight - r.bottom - 8) < h && r.top > h;
      var top = openUp ? r.top - h - 4 : r.bottom + 4;
      top = Math.max(8, Math.min(top, window.innerHeight - h - 8));
      pop.style.left = left + "px"; pop.style.top = top + "px";
      pop.style.right = ""; pop.style.bottom = "";
      pop._anchor = btn;
    }
    function closePop() {
      if (pop.hidden) return;
      pop.hidden = true; btn.classList.remove("is-open");
      btn.setAttribute("aria-expanded","false");
    }
    btn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      if (pop.hidden) openPop(); else closePop();
    });
    pop.addEventListener("click", function (ev) {
      var opt = ev.target.closest ? ev.target.closest(".ui-fancy-opt") : null;
      if (!opt) return;
      select.value = opt.getAttribute("data-value");
      select.dispatchEvent(new Event("change", { bubbles: true }));
      sync(); closePop();
    });
    // global outside-click + Esc handled centrally below, but keep per-instance for fallback
    // keep label in sync when JS populates options later (accounting/invoices fetch)
    select.addEventListener("change", sync);
    var mo = new MutationObserver(function () { sync(); });
    mo.observe(select, { childList: true, subtree: true, characterData: true, attributes: true });
    // poll until options appear — accounting accounts/projects load async after dialog open
    var pollCount = 0;
    var poll = setInterval(function () {
      pollCount++;
      var curLen = select.options.length;
      if (curLen !== select._uiLastLen) { select._uiLastLen = curLen; sync(); }
      else if (curLen <= 1 && pollCount < 60) { /* keep polling while only placeholder */ sync(); }
      if (pollCount > 60) clearInterval(poll); // 30s
      if (curLen > 1) clearInterval(poll);
    }, 500);
    select._uiLastLen = select.options.length;
    window.addEventListener("scroll", function () { if (!pop.hidden) openPop(); }, true);
    window.addEventListener("resize", function () { if (!pop.hidden) openPop(); });

    sync();
    _openPops.push({pop:pop, btn:btn, wrap:wrap});
  }

  // global outside-click / Esc for all dropdowns — exclude audit entity menu (company_settings has its own handler)
  document.addEventListener("click", function (ev) {
    if (ev.target.closest && (ev.target.closest("[data-audit-entity-wrap]") || ev.target.closest("[data-audit-entity-menu]"))) return;
    _openPops.forEach(function (info) {
      if (info.pop.hidden) return;
      if (info.wrap.contains(ev.target) || info.pop.contains(ev.target)) return;
      info.pop.hidden = true; info.btn.classList.remove("is-open"); info.btn.setAttribute("aria-expanded","false");
    });
    _openCals.forEach(function (info) {
      if (info.cal.hidden) return;
      if (info.wrap && info.wrap.contains(ev.target)) return;
      if (info.cal.contains(ev.target)) return;
      if (info.btn && info.btn.contains(ev.target)) return;
      if (info.inp && info.inp.contains(ev.target)) return;
      info.cal.hidden = true;
    });
  });
  // fallback for audit entity dropdown — capture phase, always handles toggle (company_settings handler was not firing)
  document.addEventListener("click", function (ev) {
    var t = ev.target.closest ? ev.target.closest("[data-audit-entity-toggle]") : null;
    if (!t) return;
    ev.stopPropagation();
    ev.preventDefault();
    var menu = document.querySelector("[data-audit-entity-menu]");
    var cats = document.querySelector("[data-audit-entity-cats]");
    if (!menu || !t) return;
    // if company_settings already populated categories, keep them; otherwise build fallback from known 16 types
    if (cats && !cats.innerHTML.trim()) {
      var fallback = [
        {cat:"Access & settings", items:[["user","User"],["company_profile","Company profile"],["tax_rate","Tax rate"]]},
        {cat:"Projects", items:[["project","Project"]]},
        {cat:"People", items:[["employee","Employee"]]},
        {cat:"Partners", items:[["client","Client"],["supplier","Supplier"],["contractor","Contractor"]]},
        {cat:"Operations", items:[["purchase_order","Purchase order"],["goods_receipt","Goods receipt"],["material","Material"]]},
        {cat:"Money", items:[["supplier_invoice","Supplier invoice"],["client_invoice","Client invoice"],["expense","Expense"],["payment","Payment"],["receipt","Receipt"]]}
      ];
      cats.innerHTML = '<button type="button" class="users-audit-entity-catsel is-active" data-audit-entity-all>All entities</button>'
        + fallback.map(function(g){ return '<button type="button" class="users-audit-entity-cat" data-audit-entity-cat="'+g.cat+'">'+g.cat+'</button>'; }).join("");
    }
    var isHidden = menu.hidden;
    // close any other ui pops/cals first
    _openPops.forEach(function(i){ i.pop.hidden=true; i.btn.classList.remove("is-open"); });
    _openCals.forEach(function(i){ i.cal.hidden=true; });
    if (isHidden) {
      document.body.appendChild(menu);
      menu.hidden = false;
      menu.style.display = "block";
      var rect = t.getBoundingClientRect();
      var mw = menu.offsetWidth || 220;
      var mh = menu.offsetHeight || 260;
      var left = Math.min(Math.max(rect.left, 8), window.innerWidth - mw - 8);
      var below = rect.bottom + 6 + mh <= window.innerHeight - 8;
      var top = below ? rect.bottom + 6 : Math.max(8, rect.top - mh - 6);
      menu.style.left = left + "px";
      menu.style.top = top + "px";
      t.setAttribute("aria-expanded", "true");
    } else {
      menu.hidden = true;
      t.setAttribute("aria-expanded", "false");
    }
  }, true);
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") { closeAllUi(); }
  });

  function enhanceAllSelects(root) {
    var selects = (root || document).querySelectorAll("select");
    selects.forEach(function (s) {
      enhanceSelect(s);
    });
  }

  // ----- CALENDAR: wrap every native input[type=date] with audit-style toggle -----
  function enhanceDateInput(inp) {
    if (inp.dataset.uiDateEnhanced === "1") return;
    if (inp.type !== "date") return;
    if (!inp.parentNode) return;
    var wrap = document.createElement("span");
    wrap.className = "ui-date-wrap";
    inp.parentNode.insertBefore(wrap, inp);
    wrap.appendChild(inp);
    inp.dataset.uiDateEnhanced = "1";
    var btn = document.createElement("button");
    btn.type = "button"; btn.className = "ui-date-toggle";
    btn.setAttribute("aria-label","Open calendar");
    btn.appendChild(svgCalendar());
    wrap.appendChild(btn);
    var cal = document.createElement("div");
    cal.className = "ui-calendar"; cal.hidden = true;
    // append to dialog if inside one, otherwise body — top-layer fix
    var hostDlg = inp.closest("dialog");
    (hostDlg || document.body).appendChild(cal);
    inp._uiWrap = wrap; inp._uiToggle = btn; inp._uiCal = cal;

    // Calendar state per input
    var selected = inp.value || "";
    var viewYear = new Date().getFullYear();
    var viewMonth = new Date().getMonth();
    if (selected) { var p = selected.split("-"); viewYear = parseInt(p[0],10); viewMonth = parseInt(p[1],10)-1; }
    var MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
    var DOWS = ["Su","Mo","Tu","We","Th","Fr","Sa"];
    function fmt(d){ return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0"); }
    function renderCal(){
      var first = new Date(viewYear, viewMonth, 1);
      var startDow = first.getDay();
      var daysInMonth = new Date(viewYear, viewMonth+1, 0).getDate();
      var todayStr = fmt(new Date());
      var html = '<div class="ui-cal-head">'
        + '<button type="button" class="ui-cal-nav" data-cal-prev aria-label="Previous month">‹</button>'
        + '<span class="ui-cal-title">'+MONTHS[viewMonth]+' '+viewYear+'</span>'
        + '<button type="button" class="ui-cal-nav" data-cal-next aria-label="Next month">›</button></div>'
        + '<div class="ui-cal-grid">';
      for (var i=0;i<DOWS.length;i++) html += '<div class="ui-cal-dow">'+DOWS[i]+'</div>';
      for (var b=0;b<startDow;b++) html += '<div class="ui-cal-day out"></div>';
      for (var d=1; d<=daysInMonth; d++){
        var ds = viewYear+"-"+String(viewMonth+1).padStart(2,"0")+"-"+String(d).padStart(2,"0");
        var cls="ui-cal-day"; if(ds===todayStr) cls+=" today"; if(ds===selected) cls+=" sel";
        html += '<button type="button" class="'+cls+'" data-date="'+ds+'">'+d+'</button>';
      }
      cal.innerHTML = html + '</div>';
    }
    function position(){
      var rect = inp.getBoundingClientRect();
      var w = cal.offsetWidth || 272; var h = cal.offsetHeight || 260;
      var left = Math.min(Math.max(rect.left, 8), window.innerWidth - w - 8);
      var below = rect.bottom + 6 + h <= window.innerHeight - 8;
      var top = below ? rect.bottom + 6 : Math.max(8, rect.top - h - 6);
      cal.style.left = left+"px"; cal.style.top = top+"px";
    }
    function show(){
      // user: if another calendar/dropdown is open, it must close
      closeAllPops(null);
      closeAllCals({cal:cal});
      if(inp.value) { var pp=inp.value.split("-"); viewYear=parseInt(pp[0],10); viewMonth=parseInt(pp[1],10)-1; selected=inp.value; }
      renderCal(); cal.hidden=false; position();
      // ensure host is correct if dialog opened after page load
      var host = inp.closest("dialog");
      if (host && cal.parentElement !== host) host.appendChild(cal);
    }
    function hide(){ cal.hidden=true; }
    function selectDate(ds){
      selected = ds; inp.value = ds;
      inp.dispatchEvent(new Event("change",{bubbles:true}));
      inp.dispatchEvent(new Event("input",{bubbles:true}));
      hide();
    }
    function toggle(ev){
      if(ev) { ev.preventDefault(); ev.stopPropagation(); }
      if(!cal.hidden) hide(); else show();
    }
    btn.addEventListener("click", toggle);
    inp.addEventListener("click", function(ev){
      if (cal.hidden) { ev.preventDefault(); toggle(ev); }
    });
    cal.addEventListener("click", function(ev){
      ev.stopPropagation();
      var prev = ev.target.closest("[data-cal-prev]");
      if(prev){ viewMonth--; if(viewMonth<0){viewMonth=11; viewYear--;} renderCal(); position(); return; }
      var next = ev.target.closest("[data-cal-next]");
      if(next){ viewMonth++; if(viewMonth>11){viewMonth=0; viewYear++;} renderCal(); position(); return; }
      var day = ev.target.closest("[data-date]");
      if(day) selectDate(day.getAttribute("data-date"));
    });
    window.addEventListener("scroll", function(){ if(!cal.hidden) position(); }, true);
    window.addEventListener("resize", function(){ if(!cal.hidden) position(); });
    inp.addEventListener("change", function(){ selected = inp.value || ""; });
    _openCals.push({cal:cal, btn:btn, inp:inp, wrap:wrap});
  }

  function enhanceAllDates(root){
    var inputs = (root || document).querySelectorAll('input[type="date"]');
    inputs.forEach(enhanceDateInput);
    // fallback only for inputs that could not be enhanced (e.g. detached) — otherwise you get two icons
    inputs.forEach(function(i){
      if (!i.dataset.uiDateEnhanced) i.classList.add("ui-date-fallback");
      else i.classList.remove("ui-date-fallback");
    });
  }

  function init(){
    enhanceAllSelects(document);
    enhanceAllDates(document);

    // Re-enhance when new DOM is injected (modals, PJAX)
    var obs = new MutationObserver(function(muts){
      muts.forEach(function(m){
        m.addedNodes.forEach(function(n){
          if(n.nodeType !== 1) return;
          if(n.matches && n.matches("select")) enhanceSelect(n);
          if(n.matches && n.matches('input[type="date"]')) enhanceDateInput(n);
          if(n.querySelectorAll){
            n.querySelectorAll("select").forEach(enhanceSelect);
            n.querySelectorAll('input[type="date"]').forEach(enhanceDateInput);
          }
        });
      });
    });
    obs.observe(document.body, { childList: true, subtree: true });
  }

  // make entire local-search bar clickable (not just left half)
  document.addEventListener("click", function (ev) {
    var bar = ev.target.closest && ev.target.closest(".local-search");
    if (!bar) return;
    if (ev.target.tagName === "INPUT" || ev.target.tagName === "SELECT" || ev.target.tagName === "BUTTON") return;
    var inp = bar.querySelector("input");
    if (inp) inp.focus();
  });

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
