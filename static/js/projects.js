(() => {
  const api = "/api/projects/projects/";
  const $ = (selector) => document.querySelector(selector);
  const esc = (value) => String(value ?? "—").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[char]);
  const label = (value) => String(value || "—").replaceAll("_", " ").toLowerCase().replace(/\b\w/g, char => char.toUpperCase());
  const money = (value) => new Intl.NumberFormat(undefined, {style: "currency", currency: "USD", maximumFractionDigits: 0}).format(Number(value || 0));
  const csrf = () => decodeURIComponent(document.cookie.split("; ").find(cookie => cookie.startsWith("csrftoken="))?.split("=")[1] || "");
  let projects = [];
  let clients = [];

  async function request(url, options = {}) {
    const response = await fetch(url, {credentials: "same-origin", ...options, headers: {Accept: "application/json", ...(options.method ? {"Content-Type": "application/json", "X-CSRFToken": csrf()} : {}), ...options.headers}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || Object.values(data).flat().join(" ") || `Request failed (${response.status})`);
    return data;
  }

  function render() {
    const search = $("[data-project-search]").value.trim().toLowerCase();
    const status = $("[data-project-status]").value;
    const clientName = (project) => {
      const client = clients.find(item => item.id === project.buyer_id);
      return client ? (client.company_name || client.name) : "";
    };
    const visible = projects.filter(project => (!status || project.status === status) && (!search || [project.name, project.code, project.location, clientName(project)].some(value => String(value || "").toLowerCase().includes(search))));
    $("[data-project-rows]").innerHTML = visible.length ? visible.map(project => `<tr><td><a href="/projects/${encodeURIComponent(project.id)}/"><strong>${esc(project.name)}</strong><span>${esc(project.code)}</span></a></td><td>${esc(clientName(project) || "—")}</td><td><span class="status ${esc(String(project.status).toLowerCase().replaceAll("_", "-"))}"><i></i>${esc(label(project.status))}</span></td><td>${esc(label(project.project_type))}</td><td>${money(project.contract_value)}</td><td>${esc(project.start_date)}</td><td>${esc(project.expected_completion_date)}</td></tr>`).join("") : '<tr><td colspan="7"><strong>No projects found.</strong></td></tr>';
    $("[data-project-metric=total]").textContent = projects.length;
    $("[data-project-metric=active]").textContent = projects.filter(project => project.status === "ACTIVE").length;
    $("[data-project-metric=at-risk]").textContent = projects.filter(project => project.status === "ON_HOLD").length;
    $("[data-project-metric=value]").textContent = money(projects.reduce((total, project) => total + Number(project.contract_value || 0), 0));
  }

  async function load() {
    try {
      const data = await request(api);
      projects = Array.isArray(data) ? data : data.results || [];
      render();
    } catch (error) { $("[data-project-rows]").innerHTML = `<tr><td colspan="6"><strong>Could not load projects: ${esc(error.message)}</strong></td></tr>`; }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    $("[data-project-search]").addEventListener("input", render);
    $("[data-project-status]").addEventListener("change", render);
    const dialog = $("[data-project-dialog]"), form = $("[data-project-form]");
    const clientSelect = $("[data-project-client]");
    $("[data-project-create]").addEventListener("click", () => { dialog.showModal(); });
    $("[data-dialog-close]").addEventListener("click", () => dialog.close());
    form.addEventListener("submit", async event => { event.preventDefault(); const error = $("[data-form-error]"), submit = form.querySelector("[type=submit]"); error.textContent = ""; submit.disabled = true; try { const payload = Object.fromEntries(new FormData(form)); Object.keys(payload).forEach(key => { if (payload[key] === "") delete payload[key]; }); await request(api, {method: "POST", body: JSON.stringify(payload)}); dialog.close(); form.reset(); await load(); } catch (reason) { error.textContent = reason.message; } finally { submit.disabled = false; } });
    try {
      const data = await request("/api/clients/clients/");
      clients = Array.isArray(data) ? data : data.results || [];
      clientSelect.innerHTML = `<option value="">No client</option>` + clients.map(client => `<option value="${esc(client.id)}">${esc(client.company_name || client.name)}</option>`).join("");
    } catch (error) { clientSelect.innerHTML = `<option value="">No client</option>`; }
    await load();
  });
})();
