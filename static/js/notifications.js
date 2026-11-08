(() => {
  const WL = window.WL, T = WL.t, $ = id => document.getElementById(id);
  if (!$("notif-page")) return;
  const P = WL.push, st = $("n-status"), en = $("n-enable"), dis = $("n-disable"), hint = $("n-hint"), wc = $("n-weather-city");
  const city = WL.store.get("wl_city", null);
  $("n-city").textContent = city ? "(" + city.name + ")" : ""; wc.disabled = !city;
  const cats = () => [...document.querySelectorAll("#n-prefs input[value]")].filter(x => x.checked).map(x => x.value);
  const weather = () => ({ on: wc.checked && !!city, lat: city && city.lat, lon: city && city.lon, city: city && city.name });

  async function refresh() {
    if (!P.supported) { st.textContent = T.notif_unsupported; en.disabled = true; return; }
    if (Notification.permission === "denied") { st.textContent = T.notif_denied; en.disabled = true; return; }
    const s = await P.current();
    st.textContent = s ? T.notif_on : T.notif_off; dis.hidden = !s; en.textContent = s ? T.save : T.enable;
    if (s) { try { const p = await WL.api("/api/push/prefs", { endpoint: s.endpoint });
      document.querySelectorAll("#n-prefs input[value]").forEach(x => x.checked = p.categories.includes(x.value)); wc.checked = p.weather_on; } catch {} }
  }
  en.onclick = async () => {
    try { await P.enable(cats(), weather()); hint.textContent = T.saved; } catch (e) { hint.textContent = e.message === "denied" ? T.notif_denied : T.notif_unsupported; }
    refresh();
  };
  dis.onclick = async () => { await P.disable(); hint.textContent = ""; refresh(); };
  fetch("/api/notifications").then(r => r.json()).then(j => {
    const ul = $("n-history"); if (!j.items.length) return; ul.innerHTML = "";
    j.items.forEach(n => { const li = document.createElement("li"), a = document.createElement(n.url ? "a" : "span"), s = document.createElement("small");
      a.textContent = n.title; if (n.url) a.href = n.url; s.textContent = n.body + " · " + new Date(n.created_at.replace(" ", "T") + "Z").toLocaleString(WL.cfg.lang);
      li.append(a, s); ul.append(li); });
  }).catch(() => {});
  refresh();
})();
