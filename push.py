import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import config, db

try:
    from pywebpush import webpush, WebPushException
except Exception:  # pywebpush non installé : l'envoi sera désactivé proprement
    webpush = None
    class WebPushException(Exception): pass

CATS = ("news", "weather", "worldly", "ads")

def enabled():
    return bool(webpush and config.VAPID_PUBLIC_KEY and config.VAPID_PRIVATE_KEY)

def valid_endpoint(ep):
    try:
        u = urlparse(ep)
        return u.scheme == "https" and len(ep) < 1000 and u.hostname and u.hostname.endswith(config.PUSH_HOST_SUFFIXES)
    except Exception:
        return False

def _one(sub, payload):
    info = {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}
    try:
        webpush(info, data=payload, vapid_private_key=config.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": config.VAPID_SUBJECT}, ttl=86400)
        db.run("UPDATE push_subscriptions SET last_ok=?, fail_count=0 WHERE id=?", (db.now(), sub["id"]))
        return True
    except WebPushException as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code in (404, 410):  # abonnement expiré : suppression
            db.run("DELETE FROM push_subscriptions WHERE id=?", (sub["id"],))
        else:
            db.run("UPDATE push_subscriptions SET fail_count=fail_count+1 WHERE id=?", (sub["id"],))
            db.run("DELETE FROM push_subscriptions WHERE id=? AND fail_count>=5", (sub["id"],))
        return False
    except Exception:
        return False

def send(subs, title, body, url="/", tag="worldly"):
    if not enabled():
        return 0, len(subs)
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda s: _one(s, payload), subs))
    return sum(res), len(res) - sum(res)

def audience(category="all", topic=None):
    subs = db.rows("SELECT * FROM push_subscriptions WHERE enabled=1")
    if category in CATS:
        subs = [s for s in subs if category in (s["categories"] or "").split(",")]
    if topic:  # sujet d'actualité (ex. football) : abonnés sans sujet choisi = tous les sujets
        subs = [s for s in subs if not (s.get("topics") or "").strip() or topic in s["topics"].split(",")]
    return subs

def broadcast(title, body, url="/", category="all", kind="manual", topic=None):
    subs = audience(category, topic)
    ok, fail = send(subs, title, body, url)
    nid = db.insert("notifications", dict(title=title[:120], body=body[:300], url=url[:500], category=category,
                                          kind=kind, sent_count=ok, failed_count=fail, created_at=db.now()))
    return nid, ok, fail
