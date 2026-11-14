"""Small HTTP helpers (standard library only, so there's nothing to install)."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "FarmersHelpers/0.1 (hackathon project)"


class FetchError(Exception):
    """A request failed. The message never includes the URL, because URLs can carry API keys."""


def get_json(url, params=None, timeout=30):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    return _send(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout)


def post_json(url, body, timeout=30):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
    )
    return _send(req, timeout)


def _send(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FetchError(type(e).__name__) from None
    except ValueError:
        raise FetchError("response was not JSON") from None


def load_env():
    """Read KEY=value lines from the project's .env into os.environ (without overriding)."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() and not name.startswith("#"):
                os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))
