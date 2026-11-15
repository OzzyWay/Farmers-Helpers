"""List the variable NAMES in the repo-root .env (never the values). Writes env_names_report.txt.
Also reports lines that look broken (no "=", a leading "#", quotes or spaces around the name),
again without showing any value."""
import time
from pathlib import Path

from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
path = HERE.parents[1] / ".env"
raw = path.read_bytes()
enc = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
out = [f"run at {time.strftime('%Y-%m-%d %H:%M:%S')}", f"encoding: {enc}, {len(raw)} bytes"]
for name, v in dotenv_values(path, encoding=enc).items():
    out.append(f"  {name!r}: {'set' if (v or '').strip() else 'EMPTY'}")
out.append("line shapes (name part only):")
for i, line in enumerate(raw.decode(enc, errors="replace").splitlines(), 1):
    if not line.strip():
        continue
    name = line.split("=", 1)[0]
    out.append(f"  line {i}: name={name!r} has_equals={'=' in line} commented={line.lstrip().startswith('#')}")
(HERE / "env_names_report.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
