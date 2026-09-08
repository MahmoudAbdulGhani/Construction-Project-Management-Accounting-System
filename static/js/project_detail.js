(() => {
  "use strict";

  const root = document.querySelector("[data-project-detail]");
  if (!root) return;

  const id = root.dataset.projectId;

  const $ = (selector) => root.querySelector(selector);

  const dialog = document.querySelector("[data-detail-dialog]");
  if (!dialog) return;

  const form = dialog.querySelector("form");

  /* =========================================================
       Utilities
       ========================================================= */

  const esc = (value) =>
    String(value ?? "—").replace(
      /[&<>"']/g,
      (char) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[char],
    );

  const formValue = (value) =>
    esc(value === null || value === undefined ? "" : value);

  const label = (value) =>
    String(value || "—")
      .replaceAll("_", " ")
      .toLowerCase()
      .replace(/\b\w/g, (char) => char.toUpperCase());

  const statusClass = (value) =>
    String(value || "")
      .toLowerCase()
      .replaceAll("_", "-");

  const money = (value) =>
    new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(Number(value || 0));

  const csrf = () => {
    const token = document.cookie
      .split("; ")
      .find((cookie) => cookie.startsWith("csrftoken="));

    return token ? decodeURIComponent(token.split("=")[1]) : "";
  };

  const refreshIcons = () => {
    if (window.lucide?.createIcons) {
      window.lucide.createIcons();
    }
  };

  const result = (data) => (Array.isArray(data) ? data : data?.results || []);

  /* =========================================================
       API
       ========================================================= */

  async function request(path, options = {}, optional = false) {
    const response = await fetch(
      path.startsWith("/") ? path : `/api/projects/${path}`,
      {
        credentials: "same-origin",
        ...options,

        headers: {
          Accept: "application/json",

          ...(options.method
            ? {
                "X-CSRFToken": csrf(),

                // A multipart upload (FormData) must not get a
                // Content-Type override -- the browser sets it,
                // including the boundary, when the body is raw.
                ...(options.body instanceof FormData
                  ? {}
                  : {
                      "Content-Type": "application/json",
                    }),
              }
            : {}),

          ...options.headers,
        },
      },
    );

    const data = await response.json().catch(() => ({}));

    if (optional && response.status === 404) {
      return null;
    }

    if (!response.ok) {
      throw new Error(
        data.detail ||
          Object.values(data).flat().join(" ") ||
          `Request failed (${response.status})`,
      );
    }

    return data;
  }

  /* =========================================================
       State
       ========================================================= */

  let project = null;
  let phases = [];
  let budgets = [];
  let changeOrders = [];
  let projectEmployees = [];
  let projectContractors = [];
  let budgetSummaries = new Map();
  let clients = [];

  /* =========================================================
       Project status actions
       ========================================================= */

  const PROJECT_STATUS_ACTIONS = {
    PLANNING: [
      {
        target: "ACTIVE",
        label: "Start project",
        icon: "play",
        primary: true,
      },
      {
        target: "CANCELLED",
        label: "Cancel project",
        icon: "x",
        primary: false,
      },
    ],

    ACTIVE: [
      {
        target: "ON_HOLD",
        label: "Put on hold",
        icon: "pause",
        primary: false,
      },
      {
        target: "COMPLETED",
        label: "Complete project",
        icon: "check-circle",
        primary: true,
      },
      {
        target: "CANCELLED",
        label: "Cancel project",
        icon: "x",
        primary: false,
      },
    ],

    ON_HOLD: [
      {
        target: "ACTIVE",
        label: "Resume project",
        icon: "play",
        primary: true,
      },
      {
        target: "CANCELLED",
        label: "Cancel project",
        icon: "x",
        primary: false,
      },
    ],

    COMPLETED: [],

    CANCELLED: [],
  };

  /* =========================================================
       Budget configuration
       ========================================================= */

  const BUDGET_ACTIONS = {
    DRAFT: [
      {
        type: "transition",
        target: "APPROVED",
        label: "Approve",
        icon: "check",
      },
    ],

    APPROVED: [
      {
        type: "edit",
        label: "Edit",
        icon: "pencil",
      },
      {
        type: "transition",
        target: "CLOSED",
        label: "Close",
        icon: "lock",
      },
    ],

    REVISED: [
      {
        type: "edit",
        label: "Edit",
        icon: "pencil",
      },
      {
        type: "transition",
        target: "APPROVED",
        label: "Approve",
        icon: "check",
      },
      {
        type: "transition",
        target: "CLOSED",
        label: "Close",
        icon: "lock",
      },
    ],

    CLOSED: [],
  };

  const BUDGET_ITEM_CATEGORIES = [
    "MATERIALS",
    "LABOR",
    "CONTRACTORS",
    "EQUIPMENT",
    "OTHER",
  ];

  /* =========================================================
       Project status dropdown
       ========================================================= */

  function renderProjectStatusActions() {
    const menu = $("[data-action-menu]");

    const trigger = $("[data-action-menu-trigger]");

    if (!menu || !trigger || !project) {
      return;
    }

    const actions = PROJECT_STATUS_ACTIONS[project.status] || [];

    if (!actions.length) {
      menu.innerHTML = `
                <div class="actions-dropdown-empty">
                    No actions available
                </div>
            `;

      trigger.disabled = true;
      trigger.classList.add("disabled");

      return;
    }

    trigger.disabled = false;
    trigger.classList.remove("disabled");

    menu.innerHTML = actions
      .map(
        (action) => `
                    <button
                        type="button"
                        class="actions-dropdown-item ${
                          action.primary ? "is-primary" : ""
                        }"
                        data-action-project-status
                        data-target-status="${action.target}"
                    >
                        <i data-lucide="${action.icon}"></i>
                        <span>${action.label}</span>
                    </button>
                `,
      )
      .join("");

    refreshIcons();
  }

  /* =========================================================
       Table helper
       ========================================================= */

  function table(target, headers, rows) {
    const container = $(target);

    if (!container) return;

    container.innerHTML = `
            <table>

                <thead>
                    <tr>
                        ${headers
                          .map((header) => `<th>${header}</th>`)
                          .join("")}
                    </tr>
                </thead>

                <tbody>

                    ${
                      rows.length
                        ? rows.join("")
                        : `
                                <tr>
                                    <td colspan="${headers.length}">
                                        <strong>
                                            No records found.
                                        </strong>
                                    </td>
                                </tr>
                            `
                    }

                </tbody>

            </table>
        `;
  }

  /* =========================================================
       Render overview phases
       ========================================================= */

  function renderPhasePreview() {
    const container = $("[data-project-phase-preview]");

    if (!container) return;

    if (!phases.length) {
      container.innerHTML = `
                <div class="overview-empty">
                    No phases available.
                </div>
            `;

      return;
    }

    const sorted = [...phases]
      .sort(
        (a, b) =>
          Number(a.sequence_number || 0) - Number(b.sequence_number || 0),
      )
      .slice(0, 4);

    container.innerHTML = sorted
      .map((phase) => {
        const pct = Math.max(
          0,
          Math.min(100, Number(phase.progress_percentage) || 0),
        );

        const owner =
          phase.assigned_to_name ||
          phase.employee_name ||
          phase.assignee_name ||
          phase.owner_name ||
          "No owner assigned";

        return `
                        <div>

                            <div>
                                <strong>
                                    ${esc(phase.name)}
                                </strong>

                                <span>
                                    ${esc(owner)}
                                </span>
                            </div>

                            <div class="progress-cell">

                                <div>
                                    <div
                                        style="width:${pct}%"
                                    ></div>
                                </div>

                                <b>
                                    ${Math.round(pct)}%
                                </b>

                            </div>

                        </div>
                    `;
      })
      .join("");
  }

  /* =========================================================
       Render team
       ========================================================= */

  function renderProjectTeam() {
    const container = $("[data-project-team]");

    if (!container) return;

    const employees = Array.isArray(projectEmployees)
      ? projectEmployees.filter((assignment) => !assignment.released_at)
      : [];

    const contractors = Array.isArray(projectContractors)
      ? projectContractors.filter((assignment) => !assignment.released_at)
      : [];

    const members = [
      ...employees.map((assignment) => {
        const employee = assignment.employee || {};

        const employeeFirstName = employee.first_name || "";

        const employeeLastName = employee.last_name || "";

        return {
          name:
            assignment.employee_name ||
            employee.name ||
            employee.full_name ||
            `${employeeFirstName} ${employeeLastName}`.trim() ||
            "Team member",

          role:
            assignment.role_on_project ||
            employee.position ||
            employee.job_title ||
            employee.role ||
            "Team member",
        };
      }),

      ...contractors.map((assignment) => {
        const contractor = assignment.contractor || {};

        return {
          name: contractor.company_name || contractor.name || "Contractor",

          role: contractor.specialization || "Contractor",
        };
      }),
    ];

    if (!members.length) {
      container.innerHTML = `
              <div class="overview-empty">
                  No team members available.
              </div>
          `;

      return;
    }

    container.innerHTML = members
      .slice(0, 6)
      .map((member) => {
        const name = member.name;

        const role = member.role;

        const initials = name
          .split(/\s+/)
          .filter(Boolean)
          .slice(0, 2)
          .map((part) => part[0])
          .join("")
          .toUpperCase();

        return `
                      <div class="team-row">

                          <div class="avatar">
                              ${esc(initials || "?")}
                          </div>

                          <div>
                              <strong>
                                  ${esc(name)}
                              </strong>

                              <span>
                                  ${esc(role)}
                              </span>
                          </div>

                          <i data-lucide="ellipsis"></i>

                      </div>
                  `;
      })
      .join("");

    refreshIcons();
  }

  /* =========================================================
       Render activity
       ========================================================= */

  function renderProjectActivity() {
    const container = $("[data-project-activity]");

    if (!container) return;

    const activities =
      project?.recent_activity ||
      project?.activities ||
      project?.activity ||
      [];

    if (!Array.isArray(activities) || !activities.length) {
      container.innerHTML = `
                <div class="overview-empty">
                    No recent activity available.
                </div>
            `;

      return;
    }

    container.innerHTML = activities
      .slice(0, 5)
      .map((activity) => {
        const title =
          activity.title ||
          activity.description ||
          activity.name ||
          "Project activity";

        const detail =
          activity.detail || activity.message || activity.created_at || "";

        return `
                        <div class="activity">

                            <i>
                                <span data-lucide="activity"></span>
                            </i>

                            <div>

                                <strong>
                                    ${esc(title)}
                                </strong>

                                <span>
                                    ${esc(detail)}
                                </span>

                            </div>

                            <i data-lucide="chevron-right"></i>

                        </div>
                    `;
      })
      .join("");

    refreshIcons();
  }

  /* =========================================================
       Render budgets
       ========================================================= */

  function renderBudgets() {
    const container = $("[data-project-budgets]");

    if (!container) return;

    if (!budgets.length) {
      container.innerHTML = `
                <p class="budget-empty">
                    No budgets yet for this project.
                    Create one to start allocating
                    cost categories.
                </p>
            `;

      return;
    }

    const phaseName = (phaseId) =>
      phases.find((phase) => phase.id === phaseId)?.name;

    container.innerHTML = budgets
      .map((budget) => {
        const items = budget.items || [];

        const allocated = items.reduce(
          (total, item) => total + Number(item.budgeted_amount || 0),
          0,
        );

        const unallocated = Number(budget.total_budget || 0) - allocated;

        const editable =
          budget.status === "DRAFT" || budget.status === "REVISED";

        const actions = (BUDGET_ACTIONS[budget.status] || [])
          .map((action) => {
            if (action.type === "edit") {
              return `
                                        <button
                                            class="quiet-button"
                                            type="button"
                                            data-action-edit-budget
                                        >
                                            <i data-lucide="${action.icon}"></i>
                                            ${action.label}
                                        </button>
                                    `;
            }

            return `
                                    <button
                                        class="quiet-button"
                                        type="button"
                                        data-action-transition-budget
                                        data-target-status="${action.target}"
                                    >
                                        <i data-lucide="${action.icon}"></i>
                                        ${action.label}
                                    </button>
                                `;
          })
          .join("");

        const itemRows = items
          .map(
            (item) => `
                                <tr>

                                    <td>
                                        ${esc(label(item.category))}
                                    </td>

                                    <td>
                                        ${esc(phaseName(item.phase_id) || "—")}
                                    </td>

                                    <td>
                                        ${esc(item.description || "—")}
                                    </td>

                                    <td>
                                        ${money(item.budgeted_amount)}
                                    </td>

                                </tr>
                            `,
          )
          .join("");

        return `
                        <article
                            class="budget-card"
                            data-budget-id="${budget.id}"
                        >

                            <header
                                class="budget-card-head"
                            >

                                <div
                                    class="budget-card-title"
                                >

                                    <h3>
                                        ${esc(budget.name)}
                                    </h3>

                                    <span
                                        class="status ${statusClass(
                                          budget.status,
                                        )}"
                                    >
                                        <i></i>
                                        ${esc(label(budget.status))}
                                    </span>

                                </div>


                                <div
                                    class="budget-card-figures"
                                >

                                    <div
                                        class="figure figure-total"
                                    >
                                        <strong>
                                            ${money(budget.total_budget)}
                                        </strong>

                                        <span>
                                            Total
                                        </span>
                                    </div>


                                    <div
                                        class="figure figure-allocated"
                                    >
                                        <strong>
                                            ${money(allocated)}
                                        </strong>

                                        <span>
                                            Allocated
                                        </span>
                                    </div>


                                    <div
                                        class="figure figure-unallocated"
                                    >
                                        <strong>
                                            ${money(unallocated)}
                                        </strong>

                                        <span>
                                            Unallocated
                                        </span>
                                    </div>

                                </div>


                                <div
                                    class="budget-card-actions"
                                >

                                    ${
                                      editable
                                        ? `
                                                <button
                                                    class="quiet-button"
                                                    type="button"
                                                    data-action-add-budget-item
                                                >
                                                    <i data-lucide="plus"></i>
                                                    Add item
                                                </button>
                                            `
                                        : ""
                                    }

                                    ${actions}

                                </div>

                            </header>


                            <div
                                class="responsive-table"
                            >

                                <table>

                                    <thead>

                                        <tr>
                                            <th>Category</th>
                                            <th>Phase</th>
                                            <th>Description</th>
                                            <th>Amount</th>
                                        </tr>

                                    </thead>

                                    <tbody>

                                        ${
                                          itemRows ||
                                          `
                                                <tr>
                                                    <td colspan="4">
                                                        <strong>
                                                            No items allocated yet.
                                                        </strong>
                                                    </td>
                                                </tr>
                                            `
                                        }

                                    </tbody>

                                </table>

                            </div>

                        </article>
                    `;
      })
      .join("");

    refreshIcons();
  }

  /* =========================================================
       Load project
       ========================================================= */

  async function loadRiskForecast() {
    try {
      const data = await request(`projects/${id}/risk-forecast/`);
      const level = document.querySelector("[data-project-risk-level]");
      const total = document.querySelector("[data-project-forecast-total]");
      const margin = document.querySelector("[data-project-forecast-margin]");
      const ratio = document.querySelector("[data-project-forecast-ratio]");
      const explanation = document.querySelector(
        "[data-project-advisor-explanation]",
      );
      const factors = document.querySelector("[data-project-advisor-factors]");

      if (level) {
        const normalized = (data.risk_level || "HEALTHY").toLowerCase();
        level.textContent = data.risk_level || "HEALTHY";
        level.className = `status risk-${normalized}`;
      }

      if (total) {
        total.textContent = data.forecast?.estimated_total_cost || "—";
      }

      if (margin) {
        margin.textContent = data.forecast?.estimated_margin || "—";
      }

      if (ratio) {
        ratio.textContent = data.forecast?.cost_to_contract_ratio || "—";
      }

      if (explanation) {
        explanation.textContent =
          data.explanation || "No explanation available.";
      }

      if (factors) {
        const factorIcons = {
          "Actual cost vs contract": "wallet-cards",
          "Projected margin": "badge-dollar-sign",
          "Budget utilization": "gauge",
          "Forecast variance": "chart-no-axes-combined",
          "Phase progress": "layers-3",
        };
        factors.innerHTML = (data.factors || [])
          .map(
            (factor) => `
            <div class="advisor-factor">
              <div class="advisor-factor-head">
                <span><i data-lucide="${factorIcons[factor.label] || "activity"}"></i>${factor.label}</span>
                <strong>${factor.value || "—"}</strong>
              </div>
              <div class="advisor-factor-track"><span style="width:${Math.min(Math.max(Math.abs(Number.parseFloat(factor.value) || 0), 0), 100)}%"></span></div>
            </div>
          `,
          )
          .join("");
        refreshIcons();
      }
    } catch (error) {
      const explanation = document.querySelector(
        "[data-project-advisor-explanation]",
      );
      if (explanation) {
        explanation.textContent =
          "Risk forecast unavailable: the deterministic project estimate could not be generated.";
      }
    }
  }

  async function load() {
    root.setAttribute("data-project-loading", "");

    const [
      projectData,
      phaseData,
      ordersData,
      docs,
      budgetData,
      employeesData,
      contractorsData,
    ] = await Promise.all([
      request(`projects/${id}/`),

      request(`projects/${id}/phases/`),

      request(`change-orders/?project=${id}`),

      request(`projects/${id}/documents/`),

      request(`budgets/?project=${id}`),
      request(`projects/${id}/employees/`),
      request(`projects/${id}/contractors/`),
    ]);

    project = projectData;

    phases = result(phaseData);

    budgets = result(budgetData);

    changeOrders = result(ordersData);

    projectEmployees = result(employeesData);

    projectContractors = result(contractorsData);

    /* =====================================================
           Budget summaries
           ===================================================== */

    const summaries = await Promise.all(
      budgets.map((budget) =>
        request(`projects/${id}/budget-summary/?budget=${budget.id}`, {}, true),
      ),
    );

    budgetSummaries = new Map(
      budgets.map((budget, index) => [budget.id, summaries[index]]),
    );

    /* =====================================================
           Header
           ===================================================== */

    const projectCode = $("[data-project-code]");

    const projectName = $("[data-project-name]");

    const initials = $("[data-project-initials]");

    const projectMeta = $("[data-project-meta]");

    if (projectCode) {
      projectCode.textContent = project.code || "—";
    }

    if (projectName) {
      projectName.textContent = project.name || "Untitled project";
    }

    if (initials) {
      initials.textContent = String(project.name || "Project")
        .split(/\s+/)
        .slice(0, 2)
        .map((word) => word[0])
        .join("")
        .toUpperCase();
    }

    if (projectMeta) {
      const metaClient = clients.find(
        (client) => client.id === project.buyer_id,
      );

      projectMeta.textContent =
        [
          project.code,
          project.location,
          label(project.project_type),
          metaClient
            ? `Client: ${metaClient.company_name || metaClient.name}`
            : null,
        ]
          .filter(Boolean)
          .join(" · ") || "Project details";
    }

    /* =====================================================
           Status
           ===================================================== */

    const status = $("[data-project-status]");

    if (status) {
      status.className = `status ${statusClass(project.status)}`;

      status.innerHTML = `
                <i></i>
                ${esc(label(project.status))}
            `;
    }

    renderProjectStatusActions();

    /* =====================================================
           Contract
           ===================================================== */

    const contractValue = $("[data-contract-value]");

    if (contractValue) {
      contractValue.textContent = money(project.contract_value);
    }

    const contractLabel = $("[data-contract-label]");

    if (contractLabel) {
      contractLabel.textContent = project.contract_value
        ? "Contracted value"
        : "No contract value";
    }

    /* =====================================================
           Project dates
           ===================================================== */

    const startDate = $("[data-project-start]");

    const completionDate = $("[data-project-completion]");

    if (startDate) {
      startDate.textContent = project.start_date ? project.start_date : "—";
    }

    if (completionDate) {
      completionDate.textContent = project.expected_completion_date
        ? project.expected_completion_date
        : "—";
    }

    /* =====================================================
           Progress
           ===================================================== */

    const progress = phases.length
      ? phases.reduce(
          (total, phase) => total + Number(phase.progress_percentage || 0),
          0,
        ) / phases.length
      : 0;

    const roundedProgress = Math.round(progress);

    const progressText = $("[data-project-progress]");

    const progressBar = $("[data-project-progress-bar]");

    if (progressText) {
      progressText.textContent = `${roundedProgress}%`;
    }

    if (progressBar) {
      progressBar.style.width = `${Math.max(0, Math.min(100, progress))}%`;
    }

    renderPhasePreview();

    renderProjectTeam();

    renderProjectActivity();
    await loadRiskForecast();

    /* =====================================================
           Budget totals
           ===================================================== */

    const countedBudgets = budgets.filter(
      (budget) => budget.status !== "DRAFT",
    );

    const approvedTotal = countedBudgets.reduce(
      (total, budget) => total + Number(budget.total_budget || 0),
      0,
    );

    const actualTotal = countedBudgets.reduce(
      (total, budget) =>
        total + Number(budgetSummaries.get(budget.id)?.totals?.actual || 0),
      0,
    );

    const remainingTotal = approvedTotal - actualTotal;

    const variance =
      approvedTotal > 0
        ? ((approvedTotal - actualTotal) / approvedTotal) * 100
        : 0;

    /* =====================================================
           Forecast profit
           ===================================================== */

    const contract = Number(project.contract_value || 0);

    const forecastProfit = contract - actualTotal;

    const forecastMargin = contract > 0 ? (forecastProfit / contract) * 100 : 0;

    /* =====================================================
           Overview metrics
           ===================================================== */

    const budgetTotal = $("[data-budget-total]");

    const actualCost = $("[data-actual-total]");

    const remainingLabel = $("[data-remaining-label]");

    const remainingValueLabel = $("[data-remaining-total-label]");

    const forecastProfitElement = $("[data-forecast-profit]");

    const forecastMarginElement = $("[data-forecast-margin]");

    const forecastHealth = $("[data-forecast-health]");

    if (budgetTotal) {
      budgetTotal.textContent = money(approvedTotal);
    }

    if (actualCost) {
      actualCost.textContent = money(actualTotal);
    }

    if (remainingLabel) {
      remainingLabel.textContent = `${money(
        Math.max(0, remainingTotal),
      )} remaining`;
    }

    if (remainingValueLabel) {
      remainingValueLabel.textContent =
        remainingTotal >= 0 ? "Available" : "Over budget";
    }

    if (forecastProfitElement) {
      forecastProfitElement.textContent = money(forecastProfit);
    }

    if (forecastMarginElement) {
      forecastMarginElement.textContent = `${forecastMargin.toFixed(1)}% projected margin`;
    }

    if (forecastHealth) {
      forecastHealth.textContent = forecastProfit >= 0 ? "Healthy" : "At risk";
    }

    /* =====================================================
           Budget hero
           ===================================================== */

    $("[data-budget-hero-total]").textContent = money(approvedTotal);

    $("[data-budget-hero-actual]").textContent = money(actualTotal);

    $("[data-budget-hero-remaining]").textContent = money(remainingTotal);

    $("[data-budget-hero-variance]").textContent =
      `${variance >= 0 ? "+" : ""}${variance.toFixed(1)}%`;

    const budgetStatusLabel = $("[data-budget-status-label]");

    if (budgetStatusLabel) {
      budgetStatusLabel.textContent = countedBudgets.length
        ? `${countedBudgets.length} active`
        : "None";
    }

    /* =====================================================
           Health
           ===================================================== */

    const budgetHealth = $("[data-health-budget]");

    const budgetHealthStatus = $("[data-health-budget-status]");

    if (budgetHealth) {
      budgetHealth.textContent =
        approvedTotal > 0
          ? `${variance.toFixed(1)}% remaining against approved budget`
          : "No approved budget";
    }

    if (budgetHealthStatus) {
      budgetHealthStatus.textContent =
        approvedTotal > 0
          ? remainingTotal >= 0
            ? "On track"
            : "Over budget"
          : "No data";
    }

    const scheduleHealth = $("[data-health-schedule]");

    const scheduleHealthStatus = $("[data-health-schedule-status]");

    if (scheduleHealth) {
      if (!phases.length) {
        scheduleHealth.textContent = "No phases available";
      } else {
        const incomplete = phases.filter(
          (phase) => Number(phase.progress_percentage || 0) < 100,
        ).length;

        scheduleHealth.textContent = `${incomplete} phase${
          incomplete === 1 ? "" : "s"
        } still in progress`;
      }
    }

    if (scheduleHealthStatus) {
      scheduleHealthStatus.textContent = phases.length
        ? "Monitoring"
        : "No data";
    }

    /* =====================================================
           Tables
           ===================================================== */

    table(
      "[data-project-phases]",
      ["Phase", "Status", "Progress", "Start", "End", "Actions"],

      phases.map((phase) => {
        const pct = Math.max(
          0,
          Math.min(100, Number(phase.progress_percentage) || 0),
        );

        return `
                    <tr>

                        <td>
                            <strong>
                                ${esc(phase.name)}
                            </strong>
                        </td>

                        <td>

                            <span
                                class="status ${statusClass(phase.status)}"
                            >
                                <i></i>
                                ${esc(label(phase.status))}
                            </span>

                        </td>

                        <td>

                            <div
                                class="progress-cell"
                            >

                                <div>
                                    <div
                                        style="width:${pct}%"
                                    ></div>
                                </div>

                                <b>
                                    ${Math.round(pct)}%
                                </b>

                            </div>

                        </td>

                        <td>
                            ${esc(phase.start_date || "—")}
                        </td>

                        <td>
                            ${esc(phase.end_date || "—")}
                        </td>

                        <td class="row-actions">

                            <button
                                class="quiet-button"
                                type="button"
                                data-action-edit-phase
                                title="Edit phase"
                                aria-label="Edit phase"
                            >
                                <i data-lucide="pencil"></i>
                            </button>

                            <button
                                class="quiet-button"
                                type="button"
                                data-action-update-progress
                                title="Update progress"
                                aria-label="Update progress"
                            >
                                <i data-lucide="percent"></i>
                            </button>

                        </td>

                    </tr>
                `;
      }),
    );

    renderBudgets();

    table(
      "[data-project-change-orders]",
      ["Number", "Description", "Amount", "Date", "Status", "Actions"],

      changeOrders.map((order) => {
        let actions = "";

        if (order.status === "PENDING") {
          actions = `
                        <button
                            class="quiet-button"
                            type="button"
                            data-action-approve
                            title="Approve"
                        >
                            <i data-lucide="check"></i>
                        </button>

                        <button
                            class="quiet-button"
                            type="button"
                            data-action-reject
                            title="Reject"
                        >
                            <i data-lucide="x"></i>
                        </button>
                    `;
        }

        if (order.status === "PENDING" || order.status === "APPROVED") {
          actions += `
                        <button
                            class="quiet-button"
                            type="button"
                            data-action-cancel
                            title="Cancel"
                        >
                            <i data-lucide="trash-2"></i>
                        </button>
                    `;
        }

        return `
                    <tr>

                        <td>
                            <strong>
                                ${esc(order.number)}
                            </strong>
                        </td>

                        <td>
                            ${esc(order.description)}
                        </td>

                        <td>
                            ${money(order.amount)}
                        </td>

                        <td>
                            ${esc(order.date)}
                        </td>

                        <td>

                            <span
                                class="status ${statusClass(order.status)}"
                            >
                                <i></i>
                                ${esc(label(order.status))}
                            </span>

                        </td>

                        <td>
                            ${actions || "—"}
                        </td>

                    </tr>
                `;
      }),
    );

    /* =====================================================
           Documents
           ===================================================== */

    renderDocuments(docs);

    /* =====================================================
           Finish loading
           ===================================================== */

    root.removeAttribute("data-project-loading");

    refreshIcons();
  }

  /* =========================================================
       Documents
       ========================================================= */

  function renderDocuments(data) {
    const container = $("[data-project-documents]");

    if (!container) return;

    const documents = result(data);

    if (!documents.length) {
      container.innerHTML = `
                <div class="overview-empty">
                    No documents available.
                </div>
            `;

      return;
    }

    container.innerHTML = documents
      .map((document) => {
        const fileName = document.file_name || document.name || "Document";

        const filePath =
          document.file_url || document.file_path || document.file || "#";

        const documentType =
          document.document_type || document.file_type || "Document";

        const uploadedAt = document.uploaded_at || document.created_at || "—";

        return `
                        <article
                            class="doc-card"
                        >

                            <div
                                class="doc-icon"
                            >
                                <i
                                    data-lucide="file-text"
                                ></i>
                            </div>

                            <div>

                                <strong>
                                    ${esc(fileName)}
                                </strong>

                                <span>
                                    ${esc(uploadedAt)}
                                </span>

                                <em>
                                    ${esc(documentType)}
                                </em>

                            </div>

                            <a
                                href="${esc(filePath)}"
                                target="_blank"
                                rel="noopener"
                                class="doc-open"
                                aria-label="Open document"
                            >
                                <i
                                    data-lucide="external-link"
                                ></i>
                            </a>

                        </article>
                    `;
      })
      .join("");

    refreshIcons();
  }

  /* =========================================================
       Load clients (for the project client/buyer picker)
       ========================================================= */

  async function loadClients() {
    try {
      const data = await request("/api/clients/clients/", {}, true);

      clients = Array.isArray(data) ? data : data?.results || [];
    } catch (exception) {
      clients = [];
    }
  }

  /* =========================================================
       Dialog fields
       ========================================================= */

  const fields = ({ title, action, html, submit = "Save" }) => {
    form.dataset.action = action;

    dialog.querySelector("[data-dialog-title]").textContent = title;

    dialog.querySelector("[data-dialog-fields]").innerHTML = html;

    dialog.querySelector("[data-dialog-submit]").textContent = submit;

    dialog.querySelector("[data-dialog-error]").textContent = "";

    dialog.showModal();
  };

  const input = (
    name,
    text,
    type = "text",
    value = "",
    required = false,
    extra = {},
  ) => {
    const attrs = Object.entries(extra)
      .map(([key, val]) => `${key}="${esc(val)}"`)
      .join(" ");

    return `
            <label>

                ${text}

                <input
                    name="${name}"
                    type="${type}"
                    value="${formValue(value)}"
                    ${required ? "required" : ""}
                    ${attrs}
                >

            </label>
        `;
  };

  /* =========================================================
       Open dialogs
       ========================================================= */

  function open(action, context) {
    if (action === "edit-project") {
      fields({
        title: "Edit project",

        action,

        html:
          input("name", "Name", "text", project.name, true) +
          input("code", "Code", "text", project.code, true) +
          `
                    <label>
                        Type

                        <select name="project_type">

                            <option
                                value="WHOLE_BUILDING"
                                ${
                                  project.project_type === "WHOLE_BUILDING"
                                    ? "selected"
                                    : ""
                                }
                            >
                                Whole Building
                            </option>

                            <option
                                value="MULTI_UNIT"
                                ${
                                  project.project_type === "MULTI_UNIT"
                                    ? "selected"
                                    : ""
                                }
                            >
                                Multi Unit
                            </option>

                        </select>

                    </label>
                    ` +
          `
                    <label>
                        Client (buyer)

                        <select
                            name="buyer_id"
                        >

                            <option
                                value=""
                                ${!project.buyer_id ? "selected" : ""}
                            >
                                No client
                            </option>

                            ${clients
                              .map(
                                (client) => `

                                            <option
                                                value="${esc(client.id)}"
                                                ${
                                                  project.buyer_id === client.id
                                                    ? "selected"
                                                    : ""
                                                }
                                            >
                                                ${esc(
                                                  client.company_name ||
                                                    client.name,
                                                )}
                                            </option>

                                        `,
                              )
                              .join("")}

                        </select>

                    </label>
                    ` +
          input("start_date", "Start date", "date", project.start_date, true) +
          input(
            "expected_completion_date",
            "Expected completion",
            "date",
            project.expected_completion_date || "",
          ) +
          input(
            "contract_value",
            "Contract value",
            "number",
            project.contract_value,
            true,
          ) +
          `
                    <label>
                        Location

                        <input
                            name="location"
                            value="${esc(project.location || "")}"
                        >
                    </label>

                    <label>
                        Description

                        <textarea
                            name="description"
                        >${esc(project.description || "")}</textarea>

                    </label>
                    `,
      });
    } else if (action === "add-phase") {
      fields({
        title: "Add phase",

        action,

        submit: "Add phase",

        html:
          input("name", "Phase name", "text", "", true, {
            placeholder: "e.g. Foundation",
          }) +
          input(
            "sequence_number",
            "Order",
            "number",
            String(phases.length + 1),
            true,
            {
              min: "1",
              step: "1",
            },
          ) +
          input("start_date", "Start date", "date") +
          input("end_date", "End date", "date") +
          `
                    <label class="span-2">

                        Description

                        <textarea
                            name="description"
                            placeholder="Optional notes about this phase"
                        ></textarea>

                    </label>
                    `,
      });
    } else if (action === "edit-phase") {
      const phase = context;

      if (!phase) return;

      fields({
        title: `Edit phase: ${phase.name}`,

        action: "edit-phase",

        submit: "Save changes",

        html:
          input("name", "Phase name", "text", phase.name, true) +
          input(
            "sequence_number",
            "Order",
            "number",
            String(phase.sequence_number),
            true,
            {
              min: "1",
              step: "1",
            },
          ) +
          input("start_date", "Start date", "date", phase.start_date) +
          input("end_date", "End date", "date", phase.end_date) +
          `
                    <label>
                        Status

                        <select name="status">

                            ${[
                              "NOT_STARTED",
                              "IN_PROGRESS",
                              "ON_HOLD",
                              "COMPLETED",
                            ]
                              .map(
                                (status) =>
                                  `
                                                <option
                                                    value="${status}"
                                                    ${
                                                      phase.status === status
                                                        ? "selected"
                                                        : ""
                                                    }
                                                >
                                                    ${label(status)}
                                                </option>
                                            `,
                              )
                              .join("")}

                        </select>

                    </label>
                    ` +
          input(
            "progress_percentage",
            "Progress (%)",
            "number",
            String(phase.progress_percentage),
            true,
            {
              min: "0",
              max: "100",
              step: "1",
            },
          ) +
          `
                    <label class="span-2">

                        Description

                        <textarea
                            name="description"
                            placeholder="Optional notes about this phase"
                        >${esc(phase.description || "")}</textarea>

                    </label>
                    `,
      });

      form.dataset.phaseId = phase.id;
    } else if (action === "update-phase-progress") {
      const phase = context;

      if (!phase) return;

      fields({
        title: `Update progress: ${phase.name}`,

        action,

        submit: "Update",

        html: input(
          "progress_percentage",
          "Progress (%)",
          "number",
          phase.progress_percentage,
          true,
          {
            min: "0",
            max: "100",
            step: "1",
          },
        ),
      });

      form.dataset.phaseId = phase.id;
    } else if (action === "new-budget") {
      fields({
        title: "New budget",

        action,

        submit: "Create budget",

        html:
          input("name", "Budget name", "text", "", true, {
            placeholder: "e.g. Materials",
          }) +
          input("total_budget", "Total budget", "number", "", true, {
            min: "0",
            step: "0.01",
            placeholder: "0.00",
          }),
      });
    } else if (action === "transition-project") {
      const targetStatus = context?.targetStatus;

      if (!project || !targetStatus) {
        return;
      }

      const verbMap = {
        ACTIVE: "Start project",

        ON_HOLD: "Put project on hold",

        COMPLETED: "Complete project",

        CANCELLED: "Cancel project",
      };

      const verb = verbMap[targetStatus] || "Change status";

      fields({
        title: `${verb}: ${project.name}`,

        action: "transition-project",

        submit: verb,

        html: `

                    <p class="dialog-hint span-2">

                        This will change the project
                        status from

                        <strong>
                            ${esc(label(project.status))}
                        </strong>

                        to

                        <strong>
                            ${esc(label(targetStatus))}
                        </strong>.

                    </p>


                    ${
                      targetStatus === "ACTIVE"
                        ? `
                                <p
                                    class="dialog-hint span-2"
                                >
                                    The project will become
                                    active and work can begin.
                                </p>
                            `
                        : ""
                    }


                    ${
                      targetStatus === "COMPLETED"
                        ? `
                                <p
                                    class="dialog-hint span-2"
                                >
                                    A completed project
                                    cannot be moved to
                                    another status.
                                    Please make sure all
                                    project work is finished.
                                </p>
                            `
                        : ""
                    }


                    ${
                      targetStatus === "CANCELLED"
                        ? `
                                <p
                                    class="dialog-hint span-2"
                                >
                                    A cancelled project is
                                    final and cannot be
                                    reactivated.
                                </p>
                            `
                        : ""
                    }

                `,
      });

      form.dataset.targetStatus = targetStatus;
    } else if (action === "edit-budget") {
      const budget = context;

      if (!budget) return;

      fields({
        title: `Edit budget: ${budget.name}`,

        action,

        submit: "Save changes",

        html:
          input("name", "Budget name", "text", budget.name, true) +
          input(
            "total_budget",
            "Total budget",
            "number",
            budget.total_budget,
            true,
            {
              min: "0",
              step: "0.01",
            },
          ) +
          (budget.status === "APPROVED"
            ? `
                                <p
                                    class="dialog-hint span-2"
                                >
                                    This budget is currently
                                    Approved — saving changes
                                    will mark it as Revised.
                                </p>
                            `
            : ""),
      });

      form.dataset.budgetId = budget.id;

      form.dataset.wasApproved = budget.status === "APPROVED" ? "true" : "";
    } else if (action === "add-budget-item") {
      const budget = context;

      if (!budget) return;

      const items = budget.items || [];

      const allocated = items.reduce(
        (total, item) => total + Number(item.budgeted_amount || 0),
        0,
      );

      const remaining = Number(budget.total_budget || 0) - allocated;

      const categoryOptions =
        BUDGET_ITEM_CATEGORIES.map(
          (category) =>
            `
                                <option
                                    value="${category}"
                                >
                                    ${label(category)}
                                </option>
                            `,
        ).join("") +
        `
                    <option value="__custom__">
                        Other (specify)…
                    </option>
                `;

      const phaseOptions =
        `
                    <option value="">
                        No specific phase
                    </option>
                ` +
        phases
          .map(
            (phase) =>
              `
                                <option
                                    value="${phase.id}"
                                >
                                    ${esc(phase.name)}
                                </option>
                            `,
          )
          .join("");

      fields({
        title: `Add item to ${budget.name}`,

        action,

        submit: "Add item",

        html:
          `
                        <p
                            class="dialog-hint span-2"
                        >
                            Remaining to allocate:

                            <strong>
                                ${money(remaining)}
                            </strong>

                            of

                            ${money(budget.total_budget)}

                        </p>
                    ` +
          `
                        <label>
                            Category

                            <select
                                name="category"
                                data-category-select
                            >
                                ${categoryOptions}
                            </select>

                        </label>
                    ` +
          `
                        <label
                            data-custom-category
                            hidden
                        >
                            Custom category

                            <input
                                name="category_custom"
                                placeholder="e.g. Permits"
                            >

                        </label>
                    ` +
          `
                        <label>
                            Phase

                            <select name="phase_id">
                                ${phaseOptions}
                            </select>

                        </label>
                    ` +
          input("budgeted_amount", "Amount", "number", "", true, {
            min: "0",
            step: "0.01",
            placeholder: "0.00",
          }) +
          `
                        <label class="span-2">

                            Description

                            <input
                                name="description"
                                placeholder="e.g. Cement for foundation"
                            >

                        </label>
                    `,
      });

      form.dataset.budgetId = budget.id;

      const categorySelect = dialog.querySelector("[data-category-select]");

      const customField = dialog.querySelector("[data-custom-category]");

      categorySelect?.addEventListener("change", () => {
        const isCustom = categorySelect.value === "__custom__";

        customField.hidden = !isCustom;

        customField.querySelector("input").required = isCustom;
      });
    } else if (action === "transition-budget") {
      const { budget, targetStatus } = context;

      if (!budget || !targetStatus) {
        return;
      }

      const verb =
        targetStatus === "APPROVED"
          ? "Approve"
          : targetStatus === "REVISED"
            ? "Mark as revised"
            : "Close";

      fields({
        title: `${verb} budget: ${budget.name}`,

        action: "transition-budget",

        submit: verb,

        html: `
                        <p class="span-2">

                            This will
                            ${verb.toLowerCase()}

                            <strong>
                                ${esc(budget.name)}
                            </strong>

                            — status changes from

                            ${label(budget.status)}

                            to

                            ${label(targetStatus)}.

                            ${
                              targetStatus === "CLOSED"
                                ? " No further items can be added once closed."
                                : ""
                            }

                        </p>
                    `,
      });

      form.dataset.budgetId = budget.id;

      form.dataset.targetStatus = targetStatus;
    } else if (action === "add-change-order") {
      fields({
        title: "Create change order",

        action,

        submit: "Create",

        html:
          input("number", "CO Number", "text", "", true) +
          input("description", "Description", "text", "", true) +
          input("reason", "Reason", "text") +
          input("amount", "Amount", "number", "", true) +
          input(
            "date",
            "Date",
            "date",
            new Date().toISOString().split("T")[0],
            true,
          ),
      });
    } else if (action === "approve-change-order") {
      const order = context;

      if (!order) return;

      fields({
        title: `Approve change order ${order.number}`,

        action,

        submit: "Approve",

        html: `
                        <p>
                            <strong>
                                ${esc(order.description)}
                            </strong>
                        </p>

                        <p>
                            Amount:
                            ${money(order.amount)}
                        </p>

                        <label>
                            Approved by (optional):

                            <input
                                name="approved_by"
                                type="text"
                            >
                        </label>
                    `,
      });

      form.dataset.orderId = order.id;
    } else if (action === "reject-change-order") {
      const order = context;

      if (!order) return;

      fields({
        title: `Reject change order ${order.number}`,

        action,

        submit: "Reject",

        html: `
                        <p>
                            <strong>
                                ${esc(order.description)}
                            </strong>
                        </p>

                        <p>
                            Amount:
                            ${money(order.amount)}
                        </p>

                        <p>
                            This change order will
                            be marked as rejected.
                        </p>
                    `,
      });

      form.dataset.orderId = order.id;
    } else if (action === "cancel-change-order") {
      const order = context;

      if (!order) return;

      fields({
        title: `Cancel change order ${order.number}`,

        action,

        submit: "Cancel",

        html: `
                        <p>
                            <strong>
                                ${esc(order.description)}
                            </strong>
                        </p>

                        <p>
                            Amount:
                            ${money(order.amount)}
                        </p>

                        <p>
                            This change order will
                            be marked as cancelled.
                        </p>
                    `,
      });

      form.dataset.orderId = order.id;
    } else if (action === "upload-document") {
      fields({
        title: "Upload document",

        action,

        submit: "Upload",

        html: `
                        <label>
                            File

                            <input
                                name="file"
                                type="file"
                                required
                            >
                        </label>

                        <label>
                            Document type

                            <input
                                name="document_type"
                                type="text"
                                placeholder=
                                    "e.g. Contract, Drawing, Invoice"
                            >
                        </label>
                    `,
      });
    }
  }

  /* =========================================================
       Initialization
       ========================================================= */

  document.addEventListener("DOMContentLoaded", async () => {
    try {
      await Promise.all([load(), loadClients()]);
    } catch (error) {
      root.removeAttribute("data-project-loading");

      const errorElement = $("[data-project-detail-error]");

      if (errorElement) {
        errorElement.hidden = false;

        errorElement.textContent = `Could not load this project: ${error.message}`;
      }
    }

    /* =================================================
               Project Actions Dropdown
               ================================================= */

    const actionsMenu = root.querySelector("[data-project-actions-menu]");

    const actionsTrigger = root.querySelector("[data-action-menu-trigger]");

    const actionsDropdown = root.querySelector("[data-action-menu]");

    if (actionsMenu && actionsTrigger && actionsDropdown) {
      actionsTrigger.addEventListener("click", (event) => {
        event.stopPropagation();

        if (actionsTrigger.disabled) {
          return;
        }

        const isOpen = !actionsDropdown.hidden;

        actionsDropdown.hidden = isOpen;

        actionsTrigger.setAttribute("aria-expanded", String(!isOpen));
      });

      document.addEventListener("click", (event) => {
        if (!actionsMenu.contains(event.target)) {
          actionsDropdown.hidden = true;

          actionsTrigger.setAttribute("aria-expanded", "false");
        }
      });
    }

    /* =================================================
               Generic action buttons
               ================================================= */

    root.addEventListener("click", (event) => {
      const actionButton = event.target.closest("[data-action]");

      if (!actionButton) {
        return;
      }

      const action = actionButton.dataset.action;

      if (action === "add-record") {
        open("add-change-order");

        return;
      }

      if (action === "upload-document") {
        open("upload-document");

        return;
      }

      open(action);
    });

    /* =================================================
               Project status actions
               ================================================= */

    root.addEventListener("click", (event) => {
      const button = event.target.closest("[data-action-project-status]");

      if (!button) return;

      const targetStatus = button.dataset.targetStatus;

      if (!targetStatus) {
        return;
      }

      const dropdown = root.querySelector("[data-action-menu]");

      const trigger = root.querySelector("[data-action-menu-trigger]");

      if (dropdown) {
        dropdown.hidden = true;
      }

      if (trigger) {
        trigger.setAttribute("aria-expanded", "false");
      }

      open("transition-project", {
        targetStatus,
      });
    });

    /* =================================================
               Budget actions
               ================================================= */

    const budgetsPanel = root.querySelector("[data-project-budgets]");

    if (budgetsPanel) {
      budgetsPanel.addEventListener("click", (event) => {
        const card = event.target.closest("[data-budget-id]");

        if (!card) return;

        const budget = budgets.find(
          (item) => String(item.id) === String(card.dataset.budgetId),
        );

        if (!budget) return;

        if (event.target.closest("[data-action-add-budget-item]")) {
          open("add-budget-item", budget);
        } else if (event.target.closest("[data-action-edit-budget]")) {
          open("edit-budget", budget);
        } else if (event.target.closest("[data-action-transition-budget]")) {
          const button = event.target.closest(
            "[data-action-transition-budget]",
          );

          open("transition-budget", {
            budget,
            targetStatus: button.dataset.targetStatus,
          });
        }
      });
    }

    /* =================================================
               Procurement actions
               ================================================= */

    const procurementPanel = root.querySelector(
      '[data-project-panel="procurement"]',
    );

    if (procurementPanel) {
      procurementPanel.addEventListener("click", (event) => {
        const row = event.target.closest("tr");

        if (!row) return;

        const number = row.querySelector("strong")?.textContent?.trim();

        const order = changeOrders.find(
          (item) => String(item.number) === String(number),
        );

        if (!order) return;

        if (event.target.closest("[data-action-approve]")) {
          open("approve-change-order", order);
        } else if (event.target.closest("[data-action-reject]")) {
          open("reject-change-order", order);
        } else if (event.target.closest("[data-action-cancel]")) {
          open("cancel-change-order", order);
        }
      });
    }

    /* =================================================
               Phase actions
               ================================================= */

    const phasesPanel = root.querySelector('[data-project-panel="phases"]');

    if (phasesPanel) {
      phasesPanel.addEventListener("click", (event) => {
        const button = event.target.closest("button");

        if (!button) return;

        const row = button.closest("tr");

        if (!row) return;

        const name = row.querySelector("strong")?.textContent?.trim();

        const phase = phases.find((item) => item.name === name);

        if (!phase) return;

        if (button.matches("[data-action-edit-phase]")) {
          open("edit-phase", phase);
        }

        if (button.matches("[data-action-update-progress]")) {
          open("update-phase-progress", phase);
        }
      });
    }

    /* =================================================
               View detailed plan
               ================================================= */

    const phaseLink = root.querySelector("[data-project-tab-link='phases']");

    if (phaseLink) {
      phaseLink.addEventListener("click", () => {
        const tab = root.querySelector('[data-project-tab="phases"]');

        if (tab) {
          tab.click();
        }
      });
    }

    /* =================================================
               Dialog close
               ================================================= */

    const closeButton = document.querySelector("[data-dialog-close]");

    closeButton?.addEventListener("click", () => dialog.close());

    /* =================================================
               Dialog submit
               ================================================= */

    form.addEventListener("submit", async (event) => {
      event.preventDefault();

      const submit = dialog.querySelector("[data-dialog-submit]");

      const error = dialog.querySelector("[data-dialog-error]");

      const data = Object.fromEntries(new FormData(form));

      Object.keys(data).forEach((key) => {
        if (data[key] === "") {
          // "No client" in the project dialog means
          // explicitly clear the buyer, so send null
          // rather than dropping the pairing entirely.
          if (key === "buyer_id") {
            data[key] = null;
          } else {
            delete data[key];
          }
        }
      });

      let path;

      let method = "POST";

      const action = form.dataset.action;

      /* -----------------------------------------
                       Document upload
                       ----------------------------------------- */

      if (action === "upload-document") {
        const body = new FormData(form);

        body.append("entity_type", "project");

        body.append("entity_id", id);

        submit.disabled = true;

        error.textContent = "";

        try {
          await request("/api/documents/documents/", {
            method: "POST",
            body,
          });

          dialog.close();

          form.reset();

          await load();
        } catch (exception) {
          error.textContent = exception.message;
        } finally {
          submit.disabled = false;
        }

        return;
      }

      /* -----------------------------------------
                       Project
                       ----------------------------------------- */

      if (action === "edit-project") {
        path = `projects/${id}/`;

        method = "PATCH";
      } else if (action === "transition-project") {
        path = `projects/${id}/`;

        method = "PATCH";

        data.status = form.dataset.targetStatus;
      } else if (action === "add-phase") {
        /* -----------------------------------------
                       Phases
                       ----------------------------------------- */
        path = "phases/";

        data.project_id = id;
      } else if (action === "edit-phase") {
        path = `phases/${form.dataset.phaseId}/`;

        method = "PATCH";
      } else if (action === "update-phase-progress") {
        path = `phases/${form.dataset.phaseId}/`;

        method = "PATCH";
      } else if (action === "new-budget") {
        /* -----------------------------------------
                       Budgets
                       ----------------------------------------- */
        path = "budgets/";

        data.project_id = id;
      } else if (action === "edit-budget") {
        path = `budgets/${form.dataset.budgetId}/`;

        method = "PATCH";

        if (form.dataset.wasApproved === "true") {
          data.status = "REVISED";
        }
      } else if (action === "add-budget-item") {
        path = "budget-items/";

        data.budget_id = form.dataset.budgetId;

        if (data.category === "__custom__") {
          data.category = (data.category_custom || "")
            .trim()
            .toUpperCase()
            .replace(/\s+/g, "_");
        }

        delete data.category_custom;
      } else if (action === "transition-budget") {
        path = `budgets/${form.dataset.budgetId}/`;

        method = "PATCH";

        data.status = form.dataset.targetStatus;
      } else if (action === "add-change-order") {
        /* -----------------------------------------
                       Change orders
                       ----------------------------------------- */
        path = "change-orders/";

        data.project_id = id;
      } else if (action === "approve-change-order") {
        path = `change-orders/${form.dataset.orderId}/approve/`;

        delete data.approved_by;
      } else if (action === "reject-change-order") {
        path = `change-orders/${form.dataset.orderId}/reject/`;
      } else if (action === "cancel-change-order") {
        path = `change-orders/${form.dataset.orderId}/cancel/`;
      } else {
        path = "change-orders/";

        data.project_id = id;
      }

      submit.disabled = true;

      error.textContent = "";

      try {
        await request(path, {
          method,
          body: JSON.stringify(data),
        });

        dialog.close();

        form.reset();

        await load();
      } catch (exception) {
        error.textContent = exception.message;
      } finally {
        submit.disabled = false;
      }
    });

    /* =================================================
               Tabs
               ================================================= */

    const tabs = [...root.querySelectorAll("[data-project-tab]")];

    const panels = [...root.querySelectorAll("[data-project-panel]")];

    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        tabs.forEach((item) => {
          item.classList.toggle("active", item === tab);
        });

        panels.forEach((panel) => {
          panel.hidden = panel.dataset.projectPanel !== tab.dataset.projectTab;
        });
      });
    });

    refreshIcons();
  });
})();
