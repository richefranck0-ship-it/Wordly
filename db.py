"""Couche base de données : PostgreSQL (Supabase) en production, SQLite en dev local.
Les dates sont stockées en TEXT ISO UTC, les booléens en INTEGER (portable)."""
import sqlite3, time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import config

IS_PG = config.DATABASE_URL.startswith(("postgres://", "postgresql://"))
_pool = None
if IS_PG:
    import psycopg2, psycopg2.pool, psycopg2.extras
    _pool = psycopg2.pool.ThreadedConnectionPool(
        1, 8, config.DATABASE_URL.replace("postgres://", "postgresql://", 1))

def now(delta_days=0):
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).strftime("%Y-%m-%d %H:%M:%S")

@contextmanager
def _cx():
    if IS_PG:
        c = _pool.getconn()
        try:
            yield c; c.commit()
        except Exception:
            c.rollback(); raise
        finally:
            _pool.putconn(c)
    else:
        c = sqlite3.connect(config.SQLITE_PATH, timeout=15)
        c.row_factory = sqlite3.Row
        try:
            yield c; c.commit()
        except Exception:
            c.rollback(); raise
        finally:
            c.close()

def _cur(c):
    return c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if IS_PG else c.cursor()

def _sql(s):
    return s.replace("?", "%s") if IS_PG else s

def rows(sql, p=()):
    with _cx() as c:
        cur = _cur(c); cur.execute(_sql(sql), tuple(p))
        return [dict(r) for r in cur.fetchall()]

def row(sql, p=()):
    r = rows(sql, p)
    return r[0] if r else None

def val(sql, p=(), default=0):
    r = row(sql, p)
    if not r: return default
    v = list(r.values())[0]
    return default if v is None else v

def run(sql, p=()):
    with _cx() as c:
        cur = _cur(c); cur.execute(_sql(sql), tuple(p))
        return cur.rowcount

def insert(table, data, ignore=False):
    cols = ",".join(data); ph = ",".join("?" * len(data))
    sql = f"INSERT INTO {table} ({cols}) VALUES ({ph})"
    if ignore:
        sql += " ON CONFLICT DO NOTHING"
    elif IS_PG:
        sql += " RETURNING id"
    with _cx() as c:
        cur = _cur(c); cur.execute(_sql(sql), tuple(data.values()))
        if ignore: return cur.rowcount
        return cur.fetchone()["id"] if IS_PG else cur.lastrowid

# ---------------- paramètres du site (cache 30 s) ----------------
_cache = {"t": 0, "d": {}}
DEFAULT_SETTINGS = {
    "site_name": "WORLDLY", "download_url": "", "payment_link": "",
    "payment_instructions": "Après validation, un lien de paiement sécurisé vous sera communiqué.",
    "news_langs": "fr,en", "news_retention_days": "14", "contact_email": "contact@example.com",
    "ads_enabled": "1", "news_last_refresh": "",
}

def settings():
    if time.time() - _cache["t"] > 30:
        _cache["d"] = {r["key"]: r["value"] for r in rows("SELECT key, value FROM settings")}
        _cache["t"] = time.time()
    return _cache["d"]

def setting(key, default=""):
    return settings().get(key, DEFAULT_SETTINGS.get(key, default))

def set_setting(key, value):
    run("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)))
    _cache["t"] = 0

# ---------------- schéma (idempotent : ne supprime jamais de données) ----------------
_ID = "SERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
SCHEMA = [
 "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)",
 f"""CREATE TABLE IF NOT EXISTS categories (slug TEXT PRIMARY KEY, label TEXT, q_en TEXT, q_fr TEXT, q_es TEXT,
     active INTEGER DEFAULT 1, position INTEGER DEFAULT 0)""",
 f"""CREATE TABLE IF NOT EXISTS sources (id {_ID}, domain TEXT UNIQUE, name TEXT, active INTEGER DEFAULT 1, created_at TEXT)""",
 f"""CREATE TABLE IF NOT EXISTS articles (id {_ID}, url_hash TEXT UNIQUE, title_key TEXT UNIQUE, title TEXT, url TEXT,
     image TEXT, country TEXT, domain TEXT, source_name TEXT, category TEXT, language TEXT, published_at TEXT, fetched_at TEXT,
     featured INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0, manual INTEGER DEFAULT 0, clicks INTEGER DEFAULT 0)""",
 "CREATE INDEX IF NOT EXISTS idx_articles_pub ON articles(published_at)",
 f"""CREATE TABLE IF NOT EXISTS push_subscriptions (id {_ID}, endpoint TEXT UNIQUE, p256dh TEXT, auth TEXT, lang TEXT,
     categories TEXT DEFAULT 'news,weather,worldly,ads', weather_on INTEGER DEFAULT 0, weather_lat REAL, weather_lon REAL,
     weather_city TEXT, topics TEXT DEFAULT '', alert_day TEXT, enabled INTEGER DEFAULT 1, fail_count INTEGER DEFAULT 0, created_at TEXT, last_ok TEXT)""",
 f"""CREATE TABLE IF NOT EXISTS notifications (id {_ID}, title TEXT, body TEXT, url TEXT, category TEXT, kind TEXT,
     sent_count INTEGER DEFAULT 0, failed_count INTEGER DEFAULT 0, created_at TEXT)""",
 f"""CREATE TABLE IF NOT EXISTS ad_requests (id {_ID}, advertiser TEXT, email TEXT, description TEXT, duration_days INTEGER,
     link TEXT, status TEXT DEFAULT 'pending', token TEXT UNIQUE, admin_note TEXT, created_at TEXT)""",
 f"""CREATE TABLE IF NOT EXISTS campaigns (id {_ID}, request_id INTEGER, title TEXT, text TEXT, link TEXT, start_at TEXT,
     end_at TEXT, image_url TEXT, image_data TEXT, image_mime TEXT, placement TEXT DEFAULT 'bottom', active INTEGER DEFAULT 0, paid INTEGER DEFAULT 0, impressions INTEGER DEFAULT 0, clicks INTEGER DEFAULT 0,
     created_at TEXT)""",
 "CREATE TABLE IF NOT EXISTS visits (day TEXT PRIMARY KEY, hits INTEGER DEFAULT 0, uniques INTEGER DEFAULT 0)",
 f"CREATE TABLE IF NOT EXISTS error_logs (id {_ID}, created_at TEXT, path TEXT, message TEXT)",
 f"CREATE TABLE IF NOT EXISTS contact_messages (id {_ID}, name TEXT, email TEXT, message TEXT, created_at TEXT, handled INTEGER DEFAULT 0)",
]
SCHEMA += [
 f"""CREATE TABLE IF NOT EXISTS feeds (id {_ID}, name TEXT, url TEXT UNIQUE, site_url TEXT, category TEXT DEFAULT 'world', language TEXT DEFAULT 'fr',
     country TEXT DEFAULT '', active INTEGER DEFAULT 1, partner_id INTEGER, last_fetch TEXT, last_error TEXT DEFAULT '', last_count INTEGER DEFAULT 0, created_at TEXT)""",
 f"""CREATE TABLE IF NOT EXISTS partner_sites (id {_ID}, name TEXT, url TEXT, description TEXT, logo_url TEXT, feed_url TEXT, feed_lang TEXT DEFAULT 'fr',
     email TEXT, status TEXT DEFAULT 'pending', featured INTEGER DEFAULT 0, clicks INTEGER DEFAULT 0, token TEXT UNIQUE, admin_note TEXT, created_at TEXT)""",
]
SEED_FEEDS = [
 ("BBC News – World", "https://feeds.bbci.co.uk/news/world/rss.xml", "world", "en", "United Kingdom"),
 ("BBC Sport – Football", "https://feeds.bbci.co.uk/sport/football/rss.xml", "football", "en", "United Kingdom"),
 ("France 24", "https://www.france24.com/fr/rss", "world", "fr", "France"),
 ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", "world", "en", "Qatar"),
]
CATEGORIES = [
 ("world", "International", "(world OR international OR global)", "(monde OR international OR mondial)", "(mundo OR internacional)"),
 ("politics", "Politique", "(politics OR government OR election)", "(politique OR gouvernement OR élection)", "(política OR gobierno OR elecciones)"),
 ("economy", "Économie", "(economy OR inflation OR markets)", "(économie OR inflation OR marchés)", "(economía OR inflación OR mercados)"),
 ("sport", "Sport", "(sport OR football OR tennis)", "(sport OR football OR tennis)", "(deporte OR fútbol OR tenis)"),
 ("football", "Football", "(football OR soccer OR \"premier league\" OR \"champions league\" OR \"world cup\")", "(football OR \"ligue 1\" OR \"ligue des champions\" OR \"coupe du monde\")", "(fútbol OR \"la liga\" OR \"champions league\" OR \"copa del mundo\")"),
 ("tech", "Technologie", "(technology OR \"artificial intelligence\" OR software)", "(technologie OR \"intelligence artificielle\" OR numérique)", "(tecnología OR \"inteligencia artificial\")"),
 ("health", "Santé", "(health OR medicine OR hospital)", "(santé OR médecine OR hôpital)", "(salud OR medicina OR hospital)"),
 ("science", "Sciences", "(science OR research OR space)", "(science OR recherche OR espace)", "(ciencia OR investigación OR espacio)"),
 ("entertainment", "Divertissement", "(movie OR music OR celebrity)", "(cinéma OR musique OR célébrité)", "(cine OR música OR famosos)"),
]

def _add_col(table, col, typ):
    try: run(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")   # migration additive (bases déjà existantes)
    except Exception: pass

def init_db():
    for stmt in SCHEMA:
        run(stmt)
    _add_col("articles", "country", "TEXT")
    _add_col("push_subscriptions", "topics", "TEXT DEFAULT ''")
    for col, typ in (("image_url", "TEXT"), ("image_data", "TEXT"), ("image_mime", "TEXT"), ("placement", "TEXT DEFAULT 'bottom'")):
        _add_col("campaigns", col, typ)
    for i, c in enumerate(CATEGORIES):
        insert("categories", dict(slug=c[0], label=c[1], q_en=c[2], q_fr=c[3], q_es=c[4], active=1, position=i), ignore=True)
    for k, v in DEFAULT_SETTINGS.items():
        insert("settings", dict(key=k, value=v), ignore=True)
    if not row("SELECT value FROM settings WHERE key='feeds_seeded'"):   # une seule fois : les suppressions de l'admin sont respectées
        for n, u, c, l, co in SEED_FEEDS:
            insert("feeds", dict(name=n, url=u, site_url="", category=c, language=l, country=co, active=1, created_at=now()), ignore=True)
        insert("settings", dict(key="feeds_seeded", value="1"), ignore=True)
