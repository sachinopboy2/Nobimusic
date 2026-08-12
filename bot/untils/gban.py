"""Global ban list — users banned from every chat the bot is in.

Each entry stores the banned user id and an optional reason. Persisted
as a JSON object at $GBAN_FILE (default ./gban.json):

  {"123456789": {"reason": "spam", "by": 987654321, "at": 1735000000}}

The bot/plugins/gban handler:
- Adds/removes entries here.
- Fans out ban/unban across every chat in chats.json on /gban or
  /removegban.
- Auto-bans on join: if a gbanned user enters any chat the bot can see
  member updates in, the bot kicks them.
"""

import json
import os
import time
from threading import Lock
from typing import Optional

from bot.utils import kvstore

GBAN_FILE = os.getenv("GBAN_FILE", "gban.json")
_KV = "gban"

_lock = Lock()
_loaded = False
_banned: dict[int, dict] = {}


def _ingest(data) -> None:
    if isinstance(data, dict):
        for k, v in data.items():
            try:
                _banned[int(k)] = v if isinstance(v, dict) else {}
            except (TypeError, ValueError):
                pass


def _load() -> None:
    global _loaded
    if _loaded:
        return
    if os.path.exists(GBAN_FILE):
        try:
            with open(GBAN_FILE) as f:
                _ingest(json.load(f))
        except (OSError, ValueError, TypeError):
            pass
    if kvstore.enabled():
        remote = kvstore.load(_KV)
        _ingest(remote)
        if _banned and (not isinstance(remote, dict) or len(remote) < len(_banned)):
            kvstore.save(_KV, {str(k): v for k, v in _banned.items()})
    _loaded = True


def _save() -> None:
    tmp = GBAN_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump({str(k): v for k, v in _banned.items()}, f)
        os.replace(tmp, GBAN_FILE)
    except OSError:
        pass
    kvstore.save(_KV, {str(k): v for k, v in _banned.items()})


def add(user_id: int, reason: str = "", by_user: Optional[int] = None) -> bool:
    """Add (or update) a gban entry. Returns True iff it wasn't already
    present. Updates reason/by even on duplicate adds.
    """
    with _lock:
        _load()
        was_new = user_id not in _banned
        _banned[user_id] = {
            "reason": reason or "",
            "by": by_user,
            "at": int(time.time()),
        }
        _save()
        return was_new


def remove(user_id: int) -> bool:
    with _lock:
        _load()
        if user_id not in _banned:
            return False
        _banned.pop(user_id, None)
        _save()
        return True


def is_banned(user_id: int) -> bool:
    with _lock:
        _load()
        return user_id in _banned


def get(user_id: int) -> Optional[dict]:
    with _lock:
        _load()
        return _banned.get(user_id)


def count() -> int:
    with _lock:
        _load()
        return len(_banned)


def all_ids() -> list[int]:
    with _lock:
        _load()
        return sorted(_banned)
