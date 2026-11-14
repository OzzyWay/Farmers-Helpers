"""County and state for a point (FCC Area API, US only, free, no key)."""

from .net import get_json


def county_state(lat, lon):
    data = get_json("https://geo.fcc.gov/api/census/area", {"lat": lat, "lon": lon, "format": "json"})
    results = data.get("results") or []
    if not results:
        return None
    r = results[0]
    return {"county": r.get("county_name"), "state": r.get("state_name"), "state_code": r.get("state_code")}
