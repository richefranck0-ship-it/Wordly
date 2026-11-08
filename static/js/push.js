(() => {
  const WL = window.WL, supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const b64 = s => { const p = "=".repeat((4 - s.length % 4) % 4), r = atob((s + p).replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from([...r].map(c => c.charCodeAt(0))); };
  const P = WL.push = {
    supported,
    async reg() { return navigator.serviceWorker.ready; },
    async current() { if (!supported) return null; return (await P.reg()).pushManager.getSubscription(); },
    // doit être appelé après un clic de l'utilisateur
    async enable(categories, weather, topics) {
      if (!supported) throw new Error("unsupported");
      const cfg = await (await fetch("/api/push/config")).json();
      if (!cfg.enabled) throw new Error("server");
      const perm = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
      if (perm !== "granted") throw new Error("denied");
      const reg = await P.reg();
      const sub = (await reg.pushManager.getSubscription()) || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(cfg.key) });
      await WL.api("/api/push/subscribe", { subscription: sub.toJSON(), categories: categories || ["news", "weather", "worldly", "ads"], lang: WL.cfg.lang, weather, topics: topics || [] });
      WL.store.set("wl_push_dismiss", 1);
      return sub;
    },
    async disable() {
      const s = await P.current(); if (!s) return;
      await WL.api("/api/push/unsubscribe", { endpoint: s.endpoint }).catch(() => {}); await s.unsubscribe();
    },
  };
  // présentation à la première utilisation (page d'accueil uniquement, jamais de demande automatique)
  const banner = document.getElementById("push-banner");
  if (banner && supported && location.pathname === "/" && Notification.permission === "default" && !WL.store.get("wl_push_dismiss")) {
    setTimeout(() => { banner.hidden = false; }, 2500);
    document.getElementById("push-later").onclick = () => { WL.store.set("wl_push_dismiss", 1); banner.hidden = true; };
    document.getElementById("push-enable").onclick = async () => { try { await P.enable(); } catch {} banner.hidden = true; };
  }
})();
