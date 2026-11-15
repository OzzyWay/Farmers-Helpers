"""Probe (task 11.1): can our Earthdata token read IMERG rain and GRACE groundwater / soil
moisture for Webberwood from the GES DISC Giovanni Time Series service?

Usage (from backend/):  .venv\\Scripts\\python.exe scripts\\probe_nasa_water.py
Writes backend/scripts/probe_nasa_water_report.txt and, on success, CSV samples into
backend/tests/fixtures/. The token is read from the repo-root .env and is never printed,
logged or written anywhere: the report only says whether it was found.
"""
import json
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURES = HERE.parent / "tests" / "fixtures"
REPORT = HERE / "probe_nasa_water_report.txt"
API = "https://api.giovanni.earthdata.nasa.gov"
LAT, LON = 30.233589, -97.496006  # Webberwood Ranch (config/demo_farms.json)

# Variable id -> (short fixture name, a short time range to test with)
VARIABLES = {
    "GPM_3IMERGM_07_precipitation": ("imerg_monthly", "2023-01-01T00:00:00/2023-12-31T23:59:59"),
    "GRACEDADM_CLSM0125US_7D_4_0_gws_inst": ("grace_gws", "2024-01-01T00:00:00/2024-03-31T23:59:59"),
    "GRACEDADM_CLSM0125US_7D_4_0_rtzsm_inst": ("grace_rtzsm", "2024-01-01T00:00:00/2024-03-31T23:59:59"),
}

lines = []


def env_token():
    path = ROOT / ".env"
    if not path.exists():
        return None
    enc = "utf-16" if path.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    return (dotenv_values(path, encoding=enc).get("EARTHDATA_TOKEN") or "").strip() or None


def main():
    lines.append(f"run at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    token = env_token()
    lines.append(f"EARTHDATA_TOKEN found in .env: {'yes' if token else 'NO'}")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    with httpx.Client(timeout=90, follow_redirects=False) as client:
        # 1. Is each variable configured in the service? (public list)
        try:
            r = client.get(f"{API}/configured-variables/")
            lines.append(f"configured-variables: HTTP {r.status_code}, {len(r.content)} bytes")
            if r.status_code == 200:
                text = r.text
                for var in VARIABLES:
                    lines.append(f"  {var}: {'listed' if var in text else 'NOT LISTED'}")
                # Note any similar names, in case the version number changed.
                try:
                    names = list(json.loads(text).keys()) if text.strip().startswith("{") else []
                except ValueError:
                    names = []
                for key in ("IMERGM", "GRACEDADM"):
                    similar = sorted(n for n in names if key in n)[:12]
                    lines.append(f"  names containing {key}: {similar}")
        except httpx.HTTPError as e:
            lines.append(f"configured-variables: ERROR {type(e).__name__}")

        # 2. One short sample per variable, with the token.
        if not token:
            lines.append("No token, so the data requests were skipped.")
            return
        for var, (short, time_range) in VARIABLES.items():
            params = {"data": var, "location": f"[{LAT},{LON}]", "time": time_range}
            start = time.perf_counter()
            try:
                r = client.get(f"{API}/timeseries", params=params, headers=headers)
            except httpx.HTTPError as e:
                lines.append(f"\n{var}: ERROR {type(e).__name__} after {time.perf_counter() - start:.1f}s")
                continue
            took = time.perf_counter() - start
            kind = r.headers.get("content-type", "?")
            lines.append(f"\n{var}: HTTP {r.status_code} in {took:.1f}s, {len(r.content)} bytes, {kind}")
            if r.status_code in (301, 302, 303, 307, 308):
                lines.append(f"  redirected to: {r.headers.get('location', '?').split('?')[0]}  (token not accepted?)")
            body = r.text
            lines.append("  first lines:\n    " + "\n    ".join(body.splitlines()[:14]))
            if r.status_code == 200 and "," in body:
                FIXTURES.mkdir(parents=True, exist_ok=True)
                (FIXTURES / f"giovanni_{short}.csv").write_text(body, encoding="utf-8")
                lines.append(f"  saved tests/fixtures/giovanni_{short}.csv")


try:
    main()
finally:
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
