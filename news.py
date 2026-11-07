"""Actualités via GDELT DOC 2.0. On ne stocke que titre, lien, image (lien), source et date :
aucun texte d'article n'est copié ; chaque article renvoie vers la source d'origine."""
import re, time, hashlib, threading
from datetime import datetime
from urllib.parse import urlparse
import requests
import db

GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
LANG_MAP = {"fr": ("french", "q_fr"), "en": ("english", "q_en"), "es": ("spanish", "q_es")}
CODE_OF = {"french": "fr", "english": "en", "spanish": "es"}
_lock = threading.Lock()

def norm_url(u):
    p = urlparse(u)
    return f"{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}"

def title_key(t):
    return hashlib.sha1(re.sub(r"[^a-z0-9]+", "", t.lower())[:80].encode()).hexdigest()

def _parse_date(s):
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return db.now()

def _source(domain):
    s = db.row("SELECT * FROM sources WHERE domain=?", (domain,))
    if not s:
        db.insert("sources", dict(domain=domain, name=domain, active=1, created_at=db.now()), ignore=True)
        return {"domain": domain, "name": domain, "active": 1}
    return s

def store(items, category, lang_code):
    added = 0
    for it in items:
        url, title = (it.get("url") or "").strip(), (it.get("title") or "").strip()
        if not url.startswith(("http://", "https://")) or len(title) < 12:
            continue
        domain = (it.get("domain") or urlparse(url).netloc).lower().removeprefix("www.")
        src = _source(domain)
        if not src["active"]:
            continue
        img = it.get("socialimage") or ""
        added += db.insert("articles", dict(
            url_hash=hashlib.sha1(norm_url(url).encode()).hexdigest(), title_key=title_key(title),
            title=title[:300], url=url[:1000], image=img if img.startswith("https://") else "",
            domain=domain, source_name=src["name"] or domain, category=category, language=lang_code,
            published_at=_parse_date(it.get("seendate", "")), fetched_at=db.now()), ignore=True) or 0
    return added

def fetch(query, sourcelang, timespan="24h", maxrecords=60):
    r = requests.get(GDELT, params={"query": f"{query} sourcelang:{sourcelang}", "mode": "ArtList", "format": "json",
                     "maxrecords": maxrecords, "sort": "DateDesc", "timespan": timespan},
                     headers={"User-Agent": "WORLDLY/1.0"}, timeout=25)
    r.raise_for_status()
    return r.json().get("articles", [])

def refresh_all(pause=5.5):
    """Dédoublonnage par URL normalisée et par titre. Une seule exécution à la fois."""
    if not _lock.acquire(blocking=False):
        return {"running": True}
    total, errors = 0, []
    try:
        langs = [l for l in db.setting("news_langs", "fr,en").split(",") if l in LANG_MAP]
        cats = db.rows("SELECT * FROM categories WHERE active=1 ORDER BY position")
        first = True
        for c in cats:
            for l in langs:
                gl, col = LANG_MAP[l]
                if not c.get(col):
                    continue
                if not first: time.sleep(pause)
                first = False
                try:
                    total += store(fetch(c[col], gl), c["slug"], l)
                except Exception as e:
                    errors.append(f"{c['slug']}/{l}: {e}")
        days = int(db.setting("news_retention_days", "14") or 14)
        db.run("DELETE FROM articles WHERE manual=0 AND featured=0 AND published_at < ?", (db.now(-days),))
        db.set_setting("news_last_refresh", db.now())
        return {"added": total, "errors": errors}
    finally:
        _lock.release()

def refresh_async():
    threading.Thread(target=refresh_all, daemon=True).start()

def stale(minutes=60):
    last = db.setting("news_last_refresh", "")
    return (not last) or last < db.now(-minutes / 1440)

def query(cat="", q="", lang="", page=1, per=20, order="recent"):
    where, p = ["hidden=0"], []
    if cat: where.append("category=?"); p.append(cat)
    if lang: where.append("language=?"); p.append(lang)
    if q:
        where.append("LOWER(title) LIKE ?"); p.append("%" + q.lower().replace("%", "") + "%")
    order_sql = "clicks DESC, published_at DESC" if order == "popular" else "featured DESC, published_at DESC"
    if order == "popular": where.append("published_at > ?"); p.append(db.now(-3))
    sql = f"SELECT * FROM articles WHERE {' AND '.join(where)} ORDER BY {order_sql} LIMIT ? OFFSET ?"
    return db.rows(sql, p + [per + 1, (page - 1) * per])
