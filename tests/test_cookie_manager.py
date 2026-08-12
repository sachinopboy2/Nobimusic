"""Offline tests for the automatic cookie management subsystem + /refresh
cache-purge safety. No network: the yt-dlp probe is stubbed.

Run: .venv/bin/python tests/test_cookie_manager.py
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS  {name}")
    else:
        failed += 1
        print(f"FAIL  {name}")


import bot.utils.cookie_manager as cm

_REAL_PROBE = cm._probe  # saved: the health-check tests below stub cm._probe


def _jars(n):
    paths = []
    for i in range(n):
        fd, p = tempfile.mkstemp(suffix=".txt", prefix=f"jar{i}_")
        os.write(fd, b"# Netscape\n")
        os.close(fd)
        paths.append(p)
    return paths


# ── rotation / health state ────────────────────────────────────────────────
jars = _jars(3)
cm._discover_jars = lambda: list(jars)
cm.init()
check("init discovers 3 jars", cm.stats()["jars"] == 3)
check("all healthy at init", cm.stats()["healthy"] == 3)
check("active is jar 0", cm.active_cookie_file() == jars[0])

check("mark_unhealthy rotates", cm.mark_unhealthy("test") is True)
check("active moved off jar 0", cm.active_cookie_file() != jars[0])
check("one jar now unhealthy", cm.stats()["healthy"] == 2)

# Health check with a stubbed FAILED probe → rotates again.
cm._probe = lambda jar: False
before = cm.active_cookie_file()
check("failed probe rotates", asyncio.run(cm.health_check()).startswith("unhealthy"))
check("active changed after failed probe", cm.active_cookie_file() != before)

# Healthy probe, no max-age → stays.
cm._probe = lambda jar: True
here = cm.active_cookie_file()
check("healthy probe keeps jar", asyncio.run(cm.health_check()) == "healthy")
check("active unchanged when healthy", cm.active_cookie_file() == here)

# Inconclusive probe (network blip) → never rotates.
cm._probe = lambda jar: None
here2 = cm.active_cookie_file()
check("inconclusive kept", asyncio.run(cm.health_check()).startswith("inconclusive"))
check("active unchanged when inconclusive", cm.active_cookie_file() == here2)

# Max-age forces a rotation even when healthy (fresh all-healthy state).
cm._discover_jars = lambda: list(jars)
cm.init()
cm._probe = lambda jar: True
cm.FORCE_REFRESH_HOURS = 24.0
cm._active_since = cm.time.monotonic() - 25 * 3600
before_age = cm.active_cookie_file()
res = asyncio.run(cm.health_check())
check("max-age exceeded rotates", "max-age exceeded" in res and cm.active_cookie_file() != before_age)
cm.FORCE_REFRESH_HOURS = 0.0

# ── single-jar and no-jar edge cases ────────────────────────────────────────
cm._discover_jars = lambda: [jars[0]]
cm.init()
check("single jar: rotate False", cm.rotate() is False)
check("single jar: mark_unhealthy False", cm.mark_unhealthy() is False)

cm._discover_jars = lambda: []
cm.init()
check("no jars: active file empty", cm.active_cookie_file() == "")
check("no jars: health_check safe", asyncio.run(cm.health_check()).startswith("no jars"))
check("no jars: run_forever returns", asyncio.run(cm.run_forever()) is None)

# ── player accessor fallback ────────────────────────────────────────────────
import bot.utils.player as player
# manager has no jars now → accessor falls back to the static COOKIES_FILE.
check("player accessor falls back to COOKIES_FILE",
      player.active_youtube_cookies() == player.COOKIES_FILE)

# ── /refresh purge safety: never deletes a file backing a live track ────────
import bot.utils.playback as pb
import bot.utils.queue as q

with tempfile.TemporaryDirectory() as d:
    pb._PLAY_CACHE_DIR = d
    live = os.path.join(d, "LIVE.m4a")
    orphan = os.path.join(d, "ORPHAN.m4a")
    for p in (live, orphan):
        with open(p, "wb") as f:
            f.write(b"x" * 100)
    # 'live' is backing a current track; 'orphan' is not referenced anywhere.
    q._current.clear()
    q._current[123] = q.Track(stream_url=live, title="t", requested_by="u", is_video=True)
    removed, freed = pb.purge_orphan_media()
    check("purge removes orphan only", removed == 1 and freed == 100)
    check("live file preserved", os.path.exists(live))
    check("orphan file deleted", not os.path.exists(orphan))
    q._current.clear()

# ── _probe classification (stubbed yt-dlp, no network) ──────────────────────
cm._probe = _REAL_PROBE  # restore the real probe (health-check tests stubbed it)
import yt_dlp
from yt_dlp.utils import DownloadError


class _FakeYDL:
    def __init__(self, exc=None, info=None):
        self._exc, self._info = exc, info

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        if self._exc:
            raise self._exc
        return self._info


_orig_ydl = yt_dlp.YoutubeDL
yt_dlp.YoutubeDL = lambda opts: _FakeYDL(exc=DownloadError("Requested format is not available"))
check("probe: format error => healthy", cm._probe("x") is True)
yt_dlp.YoutubeDL = lambda opts: _FakeYDL(exc=DownloadError("Sign in to confirm you're not a bot"))
check("probe: bot-wall => unhealthy", cm._probe("x") is False)
yt_dlp.YoutubeDL = lambda opts: _FakeYDL(exc=RuntimeError("connection reset"))
check("probe: network blip => inconclusive", cm._probe("x") is None)
yt_dlp.YoutubeDL = lambda opts: _FakeYDL(info={"id": "x", "formats": [{}]})
check("probe: info returned => healthy", cm._probe("x") is True)
yt_dlp.YoutubeDL = _orig_ydl

print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
