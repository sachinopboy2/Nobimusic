"""Per-chat on/off flag for the welcome handler.

Stored as a JSON list of chat ids in GREETINGS_FILE (default: ./greetings.json).
A chat in the set means "greetings are ON". Default for any new chat is OFF.
"""

import json
import os
from threading import Lock

from bot.utils import kvstore

GREETINGS_FILE = os.getenv("GREETINGS_FILE", "greetings.json")
_KV = "greetings"

_lock = Lock()
_loaded = False
_enabled: set[int] = set()


def _load() -> None:
    global _loaded
    if _loaded:
        return
    if os.path.exists(GREETINGS_FILE):
        try:
            with open(GREETINGS_FILE) as f:
                data = json.load(f)
            if isinstance(data, list):
                _enabled.update(int(x) for x in data)
        except (OSError, ValueError, TypeError):
            pass
    if kvstore.enabled():
        remote = kvstore.load(_KV)
        if isinstance(remote, list):
            _enabled.update(int(x) for x in remote)
        if _enabled and (not isinstance(remote, list) or len(remote) < len(_enabled)):
            kvstore.save(_KV, sorted(_enabled))
    _loaded = True


def _save() -> None:
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
    kvstore.save(_KV, sorted(_enabled))


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
