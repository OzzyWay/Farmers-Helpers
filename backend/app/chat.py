"""'Ask about this field' chat, answered with SerpApi (no other AI key needed).

1. The question, plus a short description of the field from the page (place, soil, crops,
   forecast, alerts) and the last exchange, goes to Google AI Mode (SerpApi engine
   `google_ai_mode`). It writes the answer; its [n] citations become links.
2. "Where can I buy / find ... near me" questions also search Google Maps around the field.
3. If AI Mode gives nothing, a web search answers with the top links instead.

The key is SERPAPI_API_KEY in the repo-root .env. Every SerpApi response is cached on disk
for 6 hours in backend/cache/serpapi/, so asking the same thing again costs no search.
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

SERPAPI_URL = "https://serpapi.com/search.json"
CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "serpapi"
CACHE_SECONDS = 6 * 3600

MAX_MESSAGE_CHARS = 500
MAX_BRIEF_CHARS = 1200
MAX_QUERY_CHARS = 1800  # keep the AI Mode prompt a sensible size

NEARBY_RX = re.compile(
    r"\b(near me|nearby|near my|close to me|around here|where (can|do|should) i (buy|get|find|take|sell)|"
    r"store|shop|nursery|dealer|supplier|feed store|co-?op|vet\b|veterinarian|rental|rent\b|lab\b|"
    r"farmers market|extension office|usda office|nrcs office|fsa office)", re.IGNORECASE)


class SerpError(Exception):
    pass


class ChatError(Exception):
    def __init__(self, message: str, status: int = 500):
        super().__init__(message)
        self.status = status


def key_configured() -> bool:
    key = os.getenv("SERPAPI_API_KEY", "").strip()
    return bool(key) and not key.startswith("your_")


# ----------------------------------------------------------------------------- SerpApi calls

def _search(params: dict, timeout: float = 40) -> dict:
    """One SerpApi call, cached on disk by its parameters (never the key)."""
    cache_key = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}.json"
    try:
        if time.time() - cache_file.stat().st_mtime < CACHE_SECONDS:
            return json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if not key_configured():
        raise ChatError("The chat isn't set up yet: add SERPAPI_API_KEY to the .env file.", 503)
    try:
        r = httpx.get(SERPAPI_URL, params={**params, "api_key": os.environ["SERPAPI_API_KEY"].strip()},
                      timeout=timeout)
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise SerpError(f"SerpApi request failed ({type(e).__name__})") from None
    if "error" in data:
        if "hasn't returned any results" in data["error"]:
            data = {}  # a normal empty answer, not a failure
        elif r.status_code in (401, 403) or "api key" in data["error"].lower():
            raise ChatError("The SerpApi key was not accepted. Check SERPAPI_API_KEY in the .env file.", 503)
        else:
            raise SerpError(data["error"])
    data.pop("search_metadata", None)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass  # a cache problem must not break the answer
    return data


def _domain(url: str) -> str:
    host = urlparse(url or "").netloc
    return host[4:] if host.startswith("www.") else host


def _nearby(query: str, lat: float, lon: float, limit: int = 5) -> list[dict]:
    data = _search({"engine": "google_maps", "type": "search", "q": query,
                    "ll": f"@{lat},{lon},11z", "hl": "en", "gl": "us"})
    out = []
    for p in (data.get("local_results") or [])[:limit]:
        out.append({"name": p.get("title", ""), "address": p.get("address", ""), "phone": p.get("phone", ""),
                    "rating": p.get("rating"), "website": p.get("website", "")})
    return [p for p in out if p["name"]]


def _web_search(query: str, limit: int = 5) -> list[dict]:
    data = _search({"engine": "google", "q": query, "hl": "en", "gl": "us", "num": 10}, timeout=25)
    out = []
    for r in data.get("organic_results") or []:
        if r.get("link"):
            out.append({"title": r.get("title", ""), "url": r["link"], "source": _domain(r["link"])})
        if len(out) == limit:
            break
    return out


# ----------------------------------------------------------------------------- the question

def _recent_turns(history) -> str:
    """The last exchange, so follow-ups ("what about tomatoes?") make sense."""
    turns = [m for m in (history or []) if isinstance(m, dict) and m.get("role") in ("user", "assistant")
             and isinstance(m.get("content"), str)]
    lines = []
    for m in turns[-2:]:
        text = re.sub(r"\s+", " ", m["content"]).strip()
        lines.append(f"{'I asked' if m['role'] == 'user' else 'You answered'}: {text[:300]}")
    return ("Earlier in our chat: " + " / ".join(lines) + ".") if lines else ""


def build_query(message: str, history, brief: str) -> str:
    brief = re.sub(r"\s+", " ", brief or "").strip()[:MAX_BRIEF_CHARS]
    earlier = _recent_turns(history)
    ask = (f"My question: {message} "
           "Answer for my exact location in plain, friendly language for someone who is not a "
           "scientist or tech expert. Keep it short, use simple steps, and point me to my county's "
           "extension office or USDA service center for local help. Never give pesticide mixing "
           "rates; tell me to follow the label.")
    query = " ".join(x for x in (brief, earlier, ask) if x)
    if len(query) > MAX_QUERY_CHARS:  # trim the background, never the question
        room = MAX_QUERY_CHARS - len(ask) - 1
        query = (" ".join(x for x in (brief, earlier) if x)[:max(room, 0)] + " " + ask).strip()
    return query


# ----------------------------------------------------------------------------- tidy the answer

REF_MARK = re.compile(r"\\?\[(\d{1,2})\\?\]")       # [0] or \[0\]
MD_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~])")
LATEX = re.compile(r"\$([^$\n]{1,80})\$")           # inline math like $24^{\circ }\text{F}$


def _plain_math(expr: str) -> str:
    expr = re.sub(r"\^\s*\{?\s*\\circ\s*\}?", "°", expr)
    expr = re.sub(r"\\(?:text|mathrm|textbf)\{([^}]*)\}", r"\1", expr)
    for a, b in (("\\%", "%"), ("\\times", "×"), ("\\approx", "≈"), ("\\le", "≤"), ("\\ge", "≥")):
        expr = expr.replace(a, b)
    expr = re.sub(r"\\[,;! ]", " ", expr).replace("--", "–")
    expr = re.sub(r"[{}]", "", expr).replace("\\", "")
    return re.sub(r"\s+", " ", expr).strip()


def clean_markdown(text: str, references: list) -> str:
    """Drop AI Mode's own reference list, unescape, and turn [n] markers into links."""
    text = re.split(r"\n#{1,6}\s*References\s*\n", text, maxsplit=1)[0]
    text = re.sub(r"\[([^\]]*?)\s*Go to product viewer dialog for this item\.?\]\([^)]*\)", r"\1", text)
    links = {r.get("index"): r.get("link") for r in references if r.get("link")}

    def cite(m):
        n = int(m.group(1))
        return f"[[{n + 1}]]({links[n]})" if n in links else ""

    text = REF_MARK.sub(cite, text)
    text = LATEX.sub(lambda m: _plain_math(m.group(1)) if re.search(r"[\\^{}]", m.group(1)) else m.group(0), text)
    text = MD_ESCAPE.sub(r"\1", text)
    text = re.sub(r"(\[\[\d+\]\]\([^)]*\))(?:\s*\1)+", r"\1", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _ai_mode_answer(query: str):
    data = _search({"engine": "google_ai_mode", "q": query, "hl": "en", "gl": "us"}, timeout=50)
    refs = data.get("references") or []
    answer = clean_markdown(data.get("reconstructed_markdown") or "", refs)
    if not answer:
        blocks = []
        for b in data.get("text_blocks") or []:
            if b.get("type") == "heading" and b.get("snippet"):
                blocks.append(f"**{b['snippet']}**")
            elif b.get("snippet"):
                blocks.append(b["snippet"])
            for item in b.get("list") or []:
                if item.get("snippet"):
                    blocks.append(f"- {item['snippet']}")
        answer = "\n\n".join(blocks).strip()
    sources = [{"title": r.get("title") or r.get("source") or "Source", "url": r["link"],
                "source": r.get("source") or _domain(r["link"])} for r in refs if r.get("link")]
    return answer, sources


STOP_WORDS = re.compile(
    r"\b(where|can|do|should|i|buy|get|find|take|sell|near me|nearby|near my farm|near my field|around here|"
    r"close to me|the|a|an|my|to|for|is|are|there|any|some)\b", re.IGNORECASE)
PLACE_KIND = re.compile(
    r"\b(store|shop|office|nursery|vet|veterinarian|clinic|co-?op|market|dealer|supply|supplier|lab|"
    r"rental|elevator|gin|mill|auction|center|service|agency|farm|ranch|garden)\b", re.IGNORECASE)


def _nearby_answer(message: str, place: dict):
    if not place or place.get("lat") is None or place.get("lon") is None:
        return "", [], None
    what = re.sub(r"[^\w\s&'-]", " ", STOP_WORDS.sub(" ", message))
    what = re.sub(r"\s+", " ", what).strip() or "farm supply store"
    # "seed" alone finds a real-estate firm called SEED; say what kind of place it is.
    if not PLACE_KIND.search(what):
        what = f"{what} farm store"
    places = _nearby(what, float(place["lat"]), float(place["lon"]))
    if not places:
        return "", [], what
    lines = [f"**Places near your field for \"{what}\"** (from Google Maps):"]
    for p in places:
        bits = [p["address"], p["phone"], f"★ {p['rating']}" if p.get("rating") else ""]
        name = f"[{p['name']}]({p['website']})" if p.get("website") else p["name"]
        lines.append(f"- {name} — " + " · ".join(b for b in bits if b))
    sources = [{"title": p["name"], "url": p["website"], "source": "Google Maps"} for p in places if p.get("website")]
    return "\n".join(lines), sources, what


def _web_fallback(message: str, place: dict):
    where = (place or {}).get("label") or ""
    query = f"{message} {where} extension".strip()
    results = _web_search(query)
    if not results:
        return "", [], query
    lines = ["I couldn't write a full answer just now, but these pages cover your question:"]
    lines += [f"- [{r['title']}]({r['url']}) — {r['source']}" for r in results]
    return "\n".join(lines), results, query


def chat(message: str, history=None, place: dict | None = None, brief: str = "") -> dict:
    """Answer one question. Returns {"reply", "sources", "searches"}."""
    message = re.sub(r"\s+", " ", message or "").strip()
    if not message:
        raise ChatError("Type a question first.", 400)
    if len(message) > MAX_MESSAGE_CHARS:
        raise ChatError(f"Please keep questions under {MAX_MESSAGE_CHARS} characters.", 400)
    if not key_configured():
        raise ChatError("The chat isn't set up yet: add SERPAPI_API_KEY to the .env file.", 503)

    searches, sources, parts = [], [], []

    # 1. Google AI Mode, with the field's details
    try:
        answer, refs = _ai_mode_answer(build_query(message, history, brief))
        searches.append({"kind": "ai", "query": message})
        if answer:
            parts.append(answer)
            sources += refs
    except SerpError:
        pass

    # 2. Nearby places, when the question is about where to go or buy
    if NEARBY_RX.search(message):
        try:
            text, refs, what = _nearby_answer(message, place)
            if what:
                searches.append({"kind": "places", "query": what})
            if text:
                parts.append(text)
                sources += refs
        except SerpError:
            pass

    # 3. Plain web search if nothing else worked
    if not parts:
        try:
            text, refs, q = _web_fallback(message, place)
            searches.append({"kind": "web", "query": q})
            if text:
                parts.append(text)
                sources += refs
        except SerpError:
            raise ChatError("The search service isn't answering right now. Please try again in a minute.", 502)

    if not parts:
        parts.append("I couldn't find a good answer to that. Try asking another way, "
                     "or call your county extension office.")

    seen, unique = set(), []
    for s in sources:
        if s["url"] not in seen:
            seen.add(s["url"])
            unique.append(s)
    return {"reply": "\n\n".join(parts), "sources": unique[:8], "searches": searches}
