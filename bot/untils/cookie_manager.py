"""Automatic YouTube cookie management: background health monitoring +
intelligent rotation over multiple cookie jars, with an optional maximum
cookie age.

Modular and independent — the rest of the bot only touches:
  • active_cookie_file()  → which jar yt-dlp should use right now
  • mark_unhealthy()      → runtime-recovery hook (rotate on auth failure)
The periodic probe, the rotation policy and the age check all live here and
run in ONE background task started from bot.start.

Cookie SOURCE: rotation cycles through operator-supplied jars — the primary
`player.COOKIES_FILE` plus any extras found in $COOKIES_DIR (*.txt) or the
COOKIES_CONTENT_2..9 env vars. This mirrors AnonXMusic's multi-cookie folder.

Automated Google password login (Playwright/headless Chromium) is
DELIBERATELY NOT implemented: it trips Google's datacenter bot-detection
(CAPTCHA/2FA) and routinely locks the account, and can't reliably produce
cookies from a PaaS IP. Supply jars instead; this manager keeps them fresh.

Security: logs jar COUNT and status only — never contents, paths beyond
basenames, or credentials.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import threading
import time

logger = logging.getLogger("WarbornMusic.cookies")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHECK_INTERVAL_S = max(60, int(os.getenv("COOKIE_CHECK_INTERVAL_MIN", "30") or 30) * 60)
try:
    FORCE_REFRESH_HOURS = float(os.getenv("COOKIE_FORCE_REFRESH_HOURS", "0") or 0)
except ValueError:
    FORCE_REFRESH_HOURS = 0.0
COOKIES_DIR = os.getenv("COOKIES_DIR", "cookies").strip()

# A rock-stable, always-available public video used only to health-probe the
# active cookie jar (never streamed to users). Overridable via env.
_PROBE_URL = os.getenv("COOKIE_PROBE_URL", "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
# Error substrings that mean the JAR is bad (auth/bot-wall), not a transient
# network blip. Only these trigger a rotation.
_AUTH_MARKERS = ("sign in", "not a bot", "confirm you", "login required",
                 "log in", "http error 403", "cookies", "account")

_lock = threading.Lock()
_jars: list[str] = []
_idx = 0
_healthy: dict[str, bool] = {}
_active_since = 0.0
_started = False


def _materialize_extra() -> list[str]:
    """Write COOKIES_CONTENT_2..9 env jars to temp files. Lets PaaS hosts
    supply several jars without a filesystem."""
    out = []
    for n in range(2, 10):
        content = os.getenv(f"COOKIES_CONTENT_{n}", "")
        if not content.strip():
            continue
        if "\\n" in content and "\n" not in content:
            content = content.replace("\\n", "\n")
        try:
            fd, tmp = tempfile.mkstemp(suffix=".txt", prefix=f"cookies_{n}_")
            with os.fdopen(fd, "w") as fh:
                fh.write(content if content.endswith("\n") else content + "\n")
            out.append(tmp)
        except OSError as exc:
            logger.warning("cookies: failed to materialize COOKIES_CONTENT_%d (%s)", n, exc)
    return out


def _discover_jars() -> list[str]:
    jars: list[str] = []
    try:
        from bot.utils.player import COOKIES_FILE
        if COOKIES_FILE and os.path.exists(COOKIES_FILE):
            jars.append(os.path.abspath(COOKIES_FILE))
    except Exception:
        pass
    d = COOKIES_DIR if os.path.isabs(COOKIES_DIR) else os.path.join(_ROOT, COOKIES_DIR)
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if name.lower().endswith(".txt"):
                p = os.path.abspath(os.path.join(d, name))
                if os.path.exists(p) and p not in jars:
                    jars.append(p)
    for p in _materialize_extra():
        if p not in jars:
            jars.append(p)
    return jars


def init() -> None:
    """(Re)discover jars and reset state. Safe to call more than once."""
    global _jars, _idx, _healthy, _active_since
    with _lock:
        _jars = _discover_jars()
        _idx = 0
        _healthy = {j: True for j in _jars}
        _active_since = time.monotonic()
    logger.info(
        "cookies: managing %d jar(s); check every %dm%s",
        len(_jars), CHECK_INTERVAL_S // 60,
        f"; max-age {FORCE_REFRESH_HOURS}h" if FORCE_REFRESH_HOURS else "",
    )


def active_cookie_file() -> str:
    with _lock:
        return _jars[_idx % len(_jars)] if _jars else ""


def _age_hours() -> float:
    return (time.monotonic() - _active_since) / 3600.0 if _jars else 0.0


def rotate() -> bool:
    """Advance to the next jar (preferring one still marked healthy). Returns
    True iff a DIFFERENT jar became active."""
    global _idx, _active_since
    with _lock:
        n = len(_jars)
        if n <= 1:
            return False
        old = _idx
        for step in range(1, n + 1):
            cand = (_idx + step) % n
            if _healthy.get(_jars[cand], True):
                _idx = cand
                break
        else:
            _idx = (_idx + 1) % n
        if _idx != old:
            _active_since = time.monotonic()
            return True
        return False


def mark_unhealthy(reason: str = "") -> bool:
    """Runtime-recovery hook (called from the yt-dlp auth-failure path). Marks
    the active jar bad and rotates. Returns True if a different jar is now
    active (caller may retry). Sync + cheap — safe from any context."""
    with _lock:
        if _jars:
            _healthy[_jars[_idx % len(_jars)]] = False
    changed = rotate()
    logger.warning(
        "cookies: active jar unhealthy (%s) — %s",
        reason or "auth failure",
        "rotated to an alternate" if changed else "no healthy alternate jar",
    )
    return changed


def _probe(jar: str):
    """Extract the probe video with `jar`. Returns True (healthy), False
    (auth/bot-wall — rotate) or None (inconclusive — network blip, don't
    rotate). Bare yt-dlp so it neither triggers the recovery hook nor blocks
    the loop (run under asyncio.to_thread)."""
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError, ExtractorError
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "noplaylist": True}
    tmp = ""
    if jar:
        # Probe a private COPY, never the committed master: yt-dlp truncates and
        # rewrites cookiefile on close, which would degrade the on-disk jar over
        # time and race concurrent readers of the same master path.
        try:
            fd, tmp = tempfile.mkstemp(suffix=".txt", prefix="ckprobe_")
            os.close(fd)
            shutil.copy2(jar, tmp)
            opts["cookiefile"] = tmp
        except OSError:
            opts["cookiefile"] = jar  # copy failed — fall back to the master
            tmp = ""
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(_PROBE_URL, download=False)
        return bool(info)
    except (DownloadError, ExtractorError) as exc:
        text = str(exc).lower()
        if any(m in text for m in _AUTH_MARKERS):
            return False  # genuine sign-in/bot-wall → jar is bad, rotate
        # Any non-auth extractor error (format unavailable, DRM, video removed)
        # means auth PASSED — the jar is healthy; this probe video just had a
        # quirk. Only auth markers mean bad cookies.
        return True
    except Exception:
        return None  # network blip / timeout → inconclusive, don't rotate
    finally:
        if tmp:
            try:
                os.remove(tmp)  # one-shot probe — no need to keep the copy
            except OSError:
                pass


async def health_check() -> str:
    """Probe the active jar; rotate on auth failure; enforce optional max age.
    Returns a short, secret-free status string."""
    if not _jars:
        return "no jars configured (yt-dlp runs cookieless)"
    result = await asyncio.to_thread(_probe, active_cookie_file())
    if result is False:
        return "unhealthy → " + ("rotated" if mark_unhealthy("probe failed") else "no alternate jar")
    if result is True and FORCE_REFRESH_HOURS and _age_hours() >= FORCE_REFRESH_HOURS:
        return "healthy; max-age exceeded → " + ("rotated" if rotate() else "single jar (kept)")
    return "healthy" if result is True else "inconclusive (kept)"


async def run_forever() -> None:
    """Background health monitor. Non-blocking; never raises out."""
    global _started
    _started = True
    if not _jars:
        logger.info("cookies: no jars — health monitor idle")
        return
    await asyncio.sleep(30)  # let startup settle first
    while True:
        try:
            logger.info("cookies: health = %s (%d jar(s), age %.1fh)",
                        await health_check(), len(_jars), _age_hours())
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("cookies: health loop error (continuing)")
        try:
            await asyncio.sleep(CHECK_INTERVAL_S)
        except asyncio.CancelledError:
            return


def stats() -> dict:
    """Secret-free snapshot for /refresh and diagnostics."""
    with _lock:
        return {
            "jars": len(_jars),
            "active_index": (_idx % len(_jars)) if _jars else -1,
            "healthy": sum(1 for v in _healthy.values() if v),
            "age_hours": round(_age_hours(), 2),
            "max_age_hours": FORCE_REFRESH_HOURS or None,
        }
