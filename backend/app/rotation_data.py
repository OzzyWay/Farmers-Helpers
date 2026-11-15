"""Gather everything the rotation explorer needs for one field, then run the engine (Req 13).

Steps:
1. At the same time: the farm-data sources (NASA POWER normals, SSURGO, CDL), the full soil
   profile, and the NASA POWER daily climate trends since 1981. The 2030-2049 outlook is only
   read if it is already available (precomputed for a demo farm, or cached); it is never
   fetched here, because one new outlook uses most of an hour's free Open-Meteo quota.
2. Turn those results into SiteFacts for today and for the outlook.
3. Work out the current rotation from the crop map history (or the farmer's choice).
4. Run the rules engine.

Like gather_farm_data, this never raises for an upstream problem: a failing source is
reported with a plain reason, its facts stay unknown, and the confidence goes down.
"""
import asyncio
import logging
from datetime import date

from app.cache import DiskCache
from app.farm_data import SERVICE_TIMEOUT, gather_farm_data
from app import ndvi_store
from app.outlook_store import OutlookStore
from app.rotation import engine
from app.rotation.current import infer
from app.rotation.site_facts import FarmInputs, build_outlook_facts, build_today
from app.services import climate_trends, nasa_water, openmeteo, soil_profile
from app.services.base import describe_failure

log = logging.getLogger("farm_data")


async def _guarded(name: str, key: str, coro) -> dict:
    """Run one source with the safety timeout. On failure return an "unavailable" entry."""
    try:
        return await asyncio.wait_for(coro, SERVICE_TIMEOUT)
    except Exception as e:  # noqa: BLE001 - a failing source must never break the page
        # Log only the source and the kind of error: no URLs, bodies or secrets.
        log.warning("farm_data source=%s error=%s", key, type(e).__name__)
        return {"status": "unavailable", "source": name, "reason": describe_failure(name, e)}


def surface_cover(farm_sources: dict) -> dict | None:
    """The latest crop map label for the top of the soil block, e.g. Grass/Pasture in 2025."""
    group = farm_sources.get("cdl") or {}
    if group.get("status") != "ok":
        return None
    rows = [r for r in group.get("records", []) if r.get("variable") == "crop_type"]
    if not rows:
        return None
    latest = max(rows, key=lambda r: str(r.get("date", "")))
    return {"value": latest["value"], "year": latest["date"], "source": latest["source"],
            "resolution_m": latest.get("resolution_m")}


MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")


def apply_ndvi(result: dict, ndvi_doc: dict) -> None:
    """Use what the satellite saw (Req 21.3, 4.5).

    The current rotation gets the months MODIS saw as bare, so its calendar can show them next
    to the crop-calendar estimate. When MODIS saw bare months, a satellite-based bare-soil
    finding replaces the crop-calendar one (it is a measurement, not an estimate).
    """
    if ndvi_doc.get("status") != "ok":
        return
    bare = ndvi_doc.get("bare_months") or []
    for s in result.get("strategies", []):
        if s.get("is_current"):
            s["satellite_bare_months"] = bare
            s["satellite_period"] = ndvi_doc.get("period")
    if not bare:
        return
    names = ", ".join(MONTHS[m - 1] for m in bare)
    finding = {
        "id": "bare_soil_satellite", "title": "Bare soil seen from space",
        "text": (f"NASA's MODIS satellite saw little green cover here in {names} in at least half of the years "
                 f"{ndvi_doc.get('period')}. Bare soil loses topsoil and water; a cover crop in those months would help."),
        "evidence": [{"value": f"NDVI below {ndvi_doc.get('bare_threshold')}", "units": "", "source": ndvi_doc.get("source"),
                      "resolution_m": ndvi_doc.get("resolution_m"), "period": ndvi_doc.get("period")}],
        "terms": ["ndvi", "cover_crop"],
    }
    found = [f for f in result.get("findings", []) if f.get("id") != "bare_soil"]
    result["findings"] = found + [finding]


def apply_water(result: dict, water: dict, trends_ok: dict | None) -> None:
    """Use the NASA satellite water data (Req 23.6, 23.7, 23.9).

    Adds IMERG's average rain for each calendar month over the same years as NASA POWER's
    monthly rain, so the page can show the two side by side, and the low-groundwater finding.
    """
    if water.get("status") != "ok":
        return
    rain = water.get("rain") or {}
    period = (trends_ok or {}).get("monthly", {}).get("period")  # e.g. "2016-2025"
    if rain.get("status") == "ok" and period:
        first, last = (int(x) for x in period.split("-"))
        rain["calendar_vs_power"] = {
            "period": period,
            "imerg_mm": nasa_water.calendar_average(rain.get("monthly", []), first, last),
            "power_mm": (trends_ok.get("monthly") or {}).get("rain_mm"),
        }
    finding = nasa_water.groundwater_finding(water)
    if finding:
        result["findings"] = list(result.get("findings", [])) + [finding]


async def gather_rotation(client, lat: float, lon: float, cache: DiskCache, store: OutlookStore,
                          crops: dict, inputs: FarmInputs, today: date | None = None,
                          ndvi_lookup=ndvi_store.get, water_fetch=nasa_water.fetch) -> dict:
    """Return the full /api/rotation response for one location.

    Raises ValueError only when inputs.current_override is not a crop id (checked by the
    route before this is called, so in practice it does not happen).
    """
    farm, profile, trends, water = await asyncio.gather(
        gather_farm_data(client, lat, lon, cache),  # never raises
        _guarded("USDA SSURGO soil profile", "soil_profile", soil_profile.fetch(client, lat, lon, cache)),
        _guarded("NASA POWER daily climate", "climate_trends", climate_trends.fetch(client, lat, lon, cache, today)),
        _guarded("NASA satellite water data", "nasa_water", water_fetch(client, lat, lon, cache, today=today)),
    )
    sources = farm["sources"]
    trends_ok = trends if trends.get("status") == "ok" else None

    # The outlook: only what is already on disk. Add the projected values to today's baseline.
    outlook_doc = None
    try:
        raw = store.get(lat, lon, today)
        if raw is not None:
            outlook_doc = openmeteo.apply_to_baseline(raw, trends_ok)
    except Exception as e:  # noqa: BLE001 - a broken outlook file must not break the page
        log.warning("farm_data source=open_meteo error=%s", type(e).__name__)
        outlook_doc = None
    outlook = outlook_doc if outlook_doc is not None else store.status(lat, lon, today)

    today_facts = build_today(sources, profile, trends_ok)
    outlook_facts = build_outlook_facts(today_facts, outlook_doc, trends_ok)
    cdl_records = (sources.get("cdl") or {}).get("records", []) if (sources.get("cdl") or {}).get("status") == "ok" else []
    current = infer(cdl_records, crops, inputs.current_override)

    try:
        result = engine.run(today_facts, outlook_facts, crops, current, inputs, trends_ok, outlook_doc)
    except Exception as e:  # noqa: BLE001 - say so plainly instead of a server error
        log.warning("farm_data source=rotation_engine error=%s", type(e).__name__)
        result = {"current_rotation": current, "strategies": [], "exclusions": [], "not_suggested": [],
                  "findings": [], "ranking_note": "",
                  "engine_error": "The rotation options could not be worked out from this location's data."}

    try:
        ndvi_doc = ndvi_lookup(lat, lon)
    except Exception as e:  # noqa: BLE001 - a broken file must not break the page
        log.warning("farm_data source=ndvi error=%s", type(e).__name__)
        ndvi_doc = {"status": "unavailable", "reason": "the satellite greenness file could not be read"}
    apply_ndvi(result, ndvi_doc)
    try:
        apply_water(result, water, trends_ok)
    except Exception as e:  # noqa: BLE001 - odd water data must not break the page
        log.warning("farm_data source=nasa_water_apply error=%s", type(e).__name__)

    return {
        "location": {"lat": lat, "lon": lon},
        "missing_sources": list(today_facts.missing_sources),
        "ndvi": ndvi_doc,
        # NASA satellite water data: IMERG rain, GRACE groundwater and soil moisture (Req 23).
        "water": water,
        "inputs": {"priorities": sorted(inputs.priorities), "irrigation": inputs.irrigation,
                   "livestock": inputs.livestock, "no_till": inputs.no_till,
                   "current": inputs.current_override},
        "soil_profile": profile,
        # Surface soil facts (SSURGO) with their sources, for the soil block's runoff and
        # drainage indicators and the facts next to it.
        "soil_facts": {name: fact.cite() for name in ("hydro_group", "drainage", "flooding", "ponding",
                                                       "om_pct", "awc", "k_factor", "slope_high")
                       if (fact := getattr(today_facts, name)) is not None},
        "surface_cover": surface_cover(sources),
        "trends": trends,
        "outlook": outlook,
        # Names, groups and sources for every crop in the table, so the page can label the
        # cards and link each crop to where its values came from.
        "crops": {cid: {"name": c["name"], "category": c["category"], "season": c["season"],
                        "sources": c["sources"]} for cid, c in crops.items()},
        **result,
    }
