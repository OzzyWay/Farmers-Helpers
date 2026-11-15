"""Dev helper: runs backend tests, a frontend build, a live geocode check and a live farm-data check.
Writes results to backend/verify_report.txt. Usage: .venv\\Scripts\\python.exe verify.py"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parent / "frontend"
NPM = r"C:\Program Files\nodejs\npm.cmd"
out = []


ENV = dict(os.environ, PATH=r"C:\Program Files\nodejs;" + os.environ.get("PATH", ""))


def run(name, cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV)
    out.append(f"===== {name} (exit {r.returncode}) =====\n{(r.stdout + r.stderr)[-2500:]}\n")


run("pytest", [sys.executable, "run_tests.py"], HERE)
run("frontend build", [NPM, "run", "build"], FRONTEND)

# Live check against the real geocoders (needs internet).
sys.path.insert(0, str(HERE))
from app.geocode import geocode  # noqa: E402

for q in ["100 W Main St, Fredericksburg, TX 78624", "Fredericksburg, Texas", "30.2752, -98.872"]:
    try:
        out.append(f"LIVE {q!r} -> {geocode(q)}")
    except Exception as e:  # noqa: BLE001
        out.append(f"LIVE {q!r} -> ERROR {type(e).__name__}: {e}")

# Live check of /api/farm-data for the first demo farm (needs internet).
# Uses a temporary cache folder so a cached result cannot hide a broken source,
# and so backend/cache/ is left as it was.
import json  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.cache import DiskCache  # noqa: E402

farm = json.loads((HERE.parent / "config" / "demo_farms.json").read_text(encoding="utf-8"))["farms"][0]
out.append(f"\n===== LIVE farm-data: {farm['name']} ({farm['lat']}, {farm['lon']}) =====")
tmp_cache = tempfile.mkdtemp(prefix="farmdata_verify_")
main.app.dependency_overrides[main.get_cache] = lambda: DiskCache(tmp_cache)
try:
    with TestClient(main.app, raise_server_exceptions=False) as client:
        start = time.perf_counter()
        r = client.get("/api/farm-data", params={"lat": str(farm["lat"]), "lon": str(farm["lon"])})
        out.append(f"HTTP {r.status_code} in {time.perf_counter() - start:.1f}s")
        if r.status_code == 200:
            for key, group in r.json()["sources"].items():
                if group["status"] == "ok":
                    states = ",".join(sorted({rec["live_or_cached"] for rec in group["records"]})) or "-"
                    out.append(f"  {key}: ok, {len(group['records'])} records ({states})")
                else:
                    out.append(f"  {key}: UNAVAILABLE - {group['reason']}")
        else:
            out.append(f"  body: {r.text[:300]}")
except Exception as e:  # noqa: BLE001
    out.append(f"  ERROR {type(e).__name__}: {e}")
finally:
    main.app.dependency_overrides.clear()

# Live check of /api/rotation for the same farm (needs internet), with its own temporary
# cache. The outlook comes from the precomputed demo-farm file; Open-Meteo is never called.
from app.outlook_store import OutlookStore  # noqa: E402

out.append(f"\n===== LIVE rotation: {farm['name']} =====")
rot_cache = DiskCache(tempfile.mkdtemp(prefix="rotation_verify_"))
main.app.dependency_overrides[main.get_cache] = lambda: rot_cache
main.app.dependency_overrides[main.get_outlook_store] = lambda: OutlookStore(rot_cache)
try:
    with TestClient(main.app, raise_server_exceptions=False) as client:
        start = time.perf_counter()
        r = client.get("/api/rotation", params={"lat": str(farm["lat"]), "lon": str(farm["lon"])})
        out.append(f"HTTP {r.status_code} in {time.perf_counter() - start:.1f}s")
        if r.status_code == 200:
            body = r.json()
            out.append(f"  missing sources: {body['missing_sources'] or 'none'}")
            out.append(f"  current rotation: {body['current_rotation'].get('label')} "
                       f"({body['current_rotation'].get('evidence')})")
            out.append(f"  strategies: {len(body['strategies'])} -> "
                       + ", ".join(f"{s['id']} ({s['confidence']})" for s in body["strategies"]))
            out.append(f"  findings: {len(body['findings'])} -> " + ", ".join(f["id"] for f in body["findings"]))
            out.append(f"  exclusions: {len(body['exclusions'])} -> "
                       + ", ".join(f"{e['crop_id']}:{e['rule']}" for e in body["exclusions"]))
            for key in ("soil_profile", "trends"):
                part = body[key]
                out.append(f"  {key}: {part['status']}" + (f" - {part.get('reason')}" if part["status"] != "ok" else ""))
            o = body["outlook"]
            out.append(f"  outlook: {o['status']}" + (f" ({o.get('origin')})" if o["status"] == "ok" else f" {o.get('reason', '')}"))
            w = body.get("water") or {}
            if w.get("status") == "ok":
                parts = []
                for p in ("rain", "groundwater", "root_zone", "surface"):
                    part = w.get(p) or {}
                    if part.get("status") != "ok":
                        parts.append(f"{p} UNAVAILABLE ({part.get('reason')})")
                    elif p == "rain":
                        parts.append(f"rain ok {part.get('period')}, recent {part.get('recent_avg')} mm/yr")
                    else:
                        parts.append(f"{p} ok latest {part['latest']['pct']} ({part['latest']['date']}), "
                                     f"12-month avg {part.get('last_12m_avg')}")
                out.append(f"  water ({w.get('live_or_cached')}): " + "; ".join(parts))
            else:
                out.append(f"  water: UNAVAILABLE - {w.get('reason')}")
            if body.get("engine_error"):
                out.append(f"  ENGINE ERROR: {body['engine_error']}")
        else:
            out.append(f"  body: {r.text[:300]}")
except Exception as e:  # noqa: BLE001
    out.append(f"  ERROR {type(e).__name__}: {e}")
finally:
    main.app.dependency_overrides.clear()

# Live check of /api/weather (National Weather Service, no key) with its own temporary cache.
out.append(f"\n===== LIVE weather: {farm['name']} =====")
wx_cache = DiskCache(tempfile.mkdtemp(prefix="weather_verify_"))
main.app.dependency_overrides[main.get_cache] = lambda: wx_cache
try:
    with TestClient(main.app, raise_server_exceptions=False) as client:
        start = time.perf_counter()
        r = client.get("/api/weather", params={"lat": str(farm["lat"]), "lon": str(farm["lon"])})
        out.append(f"HTTP {r.status_code} in {time.perf_counter() - start:.1f}s")
        if r.status_code == 200:
            body = r.json()
            missing = {"location", "source", "page_url", "forecast", "alerts"} - set(body)
            out.append(f"  keys: {'ok' if not missing else 'MISSING ' + str(missing)}")
            f, a = body["forecast"], body["alerts"]
            if f["status"] == "ok":
                out.append(f"  forecast: ok, {len(f['periods'])} periods, first {f['periods'][0]['name']}")
            else:
                out.append(f"  forecast: WARNING unavailable - {f.get('reason')}")
            if a["status"] == "ok":
                out.append(f"  alerts: ok, {len(a['official'])} official, {len(a['farm'])} farm "
                           f"({', '.join(x['title'] for x in a['farm']) or 'none'})")
            else:
                out.append(f"  alerts: WARNING unavailable - {a.get('reason')}")
        else:
            out.append(f"  body: {r.text[:300]}")
except Exception as e:  # noqa: BLE001
    out.append(f"  ERROR {type(e).__name__}: {e}")
finally:
    main.app.dependency_overrides.clear()

(HERE / "verify_report.txt").write_text("\n".join(out), encoding="utf-8")
