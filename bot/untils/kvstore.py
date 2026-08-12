"""Tiny persistence backend shared by every JSON store in the bot.

When REDIS_URL is set, each store mirrors its JSON blob to a Redis key
(write-through on every change, loaded on boot) so nothing is lost when
Railway redeploys — the process can die any way (SIGKILL/OOM/crash) and the
data is already in Redis. When REDIS_URL is unset (or Redis is unreachable),
this is inert and every store keeps using its local JSON file exactly as
before — zero behaviour change.

Use from a store module:

    from bot.utils import kvstore

    def _load():
        ...read local file into memory as before...
        if kvstore.enabled():
            remote = kvstore.load(NAME)
            if remote is not None:
                ...populate in-memory from remote (authoritative)...
            else:
                kvstore.save(NAME, _serialisable())   # one-time file->Redis

    def _save():
        ...write local file as before...
        kvstore.save(NAME, _serialisable())

`load`/`save` never raise — a Redis hiccup degrades to the local file.
"""

import json
import logging
import os

logger = logging.getLogger("WarbornMusic.kvstore")

REDIS_URL = os.getenv("REDIS_URL", "").strip()
_PREFIX = (os.getenv("REDIS_PREFIX", "warborn").strip() or "warborn") + ":"

_client = None
_checked = False


def _normalize_url(url: str) -> str:
    """Upstash requires TLS. A copied `redis://…upstash.io` URL (paired with a
    `--tls` CLI flag redis-py can't see) would connect WITHOUT TLS and be
    rejected — auto-upgrade it to the rediss:// (TLS) scheme."""
    if url.startswith("redis://") and ".upstash.io" in url:
        return "rediss://" + url[len("redis://"):]
    return url


def _get_client():
    global _client, _checked
    if _checked:
        return _client
    _checked = True
    if not REDIS_URL:
        return None
    try:
        import redis
        c = redis.from_url(
            _normalize_url(REDIS_URL), decode_responses=True,
            socket_connect_timeout=5, socket_timeout=5,
        )
        c.ping()
        _client = c
        logger.info("kvstore: Redis persistence ENABLED")
    except Exception as exc:
        logger.warning("kvstore: Redis init failed (%s) — using local JSON files", exc)
        _client = None
    return _client


def enabled() -> bool:
    """True only when a reachable Redis is configured."""
    return _get_client() is not None


def startup_status() -> str:
    """A loud, unambiguous persistence-mode line for the boot log so a
    misconfiguration (unset/unreachable REDIS_URL) is obvious in Railway logs."""
    if not REDIS_URL:
        return ("PERSISTENCE: local JSON only — EPHEMERAL, data RESETS on every "
                "redeploy. Set REDIS_URL in Railway variables to fix.")
    if enabled():
        return "PERSISTENCE: Redis ENABLED — data survives redeploys ✅"
    return ("PERSISTENCE: REDIS_URL is set but Redis is UNREACHABLE — falling "
            "back to ephemeral local JSON. Check the URL/credentials.")


def load(name: str):
    """Parsed JSON stored under `name`, or None (missing / disabled / error)."""
    global _client
    c = _get_client()
    if c is None:
        return None
    try:
        raw = c.get(_PREFIX + name)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.warning("kvstore: load(%s) failed (%s) — using local file", name, exc)
        _client = None  # stop hammering a broken connection this process
        return None


def save(name: str, obj) -> None:
    """Write-through `obj` (JSON-serialisable) under `name`. No-op when disabled."""
    global _client
    c = _get_client()
    if c is None:
        return
    try:
        c.set(_PREFIX + name, json.dumps(obj))
    except Exception as exc:
        logger.warning("kvstore: save(%s) failed (%s)", name, exc)
        _client = None
