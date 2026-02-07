async function fetchJson(url, options) {
  const res = await fetch(url, options || {});
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = { raw: text }; }
  if (!res.ok) {
    const msg = (data && (data.detail || data.error || data.message)) || res.statusText;
    throw new Error(msg);
  }
  return data;
}

function fmtMoney(v) {
  const n = Number(v || 0);
  if (Number.isNaN(n)) return String(v ?? "-");
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(v) {
  const n = Number(v || 0);
  if (Number.isNaN(n)) return String(v ?? "-");
  return (n * 100).toFixed(2) + "%";
}

function showToast(msg, ok=true) {
  const el = document.getElementById("ui-toast");
  if (!el) return;
  el.textContent = msg;
  el.style.borderColor = ok ? "rgba(46,160,67,0.6)" : "rgba(218,54,51,0.6)";
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2500);
}

function setActiveNav(path) {
  document.querySelectorAll(".nav-link").forEach((el) => {
    const href = el.getAttribute("href") || "";
    if (href === path) el.classList.add("active");
  });
}
