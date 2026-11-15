"""One address in, one report out: SerpAPI + NASA POWER + USDA soil -> recommendations."""

from concurrent.futures import ThreadPoolExecutor

from . import nasa, place, recommend, serp, soil, weather
from .net import FetchError


def _run(pool, fn, *args):
    return pool.submit(fn, *args)


def _result(future, name, warnings, default=None):
    try:
        return future.result()
    except (FetchError, serp.SerpError, KeyError, ValueError, TypeError) as e:
        warnings.append(f"{name}: {e}")
        return default


def analyze(address):
    warnings = []
    location = serp.geocode(address)  # SerpAPI Google Maps
    if not location:
        return {"error": f"Couldn't find \"{address}\" on Google Maps. Try adding a city and state."}
    lat, lon = location["lat"], location["lon"]
    try:
        area = place.county_state(lat, lon) or {}
    except FetchError:
        return {"error": "We couldn't verify this location. Try a U.S. town, county, or farm address."}

    with ThreadPoolExecutor(max_workers=6) as pool:
        f_climate = _run(pool, nasa.climate, lat, lon)
        f_recent = _run(pool, nasa.recent, lat, lon)
        f_soil = _run(pool, soil.soil_at, lat, lon)
        f_local = _run(pool, serp.local_resources, lat, lon)
        f_weather = _run(pool, weather.weather, lat, lon)

        climate = _result(f_climate, "NASA climate", warnings)
        recent = _result(f_recent, "NASA recent weather", warnings)
        soil_info = _result(f_soil, "Soil", warnings)
        local = _result(f_local, "Nearby places (SerpAPI)", warnings, [])
        forecast = _result(f_weather, "Weather forecast (NWS)", warnings)

        if not climate:
            return {"error": "NASA POWER climate data is unavailable right now. Try again in a minute.", "warnings": warnings}

        plan = recommend.crop_plan(climate, soil_info)
        top_crops = [p["crop"] for p in plan if p["status"] in ("now", "soon")] or [p["crop"] for p in plan[:3]]
        state = area.get("state") or serp.state_from_address(location["address"]) or ""
        f_guides = _run(pool, serp.planting_guides, state, top_crops)
        f_news = _run(pool, serp.farm_news, area.get("county"), state)
        guides = _result(f_guides, "Extension guides (SerpAPI)", warnings, [])
        news = _result(f_news, "Farm news (SerpAPI)", warnings, [])

    return {
        "location": {**location, **area},
        "climate": climate,
        "recent": recent,
        "weather": forecast,
        "soil": soil_info,
        "crops": plan,
        "advice": {
            "conditions": recommend.conditions_advice(climate, recent),
            "soil": recommend.soil_advice(soil_info),
        },
        "web": {"local": local, "guides": guides, "news": news},
        "warnings": warnings,
    }
