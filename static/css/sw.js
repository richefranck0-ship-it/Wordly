const V = "worldly-v1", SHELL = ["/offline", "/static/css/style.css", "/static/js/app.js", "/static/icons/icon-192.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", e => { e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== V).map(x => caches.delete(x)))).then(() => self.clients.claim())); });
self.addEventListener("fetch", e => {
  const r = e.request, u = new URL(r.url);
  if (r.method !== "GET") return;
  if (r.mode === "navigate") { e.respondWith(fetch(r).catch(() => caches.match("/offline"))); return; }
  if (u.origin === location.origin && u.pathname.startsWith("/static/")) {
    e.respondWith(caches.open(V).then(async c => { const hit = await c.match(r); const net = fetch(r).then(x => { if (x.ok) c.put(r, x.clone()); return x; }).catch(() => hit); return hit || net; }));
  }
});
self.addEventListener("push", e => {
  let d = {}; try { d = e.data ? e.data.json() : {}; } catch { d = { title: "WORLDLY", body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || "WORLDLY", {
    body: d.body || "", icon: "/static/icons/icon-192.png", badge: "/static/icons/badge.png", tag: d.tag || "worldly",
    vibrate: [120, 60, 120], data: { url: d.url || "/" }, renotify: true }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close(); const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(cs => {
    const c = cs.find(x => new URL(x.url).origin === location.origin);
    return c ? (c.navigate(url), c.focus()) : self.clients.openWindow(url);
  }));
});
