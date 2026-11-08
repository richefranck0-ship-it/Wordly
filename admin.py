import re, secrets
from functools import wraps
from flask import Blueprint, request, session, render_template, redirect, url_for, flash, abort
from werkzeug.security import check_password_hash
import hmac, config, db, news, push
from app_utils import limited_ip

bp = Blueprint("admin", __name__)
URL_RE = re.compile(r"^https?://[^\s<>\"']{3,500}$")
SECTIONS = ["dashboard", "news", "categories", "sources", "ads", "notifications", "messages", "errors", "settings"]

def required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("admin"): return redirect(url_for("admin.login"))
        return f(*a, **k)
    return w

def back(section): return redirect(url_for("admin." + section))

@bp.route("/login", methods=["GET", "POST"])
def login():
    configured = bool(config.ADMIN_PASSWORD_HASH or config.ADMIN_PASSWORD)
    if request.method == "POST":
        if limited_ip("login", 5, 900): abort(429, "Trop de tentatives. Réessayez dans 15 minutes.")
        u, p = request.form.get("user", ""), request.form.get("password", "")
        ok = configured and hmac.compare_digest(u, config.ADMIN_USER) and (
            check_password_hash(config.ADMIN_PASSWORD_HASH, p) if config.ADMIN_PASSWORD_HASH
            else hmac.compare_digest(p, config.ADMIN_PASSWORD))
        if ok:
            session.clear(); session["admin"] = True; session.permanent = True
            return back("dashboard")
        flash("Identifiants incorrects.", "err")
    return render_template("admin/login.html", configured=configured, page_title="Admin")

@bp.post("/logout")
def logout():
    session.clear(); return redirect(url_for("admin.login"))

@bp.route("/")
@required
def dashboard():
    d, n = db.now()[:10], db.now()
    stats = dict(
        today=db.row("SELECT hits, uniques FROM visits WHERE day=?", (d,)) or {"hits": 0, "uniques": 0},
        week=db.val("SELECT SUM(uniques) FROM visits WHERE day>=?", (db.now(-7)[:10],)),
        month=db.val("SELECT SUM(uniques) FROM visits WHERE day>=?", (db.now(-30)[:10],)),
        total=db.val("SELECT SUM(uniques) FROM visits"), subs=db.val("SELECT COUNT(*) FROM push_subscriptions WHERE enabled=1"),
        articles=db.val("SELECT COUNT(*) FROM articles WHERE hidden=0"), pending=db.val("SELECT COUNT(*) FROM ad_requests WHERE status='pending'"),
        live=db.val("SELECT COUNT(*) FROM campaigns WHERE active=1 AND paid=1 AND start_at<=? AND end_at>=?", (n, n)),
        sent=db.val("SELECT COUNT(*) FROM notifications"), errors=db.val("SELECT COUNT(*) FROM error_logs"),
        partners_pending=db.val("SELECT COUNT(*) FROM partner_sites WHERE status='pending'"), unread=db.val("SELECT COUNT(*) FROM contact_messages WHERE handled=0"), last_refresh=db.setting("news_last_refresh"))
    chart = list(reversed(db.rows("SELECT day, uniques, hits FROM visits ORDER BY day DESC LIMIT 14")))
    top = max([c["hits"] for c in chart] + [1])
    return render_template("admin/page.html", section="dashboard", stats=stats, chart=chart, top=top, push_ready=push.enabled())

# ---- actualités
@bp.route("/news")
@required
def news_():
    q, page = request.args.get("q", "")[:80], max(1, request.args.get("page", 1, type=int))
    where, p = ("WHERE LOWER(title) LIKE ?", ["%" + q.lower() + "%"]) if q else ("", [])
    items = db.rows(f"SELECT * FROM articles {where} ORDER BY published_at DESC LIMIT 31 OFFSET ?", p + [(page - 1) * 30])
    return render_template("admin/page.html", section="news", items=items[:30], more=len(items) > 30, page=page, q=q,
                           categories=db.rows("SELECT * FROM categories ORDER BY position"), push_ready=push.enabled())

@bp.post("/news/refresh")
@required
def news_refresh():
    news.refresh_async(); flash("Actualisation lancée en arrière-plan (environ 1 à 2 minutes).", "ok"); return back("news_")

@bp.post("/news/add")
@required
def news_add():
    f = request.form
    t, u = f.get("title", "").strip()[:300], f.get("url", "").strip()
    if len(t) < 5 or not URL_RE.match(u): flash("Titre et lien http(s) valides requis.", "err"); return back("news_")
    img = f.get("image", "").strip()
    n = db.insert("articles", dict(url_hash=news.hashlib.sha1(news.norm_url(u).encode()).hexdigest(), title_key=news.title_key(t), title=t, url=u,
        image=img if URL_RE.match(img) else "", domain=news.urlparse(u).netloc.removeprefix("www."), source_name=f.get("source", "").strip()[:100] or news.urlparse(u).netloc,
        category=f.get("category", "world"), language=f.get("language", "fr"), published_at=db.now(), fetched_at=db.now(),
        featured=1 if f.get("featured") else 0, manual=1), ignore=True)
    flash("Article ajouté." if n else "Article déjà présent.", "ok" if n else "err"); return back("news_")

@bp.post("/news/<int:aid>/<action>")
@required
def news_action(aid, action):
    if action in ("featured", "hidden"):
        db.run(f"UPDATE articles SET {action} = 1 - {action} WHERE id=?", (aid,))
    elif action == "delete":
        db.run("DELETE FROM articles WHERE id=?", (aid,))
    elif action == "push":
        a = db.row("SELECT * FROM articles WHERE id=?", (aid,))
        if a:
            _, ok, fail = push.broadcast(a["title"][:100], a["source_name"] or "", f"/go/{aid}", "news", "news", topic=a["category"])
            flash(f"Notification envoyée : {ok} réussie(s), {fail} échec(s).", "ok")
    return back("news_")

# ---- catégories & sources
@bp.route("/categories")
@required
def categories(): return render_template("admin/page.html", section="categories", categories=db.rows("SELECT * FROM categories ORDER BY position"))

@bp.post("/categories/save")
@required
def categories_save():
    f = request.form
    slug = re.sub(r"[^a-z0-9-]", "", f.get("slug", "").lower())[:30]
    if not slug: flash("Identifiant invalide.", "err"); return back("categories")
    data = dict(label=f.get("label", slug)[:60], q_en=f.get("q_en", "")[:300], q_fr=f.get("q_fr", "")[:300], q_es=f.get("q_es", "")[:300],
                active=1 if f.get("active") else 0, position=f.get("position", 0, type=int))
    if db.row("SELECT slug FROM categories WHERE slug=?", (slug,)):
        db.run("UPDATE categories SET " + ",".join(f"{k}=?" for k in data) + " WHERE slug=?", (*data.values(), slug))
    else:
        db.insert("categories", dict(slug=slug, **data))
    flash("Catégorie enregistrée.", "ok"); return back("categories")

@bp.route("/sources")
@required
def sources():
    return render_template("admin/page.html", section="sources", sources=db.rows(
        "SELECT s.*, (SELECT COUNT(*) FROM articles a WHERE a.domain=s.domain) AS n FROM sources s ORDER BY n DESC, domain LIMIT 300"))

@bp.post("/sources/save")
@required
def sources_save():
    f = request.form
    dom = re.sub(r"^https?://|^www\.|/.*$", "", f.get("domain", "").strip().lower())
    if not dom: flash("Domaine invalide.", "err"); return back("sources")
    db.insert("sources", dict(domain=dom, name=dom, active=1, created_at=db.now()), ignore=True)
    db.run("UPDATE sources SET name=?, active=? WHERE domain=?", (f.get("name", dom)[:100] or dom, 1 if f.get("active") else 0, dom))
    if not f.get("active"): db.run("UPDATE articles SET hidden=1 WHERE domain=? AND manual=0", (dom,))
    flash("Source enregistrée.", "ok"); return back("sources")

# ---- publicités
MAX_IMG = 400 * 1024
MAGIC = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF8", "image/gif"))

def read_image(file):
    """Retourne (base64, mime) pour un fichier envoyé, None si aucun fichier, ou lève ValueError."""
    import base64
    if not file or not file.filename: return None
    raw = file.read(MAX_IMG + 1)
    if len(raw) > MAX_IMG: raise ValueError("Image trop lourde (400 Ko maximum).")
    mime = next((m for sig, m in MAGIC if raw.startswith(sig)), None) or ("image/webp" if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP" else None)
    if not mime: raise ValueError("Format non reconnu (PNG, JPG, GIF ou WEBP).")
    return base64.b64encode(raw).decode(), mime

@bp.route("/ads")
@required
def ads():
    return render_template("admin/page.html", section="ads", requests=db.rows("SELECT * FROM ad_requests ORDER BY id DESC LIMIT 100"),
                           campaigns=db.rows("SELECT id, request_id, title, text, link, image_url, image_mime, placement, start_at, end_at, active, paid, impressions, clicks FROM campaigns ORDER BY id DESC LIMIT 100"), now=db.now())

@bp.post("/ads/banner/new")
@required
def banner_new():
    f = request.form
    link, img_url = f.get("link", "").strip(), f.get("image_url", "").strip()
    if not URL_RE.match(link): flash("Lien de destination invalide (http/https).", "err"); return back("ads")
    if img_url and not URL_RE.match(img_url): flash("Lien d'image invalide.", "err"); return back("ads")
    try: img = read_image(request.files.get("image"))
    except ValueError as e: flash(str(e), "err"); return back("ads")
    if not img and not img_url and not f.get("text", "").strip(): flash("Ajoutez une image (fichier ou lien) ou un texte.", "err"); return back("ads")
    days = min(max(f.get("days", 30, type=int) or 30, 1), 365)
    activate = bool(f.get("activate")) and live_count() < 2
    db.insert("campaigns", dict(request_id=None, title=f.get("title", "Bannière")[:80] or "Bannière", text=f.get("text", "")[:200], link=link,
        image_url=img_url, image_data=img[0] if img else None, image_mime=img[1] if img else None,
        placement="top" if f.get("placement") == "top" else "bottom", start_at=db.now(), end_at=db.now(days),
        active=1 if activate else 0, paid=1, created_at=db.now()))
    flash("Bannière créée et publiée." if activate else "Bannière créée (non activée : 2 publicités déjà en ligne, ou case non cochée).", "ok")
    return back("ads")

def live_count(exclude=0):
    n = db.now()
    return db.val("SELECT COUNT(*) FROM campaigns WHERE active=1 AND paid=1 AND start_at<=? AND end_at>=? AND id<>?", (n, n, exclude))

@bp.post("/ads/request/<int:rid>/<action>")
@required
def ad_request(rid, action):
    r = db.row("SELECT * FROM ad_requests WHERE id=?", (rid,))
    if not r: abort(404)
    note = request.form.get("note", "")[:500]
    if action == "approve": db.run("UPDATE ad_requests SET status='approved', admin_note=? WHERE id=?", (note, rid))
    elif action == "reject": db.run("UPDATE ad_requests SET status='rejected', admin_note=? WHERE id=?", (note, rid))
    elif action == "paid":
        if r["status"] not in ("approved", "paid"): flash("Approuvez d'abord la demande.", "err"); return back("ads")
        if not db.row("SELECT id FROM campaigns WHERE request_id=?", (rid,)):
            db.insert("campaigns", dict(request_id=rid, title=r["advertiser"][:80], text=r["description"][:200], link=r["link"], start_at=db.now(),
                      end_at=db.now(r["duration_days"]), active=0, paid=1, created_at=db.now()))
        db.run("UPDATE ad_requests SET status='paid', admin_note=? WHERE id=?", (note, rid))
        flash("Paiement confirmé : campagne créée (à activer).", "ok")
    return back("ads")

@bp.post("/ads/campaign/<int:cid>/<action>")
@required
def campaign(cid, action):
    if action == "toggle":
        c = db.row("SELECT * FROM campaigns WHERE id=?", (cid,))
        if c and not c["active"]:
            if not c["paid"]: flash("Paiement non confirmé : publication impossible.", "err"); return back("ads")
            if live_count(cid) >= 2: flash("Maximum 2 publicités visibles simultanément.", "err"); return back("ads")
        db.run("UPDATE campaigns SET active = 1 - active WHERE id=?", (cid,))
    elif action == "delete": db.run("DELETE FROM campaigns WHERE id=?", (cid,))
    elif action == "save":
        f = request.form
        if not URL_RE.match(f.get("link", "")): flash("Lien invalide.", "err"); return back("ads")
        img_url = f.get("image_url", "").strip()
        if img_url and not URL_RE.match(img_url): flash("Lien d'image invalide.", "err"); return back("ads")
        try: img = read_image(request.files.get("image"))
        except ValueError as e: flash(str(e), "err"); return back("ads")
        db.run("UPDATE campaigns SET title=?, text=?, link=?, end_at=?, image_url=?, placement=? WHERE id=?",
               (f.get("title", "")[:80], f.get("text", "")[:200], f["link"], f.get("end_at", "")[:19] or db.now(7), img_url,
                "top" if f.get("placement") == "top" else "bottom", cid))
        if img: db.run("UPDATE campaigns SET image_data=?, image_mime=? WHERE id=?", (img[0], img[1], cid))
        if f.get("remove_image"): db.run("UPDATE campaigns SET image_data=NULL, image_mime=NULL, image_url='' WHERE id=?", (cid,))
        flash("Campagne mise à jour.", "ok")
    return back("ads")

# ---- notifications
@bp.route("/notifications")
@required
def notifications():
    return render_template("admin/page.html", section="notifications", push_ready=push.enabled(), categories=db.rows("SELECT slug, label FROM categories ORDER BY position"), history=db.rows("SELECT * FROM notifications ORDER BY id DESC LIMIT 50"),
        subs=db.val("SELECT COUNT(*) FROM push_subscriptions WHERE enabled=1"),
        by_cat={c: len(push.audience(c)) for c in push.CATS})

@bp.post("/notifications/send")
@required
def notif_send():
    f = request.form
    title, body, url = f.get("title", "").strip()[:100], f.get("body", "").strip()[:250], f.get("url", "/").strip() or "/"
    cat = f.get("category", "all")
    topic = f.get("topic", "")
    if topic and not db.row("SELECT slug FROM categories WHERE slug=?", (topic,)): topic = ""
    if not title or not body or not (url.startswith("/") or URL_RE.match(url)) or cat not in ("all", *push.CATS):
        flash("Titre, message et lien valides requis.", "err"); return back("notifications")
    if not push.enabled(): flash("Web Push non configuré (clés VAPID / pywebpush).", "err"); return back("notifications")
    _, ok, fail = push.broadcast(title, body, url, cat, "ad" if cat == "ads" else "manual", topic=topic or None)
    flash(f"Envoyé : {ok} réussie(s), {fail} échec(s).", "ok"); return back("notifications")

# ---- messages, erreurs, paramètres
@bp.route("/messages")
@required
def messages(): return render_template("admin/page.html", section="messages", messages=db.rows("SELECT * FROM contact_messages ORDER BY id DESC LIMIT 100"))

@bp.post("/messages/<int:mid>/handled")
@required
def message_handled(mid):
    db.run("UPDATE contact_messages SET handled = 1 - handled WHERE id=?", (mid,)); return back("messages")

@bp.route("/errors")
@required
def errors(): return render_template("admin/page.html", section="errors", errors=db.rows("SELECT * FROM error_logs ORDER BY id DESC LIMIT 100"))

@bp.post("/errors/clear")
@required
def errors_clear(): db.run("DELETE FROM error_logs"); return back("errors")

SETTING_KEYS = ["site_name", "download_url", "payment_link", "payment_instructions", "news_langs", "news_retention_days", "contact_email", "ads_enabled"]

@bp.route("/settings", methods=["GET", "POST"])
@required
def settings():
    if request.method == "POST":
        for k in SETTING_KEYS:
            v = request.form.get(k, "").strip()[:500]
            if k in ("download_url", "payment_link") and v and not URL_RE.match(v): flash(f"{k} : lien invalide.", "err"); continue
            if k == "news_langs": v = ",".join(x for x in v.replace(" ", "").split(",") if x in news.LANG_MAP) or "fr,en"
            if k == "news_retention_days": v = str(min(max(int(v or 14), 1), 90)) if v.isdigit() else "14"
            if k == "ads_enabled": v = "1" if request.form.get(k) else "0"
            db.set_setting(k, v)
        flash("Paramètres enregistrés.", "ok"); return back("settings")
    return render_template("admin/page.html", section="settings", s={k: db.setting(k) for k in SETTING_KEYS})

# ---- flux RSS (deuxième distributeur d'actualités)
@bp.route("/feeds")
@required
def feeds():
    return render_template("admin/page.html", section="feeds", feeds=db.rows("SELECT * FROM feeds ORDER BY id"),
                           categories=db.rows("SELECT slug, label FROM categories ORDER BY position"))

def _feed_fields(f):
    return dict(name=f.get("name", "").strip()[:100], category=f.get("category", "world")[:30],
                language=f.get("language") if f.get("language") in ("fr", "en", "es") else "fr", country=f.get("country", "").strip()[:60])

@bp.post("/feeds/add")
@required
def feed_add():
    f, url = request.form, request.form.get("url", "").strip()
    d = _feed_fields(f)
    if len(d["name"]) < 2 or not URL_RE.match(url): flash("Nom et URL de flux (http/https) requis.", "err"); return back("feeds")
    n = db.insert("feeds", dict(url=url, site_url="", active=1, created_at=db.now(), **d), ignore=True)
    flash("Flux ajouté." if n else "Ce flux existe déjà.", "ok" if n else "err"); return back("feeds")

@bp.post("/feeds/fetch")
@required
def feed_fetch():
    import threading
    threading.Thread(target=news.refresh_feeds, daemon=True).start()
    flash("Lecture des flux lancée : rechargez dans quelques secondes.", "ok"); return back("feeds")

@bp.post("/feeds/<int:fid>/<action>")
@required
def feed_action(fid, action):
    if action == "toggle": db.run("UPDATE feeds SET active = 1 - active WHERE id=?", (fid,))
    elif action == "delete": db.run("DELETE FROM feeds WHERE id=?", (fid,))
    elif action == "save":
        d = _feed_fields(request.form)
        db.run("UPDATE feeds SET name=?, category=?, language=?, country=? WHERE id=?", (d["name"], d["category"], d["language"], d["country"], fid))
        flash("Flux enregistré.", "ok")
    return back("feeds")

# ---- sites partenaires
@bp.route("/partners")
@required
def partners():
    return render_template("admin/page.html", section="partners", partners=db.rows("SELECT * FROM partner_sites ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, id DESC LIMIT 200"))

@bp.post("/partners/<int:pid>/<action>")
@required
def partner_action(pid, action):
    p = db.row("SELECT * FROM partner_sites WHERE id=?", (pid,))
    if not p: abort(404)
    note = request.form.get("note", "")[:500]
    if action == "approve":
        db.run("UPDATE partner_sites SET status='approved', admin_note=? WHERE id=?", (note, pid))
        if p["feed_url"]:   # le flux RSS du site alimente aussi les actualités
            db.insert("feeds", dict(name=p["name"][:100], url=p["feed_url"], site_url=p["url"], category="world", language=p["feed_lang"] or "fr",
                                    country="", active=1, partner_id=pid, created_at=db.now()), ignore=True)
        flash("Site approuvé et affiché." + (" Flux RSS ajouté (réglez sa catégorie dans « Flux RSS »)." if p["feed_url"] else ""), "ok")
    elif action == "reject":
        db.run("UPDATE partner_sites SET status='rejected', admin_note=? WHERE id=?", (note, pid))
        db.run("UPDATE feeds SET active=0 WHERE partner_id=?", (pid,))
    elif action == "feature": db.run("UPDATE partner_sites SET featured = 1 - featured WHERE id=?", (pid,))
    elif action == "delete":
        db.run("DELETE FROM partner_sites WHERE id=?", (pid,)); db.run("DELETE FROM feeds WHERE partner_id=?", (pid,))
    return back("partners")
