(() => {
  const WL = window.WL, T = WL.t, L = WL.cfg.lang;
  const page = document.getElementById("weather-page"), mini = document.getElementById("weather-mini");
  if (!page && !mini) return;
  const $ = id => document.getElementById(id);
  const ICON = c => c === 0 ? "☀️" : c <= 2 ? "🌤️" : c === 3 ? "☁️" : c <= 48 ? "🌫️" : c <= 57 ? "🌦️" : c <= 67 ? "🌧️" : c <= 77 ? "❄️" : c <= 82 ? "🌧️" : c <= 86 ? "🌨️" : "⛈️";
  const LABEL = c => c === 0 ? T.w0 : c <= 3 ? T.w1 : c <= 48 ? T.w45 : c <= 57 ? T.w51 : c <= 67 ? T.w61 : c <= 77 ? T.w71 : c <= 82 ? T.w80 : c <= 86 ? T.w71 : T.w95;
  const hm = iso => new Date(iso).toLocaleTimeString(L, { hour: "2-digit", minute: "2-digit" });
  const getJSON = async u => { const r = await fetch(u); if (!r.ok) throw new Error(r.status); return r.json(); };
  let place = WL.store.get("wl_city", null), timer = null;

  async function forecast(p) {
    return getJSON("https://api.open-meteo.com/v1/forecast?latitude=" + p.lat + "&longitude=" + p.lon +
      "&current=temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code,is_day" +
      "&hourly=temperature_2m,precipitation_probability,weather_code" +
      "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_gusts_10m_max,sunrise,sunset" +
      "&timezone=auto&forecast_days=7");
  }
  function alerts(d) {
    const o = [], c = d.weather_code[0];
    if (c >= 95) o.push(T.al_storm);
    if ((d.precipitation_sum[0] || 0) >= 20 && (d.precipitation_probability_max[0] || 0) >= 70) o.push(T.al_rain);
    if ((d.wind_gusts_10m_max[0] || 0) >= 70) o.push(T.al_wind);
    if (d.temperature_2m_max[0] >= 35) o.push(T.al_heat);
    if (d.temperature_2m_min[0] <= -10) o.push(T.al_cold);
    if ([71, 73, 75, 77, 85, 86].includes(c)) o.push(T.al_snow);
    return o;
  }
  function renderMini(w) {
    const body = mini.querySelector(".mini-body");
    body.innerHTML = "";
    const t = document.createElement("span"); t.className = "mini-temp"; t.textContent = Math.round(w.current.temperature_2m) + "°";
    const d = document.createElement("div"); d.textContent = ICON(w.current.weather_code) + " " + LABEL(w.current.weather_code) + " · " + place.name;
    body.append(t, d);
  }
  function renderFull(w) {
    const c = w.current, i = Math.max(0, w.hourly.time.findIndex(x => x >= c.time.slice(0, 13)));
    $("w-place").textContent = place.name; $("w-temp").textContent = Math.round(c.temperature_2m) + "°C";
    $("w-desc").textContent = LABEL(c.weather_code); $("w-emoji").textContent = ICON(c.weather_code);
    $("w-feels").textContent = Math.round(c.apparent_temperature) + "°"; $("w-hum").textContent = c.relative_humidity_2m + " %";
    $("w-wind").textContent = Math.round(c.wind_speed_10m) + " km/h"; $("w-rain").textContent = (w.hourly.precipitation_probability[i] ?? 0) + " %";
    $("w-rise").textContent = hm(w.daily.sunrise[0]); $("w-set").textContent = hm(w.daily.sunset[0]);
    const al = alerts(w.daily), ul = $("w-alerts"); ul.innerHTML = "";
    (al.length ? al : [T.no_alerts]).forEach(x => { const li = document.createElement("li"); li.textContent = (al.length ? "⚠ " : "") + x; if (!al.length) li.className = "none"; ul.append(li); });
    const hs = $("w-hours"); hs.innerHTML = "";
    for (let k = i; k < i + 24 && k < w.hourly.time.length; k++) {
      const h = document.createElement("div"); h.className = "hour";
      h.innerHTML = "<small></small><span></span><b></b><small></small>";
      const [a, ic, b, r] = h.children; a.textContent = new Date(w.hourly.time[k]).toLocaleTimeString(L, { hour: "2-digit" });
      ic.textContent = ICON(w.hourly.weather_code[k]); b.textContent = Math.round(w.hourly.temperature_2m[k]) + "°"; r.textContent = "💧" + (w.hourly.precipitation_probability[k] ?? 0) + "%";
      hs.append(h);
    }
    const ds = $("w-days"); ds.innerHTML = "";
    w.daily.time.forEach((day, k) => {
      const li = document.createElement("li"), a = document.createElement("span"), b = document.createElement("span"), c2 = document.createElement("b");
      a.textContent = ICON(w.daily.weather_code[k]) + " " + new Date(day + "T12:00").toLocaleDateString(L, { weekday: "long", day: "numeric" });
      b.textContent = "💧" + (w.daily.precipitation_probability_max[k] ?? 0) + "%"; c2.textContent = Math.round(w.daily.temperature_2m_max[k]) + "° / " + Math.round(w.daily.temperature_2m_min[k]) + "°";
      li.append(a, b, c2); ds.append(li);
    });
    $("w-msg").hidden = true; $("w-data").hidden = false;
  }
  async function load() {
    if (!place) return;
    try { const w = await forecast(place); page ? renderFull(w) : renderMini(w); }
    catch { if (page) { $("w-msg").hidden = false; $("w-msg").textContent = T.weather_error; } }
  }
  function choose(p) {
    place = p; WL.store.set("wl_city", p); load(); clearInterval(timer); timer = setInterval(load, 600000); // actualisation toutes les 10 min
  }
  async function locate() {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(pos => {
      const lat = +pos.coords.latitude.toFixed(3), lon = +pos.coords.longitude.toFixed(3);
      choose({ name: T.use_location, lat, lon });
    }, () => { if (page) { $("w-msg").hidden = false; $("w-msg").textContent = T.loc_denied; } }, { timeout: 10000, maximumAge: 600000 });
  }
  if (page) {
    const input = $("city-in"), box = $("city-results"); let tm;
    input.addEventListener("input", () => {
      clearTimeout(tm); const q = input.value.trim(); if (q.length < 2) { box.hidden = true; return; }
      tm = setTimeout(async () => {
        try {
          const j = await getJSON("https://geocoding-api.open-meteo.com/v1/search?count=6&language=" + L + "&name=" + encodeURIComponent(q));
          box.innerHTML = ""; (j.results || []).forEach(r => {
            const li = document.createElement("li"); li.tabIndex = 0; li.textContent = [r.name, r.admin1, r.country].filter(Boolean).join(", ");
            const pick = () => { box.hidden = true; input.value = ""; choose({ name: r.name + (r.country ? ", " + r.country : ""), lat: r.latitude, lon: r.longitude }); };
            li.onclick = pick; li.onkeydown = e => { if (e.key === "Enter") pick(); }; box.append(li);
          }); box.hidden = !box.children.length;
        } catch {}
      }, 300);
    });
    $("locate").onclick = locate;
  } else {
    document.getElementById("wm-locate").onclick = locate;
  }
  if (place) choose(place);
})();
