(function () {
  function ensureToastHost() {
    let host = document.getElementById("toastHost");
    if (!host) {
      host = document.createElement("div");
      host.id = "toastHost";
      host.className = "toast-host";
      document.body.appendChild(host);
    }
    return host;
  }

  window.setAppStatus = function setAppStatus(label, state) {
    const chip = document.getElementById("appStatusChip");
    const text = document.getElementById("appStatusText");
    const normalized = String(state || label || "idle").toLowerCase();
    if (text) text.textContent = label || "Idle";
    if (chip) {
      chip.className = "app-status";
      chip.classList.add("status-" + normalized.replace(/[^a-z0-9_-]+/g, "-"));
    }
  };

  window.appToast = function appToast(message, type) {
    const text = String(message || "").trim();
    if (!text) return;
    const toast = document.createElement("div");
    toast.className = "app-toast toast-" + String(type || "info").toLowerCase();
    toast.textContent = text;
    ensureToastHost().appendChild(toast);
    window.setTimeout(() => toast.classList.add("is-showing"), 20);
    window.setTimeout(() => {
      toast.classList.remove("is-showing");
      window.setTimeout(() => toast.remove(), 220);
    }, 3800);
  };

  document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("appStatusChip")) {
      window.setAppStatus("Idle", "idle");
    }
  });
})();
