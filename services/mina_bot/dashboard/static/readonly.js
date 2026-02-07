(() => {
  if (!window.DASHBOARD_READ_ONLY) return;

  const MESSAGE = "Dashboard is read-only. Use Unified Dashboard.";

  const style = document.createElement("style");
  style.textContent = `
    .readonly-banner {
      margin: 10px auto 14px;
      max-width: 1400px;
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid rgba(210, 153, 34, 0.55);
      background: rgba(210, 153, 34, 0.16);
      color: #f2cc60;
      font-size: 0.85rem;
      font-weight: 700;
      letter-spacing: 0.2px;
    }
    .readonly-disabled {
      opacity: 0.45 !important;
      cursor: not-allowed !important;
      pointer-events: none !important;
    }
  `;
  document.head.appendChild(style);

  const ensureBanner = () => {
    if (document.getElementById("readonly-banner")) return;
    const div = document.createElement("div");
    div.id = "readonly-banner";
    div.className = "readonly-banner";
    div.textContent = "Managed by Unified Dashboard";
    document.body.prepend(div);
  };

  const writeWords = [
    "approve",
    "reject",
    "close",
    "kill",
    "restart",
    "save",
    "apply",
    "queue",
    "promote",
    "generate",
    "clear",
    "run",
    "test",
    "connect",
    "disconnect",
    "update",
    "publish",
    "maintenance",
    "label",
    "train",
    "rollback",
    "send",
    "sync",
    "fix",
    "delete",
  ];

  const allowWords = [
    "refresh",
    "back",
    "dashboard",
    "analytics",
    "doctor",
    "status",
    "toggle",
    "tab",
    "open",
    "view",
  ];

  const disableWriteControls = () => {
    const controls = document.querySelectorAll("button, input, select, textarea");
    controls.forEach((el) => {
      if (!(el instanceof HTMLElement)) return;

      const tag = el.tagName.toLowerCase();
      const text = (el.textContent || "").toLowerCase();
      const onclick = (el.getAttribute("onclick") || "").toLowerCase();
      const id = (el.id || "").toLowerCase();
      const cls = (el.className || "").toLowerCase();
      const hay = `${text} ${onclick} ${id} ${cls}`;

      if (allowWords.some((w) => hay.includes(w))) return;
      const isWrite = writeWords.some((w) => hay.includes(w));

      // Inputs/selects/textarea are mostly write paths on old dashboards.
      const isInputLike = tag === "input" || tag === "select" || tag === "textarea";
      if (isWrite || isInputLike) {
        if ("disabled" in el) {
          // @ts-ignore
          el.disabled = true;
        }
        el.classList.add("readonly-disabled");
        el.setAttribute("title", MESSAGE);
      }
    });
  };

  const origFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const method = String((init && init.method) || "GET").toUpperCase();
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
      return new Response(JSON.stringify({ status: "error", detail: MESSAGE }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      });
    }
    return origFetch(input, init);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      ensureBanner();
      disableWriteControls();
    });
  } else {
    ensureBanner();
    disableWriteControls();
  }
})();
