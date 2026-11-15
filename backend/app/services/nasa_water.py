"""NASA satellite water data for one field (spec rotation-explorer, Requirement 23).

From the NASA GES DISC Giovanni Time Series service (one CSV per variable and point):

  rain         GPM IMERG Final, monthly, 0.1° (about 10 km). Built from satellite microwave and
               infrared observations, adjusted with rain gauges. Unit from the service: mm/hr
               (the month's average rate), turned here into mm per month.
  groundwater  GRACE / GRACE-FO data assimilation drought indicators for the US (GRACE-DA),
  root_zone    weekly, 0.125° (about 12 km). Values are percentiles against 1948-2012: 10 means
  surface      wetter than only 10 % of the same weeks then, 90 means wetter than 90 %. The GRACE
               satellites sense water across a region hundreds of km wide; a land model blends
               that into the 0.125° grid.
  smap         not used yet (planned for later; AppEEARS answers minutes later, too slow here).

Login: an Earthdata Login bearer token from the EARTHDATA_TOKEN environment variable, with the
"NASA GESDISC DATA ARCHIVE" app approved on that account. The token goes only into the request
header: never into responses, logs or the cache (Req 23.4). Without it, or when NASA rejects it,
the water data is reported unavailable with a plain reason and everything else still works.

The four requests run in parallel (about 2.5 s for the full records on 2026-11-15). The summary
(not the raw CSV) is cached per location under a key with the current month, so it refreshes
at most once a month (Req 23.11). Only a complete, successful result is cached.
"""
import asyncio
import calendar
import os
import statistics
from datetime import date, datetime, timedelta

from app.cache import DiskCache
from app.rotation.trends import trend
from app.services.base import UPSTREAM_TIMEOUT, SourceUnavailable, describe_failure

API = "https://api.giovanni.earthdata.nasa.gov/timeseries"
SERVICE_NAME = "NASA GES DISC (Giovanni)"
IMERG_FIRST = "2000-06-01T00:00:00"
GRACE_FIRST = "2003-01-01T00:00:00"
LOW_GROUNDWATER_PCT = 20  # Req 23.9: finding when the last 12 months average below this

# part -> (Giovanni variable id, first time, source label, resolution in metres)
PARTS = {
    "rain": ("GPM_3IMERGM_07_precipitation", IMERG_FIRST,
             "NASA GPM IMERG Final (satellite rain, monthly)", 11000),
    "groundwater": ("GRACEDADM_CLSM0125US_7D_4_0_gws_inst", GRACE_FIRST,
                    "NASA GRACE/GRACE-FO data assimilation (GRACE-DA), groundwater", 14000),
    "root_zone": ("GRACEDADM_CLSM0125US_7D_4_0_rtzsm_inst", GRACE_FIRST,
                  "NASA GRACE/GRACE-FO data assimilation (GRACE-DA), root-zone soil moisture", 14000),
    "surface": ("GRACEDADM_CLSM0125US_7D_4_0_sfsm_inst", GRACE_FIRST,
                "NASA GRACE/GRACE-FO data assimilation (GRACE-DA), surface soil moisture", 14000),
}
GRACE_NOTE = ("GRACE measures changes in water across a region hundreds of kilometres wide; a land "
              "model spreads that onto a 12 km grid. Read it as the regional picture, not your field.")
IMERG_NOTE = ("IMERG is built from satellite microwave and infrared observations, adjusted with rain "
              "gauges. NASA POWER rain comes from a weather model (reanalysis).")
SMAP_STATUS = {"status": "unavailable", "source": "NASA SMAP",
               "reason": "SMAP soil moisture is planned for a later version of this tool."}

NO_TOKEN = "NASA Earthdata login is not set up on this server, so the satellite water data is not shown."
REJECTED = ("NASA Earthdata did not accept this server's login. The \"NASA GESDISC DATA ARCHIVE\" "
            "app may need approving on the Earthdata account.")


# ---- parsing ---------------------------------------------------------------------------------

def parse_csv(text: str) -> tuple[dict, list[tuple[str, float]]]:
    """Read one Giovanni CSV: metadata lines, a blank line, then "Timestamp (UTC),Data" rows.

    Returns (metadata, [(timestamp, value)]) with the "undef" fill value dropped.
    Raises SourceUnavailable when the text is not a Giovanni time series.
    """
    meta: dict[str, str] = {}
    rows: list[tuple[str, float]] = []
    in_data = False
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("timestamp"):
            in_data = True
            continue
        key, _, value = line.partition(",")
        if not in_data:
            meta[key.strip()] = value.strip()
            continue
        try:
            rows.append((key.strip(), float(value)))
        except ValueError:
            continue  # a stray line is skipped, not fatal
    if not in_data or "prod_name" not in meta:
        raise SourceUnavailable(f"{SERVICE_NAME} sent data we could not read")
    undef = _float(meta.get("undef"))
    rows = [(t, v) for t, v in rows if undef is None or abs(v - undef) > 1e-6]
    return meta, rows


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _grid(meta: dict) -> dict:
    return {"lat": _float(meta.get("lat")), "lon": _float(meta.get("lon"))}


# ---- rain (IMERG) ----------------------------------------------------------------------------

def rain_summary(meta: dict, rows: list[tuple[str, float]], source: str, resolution_m: int) -> dict:
    """Monthly rain in mm, the average of each calendar month, yearly totals and their trend."""
    monthly = []
    for stamp, rate in rows:
        y, m = int(stamp[:4]), int(stamp[5:7])
        days = calendar.monthrange(y, m)[1]
        monthly.append({"month": f"{y:04d}-{m:02d}", "rain_mm": round(rate * 24 * days, 1)})
    if not monthly:
        raise SourceUnavailable(f"{SERVICE_NAME} had no rain values for this spot")

    by_year: dict[int, list[float]] = {}
    for row in monthly:
        by_year.setdefault(int(row["month"][:4]), []).append(row["rain_mm"])
    yearly = {y: round(sum(v), 1) for y, v in by_year.items() if len(v) == 12}  # complete years only
    full_years = sorted(yearly)
    recent = full_years[-10:]
    return {
        "status": "ok", "source": source, "resolution_m": resolution_m, "units": "mm",
        "grid_point": _grid(meta), "doi": meta.get("doi"),
        "period": f"{monthly[0]['month']} to {monthly[-1]['month']}",
        "monthly": monthly,
        "calendar": calendar_average(monthly, full_years[0], full_years[-1]) if full_years else [None] * 12,
        "calendar_period": f"{full_years[0]}-{full_years[-1]}" if full_years else None,
        "yearly": [[y, yearly[y]] for y in full_years],
        "trend": trend(yearly) if yearly else None,
        "recent_avg": round(statistics.fmean(yearly[y] for y in recent), 1) if recent else None,
        "recent_period": f"{recent[0]}-{recent[-1]}" if recent else None,
        "note": IMERG_NOTE,
    }


def calendar_average(monthly: list[dict], first_year: int, last_year: int) -> list:
    """Average rain (mm) of each calendar month over the years first_year..last_year.

    A month with no value in that period is None, so the page can leave a gap instead of a 0.
    """
    sums = [[] for _ in range(12)]
    for row in monthly:
        y, m = int(row["month"][:4]), int(row["month"][5:7])
        if first_year <= y <= last_year:
            sums[m - 1].append(row["rain_mm"])
    return [round(statistics.fmean(v), 1) if v else None for v in sums]


# ---- GRACE percentiles -----------------------------------------------------------------------

def percentile_summary(meta: dict, rows: list[tuple[str, float]], source: str, resolution_m: int) -> dict:
    """Weekly percentiles -> monthly averages, the latest week, and the last-12-months average."""
    if not rows:
        raise SourceUnavailable(f"{SERVICE_NAME} had no GRACE values for this spot")
    months: dict[str, list[float]] = {}
    for stamp, v in rows:
        months.setdefault(stamp[:7], []).append(v)
    last_stamp, last_value = rows[-1]
    last_day = datetime.strptime(last_stamp[:10], "%Y-%m-%d").date()
    year_ago = (last_day - timedelta(days=365)).isoformat()
    last_year = [v for t, v in rows if t[:10] > year_ago]
    return {
        "status": "ok", "source": source, "resolution_m": resolution_m, "units": "percentile",
        "grid_point": _grid(meta), "doi": meta.get("doi"),
        "period": f"{rows[0][0][:10]} to {last_stamp[:10]}",
        "monthly": [{"month": k, "pct": round(statistics.fmean(v), 1)} for k, v in sorted(months.items())],
        "latest": {"date": last_stamp[:10], "pct": round(last_value, 1)},
        "last_12m_avg": round(statistics.fmean(last_year), 1) if last_year else None,
        "last_12m_period": f"{year_ago} to {last_stamp[:10]}",
        "note": GRACE_NOTE,
    }


# ---- fetching --------------------------------------------------------------------------------

def cache_key(today: date | None = None) -> str:
    """One cache entry per month, so the data refreshes at most once a month (Req 23.11)."""
    d = today or date.today()
    return f"nasa_water_{d.year:04d}-{d.month:02d}"


def is_valid_doc(doc: dict) -> bool:
    return doc.get("status") == "ok" and all(
        isinstance(doc.get(p), dict) and doc[p].get("status") == "ok" for p in PARTS)


async def _get_csv(client, var: str, first: str, lat: float, lon: float, token: str, today: date) -> str:
    params = {"data": var, "location": f"[{lat:.6f},{lon:.6f}]",
              "time": f"{first}/{today.isoformat()}T23:59:59"}
    r = await asyncio.wait_for(
        client.get(API, params=params, headers={"Authorization": f"Bearer {token}"}), UPSTREAM_TIMEOUT)
    # A rejected login shows up as 401/403, or as a 500 with {"message":null} from Giovanni.
    if r.status_code in (401, 403) or (r.status_code == 500 and '"message":null' in r.text.replace(" ", "")):
        raise SourceUnavailable(REJECTED)
    r.raise_for_status()
    return r.text


async def _part(client, name: str, lat: float, lon: float, token: str, today: date) -> dict:
    var, first, source, res = PARTS[name]
    try:
        meta, rows = parse_csv(await _get_csv(client, var, first, lat, lon, token, today))
        summary = rain_summary if name == "rain" else percentile_summary
        return summary(meta, rows, source, res)
    except Exception as e:  # noqa: BLE001 - one failing part must not hide the others
        return {"status": "unavailable", "source": source, "reason": describe_failure(SERVICE_NAME, e)}


async def fetch(client, lat: float, lon: float, cache: DiskCache, token: str | None = None,
                today: date | None = None) -> dict:
    """Return the water summary for a location. Never raises for an upstream problem.

    token: the Earthdata bearer token; default is the EARTHDATA_TOKEN environment variable.
    """
    today = today or date.today()
    key = cache_key(today)
    cached = cache.read_doc(key, lat, lon, is_valid_doc)
    if cached is not None:
        return cached

    token = (token if token is not None else os.environ.get("EARTHDATA_TOKEN", "")).strip()
    if not token:
        return {"status": "unavailable", "source": SERVICE_NAME, "reason": NO_TOKEN, "smap": SMAP_STATUS}

    names = list(PARTS)
    parts = await asyncio.gather(*(_part(client, n, lat, lon, token, today) for n in names))
    doc = {"status": "ok", "source": SERVICE_NAME, "fetched_on": today.isoformat(),
           **dict(zip(names, parts)), "smap": SMAP_STATUS}
    if all(p.get("status") != "ok" for p in parts):
        # Every part failed: say it once, with the first reason (they are usually the same).
        return {"status": "unavailable", "source": SERVICE_NAME, "reason": parts[0].get("reason"),
                "smap": SMAP_STATUS}
    if is_valid_doc(doc):
        cache.write_doc(key, lat, lon, doc)  # only complete results are cached
    return dict(doc, live_or_cached="live")


# ---- finding ---------------------------------------------------------------------------------

def groundwater_finding(doc: dict) -> dict | None:
    """Req 23.9: a finding when the last 12 months of GRACE groundwater average below 20 %."""
    gw = (doc or {}).get("groundwater") or {}
    avg = gw.get("last_12m_avg")
    if gw.get("status") != "ok" or avg is None or avg >= LOW_GROUNDWATER_PCT:
        return None
    return {
        "id": "low_groundwater", "title": "Groundwater is low",
        "text": (f"Over the last 12 months, groundwater in this region averaged {avg:.0f} on the 0-100 percentile "
                 f"scale: drier than about {100 - avg:.0f} % of the same weeks in 1948-2012. Wells may run lower, "
                 "so crops that need less water and living cover that helps rain soak in matter more."),
        "evidence": [{"value": avg, "units": "percentile", "source": gw.get("source"),
                      "resolution_m": gw.get("resolution_m"), "period": gw.get("last_12m_period")}],
        "terms": ["percentile", "grace"],
    }
