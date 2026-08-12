"""Per-chat on/off flag for the leave/farewell handler.

This is split from greetings.py so the user can independently enable
"savage farewell on leave" without also enabling welcome cards on join.

Default for any new chat is OFF — the bot no longer fires farewells unless
an admin opts in with `/departure on`. Storage is a JSON list of chat ids in
DEPARTURE_ON_FILE: chats in the file are the ones where departures are ON
(same opt-in shape as greetings.py). Chats not in the file — including brand
new ones — are OFF.

Note: this uses a NEW file (departure_on.json), distinct from the old
default-ON store (departure_off.json), so previously-OFF chats are never
misread as ON. Existing chats that had explicitly turned departures OFF stay
OFF; chats that never opted in are OFF by the new default.
"""

import json
import os
import logging
from threading import Lock

from bot.utils import kvstore

logger = logging.getLogger("WarbornMusic.departure")

DEPARTURE_ON_FILE = os.getenv("DEPARTURE_ON_FILE", "departure_on.json")
_KV = "departure"

_lock = Lock()
_enabled: set[int] = set()
_mtime: float | None = None  # mtime of the copy we last read; drives reload
_kv_loaded = False


def _load() -> None:
    """Reload the ON set. With Redis enabled, Redis is the source of truth
    (loaded once, then write-through) so a stale local file can't clobber it.
    Without Redis, reload from disk whenever the file changes so the in-memory
    copy can never go stale relative to a write."""
    global _mtime, _kv_loaded
    if kvstore.enabled():
        if not _kv_loaded:
            remote = kvstore.load(_KV)
            if isinstance(remote, list):
                _enabled.clear()
                _enabled.update(int(x) for x in remote)
            else:
                # First boot with Redis: migrate any existing local file up.
                if os.path.exists(DEPARTURE_ON_FILE):
                    try:
                        with open(DEPARTURE_ON_FILE) as f:
                            data = json.load(f)
                        if isinstance(data, list):
                            _enabled.update(int(x) for x in data)
                    except (OSError, ValueError, TypeError):
                        pass
                kvstore.save(_KV, sorted(_enabled))
            _kv_loaded = True
        return
    try:
        st = os.stat(DEPARTURE_ON_FILE)
    except OSError:
        return
    if _mtime is not None and st.st_mtime == _mtime:
        return
    try:
        with open(DEPARTURE_ON_FILE) as f:
            data = json.load(f)
        if isinstance(data, list):
            _enabled.clear()
            _enabled.update(int(x) for x in data)
            _mtime = st.st_mtime
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("departure: reload of %s failed: %s", DEPARTURE_ON_FILE, exc)


def _save() -> None:
    global _mtime
    tmp = DEPARTURE_ON_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(sorted(_enabled), f)
        os.replace(tmp, DEPARTURE_ON_FILE)
        _mtime = os.stat(DEPARTURE_ON_FILE).st_mtime
    except OSError as exc:
        logger.warning(
            "departure: save to %s failed (%s) — the on/off change will NOT "
            "survive a restart", DEPARTURE_ON_FILE, exc)
    kvstore.save(_KV, sorted(_enabled))


def is_enabled(chat_id: int) -> bool:
    """False (default) unless the chat has explicitly turned departures on."""
    with _lock:
        _load()
        return chat_id in _enabled


def set_enabled(chat_id: int, on: bool) -> None:
    with _lock:
        _load()
        if on:
            _enabled.add(chat_id)
        else:
            _enabled.discard(chat_id)
        _save()
