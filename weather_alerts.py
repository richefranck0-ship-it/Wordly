"""Alertes météo dérivées des prévisions Open-Meteo (Open-Meteo ne fournit pas d'alertes officielles).
Chaque abonné ayant activé l'option reçoit au plus une alerte par jour."""
import requests, db, push

API = "https://api.open-meteo.com/v1/forecast"

def detect(daily):
    out = []
    code, rain = daily["weather_code"][0], daily.get("precipitation_probability_max", [0])[0] or 0
    gust, tmax, tmin = daily.get("wind_gusts_10m_max", [0])[0] or 0, daily["temperature_2m_max"][0], daily["temperature_2m_min"][0]
    if code >= 95: out.append("al_storm")
    if (daily.get("precipitation_sum", [0])[0] or 0) >= 20 and rain >= 70: out.append("al_rain")
    if gust >= 70: out.append("al_wind")
    if tmax >= 35: out.append("al_heat")
    if tmin <= -10: out.append("al_cold")
    if code in (71, 73, 75, 77, 85, 86): out.append("al_snow")
    return out

def run():
    subs = [s for s in push.audience("weather") if s["weather_on"] and s["weather_lat"] is not None]
    today, sent, groups = db.now()[:10], 0, {}
    for s in subs:
        if s["alert_day"] == today: continue
        groups.setdefault((round(s["weather_lat"], 1), round(s["weather_lon"], 1)), []).append(s)
    from i18n import get
    for (lat, lon), members in groups.items():
        try:
            d = requests.get(API, params={"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 1,
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_gusts_10m_max"},
                timeout=15).json()["daily"]
        except Exception:
            continue
        keys = detect(d)
        if not keys: continue
        for s in members:
            t = get(s["lang"] or "fr")
            ok, _ = push.send([s], f"⚠ {s['weather_city'] or t['weather']}", " · ".join(t[k] for k in keys), "/weather", "weather")
            if ok:
                db.run("UPDATE push_subscriptions SET alert_day=? WHERE id=?", (today, s["id"])); sent += 1
    return sent
