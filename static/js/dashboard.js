document.addEventListener("DOMContentLoaded", () => {
  const sidebar = document.querySelector("[data-sidebar]");
  document.querySelectorAll("[data-sidebar-open]").forEach((button) =>
    button.addEventListener("click", () => sidebar?.classList.add("sidebar-open")),
  );
  document.querySelectorAll("[data-sidebar-close]").forEach((button) =>
    button.addEventListener("click", () => sidebar?.classList.remove("sidebar-open")),
  );
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") sidebar?.classList.remove("sidebar-open");
  });

  // Topbar user-account dropdown (My profile / Log out).
  const userMenu = document.querySelector("[data-user-menu]");
  const userMenuToggle = document.querySelector("[data-user-menu-toggle]");
  const userMenuList = document.querySelector("[data-user-menu-list]");
  if (userMenu && userMenuToggle && userMenuList) {
    const closeUserMenu = () => {
      userMenuToggle.classList.remove("open");
      userMenuToggle.setAttribute("aria-expanded", "false");
      userMenuList.hidden = true;
    };
    userMenuToggle.addEventListener("click", (event) => {
      event.stopPropagation();
      const openNow = userMenuList.hidden;
      closeUserMenu();
      if (openNow) {
        userMenuToggle.classList.add("open");
        userMenuToggle.setAttribute("aria-expanded", "true");
        userMenuList.hidden = false;
        // Opening the account menu closes the notifications dropdown.
        const notifDropdown = document.querySelector("[data-notif-dropdown]");
        if (notifDropdown) notifDropdown.hidden = true;
      }
    });
    document.addEventListener("click", (event) => {
      if (!userMenu.contains(event.target)) closeUserMenu();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeUserMenu();
    });
  }

  if (!window.lucide) return;
  const icon = (element, name) => {
    if (element) element.innerHTML = `<i data-lucide="${name}"></i>`;
  };

  const brandMark = document.querySelector(".brand-mark");
  // Only inject the fallback icon when the sidebar has no uploaded logo
  // image, otherwise the JS would clobber the real logo on every load.
  if (brandMark && !brandMark.querySelector("img")) icon(brandMark, "hard-hat");
  icon(document.querySelector(".menu-button"), "menu");
  icon(document.querySelector(".icon-button"), "bell");

  icon(document.querySelector(".attention-icon"), "trending-down");
  ["folder-kanban", "building-2", "circle-dollar-sign", "file-text"].forEach((name, index) =>
    icon(document.querySelectorAll(".metric-top i")[index], name),
  );
  document.querySelectorAll(".primary-button").forEach((button) => {
    if (button.textContent.includes("＋")) {
      button.innerHTML = `<i data-lucide="plus"></i>${button.textContent.replace("＋", "").trim()}`;
    }
  });
  document.querySelectorAll(".milestone > b").forEach((node) => icon(node, "chevron-right"));
  window.lucide.createIcons({ attrs: { "aria-hidden": "true" } });
});
