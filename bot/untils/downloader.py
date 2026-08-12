"""yt-dlp download wrappers for /song and /video.

Distinct from bot/utils/player.py — that module extracts streaming URLs
for py-tgcalls. This one writes a file to disk that the bot can upload
to Telegram via send_audio / send_video.

Reuses player.PLAYER_CLIENTS so the same anti-bot-wall fallback chain
applies. Audio downloads are post-processed to mp3@192k via ffmpeg
(installed by scripts/install.sh).

Caller is responsible for deleting the returned file. The download dir
sits under /tmp so a reboot reaps any leaks.
"""

from __future__ import annotations

import logging
import os

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError

from bot.utils.player import (
    PLAYER_CLIENTS,
    _PO_TOKENS,
    _cookie_recover,
    _is_bot_check,
    _is_youtube_url,
    _max_cookie_rotations,
    _drop_cookie_tempfile,
    active_youtube_cookies,
    cookies_for_url,
    youtube_cookiefile,
    current_proxy,
    mark_proxy_failed,
    mark_proxy_ok,
    proxy_pool_size,
    rotate_proxy,
)

logger = logging.getLogger("WarbornMusic.downloader")

DOWNLOAD_DIR = "/tmp/warborn_downloads"

# Hard duration cap so a user can't accidentally `/song <2-hour podcast>`
# and fill the VPS disk + wait forever for upload. 20 minutes covers any
# reasonable song or short video.
MAX_DURATION_SECONDS = 20 * 60

# Telegram's hard upload limit for bots over Pyrogram (MTProto) is 2 GB,
# but huge files take long enough that the userbot can hit a flood wait.
# Cap at 1.5 GB and refuse upfront.
MAX_FILE_BYTES = 1_500_000_000

_RETRY_MARKERS = (
    "format is not available",
    "no video formats",
    "no formats",
    "sign in",
    "not a bot",
    "could not find",
    # YouTube's default (web) client increasingly returns DRM/SABR-only
    # formats for videos that are NOT actually DRM; the android/ios/tv
    # clients still serve plain formats. Treat DRM as retryable so the
    # client fallback chain gets a chance instead of failing immediately.
    "drm protected",
    "drm-protected",
)


def _opts(client: str, *, video: bool, quality: str | None = None, use_cookies: bool = True, use_proxy: bool = True, cookies_path: str | None = None) -> dict:
    outtmpl = os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s")
    postprocessors: list[dict] = []
    merge_to_mp4 = False
    if video:
        # quality: "480" | "720" | "1080" | None (=> 720 default).
        # Modern YouTube splits >=720p into video-only + audio-only streams,
        # so a single muxed-mp4 selector would fail with "format not
        # available". Try muxed first (cheap, no ffmpeg work), then fall
        # through to bestvideo+bestaudio (yt-dlp will merge via ffmpeg).
        try:
            cap = int(quality) if quality else 720
        except (TypeError, ValueError):
            cap = 720
        fmt = (
            # Full quality FIRST: merge the best video+audio at the cap.
            # yt-dlp auto-skips DRM formats, and the android/ios/tv clients
            # (tried before web) return NON-DRM high-res streams, so this
            # gives original quality where it's available.
            f"bestvideo[height<={cap}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={cap}]+bestaudio/"
            # Progressive (single-file itag 22/18, always non-DRM) as a
            # safety net — used only when no non-DRM split stream exists,
            # so a datacenter-DRM video still downloads (at <=720p) instead
            # of failing with a DRM error.
            f"best[height<={cap}][vcodec!=none][acodec!=none]/"
            f"best[height<={cap}][ext=mp4]/"
            f"best[height<={cap}]/"
            # Pinterest serves HLS split video+audio with no muxed format
            # and weird heights (vertical); final fallback ignores the cap.
            f"bestvideo+bestaudio/best"
        )
        merge_to_mp4 = True
    else:
        fmt = "bestaudio/best"
        postprocessors = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]

    opts: dict = {
        "format": fmt,
        "outtmpl": outtmpl,
        "quiet": True,
        "noplaylist": True,
        "no_warnings": True,
        "remote_components": ["ejs:github"],
    }
    # client="default" → let yt-dlp pick its multi-client default (gives
    # access to split-stream formats up to 4K). Explicit names lock to a
    # single client (used as fallbacks for the bot-wall path).
    yt_args = {}
    if client != "default":
        yt_args["player_client"] = [client]
    if _PO_TOKENS:
        yt_args["po_token"] = _PO_TOKENS
    if yt_args:
        opts["extractor_args"] = {"youtube": yt_args}
    if merge_to_mp4:
        opts["merge_output_format"] = "mp4"
    if postprocessors:
        opts["postprocessors"] = postprocessors
    if use_cookies:
        # Writable working COPY for YouTube (never the master jar) — see player.
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
    return opts


def _final_path(info: dict, *, video: bool) -> str | None:
    """Find the on-disk path after yt-dlp finishes (including post-process)."""
    requested = info.get("requested_downloads") or []
    if requested:
        cand = requested[-1].get("filepath") or requested[-1].get("_filename")
        if cand and os.path.exists(cand):
            return cand

    vid_id = info.get("id")
    if vid_id and os.path.isdir(DOWNLOAD_DIR):
        # Postprocessor renames the extension; search by id prefix.
        good_exts_video = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".ts")
        good_exts_audio = (".mp3",)
        for fn in sorted(os.listdir(DOWNLOAD_DIR), key=len, reverse=True):
            if not fn.startswith(vid_id + "."):
                continue
            full = os.path.join(DOWNLOAD_DIR, fn)
            if video and fn.endswith(good_exts_video):
                return full
            if not video and fn.endswith(good_exts_audio):
                return full
    return None


# Wall-resistant client order for DOWNLOADS. YouTube serves the web/mweb
# clients storyboard-only from datacenter IPs (Railway etc.); the InnerTube
# app clients (android/ios/tv) return real formats far more often. Try those
# FIRST so a download isn't wasted on the walled web client, then fall back.
_DL_CLIENTS = ("tv", "web_safari", "android", "ios", "default", "mweb", "web")


def _download_pass(url, *, video, quality, use_cookies, use_proxy=True, cookies_path=None) -> tuple[str | None, dict | None, Exception | None]:
    last_exc: Exception | None = None
    # De-dupe while preserving the wall-resistant order, keeping any extra
    # clients configured in PLAYER_CLIENTS as later fallbacks.
    seen = set()
    clients = [c for c in (*_DL_CLIENTS, *PLAYER_CLIENTS) if not (c in seen or seen.add(c))]
    for client in clients:
        opts = _opts(client, video=video, quality=quality, use_cookies=use_cookies, use_proxy=use_proxy, cookies_path=cookies_path)
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except (ExtractorError, DownloadError) as exc:
            last_exc = exc
            if any(marker in str(exc).lower() for marker in _RETRY_MARKERS):
                continue
            raise
        except Exception as exc:
            last_exc = exc
            continue
        finally:
            _drop_cookie_tempfile(opts.get("cookiefile"))
        if not isinstance(info, dict):
            continue
        path = _final_path(info, video=video)
        if path:
            return path, info, None
    return None, None, last_exc


def _try_download(url: str, *, video: bool, quality: str | None = None, _rotations: int = 0) -> tuple[str, dict]:
    """Anon → cookied passes, proxy-rotated, but only for YouTube.

    Non-YT URLs go direct, single pass, no cookies — see
    player._try_extract for the rationale.
    """
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    is_yt = _is_youtube_url(url)

    if not is_yt:
        ig_cookies = cookies_for_url(url)
        path, info, last_exc = _download_pass(
            url, video=video, quality=quality,
            use_cookies=bool(ig_cookies), use_proxy=False, cookies_path=ig_cookies or None,
        )
        if path and info is not None:
            return path, info
        if last_exc:
            raise last_exc
        raise RuntimeError("yt-dlp returned no usable file")

    last_exc: Exception | None = None
    pool_size = max(1, proxy_pool_size())
    attempt = 0

    # while (not range) so eviction-driven pool shrinkage actually cuts
    # the remaining iterations instead of re-trying the same proxy.
    while attempt < pool_size:
        attempt += 1
        attempt_proxy = current_proxy()
        path, info, exc1 = _download_pass(
            url, video=video, quality=quality, use_cookies=False, use_proxy=True,
        )
        if path and info is not None:
            mark_proxy_ok(attempt_proxy)
            return path, info
        if exc1:
            last_exc = exc1

        if active_youtube_cookies():
            path2, info2, exc2 = _download_pass(
                url, video=video, quality=quality, use_cookies=True, use_proxy=True,
            )
            if path2 and info2 is not None:
                mark_proxy_ok(attempt_proxy)
                return path2, info2
            if exc2:
                last_exc = exc2

        mark_proxy_failed(attempt_proxy)
        if proxy_pool_size() > 1:
            rotate_proxy()
        pool_size = min(pool_size, max(1, proxy_pool_size()))  # shrink with evictions

    # Runtime recovery (mirrors player._try_extract): if every proxy hit the
    # YouTube bot-wall and another cookie jar is available, rotate to it and
    # retry the whole download — walking every jar once before giving up.
    if (last_exc and active_youtube_cookies() and _is_bot_check(str(last_exc).lower())
            and _rotations < _max_cookie_rotations() and _cookie_recover()):
        logger.warning("downloader: bot-wall — rotated cookie jar, retry %d", _rotations + 1)
        return _try_download(url, video=video, quality=quality, _rotations=_rotations + 1)

    if last_exc:
        raise last_exc
    raise RuntimeError("yt-dlp returned no usable file")


def check_size_and_duration(info: dict) -> str | None:
    """Reject upfront based on probe metadata. Returns an error or None.

    Called with the lightweight info dict from `bot.utils.player._try_extract`
    (no download). Catches the obvious "this would never upload" cases
    before we burn bandwidth.
    """
    if not isinstance(info, dict):
        return None
    duration = info.get("duration")
    if isinstance(duration, (int, float)) and duration > MAX_DURATION_SECONDS:
        mins = int(duration // 60)
        return (
            f"That's {mins} min long — /song and /video are capped at "
            f"{MAX_DURATION_SECONDS // 60} minutes."
        )
    filesize = info.get("filesize") or info.get("filesize_approx")
    if isinstance(filesize, (int, float)) and filesize > MAX_FILE_BYTES:
        mb = int(filesize / 1_000_000)
        return f"That file is ~{mb} MB — over the 1500 MB upload cap."
    return None


def download_audio(url: str) -> tuple[str, dict]:
    return _try_download(url, video=False)


def download_video(url: str, quality: str | None = None) -> tuple[str, dict]:
    return _try_download(url, video=True, quality=quality)
