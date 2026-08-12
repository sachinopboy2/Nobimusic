"""Identify the bot's owner(s) and sudo users.

Owners are the people who deploy the bot. They're configured via the
`OWNER_ID` env var — a comma- or space-separated list of Telegram user
IDs. If that var is empty, the owner falls back to whoever holds the
userbot session (`userbot.get_me().id`).

`SUDO_USERS` is a similar env-var list for delegated sudoers loaded at
startup. The persistent sudo store (bot/utils/sudo.py) is layered on top.

Both lookups are cached after first call.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger("WarbornMusic.owner")

_cached_owners: Optional[set[int]] = None
_env_sudo_loaded = False


def _parse_id_list(raw: str) -> set[int]:
    """Tolerant parser. Accepts ',' / whitespace separated ints. Ignores garbage."""
    out: set[int] = set()
    if not raw:
        return out
    for token in raw.replace(",", " ").split():
        token = token.strip()
        if not token:
            continue
        try:
            out.add(int(token))
        except ValueError:
            logger.warning("owner: ignoring non-int token %r in OWNER_ID/SUDO_USERS", token)
    return out


def _env_owners() -> set[int]:
    return _parse_id_list(os.getenv("OWNER_ID", ""))


def _load_env_sudoers_once() -> None:
    """Push SUDO_USERS env var entries into the persistent sudo store on first call.

    Idempotent — sudo_store.add() is a no-op for duplicates.
    """
    global _env_sudo_loaded
    if _env_sudo_loaded:
        return
    _env_sudo_loaded = True
    extras = _parse_id_list(os.getenv("SUDO_USERS", ""))
    if not extras:
        return
    from bot.utils import sudo as sudo_store
    for uid in extras:
        sudo_store.add(uid)
    logger.info("owner: loaded %d SUDO_USERS from env", len(extras))


async def get_owner_ids() -> set[int]:
    """Return all owner IDs as a set.

    Priority: OWNER_ID env var → userbot.get_me().id fallback. Cached
    after the first successful lookup.
    """
    global _cached_owners
    if _cached_owners is not None:
        return _cached_owners

    env = _env_owners()
    if env:
        _cached_owners = env
        logger.info("owner: using OWNER_ID env (%s)", sorted(env))
        return _cached_owners

    # Fallback: derive from the assistant userbot session.
    from bot.client import userbot
    try:
        me = await userbot.get_me()
    except Exception as exc:
        logger.warning("owner: userbot.get_me failed: %s — owner unset", exc)
        # Do NOT cache an empty set; let the next call retry.
        return set()
    _cached_owners = {me.id}
    logger.info(
        "owner: OWNER_ID env unset, falling back to userbot id %s "
        "(set OWNER_ID env to override)",
        me.id,
    )
    return _cached_owners


async def get_owner_id() -> Optional[int]:
    """Back-compat: return one owner id (the lowest) or None."""
    owners = await get_owner_ids()
    return min(owners) if owners else None


async def is_owner(user_id: int) -> bool:
    owners = await get_owner_ids()
    return user_id in owners


async def is_sudo(user_id: int) -> bool:
    """True if the user is an owner OR a sudoer.

    Use for any command that should be delegable (e.g. /broadcast, /stats).
    Reserve is_owner for actions that mutate the privileged user list
    itself (/addsudo, /delsudo).
    """
    _load_env_sudoers_once()
    if await is_owner(user_id):
        return True
    from bot.utils import sudo as sudo_store
    return sudo_store.is_sudoer(user_id)


def reset_owner_cache() -> None:
    """Test hook — invalidate the owner cache. Not used by production code."""
    global _cached_owners, _env_sudo_loaded
    _cached_owners = None
    _env_sudo_loaded = False
