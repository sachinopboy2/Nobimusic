"""Registry of chats the bot has been used in.

Bots can't enumerate dialogs over MTProto — they only know a chat exists
when they receive a message from it. So we record every chat_id that
sends us a message. Used by /broadcast to know where to fan out and by
/stats for reach. A chat_id > 0 is a served USER (DM); < 0 is a group.

Persistence:
- MongoDB (primary, persistent across restarts/redeploys)
- JSON fallback at $CHATS_FILE (default ./chats.json), written atomically
  via temp+rename.
- Existing local chats.json is migrated into MongoDB on first load.

Reads (all_chats/count) are served from the in-memory set, so they never
block on the store; only remember/forget writes touch MongoDB.
"""

import json
import os
from threading import Lock

from bot.utils import db

CHATS_FILE = os.getenv("CHATS_FILE", "chats.json")

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

    # 1. MongoDB (primary — persistent)
    if db.ready():
        if not _loaded:
            try:
                remote = db.load_chats()
                if isinstance(remote, list):
                    _known.update(int(x) for x in remote)  # Mongo authoritative
                if _known and (not isinstance(remote, list) or len(remote) < len(_known)):
                    db.save_chats(sorted(_known))  # migrate local ids into Mongo
                _loaded = True
            except Exception:
                pass
        if _loaded:
            return

    _loaded = True


def _save() -> None:
    # 1. MongoDB (primary)
    if db.ready():
        try:
            db.save_chats(sorted(_known))
        except Exception:
            pass

    # 2. Local JSON backup (original behaviour — untouched)
    tmp = CHATS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(sorted(_known), f)
        os.replace(tmp, CHATS_FILE)
    except OSError:
        pass


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
