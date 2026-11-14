"""Everything this app asks Google through SerpAPI.

  geocode()          Google Maps: the typed address -> coordinates + formatted address
  local_resources()  Google Maps near the farm: extension offices, farm & ranch supply stores
  planting_guides()  Google Search on .edu sites: the state's university extension planting guides
  farm_news()        Google News: current farming / drought / crop news for the county and state

Results are cached on disk (data/cache/) so the same address doesn't spend credits twice.
"""

import hashlib
import json
import os
import re
import time
from urllib.parse import urlparse

from .net import ROOT, FetchError, get_json

SERPAPI_URL = "https://serpapi.com/search.json"
CACHE_DIR = ROOT / "data" / "cache"
CACHE_SECONDS = 6 * 3600


class SerpError(Exception):
    pass


def _api_key():
    key = os.environ.get("SERPAPI_API_KEY")
    if not key:
        raise SerpError("SERPAPI_API_KEY is not set. Put it in a .env file in the project folder.")
    return key


def _search(params, timeout=40):
    """One SerpAPI call, cached on disk by its parameters (minus the key)."""
    cache_key = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}.json"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < CACHE_SECONDS:
        return json.loads(cache_file.read_text())
    try:
        data = get_json(SERPAPI_URL, {**params, "api_key": _api_key()}, timeout=timeout)
    except FetchError as e:
        raise SerpError(f"SerpAPI request failed ({e})") from None
    if "error" in data:
        # "Google hasn't returned any results" is a normal empty answer, not a failure
        if "hasn't returned any results" in data["error"]:
            data = {}
        else:
            raise SerpError(data["error"])
    data.pop("search_metadata", None)  # holds URLs we don't need to keep
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data))
    return data


def _domain(url):
    host = urlparse(url or "").netloc
    return host[4:] if host.startswith("www.") else host


def geocode(address):
    """Find the address on Google Maps. Returns dict(lat, lon, label, address) or None."""
    data = _search({"engine": "google_maps", "type": "search", "q": address, "hl": "en", "gl": "us"})
    place = data.get("place_results")
    if not place and data.get("local_results"):
        place = data["local_results"][0]
    gps = (place or {}).get("gps_coordinates")
    if not gps:
        return None
    return {
        "lat": gps["latitude"],
        "lon": gps["longitude"],
        "label": place.get("title") or address,
        "address": place.get("address") or address,
    }


def local_resources(lat, lon):
    """Nearby places a farmer can actually go: extension offices and farm supply stores."""
    out = []
    for kind, query in (("Extension office", "agricultural extension office"),
                        ("Farm supply", "farm and ranch supply store")):
        data = _search({"engine": "google_maps", "type": "search", "q": query,
                        "ll": f"@{lat},{lon},11z", "hl": "en", "gl": "us"})
        for r in (data.get("local_results") or [])[:5]:
            gps = r.get("gps_coordinates") or {}
            if "latitude" not in gps:
                continue
            out.append({
                "kind": kind,
                "name": r.get("title", ""),
                "address": r.get("address", ""),
                "phone": r.get("phone", ""),
                "rating": r.get("rating"),
                "website": r.get("website", ""),
                "lat": gps["latitude"],
                "lon": gps["longitude"],
            })
    return out


def planting_guides(state, crops):
    """University extension (.edu) planting guides for this state and the recommended crops.

    Uses SerpAPI's DuckDuckGo engine: Google now returns encoded redirect links and ignores
    site:.edu, while DuckDuckGo returns the real page URLs and respects it.
    """
    crop_words = " ".join(crops[:3])

    def trusted(data):
        out = []
        for r in data.get("organic_results") or []:
            link = r.get("link", "")
            domain = _domain(link)
            if domain == "google.com":  # Google redirect link: read the real site from displayed_link
                domain = _domain((r.get("displayed_link") or "").split(" › ")[0])
            if domain.endswith(".edu") or domain.endswith(".gov"):  # extension / government only
                out.append({"title": r.get("title", ""), "link": link,
                            "snippet": r.get("snippet", ""), "source": domain})
        return out[:6]

    try:
        found = trusted(_search({"engine": "duckduckgo", "kl": "us-en",
                                 "q": f"{state} planting guide {crop_words} extension site:.edu"}, timeout=12))
        if found:
            return found
    except SerpError:
        pass  # DuckDuckGo is sometimes slow; fall back to Google below
    # Google ignores site:.edu, so name the extension service instead and filter the results.
    return trusted(_search({"engine": "google", "hl": "en", "gl": "us", "num": 10,
                            "q": f"{state} university cooperative extension planting calendar {crop_words}"}, timeout=25))


def farm_news(county, state):
    """Current agriculture news for the area (drought, crops, weather); county first, then state."""
    for place in ([f"{county} {state}"] if county else []) + [state]:
        stories = _news(place)
        if stories:
            return stories
    return []


def _news(place):
    data = _search({"engine": "google_news", "q": f"{place} farmers crops drought", "hl": "en", "gl": "us"})
    out = []
    for r in (data.get("news_results") or []):
        story = r if r.get("link") else (r.get("highlight") or {})
        if not story.get("link"):
            continue
        out.append({
            "title": story.get("title", ""),
            "link": story["link"],
            "source": (story.get("source") or {}).get("name", "") or _domain(story["link"]),
            "date": story.get("date", ""),
        })
        if len(out) == 6:
            break
    return out


STATE_RX = re.compile(r",\s*([A-Z]{2})\s*\d{5}")


def state_from_address(address):
    m = STATE_RX.search(address or "")
    return m.group(1) if m else None
