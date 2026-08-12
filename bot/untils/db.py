"""MongoDB connection + data helpers for persistent storage.

Uses MONGO_URL from .env
DB_NAME = "WarbornMusic" (override with MONGO_DB env var)
"""

import logging
import os
from typing import Optional

import motor.motor_asyncio

logger = logging.getLogger("WarbornMusic.db")

MONGO_URL = os.getenv("MONGO_URL", "").strip()
DB_NAME = os.getenv("MONGO_DB", "WarbornMusic")

_client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
_db = None


def _connect():
    global _client, _db
    if _client is not None:
        return
    if not MONGO_URL:
        return
    try:
        _client = motor.motor_asyncio.AsyncIOMotorClient(
            MONGO_URL,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
        _db = _client[DB_NAME]
        logger.info("MongoDB connected")
    except Exception as exc:
        logger.warning("MongoDB connection failed: %s", exc)
        _client = None
        _db = None


def ready() -> bool:
    if _client is None:
        _connect()
    return _db is not None


# ── Greetings ─────────────────────────────────────
def load_greetings() -> list[int]:
    if not ready():
        return []
    try:
        import asyncio
        async def _get():
            doc = await _db.greetings.find_one({"_id": "enabled"})
            return doc.get("chats", []) if doc else []
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(asyncio.wait_for(_get(), timeout=5))
    except Exception:
        return []


def save_greetings(chat_ids: list[int]) -> None:
    if not ready():
        return
    try:
        import asyncio
        async def _set():
            await _db.greetings.update_one(
                {"_id": "enabled"},
                {"$set": {"chats": chat_ids}},
                upsert=True,
            )
        loop = asyncio.get_event_loop()
        loop.run_until_complete(asyncio.wait_for(_set(), timeout=5))
    except Exception:
        pass


# ── Departures ────────────────────────────────────
def load_departures() -> list[int]:
    if not ready():
        return []
    try:
        import asyncio
        async def _get():
            doc = await _db.departures.find_one({"_id": "enabled"})
            return doc.get("chats", []) if doc else []
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(asyncio.wait_for(_get(), timeout=5))
    except Exception:
        return []


def save_departures(chat_ids: list[int]) -> None:
    if not ready():
        return
    try:
        import asyncio
        async def _set():
            await _db.departures.update_one(
                {"_id": "enabled"},
                {"$set": {"chats": chat_ids}},
                upsert=True,
            )
        loop = asyncio.get_event_loop()
        loop.run_until_complete(asyncio.wait_for(_set(), timeout=5))
    except Exception:
        pass


# ── Chat Registry ─────────────────────────────────
def load_chats() -> list[int]:
    if not ready():
        return []
    try:
        import asyncio
        async def _get():
            doc = await _db.chats.find_one({"_id": "registry"})
            return doc.get("chats", []) if doc else []
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(asyncio.wait_for(_get(), timeout=5))
    except Exception:
        return []


def save_chats(chat_ids: list[int]) -> None:
    if not ready():
        return
    try:
        import asyncio
        async def _set():
            await _db.chats.update_one(
                {"_id": "registry"},
                {"$set": {"chats": chat_ids}},
                upsert=True,
            )
        loop = asyncio.get_event_loop()
        loop.run_until_complete(asyncio.wait_for(_set(), timeout=5))
    except Exception:
        pass


_connect()
