(() => {
  const WL = window.WL, T = WL.t, LANGS = WL.cfg.langs, $ = id => document.getElementById(id);
  if (!$("voice-page")) return;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const st = $("v-status"), start = $("v-start"), stop = $("v-stop"), txt = $("v-text"), out = $("v-out"), listen = $("v-listen");
  const say = (m, cls = "") => { st.textContent = m; st.className = "status " + cls; };
  if (!SR) { say(T.err_unsupported, "bad"); start.disabled = true; return; }
  let rec = null, final = "", lastOut = "";

  const ERR = { "not-allowed": T.err_denied, "service-not-allowed": T.err_denied, "no-speech": T.err_nospeech, "audio-capture": T.err_audio, "network": T.err_network };
  const idle = () => { start.disabled = false; stop.disabled = true; };

  async function finish() {
    idle(); const text = (final || txt.textContent).trim(); if (!text) return;
    say(T.translating);
    try {
      const j = await WL.translate(text, $("v-src").value, $("v-dst").value);
      out.textContent = lastOut = j.text; listen.disabled = false; say(T.tap_start);
      WL.speak(j.text, $("v-dst").value);            // lecture audio de la traduction
    } catch { say(T.tr_error, "bad"); }
  }
  start.onclick = () => {
    final = ""; txt.textContent = ""; out.textContent = ""; listen.disabled = true;
    rec = new SR(); rec.lang = (LANGS[$("v-src").value] || [])[1] || $("v-src").value; rec.interimResults = true; rec.continuous = false; rec.maxAlternatives = 1;
    let failed = false;
    rec.onstart = () => { say(T.listening, "rec"); start.disabled = true; stop.disabled = false; };
    rec.onresult = e => { let interim = ""; for (let i = e.resultIndex; i < e.results.length; i++) { const r = e.results[i]; if (r.isFinal) final += r[0].transcript + " "; else interim += r[0].transcript; } txt.textContent = (final + interim).trim(); };
    rec.onerror = e => { failed = true; idle(); say(ERR[e.error] || T.err_generic, "bad"); };
    rec.onend = () => { if (!failed) finish(); };
    try { rec.start(); } catch { say(T.err_generic, "bad"); }
  };
  stop.onclick = () => { if (rec) rec.stop(); };
  listen.onclick = () => lastOut && WL.speak(lastOut, $("v-dst").value);
  $("v-swap").onclick = () => { const a = $("v-src"), b = $("v-dst"), t = a.value; a.value = b.value; b.value = t; };
  if ("speechSynthesis" in window) speechSynthesis.getVoices();
})();
