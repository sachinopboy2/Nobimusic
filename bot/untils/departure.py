"""Per-chat on/off flag for the leave/farewell handler.

This is split from greetings.py so the user can independently enable
"savage farewell on leave" without also enabling welcome cards on join.

Default for any new chat is OFF — the bot no longer fires farewells unless
an admin opts in with `/departure on`. Storage is MongoDB (persistent) + local
JSON fallback. Chats not in the set — including brand new ones — are OFF.
"""

import json
import os
import logging
from threading import Lock

from bot.utils import db

logger = logging.getLogger("WarbornMusic.departure")

DEPARTURE_ON_FILE = os.getenv("DEPARTURE_ON_FILE", "departure_on.json")

_lock = Lock()
_loaded = False
_enabled: set[int] = set()
_mtime: float | None = None  # mtime of the copy we last read; drives reload


def _load() -> None:
    """Reload the ON set. MongoDB is primary (persistent). Without MongoDB,
    reload from disk whenever the file changes so the in-memory copy can
    never go stale relative to a write."""
    global _loaded, _mtime

    # 1. MongoDB (primary — persistent)
    if db.ready():
        if not _loaded:
            try:
                remote = db.load_departures()
                if isinstance(remote, list):
                    _enabled.clear()
                    _enabled.update(int(x) for x in remote)
                else:
                    # First boot with MongoDB: migrate any existing local file up.
                    if os.path.exists(DEPARTURE_ON_FILE):
                        try:
                            with open(DEPARTURE_ON_FILE) as f:
                                data = json.load(f)
                            if isinstance(data, list):
                                _enabled.update(int(x) for x in data)
                        except (OSError, ValueError, TypeError):
                            pass
                    db.save_departures(sorted(_enabled))
                _loaded = True
            except Exception:
                pass
        if _loaded:
            return

    # 2. Local JSON fallback (original behaviour — untouched)
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

    # 1. MongoDB (primary — persistent)
    if db.ready():
        try:
            db.save_departures(sorted(_enabled))
        except Exception:
            pass

    # 2. Local JSON backup (original behaviour — untouched)
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
