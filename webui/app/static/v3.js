(() => {
  "use strict";

  const body = document.body;
  if (!body || !body.classList.contains("ui-v3")) return;

  const icons = {
    overview: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 13h6V4H4v9Zm0 7h6v-4H4v4Zm10 0h6v-9h-6v9Zm0-16v4h6V4h-6Z"/></svg>',
    library: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5v-13Zm3 1.5v3h3V7H7Zm7 0v3h3V7h-3ZM7 14v3h3v-3H7Zm7 0v3h3v-3h-3Z"/></svg>',
    queue: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5h14v3H5V5Zm0 5.5h14v3H5v-3ZM5 16h9v3H5v-3Zm12 0 4 1.5-4 1.5v-3Z"/></svg>',
    automate: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.8 14 7l4.6.7-3.3 3.2.8 4.6-4.1-2.2-4.1 2.2.8-4.6-3.3-3.2L10 7l2-4.2Zm-7 14.7h6V20H5v-2.5Zm9 0h5V20h-5v-2.5Z"/></svg>',
    wizard: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15.7 3.3 5 5-12.4 12.4-5-5L15.7 3.3Zm0 3.5-8.9 8.9 1.5 1.5 8.9-8.9-1.5-1.5ZM5 3l.7 1.8L7.5 5.5l-1.8.7L5 8l-.7-1.8-1.8-.7 1.8-.7L5 3Zm3.5 2.5.5 1.2 1.2.5-1.2.5-.5 1.3L8 7.7l-1.2-.5L8 6.7l.5-1.2Z"/></svg>',
    settings: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.6 2h2.8l.6 2.2c.5.2 1 .5 1.5.9l2.2-.7 1.4 2.4-1.7 1.6c.1.5.1 1.1 0 1.6l1.7 1.6-1.4 2.4-2.2-.7c-.5.4-1 .7-1.5.9l-.6 2.2h-2.8l-.6-2.2c-.5-.2-1-.5-1.5-.9l-2.2.7-1.4-2.4L6.6 10a8.2 8.2 0 0 1 0-1.6L4.9 6.8l1.4-2.4 2.2.7c.5-.4 1-.7 1.5-.9l.6-2.2ZM12 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z"/></svg>',
    search: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.5 4a6.5 6.5 0 1 0 3.9 11.7l4 4 1.4-1.4-4-4A6.5 6.5 0 0 0 10.5 4Zm0 2a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9Z"/></svg>',
    plus: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6V5Z"/></svg>',
    switch: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7h10l-2.5-2.5L16 3l5 5-5 5-1.5-1.5L17 9H7V7Zm10 10H7l2.5 2.5L8 21l-5-5 5-5 1.5 1.5L7 15h10v2Z"/></svg>'
  };

  const routes = [
    { href: "/", label: "Overview", icon: "overview", match: path => path === "/" },
    { href: "/library", label: "Library", icon: "library", match: path => path.startsWith("/library") },
    { href: "/jobs", label: "Queue", icon: "queue", match: path => path.startsWith("/jobs") },
    { href: "/autopilot", label: "Automate", icon: "automate", match: path => path.startsWith("/autopilot") },
    { href: "/size_wizard", label: "Size Wizard", icon: "wizard", match: path => path.startsWith("/size_wizard") },
    { href: "/settings", label: "Settings", icon: "settings", match: path => path.startsWith("/settings") }
  ];

  const currentPath = window.location.pathname;
  const currentRoute = routes.find(route => route.match(currentPath)) || routes[0];
  const release = body.dataset.release || "Beta";

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, character => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    })[character]);
  }

  function decorateNavigation() {
    const nav = document.querySelector(".app-nav");
    if (!nav) return;

    const brand = nav.querySelector(".app-brand");
    if (brand) {
      brand.setAttribute("aria-label", "ByteSqueeze overview");
      brand.innerHTML = '<span class="brand-mark">B3</span><span class="brand-copy"><strong>ByteSqueeze</strong><span>Cinema operations</span></span>';
    }

    nav.querySelectorAll(".nav-link").forEach(link => {
      const href = new URL(link.href, window.location.origin).pathname;
      const route = routes.find(item => item.href === href);
      if (!route) return;
      link.innerHTML = `<span class="v3-nav-icon">${icons[route.icon]}</span><span class="v3-nav-label">${route.label}</span>`;
      link.title = route.label;
      link.setAttribute("aria-label", route.label);
      link.classList.toggle("nav-link-active", route.match(currentPath));
      if (route.match(currentPath)) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });

    const footer = document.createElement("div");
    footer.className = "v3-sidebar-footer";
    footer.innerHTML = `<span class="v3-beta-chip">V3 BETA</span><span class="v3-sidebar-release">Release ${release}</span>`;
    nav.appendChild(footer);
  }

  function injectTopbar() {
    const main = document.querySelector("main");
    if (!main) return;
    const topbar = document.createElement("header");
    topbar.className = "v3-topbar";
    topbar.innerHTML = `
      <div class="v3-topbar-title"><span>Workspace</span><strong>${currentRoute.label}</strong></div>
      <div class="v3-topbar-actions">
        <button class="v3-command-trigger" type="button" aria-label="Open command center">
          <span class="v3-command-icon">${icons.search}</span><span>Search and run a command</span><kbd>/</kbd>
        </button>
        <a class="v3-quick-action" href="/library"><span>${icons.plus}</span>Queue media</a>
      </div>`;
    main.parentNode.insertBefore(topbar, main);
    topbar.querySelector(".v3-command-trigger").addEventListener("click", openCommandCenter);
  }

  const commands = [
    { label: "Open Overview", detail: "System health and recent work", href: "/", icon: "overview" },
    { label: "Browse Library", detail: "Find movies and complete seasons", href: "/library", icon: "library" },
    { label: "Open Queue", detail: "Watch, pause, or reorder encodes", href: "/jobs", icon: "queue" },
    { label: "Open Automate", detail: "Train and manage Autopilot", href: "/autopilot", icon: "automate" },
    { label: "Open Size Wizard", detail: "Fine-tune a one-off plan", href: "/size_wizard", icon: "wizard" },
    { label: "Manage Smart Presets", detail: "Preservation and language safeguards", href: "/settings/smart", icon: "settings" },
    { label: "Open Settings", detail: "Interface, workers, storage, and AI", href: "/settings", icon: "settings" },
    { label: "Switch to V2 Classic", detail: "Use the stable legacy interface", href: "/settings?ui=v2", icon: "switch" }
  ];

  let commandDialog;
  let commandInput;
  let commandList;

  function createCommandCenter() {
    commandDialog = document.createElement("dialog");
    commandDialog.className = "v3-command-dialog";
    commandDialog.setAttribute("aria-label", "Command center");
    commandDialog.innerHTML = `
      <div class="v3-command-head"><span>${icons.search}</span><input class="v3-command-input" type="search" autocomplete="off" placeholder="Where do you want to go?" aria-label="Search commands"><button class="v3-command-close" type="button" aria-label="Close command center">Esc</button></div>
      <div class="v3-command-results" role="listbox"></div>
      <div class="v3-command-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move · <kbd>Enter</kbd> open · Type anything to search the library</span></div>`;
    document.body.appendChild(commandDialog);
    commandInput = commandDialog.querySelector("input");
    commandList = commandDialog.querySelector(".v3-command-results");
    renderCommands("");

    commandInput.addEventListener("input", () => renderCommands(commandInput.value));
    commandInput.addEventListener("keydown", handleCommandKeys);
    commandDialog.querySelector(".v3-command-close").addEventListener("click", () => commandDialog.close());
    commandDialog.addEventListener("click", event => {
      if (event.target === commandDialog) commandDialog.close();
    });
    commandDialog.addEventListener("close", () => { commandInput.value = ""; renderCommands(""); });
  }

  function renderCommands(query) {
    const normalized = query.trim().toLowerCase();
    const visible = commands.filter(command => `${command.label} ${command.detail}`.toLowerCase().includes(normalized));
    commandList.replaceChildren();
    visible.forEach((command, index) => {
      const link = document.createElement("a");
      link.className = `v3-command-item${index === 0 ? " is-selected" : ""}`;
      link.href = command.href;
      link.setAttribute("role", "option");
      link.innerHTML = `<span class="v3-command-item-icon">${icons[command.icon]}</span><span><strong>${command.label}</strong><small>${command.detail}</small></span><span class="v3-command-arrow">→</span>`;
      link.addEventListener("mouseenter", () => selectCommand(link));
      commandList.appendChild(link);
    });
    if (!visible.length && normalized) {
      const link = document.createElement("a");
      link.className = "v3-command-item is-selected";
      link.href = `/library?search=${encodeURIComponent(query.trim())}`;
      link.innerHTML = `<span class="v3-command-item-icon">${icons.search}</span><span><strong>Search the library</strong><small>Find “${escapeHtml(query.trim())}” in movies and shows</small></span><span class="v3-command-arrow">→</span>`;
      commandList.appendChild(link);
    }
  }

  function selectCommand(item) {
    commandList.querySelectorAll(".v3-command-item").forEach(node => node.classList.toggle("is-selected", node === item));
  }

  function handleCommandKeys(event) {
    const items = Array.from(commandList.querySelectorAll(".v3-command-item"));
    if (!items.length) return;
    const current = Math.max(0, items.findIndex(item => item.classList.contains("is-selected")));
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      selectCommand(items[(current + step + items.length) % items.length]);
    } else if (event.key === "Enter") {
      event.preventDefault();
      items[current].click();
    }
  }

  function openCommandCenter() {
    if (!commandDialog) createCommandCenter();
    if (typeof commandDialog.showModal === "function") commandDialog.showModal();
    else commandDialog.setAttribute("open", "");
    window.setTimeout(() => commandInput.focus(), 0);
  }

  function addKeyboardShortcuts() {
    document.addEventListener("keydown", event => {
      const target = event.target;
      const isTyping = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || target?.isContentEditable;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openCommandCenter();
      } else if (event.key === "/" && !isTyping && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        openCommandCenter();
      }
    });
  }

  function applyLibrarySearch() {
    if (!currentPath.startsWith("/library")) return;
    const query = new URLSearchParams(window.location.search).get("search");
    const input = document.getElementById("searchInput");
    if (!query || !input) return;
    input.value = query;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function addWizardProgress() {
    const heading = document.querySelector(".wizard-heading");
    if (!heading) return;
    const progress = document.createElement("ol");
    progress.className = "v3-workflow-steps";
    progress.setAttribute("aria-label", "Encoding workflow");
    ["Source", "Intent", "Preview", "Queue"].forEach((label, index) => {
      const step = document.createElement("li");
      step.className = "v3-workflow-step";
      step.innerHTML = `<span>${index + 1}</span><strong>${label}</strong>`;
      progress.appendChild(step);
    });
    heading.insertAdjacentElement("afterend", progress);

    const update = () => {
      const steps = Array.from(progress.children);
      const source = document.getElementById("src")?.value || "";
      const previewText = document.getElementById("previewBox")?.textContent || "";
      const compareVisible = document.getElementById("compareWrap")?.style.display !== "none";
      const queueText = `${document.getElementById("queueStatus")?.textContent || ""} ${document.getElementById("simpleQueueStatus")?.textContent || ""}`;
      const sourceReady = Boolean(source);
      const previewReady = sourceReady && !/waiting for a selected file/i.test(previewText);
      const compareReady = previewReady && compareVisible;
      const queueReady = /queued|complete|success/i.test(queueText);
      const complete = [sourceReady, previewReady, compareReady, queueReady];
      const active = queueReady ? 3 : compareReady ? 3 : previewReady ? 2 : sourceReady ? 1 : 0;
      steps.forEach((step, index) => {
        step.classList.toggle("is-complete", complete[index] && index < active);
        step.classList.toggle("is-active", index === active);
      });
    };
    const observer = new MutationObserver(update);
    ["fileNameChip", "previewBox", "compareWrap", "queueStatus", "simpleQueueStatus"].forEach(id => {
      const element = document.getElementById(id);
      if (element) observer.observe(element, { attributes: true, childList: true, characterData: true, subtree: true });
    });
    document.getElementById("src")?.addEventListener("change", update);
    update();
  }

  decorateNavigation();
  injectTopbar();
  addKeyboardShortcuts();
  applyLibrarySearch();
  addWizardProgress();
  document.title = `ByteSqueeze · ${currentRoute.label}`;
  body.classList.add("v3-ready");
})();
