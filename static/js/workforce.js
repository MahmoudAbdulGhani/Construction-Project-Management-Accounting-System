/* =========================================================
   Workforce / Employee Management
   ========================================================= */

(() => {
    "use strict";

    /*
     * Prevent accidental double initialization if the script
     * gets included more than once.
     */
    if (window.__cedarWorkforceInitialized) {
        return;
    }

    window.__cedarWorkforceInitialized = true;


    /* =========================================================
       API
       ========================================================= */

    const API = "/api/employees/";
    const PROJECTS_API = "/api/projects/projects/";
    const CURRENCY = "USD";


    /* =========================================================
       DOM helpers
       ========================================================= */

    const $ = (sel, root = document) =>
        root.querySelector(sel);

    const $$ = (sel, root = document) =>
        [...root.querySelectorAll(sel)];


    /* =========================================================
       State
       ========================================================= */

    const state = {
        employees: [],
        assignments: [],
        phases: [],
        projects: [],
        statusFilter: "all",
        search: ""
    };

    let detailEmployeeId = null;
    let detailEmployee = null;
    let activeTab = "assignments";


    /* =========================================================
       Escape HTML
       ========================================================= */

    const esc = value =>
        String(value ?? "").replace(
            /[&<>"']/g,
            c => ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;"
            }[c])
        );


    /* =========================================================
       CSRF
       ========================================================= */

    function getCookie(name) {
        const m = document.cookie.match(
            new RegExp("(^|;\\s*)" + name + "=([^;]*)")
        );

        return m ? decodeURIComponent(m[2]) : "";
    }


    /* =========================================================
       API helpers
       ========================================================= */

    async function api(url, options = {}) {
        const opts = {
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                ...(options.headers || {})
            },
            ...options
        };

        if (
            options.method &&
            !["GET", "HEAD"].includes(options.method)
        ) {
            opts.headers["X-CSRFToken"] =
                getCookie("csrftoken");
        }

        const res = await fetch(url, opts);

        if (!res.ok) {
            let detail = res.statusText;

            try {
                const data = await res.json();
                detail =
                    data.detail ||
                    data.message ||
                    JSON.stringify(data);
            } catch (e) {
                /* Ignore JSON parsing errors. */
            }

            throw new Error(
                `${res.status}: ${detail}`
            );
        }

        if (res.status === 204) {
            return null;
        }

        return res.json();
    }


    async function fetchAll(url) {
        const rows = [];
        let next = url;

        while (next) {
            const data = await api(next);

            if (Array.isArray(data)) {
                rows.push(...data);
                break;
            }

            rows.push(...(data.results || []));
            next = data.next;
        }

        return rows;
    }


    /* =========================================================
       Formatting helpers
       ========================================================= */

    /* =========================================================
      Employee data helpers
      ========================================================= */

    function getLaborRate(employee) {
        if (!employee) {
            return null;
        }

        /*
        * labor_rate is the canonical API field.
        *
        * The additional names make the frontend tolerant of
        * older serializer responses while the API is being
        * standardized.
        */
        const value =
            employee.labor_rate ??
            employee.laborRate ??
            employee.rate ??
            employee.labor_rate_per_hour ??
            null;

        if (
            value === null ||
            value === undefined ||
            value === ""
        ) {
            return null;
        }

        const number = Number(value);

        return Number.isFinite(number)
            ? number
            : null;
    }


    function statusLabel(status) {
        switch (status) {
            case "ACTIVE":
                return "Active";

            case "ON_LEAVE":
                return "On leave";

            case "TERMINATED":
                return "Terminated";

            default:
                return status || "Unknown";
        }
    }


    function fmtMoney(value) {
        if (
            value === undefined ||
            value === null ||
            value === ""
        ) {
            return "—";
        }

        const normalized =
            typeof value === "string"
                ? value.replace(/[$,\s]/g, "")
                : value;

        const n = Number(normalized);

        if (!Number.isFinite(n)) {
            return esc(value);
        }

        return n.toLocaleString("en-US", {
            style: "currency",
            currency: CURRENCY,
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }


    function statusLabel(status) {
        const labels = {
            ACTIVE: "Active",
            ON_LEAVE: "On leave",
            TERMINATED: "Terminated"
        };

        return labels[status] || status || "Active";
    }


    function statusPill(status) {
        const safe = status || "ACTIVE";

        const cls =
            safe === "ACTIVE"
                ? " active"
                : safe === "TERMINATED"
                    ? " warning"
                    : "";

        return `
            <span class="status${cls}">
                <i></i>${esc(statusLabel(safe))}
            </span>
        `;
    }


    /* =========================================================
       Employee status select
       ========================================================= */

    function statusSelect(employee) {
        const current =
            employee.employment_status || "ACTIVE";

        return `
            <select
                class="employee-status-select"
                data-employee-status="${esc(employee.id)}"
                aria-label="Change employment status for ${esc(employee.name)}"
            >
                <option
                    value="ACTIVE"
                    ${current === "ACTIVE" ? "selected" : ""}
                >
                    Active
                </option>

                <option
                    value="ON_LEAVE"
                    ${current === "ON_LEAVE" ? "selected" : ""}
                >
                    On leave
                </option>

                <option
                    value="TERMINATED"
                    ${current === "TERMINATED" ? "selected" : ""}
                >
                    Terminated
                </option>
            </select>
        `;
    }


    /* =========================================================
       Employee table
       ========================================================= */

    function renderRows() {
        const tbody = $("[data-employee-rows]");

        if (!tbody) {
            return;
        }

        let list = state.employees;

        if (state.statusFilter !== "all") {
            list = list.filter(
                e => e.employment_status === state.statusFilter
            );
        }

        const q = state.search.trim().toLowerCase();

        if (q) {
            list = list.filter(e =>
                [
                    e.name,
                    e.employee_number,
                    e.position,
                    e.department,
                    e.email
                ].some(v =>
                    String(v || "")
                        .toLowerCase()
                        .includes(q)
                )
            );
        }

        if (!list.length) {
            tbody.innerHTML = `
                <tr>
                    <td>
                        <strong>No employees found</strong>
                        <span>
                            Try adjusting the search or status filter.
                        </span>
                    </td>

                    <td>—</td>
                    <td>—</td>
                    <td>—</td>

                    <td>
                        <span class="status">
                            <i></i>—
                        </span>
                    </td>

                    <td>—</td>
                </tr>
            `;

            return;
        }

        tbody.innerHTML = list.map(employee => {

            const laborRate = getLaborRate(employee);

            return `
                <tr
                    class="row-click"
                    data-employee-id="${esc(employee.id)}"
                >

                    <td>
                        <strong>
                            ${esc(employee.name)}
                        </strong>

                        <span>
                            ${esc(employee.employee_number)}
                        </span>
                    </td>

                    <td>
                        ${esc(employee.position || "—")}
                    </td>

                    <td>
                        ${esc(employee.department || "—")}
                    </td>

                    <td>
                        ${
                            laborRate !== null
                                ? fmtMoney(laborRate)
                                : "—"
                        }
                    </td>

                    <td>
                        ${statusPill(employee.employment_status)}
                    </td>

                    <td>
                        <div class="employee-table-actions">

                            <select
                                class="employee-status-select"
                                data-status-employee="${esc(employee.id)}"
                                aria-label="Change employee status"
                            >
                                <option
                                    value="ACTIVE"
                                    ${
                                        employee.employment_status === "ACTIVE"
                                            ? "selected"
                                            : ""
                                    }
                                >
                                    Active
                                </option>

                                <option
                                    value="ON_LEAVE"
                                    ${
                                        employee.employment_status === "ON_LEAVE"
                                            ? "selected"
                                            : ""
                                    }
                                >
                                    On leave
                                </option>

                                <option
                                    value="TERMINATED"
                                    ${
                                        employee.employment_status === "TERMINATED"
                                            ? "selected"
                                            : ""
                                    }
                                >
                                    Terminated
                                </option>
                            </select>

                            <button
                                type="button"
                                class="employee-edit-icon"
                                data-employee-edit-table="${esc(employee.id)}"
                                aria-label="Edit ${esc(employee.name)}"
                                title="Edit employee"
                            >
                                <i data-lucide="pencil"></i>
                            </button>

                        </div>
                    </td>

                </tr>
            `;
        }).join("");

        /*
        * Prevent clicking the status selector or edit button
        * from opening the employee profile.
        */
        $$("[data-status-employee]", tbody).forEach(select => {

            select.addEventListener("click", event => {
                event.stopPropagation();
            });

            select.addEventListener("change", async event => {
                event.stopPropagation();

                await updateEmployeeStatus(
                    select.dataset.statusEmployee,
                    select
                );
            });
        });


        $$("[data-employee-edit-table]", tbody).forEach(button => {

            button.addEventListener("click", event => {
                event.preventDefault();
                event.stopPropagation();

                const employee = state.employees.find(
                    e =>
                        String(e.id) ===
                        String(button.dataset.employeeEditTable)
                );

                if (employee) {
                    openEmployeeForm(employee);
                }
            });
        });


        /*
        * Re-render Lucide icons after injecting the rows.
        */
        if (window.lucide) {
            window.lucide.createIcons();
        }


        /*
        * Clicking elsewhere on the row still opens the
        * read-only employee profile.
        */
        $$("[data-employee-id]", tbody).forEach(row => {

            row.addEventListener("click", event => {

                if (
                    event.target.closest(
                        "[data-status-employee], [data-employee-edit-table]"
                    )
                ) {
                    return;
                }

                openDetail(row.dataset.employeeId);
            });

        });
    }
    async function updateEmployeeStatus(employeeId, select) {
        const employee = state.employees.find(
            e => String(e.id) === String(employeeId)
        );

        if (!employee) {
            return;
        }

        const previousStatus =
            employee.employment_status;

        const newStatus = select.value;

        if (previousStatus === newStatus) {
            return;
        }

        select.disabled = true;

        try {
            const updated = await api(
                `${API}${employeeId}/`,
                {
                    method: "PATCH",
                    body: JSON.stringify({
                        employment_status: newStatus
                    })
                }
            );

            /*
            * IMPORTANT:
            * Keep every field returned by the API, including
            * labor_rate. This is why the labor rate was appearing
            * after changing status before.
            */
            Object.assign(employee, updated);

            employee.employment_status =
                updated.employment_status || newStatus;

            /*
            * If the PATCH response contains labor_rate,
            * preserve it explicitly.
            */
            const updatedRate = getLaborRate(updated);

            if (updatedRate !== null) {
                employee.labor_rate = updatedRate;
            }

            renderRows();
            renderMetrics();

        } catch (error) {

            select.value = previousStatus;

            alert(
                "Could not update employee status: " +
                error.message
            );

        } finally {
            select.disabled = false;
        }
    }


    /* =========================================================
       Change employee status
       ========================================================= */

    function bindStatusActions(root = document) {
        $$(
            "[data-employee-status]",
            root
        ).forEach(select => {
            select.addEventListener(
                "click",
                e => {
                    e.stopPropagation();
                }
            );

            select.addEventListener(
                "change",
                async e => {
                    e.stopPropagation();

                    const employeeId =
                        select.dataset.employeeStatus;

                    const newStatus =
                        select.value;

                    const employee =
                        state.employees.find(
                            item =>
                                String(item.id) ===
                                String(employeeId)
                        );

                    if (!employee) {
                        return;
                    }

                    const oldStatus =
                        employee.employment_status ||
                        "ACTIVE";

                    if (newStatus === oldStatus) {
                        return;
                    }

                    select.disabled = true;

                    try {
                        const updated =
                            await api(
                                `${API}${employeeId}/`,
                                {
                                    method: "PATCH",
                                    body: JSON.stringify({
                                        employment_status:
                                            newStatus
                                    })
                                }
                            );

                        /*
                         * Update local employee data from the
                         * API response when available.
                         */
                        Object.assign(
                            employee,
                            updated || {},
                            {
                                employment_status:
                                    updated?.employment_status ||
                                    newStatus
                            }
                        );

                        renderRows();
                        renderMetrics();

                        /*
                         * If the employee being viewed is the
                         * same employee, update the profile
                         * status immediately.
                         */
                        if (
                            detailEmployeeId &&
                            String(detailEmployeeId) ===
                                String(employeeId)
                        ) {
                            detailEmployee =
                                updated ||
                                employee;

                            renderDetailStatus(
                                detailEmployee
                            );
                        }
                    } catch (error) {
                        /*
                         * Restore the previous value if the
                         * update failed.
                         */
                        select.value = oldStatus;

                        alert(
                            "Could not change employee status: " +
                            error.message
                        );
                    } finally {
                        select.disabled = false;
                    }
                }
            );
        });
    }


    /* =========================================================
       Metrics
       ========================================================= */

    function renderMetrics() {
        const employees =
            state.employees;

        const active =
            employees.filter(
                e =>
                    e.employment_status ===
                    "ACTIVE"
            ).length;

        const onleave =
            employees.filter(
                e =>
                    e.employment_status ===
                    "ON_LEAVE"
            ).length;

        const total =
            $("[data-metric=total]");

        const activeEl =
            $("[data-metric=active]");

        const leaveEl =
            $("[data-metric=onleave]");

        const assignments =
            $("[data-metric=assignments]");

        if (total) {
            total.textContent =
                employees.length;
        }

        if (activeEl) {
            activeEl.textContent =
                active;
        }

        if (leaveEl) {
            leaveEl.textContent =
                onleave;
        }

        /*
         * Assignment count is intentionally not fetched for
         * every employee here. Doing that would create a large
         * number of API requests and make the Workforce page
         * slow.
         *
         * It is updated when an employee's assignments are
         * actually loaded.
         */
        if (assignments) {
            if (
                assignments.dataset.loaded !== "true"
            ) {
                assignments.textContent = "—";
            }
        }
    }


    /* =========================================================
       Detail dialog
       ========================================================= */

    const dialog =
        $("[data-employee-dialog]");


    function renderDetailStatus(employee) {
        const status =
            $("[data-detail-status]");

        if (!status) {
            return;
        }

        const value =
            employee?.employment_status ||
            "ACTIVE";

        const cls =
            value === "ACTIVE"
                ? " active"
                : value === "TERMINATED"
                    ? " warning"
                    : "";

        status.className =
            "status" + cls;

        status.innerHTML =
            `<i></i>${esc(statusLabel(value))}`;
    }


    function renderDetail(employee) {
        $("[data-detail-name]").textContent =
            employee.name || "—";

        $("[data-detail-number]").textContent =
            employee.employee_number || "—";

        $("[data-detail-number-2]").textContent =
            employee.employee_number || "—";

        $("[data-detail-phone]").textContent =
            employee.phone || "—";

        $("[data-detail-email]").textContent =
            employee.email || "—";

        $("[data-detail-position]").textContent =
            employee.position || "—";

        $("[data-detail-department]").textContent =
            employee.department || "—";

        $("[data-detail-rate]").textContent =
            fmtMoney(
                getLaborRate(employee)
            );

        renderDetailStatus(employee);
    }


    async function openDetail(id) {
        detailEmployeeId = id;
        detailEmployee = null;

        /*
         * Reset assignment metric until the employee's
         * assignment endpoint has actually been loaded.
         */
        const assignmentMetric =
            $("[data-metric=assignments]");

        if (assignmentMetric) {
            assignmentMetric.textContent = "—";
            assignmentMetric.dataset.loaded =
                "false";
        }

        /*
         * Open the dialog immediately with a loading state.
         * The old implementation waited for the assignments
         * request before showing the dialog.
         */
        dialog.showModal();

        $("[data-detail-name]").textContent =
            "Loading…";

        $("[data-detail-number]").textContent =
            "Loading employee profile";

        $("[data-detail-number-2]").textContent =
            "—";

        $("[data-detail-phone]").textContent =
            "—";

        $("[data-detail-email]").textContent =
            "—";

        $("[data-detail-position]").textContent =
            "—";

        $("[data-detail-department]").textContent =
            "—";

        $("[data-detail-rate]").textContent =
            "—";

        renderDetailStatus({
            employment_status: "ACTIVE"
        });

        try {
            /*
             * Only the employee profile is required to open
             * the dialog.
             */
            const detail =
                await api(`${API}${id}/`);

            /*
             * Protect against the user opening another employee
             * while this request was still in flight.
             */
            if (
                String(detailEmployeeId) !==
                String(id)
            ) {
                return;
            }

            detailEmployee = detail;

            renderDetail(detail);

            /*
             * Load only the currently active tab.
             * This is no longer blocking the profile dialog.
             */
            loadTab(activeTab);

        } catch (error) {
            if (
                String(detailEmployeeId) !==
                String(id)
            ) {
                return;
            }

            $("[data-detail-name]").textContent =
                "Could not load employee";

            $("[data-detail-number]").textContent =
                error.message;

            const panel =
                $("[data-tab-panel]");

            if (panel) {
                panel.innerHTML = `
                    <div class="employee-inline-message">
                        <strong>
                            Could not load employee profile.
                        </strong>
                        <span>
                            ${esc(error.message)}
                        </span>
                    </div>
                `;
            }
        }
    }


    /* =========================================================
       Project assignments
       ========================================================= */

    async function loadAssignments() {
        const panel =
            $("[data-tab-panel]");

        if (panel) {
            panel.innerHTML = `
                <div class="employee-loading">
                    Loading project assignments…
                </div>
            `;
        }

        try {
            state.assignments =
                await api(
                    `${API}${detailEmployeeId}/projects/`
                );

            /*
             * Update the metric after the actual assignment
             * request completes.
             */
            const assignmentMetric =
                $("[data-metric=assignments]");

            if (assignmentMetric) {
                assignmentMetric.textContent =
                    state.assignments.length;

                assignmentMetric.dataset.loaded =
                    "true";
            }

        } catch (error) {
            state.assignments = [];

            const assignmentMetric =
                $("[data-metric=assignments]");

            if (assignmentMetric) {
                assignmentMetric.textContent = "0";
                assignmentMetric.dataset.loaded =
                    "true";
            }

            if (panel) {
                panel.innerHTML = `
                    <div class="employee-inline-message">
                        <strong>
                            Could not load assignments.
                        </strong>
                        <span>
                            ${esc(error.message)}
                        </span>
                    </div>
                `;
            }

            return;
        }

        renderMetrics();
    }


    function assignmentTable() {
        const cols = [
            "Project",
            "Role",
            "Assigned",
            "Released",
            ""
        ];

        const head = `
            <table>
                <thead>
                    <tr>
                        ${cols
                            .map(c => `<th>${c}</th>`)
                            .join("")}
                    </tr>
                </thead>
        `;

        if (!state.assignments.length) {
            return `
                ${head}
                <tbody>
                    <tr>
                        <td colspan="${cols.length}">
                            <strong>
                                No project assignments for this employee.
                            </strong>
                        </td>
                    </tr>
                </tbody>
                </table>
            `;
        }

        const rows =
            state.assignments
                .map(a => `
                    <tr>
                        <td>
                            <strong>
                                ${esc(
                                    a.project?.name ||
                                    "—"
                                )}
                            </strong>

                            <span>
                                ${esc(
                                    a.project?.code ||
                                    "—"
                                )}
                            </span>
                        </td>

                        <td>
                            ${esc(
                                a.role_on_project ||
                                "—"
                            )}
                        </td>

                        <td>
                            ${esc(
                                a.assigned_at ||
                                "—"
                            )}
                        </td>

                        <td>
                            ${esc(
                                a.released_at ||
                                "—"
                            )}
                        </td>

                        <td>
                            <button
                                type="button"
                                class="tab-action"
                                data-release="${esc(a.id)}"
                                ${a.released_at
                                    ? "disabled"
                                    : ""}
                            >
                                Release
                            </button>

                            <button
                                type="button"
                                class="tab-action danger"
                                data-unassign="${esc(a.id)}"
                            >
                                Unassign
                            </button>
                        </td>
                    </tr>
                `)
                .join("");

        return `
            ${head}
            <tbody>${rows}</tbody>
            </table>
        `;
    }


    function assignForm() {
        const options =
            state.projects
                .map(p => `
                    <option value="${esc(p.id)}">
                        ${esc(p.code)} — ${esc(p.name)}
                    </option>
                `)
                .join("");

        return `
            <form
                class="employee-assign-form"
                data-assign-form
            >

                <label>
                    Project *
                    <select
                        name="project_id"
                        required
                    >
                        <option
                            value=""
                            disabled
                            selected
                        >
                            Select project…
                        </option>

                        ${options}
                    </select>
                </label>

                <label>
                    Role on project
                    <input
                        type="text"
                        name="role_on_project"
                        placeholder="e.g. Site Lead"
                    >
                </label>

                <label>
                    Assigned date *
                    <input
                        type="date"
                        name="assigned_at"
                        required
                    >
                </label>

                <button
                    type="submit"
                    class="primary-button"
                >
                    Assign
                </button>

                <button
                    type="button"
                    class="quiet-button"
                    data-assign-cancel
                >
                    Cancel
                </button>

            </form>
        `;
    }


    /* =========================================================
       Phase assignments
       ========================================================= */

    async function loadPhaseAssignments() {
        state.phases = [];

        try {
            if (!state.projects.length) {
                state.projects =
                    await fetchAll(PROJECTS_API);
            }

            /*
             * Keep the existing phase behavior, but only execute
             * it when the user actually opens Phase assignments.
             */
            for (const project of state.projects) {
                try {
                    const phases =
                        await fetchAll(
                            `${PROJECTS_API}${project.id}/phases/`
                        );

                    phases.forEach(phase => {
                        const responsibleId =
                            phase.responsible_emp_id ||
                            phase.responsible_employee?.id ||
                            phase.responsible_emp?.id ||
                            null;

                        if (
                            responsibleId &&
                            String(responsibleId) ===
                                String(detailEmployeeId)
                        ) {
                            state.phases.push({
                                ...phase,
                                project
                            });
                        }
                    });
                } catch (e) {
                    /*
                     * Ignore a project whose phase endpoint
                     * cannot be loaded.
                     */
                }
            }

        } catch (e) {
            state.phases = [];
        }
    }


    function phaseTable() {
        if (!state.phases.length) {
            return `
                <div class="employee-inline-message">
                    <strong>
                        No phase assignments found.
                    </strong>

                    <span>
                        This employee is not currently responsible
                        for a project phase.
                    </span>
                </div>
            `;
        }

        const rows =
            state.phases
                .map(phase => `
                    <tr>
                        <td>
                            <strong>
                                ${esc(
                                    phase.name ||
                                    "Unnamed phase"
                                )}
                            </strong>

                            <span>
                                ${esc(
                                    phase.project?.code ||
                                    phase.project?.name ||
                                    "—"
                                )}
                            </span>
                        </td>

                        <td>
                            ${esc(
                                phase.project?.name ||
                                "—"
                            )}
                        </td>

                        <td>
                            ${esc(
                                phase.status ||
                                "—"
                            )}
                        </td>

                        <td>
                            <button
                                type="button"
                                class="tab-action danger"
                                data-unassign-phase="${esc(
                                    phase.id
                                )}"
                                data-phase-project="${esc(
                                    phase.project?.id || ""
                                )}"
                            >
                                Remove
                            </button>
                        </td>
                    </tr>
                `)
                .join("");

        return `
            <table>
                <thead>
                    <tr>
                        <th>Phase</th>
                        <th>Project</th>
                        <th>Status</th>
                        <th></th>
                    </tr>
                </thead>

                <tbody>
                    ${rows}
                </tbody>
            </table>
        `;
    }


    function phaseAssignForm() {
        const options =
            state.projects
                .map(p => `
                    <option value="${esc(p.id)}">
                        ${esc(p.code)} — ${esc(p.name)}
                    </option>
                `)
                .join("");

        return `
            <form
                class="employee-assign-form"
                data-phase-assign-form
            >

                <label>
                    Project *
                    <select
                        name="project_id"
                        data-phase-project
                        required
                    >
                        <option
                            value=""
                            disabled
                            selected
                        >
                            Select project…
                        </option>

                        ${options}
                    </select>
                </label>

                <label>
                    Phase *
                    <select
                        name="phase_id"
                        data-phase-select
                        required
                        disabled
                    >
                        <option value="">
                            Select project first…
                        </option>
                    </select>
                </label>

                <span></span>

                <button
                    type="submit"
                    class="primary-button"
                >
                    Assign
                </button>

                <button
                    type="button"
                    class="quiet-button"
                    data-phase-cancel
                >
                    Cancel
                </button>

            </form>
        `;
    }


    async function loadPhasesForProject(projectId) {
        const phaseSelect =
            $("[data-phase-select]");

        if (!phaseSelect) {
            return;
        }

        phaseSelect.disabled = true;

        phaseSelect.innerHTML = `
            <option value="">
                Loading phases…
            </option>
        `;

        try {
            const phases =
                await fetchAll(
                    `${PROJECTS_API}${projectId}/phases/`
                );

            if (!phases.length) {
                phaseSelect.innerHTML = `
                    <option value="">
                        No phases found
                    </option>
                `;

                return;
            }

            phaseSelect.innerHTML = `
                <option
                    value=""
                    disabled
                    selected
                >
                    Select phase…
                </option>

                ${phases
                    .map(
                        phase => `
                            <option value="${esc(phase.id)}">
                                ${esc(
                                    phase.name ||
                                    phase.phase_name ||
                                    `Phase ${phase.id}`
                                )}
                            </option>
                        `
                    )
                    .join("")}
            `;

            phaseSelect.disabled = false;

        } catch (e) {
            phaseSelect.innerHTML = `
                <option value="">
                    Could not load phases
                </option>
            `;
        }
    }


    /* =========================================================
       Tabs
       ========================================================= */

    async function loadTab(tab) {
        activeTab = tab;

        const panel =
            $("[data-tab-panel]");

        if (!panel) {
            return;
        }

        $$("[data-tab]").forEach(button => {
            button.classList.toggle(
                "active",
                button.dataset.tab === tab
            );
        });


        /* -----------------------------------------------------
           Project assignments
           ----------------------------------------------------- */

        if (tab === "assignments") {
            await loadAssignments();

            /*
             * User may have changed tabs while the request
             * was loading.
             */
            if (activeTab !== "assignments") {
                return;
            }

            panel.innerHTML =
                assignmentTable();

            bindAssignmentActions(panel);

            return;
        }


        /* -----------------------------------------------------
           Assign project
           ----------------------------------------------------- */

        if (tab === "assign") {
            panel.innerHTML = `
                <div class="employee-loading">
                    Loading projects…
                </div>
            `;

            if (!state.projects.length) {
                try {
                    state.projects =
                        await fetchAll(PROJECTS_API);
                } catch (e) {
                    state.projects = [];
                }
            }

            if (activeTab !== "assign") {
                return;
            }

            panel.innerHTML =
                assignForm();

            const form =
                $("[data-assign-form]");

            const cancel =
                $("[data-assign-cancel]");

            if (cancel) {
                cancel.addEventListener(
                    "click",
                    () => loadTab("assignments")
                );
            }

            if (form) {
                form.addEventListener(
                    "submit",
                    async e => {
                        e.preventDefault();

                        const payload =
                            Object.fromEntries(
                                new FormData(form)
                                    .entries()
                            );

                        if (
                            !payload.role_on_project
                        ) {
                            delete payload.role_on_project;
                        }

                        try {
                            await api(
                                `${API}${detailEmployeeId}/projects/`,
                                {
                                    method: "POST",
                                    body:
                                        JSON.stringify(
                                            payload
                                        )
                                }
                            );

                            await loadTab(
                                "assignments"
                            );

                        } catch (err) {
                            alert(
                                "Could not assign project: " +
                                err.message
                            );
                        }
                    }
                );
            }

            return;
        }


        /* -----------------------------------------------------
           Phase assignments
           ----------------------------------------------------- */

        if (tab === "phases") {
            panel.innerHTML = `
                <div class="employee-loading">
                    Loading phase assignments…
                </div>
            `;

            if (!state.projects.length) {
                try {
                    state.projects =
                        await fetchAll(PROJECTS_API);
                } catch (e) {
                    state.projects = [];
                }
            }

            await loadPhaseAssignments();

            if (activeTab !== "phases") {
                return;
            }

            panel.innerHTML =
                phaseTable() +
                `
                    <div
                        style="border-top:1px solid var(--line);"
                    >
                        ${phaseAssignForm()}
                    </div>
                `;

            bindPhaseActions(panel);

            return;
        }
    }


    /* =========================================================
       Assignment actions
       ========================================================= */

    function bindAssignmentActions(panel) {
        $$(
            "[data-release]",
            panel
        ).forEach(btn => {
            btn.addEventListener(
                "click",
                async () => {
                    const aid =
                        btn.dataset.release;

                    if (
                        !confirm(
                            "Release this assignment?"
                        )
                    ) {
                        return;
                    }

                    btn.disabled = true;

                    try {
                        await api(
                            `${API}${detailEmployeeId}/projects/${aid}/`,
                            {
                                method: "PATCH",
                                body:
                                    JSON.stringify({
                                        released_at:
                                            new Date()
                                                .toISOString()
                                                .slice(0, 10)
                                    })
                            }
                        );

                        await loadTab(
                            "assignments"
                        );

                    } catch (e) {
                        btn.disabled = false;

                        alert(
                            "Could not release assignment: " +
                            e.message
                        );
                    }
                }
            );
        });


        $$(
            "[data-unassign]",
            panel
        ).forEach(btn => {
            btn.addEventListener(
                "click",
                async () => {
                    const aid =
                        btn.dataset.unassign;

                    if (
                        !confirm(
                            "Remove this assignment entirely?"
                        )
                    ) {
                        return;
                    }

                    btn.disabled = true;

                    try {
                        await api(
                            `${API}${detailEmployeeId}/projects/${aid}/`,
                            {
                                method: "DELETE"
                            }
                        );

                        await loadTab(
                            "assignments"
                        );

                    } catch (e) {
                        btn.disabled = false;

                        alert(
                            "Could not unassign: " +
                            e.message
                        );
                    }
                }
            );
        });
    }


    /* =========================================================
       Phase actions
       ========================================================= */

    function bindPhaseActions(panel) {
        const projectSelect =
            $("[data-phase-project]", panel);

        const phaseSelect =
            $("[data-phase-select]", panel);

        if (projectSelect) {
            projectSelect.addEventListener(
                "change",
                () =>
                    loadPhasesForProject(
                        projectSelect.value
                    )
            );
        }


        const form =
            $(
                "[data-phase-assign-form]",
                panel
            );

        if (form) {
            const cancel =
                $("[data-phase-cancel]", form);

            if (cancel) {
                cancel.addEventListener(
                    "click",
                    () => loadTab("phases")
                );
            }

            form.addEventListener(
                "submit",
                async e => {
                    e.preventDefault();

                    const phaseId =
                        phaseSelect?.value;

                    if (!phaseId) {
                        return;
                    }

                    try {
                        await api(
                            `${PROJECTS_API}${phaseId}/`,
                            {
                                method: "PATCH",
                                body:
                                    JSON.stringify({
                                        responsible_emp_id:
                                            detailEmployeeId
                                    })
                            }
                        );

                        await loadTab(
                            "phases"
                        );

                    } catch (err) {
                        alert(
                            "Could not assign employee to phase: " +
                            err.message
                        );
                    }
                }
            );
        }


        $$(
            "[data-unassign-phase]",
            panel
        ).forEach(btn => {
            btn.addEventListener(
                "click",
                async () => {
                    const phaseId =
                        btn.dataset.unassignPhase;

                    if (
                        !confirm(
                            "Remove this employee from the phase?"
                        )
                    ) {
                        return;
                    }

                    btn.disabled = true;

                    try {
                        await api(
                            `${PROJECTS_API}${phaseId}/`,
                            {
                                method: "PATCH",
                                body:
                                    JSON.stringify({
                                        responsible_emp_id:
                                            null
                                    })
                            }
                        );

                        await loadTab("phases");

                    } catch (err) {
                        btn.disabled = false;

                        alert(
                            "Could not remove phase assignment: " +
                            err.message
                        );
                    }
                }
            );
        });
    }


    /* =========================================================
       Employee create / edit modal
       ========================================================= */

    const employeeOverlay =
        $("[data-employee-create]");

    const employeeForm =
        $("[data-employee-form]");


    function openEmployeeForm(employee = null) {
        if (
            !employeeOverlay ||
            !employeeForm
        ) {
            return;
        }

        employeeForm.reset();

        const title =
            $("[data-employee-form-title]");

        const eyebrow =
            $("[data-employee-form-eyebrow]");

        const submit =
            $("[data-employee-form-submit]");

        const idInput =
            $("[data-employee-edit-id]");


        if (employee) {
            title.textContent =
                "Edit employee";

            eyebrow.textContent =
                "EMPLOYEE MANAGEMENT";

            submit.textContent =
                "Save changes";

            idInput.value =
                employee.id || "";

            employeeForm.elements.name.value =
                employee.name || "";

            employeeForm.elements.employee_number.value =
                employee.employee_number || "";

            employeeForm.elements.phone.value =
                employee.phone || "";

            employeeForm.elements.email.value =
                employee.email || "";

            employeeForm.elements.position.value =
                employee.position || "";

            employeeForm.elements.department.value =
                employee.department || "";

            const rate =
                getLaborRate(employee);

            employeeForm.elements.labor_rate.value =
                rate ?? "";

            employeeForm.elements.employment_status.value =
                employee.employment_status ||
                "ACTIVE";

        } else {
            title.textContent =
                "New employee";

            eyebrow.textContent =
                "OPERATIONS";

            submit.textContent =
                "Create employee";

            idInput.value = "";

            employeeForm.elements.employment_status.value =
                "ACTIVE";
        }


        employeeOverlay.hidden = false;

        /*
         * Prevent the browser from restoring the old form
         * position and focus the name field.
         */
        requestAnimationFrame(() => {
            const firstInput =
                employeeForm.elements.name;

            if (firstInput) {
                firstInput.focus();
            }
        });
    }


    function closeEmployeeForm() {
        if (!employeeOverlay) {
            return;
        }

        employeeOverlay.hidden = true;

        if (employeeForm) {
            employeeForm.reset();
        }

        const id =
            $("[data-employee-edit-id]");

        if (id) {
            id.value = "";
        }
    }


    async function submitEmployeeForm(e) {
        e.preventDefault();

        const form =
            e.currentTarget;

        const employeeId =
            $("[data-employee-edit-id]").value;


        const formData =
            Object.fromEntries(
                new FormData(form).entries()
            );


        const payload = {};


        Object.entries(formData)
            .forEach(([key, value]) => {
                if (
                    key ===
                        "csrfmiddlewaretoken" ||
                    key ===
                        "employee_edit_id"
                ) {
                    return;
                }

                if (
                    value === "" ||
                    value == null
                ) {
                    return;
                }

                payload[key] = value;
            });


        /*
         * Convert labor rate into a number so Django receives
         * a proper numeric value.
         */
        if (
            payload.labor_rate !== undefined
        ) {
            const rate =
                Number(payload.labor_rate);

            if (Number.isFinite(rate)) {
                payload.labor_rate =
                    rate;
            } else {
                delete payload.labor_rate;
            }
        }


        const submitButton =
            $(
                "[data-employee-form-submit]"
            );

        if (submitButton) {
            submitButton.disabled = true;
        }


        try {
            let savedEmployee;

            if (employeeId) {
                savedEmployee =
                    await api(
                        `${API}${employeeId}/`,
                        {
                            method: "PATCH",
                            body:
                                JSON.stringify(
                                    payload
                                )
                        }
                    );
            } else {
                savedEmployee =
                    await api(
                        API,
                        {
                            method: "POST",
                            body:
                                JSON.stringify(
                                    payload
                                )
                        }
                    );
            }


            closeEmployeeForm();


            /*
             * Refresh the table.
             */
            await refresh();


            /*
             * If editing, reopen the same employee's
             * profile using the fresh data.
             */
            if (employeeId) {
                await openDetail(
                    employeeId
                );
            } else if (
                savedEmployee?.id
            ) {
                await openDetail(
                    savedEmployee.id
                );
            }

        } catch (err) {
            alert(
                employeeId
                    ? "Could not update employee: " +
                      err.message
                    : "Could not create employee: " +
                      err.message
            );

        } finally {
            if (submitButton) {
                submitButton.disabled = false;
            }
        }
    }


    /* =========================================================
       Delete employee
       ========================================================= */

    async function deleteEmployee() {
        if (!detailEmployeeId) {
            return;
        }

        if (
            !confirm(
                "Delete this employee? Existing protected assignments may prevent deletion."
            )
        ) {
            return;
        }

        try {
            await api(
                `${API}${detailEmployeeId}/`,
                {
                    method: "DELETE"
                }
            );

            dialog.close();

            await refresh();

        } catch (e) {
            alert(
                "Could not delete employee: " +
                e.message
            );
        }
    }


    /* =========================================================
       Dialog bindings
       ========================================================= */

    function bindDialog() {
        if (!dialog) {
            return;
        }

        const actions =
            $(".employee-dialog-actions");


        /*
         * Add Edit/Delete buttons once.
         */
        if (
            actions &&
            !$("[data-employee-edit]", actions)
        ) {
            actions.insertAdjacentHTML(
                "afterbegin",
                `
                    <button
                        type="button"
                        class="quiet-button"
                        data-employee-edit
                    >
                        Edit
                    </button>

                    <button
                        type="button"
                        class="quiet-button"
                        data-employee-delete
                    >
                        Delete
                    </button>
                `
            );
        }


        const editButton =
            $("[data-employee-edit]");

        const deleteButton =
            $("[data-employee-delete]");

        const closeButton =
            $("[data-employee-close]");


        if (editButton) {
            editButton.addEventListener(
                "click",
                () => {
                    if (detailEmployee) {
                        openEmployeeForm(
                            detailEmployee
                        );
                    }
                }
            );
        }


        if (deleteButton) {
            deleteButton.addEventListener(
                "click",
                deleteEmployee
            );
        }


        if (closeButton) {
            closeButton.addEventListener(
                "click",
                () => dialog.close()
            );
        }


        dialog.addEventListener(
            "click",
            e => {
                if (e.target === dialog) {
                    dialog.close();
                }
            }
        );


        $$("[data-tab]").forEach(btn => {
            btn.addEventListener(
                "click",
                () =>
                    loadTab(
                        btn.dataset.tab
                    )
            );
        });
    }


    /* =========================================================
       Create / Edit bindings
       ========================================================= */

    function bindCreate() {
        const newButton =
            $("[data-employee-new]");

        if (newButton) {
            newButton.addEventListener(
                "click",
                () => openEmployeeForm()
            );
        }


        const closeButton =
            $("[data-employee-create-close]");

        if (closeButton) {
            closeButton.addEventListener(
                "click",
                closeEmployeeForm
            );
        }


        const cancelButton =
            $("[data-employee-create-cancel]");

        if (cancelButton) {
            cancelButton.addEventListener(
                "click",
                closeEmployeeForm
            );
        }


        if (employeeForm) {
            employeeForm.addEventListener(
                "submit",
                submitEmployeeForm
            );
        }


        if (employeeOverlay) {
            employeeOverlay.addEventListener(
                "click",
                e => {
                    if (
                        e.target ===
                        employeeOverlay
                    ) {
                        closeEmployeeForm();
                    }
                }
            );
        }


        /*
         * Escape closes the employee form.
         */
        document.addEventListener(
            "keydown",
            e => {
                if (
                    e.key === "Escape" &&
                    employeeOverlay &&
                    !employeeOverlay.hidden
                ) {
                    closeEmployeeForm();
                }
            }
        );
    }


    /* =========================================================
       Filters
       ========================================================= */

    function bindFilters() {
        $$("[data-status-filter]")
            .forEach(btn => {
                btn.addEventListener(
                    "click",
                    () => {
                        state.statusFilter =
                            btn.dataset.statusFilter;

                        $$(
                            "[data-status-filter]"
                        ).forEach(button => {
                            button.classList.remove(
                                "active"
                            );
                        });

                        btn.classList.add(
                            "active"
                        );

                        renderRows();
                    }
                );
            });


        const searchInput =
            $("#employee-search-input");

        if (searchInput) {
            searchInput.addEventListener(
                "input",
                () => {
                    state.search =
                        searchInput.value;

                    renderRows();
                }
            );
        }
    }


    /* =========================================================
       Refresh
       ========================================================= */

    async function refresh() {
        state.employees =
            await fetchAll(API);

        state.assignments = [];

        renderMetrics();
        renderRows();
    }


    /* =========================================================
       Init
       ========================================================= */

    document.addEventListener(
        "DOMContentLoaded",
        async () => {
            bindDialog();
            bindCreate();
            bindFilters();

            const allButton =
                $(
                    "[data-status-filter='all']"
                );

            if (allButton) {
                allButton.classList.add(
                    "active"
                );
            }


            try {
                /*
                 * Only employees are loaded when the Workforce
                 * page opens.
                 *
                 * Projects are NOT loaded here anymore.
                 * They are loaded only when the user chooses
                 * Assign project or Phase assignments.
                 */
                await refresh();

            } catch (e) {
                const tbody =
                    $("[data-employee-rows]");

                if (tbody) {
                    tbody.innerHTML = `
                        <tr>
                            <td>
                                <strong>
                                    Could not load employees
                                </strong>

                                <span>
                                    ${esc(e.message)}
                                </span>
                            </td>

                            <td>—</td>
                            <td>—</td>
                            <td>—</td>
                            <td>—</td>
                        </tr>
                    `;
                }
            }
        }
    );

})();
