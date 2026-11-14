"""National Weather Service (api.weather.gov): 7-day forecast and active alerts. Free, no key, US only.

forecast()        12-hour periods for the next 7 days
official_alerts() active NWS watches / warnings / advisories for the point
farm_alerts()     alerts this app derives from the forecast: frost, heat, heavy rain, wind
"""

import re

from .net import FetchError, get_json

NWS = "https://api.weather.gov"
SEVERITY_RANK = {"danger": 0, "warn": 1, "info": 2}


def forecast(lat, lon):
    """Returns (periods, forecast_page_url), or (None, None) outside NWS coverage."""
    try:
        point = get_json(f"{NWS}/points/{lat:.4f},{lon:.4f}")
    except FetchError as e:
        if "404" in str(e):
            return None, None  # not in the US
        raise
    props = point["properties"]
    data = get_json(props["forecast"])
    periods = []
    for p in data["properties"]["periods"]:
        speeds = [int(n) for n in re.findall(r"\d+", p.get("windSpeed") or "")]
        periods.append({
            "name": p["name"],
            "start": p["startTime"],
            "is_day": p["isDaytime"],
            "temp_f": p["temperature"] if p.get("temperatureUnit") == "F" else round(p["temperature"] * 9 / 5 + 32),
            "rain_pct": (p.get("probabilityOfPrecipitation") or {}).get("value") or 0,
            "wind": p.get("windSpeed") or "",
            "wind_max_mph": max(speeds) if speeds else 0,
            "short": p.get("shortForecast") or "",
            "detail": p.get("detailedForecast") or "",
            "icon": p.get("icon") or "",
        })
    page = f"https://forecast.weather.gov/MapClick.php?lat={lat:.4f}&lon={lon:.4f}"
    return periods, page


def official_alerts(lat, lon):
    data = get_json(f"{NWS}/alerts/active", {"point": f"{lat:.4f},{lon:.4f}"})
    out = []
    for f in data.get("features") or []:
        p = f["properties"]
        sev = (p.get("severity") or "").lower()
        out.append({
            "id": p.get("id") or f.get("id"),
            "source": "National Weather Service",
            "level": "danger" if sev in ("extreme", "severe") else "warn",
            "title": p.get("event") or "Weather alert",
            "text": p.get("headline") or "",
            "detail": "\n\n".join(x for x in (p.get("description"), p.get("instruction")) if x),
            "until": p.get("ends") or p.get("expires"),
        })
    return out


def _day(period):
    return period["start"][:10]


def farm_alerts(periods):
    """What the next 3 days of forecast mean for a farm. One alert per kind, the most serious."""
    if not periods:
        return []
    soon = periods[:6]  # ~3 days of 12-hour periods
    alerts = []

    nights = [p for p in soon if not p["is_day"]]
    if nights:
        cold = min(nights, key=lambda p: p["temp_f"])
        t, when = cold["temp_f"], cold["name"].lower()
        if t <= 36:
            if t <= 28:
                level, title = "danger", f"Hard freeze {when}: {t}°F"
                text = ("Cold enough to kill most unprotected crops. Harvest what's ready, cover or bring in tender plants, "
                        "drain irrigation lines and hoses, and make sure livestock water won't freeze.")
            elif t <= 32:
                level, title = "warn", f"Freeze {when}: {t}°F"
                text = ("Tender plants (tomatoes, peppers, beans, squash, melons) will be damaged. Cover them with "
                        "frost cloth or sheets before sunset, or harvest now. Cool-season crops will be fine.")
            else:
                level, title = "info", f"Frost possible {when}: {t}°F"
                text = "Frost can form on clear, calm nights even above freezing. Cover tender seedlings tonight."
            alerts.append({"id": f"frost-{_day(cold)}-{t}", "source": "Based on NWS forecast",
                           "level": level, "title": title, "text": text, "until": cold["start"]})

    days = [p for p in soon if p["is_day"]]
    if days:
        hot = max(days, key=lambda p: p["temp_f"])
        t = hot["temp_f"]
        if t >= 95:
            alerts.append({
                "id": f"heat-{_day(hot)}-{t}", "source": "Based on NWS forecast",
                "level": "danger" if t >= 100 else "warn",
                "title": f"{'Extreme heat' if t >= 100 else 'Heat'} {hot['name'].lower()}: {t}°F",
                "text": ("Water early in the morning so plants go into the heat hydrated, shade young transplants, "
                         "give livestock extra water and shade, and do heavy field work before 10 AM."),
                "until": hot["start"]})

    wet = max(soon, key=lambda p: p["rain_pct"])
    if wet["rain_pct"] >= 70:
        heavy = re.search(r"heavy|thunderstorm|storm", wet["short"] + " " + wet["detail"], re.I)
        alerts.append({
            "id": f"rain-{_day(wet)}-{wet['rain_pct']}", "source": "Based on NWS forecast",
            "level": "warn" if heavy else "info",
            "title": f"{'Storms' if heavy else 'Rain'} likely {wet['name'].lower()} ({wet['rain_pct']}%)",
            "text": ("Hold off on spraying or spreading fertilizer, since rain will wash it off or into ditches. "
                     "Skip irrigation and check that field drainage is clear."),
            "until": wet["start"]})

    windy = max(soon, key=lambda p: p["wind_max_mph"])
    if windy["wind_max_mph"] >= 20:
        alerts.append({
            "id": f"wind-{_day(windy)}-{windy['wind_max_mph']}", "source": "Based on NWS forecast",
            "level": "warn" if windy["wind_max_mph"] >= 30 else "info",
            "title": f"Windy {windy['name'].lower()}: up to {windy['wind_max_mph']} mph",
            "text": ("Too windy to spray: pesticide and herbicide drift onto neighbors' fields. Secure row covers "
                     "and stake tall plants. Dry, windy days also raise grass-fire risk."),
            "until": windy["start"]})

    return alerts


def weather(lat, lon):
    """Forecast plus every alert, most serious first. Returns None outside the US."""
    periods, page = forecast(lat, lon)
    if periods is None:
        return None
    try:
        official = official_alerts(lat, lon)
    except FetchError:
        official = []
    alerts = official + farm_alerts(periods)
    alerts.sort(key=lambda a: SEVERITY_RANK.get(a["level"], 3))
    return {"periods": periods, "alerts": alerts, "page": page}
