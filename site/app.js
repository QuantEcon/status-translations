/* Shared chrome + data loading for the status-translations dashboard.
   Each page defines render(DATA) and calls STDash.boot({page, render}). */
"use strict";

const STDash = (() => {
  const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const gh = (repo) => `https://github.com/QuantEcon/${repo}`;

  /* ---- theme: system by default; explicit choice persisted and applied
     via data-theme on <html> (an inline head script applies it pre-paint) ---- */
  const THEME_KEY = "st-theme";
  const MODES = ["system", "light", "dark"];
  const modeLabel = { system: "◐ Auto", light: "☀ Light", dark: "☾ Dark" };
  function currentMode() {
    let v = null;
    try { v = localStorage.getItem(THEME_KEY); } catch (e) { /* private mode */ }
    return MODES.includes(v) ? v : "system";
  }
  function applyMode(mode) {
    const root = document.documentElement;
    if (mode === "light" || mode === "dark") root.dataset.theme = mode;
    else delete root.dataset.theme;
  }
  function cycleMode() {
    const next = MODES[(MODES.indexOf(currentMode()) + 1) % MODES.length];
    try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* ignore */ }
    applyMode(next);
    return next;
  }

  /* ---- freshness badge: floored whole days since collection;
     green ≤ 7, orange > 7, red > 14 (same thresholds as data-lectures) ---- */
  function freshness(generatedAt) {
    const days = Math.max(0, Math.floor((Date.now() - Date.parse(generatedAt + "T00:00:00Z")) / 86400000));
    const cls = days > 14 ? "crit" : days > 7 ? "warn" : "good";
    const label = days === 0 ? "collected today" : days === 1 ? "collected 1 day ago" : `collected ${days} days ago`;
    const title = "Data age, floored to whole days — green within 7 days, orange past a week, red past two";
    return `<span class="freshness ${cls}" title="${title}">${label}</span>`;
  }

  const PAGES = [
    { id: "overview", href: "index.html", label: "Overview" },
    { id: "rollout", href: "rollout.html", label: "Rollout" },
    { id: "sync", href: "sync.html", label: "Sync detail" },
  ];

  function renderChrome(page, DATA) {
    const tabs = PAGES.map(p =>
      `<a href="${p.href}"${p.id === page ? ' class="active" aria-current="page"' : ""}>${p.label}</a>`).join("");
    document.getElementById("chrome").innerHTML = `
      <div class="mast">
        <div class="grow">
          <p class="eyebrow">QuantEcon · Internationalisation program</p>
          <h1>Translation progress</h1>
          <p class="dateline">${DATA
            ? `Data as of <b>${esc(DATA.generated_at)}</b><span class="sep">·</span>${freshness(DATA.generated_at)}` +
              `<span class="sep">·</span><a href="data/latest.json">data/latest.json</a>`
            : "Loading…"}</p>
        </div>
        <button type="button" class="theme-toggle" id="theme-toggle" aria-label="Switch colour theme"></button>
      </div>
      <nav class="tabs" aria-label="Dashboard pages">${tabs}</nav>`;
    const btn = document.getElementById("theme-toggle");
    btn.textContent = modeLabel[currentMode()];
    btn.addEventListener("click", () => { btn.textContent = modeLabel[cycleMode()]; });
  }

  function footer(DATA, extra) {
    document.getElementById("foot").innerHTML = `
      ${extra || ""}
      <p><b>How this page works.</b> Static HTML on GitHub Pages reading <a href="data/latest.json">data/latest.json</a>; a nightly collector compares each source repo with its editions (file coverage, per-file last-commit dates, sync activity, workflow wiring, review labels) and appends dated snapshots to <b>data/history/</b>. ${esc(DATA.collected_by)}.</p>
      <p><b>Counting rule.</b> ${esc(DATA.counting_rule)}</p>
      <p>Engine: <a href="https://github.com/QuantEcon/action-translation">action-translation</a> · dashboard source: <a href="https://github.com/QuantEcon/status-translations">status-translations</a> · program docs: QuantEcon/project-translation</p>`;
  }

  /* ---- shared tooltip (pages opt in by giving cells data-tip HTML) ---- */
  function enableTooltip() {
    const tip = document.getElementById("tip");
    if (!tip) return;
    document.addEventListener("mouseover", (ev) => {
      const c = ev.target.closest("[data-tip]");
      if (!c) { tip.style.display = "none"; return; }
      tip.innerHTML = c.dataset.tip;
      tip.style.display = "block";
    });
    document.addEventListener("mousemove", (ev) => {
      if (tip.style.display !== "block") return;
      const pad = 14;
      let x = ev.clientX + pad, y = ev.clientY + pad;
      const r = tip.getBoundingClientRect();
      if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - pad;
      if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - pad;
      tip.style.left = x + "px"; tip.style.top = y + "px";
    });
  }

  function boot({ page, render, footExtra }) {
    renderChrome(page, null);
    fetch("data/latest.json?v=" + Date.now())
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(DATA => {
        renderChrome(page, DATA);
        render(DATA);
        footer(DATA, footExtra ? footExtra(DATA) : "");
        enableTooltip();
      })
      .catch(err => {
        document.getElementById("main").innerHTML =
          `<div class="error-card"><b>Could not load data/latest.json</b> — ${esc(err.message)}. ` +
          `The data file deploys with the site; if this persists, check the latest publish run in ` +
          `<a href="https://github.com/QuantEcon/status-translations/actions">Actions</a>.</div>`;
      });
  }

  return { esc, gh, boot };
})();
