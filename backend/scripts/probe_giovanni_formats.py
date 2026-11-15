"""Probe (task 11.1, part 2): Giovanni answered HTTP 500 for every request. Try NASA's own
documented example first, then variations of our IMERG request, to find which part is wrong.
The token is never printed. Writes probe_giovanni_formats_report.txt next to this file.
Usage (from backend/):  .venv\\Scripts\\python.exe scripts\\probe_giovanni_formats.py
"""
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
API = "https://api.giovanni.earthdata.nasa.gov/timeseries"
REPORT = HERE / "probe_giovanni_formats_report.txt"


def env_token():
    path = ROOT / ".env"
    enc = "utf-16" if path.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    return (dotenv_values(path, encoding=enc).get("EARTHDATA_TOKEN") or "").strip() or None


TRIES = [
    # NASA's documented example (Giovanni In The Cloud: Time Series Service), unchanged.
    ("doc example", {"data": "M2T1NXSLV_5_12_4_U50M", "location": "[4.75,0.55]",
                     "time": "2000-06-01T00:00:00/2000-06-01T07:30:00", "version": "5.12.4"}),
    ("IMERG lat,lon", {"data": "GPM_3IMERGM_07_precipitation", "location": "[30.2336,-97.496]",
                       "time": "2023-01-01T00:00:00/2023-12-31T23:59:59"}),
    ("IMERG lat,lon +version", {"data": "GPM_3IMERGM_07_precipitation", "location": "[30.2336,-97.496]",
                                "time": "2023-01-01T00:00:00/2023-12-31T23:59:59", "version": "07"}),
    ("IMERG lon,lat +version", {"data": "GPM_3IMERGM_07_precipitation", "location": "[-97.496,30.2336]",
                                "time": "2023-01-01T00:00:00/2023-12-31T23:59:59", "version": "07"}),
    ("IMERG short time", {"data": "GPM_3IMERGM_07_precipitation", "location": "[30.2336,-97.496]",
                          "time": "2023-01-01T00:00:00/2023-03-01T00:00:00", "version": "07"}),
    ("GRACE gws +version", {"data": "GRACEDADM_CLSM0125US_7D_4_0_gws_inst", "location": "[30.2336,-97.496]",
                            "time": "2024-01-01T00:00:00/2024-03-31T23:59:59", "version": "4.0"}),
]

lines = [f"run at {time.strftime('%Y-%m-%d %H:%M:%S')}"]
try:
    token = env_token()
    lines.append(f"token found: {'yes' if token else 'NO'}")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=120, follow_redirects=False) as client:
        for label, params in TRIES:
            start = time.perf_counter()
            try:
                r = client.get(API, params=params, headers=headers)
                lines.append(f"\n[{label}] HTTP {r.status_code} in {time.perf_counter() - start:.1f}s, "
                             f"{len(r.content)} bytes, {r.headers.get('content-type', '?')}")
                if r.is_redirect:
                    lines.append(f"  redirect to {r.headers.get('location', '?').split('?')[0]}")
                lines.append("  " + "\n  ".join(r.text.splitlines()[:12]))
            except httpx.HTTPError as e:
                lines.append(f"\n[{label}] ERROR {type(e).__name__} after {time.perf_counter() - start:.1f}s")
        # Same doc example with no token, to see how a missing login looks.
        r = client.get(API, params=TRIES[0][1])
        lines.append(f"\n[doc example, NO token] HTTP {r.status_code}, {len(r.content)} bytes; "
                     f"redirect={r.is_redirect} {r.headers.get('location', '').split('?')[0]}")
finally:
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
