"""Voice for the "Ask about this field" chat, using ElevenLabs.

- speak(text):       chat answer -> MP3 (ElevenLabs text-to-speech). The answer is first turned
                     into plain spoken sentences (no links, source numbers or Markdown) and kept
                     short, since speech is billed per character. Audio is cached on disk, so
                     replaying an answer costs nothing.
- transcribe(audio): a recorded question -> text (ElevenLabs speech-to-text, "Scribe").

The key is ELEVENLABS_API_KEY in the repo-root .env. It never leaves the backend.
Optional: ELEVENLABS_VOICE_ID and ELEVENLABS_TTS_MODEL to change the voice or model.
"""
import hashlib
import os
import re
from pathlib import Path

import httpx

API = "https://api.elevenlabs.io/v1"
CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "tts"
DEFAULT_VOICE = "EXAVITQu4vr4xnSDxMaL"   # "Sarah": calm, reassuring; a built-in voice free accounts can use
DEFAULT_TTS_MODEL = "eleven_flash_v2_5"  # fast, and half the credits of the larger models
STT_MODEL = "scribe_v1"
# About 45 seconds of speech. The free ElevenLabs plan has 10,000 characters a month, so this
# allows about 14 answers; raise it with ELEVENLABS_MAX_CHARS on a paid plan.
MAX_SPOKEN_CHARS = 700
MAX_AUDIO_BYTES = 10 * 1024 * 1024
ALLOWED_AUDIO = ("audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/aac")


class SpeechError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def _key() -> str:
    return os.getenv("ELEVENLABS_API_KEY", "").strip()


def key_configured() -> bool:
    k = _key()
    return bool(k) and not k.startswith("your_")


def _require_key() -> str:
    if not key_configured():
        raise SpeechError("Voice isn't set up yet: add ELEVENLABS_API_KEY to the .env file.", 503)
    return _key()


def _upstream_error(r: httpx.Response, what: str) -> SpeechError:
    if r.status_code in (401, 403):
        return SpeechError("The ElevenLabs key was not accepted. Check ELEVENLABS_API_KEY in the .env file.", 503)
    if r.status_code == 429:
        return SpeechError("Voice is busy or out of credits right now. Please try again later.", 503)
    try:
        detail = r.json().get("detail")
        status = detail.get("status") if isinstance(detail, dict) else ""
    except ValueError:
        status = ""
    if status == "quota_exceeded":
        return SpeechError("The ElevenLabs account is out of voice credits for this month.", 503)
    if r.status_code == 402:
        return SpeechError("This voice needs a paid ElevenLabs plan. Set ELEVENLABS_VOICE_ID to one of "
                           "the account's built-in voices.", 503)
    return SpeechError(f"The voice service couldn't {what} right now. Please try again.", 502)


# ----------------------------------------------------------------------------- answer -> speech

def spoken_text(markdown: str, limit: int | None = None) -> str:
    """Turn a chat answer into plain sentences that sound right read aloud."""
    if limit is None:  # read at call time: .env is loaded after this module is imported
        try:
            limit = int(os.getenv("ELEVENLABS_MAX_CHARS") or MAX_SPOKEN_CHARS)
        except ValueError:
            limit = MAX_SPOKEN_CHARS
    t = markdown or ""
    t = re.sub(r"\[\[\d+\]\]\([^)]*\)", "", t)                 # [[1]](url) source numbers
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)             # [label](url) -> label
    t = re.sub(r"https?://\S+", "", t)                          # bare links
    t = re.sub(r"(\*\*|__|\*|`)", "", t)                        # bold / italic / code marks
    t = re.sub(r"^\s*#{1,6}\s*(.+)$", r"\1.", t, flags=re.M)    # headings become short sentences
    t = re.sub(r"^\s*(?:[-•]|\d+[.)])\s+", "", t, flags=re.M)   # list markers
    t = t.replace("★", "rated ").replace(" · ", ", ").replace(" — ", ", ").replace("°F", " degrees")
    lines = []
    for line in t.split("\n"):
        line = line.strip()
        if line:
            lines.append(line if re.search(r"[.!?:;,]$", line) else line + ".")
    t = re.sub(r"\s+", " ", " ".join(lines)).strip()
    t = re.sub(r"\s+([.,;:!?])", r"\1", t).replace("..", ".")
    if len(t) > limit:  # stop at the last full sentence that fits
        cut = t[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        t = (cut[: end + 1] if end > limit // 2 else cut.rsplit(" ", 1)[0] + ".")
        t += " The full answer is written in the chat."
    return t


def speak(markdown: str) -> bytes:
    """Return MP3 audio for a chat answer."""
    text = spoken_text(markdown)
    if not text:
        raise SpeechError("There is nothing to read aloud.", 400)
    voice = os.getenv("ELEVENLABS_VOICE_ID", "").strip() or DEFAULT_VOICE
    model = os.getenv("ELEVENLABS_TTS_MODEL", "").strip() or DEFAULT_TTS_MODEL
    cache_file = CACHE_DIR / (hashlib.sha1(f"{voice}|{model}|{text}".encode()).hexdigest() + ".mp3")
    try:
        return cache_file.read_bytes()
    except OSError:
        pass
    key = _require_key()
    try:
        r = httpx.post(
            f"{API}/text-to-speech/{voice}",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": key, "Accept": "audio/mpeg"},
            json={"text": text, "model_id": model},
            timeout=60,
        )
    except httpx.HTTPError:
        raise SpeechError("The voice service couldn't be reached. Please try again.", 502) from None
    if r.status_code != 200 or not r.content:
        raise _upstream_error(r, "read this aloud")
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(r.content)
    except OSError:
        pass  # a cache problem must not stop the audio
    return r.content


# ----------------------------------------------------------------------------- speech -> question

def transcribe(audio: bytes, content_type: str) -> str:
    """Return the words spoken in a short recording."""
    if not audio:
        raise SpeechError("I didn't hear anything. Tap the microphone and try again.", 400)
    if len(audio) > MAX_AUDIO_BYTES:
        raise SpeechError("That recording is too long. Please keep questions under a minute.", 400)
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime not in ALLOWED_AUDIO:
        raise SpeechError("That recording format isn't supported.", 400)
    key = _require_key()
    ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3",
           "audio/aac": "aac"}.get(mime, "wav")
    try:
        r = httpx.post(
            f"{API}/speech-to-text",
            headers={"xi-api-key": key},
            data={"model_id": STT_MODEL, "tag_audio_events": "false"},
            files={"file": (f"question.{ext}", audio, mime)},
            timeout=60,
        )
    except httpx.HTTPError:
        raise SpeechError("The voice service couldn't be reached. Please try again.", 502) from None
    if r.status_code != 200:
        raise _upstream_error(r, "understand the recording")
    text = re.sub(r"\s+", " ", (r.json().get("text") or "")).strip()
    text = re.sub(r"\((?:[^)]*(?:music|noise|silence|background)[^)]*)\)", "", text, flags=re.I).strip()
    if not text:
        raise SpeechError("I couldn't make out any words. Try again a little closer to the microphone.", 400)
    return text
