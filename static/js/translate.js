(() => {
  const WL = window.WL, T = WL.t, LANGS = WL.cfg.langs;
  const $ = id => document.getElementById(id);
  const speak = (text, lang) => {
    if (!("speechSynthesis" in window)) return false;
    const loc = (LANGS[lang] || [])[1] || lang, u = new SpeechSynthesisUtterance(text); u.lang = loc;
    const v = speechSynthesis.getVoices().find(x => x.lang.toLowerCase().startsWith(lang.toLowerCase()));
    if (v) u.voice = v; else if (speechSynthesis.getVoices().length) { alert(T.no_voice); return false; }
    speechSynthesis.cancel(); speechSynthesis.speak(u); return true;
  };
  WL.speak = speak;
  WL.translate = (text, src, dst) => WL.api("/api/translate", { text, src, dst });

  // mini traducteur de l'accueil
  if ($("quick-tr")) {
    $("qt-go").onclick = async () => {
      const txt = $("qt-in").value.trim(), out = $("qt-out"); if (!txt) return;
      out.textContent = T.translating;
      try { out.textContent = (await WL.translate(txt, "auto", $("qt-dst").value)).text; } catch (e) { out.textContent = T.tr_error + " (" + e.message + ")"; }
    };
  }
  if (!$("tr-page")) return;
  const inp = $("tr-in"), out = $("tr-out"), src = $("tr-src"), dst = $("tr-dst"), det = $("tr-detected");
  let last = { text: "", lang: dst.value }, timer, seq = 0;

  const renderHistory = () => {
    const ul = $("tr-history"), h = WL.store.get("wl_tr_hist", []); ul.innerHTML = "";
    if (!h.length) { const li = document.createElement("li"); li.className = "muted"; li.textContent = T.empty; ul.append(li); return; }
    h.forEach(x => { const li = document.createElement("li"), a = document.createElement("a"), s = document.createElement("small");
      a.href = "#"; a.textContent = x.in.slice(0, 80); s.textContent = "→ " + x.out.slice(0, 120);
      a.onclick = e => { e.preventDefault(); src.value = x.src; dst.value = x.dst; inp.value = x.in; run(); };
      li.append(a, s); ul.append(li); });
  };
  const saveHistory = (e) => { const h = WL.store.get("wl_tr_hist", []).filter(x => x.in !== e.in || x.dst !== e.dst); h.unshift(e); WL.store.set("wl_tr_hist", h.slice(0, 20)); renderHistory(); };

  async function run() {
    const text = inp.value.trim(), my = ++seq;
    if (!text) { out.textContent = ""; det.textContent = ""; return; }
    out.textContent = T.translating;
    try {
      const j = await WL.translate(text, src.value, dst.value); if (my !== seq) return;
      out.textContent = j.text; last = { text: j.text, lang: dst.value };
      det.dataset.code = src.value === "auto" ? (j.detected || "") : "";
      det.textContent = src.value === "auto" && j.detected ? T.detected + " : " + ((LANGS[j.detected] || [j.detected])[0]) : "";
      saveHistory({ in: text, out: j.text, src: src.value, dst: dst.value });
    } catch (e) { if (my === seq) out.textContent = T.tr_error + " (" + e.message + ")"; }
  }
  inp.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 700); }); // traduction instantanée
  src.onchange = dst.onchange = run;
  $("tr-swap").onclick = () => {
    const from = src.value === "auto" ? (det.dataset.code || (dst.value === "en" ? "fr" : "en")) : src.value;
    src.value = dst.value; dst.value = from;
    if (last.text) inp.value = last.text; run();
  };
  $("tr-clear").onclick = () => { inp.value = ""; out.textContent = ""; det.textContent = ""; inp.focus(); };
  $("tr-copy").onclick = async e => { if (!last.text) return; try { await navigator.clipboard.writeText(out.textContent); const b = e.target, o = b.textContent; b.textContent = T.copied; setTimeout(() => b.textContent = o, 1500); } catch {} };
  $("tr-listen").onclick = () => { if (out.textContent && last.text) speak(out.textContent, dst.value); };
  $("tr-clear-history").onclick = () => { WL.store.del("wl_tr_hist"); renderHistory(); };
  if ("speechSynthesis" in window) speechSynthesis.getVoices();
  renderHistory();
})();
