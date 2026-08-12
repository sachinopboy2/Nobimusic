"""Per-chat on/off flag for the welcome handler.

Stored in MongoDB (persistent) + local JSON fallback.
"""

import json
import os
from threading import Lock

from bot.utils import db

GREETINGS_FILE = os.getenv("GREETINGS_FILE", "greetings.json")

_lock = Lock()
_loaded = False
_enabled: set[int] = set()


def _load() -> None:
    global _loaded
    if _loaded:
        return

    # 1. MongoDB (primary — persistent)
    if db.ready():
        try:
            remote = db.load_greetings()
            if isinstance(remote, list):
                _enabled.update(int(x) for x in remote)
                _loaded = True
                return
        except Exception:
            pass

    # 2. Local JSON fallback
    if os.path.exists(GREETINGS_FILE):
        try:
            with open(GREETINGS_FILE) as f:
                data = json.load(f)
            if isinstance(data, list):
                _enabled.update(int(x) for x in data)
        except (OSError, ValueError, TypeError):
            pass

    _loaded = True


def _save() -> None:
    # 1. MongoDB (primary)
    if db.ready():
        try:
            db.save_greetings(sorted(_enabled))
        except Exception:
            pass

    # 2. Local JSON backup
    tmp = f"{GREETINGS_FILE}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(sorted(_enabled), f)
        os.replace(tmp, GREETINGS_FILE)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def is_enabled(chat_id: int) -> bool:
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
