"""Field Shift backend. Run with: uvicorn app.main:app --reload (from /backend)."""
import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Body, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import Response
import rasterio

from app.cache import DiskCache
from app.farm_data import gather_farm_data
from app.geocode import GeocodeError, check_location, geocode
from app.outlook_store import OutlookStore
from app.rotation import crops as crop_table
from app.rotation.site_facts import LIVESTOCK_VALUES, PRIORITIES, FarmInputs
from app.rotation_data import gather_rotation
from app.weather_data import gather_weather
from app.services.base import make_client
from app.raster_overlays import RasterOverlayService

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"


def _env_encoding(path: Path) -> str:
    """.env files saved from PowerShell are often UTF-16; detect via the BOM."""
    if not path.exists():
        return "utf-8"
    head = path.read_bytes()[:2]
    return "utf-16" if head in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"


# The Earthdata token lives in the repo-root .env. Only the backend reads it.
load_dotenv(ENV_FILE, encoding=_env_encoding(ENV_FILE))

app = FastAPI(title="Field Shift API")

# Allow the Vite dev server to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/geocode")
def geocode_endpoint(q: str = Query(..., description="Street address or 'lat, lon'")):
    """Return {lat, lon, label, source} for a US address or coordinates."""
    try:
        return geocode(q)
    except GeocodeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/demo-farms")
def demo_farms():
    """Exact demo farm coordinates are stored in config/demo_farms.json."""
    with open(ROOT / "config" / "demo_farms.json", encoding="utf-8") as f:
        return json.load(f)


async def get_http_client():
    """One HTTP client per request for the upstream sources. Tests replace this with a mock."""
    async with make_client() as client:
        yield client


def get_cache() -> DiskCache:
    """The disk cache in backend/cache/. Tests replace this with a temporary folder."""
    return DiskCache()


@app.get("/api/farm-data")
async def farm_data(
    lat: str | None = Query(None, description="Latitude, e.g. 30.233589"),
    lon: str | None = Query(None, description="Longitude, e.g. -97.496006"),
    client=Depends(get_http_client),
    cache: DiskCache = Depends(get_cache),
):
    """Climate, soil and crop history for one US location, grouped by source.

    lat/lon are read as text so bad input gets a plain 400 message instead of
    FastAPI's default validation error. Upstream failures never cause a 500: the
    failing source is reported as unavailable and the others are still returned.
    """
    try:
        lat_f, lon_f = check_location(lat, lon)
    except GeocodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await gather_farm_data(client, lat_f, lon_f, cache)


# ---------------------------------------------------------------------------
# Rotation explorer (spec rotation-explorer, task 8)
# ---------------------------------------------------------------------------

# Read and check config/crops.json once, when the server starts. A bad edit stops the
# server here with a message naming the crop and the field (Req 5.5).
CROPS = crop_table.load()

# One outlook store for the whole server: it remembers which outlook is loading.
_outlook_store: OutlookStore | None = None
_raster_overlay_service = RasterOverlayService()


def get_crops() -> dict:
    return CROPS


def get_outlook_store() -> OutlookStore:
    """The shared outlook store. Tests replace this with one using a temporary folder."""
    global _outlook_store
    if _outlook_store is None:
        _outlook_store = OutlookStore(DiskCache())
    return _outlook_store


def get_raster_overlay_service() -> RasterOverlayService:
    return _raster_overlay_service


@app.get("/api/rasters")
def raster_catalog(
    refresh: bool = Query(False),
    service: RasterOverlayService = Depends(get_raster_overlay_service),
):
    """Discover raster paths without downloading raster pixels."""
    try:
        rasters = service.catalog(refresh=refresh)
        return {"rasters": rasters, "warnings": service.warnings}
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"Could not read raster catalog: {e}")


@app.get("/api/rasters/{asset_id}")
def raster_details(
    asset_id: str,
    service: RasterOverlayService = Depends(get_raster_overlay_service),
):
    """Download and inspect only the selected raster."""
    try:
        asset = service.asset(asset_id)
        return {
            key: value
            for key, value in asset.items()
            if key not in {
                "path", "identity", "modified", "series_key", "overrides",
                "repo_id", "repo_path", "revision", "kind",
            }
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=422, detail=f"Could not inspect raster: {e}")


@app.get("/api/rasters/{asset_id}/tiles/{z}/{x}/{y}.png")
def raster_tile(
    asset_id: str,
    z: int,
    x: int,
    y: int,
    band: int = Query(1, ge=1),
    ramp: str = Query("viridis", pattern="^(viridis|magma|blue-red)$"),
    service: RasterOverlayService = Depends(get_raster_overlay_service),
):
    """Read, reproject, and color only the requested 256px Web Mercator tile."""
    try:
        image = service.tile(asset_id, z, x, y, band, ramp)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (OSError, rasterio.errors.RasterioError) as e:
        raise HTTPException(status_code=502, detail=f"Could not render raster tile: {e}")
    return Response(
        content=image,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/api/rasters/{asset_id}/summary")
def raster_summary(
    asset_id: str,
    geometry: dict = Body(..., description="GeoJSON Polygon or MultiPolygon in EPSG:4326."),
    service: RasterOverlayService = Depends(get_raster_overlay_service),
):
    """Calculate raster statistics only for pixels intersecting the selected region."""
    try:
        return service.summary(asset_id, geometry)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (OSError, rasterio.errors.RasterioError) as e:
        raise HTTPException(status_code=422, detail=f"Could not summarize raster: {e}")


def get_client_factory():
    """Makes the HTTP client for a background outlook load. The per-request client is
    closed when the response is sent, so the background task needs its own."""
    return make_client


def _location(lat, lon) -> tuple[float, float]:
    try:
        return check_location(lat, lon)
    except GeocodeError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _choice(name: str, value: str | None, allowed: tuple, default: str) -> str:
    """Check a yes/no style parameter. Unknown values give a 400 that names the value."""
    if value is None or value.strip() == "":
        return default
    v = value.strip().lower()
    if v not in allowed:
        raise HTTPException(status_code=400,
                            detail=f"unknown {name} value '{value}'; use one of: {', '.join(allowed)}")
    return v


def parse_inputs(priorities, irrigation, livestock, no_till, current, crops) -> FarmInputs:
    chosen = set()
    for item in (priorities or "").split(","):
        item = item.strip().lower()
        if not item:
            continue
        if item not in PRIORITIES:
            raise HTTPException(status_code=400,
                                detail=f"unknown priority '{item}'; use one of: {', '.join(PRIORITIES)}")
        chosen.add(item)
    current = (current or "").strip() or None
    if current is not None and current not in crops:
        raise HTTPException(status_code=400,
                            detail=f"unknown crop '{current}'; use a crop id from the crop table")
    return FarmInputs(
        priorities=frozenset(chosen),
        irrigation=_choice("irrigation", irrigation, ("yes", "no"), "no") == "yes",
        livestock=_choice("livestock", livestock, LIVESTOCK_VALUES, "unknown"),
        no_till=_choice("no_till", no_till, ("yes", "no"), "no") == "yes",
        current_override=current,
    )


@app.get("/api/rotation")
async def rotation(
    lat: str | None = Query(None, description="Latitude, e.g. 30.233589"),
    lon: str | None = Query(None, description="Longitude, e.g. -97.496006"),
    priorities: str | None = Query(None, description="Comma list: " + ", ".join(PRIORITIES)),
    irrigation: str | None = Query(None, description="yes or no (default no)"),
    livestock: str | None = Query(None, description="yes, no or unknown (default unknown)"),
    no_till: str | None = Query(None, description="yes or no (default no)"),
    current: str | None = Query(None, description="Crop id that replaces the crop-map guess"),
    client=Depends(get_http_client),
    cache: DiskCache = Depends(get_cache),
    store: OutlookStore = Depends(get_outlook_store),
    crops: dict = Depends(get_crops),
):
    """Rotation options for one US field, with the soil profile, climate trends and outlook.

    Bad input gives a 400 that names the bad value. After that the answer is always 200:
    a failing source is listed in missing_sources and lowers the confidence.
    """
    lat_f, lon_f = _location(lat, lon)
    inputs = parse_inputs(priorities, irrigation, livestock, no_till, current, crops)
    return await gather_rotation(client, lat_f, lon_f, cache, store, crops, inputs)


@app.get("/api/outlook")
def outlook_status(
    lat: str | None = Query(None),
    lon: str | None = Query(None),
    store: OutlookStore = Depends(get_outlook_store),
):
    """Whether the 2030-2049 outlook is ready, loading, not loaded or unavailable here."""
    lat_f, lon_f = _location(lat, lon)
    try:
        return store.status(lat_f, lon_f)
    except Exception:  # noqa: BLE001 - never a 500
        return {"status": "unavailable", "reason": "the outlook status could not be read"}


@app.post("/api/outlook/load")
def outlook_load(
    background: BackgroundTasks,
    lat: str | None = Query(None),
    lon: str | None = Query(None),
    store: OutlookStore = Depends(get_outlook_store),
    client_factory=Depends(get_client_factory),
):
    """Start loading the outlook in the background if the free Open-Meteo quota allows it.

    202 "loading" when a load starts (or is already running here), 200 "ready" when the
    outlook is already available, 200 "unavailable" with a reason otherwise.
    """
    lat_f, lon_f = _location(lat, lon)
    try:
        current = store.status(lat_f, lon_f)
        if current["status"] in ("ready", "loading"):
            return JSONResponse(current, status_code=202 if current["status"] == "loading" else 200)
        decision = store.can_start(lat_f, lon_f)
    except Exception:  # noqa: BLE001 - never a 500
        return {"status": "unavailable", "reason": "the outlook could not be started"}
    if decision["status"] != "loading":
        return decision

    async def run_load():
        async with client_factory() as c:
            await store.load(c, lat_f, lon_f)  # never raises; records its own failure

    store.reserve(lat_f, lon_f)
    background.add_task(run_load)
    return JSONResponse(decision, status_code=202)


@app.get("/api/weather")
async def weather(
    lat: str | None = Query(None, description="Latitude, e.g. 30.233589"),
    lon: str | None = Query(None, description="Longitude, e.g. -97.496006"),
    client=Depends(get_http_client),
    cache: DiskCache = Depends(get_cache),
):
    """National Weather Service 7-day forecast, official alerts and farm alerts for one US location.

    Same location checks as /api/farm-data (400 naming the bad value). After that the answer is
    always 200: a failing part is marked unavailable with a plain reason.
    """
    lat_f, lon_f = _location(lat, lon)
    return await gather_weather(client, lat_f, lon_f, cache)
