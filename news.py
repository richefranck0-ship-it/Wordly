"""Actualités via GDELT DOC 2.0. On ne stocke que titre, lien, image (lien), source et date :
aucun texte d'article n'est copié ; chaque article renvoie vers la source d'origine."""
import re, time, hashlib, threading, socket, ipaddress
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
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
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y-%m-%d %H:%M:%S"):
        try: return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except Exception: pass
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
            title=title[:300], url=url[:1000], image=img if img.startswith("https://") else "", country=(it.get("sourcecountry") or "")[:60],
            domain=domain, source_name=(it.get("source_name") or src["name"] or domain)[:100], category=category, language=lang_code,
            published_at=_parse_date(it.get("seendate", "")), fetched_at=db.now()), ignore=True) or 0
    return added

UA = {"User-Agent": "Mozilla/5.0 (compatible; WORLDLY/1.0)"}
MAX_FEED = 2_000_000

def safe_get(url, max_bytes=MAX_FEED, timeout=15):
    """Téléchargement protégé (SSRF) : adresses publiques uniquement, redirections revérifiées, taille limitée."""
    for _ in range(4):
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname: raise ValueError("URL invalide")
        for ai in socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP):
            if not ipaddress.ip_address(ai[4][0]).is_global: raise ValueError("adresse non publique refusée")
        r = requests.get(url, headers=UA, timeout=timeout, stream=True, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, r.headers.get("Location", "")); r.close(); continue
        r.raise_for_status()
        data = r.raw.read(max_bytes + 1, decode_content=True); r.close()
        if len(data) > max_bytes: raise ValueError("flux trop volumineux")
        return data
    raise ValueError("trop de redirections")

def _local(tag): return tag.rsplit("}", 1)[-1]

def _feed_date(s):
    s = (s or "").strip()
    try: d = parsedate_to_datetime(s)
    except Exception:
        try: d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception: return db.now()
    if d.tzinfo: d = d.astimezone(__import__("datetime").timezone.utc)
    return d.strftime("%Y-%m-%d %H:%M:%S")

def parse_feed(data):
    """RSS 2.0 / Atom. On ne garde que titre, lien, date et image : jamais le texte de l'article."""
    if b"<!ENTITY" in data.upper(): raise ValueError("flux refusé (entités XML)")
    items = []
    for el in ET.fromstring(data).iter():
        if _local(el.tag) not in ("item", "entry"): continue
        it = {"title": "", "url": "", "socialimage": "", "seendate": ""}
        for ch in el:
            n = _local(ch.tag)
            if n == "title": it["title"] = re.sub(r"\s+", " ", "".join(ch.itertext())).strip()
            elif n == "link":
                if ch.get("href"):
                    if ch.get("rel", "alternate") == "alternate" or not it["url"]: it["url"] = ch.get("href")
                elif (ch.text or "").strip(): it["url"] = ch.text.strip()
            elif n in ("pubDate", "published", "updated", "date") and not it["seendate"]: it["seendate"] = _feed_date(ch.text)
            elif n in ("content", "thumbnail") and ch.get("url") and not it["socialimage"]: it["socialimage"] = ch.get("url")
            elif n == "enclosure" and (ch.get("type") or "").startswith("image/") and not it["socialimage"]: it["socialimage"] = ch.get("url", "")
        if it["title"] and it["url"]: items.append(it)
    return items

def refresh_feeds():
    total, errors = 0, []
    for f in db.rows("SELECT * FROM feeds WHERE active=1"):
        try:
            items = parse_feed(safe_get(f["url"]))[:40]
            for it in items: it["source_name"], it["sourcecountry"] = f["name"], f["country"] or ""
            n = store(items, f["category"] or "world", f["language"] or "fr")
            db.run("UPDATE feeds SET last_fetch=?, last_error='', last_count=? WHERE id=?", (db.now(), n, f["id"])); total += n
        except Exception as e:
            db.run("UPDATE feeds SET last_fetch=?, last_error=? WHERE id=?", (db.now(), str(e)[:300], f["id"])); errors.append(f"{f['name']}: {e}")
    return {"added": total, "errors": errors}

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
        rf = refresh_feeds(); total += rf["added"]; errors += rf["errors"]
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

def countries():
    return db.rows("SELECT country, COUNT(*) AS n FROM articles WHERE hidden=0 AND country IS NOT NULL AND country<>'' GROUP BY country ORDER BY n DESC LIMIT 80")

def query(cat="", q="", lang="", page=1, per=20, order="recent", country=""):
    where, p = ["hidden=0"], []
    if cat: where.append("category=?"); p.append(cat)
    if lang: where.append("language=?"); p.append(lang)
    if country: where.append("country=?"); p.append(country)
    if q:
        where.append("LOWER(title) LIKE ?"); p.append("%" + q.lower().replace("%", "") + "%")
    order_sql = "clicks DESC, published_at DESC" if order == "popular" else "featured DESC, published_at DESC"
    if order == "popular": where.append("published_at > ?"); p.append(db.now(-3))
    sql = f"SELECT * FROM articles WHERE {' AND '.join(where)} ORDER BY {order_sql} LIMIT ? OFFSET ?"
    return db.rows(sql, p + [per + 1, (page - 1) * per])
