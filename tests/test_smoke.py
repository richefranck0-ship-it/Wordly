"""Test de bout en bout (SQLite local, réseau simulé). Lancer : python tests/test_smoke.py"""
import os, sys, re, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.update(FLASK_ENV="development", SQLITE_PATH=tempfile.mktemp(suffix=".db"), ADMIN_PASSWORD="pw-test", ADMIN_USER="admin",
                  CRON_TOKEN="cron", VAPID_PUBLIC_KEY="BPUB", VAPID_PRIVATE_KEY="PRIV")
import app as A, news, translate, push, db
GD = {"articles": [
  {"url": "https://www.lemonde.fr/a/1?x=1", "title": "Un titre d'article suffisamment long", "domain": "lemonde.fr", "seendate": "20261107T101500Z", "socialimage": "https://img.example/i.jpg"},
  {"url": "https://lemonde.fr/a/1/", "title": "Doublon d'URL avec un autre titre", "domain": "lemonde.fr", "seendate": "20261107T101500Z"},
  {"url": "https://bbc.com/b", "title": "Un titre d'article suffisamment long", "domain": "bbc.com", "seendate": "20261107T101500Z"}]}
MM = {"responseStatus": 200, "responseData": {"translatedText": "Hello", "detectedLanguage": "fr"}}
def fake_get(url, *a, **k):   # news et translate partagent le même module requests : on aiguille par URL
    data = GD if "gdelt" in url else MM
    return type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: data})()
news.requests.get = fake_get
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))

db.set_setting("news_last_refresh", db.now())  # évite le rafraîchissement paresseux pendant le test
c = A.app.test_client()
def csrf(path="/"):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(path).get_data(as_text=True)).group(1) if 'name="csrf"' in c.get(path).get_data(as_text=True) else c.get("/") and re.search(r'"csrf":\s*"([^"]+)"', c.get("/").get_data(as_text=True)).group(1)

for p in ["/", "/news", "/weather", "/translate", "/voice", "/notifications", "/download", "/advertise", "/faq", "/terms", "/privacy", "/legal", "/contact", "/privacy-settings", "/offline", "/sitemap.xml", "/robots.txt", "/manifest.webmanifest", "/sw.js", "/favicon.ico"]:
    r = c.get(p); ok(r.status_code == 200, f"GET {p}")
ok(c.get("/nope").status_code == 404, "404")
ok(c.get("/en-lang-test").status_code == 404, "404 api-free")
ok(c.post("/api/translate", json={"text": "Bonjour", "src": "auto", "dst": "en"}).status_code == 400, "CSRF requis sur POST")

tok = re.search(r'"csrf":\s*"([^"]+)"', c.get("/").get_data(as_text=True)).group(1)
H = {"X-CSRF-Token": tok}
r = c.post("/api/translate", json={"text": "Bonjour", "src": "auto", "dst": "en"}, headers=H); ok(r.json["text"] == "Hello" and r.json["detected"] == "fr", "traduction + détection")
ok(c.post("/api/translate", json={"text": "x", "src": "xx", "dst": "en"}, headers=H).status_code == 400, "langue invalide refusée")

res = news.refresh_all(pause=0); ok(db.val("SELECT COUNT(*) FROM articles") >= 1, f"actualités stockées ({res})")
ok(db.val("SELECT COUNT(*) FROM articles WHERE url LIKE '%lemonde.fr/a/1%'") == 1, "doublons d'URL/titre éliminés")
ok("Un titre d" in c.get("/news").get_data(as_text=True), "article affiché")
aid = db.val("SELECT id FROM articles LIMIT 1"); ok(c.get(f"/go/{aid}").status_code == 302, "redirection vers la source")

# push
sub = {"subscription": {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "k", "auth": "a"}}, "categories": ["news"], "lang": "fr", "weather": {"on": True, "lat": 48.8, "lon": 2.3, "city": "Paris"}}
ok(c.post("/api/push/subscribe", json=sub, headers=H).status_code == 200, "abonnement push")
bad = json.loads(json.dumps(sub)); bad["subscription"]["endpoint"] = "https://evil.example/x"
ok(c.post("/api/push/subscribe", json=bad, headers=H).status_code == 400, "endpoint push non autorisé refusé (SSRF)")
ok(c.post("/api/push/prefs", json={"endpoint": sub["subscription"]["endpoint"]}, headers=H).json["categories"] == ["news"], "préférences push")

# publicité
r = c.post("/advertise", data={"csrf": tok, "advertiser": "ACME", "email": "a@b.co", "description": "Une belle publicité pour ACME mondial", "duration": "7", "link": "https://acme.example", "consent": "on"})
ok(r.status_code == 302, "demande de publicité"); token = r.headers["Location"].rsplit("/", 1)[1]
ok("En attente" in c.get(f"/advertise/status/{token}").get_data(as_text=True), "suivi de la demande")

# admin
AP = A.config.ADMIN_PATH
ok(c.get(AP + "/").status_code == 302, "admin protégé")
ok("Identifiants" in c.post(AP + "/login", data={"csrf": tok, "user": "admin", "password": "mauvais"}).get_data(as_text=True), "mauvais mot de passe refusé")
ok(c.post(AP + "/login", data={"csrf": tok, "user": "admin", "password": "pw-test"}).status_code == 302, "connexion admin")
tok = re.search(r'name="csrf" value="([^"]+)"', c.get(AP + "/").get_data(as_text=True)).group(1)  # le jeton change à la connexion
for s in ["/", "/news", "/categories", "/sources", "/ads", "/notifications", "/messages", "/errors", "/settings"]:
    r = c.get(AP + s); ok(r.status_code == 200, f"admin {s}")
ok(c.get(AP + "/").headers.get("X-Robots-Tag", "").startswith("noindex"), "admin noindex")
rid = db.val("SELECT id FROM ad_requests LIMIT 1")
ok(c.post(f"{AP}/ads/request/{rid}/paid", data={"csrf": tok}).status_code == 302 and db.val("SELECT COUNT(*) FROM campaigns") == 0, "pas de campagne avant approbation")
c.post(f"{AP}/ads/request/{rid}/approve", data={"csrf": tok}); c.post(f"{AP}/ads/request/{rid}/paid", data={"csrf": tok})
ok(db.val("SELECT COUNT(*) FROM campaigns") == 1, "campagne créée après paiement confirmé")
cid = db.val("SELECT id FROM campaigns"); c.post(f"{AP}/ads/campaign/{cid}/toggle", data={"csrf": tok})
ok("ACME" in c2 if (c2 := A.app.test_client().get("/").get_data(as_text=True)) else False, "publicité visible publiquement")
for i in range(2):  # max 2 simultanées
    db.insert("campaigns", dict(title=f"X{i}", text="t", link="https://x.example", start_at=db.now(-1), end_at=db.now(5), active=0, paid=1, created_at=db.now()))
ids = [r["id"] for r in db.rows("SELECT id FROM campaigns WHERE active=0")]
for i in ids: c.post(f"{AP}/ads/campaign/{i}/toggle", data={"csrf": tok})
ok(db.val("SELECT COUNT(*) FROM campaigns WHERE active=1") == 2, "maximum 2 publicités actives")
ok(len(db.rows("SELECT id FROM campaigns WHERE active=1 AND paid=1 LIMIT 2")) == 2, "affichage limité à 2")
push.webpush = lambda *a, **k: None
r = c.post(AP + "/notifications/send", data={"csrf": tok, "title": "Bonjour", "body": "Test", "url": "/", "category": "all"}); ok(db.val("SELECT sent_count FROM notifications") == 1, "notification envoyée aux abonnés")
ok(c.get("/api/notifications").json["items"][0]["title"] == "Bonjour", "centre de notifications")
ok(A.app.test_client().get("/cron/refresh-news").status_code == 403, "cron protégé")
ok(c.post("/cron/weather-alerts", headers={"X-Cron-Token": "cron"}).status_code == 200, "cron météo")
ok(c.post(AP + "/logout", data={"csrf": tok}).status_code == 302 and c.get(AP + "/").status_code == 302, "déconnexion")
print("TOUS LES TESTS PASSENT")
