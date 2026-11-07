import re
import requests
import config
from languages import LANGUAGES

def _chunks(text, size=450):
    parts, cur = [], ""
    for s in re.split(r"(?<=[.!?。！？\n])\s*", text):
        if len(cur) + len(s) + 1 > size and cur:
            parts.append(cur); cur = ""
        while len(s) > size:
            parts.append(s[:size]); s = s[size:]
        cur = f"{cur} {s}".strip()
    if cur: parts.append(cur)
    return parts

def _mymemory(text, src, dst):
    params = {"q": text, "langpair": f"{'Autodetect' if src == 'auto' else src}|{dst}"}
    if config.MYMEMORY_EMAIL: params["de"] = config.MYMEMORY_EMAIL
    r = requests.get("https://api.mymemory.translated.net/get", params=params, timeout=15)
    r.raise_for_status()
    d = r.json()
    if int(d.get("responseStatus", 0)) != 200:
        raise RuntimeError(d.get("responseDetails", "translation error"))
    det = (d.get("responseData", {}).get("detectedLanguage") or "")[:2].lower()
    return d["responseData"]["translatedText"], det

def _libre(text, src, dst):
    r = requests.post(config.LIBRETRANSLATE_URL.rstrip("/") + "/translate", timeout=20,
                      json={"q": text, "source": src, "target": dst, "api_key": config.LIBRETRANSLATE_KEY})
    r.raise_for_status()
    d = r.json()
    det = (d.get("detectedLanguage") or {}).get("language", "") if isinstance(d.get("detectedLanguage"), dict) else ""
    return d["translatedText"], det

def translate(text, src, dst):
    text = (text or "").strip()
    if not text: raise ValueError("empty")
    if len(text) > 2000: raise ValueError("too long")
    if dst not in LANGUAGES or (src != "auto" and src not in LANGUAGES): raise ValueError("language")
    fn = _libre if (config.TRANSLATE_PROVIDER == "libretranslate" and config.LIBRETRANSLATE_URL) else _mymemory
    out, detected = [], ""
    for ch in _chunks(text):
        t, det = fn(ch, src, dst)
        out.append(t); detected = detected or det
    return " ".join(out), (detected if src == "auto" else src)
