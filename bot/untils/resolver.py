"""Single entry point that turns any user input (plain text, YouTube link,
Spotify link, Resso link, SoundCloud link) into a stream URL that the player
can hand to PyTgCalls.

Resolution rules:
- YouTube URL          -> return as-is, yt-dlp will handle it
- SoundCloud URL       -> return as-is, yt-dlp handles SoundCloud natively
- Spotify track URL    -> read "Artist - Title" from Spotify API, YouTube-search it
- Resso song URL       -> scrape "Artist - Title" from the share page, YouTube-search it
- Anything else (text) -> treat as a YouTube text search

Returns (audio_stream_url, display_query) on success, (None, error_message)
on failure. All known failure modes are caught so the caller can always
edit_text the status message instead of leaving it hanging.
"""

import asyncio
import logging
import os
import re
import time

import aiohttp

from bot.utils.player import (
    YouTubeAuthRequiredError,
    get_audio_meta,
    get_audio_stream,
    get_video_meta,
    get_video_stream,
    search_youtube,
    search_youtube_detailed,
)
from bot.utils.resso import is_resso_url, resolve_resso
from bot.utils.spotify import is_spotify_url, resolve_spotify

logger = logging.getLogger("WarbornMusic.resolver")

_YT_RE = re.compile(r"(?:youtube\.com|youtu\.be|music\.youtube\.com)", re.IGNORECASE)
_SC_RE = re.compile(r"(?:soundcloud\.com|snd\.sc)", re.IGNORECASE)

# YouTube is the source of truth for song selection. By default the audio path
# is YouTube-only (media-API fetch of the YouTube-chosen video → yt-dlp of the
# same video): it plays the CORRECT track or reports why it couldn't. The
# JioSaavn fallback is what previously substituted a wrong-language/cover track
# when the API was unavailable, so it's OFF unless explicitly re-enabled.
_ALLOW_JIOSAAVN = os.getenv("ALLOW_JIOSAAVN_FALLBACK", "").strip().lower() in (
    "1", "true", "yes", "on",
)

_QUOTA_MSG = (
    "🚫 YouTube found the track, but the download API's daily limit is used up "
    "(it resets at midnight). It can't fetch the audio right now — please try "
    "again later."
)


def _humanize_ytdlp_error(exc: Exception) -> str:
    # The player layer already builds a polished message for the
    # cookies-required case — use it verbatim rather than re-deriving
    # from the string. Must come BEFORE the string-matching branches.
    if isinstance(exc, YouTubeAuthRequiredError):
        return YouTubeAuthRequiredError.USER_MESSAGE
    text = str(exc).lower()
    if "sign in to confirm" in text or "not a bot" in text:
        # If cookies ARE configured (the usual case here), this is YouTube
        # rate-limiting the server IP, not a missing-cookies problem — don't
        # tell the operator to add cookies they already have.
        try:
            from bot.utils import player
            has_cookies = bool(player.active_youtube_cookies())
        except Exception:
            has_cookies = False
        if has_cookies:
            return (
                "🍪 YouTube is rate-limiting this server and demanding a bot-check "
                "even with cookies configured. It usually clears on its own — "
                "please try again in a minute or two. If it keeps happening for "
                "every video, the cookies may need refreshing."
            )
        return (
            "YouTube is asking yt-dlp to prove it's not a bot. Add a Netscape "
            "`cookies.txt` from a logged-in YouTube account and set "
            "`COOKIES_FILE=/absolute/path/cookies.txt` in `.env`, then restart."
        )
    if "drm protected" in text or "drm-protected" in text:
        return (
            "🔒 That video is DRM-protected — YouTube encrypts it, so it "
            "can't be downloaded or streamed by any yt-dlp bot. Try a "
            "different (non-DRM) video."
        )
    if "video unavailable" in text or "private video" in text:
        return "That video is unavailable or private."
    if "age-restricted" in text or "age restricted" in text:
        return "That video is age-restricted. Cookies from a verified account fix this."
    if "no video found" in text or "unable to extract" in text:
        return "yt-dlp couldn't extract that source. It may have been removed or moved."
    return f"yt-dlp error: {exc}"


# Short-lived cache of resolved results (search + extraction + metadata) so a
# repeated song starts almost instantly. Stream URLs stay valid far longer than
# this TTL, so a cache hit is safe to replay.
_RESOLVE_CACHE: dict[tuple[str, bool], tuple[float, tuple]] = {}
_RESOLVE_TTL = 300.0


async def resolve(query: str, *, video: bool = False) -> tuple[str | None, str, int | None]:
    """Cached front for _resolve_impl: a repeat of the same query within the
    TTL skips the search + yt-dlp extraction entirely."""
    key = (query.strip().lower(), video)
    now = time.monotonic()
    hit = _RESOLVE_CACHE.get(key)
    if hit and hit[0] > now:
        return hit[1]
    result = await _resolve_impl(query, video=video)
    # Cache successful resolutions — but never a local file path (a downloaded
    # temp file may be reaped before the TTL; only remote stream URLs are safe
    # to replay).
    if result and result[0] and str(result[0]).startswith(("http://", "https://")):
        _RESOLVE_CACHE[key] = (now + _RESOLVE_TTL, result)
        if len(_RESOLVE_CACHE) > 256:
            for k in [k for k, v in _RESOLVE_CACHE.items() if v[0] <= now]:
                _RESOLVE_CACHE.pop(k, None)
    return result


async def _resolve_impl(query: str, *, video: bool = False) -> tuple[str | None, str, int | None]:
    """Returns (stream_url, title, duration_seconds). title is the real
    resolved track title (not the raw query); duration may be None."""
    query = query.strip()
    meta_extractor = get_video_meta if video else get_audio_meta

    # Direct YouTube / SoundCloud link.
    if _YT_RE.search(query) or _SC_RE.search(query):
        # AUDIO: fetch the exact linked track via the configured media API
        # (/download?url=…) — it returns a directly-streamable URL, so this
        # server needs no YouTube cookies/proxy. yt-dlp is only the fallback
        # when the API is unavailable/rate-limited.
        if not video:
            path, og_title, og_dur = await _api_fetch(query)
            if path:
                return path, og_title or query, og_dur
        try:
            stream, title, duration = await asyncio.to_thread(meta_extractor, query)
        except Exception as exc:
            return None, _humanize_ytdlp_error(exc), None
        if not stream:
            kind = "video" if video else "audio"
            return None, f"Couldn't extract a {kind} stream for that link.", None
        if not await _stream_alive(stream):
            local, ltitle, ldur = await _download_local(query, video=video)
            if local:
                return local, ltitle or title or query, ldur or duration
            return None, _DEAD_STREAM_MSG, None
        return stream, title or query, duration

    if is_spotify_url(query):
        try:
            meta = await resolve_spotify(query)
        except Exception as exc:
            return None, f"Spotify lookup failed: {exc}", None
        if not meta:
            return None, (
                "Spotify lookup failed. Make sure SPOTIFY_CLIENT_ID and "
                "SPOTIFY_CLIENT_SECRET are set in .env."
            ), None
        return await _via_youtube_search(meta, video=video)

    if is_resso_url(query):
        try:
            meta = await resolve_resso(query)
        except Exception as exc:
            return None, f"Resso lookup failed: {exc}", None
        if not meta:
            return None, "Couldn't read song info from that Resso link.", None
        return await _via_youtube_search(meta, video=video)

    return await _via_youtube_search(query, video=video)


_DEAD_STREAM_MSG = (
    "🍪 YouTube returned a stream but its CDN isn't delivering data to this "
    "server (IP throttling). This usually clears on its own — please try "
    "again in a minute or two."
)


async def _stream_alive(url: str) -> bool:
    """Pre-flight a googlevideo stream URL: YouTube's extractor can 'succeed'
    while the CDN stalls all data to a throttled datacenter IP — the player
    then dies with a bare TimeoutError only AFTER the resolver chain (other
    results, JioSaavn) has been skipped and the dead URL cached. A 1-byte
    ranged read with a short cap catches that here instead. Only googlevideo
    URLs are probed; other hosts (JioSaavn, SoundCloud, …) pass through."""
    if "googlevideo" not in url:
        return True
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(url, headers={"Range": "bytes=0-1023"}) as r:
                if r.status not in (200, 206):
                    logger.info("resolver: stream pre-flight HTTP %s — treating as dead", r.status)
                    return False
                chunk = await r.content.read(1)
                if not chunk:
                    logger.info("resolver: stream pre-flight returned no data — treating as dead")
                return bool(chunk)
    except Exception as exc:
        logger.info("resolver: stream pre-flight failed (%s: %s) — treating as dead",
                    type(exc).__name__, exc)
        return False


async def _download_local(url: str, *, video: bool) -> tuple[str | None, str, int | None]:
    """When a YouTube URL's direct stream won't deliver to this server IP (the
    URL is IP-locked to the proxy that extracted it, or the direct IP is
    throttled), download the media THROUGH the proxy pool — yt-dlp routes the
    media fetch via the proxy, so the bytes actually arrive — to a local file
    the player streams with no CDN fetch. Only attempted when a real proxy is
    configured (a proxy-less download would hit the same throttle). Returns
    (local_path, title, duration) or (None, "", None)."""
    try:
        from bot.utils import player, downloader
    except Exception:
        return None, "", None
    if player.proxy_pool_size() <= 1:
        return None, "", None  # only the direct fallback in the pool — no real proxy
    logger.info("resolver: direct stream dead — downloading %s via proxy pool", url[:70])
    try:
        fn = downloader.download_video if video else downloader.download_audio
        path, info = await asyncio.to_thread(fn, url)
    except Exception as exc:
        logger.info("resolver: proxy-download fallback failed for %s: %s", url[:60], exc)
        return None, "", None
    if path:
        info = info or {}
        logger.info("resolver: proxy-download produced local file for %s", url[:70])
        return path, info.get("title") or url, info.get("duration")
    return None, "", None


async def _via_youtube_search(query: str, *, video: bool = False) -> tuple[str | None, str, int | None]:
    """Resolve a text query by hitting YOUTUBE first, then fetching the chosen
    video's audio through the configured media API.

    Step 1 — YouTube InnerTube search (py_yt). This is cookieless/proxyless and
    works from datacenter IPs, and its ranking is authoritative, so it picks the
    CORRECT video (fixes the wrong-song bug where a media API's own search
    returned a different track/platform).

    Step 2 (audio) — hand that exact YouTube URL to the media API (/download):
    it returns a directly-streamable URL for that video, so this server needs no
    YouTube cookies/proxy. yt-dlp direct extraction and JioSaavn are fallbacks
    only.

    Video stays on yt-dlp (the media API is used for audio only here)."""
    meta_extractor = get_video_meta if video else get_audio_meta

    # Step 1: YouTube InnerTube search → [(watch_url, title), ...] (correct song).
    last_err: str | None = None
    try:
        yts = await search_youtube_detailed(query)
    except Exception as exc:
        last_err = _humanize_ytdlp_error(exc)
        yts = []

    # Step 2 (audio): fetch the top correct video(s) via the media API.
    if not video:
        for url, title in yts[:3]:
            path, og_title, og_dur = await _api_fetch(url)
            if path:
                return path, title or og_title or query, og_dur
        # Media API unavailable / rate-limited → direct yt-dlp extraction
        # (needs cookies/proxy — may fail on a bare datacenter IP), best-first.
        for url, title in yts[:3]:
            try:
                stream, xtitle, duration = await asyncio.to_thread(meta_extractor, url)
            except Exception as exc:
                last_err = _humanize_ytdlp_error(exc)
                continue
            if not stream:
                continue
            if await _stream_alive(stream):
                return stream, title or xtitle or query, duration
            # Direct stream won't deliver to this IP (CDN throttling / IP-lock).
            # Download it through the proxy pool and play the local file —
            # parity with the video path and the direct-YouTube-link audio path,
            # both of which already do this. Only fires when a real proxy is
            # configured; otherwise it's a no-op and we fall through as before.
            local, ltitle, ldur = await _download_local(url, video=video)
            if local:
                return local, ltitle or title or query, ldur or duration
            last_err = _DEAD_STREAM_MSG
        # Optional last resort: direct JioSaavn MP3. OFF by default — it's the
        # source of the wrong-song substitution when the API is unavailable.
        # Enable with ALLOW_JIOSAAVN_FALLBACK=1 only if a possibly-mismatched
        # track is preferable to nothing.
        if _ALLOW_JIOSAAVN:
            saavn = await _via_jiosaavn(query)
            if saavn[0]:
                return saavn
        # Nothing playable from YouTube. If the API is rate-limited, say so
        # explicitly (the track WAS found on YouTube — it just can't be fetched).
        try:
            from bot.utils import mediaapi
            if yts and mediaapi.rate_limited_recently():
                return None, _QUOTA_MSG, None
        except Exception:
            pass
        if not yts:
            return None, last_err or f"No YouTube result found for: {query}", None
        return None, last_err or f"Couldn't fetch audio for: {query}", None

    # Video: yt-dlp extraction (media API is used for audio only), best-first.
    for url, title in yts[:3]:
        try:
            stream, xtitle, duration = await asyncio.to_thread(meta_extractor, url)
        except Exception as exc:
            last_err = _humanize_ytdlp_error(exc)
            continue
        if stream:
            if not await _stream_alive(stream):
                local, ltitle, ldur = await _download_local(url, video=video)
                if local:
                    return local, ltitle or title or query, ldur or duration
                last_err = _DEAD_STREAM_MSG
                continue
            return stream, title or xtitle or query, duration

    if not yts:
        return None, last_err or f"No YouTube result found for: {query}", None
    return None, last_err or f"Couldn't extract video for: {query}", None


# Markers that indicate a NON-original rendition. If a candidate title has
# one but the user's query does not, it's penalised so the real track wins.
_COVER_MARKERS = (
    "cover", "karaoke", "tribute", "remix", "instrumental", "lofi", "lo-fi",
    "8d", "sped up", "spedup", "slowed", "reverb", "nightcore", "mashup",
    "acoustic", "made famous", "originally performed", "in the style of",
    "rendition", "live", "concert",
)


def _tokens(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


# Title noise stripped when building the reference from YouTube's top hit,
# so "Imagine Dragons - Believer (Official Video)" → {imagine,dragons,believer}.
_NOISE = {
    "official", "video", "audio", "lyric", "lyrics", "hd", "4k", "mv",
    "feat", "ft", "ost", "full", "song", "original", "version", "hq",
    "remastered", "explicit", "m", "v", "the", "a", "music", "visualizer",
    "performance", "with", "and",
}


def _ref_coverage(ref_tokens: set, query: str, title: str) -> float:
    """Fraction of the reference (real artist+song) tokens present in a
    candidate title, minus a cover/karaoke penalty the user didn't ask for."""
    if not ref_tokens:
        return 0.0
    c = len(ref_tokens & _tokens(title)) / len(ref_tokens)
    tl = (title or "").lower()
    if any(m in tl and m not in query.lower() for m in _COVER_MARKERS):
        c -= 0.6
    return c


async def _best_audio(query: str) -> tuple[str | None, str]:
    """Pick the CORRECT track across JioSaavn + YouTube.

    YouTube's #1 result is the authoritative reference for the real artist
    (its ranking knows "believer" → Imagine Dragons). A JioSaavn hit is
    preferred only when it actually matches that reference (fast, direct
    URL) — so "Believer - Aish" loses to the real "Imagine Dragons -
    Believer". Otherwise YouTube's top result is played.
    """
    from bot.utils.saavn import search_jiosaavn_candidates

    jio, yts = await asyncio.gather(
        search_jiosaavn_candidates(query),
        search_youtube_detailed(query),
        return_exceptions=True,
    )
    jio = jio if isinstance(jio, list) else []
    yts = yts if isinstance(yts, list) else []

    ref_tokens = (_tokens(yts[0][1]) - _NOISE) if yts else set()
    if not ref_tokens:
        ref_tokens = _tokens(query)

    best_jio = max(jio, key=lambda c: _ref_coverage(ref_tokens, query, c[1]),
                   default=None)
    best_jio_cov = _ref_coverage(ref_tokens, query, best_jio[1]) if best_jio else 0.0
    logger.info(
        "resolver: audio %r → ref=%s | jio_best=%r cov=%.2f | yt_top=%r",
        query, sorted(ref_tokens),
        best_jio[1] if best_jio else None, best_jio_cov,
        yts[0][1] if yts else None,
    )

    # JioSaavn wins only when it clearly matches the real track.
    if best_jio and best_jio_cov >= 0.6:
        return best_jio[0], best_jio[1]

    # Otherwise play YouTube's best (the original), extracting best-first.
    for url, title in yts[:3]:
        try:
            stream = await asyncio.to_thread(get_audio_stream, url)
        except Exception as exc:
            logger.info("resolver: yt extract failed for %r: %s", title, exc)
            continue
        if stream:
            return stream, title or query

    # Last resort: any JioSaavn hit beats silence.
    if best_jio:
        return best_jio[0], best_jio[1]
    return None, ""


def _query_matches(query: str, label: str) -> bool:
    """True if `label` (a resolved "Title - Artist") plausibly matches `query`.
    Guards the JioSaavn fallback: its Indian catalogue happily returns an
    unrelated Hindi track for a Western query, so require a real token overlap
    before accepting — otherwise it's a wrong-song hit and we'd rather report
    'not found'."""
    q = _tokens(query) - _NOISE
    if not q:
        return True  # nothing meaningful to check against — don't block
    have = _tokens(label)
    matched = len(q & have)
    # At least half of the query's meaningful tokens must appear in the result.
    return matched >= max(1, (len(q) + 1) // 2)


async def _api_fetch(track_url: str) -> tuple[str | None, str, int | None]:
    """Fetch a SPECIFIC track URL's audio via the configured media API
    (mediaapi.fetch_track → /download).

    The caller has already chosen the exact track — normally a YouTube watch URL
    picked by YouTube's own InnerTube search — so there is NO wrong-song risk
    here: the API just delivers a streamable URL for that exact video (no
    cookies/proxy on this server). Returns (stream_url, title, duration) or
    (None, "", None) on any miss (disabled, 401, rate-limited, network).
    Never raises."""
    try:
        from bot.utils import mediaapi
        if not mediaapi.enabled():
            return None, "", None
        return await mediaapi.fetch_track(track_url)
    except Exception as exc:
        logger.info("resolver: media API fetch error for %s: %s", str(track_url)[:60], exc)
        return None, "", None


async def _via_jiosaavn(query: str) -> tuple[str | None, str, int | None]:
    try:
        from bot.utils.saavn import search_jiosaavn
        hit = await search_jiosaavn(query)
    except Exception as exc:
        logger.warning("resolver: JioSaavn lookup failed for %r: %s", query, exc)
        return None, "", None
    if hit and hit[0]:
        label = hit[1] or ""
        if not _query_matches(query, label):
            logger.info("resolver: JioSaavn hit %r rejected — doesn't match query %r", label, query)
            return None, "", None
        return hit
    return None, "", None


async def resolve_url(query: str) -> tuple[str | None, str]:
    """Like `resolve` but returns a canonical webpage URL (not a streaming
    URL). Used by /song and /video, which hand the URL to yt-dlp for an
    on-disk download rather than a live stream.
    """
    query = query.strip()

    if _YT_RE.search(query) or _SC_RE.search(query):
        return query, query

    if is_spotify_url(query):
        try:
            meta = await resolve_spotify(query)
        except Exception as exc:
            return None, f"Spotify lookup failed: {exc}"
        if not meta:
            return None, (
                "Spotify lookup failed. Make sure SPOTIFY_CLIENT_ID and "
                "SPOTIFY_CLIENT_SECRET are set in .env."
            )
        return await _first_youtube_url(meta)

    if is_resso_url(query):
        try:
            meta = await resolve_resso(query)
        except Exception as exc:
            return None, f"Resso lookup failed: {exc}"
        if not meta:
            return None, "Couldn't read song info from that Resso link."
        return await _first_youtube_url(meta)

    return await _first_youtube_url(query)


async def _first_youtube_url(query: str) -> tuple[str | None, str]:
    try:
        results = await search_youtube(query)
    except Exception as exc:
        results = None
        logger.info("resolver: YouTube search errored for %r: %s", query, exc)
    if results:
        if isinstance(results, str):
            return results, query
        return results[0], query
    # No YouTube result — fall back to JioSaavn's direct URL (yt-dlp's
    # generic extractor downloads it). Keeps /song working on datacenter IPs.
    saavn = await _via_jiosaavn(query)
    if saavn[0]:
        return saavn[0], saavn[1]
    return None, f"No result found for: {query}"
