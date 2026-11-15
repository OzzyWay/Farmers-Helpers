"""Does our token open a protected GES DISC data FILE (outside Giovanni)? This tells apart
"GES DISC app not approved on the Earthdata account" from "Giovanni service failing".
Only headers are requested (no download). The token is never printed.
Writes probe_gesdisc_access_report.txt next to this file.
"""
import re
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
path = HERE.parents[1] / ".env"
enc = "utf-16" if path.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
token = (dotenv_values(path, encoding=enc).get("EARTHDATA_TOKEN") or "").strip()
FOLDER = "https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/GPM_3IMERGM.07/2023/"

lines = [f"run at {time.strftime('%Y-%m-%d %H:%M:%S')}"]
try:
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        listing = client.get(FOLDER).text
        names = sorted(set(re.findall(r'href="([^"]+\.HDF5)"', listing)))
        lines.append(f"files in the 2023 IMERG monthly folder: {len(names)}")
        if names:
            url = FOLDER + names[0].split("/")[-1]
            lines.append(f"testing: {url}")
            for label, headers in (("with token", {"Authorization": f"Bearer {token}"}), ("no token", {})):
                r = client.head(url, headers=headers)
                where = r.headers.get("location", "").split("?")[0]
                lines.append(f"  [{label}] HTTP {r.status_code}, length {r.headers.get('content-length', '?')}"
                             + (f", redirect to {where}" if where else ""))
                # Follow one redirect step by hand, still with the token, to see where it ends.
                hops = 0
                while r.is_redirect and hops < 4 and label == "with token":
                    nxt = r.headers["location"]
                    r = client.head(nxt, headers=headers)
                    hops += 1
                    lines.append(f"    hop {hops}: HTTP {r.status_code} at {nxt.split('?')[0]}")
finally:
    (HERE / "probe_gesdisc_access_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
