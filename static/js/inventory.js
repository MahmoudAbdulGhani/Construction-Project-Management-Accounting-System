(() => {
    "use strict";

    // ============================================================
    // INVENTORY
    // ============================================================

    const API = "/api/inventory/";

    const $ = (selector) =>
        document.querySelector(selector);

    // ------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------

    const list = (data) => {
        if (Array.isArray(data)) {
            return data;
        }

        if (Array.isArray(data?.results)) {
            return data.results;
        }

        if (Array.isArray(data?.data)) {
            return data.data;
        }

        if (Array.isArray(data?.items)) {
            return data.items;
        }

        return [];
    };


    const esc = (value) =>
        String(value ?? "—").replace(
            /[&<>"']/g,
            (char) => ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;",
            })[char]
        );


    // Same escaping as esc(), but for pre-filling form field values --
    // esc()'s "—" fallback is meant for read-only table cells, and
    // showing that literal dash as an input's value (e.g. when adding
    // a new material) looks like leftover text the user has to
    // delete. Form fields should just start empty and rely on their
    // placeholder instead.
    const formValue = (value) =>
        esc(
            value === null || value === undefined
                ? ""
                : value
        );


    const money = (value) =>
        new Intl.NumberFormat(undefined, {
            style: "currency",
            currency: "USD",
            maximumFractionDigits: 0,
        }).format(Number(value || 0));


    const csrf = () => {
        const cookie = document.cookie
            .split("; ")
            .find((item) =>
                item.startsWith("csrftoken=")
            );

        if (!cookie) {
            return "";
        }

        return decodeURIComponent(
            cookie.split("=")[1] || ""
        );
    };


    // ============================================================
    // STATE
    // ============================================================

    let stocks = [];
    let materials = [];
    let warehouses = [];
    let categories = [];
    let movements = [];
    let currentUser = null;

    const PAGE_SIZE = 10;

    let currentPage = 1;


    // ============================================================
    // API REQUEST
    // ============================================================

    async function request(url, options = {}) {

        const response = await fetch(url, {
            credentials: "same-origin",

            ...options,

            headers: {
                Accept: "application/json",

                ...(options.method
                    ? {
                        "Content-Type":
                            "application/json",

                        "X-CSRFToken": csrf(),
                    }
                    : {}),

                ...options.headers,
            },
        });


        const data =
            await response
                .json()
                .catch(() => ({}));


        if (!response.ok) {

            let message =
                data?.detail ||
                data?.message ||
                "";

            if (!message && typeof data === "object") {
                message = Object.values(data)
                    .flat()
                    .join(" ");
            }

            throw new Error(
                message ||
                `Request failed (${response.status})`
            );
        }


        return data;
    }


    // ============================================================
    // SELECT OPTIONS
    // ============================================================

    const opts = (
        items,
        value,
        text,
        placeholder
    ) => {

        const safeItems =
            Array.isArray(items)
                ? items
                : [];

        return `
            <option value="">
                ${esc(placeholder)}
            </option>

            ${safeItems
                .map(
                    (item) => `
                        <option
                            value="${esc(item.id)}"
                            ${
                                String(item.id) ===
                                String(value)
                                    ? "selected"
                                    : ""
                            }
                        >
                            ${esc(text(item))}
                        </option>
                    `
                )
                .join("")}
        `;
    };


    // ============================================================
    // INVENTORY TABLE
    // ============================================================

    function render() {

        const searchInput =
            $("[data-inventory-search]");

        const warehouseSelect =
            $("[data-inventory-warehouse]");

        const stockSelect =
            $("[data-inventory-stock]");

        const categorySelect =
            $("[data-inventory-category]");

        const rowsContainer =
            $("[data-inventory-rows]");


        if (!rowsContainer) {
            return;
        }


        const query =
            searchInput
                ? searchInput.value
                    .trim()
                    .toLowerCase()
                : "";


        const warehouse =
            warehouseSelect
                ? warehouseSelect.value
                : "";


        const stockFilter =
            stockSelect
                ? stockSelect.value
                : "";


        const categoryFilterId =
            categorySelect
                ? categorySelect.value
                : "";


        // --------------------------------------------------------
        // FILTER
        // --------------------------------------------------------

        const rows =
            stocks.filter((stock) => {

                // Warehouse
                const matchesWarehouse =
                    !warehouse ||
                    String(stock.warehouse) ===
                    String(warehouse);


                // Stock status
                const matchesStock =
                    !stockFilter ||
                    (
                        stockFilter === "low"
                            ? Boolean(stock.is_low_stock)
                            : !Boolean(stock.is_low_stock)
                    );


                // Search
                const searchableText = [

                    stock.material_name,

                    stock.material_sku,

                    stock.warehouse_name,

                    stock.material,

                    stock.warehouse,

                ]
                    .filter(
                        (value) =>
                            value !== null &&
                            value !== undefined
                    )
                    .join(" ")
                    .toLowerCase();


                const matchesSearch =
                    !query ||
                    searchableText.includes(query);


                // Category
                const matchesCategory =
                    !categoryFilterId ||

                    (() => {

                        const material =
                            materials.find(
                                (item) =>
                                    String(item.id) ===
                                    String(stock.material)
                            );


                        return (
                            material &&
                            String(
                                material.category
                            ) ===
                            String(
                                categoryFilterId
                            )
                        );

                    })();


                return (
                    matchesWarehouse &&
                    matchesStock &&
                    matchesSearch &&
                    matchesCategory
                );

            });


        // --------------------------------------------------------
        // PAGINATION
        // --------------------------------------------------------

        const totalRows =
            rows.length;

        const totalPages =
            Math.max(
                1,
                Math.ceil(
                    totalRows / PAGE_SIZE
                )
            );


        if (currentPage > totalPages) {
            currentPage = totalPages;
        }


        if (currentPage < 1) {
            currentPage = 1;
        }


        const pageStart =
            (currentPage - 1) *
            PAGE_SIZE;


        const pageRows =
            rows.slice(
                pageStart,
                pageStart + PAGE_SIZE
            );

        document.querySelector(
            "[data-inventory-visible-count]"
        ).textContent = pageRows.length;

        document.querySelector(
            "[data-inventory-total-count]"
        ).textContent = totalRows;


        // --------------------------------------------------------
        // TABLE ROWS
        // --------------------------------------------------------

        if (!pageRows.length) {

            rowsContainer.innerHTML = `
                <tr>
                    <td colspan="8">
                        <strong>
                            No stock balances found.
                        </strong>
                    </td>
                </tr>
            `;

        } else {

            rowsContainer.innerHTML =

                pageRows
                    .map((stock) => {

                        const material =
                            materials.find(
                                (item) =>
                                    String(item.id) ===
                                    String(
                                        stock.material
                                    )
                            );


                        const statusClass =
                            stock.is_low_stock
                                ? "at-risk"
                                : "active";


                        const statusText =
                            stock.is_low_stock
                                ? "Low stock"
                                : "In stock";


                        return `
                            <tr>

                                <td>
                                    <strong>
                                        ${esc(
                                            stock.material_name
                                        )}
                                    </strong>

                                    <span>
                                        View details
                                    </span>
                                </td>


                                <td>
                                    ${esc(
                                        stock.material_sku
                                    )}
                                </td>


                                <td>
                                    ${esc(
                                        stock.warehouse_name
                                    )}
                                </td>


                                <td>
                                    ${esc(
                                        stock.quantity
                                    )}${
                                        material?.unit
                                            ? ` ${esc(material.unit)}`
                                            : ""
                                    }
                                </td>


                                <td>
                                    ${money(
                                        material?.standard_cost || 0
                                    )}
                                </td>


                                <td>
                                    ${esc(
                                        stock.minimum_stock_level
                                    )}
                                </td>


                                <td>

                                    <span
                                        class="status ${statusClass}"
                                    >

                                        <i></i>

                                        ${statusText}

                                    </span>

                                </td>


                                <td>

                                    <button
                                        class="quiet-button"
                                        type="button"
                                        data-movement-material="${esc(
                                            stock.material
                                        )}"
                                        data-movement-warehouse="${esc(
                                            stock.warehouse
                                        )}"
                                    >
                                        Record
                                    </button>

                                </td>

                            </tr>
                        `;

                    })
                    .join("");
        }


        // --------------------------------------------------------
        // FOOTER COUNT
        // --------------------------------------------------------

        const countEl =
            $("[data-inventory-count]");


        if (countEl) {

            countEl.textContent =
                `Showing ${pageRows.length} of ${totalRows} record${
                    totalRows === 1
                        ? ""
                        : "s"
                }`;

        }


        // --------------------------------------------------------
        // PREVIOUS BUTTON
        // --------------------------------------------------------

        const prevBtn =
            $("[data-inventory-prev]");


        if (prevBtn) {

            prevBtn.disabled =
                currentPage <= 1;

        }


        // --------------------------------------------------------
        // NEXT BUTTON
        // --------------------------------------------------------

        const nextBtn =
            $("[data-inventory-next]");


        if (nextBtn) {

            nextBtn.disabled =
                currentPage >= totalPages;

        }


        // --------------------------------------------------------
        // PAGE NUMBERS
        // --------------------------------------------------------

        const pagesEl =
            $("[data-inventory-pages]");


        if (pagesEl) {

            const pageNumbers = [];


            for (
                let page = 1;
                page <= totalPages;
                page += 1
            ) {

                const isEdge =
                    page === 1 ||
                    page === totalPages;


                const isNearCurrent =
                    Math.abs(
                        page - currentPage
                    ) <= 1;


                if (
                    isEdge ||
                    isNearCurrent
                ) {

                    pageNumbers.push(page);

                } else if (
                    pageNumbers[
                        pageNumbers.length - 1
                    ] !== "…"
                ) {

                    pageNumbers.push("…");

                }

            }


            pagesEl.innerHTML =
                pageNumbers
                    .map((page) => {

                        if (page === "…") {

                            return `
                                <span class="pagination-ellipsis">
                                    …
                                </span>
                            `;

                        }


                        return `
                            <button
                                type="button"
                                class="quiet-button ${
                                    page === currentPage
                                        ? "active"
                                        : ""
                                }"
                                data-page="${page}"
                            >
                                ${page}
                            </button>
                        `;

                    })
                    .join("");

        }


        // --------------------------------------------------------
        // METRICS
        // --------------------------------------------------------

        const itemsMetric =
            $("[data-inventory-metric=items]");


        const lowMetric =
            $("[data-inventory-metric=low]");


        const valueMetric =
            $("[data-inventory-metric=value]");


        const warehousesMetric =
            $("[data-inventory-metric=warehouses]");


        if (itemsMetric) {

            itemsMetric.textContent =
                materials.length;

        }


        if (lowMetric) {

            lowMetric.textContent =
                stocks.filter(
                    (stock) =>
                        Boolean(
                            stock.is_low_stock
                        )
                ).length;

        }


        if (valueMetric) {

            const inventoryValue =
                stocks.reduce(
                    (total, stock) => {

                        const material =
                            materials.find(
                                (item) =>
                                    String(item.id) ===
                                    String(
                                        stock.material
                                    )
                            );


                        const cost =
                            Number(
                                material?.standard_cost ||
                                0
                            );


                        return (
                            total +
                            Number(
                                stock.quantity || 0
                            ) *
                            cost
                        );

                    },
                    0
                );


            valueMetric.textContent =
                money(inventoryValue);

        }


        if (warehousesMetric) {

            warehousesMetric.textContent =
                warehouses.length;

        }

    }


    // ============================================================
    // FILTERS
    // ============================================================

    function applyFiltersAndRender() {

        currentPage = 1;

        render();

    }


    // ============================================================
    // MOVEMENTS
    // ============================================================

    const MOVEMENTS_DISPLAY_LIMIT = 25;

    function renderMovements() {

        const rowsContainer =
            $("[data-inventory-movement-rows]");


        const count =
            $("[data-inventory-movement-count]");


        if (!rowsContainer) {
            return;
        }


        const searchInput =
            $("[data-movement-search]");

        const typeSelect =
            $("[data-movement-type]");


        const query =
            searchInput
                ? searchInput.value
                    .trim()
                    .toLowerCase()
                : "";


        const typeFilter =
            typeSelect
                ? typeSelect.value
                : "";


        const dateFrom =
            $("[data-movement-date-from]")
                ?.value ||
            "";


        const dateTo =
            $("[data-movement-date-to]")
                ?.value ||
            "";


        // --------------------------------------------------------
        // FILTER
        // --------------------------------------------------------

        const filtered =
            movements.filter((movement) => {

                // In / Out
                const matchesType =
                    !typeFilter ||
                    movement.movement_type ===
                    typeFilter;


                // Search
                const searchableText = [

                    movement.material_name,

                    movement.warehouse_name,

                    movement.reference,

                ]
                    .filter(
                        (value) =>
                            value !== null &&
                            value !== undefined
                    )
                    .join(" ")
                    .toLowerCase();


                const matchesSearch =
                    !query ||
                    searchableText.includes(query);


                // Date -- "from" and "to" can each be applied on
                // their own or together.
                const matchesDate =
                    (!dateFrom && !dateTo) ||

                    !movement.movement_date ||

                    (() => {

                        const rowDate =
                            String(
                                movement.movement_date
                            ).slice(0, 10);


                        if (
                            dateFrom &&
                            rowDate < dateFrom
                        ) {
                            return false;
                        }


                        if (
                            dateTo &&
                            rowDate > dateTo
                        ) {
                            return false;
                        }


                        return true;

                    })();


                return (
                    matchesType &&
                    matchesSearch &&
                    matchesDate
                );

            });


        const recentMovements =

            [...filtered]

                .sort(
                    (a, b) =>
                        new Date(
                            b.movement_date || 0
                        ) -
                        new Date(
                            a.movement_date || 0
                        )
                )

                .slice(0, MOVEMENTS_DISPLAY_LIMIT);


        if (count) {

            count.textContent =
                `Showing ${recentMovements.length} of ${filtered.length} movement${
                    filtered.length === 1
                        ? ""
                        : "s"
                }`;

        }


        if (!recentMovements.length) {

            rowsContainer.innerHTML = `
                <tr>
                    <td colspan="6">
                        <strong>
                            No stock movements found.
                        </strong>
                    </td>
                </tr>
            `;

            return;
        }


        rowsContainer.innerHTML =

            recentMovements
                .map((movement) => {

                    const movementType =
                        movement.movement_type ||
                        "—";


                    const statusClass =
                        movementType === "OUT"
                            ? "at-risk"
                            : "active";


                    const date =
                        movement.movement_date
                            ? new Date(
                                movement.movement_date
                            ).toLocaleDateString()
                            : "—";


                    const material =
                        materials.find(
                            (item) =>
                                String(item.id) ===
                                String(
                                    movement.material
                                )
                        );


                    return `
                        <tr>

                            <td>
                                <strong>
                                    ${esc(
                                        movement.material_name
                                    )}
                                </strong>
                            </td>


                            <td>
                                ${esc(
                                    movement.warehouse_name
                                )}
                            </td>


                            <td>

                                <span
                                    class="status ${statusClass}"
                                >

                                    <i></i>

                                    ${esc(
                                        movementType
                                    )}

                                </span>

                            </td>


                            <td>
                                ${esc(
                                    movement.quantity
                                )}${
                                    material?.unit
                                        ? ` ${esc(material.unit)}`
                                        : ""
                                }
                            </td>


                            <td>
                                ${esc(
                                    movement.reference
                                )}
                            </td>


                            <td>
                                ${esc(date)}
                            </td>

                        </tr>
                    `;

                })
                .join("");

    }


    // ============================================================
    // LOAD INVENTORY
    // ============================================================

    async function loadInventory() {

        const [
            stockData,
            movementData
        ] = await Promise.all([

            request(
                `${API}stocks/?page_size=100`
            ),

            request(
                `${API}stock-movements/?page_size=100`
            ),

        ]);


        stocks =
            list(stockData);


        movements =
            list(movementData);


        console.log(
            "Inventory loaded:",
            {
                stocks: stocks.length,
                movements: movements.length,
                materials: materials.length,
                warehouses: warehouses.length,
                categories: categories.length,
            }
        );


        const today =
            new Date()
                .toISOString()
                .slice(0, 10);


        const transfersToday =
            movements.filter(
                (movement) =>
                    movement.movement_type ===
                    "TRANSFER" &&

                    movement.movement_date
                        ?.startsWith(today)
            ).length;


        const transfersMetric =
            $("[data-inventory-metric=transfers]");


        if (transfersMetric) {

            transfersMetric.textContent =
                transfersToday;

        }

    }


    // ============================================================
    // CURRENT USER
    // ============================================================

    async function loadCurrentUser() {

        try {

            currentUser =
                await request(
                    "/api/auth/me/"
                );


            return currentUser;

        } catch (error) {

            console.warn(
                "Could not load current user:",
                error.message
            );


            currentUser = null;

            return null;

        }

    }


    // ============================================================
    // MATERIAL MANAGEMENT
    // ============================================================

    function renderMaterialsManagement() {

        const container =
            $("[data-material-management-rows]");


        if (!container) {
            return;
        }


        const search =
            $("[data-material-management-search]")
                ?.value
                .trim()
                .toLowerCase() || "";


        const filtered =
            materials.filter((material) => {

                const category =
                    categories.find(
                        (item) =>
                            String(item.id) ===
                            String(
                                material.category
                            )
                    );


                const text = [

                    material.name,

                    material.sku,

                    category?.name,

                    material.unit,

                ]
                    .join(" ")
                    .toLowerCase();


                return (
                    !search ||
                    text.includes(search)
                );

            });


        if (!filtered.length) {

            container.innerHTML = `
                <tr>
                    <td colspan="8">
                        <strong>
                            No materials found.
                        </strong>
                    </td>
                </tr>
            `;

            return;
        }


        container.innerHTML =

            filtered
                .map((material) => {

                    const category =
                        categories.find(
                            (item) =>
                                String(item.id) ===
                                String(
                                    material.category
                                )
                        );


                    const active =
                        material.is_active !== false;


                    return `
                        <tr>

                            <td>

                                <strong>
                                    ${esc(
                                        material.name
                                    )}
                                </strong>

                                ${
                                    material.description
                                        ? `
                                            <span>
                                                ${esc(
                                                    material.description
                                                )}
                                            </span>
                                        `
                                        : ""
                                }

                            </td>


                            <td>
                                ${esc(
                                    material.sku
                                )}
                            </td>


                            <td>
                                ${esc(
                                    category?.name ||
                                    material.category_name ||
                                    "—"
                                )}
                            </td>


                            <td>
                                ${esc(
                                    material.unit
                                )}
                            </td>


                            <td>
                                ${money(
                                    material.standard_cost
                                )}
                            </td>


                            <td>
                                ${esc(
                                    material.minimum_stock_level
                                )}
                            </td>


                            <td>

                                <span
                                    class="status ${
                                        active
                                            ? "active"
                                            : "at-risk"
                                    }"
                                >

                                    <i></i>

                                    ${
                                        active
                                            ? "Active"
                                            : "Inactive"
                                    }

                                </span>

                            </td>


                            <td>

                                <div
                                    class="inventory-row-actions"
                                >

                                    <button
                                        type="button"
                                        class="quiet-button"
                                        data-edit-material="${esc(
                                            material.id
                                        )}"
                                    >
                                        Edit
                                    </button>


                                    <button
                                        type="button"
                                        class="quiet-button danger-button"
                                        data-delete-material="${esc(
                                            material.id
                                        )}"
                                    >
                                        Delete
                                    </button>

                                </div>

                            </td>

                        </tr>
                    `;

                })
                .join("");

    }


    // ============================================================
    // CATEGORY MANAGEMENT
    // ============================================================

    function renderCategoriesManagement() {

        const container =
            $("[data-category-management-rows]");


        if (!container) {
            return;
        }


        const search =
            $("[data-category-management-search]")
                ?.value
                .trim()
                .toLowerCase() || "";


        const filtered =
            categories.filter((category) => {

                const text = [

                    category.name,

                    category.description,

                ]
                    .join(" ")
                    .toLowerCase();


                return (
                    !search ||
                    text.includes(search)
                );

            });


        if (!filtered.length) {

            container.innerHTML = `
                <tr>
                    <td colspan="3">
                        <strong>
                            No categories found.
                        </strong>
                    </td>
                </tr>
            `;

            return;
        }


        container.innerHTML =

            filtered
                .map((category) => {

                    return `
                        <tr>

                            <td>

                                <strong>
                                    ${esc(
                                        category.name
                                    )}
                                </strong>

                            </td>


                            <td>
                                ${esc(
                                    category.description
                                )}
                            </td>


                            <td>

                                <div
                                    class="inventory-row-actions"
                                >

                                    <button
                                        type="button"
                                        class="quiet-button"
                                        data-edit-category="${esc(
                                            category.id
                                        )}"
                                    >
                                        Edit
                                    </button>


                                    <button
                                        type="button"
                                        class="quiet-button danger-button"
                                        data-delete-category="${esc(
                                            category.id
                                        )}"
                                    >
                                        Delete
                                    </button>

                                </div>

                            </td>

                        </tr>
                    `;

                })
                .join("");

    }


    // ============================================================
    // WAREHOUSE MANAGEMENT
    // ============================================================

    function renderWarehousesManagement() {

        const container =
            $("[data-warehouse-management-rows]");


        if (!container) {
            return;
        }


        const search =
            $("[data-warehouse-management-search]")
                ?.value
                .trim()
                .toLowerCase() || "";


        const filtered =
            warehouses.filter((warehouse) => {

                const text = [

                    warehouse.name,

                    warehouse.location,

                ]
                    .join(" ")
                    .toLowerCase();


                return (
                    !search ||
                    text.includes(search)
                );

            });


        if (!filtered.length) {

            container.innerHTML = `
                <tr>
                    <td colspan="3">
                        <strong>
                            No warehouses found.
                        </strong>
                    </td>
                </tr>
            `;

            return;
        }


        container.innerHTML =

            filtered
                .map((warehouse) => {

                    return `
                        <tr>

                            <td>

                                <strong>
                                    ${esc(
                                        warehouse.name
                                    )}
                                </strong>

                            </td>


                            <td>
                                ${esc(
                                    warehouse.location
                                )}
                            </td>


                            <td>

                                <div
                                    class="inventory-row-actions"
                                >

                                    <button
                                        type="button"
                                        class="quiet-button"
                                        data-edit-warehouse="${esc(
                                            warehouse.id
                                        )}"
                                    >
                                        Edit
                                    </button>


                                    <button
                                        type="button"
                                        class="quiet-button danger-button"
                                        data-delete-warehouse="${esc(
                                            warehouse.id
                                        )}"
                                    >
                                        Delete
                                    </button>

                                </div>

                            </td>

                        </tr>
                    `;

                })
                .join("");

    }


    function renderInventoryManagement() {

        renderMaterialsManagement();

        renderCategoriesManagement();

        renderWarehousesManagement();

    }


    // ============================================================
    // FILTER POPOVERS
    // ============================================================

    function closeAllPopovers() {

        document
            .querySelectorAll(
                ".filter-popover"
            )
            .forEach((popover) => {

                popover.hidden = true;

                popover.classList.remove(
                    "is-open"
                );


                const anchor =
                    popover.closest(
                        ".filter-popover-anchor"
                    );


                const button =
                    anchor?.querySelector(
                        "[aria-haspopup]"
                    );


                button?.setAttribute(
                    "aria-expanded",
                    "false"
                );

            });

    }


    function togglePopover(
        buttonSelector,
        popoverSelector
    ) {

        const button =
            $(buttonSelector);


        const popover =
            $(popoverSelector);


        if (!button || !popover) {
            console.warn(
                "Inventory popover not found:",
                {
                    buttonSelector,
                    popoverSelector,
                }
            );

            return;
        }


        button.addEventListener(
            "click",
            (event) => {

                event.preventDefault();

                event.stopPropagation();


                const isOpen =
                    popover.classList.contains(
                        "is-open"
                    ) ||
                    !popover.hidden;


                closeAllPopovers();


                if (!isOpen) {

                    popover.hidden = false;

                    popover.classList.add(
                        "is-open"
                    );


                    button.setAttribute(
                        "aria-expanded",
                        "true"
                    );

                }

            }
        );


        popover.addEventListener(
            "click",
            (event) => {

                event.stopPropagation();

            }
        );

    }


    // ============================================================
    // DIALOG
    // ============================================================

    function openDialog(
        kind,
        preset = {}
    ) {

        const dialog =
            $("[data-inventory-dialog]");


        const fields =
            $("[data-inventory-fields]");


        if (!dialog || !fields) {
            return;
        }


        dialog.dataset.kind =
            kind;


        dialog.dataset.id =
            preset.id || "";


        $("[data-inventory-error]")
            .textContent = "";


        // --------------------------------------------------------
        // MATERIAL
        // --------------------------------------------------------

        if (kind === "material") {

            const editing =
                Boolean(preset.id);


            $("[data-inventory-title]")
                .textContent =
                    editing
                        ? "Edit material"
                        : "Add material";


            $("[data-inventory-submit]")
                .textContent =
                    editing
                        ? "Save changes"
                        : "Create material";


            fields.innerHTML = `

                <label>

                    Material name

                    <input
                        name="name"
                        value="${formValue(
                            preset.name
                        )}"
                        placeholder="e.g. Portland Cement"
                        required
                    >

                </label>


                <label>

                    SKU

                    <input
                        name="sku"
                        value="${formValue(
                            preset.sku
                        )}"
                        placeholder="e.g. CEM-001"
                        required
                    >

                </label>


                <label>

                    Category

                    <select
                        name="category"
                        required
                    >

                        ${opts(
                            categories,
                            preset.category || "",
                            (item) => item.name,
                            "Select category"
                        )}

                    </select>

                </label>


                <label>

                    Unit

                    <input
                        name="unit"
                        value="${formValue(
                            preset.unit
                        )}"
                        placeholder="e.g. bag, kg, m"
                        required
                    >

                </label>


                <label>

                    Description

                    <input
                        name="description"
                        value="${formValue(
                            preset.description
                        )}"
                        placeholder="Optional description"
                    >

                </label>


                <label>

                    Standard cost

                    <input
                        name="standard_cost"
                        type="number"
                        min="0"
                        step="0.01"
                        value="${formValue(
                            preset.standard_cost
                        )}"
                        placeholder="0.00"
                    >

                </label>


                <label>

                    Minimum stock

                    <input
                        name="minimum_stock_level"
                        type="number"
                        min="0"
                        step="0.001"
                        value="${formValue(
                            preset.minimum_stock_level ??
                            0
                        )}"
                    >

                </label>


                <label>

                    Status

                    <select name="is_active">

                        <option
                            value="true"
                            ${
                                preset.is_active !== false
                                    ? "selected"
                                    : ""
                            }
                        >
                            Active
                        </option>


                        <option
                            value="false"
                            ${
                                preset.is_active === false
                                    ? "selected"
                                    : ""
                            }
                        >
                            Inactive
                        </option>

                    </select>

                </label>

            `;

        }


        // --------------------------------------------------------
        // CATEGORY
        // --------------------------------------------------------

        else if (kind === "category") {

            const editing =
                Boolean(preset.id);


            $("[data-inventory-title]")
                .textContent =
                    editing
                        ? "Edit category"
                        : "Add category";


            $("[data-inventory-submit]")
                .textContent =
                    editing
                        ? "Save changes"
                        : "Create category";


            fields.innerHTML = `

                <label>

                    Category name

                    <input
                        name="name"
                        value="${formValue(
                            preset.name
                        )}"
                        placeholder="e.g. Electrical"
                        required
                    >

                </label>


                <label>

                    Description

                    <input
                        name="description"
                        value="${formValue(
                            preset.description
                        )}"
                        placeholder="Optional description"
                    >

                </label>

            `;

        }


        // --------------------------------------------------------
        // WAREHOUSE
        // --------------------------------------------------------

        else if (kind === "warehouse") {

            const editing =
                Boolean(preset.id);


            $("[data-inventory-title]")
                .textContent =
                    editing
                        ? "Edit warehouse"
                        : "Add warehouse";


            $("[data-inventory-submit]")
                .textContent =
                    editing
                        ? "Save changes"
                        : "Create warehouse";


            fields.innerHTML = `

                <label>

                    Warehouse name

                    <input
                        name="name"
                        value="${formValue(
                            preset.name
                        )}"
                        placeholder="e.g. Main Warehouse"
                        required
                    >

                </label>


                <label>

                    Location

                    <input
                        name="location"
                        value="${formValue(
                            preset.location
                        )}"
                        placeholder="e.g. 123 Site Road, Bay 3"
                        required
                    >

                </label>

            `;

        }


        // --------------------------------------------------------
        // MOVEMENT
        // --------------------------------------------------------

        else if (kind === "movement") {

            $("[data-inventory-title]")
                .textContent =
                    "Record movement";


            $("[data-inventory-submit]")
                .textContent =
                    "Record movement";


            fields.innerHTML = `

                <label>

                    Material

                    <select
                        name="material"
                        required
                    >

                        ${opts(
                            materials,
                            preset.material || "",
                            (item) =>
                                `${item.name} (${item.sku || "No SKU"})`,
                            "Select material"
                        )}

                    </select>

                </label>


                <label>

                    Movement type

                    <select
                        name="movement_type"
                        required
                    >

                        <option value="IN">
                            Stock in
                        </option>

                        <option value="OUT">
                            Stock out
                        </option>

                        <option value="TRANSFER">
                            Transfer
                        </option>

                    </select>

                </label>


                <label>

                    Quantity

                    <input
                        name="quantity"
                        type="number"
                        min="0"
                        step="0.001"
                        required
                    >

                </label>


                <label>

                    Warehouse

                    <select
                        name="warehouse"
                        required
                    >

                        ${opts(
                            warehouses,
                            preset.warehouse || "",
                            (item) => item.name,
                            "Select warehouse"
                        )}

                    </select>

                </label>


                <label data-source>

                    Reference

                    <input
                        name="reference"
                        placeholder="Optional reference"
                    >

                </label>


                <div
                    data-transfer
                    hidden
                >

                    <label>

                        From warehouse

                        <select
                            name="from_warehouse"
                        >

                            ${opts(
                                warehouses,
                                "",
                                (item) => item.name,
                                "Select source warehouse"
                            )}

                        </select>

                    </label>


                    <label>

                        To warehouse

                        <select
                            name="to_warehouse"
                        >

                            ${opts(
                                warehouses,
                                "",
                                (item) => item.name,
                                "Select destination warehouse"
                            )}

                        </select>

                    </label>

                </div>

            `;


            const movementType =
                fields.querySelector(
                    "[name=movement_type]"
                );


            movementType?.addEventListener(
                "change",
                () => {

                    const transfer =
                        movementType.value ===
                        "TRANSFER";


                    const source =
                        fields.querySelector(
                            "[data-source]"
                        );


                    const warehouse =
                        fields.querySelector(
                            "[name=warehouse]"
                        );


                    const transferFields =
                        fields.querySelectorAll(
                            "[data-transfer]"
                        );


                    if (source) {
                        source.hidden =
                            transfer;
                    }


                    transferFields.forEach(
                        (field) => {

                            field.hidden =
                                !transfer;

                        }
                    );


                    if (warehouse) {

                        warehouse.required =
                            !transfer;

                    }


                    fields
                        .querySelectorAll(
                            "[name=from_warehouse],[name=to_warehouse]"
                        )
                        .forEach(
                            (field) => {

                                field.required =
                                    transfer;

                            }
                        );

                }
            );

        }


        if (
            typeof dialog.showModal ===
            "function"
        ) {

            dialog.showModal();

        } else {

            dialog.setAttribute(
                "open",
                ""
            );

        }

    }


    // ============================================================
    // SUBMIT FORM
    // ============================================================

    async function submitForm(event) {

        event.preventDefault();


        const form =
            event.currentTarget;


        const dialog =
            $("[data-inventory-dialog]");


        const kind =
            dialog.dataset.kind;


        const id =
            dialog.dataset.id;


        const data =
            Object.fromEntries(
                new FormData(form)
            );


        Object.keys(data).forEach((key) => {

            if (data[key] === "") {

                delete data[key];

            }

        });


        const error =
            $("[data-inventory-error]");


        const submit =
            $("[data-inventory-submit]");


        error.textContent = "";

        submit.disabled = true;


        try {

            // ----------------------------------------------------
            // MATERIAL
            // ----------------------------------------------------

            if (kind === "material") {

                data.is_active =
                    data.is_active !== "false";


                const url =
                    id
                        ? `${API}materials/${id}/`
                        : `${API}materials/`;


                await request(
                    url,
                    {

                        method:
                            id
                                ? "PATCH"
                                : "POST",

                        body:
                            JSON.stringify(data),

                    }
                );

            }


            // ----------------------------------------------------
            // WAREHOUSE
            // ----------------------------------------------------

            else if (
                kind === "warehouse"
            ) {

                const url =
                    id
                        ? `${API}warehouses/${id}/`
                        : `${API}warehouses/`;


                await request(
                    url,
                    {

                        method:
                            id
                                ? "PATCH"
                                : "POST",

                        body:
                            JSON.stringify(data),

                    }
                );

            }


            // ----------------------------------------------------
            // CATEGORY
            // ----------------------------------------------------

            else if (
                kind === "category"
            ) {

                const url =
                    id
                        ? `${API}material-categories/${id}/`
                        : `${API}material-categories/`;


                await request(
                    url,
                    {

                        method:
                            id
                                ? "PATCH"
                                : "POST",

                        body:
                            JSON.stringify(data),

                    }
                );

            }


            // ----------------------------------------------------
            // TRANSFER
            // ----------------------------------------------------

            else if (
                data.movement_type ===
                "TRANSFER"
            ) {

                if (!currentUser) {

                    currentUser =
                        await loadCurrentUser();

                }


                if (!currentUser?.id) {

                    throw new Error(
                        "Could not identify the current user. Please fix the /api/auth/me/ endpoint before recording movements."
                    );

                }


                data.user =
                    currentUser.id;


                data.quantity =
                    Math.abs(
                        Number(
                            data.quantity
                        )
                    );


                delete data.warehouse;

                delete data.movement_type;


                await request(
                    `${API}stock-movements/transfer/`,
                    {

                        method: "POST",

                        body:
                            JSON.stringify(data),

                    }
                );

            }


            // ----------------------------------------------------
            // IN / OUT MOVEMENT
            // ----------------------------------------------------

            else {

                if (!currentUser) {

                    currentUser =
                        await loadCurrentUser();

                }


                if (!currentUser?.id) {

                    throw new Error(
                        "Could not identify the current user. Please fix the /api/auth/me/ endpoint before recording movements."
                    );

                }


                data.user =
                    currentUser.id;


                if (
                    data.movement_type ===
                    "OUT"
                ) {

                    data.quantity =
                        -Math.abs(
                            Number(
                                data.quantity
                            )
                        );

                } else {

                    data.quantity =
                        Math.abs(
                            Number(
                                data.quantity
                            )
                        );

                }


                await request(
                    `${API}stock-movements/`,
                    {

                        method: "POST",

                        body:
                            JSON.stringify(data),

                    }
                );

            }


            // ----------------------------------------------------
            // REFRESH
            // ----------------------------------------------------

            dialog.close();

            form.reset();


            await loadReferenceData();


            renderInventoryManagement();


            await loadInventory();

        } catch (err) {

            console.error(
                "Inventory form submission failed:",
                err
            );


            error.textContent =
                err.message;

        } finally {

            submit.disabled = false;

        }

    }


    // ============================================================
    // DELETE
    // ============================================================

    async function deleteInventoryItem(
        endpoint,
        id,
        type
    ) {

        const confirmed =
            window.confirm(
                `Are you sure you want to delete this ${type}?`
            );


        if (!confirmed) {
            return;
        }


        try {

            await request(
                `${API}${endpoint}/${id}/`,
                {
                    method: "DELETE",
                }
            );


            await loadReferenceData();


            renderInventoryManagement();


            await loadInventory();

        } catch (error) {

            console.error(
                `Could not delete ${type}:`,
                error
            );


            window.alert(
                `Could not delete ${type}: ${error.message}`
            );

        }

    }


    // ============================================================
    // LOAD REFERENCE DATA
    // ============================================================

    async function loadReferenceData() {

        const [
            materialsData,
            warehousesData,
            categoriesData
        ] = await Promise.all([

            request(
                `${API}materials/?page_size=100`
            ),

            request(
                `${API}warehouses/?page_size=100`
            ),

            request(
                `${API}material-categories/?page_size=100`
            ),

        ]);


        materials =
            list(materialsData);


        warehouses =
            list(warehousesData);


        categories =
            list(categoriesData);


        // --------------------------------------------------------
        // WAREHOUSE FILTER
        // --------------------------------------------------------

        const warehouseFilter =
            $("[data-inventory-warehouse]");


        if (warehouseFilter) {

            const currentValue =
                warehouseFilter.value;


            warehouseFilter.innerHTML =
                opts(
                    warehouses,
                    currentValue,
                    (item) => item.name,
                    "Store: All"
                );

        }


        // --------------------------------------------------------
        // CATEGORY FILTER
        // --------------------------------------------------------

        const categoryFilterSelect =
            $("[data-inventory-category]");


        if (categoryFilterSelect) {

            const currentCategoryValue =
                categoryFilterSelect.value;


            categoryFilterSelect.innerHTML =
                opts(
                    categories,
                    currentCategoryValue,
                    (item) => item.name,
                    "Category: All"
                );

        }

    }


    // ============================================================
    // DOM READY
    // ============================================================

    document.addEventListener(
        "DOMContentLoaded",
        async () => {

            console.log(
                "Inventory JS initialized"
            );


            // ----------------------------------------------------
            // LOAD DATA
            // ----------------------------------------------------

            try {

                // Fire every list request at once instead of waiting on
                // reference data before requesting stocks/movements --
                // these don't actually depend on each other, so loading
                // them in parallel cuts the wait roughly in half.
                await Promise.all([
                    loadReferenceData(),
                    loadInventory(),
                ]);


                renderInventoryManagement();

                render();

                renderMovements();

            } catch (error) {

                console.error(
                    "Inventory loading failed:",
                    error
                );


                const errorRow =
                    (colspan, label) => `
                        <tr>
                            <td colspan="${colspan}">
                                <strong>
                                    Could not load ${esc(
                                        label
                                    )}: ${esc(
                                        error.message
                                    )}
                                </strong>
                            </td>
                        </tr>
                    `;


                const targets = [

                    [
                        "[data-inventory-rows]",
                        8,
                        "inventory"
                    ],

                    [
                        "[data-inventory-movement-rows]",
                        6,
                        "movements"
                    ],

                    [
                        "[data-material-management-rows]",
                        8,
                        "materials"
                    ],

                    [
                        "[data-category-management-rows]",
                        3,
                        "categories"
                    ],

                    [
                        "[data-warehouse-management-rows]",
                        3,
                        "warehouses"
                    ],

                ];


                targets.forEach(
                    ([selector, colspan, label]) => {

                        const el =
                            $(selector);


                        if (el) {

                            el.innerHTML =
                                errorRow(
                                    colspan,
                                    label
                                );

                        }

                    }
                );

            }


            // ====================================================
            // SEARCH
            // ====================================================

            $("[data-inventory-search]")
                ?.addEventListener(
                    "input",
                    applyFiltersAndRender
                );


            // ====================================================
            // WAREHOUSE FILTER
            // ====================================================

            $("[data-inventory-warehouse]")
                ?.addEventListener(
                    "change",
                    applyFiltersAndRender
                );


            // ====================================================
            // STOCK FILTER
            // ====================================================

            $("[data-inventory-stock]")
                ?.addEventListener(
                    "change",
                    applyFiltersAndRender
                );


            // ====================================================
            // CATEGORY FILTER
            // ====================================================

            $("[data-inventory-category]")
                ?.addEventListener(
                    "change",
                    applyFiltersAndRender
                );


            // ====================================================
            // PAGINATION
            // ====================================================

            $("[data-inventory-prev]")
                ?.addEventListener(
                    "click",
                    () => {

                        if (
                            currentPage > 1
                        ) {

                            currentPage -= 1;

                            render();

                        }

                    }
                );


            $("[data-inventory-next]")
                ?.addEventListener(
                    "click",
                    () => {

                        currentPage += 1;

                        render();

                    }
                );


            $("[data-inventory-pages]")
                ?.addEventListener(
                    "click",
                    (event) => {

                        const button =
                            event.target.closest(
                                "[data-page]"
                            );


                        if (!button) {
                            return;
                        }


                        currentPage =
                            Number(
                                button.dataset.page
                            );


                        render();

                    }
                );


            // ====================================================
            // MOVEMENT SEARCH
            // ====================================================

            $("[data-movement-search]")
                ?.addEventListener(
                    "input",
                    renderMovements
                );


            // ====================================================
            // MOVEMENT TYPE FILTER (In / Out)
            // ====================================================

            $("[data-movement-type]")
                ?.addEventListener(
                    "change",
                    renderMovements
                );


            // ====================================================
            // MOVEMENT DATE FILTERS (From / To -- either or both)
            // ====================================================

            $("[data-movement-date-from]")
                ?.addEventListener(
                    "change",
                    renderMovements
                );


            $("[data-movement-date-to]")
                ?.addEventListener(
                    "change",
                    renderMovements
                );


            document.addEventListener(
                "click",
                () => {

                    closeAllPopovers();

                }
            );


            document.addEventListener(
                "keydown",
                (event) => {

                    if (
                        event.key ===
                        "Escape"
                    ) {

                        closeAllPopovers();

                    }

                }
            );


            // ====================================================
            // TOP ACTION BUTTONS
            // ====================================================

            document
                .querySelectorAll(
                    "[data-inventory-action]"
                )
                .forEach((button) => {

                    button.addEventListener(
                        "click",
                        () => {

                            openDialog(
                                button.dataset
                                    .inventoryAction
                            );

                        }
                    );

                });


            // ====================================================
            // RECORD MOVEMENT
            // ====================================================

            $("[data-inventory-rows]")
                ?.addEventListener(
                    "click",
                    (event) => {

                        const button =
                            event.target.closest(
                                "[data-movement-material]"
                            );


                        if (!button) {
                            return;
                        }


                        openDialog(
                            "movement",
                            {

                                material:
                                    button.dataset
                                        .movementMaterial,

                                warehouse:
                                    button.dataset
                                        .movementWarehouse,

                            }
                        );

                    }
                );


            // ====================================================
            // DIALOG CANCEL
            // ====================================================

            $("[data-inventory-cancel]")
                ?.addEventListener(
                    "click",
                    () => {

                        const dialog =
                            $(
                                "[data-inventory-dialog]"
                            );


                        if (dialog) {

                            dialog.close();

                        }

                    }
                );


            // ====================================================
            // DIALOG SUBMIT
            // ====================================================

            $("[data-inventory-form]")
                ?.addEventListener(
                    "submit",
                    submitForm
                );


            // ====================================================
            // MANAGEMENT SEARCH
            // ====================================================

            $("[data-material-management-search]")
                ?.addEventListener(
                    "input",
                    renderMaterialsManagement
                );


            $("[data-category-management-search]")
                ?.addEventListener(
                    "input",
                    renderCategoriesManagement
                );


            $("[data-warehouse-management-search]")
                ?.addEventListener(
                    "input",
                    renderWarehousesManagement
                );


            // ====================================================
            // MANAGEMENT TABS
            // ====================================================

            document
                .querySelectorAll(
                    "[data-inventory-management-tab]"
                )
                .forEach((button) => {

                    button.addEventListener(
                        "click",
                        () => {

                            const target =
                                button.dataset
                                    .inventoryManagementTab;


                            document
                                .querySelectorAll(
                                    "[data-inventory-management-tab]"
                                )
                                .forEach(
                                    (item) => {

                                        item.classList.remove(
                                            "active"
                                        );

                                    }
                                );


                            document
                                .querySelectorAll(
                                    "[data-inventory-management-content]"
                                )
                                .forEach(
                                    (content) => {

                                        content.classList.remove(
                                            "active"
                                        );

                                    }
                                );


                            button.classList.add(
                                "active"
                            );


                            $(
                                `[data-inventory-management-content="${target}"]`
                            )?.classList.add(
                                "active"
                            );

                        }
                    );

                });


            // ====================================================
            // EDIT / DELETE ACTIONS
            // ====================================================

            document.addEventListener(
                "click",
                async (event) => {

                    const target =
                        event.target;


                    if (
                        !(target instanceof Element)
                    ) {
                        return;
                    }


                    // ------------------------------------------------
                    // EDIT MATERIAL
                    // ------------------------------------------------

                    const editMaterial =
                        target.closest(
                            "[data-edit-material]"
                        );


                    if (editMaterial) {

                        const material =
                            materials.find(
                                (item) =>
                                    String(
                                        item.id
                                    ) ===
                                    String(
                                        editMaterial
                                            .dataset
                                            .editMaterial
                                    )
                            );


                        if (material) {

                            openDialog(
                                "material",
                                material
                            );

                        }


                        return;

                    }


                    // ------------------------------------------------
                    // EDIT CATEGORY
                    // ------------------------------------------------

                    const editCategory =
                        target.closest(
                            "[data-edit-category]"
                        );


                    if (editCategory) {

                        const category =
                            categories.find(
                                (item) =>
                                    String(
                                        item.id
                                    ) ===
                                    String(
                                        editCategory
                                            .dataset
                                            .editCategory
                                    )
                            );


                        if (category) {

                            openDialog(
                                "category",
                                category
                            );

                        }


                        return;

                    }


                    // ------------------------------------------------
                    // EDIT WAREHOUSE
                    // ------------------------------------------------

                    const editWarehouse =
                        target.closest(
                            "[data-edit-warehouse]"
                        );


                    if (editWarehouse) {

                        const warehouse =
                            warehouses.find(
                                (item) =>
                                    String(
                                        item.id
                                    ) ===
                                    String(
                                        editWarehouse
                                            .dataset
                                            .editWarehouse
                                    )
                            );


                        if (warehouse) {

                            openDialog(
                                "warehouse",
                                warehouse
                            );

                        }


                        return;

                    }


                    // ------------------------------------------------
                    // DELETE MATERIAL
                    // ------------------------------------------------

                    const deleteMaterial =
                        target.closest(
                            "[data-delete-material]"
                        );


                    if (deleteMaterial) {

                        await deleteInventoryItem(
                            "materials",
                            deleteMaterial.dataset
                                .deleteMaterial,
                            "material"
                        );


                        return;

                    }


                    // ------------------------------------------------
                    // DELETE CATEGORY
                    // ------------------------------------------------

                    const deleteCategory =
                        target.closest(
                            "[data-delete-category]"
                        );


                    if (deleteCategory) {

                        await deleteInventoryItem(
                            "material-categories",
                            deleteCategory.dataset
                                .deleteCategory,
                            "category"
                        );


                        return;

                    }


                    // ------------------------------------------------
                    // DELETE WAREHOUSE
                    // ------------------------------------------------

                    const deleteWarehouse =
                        target.closest(
                            "[data-delete-warehouse]"
                        );


                    if (deleteWarehouse) {

                        await deleteInventoryItem(
                            "warehouses",
                            deleteWarehouse.dataset
                                .deleteWarehouse,
                            "warehouse"
                        );

                    }

                }
            );

        }

    );

})();