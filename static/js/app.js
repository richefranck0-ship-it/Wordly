(() => {
  const CFG = JSON.parse(document.getElementById("cfg").textContent);
  const WL = window.WL = { cfg: CFG, t: CFG.t, csrf: CFG.csrf };
  WL.api = async (path, body) => {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": WL.csrf }, body: JSON.stringify(body || {}) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(j.error || r.status), { status: r.status });
    return j;
  };
  WL.store = {
    get: (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
    del: (k) => { try { localStorage.removeItem(k); } catch {} },
  };
  // changement de langue de l'interface
  document.querySelectorAll("[data-lang-switch]").forEach(s => s.addEventListener("change", () => {
    location.href = "/lang/" + s.value + "?next=" + encodeURIComponent(location.pathname + location.search);
  }));
  // confirmations (pas de JS inline à cause de la CSP)
  document.addEventListener("submit", e => { const m = e.target.dataset && e.target.dataset.confirm; if (m && !confirm(m)) e.preventDefault(); });
  // images cassées
  document.addEventListener("error", e => { const el = e.target; if (el.tagName === "IMG" && el.hasAttribute("data-hide-on-error")) { const a = el.closest(".card-img"); (a || el).style.display = "none"; } }, true);
  // dates relatives
  const rtf = new Intl.RelativeTimeFormat(CFG.lang, { numeric: "auto" });
  document.querySelectorAll("time[data-rel]").forEach(el => {
    const d = new Date(el.getAttribute("datetime")); if (isNaN(d)) return;
    const m = Math.round((d - Date.now()) / 60000), a = Math.abs(m);
    el.textContent = a < 60 ? rtf.format(m, "minute") : a < 1440 ? rtf.format(Math.round(m / 60), "hour") : a < 10080 ? rtf.format(Math.round(m / 1440), "day") : d.toLocaleDateString(CFG.lang);
  });
  // PWA : service worker + installation
  if ("serviceWorker" in navigator) addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  let deferred = null;
  addEventListener("beforeinstallprompt", e => { e.preventDefault(); deferred = e; document.querySelectorAll("#install-btn,#install-btn-2").forEach(b => b.hidden = false); });
  document.querySelectorAll("#install-btn,#install-btn-2").forEach(b => b.addEventListener("click", async () => {
    if (!deferred) return; deferred.prompt(); await deferred.userChoice; deferred = null; b.hidden = true;
  }));
  addEventListener("appinstalled", () => document.querySelectorAll("#install-btn,#install-btn-2").forEach(b => b.hidden = true));
  // nouvelles actualités (vérification toutes les 5 min)
  const list = document.getElementById("news-list");
  if (list) {
    const latest = +list.dataset.latest || 0, btn = document.getElementById("new-articles");
    setInterval(async () => {
      try { const j = await (await fetch("/api/news/status")).json(); if (j.latest_id > latest) btn.hidden = false; } catch {}
    }, 300000);
    btn.addEventListener("click", () => location.reload());
  }
  // erreurs JS -> administration
  let sent = 0;
  addEventListener("error", e => { if (sent++ < 3 && e.message) WL.api("/api/log-error", { message: e.message + " @" + (e.filename || "").split("/").pop() + ":" + e.lineno }).catch(() => {}); });
})();
