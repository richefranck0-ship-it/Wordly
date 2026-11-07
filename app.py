import os, re, json, hmac, secrets, time, traceback
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse
from flask import (Flask, request, session, render_template, redirect, url_for, jsonify, abort, flash,
                   make_response, send_from_directory, g, Response)
from werkzeug.security import check_password_hash
import config, db, i18n, news, push, translate as tr, weather_alerts
from languages import LANGUAGES, UI_LANGS, RTL

if config.IS_PROD and not config.SECRET_KEY:
    raise RuntimeError("SECRET_KEY manquant (variable d'environnement obligatoire en production)")

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=config.IS_PROD,
                  MAX_CONTENT_LENGTH=64 * 1024, PERMANENT_SESSION_LIFETIME=60 * 60 * 8, JSON_AS_ASCII=False)
db.init_db()

ASSET_V = str(int(max(os.path.getmtime(os.path.join(r, f)) for r, _, fs in os.walk(os.path.join(app.root_path, "static")) for f in fs)))
URL_RE = re.compile(r"^https?://[^\s<>\"']{3,500}$")
MAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")

# ------------------------------------------------------------------ utilitaires
from app_utils import limited_ip as limited

def current_lang():
    c = request.cookies.get("wl_lang")
    if c in UI_LANGS: return c
    best = request.accept_languages.best_match(list(UI_LANGS))
    return best or "fr"

def safe_next(n):
    return n if n and n.startswith("/") and not n.startswith("//") else "/"

def csrf_token():
    if "csrf" not in session: session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]

def active_ads():
    if db.setting("ads_enabled", "1") != "1": return []
    n = db.now()
    ads = db.rows("SELECT * FROM campaigns WHERE active=1 AND paid=1 AND start_at<=? AND end_at>=? ORDER BY id LIMIT 2", (n, n))
    for a in ads: db.run("UPDATE campaigns SET impressions=impressions+1 WHERE id=?", (a["id"],))
    return ads

def log_error(msg):
    try: db.insert("error_logs", dict(created_at=db.now(), path=request.path[:200], message=msg[:2000]))
    except Exception: pass

@app.context_processor
def inject():
    lang = getattr(g, "lang", "fr")
    t = i18n.get(lang)
    is_admin = request.path.startswith(config.ADMIN_PATH)
    return dict(t=t, lang=lang, rtl=lang in RTL, ui_langs=UI_LANGS, languages=LANGUAGES, csrf_token=csrf_token,
                site_name=db.setting("site_name", "WORLDLY"), ads=[] if is_admin else active_ads(), v=ASSET_V,
                vapid_key=config.VAPID_PUBLIC_KEY, download_url=db.setting("download_url", ""),
                canonical=(config.SITE_URL or request.url_root.rstrip("/")) + request.path, is_admin=is_admin,
                js_cfg=json.dumps({"t": t, "lang": lang, "vapid": config.VAPID_PUBLIC_KEY, "csrf": csrf_token(),
                                   "langs": {k: v for k, v in LANGUAGES.items()}}, ensure_ascii=False).replace("</", "<\\/"))

@app.before_request
def before():
    g.lang = current_lang()
    if request.method == "POST" and not request.path.startswith("/cron/"):
        tok = request.headers.get("X-CSRF-Token") or request.form.get("csrf", "")
        if not tok or not hmac.compare_digest(tok, session.get("csrf", "")):
            abort(400, "CSRF")

@app.after_request
def after(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "microphone=(self), geolocation=(self), camera=()"
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src * data:; media-src *; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; script-src 'self'; connect-src 'self' https://api.open-meteo.com https://geocoding-api.open-meteo.com; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    if request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "public, max-age=604800"
    elif resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-cache"
        if request.path.startswith(config.ADMIN_PATH): resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        # statistiques de visites (sans identifiant personnel, hors robots et admin)
        if (request.method == "GET" and resp.status_code == 200 and not request.path.startswith(config.ADMIN_PATH)
                and not re.search(r"bot|crawl|spider|slurp", request.user_agent.string, re.I)):
            day, new = db.now()[:10], request.cookies.get("wl_v") != db.now()[:10]
            try:
                db.run("INSERT INTO visits(day,hits,uniques) VALUES(?,1,?) ON CONFLICT(day) DO UPDATE SET hits=visits.hits+1, uniques=visits.uniques+excluded.uniques", (day, 1 if new else 0))
                if new: resp.set_cookie("wl_v", day, max_age=86400, samesite="Lax", secure=config.IS_PROD)
            except Exception: pass
    return resp

@app.errorhandler(404)
def e404(e):
    if request.path.startswith("/api/"): return jsonify(error="not_found"), 404
    return render_template("404.html", page_title="404"), 404

@app.errorhandler(400)
@app.errorhandler(429)
def e4xx(e):
    if request.path.startswith("/api/") or request.is_json: return jsonify(error=str(e.description)), e.code
    return render_template("error.html", code=e.code, msg=e.description), e.code

@app.errorhandler(Exception)
def e500(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException): return e
    log_error(traceback.format_exc())
    if request.path.startswith("/api/"): return jsonify(error="server_error"), 500
    return render_template("error.html", code=500, msg="Erreur serveur"), 500

# ------------------------------------------------------------------ pages publiques
def maybe_refresh():
    if news.stale(60): news.refresh_async()

@app.route("/")
def index():
    maybe_refresh()
    top = news.query(order="recent", per=9)
    return render_template("index.html", top=top[:8], popular=news.query(order="popular", per=5)[:5],
                           page_title="WORLDLY – " + g_t("tagline"), page_desc=g_t("hero_sub"),
                           categories=db.rows("SELECT * FROM categories WHERE active=1 ORDER BY position"))

def g_t(k): return i18n.get(g.lang)[k]

@app.route("/news")
def news_page():
    maybe_refresh()
    cat, q, l = request.args.get("cat", "")[:30], request.args.get("q", "").strip()[:80], request.args.get("l", "")
    page = max(1, request.args.get("page", 1, type=int))
    items = news.query(cat, q, l if l in ("fr", "en", "es") else "", page)
    more = len(items) > 20
    cats = db.rows("SELECT * FROM categories WHERE active=1 ORDER BY position")
    return render_template("news.html", items=items[:20], more=more, page=page, cat=cat, q=q, l=l, categories=cats,
                           latest_id=db.val("SELECT MAX(id) FROM articles"), page_title=g_t("news") + " – WORLDLY",
                           page_desc=g_t("latest"))

@app.route("/go/<int:aid>")
def go(aid):
    a = db.row("SELECT url FROM articles WHERE id=?", (aid,))
    if not a: abort(404)
    db.run("UPDATE articles SET clicks=clicks+1 WHERE id=?", (aid,))
    return redirect(a["url"], 302)

@app.route("/ads/click/<int:cid>")
def ad_click(cid):
    c = db.row("SELECT link FROM campaigns WHERE id=? AND active=1 AND paid=1", (cid,))
    if not c: abort(404)
    db.run("UPDATE campaigns SET clicks=clicks+1 WHERE id=?", (cid,))
    return redirect(c["link"], 302)

@app.route("/weather")
def weather_page(): return render_template("weather.html", page_title=g_t("weather") + " – WORLDLY", page_desc=g_t("weather"))

@app.route("/translate")
def translate_page(): return render_template("translate.html", page_title=g_t("translate") + " – WORLDLY", page_desc=g_t("quick_translate"))

@app.route("/voice")
def voice_page(): return render_template("voice.html", page_title=g_t("voice") + " – WORLDLY", page_desc=g_t("quick_voice"))

@app.route("/notifications")
def notifications_page(): return render_template("notifications.html", page_title=g_t("notifications") + " – WORLDLY")

@app.route("/download")
def download_page(): return render_template("download.html", page_title=g_t("download") + " – WORLDLY")

@app.route("/offline")
def offline(): return render_template("offline.html", page_title="Offline")

@app.route("/lang/<code>")
def set_lang(code):
    resp = redirect(safe_next(request.args.get("next", "/")))
    if code in UI_LANGS: resp.set_cookie("wl_lang", code, max_age=31536000, samesite="Lax", secure=config.IS_PROD)
    return resp

PAGES = {"faq": "faq.html", "terms": "terms.html", "privacy": "privacy.html", "legal": "legal.html", "privacy-settings": "privacy_settings.html"}
for slug, tpl in PAGES.items():
    app.add_url_rule(f"/{slug}", slug, (lambda tpl=tpl: render_template(tpl, page_title=tpl.split(".")[0].replace("_", " ").title() + " – WORLDLY")))

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        f = request.form
        if f.get("website"): return redirect("/contact")        # honeypot
        if limited("contact", 3, 3600): abort(429, "Trop de messages. Réessayez plus tard.")
        name, email, msg = f.get("name", "").strip()[:100], f.get("email", "").strip()[:255], f.get("message", "").strip()[:3000]
        if len(name) < 2 or not MAIL_RE.match(email) or len(msg) < 10:
            flash("Merci de remplir correctement tous les champs.", "err")
        else:
            db.insert("contact_messages", dict(name=name, email=email, message=msg, created_at=db.now()))
            flash("Message envoyé. Merci !", "ok")
            return redirect("/contact")
    return render_template("contact.html", page_title="Contact – WORLDLY")

# ------------------------------------------------------------------ publicités
@app.route("/advertise", methods=["GET", "POST"])
def advertise():
    if request.method == "POST":
        f = request.form
        if f.get("website"): return redirect("/advertise")
        if limited("ad", 3, 3600): abort(429, "Trop de demandes. Réessayez plus tard.")
        d = dict(advertiser=f.get("advertiser", "").strip()[:100], email=f.get("email", "").strip()[:255],
                 description=f.get("description", "").strip()[:1000], link=f.get("link", "").strip(),
                 duration_days=f.get("duration", 7, type=int))
        if (len(d["advertiser"]) < 2 or not MAIL_RE.match(d["email"]) or len(d["description"]) < 20
                or not URL_RE.match(d["link"]) or d["duration_days"] not in (7, 14, 30) or not f.get("consent")):
            flash("Vérifiez les champs (description ≥ 20 caractères, lien http(s) valide, consentement).", "err")
            return render_template("advertise.html", form=f, page_title="Publicité – WORLDLY"), 400
        d.update(status="pending", token=secrets.token_urlsafe(16), created_at=db.now())
        db.insert("ad_requests", d)
        return redirect(url_for("ad_status", token=d["token"]))
    return render_template("advertise.html", form={}, page_title="Publicité – WORLDLY")

@app.route("/advertise/status/<token>")
def ad_status(token):
    r = db.row("SELECT * FROM ad_requests WHERE token=?", (token,))
    if not r: abort(404)
    return render_template("ad_status.html", r=r, payment_link=db.setting("payment_link"),
                           payment_instructions=db.setting("payment_instructions"), page_title="Suivi – WORLDLY")

# ------------------------------------------------------------------ API publique
@app.post("/api/translate")
def api_translate():
    if limited("tr", 40, 60): return jsonify(error="rate_limited"), 429
    j = request.get_json(silent=True) or {}
    try:
        text, det = tr.translate(j.get("text"), j.get("src", "auto"), j.get("dst", "en"))
        return jsonify(text=text, detected=det)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        log_error(f"translate: {e}")
        return jsonify(error="provider"), 502

@app.get("/api/news/status")
def api_news_status():
    return jsonify(latest_id=db.val("SELECT MAX(id) FROM articles"), last_refresh=db.setting("news_last_refresh"))

@app.get("/api/notifications")
def api_notifications():
    return jsonify(items=db.rows("SELECT title, body, url, category, created_at FROM notifications ORDER BY id DESC LIMIT 30"))

@app.get("/api/push/config")
def api_push_config(): return jsonify(enabled=push.enabled(), key=config.VAPID_PUBLIC_KEY)

@app.post("/api/push/subscribe")
def api_push_subscribe():
    if limited("sub", 30, 3600): return jsonify(error="rate_limited"), 429
    j = request.get_json(silent=True) or {}
    s, keys = j.get("subscription") or {}, (j.get("subscription") or {}).get("keys") or {}
    ep = s.get("endpoint", "")
    if not push.valid_endpoint(ep) or not keys.get("p256dh") or not keys.get("auth"): return jsonify(error="invalid"), 400
    cats = ",".join(c for c in (j.get("categories") or []) if c in push.CATS)
    w = j.get("weather") or {}
    wl = (isinstance(w.get("lat"), (int, float)) and isinstance(w.get("lon"), (int, float)) and abs(w["lat"]) <= 90 and abs(w["lon"]) <= 180)
    data = dict(p256dh=keys["p256dh"][:200], auth=keys["auth"][:100], lang=j.get("lang") if j.get("lang") in UI_LANGS else "fr",
                categories=cats, weather_on=1 if (w.get("on") and wl) else 0, weather_lat=w["lat"] if wl else None,
                weather_lon=w["lon"] if wl else None, weather_city=str(w.get("city", ""))[:80], enabled=1)
    if db.row("SELECT id FROM push_subscriptions WHERE endpoint=?", (ep,)):
        sets = ",".join(f"{k}=?" for k in data)
        db.run(f"UPDATE push_subscriptions SET {sets} WHERE endpoint=?", (*data.values(), ep))
    else:
        db.insert("push_subscriptions", dict(endpoint=ep, created_at=db.now(), **data))
    return jsonify(ok=True)

@app.post("/api/push/prefs")
def api_push_prefs():
    ep = (request.get_json(silent=True) or {}).get("endpoint", "")
    r = db.row("SELECT categories, weather_on, weather_city FROM push_subscriptions WHERE endpoint=?", (ep,))
    return jsonify(subscribed=bool(r), categories=(r["categories"].split(",") if r and r["categories"] else []),
                   weather_on=bool(r and r["weather_on"]), city=r["weather_city"] if r else "")

@app.post("/api/push/unsubscribe")
def api_push_unsub():
    db.run("DELETE FROM push_subscriptions WHERE endpoint=?", ((request.get_json(silent=True) or {}).get("endpoint", ""),))
    return jsonify(ok=True)

@app.post("/api/log-error")
def api_log_error():
    if limited("jserr", 10, 600): return jsonify(ok=False), 429
    log_error("JS: " + str((request.get_json(silent=True) or {}).get("message", ""))[:800]); return jsonify(ok=True)

# ------------------------------------------------------------------ cron (Render Cron Job / pinger externe)
def cron_ok():
    tok = request.headers.get("X-Cron-Token") or request.args.get("token", "")
    return bool(config.CRON_TOKEN) and hmac.compare_digest(tok, config.CRON_TOKEN)

@app.route("/cron/refresh-news", methods=["GET", "POST"])
def cron_news():
    if not cron_ok(): abort(403)
    news.refresh_async(); return jsonify(started=True)

@app.route("/cron/weather-alerts", methods=["GET", "POST"])
def cron_weather():
    if not cron_ok(): abort(403)
    return jsonify(sent=weather_alerts.run())

# ------------------------------------------------------------------ PWA / SEO
@app.route("/sw.js")
def sw():
    r = send_from_directory("static/js", "sw.js", mimetype="application/javascript")
    r.headers["Service-Worker-Allowed"] = "/"; r.headers["Cache-Control"] = "no-cache"; return r

@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory("static", "manifest.webmanifest", mimetype="application/manifest+json")

@app.route("/favicon.ico")
def favicon(): return send_from_directory("static/icons", "favicon.ico")

@app.route("/robots.txt")
def robots():
    base = config.SITE_URL or request.url_root.rstrip("/")
    return Response(f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /go/\nDisallow: /advertise/status/\nSitemap: {base}/sitemap.xml\n", mimetype="text/plain")

@app.route("/sitemap.xml")
def sitemap():
    base = config.SITE_URL or request.url_root.rstrip("/")
    paths = ["/", "/news", "/weather", "/translate", "/voice", "/notifications", "/download", "/advertise", "/faq",
             "/terms", "/privacy", "/legal", "/contact"] + [f"/news?cat={c['slug']}" for c in db.rows("SELECT slug FROM categories WHERE active=1")]
    body = "".join(f"<url><loc>{base}{p.replace('&', '&amp;')}</loc></url>" for p in paths)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>', mimetype="application/xml")

import admin  # noqa: E402  (enregistre le blueprint d'administration)
app.register_blueprint(admin.bp, url_prefix=config.ADMIN_PATH)

if __name__ == "__main__":
    app.run(debug=not config.IS_PROD, port=int(os.getenv("PORT", 5000)))
