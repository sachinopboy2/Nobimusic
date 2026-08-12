"""Registry of chats the bot has been used in.

Bots can't enumerate dialogs over MTProto — they only know a chat exists
when they receive a message from it. So we record every chat_id that
sends us a message. Used by /broadcast to know where to fan out and by
/stats for reach. A chat_id > 0 is a served USER (DM); < 0 is a group.

Persistence:
- If REDIS_URL is set, the id set is mirrored to Redis (write-through on
  every remember/forget, loaded on boot) so it survives Railway redeploys.
  Any existing local chats.json is migrated in automatically on first load.
- Otherwise it falls back to a JSON list at $CHATS_FILE (default
  ./chats.json), written atomically via temp+rename.

Reads (all_chats/count) are served from the in-memory set, so they never
block on the store; only remember/forget writes touch Redis.
"""

import json
import os
from threading import Lock

from bot.utils import kvstore

CHATS_FILE = os.getenv("CHATS_FILE", "chats.json")
_KV = "chats"

_lock = Lock()
_loaded = False
_known: set[int] = set()


def _load() -> None:
    global _loaded
    if _loaded:
        return
    json_ids: set[int] = set()
    if os.path.exists(CHATS_FILE):
        try:
            with open(CHATS_FILE) as f:
                data = json.load(f)
            if isinstance(data, list):
                json_ids = {int(x) for x in data}
        except (OSError, ValueError, TypeError):
            pass
    _known.update(json_ids)

    if kvstore.enabled():
        remote = kvstore.load(_KV)
        if isinstance(remote, list):
            _known.update(int(x) for x in remote)  # Redis authoritative
        if _known and (not isinstance(remote, list) or len(remote) < len(_known)):
            kvstore.save(_KV, sorted(_known))  # migrate local ids into Redis
    _loaded = True


def _save() -> None:
    tmp = CHATS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(sorted(_known), f)
        os.replace(tmp, CHATS_FILE)
    except OSError:
        pass
    kvstore.save(_KV, sorted(_known))


def remember(chat_id: int) -> bool:
    """Record chat_id if new. Returns True iff it was added this call."""
    with _lock:
        _load()
        if chat_id in _known:
            return False
        _known.add(chat_id)
        _save()
        return True


def all_chats() -> list[int]:
    with _lock:
        _load()
        return sorted(_known)


def forget(chat_id: int) -> bool:
    """Drop a chat (bot kicked / user blocked / id invalid)."""
    with _lock:
        _load()
        if chat_id not in _known:
            return False
        _known.discard(chat_id)
        _save()
        return True


def count() -> int:
    with _lock:
        _load()
        return len(_known)
