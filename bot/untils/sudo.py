"""Persistent sudo-user list.

The OWNER (from OWNER_ID env var or fallback to userbot.id) is implicit
and always sudo. The list here is for delegating privileged commands to
additional accounts — the owner can /addsudo people.

Stored as a JSON list at $SUDO_FILE (default ./sudo.json). Atomic write
via temp + rename. Thread-locked since both message handlers and the
backfill/discover code may touch it.
"""

import json
import os
from threading import Lock

from bot.utils import kvstore

SUDO_FILE = os.getenv("SUDO_FILE", "sudo.json")
_KV = "sudo"

_lock = Lock()
_loaded = False
_sudoers: set[int] = set()


def _load() -> None:
    global _loaded
    if _loaded:
        return
    if os.path.exists(SUDO_FILE):
        try:
            with open(SUDO_FILE) as f:
                data = json.load(f)
            if isinstance(data, list):
                _sudoers.update(int(x) for x in data)
        except (OSError, ValueError, TypeError):
            pass
    if kvstore.enabled():
        remote = kvstore.load(_KV)
        if isinstance(remote, list):
            _sudoers.update(int(x) for x in remote)
        if _sudoers and (not isinstance(remote, list) or len(remote) < len(_sudoers)):
            kvstore.save(_KV, sorted(_sudoers))
    _loaded = True


def _save() -> None:
    tmp = SUDO_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(sorted(_sudoers), f)
        os.replace(tmp, SUDO_FILE)
    except OSError:
        pass
    kvstore.save(_KV, sorted(_sudoers))


def add(user_id: int) -> bool:
    with _lock:
        _load()
        if user_id in _sudoers:
            return False
        _sudoers.add(user_id)
        _save()
        return True


def remove(user_id: int) -> bool:
    with _lock:
        _load()
        if user_id not in _sudoers:
            return False
        _sudoers.discard(user_id)
        _save()
        return True


def is_sudoer(user_id: int) -> bool:
    with _lock:
        _load()
        return user_id in _sudoers


def all_sudoers() -> list:
    with _lock:
        _load()
        return sorted(_sudoers)
