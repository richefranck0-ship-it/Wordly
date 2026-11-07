import time
from collections import defaultdict
from flask import request
_hits = defaultdict(list)

def limited_ip(bucket, limit, window):
    ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0]).strip()
    k, t = (bucket, ip), time.time()
    _hits[k] = [x for x in _hits[k] if t - x < window]
    if len(_hits[k]) >= limit: return True
    _hits[k].append(t); return False
