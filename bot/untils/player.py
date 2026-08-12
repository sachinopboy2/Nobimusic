"""yt-dlp wrapper that survives YouTube's anti-bot wall.

Strategy: instead of using a single YouTube `player_client`, try a chain of
clients in order. The newer/embed-style clients (`tv_embedded`,
`mediaconnect_frontend`) frequently slip past the "Sign in to confirm you're
not a bot" check that hits `android` and `web` from server IPs.

If COOKIES_FILE env var is set, cookies are passed in addition — which makes
every client more reliable.

Cookie-clobber defense: yt-dlp opens `cookiefile` read-write and saves
the post-request cookie jar back to disk. When Instagram soft-bans the
session, its response wipes the `sessionid` cookie, and yt-dlp persists
that empty state — so the master `instagram_cookies.txt` degrades from a
valid auth jar to junk after a single bad response. To avoid that we
hand yt-dlp a per-request *tempfile copy* of the master jar and never
let it touch the master. The tempfiles are cleaned up at process exit.
"""

import asyncio
import atexit
import logging
import os
import shutil
import tempfile

from yt_dlp import YoutubeDL
from yt_dlp.utils import ExtractorError, DownloadError

logger = logging.getLogger("WarbornMusic.player")

# Repo root (parent of the bot/ package) — used to resolve relative cookie
# paths CWD-independently.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _materialize_cookies(file_env: str, content_env: str, label: str,
                         default_name: str = "") -> str:
    """Resolve a cookies file path.

    Priority:
      1. <file_env> — an absolute path to a cookies.txt on disk.
      2. <content_env> — the RAW cookies.txt contents pasted into an env
         var. Written to a persistent temp file and its path returned.
         This is how you supply cookies on PaaS hosts (Railway, Fly, etc.)
         where you set env vars but can't upload a file.
      3. <default_name> — a cookie file committed to the repo root (e.g.
         cookies.txt). Lets "commit the file, push, redeploy" work with no
         env var at all.
    Returns "" if none are provided.
    """
    path = os.getenv(file_env, "").strip()
    if path:
        # Resolve a relative path against the repo root, not the process CWD:
        # on Railway/PaaS the CWD often isn't the repo, so a bare
        # "cookies.txt" would silently not be found and yt-dlp would run
        # cookieless → the "prove you're not a bot" wall.
        cand = path if os.path.isabs(path) else os.path.join(_ROOT, path)
        if os.path.exists(cand):
            return os.path.abspath(cand)
        # A stale/wrong path (e.g. a sandbox path copied to another host)
        # must NOT be handed to yt-dlp — it raises FileNotFoundError and
        # kills the download. Ignore it and fall through to content/default.
        logger.warning("player: %s=%r does not exist on disk — ignoring it", file_env, path)
    content = os.getenv(content_env, "")
    if content.strip():
        # Env vars often arrive with escaped newlines ("\n") instead of
        # real ones — normalize so yt-dlp gets a valid Netscape jar.
        if "\\n" in content and "\n" not in content:
            content = content.replace("\\n", "\n")
        try:
            fd, tmp = tempfile.mkstemp(suffix=".txt", prefix="cookies_env_")
            with os.fdopen(fd, "w") as fh:
                fh.write(content if content.endswith("\n") else content + "\n")
            logger.info("player: materialized %s from %s (%d bytes)", label, content_env, len(content))
            return tmp
        except OSError as exc:
            logger.warning("player: failed to write %s from %s: %s", label, content_env, exc)
    # Repo-committed default (e.g. ./cookies.txt) — resolve against the repo
    # root (not CWD) so yt-dlp finds it regardless of the process CWD.
    if default_name:
        cand = default_name if os.path.isabs(default_name) else os.path.join(_ROOT, default_name)
        if os.path.exists(cand):
            resolved = os.path.abspath(cand)
            logger.info("player: using committed %s at %s", label, resolved)
            return resolved
    return ""


COOKIES_FILE = _materialize_cookies(
    "COOKIES_FILE", "COOKIES_CONTENT", "YouTube cookies", default_name="cookies.txt"
)
INSTAGRAM_COOKIES_FILE = _materialize_cookies(
    "INSTAGRAM_COOKIES_FILE", "INSTAGRAM_COOKIES_CONTENT", "Instagram cookies",
    default_name="instagram_cookies.txt",
)

def active_youtube_cookies() -> str:
    """The YouTube cookie jar to use right now. Defers to the cookie_manager's
    rotation when it's initialized, else the statically-materialized
    COOKIES_FILE (unchanged behaviour). Lazy import avoids an import cycle."""
    try:
        from bot.utils import cookie_manager
        active = cookie_manager.active_cookie_file()
        if active:
            return active
    except Exception:
        pass
    return COOKIES_FILE


def _cookie_recover() -> bool:
    """Runtime recovery: tell the cookie_manager the active jar tripped the
    bot-wall so it rotates to an alternate. True if a different jar is now
    active (worth one retry)."""
    try:
        from bot.utils import cookie_manager
        return cookie_manager.mark_unhealthy("bot-check")
    except Exception:
        return False


def _max_cookie_rotations() -> int:
    """How many jar rotations to attempt on a bot-wall before giving up —
    enough to try EVERY configured jar once (jars-1 rotations from the jar we
    started on). 1 when the count is unknown."""
    try:
        from bot.utils import cookie_manager
        return max(1, int(cookie_manager.stats().get("jars", 1)) - 1)
    except Exception:
        return 1


_COOKIE_TEMPFILES: list[str] = []


def _cleanup_cookie_tempfiles():
    for p in _COOKIE_TEMPFILES:
        try:
            os.remove(p)
        except OSError:
            pass


atexit.register(_cleanup_cookie_tempfiles)


# yt-dlp opens `cookiefile` read-write and truncates+rewrites it on close
# (YoutubeDL.close -> save_cookies -> MozillaCookieJar.save, a non-atomic
# open('w')). Extraction/download run under asyncio.to_thread, so many /play
# resolves run as real OS threads at once. A SHARED cookie copy would let one
# instance truncate the file mid-write while another loads it, yielding
# CookieLoadError("<file> does not look like a Netscape format cookies file")
# — which is NOT a DownloadError/ExtractorError, so it gets silently swallowed
# and later misreported as a bot-wall. So every call returns its OWN fresh,
# private copy (mirrors cookies_for_url below); the committed master stays
# pristine and no two in-flight yt-dlp instances ever share a cookiefile.
def youtube_cookiefile() -> str:
    """Writable PRIVATE copy of the active YT cookie jar — a fresh tempfile on
    every call, never shared with another in-flight yt-dlp instance, and never
    the master. "" when no jar is configured."""
    master = active_youtube_cookies()
    if not master or not os.path.exists(master):
        return ""
    try:
        fd, tmp = tempfile.mkstemp(suffix=".txt", prefix="ytwork_")
        os.close(fd)
        shutil.copy2(master, tmp)
        _COOKIE_TEMPFILES.append(tmp)
        return tmp
    except OSError as exc:
        logger.warning("youtube_cookiefile: copy failed (%s) — using master", exc)
        return master


def _drop_cookie_tempfile(path) -> None:
    """Delete a per-request cookie copy right after its yt-dlp call — it's
    already been read (and rewritten) by then, so there's no reason to keep it
    until atexit. No-op for the master jar or any path we didn't create (only
    files tracked in _COOKIE_TEMPFILES are removed, so the master can never be
    deleted even when a copy failed and youtube_cookiefile fell back to it)."""
    if not path:
        return
    try:
        _COOKIE_TEMPFILES.remove(path)
    except ValueError:
        return  # not one of our tempfiles (e.g. master fallback) — leave it
    try:
        os.remove(path)
    except OSError:
        pass


def _master_cookies_for_url(url) -> str:
    if not isinstance(url, str):
        return active_youtube_cookies()
    u = url.lower()
    if ("instagram.com" in u or "instagr.am" in u) and INSTAGRAM_COOKIES_FILE:
        return INSTAGRAM_COOKIES_FILE
    return active_youtube_cookies()


def cookies_for_url(url) -> str:
    """Pick the right cookies file for a URL and return a tempfile copy
    so yt-dlp's cookie writeback can't degrade the master jar. Returns
    "" if no master is configured for this URL's host.

    Instagram and YouTube each block datacenter IPs unless requests come
    from a logged-in browser session, but they use entirely separate
    cookie jars — feeding YT cookies into IG (or vice versa) does
    nothing and risks confusing yt-dlp's extractor. Dispatch by host.
    """
    master = _master_cookies_for_url(url)
    if not master or not os.path.exists(master):
        return ""
    try:
        fd, tmp = tempfile.mkstemp(suffix=".txt", prefix="cookies_")
        os.close(fd)
        shutil.copy2(master, tmp)
        _COOKIE_TEMPFILES.append(tmp)
        return tmp
    except OSError as exc:
        logger.warning("cookies_for_url: tempfile copy of %s failed: %s — falling back to master", master, exc)
        return master


class YouTubeAuthRequiredError(Exception):
    """All extraction paths failed with the YouTube bot-check / sign-in
    page AND no cookies file is configured. Callers catch this to
    render a friendly UX message instead of a raw yt-dlp traceback.
    """

    USER_MESSAGE = (
        "🍪 YouTube is temporarily blocking requests from the server "
        "(rate-limit / bot-check). This usually clears on its own — please "
        "try again in a few minutes.\n\n"
        "<i>If it happens for every song for a long time, the cookies may need "
        "refreshing.</i>"
    )

# Outbound proxy for yt-dlp specifically. If unset, fall back to:
#   1) PROXY_URL (explicit single proxy)
#   2) the same picked-from-pool config that Telegram uses (so a single
#      pool file configures both).
def _yt_dlp_proxy() -> str:
    explicit = os.getenv("YT_DLP_PROXY", "").strip()
    if explicit:
        return explicit
    single = os.getenv("PROXY_URL", "").strip()
    if single:
        return single
    # Reuse the same config.PROXY pick — yt-dlp wants a URL string.
    try:
        from bot.config import PROXY
    except Exception:
        return ""
    if not PROXY:
        return ""
    auth = ""
    if PROXY.get("username"):
        auth = PROXY["username"]
        if PROXY.get("password"):
            auth += ":" + PROXY["password"]
        auth += "@"
    return f"{PROXY['scheme']}://{auth}{PROXY['hostname']}:{PROXY['port']}"


YT_DLP_PROXY = _yt_dlp_proxy()


def _load_proxy_pool() -> list[str]:
    """Build the proxy fallback pool.

    Sources, in order:
      1. YT_DLP_PROXY_LIST env var pointing at a file (one proxy URL per
         non-blank, non-`#` line). Lets the operator hot-swap the pool
         without restarting.
      2. YT_DLP_PROXIES env var as comma- or newline-separated URLs.
      3. The single-proxy fallbacks from _yt_dlp_proxy() (already covers
         YT_DLP_PROXY / PROXY_URL / bot.config.PROXY).

    Always returns at least one entry: "" means "direct, no proxy". The
    rotation loop in _try_extract iterates through the pool, so an empty
    pool means a single direct attempt.
    """
    pool: list[str] = []

    list_path = os.getenv("YT_DLP_PROXY_LIST", "").strip()
    if list_path and os.path.exists(list_path):
        try:
            with open(list_path) as f:
                for line in f:
                    s = line.strip()
                    if s and not s.startswith("#"):
                        pool.append(s)
        except OSError:
            pass

    raw = os.getenv("YT_DLP_PROXIES", "")
    if raw:
        for part in raw.replace("\n", ",").split(","):
            s = part.strip()
            if s and s not in pool:
                pool.append(s)

    if YT_DLP_PROXY and YT_DLP_PROXY not in pool:
        pool.append(YT_DLP_PROXY)

    # Always keep a direct (no-proxy) attempt as the FINAL fallback so a dead or
    # unreachable proxy can never fully brick playback — the bot degrades to its
    # previous direct behaviour instead of failing every request. Opt out with
    # YT_DLP_PROXY_STRICT=1 (e.g. when the proxy is mandatory for geo reasons).
    strict = os.getenv("YT_DLP_PROXY_STRICT", "").strip().lower() in ("1", "true", "yes")
    if pool and "" not in pool and not strict:
        pool.append("")

    return pool or [""]


_PROXY_POOL: list[str] = _load_proxy_pool()
_active_proxy_idx: int = 0

# Per-proxy consecutive-fail counter. When a proxy hits the threshold,
# it's evicted from the pool and won't be retried until process restart.
# Direct ("") is never evicted — it's the fallback floor.
_PROXY_FAIL_COUNT: dict[str, int] = {}
_PROXY_FAIL_THRESHOLD = 3


def current_proxy() -> str:
    return _PROXY_POOL[_active_proxy_idx % len(_PROXY_POOL)]


def rotate_proxy() -> str:
    """Advance the active proxy to the next slot. Returns the new active."""
    global _active_proxy_idx
    _active_proxy_idx = (_active_proxy_idx + 1) % len(_PROXY_POOL)
    return current_proxy()


def proxy_pool_size() -> int:
    return len(_PROXY_POOL)


def mark_proxy_ok(proxy: str) -> None:
    """Reset the fail counter for `proxy` on a successful attempt."""
    _PROXY_FAIL_COUNT.pop(proxy, None)


def mark_proxy_failed(proxy: str) -> None:
    """Increment the proxy's fail counter. Evict from the pool when the
    counter reaches `_PROXY_FAIL_THRESHOLD`. Direct connection ("") is
    never evicted. Logs the eviction so the operator can see why the
    pool is shrinking.
    """
    global _active_proxy_idx
    if not proxy:
        return
    _PROXY_FAIL_COUNT[proxy] = _PROXY_FAIL_COUNT.get(proxy, 0) + 1
    if _PROXY_FAIL_COUNT[proxy] < _PROXY_FAIL_THRESHOLD:
        return
    if proxy not in _PROXY_POOL:
        return
    # Keep at least one entry; if this is the last live proxy, replace
    # the pool with [""] so the bot falls back to direct.
    if len(_PROXY_POOL) <= 1:
        logger.warning(
            "proxy pool exhausted: last proxy %s evicted, falling back to direct",
            proxy,
        )
        _PROXY_POOL.clear()
        _PROXY_POOL.append("")
        _active_proxy_idx = 0
        _PROXY_FAIL_COUNT.pop(proxy, None)
        return
    idx = _PROXY_POOL.index(proxy)
    _PROXY_POOL.pop(idx)
    _PROXY_FAIL_COUNT.pop(proxy, None)
    if _active_proxy_idx >= len(_PROXY_POOL):
        _active_proxy_idx = 0
    logger.warning(
        "evicted dead proxy %s after %d consecutive failures; pool size now %d",
        proxy, _PROXY_FAIL_THRESHOLD, len(_PROXY_POOL),
    )

# Order matters — fastest / most reliable first. As of yt-dlp 2026.x:
# - `web` is the only client that fully honours cookies AND can solve the
#   n-challenge (with deno + ejs:github components downloaded).
# - `mweb` is a lighter web variant, also cookie-aware.
# - `tv` is the new name for the old tv_embedded client.
# - `android` and `ios` are kept as bot-wall fallbacks but they silently
#   drop cookies, so they only work for videos not gated by the wall.
# Older client names (tv_embedded, mediaconnect_frontend) were removed
# and yt-dlp prints "Skipping unsupported client" for them.
# Ordered by datacenter-IP bot-wall resilience: `tv` and `web_safari` get past
# YouTube's bot-check from server IPs without a PO token, so they lead; `web`
# and `mweb` now require a PO token and trip the bot-wall most readily, so they
# are last-resort. _extract_pass returns on the first client that yields a
# stream, so leading with the resilient ones cuts wasted bot-walled attempts.
PLAYER_CLIENTS = [
    "tv",
    "web_safari",
    "android",
    "ios",
    "mweb",
    "web",
]

# Optional Proof-of-Origin tokens (comma-separated "client.context+token"
# entries, e.g. "web.gvs+XXform...,web.player+YYform..."). When set, they let
# the PO-token-gated clients (web/mweb) get past the bot-check from a datacenter
# IP. Opt-in — no effect when unset. Tokens expire; refresh from a browser.
_PO_TOKENS = [t.strip() for t in os.getenv("YT_PO_TOKEN", "").split(",") if t.strip()]


def _is_youtube_url(url: str) -> bool:
    """The SOCKS5 proxy pool is YouTube-only.

    Instagram / Pinterest / etc. work fine from the bot's direct IP but
    get rate-limited or blocked when routed through a shared free
    proxy whose IP other scrapers have already burned. So apply the
    proxy and the YT-specific multi-pass logic only to YouTube URLs.
    """
    if not isinstance(url, str):
        return False
    u = url.lower()
    return "youtube.com" in u or "youtu.be" in u


def _opts_for(client: str, extra=None, *, video: bool = False, use_cookies: bool = True, use_proxy: bool = True, cookies_path: str | None = None) -> dict:
    # Prefer a progressive (combined a+v) ≤720 format; fall back to merging
    # separate video+audio streams. Pinterest now serves split HLS pins
    # (video-only + audio-only tracks), for which a bare `best` matches
    # nothing and yt-dlp raises "Requested format is not available".
    fmt = (
        "best[height<=720]/bestvideo[height<=720]+bestaudio/bestvideo+bestaudio/best"
        if video else "bestaudio/best"
    )
    opts = {
        "format": fmt,
        "quiet": True,
        "noplaylist": True,
        "no_warnings": True,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "remote_components": ["ejs:github"],
    }
    yt_args = {}
    if client != "default":
        yt_args["player_client"] = [client]
    if _PO_TOKENS:
        yt_args["po_token"] = _PO_TOKENS
    if yt_args:
        opts["extractor_args"] = {"youtube": yt_args}
    if use_cookies:
        # Feed yt-dlp a writable working COPY for YouTube (never the master),
        # so its cookie writeback can't degrade the committed jar.
        ck = cookies_path if cookies_path is not None else youtube_cookiefile()
        if ck:
            opts["cookiefile"] = ck
    if use_proxy:
        proxy = current_proxy()
        if proxy:
            opts["proxy"] = proxy
            # Fail fast on a dead/hanging proxy so the pool rotates + evicts
            # quickly and reaches the direct fallback well before any playback
            # timeout (a stuck proxy is what caused the earlier TimeoutError).
            opts["socket_timeout"] = 12
    if extra:
        opts.update(extra)
    return opts


def _is_bot_check(text: str) -> bool:
    return any(m in text for m in ("sign in", "not a bot", "confirm you"))


def _has_real_media(info, *, video: bool) -> bool:
    """True if info contains at least one usable audio/video format.

    YouTube on AWS-IP cookied sessions sometimes returns only image
    storyboards (mhtml) — no error, just unusable info. Detect that
    explicitly so callers can retry through a different path.
    """
    if not isinstance(info, dict):
        return False
    if isinstance(info.get("url"), str) and info["url"].startswith("http"):
        return True
    for f in info.get("formats") or []:
        if not isinstance(f, dict):
            continue
        if f.get("protocol") == "mhtml" or f.get("ext") == "mhtml":
            continue
        if video:
            if f.get("vcodec") not in (None, "none"):
                return True
        else:
            if f.get("acodec") not in (None, "none"):
                return True
    return False


def _extract_pass(url_or_query, extra, *, video, use_cookies, use_proxy=True, cookies_path=None):
    """One iteration over PLAYER_CLIENTS with a fixed cookie policy.

    Returns (info_dict_or_None, last_exc, bot_check_count).
    """
    last_exc: Exception | None = None
    bot_check_count = 0
    for client in ("default", *PLAYER_CLIENTS):
        opts = _opts_for(client, extra, video=video, use_cookies=use_cookies, use_proxy=use_proxy, cookies_path=cookies_path)
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url_or_query, download=False)
            if info and _has_real_media(info, video=video):
                return info, last_exc, bot_check_count
            # No-error but storyboard-only: treat as retryable.
            continue
        except (ExtractorError, DownloadError) as exc:
            text = str(exc).lower()
            last_exc = exc
            if _is_bot_check(text):
                bot_check_count += 1
                continue
            if any(
                m in text for m in
                ("format is not available", "no video formats", "no formats", "could not find",
                 # Web/datacenter clients falsely report DRM/SABR-only formats;
                 # the tv/android/ios clients serve real ones. Retry, don't abort.
                 "drm protected", "drm-protected")
            ):
                continue
            raise
        except Exception as exc:
            last_exc = exc
            continue
        finally:
            _drop_cookie_tempfile(opts.get("cookiefile"))
    return None, last_exc, bot_check_count


def _try_extract(url_or_query: str, extra: dict | None = None, *, video: bool = False, _rotations: int = 0) -> dict | None:
    """Two-pass extract (anon → cookied) with proxy rotation for YouTube.

    Non-YouTube URLs (Instagram, Pinterest, SoundCloud, etc.) go direct
    — no proxy, no cookies, single pass. Free shared SOCKS5 IPs are
    rate-limited or blocklisted by those services, and the YT-specific
    fallbacks waste latency for no benefit.
    """
    is_yt = _is_youtube_url(url_or_query)

    if not is_yt:
        # Non-YouTube: direct, no proxy, no rotation, but per-host
        # cookies if configured (e.g. INSTAGRAM_COOKIES_FILE for IG).
        ig_cookies = cookies_for_url(url_or_query)
        info, last_exc, _ = _extract_pass(
            url_or_query, extra, video=video,
            use_cookies=bool(ig_cookies), use_proxy=False, cookies_path=ig_cookies or None,
        )
        if info is not None:
            return info
        if last_exc:
            raise last_exc
        return None

    last_exc: Exception | None = None
    bot_no_cookies = 0
    bot_with_cookies = 0
    pool_size = max(1, proxy_pool_size())
    attempt = 0

    # while (not range) so eviction-driven pool shrinkage actually cuts
    # the remaining iterations instead of re-trying the same proxy.
    # Pass order: when cookies exist, try the COOKIED pass FIRST. From a
    # datacenter IP the anon pass almost always fails the bot-wall across all
    # player clients (~6 slow extractions wasted) before cookies would have
    # succeeded on the first client — cookied-first cuts that latency. Anon
    # stays as a fallback (e.g. if cookies expire). No cookies → anon only,
    # exactly as before.
    use_cookie_order = [True, False] if active_youtube_cookies() else [False]

    while attempt < pool_size:
        attempt += 1
        attempt_proxy = current_proxy()
        got = None
        for use_ck in use_cookie_order:
            info, exc, b = _extract_pass(
                url_or_query, extra, video=video, use_cookies=use_ck, use_proxy=True,
            )
            if info is not None:
                got = info
                break
            if exc:
                last_exc = exc
            if use_ck:
                bot_with_cookies = max(bot_with_cookies, b)
            else:
                bot_no_cookies = max(bot_no_cookies, b)
        if got is not None:
            mark_proxy_ok(attempt_proxy)
            return got

        # Every pass through this proxy returned nothing usable — count it as
        # a fail for eviction purposes.
        mark_proxy_failed(attempt_proxy)
        if proxy_pool_size() > 1:
            rotate_proxy()
        pool_size = min(pool_size, max(1, proxy_pool_size()))  # shrink with evictions

    if (bot_no_cookies or bot_with_cookies) and (not active_youtube_cookies() or bot_with_cookies):
        # Runtime recovery: the active jar hit the bot-wall. Rotate to another
        # healthy jar and retry the whole extract — walking through EVERY jar
        # (once each) until one gets past the wall, before giving up.
        if _rotations < _max_cookie_rotations() and _cookie_recover():
            logger.warning("player: bot-wall with cookies — rotated jar, retry %d", _rotations + 1)
            return _try_extract(url_or_query, extra, video=video, _rotations=_rotations + 1)
        raise YouTubeAuthRequiredError(
            "Every proxy / player client hit the YouTube bot-check or returned no playable formats."
        ) from last_exc
    if last_exc:
        raise last_exc
    return None


def _ytdlp_search(query: str, limit: int = 5) -> list[tuple[str, str]]:
    """yt-dlp `ytsearch` fallback (WITH cookies + proxy) for when py_yt's
    InnerTube search returns nothing from a datacenter IP. Keeps YouTube as the
    first source instead of dropping straight to JioSaavn. Returns
    [(watch_url, title), ...]; [] on failure. Sync — call via asyncio.to_thread."""
    opts = _opts_for("default", {"extract_flat": True, "noplaylist": False,
                                 "skip_download": True})
    out: list[tuple[str, str]] = []
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        for e in (info or {}).get("entries") or []:
            if not isinstance(e, dict):
                continue
            vid = e.get("id")
            url = e.get("url") or e.get("webpage_url")
            if vid:
                url = f"https://www.youtube.com/watch?v={vid}"
            if url:
                out.append((url, e.get("title") or ""))
    except Exception as exc:
        logger.info("player: yt-dlp ytsearch fallback failed for %r: %s", query, exc)
    finally:
        _drop_cookie_tempfile(opts.get("cookiefile"))
    return out


async def search_youtube(query, limit: int = 5):
    """Return up to `limit` candidate YouTube watch URLs.

    Uses py_yt's InnerTube search (VideosSearch) rather than yt-dlp's
    `ytsearch`. yt-dlp's search endpoint returns ZERO results from many
    datacenter IPs (the same class of block that affects downloads),
    which surfaced to users as "song not found". The InnerTube search
    still answers from those IPs, so text queries resolve reliably.

    Async so it runs on the bot's live event loop — py_yt opens a fresh
    aiohttp session per call, so awaiting directly avoids the loop churn
    an asyncio.run-in-a-thread would cause. Returns a list of watch URLs,
    or None if nothing matched. A query already a YouTube URL is returned
    as-is.
    """
    if _is_youtube_url(query):
        return [query]

    try:
        from py_yt import VideosSearch
        res = await VideosSearch(query, limit=limit).next()
        results = (res or {}).get("result") or []
    except Exception as exc:
        logger.warning("search_youtube: py_yt search failed for %r: %s", query, exc)
        results = []

    urls = []
    for data in results[:limit]:
        link = data.get("link") or (
            f"https://www.youtube.com/watch?v={data['id']}" if data.get("id") else None
        )
        if link:
            urls.append(link)
    if not urls:
        # InnerTube gave nothing (often a datacenter block) — try yt-dlp's own
        # cookie-backed ytsearch so YouTube is still attempted before JioSaavn.
        urls = [u for u, _ in await asyncio.to_thread(_ytdlp_search, query, limit)]
    return urls if urls else None


async def search_youtube_detailed(query, limit: int = 5):
    """Like search_youtube but returns [(watch_url, title), ...] so callers
    can score the result title against the query (used to beat cover /
    karaoke mismatches). Empty list on failure. A YouTube URL is returned
    as-is with an empty title."""
    if _is_youtube_url(query):
        return [(query, "")]
    try:
        from py_yt import VideosSearch
        res = await VideosSearch(query, limit=limit).next()
        results = (res or {}).get("result") or []
    except Exception as exc:
        logger.warning("search_youtube_detailed: failed for %r: %s", query, exc)
        results = []
    out = []
    for data in results[:limit]:
        link = data.get("link") or (
            f"https://www.youtube.com/watch?v={data['id']}" if data.get("id") else None
        )
        if link:
            out.append((link, data.get("title") or ""))
    if not out:
        out = await asyncio.to_thread(_ytdlp_search, query, limit)
    return out


# Live VC streaming needs ONE progressive (muxed audio+video) URL: py-tgcalls
# plays a single URL, so a bestvideo+bestaudio *merge* — which yt-dlp returns
# as two separate URLs with no top-level `url` — can't be streamed and leaves
# the video blank (the /vplay "assistant joins but video won't play" bug).
# Force a single-file format that carries both streams (itag 22/18 on YouTube).
_STREAM_VIDEO_FMT = (
    "best[height<=720][vcodec!=none][acodec!=none]/"
    "best[vcodec!=none][acodec!=none]/"
    "best[height<=720]/best"
)


def _extract_stream(url: str, *, video: bool) -> str | None:
    extra = {"format": _STREAM_VIDEO_FMT} if video else None
    info = _try_extract(url, extra, video=video)
    if not isinstance(info, dict):
        return None
    stream = info.get("url")
    if stream:
        return stream
    # No single muxed URL — pick the best format that has BOTH codecs rather
    # than blindly taking the last (often a video-only or audio-only split).
    formats = info.get("formats") or []
    progressive = [
        f for f in formats
        if isinstance(f, dict) and f.get("url")
        and f.get("vcodec") not in (None, "none")
        and f.get("acodec") not in (None, "none")
    ]
    if progressive:
        return progressive[-1]["url"]
    return formats[-1]["url"] if formats else None


def get_audio_stream(url):
    return _extract_stream(url, video=False)


def get_video_stream(url):
    return _extract_stream(url, video=True)


def _extract_stream_meta(url: str, *, video: bool) -> tuple[str | None, str | None, int | None]:
    """Like _extract_stream but also returns (title, duration_seconds) from
    the SAME extraction — no extra network round-trip. Used so the Now Playing
    card shows the real track title + length instead of the user's raw query."""
    extra = {"format": _STREAM_VIDEO_FMT} if video else None
    info = _try_extract(url, extra, video=video)
    if not isinstance(info, dict):
        return None, None, None
    stream = info.get("url")
    if not stream:
        formats = info.get("formats") or []
        progressive = [
            f for f in formats
            if isinstance(f, dict) and f.get("url")
            and f.get("vcodec") not in (None, "none")
            and f.get("acodec") not in (None, "none")
        ]
        stream = progressive[-1]["url"] if progressive else (formats[-1]["url"] if formats else None)
    dur = info.get("duration")
    dur = int(dur) if isinstance(dur, (int, float)) and dur > 0 else None
    return stream, info.get("title"), dur


def get_audio_meta(url):
    return _extract_stream_meta(url, video=False)


def get_video_meta(url):
    return _extract_stream_meta(url, video=True)


def get_title(url: str) -> str | None:
    """Best-effort fetch of the human-readable title for a URL.

    Used to render `/queue` lines. Falls back to None on any error so callers
    can substitute the raw query.
    """
    try:
        info = _try_extract(url)
    except Exception:
        return None
    if isinstance(info, dict):
        return info.get("title")
    return None
