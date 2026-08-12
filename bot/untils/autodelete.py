"""Auto-delete the bot's own responses in groups/channels after a delay.

DMs (private chats) are never touched. Restart-safe: pending deletions are
persisted to $AUTODELETE_FILE and a single background sweeper removes them
when due, so a Railway redeploy doesn't drop scheduled deletes. One sweeper +
a JSON file instead of thousands of sleeping tasks (bounded memory + I/O).
"""

import asyncio
import json
import logging
import os
import time
from functools import wraps

from bot.utils import kvstore

logger = logging.getLogger("WarbornMusic.autodelete")

DELAY_SECONDS = int(os.getenv("AUTODELETE_AFTER", str(12 * 3600)))
_SWEEP_INTERVAL = 60
_FILE = os.getenv("AUTODELETE_FILE", "autodelete.json")
_KV = "autodelete"

# group / supergroup / channel only — private (DM) and bot chats never expire.
_EXPIRE_TYPES = {"group", "supergroup", "channel"}

# Each entry: [chat_id, message_id, delete_at_epoch].
_pending: list = []
_loaded = False
_dirty = False

# All the ways the bot posts a message. reply_* on Message delegate to these
# client methods, so wrapping the client covers reply_text/reply_photo/etc.
_SEND_METHODS = (
    "send_message", "send_photo", "send_audio", "send_video", "send_document",
    "send_animation", "send_voice", "send_video_note", "send_sticker",
    "send_media_group", "copy_message",
)


def _load() -> None:
    global _pending, _loaded
    if _loaded:
        return
    try:
        with open(_FILE) as f:
            _pending = json.load(f) or []
    except Exception:
        _pending = []
    if kvstore.enabled():
        remote = kvstore.load(_KV)
        if isinstance(remote, list):
            _pending = remote  # Redis authoritative (latest write-through)
        elif _pending:
            kvstore.save(_KV, _pending)  # migrate local up on first boot
    _loaded = True


def _save() -> None:
    global _dirty
    tmp = f"{_FILE}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(_pending, f)
        os.replace(tmp, _FILE)
        _dirty = False
    except Exception:
        logger.exception("autodelete: save failed")
        try:
            os.remove(tmp)
        except OSError:
            pass
    kvstore.save(_KV, _pending)


def _record(msg) -> None:
    global _dirty
    chat = getattr(msg, "chat", None)
    ctype = getattr(getattr(chat, "type", None), "value", None)
    mid = getattr(msg, "id", None)
    if chat is None or mid is None or ctype not in _EXPIRE_TYPES:
        return
    _pending.append([chat.id, mid, time.time() + DELAY_SECONDS])
    _dirty = True


def install(app) -> None:
    """Wrap the bot client's send methods so every message it posts to a
    group/channel is queued for deletion. DMs are ignored. Idempotent."""
    _load()
    for name in _SEND_METHODS:
        orig = getattr(app, name, None)
        if orig is None or getattr(orig, "_autodelete", False):
            continue

        @wraps(orig)
        async def wrapper(*args, __orig=orig, **kwargs):
            res = await __orig(*args, **kwargs)
            try:
                if isinstance(res, list):
                    for m in res:
                        _record(m)
                elif res is not None:
                    _record(res)
            except Exception:
                logger.exception("autodelete: record failed")
            return res

        wrapper._autodelete = True
        setattr(app, name, wrapper)
    logger.info("autodelete installed (after %ss, groups/channels only)", DELAY_SECONDS)


async def run_sweeper(app) -> None:
    """Delete due messages and persist the queue. Runs forever."""
    _load()
    while True:
        await asyncio.sleep(_SWEEP_INTERVAL)
        now = time.time()
        due = [e for e in _pending if e[2] <= now]
        for chat_id, mid, _ in due:
            try:
                await app.delete_messages(chat_id, mid)
            except Exception as exc:
                logger.debug("autodelete: delete %s/%s failed: %s", chat_id, mid, exc)
        if due:
            _pending[:] = [e for e in _pending if e[2] > now]
            _save()
        elif _dirty:
            _save()
