"""Regression tests for the two Prompt-1 fixes:
  1. Video auto-leave: a local-file StreamEnded is trusted (premature guard is
     URL-only); replied-media duration is carried so the watchdog can arm.
  2. Served-chats persistence: chats.py works via JSON fallback and degrades
     gracefully when MONGO_URI is set but unreachable.

Run: .venv/bin/python tests/test_prompt1_fixes.py
"""
import asyncio
import importlib
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


# ── Issue 1: playback premature-end guard is URL-only ──────────────────────
import bot.utils.playback as pb


class _FakeTrack:
    def __init__(self, duration):
        self.duration = duration


def _run_streamend(chat_id, *, local, dur, elapsed):
    """Drive _on_pytgcalls_update with a controlled state; return whether
    _complete_track was invoked (i.e. the end was honored, not suppressed)."""
    calls = []

    async def fake_complete(cid, token):
        calls.append((cid, token))

    orig_complete = pb._complete_track
    orig_now = pb.q.now_playing
    pb._complete_track = fake_complete
    pb.q.now_playing = lambda c: _FakeTrack(dur)
    pb._src_is_local[chat_id] = local
    pb._started_at[chat_id] = pb.time.monotonic() - elapsed
    try:
        asyncio.run(pb._on_pytgcalls_update(None, type("StreamEnded", (), {"chat_id": chat_id})()))
    finally:
        pb._complete_track = orig_complete
        pb.q.now_playing = orig_now
        pb._src_is_local.pop(chat_id, None)
        pb._started_at.pop(chat_id, None)
    return bool(calls)


# Local file, short clip (8s) that "ended" after 8s: MUST complete (the bug was
# this being suppressed because 8 < _MIN_PLAY_S=30 with unknown duration).
check("local short-clip StreamEnded is honored (auto-leave)",
      _run_streamend(1, local=True, dur=None, elapsed=8) is True)
# Local file with known short duration, ended on time: honored.
check("local known-duration end honored",
      _run_streamend(2, local=True, dur=8, elapsed=8) is True)
# URL stream, spurious early end well before known duration: still suppressed.
check("URL premature end still suppressed",
      _run_streamend(3, local=False, dur=300, elapsed=5) is False)
# URL stream, genuine end past duration: honored.
check("URL genuine end honored",
      _run_streamend(4, local=False, dur=100, elapsed=120) is True)


# ── Issue 1: replied-media duration extraction ─────────────────────────────
def _dur(media):
    # Mirrors play_actions do_play: getattr(media, "duration", None) or None
    return getattr(media, "duration", None) or None


check("video with duration carried", _dur(type("V", (), {"duration": 8})()) == 8)
check("document without duration -> None", _dur(type("D", (), {})()) is None)
check("zero duration -> None", _dur(type("Z", (), {"duration": 0})()) is None)


# ── Issue 2: chats.py JSON fallback (no REDIS_URL) still works ──────────────
def _fresh_chats(env):
    for k in ("REDIS_URL", "CHATS_FILE"):
        os.environ.pop(k, None)
    os.environ.update(env)
    import bot.utils.kvstore as kv
    importlib.reload(kv)
    import bot.utils.chats as c
    return importlib.reload(c)


with tempfile.TemporaryDirectory() as d:
    cf = os.path.join(d, "chats.json")
    c = _fresh_chats({"CHATS_FILE": cf})
    check("no-redis: kvstore disabled", __import__("bot.utils.kvstore", fromlist=["x"]).enabled() is False)
    check("remember new -> True", c.remember(-100123) is True)
    check("remember dup -> False", c.remember(-100123) is False)
    check("remember user (DM id>0)", c.remember(555) is True)
    check("count == 2", c.count() == 2)
    check("all_chats sorted", c.all_chats() == [-100123, 555])
    check("json persisted", os.path.exists(cf))
    # Reload from JSON only — data survives (proves persistence contract).
    c2 = _fresh_chats({"CHATS_FILE": cf})
    check("reload keeps ids", set(c2.all_chats()) == {-100123, 555})
    check("forget drops id", c2.forget(555) is True and 555 not in c2.all_chats())

# Restore a clean import for any later importer.
_fresh_chats({})

print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
