"""Check the SHAPE of EARTHDATA_TOKEN without revealing it: is it a JWT, when does it expire,
which login server issued it, and does it contain stray quotes or spaces?
Earthdata Login tokens are JWTs whose middle part is readable JSON (not secret by itself, but
we still print only a few safe fields). Writes check_token_shape_report.txt next to this file.
"""
import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
path = HERE.parents[1] / ".env"
enc = "utf-16" if path.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
raw = dotenv_values(path, encoding=enc).get("EARTHDATA_TOKEN") or ""
out = [f"run at {time.strftime('%Y-%m-%d %H:%M:%S')}"]
token = raw.strip()
out.append(f"present: {bool(token)}; length {len(token)}; spaces or newlines inside: {any(c.isspace() for c in token)}")
out.append(f"starts or ends with a quote: {token[:1] in '\"\'' or token[-1:] in '\"\''}" if token else "")
out.append(f"starts with 'Bearer ': {token.lower().startswith('bearer ')}")
parts = token.split(".")
out.append(f"JWT shape (3 dot-separated parts): {len(parts) == 3}")
if len(parts) == 3:
    try:
        pad = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
        exp = payload.get("exp")
        iat = payload.get("iat")
        if exp:
            exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
            out.append(f"expires: {exp_dt:%Y-%m-%d %H:%M} UTC ({'EXPIRED' if exp_dt < datetime.now(timezone.utc) else 'still valid'})")
        if iat:
            out.append(f"issued: {datetime.fromtimestamp(iat, tz=timezone.utc):%Y-%m-%d %H:%M} UTC")
        out.append(f"issuer: {payload.get('iss', '?')}")
        out.append(f"type: {payload.get('type', '?')}")
        out.append(f"payload fields: {sorted(payload.keys())}")
    except Exception as e:  # noqa: BLE001
        out.append(f"could not read the token header: {type(e).__name__}")
(HERE / "check_token_shape_report.txt").write_text("\n".join(x for x in out if x) + "\n", encoding="utf-8")
