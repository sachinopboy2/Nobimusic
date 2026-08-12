"""Media download API client (configured via API_URL / API_KEY).

This is the FETCH gateway for YouTube on a COOKIELESS / PROXYLESS server. Song
SELECTION is done by YouTube's own InnerTube search (bot.utils.player.
search_youtube_detailed); the chosen YouTube watch URL is handed here to obtain
a directly-streamable media URL — so the bot never hits YouTube's throttled CDN
from its own IP, and never plays the wrong song.

Points at whatever API_URL you configure. Expected contract:
  GET /download?url=<media_url>&type=audio|video&api_key=<key>
    -> raw media bytes (audio/mp4 or video/mp4), Cloudflare-fronted with HTTP
       range support (206 on a ranged GET). 401 on bad key; JSON
       {"detail": "..."} (non-media content-type) on failure.

fetch_track(url) returns the ready-to-stream /download URL — NOT a download.
Because the endpoint supports range requests, py-tgcalls/ffmpeg streams it
directly; a cheap ranged preflight first confirms it returns media (not a JSON
error) so a bad/unsupported URL falls back instead of stalling the player.

Provider-agnostic: swap API_URL/API_KEY to any service exposing this /download
contract. (Was OneGrab's /api/track -> t.me flow before pass 65.)
"""

import logging
import os
import time
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger("WarbornMusic.mediaapi")

API_URL = os.getenv("API_URL", "").strip().rstrip("/")
API_KEY = os.getenv("API_KEY", "").strip()

_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Monotonic timestamp of the last 429. Lets the resolver tell the user WHY a
# YouTube-found track couldn't be fetched (rate-limited) rather than silently
# substituting a wrong song.
_last_429: float = 0.0


def enabled() -> bool:
    return bool(API_KEY and API_URL)


def rate_limited_recently(within: float = 180.0) -> bool:
    """True if the API returned a 429 in the last `within` seconds."""
    return _last_429 > 0.0 and (time.monotonic() - _last_429) < within


def download_url(track_url: str, kind: str = "audio") -> str:
    """Build the /download URL for a media URL. kind is 'audio' or 'video'.
    The api_key is placed LAST so a truncated log (...[:80]) can't leak it."""
    return f"{API_URL}/download?" + urlencode(
        {"url": track_url, "type": kind, "api_key": API_KEY}
    )


def _redact(url: str) -> str:
    return url.split("&api_key=", 1)[0] + "&api_key=***" if "&api_key=" in url else url


async def _preflight(url: str) -> bool:
    """Ranged GET of the first byte: True iff the endpoint returns media (a real
    audio/* or video/* body), False on 401/429/4xx/5xx or a JSON error body."""
    global _last_429
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
            async with s.get(url, headers={"Range": "bytes=0-1"}) as r:
                if r.status == 429:
                    _last_429 = time.monotonic()
                    logger.warning("[mediaapi] 429 rate-limited: %s", _redact(url))
                    return False
                if r.status not in (200, 206):
                    logger.info("[mediaapi] preflight HTTP %s: %s", r.status, _redact(url))
                    return False
                ctype = (r.headers.get("Content-Type") or "").lower()
                if not (ctype.startswith("audio/") or ctype.startswith("video/")):
                    logger.info("[mediaapi] preflight non-media (%s): %s", ctype, _redact(url))
                    return False
                return True
    except Exception as exc:
        logger.info("[mediaapi] preflight failed (%s): %s", exc, _redact(url))
        return False


async def fetch_track(track_url: str, *, video: bool = False) -> tuple[str | None, str, int | None]:
    """Resolve a SPECIFIC media URL (normally a YouTube watch URL chosen by
    YouTube's own search) to a streamable /download URL.

    Returns (stream_url, title, duration) or (None, "", None) on any miss
    (disabled, 401, rate-limited, unsupported URL). Title/duration are empty —
    the caller supplies them from the YouTube search result. Audio only for now;
    video stays on the yt-dlp path (a video=True call is skipped).
    """
    if not enabled() or video:
        return None, "", None
    url = download_url(track_url, "audio")
    if not await _preflight(url):
        return None, "", None
    logger.info("[mediaapi] stream ready for %s", str(track_url)[:60])
    return url, "", None
