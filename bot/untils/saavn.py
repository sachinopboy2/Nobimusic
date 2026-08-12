"""JioSaavn audio source.

A fallback audio provider for text /play and /song queries. JioSaavn's
public API returns a direct MP3/M4A URL that PyTgCalls can stream and
yt-dlp can download — and it answers from datacenter IPs (Railway, AWS,
etc.) where YouTube withholds music formats. No cookies, no login.

Flow: search.getResults -> pick first song -> DES-decrypt its
`encrypted_media_url` (JioSaavn's public scheme) -> upgrade to 320kbps
when the track advertises it.
"""

import base64
import logging
import urllib.parse

import aiohttp

from cryptography.hazmat.primitives.ciphers import Cipher, modes

try:  # cryptography>=43 moved single-key DES here
    from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
except Exception:  # pragma: no cover - older cryptography
    from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES

logger = logging.getLogger("WarbornMusic.saavn")

_DES_KEY = b"38346591"  # JioSaavn's public media-URL key
_SEARCH_URL = (
    "https://www.jiosaavn.com/api.php?__call=search.getResults&_format=json"
    "&_marker=0&api_version=4&ctx=web6dot0&q={q}"
)
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_TIMEOUT = aiohttp.ClientTimeout(total=20)


def _decrypt_media_url(encrypted: str) -> str:
    ct = base64.b64decode(encrypted)
    dec = Cipher(TripleDES(_DES_KEY), modes.ECB()).decryptor()
    out = dec.update(ct) + dec.finalize()
    # Strip PKCS#5/7 padding.
    pad = out[-1]
    if 1 <= pad <= 8:
        out = out[:-pad]
    return out.decode("utf-8", errors="replace")


def _upgrade_quality(url: str, has_320: bool) -> str:
    if not has_320:
        return url
    for low in ("_96.mp4", "_160.mp4"):
        if low in url:
            return url.replace(low, "_320.mp4")
    return url


def _duration_of(more: dict, song: dict) -> int | None:
    raw = more.get("duration") or song.get("duration")
    try:
        d = int(raw)
        return d if d > 0 else None
    except (TypeError, ValueError):
        return None


async def search_jiosaavn(query: str) -> tuple[str, str, int | None] | None:
    """Return (stream_url, "Title - Artist", duration_seconds) for the top
    JioSaavn match, or None if nothing usable was found.
    """
    url = _SEARCH_URL.format(q=urllib.parse.quote(query))
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
            async with s.get(url, headers=_HEADERS) as resp:
                if resp.status != 200:
                    logger.info("saavn: search HTTP %s for %r", resp.status, query)
                    return None
                data = await resp.json(content_type=None)
    except Exception as exc:
        logger.info("saavn: search failed for %r: %s", query, exc)
        return None

    # Use JioSaavn's own relevance ranking (first usable result). Sorting
    # by play_count was tried and hurt relevance (surfaced popular but
    # unrelated tracks), so keep the API order.
    for song in (data.get("results") or []):
        more = song.get("more_info") or {}
        enc = more.get("encrypted_media_url") or song.get("encrypted_media_url")
        if not enc:
            continue
        try:
            media = _decrypt_media_url(enc)
        except Exception as exc:
            logger.info("saavn: decrypt failed: %s", exc)
            continue
        if not media.startswith("http"):
            continue
        has_320 = str(more.get("320kbps") or song.get("320kbps") or "").lower() == "true"
        stream = _upgrade_quality(media, has_320)
        title = song.get("title") or song.get("song") or query
        artist = (
            more.get("artistMap", {}).get("primary_artists", [{}])[0].get("name")
            if isinstance(more.get("artistMap"), dict) else None
        ) or song.get("subtitle") or ""
        # Titles/subtitles arrive HTML-escaped from the API.
        import html
        label = html.unescape(f"{title} - {artist}".strip(" -")) or query
        logger.info("saavn: matched %r -> %s", query, label)
        return stream, label, _duration_of(more, song)

    return None


async def search_jiosaavn_candidates(query: str, limit: int = 4) -> list[tuple[str, str]]:
    """Return up to `limit` (stream_url, "Title - Artist") JioSaavn matches
    so the resolver can score them against the query and beat covers. Empty
    list on failure. Same decrypt/quality logic as search_jiosaavn."""
    import html
    url = _SEARCH_URL.format(q=urllib.parse.quote(query))
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
            async with s.get(url, headers=_HEADERS) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json(content_type=None)
    except Exception as exc:
        logger.info("saavn: candidates search failed for %r: %s", query, exc)
        return []

    out: list[tuple[str, str]] = []
    for song in (data.get("results") or []):
        more = song.get("more_info") or {}
        enc = more.get("encrypted_media_url") or song.get("encrypted_media_url")
        if not enc:
            continue
        try:
            media = _decrypt_media_url(enc)
        except Exception:
            continue
        if not media.startswith("http"):
            continue
        has_320 = str(more.get("320kbps") or song.get("320kbps") or "").lower() == "true"
        stream = _upgrade_quality(media, has_320)
        title = song.get("title") or song.get("song") or query
        artist = (
            more.get("artistMap", {}).get("primary_artists", [{}])[0].get("name")
            if isinstance(more.get("artistMap"), dict) else None
        ) or song.get("subtitle") or ""
        out.append((stream, html.unescape(f"{title} - {artist}".strip(" -")) or query))
        if len(out) >= limit:
            break
    return out
