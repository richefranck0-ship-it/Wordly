"""Traduction avec chaîne de secours : si un service échoue, le suivant prend le relais.
Ordre : service configuré (LibreTranslate si défini) -> MyMemory -> Google (point d'accès public non officiel)."""
import re
import requests
import config
from languages import LANGUAGES

UA = {"User-Agent": "Mozilla/5.0 (compatible; WORLDLY/1.0)"}
MM_CODE = {"zh": "zh-CN", "he": "he-IL"}   # MyMemory attend certains codes régionaux

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
    s = "Autodetect" if src == "auto" else MM_CODE.get(src, src)
    params = {"q": text, "langpair": f"{s}|{MM_CODE.get(dst, dst)}"}
    if config.MYMEMORY_EMAIL: params["de"] = config.MYMEMORY_EMAIL
    r = requests.get("https://api.mymemory.translated.net/get", params=params, headers=UA, timeout=15)
    r.raise_for_status()
    d = r.json()
    if int(d.get("responseStatus", 0)) != 200:
        raise RuntimeError(f"mymemory {d.get('responseStatus')}: {d.get('responseDetails', '')}")
    out = d["responseData"]["translatedText"]
    if "MYMEMORY WARNING" in out.upper() or "QUERY LENGTH LIMIT" in out.upper():
        raise RuntimeError("mymemory quota")
    return out, (d["responseData"].get("detectedLanguage") or "")[:2].lower()

def _libre(text, src, dst):
    r = requests.post(config.LIBRETRANSLATE_URL.rstrip("/") + "/translate", timeout=20,
                      json={"q": text, "source": src, "target": dst, "api_key": config.LIBRETRANSLATE_KEY})
    r.raise_for_status()
    d = r.json()
    det = d.get("detectedLanguage")
    return d["translatedText"], (det.get("language", "") if isinstance(det, dict) else "")

def _google(text, src, dst):
    r = requests.get("https://translate.googleapis.com/translate_a/single", headers=UA, timeout=15,
                     params={"client": "gtx", "sl": "auto" if src == "auto" else ("zh-CN" if src == "zh" else src),
                             "tl": "zh-CN" if dst == "zh" else dst, "dt": "t", "q": text})
    r.raise_for_status()
    d = r.json()
    return "".join(x[0] for x in d[0] if x and x[0]), (d[2] if len(d) > 2 and isinstance(d[2], str) else "")[:2].lower()

def _providers(src):
    chain = []
    if config.TRANSLATE_PROVIDER == "libretranslate" and config.LIBRETRANSLATE_URL: chain.append(_libre)
    chain += [_google, _mymemory] if src == "auto" else [_mymemory, _google]   # Google détecte mieux la langue
    return chain

def translate(text, src, dst):
    text = (text or "").strip()
    if not text: raise ValueError("empty")
    if len(text) > 2000: raise ValueError("too long")
    if dst not in LANGUAGES or (src != "auto" and src not in LANGUAGES): raise ValueError("language")
    errors = []
    for fn in _providers(src):
        try:
            out, detected = [], ""
            for ch in _chunks(text):
                t, det = fn(ch, src, dst)
                out.append(t); detected = detected or det
            return " ".join(out), (detected if src == "auto" else src)
        except Exception as e:
            errors.append(f"{fn.__name__}: {e}")
    raise RuntimeError(" | ".join(errors))
