"""Time full-length Giovanni requests for Webberwood and save them as fixtures (task 11.3 prep).
The token is never printed. Writes probe_nasa_water_full_report.txt next to this file.
"""
import asyncio
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "tests" / "fixtures"
path = HERE.parents[1] / ".env"
enc = "utf-16" if path.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
TOKEN = (dotenv_values(path, encoding=enc).get("EARTHDATA_TOKEN") or "").strip()
API = "https://api.giovanni.earthdata.nasa.gov/timeseries"
LOC = "[30.233589,-97.496006]"
JOBS = {
    "imerg_full": ("GPM_3IMERGM_07_precipitation", "2000-06-01T00:00:00/2026-10-31T23:59:59"),
    "grace_gws_full": ("GRACEDADM_CLSM0125US_7D_4_0_gws_inst", "2003-01-01T00:00:00/2026-11-14T23:59:59"),
    "grace_rtzsm_full": ("GRACEDADM_CLSM0125US_7D_4_0_rtzsm_inst", "2003-01-01T00:00:00/2026-11-14T23:59:59"),
    "grace_sfsm_full": ("GRACEDADM_CLSM0125US_7D_4_0_sfsm_inst", "2003-01-01T00:00:00/2026-11-14T23:59:59"),
}
lines = [f"run at {time.strftime('%Y-%m-%d %H:%M:%S')}"]


async def one(client, name, var, rng):
    start = time.perf_counter()
    try:
        r = await client.get(API, params={"data": var, "location": LOC, "time": rng},
                             headers={"Authorization": f"Bearer {TOKEN}"})
    except httpx.HTTPError as e:
        return f"{name}: ERROR {type(e).__name__} after {time.perf_counter() - start:.1f}s"
    took = time.perf_counter() - start
    rows = [ln for ln in r.text.splitlines() if ln[:2] in ("19", "20") and ln[4:5] == "-"]
    msg = f"{name}: HTTP {r.status_code} in {took:.1f}s, {len(r.content)} bytes, {len(rows)} rows"
    if rows:
        msg += f", first {rows[0]}, last {rows[-1]}"
    if r.status_code == 200 and rows:
        (FIXTURES / f"giovanni_{name}.csv").write_text(r.text, encoding="utf-8")
    else:
        msg += "\n  " + "\n  ".join(r.text.splitlines()[:5])
    return msg


async def main():
    async with httpx.AsyncClient(timeout=120) as client:
        start = time.perf_counter()
        results = await asyncio.gather(*(one(client, n, v, t) for n, (v, t) in JOBS.items()))
        lines.extend(results)
        lines.append(f"all four in parallel: {time.perf_counter() - start:.1f}s")


try:
    asyncio.run(main())
finally:
    (HERE / "probe_nasa_water_full_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
